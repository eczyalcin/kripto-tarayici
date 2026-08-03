"""Likidasyon toplayıcı (WebSocket).

Binance likidasyon (force order) verisini REST ile vermez; sadece
`<symbol>@forceOrder` akışından yayınlar. Bu toplayıcı arka planda çalışıp
verileri SQLite'a yazar, Derivatives Engine de oradan okur.

Akıştaki `S` alanı zorunlu kapanış emrinin yönüdür:
    SELL -> LONG pozisyon likide oldu
    BUY  -> SHORT pozisyon likide oldu
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import websocket

from core.config import Config, get_config
from core.logging_setup import log
from core.storage import Storage, get_storage

WS_BASE = "wss://fstream.binance.com/stream?streams="


class LiquidationCollector:
    def __init__(self, symbols: List[str], storage: Optional[Storage] = None,
                 cfg: Optional[Config] = None):
        self.cfg = cfg or get_config()
        self.symbols = [s.upper() for s in symbols]
        self.storage = storage or get_storage()
        self.ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.count = 0

    # ------------------------------------------------------------- callbacks
    def _on_message(self, _ws, message: str):
        try:
            payload = json.loads(message)
            data = payload.get("data", payload)
            if data.get("e") != "forceOrder":
                return
            o = data["o"]
            symbol = o["s"]
            if symbol not in self.symbols:
                return
            price = float(o.get("ap") or o.get("p") or 0)
            qty = float(o.get("l") or o.get("q") or 0)
            ts = datetime.fromtimestamp(int(o["T"]) / 1000, tz=timezone.utc).isoformat()
            notional = price * qty
            self.storage.add_liquidation(symbol, ts, o["S"], price, qty, notional)
            self.count += 1
            kind = "LONG" if o["S"] == "SELL" else "SHORT"
            if notional >= 10_000:
                log.info(f"💥 {symbol} {kind} likidasyonu {notional:,.0f} USDT @ {price}")
        except Exception as exc:  # noqa: BLE001
            log.debug(f"Likidasyon mesajı işlenemedi: {exc}")

    def _on_error(self, _ws, error):
        log.warning(f"Likidasyon websocket hatası: {error}")

    def _on_close(self, _ws, code, msg):
        log.info(f"Likidasyon websocket kapandı ({code} {msg})")

    def _on_open(self, _ws):
        log.info(f"Likidasyon akışı bağlandı: {', '.join(self.symbols)}")

    # ----------------------------------------------------------------- döngü
    def _url(self) -> str:
        streams = "/".join(f"{s.lower()}@forceOrder" for s in self.symbols)
        return WS_BASE + streams

    def _run_forever(self):
        backoff = 1
        while not self._stop.is_set():
            try:
                self.ws = websocket.WebSocketApp(
                    self._url(),
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                )
                self.ws.run_forever(ping_interval=180, ping_timeout=10)
            except Exception as exc:  # noqa: BLE001
                log.warning(f"Likidasyon akışı koptu: {exc}")
            if self._stop.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def start(self, block: bool = False):
        if block:
            self._run_forever()
            return
        self._thread = threading.Thread(target=self._run_forever, daemon=True,
                                        name="liquidation-collector")
        self._thread.start()
        log.info("Likidasyon toplayıcı arka planda başlatıldı")

    def stop(self):
        self._stop.set()
        if self.ws:
            try:
                self.ws.close()
            except Exception:  # noqa: BLE001
                pass


def start_collector(symbols: Optional[List[str]] = None, block: bool = False
                    ) -> LiquidationCollector:
    cfg = get_config()
    collector = LiquidationCollector(symbols or cfg.symbols, get_storage(), cfg)
    collector.start(block=block)
    return collector
