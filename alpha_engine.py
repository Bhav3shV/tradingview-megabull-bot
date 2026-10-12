"""
Adaptive Dual-Alpha Generation Engine
Generates institutional signals for both Trending and Mean-Reverting Regimes.
"""

from typing import Optional, Dict
import pandas as pd
import numpy as np

from regime_classifier import classify_market_regime, compute_vwap


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs)).fillna(50)


def evaluate_alpha_signal(df: pd.DataFrame) -> Optional[Dict]:
    """
    Evaluates market regime and generates an actionable alpha signal
    with mathematically derived Stop-Loss, Take-Profit, and Confidence Score.
    """
    if len(df) < 50:
        return None

    regime_data = classify_market_regime(df)
    engine = regime_data.get("engine")
    regime = regime_data.get("regime")
    
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    current_price = float(close.iloc[-1])
    atr = regime_data.get("atr", current_price * 0.01)
    vwap = regime_data.get("vwap", current_price)

    rsi = compute_rsi(close)
    current_rsi = float(rsi.iloc[-1])

    # -------------------------------------------------------------
    # ALPHA 1: MOMENTUM ACCELERATION (BULL REGIME)
    # -------------------------------------------------------------
    if engine == "MOMENTUM_LONG":
        # Price above VWAP, RSI between 52 and 72 (healthy momentum, not exhausted)
        if current_price > vwap and 50 < current_rsi < 75:
            sl = round(current_price - (atr * 1.5), 2)
            tp = round(current_price + (atr * 3.0), 2)
            return {
                "action": "BUY",
                "strategy": "TREND_MOMENTUM_LONG",
                "regime": regime,
                "price": current_price,
                "sl": sl,
                "tp": tp,
                "confidence": round(regime_data.get("hurst", 0.5) * 100, 1),
                "rationale": f"Hurst {regime_data.get('hurst'):.2f} (Persistent Trend) + Price > VWAP (Rs.{vwap:.1f}) + RSI {current_rsi:.1f}"
            }

    # -------------------------------------------------------------
    # ALPHA 2: MOMENTUM BREAKDOWN (BEAR REGIME)
    # -------------------------------------------------------------
    elif engine == "MOMENTUM_SHORT":
        # Price below VWAP, RSI between 25 and 48 (healthy downward acceleration)
        if current_price < vwap and 25 < current_rsi < 50:
            sl = round(current_price + (atr * 1.5), 2)
            tp = round(current_price - (atr * 3.0), 2)
            return {
                "action": "SELL",
                "strategy": "TREND_MOMENTUM_SHORT",
                "regime": regime,
                "price": current_price,
                "sl": sl,
                "tp": tp,
                "confidence": round(regime_data.get("hurst", 0.5) * 100, 1),
                "rationale": f"Hurst {regime_data.get('hurst'):.2f} (Persistent Bear) + Price < VWAP (Rs.{vwap:.1f}) + RSI {current_rsi:.1f}"
            }

    # -------------------------------------------------------------
    # ALPHA 3: STATISTICAL MEAN REVERSION (RANGE REGIME)
    # -------------------------------------------------------------
    elif engine == "REVERSION":
        # Oversold at lower boundary -> Revert to VWAP
        if current_rsi < 32 and current_price < (vwap - atr):
            sl = round(current_price - (atr * 1.2), 2)
            tp = round(vwap, 2)
            return {
                "action": "BUY",
                "strategy": "MEAN_REVERSION_LONG",
                "regime": regime,
                "price": current_price,
                "sl": sl,
                "tp": tp,
                "confidence": 75.0,
                "rationale": f"Mean Reversion: Oversold RSI ({current_rsi:.1f}) at discount below VWAP"
            }
        # Overbought at upper boundary -> Revert to VWAP
        elif current_rsi > 68 and current_price > (vwap + atr):
            sl = round(current_price + (atr * 1.2), 2)
            tp = round(vwap, 2)
            return {
                "action": "SELL",
                "strategy": "MEAN_REVERSION_SHORT",
                "regime": regime,
                "price": current_price,
                "sl": sl,
                "tp": tp,
                "confidence": 75.0,
                "rationale": f"Mean Reversion: Overbought RSI ({current_rsi:.1f}) at premium above VWAP"
            }

    # Regime is Noise / Chop -> Protect capital
    return None
