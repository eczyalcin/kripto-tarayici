"""Tarama hattı — tüm motorları sırayla çalıştırıp tek bir snapshot üretir."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import pandas as pd

from core.binance import BinanceClient, get_client
from core.config import Config, get_config
from core.logging_setup import log
from core.storage import Storage, get_storage, iso
from engines import derivatives as derivatives_engine
from engines import order_flow as flow_engine
from engines import orderbook as book_engine
from engines import risk as risk_engine
from engines import scoring as scoring_engine
from engines import smart_money as sm_engine
from engines import trade_setup as setup_engine
from engines import trend as trend_engine
from engines import whale as whale_engine


def fetch_candles(client: BinanceClient, symbol: str, cfg: Config) -> Dict[str, pd.DataFrame]:
    tf = cfg.get("timeframes", {})
    limit = tf.get("klines_limit", 500)
    out: Dict[str, pd.DataFrame] = {}
    for key in ("ltf", "mtf", "htf"):
        interval = tf.get(key)
        if not interval:
            continue
        try:
            out[key] = client.klines(symbol, interval, limit)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"{symbol} {interval} mumları alınamadı: {exc}")
            out[key] = pd.DataFrame()
    return out


def scan_symbol(symbol: str, cfg: Optional[Config] = None,
                client: Optional[BinanceClient] = None,
                storage: Optional[Storage] = None,
                save: bool = True,
                run_alerts: bool = True) -> Dict[str, Any]:
    """Tek parite için tam tarama. Tüm motorların çıktısını içeren snapshot döner."""
    cfg = cfg or get_config()
    client = client or get_client(cfg)
    storage = storage or get_storage()
    t0 = time.time()

    log.info(f"[{symbol}] tarama başladı")
    spot_map = client.spot_symbol_for(symbol)
    candles = fetch_candles(client, symbol, cfg)

    engines: Dict[str, Any] = {}

    # 1) Trend
    engines["trend"] = trend_engine.run(candles, cfg)

    # 2) Smart Money
    engines["smart_money"] = sm_engine.run(candles, cfg)

    # 3) Derivatives
    engines["derivatives"] = derivatives_engine.run(symbol, client, cfg, storage, spot_map)

    # 4) Order Flow / Spot (agg-trade akışını bir kez çeker, whale motoru yeniden kullanır)
    engines["order_flow"] = flow_engine.run(symbol, client, cfg, spot_map)
    fut_trades = engines["order_flow"].get("_futures_trades")

    # 5) Whale
    engines["whale"] = whale_engine.run(symbol, cfg, engines["order_flow"], storage)

    # 6) Order Book
    engines["orderbook"] = book_engine.run(symbol, client, cfg, storage, fut_trades)

    # Ham işlem tabloları snapshot'a yazılmaz (JSON boyutu için)
    engines["order_flow"].pop("_futures_trades", None)
    engines["order_flow"].pop("_spot_trades", None)

    # 7) Skor
    score = scoring_engine.run(engines, cfg)

    # 8) Risk
    risk = risk_engine.run(engines, cfg)

    # 9) Trade Setup
    try:
        tick = client.tick_size(symbol)
        precision = client.price_precision(symbol)
    except Exception:  # noqa: BLE001
        tick, precision = 0.0, 8
    setup = setup_engine.run(symbol, engines, score, risk, cfg, tick, precision)

    price = engines["trend"].get("price") or engines["orderbook"].get("mid_price")

    snapshot: Dict[str, Any] = {
        "symbol": symbol,
        "timestamp": iso(),
        "price": price,
        "spot_symbol": spot_map,
        "trend": engines["trend"],
        "smart_money": engines["smart_money"],
        "derivatives": engines["derivatives"],
        "order_flow": engines["order_flow"],
        "whale": engines["whale"],
        "orderbook": engines["orderbook"],
        "score": score,
        "risk": risk,
        "setup": setup,
        "elapsed_seconds": round(time.time() - t0, 2),
    }

    triggered: List[Dict[str, Any]] = []
    if run_alerts and cfg.get("alerts.enabled", True):
        from alerts.rules import evaluate           # döngüsel import olmaması için burada
        from alerts.notifier import dispatch
        previous = storage.latest_snapshot(symbol) if storage else None
        triggered = evaluate(snapshot, previous, cfg, storage)
        if triggered:
            dispatch(triggered, cfg, storage)
    snapshot["alerts"] = triggered

    if save and storage:
        storage.save_snapshot(snapshot)

    log.info(f"[{symbol}] tamamlandı — {score['decision']} "
             f"(Long {score['long_score']}/100, güven %{score['confidence']}) "
             f"[{snapshot['elapsed_seconds']}s]")
    return snapshot


def scan_all(symbols: Optional[List[str]] = None, cfg: Optional[Config] = None,
             save: bool = True) -> List[Dict[str, Any]]:
    """Tüm pariteleri tarar ve skor sırasına göre sıralanmış özet listesi döner."""
    cfg = cfg or get_config()
    client = get_client(cfg)
    storage = get_storage()
    symbols = symbols or cfg.symbols

    results: List[Dict[str, Any]] = []
    for sym in symbols:
        try:
            snap = scan_symbol(sym, cfg, client, storage, save=save)
            results.append(snap)
        except Exception as exc:  # noqa: BLE001
            log.error(f"{sym} taranamadı: {exc}")

    return sorted(results, key=lambda s: s["score"]["long_score"], reverse=True)


def scan_market(cfg: Optional[Config] = None, top_n: Optional[int] = None,
                deep: bool = True, save: bool = True,
                progress=None) -> Dict[str, Any]:
    """Binance vadelideki TÜM pariteleri tarar.

    1. Ön eleme: tüm piyasa ucuz toplu veriyle elenir (screener)
    2. Derin tarama: öne çıkan pariteler 9 motorlu hattan geçer

    Dönüş: {"screened": DataFrame, "snapshots": [...], "candidates": [...]}
    """
    import pandas as pd

    from engines.screener import pick_candidates, screen_market

    cfg = cfg or get_config()
    client = get_client(cfg)
    storage = get_storage()

    t0 = time.time()
    screened = screen_market(client, cfg, progress=progress)
    if screened.empty:
        log.error("Ön eleme boş döndü")
        return {"screened": screened, "snapshots": [], "candidates": []}

    log.info(f"Ön eleme tamamlandı: {len(screened)} parite "
             f"[{round(time.time() - t0, 1)}s]")

    if save:
        try:
            storage.save_screening(screened.to_dict("records"))
        except Exception as exc:  # noqa: BLE001
            log.warning(f"Ön eleme kaydedilemedi: {exc}")

    if not deep:
        return {"screened": screened, "snapshots": [], "candidates": []}

    candidates = pick_candidates(screened, cfg, top_n)
    log.info(f"Derin tarama listesi ({len(candidates)}): {', '.join(candidates)}")

    # Derin taramada işlem akışı sayfasını düşürüyoruz: 20 parite x 3 sayfa
    # agg-trade dakikalık ağırlık limitini zorlardı.
    pages = cfg.get("market.deep_scan_agg_pages", 1)
    deep_cfg = cfg.with_overrides({"data.agg_trades_pages": pages})

    snapshots: List[Dict[str, Any]] = []
    for i, sym in enumerate(candidates, start=1):
        if progress:
            progress(f"Derin tarama {i}/{len(candidates)}: {sym}")
        try:
            snapshots.append(scan_symbol(sym, deep_cfg, client, storage, save=save))
        except Exception as exc:  # noqa: BLE001
            log.error(f"{sym} derin tarama hatası: {exc}")

    snapshots.sort(key=lambda s: s["score"]["long_score"], reverse=True)
    log.info(f"Tüm piyasa taraması bitti — {len(snapshots)} parite derin tarandı "
             f"[toplam {round(time.time() - t0, 1)}s]")

    return {"screened": screened, "snapshots": snapshots, "candidates": candidates}


def ranking_table(snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Nihai hedefteki sıralama tablosu."""
    rows: List[Dict[str, Any]] = []
    for i, s in enumerate(sorted(snapshots, key=lambda x: x["score"]["long_score"],
                                 reverse=True), start=1):
        setup = s.get("setup", {})
        rows.append({
            "rank": i,
            "symbol": s["symbol"],
            "price": s["price"],
            "long_score": s["score"]["long_score"],
            "short_score": s["score"]["short_score"],
            "decision": s["score"]["decision"],
            "confidence": s["score"]["confidence"],
            "trend": s["trend"].get("label"),
            "oi_1h": s["derivatives"].get("open_interest", {}).get("change_1h_pct"),
            "funding": s["derivatives"].get("funding", {}).get("current_pct"),
            "cvd": s["order_flow"].get("label"),
            "whales": s["whale"].get("state"),
            "risk": s["risk"].get("level"),
            "setup": setup.get("direction") if setup.get("available") else "-",
        })
    return rows
