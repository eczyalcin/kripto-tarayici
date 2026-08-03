"""Trend Engine — EMA / VWAP / ATR / ADX / SuperTrend / Market Structure."""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from core.indicators import clamp, enrich, market_structure, pct_change, safe_last


def _ema_alignment(row: pd.Series, periods) -> Dict[str, Any]:
    values = [row.get(f"ema{p}") for p in periods]
    valid = [v for v in values if v is not None and not pd.isna(v)]
    if len(valid) < 2:
        return {"state": "UNKNOWN", "score": 0.0}
    ascending = all(valid[i] > valid[i + 1] for i in range(len(valid) - 1))
    descending = all(valid[i] < valid[i + 1] for i in range(len(valid) - 1))
    price = float(row["close"])
    above = sum(1 for v in valid if price > v)
    ratio = above / len(valid)
    if ascending and ratio == 1.0:
        return {"state": "PERFECT_BULLISH", "score": 1.0}
    if descending and ratio == 0.0:
        return {"state": "PERFECT_BEARISH", "score": -1.0}
    return {"state": "MIXED", "score": clamp((ratio - 0.5) * 2)}


def analyze_timeframe(df: pd.DataFrame, cfg_trend: Dict[str, Any]) -> Dict[str, Any]:
    """Tek bir zaman dilimi için trend fotoğrafı."""
    if df is None or df.empty or len(df) < 30:
        return {"available": False}

    e = enrich(df, cfg_trend)
    last = e.iloc[-1]
    prev = e.iloc[-2]
    periods = cfg_trend.get("ema_periods", [20, 50, 100, 200])
    price = float(last["close"])

    alignment = _ema_alignment(last, periods)
    atr_val = float(last["atr"])
    atr_pct = atr_val / price * 100 if price else 0.0

    adx_val = float(last["adx"])
    di_bias = 1.0 if last["plus_di"] > last["minus_di"] else -1.0
    # ADX 20 altı = trendsiz, 40 üstü = güçlü trend
    adx_strength = clamp((adx_val - 20) / 25, 0, 1)

    st_dir = int(last["st_dir"])
    st_flip = bool(st_dir != int(prev["st_dir"]))

    vwap_d = float(last["vwap_d"]) if not pd.isna(last["vwap_d"]) else None
    vwap_w = float(last["vwap_w"]) if not pd.isna(last["vwap_w"]) else None

    structure = market_structure(e, cfg_trend.get("swing_lookback", 3))

    # --- bileşen skorları ------------------------------------------------
    s_align = alignment["score"] * 0.35
    s_adx = di_bias * adx_strength * 0.20
    s_st = st_dir * 0.20
    s_vwap = 0.0
    if vwap_d:
        s_vwap += clamp(pct_change(price, vwap_d) / 1.5) * 0.10
    if vwap_w:
        s_vwap += clamp(pct_change(price, vwap_w) / 3.0) * 0.05
    s_struct = {"BULLISH": 0.10, "BEARISH": -0.10}.get(structure["state"], 0.0)
    score = clamp(s_align + s_adx + s_st + s_vwap + s_struct)

    if score > 0.35:
        label = "BULLISH"
    elif score < -0.35:
        label = "BEARISH"
    else:
        label = "NEUTRAL"

    return {
        "available": True,
        "price": price,
        "label": label,
        "score": round(score, 4),
        "ema": {f"ema{p}": (None if pd.isna(last[f"ema{p}"]) else round(float(last[f"ema{p}"]), 10))
                for p in periods},
        "ema_alignment": alignment["state"],
        "price_vs_ema": {f"ema{p}": round(pct_change(price, float(last[f"ema{p}"])), 3)
                         for p in periods if not pd.isna(last[f"ema{p}"])},
        "vwap": {
            "daily": vwap_d,
            "weekly": vwap_w,
            "price_vs_daily_pct": round(pct_change(price, vwap_d), 3) if vwap_d else None,
            "price_vs_weekly_pct": round(pct_change(price, vwap_w), 3) if vwap_w else None,
        },
        "atr": {"value": atr_val, "pct": round(atr_pct, 3)},
        "adx": {"value": round(adx_val, 2),
                "plus_di": round(float(last["plus_di"]), 2),
                "minus_di": round(float(last["minus_di"]), 2),
                "strength": ("STRONG" if adx_val >= 40 else
                             "TRENDING" if adx_val >= 25 else
                             "WEAK" if adx_val >= 20 else "RANGE")},
        "supertrend": {"value": float(last["supertrend"]),
                       "direction": "UP" if st_dir == 1 else "DOWN",
                       "flipped": st_flip},
        "rsi": round(float(last["rsi"]), 2),
        "macd": {"macd": float(last["macd"]), "signal": float(last["macd_signal"]),
                 "hist": float(last["macd_hist"]),
                 "cross": ("BULLISH" if last["macd"] > last["macd_signal"] else "BEARISH"),
                 "hist_rising": bool(last["macd_hist"] > prev["macd_hist"])},
        "structure": {
            "state": structure["state"],
            "recent_labels": structure["recent_labels"],
            "last_swing_high": structure["last_swing_high"],
            "last_swing_low": structure["last_swing_low"],
            "points": [{"time": str(p["time"]), "type": p["type"],
                        "price": p["price"], "label": p["label"]}
                       for p in structure["points"][-10:]],
        },
        "volume": {
            "last": float(last["volume"]),
            "ma20": float(last["vol_ma20"]),
            "ratio": round(float(last["volume"]) / float(last["vol_ma20"]), 2)
            if last["vol_ma20"] else 0.0,
        },
    }


def run(candles: Dict[str, pd.DataFrame], cfg) -> Dict[str, Any]:
    """Çok zaman dilimli trend analizi.

    candles: {"ltf": df, "mtf": df, "htf": df}
    """
    cfg_trend = cfg.get("trend", {})
    result: Dict[str, Any] = {"timeframes": {}}

    for tf_key, df in candles.items():
        result["timeframes"][tf_key] = analyze_timeframe(df, cfg_trend)

    mtf = result["timeframes"].get("mtf", {})
    htf = result["timeframes"].get("htf", {})
    ltf = result["timeframes"].get("ltf", {})

    # Ana skor: MTF %50, HTF %30, LTF %20
    weights = {"mtf": 0.5, "htf": 0.3, "ltf": 0.2}
    total_w = 0.0
    acc = 0.0
    for k, w in weights.items():
        tf = result["timeframes"].get(k, {})
        if tf.get("available"):
            acc += tf["score"] * w
            total_w += w
    score = clamp(acc / total_w) if total_w else 0.0

    aligned = all(result["timeframes"].get(k, {}).get("label") == mtf.get("label")
                  for k in ("ltf", "htf")
                  if result["timeframes"].get(k, {}).get("available"))

    result.update({
        "score": round(score, 4),
        "label": ("BULLISH" if score > 0.35 else "BEARISH" if score < -0.35 else "NEUTRAL"),
        "mtf_aligned": bool(aligned),
        "price": mtf.get("price") or ltf.get("price"),
        "atr_pct": mtf.get("atr", {}).get("pct"),
        "adx": mtf.get("adx", {}).get("value"),
        "rsi": mtf.get("rsi"),
        "structure_state": mtf.get("structure", {}).get("state"),
        "summary": _summary(mtf, htf, ltf),
    })
    return result


def _summary(mtf: Dict, htf: Dict, ltf: Dict) -> str:
    if not mtf.get("available"):
        return "Yetersiz veri"
    parts = [
        f"1H {mtf['label']} (ADX {mtf['adx']['value']:.0f}, {mtf['adx']['strength']})",
        f"SuperTrend {mtf['supertrend']['direction']}",
        f"Yapı {mtf['structure']['state']}",
    ]
    if htf.get("available"):
        parts.append(f"4H {htf['label']}")
    if mtf["vwap"]["price_vs_daily_pct"] is not None:
        parts.append(f"Günlük VWAP'ın %{mtf['vwap']['price_vs_daily_pct']:+.2f} "
                     f"{'üstünde' if mtf['vwap']['price_vs_daily_pct'] > 0 else 'altında'}")
    return " · ".join(parts)


# ------------------------------------------------------------------ RSI/MACD
def rsi_score(trend_result: Dict[str, Any]) -> Dict[str, Any]:
    """RSI'yi ayrı bir skor bileşeni olarak değerlendirir."""
    mtf = trend_result.get("timeframes", {}).get("mtf", {})
    if not mtf.get("available"):
        return {"score": 0.0, "value": None, "state": "NA"}
    r = mtf["rsi"]
    # 50 = nötr; 70+ aşırı alım (momentum güçlü ama risk), 30- aşırı satım
    if r >= 70:
        score, state = 0.35, "AŞIRI ALIM"
    elif r >= 60:
        score, state = 0.8, "GÜÇLÜ"
    elif r >= 50:
        score, state = clamp((r - 50) / 12.5), "POZİTİF"
    elif r >= 40:
        score, state = clamp((r - 50) / 12.5), "NEGATİF"
    elif r >= 30:
        score, state = -0.8, "ZAYIF"
    else:
        score, state = -0.35, "AŞIRI SATIM"
    return {"score": round(float(score), 4), "value": r, "state": state}


def macd_score(trend_result: Dict[str, Any]) -> Dict[str, Any]:
    mtf = trend_result.get("timeframes", {}).get("mtf", {})
    if not mtf.get("available"):
        return {"score": 0.0, "state": "NA"}
    m = mtf["macd"]
    base = 0.6 if m["cross"] == "BULLISH" else -0.6
    momentum = 0.4 if m["hist_rising"] else -0.4
    score = clamp(base + momentum * (1 if base > 0 else 1))
    state = f"{m['cross']}/{'ARTAN' if m['hist_rising'] else 'AZALAN'}"
    return {"score": round(float(score), 4), "state": state,
            "hist": m["hist"], "cross": m["cross"]}
