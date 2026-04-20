from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import random

from arbitrageur.models import MarketSnapshot


class ExchangeGateway(ABC):
    @abstractmethod
    def fetch_snapshot(self, symbol: str) -> MarketSnapshot:
        raise NotImplementedError


class MockExchangeGateway(ExchangeGateway):
    """Pseudo market data for paper mode development and testing."""

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
        self._base_prices = {
            "BTC/USDT": 65000.0,
            "ETH/USDT": 3200.0,
            "SOL/USDT": 145.0,
            "BNB/USDT": 590.0,
            "ARB/USDT": 2.1,
        }

    def fetch_snapshot(self, symbol: str) -> MarketSnapshot:
        if symbol not in self._base_prices:
            self._base_prices[symbol] = self._rng.uniform(1.0, 200.0)

        base = self._base_prices[symbol]
        spot_move = self._rng.uniform(-0.006, 0.006)
        spread = self._rng.uniform(-0.04, 0.04)
        funding = self._rng.uniform(-0.01, 0.12)

        spot_price = base * (1 + spot_move)
        perp_price = spot_price * (1 + spread / 100)
        self._base_prices[symbol] = spot_price

        return MarketSnapshot(
            symbol=symbol,
            spot_price=spot_price,
            perp_price=perp_price,
            funding_rate_pct_8h=funding,
            spread_pct=abs(spread),
            timestamp=datetime.now(timezone.utc),
        )