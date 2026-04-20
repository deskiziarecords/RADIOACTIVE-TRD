import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

# ═══════════════════════════════════════════════════════════════
# CONSTANTS & CONFIGURATION
# ═══════════════════════════════════════════════════════════════

COLORS = {
    'bsl': '#00BFFF',   # Deep Sky Blue
    'ssl': '#FF4C6A',   # Light Red/Pink
    'eqh': '#FFD700',   # Gold
    'swept_fade': 75,   # Alpha transparency for swept lines
    'zone_fade': 88     # Alpha transparency for zones
}

@dataclass
class LiquidityLevel:
    """Represents a single BSL or SSL level instance."""
    level_type: str       # 'BSL' or 'SSL'
    price: float
    start_idx: int        # Bar index where pivot occurred
    active: bool          # True if not yet swept
    swept: bool           # True if swept
    eq: bool              # True if it is an Equal High/Low connection
    end_idx: int          # Bar index where level ends (swept or current)
    color: str
    style: str            # 'solid', 'dotted', 'dashed'
    text: str             # Label text
    
class LiquidityPoolEngine:
    def __init__(self, lookback=106, swing_len=5, eq_pct=3.0, ext_right=30, show_swept=True):
        self.lookback = lookback
        self.swing_len = swing_len
        self.eq_pct = eq_pct
        self.ext_right = ext_right
        self.show_swept = show_swept
        
        self.levels: List[LiquidityLevel] = []
        self.zones: List[dict] = [] # Stores EQ zones
        
    def _f_near(self, a: float, b: float) -> bool:
        """Pine script equivalent: math.abs(a - b) / ((a + b) * 0.5) * 100 <= eq_pct"""
        if a == 0 or b == 0: return False
        return abs(a - b) / ((a + b) * 0.5) * 100 <= self.eq_pct

    def detect_pivots(self, df: pd.DataFrame):
        """
        Detect Pivot Highs and Lows using rolling windows.
        ta.pivothigh(high, swing_len, swing_len) -> rolling max check
        """
        window = self.swing_len * 2 + 1
        
        # Check if high is max in window (center=True)
        is_ph = df['high'].rolling(window, center=True).max() == df['high']
        # Check if low is min in window
        is_pl = df['low'].rolling(window, center=True).min() == df['low']
        
        # Fill NaNs (edges of dataframe) with False
        df['ph_val'] = df['high'].where(is_ph)
        df['pl_val'] = df['low'].where(is_pl)
        
        return df

    def run_simulation(self, df: pd.DataFrame):
        """
        Simulate the bar-by-bar logic of the Pine Script.
        """
        # Pre-calculate pivots
        df = self.detect_pivots(df)
        
        total_bars = len(df)
        
        for i in range(total_bars):
            high = df['high'].iloc[i]
            low = df['low'].iloc[i]
            ph_val = df['ph_val'].iloc[i]
            pl_val = df['pl_val'].iloc[i]
            
            # ═══════════════════════════════════════════════════════════════
            # 1. UPDATE LOOP (Sweeps, Extensions, Cleanup)
            # Iterate backwards to safely remove items (Pine script style)
            # ═══════════════════════════════════════════════════════════════
            
            # We iterate a copy or use indices carefully because we might delete
            # However, list modification in reverse loop is safe.
            
            for k in range(len(self.levels) - 1, -1, -1):
                lvl = self.levels[k]
                age = i - lvl.start_idx
                
                # Cleanup: Exceed Lookback
                if age > self.lookback:
                    del self.levels[k]
                    continue
                
                # Sweep Logic
                if lvl.active:
                    is_swept = False
                    if lvl.level_type == 'BSL' and high > lvl.price:
                        is_swept = True
                    elif lvl.level_type == 'SSL' and low < lvl.price:
                        is_swept = True
                    
                    if is_swept:
                        lvl.active = False
                        lvl.swept = True
                        lvl.end_idx = i
                        
                        # Update style for swept
                        lvl.style = 'dashed'
                        # Logic: if show_swept is false, we could delete, 
                        # but keeping them allows visualization of the "ghost" liquidity
                        if not self.show_swept:
                            del self.levels[k]
                            continue
                    else:
                        # Extension: Update end index to current bar
                        lvl.end_idx = i

            # ═══════════════════════════════════════════════════════════════
            # 2. REGISTER NEW LEVELS (Pivots)
            # ═══════════════════════════════════════════════════════════════
            
            # Register BSL (Pivot High)
            if not pd.isna(ph_val):
                # Check for EQH
                is_eqh = False
                match_idx = -1
                
                # Check active levels for proximity
                for l in self.levels:
                    if l.active and l.level_type == 'BSL' and self._f_near(l.price, ph_val):
                        is_eqh = True
                        match_idx = l.start_idx
                        # Update the matched old level to EQ style
                        l.eq = True
                        l.color = COLORS['eqh']
                        l.style = 'solid'
                        l.text = "EQH · BSL"
                        break
                
                # Create Zone visual data if EQ
                if is_eqh and match_idx != -1:
                    self.zones.append({
                        'start_idx': match_idx,
                        'end_idx': i + self.ext_right, # Placeholder, fixed later
                        'price1': ph_val,
                        'price2': ph_val,
                        'type': 'EQH'
                    })

                # Create new level
                new_lvl = LiquidityLevel(
                    level_type='BSL',
                    price=ph_val,
                    start_idx=i,
                    active=True,
                    swept=False,
                    eq=is_eqh,
                    end_idx=i + self.ext_right,
                    color=COLORS['bsl'],
                    style='solid',
                    text="BSL"
                )
                self.levels.append(new_lvl)

            # Register SSL (Pivot Low)
            if not pd.isna(pl_val):
                is_eql = False
                match_idx = -1
                
                for l in self.levels:
                    if l.active and l.level_type == 'SSL' and self._f_near(l.price, pl_val):
                        is_eql = True
                        match_idx = l.start_idx
                        l.eq = True
                        l.color = COLORS['eqh']
                        l.style = 'solid'
                        l.text = "EQL · SSL"
                        break
                
                if is_eql and match_idx != -1:
                    self.zones.append({
                        'start_idx': match_idx,
                        'end_idx': i + self.ext_right,
                        'price1': pl_val,
                        'price2': pl_val,
                        'type': 'EQL'
                    })

                new_lvl = LiquidityLevel(
                    level_type='SSL',
                    price=pl_val,
                    start_idx=i,
                    active=True,
                    swept=False,
                    eq=is_eql,
                    end_idx=i + self.ext_right,
                    color=COLORS['ssl'],
                    style='solid',
                    text="SSL"
                )
                self.levels
