// Binance halka açık market-data istemcisi — doğrudan tarayıcıdan.
// Tüm uçlar `Access-Control-Allow-Origin: *` gönderdiği için sunucuya gerek yok.
// API anahtarı kullanılmaz; sadece okuma yapılır.

import { pool } from './util.js';

const FUT = 'https://fapi.binance.com';
const SPOT = 'https://api.binance.com';

const cache = new Map();
const CACHE_TTL = 20_000;

let spotSymbols = null;
let exchangeInfoCache = null;

async function req(base, path, params = {}, { useCache = true, timeout = 20000 } = {}) {
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&');
  const url = base + path + (qs ? `?${qs}` : '');

  if (useCache) {
    const hit = cache.get(url);
    if (hit && Date.now() - hit.t < CACHE_TTL) return hit.v;
  }

  let lastErr;
  for (let attempt = 0; attempt < 3; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    try {
      const r = await fetch(url, { signal: ctrl.signal });
      clearTimeout(timer);
      if (r.status === 429 || r.status === 418) {
        await new Promise((res) => setTimeout(res, 2000 * (attempt + 1)));
        continue;
      }
      if (r.status === 451 || r.status === 403) {
        throw new Error('Binance bu bölgeden erişimi engelliyor (HTTP ' + r.status + ')');
      }
      if (!r.ok) throw new Error(`HTTP ${r.status} — ${path}`);
      const data = await r.json();
      if (useCache) cache.set(url, { t: Date.now(), v: data });
      return data;
    } catch (e) {
      clearTimeout(timer);
      lastErr = e;
      if (e.message && e.message.includes('engelliyor')) throw e;
      await new Promise((res) => setTimeout(res, 600 * (attempt + 1)));
    }
  }
  throw new Error(`İstek başarısız: ${path} — ${lastErr?.message || 'bilinmeyen hata'}`);
}

const fut = (p, params, opts) => req(FUT, p, params, opts);
const spot = (p, params, opts) => req(SPOT, p, params, opts);

// ------------------------------------------------------------------- mumlar
function toCandles(raw) {
  return raw.map((k) => ({
    t: k[0],
    o: +k[1], h: +k[2], l: +k[3], c: +k[4],
    v: +k[5], qv: +k[7], n: +k[8],
    tbb: +k[9], tbq: +k[10],
  }));
}

export async function klines(symbol, interval, limit = 500) {
  return toCandles(await fut('/fapi/v1/klines', { symbol, interval, limit }));
}

export async function spotKlines(symbol, interval, limit = 500) {
  return toCandles(await spot('/api/v3/klines', { symbol, interval, limit }));
}

// ------------------------------------------------------------- sembol bilgisi
export async function exchangeInfo() {
  if (!exchangeInfoCache) exchangeInfoCache = await fut('/fapi/v1/exchangeInfo');
  return exchangeInfoCache;
}

export async function perpetualSymbols(quote = 'USDT') {
  const info = await exchangeInfo();
  return info.symbols
    .filter((s) => s.contractType === 'PERPETUAL' && s.status === 'TRADING' && s.quoteAsset === quote)
    .map((s) => s.symbol)
    .sort();
}

export async function symbolMeta(symbol) {
  const info = await exchangeInfo();
  const s = info.symbols.find((x) => x.symbol === symbol);
  if (!s) return { tickSize: 0, pricePrecision: 6 };
  const pf = (s.filters || []).find((f) => f.filterType === 'PRICE_FILTER');
  return { tickSize: pf ? +pf.tickSize : 0, pricePrecision: s.pricePrecision ?? 6 };
}

// 1000SHIBUSDT (vadeli) → SHIBUSDT (spot), fiyat çarpanı 1000
export async function spotSymbolFor(futuresSymbol) {
  if (!spotSymbols) {
    try {
      const info = await spot('/api/v3/exchangeInfo', { permissions: 'SPOT' });
      spotSymbols = new Set(info.symbols.filter((s) => s.status === 'TRADING').map((s) => s.symbol));
    } catch {
      spotSymbols = new Set();
    }
  }
  if (spotSymbols.has(futuresSymbol)) return { symbol: futuresSymbol, multiplier: 1 };
  for (const prefix of ['1000000', '10000', '1000']) {
    if (futuresSymbol.startsWith(prefix)) {
      const cand = futuresSymbol.slice(prefix.length);
      if (spotSymbols.has(cand)) return { symbol: cand, multiplier: +prefix };
    }
  }
  return null;
}

// -------------------------------------------------------------- türev veriler
export const markPrice = (symbol) => fut('/fapi/v1/premiumIndex', { symbol });
export const openInterest = (symbol) => fut('/fapi/v1/openInterest', { symbol }, { useCache: false });
export const ticker24h = (symbol) => fut('/fapi/v1/ticker/24hr', { symbol });
export const allTickers24h = () => fut('/fapi/v1/ticker/24hr');
export const allPremiumIndex = () => fut('/fapi/v1/premiumIndex');

export async function fundingHistory(symbol, limit = 30) {
  const raw = await fut('/fapi/v1/fundingRate', { symbol, limit });
  return raw.map((r) => ({ time: r.fundingTime, rate: +r.fundingRate }));
}

export async function openInterestHist(symbol, period = '5m', limit = 200) {
  const raw = await fut('/futures/data/openInterestHist', { symbol, period, limit: Math.min(limit, 500) });
  return raw.map((r) => ({
    time: r.timestamp,
    oi: +r.sumOpenInterest,
    oiUsd: +r.sumOpenInterestValue,
  }));
}

async function ratioFrame(path, symbol, period, limit) {
  const raw = await fut(path, { symbol, period, limit: Math.min(limit, 500) });
  return raw.map((r) => ({
    time: r.timestamp,
    ratio: +r.longShortRatio,
    longPct: +r.longAccount,
    shortPct: +r.shortAccount,
  }));
}

export const topPositionsRatio = (s, p = '1h', l = 24) =>
  ratioFrame('/futures/data/topLongShortPositionRatio', s, p, l);
export const topAccountsRatio = (s, p = '1h', l = 24) =>
  ratioFrame('/futures/data/topLongShortAccountRatio', s, p, l);
export const globalAccountsRatio = (s, p = '1h', l = 24) =>
  ratioFrame('/futures/data/globalLongShortAccountRatio', s, p, l);

export async function takerRatio(symbol, period = '5m', limit = 24) {
  const raw = await fut('/futures/data/takerlongshortRatio', { symbol, period, limit });
  return raw.map((r) => ({ time: r.timestamp, buy: +r.buyVol, sell: +r.sellVol, ratio: +r.buySellRatio }));
}

// ---------------------------------------------------------------- order book
export async function depth(symbol, limit = 100) {
  const valid = [5, 10, 20, 50, 100, 500, 1000];
  const lim = valid.find((v) => v >= limit) || 1000;
  const d = await fut('/fapi/v1/depth', { symbol, limit: lim }, { useCache: false });
  return {
    bids: d.bids.map(([p, q]) => [+p, +q]),
    asks: d.asks.map(([p, q]) => [+p, +q]),
  };
}

// ------------------------------------------------------------------ işlemler
export async function aggTrades(symbol, { limit = 1000, pages = 1, isSpot = false } = {}) {
  const path = isSpot ? '/api/v3/aggTrades' : '/fapi/v1/aggTrades';
  const fn = isSpot ? spot : fut;
  const out = [];
  let fromId = null;

  for (let i = 0; i < Math.max(1, pages); i++) {
    const params = { symbol, limit: Math.min(limit, 1000) };
    if (fromId != null) {
      const start = Math.max(0, fromId - Math.min(limit, 1000));
      params.fromId = start;
    }
    const raw = await fn(path, params, { useCache: false });
    if (!raw || !raw.length) break;
    for (const t of raw) {
      out.push({
        id: t.a,
        price: +t.p,
        qty: +t.q,
        time: t.T,
        // m=true → alıcı maker, yani agresif taraf SATICI
        side: t.m ? 'sell' : 'buy',
        notional: +t.p * +t.q,
      });
    }
    fromId = Math.min(...raw.map((t) => t.a));
    if (fromId <= 0) break;
  }

  const seen = new Set();
  return out
    .filter((t) => (seen.has(t.id) ? false : (seen.add(t.id), true)))
    .sort((a, b) => a.time - b.time);
}

export async function spotPrice(symbol) {
  const d = await spot('/api/v3/ticker/price', { symbol });
  return +d.price;
}

export { pool };
