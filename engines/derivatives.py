"""Derivatives Engine — OI, Funding, Long/Short oranları, Taker akışı,
Likidasyonlar ve Basis.

Sistemin en kritik parçası: fiyatın değil, pozisyonlanmanın ne yaptığını okur.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.binance import BinanceClient
from core.indicators import clamp, pct_change
from core.logging_setup import log

# 5 dakikalık OI barları cinsinden pencere uzunlukları
_OI_WINDOWS = {"1h": 12, "4h": 48, "24h": 288}


def _oi_change(df: pd.DataFrame, bars: int) -> Optional[float]:
    if df.empty or len(df) <= bars:
        return None
    now = float(df["sumOpenInterest"].iloc[-1])
    then = float(df["sumOpenInterest"].iloc[-1 - bars])
    return round(pct_change(now, then), 3)


def _price_change(df: pd.DataFrame, bars: int) -> Optional[float]:
    """OI barlarıyla aynı pencerede fiyat değişimi (OI değeri / miktar oranından)."""
    if df.empty or len(df) <= bars:
        return None
    price_now = float(df["sumOpenInterestValue"].iloc[-1]) / max(float(df["sumOpenInterest"].iloc[-1]), 1e-9)
    price_then = float(df["sumOpenInterestValue"].iloc[-1 - bars]) / max(float(df["sumOpenInterest"].iloc[-1 - bars]), 1e-9)
    return round(pct_change(price_now, price_then), 3)


def interpret_oi(oi_change: Optional[float], price_change: Optional[float]) -> Dict[str, Any]:
    """Klasik OI/fiyat matrisi."""
    if oi_change is None or price_change is None:
        return {"state": "NA", "meaning": "Veri yok", "score": 0.0}

    oi_up = oi_change > 0.3
    oi_down = oi_change < -0.3
    px_up = price_change > 0.1
    px_down = price_change < -0.1

    strength = clamp(abs(oi_change) / 8.0, 0, 1)

    if oi_up and px_up:
        return {"state": "YENİ LONG", "meaning": "OI ve fiyat birlikte artıyor — taze long girişi",
                "score": round(0.9 * strength, 3)}
    if oi_up and px_down:
        return {"state": "YENİ SHORT", "meaning": "OI artarken fiyat düşüyor — taze short girişi",
                "score": round(-0.9 * strength, 3)}
    if oi_down and px_up:
        return {"state": "SHORT KAPANIŞI", "meaning": "OI düşerken fiyat yükseliyor — short covering, itici güç zayıf",
                "score": round(0.35 * strength, 3)}
    if oi_down and px_down:
        return {"state": "LONG KAPANIŞI", "meaning": "OI ve fiyat birlikte düşüyor — long tasfiyesi",
                "score": round(-0.35 * strength, 3)}
    return {"state": "YATAY", "meaning": "Belirgin pozisyon değişimi yok", "score": 0.0}


def analyze_funding(current: float, history: pd.DataFrame,
                    mark: float, index: float, interest_rate: float) -> Dict[str, Any]:
    """Funding sağlık analizi. Oranlar yüzde (%) cinsine çevrilir."""
    cur_pct = current * 100
    avg_pct = float(history["fundingRate"].mean() * 100) if not history.empty else cur_pct
    last8 = float(history["fundingRate"].tail(8).mean() * 100) if not history.empty else cur_pct

    # Yaklaşık tahmini funding: premium + clamp(interest - premium, ±0.05%)
    premium = (mark - index) / index if index else 0.0
    predicted = premium + max(min(interest_rate - premium, 0.0005), -0.0005)
    predicted_pct = predicted * 100

    a = abs(cur_pct)
    if a < 0.01:
        health, score = "SAĞLIKLI", 0.0
    elif a < 0.03:
        health = "NORMAL"
        score = 0.25 if cur_pct > 0 else -0.25
    elif a < 0.06:
        health = "ISINIYOR"
        # Pozitif ve yüksek funding = kalabalık long => kontra negatif
        score = -0.45 if cur_pct > 0 else 0.45
    else:
        health = "AŞIRI"
        score = -0.9 if cur_pct > 0 else 0.9

    if cur_pct > 0:
        bias = "Long'lar short'lara ödüyor (long ağırlıklı pozisyonlanma)"
    elif cur_pct < 0:
        bias = "Short'lar long'lara ödüyor (short ağırlıklı pozisyonlanma)"
    else:
        bias = "Dengeli"

    trend = "ARTIYOR" if cur_pct > last8 else "AZALIYOR" if cur_pct < last8 else "SABİT"

    return {
        "current_pct": round(cur_pct, 5),
        "avg_pct": round(avg_pct, 5),
        "avg_8_pct": round(last8, 5),
        "predicted_pct": round(predicted_pct, 5),
        "annualized_pct": round(cur_pct * 3 * 365, 2),
        "health": health,
        "bias": bias,
        "trend": trend,
        "score": round(float(score), 3),
        "history": [{"time": str(t), "rate_pct": round(float(r) * 100, 5)}
                    for t, r in zip(history["fundingTime"], history["fundingRate"])]
        if not history.empty else [],
    }


def analyze_ls_ratios(top_acc: pd.DataFrame, top_pos: pd.DataFrame,
                      glob: pd.DataFrame, crowded: float) -> Dict[str, Any]:
    def _last(df: pd.DataFrame, col: str) -> Optional[float]:
        if df.empty or col not in df.columns:
            return None
        return float(df[col].iloc[-1])

    def _delta(df: pd.DataFrame, col: str, bars: int = 6) -> Optional[float]:
        if df.empty or col not in df.columns or len(df) <= bars:
            return None
        return round(pct_change(float(df[col].iloc[-1]), float(df[col].iloc[-1 - bars])), 2)

    tp_ratio = _last(top_pos, "longShortRatio")
    ta_ratio = _last(top_acc, "longShortRatio")
    gl_ratio = _last(glob, "longShortRatio")

    score = 0.0
    notes: List[str] = []

    # Büyük oyuncuların POZİSYON oranı en anlamlı sinyal
    if tp_ratio is not None:
        delta = _delta(top_pos, "longShortRatio") or 0.0
        if tp_ratio >= crowded:
            score -= 0.5
            notes.append(f"Büyük hesap pozisyonları aşırı long kalabalığı ({tp_ratio:.2f})")
        elif tp_ratio <= 1 / crowded:
            score += 0.5
            notes.append(f"Büyük hesap pozisyonları aşırı short kalabalığı ({tp_ratio:.2f})")
        else:
            score += clamp((tp_ratio - 1) / 1.0) * 0.35
        # Oranın yönü de bilgi taşır
        score += clamp(delta / 15.0) * 0.25
        if abs(delta) > 3:
            notes.append(f"Büyük hesap long oranı son 6 barda %{delta:+.1f}")

    # Perakende (global hesap) oranı genelde kontra sinyaldir
    if gl_ratio is not None:
        if gl_ratio >= 3.0:
            score -= 0.25
            notes.append(f"Perakende aşırı long ({gl_ratio:.2f}) — kontra sinyal")
        elif gl_ratio <= 0.6:
            score += 0.25
            notes.append(f"Perakende aşırı short ({gl_ratio:.2f}) — kontra sinyal")

    return {
        "top_accounts_ratio": ta_ratio,
        "top_accounts_long_pct": _last(top_acc, "longAccount"),
        "top_positions_ratio": tp_ratio,
        "top_positions_long_pct": _last(top_pos, "longAccount"),
        "global_accounts_ratio": gl_ratio,
        "global_long_pct": _last(glob, "longAccount"),
        "top_positions_delta_pct": _delta(top_pos, "longShortRatio"),
        "score": round(clamp(score), 3),
        "notes": notes,
        "series": [{"time": str(t), "ratio": float(r)}
                   for t, r in zip(top_pos["timestamp"], top_pos["longShortRatio"])]
        if not top_pos.empty else [],
    }


def analyze_taker(df: pd.DataFrame) -> Dict[str, Any]:
    """Binance taker buy/sell hacim oranı (5dk barlar)."""
    if df.empty:
        return {"score": 0.0, "available": False}
    buy = float(df["buyVol"].sum())
    sell = float(df["sellVol"].sum())
    delta = buy - sell
    total = buy + sell
    ratio = float(df["buySellRatio"].iloc[-1])
    imbalance = delta / total if total else 0.0

    recent = df.tail(6)
    recent_delta = float(recent["buyVol"].sum() - recent["sellVol"].sum())
    recent_total = float(recent["buyVol"].sum() + recent["sellVol"].sum())
    recent_imb = recent_delta / recent_total if recent_total else 0.0

    score = clamp(imbalance * 4 * 0.5 + recent_imb * 4 * 0.5)
    return {
        "available": True,
        "buy_volume": buy,
        "sell_volume": sell,
        "delta": delta,
        "imbalance_pct": round(imbalance * 100, 2),
        "recent_imbalance_pct": round(recent_imb * 100, 2),
        "last_ratio": ratio,
        "score": round(float(score), 3),
        "state": "ALICI BASKIN" if imbalance > 0.03 else "SATICI BASKIN" if imbalance < -0.03 else "DENGELİ",
        "series": [{"time": str(t), "buy": float(b), "sell": float(s)}
                   for t, b, s in zip(df["timestamp"], df["buyVol"], df["sellVol"])],
    }


def analyze_liquidations(rows: List[Dict[str, Any]], hours: int) -> Dict[str, Any]:
    """WebSocket toplayıcısının kaydettiği zorunlu kapanışlar.

    Binance force-order akışında side=SELL ise long pozisyon likide olmuştur.
    """
    if not rows:
        return {"available": False, "score": 0.0,
                "note": "Likidasyon verisi için `python run.py collect` toplayıcısı çalışmalı",
                "long_usdt": 0.0, "short_usdt": 0.0, "total_usdt": 0.0, "count": 0}

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    long_liq = float(df.loc[df["side"] == "SELL", "notional"].sum())
    short_liq = float(df.loc[df["side"] == "BUY", "notional"].sum())
    total = long_liq + short_liq

    cutoff = df["ts"].max() - pd.Timedelta(hours=1)
    last_hour = df[df["ts"] >= cutoff]
    lh_long = float(last_hour.loc[last_hour["side"] == "SELL", "notional"].sum())
    lh_short = float(last_hour.loc[last_hour["side"] == "BUY", "notional"].sum())

    # Short likidasyonu baskınsa yukarı squeeze, long likidasyonu baskınsa aşağı
    dominance = (short_liq - long_liq) / total if total else 0.0
    intensity = clamp(total / 1_000_000, 0, 1)
    score = clamp(dominance * intensity * 1.5)

    squeeze = "NONE"
    if lh_short > 0 and lh_short > lh_long * 3 and lh_short > 50_000:
        squeeze = "SHORT_SQUEEZE"
    elif lh_long > 0 and lh_long > lh_short * 3 and lh_long > 50_000:
        squeeze = "LONG_SQUEEZE"

    return {
        "available": True,
        "hours": hours,
        "long_usdt": round(long_liq, 2),
        "short_usdt": round(short_liq, 2),
        "total_usdt": round(total, 2),
        "count": int(len(df)),
        "last_hour_long_usdt": round(lh_long, 2),
        "last_hour_short_usdt": round(lh_short, 2),
        "dominance": round(dominance, 3),
        "squeeze": squeeze,
        "score": round(float(score), 3),
        "largest": df.nlargest(5, "notional")[["ts", "side", "price", "notional"]]
                     .assign(ts=lambda d: d["ts"].astype(str)).to_dict("records"),
    }


def analyze_basis(mark: float, spot: Optional[float]) -> Dict[str, Any]:
    if not spot:
        return {"available": False, "score": 0.0}
    basis = mark - spot
    basis_pct = basis / spot * 100
    if basis_pct > 0.15:
        state, score = "PREMIUM (vadeli önde)", -0.3
    elif basis_pct < -0.15:
        state, score = "DISCOUNT (spot önde)", 0.3
    else:
        state, score = "DENGELİ", 0.0
    return {"available": True, "perp_mark": mark, "spot_price": spot,
            "basis": basis, "basis_pct": round(basis_pct, 4),
            "state": state, "score": score}


# ----------------------------------------------------------------------- run
def run(symbol: str, client: BinanceClient, cfg, storage=None,
        spot_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    d = cfg.get("derivatives", {})
    out: Dict[str, Any] = {"available": True}

    # ---------------------------------------------------------- Open Interest
    try:
        oi_now = client.open_interest(symbol)
        oi_hist = client.open_interest_hist(symbol, "5m", 500)
        oi_value_now = float(oi_hist["sumOpenInterestValue"].iloc[-1]) if not oi_hist.empty else None
        changes = {k: _oi_change(oi_hist, bars) for k, bars in _OI_WINDOWS.items()}
        px_changes = {k: _price_change(oi_hist, bars) for k, bars in _OI_WINDOWS.items()}
        interp_1h = interpret_oi(changes.get("1h"), px_changes.get("1h"))
        interp_4h = interpret_oi(changes.get("4h"), px_changes.get("4h"))
        oi_score = clamp(interp_1h["score"] * 0.6 + interp_4h["score"] * 0.4)
        out["open_interest"] = {
            "current": float(oi_now.get("openInterest", 0)),
            "current_usdt": oi_value_now,
            "change_1h_pct": changes.get("1h"),
            "change_4h_pct": changes.get("4h"),
            "change_24h_pct": changes.get("24h"),
            "price_change_1h_pct": px_changes.get("1h"),
            "interpretation_1h": interp_1h,
            "interpretation_4h": interp_4h,
            "score": round(float(oi_score), 3),
            "trend": ("ARTIYOR" if (changes.get("1h") or 0) > 0.3 else
                      "AZALIYOR" if (changes.get("1h") or 0) < -0.3 else "YATAY"),
            "series": [{"time": str(t), "oi": float(v), "oi_usdt": float(u)}
                       for t, v, u in zip(oi_hist["timestamp"].tail(288),
                                          oi_hist["sumOpenInterest"].tail(288),
                                          oi_hist["sumOpenInterestValue"].tail(288))]
            if not oi_hist.empty else [],
        }
    except Exception as exc:  # noqa: BLE001
        log.warning(f"{symbol} OI verisi alınamadı: {exc}")
        out["open_interest"] = {"score": 0.0, "error": str(exc)}

    # --------------------------------------------------------------- Funding
    try:
        prem = client.mark_price(symbol)
        mark = float(prem["markPrice"])
        index = float(prem["indexPrice"])
        rate = float(prem["lastFundingRate"])
        interest = float(prem.get("interestRate", 0.0001))
        hist = client.funding_history(symbol, d.get("funding_history_limit", 30))
        out["funding"] = analyze_funding(rate, hist, mark, index, interest)
        out["funding"]["next_funding_time"] = int(prem.get("nextFundingTime", 0))
        out["mark_price"] = mark
        out["index_price"] = index
    except Exception as exc:  # noqa: BLE001
        log.warning(f"{symbol} funding verisi alınamadı: {exc}")
        out["funding"] = {"score": 0.0, "error": str(exc)}
        mark = None

    # ------------------------------------------------------- Long/Short oran
    try:
        period = d.get("ls_ratio_period", "1h")
        limit = d.get("ls_ratio_limit", 24)
        out["long_short"] = analyze_ls_ratios(
            client.top_accounts_ratio(symbol, period, limit),
            client.top_positions_ratio(symbol, period, limit),
            client.global_accounts_ratio(symbol, period, limit),
            cfg.get("risk.crowded_ls_ratio", 2.5),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(f"{symbol} L/S oranı alınamadı: {exc}")
        out["long_short"] = {"score": 0.0, "error": str(exc)}

    # ------------------------------------------------------------ Taker akış
    try:
        out["taker"] = analyze_taker(client.taker_ratio(
            symbol, d.get("taker_ratio_period", "5m"), d.get("taker_ratio_limit", 24)))
    except Exception as exc:  # noqa: BLE001
        log.warning(f"{symbol} taker oranı alınamadı: {exc}")
        out["taker"] = {"score": 0.0, "error": str(exc)}

    # ---------------------------------------------------------- Likidasyonlar
    hours = d.get("liquidation_lookback_hours", 24)
    rows = storage.liquidations_since(symbol, hours) if storage else []
    out["liquidations"] = analyze_liquidations(rows, hours)

    # ------------------------------------------------------------------ Basis
    spot_price = None
    try:
        if spot_map:
            raw = client.spot_price(spot_map["symbol"])
            spot_price = raw * spot_map["multiplier"]
    except Exception as exc:  # noqa: BLE001
        log.debug(f"{symbol} spot fiyatı alınamadı: {exc}")
    out["basis"] = analyze_basis(out.get("mark_price") or 0.0, spot_price)

    # -------------------------------------------------------- birleşik özet
    out["summary"] = _summary(out)
    return out


def _summary(d: Dict[str, Any]) -> str:
    parts: List[str] = []
    oi = d.get("open_interest", {})
    if oi.get("change_1h_pct") is not None:
        parts.append(f"OI 1s %{oi['change_1h_pct']:+.2f} ({oi['interpretation_1h']['state']})")
    f = d.get("funding", {})
    if f.get("current_pct") is not None:
        parts.append(f"Funding %{f['current_pct']:+.4f} ({f['health']})")
    ls = d.get("long_short", {})
    if ls.get("top_positions_ratio"):
        parts.append(f"Büyük hesap L/S {ls['top_positions_ratio']:.2f}")
    t = d.get("taker", {})
    if t.get("available"):
        parts.append(f"Taker {t['state']} (%{t['imbalance_pct']:+.1f})")
    liq = d.get("liquidations", {})
    if liq.get("available") and liq.get("squeeze") != "NONE":
        parts.append(liq["squeeze"])
    return " · ".join(parts) if parts else "Türev verisi yok"
