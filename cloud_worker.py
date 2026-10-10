"""
24/7 Cloud Background Trading Worker for Render
Runs autonomously in the cloud without needing your laptop or any .bat clicks.
Monitors Indian Market Hours (Monday-Friday, 9:20 AM - 3:15 PM IST).
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import yfinance as yf
import pandas as pd

import config
from indicators import add_strategy_signals
from megabull_client import MegaBullClient

logger = logging.getLogger("CloudWorker")

# Indian Timezone (UTC + 5:30)
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))

# Curated High-Volume Indian Stocks
AUTONOMOUS_WATCHLIST = [
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
    "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS", "AXISBANK.NS", "LT.NS",
    "BAJFINANCE.NS", "MARUTI.NS", "TATASTEEL.NS", "M&M.NS", "ADANIENT.NS"
]


class CloudAutonomousTrader:
    def __init__(
        self,
        timeframe: str = "5m",
        capital_per_trade: float = 25000,
        max_positions: int = 3,
    ):
        self.tickers = AUTONOMOUS_WATCHLIST
        self.timeframe = timeframe
        self.capital_per_trade = capital_per_trade
        self.max_positions = max_positions
        self.megabull = MegaBullClient(config.MEGABULL_API_KEY) if not config.SIMULATION_MODE else None
        self.positions: Dict[str, dict] = {}
        self.daily_swing_scanned_today = False

    def get_ist_now(self) -> datetime:
        """Get current date and time in Indian Standard Time (IST)."""
        return datetime.now(IST_OFFSET)

    def is_market_open(self) -> bool:
        """Check if Indian Market (NSE/BSE) is currently open."""
        now_ist = self.get_ist_now()
        # Monday is 0, Sunday is 6
        if now_ist.weekday() >= 5:
            return False  # Weekend
        
        current_time_str = now_ist.strftime("%H:%M")
        return "09:20" <= current_time_str <= "15:30"

    def fetch_live_data(self, ticker: str) -> Optional[pd.DataFrame]:
        try:
            df = yf.download(ticker, period="3d", interval=self.timeframe, progress=False)
            if df.empty or len(df) < 50:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
        except Exception:
            return None

    def scan_market_tick(self):
        """Scans the market and executes trades when setups trigger."""
        now_ist = self.get_ist_now()
        time_str = now_ist.strftime("%H:%M")

        # 3:15 PM Intraday Auto Square-off
        if time_str >= "15:15" and self.positions:
            logger.info("[3:15 PM IST] Squaring off open positions before market close...")
            for sym, pos in list(self.positions.items()):
                self.close_position(sym, pos["qty"], reason="3:15 PM EOD Square-off")
            return

        logger.info(f"[CLOUD SCAN] Active Positions: {len(self.positions)}/{self.max_positions} | IST: {now_ist.strftime('%H:%M:%S')}")

        for ticker in self.tickers:
            clean_name = ticker.replace(".NS", "")
            df = self.fetch_live_data(ticker)
            if df is None:
                continue

            df = add_strategy_signals(df)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            price = float(last["Close"])
            atr = float(last["ATR"])
            adx = float(last["ADX"])
            ema200 = float(last["EMA_200"])

            # Check existing position for SL / Target
            if clean_name in self.positions:
                self.manage_open_position(clean_name, price)
                continue

            # Check Long Breakout Signal
            if (bool(last["Signal_Long"]) or bool(prev["Signal_Long"])) and len(self.positions) < self.max_positions:
                sl = round(price - (atr * 1.2), 2)
                tp = round(price + (atr * 2.5), 2)
                qty = max(1, int(self.capital_per_trade / price))

                logger.info(f"🚀 [CLOUD TRIGGER] BUY {clean_name} @ Rs.{price:.2f} | SL: {sl} | TP: {tp}")
                self.execute_order(clean_name, "BUY", qty, sl, tp, price)

            # Check Short Breakdown Signal
            elif (bool(last["Signal_Short"]) or bool(prev["Signal_Short"])) and len(self.positions) < self.max_positions:
                sl = round(price + (atr * 1.2), 2)
                tp = round(price - (atr * 2.5), 2)
                qty = max(1, int(self.capital_per_trade / price))

                logger.info(f"🔻 [CLOUD TRIGGER] SHORT {clean_name} @ Rs.{price:.2f} | SL: {sl} | TP: {tp}")
                self.execute_order(clean_name, "SELL", qty, sl, tp, price)

            time.sleep(0.1)

    def execute_order(self, symbol: str, side: str, qty: int, sl: float, tp: float, price: float):
        if config.SIMULATION_MODE or self.megabull is None:
            logger.info(f"✨ [CLOUD SIMULATED] {side} {qty} {symbol} at Rs.{price:.2f}")
            self.positions[symbol] = {"side": side, "entry": price, "sl": sl, "tp": tp, "qty": qty}
        else:
            try:
                resp = self.megabull.place_order(symbol=symbol, action=side, qty=qty, duration="MIS", order_type="MKT")
                logger.info(f"✅ [CLOUD MEGABULL FILLED] Order ID: {resp.get('id')}")
                self.positions[symbol] = {"side": side, "entry": price, "sl": sl, "tp": tp, "qty": qty, "id": resp.get("id")}
            except Exception as e:
                logger.error(f"Cloud MegaBull order error: {e}")

    def manage_open_position(self, symbol: str, current_price: float):
        pos = self.positions[symbol]
        side = pos["side"]
        entry = pos["entry"]
        sl = pos["sl"]
        tp = pos["tp"]
        qty = pos["qty"]

        if side == "BUY":
            if current_price <= sl:
                logger.warning(f"🛑 [STOP LOSS HIT] {symbol} @ Rs.{current_price:.2f}")
                self.close_position(symbol, qty, "Stop Loss")
            elif current_price >= tp:
                logger.info(f"🎯 [TARGET HIT] {symbol} @ Rs.{current_price:.2f}")
                self.close_position(symbol, qty, "Target Profit")
        elif side == "SELL":
            if current_price >= sl:
                logger.warning(f"🛑 [STOP LOSS HIT] {symbol} @ Rs.{current_price:.2f}")
                self.close_position(symbol, qty, "Stop Loss")
            elif current_price <= tp:
                logger.info(f"🎯 [TARGET HIT] {symbol} @ Rs.{current_price:.2f}")
                self.close_position(symbol, qty, "Target Profit")

    def close_position(self, symbol: str, qty: int, reason: str = ""):
        logger.info(f"Squaring off {symbol} on MegaBull ({reason})...")
        if not config.SIMULATION_MODE and self.megabull:
            try:
                self.megabull.close_position(symbol)
            except Exception as e:
                logger.error(f"Error closing {symbol}: {e}")
        self.positions.pop(symbol, None)

    def run_247_cloud_loop(self):
        """The permanent 24/7 background worker running in the cloud."""
        logger.info("=" * 60)
        logger.info("☁️ 24/7 AUTONOMOUS CLOUD TRADING WORKER ACTIVATED")
        logger.info("   No laptop needed! Runs continuously in the cloud.")
        logger.info("=" * 60)

        while True:
            try:
                now_ist = self.get_ist_now()
                if self.is_market_open():
                    self.scan_market_tick()
                    time.sleep(60)  # Scan every 60 seconds during market hours
                else:
                    status_msg = "Weekend" if now_ist.weekday() >= 5 else "After Hours (Closed)"
                    logger.info(f"💤 [MARKET CLOSED: {status_msg}] Current IST: {now_ist.strftime('%a %H:%M:%S')}. Worker sleeping...")
                    time.sleep(120)  # Check every 2 minutes when closed
            except Exception as e:
                logger.error(f"Worker exception: {e}")
                time.sleep(30)


_worker_instance = None

def start_cloud_worker_thread():
    global _worker_instance
    import threading
    if _worker_instance is None:
        _worker_instance = CloudAutonomousTrader()
        t = threading.Thread(target=_worker_instance.run_247_cloud_loop, daemon=True)
        t.start()
        logger.info("Background 24/7 cloud trader thread successfully spawned!")
