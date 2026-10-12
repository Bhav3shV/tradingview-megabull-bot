"""
Regime Classification Module for Autonomous Quantitative Trading
Classifies market regimes mathematically into:
- TRENDING_BULL
- TRENDING_BEAR
- MEAN_REVERTING_RANGE
- HIGH_VOLATILITY_NOISE (Zero Trade / Capital Preservation)
"""

import numpy as np
import pandas as pd


def compute_hurst_exponent(price_series: pd.Series, max_lag: int = 20) -> float:
    """
    Computes Hurst Exponent (H) to distinguish between:
    - H > 0.55: Persistent Trend (Momentum operates here)
    - H < 0.45: Mean-Reverting (Range trading operates here)
    - 0.45 <= H <= 0.55: Random Walk / Noise (Cash is king)
    """
    try:
        prices = price_series.dropna().values
        if len(prices) < max_lag * 2:
            return 0.5

        lags = range(2, max_lag)
        tau = [np.std(prices[lag:] - prices[:-lag]) for lag in lags]
        
        # Linear regression on log(lag) vs log(tau)
        reg = np.polyfit(np.log(lags), np.log(tau), 1)
        hurst = reg[0]
        return float(np.clip(hurst, 0.0, 1.0))
    except Exception:
        return 0.5


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """Calculate Volume-Weighted Average Price (VWAP)."""
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3.0
    cumulative_pv = (typical_price * df["Volume"]).cumsum()
    cumulative_vol = df["Volume"].cumsum()
    return cumulative_pv / cumulative_vol.replace(0, np.nan)


def classify_market_regime(df: pd.DataFrame) -> dict:
    """
    Evaluates current bar's statistical regime and returns regime state,
    strength score, and recommended execution engine.
    """
    if len(df) < 50:
        return {"regime": "INSUFFICIENT_DATA", "engine": "NONE", "confidence": 0.0}

    close = df["Close"]
    volume = df["Volume"]
    
    # 1. VWAP & Moving Averages
    vwap = compute_vwap(df)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    current_close = float(close.iloc[-1])
    current_vwap = float(vwap.iloc[-1])
    current_ema20 = float(ema20.iloc[-1])
    current_ema50 = float(ema50.iloc[-1])

    # 2. Volatility (ATR %)
    high = df["High"]
    low = df["Low"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()
    current_atr = float(atr.iloc[-1])
    atr_pct = (current_atr / current_close) * 100

    # 3. Hurst Exponent
    hurst = compute_hurst_exponent(close.tail(60))

    # 4. Volume Ratio
    vol_sma20 = volume.rolling(20).mean()
    vol_ratio = float(volume.iloc[-1] / vol_sma20.iloc[-1]) if vol_sma20.iloc[-1] > 0 else 1.0

    # Regime Decision Tree
    if hurst > 0.52:
        # Strong Persistent Trend
        if current_close > current_vwap and current_ema20 > current_ema50:
            return {
                "regime": "TRENDING_BULL",
                "engine": "MOMENTUM_LONG",
                "hurst": hurst,
                "atr": current_atr,
                "atr_pct": atr_pct,
                "vol_ratio": vol_ratio,
                "vwap": current_vwap,
            }
        elif current_close < current_vwap and current_ema20 < current_ema50:
            return {
                "regime": "TRENDING_BEAR",
                "engine": "MOMENTUM_SHORT",
                "hurst": hurst,
                "atr": current_atr,
                "atr_pct": atr_pct,
                "vol_ratio": vol_ratio,
                "vwap": current_vwap,
            }

    elif hurst < 0.44:
        # Mean Reverting
        return {
            "regime": "MEAN_REVERTING_RANGE",
            "engine": "REVERSION",
            "hurst": hurst,
            "atr": current_atr,
            "atr_pct": atr_pct,
            "vol_ratio": vol_ratio,
            "vwap": current_vwap,
        }

    # Default to Noise / Chop Preservation
    return {
        "regime": "RANDOM_WALK_CHOP",
        "engine": "HOLD_CASH",
        "hurst": hurst,
        "atr": current_atr,
        "atr_pct": atr_pct,
        "vol_ratio": vol_ratio,
        "vwap": current_vwap,
    }
