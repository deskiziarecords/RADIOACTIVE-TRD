import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import IntEnum

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

class Config:
    def __init__(self):
        # Pattern Detection
        self.pivot_len = 5
        self.sym_min = 60.0
        self.neckline_tol = 1.5  # ATR units
        self.shoulder_tol = 2.5   # ATR units
        self.head_min_ext = 1.2   # ATR units
        self.vol_confirm = True
        
        # Lifecycle
        self.show_forming = True
        self.track_retest = True
        self.tp1_mode = "Classic" # or "Measured Move"
        self.show_tp2 = True
        self.stop_buff_atr = 0.35
        self.invalid_bars = 120
        
        # Visuals
        self.font_size = "Normal" # Small, Normal, Large
        self.show_labels = True
        self.show_zones = True
        self.label_offset_atr = 1.5
        
        # Colors
        self.bull_col = '#22C5A6'
        self.bear_col = '#F472B6'
        self.neutral_col = '#F5BD5C'
        self.accent_col = '#818CF8'

# ═══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

class PatternState(IntEnum):
    NONE = 0
    FORMING = 1
    CONFIRMED = 2
    TARGET_HIT = 3
    FAILED = 4

@dataclass
class HSPattern:
    id: int
    bearish: bool
    ls_bar: int
    ls_price: float
    head_bar: int
    head_price: float
    rs_bar: int
    rs_price: float
    nl1_bar: int
    nl1_price: float
    nl2_bar: int
    nl2_price: float
    sym_score: float
    qual_score: float
    state: PatternState
    confirm_bar: int = -1
    tp1: float = np.nan
    tp2: float = np.nan
    stop: float = np.nan
    retested: bool = False
    # These are calculated dynamically for plotting
    # or stored if we want exact Pine replica
    
# ═══════════════════════════════════════════════════════════════
# ENGINE
# ═══════════════════════════════════════════════════════════════

class HSDetector:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.patterns: List[HSPattern] = []
        self.next_id = 1
        
        # Buffers (Circular) - storing (price, bar_idx, volume)
        self.high_buffer: List[Tuple[float, int, float]] = []
        self.low_buffer: List[Tuple[float, int, float]] = []
        self.buffer_cap = 12

    def _rma(self, series, length):
        """Wilder's Smoothing (RMA) equivalent to ta.atr."""
        alpha = 1 / length
        return series.ewm(alpha=alpha, adjust=False).mean()

    def _atr(self, df, length):
        high = df['high']
        low = df['low']
        close = df['close']
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return self._rma(tr, length)

    def _get_pivots(self, df: pd.DataFrame):
        """Detect High and Low pivots using centered windows."""
        # Pine script: ta.pivothigh(high, pivotLen, pivotLen)
        # Pandas equivalent: rolling max/min with center=True
        window = self.cfg.pivot_len * 2 + 1
        
        # Check strict equality for pivot to avoid duplicates on flat tops
        is_ph = df['high'].rolling(window, center=True).max() == df['high']
        is_pl = df['low'].rolling(window, center=True).min() == df['low']
        
        return is_ph, is_pl

    def _find_neckline_anchors(self, df, ls_bar, head_bar, rs_bar, look_for_highs):
        """
        Find opposite pivots between LS-Head and Head-RS.
        If pattern is Bearish (H-S), we look for Low pivots for necklines.
        """
        anchors = []
        
        # Select the correct column and series
        if look_for_highs:
            col, pivot_bool = 'high', self.is_ph
        else:
            col, pivot_bool = 'low', self.is_pl
            
        # Slice dataframe to find pivots in range 1
        range1_df = df.loc[(df.index > ls_bar) & (df.index < head_bar)]
        pivots_1 = range1_df[range1_df.index.isin(df[pivot_bool][pivot_bool].index)]
        
        # Slice dataframe to find pivots in range 2
        range2_df = df.loc[(df.index > head_bar) & (df.index < rs_bar)]
        pivots_2 = range2_df[range2_df.index.isin(df[pivot_bool][pivot_bool].index)]
        
        # Take the last (closest to head) pivot found in range 1, and first in range 2
        if not pivots_1.empty:
            anchors.append((pivots_1.index[-1], pivots_1[col].iloc[-1]))
        else:
            return None, None
            
        if not pivots_2.empty:
            anchors.append((pivots_2.index[0], pivots_2[col].iloc[0]))
        else:
            return None, None
            
        return anchors[0], anchors[1]

    def _calc_neckline_at(self, pattern: HSPattern, bar_idx):
        """Linear interpolation of neckline."""
        dx = pattern.nl2_bar - pattern.nl1_bar
        dy = pattern.nl2_price - pattern.nl1_price
        if dx == 0: return pattern.nl1_price
        slope = dy / dx
        return pattern.nl1_price + slope * (bar_idx - pattern.nl1_bar)

    def run_simulation(self, df: pd.DataFrame):
        """Main simulation loop."""
        self.df = df.copy()
        
        # 1. Calculate Indicators
        self.df['atr'] = self._atr(self.df, 14)
        self.is_ph, self.is_pl = self._get_pivots(self.df)
        
        # Statistics for panel
        stats = {
            'forming': 0, 'confirmed': 0, 'total_conf': 0,
            'target_hit': 0, 'failed': 0, 'qual_sum': 0.0, 'qual_cnt': 0
        }
        
        last_pattern_bar = -999
        
        for i in self.df.index:
            row = self.df.loc[i]
            
            # 1. Update Buffers
            if self.is_ph.loc[i]:
                # In Pine, volume is taken from pivotLen ago because pivot is confirmed late
                # In Pandas centered, we are at the pivot bar.
                # To mimic Pine's "confirmed" delay, we could look back, but centered is standard for Python.
                # We'll use current volume for simplicity.
                self.high_buffer.append((row['high'], i, row['volume']))
                if len(self.high_buffer) > self.buffer_cap:
                    self.high_buffer.pop(0)
                    
            if self.is_pl.loc[i]:
                self.low_buffer.append((row['low'], i, row['volume']))
                if len(self.low_buffer) > self.buffer_cap:
                    self.low_buffer.pop(0)

            # 2. Detect New Pattern
            # Check cooldown
            if (i - last_pattern_bar) >= (self.cfg.pivot_len * 2):
                pat = self._detect_pattern(bearish=True)
                if pat:
                    self.patterns.append(pat)
                    last_pattern_bar = i
                else:
                    pat = self._detect_pattern(bearish=False)
                    if pat:
                        self.patterns.append(pat)
                        last_pattern_bar = i

            # 3. Update Lifecycle of existing patterns
            for pat in self.patterns:
                if pat.state == PatternState.FORMING:
                    # Check Confirmation (Neckline Break)
                    nl_level = self._calc_neckline_at(pat, i)
                    
                    if pat.bearish:
                        broken = row['close'] < nl_level
                    else:
                        broken = row['close'] > nl_level
                        
                    if broken and i > pat.rs_bar:
                        pat.state = PatternState.CONFIRMED
                        pat.confirm_bar = i
                        
                        # Calculate Targets & Stop
                        # Classic: Head to horizontal midpoint of neck
                        mid_nl = (pat.nl1_price + pat.nl2_price) / 2.0
                        # Measured: Head to actual neck at head_bar
                        nl_at_head = self._calc_neckline_at(pat, pat.head_bar)
                        
                        dist = abs(pat.head_price - nl_at_head) if self.cfg.tp1_mode == "Measured Move" else abs(pat.head_price - mid_nl)
                        
                        if pat.bearish:
                            pat.tp1 = nl_level - dist
                            pat.tp2 = nl_level - dist * 1.618
                            pat.stop = pat.head_price + (row['atr'] * self.cfg.stop_buff_atr)
                        else:
                            pat.tp1 = nl_level + dist
                            pat.tp2 = nl_level + dist * 1.618
                            pat.stop = pat.head_price - (row['atr'] * self.cfg.stop_buff_atr)
                            
                        stats['total_conf'] += 1
                        stats['qual_sum'] += pat.qual_score
                        stats['qual_cnt'] += 1
                        
                    # Check Invalidation (Age or Head Break)
                    elif (i - pat.rs_bar) > self.cfg.invalid_bars:
                        pat.state = PatternState.FAILED
                        stats['failed'] += 1
                    else:
                        # Head broken?
                        if (pat.bearish and row['close'] > pat.head_price) or \
                           (not pat.bearish and row['close'] < pat.head_price):
                            pat.state = PatternState.FAILED
                            stats['failed'] += 1

                elif pat.state == PatternState.CONFIRMED:
                    # Check TP1
                    if pat.bearish and row['low'] <= pat.tp1:
                        pat.state = PatternState.TARGET_HIT
                        stats['target_hit'] += 1
                    elif not pat.bearish and row['high'] >= pat.tp1:
                        pat.state = PatternState.TARGET_HIT
                        stats['target_hit'] += 1
                    
                    # Check Stop
                    if pat.bearish and row['high'] >= pat.stop:
                        pat.state = PatternState.FAILED
                        stats['failed'] += 1
                    elif not pat.bearish and row['low'] <= pat.stop:
                        pat.state = PatternState.FAILED
                        stats['failed'] += 1
                        
                    # Retest
                    if self.cfg.track_retest and not pat.retested and (i - pat.confirm_bar) > 2:
                        nl_now = self._calc_neckline_at(pat, i)
                        # Touch condition
                        if (row['low'] <= nl_now <= row['high']):
                            pat.retested = True

            # Cleanup very old patterns to save memory (optional, kept for plotting history)
            
        return stats

    def _detect_pattern(self, bearish: bool) -> Optional[HSPattern]:
        """
        Checks last 3 pivots in buffer.
        Bearish = H-S-H (High pivots)
        Bullish = S-H-S (Low pivots)
        """
        buffer = self.high_buffer if bearish else self.low_buffer
        if len(buffer) < 3: return None
        
        # Get last 3
        rs = buffer[-1]
        head = buffer[-2]
        ls = buffer[-3] # Most recent is RS (Right Shoulder) in terms of time progression in buffer? 
                         # Actually in Pine buffer: [ ..., LS, Head, RS ] where RS is most recent.
                         # My buffer appends new pivots to the end. So buffer[-1] is RS, -2 is Head, -3 is LS.
                         
        rs_p, rs_b, rs_v = rs
        hd_p, hd_b, hd_v = head
        ls_p, ls_b, ls_v = ls
        
        atr = self.df.loc[rs_b]['atr'] # ATR at the moment of RS pivot
        
        # 1. Head Validity
        head_valid = (hd_p > ls_p and hd_p > rs_p) if bearish else (hd_p < ls_p and hd_p < rs_p)
        if not head_valid: return None
        
        # 2. Head Prominence
        ext = min(hd_p - ls_p, hd_p - rs_p) if bearish else min(ls_p - hd_p, rs_p - hd_p)
        if ext < (self.cfg.head_min_ext * atr): return None
        
        # 3. Symmetry
        diff = abs(ls_p - rs_p)
        if diff > (self.cfg.shoulder_tol * atr): return None
        
        # 4. Bar Spacing (Sanity check)
        if (hd_b - ls_b < self.cfg.pivot_len) or (rs_b - hd_b < self.cfg.pivot_len): return None
        
        # 5. Neckline
        nl1, nl2 = self._find_neckline_anchors(self.df, ls_b, hd_b, rs_b, look_for_highs=not bearish)
        if nl1 is None or nl2 is None: return None
        
        nl_delta = abs(nl1[1] - nl2[1])
        if nl_delta > (self.cfg.neckline_tol * atr): return None
        
        # 6. Calculate Scores
        # Time Symmetry
        span_lh = hd_b - ls_b
        span_hr = rs_b - hd_b
        time_sym = 100.0 * (1.0 - abs(span_lh - span_hr) / max(span_lh, span_hr))
        
        # Price Symmetry
        price_sym = 100.0 * (1.0 - diff / max(ext, atr))
        price_sym = max(0.0, min(100.0, price_sym))
        
        sym_score = (time_sym * 0.5 + price_sym * 0.5)
        if sym_score < self.cfg.sym_min: return None
        
        # Volume Score (Soft)
        vol_score = 50.0
        if self.cfg.vol_confirm and hd_v and ls_v and rs_v:
            avg_vol = (ls_v + rs_v) / 2.0
            if avg_vol > 0:
                vol_score = min(100.0, 50.0 + (hd_v / avg_vol - 1.0) * 50.0)
                vol_score = max(0.0, vol_score)
        
        # Flatness
        flat_score = 100.0 * (1.0 - nl_delta / (self.cfg.neckline_tol * atr))
        
        # Prominence Score
        prom_score = min(100.0, (ext / atr) * 30.0)
        
        # Quality
        qual = (sym_score * 0.45 + flat_score * 0.25 + vol_score * 0.15 + prom_score * 0.15)
        
        return HSPattern(
            id=self.next_id,
            bearish=bearish,
            ls_bar=ls_b, ls_price=ls_p,
            head_bar=hd_b, head_price=hd_p,
            rs_bar=rs_b, rs_price=rs_p,
            nl1_bar=nl1[0], nl1_price=nl1[1],
            nl2_bar=nl2[0], nl2_price=nl2[1],
            sym_score=sym_score,
            qual_score=qual,
            state=PatternState.FORMING,
            retested=False
        )

# ═══════════════════════════════════════════════════════════════
# PLOTTING
# ═══════════════════════════════════════════════════════════════

def plot_patterns(df, detector: HSDetector):
    fig, ax = plt.subplots(figsize=(20, 10))
    
    # Plot Price
    ax.plot(df.index, df['close'], color='black', alpha=0.6, linewidth=1, label='Close')
    
    # Plot Patterns
    for pat in detector.patterns:
        # Only plot forming, confirmed, or recent targets
        if pat.state == PatternState.FAILED: continue
        
        col = detector.cfg.bear_col if pat.bearish else detector.cfg.bull_col
        
        # Neckline
        # Calculate end point (extend to end of chart)
        end_idx = df.index[-1]
        end_price = detector._calc_neckline_at(pat, end_idx)
        
        ax.plot([pat.nl1_bar, pat.nl2_bar, end_idx], 
                [pat.nl1_price, pat.nl2_price, end_price], 
                color=detector.cfg.accent_col, linestyle='-', linewidth=2, alpha=0.8)
        
        # Skeleton (LS-Head-RS)
        ax.plot([pat.ls_bar, pat.head_bar], [pat.ls_price, pat.head_price], color=col, linestyle=':', linewidth=1)
        ax.plot([pat.head_bar, pat.rs_bar], [pat.head_price, pat.rs_price], color=col, linestyle=':', linewidth=1)
        
        # Shoulders Zones
        if detector.cfg.show_zones:
            atr = df.loc[pat.ls_bar]['atr']
            z_h = atr * 0.5
            w = max(detector.cfg.pivot_len * 2, 8)
            
            # LS Zone
            ax.add_patch(patches.Rectangle((pat.ls_bar - w, pat.ls_price - z_h), w*2, z_h*2, 
                                       facecolor=col, alpha=0.1, edgecolor=col, linewidth=0.5))
            # RS Zone
            ax.add_patch(patches.Rectangle((pat.rs_bar - w, pat.rs_price - z_h), w*2, z_h*2, 
                                       facecolor=col, alpha=0.1, edgecolor=col, linewidth=0.5))

        # Label
        offset = df.loc[pat.head_bar]['atr'] * detector.cfg.label_offset_atr
        y_lbl = pat.head_price + offset if pat.bearish else pat.head_price - offset
        
        status_txt = "⭐" if pat.qual_score >= 75 else ""
        txt = f"{status_txt}{'H-S-H' if pat.bearish else 'S-H-S'}\nQ:{int(pat.qual_score)}"
        
        ax.text(pat.head_bar, y_lbl, txt, color=col, ha='center', va='center',
               bbox=dict(boxstyle="round,pad=0.3", fc='white', ec=col, alpha=0.8, linewidth=1),
               fontsize=8, weight='bold')

        # Targets (if confirmed)
        if pat.state == PatternState.CONFIRMED or pat.state == PatternState.TARGET_HIT:
            # TP1
            ax.plot([pat.confirm_bar, end_idx], [pat.tp1, pat.tp1], 
                    color=col, linestyle='--', linewidth=1, alpha=0.5)
            ax.text(pat.confirm_bar + 10, pat.tp1, f"TP1", color=col, fontsize=8, va='bottom')
            
            # TP2
            if detector.cfg.show_tp2:
                ax.plot([pat.confirm_bar, end_idx], [pat.tp2, pat.tp2], 
                        color=col, linestyle='--', linewidth=1, alpha=0.3)
                ax.text(pat.confirm_bar + 10, pat.tp2, f"TP2", color=col, fontsize=8, va='bottom')
            
            # Stop
            ax.plot([pat.confirm_bar, end_idx], [pat.stop, pat.stop], 
                    color='gray', linestyle=':', linewidth=1, alpha=0.3)

    ax.set_title(f"AG Pro H&S Detector - {len(detector.patterns)} Patterns Found")
    ax.grid(True, linestyle=':', alpha=0.3)
    plt.show()

# ═══════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 1. Generate Synthetic Data
    np.random.seed(101)
    length = 300
    dates = pd.date_range(start='2023-01-01', periods=length, freq='H')
    
    # Create a synthetic H&S pattern
    prices = [100.0]
    for i in range(1, length):
        trend = 0
        # Force a pattern at bar 150
        if i == 80: prices.append(105)   # LS
        elif i == 90: prices.append(100)   # Neck
        elif i == 110: prices.append(108) # Head
        elif i == 130: prices.append(103) # Neck
        elif i == 150: prices.append(106) # RS
        elif i == 170: prices.append(102) # Neck
        elif i == 180: prices.append(98)  # Break
        else:
            # Random walk
            noise = np.random.normal(0, 0.5)
            prices.append(prices[-1] + noise)
            
    close = np.array(prices)
    high = close + np.random.uniform(0, 0.2, length)
    low = close - np.random.uniform(0, 0.2, length)
    open_ = close + np.random.uniform(-0.1, 0.1, length)
    volume = np.random.randint(100, 1000, length)
    
    # Make the Head and Shoulders more distinct in Highs/Lows
    high[80] = 105.5; low[80] = 104.5
    high[110] = 109; low[110] = 108
    high[150] = 106.5; low[150] = 105.5
    
    df = pd.DataFrame({
        'open': open_, 'high': high, 'low': low, 'close': close, 'volume': volume
    }, index=dates)
    
    # 2. Run Detector
    cfg = Config()
    detector = HSDetector(cfg)
    stats = detector.run_simulation(df)
    
    # 3. Print Stats
    print(f"Total Patterns: {len(detector.patterns)}")
    print(f"Confirmed: {stats['total_conf']}")
    print(f"Target Hits: {stats['target_hit']}")
    print(f"Failed: {stats['failed']}")
    if stats['qual_cnt'] > 0:
        print(f"Avg Quality: {stats['qual_sum']/stats['qual_cnt']:.1f}")
    
    # 4. Plot
    plot_patterns(df, detector)
