"""Order Book Engine — ilk 100 seviye: duvarlar, dengesizlik, absorption, spoof.

Spoof/absorption tespiti iki ardışık order book fotoğrafının karşılaştırılmasıyla
yapılır; bu yüzden ilk taramada "veri birikiyor" uyarısı normaldir.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.binance import BinanceClient
from core.indicators import clamp
from core.logging_setup import log


def _levels(raw: List[List[str]], limit: int) -> List[List[float]]:
    return [[float(p), float(q)] for p, q in raw[:limit]]


def _walls(levels: List[List[float]], mid: float, multiplier: float,
           side: str) -> List[Dict[str, Any]]:
    if not levels:
        return []
    notionals = np.array([p * q for p, q in levels])
    avg = notionals.mean()
    if avg <= 0:
        return []
    out = []
    for (price, qty), notional in zip(levels, notionals):
        if notional >= avg * multiplier:
            out.append({
                "side": side,
                "price": price,
                "qty": qty,
                "notional": round(float(notional), 2),
                "x_average": round(float(notional / avg), 2),
                "distance_pct": round((price - mid) / mid * 100, 4),
            })
    out.sort(key=lambda x: x["notional"], reverse=True)
    return out[:6]


def _compare_walls(prev_walls: List[Dict[str, Any]], cur_levels: List[List[float]],
                   traded_prices: Optional[pd.DataFrame], side: str,
                   cfg_ob: Dict[str, Any]) -> Tuple[List[Dict], List[Dict]]:
    """Önceki duvarların akıbetine bakar.

    - İşlem görmeden kaybolduysa  -> SPOOF
    - Fiyat seviyeye değdiği hâlde duvar durduysa/eridiyse -> ABSORPTION
    """
    spoofs: List[Dict[str, Any]] = []
    absorptions: List[Dict[str, Any]] = []
    if not prev_walls:
        return spoofs, absorptions

    min_notional = cfg_ob.get("spoof_min_notional", 150000)
    vanish_pct = cfg_ob.get("spoof_vanish_pct", 0.65)
    cur_map = {round(p, 12): q for p, q in cur_levels}

    for w in prev_walls:
        if w["notional"] < min_notional:
            continue
        price = round(w["price"], 12)
        now_qty = cur_map.get(price, 0.0)
        shrink = 1 - (now_qty / w["qty"] if w["qty"] else 0)

        traded_here = 0.0
        if traded_prices is not None and not traded_prices.empty:
            tol = price * 0.0006
            hit = traded_prices[(traded_prices["price"] >= price - tol) &
                                (traded_prices["price"] <= price + tol)]
            traded_here = float(hit["qty"].sum())

        if shrink >= vanish_pct:
            consumed_ratio = traded_here / (w["qty"] * shrink) if w["qty"] * shrink else 0.0
            if consumed_ratio < 0.25:
                spoofs.append({**w, "shrink_pct": round(shrink * 100, 1),
                               "traded_qty": traded_here,
                               "verdict": "İşlem görmeden çekildi (spoof şüphesi)"})
            else:
                absorptions.append({**w, "shrink_pct": round(shrink * 100, 1),
                                    "traded_qty": traded_here,
                                    "verdict": "Emirler yenmiş (gerçek likidite)"})
        elif traded_here > w["qty"] * 0.5 and shrink < 0.3:
            absorptions.append({**w, "shrink_pct": round(shrink * 100, 1),
                                "traded_qty": traded_here,
                                "verdict": "Duvar yenilendi — absorption"})
    return spoofs, absorptions


def _book_icebergs(prev_levels: List[List[float]], cur_levels: List[List[float]],
                   side: str) -> List[Dict[str, Any]]:
    """Aynı seviyede miktarın sürekli aynı değere geri dolması = iceberg."""
    prev_map = {round(p, 12): q for p, q in prev_levels}
    out = []
    for price, qty in cur_levels:
        key = round(price, 12)
        if key in prev_map and qty > 0:
            if abs(prev_map[key] - qty) / max(qty, 1e-12) < 0.02 and price * qty > 50_000:
                out.append({"side": side, "price": price, "qty": qty,
                            "notional": round(price * qty, 2),
                            "note": "Seviye miktarı sabit kalıyor — yenilenen gizli emir"})
    return out[:4]


def run(symbol: str, client: BinanceClient, cfg, storage=None,
        futures_trades: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    cfg_ob = cfg.get("orderbook", {})
    depth_limit = cfg.get("data.depth_limit", 100)

    try:
        raw = client.depth(symbol, depth_limit)
    except Exception as exc:  # noqa: BLE001
        log.warning(f"{symbol} order book alınamadı: {exc}")
        return {"available": False, "score": 0.0, "error": str(exc)}

    bids = _levels(raw.get("bids", []), depth_limit)
    asks = _levels(raw.get("asks", []), depth_limit)
    if not bids or not asks:
        return {"available": False, "score": 0.0}

    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2
    spread_pct = (best_ask - best_bid) / mid * 100

    # ------------------------------------------------- yakın likidite dengesi
    band = cfg_ob.get("imbalance_depth_pct", 0.5) / 100
    lo, hi = mid * (1 - band), mid * (1 + band)
    bid_near = sum(p * q for p, q in bids if p >= lo)
    ask_near = sum(p * q for p, q in asks if p <= hi)
    near_total = bid_near + ask_near
    near_imb = (bid_near - ask_near) / near_total if near_total else 0.0

    bid_total = sum(p * q for p, q in bids)
    ask_total = sum(p * q for p, q in asks)
    full_imb = (bid_total - ask_total) / (bid_total + ask_total) if (bid_total + ask_total) else 0.0

    mult = cfg_ob.get("wall_multiplier", 4.0)
    bid_walls = _walls(bids, mid, mult, "bid")
    ask_walls = _walls(asks, mid, mult, "ask")

    # --------------------------------------------- önceki fotoğrafla kıyasla
    prev = storage.previous_depth(symbol) if storage else None
    spoofs: List[Dict[str, Any]] = []
    absorptions: List[Dict[str, Any]] = []
    icebergs: List[Dict[str, Any]] = []
    compare_note = "Karşılaştırma için ikinci tarama bekleniyor"

    if prev:
        prev_bids, prev_asks = prev["bids"], prev["asks"]
        prev_mid = prev["mid"]
        prev_bid_walls = _walls(prev_bids, prev_mid, mult, "bid")
        prev_ask_walls = _walls(prev_asks, prev_mid, mult, "ask")

        trades_df = futures_trades[["price", "qty"]] if (futures_trades is not None
                                                         and not futures_trades.empty) else None
        s1, a1 = _compare_walls(prev_bid_walls, bids, trades_df, "bid", cfg_ob)
        s2, a2 = _compare_walls(prev_ask_walls, asks, trades_df, "ask", cfg_ob)
        spoofs, absorptions = s1 + s2, a1 + a2
        icebergs = _book_icebergs(prev_bids, bids, "bid") + _book_icebergs(prev_asks, asks, "ask")
        compare_note = f"Önceki fotoğraf: {prev['ts']}"

    if storage:
        storage.save_depth(symbol, mid, bids, asks)

    # ------------------------------------------------------------- skorlama
    score = clamp(near_imb * 2.0) * 0.55 + clamp(full_imb * 2.0) * 0.20

    wall_bias = 0.0
    if bid_walls or ask_walls:
        bw = sum(w["notional"] for w in bid_walls)
        aw = sum(w["notional"] for w in ask_walls)
        if bw + aw > 0:
            wall_bias = (bw - aw) / (bw + aw)
    score += clamp(wall_bias) * 0.15

    # Spoof edilen duvarlar ters sinyaldir: sahte bid duvarı = aslında satıcı var
    for s in spoofs:
        score += -0.08 if s["side"] == "bid" else 0.08
    for a in absorptions:
        score += 0.08 if a["side"] == "ask" else -0.08   # ask'ta absorption = alıcı yiyor

    score = clamp(score)

    return {
        "available": True,
        "score": round(float(score), 4),
        "mid_price": mid,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": round(spread_pct, 5),
        "levels_read": len(bids),
        "near_band_pct": cfg_ob.get("imbalance_depth_pct", 0.5),
        "bid_liquidity_near": round(bid_near, 2),
        "ask_liquidity_near": round(ask_near, 2),
        "near_imbalance_pct": round(near_imb * 100, 2),
        "bid_liquidity_total": round(bid_total, 2),
        "ask_liquidity_total": round(ask_total, 2),
        "full_imbalance_pct": round(full_imb * 100, 2),
        "bid_walls": bid_walls,
        "ask_walls": ask_walls,
        "spoofs": spoofs,
        "absorptions": absorptions,
        "icebergs": icebergs,
        "compare_note": compare_note,
        "state": ("ALICI AĞIRLIKLI" if near_imb > 0.1 else
                  "SATICI AĞIRLIKLI" if near_imb < -0.1 else "DENGELİ"),
        "summary": _summary(near_imb, bid_walls, ask_walls, spoofs, absorptions),
        "depth_chart": {
            "bids": [{"price": p, "qty": q, "notional": p * q} for p, q in bids],
            "asks": [{"price": p, "qty": q, "notional": p * q} for p, q in asks],
        },
    }


def _summary(near_imb, bid_walls, ask_walls, spoofs, absorptions) -> str:
    parts = [f"Yakın likidite dengesi %{near_imb * 100:+.1f}"]
    if bid_walls:
        parts.append(f"{len(bid_walls)} bid duvarı (en büyüğü {bid_walls[0]['notional']:,.0f} USDT)")
    if ask_walls:
        parts.append(f"{len(ask_walls)} ask duvarı (en büyüğü {ask_walls[0]['notional']:,.0f} USDT)")
    if spoofs:
        parts.append(f"{len(spoofs)} spoof şüphesi")
    if absorptions:
        parts.append(f"{len(absorptions)} absorption")
    return " · ".join(parts)
