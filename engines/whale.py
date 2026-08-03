"""Whale Engine — büyük emirler, iceberg ve gizli birikim tespiti.

Kaynak: agg-trade akışı. Binance agg-trade'leri aynı fiyat/yön/zamandaki emirleri
birleştirdiği için tek bir büyük agg-trade, tek bir büyük piyasa emrine karşılık gelir.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.indicators import clamp


def _tier_label(t: float) -> str:
    if t >= 1_000_000:
        return f"{t / 1_000_000:.1f}M+".replace(".0M", "M")
    if t >= 1_000:
        return f"{t / 1_000:.0f}k+"
    return f"{t:.0f}+"


def effective_tiers(trades: pd.DataFrame, tiers: List[float],
                    cfg_w: Dict[str, Any]) -> Dict[str, Any]:
    """Sembolün gerçek işlem büyüklüğüne göre balina eşiklerini ölçekler.

    1000SHIBUSDT gibi paritelerde tek bir agg-trade nadiren 100k USDT'yi geçer;
    sabit eşikler kullanılırsa balina motoru hep boş döner. Bu yüzden yeterli
    sayıda işlem eşiği aşmıyorsa eşikler, o sembolün işlem dağılımının üst
    yüzdeliğine göre yeniden hesaplanır.
    """
    tiers = sorted(tiers)
    if not cfg_w.get("auto_scale", True) or trades is None or trades.empty:
        return {"tiers": tiers, "scaled": False}

    min_hits = cfg_w.get("auto_min_hits", 5)
    if int((trades["notional"] >= tiers[0]).sum()) >= min_hits:
        return {"tiers": tiers, "scaled": False}

    pct = cfg_w.get("auto_percentile", 99.0)
    floor = cfg_w.get("min_tier_floor", 5000)
    base = float(np.percentile(trades["notional"], pct))
    base = max(base, floor)
    ratios = [t / tiers[0] for t in tiers]
    return {"tiers": [round(base * r, 2) for r in ratios], "scaled": True,
            "base": round(base, 2), "percentile": pct}


def _tier_stats(trades: pd.DataFrame, tiers: List[float]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for t in tiers:
        sub = trades[trades["notional"] >= t]
        buy = float(sub.loc[sub["side"] == "buy", "notional"].sum())
        sell = float(sub.loc[sub["side"] == "sell", "notional"].sum())
        label = _tier_label(t)
        out[label] = {
            "threshold_usdt": t,
            "count": int(len(sub)),
            "buy_usdt": round(buy, 2),
            "sell_usdt": round(sell, 2),
            "delta_usdt": round(buy - sell, 2),
            "buy_count": int((sub["side"] == "buy").sum()),
            "sell_count": int((sub["side"] == "sell").sum()),
        }
    return out


def detect_iceberg(trades: pd.DataFrame, cfg_w: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Aynı miktarın kısa aralıklarla tekrar tekrar işlem görmesi = gizli (iceberg) emir."""
    if trades is None or trades.empty:
        return []

    min_repeats = cfg_w.get("iceberg_min_repeats", 5)
    tol = cfg_w.get("iceberg_qty_tolerance", 0.01)
    window = pd.Timedelta(seconds=cfg_w.get("iceberg_window_seconds", 300))

    df = trades.copy()
    # Miktarları toleransa göre yuvarlayıp kovalara ayır
    df["bucket"] = (df["qty"] / (df["qty"] * tol).clip(lower=1e-12)).round() * tol
    df["qty_key"] = df["qty"].apply(lambda q: round(q, max(0, 8 - len(str(int(max(q, 1)))))))

    results: List[Dict[str, Any]] = []
    for (qty_key, side), grp in df.groupby(["qty_key", "side"]):
        if len(grp) < min_repeats:
            continue
        grp = grp.sort_values("time")
        span = grp["time"].iloc[-1] - grp["time"].iloc[0]
        if span > window * 4:
            # Çok geniş zamana yayılmışsa iceberg değil, rutin işlem büyüklüğüdür
            continue
        notional = float(grp["notional"].sum())
        if notional < 20_000:
            continue
        results.append({
            "qty": float(qty_key),
            "side": side,
            "repeats": int(len(grp)),
            "total_notional": round(notional, 2),
            "avg_price": round(float(grp["price"].mean()), 10),
            "span_seconds": round(span.total_seconds(), 1),
            "first": str(grp["time"].iloc[0]),
            "last": str(grp["time"].iloc[-1]),
        })

    results.sort(key=lambda x: x["total_notional"], reverse=True)
    return results[:5]


def _analyze_market(trades: pd.DataFrame, tiers: List[float],
                    cfg_w: Dict[str, Any], market: str) -> Dict[str, Any]:
    if trades is None or trades.empty:
        return {"available": False, "market": market, "score": 0.0}

    scaling = effective_tiers(trades, tiers, cfg_w)
    tiers = scaling["tiers"]
    tier_stats = _tier_stats(trades, tiers)
    base_tier = tiers[0]
    whales = trades[trades["notional"] >= base_tier].copy()

    buy = float(whales.loc[whales["side"] == "buy", "notional"].sum())
    sell = float(whales.loc[whales["side"] == "sell", "notional"].sum())
    total = buy + sell
    imbalance = (buy - sell) / total if total else 0.0

    # Büyük dilimler daha ağır: 1M+ işlem 100k+'dan güçlü sinyal
    weighted = 0.0
    weight_sum = 0.0
    for i, t in enumerate(tiers):
        st = tier_stats[_tier_label(t)]
        tot = st["buy_usdt"] + st["sell_usdt"]
        if tot <= 0:
            continue
        w = (i + 1) ** 1.5
        weighted += (st["delta_usdt"] / tot) * w
        weight_sum += w
    weighted_imb = weighted / weight_sum if weight_sum else imbalance

    icebergs = detect_iceberg(trades, cfg_w)
    ice_bias = 0.0
    if icebergs:
        ib = sum(i["total_notional"] for i in icebergs if i["side"] == "buy")
        isl = sum(i["total_notional"] for i in icebergs if i["side"] == "sell")
        if ib + isl > 0:
            ice_bias = (ib - isl) / (ib + isl)

    score = clamp(weighted_imb * 1.4 * 0.8 + ice_bias * 0.2)

    largest = whales.nlargest(10, "notional")[["time", "side", "price", "qty", "notional"]]
    largest_records = [{"time": str(r["time"]), "side": r["side"], "price": float(r["price"]),
                        "qty": float(r["qty"]), "notional": round(float(r["notional"]), 2)}
                       for _, r in largest.iterrows()]

    return {
        "available": True,
        "market": market,
        "tiers": tier_stats,
        "tier_scaling": scaling,
        "whale_buy_usdt": round(buy, 2),
        "whale_sell_usdt": round(sell, 2),
        "whale_delta_usdt": round(buy - sell, 2),
        "imbalance_pct": round(imbalance * 100, 2),
        "weighted_imbalance": round(weighted_imb, 3),
        "whale_count": int(len(whales)),
        "largest_trades": largest_records,
        "icebergs": icebergs,
        "score": round(float(score), 3),
        "state": ("BİRİKİM" if imbalance > 0.15 else
                  "DAĞITIM" if imbalance < -0.15 else "NÖTR"),
    }


def run(symbol: str, cfg, order_flow: Dict[str, Any], storage=None) -> Dict[str, Any]:
    cfg_w = cfg.get("whale", {})
    tiers = cfg_w.get("tiers", [100000, 250000, 500000, 1000000])

    fut_trades = order_flow.get("_futures_trades")
    spot_trades = order_flow.get("_spot_trades")

    fut = _analyze_market(fut_trades, tiers, cfg_w, "futures")
    spot = _analyze_market(spot_trades, tiers, cfg_w, "spot")

    scores, weights = [], []
    if fut.get("available"):
        scores.append(fut["score"]); weights.append(0.55)
    if spot.get("available"):
        scores.append(spot["score"]); weights.append(0.45)
    score = clamp(sum(s * w for s, w in zip(scores, weights)) / sum(weights)) if scores else 0.0

    # Kayıt/alarm eşiği: ölçeklenmişse sembolün kendi eşiği kullanılır
    eff = (fut.get("tier_scaling") or spot.get("tier_scaling") or {})
    eff_tiers = eff.get("tiers", tiers)
    record_threshold = eff_tiers[0]
    alert_threshold = eff_tiers[1] if eff.get("scaled") else None

    # ---------------------------------------------------- veritabanına kayıt
    new_whales: List[Dict[str, Any]] = []
    if storage:
        for market, trades in (("futures", fut_trades), ("spot", spot_trades)):
            if trades is None or trades.empty:
                continue
            big = trades[trades["notional"] >= record_threshold]
            for _, r in big.iterrows():
                rec = {"time": str(r["time"]), "side": r["side"], "price": float(r["price"]),
                       "qty": float(r["qty"]), "notional": float(r["notional"])}
                if not storage.whale_trade_exists(symbol, rec["time"], rec["notional"]):
                    storage.add_whale_trades(symbol, [rec], market)
                    new_whales.append({**rec, "market": market})

    total_delta = (fut.get("whale_delta_usdt", 0.0) if fut.get("available") else 0.0) + \
                  (spot.get("whale_delta_usdt", 0.0) if spot.get("available") else 0.0)

    return {
        "available": fut.get("available") or spot.get("available"),
        "score": round(float(score), 4),
        "futures": fut,
        "spot": spot,
        "total_whale_delta_usdt": round(total_delta, 2),
        "new_whale_trades": new_whales,
        "tier_scaling": eff,
        "record_threshold_usdt": record_threshold,
        "alert_threshold_usdt": alert_threshold,
        "state": ("BİRİKİM" if score > 0.2 else "DAĞITIM" if score < -0.2 else "NÖTR"),
        "summary": _summary(fut, spot, total_delta),
    }


def _summary(fut: Dict, spot: Dict, total_delta: float) -> str:
    parts: List[str] = []
    if fut.get("available"):
        sc = fut.get("tier_scaling", {})
        if sc.get("scaled"):
            parts.append(f"Eşik sembole göre ölçeklendi (≥{sc['base']:,.0f} USDT)")
        parts.append(f"Vadeli balina deltası {fut['whale_delta_usdt']:+,.0f} USDT "
                     f"({fut['whale_count']} işlem, {fut['state']})")
    if spot.get("available"):
        parts.append(f"Spot balina deltası {spot['whale_delta_usdt']:+,.0f} USDT ({spot['state']})")
    ice = (fut.get("icebergs") or []) + (spot.get("icebergs") or [])
    if ice:
        parts.append(f"{len(ice)} iceberg şüphesi")
    return " · ".join(parts) if parts else "Balina aktivitesi yok"
