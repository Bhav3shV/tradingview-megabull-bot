"""
Autonomous Institutional Cloud Daemon (Zero-Touch Self-Governing Engine)
Features:
- Market Regime Adaptive Execution (Hurst Exponent + VWAP)
- Dual-Direction Trading (Long & Short MIS)
- Audited Telemetry Logging (SQLite Database)
- 100% Zero-Touch Automation (No Laptop, No Bat Files)
"""

import logging
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import yfinance as yf
import pandas as pd

import config
from alpha_engine import evaluate_alpha_signal
from megabull_client import MegaBullClient

logger = logging.getLogger("AutonomousDaemon")
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))

LEADER_WATCHLIST = [
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
    "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS", "AXISBANK.NS", "LT.NS",
    "BAJFINANCE.NS", "MARUTI.NS", "TATASTEEL.NS", "M&M.NS", "ADANIENT.NS"
]


class AutonomousQuantitativeEngine:
    def __init__(self, db_path: str = "telemetry.db", capital_per_trade: float = 25000, max_positions: int = 3):
        self.db_path = db_path
        self.tickers = LEADER_WATCHLIST
        self.capital_per_trade = capital_per_trade
        self.max_positions = max_positions
        self.megabull = MegaBullClient(config.MEGABULL_API_KEY) if not config.SIMULATION_MODE else None
        self.positions: Dict[str, dict] = {}
        self._init_database()

    def _init_database(self):
        """Creates audit telemetry table for patent & performance verification."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                action TEXT,
                strategy TEXT,
                regime TEXT,
                entry_price REAL,
                sl_price REAL,
                tp_price REAL,
                qty INTEGER,
                exit_price REAL,
                exit_reason TEXT,
                pnl_amount REAL,
                order_id TEXT
            )
        """)
        conn.commit()
        conn.close()

    def get_ist(self) -> datetime:
        return datetime.now(IST_OFFSET)

    def is_market_active(self) -> bool:
        now_ist = self.get_ist()
        if now_ist.weekday() >= 5:
            return False  # Weekend
        time_str = now_ist.strftime("%H:%M")
        return "09:20" <= time_str <= "15:30"

    def fetch_bars(self, ticker: str) -> Optional[pd.DataFrame]:
        try:
            df = yf.download(ticker, period="2d", interval="5m", progress=False)
            if df.empty or len(df) < 50:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception:
            return None

    def execute_trade(self, symbol: str, signal: dict):
        action = signal["action"]
        price = signal["price"]
        sl = signal["sl"]
        tp = signal["tp"]
        strategy = signal["strategy"]
        regime = signal["regime"]
        qty = max(1, int(self.capital_per_trade / price))

        logger.info(f"⚡ [AUTONOMOUS TRIGGER] {action} {qty} {symbol} @ Rs.{price:.2f} ({strategy} in {regime})")
        logger.info(f"   |-- Stop-Loss : Rs.{sl:.2f}")
        logger.info(f"   +-- Target    : Rs.{tp:.2f}")

        order_id = "sim-" + str(int(time.time()))
        if not config.SIMULATION_MODE and self.megabull:
            try:
                resp = self.megabull.place_order(symbol=symbol, action=action, qty=qty, duration="MIS", order_type="MKT")
                order_id = str(resp.get("id", order_id))
                logger.info(f"✅ [MEGABULL LIVE FILLED] Order ID: {order_id}")
            except Exception as e:
                logger.error(f"MegaBull execution error for {symbol}: {e}")

        # Record position
        self.positions[symbol] = {
            "action": action,
            "entry_price": price,
            "sl": sl,
            "tp": tp,
            "qty": qty,
            "strategy": strategy,
            "regime": regime,
            "order_id": order_id,
            "entered_at": self.get_ist().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def manage_positions(self, ticker_map: Dict[str, float]):
        for symbol, pos in list(self.positions.items()):
            if symbol not in ticker_map:
                continue
            current_price = ticker_map[symbol]
            action = pos["action"]
            entry = pos["entry_price"]
            sl = pos["sl"]
            tp = pos["tp"]
            qty = pos["qty"]

            exit_triggered = False
            exit_reason = ""
            pnl = 0.0

            if action == "BUY":
                if current_price <= sl:
                    exit_triggered = True
                    exit_reason = "STOP_LOSS"
                    pnl = (current_price - entry) * qty
                elif current_price >= tp:
                    exit_triggered = True
                    exit_reason = "TAKE_PROFIT"
                    pnl = (current_price - entry) * qty
            elif action == "SELL":
                if current_price >= sl:
                    exit_triggered = True
                    exit_reason = "STOP_LOSS"
                    pnl = (entry - current_price) * qty
                elif current_price <= tp:
                    exit_triggered = True
                    exit_reason = "TAKE_PROFIT"
                    pnl = (entry - current_price) * qty

            if exit_triggered:
                logger.info(f"🎯 [AUTONOMOUS EXIT] {symbol} {action} closed ({exit_reason}) | PnL: Rs.{pnl:+.2f}")
                self.close_position_internal(symbol, qty, exit_reason, current_price, pnl)

    def close_position_internal(self, symbol: str, qty: int, reason: str, exit_price: float, pnl: float):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return

        if not config.SIMULATION_MODE and self.megabull:
            try:
                self.megabull.close_position(symbol)
            except Exception as e:
                logger.error(f"Error closing MegaBull position: {e}")

        # Audit log into SQLite
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO audit_trades 
                (timestamp, symbol, action, strategy, regime, entry_price, sl_price, tp_price, qty, exit_price, exit_reason, pnl_amount, order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.get_ist().strftime("%Y-%m-%d %H:%M:%S"),
                symbol, pos["action"], pos["strategy"], pos["regime"],
                pos["entry_price"], pos["sl"], pos["tp"], qty,
                exit_price, reason, pnl, pos["order_id"]
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Audit DB log error: {e}")

    def run_market_cycle(self):
        now_ist = self.get_ist()
        time_str = now_ist.strftime("%H:%M")

        # 3:15 PM EOD Square-off
        if time_str >= "15:15" and self.positions:
            logger.info("[3:15 PM AUTO SQUARE-OFF] Closing remaining positions...")
            for symbol, pos in list(self.positions.items()):
                self.close_position_internal(symbol, pos["qty"], "EOD_SQUARE_OFF", pos["entry_price"], 0.0)
            return

        price_map = {}
        for ticker in self.tickers:
            clean_name = ticker.replace(".NS", "")
            df = self.fetch_bars(ticker)
            if df is None:
                continue

            current_price = float(df["Close"].iloc[-1])
            price_map[clean_name] = current_price

            # If already holding this symbol, manage it
            if clean_name in self.positions:
                continue

            # Check if slots are available
            if len(self.positions) < self.max_positions:
                signal = evaluate_alpha_signal(df)
                if signal:
                    self.execute_trade(clean_name, signal)

            time.sleep(0.1)

        # Monitor active stops and targets
        self.manage_positions(price_map)

    def start_perpetual_cloud_loop(self):
        logger.info("=" * 65)
        logger.info("🚀 100% AUTONOMOUS INSTITUTIONAL CLOUD DAEMON ONLINE")
        logger.info("   Mode: Regime-Adaptive Dual-Alpha (Long + Short MIS)")
        logger.info("   Database Audit: Enabled (telemetry.db)")
        logger.info("   Human Interaction: ZERO REQUIRED (Full Cloud Autopilot)")
        logger.info("=" * 65)

        while True:
            try:
                if self.is_market_active():
                    self.run_market_cycle()
                    time.sleep(60)
                else:
                    now = self.get_ist()
                    logger.info(f"💤 Market Inactive (IST {now.strftime('%a %H:%M:%S')}). Waiting for next market open (09:20 AM)...")
                    time.sleep(120)
            except Exception as e:
                logger.error(f"Engine Loop Error: {e}", exc_info=True)
                time.sleep(30)


_engine_singleton = None

def get_engine():
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = AutonomousQuantitativeEngine()
    return _engine_singleton

def start_daemon_background():
    import threading
    engine = get_engine()
    t = threading.Thread(target=engine.start_perpetual_cloud_loop, daemon=True)
    t.start()
    return engine
