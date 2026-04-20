import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

# =============================================================================
# 📦 CORE DATA STRUCTURES
# =============================================================================
@dataclass
class LiquidityPool:
    price: float
    bar_idx: int
    pool_type: str          # 'BSL', 'SSL', 'EQH', 'EQL'
    status: str = 'ACTIVE'  # 'ACTIVE', 'SWEPT'
    sweep_bar_idx: Optional[int] = None

# =============================================================================
# 🔧 ALGORITHMIC ENGINE
# =============================================================================
class LiquidityTracker:
    def __init__(
        self, 
        pivot_bars: int = 5, 
        eq_tolerance_pct: float = 0.03, 
        keep_swept: bool = False,
        highlight_sweep: bool = True
    ):
        self.pivot_bars = pivot_bars
        self.eq_tolerance = eq_tolerance_pct / 100
        self.keep_swept = keep_swept
        self.highlight_sweep = highlight_sweep
        self.pools: List[LiquidityPool] = []
        
    def _detect_swings(self, df: pd.DataFrame) -> pd.DataFrame:
        """Identifies confirmed swing highs/lows without look-ahead bias."""
        # Shift ensures we only confirm after `pivot_bars` have passed
        df['is_sh'] = df['high'] == df['high'].shift(self.pivot_bars).rolling(window=2*self.pivot_bars+1, min_periods=1).max()
        df['is_sl'] = df['low']  == df['low'].shift(self.pivot_bars).rolling(window=2*self.pivot_bars+1, min_periods=1).min()
        df[['is_sh', 'is_sl']] = df[['is_sh', 'is_sl']].fillna(False)
        return df

    def _build_pools(self, df: pd.DataFrame) -> List[LiquidityPool]:
        """Creates initial BSL/SSL pools from detected swings."""
        pools = []
        for idx in df[df['is_sh']].index:
            pools.append(LiquidityPool(price=df.loc[idx, 'high'], bar_idx=idx, pool_type='BSL'))
        for idx in df[df['is_sl']].index:
            pools.append(LiquidityPool(price=df.loc[idx, 'low'], bar_idx=idx, pool_type='SSL'))
        return pools

    def _cluster_equal_levels(self, pools: List[LiquidityPool]) -> List[LiquidityPool]:
        """Groups levels within tolerance % and upgrades to EQH/EQL."""
        def _mark_equals(group, target_type):
            if len(group) < 2: return group
            group.sort(key=lambda x: x.price)
            i = 0
            while i < len(group):
                j = i + 1
                while j < len(group):
                    if abs(group[j].price - group[i].price) / group[i].price <= self.eq_tolerance:
                        group[i].pool_type = target_type
                        group[j].pool_type = target_type
                    else:
                        break
                    j += 1
                i = j
            return group

        bsl = [p for p in pools if p.pool_type == 'BSL']
        ssl = [p for p in pools if p.pool_type == 'SSL']
        return _mark_equals(bsl, 'EQH') + _mark_equals(ssl, 'EQL')

    def _find_nearest_draws(self, current_price: float, pools: List[LiquidityPool]) -> Tuple[Optional[LiquidityPool], Optional[LiquidityPool]]:
        """Step 1 & 2: Identifies the most likely directional draw."""
        active = [p for p in pools if p.status == 'ACTIVE']
        above = [p for p in active if p.price > current_price]
        below = [p for p in active if p.price < current_price]

        # Priority: Gold (EQH/EQL) > Regular (BSL/SSL)
        bsl_draw = min((p for p in above if p.pool_type == 'EQH'), key=lambda x: x.price, default=None)
        if not bsl_draw:
            bsl_draw = min(above, key=lambda x: x.price, default=None)

        ssl_draw = max((p for p in below if p.pool_type == 'EQL'), key=lambda x: x.price, default=None)
        if not ssl_draw:
            ssl_draw = max(below, key=lambda x: x.price, default=None)

        return bsl_draw, ssl_draw

    def _check_sweeps(self, bar: pd.Series, bsl: Optional[LiquidityPool], ssl: Optional[LiquidityPool]) -> str:
        """Detects liquidity grabs with 1-bar rejection confirmation."""
        if bsl and bar['high'] > bsl.price and bar['close'] < bsl.price:
            bsl.status = 'SWEPT'
            bsl.sweep_bar_idx = bar.name
            return 'BSL_SWEEP'
        if ssl and bar['low'] < ssl.price and bar['close'] > ssl.price:
            ssl.status = 'SWEPT'
            ssl.sweep_bar_idx = bar.name
            return 'SSL_SWEEP'
        return ''

    def process(self, df: pd.DataFrame) -> pd.DataFrame:
        """Main execution pipeline. Returns enriched DataFrame with levels & signals."""
        df = self._detect_swings(df.copy())
        self.pools = self._build_pools(df)
        self.pools = self._cluster_equal_levels(self.pools)

        # Output columns
        df['active_bsl'] = np.nan
        df['active_ssl'] = np.nan
        df['sweep_event'] = ''
        df['signal'] = ''
        df['highlight_bar'] = False

        for i, bar in df.iterrows():
            # Step 1 & 2: Identify draw
            bsl_draw, ssl_draw = self._find_nearest_draws(bar['close'], self.pools)
            
            df.loc[i, 'active_bsl'] = bsl_draw.price if bsl_draw else np.nan
            df.loc[i, 'active_ssl'] = ssl_draw.price if ssl_draw else np.nan

            # Step 3: Wait for sweep
            event = self._check_sweeps(bar, bsl_draw, ssl_draw)
            df.loc[i, 'sweep_event'] = event
            
            if event and self.highlight_sweep:
                df.loc[i, 'highlight_bar'] = True

            # Step 4 & 5: Signal generation & target mapping
            if event == 'SSL_SWEEP' and bsl_draw:
                df.loc[i, 'signal'] = 'LONG'
            elif event == 'BSL_SWEEP' and ssl_draw:
                df.loc[i, 'signal'] = 'SHORT'

        if not self.keep_swept:
            # Mask swept levels for clean charts
            df['active_bsl'] = df.apply(lambda r: r['active_bsl'] if any(
                p.price == r['active_bsl'] and p.status == 'ACTIVE' for p in self.pools
            ) else np.nan, axis=1)
            df['active_ssl'] = df.apply(lambda r: r['active_ssl'] if any(
                p.price == r['active_ssl'] and p.status == 'ACTIVE' for p in self.pools
            ) else np.nan, axis=1)

        return df
