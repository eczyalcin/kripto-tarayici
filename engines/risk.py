"""Risk Engine — volatilite, funding maliyeti, kalabalıklaşma, likidite ve
likidasyon zinciri riski + pozisyon büyüklüğü hesabı.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.indicators import clamp


def _level(points: float) -> str:
    if points >= 6:
        return "YÜKSEK"
    if points >= 3:
        return "ORTA"
    return "DÜŞÜK"


def run(engines: Dict[str, Any], cfg) -> Dict[str, Any]:
    r = cfg.get("risk", {})
    trend = engines.get("trend", {})
    deriv = engines.get("derivatives", {})
    book = engines.get("orderbook", {})

    factors: List[Dict[str, Any]] = []
    points = 0.0

    # ------------------------------------------------------------ volatilite
    atr_pct = trend.get("atr_pct")
    if atr_pct is not None:
        high_vol = r.get("high_volatility_atr_pct", 3.0)
        if atr_pct >= high_vol * 1.5:
            p, state = 3.0, "ÇOK YÜKSEK"
        elif atr_pct >= high_vol:
            p, state = 2.0, "YÜKSEK"
        elif atr_pct >= high_vol * 0.5:
            p, state = 1.0, "NORMAL"
        else:
            p, state = 0.0, "DÜŞÜK"
        points += p
        factors.append({"factor": "Volatilite (ATR%)", "value": f"%{atr_pct:.2f}",
                        "state": state, "points": p})

    # --------------------------------------------------------------- funding
    f = deriv.get("funding", {})
    cur = f.get("current_pct")
    if cur is not None:
        extreme = r.get("extreme_funding", 0.05)
        a = abs(cur)
        if a >= extreme * 2:
            p, state = 3.0, "AŞIRI"
        elif a >= extreme:
            p, state = 2.0, "YÜKSEK"
        elif a >= extreme / 2:
            p, state = 1.0, "ARTIYOR"
        else:
            p, state = 0.0, "SAĞLIKLI"
        points += p
        factors.append({"factor": "Funding maliyeti", "value": f"%{cur:+.4f}",
                        "state": state, "points": p,
                        "note": f"Yıllıklandırılmış ~%{f.get('annualized_pct', 0):.1f}"})

    # ---------------------------------------------------------- kalabalıklık
    ls = deriv.get("long_short", {}).get("top_positions_ratio")
    if ls:
        crowded = r.get("crowded_ls_ratio", 2.5)
        if ls >= crowded or ls <= 1 / crowded:
            p, state = 2.0, "KALABALIK"
        elif ls >= crowded * 0.75 or ls <= 1 / (crowded * 0.75):
            p, state = 1.0, "YOĞUNLAŞIYOR"
        else:
            p, state = 0.0, "DENGELİ"
        points += p
        factors.append({"factor": "Pozisyon kalabalığı", "value": f"L/S {ls:.2f}",
                        "state": state, "points": p})

    # ------------------------------------------------------ likidasyon riski
    liq = deriv.get("liquidations", {})
    if liq.get("available"):
        total = liq.get("total_usdt", 0)
        if liq.get("squeeze") != "NONE":
            p, state = 2.0, liq["squeeze"]
        elif total > 1_000_000:
            p, state = 1.5, "YOĞUN"
        elif total > 250_000:
            p, state = 1.0, "ARTIYOR"
        else:
            p, state = 0.0, "SAKİN"
        points += p
        factors.append({"factor": "Likidasyon baskısı",
                        "value": f"{total:,.0f} USDT / {liq.get('hours', 24)}s",
                        "state": state, "points": p})

    # ------------------------------------------------------- kitap likiditesi
    if book.get("available"):
        spread = book.get("spread_pct", 0)
        if spread > 0.08:
            p, state = 2.0, "GENİŞ SPREAD"
        elif spread > 0.03:
            p, state = 1.0, "ORTA"
        else:
            p, state = 0.0, "DERİN"
        points += p
        factors.append({"factor": "Order book likiditesi", "value": f"%{spread:.4f} spread",
                        "state": state, "points": p})
        if book.get("spoofs"):
            points += 1.0
            factors.append({"factor": "Spoof aktivitesi",
                            "value": f"{len(book['spoofs'])} şüpheli duvar",
                            "state": "MANİPÜLASYON ŞÜPHESİ", "points": 1.0})

    # --------------------------------------------------- zaman dilimi uyumu
    if trend.get("timeframes") and not trend.get("mtf_aligned", True):
        points += 1.0
        factors.append({"factor": "Zaman dilimi uyumu", "value": "Uyumsuz",
                        "state": "KARARSIZ", "points": 1.0})

    level = _level(points)

    # ------------------------------------------------------- pozisyon boyutu
    account = r.get("account_size_usdt", 1000)
    risk_pct = r.get("risk_per_trade_pct", 1.0)
    risk_usdt = account * risk_pct / 100

    max_lev = r.get("max_leverage", 10)
    lev_factor = {"DÜŞÜK": 1.0, "ORTA": 0.6, "YÜKSEK": 0.3}[level]
    suggested_leverage = max(1, round(max_lev * lev_factor))

    return {
        "level": level,
        "points": round(points, 1),
        "factors": factors,
        "account_size_usdt": account,
        "risk_per_trade_pct": risk_pct,
        "risk_usdt": round(risk_usdt, 2),
        "suggested_max_leverage": suggested_leverage,
        "summary": f"Risk {level} ({points:.0f} puan) · " +
                   " · ".join(f"{x['factor']}: {x['state']}" for x in factors[:3]),
    }


def position_size(entry: float, stop: float, risk_usdt: float) -> Dict[str, Any]:
    """Stop mesafesine göre pozisyon büyüklüğü."""
    if not entry or not stop or entry == stop:
        return {"qty": 0.0, "notional": 0.0, "stop_distance_pct": 0.0}
    dist = abs(entry - stop)
    qty = risk_usdt / dist
    return {
        "qty": round(qty, 4),
        "notional": round(qty * entry, 2),
        "stop_distance_pct": round(dist / entry * 100, 3),
    }
