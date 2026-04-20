from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class MarketSnapshot:
    symbol: str
    spot_price: float
    perp_price: float
    funding_rate_pct_8h: float
    spread_pct: float
    timestamp: datetime


@dataclass(slots=True)
class Opportunity:
    snapshot: MarketSnapshot
    estimated_apr_pct: float


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float
    spot_entry_price: float
    perp_entry_price: float
    notional_usdt: float
    opened_at: datetime
    last_funding_rate_pct_8h: float


@dataclass(slots=True)
class CycleResult:
    opened_positions: list[Position] = field(default_factory=list)
    skipped_symbols: list[str] = field(default_factory=list)
    realized_funding_usdt: float = 0.0