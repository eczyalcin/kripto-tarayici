"""Trade Setup Engine — skor + yapı + ATR'den somut işlem planı üretir.

Giriş bölgesi mümkün olduğunca smart-money seviyelerine (FVG / Order Block / VWAP)
oturtulur; stop yapısal seviyenin ötesine, hedefler R katlarına ve yakın yapıya göre
belirlenir.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from engines.risk import position_size


def _round_tick(value: float, tick: float, precision: int) -> float:
    if not value:
        return value
    if tick and tick > 0:
        value = round(value / tick) * tick
    return round(value, precision)


def _nearest_levels(sm: Dict[str, Any], direction: str, price: float) -> List[Dict[str, Any]]:
    """Giriş için aday smart-money bölgeleri."""
    out: List[Dict[str, Any]] = []
    fvg = sm.get("fvg", {})
    obs = sm.get("order_blocks", {}).get("fresh", [])

    want = "bullish" if direction == "LONG" else "bearish"
    for f in fvg.get("open", []):
        if f["direction"] != want:
            continue
        if direction == "LONG" and f["top"] <= price * 1.002:
            out.append({"kind": "FVG", "low": f["bottom"], "high": f["top"],
                        "distance_pct": f["distance_pct"]})
        elif direction == "SHORT" and f["bottom"] >= price * 0.998:
            out.append({"kind": "FVG", "low": f["bottom"], "high": f["top"],
                        "distance_pct": f["distance_pct"]})

    for o in obs:
        if o["direction"] != want:
            continue
        if direction == "LONG" and o["top"] <= price * 1.002:
            out.append({"kind": "OB", "low": o["bottom"], "high": o["top"],
                        "distance_pct": o["distance_pct"]})
        elif direction == "SHORT" and o["bottom"] >= price * 0.998:
            out.append({"kind": "OB", "low": o["bottom"], "high": o["top"],
                        "distance_pct": o["distance_pct"]})

    out.sort(key=lambda x: abs(x["distance_pct"]))
    return out[:3]


def _snap_target(target: float, candidates: List[float], direction: str,
                 tolerance_pct: float = 1.2) -> float:
    """Hedefi yakınındaki yapısal seviyeye çeker (biraz önüne koyar)."""
    for c in candidates:
        if not c:
            continue
        diff_pct = abs(c - target) / target * 100
        if diff_pct <= tolerance_pct:
            return c * (0.999 if direction == "LONG" else 1.001)
    return target


def run(symbol: str, engines: Dict[str, Any], score: Dict[str, Any],
        risk: Dict[str, Any], cfg, tick: float = 0.0,
        precision: int = 6) -> Dict[str, Any]:
    s = cfg.get("setup", {})
    min_score = s.get("min_score_for_setup", 55)
    trend = engines.get("trend", {})
    sm = engines.get("smart_money", {})
    deriv = engines.get("derivatives", {})
    book = engines.get("orderbook", {})

    price = trend.get("price") or book.get("mid_price")
    mtf = trend.get("timeframes", {}).get("mtf", {})
    atr = mtf.get("atr", {}).get("value")

    long_score = score.get("long_score", 50)
    short_score = score.get("short_score", 50)

    if long_score >= min_score:
        direction = "LONG"
        conviction = long_score
    elif short_score >= min_score:
        direction = "SHORT"
        conviction = short_score
    else:
        return {
            "available": False,
            "direction": "NONE",
            "reason": f"Skor nötr bölgede (Long {long_score}/100). "
                      f"Setup için en az {min_score} gerekiyor.",
            "recommendation": "BEKLE",
        }

    if not price or not atr or atr <= 0:
        return {"available": False, "direction": direction,
                "reason": "Fiyat/ATR verisi eksik", "recommendation": "BEKLE"}

    # ------------------------------------------------------------- giriş
    zones = _nearest_levels(sm, direction, price)
    pullback = s.get("entry_pullback_atr", 0.35) * atr
    vwap_d = mtf.get("vwap", {}).get("daily")

    if zones:
        z = zones[0]
        entry_low, entry_high = min(z["low"], z["high"]), max(z["low"], z["high"])
        entry = (entry_low + entry_high) / 2
        entry_basis = f"{z['kind']} bölgesi"
    else:
        if direction == "LONG":
            entry_high = price
            entry_low = price - pullback
            if vwap_d and price > vwap_d > price - 2 * atr:
                entry_low = min(entry_low, vwap_d)
        else:
            entry_low = price
            entry_high = price + pullback
            if vwap_d and price < vwap_d < price + 2 * atr:
                entry_high = max(entry_high, vwap_d)
        entry = (entry_low + entry_high) / 2
        entry_basis = "ATR geri çekilmesi" + (" + Günlük VWAP" if vwap_d else "")

    # -------------------------------------------------------------- stop
    stop_mult = s.get("stop_atr_multiplier", 1.5)
    struct = mtf.get("structure", {})
    swing_low = struct.get("last_swing_low")
    swing_high = struct.get("last_swing_high")

    if direction == "LONG":
        atr_stop = entry - stop_mult * atr
        struct_stop = (swing_low - 0.25 * atr) if swing_low and swing_low < entry else None
        stop = min(atr_stop, struct_stop) if struct_stop else atr_stop
        stop_basis = "Swing low altı" if struct_stop and struct_stop <= atr_stop else f"{stop_mult}x ATR"
    else:
        atr_stop = entry + stop_mult * atr
        struct_stop = (swing_high + 0.25 * atr) if swing_high and swing_high > entry else None
        stop = max(atr_stop, struct_stop) if struct_stop else atr_stop
        stop_basis = "Swing high üstü" if struct_stop and struct_stop >= atr_stop else f"{stop_mult}x ATR"

    r_distance = abs(entry - stop)
    if r_distance <= 0:
        return {"available": False, "direction": direction,
                "reason": "Geçersiz stop mesafesi", "recommendation": "BEKLE"}

    # ------------------------------------------------------------ hedefler
    multiples = s.get("tp_r_multiples", [1.5, 2.5, 4.0])
    structural: List[float] = []
    if direction == "LONG":
        if swing_high:
            structural.append(swing_high)
        structural += [f["bottom"] for f in sm.get("fvg", {}).get("open", [])
                       if f["direction"] == "bearish" and f["bottom"] > entry]
        structural += [w["price"] for w in book.get("ask_walls", []) if w["price"] > entry]
    else:
        if swing_low:
            structural.append(swing_low)
        structural += [f["top"] for f in sm.get("fvg", {}).get("open", [])
                       if f["direction"] == "bullish" and f["top"] < entry]
        structural += [w["price"] for w in book.get("bid_walls", []) if w["price"] < entry]

    targets: List[Dict[str, Any]] = []
    for i, m in enumerate(multiples, start=1):
        raw = entry + r_distance * m if direction == "LONG" else entry - r_distance * m
        snapped = _snap_target(raw, structural, direction)
        targets.append({
            "name": f"TP{i}",
            "price": _round_tick(snapped, tick, precision),
            "r_multiple": m,
            "gain_pct": round((snapped - entry) / entry * 100 * (1 if direction == "LONG" else -1), 3),
            "snapped": abs(snapped - raw) > 1e-12,
        })

    rr = targets[0]["r_multiple"] if targets else 0.0
    min_rr = s.get("min_rr", 1.2)

    # ------------------------------------------------------------ boyutlama
    entry_r = _round_tick(entry, tick, precision)
    stop_r = _round_tick(stop, tick, precision)
    sizing = position_size(entry_r, stop_r, risk.get("risk_usdt", 0))

    # -------------------------------------------------------- olasılık tahmini
    # Skor + güven karışımı; kalibre edilmiş bir olasılık değil, göreli bir güç ölçüsüdür.
    probability = round(min(95.0, 0.65 * conviction + 0.35 * score.get("confidence", 50)), 1)

    invalidation: List[str] = []
    if direction == "LONG":
        if swing_low:
            invalidation.append(f"1H swing low {_round_tick(swing_low, tick, precision)} altında kapanış")
        invalidation.append("SuperTrend yönünün DOWN'a dönmesi")
        invalidation.append("OI artarken fiyatın düşmesi (yeni short girişi)")
    else:
        if swing_high:
            invalidation.append(f"1H swing high {_round_tick(swing_high, tick, precision)} üstünde kapanış")
        invalidation.append("SuperTrend yönünün UP'a dönmesi")
        invalidation.append("OI artarken fiyatın yükselmesi (yeni long girişi)")

    return {
        "available": True,
        "symbol": symbol,
        "direction": direction,
        "recommendation": score.get("decision", direction),
        "trend": trend.get("label", "NEUTRAL"),
        "probability": probability,
        "confidence": score.get("confidence"),
        "price": price,
        "entry": entry_r,
        "entry_zone": [_round_tick(min(entry_low, entry_high), tick, precision),
                       _round_tick(max(entry_low, entry_high), tick, precision)],
        "entry_basis": entry_basis,
        "stop": stop_r,
        "stop_basis": stop_basis,
        "stop_distance_pct": sizing["stop_distance_pct"],
        "targets": targets,
        "risk_reward": rr,
        "rr_ok": rr >= min_rr,
        "position": {
            "risk_usdt": risk.get("risk_usdt"),
            "qty": sizing["qty"],
            "notional_usdt": sizing["notional"],
            "suggested_max_leverage": risk.get("suggested_max_leverage"),
        },
        "context": {
            "funding": deriv.get("funding", {}).get("health", "NA"),
            "funding_pct": deriv.get("funding", {}).get("current_pct"),
            "oi": deriv.get("open_interest", {}).get("trend", "NA"),
            "oi_change_1h": deriv.get("open_interest", {}).get("change_1h_pct"),
            "cvd": engines.get("order_flow", {}).get("label", "NA"),
            "whales": engines.get("whale", {}).get("state", "NA"),
            "risk": risk.get("level", "NA"),
            "atr_pct": mtf.get("atr", {}).get("pct"),
        },
        "invalidation": invalidation,
    }
