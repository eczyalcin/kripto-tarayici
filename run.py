#!/usr/bin/env python3
"""Crypto Intelligence Dashboard — komut satırı arayüzü.

Kullanım:
    python run.py scan [SEMBOL]     Tek parite için tam tarama ve rapor
    python run.py rank              Tüm pariteleri tarayıp sıralar
    python run.py watch             Zamanlayıcıyı başlatır (saatlik tarama + alarmlar)
    python run.py collect           Likidasyon websocket toplayıcısı (ön planda)
    python run.py report            Günlük raporu üretir ve kaydeder
    python run.py serve             Streamlit arayüzünü açar
    python run.py check             Bağlantı ve veri kaynağı testi
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from rich.console import Console          # noqa: E402
from rich.panel import Panel              # noqa: E402
from rich.table import Table              # noqa: E402
from rich.text import Text                # noqa: E402

from core.config import get_config        # noqa: E402
from core.logging_setup import setup_logging  # noqa: E402

console = Console()

DECISION_STYLE = {
    "STRONG LONG": "bold green",
    "LONG": "green",
    "WEAK LONG": "dim green",
    "NÖTR": "yellow",
    "WEAK SHORT": "dim red",
    "SHORT": "red",
    "STRONG SHORT": "bold red",
}


def _fmt(v: Optional[float], d: int = 2, suffix: str = "") -> str:
    return "—" if v is None else f"{v:,.{d}f}{suffix}"


# --------------------------------------------------------------------- yazdır
def print_snapshot(snap: Dict[str, Any]):
    score = snap["score"]
    style = DECISION_STYLE.get(score["decision"], "white")

    console.print()
    console.print(Panel(
        Text.assemble(
            (f"{snap['symbol']}  ", "bold cyan"),
            (f"{snap['price']}\n\n", "bold white"),
            (f"{score['decision']}", style),
            (f"   Long {score['long_score']}/100 · Short {score['short_score']}/100 · "
             f"güven %{score['confidence']}\n\n", "white"),
            (score["answer"], "italic"),
        ),
        title="AI Karar Motoru", border_style=style))

    # ---- skor tablosu
    t = Table(title="Skor Dağılımı", show_lines=False, header_style="bold")
    t.add_column("Gösterge"); t.add_column("Puan", justify="right")
    t.add_column("Maks", justify="right"); t.add_column("Yön")
    t.add_column("Detay", overflow="fold", max_width=62)
    for c in score["components"]:
        color = "green" if c["points"] > 0 else "red" if c["points"] < 0 else "yellow"
        t.add_row(c["name"], f"[{color}]{c['points']:+.1f}[/{color}]", str(c["max_points"]),
                  c["direction"], (c["detail"] or "")[:200] if c["available"] else "[dim]veri yok[/dim]")
    t.add_row("[bold]TOPLAM[/bold]", f"[bold]{score['total_points']:+.1f}[/bold]",
              f"[bold]{score['total_weight']}[/bold]", f"[{style}]{score['decision']}[/{style}]",
              f"Long {score['long_score']}/100")
    console.print(t)

    # ---- trend
    trend = snap["trend"]
    tt = Table(title="Trend Engine", header_style="bold")
    tt.add_column("TF"); tt.add_column("Yön"); tt.add_column("ADX"); tt.add_column("SuperTrend")
    tt.add_column("Yapı"); tt.add_column("RSI"); tt.add_column("ATR %"); tt.add_column("VWAP-D farkı")
    for key, name in (("ltf", "15m"), ("mtf", "1h"), ("htf", "4h")):
        tf = trend.get("timeframes", {}).get(key, {})
        if not tf.get("available"):
            continue
        tt.add_row(f"{name}", tf["label"],
                   f"{tf['adx']['value']:.0f} ({tf['adx']['strength']})",
                   tf["supertrend"]["direction"] + (" ⚡" if tf["supertrend"]["flipped"] else ""),
                   tf["structure"]["state"], f"{tf['rsi']:.0f}", f"{tf['atr']['pct']:.2f}",
                   f"%{_fmt(tf['vwap']['price_vs_daily_pct'], 2)}")
    console.print(tt)

    # ---- türev
    d = snap["derivatives"]
    oi, f, ls, taker, liq, basis = (d.get("open_interest", {}), d.get("funding", {}),
                                    d.get("long_short", {}), d.get("taker", {}),
                                    d.get("liquidations", {}), d.get("basis", {}))
    dt = Table(title="Derivatives Engine", header_style="bold")
    dt.add_column("Metrik"); dt.add_column("Değer"); dt.add_column("Yorum", overflow="fold")
    dt.add_row("Open Interest", f"{_fmt(oi.get('current'), 0)} ({_fmt(oi.get('current_usdt'), 0, ' USDT')})",
               oi.get("trend", "—"))
    dt.add_row("OI 1s / 4s / 24s",
               f"%{_fmt(oi.get('change_1h_pct'))} / %{_fmt(oi.get('change_4h_pct'))} / "
               f"%{_fmt(oi.get('change_24h_pct'))}",
               f"{oi.get('interpretation_1h', {}).get('state', '')} — "
               f"{oi.get('interpretation_1h', {}).get('meaning', '')}")
    dt.add_row("Funding", f"%{_fmt(f.get('current_pct'), 4)}",
               f"{f.get('health', '')} · ort %{_fmt(f.get('avg_pct'), 4)} · "
               f"tahmini %{_fmt(f.get('predicted_pct'), 4)} · yıllık %{_fmt(f.get('annualized_pct'), 1)}")
    dt.add_row("Büyük hesap L/S", f"poz {_fmt(ls.get('top_positions_ratio'))} · "
                                  f"hesap {_fmt(ls.get('top_accounts_ratio'))}",
               f"global {_fmt(ls.get('global_accounts_ratio'))} · " + "; ".join(ls.get("notes", []))[:120])
    if taker.get("available"):
        dt.add_row("Taker Buy/Sell", f"{_fmt(taker.get('buy_volume'), 0)} / {_fmt(taker.get('sell_volume'), 0)}",
                   f"{taker.get('state')} (delta %{_fmt(taker.get('imbalance_pct'))})")
    dt.add_row("Likidasyon",
               f"Long {_fmt(liq.get('long_usdt'), 0)} / Short {_fmt(liq.get('short_usdt'), 0)} USDT",
               liq.get("squeeze", "—") if liq.get("available") else liq.get("note", ""))
    if basis.get("available"):
        dt.add_row("Basis (Perp-Spot)", f"%{_fmt(basis.get('basis_pct'), 4)}", basis.get("state", ""))
    console.print(dt)

    # ---- akış + balina + kitap
    flow, whale, book = snap["order_flow"], snap["whale"], snap["orderbook"]
    ft = Table(title="Order Flow · Whale · Order Book", header_style="bold")
    ft.add_column("Alan"); ft.add_column("Değer", overflow="fold")
    if flow.get("available"):
        fut, sp = flow["futures"], flow.get("spot", {})
        ft.add_row("Vadeli CVD", f"{_fmt(fut.get('delta'), 0, ' USDT')} "
                                 f"(alım {_fmt(fut.get('buy'), 0)} / satım {_fmt(fut.get('sell'), 0)}, "
                                 f"{fut.get('trades')} işlem)")
        if sp.get("available"):
            ft.add_row("Spot CVD", f"{_fmt(sp.get('delta'), 0, ' USDT')} "
                                   f"(%{_fmt(sp.get('imbalance_pct'))} dengesizlik)")
        ft.add_row("Ayrışma", f"{flow.get('divergence')} — {flow.get('divergence_note')}")
    if whale.get("available"):
        ft.add_row("Balina deltası", f"{_fmt(whale.get('total_whale_delta_usdt'), 0, ' USDT')} "
                                     f"({whale.get('state')})")
        fw = whale.get("futures", {})
        if fw.get("available"):
            tiers = " · ".join(f"{k}: {v['count']} işlem, delta {v['delta_usdt']:+,.0f}"
                               for k, v in fw.get("tiers", {}).items() if v["count"])
            ft.add_row("Balina dilimleri (vadeli)", tiers or "eşik üstü işlem yok")
        ice = (fw.get("icebergs") or []) + (whale.get("spot", {}).get("icebergs") or [])
        if ice:
            ft.add_row("Iceberg", "; ".join(f"{i['side']} x{i['repeats']} "
                                            f"({i['total_notional']:,.0f} USDT)" for i in ice[:3]))
    if book.get("available"):
        ft.add_row("Order Book", f"{book['state']} · yakın denge %{_fmt(book.get('near_imbalance_pct'))} · "
                                 f"spread %{_fmt(book.get('spread_pct'), 4)} · {book['levels_read']} seviye")
        if book.get("bid_walls"):
            ft.add_row("Bid duvarları", "; ".join(f"{w['price']} → {w['notional']:,.0f} USDT "
                                                  f"(x{w['x_average']})" for w in book["bid_walls"][:3]))
        if book.get("ask_walls"):
            ft.add_row("Ask duvarları", "; ".join(f"{w['price']} → {w['notional']:,.0f} USDT "
                                                  f"(x{w['x_average']})" for w in book["ask_walls"][:3]))
        if book.get("spoofs"):
            ft.add_row("[red]Spoof şüphesi[/red]", "; ".join(f"{s['side']} {s['price']} "
                                                             f"({s['notional']:,.0f} USDT)" for s in book["spoofs"][:3]))
        if book.get("absorptions"):
            ft.add_row("Absorption", "; ".join(f"{a['side']} {a['price']}" for a in book["absorptions"][:3]))
    console.print(ft)

    # ---- smart money
    sm = snap["smart_money"]
    if sm.get("available"):
        st = Table(title="Smart Money Engine", header_style="bold")
        st.add_column("Olay"); st.add_column("Detay", overflow="fold")
        for s in sm.get("recent_sweeps", [])[:3]:
            st.add_row(s["type"], f"{s['swept_level']} seviyesi süpürüldü · fitil {s['wick_ratio']} · "
                                  f"hacim x{s.get('volume_ratio')} · {s['bars_ago']} mum önce")
        for b in sm.get("structure_breaks", [])[-3:]:
            st.add_row(f"{b['type']} {b['direction']}",
                       f"{b['broken_level']} kırıldı · {b['bars_ago']} mum önce")
        fvg = sm.get("fvg", {})
        for fv in fvg.get("open", [])[:3]:
            st.add_row(fv["type"], f"{fv['bottom']} - {fv['top']} · uzaklık %{fv['distance_pct']:+.2f} · "
                                   f"{'dokunuldu' if fv['mitigated'] else 'temiz'}")
        for ob in sm.get("order_blocks", {}).get("fresh", [])[:3]:
            st.add_row(ob["type"], f"{ob['bottom']} - {ob['top']} · uzaklık %{ob['distance_pct']:+.2f} · "
                                   f"displacement {ob['displacement_atr']}x ATR")
        if st.row_count:
            console.print(st)

    # ---- risk
    risk = snap["risk"]
    rt = Table(title=f"Risk Engine — {risk['level']} ({risk['points']} puan)", header_style="bold")
    rt.add_column("Faktör"); rt.add_column("Değer"); rt.add_column("Durum")
    for fct in risk["factors"]:
        rt.add_row(fct["factor"], str(fct["value"]), fct["state"])
    console.print(rt)

    # ---- setup
    setup = snap["setup"]
    if setup.get("available"):
        ctx = setup["context"]
        body = Text()
        body.append(f"{setup['direction']}", style="bold green" if setup["direction"] == "LONG" else "bold red")
        body.append(f"   olasılık %{setup['probability']} · R/R {setup['risk_reward']}"
                    f"{'' if setup['rr_ok'] else '  (düşük!)'}\n\n")
        body.append(f"Giriş bölgesi : {setup['entry_zone'][0]} - {setup['entry_zone'][1]}  "
                    f"({setup['entry_basis']})\n")
        body.append(f"Giriş         : {setup['entry']}\n")
        body.append(f"Stop          : {setup['stop']}  ({setup['stop_basis']}, "
                    f"%{setup['stop_distance_pct']})\n")
        for t in setup["targets"]:
            body.append(f"{t['name']}           : {t['price']}  ({t['r_multiple']}R, "
                        f"%{t['gain_pct']:+.2f})\n")
        body.append(f"\nPozisyon      : {setup['position']['qty']} adet "
                    f"(~{_fmt(setup['position']['notional_usdt'], 0)} USDT), "
                    f"risk {_fmt(setup['position']['risk_usdt'], 2)} USDT, "
                    f"maks {setup['position']['suggested_max_leverage']}x\n")
        body.append(f"Bağlam        : Funding {ctx['funding']} · OI {ctx['oi']} · "
                    f"CVD {ctx['cvd']} · Balina {ctx['whales']} · Risk {ctx['risk']}\n")
        if setup.get("invalidation"):
            body.append(f"Geçersizlik   : {'; '.join(setup['invalidation'])}")
        console.print(Panel(body, title="AI Trade Setup",
                            border_style="green" if setup["direction"] == "LONG" else "red"))
    else:
        console.print(Panel(setup.get("reason", "Setup yok"), title="AI Trade Setup",
                            border_style="yellow"))

    if snap.get("alerts"):
        at = Table(title="Tetiklenen Alarmlar", header_style="bold")
        at.add_column("Kural"); at.add_column("Başlık"); at.add_column("Mesaj", overflow="fold")
        for a in snap["alerts"]:
            at.add_row(a["rule"], a["title"], a["message"])
        console.print(at)

    console.print(f"[dim]Tarama süresi: {snap['elapsed_seconds']}s · "
                  f"{snap['timestamp']}[/dim]\n")


def print_ranking(rows: List[Dict[str, Any]]):
    """Terminal darsa sütun sayısı otomatik azaltılır."""
    wide = console.width >= 130
    t = Table(title="Parite Sıralaması", header_style="bold", expand=False)
    t.add_column("#", justify="right", no_wrap=True)
    t.add_column("Parite", no_wrap=True)
    t.add_column("Fiyat", justify="right", no_wrap=True)
    t.add_column("Long", justify="right", no_wrap=True)
    t.add_column("Short", justify="right", no_wrap=True)
    t.add_column("Karar", no_wrap=True)
    t.add_column("OI 1s", justify="right", no_wrap=True)
    t.add_column("Funding", justify="right", no_wrap=True)
    t.add_column("Risk", no_wrap=True)
    if wide:
        t.add_column("Güven", justify="right", no_wrap=True)
        t.add_column("Trend", no_wrap=True)
        t.add_column("CVD", no_wrap=True)
        t.add_column("Balina", no_wrap=True)

    for r in rows:
        style = DECISION_STYLE.get(r["decision"], "white")
        cells = [str(r["rank"]), r["symbol"], f"{r['price']}",
                 f"{r['long_score']:.0f}", f"{r['short_score']:.0f}",
                 f"[{style}]{r['decision']}[/{style}]",
                 f"%{_fmt(r['oi_1h'])}", f"%{_fmt(r['funding'], 4)}", str(r["risk"])]
        if wide:
            cells += [f"%{r['confidence']:.0f}", str(r["trend"]), str(r["cvd"]),
                      str(r["whales"])]
        t.add_row(*cells)
    console.print(t)
    if not wide:
        console.print("[dim]Terminal genişletilirse güven, trend, CVD ve balina "
                      "sütunları da gösterilir.[/dim]")


# ------------------------------------------------------------------ komutlar
def cmd_scan(args):
    from pipeline import scan_symbol
    cfg = get_config()
    symbol = (args.symbol or cfg.primary_symbol).upper()
    with console.status(f"[cyan]{symbol} taranıyor...[/cyan]"):
        snap = scan_symbol(symbol, cfg, save=not args.no_save)
    print_snapshot(snap)


def cmd_rank(args):
    from pipeline import ranking_table, scan_all
    cfg = get_config()
    symbols = args.symbols or cfg.symbols
    with console.status(f"[cyan]{len(symbols)} parite taranıyor...[/cyan]"):
        snaps = scan_all(symbols, cfg, save=not args.no_save)
    print_ranking(ranking_table(snaps))
    if args.detail:
        for s in snaps:
            print_snapshot(s)


def print_screener(df, limit: int = 30):
    """Ön eleme tablosu — tüm piyasadan dikkat çekenler."""
    wide = console.width >= 130
    t = Table(title=f"Tüm Piyasa Ön Elemesi — en dikkat çekici {min(limit, len(df))} "
                    f"parite ({len(df)} parite tarandı)", header_style="bold")
    t.add_column("#", justify="right", no_wrap=True)
    t.add_column("Parite", no_wrap=True)
    t.add_column("Fiyat", justify="right", no_wrap=True)
    t.add_column("24s %", justify="right", no_wrap=True)
    t.add_column("Dikkat", justify="right", no_wrap=True)
    t.add_column("OI 1s %", justify="right", no_wrap=True)
    t.add_column("Fiyat 1s %", justify="right", no_wrap=True)
    t.add_column("Durum", no_wrap=True)
    t.add_column("Funding", justify="right", no_wrap=True)
    if wide:
        t.add_column("24s Hacim", justify="right", no_wrap=True)
        t.add_column("Ön eğilim", no_wrap=True)

    for rank, (_, r) in enumerate(df.head(limit).iterrows(), start=1):
        chg = r.get("priceChangePercent")
        chg_col = "green" if (chg or 0) > 0 else "red"
        p1h = r.get("price_change_1h")
        p1h_col = "green" if (p1h or 0) > 0 else "red"
        bias_col = {"LONG EĞİLİM": "green", "SHORT EĞİLİM": "red"}.get(
            r.get("bias_label", ""), "yellow")
        cells = [
            str(rank), str(r["symbol"]), f"{r.get('lastPrice')}",
            f"[{chg_col}]{_fmt(chg)}[/{chg_col}]",
            f"{r.get('interest')}",
            f"{_fmt(r.get('oi_change_1h'))}",
            f"[{p1h_col}]{_fmt(p1h)}[/{p1h_col}]",
            str(r.get("oi_state", "")),
            f"{_fmt(r.get('funding_pct'), 4)}",
        ]
        if wide:
            vol = r.get("quoteVolume") or 0
            cells += [f"{vol / 1e6:,.0f}M",
                      f"[{bias_col}]{r.get('bias_label', '')}[/{bias_col}]"]
        t.add_row(*cells)
    console.print(t)
    if not wide:
        console.print("[dim]Terminali genişletirseniz hacim ve ön eğilim sütunları "
                      "da görünür.[/dim]")


def cmd_market(args):
    from pipeline import ranking_table, scan_market

    cfg = get_config()
    overrides = {}
    if args.all:
        overrides["market.min_quote_volume_usdt"] = 0
        overrides["market.oi_enrich_top"] = 600
    elif args.min_volume is not None:
        overrides["market.min_quote_volume_usdt"] = args.min_volume
    if overrides:
        cfg = cfg.with_overrides(overrides)

    status = console.status("[cyan]Tüm piyasa taranıyor...[/cyan]")
    status.start()

    def progress(msg: str):
        status.update(f"[cyan]{msg}[/cyan]")

    try:
        result = scan_market(cfg, top_n=args.top, deep=not args.no_deep,
                             save=not args.no_save, progress=progress)
    finally:
        status.stop()

    screened = result["screened"]
    if screened is None or screened.empty:
        console.print("[red]Ön eleme sonuç vermedi.[/red]")
        return

    print_screener(screened, args.list)

    if args.no_deep:
        console.print("[dim]--no-deep verildiği için derin tarama yapılmadı.[/dim]")
        return

    snaps = result["snapshots"]
    if snaps:
        console.print()
        print_ranking(ranking_table(snaps))
        best = snaps[0]
        console.print(f"\n[bold]En yüksek skor:[/bold] {best['symbol']} — "
                      f"{best['score']['decision']} "
                      f"(Long {best['score']['long_score']}/100)")
        if args.detail:
            for s in snaps[:args.detail]:
                print_snapshot(s)
        else:
            console.print("[dim]Tek parite detayı için: python run.py scan SEMBOL[/dim]")


def cmd_watch(args):
    from scheduler import run_forever
    console.print("[green]Zamanlayıcı başlatılıyor... (Ctrl+C ile durdurun)[/green]")
    run_forever(args.symbols or None, get_config(), scan_now=not args.no_initial)


def cmd_collect(args):
    from collectors.liquidations import start_collector
    cfg = get_config()
    symbols = args.symbols or cfg.symbols
    console.print(f"[green]Likidasyon akışı dinleniyor: {', '.join(symbols)} "
                  f"(Ctrl+C ile durdurun)[/green]")
    try:
        start_collector(symbols, block=True)
    except KeyboardInterrupt:
        console.print("[yellow]Durduruldu[/yellow]")


def cmd_report(args):
    from report import daily_report
    cfg = get_config()
    with console.status("[cyan]Rapor hazırlanıyor...[/cyan]"):
        content = daily_report(args.symbols or None, cfg, send=not args.no_send,
                               use_cache=args.cached)
    console.print(content)


def local_ip() -> str:
    """Bu makinenin yerel ağdaki IP adresi."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def cmd_serve(args):
    """Streamlit'i başlatır ve tarayıcıyı kendimiz açarız.

    headless=true veriyoruz: aksi hâlde Streamlit ilk çalıştırmada terminalde
    e-posta soruyor ve sunucu o soruya cevap verilene kadar açılmıyor.
    --lan ile telefon/başka bilgisayarlardan erişim için 0.0.0.0'a bağlanır.
    """
    import os
    import threading
    import webbrowser

    app = ROOT / "dashboard" / "app.py"
    address = "0.0.0.0" if args.lan else "localhost"
    url = f"http://localhost:{args.port}"

    cmd = [sys.executable, "-m", "streamlit", "run", str(app),
           "--server.port", str(args.port),
           "--server.address", address,
           "--server.headless", "true",
           "--browser.gatherUsageStats", "false"]

    console.print(f"[green]Streamlit başlatılıyor: {url}[/green]")

    if args.lan:
        ip = local_ip()
        console.print(Panel(
            Text.assemble(
                ("Aynı Wi-Fi ağındaki cihazlardan erişim:\n\n", "white"),
                (f"   http://{ip}:{args.port}\n\n", "bold cyan"),
                ("Telefonun tarayıcısına bu adresi yazın. "
                 "Mac uyku moduna geçerse bağlantı kesilir.", "dim"),
            ), title="📱 Ağ Erişimi", border_style="cyan"))

        get_config()  # .env yüklenir
        if not os.getenv("DASHBOARD_PASSWORD", "").strip():
            console.print("[yellow]⚠ Parola tanımlı değil — panel yerel ağdaki herkese "
                          "açık. .env dosyasına DASHBOARD_PASSWORD ekleyin.[/yellow]")

    console.print("[dim]Durdurmak için Ctrl+C[/dim]")

    if not args.no_browser:
        threading.Timer(3.0, lambda: webbrowser.open(url)).start()
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        pass


def cmd_check(args):
    from core.binance import get_client
    cfg = get_config()
    client = get_client(cfg)
    symbol = (args.symbol or cfg.primary_symbol).upper()

    t = Table(title=f"Veri Kaynağı Kontrolü — {symbol}", header_style="bold")
    t.add_column("Uç nokta"); t.add_column("Durum"); t.add_column("Örnek", overflow="fold")

    checks = [
        ("Vadeli mum (1h)", lambda: f"{len(client.klines(symbol, '1h', 100))} mum"),
        ("Mark/Funding", lambda: f"funding {float(client.mark_price(symbol)['lastFundingRate']) * 100:.4f}%"),
        ("Open Interest", lambda: f"{float(client.open_interest(symbol)['openInterest']):,.0f}"),
        ("OI geçmişi", lambda: f"{len(client.open_interest_hist(symbol, '5m', 100))} kayıt"),
        ("Long/Short oranı", lambda: f"{len(client.top_positions_ratio(symbol))} kayıt"),
        ("Taker oranı", lambda: f"{len(client.taker_ratio(symbol))} kayıt"),
        ("Order book", lambda: f"{len(client.depth(symbol, 100)['bids'])} bid seviyesi"),
        ("Agg trades", lambda: f"{len(client.agg_trades(symbol, 1000, 1))} işlem"),
    ]
    for name, fn in checks:
        try:
            t.add_row(name, "[green]OK[/green]", str(fn()))
        except Exception as exc:  # noqa: BLE001
            t.add_row(name, "[red]HATA[/red]", str(exc)[:120])

    spot_map = client.spot_symbol_for(symbol)
    if spot_map:
        try:
            price = client.spot_price(spot_map["symbol"])
            t.add_row("Spot eşleşmesi", "[green]OK[/green]",
                      f"{spot_map['symbol']} @ {price} (çarpan x{spot_map['multiplier']})")
        except Exception as exc:  # noqa: BLE001
            t.add_row("Spot eşleşmesi", "[red]HATA[/red]", str(exc)[:120])
    else:
        t.add_row("Spot eşleşmesi", "[yellow]YOK[/yellow]", "Spot CVD devre dışı kalacak")

    console.print(t)


def main():
    parser = argparse.ArgumentParser(
        description="Crypto Intelligence Dashboard — Binance vadeli piyasa tarayıcı")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="Tek parite için tam tarama")
    p.add_argument("symbol", nargs="?", help="Örn: 1000SHIBUSDT")
    p.add_argument("--no-save", action="store_true", help="Veritabanına yazma")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("rank", help="Tüm pariteleri tara ve sırala")
    p.add_argument("symbols", nargs="*", help="Boş bırakılırsa config.yaml kullanılır")
    p.add_argument("--detail", action="store_true", help="Her parite için tam rapor da yazdır")
    p.add_argument("--no-save", action="store_true")
    p.set_defaults(func=cmd_rank)

    p = sub.add_parser("market", help="Binance vadelideki TÜM pariteleri tara")
    p.add_argument("--top", type=int, default=None,
                   help="Kaç parite derin taransın (varsayılan: config market.deep_scan_top)")
    p.add_argument("--list", type=int, default=30,
                   help="Ön eleme tablosunda kaç satır gösterilsin (varsayılan 30)")
    p.add_argument("--no-deep", action="store_true",
                   help="Sadece ön eleme yap, derin tarama yapma (çok hızlı)")
    p.add_argument("--all", action="store_true",
                   help="Hacim filtresi olmadan piyasadaki TÜM pariteleri ön ele")
    p.add_argument("--min-volume", type=float, default=None,
                   help="24s hacim alt sınırı (USDT). Örn: 1000000")
    p.add_argument("--detail", type=int, default=0,
                   help="İlk N parite için tam rapor da yazdır")
    p.add_argument("--no-save", action="store_true")
    p.set_defaults(func=cmd_market)

    p = sub.add_parser("watch", help="Zamanlayıcıyı başlat (saatlik tarama + alarmlar)")
    p.add_argument("symbols", nargs="*")
    p.add_argument("--no-initial", action="store_true", help="Başlangıçta taramayı atla")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("collect", help="Likidasyon websocket toplayıcısı")
    p.add_argument("symbols", nargs="*")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("report", help="Günlük raporu üret")
    p.add_argument("symbols", nargs="*")
    p.add_argument("--no-send", action="store_true", help="Telegram/e-posta gönderme")
    p.add_argument("--cached", action="store_true", help="Yeni tarama yapmadan son veriyi kullan")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("serve", help="Streamlit arayüzünü aç")
    p.add_argument("--port", type=int, default=8501)
    p.add_argument("--no-browser", action="store_true", help="Tarayıcıyı otomatik açma")
    p.add_argument("--lan", action="store_true",
                   help="Telefon/diğer bilgisayarlardan erişim için yerel ağa aç")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("check", help="Veri kaynaklarını test et")
    p.add_argument("symbol", nargs="?")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args()
    cfg = get_config()
    setup_logging(cfg.path_for("storage.log_path", "logs/scanner.log"))
    args.func(args)


if __name__ == "__main__":
    main()
