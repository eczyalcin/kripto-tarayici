"""APScheduler tabanlı görev zamanlayıcı.

İşler:
  - full_scan       : tüm motorlar (varsayılan saatlik)
  - fast_derivatives: sadece türev verisi + alarm kontrolü (varsayılan 5 dakika)
  - daily_report    : her sabah özet rapor
  - prune           : eski kayıtların temizliği
Ayrıca likidasyon websocket toplayıcısını arka planda başlatır.
"""
from __future__ import annotations

import signal
import time
from typing import List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.binance import get_client
from core.config import Config, get_config
from core.logging_setup import log, setup_logging
from core.storage import get_storage
from engines import derivatives as derivatives_engine
from pipeline import scan_all, scan_symbol


def _full_scan(cfg: Config, symbols: List[str]):
    log.info("=== Tam tarama başlıyor ===")
    try:
        results = scan_all(symbols, cfg)
        for r in results:
            log.info(f"  {r['symbol']}: {r['score']['decision']} "
                     f"(L{r['score']['long_score']}/S{r['score']['short_score']})")
    except Exception as exc:  # noqa: BLE001
        log.error(f"Tam tarama hatası: {exc}")


def _fast_derivatives(cfg: Config, symbols: List[str]):
    """5 dakikada bir türev verisi: OI/funding/likidasyon alarmları için."""
    client = get_client(cfg)
    storage = get_storage()
    from alerts.notifier import dispatch
    from alerts.rules import evaluate

    for sym in symbols:
        try:
            spot_map = client.spot_symbol_for(sym)
            deriv = derivatives_engine.run(sym, client, cfg, storage, spot_map)
            previous = storage.latest_snapshot(sym)
            if not previous:
                continue
            # Sadece türev bölümü güncellenmiş sanal bir snapshot ile kural kontrolü
            probe = dict(previous)
            probe["derivatives"] = deriv
            probe["timestamp"] = None
            probe["whale"] = {"new_whale_trades": []}
            probe["smart_money"] = {"structure_breaks": [], "recent_sweeps": [],
                                    "fvg": {"open": []}}
            triggered = [a for a in evaluate(probe, previous, cfg, storage)
                         if a["rule"] in ("oi_change", "funding", "liquidation",
                                          "squeeze_SHORT_SQUEEZE", "squeeze_LONG_SQUEEZE")]
            if triggered:
                dispatch(triggered, cfg, storage)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"{sym} hızlı türev kontrolü başarısız: {exc}")


def _market_scan(cfg: Config):
    """Tüm piyasa ön elemesi + öne çıkanların derin taraması."""
    from pipeline import scan_market
    log.info("=== Tüm piyasa taraması başlıyor ===")
    try:
        result = scan_market(cfg, deep=True, save=True)
        snaps = result.get("snapshots", [])
        for r in snaps[:5]:
            log.info(f"  {r['symbol']}: {r['score']['decision']} "
                     f"(L{r['score']['long_score']})")
    except Exception as exc:  # noqa: BLE001
        log.error(f"Piyasa taraması hatası: {exc}")


def _daily_report(cfg: Config, symbols: List[str]):
    from report import daily_report
    log.info("=== Günlük rapor üretiliyor ===")
    try:
        daily_report(symbols, cfg, send=True)
    except Exception as exc:  # noqa: BLE001
        log.error(f"Günlük rapor hatası: {exc}")


def _prune(cfg: Config):
    try:
        get_storage().prune(cfg.get("storage.keep_days", 30))
        log.info("Eski kayıtlar temizlendi")
    except Exception as exc:  # noqa: BLE001
        log.warning(f"Temizlik başarısız: {exc}")


def build_scheduler(cfg: Optional[Config] = None,
                    symbols: Optional[List[str]] = None) -> BackgroundScheduler:
    cfg = cfg or get_config()
    symbols = symbols or cfg.symbols
    sch = cfg.get("scheduler", {})

    # Günlük rapor saati yerel saate göre olsun (UTC'de 08:00 Türkiye'de 11:00 demekti)
    tz = sch.get("timezone") or None
    scheduler = BackgroundScheduler(timezone=tz) if tz else BackgroundScheduler()
    scheduler.add_job(_full_scan, IntervalTrigger(minutes=sch.get("scan_interval_minutes", 60)),
                      args=[cfg, symbols], id="full_scan", max_instances=1,
                      coalesce=True, next_run_time=None)
    scheduler.add_job(_fast_derivatives,
                      IntervalTrigger(minutes=sch.get("fast_interval_minutes", 5)),
                      args=[cfg, symbols], id="fast_derivatives", max_instances=1,
                      coalesce=True)
    market_hours = sch.get("market_scan_hours", 0)
    if market_hours:
        scheduler.add_job(_market_scan, IntervalTrigger(hours=market_hours),
                          args=[cfg], id="market_scan", max_instances=1, coalesce=True)
    scheduler.add_job(_daily_report,
                      CronTrigger(hour=sch.get("daily_report_hour", 8),
                                  minute=sch.get("daily_report_minute", 0)),
                      args=[cfg, symbols], id="daily_report")
    scheduler.add_job(_prune, CronTrigger(hour=3, minute=30), args=[cfg], id="prune")
    return scheduler


def run_forever(symbols: Optional[List[str]] = None, cfg: Optional[Config] = None,
                scan_now: bool = True):
    cfg = cfg or get_config()
    setup_logging(cfg.path_for("storage.log_path", "logs/scanner.log"))
    symbols = symbols or cfg.symbols

    collector = None
    if cfg.get("scheduler.collect_liquidations", True):
        from collectors.liquidations import start_collector
        collector = start_collector(symbols)

    scheduler = build_scheduler(cfg, symbols)
    scheduler.start()
    log.info(f"Zamanlayıcı çalışıyor · pariteler: {', '.join(symbols)} · "
             f"tam tarama her {cfg.get('scheduler.scan_interval_minutes', 60)} dk · "
             f"türev kontrolü her {cfg.get('scheduler.fast_interval_minutes', 5)} dk")

    if scan_now:
        _full_scan(cfg, symbols)

    stop = False

    def _handle(_sig, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    try:
        while not stop:
            time.sleep(1)
    finally:
        log.info("Kapatılıyor...")
        scheduler.shutdown(wait=False)
        if collector:
            collector.stop()
