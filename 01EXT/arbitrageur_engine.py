from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from arbitrageur.config import AppConfig
from arbitrageur.exchange import ExchangeGateway
from arbitrageur.models import CycleResult, Opportunity, Position


def annualize_from_8h_rate(rate_pct_8h: float) -> float:
    periods_per_year = 3 * 365
    return ((1 + rate_pct_8h / 100) ** periods_per_year - 1) * 100


@dataclass(slots=True)
class PortfolioState:
    free_usdt: float
    realized_funding_usdt_total: float = 0.0
    total_cycles: int = 0


class FundingArbitrageEngine:
    def __init__(
        self,
        config: AppConfig,
        market: ExchangeGateway,
        logger: logging.Logger,
    ):
        self.config = config
        self.market = market
        self.logger = logger
        reserve = config.capital.total_usdt * (config.capital.reserve_pct / 100)
        self.portfolio = PortfolioState(free_usdt=config.capital.total_usdt - reserve)
        self.open_positions: dict[str, Position] = {}

    def run_cycle(self) -> CycleResult:
        cycle = CycleResult()
        opportunities = self._scan()
        self._open_new_positions(opportunities, cycle)
        cycle.realized_funding_usdt = self._settle_funding()
        self.portfolio.realized_funding_usdt_total += cycle.realized_funding_usdt
        self.portfolio.total_cycles += 1
        self._log_cycle(cycle)
        return cycle

    def _scan(self) -> list[Opportunity]:
        candidates: list[Opportunity] = []
        for symbol in self.config.tracked_assets:
            snapshot = self.market.fetch_snapshot(symbol)
            apr = annualize_from_8h_rate(snapshot.funding_rate_pct_8h)
            if snapshot.funding_rate_pct_8h < self.config.strategy.funding_rate_threshold:
                continue
            if snapshot.spread_pct > self.config.strategy.max_spread_pct:
                continue
            if apr < self.config.strategy.min_apr_estimate:
                continue
            candidates.append(Opportunity(snapshot=snapshot, estimated_apr_pct=apr))
        candidates.sort(key=lambda item: item.estimated_apr_pct, reverse=True)
        return candidates

    def _open_new_positions(self, opportunities: list[Opportunity], cycle: CycleResult) -> None:
        if not opportunities:
            return

        max_per_asset = self.config.capital.total_usdt * (self.config.capital.max_per_asset_pct / 100)
        slots = max(1, len(opportunities))
        per_asset_budget = min(self.portfolio.free_usdt / slots, max_per_asset)

        for opportunity in opportunities:
            symbol = opportunity.snapshot.symbol
            if symbol in self.open_positions:
                cycle.skipped_symbols.append(symbol)
                continue
            if self.portfolio.free_usdt <= 1:
                break

            budget = min(per_asset_budget, self.portfolio.free_usdt)
            qty = budget / opportunity.snapshot.spot_price
            if qty <= 0:
                cycle.skipped_symbols.append(symbol)
                continue

            position = Position(
                symbol=symbol,
                quantity=qty,
                spot_entry_price=opportunity.snapshot.spot_price,
                perp_entry_price=opportunity.snapshot.perp_price,
                notional_usdt=budget,
                opened_at=datetime.now(timezone.utc),
                last_funding_rate_pct_8h=opportunity.snapshot.funding_rate_pct_8h,
            )
            self.open_positions[symbol] = position
            self.portfolio.free_usdt -= budget
            cycle.opened_positions.append(position)

    def _settle_funding(self) -> float:
        realized = 0.0
        for position in self.open_positions.values():
            snapshot = self.market.fetch_snapshot(position.symbol)
            position.last_funding_rate_pct_8h = snapshot.funding_rate_pct_8h
            funding_fee = position.notional_usdt * (snapshot.funding_rate_pct_8h / 100)
            realized += funding_fee
        return realized

    def _log_cycle(self, cycle: CycleResult) -> None:
        self.logger.info("Cycle completed @ %s", datetime.now(timezone.utc).isoformat())
        self.logger.info("Open positions: %d", len(self.open_positions))
        if cycle.opened_positions:
            for pos in cycle.opened_positions:
                self.logger.info(
                    "OPEN %s qty=%.6f notional=%.2f funding(8h)=%.4f%%",
                    pos.symbol,
                    pos.quantity,
                    pos.notional_usdt,
                    pos.last_funding_rate_pct_8h,
                )
        if cycle.skipped_symbols:
            self.logger.info("Skipped symbols this cycle: %s", ", ".join(cycle.skipped_symbols))
        self.logger.info("Funding realized this cycle: %.4f USDT", cycle.realized_funding_usdt)
        self.logger.info("Funding realized total: %.4f USDT", self.portfolio.realized_funding_usdt_total)