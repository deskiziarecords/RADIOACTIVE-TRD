// =============================================================================
// SMART-EXE v1.0  –  Rust Port
// Converted from Python (which was ported from C)
// =============================================================================

#![allow(dead_code)]

use std::collections::VecDeque;
use std::fs;
use std::io;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use clap::Parser;
use rand::Rng;
use serde::{Deserialize, Serialize};

// =============================================================================
// CONSTANTS
// =============================================================================

const SEQ_LEN: usize = 20;
const SYMBOLS: usize = 7;
const DIM: usize = SEQ_LEN * SYMBOLS; // 140
const MEMORY_CAP: usize = 10_000;
const KNN_K: usize = 5;

const SYM_CHAR: [char; SYMBOLS] = ['B', 'I', 'W', 'w', 'U', 'D', 'X'];
const SYM_VALUE: [f64; SYMBOLS] = [900.0, -900.0, 500.0, -500.0, 330.0, -320.0, 100.0];
const SYM_SL_PCT: [f64; SYMBOLS] = [0.008, 0.008, 0.006, 0.006, 0.010, 0.010, 0.005];
const EDIM: usize = 4;

#[rustfmt::skip]
const EMBEDDING: [[f64; EDIM]; SYMBOLS] = [
    [ 1.0,  0.8,  0.3,  0.0],
    [-1.0, -0.8, -0.3,  0.0],
    [ 0.6,  0.2, -0.8,  0.5],
    [-0.6, -0.2,  0.8, -0.5],
    [ 0.4,  0.3,  0.1,  0.2],
    [-0.4, -0.3, -0.1, -0.2],
    [ 0.0,  0.0,  0.0,  0.0],
];

#[rustfmt::skip]
const POSITION_TABLES: [[i32; 64]; SYMBOLS] = [
    [-20,-15,-10,-5,-5,-10,-15,-20,-10,0,0,5,5,0,0,-10,
     -10,5,10,15,15,10,5,-10,-5,0,15,20,20,15,0,-5,
     -5,5,15,25,25,15,5,-5,-10,0,10,20,20,10,0,-10,
     10,20,30,40,40,30,20,10,50,50,55,60,60,55,50,50],
    [-5,-5,-5,-6,-6,-5,-5,-5,-1,-2,-3,-4,-4,-3,-2,-1,
     1,0,-1,-1,-1,-1,0,1,0,0,-1,-2,-2,-1,0,0,
     0,0,-1,-2,-2,-1,0,0,1,0,-1,-1,-1,-1,0,1,
     2,1,1,0,0,1,1,2,2,1,1,0,0,1,1,2],
    [0,0,0,0,0,0,0,0,-1,0,0,1,1,0,0,-1,-1,0,1,2,2,1,0,-1,
     0,0,1,2,2,1,0,0,0,0,1,2,2,1,0,0,-1,0,1,1,1,1,0,-1,
     0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,1,0,-1,-1,-1,-1,0,1,0,0,-1,-2,-2,-1,0,0,
     0,0,-1,-2,-2,-1,0,0,0,0,-1,-2,-2,-1,0,0,1,0,-1,-1,-1,-1,0,1,
     0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,
     0,0,1,2,2,1,0,0,0,0,1,2,2,1,0,0,1,1,2,3,3,2,1,1,
     4,4,4,5,5,4,4,4,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,-1,-1,0,0,0,
     0,0,-1,-2,-2,-1,0,0,0,0,-1,-2,-2,-1,0,0,-1,-1,-2,-3,-3,-2,-1,-1,
     -4,-4,-4,-5,-5,-4,-4,-4,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
     0,0,0,1,1,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,
     0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
];

// =============================================================================
// SYMBOL ENUM
// =============================================================================

/// 7-symbol price-action alphabet. 'w' (lower wick) becomes Wl here
/// because lowercase idents are not valid Rust enum variants.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[repr(u8)]
pub enum Symbol {
    B  = 0,  // Bull Queen
    I  = 1,  // Bear Queen
    W  = 2,  // Upper Wick
    Wl = 3,  // Lower Wick  (Python: 'w')
    U  = 4,  // Weak Bull
    D  = 5,  // Weak Bear
    X  = 6,  // Neutral
}

impl Symbol {
    pub fn from_u8(v: u8) -> Option<Self> {
        match v {
            0 => Some(Self::B),
            1 => Some(Self::I),
            2 => Some(Self::W),
            3 => Some(Self::Wl),
            4 => Some(Self::U),
            5 => Some(Self::D),
            6 => Some(Self::X),
            _ => None,
        }
    }
    pub fn as_usize(self) -> usize { self as usize }
    pub fn as_char(self) -> char   { SYM_CHAR[self as usize] }

    pub fn from_char(c: char) -> Option<Self> {
        match c {
            'B' => Some(Self::B),
            'I' => Some(Self::I),
            'W' => Some(Self::W),
            'w' => Some(Self::Wl),
            'U' => Some(Self::U),
            'D' => Some(Self::D),
            'X' => Some(Self::X),
            _   => None,
        }
    }
}

impl Default for Symbol { fn default() -> Self { Self::X } }

// =============================================================================
// DATA STRUCTURES
// =============================================================================

#[derive(Debug, Clone)]
pub struct Candle {
    pub open: f64, pub high: f64, pub low: f64, pub close: f64,
    pub timestamp_ms: i64, pub volume: u64, pub spread: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryEntry {
    pub seq: Vec<Symbol>,
    pub pnl: f64,
}

// =============================================================================
// CONFIG
// =============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfigFile {
    #[serde(default = "default_asset")]          pub asset: String,
    #[serde(default = "default_api_key")]        pub api_key: String,
    #[serde(default = "default_account_id")]     pub account_id: String,
    #[serde(default = "default_true")]           pub practice: bool,
    #[serde(default = "default_true")]           pub paper: bool,
    #[serde(default = "default_capital")]        pub capital: f64,
    #[serde(default = "default_risk_pct")]       pub risk_pct: f64,
    #[serde(default = "default_entropy_thresh")] pub entropy_thresh: f64,
    #[serde(default = "default_min_confidence")] pub min_confidence: f64,
    #[serde(default = "default_min_bias")]       pub min_bias: f64,
    #[serde(default = "default_max_energy")]     pub max_energy: f64,
    #[serde(default = "default_curl_thresh")]    pub curl_thresh: f64,
    #[serde(default = "default_min_delta")]      pub min_delta: f64,
    #[serde(default = "default_max_daily_loss")] pub max_daily_loss: f64,
    #[serde(default = "default_log_level")]      pub log_level: u8,
    #[serde(default = "default_log_path")]       pub log_path: String,
    #[serde(default)]                            pub asset_bias: i8,
}

fn default_asset()          -> String { "USD_CAD".into() }
fn default_api_key()        -> String { "YOUR_OANDA_API_KEY_HERE".into() }
fn default_account_id()     -> String { "YOUR_ACCOUNT_ID_HERE".into() }
fn default_true()           -> bool   { true }
fn default_capital()        -> f64    { 10_000.0 }
fn default_risk_pct()       -> f64    { 1.0 }
fn default_entropy_thresh() -> f64    { 0.60 }
fn default_min_confidence() -> f64    { 0.60 }
fn default_min_bias()       -> f64    { 0.10 }
fn default_max_energy()     -> f64    { 0.50 }
fn default_curl_thresh()    -> f64    { 0.80 }
fn default_min_delta()      -> f64    { 500.0 }
fn default_max_daily_loss() -> f64    { 5.0 }
fn default_log_level()      -> u8     { 1 }
fn default_log_path()       -> String { "logs/smart.log".into() }

impl Default for ConfigFile {
    fn default() -> Self { serde_json::from_str("{}").unwrap() }
}

pub fn load_config(path: &str) -> ConfigFile {
    if !Path::new(path).exists() {
        log::warn!("Config file {} not found. Using defaults.", path);
        return ConfigFile::default();
    }
    let raw = fs::read_to_string(path).expect("Cannot read config");
    serde_json::from_str::<ConfigFile>(&raw).unwrap_or_else(|e| {
        log::error!("Config parse error: {}. Using defaults.", e);
        ConfigFile::default()
    })
}

// =============================================================================
// LOGGING
// =============================================================================

pub fn setup_logging(cfg: &ConfigFile) {
    if let Some(parent) = Path::new(&cfg.log_path).parent() {
        if !parent.as_os_str().is_empty() { fs::create_dir_all(parent).ok(); }
    }
    let level = match cfg.log_level { 0 => "warn", 1 => "info", _ => "debug" };
    if std::env::var("RUST_LOG").is_err() {
        std::env::set_var("RUST_LOG", level);
    }
    env_logger::builder().format_timestamp_secs().init();
}

// =============================================================================
// PATTERN RECOGNITION  (pattern.c)
// =============================================================================

pub struct SeqBuffer {
    buf: [Symbol; SEQ_LEN],
    ptr: usize,
    count: usize,
}

impl SeqBuffer {
    pub fn new() -> Self {
        Self { buf: [Symbol::X; SEQ_LEN], ptr: 0, count: 0 }
    }

    pub fn push(&mut self, s: Symbol) {
        self.buf[self.ptr % SEQ_LEN] = s;
        self.ptr += 1;
        if self.count < SEQ_LEN { self.count += 1; }
    }

    /// Return the sequence oldest-first, X-padded on the left until the
    /// buffer is full.
    pub fn read(&self) -> [Symbol; SEQ_LEN] {
        let mut out = [Symbol::X; SEQ_LEN];
        if self.count < SEQ_LEN {
            let pad   = SEQ_LEN - self.count;
            let start = (self.ptr + SEQ_LEN - self.count) % SEQ_LEN;
            for i in 0..self.count {
                out[pad + i] = self.buf[(start + i) % SEQ_LEN];
            }
        } else {
            let start = self.ptr % SEQ_LEN;
            for i in 0..SEQ_LEN {
                out[i] = self.buf[(start + i) % SEQ_LEN];
            }
        }
        out
    }
}

pub fn seq_to_str(seq: &[Symbol; SEQ_LEN]) -> String {
    seq.iter().map(|s| s.as_char()).collect()
}

/// Encode a single candle into the 7-symbol alphabet.
pub fn encode_candle(c: &Candle) -> Symbol {
    let body  = (c.close - c.open).abs();
    let range = c.high - c.low;
    if range < 1e-9 { return Symbol::X; }

    let ratio = body / range;
    let upper = c.high - c.open.max(c.close);
    let lower = c.open.min(c.close) - c.low;

    if upper > range * 0.6 { return Symbol::W;  }
    if lower > range * 0.6 { return Symbol::Wl; }
    if ratio < 0.10        { return Symbol::X;  }

    if c.close > c.open {
        if ratio > 0.6 { Symbol::B } else { Symbol::U }
    } else {
        if ratio > 0.6 { Symbol::I } else { Symbol::D }
    }
}

// =============================================================================
// EVALUATION  (eval.c)
// =============================================================================

pub fn evaluate_sequence(seq: &[Symbol; SEQ_LEN]) -> f64 {
    let mut material = 0.0_f64;
    let mut position = 0.0_f64;
    for i in 0..SEQ_LEN {
        let s = seq[i].as_usize();
        let w = (i + 1) as f64 / SEQ_LEN as f64;
        material += SYM_VALUE[s] * w;
        let tbl = ((i as f64 * 63.0) / (SEQ_LEN - 1) as f64) as usize;
        position += POSITION_TABLES[s][tbl.min(63)] as f64;
    }
    material + position
}

pub fn predict_next(seq: &[Symbol; SEQ_LEN]) -> (f64, Symbol) {
    let base = evaluate_sequence(seq);
    let mut best_abs   = -1.0_f64;
    let mut best_delta = 0.0_f64;
    let mut best_sym   = Symbol::X;
    let mut candidate  = *seq;

    for s_val in 0..SYMBOLS as u8 {
        let sym = Symbol::from_u8(s_val).unwrap();
        for i in 0..(SEQ_LEN - 1) { candidate[i] = seq[i + 1]; }
        candidate[SEQ_LEN - 1] = sym;
        let delta = evaluate_sequence(&candidate) - base;
        let absd  = delta.abs();
        if absd > best_abs { best_abs = absd; best_delta = delta; best_sym = sym; }
    }
    (best_delta, best_sym)
}

// =============================================================================
// GEOMETRY & ENTROPY  (geometry.c, entropy.c)
// =============================================================================

const MAX_H: f64 = 2.807_354; // log2(7)

pub fn calc_entropy(seq: &[Symbol; SEQ_LEN]) -> f64 {
    let mut counts = [0usize; SYMBOLS];
    for s in seq { counts[s.as_usize()] += 1; }
    let mut h = 0.0_f64;
    for &c in &counts {
        if c == 0 { continue; }
        let p = c as f64 / SEQ_LEN as f64;
        h -= p * p.log2();
    }
    h / MAX_H
}

pub fn calc_energy(seq: &[Symbol; SEQ_LEN]) -> f64 {
    let mut diff = [[0.0_f64; EDIM]; SEQ_LEN];
    let mut energy = 0.0_f64;
    for i in 0..(SEQ_LEN - 1) {
        for d in 0..EDIM {
            let dv = EMBEDDING[seq[i+1].as_usize()][d] - EMBEDDING[seq[i].as_usize()][d];
            diff[i][d] = dv;
            energy += dv * dv;
        }
    }
    for i in 0..(SEQ_LEN - 2) {
        for d in 0..EDIM {
            let curv = diff[i+1][d] - diff[i][d];
            energy += curv * curv;
        }
    }
    let max_e = ((SEQ_LEN - 1) + (SEQ_LEN - 2)) as f64 * EDIM as f64 * 4.0;
    energy / max_e
}

pub fn calc_divergence(seq: &[Symbol; SEQ_LEN]) -> f64 {
    let older:  f64 = seq[..10].iter().map(|s| SYM_VALUE[s.as_usize()]).sum();
    let recent: f64 = seq[10..].iter().map(|s| SYM_VALUE[s.as_usize()]).sum();
    (recent - older) / (10.0 * 900.0)
}

pub fn calc_curl(seq: &[Symbol; SEQ_LEN]) -> f64 {
    const BULLISH: [bool; SYMBOLS] = [true, false, true, false, true, false, false];
    let mut flips = 0usize;
    for i in 1..SEQ_LEN {
        let a = seq[i - 1];
        let b = seq[i];
        if a != Symbol::X && b != Symbol::X
            && BULLISH[a.as_usize()] != BULLISH[b.as_usize()]
        {
            flips += 1;
        }
    }
    flips as f64 / (SEQ_LEN - 1) as f64
}

// =============================================================================
// MEMORY STORE  (memory.c)
// =============================================================================

pub struct MemoryStore {
    /// VecDeque gives O(1) push-back and pop-front.
    /// Python used list.pop(0) which is O(n) — fixed here.
    db: VecDeque<MemoryEntry>,
}

impl MemoryStore {
    pub fn new()    -> Self { Self { db: VecDeque::new() } }
    pub fn count(&self) -> usize { self.db.len() }

    pub fn store(&mut self, seq: &[Symbol; SEQ_LEN], pnl: f64) {
        self.db.push_back(MemoryEntry { seq: seq.to_vec(), pnl });
        if self.db.len() > MEMORY_CAP { self.db.pop_front(); }
    }

    /// KNN (brute-force L2 on one-hot vectors), returns mean PnL of K nearest.
    pub fn query_bias(&self, seq: &[Symbol; SEQ_LEN]) -> f64 {
        if self.db.is_empty() { return 0.0; }

        let mut query = [0.0_f64; DIM];
        for i in 0..SEQ_LEN { query[i * SYMBOLS + seq[i].as_usize()] = 1.0; }

        // Keep a small sorted Vec of (dist², index); K=5 so linear scan is fine.
        let mut top: Vec<(f64, usize)> = Vec::with_capacity(KNN_K + 1);

        for (i, entry) in self.db.iter().enumerate() {
            let mut vec = [0.0_f64; DIM];
            for j in 0..SEQ_LEN.min(entry.seq.len()) {
                vec[j * SYMBOLS + entry.seq[j].as_usize()] = 1.0;
            }
            let d: f64 = (0..DIM).map(|k| { let x = query[k] - vec[k]; x * x }).sum();

            if top.len() < KNN_K || d < top.last().unwrap().0 {
                top.push((d, i));
                top.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
                if top.len() > KNN_K { top.pop(); }
            }
        }

        if top.is_empty() { return 0.0; }
        top.iter().map(|(_, i)| self.db[*i].pnl).sum::<f64>() / top.len() as f64
    }

    pub fn save(&self, path: &str) {
        let entries: Vec<&MemoryEntry> = self.db.iter().collect();
        match bincode::serialize(&entries) {
            Ok(b) => { fs::write(path, &b).unwrap_or_else(|e| log::error!("Save failed: {}", e)); }
            Err(e) => log::error!("Serialize failed: {}", e),
        }
    }

    pub fn load(&mut self, path: &str) {
        if !Path::new(path).exists() { return; }
        match fs::read(path) {
            Ok(b) => match bincode::deserialize::<Vec<MemoryEntry>>(&b) {
                Ok(v) => { self.db = VecDeque::from(v); log::info!("Loaded {} memory entries", self.db.len()); }
                Err(e) => log::error!("Deserialize failed: {}", e),
            },
            Err(e) => log::error!("Read memory failed: {}", e),
        }
    }
}

// =============================================================================
// SIGNAL & POSITION
// =============================================================================

#[derive(Debug, Clone)]
pub struct Signal {
    pub confidence: f64, pub bias: f64,   pub energy: f64,
    pub curl: f64,       pub entropy: f64, pub delta: f64,
    pub lot_size: f64,   pub valid: bool,
    pub direction: i8,   pub block_gate: u8,
}

impl Signal {
    fn blocked(gate: u8, entropy: f64, bias: f64) -> Self {
        Self { confidence: 0.0, bias, energy: 0.0, curl: 0.0,
               entropy, delta: 0.0, lot_size: 0.0,
               valid: false, direction: 0, block_gate: gate }
    }
}

#[derive(Debug, Clone)]
pub struct OpenPosition {
    pub timestamp_ms: i64, pub direction: i8,
    pub entry_price: f64,  pub sl_price: f64,  pub tp_price: f64,
    pub lot_size: f64,     pub signal: Signal,
    pub entry_seq: [Symbol; SEQ_LEN],
}

// =============================================================================
// RISK MANAGEMENT  (risk.c)
// =============================================================================

pub fn evaluate_signal(seq: &[Symbol; SEQ_LEN], cfg: &ConfigFile, mem: &MemoryStore) -> Signal {
    // λ1 – Entropy
    let entropy = calc_entropy(seq);
    if entropy >= cfg.entropy_thresh { return Signal::blocked(1, entropy, 0.0); }

    // λ2 – Memory bias
    let bias = mem.query_bias(seq);
    if bias <= cfg.min_bias { return Signal::blocked(2, entropy, bias); }

    // Prediction
    let (delta, _)  = predict_next(seq);
    let confidence  = (delta.abs() / 2000.0).min(1.0);
    let direction: i8 = if delta > 0.0 { 1 } else { -1 };

    // λ3 – Confidence / delta magnitude
    if confidence < cfg.min_confidence || delta.abs() < cfg.min_delta {
        return Signal { entropy, bias, delta, confidence, direction,
                        valid: false, block_gate: 3,
                        energy: 0.0, curl: 0.0, lot_size: 0.0 };
    }

    // λ4 – Geometry
    let energy = calc_energy(seq);
    let curl   = calc_curl(seq);
    if energy >= cfg.max_energy || curl > cfg.curl_thresh {
        return Signal { entropy, bias, delta, confidence, direction, energy, curl,
                        valid: false, block_gate: 4, lot_size: 0.0 };
    }

    // λ5 – Directional asset bias
    if cfg.asset_bias != 0 && direction != cfg.asset_bias {
        return Signal { entropy, bias, delta, confidence, direction, energy, curl,
                        valid: false, block_gate: 5, lot_size: 0.0 };
    }

    Signal { confidence, bias, energy, curl, entropy, delta,
             lot_size: 0.0, valid: true, direction, block_gate: 0 }
}

/// Fractional Kelly position size, clamped to [risk*0.5%, risk*2%].
pub fn kelly_size(win_rate: f64, avg_win: f64, avg_loss: f64,
                  conf: f64, stability: f64, cfg: &ConfigFile) -> f64 {
    if avg_win < 1e-9 { return cfg.risk_pct * 0.005; }
    let loss_rate = 1.0 - win_rate;
    let base = (win_rate * avg_win - loss_rate * avg_loss) / avg_win;
    let size = (base * 0.5) * conf * (1.0 - stability * 0.3);
    size.clamp(cfg.risk_pct * 0.005, cfg.risk_pct * 0.02)
}

// =============================================================================
// BROKER STUB
// =============================================================================

pub struct OandaBroker {
    cfg: ConfigFile,
    synth_price: f64,
    synth_ts: i64,
    connected: bool,
}

impl OandaBroker {
    pub fn new(cfg: ConfigFile) -> Self {
        Self { cfg, synth_price: 1.345_00, synth_ts: now_ms(), connected: false }
    }

    pub fn connect(&mut self) -> bool {
        self.connected = true;
        log::info!("[OANDA] PAPER mode – synthetic price feed");
        true
    }

    pub fn fetch_candle(&mut self) -> Option<Candle> {
        if !self.connected { return None; }
        let mut rng = rand::thread_rng();
        let drift  = (rng.gen::<f64>() - 0.5) * 0.001_0;
        let hi_ext = rng.gen::<f64>() * 0.001_5;
        let lo_ext = rng.gen::<f64>() * 0.001_5;
        let o = self.synth_price;
        let c = o * (1.0 + drift);
        let h = o.max(c) * (1.0 + hi_ext);
        let l = o.min(c) * (1.0 - lo_ext);
        let candle = Candle { open:o, high:h, low:l, close:c,
            volume: (rng.gen::<f64>() * 5000.0 + 500.0) as u64,
            spread: 0.000_2, timestamp_ms: self.synth_ts };
        self.synth_price = c;
        self.synth_ts   += 60_000;
        Some(candle)
    }

    pub fn get_price(&self) -> (f64, f64) {
        (self.synth_price - 0.000_1, self.synth_price + 0.000_1)
    }

    pub fn place_order(&self, sig: &Signal, entry_price: f64) -> Option<OpenPosition> {
        let sl_dist = entry_price * SYM_SL_PCT[0];
        let tp_dist = sl_dist * 2.0;
        let (sl_price, tp_price) = if sig.direction == 1 {
            (entry_price - sl_dist, entry_price + tp_dist)
        } else {
            (entry_price + sl_dist, entry_price - tp_dist)
        };
        log::info!("[ORDER] {} {:.2} lots @ {:.5}",
            if sig.direction == 1 { "LONG" } else { "SHORT" }, sig.lot_size, entry_price);
        Some(OpenPosition {
            timestamp_ms: now_ms(), direction: sig.direction,
            entry_price, sl_price, tp_price,
            lot_size: sig.lot_size, signal: sig.clone(),
            entry_seq: [Symbol::X; SEQ_LEN],
        })
    }
}

// =============================================================================
// BACKTESTER  (backtest.c)
// =============================================================================

#[derive(Debug, Deserialize)]
struct CsvRow {
    timestamp_ms: i64,
    open: f64, high: f64, low: f64, close: f64,
    #[serde(default)]
    volume: u64,
}

pub fn run_backtest(csv_path: &str, cfg: &ConfigFile, mem: &mut MemoryStore)
    -> Result<usize, String>
{
    let mut sb  = SeqBuffer::new();
    let mut seq = [Symbol::X; SEQ_LEN];

    let mut total_trades = 0usize;
    let mut wins = 0usize; let mut losses = 0usize;
    let mut total_pnl = 0.0_f64;
    let mut max_dd = 0.0_f64; let mut peak_pnl = 0.0_f64;
    let mut win_sum = 0.0_f64; let mut loss_sum = 0.0_f64;

    let mut in_trade = false;
    let mut cur_pos: Option<OpenPosition> = None;

    log::info!("[BACKTEST] Starting replay: {}", csv_path);

    let file = fs::File::open(csv_path)
        .map_err(|_| format!("[BACKTEST] File not found: {}", csv_path))?;
    let mut reader = csv::Reader::from_reader(io::BufReader::new(file));

    for result in reader.deserialize::<CsvRow>() {
        let row = match result { Ok(r) => r, Err(_) => continue };
        let c = Candle {
            open: row.open, high: row.high, low: row.low, close: row.close,
            timestamp_ms: row.timestamp_ms, volume: row.volume, spread: 0.0,
        };

        // ── Position management ───────────────────────────────────────────────
        if in_trade {
            if let Some(ref pos) = cur_pos {
                let (closed, pnl, reason) = check_exit(pos, &c);
                if closed {
                    total_pnl += pnl;
                    if pnl > 0.0 { wins += 1; win_sum += pnl; }
                    else         { losses += 1; loss_sum += -pnl; }
                    if total_pnl > peak_pnl { peak_pnl = total_pnl; }
                    let dd = peak_pnl - total_pnl;
                    if dd > max_dd { max_dd = dd; }
                    mem.store(&pos.entry_seq, pnl);
                    log::debug!("[BT] CLOSE {} pnl={:.1} reason={}",
                        if pos.direction==1 {"LONG"} else {"SHORT"}, pnl, reason);
                    in_trade = false; cur_pos = None;
                }
            }
        }

        sym_push(&mut sb, &mut seq, &c);
        if in_trade { continue; }

        // ── Signal ────────────────────────────────────────────────────────────
        let mut sig = evaluate_signal(&seq, cfg, mem);
        if !sig.valid { continue; }

        let wr = if total_trades > 0 { wins as f64 / total_trades as f64 } else { 0.55 };
        let aw = if wins   > 0 { win_sum  / wins   as f64 } else { 12.0 };
        let al = if losses > 0 { loss_sum / losses as f64 } else { 8.0 };
        sig.lot_size = kelly_size(wr, aw, al, sig.confidence, sig.energy, cfg);

        let entry = (c.open + c.close) / 2.0;
        let sl_d  = entry * SYM_SL_PCT[0];
        let tp_d  = sl_d * 2.0;
        let (sl_price, tp_price) = if sig.direction == 1 {
            (entry - sl_d, entry + tp_d)
        } else {
            (entry + sl_d, entry - tp_d)
        };

        cur_pos = Some(OpenPosition {
            timestamp_ms: c.timestamp_ms, direction: sig.direction,
            entry_price: entry, sl_price, tp_price,
            lot_size: sig.lot_size, signal: sig.clone(), entry_seq: seq,
        });
        in_trade = true;
        total_trades += 1;
        log::debug!("[BT] OPEN {} {:.2} lots @ {:.5}",
            if sig.direction==1 {"LONG"} else {"SHORT"}, sig.lot_size, entry);
    }

    let wr_pct = if total_trades > 0 { 100.0 * wins as f64 / total_trades as f64 } else { 0.0 };
    log::info!("─────────────────────────────────────────");
    log::info!("[BACKTEST] Trades: {} | Wins: {} ({:.1}%) | Losses: {}", total_trades, wins, wr_pct, losses);
    log::info!("[BACKTEST] Total PnL: {:.1} pips | Max DD: {:.1} pips", total_pnl, max_dd);
    log::info!("─────────────────────────────────────────");

    Ok(total_trades)
}

// =============================================================================
// LIVE / PAPER LOOP
// =============================================================================

pub fn run_live(cfg: ConfigFile, mem: &mut MemoryStore, running: Arc<AtomicBool>) {
    let mut broker = OandaBroker::new(cfg.clone());
    if !broker.connect() { log::error!("Broker connection failed"); return; }

    let mut sb  = SeqBuffer::new();
    let mut seq = [Symbol::X; SEQ_LEN];
    let mut in_trade = false;
    let mut cur_pos: Option<OpenPosition> = None;
    let mut stats = TradeStats::default();

    while running.load(Ordering::SeqCst) {
        let candle = match broker.fetch_candle() {
            Some(c) => c,
            None    => { std::thread::sleep(std::time::Duration::from_secs(5)); continue; }
        };

        sym_push(&mut sb, &mut seq, &candle);

        if in_trade {
            if let Some(ref pos) = cur_pos {
                let (bid, ask) = broker.get_price();
                let current = if pos.direction == 1 { bid } else { ask };
                let sl_hit  = if pos.direction == 1 { current <= pos.sl_price }
                              else                   { current >= pos.sl_price };
                let tp_hit  = if pos.direction == 1 { current >= pos.tp_price }
                              else                   { current <= pos.tp_price };
                if sl_hit || tp_hit {
                    let pnl = (current - pos.entry_price) * pos.direction as f64 / 0.000_1;
                    mem.store(&pos.entry_seq, pnl);
                    log::info!("[CLOSE] PnL={:.1} pips ({})", pnl, if sl_hit {"SL"} else {"TP"});
                    stats.record(pnl);
                    in_trade = false; cur_pos = None;
                }
            }
            std::thread::sleep(std::time::Duration::from_secs(1));
            continue;
        }

        let mut sig = evaluate_signal(&seq, &cfg, mem);
        if !sig.valid { std::thread::sleep(std::time::Duration::from_secs(1)); continue; }

        sig.lot_size = kelly_size(stats.win_rate(), stats.avg_win(), stats.avg_loss(),
                                  sig.confidence, sig.energy, &cfg);

        if let Some(mut pos) = broker.place_order(&sig, candle.close) {
            pos.entry_seq = seq;
            cur_pos = Some(pos);
            in_trade = true;
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
}

// =============================================================================
// HELPERS
// =============================================================================

/// Check SL/TP against the current bar; returns (closed, pnl_pips, reason).
fn check_exit(pos: &OpenPosition, c: &Candle) -> (bool, f64, &'static str) {
    if pos.direction == 1 {
        if c.low <= pos.sl_price {
            return (true, (pos.sl_price - pos.entry_price) / 0.000_1 * pos.lot_size, "sl");
        }
        if c.high >= pos.tp_price {
            return (true, (pos.tp_price  - pos.entry_price) / 0.000_1 * pos.lot_size, "tp");
        }
    } else {
        if c.high >= pos.sl_price {
            return (true, (pos.entry_price - pos.sl_price) / 0.000_1 * pos.lot_size, "sl");
        }
        if c.low <= pos.tp_price {
            return (true, (pos.entry_price - pos.tp_price) / 0.000_1 * pos.lot_size, "tp");
        }
    }
    (false, 0.0, "")
}

/// Encode a candle and push it into the SeqBuffer, then update the seq snapshot.
fn sym_push(sb: &mut SeqBuffer, seq: &mut [Symbol; SEQ_LEN], c: &Candle) {
    let sym = encode_candle(c);
    sb.push(sym);
    *seq = sb.read();
}

fn now_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64).unwrap_or(0)
}

#[derive(Default)]
struct TradeStats {
    wins: usize, losses: usize, win_sum: f64, loss_sum: f64, trades: usize,
}
impl TradeStats {
    fn record(&mut self, pnl: f64) {
        self.trades += 1;
        if pnl > 0.0 { self.wins += 1; self.win_sum += pnl; }
        else          { self.losses += 1; self.loss_sum += -pnl; }
    }
    fn win_rate(&self) -> f64 { if self.trades > 0 { self.wins as f64 / self.trades as f64 } else { 0.55 } }
    fn avg_win(&self)  -> f64 { if self.wins   > 0 { self.win_sum  / self.wins   as f64 } else { 12.0 } }
    fn avg_loss(&self) -> f64 { if self.losses > 0 { self.loss_sum / self.losses as f64 } else { 8.0 } }
}

// =============================================================================
// CLI
// =============================================================================

#[derive(Parser, Debug)]
#[command(name = "smart_exe", version = "1.0", about = "SMART-EXE Trading Engine – Rust Port")]
struct Cli {
    #[arg(long, default_value_t = true)]  paper:    bool,
    #[arg(long)]                          live:     bool,
    #[arg(long)]                          backtest: Option<String>,
    #[arg(long)]                          once:     bool,
    #[arg(long)]                          sequence: Option<String>,
    #[arg(long, default_value = "config.json")] config: String,
    #[arg(long)]                          verbose:  bool,
}

// =============================================================================
// MAIN
// =============================================================================

fn main() {
    let args = Cli::parse();

    let mut cfg = load_config(&args.config);
    if args.verbose { cfg.log_level = 2; }
    if args.live    { cfg.paper = false; }
    else if args.paper { cfg.paper = true; }

    setup_logging(&cfg);

    let mut mem = MemoryStore::new();
    mem.load("memory.bin");

    // Graceful shutdown flag shared with Ctrl-C handler
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();
    ctrlc::set_handler(move || {
        log::info!("Shutdown requested...");
        r.store(false, Ordering::SeqCst);
    }).expect("Error setting Ctrl-C handler");

    // ── Once mode ─────────────────────────────────────────────────────────────
    if args.once {
        let seq_str = args.sequence.as_deref().unwrap_or("BBUIBBXIBB");
        let mut sb = SeqBuffer::new();
        for ch in seq_str.chars() {
            if let Some(sym) = Symbol::from_char(ch) { sb.push(sym); }
        }
        let seq = sb.read();
        let sig = evaluate_signal(&seq, &cfg, &mem);
        println!("Sequence:   {}", seq_to_str(&seq));
        println!("Decision:   {}", if sig.valid && sig.direction==1 {"LONG"}
                                   else if sig.valid {"SHORT"} else {"BLOCK"});
        println!("Valid:      {} (Gate {})", sig.valid, sig.block_gate);
        println!("Entropy:    {:.3}", sig.entropy);
        println!("Confidence: {:.3}", sig.confidence);
        println!("Delta:      {:.1}", sig.delta);
        mem.save("memory.bin");
        return;
    }

    // ── Backtest mode ─────────────────────────────────────────────────────────
    if let Some(ref path) = args.backtest {
        match run_backtest(path, &cfg, &mut mem) {
            Ok(n)  => log::info!("[BACKTEST] Completed: {} trades", n),
            Err(e) => log::error!("{}", e),
        }
        mem.save("memory.bin");
        return;
    }

    // ── Live / paper loop ─────────────────────────────────────────────────────
    run_live(cfg, &mut mem, running.clone());
    mem.save("memory.bin");
    log::info!("Memory saved. Goodbye.");
}
