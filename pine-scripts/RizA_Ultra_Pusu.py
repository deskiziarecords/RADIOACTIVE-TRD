import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from datetime import datetime, time
import warnings

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION & PALETTE
# ═══════════════════════════════════════════════════════════════

class Config:
    # Inputs
    pivot_len = 30
    show_bull_ob = True
    show_bear_ob = True
    show_killzones = True
    
    # Colors
    bull_color = '#061b3a'
    bull_break = '#4785f9'
    bear_color = '#FF3131'
    bear_break = '#f9ff57'
    
    # SMA Colors
    sma_bull_fill = '#124b2d'
    sma_bear_fill = '#750c0c'
    
    # Killzone Colors
    kz_asia = 'blue'
    kz_london = 'red'
    kz_ny_am = '#089981'
    kz_ny_lunch = 'yellow'
    kz_ny_pm = 'purple'

# ═══════════════════════════════════════════════════════════════
# CORE ANALYZER CLASS
# ═══════════════════════════════════════════════════════════════

class RizAEngine:
    def __init__(self, df: pd.DataFrame, config: Config):
        self.df = df.copy()
        self.cfg = config
        self.df['datetime'] = pd.to_datetime(self.df.index) # Assuming datetime index
        
        # Results containers
        self.ob_zones = [] # List of dicts for Order Blocks
        self.kz_pivots = [] # List of dicts for Killzone Pivots
        
        # Session Helper
        self.sessions = [
            {'name': 'ASIA', 'start': 20, 'end': 0, 'color': self.cfg.kz_asia, 'active': False},
            {'name': 'LONDON', 'start': 2, 'end': 5, 'color': self.cfg.kz_london, 'active': False},
            {'name': 'NY AM', 'start': 9, 'end': 11, 'color': self.cfg.kz_ny_am, 'active': False},
            {'name': 'NY LUNCH', 'start': 12, 'end': 13, 'color': self.cfg.kz_ny_lunch, 'active': False},
            {'name': 'NY PM', 'start': 13, 'end': 16, 'color': self.cfg.kz_ny_pm, 'active': False}
        ]

    def calculate_indicators(self):
        # SMAs
        self.df['sma_short'] = self.df['close'].rolling(20).mean()
        self.df['sma_long'] = self.df['close'].rolling(50).mean()
        self.df['trend'] = np.where(self.df['sma_short'] > self.df['sma_long'], 1, -1)
        
        # Killzone Helpers
        self.df['hour'] = self.df['datetime'].dt.hour

    def detect_order_blocks(self):
        """
        Logic: 
        1. Detect Swing High/Low.
        2. Bearish Setup: Swing High -> Swing Low. 
           OB is the last aggressive down candle before the low.
        3. Bullish Setup: Swing Low -> Swing High.
           OB is the last aggressive up candle before the high.
        """
        df = self.df
        l = self.cfg.pivot_len
        
        # Pivot Highs/Lows
        # Note: Pine script logic checks against highest/lowest of last `l` bars
        df['is_ph'] = df['high'] == df['high'].rolling(window=l*2+1, center=True).max()
        df['is_pl'] = df['low'] == df['low'].rolling(window=l*2+1, center=True).min()
        
        # Fill NaNs
        df['is_ph'].fillna(False, inplace=True)
        df['is_pl'].fillna(False, inplace=True)

        # State variables for logic (simulating Pine Script `var` arrays)
        last_top_y = np.nan
        last_top_x = 0
        last_btm_y = np.nan
        last_btm_x = 0
        top_crossed = False
        btm_crossed = False

        # Iterate
        for i in range(l, len(df) - l):
            # Check Swing High
            if df['is_ph'].iloc[i]:
                if not top_crossed and (not np.isnan(last_top_y)):
                    # We have a previous top that wasn't crossed, this is invalid structure?
                    # The Pine script logic creates an OB when we reverse direction.
                    pass
                last_top_y = df['high'].iloc[i]
                last_top_x = i
                top_crossed = False
            
            # Check Swing Low
            if df['is_pl'].iloc[i]:
                last_btm_y = df['low'].iloc[i]
                last_btm_x = i
                btm_crossed = False

            # Bearish OB Detection (Swing High -> Swing Low)
            # If we hit a swing low, and previously had a swing high...
            # The OB is the candle that pushed down towards the low.
            # Simplified: The bearish OB is usually the start of the down move.
            if df['is_pl'].iloc[i] and not np.isnan(last_top_y) and i > last_top_x:
                # Look back from `i` to `last_top_x` to find the "aggressive" candle (body)
                # Pine uses ob_max = max(close, open).
                # We will define OB Top as the High of the swing, OB Btm as the Low of the swing.
                
                # Calculate if broken later
                ob_high = last_top_y
                ob_low = df['low'].iloc[i] # Or low of the specific OB candle
                ob_start_idx = last_top_x
                
                # Check if this OB was broken in the future
                # (Simulated by looking ahead in the dataframe)
                future_highs = df['high'].iloc[i+1:]
                if (future_highs > ob_high).any():
                    status = "BROKEN"
                    color = self.cfg.bear_break
                else:
                    status = "ACTIVE"
                    color = self.cfg.bear_color
                
                self.ob_zones.append({
                    'x_start': ob_start_idx, 
                    'x_end': i,
                    'y_top': ob_high,
                    'y_btm': ob_low,
                    'type': 'BEAR',
                    'status': status,
                    'color': color
                })
                
                # Reset top to avoid reusing? Pine script keeps buffers.
                # For this viz, we reset to keep it clean.
                last_top_y = np.nan

            # Bullish OB Detection (Swing Low -> Swing High)
            if df['is_ph'].iloc[i] and not np.isnan(last_btm_y) and i > last_btm_x:
                ob_high = df['high'].iloc[i]
                ob_low = last_btm_y
                ob_start_idx = last_btm_x
                
                future_lows = df['low'].iloc[i+1:]
                if (future_lows < ob_low).any():
                    status = "BROKEN"
                    color = self.cfg.bull_break
                else:
                    status = "ACTIVE"
                    color = self.cfg.bull_color
                    
                self.ob_zones.append({
                    'x_start': ob_start_idx,
                    'x_end': i,
                    'y_top': ob_high,
                    'y_btm': ob_low,
                    'type': 'BULL',
                    'status': status,
                    'color': color
                })
                last_btm_y = np.nan

    def detect_killzone_pivots(self):
        """Tracks High/Low of active sessions and lines."""
        df = self.df
        
        active_sessions = {}
        
        for i, row in df.iterrows():
            current_time = row['hour']
            
            for session in self.sessions:
                s_name = session['name']
                s_start = session['start']
                s_end = session['end']
                
                # Check if inside session
                # Handle midnight crossover (e.g. 20:00 to 00:00)
                in_session = False
                if s_end < s_start: # Midnight crossover
                    in_session = current_time >= s_start or current_time < s_end
                else:
                    in_session = s_start <= current_time < s_end

                if in_session:
                    if s_name not in active_sessions:
                        # Session Started
                        active_sessions[s_name] = {
                            'start_idx': i,
                            'high': row['high'],
                            'low': row['low'],
                            'high_broken': False,
                            'low_broken': False
                        }
                    else:
                        # Session Active - Update High/Low
                        cur_ses = active_sessions[s_name]
                        if row['high'] > cur_ses['high']:
                            cur_ses['high'] = row['high']
                        if row['low'] < cur_ses['low']:
                            cur_ses['low'] = row['low']
                        
                        # Check Breaks
                        if row['high'] > cur_ses['high']: # Should be redundant based on update logic above
                            # Actually check against the "pivot" line (highest point at that time)
                            pass 
                        
                        # In Pine, line extends until price crosses it.
                        # Logic simplified: If price > session_max + margin, line broken.
                        # We will just mark the session High/Low.
                        
                elif s_name in active_sessions:
                    # Session Ended
                    ended_ses = active_sessions.pop(s_name)
                    
                    # Determine if the lines are still valid (unbroken)
                    # Check price action after session end
                    future_data = df.loc[i:]
                    
                    high_broken = (future_data['high'] > ended_ses['high']).any()
                    low_broken = (future_data['low'] < ended_ses['low']).any()
                    
                    self.kz_pivots.append({
                        'name': s_name,
                        'x_start': ended_ses['start_idx'],
                        'x_end': i, # Or last bar of data
                        'high': ended_ses['high'],
                        'low': ended_ses['low'],
                        'color': session['color'],
                        'high_broken': high_broken,
                        'low_broken': low_broken
                    })

    def analyze(self):
        self.calculate_indicators()
        self.detect_order_blocks()
        self.detect_killzone_pivots()

# ═══════════════════════════════════════════════════════════════
# PLOTTING
# ═══════════════════════════════════════════════════════════════

def plot_riza(df, engine: RizAEngine):
    fig, ax = plt.subplots(figsize=(20, 10))
    ax.set_facecolor('#121212') # Dark background
    
    # Plot Price
    for i in range(len(df)):
        color = '#00E676' if df['close'].iloc[i] >= df['open'].iloc[i] else '#FF3D57'
        # Simple Candlestick simulation
        ax.plot([i, i], [df['low'].iloc[i], df['high'].iloc[i]], color='black', linewidth=0.5)
        ax.plot([i-0.4, i+0.4], [df['open'].iloc[i], df['open'].iloc[i]], color=color, linewidth=1)
        ax.plot([i-0.4, i+0.4], [df['close'].iloc[i], df['close'].iloc[i]], color=color, linewidth=1)
        
    # 1. Plot SMA Area
    # Create filled polygon
    x = np.arange(len(df))
    ax.plot(x, df['sma_short'], color='#888888', linewidth=1)
    ax.plot(x, df['sma_long'], color='#888888', linewidth=1)
    ax.fill_between(x, df['sma_short'], df['sma_long'], 
                   where=(df['trend'] == 1), color=engine.cfg.sma_bull_fill, alpha=0.2)
    ax.fill_between(x, df['sma_short'], df['sma_long'], 
                   where=(df['trend'] == -1), color=engine.cfg.sma_bear_fill, alpha=0.2)

    # 2. Plot Order Blocks
    for ob in engine.ob_zones:
        if ob['status'] == 'BROKEN': continue # Only show active if preferred, or distinct style
        
        w = ob['x_end'] - ob['x_start']
        rect = patches.Rectangle((ob['x_start'], ob['y_btm']), w, ob['y_top'] - ob['y_btm'],
                               facecolor=ob['color'], edgecolor=ob['color'], alpha=0.4, linewidth=1)
        ax.add_patch(rect)
        
        # Label
        lbl = "Bull OB" if ob['type'] == 'BULL' else "Bear OB"
        ax.text(ob['x_start'], ob['y_top'], lbl, color='white', fontsize=8, 
                bbox=dict(facecolor='black', alpha=0.7, pad=2))

    # 3. Plot Killzone Pivots
    for kz in engine.kz_pivots:
        # Extend line to end of chart or until broken
        # Here we just draw from start to end of session for visual clarity
        ax.plot([kz['x_start'], len(df)], [kz['high'], kz['high']], 
                color=kz['color'], linestyle='--', linewidth=0.8, alpha=0.7)
        ax.plot([kz['x_start'], len(df)], [kz['low'], kz['low']], 
                color=kz['color'], linestyle='--', linewidth=0.8, alpha=0.7)
        
        # Draw Session Box
        h = kz['high'] - kz['low']
        rect = patches.Rectangle((kz['x_start'], kz['low']), kz['x_end'] - kz['x_start'], h,
                               facecolor=kz['color'], edgecolor='none', alpha=0.1)
        ax.add_patch(rect)
        
        # Text
        ax.text(kz['x_start'], kz['high'], kz['name'], color=kz['color'], fontsize=9, va='bottom')

    # 4. Table (Top Right)
    # Trend
    trend_txt = "BUY" if df['trend'].iloc[-1] == 1 else "SELL"
    trend_col = engine.cfg.sma_bull_fill if df['trend'].iloc[-1] == 1 else engine.cfg.sma_bear_fill
    
    info_text = (
        f"RIZA ULTRA PUSU\n"
        f"------------------\n"
        f"Trend : {trend_txt}\n"
        f"Order Blocks: {len(engine.ob_zones)}\n"
        f"Killzone Pivots: {len(engine.kz_pivots)}"
    )
    
    props = dict(boxstyle='round', facecolor='#1e1e1e', alpha=0.9, edgecolor='gray')
    ax.text(0.98, 0.98, info_text, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', horizontalalignment='right', 
            bbox=props, color='white', family='monospace')

    # 5. Timer (Next Session)
    # Simple logic for display: Current Hour
    curr_hour = df['hour'].iloc[-1]
    ax.text(0.02, 0.02, f"Current Hour: {curr_hour}:00 (Server Time)", transform=ax.transAxes, 
            fontsize=10, color='white', verticalalignment='bottom')

    ax.set_title(f"RizA Ultra Pusu - {df.index[0]} to {df.index[-1]}")
    ax.grid(True, color='gray', linestyle=':', linewidth=0.5, alpha=0.3)
    plt.show()

# ═══════════════════════════════════════════════════════════════
# USAGE EXAMPLE
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Generate Data
    np.random.seed(42)
    length = 500
    dates = pd.date_range(start='2023-01-01 08:00:00', periods=length, freq='H')
    
    price = 1.1000
    closes = []
    for _ in range(length):
        change = np.random.normal(0, 0.0005)
        price += change
        closes.append(price)
        
    close = np.array(closes)
    high = close + np.random.uniform(0, 0.0005, length)
    low = close - np.random.uniform(0, 0.0005, length)
    open_ = close + np.random.uniform(-0.0002, 0.0002, length)
    
    df = pd.DataFrame({
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': np.random.randint(100, 1000, length)
    }, index=dates)
    
    # Run Analysis
    cfg = Config()
    engine = RizAEngine(df, cfg)
    engine.analyze()
    
    # Plot
    plot_riza(df, engine)
