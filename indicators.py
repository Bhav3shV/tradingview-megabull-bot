"""
Quantitative indicators module (EMA, ATR, ADX) matching Pine Script v5 logic.
"""

import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, span: int) -> pd.Series:
    """Calculate Exponential Moving Average."""
    return series.ewm(span=span, adjust=False).mean()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average Directional Index (ADX) matching Pine Script ta.dmi."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # True Range
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    # Wilder's Smoothing
    tr_smooth = pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / tr_smooth)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / tr_smooth)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()

    return adx.fillna(0)


def add_strategy_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA, ATR, ADX and entry/exit conditions matching strategy.pine."""
    df = df.copy()
    close = df["Close"]

    df["EMA_20"] = calculate_ema(close, 20)
    df["EMA_50"] = calculate_ema(close, 50)
    df["EMA_200"] = calculate_ema(close, 200)

    df["ATR"] = calculate_atr(df, 14)
    df["ADX"] = calculate_adx(df, 14)

    df["Vol_SMA"] = df["Volume"].rolling(window=20).mean()
    df["Vol_OK"] = df["Volume"] > df["Vol_SMA"]

    # Bullish condition:
    # 1. Macro trend: Close > EMA_200
    # 2. Crossover: EMA_20 crossed above EMA_50
    # 3. ADX > 20 (Strong trend)
    # 4. Volume > 20 SMA
    ema20_prev = df["EMA_20"].shift(1)
    ema50_prev = df["EMA_50"].shift(1)
    crossover = (ema20_prev <= ema50_prev) & (df["EMA_20"] > df["EMA_50"])
    crossunder = (ema20_prev >= ema50_prev) & (df["EMA_20"] < df["EMA_50"])

    df["Signal_Long"] = (close > df["EMA_200"]) & crossover & (df["ADX"] > 20) & df["Vol_OK"]
    df["Signal_Short"] = (close < df["EMA_200"]) & crossunder & (df["ADX"] > 20) & df["Vol_OK"]

    return df
