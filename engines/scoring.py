"""AI Skor Sistemi — her motorun ürettiği ham skoru (-1..+1) ağırlıklandırır.

Çıktı:
  long_score  0-100
  short_score 100 - long_score
  decision    STRONG LONG / LONG / WEAK LONG / NÖTR / WEAK SHORT / SHORT / STRONG SHORT
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.indicators import clamp, tr_lower
from engines import trend as trend_engine

# Gösterge adlarının kullanıcıya gösterilecek karşılıkları
LABELS = {
    "trend": "Trend",
    "open_interest": "Open Interest",
    "funding": "Funding",
    "cvd": "CVD / Order Flow",
    "rsi": "RSI",
    "macd": "MACD",
    "orderbook": "Order Book",
    "whale": "Whale",
    "liquidation": "Likidasyon",
    "smart_money": "Smart Money",
}


def _get(d: Optional[Dict], *path, default: float = 0.0) -> float:
    node: Any = d
    for p in path:
        if not isinstance(node, dict) or p not in node:
            return default
        node = node[p]
    try:
        return float(node)
    except (TypeError, ValueError):
        return default


def collect_components(engines: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Her bileşen için ham skor (-1..+1) ve kısa gerekçe üretir."""
    trend = engines.get("trend", {})
    deriv = engines.get("derivatives", {})
    flow = engines.get("order_flow", {})
    book = engines.get("orderbook", {})
    whale = engines.get("whale", {})
    sm = engines.get("smart_money", {})

    rsi_part = trend_engine.rsi_score(trend)
    macd_part = trend_engine.macd_score(trend)

    # OI bileşeni, büyük hesap Long/Short oranıyla harmanlanır
    oi_raw = _get(deriv, "open_interest", "score")
    ls_raw = _get(deriv, "long_short", "score")
    oi_component = clamp(oi_raw * 0.7 + ls_raw * 0.3)

    # CVD bileşeni, Binance taker buy/sell dengesiyle harmanlanır
    flow_raw = _get(flow, "score")
    taker_raw = _get(deriv, "taker", "score")
    cvd_component = clamp(flow_raw * 0.7 + taker_raw * 0.3)

    comps: Dict[str, Dict[str, Any]] = {
        "trend": {
            "raw": clamp(_get(trend, "score")),
            "detail": trend.get("summary", ""),
            "available": bool(trend.get("timeframes")),
        },
        "open_interest": {
            "raw": oi_component,
            "detail": _oi_detail(deriv),
            "available": "error" not in deriv.get("open_interest", {}),
        },
        "funding": {
            "raw": clamp(_get(deriv, "funding", "score")),
            "detail": _funding_detail(deriv),
            "available": "error" not in deriv.get("funding", {}),
        },
        "cvd": {
            "raw": cvd_component,
            "detail": flow.get("summary", ""),
            "available": bool(flow.get("available")),
        },
        "rsi": {
            "raw": clamp(rsi_part["score"]),
            "detail": f"RSI {rsi_part.get('value')} — {rsi_part.get('state')}",
            "available": rsi_part.get("value") is not None,
        },
        "macd": {
            "raw": clamp(macd_part["score"]),
            "detail": f"MACD {macd_part.get('state')}",
            "available": macd_part.get("state") != "NA",
        },
        "orderbook": {
            "raw": clamp(_get(book, "score")),
            "detail": book.get("summary", ""),
            "available": bool(book.get("available")),
        },
        "whale": {
            "raw": clamp(_get(whale, "score")),
            "detail": whale.get("summary", ""),
            "available": bool(whale.get("available")),
        },
        "liquidation": {
            "raw": clamp(_get(deriv, "liquidations", "score")),
            "detail": _liq_detail(deriv),
            "available": bool(deriv.get("liquidations", {}).get("available")),
        },
        "smart_money": {
            "raw": clamp(_get(sm, "score")),
            "detail": sm.get("summary", ""),
            "available": bool(sm.get("available")),
        },
    }
    return comps


def _oi_detail(deriv: Dict) -> str:
    oi = deriv.get("open_interest", {})
    if "error" in oi:
        return "Veri yok"
    ch = oi.get("change_1h_pct")
    interp = oi.get("interpretation_1h", {})
    ls = deriv.get("long_short", {})
    txt = f"OI 1s %{ch:+.2f} — {interp.get('state', '')}" if ch is not None else "OI verisi yok"
    if ls.get("top_positions_ratio"):
        txt += f" | Büyük hesap L/S {ls['top_positions_ratio']:.2f}"
    return txt


def _funding_detail(deriv: Dict) -> str:
    f = deriv.get("funding", {})
    if "error" in f or f.get("current_pct") is None:
        return "Veri yok"
    return (f"%{f['current_pct']:+.4f} ({f['health']}, yıllık ~%{f['annualized_pct']:.1f}) "
            f"· {f['bias']}")


def _liq_detail(deriv: Dict) -> str:
    liq = deriv.get("liquidations", {})
    if not liq.get("available"):
        return liq.get("note", "Likidasyon verisi yok")
    return (f"Long {liq['long_usdt']:,.0f} / Short {liq['short_usdt']:,.0f} USDT "
            f"({liq['hours']}s)" + (f" · {liq['squeeze']}" if liq["squeeze"] != "NONE" else ""))


def decide(long_score: float, thresholds: Dict[str, float]) -> str:
    if long_score >= thresholds.get("strong_long", 75):
        return "STRONG LONG"
    if long_score >= thresholds.get("long", 62):
        return "LONG"
    if long_score >= thresholds.get("weak_long", 55):
        return "WEAK LONG"
    if long_score <= thresholds.get("strong_short", 25):
        return "STRONG SHORT"
    if long_score <= thresholds.get("short", 38):
        return "SHORT"
    if long_score <= thresholds.get("weak_short", 45):
        return "WEAK SHORT"
    return "NÖTR"


def run(engines: Dict[str, Any], cfg) -> Dict[str, Any]:
    weights: Dict[str, float] = dict(cfg.get("scoring.weights", {}))
    thresholds: Dict[str, float] = dict(cfg.get("scoring.thresholds", {}))
    comps = collect_components(engines)

    rows: List[Dict[str, Any]] = []
    total_weight = 0.0
    weighted_sum = 0.0
    available_weight = 0.0

    for key, w in weights.items():
        c = comps.get(key)
        if c is None:
            continue
        raw = c["raw"] if c["available"] else 0.0
        points = raw * w
        weighted_sum += points
        total_weight += w
        if c["available"]:
            available_weight += w
        rows.append({
            "key": key,
            "name": LABELS.get(key, key),
            "weight": w,
            "raw": round(raw, 4),
            "points": round(points, 2),
            "max_points": w,
            "available": c["available"],
            "detail": c["detail"],
            "direction": ("LONG" if raw > 0.05 else "SHORT" if raw < -0.05 else "NÖTR"),
        })

    net = weighted_sum / total_weight if total_weight else 0.0     # -1 .. +1
    long_score = round(50 + 50 * net, 1)
    long_score = max(0.0, min(100.0, long_score))
    short_score = round(100 - long_score, 1)
    decision = decide(long_score, thresholds)

    # Güven: veri kapsaması + bileşenler arası uyum
    coverage = available_weight / total_weight if total_weight else 0.0
    directions = [r["raw"] for r in rows if r["available"] and abs(r["raw"]) > 0.05]
    if directions:
        agree = sum(1 for d in directions if (d > 0) == (net > 0)) / len(directions)
    else:
        agree = 0.5
    confidence = round(clamp(coverage * 0.5 + agree * 0.5, 0, 1) * 100, 1)

    rows_sorted = sorted(rows, key=lambda r: abs(r["points"]), reverse=True)

    return {
        "long_score": long_score,
        "short_score": short_score,
        "net": round(net, 4),
        "decision": decision,
        "confidence": confidence,
        "coverage_pct": round(coverage * 100, 1),
        "agreement_pct": round(agree * 100, 1),
        "components": rows,
        "top_drivers": rows_sorted[:4],
        "total_points": round(weighted_sum, 2),
        "total_weight": total_weight,
        "answer": _answer(engines, decision, long_score),
    }


def _answer(engines: Dict[str, Any], decision: str, long_score: float) -> str:
    """'Büyük para şu anda ne yapıyor?' sorusuna tek cümlelik cevap."""
    deriv = engines.get("derivatives", {})
    whale = engines.get("whale", {})
    flow = engines.get("order_flow", {})

    oi_state = deriv.get("open_interest", {}).get("interpretation_1h", {}).get("state", "")
    whale_state = whale.get("state", "")
    div = flow.get("divergence_note", "")
    ls = deriv.get("long_short", {}).get("top_positions_ratio")

    bits: List[str] = []
    if oi_state and oi_state != "NA":
        bits.append(f"pozisyonlanma: {tr_lower(oi_state)}")
    if ls:
        taraf = "long" if ls > 1 else "short"
        bits.append(f"büyük hesaplar {taraf} ağırlıklı (L/S {ls:.2f})")
    if whale_state and whale_state != "NÖTR":
        bits.append(f"balinalar {tr_lower(whale_state)} yapıyor")
    if div:
        bits.append(tr_lower(div))

    core = "; ".join(bits) if bits else "belirgin bir yön yok"
    return f"{decision} (Long {long_score:.0f}/100) — {core}."
