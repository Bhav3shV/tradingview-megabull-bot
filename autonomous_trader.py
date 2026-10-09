"""
Autonomous AI & Algorithmic Trading Bot (100% Free - No TradingView Subscription Needed)
Fetches live NSE/BSE market data, calculates strategy indicators, and executes trades on MegaBull Paper Trading.
"""

import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional
import yfinance as yf
import pandas as pd

import config
from megabull_client import MegaBullClient
from indicators import add_strategy_signals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("AutonomousTrader")

# Default Watchlist of high-liquidity Indian stocks (NSE)
DEFAULT_WATCHLIST = [
    "RELIANCE.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "INFY.NS",
    "TCS.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "KOTAKBANK.NS",
]


class AutonomousTrader:
    def __init__(self, watchlist: Optional[List[str]] = None, timeframe: str = "5m"):
        self.watchlist = watchlist or DEFAULT_WATCHLIST
        self.timeframe = timeframe  # "1m", "5m", "15m"
        self.megabull = MegaBullClient(config.MEGABULL_API_KEY) if not config.SIMULATION_MODE else None
        self.positions: Dict[str, dict] = {}  # In-memory tracking: {symbol: {side, entry, sl, tp, qty}}

    def fetch_live_data(self, ticker: str) -> Optional[pd.DataFrame]:
        """Fetch latest intraday candles via free market feed."""
        try:
            # Multi-period fetch to ensure 200 EMA has sufficient lookback
            df = yf.download(ticker, period="5d", interval=self.timeframe, progress=False)
            if df.empty or len(df) < 50:
                logger.warning(f"Not enough data bars for {ticker} ({len(df)} bars)")
                return None
            
            # Flatten multi-index columns if returned by yfinance
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            return df
        except Exception as e:
            logger.error(f"Error fetching data for {ticker}: {e}")
            return None

    def evaluate_symbol(self, ticker: str):
        """Analyze a stock and execute orders if conditions are met."""
        clean_name = ticker.replace(".NS", "").replace(".BO", "")
        df = self.fetch_live_data(ticker)
        if df is None:
            return

        df = add_strategy_signals(df)
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        current_price = float(last_row["Close"])
        atr_val = float(last_row["ATR"])
        adx_val = float(last_row["ADX"])
        ema20 = float(last_row["EMA_20"])
        ema50 = float(last_row["EMA_50"])
        ema200 = float(last_row["EMA_200"])

        # Status check for console
        trend_status = "BULLISH" if current_price > ema200 else "BEARISH"
        logger.info(
            f"[{clean_name}] ₹{current_price:.2f} | Trend: {trend_status} | ADX: {adx_val:.1f} | EMA(20/50): {ema20:.1f}/{ema50:.1f}"
        )

        # 1. Check existing open position for exit (SL or TP)
        if clean_name in self.positions:
            pos = self.positions[clean_name]
            side = pos["side"]
            entry = pos["entry"]
            sl = pos["sl"]
            tp = pos["tp"]
            qty = pos["qty"]

            # Long exit check
            if side == "BUY":
                if current_price <= sl:
                    logger.warning(f"🛑 [STOP LOSS HIT] {clean_name} at ₹{current_price:.2f} (Entry: ₹{entry:.2f})")
                    self.close_position(clean_name, qty)
                elif current_price >= tp:
                    logger.info(f"🎯 [TAKE PROFIT HIT] {clean_name} at ₹{current_price:.2f} (Entry: ₹{entry:.2f})")
                    self.close_position(clean_name, qty)
            return

        # 2. Check for Long Entry Signal
        if bool(last_row["Signal_Long"]) or bool(prev_row["Signal_Long"]):
            sl_price = round(current_price - (atr_val * 1.5), 2)
            tp_price = round(current_price + (atr_val * 3.0), 2)
            qty = 10  # default order qty

            logger.info(
                f"🚀 [BUY SIGNAL DETECTED] {clean_name} at ₹{current_price:.2f} | SL: ₹{sl_price} | TP: ₹{tp_price}"
            )
            self.execute_order(clean_name, "BUY", qty, sl_price, tp_price, current_price)

        # 3. Check for Short Entry Signal
        elif bool(last_row["Signal_Short"]) or bool(prev_row["Signal_Short"]):
            sl_price = round(current_price + (atr_val * 1.5), 2)
            tp_price = round(current_price - (atr_val * 3.0), 2)
            qty = 10

            logger.info(
                f"🔻 [SELL/SHORT SIGNAL DETECTED] {clean_name} at ₹{current_price:.2f} | SL: ₹{sl_price} | TP: ₹{tp_price}"
            )
            self.execute_order(clean_name, "SELL", qty, sl_price, tp_price, current_price)

    def execute_order(self, symbol: str, side: str, qty: int, sl: float, tp: float, price: float):
        """Submit order to MegaBull or simulated environment."""
        if config.SIMULATION_MODE or self.megabull is None:
            logger.info(f"✨ [SIMULATED EXECUTION] {side} {qty} shares of {symbol} at ₹{price:.2f}")
            self.positions[symbol] = {
                "side": side,
                "entry": price,
                "sl": sl,
                "tp": tp,
                "qty": qty,
                "time": datetime.now().isoformat(),
            }
        else:
            try:
                resp = self.megabull.place_order(
                    symbol=symbol,
                    action=side,
                    qty=qty,
                    duration="MIS",
                    order_type="MKT",
                )
                logger.info(f"✅ [MEGABULL ORDER PLACED] Order ID: {resp.get('id')}")
                self.positions[symbol] = {
                    "side": side,
                    "entry": price,
                    "sl": sl,
                    "tp": tp,
                    "qty": qty,
                    "order_id": resp.get("id"),
                    "time": datetime.now().isoformat(),
                }
            except Exception as e:
                logger.error(f"Failed to place MegaBull order for {symbol}: {e}")

    def close_position(self, symbol: str, qty: int):
        """Close open position on MegaBull."""
        if not config.SIMULATION_MODE and self.megabull:
            try:
                self.megabull.close_position(symbol)
                logger.info(f"✅ Closed position for {symbol} on MegaBull.")
            except Exception as e:
                logger.error(f"Error closing position for {symbol} on MegaBull: {e}")
        
        self.positions.pop(symbol, None)

    def scan_once(self):
        """Run one full scan pass over the watchlist."""
        logger.info("=" * 60)
        logger.info(f"Scanning {len(self.watchlist)} stocks at {datetime.now().strftime('%H:%M:%S')}...")
        for sym in self.watchlist:
            self.evaluate_symbol(sym)
            time.sleep(0.5)
        logger.info("=" * 60)

    def run_continuous_loop(self, interval_seconds: int = 60):
        """Run continuous automated scanner during market hours."""
        logger.info("Starting Autonomous Trading Loop. Press Ctrl+C to stop.")
        while True:
            try:
                self.scan_once()
                logger.info(f"Waiting {interval_seconds}s for next candle update...\n")
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                logger.info("Autonomous Trader stopped by user.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in scanner loop: {e}")
                time.sleep(10)


if __name__ == "__main__":
    bot = AutonomousTrader()
    # Perform an initial scan pass
    bot.scan_once()
