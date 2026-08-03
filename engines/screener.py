"""Market Screener — Binance vadelideki TÜM pariteleri tarar.

İki aşamalı çalışır çünkü 530 paritenin her birini 9 motorla taramak
onbinlerce istek demek olurdu (Binance dakikada 2400 ağırlık veriyor):

  1. ÖN ELEME (ucuz, tüm piyasa)
     - /fapi/v1/ticker/24hr    → tek istekte tüm fiyat/hacim (ağırlık 40)
     - /fapi/v1/premiumIndex   → tek istekte tüm funding (ağırlık 10)
     - openInterestHist        → sembol başına 1 istek (ağırlık 1), OI + fiyat
                                 değişimini birlikte verir
     Buradan her parite için "dikkat skoru" ve ön eğilim çıkarılır.

  2. DERİN TARAMA (pahalı, sadece seçilenler)
     Ön elemede öne çıkan N parite tam 9 motorlu hattan geçirilir.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.binance import BinanceClient
from core.config import Config
from core.indicators import clamp, pct_change
from core.logging_setup import log
from engines.derivatives import interpret_oi


# --------------------------------------------------------------- OI zenginleştirme
def _oi_snapshot(client: BinanceClient, symbol: str) -> Dict[str, Any]:
    """Tek istekle OI ve fiyatın 1s/4s değişimi.

    openInterestHist hem miktarı hem USDT değerini verdiği için
    (değer / miktar) oranından o andaki ortalama fiyatı da türetebiliyoruz.
    """
    try:
        df = client.open_interest_hist(symbol, "5m", 49)   # 49 x 5dk ≈ 4 saat
    except Exception as exc:  # noqa: BLE001
        log.debug(f"{symbol} OI geçmişi alınamadı: {exc}")
        return {"symbol": symbol}

    if df.empty or len(df) < 13:
        return {"symbol": symbol}

    def price_at(i: int) -> float:
        qty = float(df["sumOpenInterest"].iloc[i])
        val = float(df["sumOpenInterestValue"].iloc[i])
        return val / qty if qty else 0.0

    oi_now = float(df["sumOpenInterest"].iloc[-1])
    oi_usdt = float(df["sumOpenInterestValue"].iloc[-1])
    out: Dict[str, Any] = {
        "symbol": symbol,
        "oi": oi_now,
        "oi_usdt": oi_usdt,
        "oi_change_1h": round(pct_change(oi_now, float(df["sumOpenInterest"].iloc[-13])), 3),
        "price_change_1h": round(pct_change(price_at(-1), price_at(-13)), 3),
    }
    if len(df) >= 49:
        out["oi_change_4h"] = round(pct_change(oi_now, float(df["sumOpenInterest"].iloc[-49])), 3)
        out["price_change_4h"] = round(pct_change(price_at(-1), price_at(-49)), 3)
    return out


def enrich_with_oi(client: BinanceClient, symbols: List[str],
                   workers: int = 4) -> pd.DataFrame:
    """Verilen semboller için OI anlık görüntülerini paralel toplar."""
    rows: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_oi_snapshot, client, s): s for s in symbols}
        for fut in as_completed(futures):
            try:
                rows.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                log.debug(f"{futures[fut]} OI hatası: {exc}")
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["symbol"])


# ----------------------------------------------------------------- skorlama
def _interest_score(row: pd.Series, vol_rank: float, cfg_m: Dict[str, Any]) -> float:
    """0-100 'dikkat skoru': bu parite şu an bakmaya değer mi?

    Yön değil, HAREKETLİLİK ölçer. Yön ayrıca bias olarak hesaplanır.
    """
    score = 0.0

    # 1) Fiyat hareketi (24s)
    chg = abs(row.get("priceChangePercent") or 0)
    score += min(chg / 12.0, 1.0) * 25

    # 2) OI değişimi (1s) — pozisyonlanmada hareket
    oi_chg = abs(row.get("oi_change_1h") or 0)
    score += min(oi_chg / 6.0, 1.0) * 30

    # 3) Funding aşırılığı
    fnd = abs(row.get("funding_pct") or 0)
    score += min(fnd / cfg_m.get("extreme_funding_pct", 0.05), 1.0) * 20

    # 4) Likidite (hacim sıralaması) — likit olmayan pariteler cezalı
    score += vol_rank * 15

    # 5) OI/fiyat uyumsuzluğu (yeni pozisyon girişi güçlü sinyaldir)
    interp = row.get("oi_state")
    if interp in ("YENİ LONG", "YENİ SHORT"):
        score += 10
    elif interp in ("SHORT KAPANIŞI", "LONG KAPANIŞI"):
        score += 4

    return round(min(score, 100.0), 1)


def _quick_bias(row: pd.Series) -> Dict[str, Any]:
    """Ucuz veriden ön eğilim (-1..+1). Derin taramanın yerini tutmaz."""
    parts: List[float] = []

    oi_score = row.get("oi_score")
    if oi_score is not None and not pd.isna(oi_score):
        parts.append(float(oi_score) * 1.0)

    # Aşırı funding kontra sinyaldir
    fnd = row.get("funding_pct")
    if fnd is not None and not pd.isna(fnd):
        if abs(fnd) >= 0.05:
            parts.append(-0.8 if fnd > 0 else 0.8)
        elif abs(fnd) >= 0.02:
            parts.append(-0.35 if fnd > 0 else 0.35)

    # 24s momentum (zayıf ağırlık)
    chg = row.get("priceChangePercent")
    if chg is not None and not pd.isna(chg):
        parts.append(clamp(float(chg) / 15.0) * 0.5)

    if not parts:
        return {"bias": 0.0, "label": "NÖTR"}

    bias = clamp(sum(parts) / len(parts))
    if bias > 0.3:
        label = "LONG EĞİLİM"
    elif bias < -0.3:
        label = "SHORT EĞİLİM"
    else:
        label = "NÖTR"
    return {"bias": round(bias, 3), "label": label}


# --------------------------------------------------------------------- run
def screen_market(client: BinanceClient, cfg: Config,
                  progress=None) -> pd.DataFrame:
    """Tüm Binance vadeli piyasasını ön eler ve dikkat skoruna göre sıralar."""
    cfg_m = cfg.get("market", {}) or {}
    quote = cfg_m.get("quote_asset", "USDT")

    symbols = client.perpetual_symbols(quote)
    log.info(f"Binance vadelide {len(symbols)} adet {quote} sürekli parite bulundu")
    if progress:
        progress(f"{len(symbols)} parite bulundu, toplu veri çekiliyor...")

    # ---------------------------------------------------- 1) toplu ucuz veri
    tickers = client.all_tickers_24h()
    premium = client.all_premium_index()
    if tickers.empty:
        return pd.DataFrame()

    df = tickers[tickers["symbol"].isin(symbols)].copy()
    if not premium.empty:
        prem = premium[["symbol", "lastFundingRate", "markPrice", "indexPrice"]].copy()
        prem["funding_pct"] = prem["lastFundingRate"] * 100
        df = df.merge(prem[["symbol", "funding_pct", "markPrice", "indexPrice"]],
                      on="symbol", how="left")

    # ------------------------------------------------------ 2) likidite filtresi
    min_vol = cfg_m.get("min_quote_volume_usdt", 3_000_000)
    if min_vol > 0:
        liquid = df[df["quoteVolume"] >= min_vol].copy()
        if liquid.empty:
            log.warning(f"Hacim filtresini ({min_vol:,.0f} USDT) geçen parite yok, "
                        f"filtre gevşetiliyor")
            liquid = df.nlargest(100, "quoteVolume").copy()
    else:
        liquid = df.copy()          # eleme yok — tüm piyasa
    liquid = liquid.sort_values("quoteVolume", ascending=False)

    excluded = set(cfg_m.get("exclude", []) or [])
    if excluded:
        liquid = liquid[~liquid["symbol"].isin(excluded)]

    # -------------------------------------------------- 3) OI zenginleştirme
    oi_limit = cfg_m.get("oi_enrich_top", 150)
    targets = liquid.head(oi_limit)["symbol"].tolist()
    log.info(f"Hacim filtresini geçen: {len(liquid)} · OI verisi çekilecek: {len(targets)}")
    if progress:
        progress(f"{len(targets)} parite için Open Interest verisi çekiliyor...")

    oi_df = enrich_with_oi(client, targets, cfg_m.get("oi_workers", 4))
    liquid = liquid.merge(oi_df, on="symbol", how="left")

    # ------------------------------------------------------- 4) yorum + skor
    states, scores_oi = [], []
    for _, r in liquid.iterrows():
        interp = interpret_oi(r.get("oi_change_1h"), r.get("price_change_1h"))
        states.append(interp["state"])
        scores_oi.append(interp["score"])
    liquid["oi_state"] = states
    liquid["oi_score"] = scores_oi

    vol_ranks = liquid["quoteVolume"].rank(pct=True)
    liquid["interest"] = [
        _interest_score(r, vol_ranks.iloc[i], cfg_m)
        for i, (_, r) in enumerate(liquid.iterrows())
    ]

    bias = [_quick_bias(r) for _, r in liquid.iterrows()]
    liquid["bias"] = [b["bias"] for b in bias]
    liquid["bias_label"] = [b["label"] for b in bias]

    cols = ["symbol", "lastPrice", "priceChangePercent", "quoteVolume", "funding_pct",
            "oi", "oi_usdt", "oi_change_1h", "oi_change_4h", "price_change_1h",
            "oi_state", "interest", "bias", "bias_label"]
    cols = [c for c in cols if c in liquid.columns]
    out = liquid[cols].sort_values("interest", ascending=False).reset_index(drop=True)
    out.index = out.index + 1
    return out


def pick_candidates(screened: pd.DataFrame, cfg: Config,
                    top_n: Optional[int] = None) -> List[str]:
    """Derin taramaya girecek pariteleri seçer.

    Dikkat skoru en yüksekler + izleme listesindeki pariteler (varsa) birleştirilir.
    """
    cfg_m = cfg.get("market", {}) or {}
    n = top_n or cfg_m.get("deep_scan_top", 20)

    picks = screened.head(n)["symbol"].tolist()
    if cfg_m.get("always_include_watchlist", True):
        for s in cfg.symbols:
            if s not in picks and s in set(screened["symbol"]):
                picks.append(s)
    return picks
