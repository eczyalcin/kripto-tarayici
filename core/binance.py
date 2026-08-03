"""Binance Futures + Spot REST istemcisi.

Sadece halka açık market data uçları kullanılır; API anahtarı gerekmez.
Tüm çağrılar TTL önbellekli, tekrar denemeli ve rate-limit dostudur.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from core.config import Config, get_config
from core.logging_setup import log

FUTURES_BASE = "https://fapi.binance.com"
SPOT_BASE = "https://api.binance.com"

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
]


class BinanceError(RuntimeError):
    pass


class _TTLCache:
    def __init__(self, ttl: float):
        self.ttl = ttl
        self._store: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            hit = self._store.get(key)
        if not hit:
            return None
        ts, value = hit
        if time.time() - ts > self.ttl:
            return None
        return value

    def set(self, key: str, value: Any):
        with self._lock:
            self._store[key] = (time.time(), value)

    def clear(self):
        with self._lock:
            self._store.clear()


class BinanceClient:
    """İhtiyaç duyulan tüm market-data uçlarını kapsayan ince istemci."""

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or get_config()
        self.timeout = self.cfg.get("data.request_timeout", 15)
        self.max_retries = self.cfg.get("data.max_retries", 3)
        self.cache = _TTLCache(self.cfg.get("data.cache_ttl_seconds", 20))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "crypto-intel-dashboard/1.0"})
        self._exchange_info: Optional[Dict[str, Any]] = None
        self._spot_symbols: Optional[set] = None

    # ------------------------------------------------------------------ core
    def _request(self, base: str, path: str, params: Optional[dict] = None,
                 cache: bool = True) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = f"{base}{path}?{sorted(params.items())}"
        if cache:
            cached = self.cache.get(key)
            if cached is not None:
                return cached

        url = base + path
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code == 418:
                    wait = min(2 ** attempt * 2, 30)
                    log.warning(f"Rate limit ({resp.status_code}) -> {wait}s bekleniyor: {path}")
                    time.sleep(wait)
                    continue
                if resp.status_code >= 400:
                    raise BinanceError(f"{resp.status_code} {path}: {resp.text[:200]}")
                data = resp.json()
                if cache:
                    self.cache.set(key, data)
                return data
            except (requests.RequestException, ValueError) as exc:  # ağ / json hatası
                last_err = exc
                time.sleep(min(2 ** attempt, 8))
        raise BinanceError(f"İstek başarısız: {path} -> {last_err}")

    def _fut(self, path: str, params: Optional[dict] = None, cache: bool = True):
        return self._request(FUTURES_BASE, path, params, cache)

    def _spot(self, path: str, params: Optional[dict] = None, cache: bool = True):
        return self._request(SPOT_BASE, path, params, cache)

    # ------------------------------------------------------- sembol eşleştirme
    def spot_symbol_for(self, futures_symbol: str) -> Optional[Dict[str, Any]]:
        """Vadeli sembolün spot karşılığını ve fiyat çarpanını döndürür.

        1000SHIBUSDT gibi çarpanlı vadeli semboller spotta SHIBUSDT olarak işlem
        görür ve fiyatı 1000 kat küçüktür. Bu eşleme burada çözülür.
        """
        if self._spot_symbols is None:
            try:
                info = self._spot("/api/v3/exchangeInfo", {"permissions": "SPOT"})
                self._spot_symbols = {s["symbol"] for s in info.get("symbols", [])
                                      if s.get("status") == "TRADING"}
            except BinanceError as exc:
                log.warning(f"Spot exchangeInfo alınamadı: {exc}")
                self._spot_symbols = set()

        if futures_symbol in self._spot_symbols:
            return {"symbol": futures_symbol, "multiplier": 1}

        for prefix in ("1000000", "10000", "1000"):
            if futures_symbol.startswith(prefix):
                candidate = futures_symbol[len(prefix):]
                if candidate in self._spot_symbols:
                    return {"symbol": candidate, "multiplier": int(prefix)}
        return None

    def exchange_info(self, symbol: str) -> Dict[str, Any]:
        if self._exchange_info is None:
            self._exchange_info = self._fut("/fapi/v1/exchangeInfo")
        for s in self._exchange_info.get("symbols", []):
            if s["symbol"] == symbol:
                return s
        return {}

    def tick_size(self, symbol: str) -> float:
        info = self.exchange_info(symbol)
        for f in info.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                return float(f["tickSize"])
        return 0.0

    def price_precision(self, symbol: str) -> int:
        info = self.exchange_info(symbol)
        return int(info.get("pricePrecision", 6))

    # -------------------------------------------------------------- mum verisi
    @staticmethod
    def _klines_to_df(raw: List[list]) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame(columns=KLINE_COLUMNS)
        df = pd.DataFrame(raw, columns=KLINE_COLUMNS)
        numeric = ["open", "high", "low", "close", "volume", "quote_volume",
                   "taker_buy_base", "taker_buy_quote", "trades"]
        for col in numeric:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        df = df.drop(columns=["ignore"])
        return df.reset_index(drop=True)

    def klines(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
        raw = self._fut("/fapi/v1/klines",
                        {"symbol": symbol, "interval": interval, "limit": limit})
        return self._klines_to_df(raw)

    def spot_klines(self, symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
        raw = self._spot("/api/v3/klines",
                         {"symbol": symbol, "interval": interval, "limit": limit})
        return self._klines_to_df(raw)

    # ------------------------------------------------------------ fiyat / özet
    def mark_price(self, symbol: str) -> Dict[str, Any]:
        """markPrice, indexPrice, lastFundingRate, nextFundingTime."""
        return self._fut("/fapi/v1/premiumIndex", {"symbol": symbol})

    def ticker_24h(self, symbol: str) -> Dict[str, Any]:
        return self._fut("/fapi/v1/ticker/24hr", {"symbol": symbol})

    def spot_price(self, symbol: str) -> float:
        data = self._spot("/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])

    # -------------------------------------------------------------- türev veri
    def open_interest(self, symbol: str) -> Dict[str, Any]:
        return self._fut("/fapi/v1/openInterest", {"symbol": symbol}, cache=False)

    def open_interest_hist(self, symbol: str, period: str = "5m",
                           limit: int = 200) -> pd.DataFrame:
        raw = self._fut("/futures/data/openInterestHist",
                        {"symbol": symbol, "period": period, "limit": min(limit, 500)})
        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for c in ("sumOpenInterest", "sumOpenInterestValue"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.sort_values("timestamp").reset_index(drop=True)

    def funding_history(self, symbol: str, limit: int = 30) -> pd.DataFrame:
        raw = self._fut("/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})
        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw)
        df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
        df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
        return df.sort_values("fundingTime").reset_index(drop=True)

    def _ratio_frame(self, path: str, symbol: str, period: str, limit: int) -> pd.DataFrame:
        raw = self._fut(path, {"symbol": symbol, "period": period, "limit": min(limit, 500)})
        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for c in df.columns:
            if c not in ("timestamp", "symbol", "pair"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.sort_values("timestamp").reset_index(drop=True)

    def top_accounts_ratio(self, symbol: str, period="1h", limit=24) -> pd.DataFrame:
        return self._ratio_frame("/futures/data/topLongShortAccountRatio", symbol, period, limit)

    def top_positions_ratio(self, symbol: str, period="1h", limit=24) -> pd.DataFrame:
        return self._ratio_frame("/futures/data/topLongShortPositionRatio", symbol, period, limit)

    def global_accounts_ratio(self, symbol: str, period="1h", limit=24) -> pd.DataFrame:
        return self._ratio_frame("/futures/data/globalLongShortAccountRatio", symbol, period, limit)

    def taker_ratio(self, symbol: str, period="5m", limit=24) -> pd.DataFrame:
        return self._ratio_frame("/futures/data/takerlongshortRatio", symbol, period, limit)

    # ------------------------------------------------------------- order book
    def depth(self, symbol: str, limit: int = 100) -> Dict[str, Any]:
        valid = [5, 10, 20, 50, 100, 500, 1000]
        limit = min([v for v in valid if v >= limit] or [1000])
        return self._fut("/fapi/v1/depth", {"symbol": symbol, "limit": limit}, cache=False)

    def spot_depth(self, symbol: str, limit: int = 100) -> Dict[str, Any]:
        return self._spot("/api/v3/depth", {"symbol": symbol, "limit": limit}, cache=False)

    # ----------------------------------------------------------------- işlemler
    def agg_trades(self, symbol: str, limit: int = 1000, pages: int = 1,
                   spot: bool = False) -> pd.DataFrame:
        """Son N agg-trade. pages>1 ise fromId ile geriye doğru sayfalanır."""
        path = "/api/v3/aggTrades" if spot else "/fapi/v1/aggTrades"
        fetch = self._spot if spot else self._fut

        frames: List[pd.DataFrame] = []
        from_id: Optional[int] = None
        for _ in range(max(1, pages)):
            params: Dict[str, Any] = {"symbol": symbol, "limit": min(limit, 1000)}
            if from_id is not None:
                start = max(0, from_id - min(limit, 1000))
                params["fromId"] = start
            raw = fetch(path, params, cache=False)
            if not raw:
                break
            df = pd.DataFrame(raw)
            frames.append(df)
            from_id = int(df["a"].min())
            if from_id <= 0:
                break

        if not frames:
            return pd.DataFrame(columns=["a", "p", "q", "T", "m", "time", "price",
                                         "qty", "notional", "side"])
        out = pd.concat(frames, ignore_index=True).drop_duplicates(subset="a")
        out["price"] = pd.to_numeric(out["p"], errors="coerce")
        out["qty"] = pd.to_numeric(out["q"], errors="coerce")
        out["time"] = pd.to_datetime(out["T"], unit="ms", utc=True)
        out["notional"] = out["price"] * out["qty"]
        # m=True -> alıcı maker, yani agresif taraf SATICI
        out["side"] = out["m"].map(lambda m: "sell" if m else "buy")
        return out.sort_values("time").reset_index(drop=True)


_client: Optional[BinanceClient] = None


def get_client(cfg: Optional[Config] = None) -> BinanceClient:
    global _client
    if _client is None:
        _client = BinanceClient(cfg)
    return _client
