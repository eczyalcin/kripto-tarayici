"""Smart Money Engine — Liquidity Sweep, FVG, Order Block, BOS/CHOCH.

Tüm tespitler mum verisi üzerinde kural tabanlıdır; öznel çizim yoktur.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.indicators import atr as atr_ind
from core.indicators import clamp, swing_points


# --------------------------------------------------------------- liquidity sweep
def find_liquidity_sweeps(df: pd.DataFrame, cfg_sm: Dict[str, Any],
                          atr_series: pd.Series) -> List[Dict[str, Any]]:
    """Dip/tepe süpürme: önce likidite seviyesi, sonra uzun fitil + hacim + geri dönüş.

    Adımlar:
      1. Mum, önceki swing low'un altına (veya swing high'ın üstüne) sarkar
      2. Fitil, mum boyunun `sweep_wick_ratio` oranından büyüktür
      3. Hacim, 20 mumluk ortalamanın `sweep_volume_mult` katıdır
      4. Kapanış, süpürülen seviyenin geri tarafına döner
    """
    out: List[Dict[str, Any]] = []
    if len(df) < 30:
        return out

    wick_ratio = cfg_sm.get("sweep_wick_ratio", 0.55)
    vol_mult = cfg_sm.get("sweep_volume_mult", 1.4)
    lookback = cfg_sm.get("sweep_lookback", 60)

    sw = swing_points(df, 3)
    vol_ma = df["volume"].rolling(20, min_periods=5).mean()

    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    opens, closes = df["open"].to_numpy(), df["close"].to_numpy()
    vols = df["volume"].to_numpy()
    sw_high = sw["swing_high"].to_numpy()
    sw_low = sw["swing_low"].to_numpy()

    start = max(20, len(df) - lookback)
    for i in range(start, len(df)):
        rng = highs[i] - lows[i]
        if rng <= 0:
            continue
        body_low, body_high = min(opens[i], closes[i]), max(opens[i], closes[i])
        lower_wick = body_low - lows[i]
        upper_wick = highs[i] - body_high
        vma = vol_ma[i] if not np.isnan(vol_ma.iloc[i]) else vols[i]
        vol_ok = vols[i] >= vma * vol_mult

        window = range(max(0, i - lookback), i - 2)

        # --- BUY SIDE LIQUIDITY (dip süpürme -> yükseliş sinyali)
        if lower_wick / rng >= wick_ratio:
            prior_lows = [lows[j] for j in window if sw_low[j]]
            if prior_lows:
                target = max([lv for lv in prior_lows if lv > lows[i]], default=None)
                if target is not None and closes[i] > target:
                    out.append({
                        "type": "BUY_LIQUIDITY_SWEPT",
                        "direction": "bullish",
                        "index": int(i),
                        "time": str(df["open_time"].iat[i]),
                        "swept_level": float(target),
                        "wick_low": float(lows[i]),
                        "close": float(closes[i]),
                        "wick_ratio": round(lower_wick / rng, 3),
                        "volume_ratio": round(float(vols[i] / vma), 2) if vma else None,
                        "volume_confirmed": bool(vol_ok),
                        "bars_ago": int(len(df) - 1 - i),
                    })

        # --- SELL SIDE LIQUIDITY (tepe süpürme -> düşüş sinyali)
        if upper_wick / rng >= wick_ratio:
            prior_highs = [highs[j] for j in window if sw_high[j]]
            if prior_highs:
                target = min([lv for lv in prior_highs if lv < highs[i]], default=None)
                if target is not None and closes[i] < target:
                    out.append({
                        "type": "SELL_LIQUIDITY_SWEPT",
                        "direction": "bearish",
                        "index": int(i),
                        "time": str(df["open_time"].iat[i]),
                        "swept_level": float(target),
                        "wick_high": float(highs[i]),
                        "close": float(closes[i]),
                        "wick_ratio": round(upper_wick / rng, 3),
                        "volume_ratio": round(float(vols[i] / vma), 2) if vma else None,
                        "volume_confirmed": bool(vol_ok),
                        "bars_ago": int(len(df) - 1 - i),
                    })

    return out


# ------------------------------------------------------------------ fair value gap
def find_fvgs(df: pd.DataFrame, cfg_sm: Dict[str, Any],
              atr_series: pd.Series) -> List[Dict[str, Any]]:
    """3 mumluk dengesizlik: low[i] > high[i-2] (bullish) / high[i] < low[i-2] (bearish)."""
    out: List[Dict[str, Any]] = []
    if len(df) < 5:
        return out

    min_size = cfg_sm.get("fvg_min_size_atr", 0.15)
    max_age = cfg_sm.get("fvg_max_age", 80)
    highs, lows, closes = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    atr_arr = atr_series.to_numpy()
    n = len(df)
    last_close = closes[-1]

    for i in range(2, n):
        if n - 1 - i > max_age:
            continue
        a = atr_arr[i] if not np.isnan(atr_arr[i]) and atr_arr[i] > 0 else None
        if a is None:
            continue

        # Bullish FVG
        if lows[i] > highs[i - 2]:
            size = lows[i] - highs[i - 2]
            if size >= a * min_size:
                bottom, top = float(highs[i - 2]), float(lows[i])
                filled = bool(np.min(lows[i:]) <= bottom)
                mitigated = bool(np.min(lows[i:]) <= top)
                out.append({
                    "type": "BULLISH_FVG", "direction": "bullish",
                    "index": int(i), "time": str(df["open_time"].iat[i]),
                    "bottom": bottom, "top": top, "mid": (bottom + top) / 2,
                    "size_pct": round(size / last_close * 100, 4),
                    "size_atr": round(size / a, 2),
                    "filled": filled, "mitigated": mitigated,
                    "bars_ago": int(n - 1 - i),
                    "distance_pct": round((bottom - last_close) / last_close * 100, 3),
                })

        # Bearish FVG
        if highs[i] < lows[i - 2]:
            size = lows[i - 2] - highs[i]
            if size >= a * min_size:
                bottom, top = float(highs[i]), float(lows[i - 2])
                filled = bool(np.max(highs[i:]) >= top)
                mitigated = bool(np.max(highs[i:]) >= bottom)
                out.append({
                    "type": "BEARISH_FVG", "direction": "bearish",
                    "index": int(i), "time": str(df["open_time"].iat[i]),
                    "bottom": bottom, "top": top, "mid": (bottom + top) / 2,
                    "size_pct": round(size / last_close * 100, 4),
                    "size_atr": round(size / a, 2),
                    "filled": filled, "mitigated": mitigated,
                    "bars_ago": int(n - 1 - i),
                    "distance_pct": round((top - last_close) / last_close * 100, 3),
                })

    return out


# ------------------------------------------------------------------ order block
def find_order_blocks(df: pd.DataFrame, cfg_sm: Dict[str, Any],
                      atr_series: pd.Series) -> List[Dict[str, Any]]:
    """Güçlü hareket öncesindeki son ters yönlü mum = order block."""
    out: List[Dict[str, Any]] = []
    if len(df) < 10:
        return out

    disp = cfg_sm.get("ob_displacement_atr", 1.0)
    max_age = cfg_sm.get("fvg_max_age", 80)
    opens, closes = df["open"].to_numpy(), df["close"].to_numpy()
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    atr_arr = atr_series.to_numpy()
    n = len(df)
    last_close = closes[-1]

    for i in range(1, n - 1):
        if n - 1 - i > max_age:
            continue
        a = atr_arr[i] if not np.isnan(atr_arr[i]) and atr_arr[i] > 0 else None
        if a is None:
            continue

        move = closes[i + 1] - opens[i + 1]
        # Bullish OB: düşen mum + hemen ardından güçlü yükseliş
        if closes[i] < opens[i] and move > a * disp:
            bottom, top = float(lows[i]), float(highs[i])
            mitigated = bool(np.min(lows[i + 2:]) <= top) if i + 2 < n else False
            out.append({
                "type": "BULLISH_OB", "direction": "bullish",
                "index": int(i), "time": str(df["open_time"].iat[i]),
                "bottom": bottom, "top": top, "mid": (bottom + top) / 2,
                "displacement_atr": round(float(move / a), 2),
                "mitigated": mitigated, "bars_ago": int(n - 1 - i),
                "distance_pct": round((top - last_close) / last_close * 100, 3),
            })

        # Bearish OB: yükselen mum + hemen ardından güçlü düşüş
        if closes[i] > opens[i] and move < -a * disp:
            bottom, top = float(lows[i]), float(highs[i])
            mitigated = bool(np.max(highs[i + 2:]) >= bottom) if i + 2 < n else False
            out.append({
                "type": "BEARISH_OB", "direction": "bearish",
                "index": int(i), "time": str(df["open_time"].iat[i]),
                "bottom": bottom, "top": top, "mid": (bottom + top) / 2,
                "displacement_atr": round(float(abs(move) / a), 2),
                "mitigated": mitigated, "bars_ago": int(n - 1 - i),
                "distance_pct": round((bottom - last_close) / last_close * 100, 3),
            })

    return out


# ------------------------------------------------------------------ BOS / CHOCH
def find_structure_breaks(df: pd.DataFrame, lookback_bars: int = 120) -> List[Dict[str, Any]]:
    """Swing yapısına göre BOS (trend devamı) ve CHOCH (trend değişimi)."""
    out: List[Dict[str, Any]] = []
    if len(df) < 30:
        return out

    sw = swing_points(df, 3)
    highs, lows, closes = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    sw_high, sw_low = sw["swing_high"].to_numpy(), sw["swing_low"].to_numpy()
    n = len(df)

    last_sh: Optional[float] = None
    last_sl: Optional[float] = None
    trend: Optional[str] = None       # "up" | "down"
    start = max(10, n - lookback_bars)

    for i in range(10, n):
        if sw_high[i]:
            last_sh = highs[i]
        if sw_low[i]:
            last_sl = lows[i]

        if last_sh is not None and closes[i] > last_sh:
            kind = "CHOCH" if trend == "down" else "BOS"
            if i >= start:
                out.append({
                    "type": kind, "direction": "bullish",
                    "index": int(i), "time": str(df["open_time"].iat[i]),
                    "broken_level": float(last_sh), "close": float(closes[i]),
                    "bars_ago": int(n - 1 - i),
                })
            trend = "up"
            last_sh = None

        if last_sl is not None and closes[i] < last_sl:
            kind = "CHOCH" if trend == "up" else "BOS"
            if i >= start:
                out.append({
                    "type": kind, "direction": "bearish",
                    "index": int(i), "time": str(df["open_time"].iat[i]),
                    "broken_level": float(last_sl), "close": float(closes[i]),
                    "bars_ago": int(n - 1 - i),
                })
            trend = "down"
            last_sl = None

    return out


# ----------------------------------------------------------------------- run
def run(candles: Dict[str, pd.DataFrame], cfg) -> Dict[str, Any]:
    cfg_sm = cfg.get("smart_money", {})
    cfg_trend = cfg.get("trend", {})
    max_items = cfg_sm.get("max_items", 6)

    df = candles.get("mtf")
    if df is None or df.empty or len(df) < 30:
        return {"available": False, "score": 0.0}

    atr_series = atr_ind(df, cfg_trend.get("atr_period", 14))

    sweeps = find_liquidity_sweeps(df, cfg_sm, atr_series)
    fvgs = find_fvgs(df, cfg_sm, atr_series)
    obs = find_order_blocks(df, cfg_sm, atr_series)
    breaks = find_structure_breaks(df)

    # LTF üzerinde de yapı kırılımı arayalım (daha erken sinyal)
    ltf = candles.get("ltf")
    ltf_breaks = find_structure_breaks(ltf, 60) if ltf is not None and not ltf.empty else []

    open_fvgs = [f for f in fvgs if not f["filled"]]
    fresh_obs = [o for o in obs if not o["mitigated"]]
    recent_sweeps = [s for s in sweeps if s["bars_ago"] <= 12]
    recent_breaks = [b for b in breaks if b["bars_ago"] <= 12]

    # ------------------------------------------------------------- skorlama
    score = 0.0
    signals: List[str] = []

    for s in recent_sweeps:
        w = 0.45 if s["volume_confirmed"] else 0.25
        decay = max(0.3, 1 - s["bars_ago"] / 12)
        score += (w * decay) if s["direction"] == "bullish" else -(w * decay)
        signals.append(f"{s['type']} ({s['bars_ago']} mum önce)")

    for b in recent_breaks:
        base = 0.40 if b["type"] == "CHOCH" else 0.30
        decay = max(0.3, 1 - b["bars_ago"] / 12)
        score += (base * decay) if b["direction"] == "bullish" else -(base * decay)
        signals.append(f"{b['type']} {b['direction']} ({b['bars_ago']} mum önce)")

    # Fiyatın hemen altındaki dolmamış bullish FVG = destek, üstündeki bearish = direnç
    near_bull_fvg = [f for f in open_fvgs
                     if f["direction"] == "bullish" and -3 <= f["distance_pct"] <= 0.5]
    near_bear_fvg = [f for f in open_fvgs
                     if f["direction"] == "bearish" and -0.5 <= f["distance_pct"] <= 3]
    score += 0.15 * min(len(near_bull_fvg), 2)
    score -= 0.15 * min(len(near_bear_fvg), 2)

    score = clamp(score)
    last_break = breaks[-1] if breaks else None

    return {
        "available": True,
        "score": round(float(score), 4),
        "label": ("BULLISH" if score > 0.3 else "BEARISH" if score < -0.3 else "NEUTRAL"),
        "liquidity_sweeps": sweeps[-max_items:],
        "recent_sweeps": recent_sweeps,
        "fvg": {
            "open": sorted(open_fvgs, key=lambda x: abs(x["distance_pct"]))[:max_items],
            "bullish_count": sum(1 for f in open_fvgs if f["direction"] == "bullish"),
            "bearish_count": sum(1 for f in open_fvgs if f["direction"] == "bearish"),
            "nearest_bullish": min(near_bull_fvg, key=lambda x: abs(x["distance_pct"]))
            if near_bull_fvg else None,
            "nearest_bearish": min(near_bear_fvg, key=lambda x: abs(x["distance_pct"]))
            if near_bear_fvg else None,
        },
        "order_blocks": {
            "fresh": sorted(fresh_obs, key=lambda x: abs(x["distance_pct"]))[:max_items],
            "bullish_count": sum(1 for o in fresh_obs if o["direction"] == "bullish"),
            "bearish_count": sum(1 for o in fresh_obs if o["direction"] == "bearish"),
        },
        "structure_breaks": breaks[-max_items:],
        "ltf_structure_breaks": ltf_breaks[-3:],
        "last_break": last_break,
        "signals": signals,
        "summary": _summary(recent_sweeps, recent_breaks, open_fvgs, last_break),
    }


def _summary(sweeps, breaks, open_fvgs, last_break) -> str:
    parts: List[str] = []
    if sweeps:
        s = sweeps[-1]
        yon = "Dip" if s["direction"] == "bullish" else "Tepe"
        parts.append(f"{yon} likiditesi süpürüldü ({s['bars_ago']} mum önce)")
    if last_break:
        parts.append(f"Son yapı olayı: {last_break['type']} {last_break['direction']} "
                     f"({last_break['bars_ago']} mum önce)")
    if open_fvgs:
        parts.append(f"{len(open_fvgs)} açık FVG")
    return " · ".join(parts) if parts else "Belirgin smart money sinyali yok"
