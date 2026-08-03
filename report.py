"""Günlük AI Raporu — her sabah otomatik özet (Markdown + konsol + bildirim)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import Config, get_config
from core.logging_setup import log
from core.storage import get_storage


def _fmt(value: Optional[float], digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}{suffix}"


def build_symbol_section(snap: Dict[str, Any]) -> str:
    score = snap.get("score", {})
    deriv = snap.get("derivatives", {})
    flow = snap.get("order_flow", {})
    whale = snap.get("whale", {})
    setup = snap.get("setup", {})
    trend = snap.get("trend", {})
    risk = snap.get("risk", {})
    oi = deriv.get("open_interest", {})
    f = deriv.get("funding", {})

    lines: List[str] = []
    lines.append(f"## {snap['symbol']}")
    lines.append("")
    lines.append(f"**Fiyat:** {snap.get('price')}  ")
    lines.append(f"**Karar:** {score.get('decision')} — Long {score.get('long_score')}/100 "
                 f"(güven %{score.get('confidence')})  ")
    lines.append("")
    lines.append("| Alan | Değer |")
    lines.append("|---|---|")
    lines.append(f"| Trend | {trend.get('label')} ({trend.get('structure_state')}) |")
    lines.append(f"| Funding | {f.get('health', '—')} (%{_fmt(f.get('current_pct'), 4)}) |")
    lines.append(f"| Open Interest | %{_fmt(oi.get('change_24h_pct'), 2)} (24s) · "
                 f"%{_fmt(oi.get('change_1h_pct'), 2)} (1s) — {oi.get('trend', '—')} |")
    lines.append(f"| OI yorumu | {oi.get('interpretation_1h', {}).get('state', '—')} |")
    spot = flow.get("spot", {})
    lines.append(f"| Spot CVD | {_fmt(spot.get('delta'), 0, ' USDT') if spot.get('available') else '—'} |")
    lines.append(f"| Vadeli CVD | {_fmt(flow.get('futures', {}).get('delta'), 0, ' USDT')} |")
    lines.append(f"| Balinalar | {whale.get('state', '—')} "
                 f"({_fmt(whale.get('total_whale_delta_usdt'), 0, ' USDT')} delta) |")
    lines.append(f"| Order Book | {snap.get('orderbook', {}).get('state', '—')} |")
    lines.append(f"| Risk | {risk.get('level', '—')} |")
    lines.append(f"| Olasılık | %{setup.get('probability', '—')} |")
    lines.append("")

    if setup.get("available"):
        tps = setup.get("targets", [])
        lines.append(f"**Bugünün eğilimi: {setup['direction']}**")
        lines.append("")
        lines.append(f"- Giriş bölgesi: `{setup['entry_zone'][0]} - {setup['entry_zone'][1]}` "
                     f"({setup['entry_basis']})")
        lines.append(f"- Stop: `{setup['stop']}` ({setup['stop_basis']}, "
                     f"%{setup['stop_distance_pct']} uzaklık)")
        for t in tps:
            lines.append(f"- {t['name']}: `{t['price']}` ({t['r_multiple']}R, %{t['gain_pct']:+.2f})")
        lines.append(f"- Pozisyon: {setup['position']['qty']} adet "
                     f"(~{_fmt(setup['position']['notional_usdt'], 0, ' USDT')}), "
                     f"maks kaldıraç {setup['position']['suggested_max_leverage']}x")
        if setup.get("invalidation"):
            lines.append(f"- Geçersizlik: {'; '.join(setup['invalidation'])}")
    else:
        lines.append(f"**Setup yok** — {setup.get('reason', 'nötr bölge')}")
    lines.append("")

    lines.append("**Skor dağılımı**")
    lines.append("")
    lines.append("| Gösterge | Puan | Maks | Yön |")
    lines.append("|---|---:|---:|---|")
    for c in score.get("components", []):
        lines.append(f"| {c['name']} | {c['points']:+.1f} | {c['max_points']} | {c['direction']} |")
    lines.append(f"| **Toplam** | **{score.get('total_points', 0):+.1f}** | "
                 f"**{score.get('total_weight', 0)}** | **{score.get('decision')}** |")
    lines.append("")
    lines.append(f"> {score.get('answer', '')}")
    lines.append("")
    return "\n".join(lines)


def build_report(snapshots: List[Dict[str, Any]], cfg: Optional[Config] = None) -> str:
    cfg = cfg or get_config()
    now = datetime.now(timezone.utc).astimezone()
    ranked = sorted(snapshots, key=lambda s: s["score"]["long_score"], reverse=True)

    lines: List[str] = []
    lines.append(f"# Günlük Kripto İstihbarat Raporu")
    lines.append(f"_{now.strftime('%d.%m.%Y %H:%M %Z')}_")
    lines.append("")
    lines.append("## Sıralama")
    lines.append("")
    lines.append("| # | Parite | Long | Short | Karar | Güven | Funding | OI 1s | Risk |")
    lines.append("|---:|---|---:|---:|---|---:|---:|---:|---|")
    for i, s in enumerate(ranked, start=1):
        sc = s["score"]
        f = s["derivatives"].get("funding", {})
        oi = s["derivatives"].get("open_interest", {})
        lines.append(
            f"| {i} | {s['symbol']} | {sc['long_score']:.0f} | {sc['short_score']:.0f} | "
            f"{sc['decision']} | %{sc['confidence']:.0f} | %{_fmt(f.get('current_pct'), 4)} | "
            f"%{_fmt(oi.get('change_1h_pct'), 2)} | {s['risk'].get('level')} |")
    lines.append("")

    for s in ranked:
        lines.append(build_symbol_section(s))
        lines.append("---")
        lines.append("")

    lines.append("_Bu rapor otomatik üretilmiş veri özetidir; yatırım tavsiyesi değildir._")
    return "\n".join(lines)


def save_report(content: str, cfg: Optional[Config] = None) -> Path:
    cfg = cfg or get_config()
    reports_dir = cfg.path_for("storage.reports_dir", "reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("rapor_%Y-%m-%d_%H%M.md")
    path = reports_dir / name
    path.write_text(content, encoding="utf-8")
    log.info(f"Rapor kaydedildi: {path}")
    return path


def daily_report(symbols: Optional[List[str]] = None, cfg: Optional[Config] = None,
                 send: bool = True, use_cache: bool = False) -> str:
    """Taramayı çalıştırıp raporu üretir, kaydeder ve isteğe bağlı gönderir."""
    from pipeline import scan_all
    cfg = cfg or get_config()
    symbols = symbols or cfg.symbols

    if use_cache:
        storage = get_storage()
        snapshots = [s for s in (storage.latest_snapshot(sym) for sym in symbols) if s]
        if not snapshots:
            snapshots = scan_all(symbols, cfg)
    else:
        snapshots = scan_all(symbols, cfg)

    content = build_report(snapshots, cfg)
    save_report(content, cfg)

    if send:
        from alerts.notifier import send_text
        top = sorted(snapshots, key=lambda s: s["score"]["long_score"], reverse=True)
        summary_lines = ["📊 Günlük Kripto Raporu", ""]
        for i, s in enumerate(top, start=1):
            sc = s["score"]
            summary_lines.append(
                f"{i}. {s['symbol']}: {sc['decision']} "
                f"(L{sc['long_score']:.0f}/S{sc['short_score']:.0f}) — {s['risk']['level']} risk")
        primary = next((s for s in top if s["symbol"] == cfg.primary_symbol), top[0])
        setup = primary.get("setup", {})
        if setup.get("available"):
            summary_lines += [
                "", f"{primary['symbol']} planı:",
                f"Yön: {setup['direction']} (olasılık %{setup['probability']})",
                f"Giriş: {setup['entry_zone'][0]} - {setup['entry_zone'][1]}",
                f"Stop: {setup['stop']}",
                "Hedefler: " + ", ".join(str(t["price"]) for t in setup["targets"]),
            ]
        send_text("\n".join(summary_lines), cfg, subject="Günlük Kripto Raporu")

    return content
