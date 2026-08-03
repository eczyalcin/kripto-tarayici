"""Order Flow / Spot Engine — Spot CVD vs Futures CVD.

Soru: "Gerçek para mı alıyor, yoksa kaldıraçlı vadeli mi?"
Karşılaştırma USDT (notional) cinsinden yapılır; böylece 1000SHIB gibi çarpanlı
vadeli semboller spot karşılığıyla aynı ölçekte kıyaslanır.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.binance import BinanceClient
from core.indicators import clamp
from core.logging_setup import log


def _cvd_frame(trades: pd.DataFrame) -> Dict[str, Any]:
    """Agresif alım/satım ayrıştırması ve kümülatif delta serisi."""
    if trades is None or trades.empty:
        return {"available": False, "buy": 0.0, "sell": 0.0, "delta": 0.0,
                "cvd": 0.0, "series": [], "trades": 0}

    buy = float(trades.loc[trades["side"] == "buy", "notional"].sum())
    sell = float(trades.loc[trades["side"] == "sell", "notional"].sum())
    signed = np.where(trades["side"].to_numpy() == "buy",
                      trades["notional"].to_numpy(), -trades["notional"].to_numpy())
    cvd_series = np.cumsum(signed)

    tmp = trades[["time"]].copy()
    tmp["signed"] = signed
    per_min = tmp.set_index("time").resample("1min")["signed"].sum().fillna(0.0)
    cum = per_min.cumsum()

    total = buy + sell
    return {
        "available": True,
        "buy": buy,
        "sell": sell,
        "delta": buy - sell,
        "imbalance_pct": round((buy - sell) / total * 100, 2) if total else 0.0,
        "cvd": float(cvd_series[-1]) if len(cvd_series) else 0.0,
        "trades": int(len(trades)),
        "window_minutes": round((trades["time"].iloc[-1] - trades["time"].iloc[0]).total_seconds() / 60, 1),
        "start": str(trades["time"].iloc[0]),
        "end": str(trades["time"].iloc[-1]),
        "series": [{"time": str(t), "cvd": float(v)} for t, v in cum.items()],
        "avg_buy_size": round(float(trades.loc[trades["side"] == "buy", "notional"].mean() or 0), 2),
        "avg_sell_size": round(float(trades.loc[trades["side"] == "sell", "notional"].mean() or 0), 2),
    }


def _slope(series: List[Dict[str, Any]], tail: int = 15) -> float:
    """CVD serisinin son eğilimi (normalize edilmiş eğim)."""
    if len(series) < 4:
        return 0.0
    vals = np.array([p["cvd"] for p in series[-tail:]], dtype=float)
    x = np.arange(len(vals))
    if vals.std() == 0:
        return 0.0
    slope = np.polyfit(x, vals, 1)[0]
    scale = max(abs(vals).max(), 1.0)
    return float(np.clip(slope / scale * len(vals), -1, 1))


def run(symbol: str, client: BinanceClient, cfg,
        spot_map: Optional[Dict[str, Any]] = None,
        futures_trades: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    limit = cfg.get("data.agg_trades_limit", 1000)
    pages = cfg.get("data.agg_trades_pages", 3)

    # ------------------------------------------------------------- futures
    if futures_trades is None:
        try:
            futures_trades = client.agg_trades(symbol, limit, pages, spot=False)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"{symbol} vadeli işlem akışı alınamadı: {exc}")
            futures_trades = pd.DataFrame()
    fut = _cvd_frame(futures_trades)

    # ---------------------------------------------------------------- spot
    spot: Dict[str, Any] = {"available": False}
    spot_trades = pd.DataFrame()
    if spot_map:
        try:
            spot_trades = client.agg_trades(spot_map["symbol"], limit, pages, spot=True)
            if not spot_trades.empty:
                # notional zaten USDT cinsinden; çarpan gerekmez
                spot = _cvd_frame(spot_trades)
                spot["symbol"] = spot_map["symbol"]
        except Exception as exc:  # noqa: BLE001
            log.warning(f"{symbol} spot akışı alınamadı: {exc}")

    # ------------------------------------------------------------ skorlama
    fut_score = clamp(fut.get("imbalance_pct", 0) / 12.0) if fut["available"] else 0.0
    fut_slope = _slope(fut.get("series", []))
    spot_score = clamp(spot.get("imbalance_pct", 0) / 12.0) if spot.get("available") else 0.0
    spot_slope = _slope(spot.get("series", []))

    if spot.get("available"):
        # Spot akışı "gerçek para" olduğu için biraz daha ağırlıklı
        score = clamp(0.35 * fut_score + 0.15 * fut_slope +
                      0.35 * spot_score + 0.15 * spot_slope)
    else:
        score = clamp(0.7 * fut_score + 0.3 * fut_slope)

    # ---------------------------------------------------------- divergence
    divergence = "NA"
    divergence_note = ""
    if spot.get("available") and fut["available"]:
        f_pos, s_pos = fut["delta"] > 0, spot["delta"] > 0
        if f_pos and s_pos:
            divergence = "UYUMLU_ALIM"
            divergence_note = "Hem spot hem vadeli tarafta agresif alım — sağlıklı yükseliş"
        elif not f_pos and not s_pos:
            divergence = "UYUMLU_SATIM"
            divergence_note = "Hem spot hem vadeli tarafta agresif satım — sağlıklı düşüş"
        elif f_pos and not s_pos:
            divergence = "SADECE_VADELİ_ALIM"
            divergence_note = "Vadeli alıyor, spot satıyor — kaldıraçlı/kırılgan yükseliş"
        else:
            divergence = "SADECE_SPOT_ALIM"
            divergence_note = "Spot alıyor, vadeli satıyor — gerçek para birikim yapıyor olabilir"

        # Uyumsuzluk skorunu yumuşat
        if divergence == "SADECE_VADELİ_ALIM":
            score = clamp(score * 0.6)
        elif divergence == "SADECE_SPOT_ALIM":
            score = clamp(score * 0.6 + 0.15)

    return {
        "available": fut["available"],
        "score": round(float(score), 4),
        "label": ("BULLISH" if score > 0.25 else "BEARISH" if score < -0.25 else "NEUTRAL"),
        "futures": fut,
        "spot": spot,
        "futures_slope": round(fut_slope, 3),
        "spot_slope": round(spot_slope, 3),
        "divergence": divergence,
        "divergence_note": divergence_note,
        "aggressive_buyers_usdt": fut.get("buy", 0.0) + spot.get("buy", 0.0),
        "aggressive_sellers_usdt": fut.get("sell", 0.0) + spot.get("sell", 0.0),
        "summary": _summary(fut, spot, divergence_note),
        "_futures_trades": futures_trades,   # whale motoru yeniden kullanır
        "_spot_trades": spot_trades,
    }


def _summary(fut: Dict, spot: Dict, divergence_note: str) -> str:
    parts: List[str] = []
    if fut.get("available"):
        parts.append(f"Vadeli CVD {fut['delta']:+,.0f} USDT (%{fut['imbalance_pct']:+.1f})")
    if spot.get("available"):
        parts.append(f"Spot CVD {spot['delta']:+,.0f} USDT (%{spot['imbalance_pct']:+.1f})")
    if divergence_note:
        parts.append(divergence_note)
    return " · ".join(parts) if parts else "Akış verisi yok"
