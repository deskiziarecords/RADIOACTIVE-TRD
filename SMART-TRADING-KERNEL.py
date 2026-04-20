#!/usr/bin/env python3
"""
Smart Trading Engine - Python Port (PATCHED)
Converted from C source
"""

import argparse
import csv
import json
import logging
import math
import os
import pickle
import random
import signal
import struct
import sys
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple

# =============================================================================
# CONSTANTS & DEFINITIONS (from smart.h)
# =============================================================================

SEQ_LEN = 20
SYMBOLS = 7
DIM = SEQ_LEN * SYMBOLS  # 140
MEMORY_CAP = 10000
KNN_K = 5

# Defaults (can be overridden by config.json)
DEFAULT_CONFIG = {
    "asset": "USD_CAD",
    "api_key": "YOUR_OANDA_API_KEY_HERE",
    "account_id": "YOUR_ACCOUNT_ID_HERE",
    "practice": True,
    "paper": True,
    "capital": 10000.0,
    "risk_pct": 1.0,
    "entropy_thresh": 0.60,
    "min_confidence": 0.60,
    "min_bias": 0.10,
    "max_energy": 0.50,
    "curl_thresh": 0.80,
    "min_delta": 500.0,
    "max_daily_loss": 5.0,
    "log_level": 1,  # 0=QUIET, 1=INFO, 2=DEBUG
    "log_path": "logs/smart.log",
    "asset_bias": 0  # 0=both, 1=long-only, -1=short-only
}

# Symbol Enum
class Symbol(IntEnum):
    SYM_B = 0  # Bull Queen
    SYM_I = 1  # Bear Queen
    SYM_W = 2  # Upper Wick
    SYM_w = 3  # Lower Wick
    SYM_U = 4  # Weak Bull
    SYM_D = 5  # Weak Bear
    SYM_X = 6  # Neutral

SYM_CHAR = ['B', 'I', 'W', 'w', 'U', 'D', 'X']
SYM_VALUE = [900, -900, 500, -500, 330, -320, 100]
SYM_SL_PCT = [0.008, 0.008, 0.006, 0.006, 0.010, 0.010, 0.005]

# Position Tables (7 symbols x 64 cells)
POSITION_TABLES = [
    # B
    [-20,-15,-10,-5,-5,-10,-15,-20,-10,0,0,5,5,0,0,-10,
     -10,5,10,15,15,10,5,-10,-5,0,15,20,20,15,0,-5,
     -5,5,15,25,25,15,5,-5,-10,0,10,20,20,10,0,-10,
     10,20,30,40,40,30,20,10,50,50,55,60,60,55,50,50],
    # I
    [-5,-5,-5,-6,-6,-5,-5,-5,-1,-2,-3,-4,-4,-3,-2,-1,
     1,0,-1,-1,-1,-1,0,1,0,0,-1,-2,-2,-1,0,0,
     0,0,-1,-2,-2,-1,0,0,1,0,-1,-1,-1,-1,0,1,
     2,1,1,0,0,1,1,2,2,1,1,0,0,1,1,2],
    # W
    [0,0,0,0,0,0,0,0,-1,0,0,1,1,0,0,-1,-1,0,1,2,2,1,0,-1,
     0,0,1,2,2,1,0,0,0,0,1,2,2,1,0,0,-1,0,1,1,1,1,0,-1,
     0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    # w
    [0,0,0,0,0,0,0,0,1,0,-1,-1,-1,-1,0,1,0,0,-1,-2,-2,-1,0,0,
     0,0,-1,-2,-2,-1,0,0,0,0,-1,-2,-2,-1,0,0,1,0,-1,-1,-1,-1,0,1,
     0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    # U
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,
     0,0,1,2,2,1,0,0,0,0,1,2,2,1,0,0,1,1,2,3,3,2,1,1,
     4,4,4,5,5,4,4,4,0,0,0,0,0,0,0,0],
    # D
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,-1,-1,0,0,0,
     0,0,-1,-2,-2,-1,0,0,0,0,-1,-2,-2,-1,0,0,-1,-1,-2,-3,-3,-2,-1,-1,
     -4,-4,-4,-5,-5,-4,-4,-4,0,0,0,0,0,0,0,0],
    # X
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
     0,0,0,1,1,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,
     0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
]

EMBEDDING = [
    [ 1.0,  0.8,  0.3,  0.0], # B
    [-1.0, -0.8, -0.3,  0.0], # I
    [ 0.6,  0.2, -0.8,  0.5], # W
    [-0.6, -0.2,  0.8, -0.5], # w
    [ 0.4,  0.3,  0.1,  0.2], # U
    [-0.4, -0.3, -0.1, -0.2], # D
    [ 0.0,  0.0,  0.0,  0.0]  # X
]
EDIM = 4

# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    timestamp_ms: int = 0
    volume: int = 0
    spread: float = 0.0

@dataclass
class MemoryEntry:
    seq: List[int]
    pnl: float

@dataclass
class Config:
    asset: str
    api_key: str
    account_id: str
    practice: bool
    paper: bool
    capital: float
    risk_pct: float
    entropy_thresh: float
    min_confidence: float
    min_bias: float
    max_energy: float
    curl_thresh: float
    min_delta: float
    max_daily_loss_pct: float
    log_level: int
    log_path: str
    asset_bias: int

@dataclass
class Signal:
    confidence: float
    bias: float
    energy: float
    curl: float
    entropy: float
    delta: float
    lot_size: float
    valid: bool
    direction: int
    block_gate: int # 0=none, 1-7=gate#

@dataclass
class OpenPosition:
    timestamp_ms: int
    direction: int
    entry_price: float
    sl_price: float
    tp_price: float
    lot_size: float
    signal: Signal
    entry_seq: List[int]

# =============================================================================
# UTILITIES: LOGGING & CONFIG
# =============================================================================

def setup_logging(cfg: Config):
    log_dir = os.path.dirname(cfg.log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    level = logging.WARNING
    if cfg.log_level >= 1: level = logging.INFO
    if cfg.log_level >= 2: level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format='[%(asctime)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(cfg.log_path),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def load_config(path: str) -> Config:
    if not os.path.exists(path):
        logging.warning(f"Config file {path} not found. Using defaults.")
        c = DEFAULT_CONFIG.copy()
        return Config(**c)

    with open(path, 'r') as f:
        data = json.load(f)

    # Merge with defaults
    cfg = DEFAULT_CONFIG.copy()
    cfg.update(data)

    # Map specific keys if names differ slightly
    if "max_daily_loss" in data and "max_daily_loss_pct" not in data:
        cfg["max_daily_loss_pct"] = data["max_daily_loss"]

    return Config(**cfg)


# =============================================================================
# PATTERN RECOGNITION (pattern.c)
# =============================================================================

class SeqBuffer:
    def __init__(self):
        self.seq = [Symbol.SYM_X] * SEQ_LEN
        self.ptr = 0
        self.count = 0

    def push(self, s: Symbol):
        self.seq[self.ptr % SEQ_LEN] = s
        self.ptr += 1
        if self.count < SEQ_LEN:
            self.count += 1

    def read(self) -> List[Symbol]:
        out = [Symbol.SYM_X] * SEQ_LEN
        if self.count < SEQ_LEN:
            pad = SEQ_LEN - self.count
            # Copy the count symbols we have
            start = (self.ptr - self.count + SEQ_LEN) % SEQ_LEN
            for i in range(self.count):
                out[pad + i] = self.seq[(start + i) % SEQ_LEN]
        else:
            # Full buffer
            start = self.ptr % SEQ_LEN
            for i in range(SEQ_LEN):
                out[i] = self.seq[(start + i) % SEQ_LEN]
        return out

def seq_to_str(seq: List[Symbol]) -> str:
    return "".join([SYM_CHAR[int(s)] for s in seq])

def encode_candle(c: Candle) -> Symbol:
    body = abs(c.close - c.open)
    range_val = c.high - c.low

    if range_val < 1e-9: return Symbol.SYM_X

    ratio = body / range_val
    upper = c.high - max(c.open, c.close)
    lower = min(c.open, c.close) - c.low

    # Wick overrides
    if upper > range_val * 0.6: return Symbol.SYM_W
    if lower > range_val * 0.6: return Symbol.SYM_w

    # Doji
    if ratio < 0.10: return Symbol.SYM_X

    # Directional
    if c.close > c.open:
        return Symbol.SYM_B if ratio > 0.6 else Symbol.SYM_U
    else:
        return Symbol.SYM_I if ratio > 0.6 else Symbol.SYM_D

# =============================================================================
# EVALUATION (eval.c)
# =============================================================================

def evaluate_sequence(seq: List[Symbol]) -> float:
    material = 0.0
    position = 0.0

    for i in range(SEQ_LEN):
        s = int(seq[i])
        w = (i + 1.0) / SEQ_LEN
        material += SYM_VALUE[s] * w

        tbl_idx = int(i * 63.0 / (SEQ_LEN - 1))
        if tbl_idx > 63: tbl_idx = 63
        position += POSITION_TABLES[s][tbl_idx]

    return material + position

def predict_next(seq: List[Symbol]) -> Tuple[float, Symbol]:
    base = evaluate_sequence(seq)
    best_abs = -1.0
    best_delt = 0.0
    best_sym = Symbol.SYM_X

    candidate = [Symbol.SYM_X] * SEQ_LEN

    for s_val in range(SYMBOLS):
        # Shift
        for i in range(SEQ_LEN - 1):
            candidate[i] = seq[i+1]
        candidate[SEQ_LEN - 1] = Symbol(s_val)

        delta = evaluate_sequence(candidate) - base
        absd = abs(delta)

        if absd > best_abs:
            best_abs = absd
            best_delt = delta
            best_sym = Symbol(s_val)

    return best_delt, best_sym

# =============================================================================
# GEOMETRY & ENTROPY (geometry.c, entropy.c)
# =============================================================================

def calc_entropy(seq: List[Symbol]) -> float:
    counts = [0] * SYMBOLS
    for s in seq:
        counts[int(s)] += 1

    MAX_H = 2.80735 # log2(7)
    H = 0.0
    for c in counts:
        if c == 0: continue
        p = c / SEQ_LEN
        H -= p * math.log2(p)
    return H / MAX_H

def calc_energy(seq: List[Symbol]) -> float:
    diff = [[0.0]*EDIM for _ in range(SEQ_LEN - 1)]
    energy = 0.0

    # First diff
    for i in range(SEQ_LEN - 1):
        for d in range(EDIM):
            d_val = EMBEDDING[int(seq[i+1])][d] - EMBEDDING[int(seq[i])][d]
            diff[i][d] = d_val
            energy += d_val * d_val

    # Second diff (curvature)
    for i in range(SEQ_LEN - 2):
        for d in range(EDIM):
            curv = diff[i+1][d] - diff[i][d]
            energy += curv * curv

    max_e = ((SEQ_LEN - 1) + (SEQ_LEN - 2)) * EDIM * 4.0
    return energy / max_e

def calc_divergence(seq: List[Symbol]) -> float:
    older = sum(SYM_VALUE[int(s)] for s in seq[:10])
    recent = sum(SYM_VALUE[int(s)] for s in seq[10:])
    return (recent - older) / (10.0 * 900.0)

def calc_curl(seq: List[Symbol]) -> float:
    BULLISH = [1, 0, 1, 0, 1, 0, 0] # B, I, W, w, U, D, X
    flips = 0
    for i in range(1, SEQ_LEN):
        a = BULLISH[int(seq[i-1])]
        b = BULLISH[int(seq[i])]
        na = (int(seq[i-1]) != Symbol.SYM_X)
        nb = (int(seq[i]) != Symbol.SYM_X)
        if na and nb and (a != b):
            flips += 1
    return flips / (SEQ_LEN - 1)

# =============================================================================
# MEMORY (memory.c) - PATCHED
# =============================================================================

class MemoryStore:
    def __init__(self):
        self.db: List[MemoryEntry] = []
        self.count = 0

    def init(self):
        self.db = []
        self.count = 0

    def store(self, seq: List[Symbol], pnl: float):
        entry = MemoryEntry(seq=list(seq), pnl=pnl)
        self.db.append(entry)
        if len(self.db) > MEMORY_CAP:
            self.db.pop(0)
        self.count = len(self.db)

    def query_bias(self, seq: List[Symbol]) -> float:
        if self.count == 0: 
            return 0.0

        # One-hot encoding
        query = [0.0] * DIM
        for i in range(SEQ_LEN):
            query[i * SYMBOLS + int(seq[i])] = 1.0

        # KNN (Brute force) - PATCHED: Fixed insertion logic
        top_dist = [float('inf')] * KNN_K
        top_idx = [-1] * KNN_K
        found = 0

        for i, entry in enumerate(self.db):
            # One-hot encode memory entry
            vec = [0.0] * DIM
            for j in range(SEQ_LEN):
                vec[j * SYMBOLS + int(entry.seq[j])] = 1.0

            # L2 squared
            d = 0.0
            for k in range(DIM):
                diff = query[k] - vec[k]
                d += diff * diff

            # Insert if better than worst in current top-k or if we haven't filled K yet
            if found < KNN_K or d < top_dist[KNN_K - 1]:
                idx = min(found, KNN_K - 1)
                top_dist[idx] = d
                top_idx[idx] = i

                # Bubble up to maintain sorted order
                for j in range(idx, 0, -1):
                    if top_dist[j] < top_dist[j-1]:
                        top_dist[j], top_dist[j-1] = top_dist[j-1], top_dist[j]
                        top_idx[j], top_idx[j-1] = top_idx[j-1], top_idx[j]
                    else:
                        break
                if found < KNN_K:
                    found += 1

        if found == 0: 
            return 0.0
        return sum(self.db[top_idx[i]].pnl for i in range(found)) / found

    def save(self, path: str):
        try:
            with open(path, 'wb') as f:
                pickle.dump(self.db, f)
        except Exception as e:
            logging.error(f"Failed to save memory: {e}")

    def load(self, path: str):
        if not os.path.exists(path): 
            return
        try:
            with open(path, 'rb') as f:
                self.db = pickle.load(f)
                self.count = len(self.db)
        except Exception as e:
            logging.error(f"Failed to load memory: {e}")

# =============================================================================
# RISK MANAGEMENT (risk.c) - PATCHED
# =============================================================================

def evaluate_signal(seq: List[Symbol], cfg: Config, mem: MemoryStore) -> Signal:
    sig = Signal(
        confidence=0, bias=0, energy=0, curl=0, entropy=0, delta=0,
        lot_size=0, valid=False, direction=0, block_gate=0
    )

    # Lambda 1: Entropy
    sig.entropy = calc_entropy(seq)
    if sig.entropy >= cfg.entropy_thresh:
        sig.valid = False
        sig.block_gate = 1
        return sig

    # Lambda 2: Memory Bias
    sig.bias = mem.query_bias(seq)
    if sig.bias <= cfg.min_bias:
        sig.valid = False
        sig.block_gate = 2
        return sig

    # Prediction
    sig.delta, _ = predict_next(seq)
    sig.confidence = min(1.0, abs(sig.delta) / 2000.0)
    sig.direction = 1 if sig.delta > 0 else -1

    # Lambda 3: Confidence
    if sig.confidence < cfg.min_confidence or abs(sig.delta) < cfg.min_delta:
        sig.valid = False
        sig.block_gate = 3
        return sig

    # Lambda 4: Geometry
    sig.energy = calc_energy(seq)
    if sig.energy >= cfg.max_energy:
        sig.valid = False
        sig.block_gate = 4
        return sig
    sig.curl = calc_curl(seq)
    if sig.curl > cfg.curl_thresh:
        sig.valid = False
        sig.block_gate = 4
        return sig

    # Lambda 5: Asset Bias
    if cfg.asset_bias != 0 and sig.direction != cfg.asset_bias:
        sig.valid = False
        sig.block_gate = 5
        return sig

    sig.valid = True
    return sig

def kelly_size(win_rate: float, avg_win: float, avg_loss: float, 
               conf: float, stability: float, cfg: Config) -> float:
    if avg_win < 1e-9: 
        return cfg.risk_pct * 0.005 # MIN_POS_PCT approximate

    loss_rate = 1.0 - win_rate
    base = (win_rate * avg_win - loss_rate * avg_loss) / avg_win

    size = (base * 0.5) * conf * (1.0 - stability * 0.3)

    lo = cfg.risk_pct * 0.005
    hi = cfg.risk_pct * 0.02
    return max(lo, min(hi, size))

# =============================================================================
# BROKER (Oanda Stub)
# =============================================================================

class OandaBroker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.synth_price = 1.34500
        self.synth_ts = int(time.time() * 1000)
        self.connected = False

    def connect(self):
        self.connected = True
        logging.info("[OANDA] PAPER mode - synthetic price feed")
        return True

    def fetch_candle(self) -> Optional[Candle]:
        if not self.connected: 
            return None

        drift = (random.random() - 0.50) * 0.0010
        hi_ext = random.random() * 0.0015
        lo_ext = random.random() * 0.0015

        o = self.synth_price
        c = o * (1.0 + drift)
        h = max(o, c) * (1.0 + hi_ext)
        l = min(o, c) * (1.0 - lo_ext)

        candle = Candle(
            open=o, high=h, low=l, close=c,
            volume=int(random.random() * 5000 + 500),
            spread=0.0002,
            timestamp_ms=self.synth_ts
        )
        self.synth_price = c
        self.synth_ts += 60000
        return candle

    def get_price(self) -> Tuple[float, float]:
        return (self.synth_price - 0.0001, self.synth_price + 0.0001)

    def place_order(self, sig: Signal, entry_price: float) -> Optional[OpenPosition]:
        sl_pct = SYM_SL_PCT[0]
        sl_dist = entry_price * sl_pct
        tp_dist = sl_dist * 2.0

        pos = OpenPosition(
            timestamp_ms=int(time.time()*1000),
            direction=sig.direction,
            entry_price=entry_price,
            sl_price=0.0, tp_price=0.0,
            lot_size=sig.lot_size,
            signal=sig,
            entry_seq=[]
        )

        if sig.direction == 1:
            pos.sl_price = entry_price - sl_dist
            pos.tp_price = entry_price + tp_dist
        else:
            pos.sl_price = entry_price + sl_dist
            pos.tp_price = entry_price - tp_dist

        logging.info(f"[ORDER] {'LONG' if sig.direction==1 else 'SHORT'} {sig.lot_size:.2f} lots @ {entry_price:.5f}")
        return pos

# =============================================================================
# BACKTESTER (backtest.c) - PATCHED
# =============================================================================

def run_backtest(csv_path: str, cfg: Config, mem: MemoryStore):
    sb = SeqBuffer()
    seq = [Symbol.SYM_X] * SEQ_LEN

    total_trades = 0
    wins, losses = 0, 0
    total_pnl = 0.0
    max_dd = 0.0
    peak_pnl = 0.0
    win_sum, loss_sum = 0.0, 0.0

    in_trade = False
    cur_pos = None

    logging.info(f"[BACKTEST] Starting replay: {csv_path}")

    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Parse CSV
                try:
                    c = Candle(
                        timestamp_ms=int(row['timestamp_ms']),
                        open=float(row['open']),
                        high=float(row['high']),
                        low=float(row['low']),
                        close=float(row['close']),
                        volume=int(row.get('volume', 0))
                    )
                except (ValueError, KeyError):
                    continue

                # Check Position
                if in_trade and cur_pos:
                    closed = False
                    pnl = 0.0
                    reason = "tp"

                    if cur_pos.direction == 1: # LONG
                        if c.low <= cur_pos.sl_price:
                            pnl = (cur_pos.sl_price - cur_pos.entry_price) / 0.0001 * cur_pos.lot_size
                            reason = "sl"
                            closed = True
                        elif c.high >= cur_pos.tp_price:
                            pnl = (cur_pos.tp_price - cur_pos.entry_price) / 0.0001 * cur_pos.lot_size
                            closed = True
                    else: # SHORT
                        if c.high >= cur_pos.sl_price:
                            pnl = (cur_pos.entry_price - cur_pos.sl_price) / 0.0001 * cur_pos.lot_size
                            reason = "sl"
                            closed = True
                        elif c.low <= cur_pos.tp_price:
                            pnl = (cur_pos.entry_price - cur_pos.tp_price) / 0.0001 * cur_pos.lot_size
                            closed = True

                    if closed:
                        total_pnl += pnl
                        if pnl > 0: 
                            wins += 1
                            win_sum += pnl
                        else: 
                            losses += 1
                            loss_sum += -pnl

                        if total_pnl > peak_pnl: 
                            peak_pnl = total_pnl
                        dd = peak_pnl - total_pnl
                        if dd > max_dd: 
                            max_dd = dd

                        mem.store(cur_pos.entry_seq, pnl)
                        logging.debug(f"[BT] CLOSE {'LONG' if cur_pos.direction==1 else 'SHORT'} pnl={pnl:.1f} pips reason={reason}")
                        in_trade = False

                # Encode
                sym = encode_candle(c)
                sb.push(sym)
                seq = sb.read()

                if in_trade: 
                    continue

                # Signal
                sig = evaluate_signal(seq, cfg, mem)
                if not sig.valid:
                    continue

                # Sizing
                wr = (wins / total_trades) if total_trades > 0 else 0.55
                aw = (win_sum / wins) if wins > 0 else 12.0
                al = (loss_sum / losses) if losses > 0 else 8.0
                sig.lot_size = kelly_size(wr, aw, al, sig.confidence, sig.energy, cfg)

                # Open
                entry = (c.open + c.close) / 2.0
                sl_d = entry * SYM_SL_PCT[0]
                tp_d = sl_d * 2.0

                cur_pos = OpenPosition(
                    timestamp_ms=c.timestamp_ms,
                    direction=sig.direction,
                    entry_price=entry,
                    sl_price=(entry - sl_d) if sig.direction==1 else (entry + sl_d),
                    tp_price=(entry + tp_d) if sig.direction==1 else (entry - tp_d),
                    lot_size=sig.lot_size,
                    signal=sig,
                    entry_seq=list(seq)
                )

                in_trade = True
                total_trades += 1
                logging.debug(f"[BT] OPEN {'LONG' if sig.direction==1 else 'SHORT'} {sig.lot_size:.2f} lots @ {entry:.5f}")

    except FileNotFoundError:
        logging.error(f"[BACKTEST] File not found: {csv_path}")
        return -1

    # Summary
    wr_pct = (100.0 * wins / total_trades) if total_trades > 0 else 0.0
    logging.info("─────────────────────────────────────────")
    logging.info(f"[BACKTEST] Trades: {total_trades} | Wins: {wins} ({wr_pct:.1f}%) | Losses: {losses}")
    logging.info(f"[BACKTEST] Total PnL: {total_pnl:.1f} pips | Max DD: {max_dd:.1f} pips")
    logging.info("─────────────────────────────────────────")

    return total_trades

# =============================================================================
# MAIN - PATCHED
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="SMART-EXE v1.0 Python Port")
    parser.add_argument("--paper", action="store_true", default=True, help="Paper trading (default)")
    parser.add_argument("--live", action="store_true", help="Live trading")
    parser.add_argument("--backtest", type=str, help="Backtest CSV file")
    parser.add_argument("--once", action="store_true", help="Single evaluation")
    parser.add_argument("--sequence", type=str, help="Sequence string for --once")
    parser.add_argument("--config", type=str, default="config.json", help="Config path")
    parser.add_argument("--verbose", action="store_true", help="Debug logs")

    args = parser.parse_args()

    # Load Config - PATCHED: Respect config file unless explicitly overridden
    cfg = load_config(args.config)
    if args.verbose: 
        cfg.log_level = 2
    if args.live: 
        cfg.paper = False
    elif args.paper:
        cfg.paper = True
    # else: respect config file value

    logger = setup_logging(cfg)

    # Init Memory
    mem = MemoryStore()
    mem.init()
    mem.load("memory.bin")

    # Signals - PATCHED: Flush log handlers on shutdown
    def shutdown(signum, frame):
        logging.info("Shutdown requested...")
        mem.save("memory.bin")
        # Flush all handlers to ensure logs are written
        for handler in logging.getLogger(__name__).handlers:
            handler.flush()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # ONCE MODE
    if args.once:
        seq_str = args.sequence if args.sequence else "BBUIBBXIBB"
        sb = SeqBuffer()
        for ch in seq_str:
            mapping = {'B':0, 'I':1, 'W':2, 'w':3, 'U':4, 'D':5, 'X':6}
            if ch in mapping:
                sb.push(Symbol(mapping[ch]))
        seq = sb.read()

        sig = evaluate_signal(seq, cfg, mem)
        print(f"Sequence: {seq_to_str(seq)}")
        print(f"Decision: {'LONG' if sig.valid and sig.direction==1 else 'SHORT' if sig.valid else 'BLOCK'}")
        print(f"Valid: {sig.valid} (Gate {sig.block_gate})")
        print(f"Entropy: {sig.entropy:.3f}")
        print(f"Confidence: {sig.confidence:.3f}")
        print(f"Delta: {sig.delta:.1f}")
        mem.save("memory.bin")
        return

    # BACKTEST MODE
    if args.backtest:
        run_backtest(args.backtest, cfg, mem)
        mem.save("memory.bin")
        return

    # LIVE / PAPER LOOP MODE - PATCHED: Fixed SL/TP logic for SHORT
    broker = OandaBroker(cfg)
    if not broker.connect():
        logging.error("Broker connection failed")
        return

    sb = SeqBuffer()
    seq = [Symbol.SYM_X] * SEQ_LEN

    in_trade = False
    cur_pos = None

    stats = {"wins":0, "losses":0, "pnl":0.0, "win_sum":0.0, "loss_sum":0.0, "trades":0}

    try:
        while True:
            candle = broker.fetch_candle()
            if not candle:
                time.sleep(5)
                continue

            sym = encode_candle(candle)
            sb.push(sym)
            seq = sb.read()

            # Manage Trade
            if in_trade and cur_pos:
                bid, ask = broker.get_price()
                current = bid if cur_pos.direction == 1 else ask

                # PATCHED: Correct SL/TP logic for both directions
                if cur_pos.direction == 1:  # LONG
                    sl_hit = current <= cur_pos.sl_price
                    tp_hit = current >= cur_pos.tp_price
                else:  # SHORT
                    sl_hit = current >= cur_pos.sl_price  # SL is above entry for short
                    tp_hit = current <= cur_pos.tp_price  # TP is below entry for short

                if sl_hit or tp_hit:
                    raw_pnl = (current - cur_pos.entry_price) * cur_pos.direction
                    pnl = raw_pnl / 0.0001

                    mem.store(cur_pos.entry_seq, pnl)
                    logging.info(f"[CLOSE] PnL={pnl:.1f} pips ({'SL' if sl_hit else 'TP'})")

                    stats["pnl"] += pnl
                    stats["trades"] += 1
                    if pnl > 0:
                        stats["wins"] += 1
                        stats["win_sum"] += pnl
                    else:
                        stats["losses"] += 1
                        stats["loss_sum"] += -pnl

                    in_trade = False

            if in_trade:
                time.sleep(1)
                continue

            # Signal
            sig = evaluate_signal(seq, cfg, mem)
            if not sig.valid:
                time.sleep(1)
                continue

            # Size
            wr = (stats["wins"] / stats["trades"]) if stats["trades"] > 0 else 0.55
            aw = (stats["win_sum"] / stats["wins"]) if stats["wins"] > 0 else 12.0
            al = (stats["loss_sum"] / stats["losses"]) if stats["losses"] > 0 else 8.0
            sig.lot_size = kelly_size(wr, aw, al, sig.confidence, sig.energy, cfg)

            # Execute
            entry = candle.close
            cur_pos = broker.place_order(sig, entry)
            if cur_pos:
                cur_pos.entry_seq = list(seq)
                in_trade = True

            time.sleep(1)

    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()
