import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from dataclasses import dataclass
from typing import List, Tuple

# ═══════════════════════════════════════════════════════════════
# SETTINGS & CONFIGURATION
# ═══════════════════════════════════════════════════════════════

class Config:
    def __init__(self):
        # Original Settings
        self.lookback = 20
        self.confirmation = 3
        self.non_repaint = False  # Not fully implemented in backtest logic, defaults to Standard
        
        # Probability Settings
        self.en_prob = True
        self.en_rsi = True
        self.en_vol = True
        self.en_zone = True
        self.en_wick = True
        self.en_ema = True
        self.min_prob = 40
        
        # Factor Settings
        self.rsi_len = 14
        self.rsi_ob = 65
        self.rsi_os = 35
        self.ema_len = 50
        self.wick_ratio = 0.55
        self.swing_len = 50
        
        # Visuals
        self.bull_col = '#00E676'
        self.bear_col = '#FF3D57'
        self.gold_col = '#FFD700'
        self.bg_col = '#0D1117'
        self.show_panel = True

# ═══════════════════════════════════════════════════════════════
# INDICATOR ENGINE
# ═══════════════════════════════════════════════════════════════

class ReversalProbabilityEngine:
    def __init__(self, config: Config):
        self.cfg = config

    def _rsi(self, series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _ema(self, series, period):
        return series.ewm(span=period, adjust=False).mean()

    def _atr(self, df, period=14):
        high = df['high']
        low = df['low']
        close = df['close']
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, adjust=False).mean()

    def analyze(self, df: pd.DataFrame):
        """
        Runs the simulation and adds signals and probabilities to the DataFrame.
        """
        df = df.copy()
        
        # 1. Calculate Indicators
        df['atr'] = self._atr(df, 14)
        df['rsi'] = self._rsi(df['close'], self.cfg.rsi_len)
        df['ema'] = self._ema(df['close'], self.cfg.ema_len)
        df['vol_avg'] = df['volume'].rolling(20).mean()
        
        # Volume Spike
        df['vol_spike'] = df['volume'] > (df['vol_avg'] * 1.5)
        
        # Wick Calculations
        df['body'] = (df['close'] - df['open']).abs()
        df['total_range'] = df['high'] - df['low']
        df['upper_wick'] = df['high'] - df[['close', 'open']].max(axis=1)
        df['lower_wick'] = df[['close', 'open']].min(axis=1) - df['low']
        
        # Zones (Premium/Discount)
        df['swing_high'] = df['high'].rolling(self.cfg.swing_len).max()
        df['swing_low'] = df['low'].rolling(self.cfg.swing_len).min()
        df['eq_mid'] = (df['swing_high'] + df['swing_low']) / 2.0
        df['in_discount'] = df['close'] < df['eq_mid']
        df['in_premium'] = df['close'] > df['eq_mid']

        # 2. State Machine Simulation
        # Initialize State Variables
        bull_active = False
        bull_active_low = 0.0
        bull_active_high = 0.0
        bull_signal_active = False
        bull_count = 0
        
        bear_active = False
        bear_active_low = 0.0
        bear_active_high = 0.0
        bear_signal_active = False
        bear_count = 0
        
        # Lists to store results
        signals = [] # 0=none, 1=bull, -1=bear
        probs = []
        
        for i in range(len(df)):
            row = df.iloc[i]
            
            vup = False
            vdn = False
            
            # ---- Bull Logic ----
            # Check for "New Low" setup (Crash candle)
            # Condition: close < low[i-1], close < low[i-2] ... for lookback bars
            is_crash_candle = False
            if i >= self.cfg.lookback:
                # Get previous lookback-1 lows
                prev_lows = df['low'].iloc[i-self.cfg.lookback : i]
                if (row['close'] < prev_lows).all():
                    is_crash_candle = True
            
            if is_crash_candle:
                bull_active = True
                bull_active_low = row['low']
                bull_active_high = row['high']
                bull_signal_active = False
                bull_count = 0
            
            if bull_active:
                bull_count += 1
                
                # Invalidate if we make a lower low
                if row['close'] < bull_active_low:
                    bull_active = False
                    
                # Check Trigger (Reversal)
                # Must break the high of the crash candle
                if row['close'] > bull_active_high and not bull_signal_active:
                    if bull_count <= (self.cfg.confirmation + 1):
                        vup = True
                        bull_signal_active = True
                        # Optional: bull_active = False # In Pine it might stay active, but signal flags prevent repeat
                        # The Pine script doesn't set bull_active := false on trigger.
            
            # ---- Bear Logic ----
            # Check for "New High" setup (Pump candle)
            is_pump_candle = False
            if i >= self.cfg.lookback:
                prev_highs = df['high'].iloc[i-self.cfg.lookback : i]
                if (row['close'] > prev_highs).all():
                    is_pump_candle = True
            
            if is_pump_candle:
                bear_active = True
                bear_active_low = row['low']
                bear_active_high = row['high']
                bear_signal_active = False
                bear_count = 0
            
            if bear_active:
                bear_count += 1
                
                # Invalidate if we make a higher high
                if row['close'] > bear_active_high:
                    bear_active = False
                    
                # Check Trigger (Reversal)
                if row['close'] < bear_active_low and not bear_signal_active:
                    if bear_count <= (self.cfg.confirmation + 1):
                        vdn = True
                        bear_signal_active = True
            
            # ---- Probability Scoring ----
            curr_prob = 0
            signal_type = 0
            
            if vup or vdn:
                # Count enabled factors
                max_pts = 0
                if self.cfg.en_rsi: max_pts += 1
                if self.cfg.en_vol: max_pts += 1
                if self.cfg.en_zone: max_pts += 1
                if self.cfg.en_wick: max_pts += 1
                if self.cfg.ema_len > 0: max_pts += 1 # using ema len check as flag proxy for simplicity
                
                pts = 0
                
                # Bull Factors
                if vup:
                    if self.cfg.en_rsi and row['rsi'] < self.cfg.rsi_os: pts += 1
                    if self.cfg.en_vol and row['vol_spike'] and row['close'] > row['open']: pts += 1
                    if self.cfg.en_zone and row['in_discount']: pts += 1
                    if self.cfg.en_wick and row['lower_wick'] >= (row['total_range'] * self.cfg.wick_ratio): pts += 1
                    if self.cfg.ema_len > 0 and row['close'] > row['ema']: pts += 1
                    
                    signal_type = 1
                
                # Bear Factors
                elif vdn:
                    if self.cfg.en_rsi and row['rsi'] > self.cfg.rsi_ob: pts += 1
                    if self.cfg.en_vol and row['vol_spike'] and row['close'] < row['open']: pts += 1
                    if self.cfg.en_zone and row['in_premium']: pts += 1
                    if self.cfg.en_wick and row['upper_wick'] >= (row['total_range'] * self.cfg.wick_ratio): pts += 1
                    if self.cfg.ema_len > 0 and row['close'] < row['ema']: pts += 1
                    
                    signal_type = -1
                
                curr_prob = int((pts / max_pts) * 100) if max_pts > 0 else 50
            
            # Filter by min_prob
            if self.cfg.en_prob and curr_prob < self.cfg.min_prob:
                signal_type = 0
            
            signals.append(signal_type)
            probs.append(curr_prob)

        df['signal'] = signals
        df['probability'] = probs
        
        return df

# ═══════════════════════════════════════════════════════════════
# PLOTTING
# ═══════════════════════════════════════════════════════════════

def plot_indicator(df: pd.DataFrame, cfg: Config):
    plt.figure(figsize=(16, 9))
    ax = plt.gca()
    ax.set_facecolor(cfg.bg_col)
    
    # Plot Price
    for i in range(len(df)):
        color = cfg.bull_col if df['close'].iloc[i] >= df['open'].iloc[i] else cfg.bear_col
        # Highlight background for signals
        sig = df['signal'].iloc[i]
        if sig != 0:
            prob = df['probability'].iloc[i]
            bg_col = cfg.gold_col if prob >= 75 else (cfg.bull_col if sig == 1 else cfg.bear_col)
            # Highlight bar (Background)
            ax.axvspan(i-0.5, i+0.5, color=bg_col, alpha=0.2)
            
            # Draw Candlestick simple
        # (Simplifying OHLC plot for speed, just plotting lines)
        # In a full implementation, use mplfinance or proper candlestick plotting
        
        high = df['high'].iloc[i]
        low = df['low'].iloc[i]
        open_ = df['open'].iloc[i]
        close = df['close'].iloc[i]
        
        ax.plot([i, i], [low, high], color='black', linewidth=1)
        ax.plot([i-0.4, i+0.4], [open_, open_], color=color, linewidth=2)
        ax.plot([i-0.4, i+0.4], [close, close], color=color, linewidth=2)
        ax.plot([i, i], [open_, close], color=color, linewidth=2)

        # Labels
        if sig != 0:
            prob = df['probability'].iloc[i]
            lbl_col = cfg.gold_col if prob >= 75 else (cfg.bull_col if sig == 1 else cfg.bear_col)
            txt = f"{'▲' if sig == 1 else '▼'}\n{prob}%"
            
            y_pos = df['low'].iloc[i] - (df['atr'].iloc[i] * 0.4) if sig == 1 else df['high'].iloc[i] + (df['atr'].iloc[i] * 0.4)
            
            ax.annotate(txt, xy=(i, y_pos), xytext=(i, y_pos),
                       textcoords="offset points", ha='center', va='center',
                       bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.7),
                       color=lbl_col, fontsize=8, weight='bold')

    # EMA Line
    ax.plot(df.index, df['ema'], color='#888888', linestyle='--', linewidth=1, label=f'EMA({cfg.ema_len})', alpha=0.7)

    # Panel (Top Right Info Box)
    last = df.iloc[-1]
    
    # Bull/Bear current probability context (calculated on last bar regardless of signal)
    # Recalculate quickly for display context
    def get_score(is_bull):
        p = 0
        m = 0
        if cfg.en_rsi: m+=1
        if cfg.vol_spike: m+=1 # Using last bar vol spike state
        if cfg.en_zone: m+=1
        if cfg.en_wick: m+=1
        if cfg.ema_len > 0: m+=1
        
        rsi_c = last['rsi']
        
        if is_bull:
            if cfg.en_rsi and rsi_c < cfg.rsi_os: p+=1
            if cfg.en_vol and last['vol_spike'] and last['close'] > last['open']: p+=1
            if cfg.en_zone and last['in_discount']: p+=1
            if cfg.en_wick and last['lower_wick'] >= last['total_range']*cfg.wick_ratio: p+=1
            if cfg.ema_len > 0 and last['close'] > last['ema']: p+=1
        else:
            if cfg.en_rsi and rsi_c > cfg.rsi_ob: p+=1
            if cfg.en_vol and last['vol_spike'] and last['close'] < last['open']: p+=1
            if cfg.en_zone and last['in_premium']: p+=1
            if cfg.en_wick and last['upper_wick'] >= last['total_range']*cfg.wick_ratio: p+=1
            if cfg.ema_len > 0 and last['close'] < last['ema']: p+=1
            
        return int(p/m*100) if m>0 else 50

    bull_prob_now = get_score(True)
    bear_prob_now = get_score(False)
    
    panel_text = (
        f"REVERSAL · PROB\n"
        f"----------------\n"
        f"▲ Bull Prob: {bull_prob_now}%\n"
        f"▼ Bear Prob: {bear_prob_now}%\n"
        f"RSI: {int(last['rsi'])}\n"
        f"Zone: {'Premium' if last['in_premium'] else 'Discount'}\n"
        f"Min Filter: {cfg.min_prob}%"
    )
    
    props = dict(boxstyle='round', facecolor='#161B22', alpha=0.9)
    ax.text(0.98, 0.98, panel_text, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', horizontalalignment='right', bbox=props, color='white', family='monospace')

    ax.set_title("Reversal · Probability %", color='white')
    ax.grid(True, color='gray', linestyle=':', linewidth=0.5, alpha=0.3)
    ax.set_facecolor(cfg.bg_col)
    
    # Legend colors
    bull_patch = mpatches.Patch(color=cfg.bull_col, label='Bullish')
    bear_patch = mpatches.Patch(color=cfg.bear_col, label='Bearish')
    gold_patch = mpatches.Patch(color=cfg.gold_col, label='High Prob (≥75%)')
    plt.legend(handles=[bull_patch, bear_patch, gold_patch], loc='upper left')
    
    plt.tight_layout()
    plt.show()

# ═══════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 1. Generate Synthetic Data
    np.random.seed(42)
    length = 300
    dates = pd.date_range(start='2023-01-01', periods=length, freq='H')
    
    # Create a trend with reversals to test the logic
    price = 1.1000
    trend = 0
    closes = []
    for _ in range(length):
        # Random trend switch
        if np.random.rand() < 0.02:
            trend = np.random.choice([-0.001, 0.001])
        
        noise = np.random.normal(0, 0.0005)
        price += trend + noise
        closes.append(price)
        
    close = np.array(closes)
    high = close + np.random.uniform(0, 0.0005, length)
    low = close - np.random.uniform(0, 0.0005, length)
    open_ = close + np.random.uniform(-0.0002, 0.0002, length)
    volume = np.random.randint(100, 500, length)
    
    # Inject specific patterns to trigger logic (New Low then Breakout)
    # At bar 100: Crash
    if len(low) > 105:
        low[100] = low[90] - 0.002 # Break all previous lows
        close[100] = low[100]
        open_[100] = low[100]
        # Then breakout
        close[101:105] = np.linspace(low[100], low[100] + 0.003, 4)
        high[101:105] = close[101:105] + 0.0001

    data = {
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    }
    df = pd.DataFrame(data, index=dates)
    
    # 2. Initialize and Run
    cfg = Config()
    engine = ReversalProbabilityEngine(cfg)
    result_df = engine.analyze(df)
    
    # 3. Plot
    plot_indicator(result_df, cfg)
