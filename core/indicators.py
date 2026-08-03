"""Teknik gösterge kütüphanesi (saf pandas/numpy - TA-Lib derlemesi gerekmez).

Wilder yumuşatması kullanan göstergeler (RSI, ATR, ADX) TradingView/Binance ile
uyumlu sonuç verir.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# --------------------------------------------------------------------- ortalama
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=1).mean()


def wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder (RMA) yumuşatması."""
    return series.ewm(alpha=1 / period, adjust=False).mean()


# ------------------------------------------------------------------- momentum
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = wilder(gain.fillna(0), period)
    avg_loss = wilder(loss.fillna(0), period)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9) -> pd.DataFrame:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    return pd.DataFrame({
        "macd": macd_line,
        "signal": signal_line,
        "hist": macd_line - signal_line,
    })


# ----------------------------------------------------------------- volatilite
def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return wilder(true_range(df).fillna(0), period)


def bollinger(close: pd.Series, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    basis = close.rolling(period, min_periods=1).mean()
    dev = close.rolling(period, min_periods=1).std(ddof=0)
    return pd.DataFrame({
        "basis": basis,
        "upper": basis + mult * dev,
        "lower": basis - mult * dev,
        "width_pct": (2 * mult * dev / basis.replace(0, np.nan)) * 100,
    })


# ---------------------------------------------------------------- trend gücü
def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr_s = wilder(true_range(df).fillna(0), period)
    plus_di = 100 * wilder(pd.Series(plus_dm, index=df.index), period) / tr_s.replace(0, np.nan)
    minus_di = 100 * wilder(pd.Series(minus_dm, index=df.index), period) / tr_s.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_line = wilder(dx.fillna(0), period)
    return pd.DataFrame({"adx": adx_line, "plus_di": plus_di, "minus_di": minus_di})


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    atr_s = atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upper_basic = hl2 + multiplier * atr_s
    lower_basic = hl2 - multiplier * atr_s

    close = df["close"].to_numpy()
    ub = upper_basic.to_numpy()
    lb = lower_basic.to_numpy()
    n = len(df)
    final_ub = np.zeros(n)
    final_lb = np.zeros(n)
    direction = np.ones(n)  # 1 = yükseliş, -1 = düşüş
    st = np.zeros(n)

    for i in range(n):
        if i == 0:
            final_ub[i], final_lb[i] = ub[i], lb[i]
            st[i] = final_ub[i]
            continue
        final_ub[i] = ub[i] if (ub[i] < final_ub[i - 1] or close[i - 1] > final_ub[i - 1]) else final_ub[i - 1]
        final_lb[i] = lb[i] if (lb[i] > final_lb[i - 1] or close[i - 1] < final_lb[i - 1]) else final_lb[i - 1]

        if st[i - 1] == final_ub[i - 1]:
            direction[i] = -1 if close[i] <= final_ub[i] else 1
        else:
            direction[i] = 1 if close[i] >= final_lb[i] else -1
        st[i] = final_lb[i] if direction[i] == 1 else final_ub[i]

    return pd.DataFrame({"supertrend": st, "direction": direction}, index=df.index)


# ------------------------------------------------------------------- VWAP
def anchored_vwap(df: pd.DataFrame, anchor: str = "D") -> pd.Series:
    """anchor: 'D' günlük, 'W' haftalık, 'M' aylık."""
    if df.empty:
        return pd.Series(dtype=float)
    typical = (df["high"] + df["low"] + df["close"]) / 3
    tpv = typical * df["volume"]
    times = pd.DatetimeIndex(df["open_time"])
    if anchor == "D":
        groups = times.floor("D")
    elif anchor == "W":
        # Haftanın pazartesi 00:00 UTC başlangıcına yuvarla (tz bilgisi korunur)
        days = times.floor("D")
        groups = days - pd.to_timedelta(days.dayofweek, unit="D")
    else:
        groups = times.floor("D") - pd.to_timedelta(times.day - 1, unit="D")
    g = pd.Series(groups, index=df.index)
    cum_tpv = tpv.groupby(g).cumsum()
    cum_vol = df["volume"].groupby(g).cumsum().replace(0, np.nan)
    return cum_tpv / cum_vol


# ------------------------------------------------------------ market yapısı
def swing_points(df: pd.DataFrame, lookback: int = 3) -> pd.DataFrame:
    """Fraktal pivotlar: solunda ve sağında `lookback` mum bulunan tepe/dipler."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback:i + lookback + 1]
        window_l = lows[i - lookback:i + lookback + 1]
        if highs[i] == window_h.max() and (window_h.argmax() == lookback):
            is_high[i] = True
        if lows[i] == window_l.min() and (window_l.argmin() == lookback):
            is_low[i] = True
    return pd.DataFrame({"swing_high": is_high, "swing_low": is_low}, index=df.index)


def market_structure(df: pd.DataFrame, lookback: int = 3) -> Dict:
    """HH / HL / LH / LL etiketlerini ve mevcut yapı durumunu üretir."""
    sw = swing_points(df, lookback)
    points: List[Dict] = []
    for i in range(len(df)):
        if sw["swing_high"].iat[i]:
            points.append({"idx": i, "type": "high", "price": float(df["high"].iat[i]),
                           "time": df["open_time"].iat[i]})
        elif sw["swing_low"].iat[i]:
            points.append({"idx": i, "type": "low", "price": float(df["low"].iat[i]),
                           "time": df["open_time"].iat[i]})

    labeled: List[Dict] = []
    last_high: Optional[float] = None
    last_low: Optional[float] = None
    for p in points:
        label = None
        if p["type"] == "high":
            if last_high is not None:
                label = "HH" if p["price"] > last_high else "LH"
            last_high = p["price"]
        else:
            if last_low is not None:
                label = "HL" if p["price"] > last_low else "LL"
            last_low = p["price"]
        if label:
            labeled.append({**p, "label": label})

    recent = [p["label"] for p in labeled[-4:]]
    if recent[-2:] == ["HH", "HL"] or recent[-2:] == ["HL", "HH"]:
        state = "BULLISH"
    elif recent[-2:] == ["LL", "LH"] or recent[-2:] == ["LH", "LL"]:
        state = "BEARISH"
    elif recent and recent[-1] in ("HH", "HL"):
        state = "BULLISH"
    elif recent and recent[-1] in ("LL", "LH"):
        state = "BEARISH"
    else:
        state = "RANGE"

    return {
        "points": labeled,
        "state": state,
        "recent_labels": recent,
        "last_swing_high": last_high,
        "last_swing_low": last_low,
        "swing_flags": sw,
    }


# --------------------------------------------------------------- yardımcılar
def tr_lower(text: str) -> str:
    """Türkçe'ye uygun küçük harf (I -> ı, İ -> i)."""
    return text.replace("I", "ı").replace("İ", "i").lower()


def pct_change(new: float, old: float) -> float:
    if old in (0, None) or new is None or (isinstance(old, float) and np.isnan(old)):
        return 0.0
    return (new - old) / abs(old) * 100.0


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def safe_last(series: pd.Series, default: float = float("nan")) -> float:
    if series is None or len(series) == 0:
        return default
    val = series.iloc[-1]
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def enrich(df: pd.DataFrame, cfg_trend: Dict) -> pd.DataFrame:
    """Bir mum DataFrame'ine tüm temel göstergeleri ekler."""
    out = df.copy()
    for p in cfg_trend.get("ema_periods", [20, 50, 100, 200]):
        out[f"ema{p}"] = ema(out["close"], p)
    out["rsi"] = rsi(out["close"], cfg_trend.get("rsi_period", 14))
    m = cfg_trend.get("macd", {"fast": 12, "slow": 26, "signal": 9})
    macd_df = macd(out["close"], m["fast"], m["slow"], m["signal"])
    out["macd"] = macd_df["macd"]
    out["macd_signal"] = macd_df["signal"]
    out["macd_hist"] = macd_df["hist"]
    out["atr"] = atr(out, cfg_trend.get("atr_period", 14))
    adx_df = adx(out, cfg_trend.get("adx_period", 14))
    out["adx"] = adx_df["adx"]
    out["plus_di"] = adx_df["plus_di"]
    out["minus_di"] = adx_df["minus_di"]
    st_cfg = cfg_trend.get("supertrend", {"period": 10, "multiplier": 3.0})
    st = supertrend(out, st_cfg["period"], st_cfg["multiplier"])
    out["supertrend"] = st["supertrend"]
    out["st_dir"] = st["direction"]
    out["vwap_d"] = anchored_vwap(out, "D")
    out["vwap_w"] = anchored_vwap(out, "W")
    out["vol_ma20"] = out["volume"].rolling(20, min_periods=1).mean()
    return out
