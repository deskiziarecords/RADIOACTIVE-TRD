#!/usr/bin/env python3
"""
sent-full.py — Unified Real-Time Trading + Pattern Intelligence System

Components:
- Tick → Candle aggregation
- Numba pattern encoding
- Pattern sequence tracking
- Entropy / structure metrics
- RealTimeSentinel (signals)
- WebSocket streaming
"""

import asyncio
import json
import logging
from collections import deque, Counter
from dataclasses import dataclass
from typing import Dict, List
from math import log2

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from numba import njit

# ─────────────────────────────────────────────────────────────
# FAST PATTERN ENCODER (NUMBA)
# ─────────────────────────────────────────────────────────────

@njit
def encode_candle(open_p: float, high: float, low: float, close: float) -> int:
    """Encodes a candle into a pattern index."""
    body = close - open_p
    body_size = abs(body)
    range_ = high - low

    if body_size <= 0.00005 or (body_size / (range_ + 1e-10)) < 0.1:
        return 0

    upper_wick = high - max(open_p, close)
    lower_wick = min(open_p, close) - low

    if upper_wick > 0.00015 and upper_wick > body_size * 1.5:
        return 5
    if lower_wick > 0.00015 and lower_wick > body_size * 1.5:
        return 6

    if body > 0:
        return 1 if body_size > 0.0001 else 3
    elif body < 0:
        return 2 if body_size > 0.0001 else 4

    return 0

SYMBOL_MAP = {0: 'I', 1: 'B', 2: 'X', 3: 'U', 4: 'D', 5: 'W', 6: 'w'}

# ─────────────────────────────────────────────────────────────
# SENTINEL (FAST SIGNAL CORE)
# ─────────────────────────────────────────────────────────────

@dataclass
class Signal:
    direction: str
    confidence: float

class RealTimeSentinel:
    def __init__(self):
        self.highs = deque(maxlen=20)
        self.lows = deque(maxlen=20)

    def update(self, candle: Dict) -> Signal:
        """Updates the sentinel with a new candle and returns a signal."""
        self.highs.append(candle["high"])
        self.lows.append(candle["low"])

        h = max(self.highs)
        l = min(self.lows)
        pos = (candle["close"] - l) / max(h - l, 1e-10)

        if pos > 0.8:
            return Signal("SHORT", 0.7)
        elif pos < 0.2:
            return Signal("LONG", 0.7)
        return Signal("NEUTRAL", 0.3)

# ─────────────────────────────────────────────────────────────
# AGGREGATOR
# ─────────────────────────────────────────────────────────────

class MinuteAggregator:
    def __init__(self, callback):
        self.callback = callback
        self.current = None

    def update(self, tick: Dict):
        """Aggregates ticks into minute candles."""
        bucket = tick["timestamp"] // 60

        if self.current is None:
            self.current = {**tick, "bucket": bucket}
            return

        if bucket != self.current["bucket"]:
            self.callback(self.current)
            self.current = {**tick, "bucket": bucket}
        else:
            self.current["high"] = max(self.current["high"], tick["high"])
            self.current["low"] = min(self.current["low"], tick["low"])
            self.current["close"] = tick["close"]

# ─────────────────────────────────────────────────────────────
# MAIN STREAMER
# ─────────────────────────────────────────────────────────────

class PatternStreamer:
    def __init__(self):
        self.connections: List[WebSocket] = []
        self.patterns = deque(maxlen=1000)
        self.sentinel = RealTimeSentinel()
        self.aggregator = MinuteAggregator(self.on_candle)

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    async def disconnect(self, ws: WebSocket):
        self.connections.remove(ws)

    def on_candle(self, candle: Dict):
        """Processes a candle and broadcasts updates."""
        idx = encode_candle(candle["open"], candle["high"], candle["low"], candle["close"])
        symbol = SYMBOL_MAP[idx]
        self.patterns.append(symbol)
        signal = self.sentinel.update(candle)

        event = {
            "type": "update",
            "pattern": symbol,
            "sequence": ''.join(self.patterns)[-50:],
            "metrics": self.metrics(),
            "signal": {"direction": signal.direction, "confidence": signal.confidence}
        }
        asyncio.create_task(self.broadcast(event))

    async def broadcast(self, msg: Dict):
        """Broadcasts a message to all connected clients."""
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)

    def metrics(self) -> Dict:
        """Calculates entropy and mechanical metrics."""
        recent = list(self.patterns)[-60:]
        if not recent:
            return {}

        dist = Counter(recent)
        total = len(recent)
        entropy = -sum((c/total)*log2(c/total) for c in dist.values())

        return {
            "entropy": round(entropy, 3),
            "mechanical": round(1 - dist.get('I', 0)/total, 3),
            "last_20": ''.join(recent)[-20:]
        }

# ─────────────────────────────────────────────────────────────
# FASTAPI SERVER
# ─────────────────────────────────────────────────────────────

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
streamer = PatternStreamer()

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """WebSocket endpoint for real-time tick data."""
    await streamer.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            tick = json.loads(data)
            if not all(key in tick for key in ["open", "high", "low", "close", "timestamp"]):
                raise ValueError("Invalid tick data")
            streamer.aggregator.update(tick)
    except (WebSocketDisconnect, json.JSONDecodeError, ValueError) as e:
        logging.error(f"WebSocket error: {e}")
    finally:
        await streamer.disconnect(ws)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
