// Tarama hattı — Python sürümündeki pipeline.py ve engines/screener.py karşılığı.

import * as api from './binance.js';
import {
  derivativesEngine, interpretOi, orderBookEngine, orderFlowEngine,
  smartMoneyEngine, trendEngine, whaleEngine,
} from './engines.js';
import * as journal from './journal.js';
import { riskEngine, scoreEngine, tradeSetupEngine } from './scoring.js';
import * as store from './store.js';
import { clamp, percentile, pctChange, pool } from './util.js';

// ===========================================================================
// TEK PARİTE — TAM TARAMA (9 motor)
// ===========================================================================
export async function scanSymbol(symbol, cfg, { onProgress = () => {}, aggPages = null } = {}) {
  const t0 = performance.now();
  const tf = cfg.timeframes;
  const limit = tf.klinesLimit;
  const pages = aggPages ?? cfg.data.aggTradesPages;

  onProgress('Sembol bilgisi alınıyor...');
  const [meta, spotMap] = await Promise.all([
    api.symbolMeta(symbol),
    api.spotSymbolFor(symbol),
  ]);

  onProgress('Mum verileri çekiliyor (15m · 1h · 4h)...');
  const [ltf, mtf, htf] = await Promise.all([
    api.klines(symbol, tf.ltf, limit),
    api.klines(symbol, tf.mtf, limit),
    api.klines(symbol, tf.htf, limit),
  ]);
  const candles = { ltf, mtf, htf };

  onProgress('Türev verileri çekiliyor (OI · funding · L/S · taker)...');
  const d = cfg.derivatives;
  const [oiNow, oiHist, prem, fundHist, topAcc, topPos, glob, taker] = await Promise.all([
    api.openInterest(symbol),
    api.openInterestHist(symbol, '5m', 500),
    api.markPrice(symbol),
    api.fundingHistory(symbol, d.fundingHistoryLimit),
    api.topAccountsRatio(symbol, d.lsRatioPeriod, d.lsRatioLimit),
    api.topPositionsRatio(symbol, d.lsRatioPeriod, d.lsRatioLimit),
    api.globalAccountsRatio(symbol, d.lsRatioPeriod, d.lsRatioLimit),
    api.takerRatio(symbol, d.takerRatioPeriod, d.takerRatioLimit),
  ]);

  let spotPx = null;
  if (spotMap) {
    try { spotPx = (await api.spotPrice(spotMap.symbol)) * spotMap.multiplier; } catch { /* yoksay */ }
  }

  onProgress('İşlem akışı çekiliyor (vadeli + spot)...');
  const futTrades = await api.aggTrades(symbol, { limit: cfg.data.aggTradesLimit, pages });
  let spotTrades = [];
  if (spotMap) {
    try {
      spotTrades = await api.aggTrades(spotMap.symbol, {
        limit: cfg.data.aggTradesLimit,
        pages: Math.min(pages, cfg.data.spotAggTradesPages),
        isSpot: true,
      });
    } catch { /* spot yoksa devam */ }
  }

  onProgress('Order book okunuyor (100 seviye)...');
  const book = await api.depth(symbol, cfg.data.depthLimit);

  onProgress('Motorlar çalışıyor...');
  const engines = {};
  engines.trend = trendEngine(candles, cfg);
  engines.smartMoney = smartMoneyEngine(candles, cfg);
  engines.derivatives = derivativesEngine(
    { oiNow, oiHist, prem, fundHist, topAcc, topPos, glob, taker, spotPx }, cfg);
  engines.orderFlow = orderFlowEngine(futTrades, spotTrades, spotMap);
  engines.whale = whaleEngine(futTrades, spotTrades, cfg);

  const prevDepth = store.previousDepth(symbol);
  engines.orderbook = orderBookEngine(book, cfg, futTrades, prevDepth);
  const mid = engines.orderbook.midPrice;
  if (mid) store.saveDepth(symbol, mid, book.bids, book.asks);

  const score = scoreEngine(engines, cfg);
  const risk = riskEngine(engines, cfg);
  const setup = tradeSetupEngine(symbol, engines, score, risk, cfg, meta);

  const price = engines.trend.price ?? engines.orderbook.midPrice;
  const snapshot = {
    symbol, timestamp: new Date().toISOString(), price, spotSymbol: spotMap,
    trend: engines.trend, smartMoney: engines.smartMoney, derivatives: engines.derivatives,
    orderFlow: engines.orderFlow, whale: engines.whale, orderbook: engines.orderbook,
    score, risk, setup,
    elapsedSeconds: (performance.now() - t0) / 1000,
  };

  // Ham mum verisini grafik için ayrı tutuyoruz (localStorage'a yazılmaz)
  snapshot._candles = candles;

  // Saklanacak kopya: ağır alanlar çıkarılır. Sığ kopyada iç nesneler paylaşıldığı
  // için orderbook/derivatives ayrıca kopyalanmalı — aksi hâlde canlı snapshot'tan
  // da silinir ve grafikler boş kalır.
  const persist = { ...snapshot };
  delete persist._candles;
  persist.orderbook = { ...snapshot.orderbook };
  delete persist.orderbook.depthChart;
  persist.derivatives = {
    ...snapshot.derivatives,
    openInterest: { ...snapshot.derivatives.openInterest, series: snapshot.derivatives.openInterest.series.slice(-96) },
  };
  persist.trend = {
    ...snapshot.trend,
    timeframes: Object.fromEntries(Object.entries(snapshot.trend.timeframes).map(([k, v]) => {
      const c = { ...v }; delete c._enriched; return [k, c];
    })),
  };
  store.saveSnapshot(symbol, persist);
  store.addScan(symbol, {
    ts: snapshot.timestamp, price, longScore: score.longScore,
    shortScore: score.shortScore, decision: score.decision,
  });

  // Setup üretildiyse sinyal günlüğüne düşsün — sonucu sonradan otomatik ölçülecek
  try {
    journal.kaydet(snapshot);
  } catch (e) {
    console.warn('Sinyal günlüğe yazılamadı:', e);
  }

  return snapshot;
}

// ===========================================================================
// TÜM PİYASA — ÖN ELEME
// ===========================================================================
async function oiSnapshot(symbol) {
  try {
    const hist = await api.openInterestHist(symbol, '5m', 49);
    if (!hist || hist.length < 13) return { symbol };
    const priceAt = (i) => (hist[i].oi ? hist[i].oiUsd / hist[i].oi : 0);
    const n = hist.length;
    const out = {
      symbol,
      oi: hist[n - 1].oi,
      oiUsd: hist[n - 1].oiUsd,
      oiChange1h: pctChange(hist[n - 1].oi, hist[n - 13].oi),
      priceChange1h: pctChange(priceAt(n - 1), priceAt(n - 13)),
    };
    if (n >= 49) {
      out.oiChange4h = pctChange(hist[n - 1].oi, hist[n - 49].oi);
      out.priceChange4h = pctChange(priceAt(n - 1), priceAt(n - 49));
    }
    return out;
  } catch {
    return { symbol };
  }
}

function interestScore(row, volRank, m) {
  let score = 0;
  score += Math.min(Math.abs(row.priceChangePercent || 0) / 12, 1) * 25;
  score += Math.min(Math.abs(row.oiChange1h || 0) / 6, 1) * 30;
  score += Math.min(Math.abs(row.fundingPct || 0) / m.extremeFundingPct, 1) * 20;
  score += volRank * 15;
  if (['YENİ LONG', 'YENİ SHORT'].includes(row.oiState)) score += 10;
  else if (['SHORT KAPANIŞI', 'LONG KAPANIŞI'].includes(row.oiState)) score += 4;
  return Math.min(score, 100);
}

function quickBias(row) {
  const parts = [];
  if (row.oiScore != null) parts.push(row.oiScore);
  const f = row.fundingPct;
  if (f != null) {
    if (Math.abs(f) >= 0.05) parts.push(f > 0 ? -0.8 : 0.8);
    else if (Math.abs(f) >= 0.02) parts.push(f > 0 ? -0.35 : 0.35);
  }
  if (row.priceChangePercent != null) parts.push(clamp(row.priceChangePercent / 15) * 0.5);
  if (!parts.length) return { bias: 0, label: 'NÖTR' };
  const bias = clamp(parts.reduce((a, b) => a + b, 0) / parts.length);
  return { bias, label: bias > 0.3 ? 'LONG EĞİLİM' : bias < -0.3 ? 'SHORT EĞİLİM' : 'NÖTR' };
}

export async function screenMarket(cfg, { onProgress = () => {} } = {}) {
  const m = cfg.market;
  onProgress('Parite listesi alınıyor...');
  const symbols = new Set(await api.perpetualSymbols(m.quoteAsset));

  onProgress(`${symbols.size} parite bulundu · toplu fiyat ve funding verisi çekiliyor...`);
  const [tickers, premium] = await Promise.all([api.allTickers24h(), api.allPremiumIndex()]);

  const premMap = new Map(premium.map((p) => [p.symbol, p]));
  let rows = tickers
    .filter((t) => symbols.has(t.symbol))
    .map((t) => {
      const p = premMap.get(t.symbol);
      return {
        symbol: t.symbol,
        lastPrice: +t.lastPrice,
        priceChangePercent: +t.priceChangePercent,
        quoteVolume: +t.quoteVolume,
        fundingPct: p ? +p.lastFundingRate * 100 : null,
        markPrice: p ? +p.markPrice : null,
      };
    });

  const minVol = m.minQuoteVolumeUsdt;
  let liquid = minVol > 0 ? rows.filter((r) => r.quoteVolume >= minVol) : rows;
  if (!liquid.length) liquid = rows.slice().sort((a, b) => b.quoteVolume - a.quoteVolume).slice(0, 100);
  liquid.sort((a, b) => b.quoteVolume - a.quoteVolume);

  const targets = liquid.slice(0, m.oiEnrichTop);
  onProgress(`${targets.length} parite için Open Interest verisi çekiliyor...`);
  const oiRows = await pool(
    targets.map((r) => r.symbol),
    (s) => oiSnapshot(s),
    m.oiConcurrency,
    (done, total) => onProgress(`Open Interest: ${done}/${total} parite`)
  );
  const oiMap = new Map(oiRows.filter(Boolean).map((r) => [r.symbol, r]));

  for (const r of liquid) {
    const oi = oiMap.get(r.symbol);
    Object.assign(r, oi || {});
    // OI verisi olmayan pariteler dikkat skorunun 40 puanını (30 OI değişimi +
    // 10 durum bonusu) hiç alamaz. Bunları işaretliyoruz ki sıralamada
    // sessizce dezavantajlı duruma düşmesinler.
    r.oiVerisiYok = !oi || oi.oiChange1h == null;
    const interp = interpretOi(r.oiChange1h, r.priceChange1h);
    r.oiState = r.oiVerisiYok ? null : interp.state;
    r.oiScore = r.oiVerisiYok ? null : interp.score;
    r.oiMeaning = interp.meaning;
  }

  const vols = liquid.map((r) => r.quoteVolume).sort((a, b) => a - b);
  const rankOf = (v) => {
    let lo = 0, hi = vols.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (vols[mid] < v) lo = mid + 1; else hi = mid; }
    return vols.length ? lo / vols.length : 0;
  };

  for (const r of liquid) {
    r.interest = interestScore(r, rankOf(r.quoteVolume), m);
    const b = quickBias(r);
    r.bias = b.bias;
    r.biasLabel = b.label;
  }

  // OI verisi olanlar önce sıralanır; olmayanlar (güvenlik tavanı devreye
  // girdiyse) eksik skorla üste çıkamayacakları için sona alınır.
  liquid.sort((a, b) => {
    if (a.oiVerisiYok !== b.oiVerisiYok) return a.oiVerisiYok ? 1 : -1;
    return b.interest - a.interest;
  });
  liquid.oiCekilen = targets.length;
  store.saveScreening(liquid);
  return liquid;
}

export function pickCandidates(screened, cfg, topN = null) {
  const m = cfg.market;
  const n = topN ?? m.deepScanTop;
  const picks = screened.slice(0, n).map((r) => r.symbol);
  if (m.alwaysIncludeWatchlist) {
    const avail = new Set(screened.map((r) => r.symbol));
    for (const s of cfg.symbols) if (!picks.includes(s) && avail.has(s)) picks.push(s);
  }
  return picks;
}

export async function scanMarket(cfg, { deep = true, topN = null, onProgress = () => {} } = {}) {
  const screened = await screenMarket(cfg, { onProgress });
  if (!deep) return { screened, snapshots: [], candidates: [] };

  const candidates = pickCandidates(screened, cfg, topN);
  const snapshots = [];
  for (let i = 0; i < candidates.length; i++) {
    const sym = candidates[i];
    onProgress(`Derin tarama ${i + 1}/${candidates.length}: ${sym}`);
    try {
      snapshots.push(await scanSymbol(sym, cfg, {
        onProgress: (msg) => onProgress(`${sym} (${i + 1}/${candidates.length}) — ${msg}`),
        aggPages: cfg.market.deepScanAggPages,
      }));
    } catch (e) {
      console.warn(`${sym} taranamadı:`, e);
    }
  }
  snapshots.sort((a, b) => b.score.longScore - a.score.longScore);
  return { screened, snapshots, candidates };
}
