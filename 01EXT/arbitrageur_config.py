from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(slots=True)
class ExchangeCredentials:
    api_key: str
    api_secret: str
    market_type: str


@dataclass(slots=True)
class StrategyConfig:
    mode: str
    funding_rate_threshold: float
    min_apr_estimate: float
    max_spread_pct: float
    hedge_ratio_tolerance: float
    settlement_interval_hours: int = 8


@dataclass(slots=True)
class CapitalConfig:
    total_usdt: float
    max_per_asset_pct: float
    reserve_pct: float


@dataclass(slots=True)
class LoggingConfig:
    log_file: str
    console_output: bool
    cycle_summary: bool


@dataclass(slots=True)
class AppConfig:
    binance: ExchangeCredentials
    bybit: ExchangeCredentials
    strategy: StrategyConfig
    capital: CapitalConfig
    tracked_assets: list[str]
    logging: LoggingConfig


def _required(section: dict, key: str):
    if key not in section:
        raise ValueError(f"Missing required config key: {key}")
    return section[key]


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Config root must be a mapping.")

    exchanges = _required(parsed, "exchanges")
    strategy = _required(parsed, "strategy")
    capital = _required(parsed, "capital")
    assets = _required(parsed, "assets")
    logging_cfg = _required(parsed, "logging")

    app_config = AppConfig(
        binance=ExchangeCredentials(
            api_key=_required(exchanges["binance"], "api_key"),
            api_secret=_required(exchanges["binance"], "api_secret"),
            market_type=_required(exchanges["binance"], "market_type"),
        ),
        bybit=ExchangeCredentials(
            api_key=_required(exchanges["bybit"], "api_key"),
            api_secret=_required(exchanges["bybit"], "api_secret"),
            market_type=_required(exchanges["bybit"], "market_type"),
        ),
        strategy=StrategyConfig(
            mode=_required(strategy, "mode"),
            funding_rate_threshold=float(_required(strategy, "funding_rate_threshold")),
            min_apr_estimate=float(_required(strategy, "min_apr_estimate")),
            max_spread_pct=float(_required(strategy, "max_spread_pct")),
            hedge_ratio_tolerance=float(_required(strategy, "hedge_ratio_tolerance")),
            settlement_interval_hours=int(strategy.get("settlement_interval_hours", 8)),
        ),
        capital=CapitalConfig(
            total_usdt=float(_required(capital, "total_usdt")),
            max_per_asset_pct=float(_required(capital, "max_per_asset_pct")),
            reserve_pct=float(_required(capital, "reserve_pct")),
        ),
        tracked_assets=list(_required(assets, "tracked")),
        logging=LoggingConfig(
            log_file=str(_required(logging_cfg, "log_file")),
            console_output=bool(_required(logging_cfg, "console_output")),
            cycle_summary=bool(_required(logging_cfg, "cycle_summary")),
        ),
    )
    _validate(app_config)
    return app_config


def _validate(config: AppConfig) -> None:
    if config.strategy.mode not in {"paper", "live"}:
        raise ValueError("strategy.mode must be either 'paper' or 'live'.")
    if config.capital.total_usdt <= 0:
        raise ValueError("capital.total_usdt must be > 0.")
    if not 0 <= config.capital.max_per_asset_pct <= 100:
        raise ValueError("capital.max_per_asset_pct must be between 0 and 100.")
    if not 0 <= config.capital.reserve_pct < 100:
        raise ValueError("capital.reserve_pct must be between 0 and <100.")
    if len(config.tracked_assets) == 0:
        raise ValueError("assets.tracked cannot be empty.")