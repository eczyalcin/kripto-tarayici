"""Alarm kuralları — snapshot ve bir önceki snapshot karşılaştırılarak değerlendirilir."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.indicators import tr_lower
from core.storage import iso, utcnow


def _cooldown_ok(storage, symbol: str, rule: str, minutes: int) -> bool:
    if storage is None:
        return True
    last = storage.last_alert_time(symbol, rule)
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return utcnow() - last >= timedelta(minutes=minutes)


def _mk(symbol: str, rule: str, severity: str, title: str, message: str,
        payload: Optional[Dict] = None) -> Dict[str, Any]:
    return {"symbol": symbol, "rule": rule, "severity": severity, "title": title,
            "message": message, "payload": payload or {}, "ts": iso()}


def evaluate(snapshot: Dict[str, Any], previous: Optional[Dict[str, Any]],
             cfg, storage=None) -> List[Dict[str, Any]]:
    r = cfg.get("alerts.rules", {})
    cooldown = cfg.get("alerts.cooldown_minutes", 45)
    symbol = snapshot["symbol"]
    out: List[Dict[str, Any]] = []

    deriv = snapshot.get("derivatives", {})
    sm = snapshot.get("smart_money", {})
    whale = snapshot.get("whale", {})
    score = snapshot.get("score", {})
    price = snapshot.get("price")

    def add(alert: Dict[str, Any]):
        if _cooldown_ok(storage, symbol, alert["rule"], cooldown):
            out.append(alert)

    # -------------------------------------------------------- Open Interest
    oi = deriv.get("open_interest", {})
    thr = r.get("oi_change_pct", 10.0)
    ch1 = oi.get("change_1h_pct")
    if ch1 is not None and abs(ch1) >= thr:
        interp = oi.get("interpretation_1h", {})
        add(_mk(symbol, "oi_change", "high",
                f"OI 1 saatte %{ch1:+.1f} değişti",
                f"{symbol} — Open Interest 1 saatte %{ch1:+.2f}. "
                f"Yorum: {interp.get('state', '')} — {interp.get('meaning', '')}. "
                f"Fiyat: {price}",
                {"oi_change_1h": ch1, "state": interp.get("state")}))

    # -------------------------------------------------------------- Funding
    f = deriv.get("funding", {})
    cur = f.get("current_pct")
    fthr = r.get("funding_abs", 0.02)
    if cur is not None and abs(cur) >= fthr:
        add(_mk(symbol, "funding", "medium",
                f"Funding %{cur:+.4f}",
                f"{symbol} — Funding oranı %{cur:+.4f} ({f.get('health')}). "
                f"{f.get('bias')}. Yıllık ~%{f.get('annualized_pct', 0):.1f}",
                {"funding_pct": cur}))

    # --------------------------------------------------------- Likidasyonlar
    liq = deriv.get("liquidations", {})
    if liq.get("available"):
        lthr = r.get("liquidation_usdt", 250000)
        lh = liq.get("last_hour_long_usdt", 0) + liq.get("last_hour_short_usdt", 0)
        if lh >= lthr:
            add(_mk(symbol, "liquidation", "high",
                    f"Son 1 saatte {lh:,.0f} USDT likidasyon",
                    f"{symbol} — Long {liq['last_hour_long_usdt']:,.0f} / "
                    f"Short {liq['last_hour_short_usdt']:,.0f} USDT likide oldu.",
                    {"last_hour_total": lh}))
        if r.get("squeeze", True) and liq.get("squeeze") != "NONE":
            yon = "SHORT SQUEEZE (yukarı)" if liq["squeeze"] == "SHORT_SQUEEZE" else "LONG SQUEEZE (aşağı)"
            add(_mk(symbol, f"squeeze_{liq['squeeze']}", "high", yon,
                    f"{symbol} — {yon} başlıyor olabilir. Son 1 saat: "
                    f"Long {liq['last_hour_long_usdt']:,.0f} / Short {liq['last_hour_short_usdt']:,.0f} USDT",
                    {"squeeze": liq["squeeze"]}))

    # ---------------------------------------------------------------- Whale
    # Eşik sembole göre ölçeklenmişse (ör. 1000SHIB) sabit 250k yerine o eşik geçerli
    wthr = whale.get("alert_threshold_usdt") or r.get("whale_notional", 250000)
    candidates = [t for t in whale.get("new_whale_trades", []) if t["notional"] >= wthr]
    # Tek taramada onlarca alarm üretmemek için yön başına sadece en büyük işlem bildirilir
    for side in ("buy", "sell"):
        same = [t for t in candidates if t["side"] == side]
        if not same:
            continue
        t = max(same, key=lambda x: x["notional"])
        yon = "ALIM" if side == "buy" else "SATIM"
        extra = f" (+{len(same) - 1} işlem daha)" if len(same) > 1 else ""
        total = sum(x["notional"] for x in same)
        add(_mk(symbol, f"whale_{side}", "high",
                f"Balina {yon}: {t['notional']:,.0f} USDT{extra}",
                f"{symbol} ({t['market']}) — {t['notional']:,.0f} USDT'lik agresif "
                f"{tr_lower(yon)} @ {t['price']}" +
                (f". Bu taramada toplam {len(same)} büyük {tr_lower(yon)}, "
                 f"{total:,.0f} USDT." if len(same) > 1 else ""),
                {**t, "batch_count": len(same), "batch_total": total}))

    # -------------------------------------------------------- Yapı olayları
    for b in sm.get("structure_breaks", []):
        if b["bars_ago"] > 1:
            continue
        if b["type"] == "BOS" and r.get("bos", True):
            add(_mk(symbol, f"bos_{b['direction']}", "medium",
                    f"BOS {b['direction']}",
                    f"{symbol} — Break of Structure ({b['direction']}), "
                    f"kırılan seviye {b['broken_level']}",
                    b))
        elif b["type"] == "CHOCH" and r.get("choch", True):
            add(_mk(symbol, f"choch_{b['direction']}", "high",
                    f"CHOCH {b['direction']}",
                    f"{symbol} — Karakter değişimi (CHOCH {b['direction']}), "
                    f"kırılan seviye {b['broken_level']}. Trend dönüş adayı.",
                    b))

    # ------------------------------------------------------- Likidite sweep
    if r.get("liquidity_sweep", True):
        for s in sm.get("recent_sweeps", []):
            if s["bars_ago"] <= 1:
                add(_mk(symbol, s["type"], "high", s["type"],
                        f"{symbol} — {s['type']}: {s['swept_level']} seviyesi süpürüldü, "
                        f"fitil oranı {s['wick_ratio']}, hacim x{s.get('volume_ratio')}",
                        s))

    # ------------------------------------------------------------------ FVG
    if r.get("fvg", True):
        for fv in sm.get("fvg", {}).get("open", []):
            if fv["bars_ago"] <= 1:
                add(_mk(symbol, f"fvg_{fv['direction']}", "low", fv["type"],
                        f"{symbol} — Yeni {fv['type']}: {fv['bottom']} - {fv['top']} "
                        f"(fiyata uzaklık %{fv['distance_pct']:+.2f})",
                        fv))

    # --------------------------------------------------------- Skor değişimi
    if r.get("score_flip", True) and previous:
        prev_dec = previous.get("score", {}).get("decision")
        cur_dec = score.get("decision")
        prev_val = previous.get("score", {}).get("long_score")
        cur_val = score.get("long_score")
        # Histerezis: eşik sınırında 0.4 puanlık salınımlar alarm üretmesin
        min_move = r.get("score_flip_min_move", 3.0)
        moved = (prev_val is None or cur_val is None or abs(cur_val - prev_val) >= min_move)
        if prev_dec and cur_dec and prev_dec != cur_dec and moved:
            add(_mk(symbol, "score_flip", "medium",
                    f"Karar değişti: {prev_dec} → {cur_dec}",
                    f"{symbol} — AI kararı {prev_dec} konumundan {cur_dec} konumuna geçti. "
                    f"Long skor {previous.get('score', {}).get('long_score')} → "
                    f"{score.get('long_score')}",
                    {"from": prev_dec, "to": cur_dec}))

    return out
