// Analiz motorları — Python sürümündeki engines/ klasörünün karşılığı.
// Trend · Smart Money · Derivatives · Order Flow · Whale · Order Book

import { atr as atrOf, enrich, marketStructure, swingPoints } from './indicators.js';
import { clamp, mean, pctChange, percentile, sum } from './util.js';

// ===========================================================================
// 1) TREND ENGINE
// ===========================================================================
function emaAlignment(last, periods) {
  const vals = periods.map((p) => last.ema[p]).filter((v) => isFinite(v));
  if (vals.length < 2) return { state: 'UNKNOWN', score: 0 };
  let asc = true, desc = true;
  for (let i = 0; i < vals.length - 1; i++) {
    if (!(vals[i] > vals[i + 1])) asc = false;
    if (!(vals[i] < vals[i + 1])) desc = false;
  }
  const above = vals.filter((v) => last.price > v).length;
  const ratio = above / vals.length;
  if (asc && ratio === 1) return { state: 'PERFECT_BULLISH', score: 1 };
  if (desc && ratio === 0) return { state: 'PERFECT_BEARISH', score: -1 };
  return { state: 'MIXED', score: clamp((ratio - 0.5) * 2) };
}

export function analyzeTimeframe(candles, cfg) {
  if (!candles || candles.length < 30) return { available: false };
  const e = enrich(candles, cfg);
  const i = candles.length - 1;
  const price = candles[i].c;
  const periods = cfg.emaPeriods;

  const last = { price, ema: Object.fromEntries(periods.map((p) => [p, e.ema[p][i]])) };
  const align = emaAlignment(last, periods);

  const atrVal = e.atr[i];
  const atrPct = price ? (atrVal / price) * 100 : 0;
  const adxVal = e.adx[i];
  const diBias = e.plusDi[i] > e.minusDi[i] ? 1 : -1;
  const adxStrength = clamp((adxVal - 20) / 25, 0, 1);
  const stDir = e.stDir[i];
  const stFlip = stDir !== e.stDir[i - 1];
  const vwapD = e.vwapD[i], vwapW = e.vwapW[i];
  const structure = marketStructure(candles, cfg.swingLookback);

  let sVwap = 0;
  if (vwapD) sVwap += clamp(pctChange(price, vwapD) / 1.5) * 0.10;
  if (vwapW) sVwap += clamp(pctChange(price, vwapW) / 3.0) * 0.05;
  const sStruct = { BULLISH: 0.10, BEARISH: -0.10 }[structure.state] || 0;
  const score = clamp(align.score * 0.35 + diBias * adxStrength * 0.20 + stDir * 0.20 + sVwap + sStruct);

  return {
    available: true,
    price,
    label: score > 0.35 ? 'BULLISH' : score < -0.35 ? 'BEARISH' : 'NEUTRAL',
    score,
    ema: last.ema,
    emaAlignment: align.state,
    priceVsEma: Object.fromEntries(periods.map((p) => [p, pctChange(price, e.ema[p][i])])),
    vwap: {
      daily: vwapD, weekly: vwapW,
      vsDaily: vwapD ? pctChange(price, vwapD) : null,
      vsWeekly: vwapW ? pctChange(price, vwapW) : null,
    },
    atr: { value: atrVal, pct: atrPct },
    adx: {
      value: adxVal, plusDi: e.plusDi[i], minusDi: e.minusDi[i],
      strength: adxVal >= 40 ? 'STRONG' : adxVal >= 25 ? 'TRENDING' : adxVal >= 20 ? 'WEAK' : 'RANGE',
    },
    supertrend: { value: e.supertrend[i], direction: stDir === 1 ? 'UP' : 'DOWN', flipped: stFlip },
    rsi: e.rsi[i],
    macd: {
      macd: e.macd[i], signal: e.macdSignal[i], hist: e.macdHist[i],
      cross: e.macd[i] > e.macdSignal[i] ? 'BULLISH' : 'BEARISH',
      histRising: e.macdHist[i] > e.macdHist[i - 1],
    },
    structure: {
      state: structure.state,
      recentLabels: structure.recentLabels,
      lastSwingHigh: structure.lastSwingHigh,
      lastSwingLow: structure.lastSwingLow,
      points: structure.points.slice(-10),
    },
    volume: { last: candles[i].v, ma20: e.volMa20[i], ratio: e.volMa20[i] ? candles[i].v / e.volMa20[i] : 0 },
    _enriched: e,
  };
}

export function trendEngine(candlesByTf, cfg) {
  const timeframes = {};
  for (const [k, c] of Object.entries(candlesByTf)) timeframes[k] = analyzeTimeframe(c, cfg.trend);

  const weights = { mtf: 0.5, htf: 0.3, ltf: 0.2 };
  let acc = 0, tw = 0;
  for (const [k, w] of Object.entries(weights)) {
    if (timeframes[k]?.available) { acc += timeframes[k].score * w; tw += w; }
  }
  const score = tw ? clamp(acc / tw) : 0;
  const mtf = timeframes.mtf || {};
  const aligned = ['ltf', 'htf']
    .filter((k) => timeframes[k]?.available)
    .every((k) => timeframes[k].label === mtf.label);

  const parts = [];
  if (mtf.available) {
    parts.push(`1H ${mtf.label} (ADX ${mtf.adx.value.toFixed(0)}, ${mtf.adx.strength})`);
    parts.push(`SuperTrend ${mtf.supertrend.direction}`);
    parts.push(`Yapı ${mtf.structure.state}`);
    if (timeframes.htf?.available) parts.push(`4H ${timeframes.htf.label}`);
    if (mtf.vwap.vsDaily != null) {
      parts.push(`Günlük VWAP'ın %${mtf.vwap.vsDaily.toFixed(2)} ${mtf.vwap.vsDaily > 0 ? 'üstünde' : 'altında'}`);
    }
  }

  return {
    timeframes, score,
    label: score > 0.35 ? 'BULLISH' : score < -0.35 ? 'BEARISH' : 'NEUTRAL',
    mtfAligned: aligned,
    price: mtf.price ?? timeframes.ltf?.price,
    atrPct: mtf.atr?.pct,
    adx: mtf.adx?.value,
    rsi: mtf.rsi,
    structureState: mtf.structure?.state,
    summary: parts.join(' · ') || 'Yetersiz veri',
  };
}

export function rsiScore(trend) {
  const mtf = trend.timeframes?.mtf;
  if (!mtf?.available) return { score: 0, value: null, state: 'NA' };
  const r = mtf.rsi;
  let score, state;
  if (r >= 70) { score = 0.35; state = 'AŞIRI ALIM'; }
  else if (r >= 60) { score = 0.8; state = 'GÜÇLÜ'; }
  else if (r >= 50) { score = clamp((r - 50) / 12.5); state = 'POZİTİF'; }
  else if (r >= 40) { score = clamp((r - 50) / 12.5); state = 'NEGATİF'; }
  else if (r >= 30) { score = -0.8; state = 'ZAYIF'; }
  else { score = -0.35; state = 'AŞIRI SATIM'; }
  return { score, value: r, state };
}

export function macdScore(trend) {
  const mtf = trend.timeframes?.mtf;
  if (!mtf?.available) return { score: 0, state: 'NA' };
  const m = mtf.macd;
  const base = m.cross === 'BULLISH' ? 0.6 : -0.6;
  const momentum = m.histRising ? 0.4 : -0.4;
  return {
    score: clamp(base + momentum),
    state: `${m.cross}/${m.histRising ? 'ARTAN' : 'AZALAN'}`,
    hist: m.hist, cross: m.cross,
  };
}

// ===========================================================================
// 2) SMART MONEY ENGINE
// ===========================================================================
function findLiquiditySweeps(candles, cfg, sm) {
  const out = [];
  if (candles.length < 30) return out;
  const { isHigh, isLow } = swingPoints(candles, 3);
  const volMa = [];
  for (let i = 0; i < candles.length; i++) {
    const from = Math.max(0, i - 19);
    volMa[i] = mean(candles.slice(from, i + 1).map((c) => c.v));
  }
  const start = Math.max(20, candles.length - sm.sweepLookback);

  for (let i = start; i < candles.length; i++) {
    const c = candles[i];
    const range = c.h - c.l;
    if (range <= 0) continue;
    const bodyLow = Math.min(c.o, c.c), bodyHigh = Math.max(c.o, c.c);
    const lowerWick = bodyLow - c.l, upperWick = c.h - bodyHigh;
    const vma = volMa[i] || c.v;
    const volOk = c.v >= vma * sm.sweepVolumeMult;
    const from = Math.max(0, i - sm.sweepLookback);

    if (lowerWick / range >= sm.sweepWickRatio) {
      const priorLows = [];
      for (let j = from; j < i - 2; j++) if (isLow[j]) priorLows.push(candles[j].l);
      const above = priorLows.filter((lv) => lv > c.l);
      if (above.length) {
        const target = Math.max(...above);
        if (c.c > target) {
          out.push({
            type: 'BUY_LIQUIDITY_SWEPT', direction: 'bullish', index: i, time: c.t,
            sweptLevel: target, wick: c.l, close: c.c,
            wickRatio: lowerWick / range, volumeRatio: vma ? c.v / vma : null,
            volumeConfirmed: volOk, barsAgo: candles.length - 1 - i,
          });
        }
      }
    }

    if (upperWick / range >= sm.sweepWickRatio) {
      const priorHighs = [];
      for (let j = from; j < i - 2; j++) if (isHigh[j]) priorHighs.push(candles[j].h);
      const below = priorHighs.filter((lv) => lv < c.h);
      if (below.length) {
        const target = Math.min(...below);
        if (c.c < target) {
          out.push({
            type: 'SELL_LIQUIDITY_SWEPT', direction: 'bearish', index: i, time: c.t,
            sweptLevel: target, wick: c.h, close: c.c,
            wickRatio: upperWick / range, volumeRatio: vma ? c.v / vma : null,
            volumeConfirmed: volOk, barsAgo: candles.length - 1 - i,
          });
        }
      }
    }
  }
  return out;
}

function findFvgs(candles, sm, atrArr) {
  const out = [];
  const n = candles.length;
  if (n < 5) return out;
  const lastClose = candles[n - 1].c;

  for (let i = 2; i < n; i++) {
    if (n - 1 - i > sm.fvgMaxAge) continue;
    const a = atrArr[i];
    if (!a || a <= 0) continue;

    if (candles[i].l > candles[i - 2].h) {
      const size = candles[i].l - candles[i - 2].h;
      if (size >= a * sm.fvgMinSizeAtr) {
        const bottom = candles[i - 2].h, top = candles[i].l;
        let minLow = Infinity;
        for (let j = i; j < n; j++) minLow = Math.min(minLow, candles[j].l);
        out.push({
          type: 'BULLISH_FVG', direction: 'bullish', index: i, time: candles[i].t,
          bottom, top, mid: (bottom + top) / 2,
          sizePct: (size / lastClose) * 100, sizeAtr: size / a,
          filled: minLow <= bottom, mitigated: minLow <= top,
          barsAgo: n - 1 - i, distancePct: ((bottom - lastClose) / lastClose) * 100,
        });
      }
    }

    if (candles[i].h < candles[i - 2].l) {
      const size = candles[i - 2].l - candles[i].h;
      if (size >= a * sm.fvgMinSizeAtr) {
        const bottom = candles[i].h, top = candles[i - 2].l;
        let maxHigh = -Infinity;
        for (let j = i; j < n; j++) maxHigh = Math.max(maxHigh, candles[j].h);
        out.push({
          type: 'BEARISH_FVG', direction: 'bearish', index: i, time: candles[i].t,
          bottom, top, mid: (bottom + top) / 2,
          sizePct: (size / lastClose) * 100, sizeAtr: size / a,
          filled: maxHigh >= top, mitigated: maxHigh >= bottom,
          barsAgo: n - 1 - i, distancePct: ((top - lastClose) / lastClose) * 100,
        });
      }
    }
  }
  return out;
}

function findOrderBlocks(candles, sm, atrArr) {
  const out = [];
  const n = candles.length;
  if (n < 10) return out;
  const lastClose = candles[n - 1].c;

  for (let i = 1; i < n - 1; i++) {
    if (n - 1 - i > sm.fvgMaxAge) continue;
    const a = atrArr[i];
    if (!a || a <= 0) continue;
    const move = candles[i + 1].c - candles[i + 1].o;

    if (candles[i].c < candles[i].o && move > a * sm.obDisplacementAtr) {
      const bottom = candles[i].l, top = candles[i].h;
      let minLow = Infinity;
      for (let j = i + 2; j < n; j++) minLow = Math.min(minLow, candles[j].l);
      out.push({
        type: 'BULLISH_OB', direction: 'bullish', index: i, time: candles[i].t,
        bottom, top, mid: (bottom + top) / 2, displacementAtr: move / a,
        mitigated: isFinite(minLow) && minLow <= top,
        barsAgo: n - 1 - i, distancePct: ((top - lastClose) / lastClose) * 100,
      });
    }

    if (candles[i].c > candles[i].o && move < -a * sm.obDisplacementAtr) {
      const bottom = candles[i].l, top = candles[i].h;
      let maxHigh = -Infinity;
      for (let j = i + 2; j < n; j++) maxHigh = Math.max(maxHigh, candles[j].h);
      out.push({
        type: 'BEARISH_OB', direction: 'bearish', index: i, time: candles[i].t,
        bottom, top, mid: (bottom + top) / 2, displacementAtr: Math.abs(move) / a,
        mitigated: isFinite(maxHigh) && maxHigh >= bottom,
        barsAgo: n - 1 - i, distancePct: ((bottom - lastClose) / lastClose) * 100,
      });
    }
  }
  return out;
}

function findStructureBreaks(candles, lookbackBars = 120) {
  const out = [];
  const n = candles.length;
  if (n < 30) return out;
  const { isHigh, isLow } = swingPoints(candles, 3);
  let lastSh = null, lastSl = null, trend = null;
  const start = Math.max(10, n - lookbackBars);

  for (let i = 10; i < n; i++) {
    if (isHigh[i]) lastSh = candles[i].h;
    if (isLow[i]) lastSl = candles[i].l;

    if (lastSh != null && candles[i].c > lastSh) {
      const kind = trend === 'down' ? 'CHOCH' : 'BOS';
      if (i >= start) out.push({ type: kind, direction: 'bullish', index: i, time: candles[i].t, brokenLevel: lastSh, close: candles[i].c, barsAgo: n - 1 - i });
      trend = 'up'; lastSh = null;
    }
    if (lastSl != null && candles[i].c < lastSl) {
      const kind = trend === 'up' ? 'CHOCH' : 'BOS';
      if (i >= start) out.push({ type: kind, direction: 'bearish', index: i, time: candles[i].t, brokenLevel: lastSl, close: candles[i].c, barsAgo: n - 1 - i });
      trend = 'down'; lastSl = null;
    }
  }
  return out;
}

export function smartMoneyEngine(candlesByTf, cfg) {
  const sm = cfg.smartMoney;
  const candles = candlesByTf.mtf;
  if (!candles || candles.length < 30) return { available: false, score: 0 };

  const atrArr = atrOf(candles, cfg.trend.atrPeriod);
  const sweeps = findLiquiditySweeps(candles, cfg, sm);
  const fvgs = findFvgs(candles, sm, atrArr);
  const obs = findOrderBlocks(candles, sm, atrArr);
  const breaks = findStructureBreaks(candles);
  const ltfBreaks = candlesByTf.ltf?.length ? findStructureBreaks(candlesByTf.ltf, 60) : [];

  const openFvgs = fvgs.filter((f) => !f.filled);
  const freshObs = obs.filter((o) => !o.mitigated);
  const recentSweeps = sweeps.filter((s) => s.barsAgo <= 12);
  const recentBreaks = breaks.filter((b) => b.barsAgo <= 12);

  let score = 0;
  const signals = [];
  for (const s of recentSweeps) {
    const w = s.volumeConfirmed ? 0.45 : 0.25;
    const decay = Math.max(0.3, 1 - s.barsAgo / 12);
    score += s.direction === 'bullish' ? w * decay : -(w * decay);
    signals.push(`${s.type} (${s.barsAgo} mum önce)`);
  }
  for (const b of recentBreaks) {
    const base = b.type === 'CHOCH' ? 0.40 : 0.30;
    const decay = Math.max(0.3, 1 - b.barsAgo / 12);
    score += b.direction === 'bullish' ? base * decay : -(base * decay);
    signals.push(`${b.type} ${b.direction} (${b.barsAgo} mum önce)`);
  }

  const nearBull = openFvgs.filter((f) => f.direction === 'bullish' && f.distancePct >= -3 && f.distancePct <= 0.5);
  const nearBear = openFvgs.filter((f) => f.direction === 'bearish' && f.distancePct >= -0.5 && f.distancePct <= 3);
  score += 0.15 * Math.min(nearBull.length, 2);
  score -= 0.15 * Math.min(nearBear.length, 2);
  score = clamp(score);

  const lastBreak = breaks.length ? breaks[breaks.length - 1] : null;
  const byDist = (a, b) => Math.abs(a.distancePct) - Math.abs(b.distancePct);
  const parts = [];
  if (recentSweeps.length) {
    const s = recentSweeps[recentSweeps.length - 1];
    parts.push(`${s.direction === 'bullish' ? 'Dip' : 'Tepe'} likiditesi süpürüldü (${s.barsAgo} mum önce)`);
  }
  if (lastBreak) parts.push(`Son yapı olayı: ${lastBreak.type} ${lastBreak.direction} (${lastBreak.barsAgo} mum önce)`);
  if (openFvgs.length) parts.push(`${openFvgs.length} açık FVG`);

  return {
    available: true, score,
    label: score > 0.3 ? 'BULLISH' : score < -0.3 ? 'BEARISH' : 'NEUTRAL',
    liquiditySweeps: sweeps.slice(-sm.maxItems),
    recentSweeps,
    fvg: {
      open: openFvgs.slice().sort(byDist).slice(0, sm.maxItems),
      bullishCount: openFvgs.filter((f) => f.direction === 'bullish').length,
      bearishCount: openFvgs.filter((f) => f.direction === 'bearish').length,
      nearestBullish: nearBull.length ? nearBull.slice().sort(byDist)[0] : null,
      nearestBearish: nearBear.length ? nearBear.slice().sort(byDist)[0] : null,
    },
    orderBlocks: {
      fresh: freshObs.slice().sort(byDist).slice(0, sm.maxItems),
      bullishCount: freshObs.filter((o) => o.direction === 'bullish').length,
      bearishCount: freshObs.filter((o) => o.direction === 'bearish').length,
    },
    structureBreaks: breaks.slice(-sm.maxItems),
    ltfStructureBreaks: ltfBreaks.slice(-3),
    lastBreak, signals,
    summary: parts.join(' · ') || 'Belirgin smart money sinyali yok',
  };
}

// ===========================================================================
// 3) DERIVATIVES ENGINE
// ===========================================================================
export function interpretOi(oiChange, priceChange) {
  if (oiChange == null || priceChange == null) {
    return { state: 'NA', meaning: 'Veri yok', score: 0 };
  }
  const oiUp = oiChange > 0.3, oiDown = oiChange < -0.3;
  const pxUp = priceChange > 0.1, pxDown = priceChange < -0.1;
  const strength = clamp(Math.abs(oiChange) / 8, 0, 1);

  if (oiUp && pxUp) return { state: 'YENİ LONG', meaning: 'OI ve fiyat birlikte artıyor — taze long girişi', score: 0.9 * strength };
  if (oiUp && pxDown) return { state: 'YENİ SHORT', meaning: 'OI artarken fiyat düşüyor — taze short girişi', score: -0.9 * strength };
  if (oiDown && pxUp) return { state: 'SHORT KAPANIŞI', meaning: 'OI düşerken fiyat yükseliyor — short covering, itici güç zayıf', score: 0.35 * strength };
  if (oiDown && pxDown) return { state: 'LONG KAPANIŞI', meaning: 'OI ve fiyat birlikte düşüyor — long tasfiyesi', score: -0.35 * strength };
  return { state: 'YATAY', meaning: 'Belirgin pozisyon değişimi yok', score: 0 };
}

function analyzeFunding(current, history, mark, index, interestRate) {
  const curPct = current * 100;
  const avgPct = history.length ? mean(history.map((h) => h.rate)) * 100 : curPct;
  const last8 = history.length ? mean(history.slice(-8).map((h) => h.rate)) * 100 : curPct;
  const premium = index ? (mark - index) / index : 0;
  const predicted = premium + Math.max(Math.min(interestRate - premium, 0.0005), -0.0005);

  const a = Math.abs(curPct);
  let health, score;
  if (a < 0.01) { health = 'SAĞLIKLI'; score = 0; }
  else if (a < 0.03) { health = 'NORMAL'; score = curPct > 0 ? 0.25 : -0.25; }
  else if (a < 0.06) { health = 'ISINIYOR'; score = curPct > 0 ? -0.45 : 0.45; }
  else { health = 'AŞIRI'; score = curPct > 0 ? -0.9 : 0.9; }

  return {
    currentPct: curPct, avgPct, avg8Pct: last8, predictedPct: predicted * 100,
    annualizedPct: curPct * 3 * 365, health, score,
    bias: curPct > 0 ? "Long'lar short'lara ödüyor (long ağırlıklı pozisyonlanma)"
      : curPct < 0 ? "Short'lar long'lara ödüyor (short ağırlıklı pozisyonlanma)" : 'Dengeli',
    trend: curPct > last8 ? 'ARTIYOR' : curPct < last8 ? 'AZALIYOR' : 'SABİT',
    history,
  };
}

function analyzeLsRatios(topAcc, topPos, glob, crowded) {
  const last = (arr, key) => (arr?.length ? arr[arr.length - 1][key] : null);
  const delta = (arr, bars = 6) =>
    arr?.length > bars ? pctChange(arr[arr.length - 1].ratio, arr[arr.length - 1 - bars].ratio) : null;

  const tp = last(topPos, 'ratio'), ta = last(topAcc, 'ratio'), gl = last(glob, 'ratio');
  let score = 0;
  const notes = [];

  if (tp != null) {
    const d = delta(topPos) || 0;
    if (tp >= crowded) { score -= 0.5; notes.push(`Büyük hesap pozisyonları aşırı long kalabalığı (${tp.toFixed(2)})`); }
    else if (tp <= 1 / crowded) { score += 0.5; notes.push(`Büyük hesap pozisyonları aşırı short kalabalığı (${tp.toFixed(2)})`); }
    else score += clamp(tp - 1) * 0.35;
    score += clamp(d / 15) * 0.25;
    if (Math.abs(d) > 3) notes.push(`Büyük hesap long oranı son 6 barda %${d.toFixed(1)}`);
  }
  if (gl != null) {
    if (gl >= 3) { score -= 0.25; notes.push(`Perakende aşırı long (${gl.toFixed(2)}) — kontra sinyal`); }
    else if (gl <= 0.6) { score += 0.25; notes.push(`Perakende aşırı short (${gl.toFixed(2)}) — kontra sinyal`); }
  }

  return {
    topAccountsRatio: ta, topPositionsRatio: tp, globalAccountsRatio: gl,
    topPositionsLongPct: last(topPos, 'longPct'), globalLongPct: last(glob, 'longPct'),
    topPositionsDeltaPct: delta(topPos),
    score: clamp(score), notes, series: topPos || [],
  };
}

function analyzeTaker(rows) {
  if (!rows?.length) return { available: false, score: 0 };
  const buy = sum(rows.map((r) => r.buy)), sell = sum(rows.map((r) => r.sell));
  const total = buy + sell;
  const imbalance = total ? (buy - sell) / total : 0;
  const recent = rows.slice(-6);
  const rb = sum(recent.map((r) => r.buy)), rs = sum(recent.map((r) => r.sell));
  const recentImb = rb + rs ? (rb - rs) / (rb + rs) : 0;

  return {
    available: true, buyVolume: buy, sellVolume: sell, delta: buy - sell,
    imbalancePct: imbalance * 100, recentImbalancePct: recentImb * 100,
    lastRatio: rows[rows.length - 1].ratio,
    score: clamp(imbalance * 4 * 0.5 + recentImb * 4 * 0.5),
    state: imbalance > 0.03 ? 'ALICI BASKIN' : imbalance < -0.03 ? 'SATICI BASKIN' : 'DENGELİ',
    series: rows,
  };
}

function analyzeBasis(mark, spotPx) {
  if (!spotPx) return { available: false, score: 0 };
  const basis = mark - spotPx;
  const pct = (basis / spotPx) * 100;
  let state, score;
  if (pct > 0.15) { state = 'PREMIUM (vadeli önde)'; score = -0.3; }
  else if (pct < -0.15) { state = 'DISCOUNT (spot önde)'; score = 0.3; }
  else { state = 'DENGELİ'; score = 0; }
  return { available: true, perpMark: mark, spotPrice: spotPx, basis, basisPct: pct, state, score };
}

export function derivativesEngine(data, cfg) {
  const out = { available: true };
  const { oiNow, oiHist, prem, fundHist, topAcc, topPos, glob, taker, spotPx } = data;

  // Open Interest — 5dk barlar: 12=1s, 48=4s, 288=24s
  const oiChange = (bars) => (oiHist.length > bars ? pctChange(oiHist[oiHist.length - 1].oi, oiHist[oiHist.length - 1 - bars].oi) : null);
  const priceAt = (i) => (oiHist[i].oi ? oiHist[i].oiUsd / oiHist[i].oi : 0);
  const pxChange = (bars) => (oiHist.length > bars ? pctChange(priceAt(oiHist.length - 1), priceAt(oiHist.length - 1 - bars)) : null);

  const i1 = interpretOi(oiChange(12), pxChange(12));
  const i4 = interpretOi(oiChange(48), pxChange(48));
  out.openInterest = {
    current: +oiNow.openInterest,
    currentUsd: oiHist.length ? oiHist[oiHist.length - 1].oiUsd : null,
    change1hPct: oiChange(12), change4hPct: oiChange(48), change24hPct: oiChange(288),
    priceChange1hPct: pxChange(12),
    interpretation1h: i1, interpretation4h: i4,
    score: clamp(i1.score * 0.6 + i4.score * 0.4),
    trend: (oiChange(12) || 0) > 0.3 ? 'ARTIYOR' : (oiChange(12) || 0) < -0.3 ? 'AZALIYOR' : 'YATAY',
    series: oiHist.slice(-288),
  };

  const mark = +prem.markPrice, index = +prem.indexPrice;
  out.funding = analyzeFunding(+prem.lastFundingRate, fundHist, mark, index, +(prem.interestRate ?? 0.0001));
  out.funding.nextFundingTime = +prem.nextFundingTime;
  out.markPrice = mark;
  out.indexPrice = index;

  out.longShort = analyzeLsRatios(topAcc, topPos, glob, cfg.risk.crowdedLsRatio);
  out.taker = analyzeTaker(taker);

  // Likidasyon: tarayıcı sürümünde 7/24 websocket toplayıcı olmadığı için
  // geçmiş veri yok. Skorlama bu bileşeni "veri yok" sayar, güven düşer.
  out.liquidations = {
    available: false, score: 0, longUsdt: 0, shortUsdt: 0, totalUsdt: 0, count: 0, squeeze: 'NONE',
    note: 'Likidasyon geçmişi 7/24 açık bir toplayıcı gerektirir — tarayıcı sürümünde yok',
  };

  out.basis = analyzeBasis(mark, spotPx);

  const parts = [];
  if (out.openInterest.change1hPct != null) parts.push(`OI 1s %${out.openInterest.change1hPct.toFixed(2)} (${i1.state})`);
  parts.push(`Funding %${out.funding.currentPct.toFixed(4)} (${out.funding.health})`);
  if (out.longShort.topPositionsRatio) parts.push(`Büyük hesap L/S ${out.longShort.topPositionsRatio.toFixed(2)}`);
  if (out.taker.available) parts.push(`Taker ${out.taker.state} (%${out.taker.imbalancePct.toFixed(1)})`);
  out.summary = parts.join(' · ');
  return out;
}

// ===========================================================================
// 4) ORDER FLOW ENGINE (Spot CVD vs Futures CVD)
// ===========================================================================
function cvdFrame(trades) {
  if (!trades?.length) {
    return { available: false, buy: 0, sell: 0, delta: 0, cvd: 0, series: [], trades: 0 };
  }
  const buy = sum(trades.filter((t) => t.side === 'buy').map((t) => t.notional));
  const sell = sum(trades.filter((t) => t.side === 'sell').map((t) => t.notional));

  // Dakikalık kümülatif delta serisi
  const perMin = new Map();
  for (const t of trades) {
    const k = Math.floor(t.time / 60000) * 60000;
    perMin.set(k, (perMin.get(k) || 0) + (t.side === 'buy' ? t.notional : -t.notional));
  }
  const keys = [...perMin.keys()].sort((a, b) => a - b);
  let cum = 0;
  const series = keys.map((k) => { cum += perMin.get(k); return { time: k, cvd: cum }; });

  const total = buy + sell;
  const buyTrades = trades.filter((t) => t.side === 'buy');
  const sellTrades = trades.filter((t) => t.side === 'sell');
  return {
    available: true, buy, sell, delta: buy - sell,
    imbalancePct: total ? ((buy - sell) / total) * 100 : 0,
    cvd: cum, trades: trades.length,
    windowMinutes: (trades[trades.length - 1].time - trades[0].time) / 60000,
    start: trades[0].time, end: trades[trades.length - 1].time,
    series,
    avgBuySize: buyTrades.length ? mean(buyTrades.map((t) => t.notional)) : 0,
    avgSellSize: sellTrades.length ? mean(sellTrades.map((t) => t.notional)) : 0,
  };
}

function slope(series, tail = 15) {
  if (series.length < 4) return 0;
  const vals = series.slice(-tail).map((p) => p.cvd);
  const n = vals.length;
  const xs = vals.map((_, i) => i);
  const mx = mean(xs), my = mean(vals);
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) { num += (xs[i] - mx) * (vals[i] - my); den += (xs[i] - mx) ** 2; }
  if (!den) return 0;
  const sl = num / den;
  const scale = Math.max(...vals.map(Math.abs), 1);
  return clamp((sl / scale) * n);
}

export function orderFlowEngine(futTrades, spotTrades, spotMap) {
  const fut = cvdFrame(futTrades);
  const spotF = spotTrades?.length ? cvdFrame(spotTrades) : { available: false };
  if (spotF.available && spotMap) spotF.symbol = spotMap.symbol;

  const futScore = fut.available ? clamp(fut.imbalancePct / 12) : 0;
  const futSlope = slope(fut.series || []);
  const spotScore = spotF.available ? clamp(spotF.imbalancePct / 12) : 0;
  const spotSlope = slope(spotF.series || []);

  let score = spotF.available
    ? clamp(0.35 * futScore + 0.15 * futSlope + 0.35 * spotScore + 0.15 * spotSlope)
    : clamp(0.7 * futScore + 0.3 * futSlope);

  let divergence = 'NA', note = '';
  if (spotF.available && fut.available) {
    const fp = fut.delta > 0, sp = spotF.delta > 0;
    if (fp && sp) { divergence = 'UYUMLU_ALIM'; note = 'Hem spot hem vadeli tarafta agresif alım — sağlıklı yükseliş'; }
    else if (!fp && !sp) { divergence = 'UYUMLU_SATIM'; note = 'Hem spot hem vadeli tarafta agresif satım — sağlıklı düşüş'; }
    else if (fp && !sp) { divergence = 'SADECE_VADELİ_ALIM'; note = 'Vadeli alıyor, spot satıyor — kaldıraçlı/kırılgan yükseliş'; score = clamp(score * 0.6); }
    else { divergence = 'SADECE_SPOT_ALIM'; note = 'Spot alıyor, vadeli satıyor — gerçek para birikim yapıyor olabilir'; score = clamp(score * 0.6 + 0.15); }
  }

  const parts = [];
  if (fut.available) parts.push(`Vadeli CVD ${fut.delta.toFixed(0)} USDT (%${fut.imbalancePct.toFixed(1)})`);
  if (spotF.available) parts.push(`Spot CVD ${spotF.delta.toFixed(0)} USDT (%${spotF.imbalancePct.toFixed(1)})`);
  if (note) parts.push(note);

  return {
    available: fut.available, score,
    label: score > 0.25 ? 'BULLISH' : score < -0.25 ? 'BEARISH' : 'NEUTRAL',
    futures: fut, spot: spotF, futuresSlope: futSlope, spotSlope,
    divergence, divergenceNote: note,
    aggressiveBuyersUsdt: (fut.buy || 0) + (spotF.buy || 0),
    aggressiveSellersUsdt: (fut.sell || 0) + (spotF.sell || 0),
    summary: parts.join(' · ') || 'Akış verisi yok',
  };
}

// ===========================================================================
// 5) WHALE ENGINE
// ===========================================================================
const tierLabel = (t) =>
  t >= 1e6 ? `${(t / 1e6).toFixed(1).replace('.0', '')}M+` : t >= 1e3 ? `${Math.round(t / 1e3)}k+` : `${Math.round(t)}+`;

function effectiveTiers(trades, tiers, cfg) {
  const sorted = [...tiers].sort((a, b) => a - b);
  if (!cfg.autoScale || !trades?.length) return { tiers: sorted, scaled: false };
  const hits = trades.filter((t) => t.notional >= sorted[0]).length;
  if (hits >= cfg.autoMinHits) return { tiers: sorted, scaled: false };
  const base = Math.max(percentile(trades.map((t) => t.notional), cfg.autoPercentile), cfg.minTierFloor);
  const ratios = sorted.map((t) => t / sorted[0]);
  return { tiers: ratios.map((r) => base * r), scaled: true, base, percentile: cfg.autoPercentile };
}

function detectIceberg(trades, cfg) {
  if (!trades?.length) return [];
  const groups = new Map();
  for (const t of trades) {
    // Miktarı 4 anlamlı basamağa yuvarlayarak grupla
    const mag = Math.pow(10, Math.floor(Math.log10(Math.max(t.qty, 1e-12))) - 3);
    const key = `${Math.round(t.qty / mag) * mag}|${t.side}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(t);
  }
  const out = [];
  const windowMs = cfg.icebergWindowSeconds * 1000;
  for (const [key, grp] of groups) {
    if (grp.length < cfg.icebergMinRepeats) continue;
    grp.sort((a, b) => a.time - b.time);
    const span = grp[grp.length - 1].time - grp[0].time;
    if (span > windowMs * 4) continue;
    const notional = sum(grp.map((t) => t.notional));
    if (notional < 20000) continue;
    out.push({
      qty: +key.split('|')[0], side: key.split('|')[1], repeats: grp.length,
      totalNotional: notional, avgPrice: mean(grp.map((t) => t.price)),
      spanSeconds: span / 1000, first: grp[0].time, last: grp[grp.length - 1].time,
    });
  }
  return out.sort((a, b) => b.totalNotional - a.totalNotional).slice(0, 5);
}

function analyzeWhaleMarket(trades, tiers, cfg, market) {
  if (!trades?.length) return { available: false, market, score: 0 };
  const scaling = effectiveTiers(trades, tiers, cfg);
  const useTiers = scaling.tiers;

  const tierStats = {};
  for (const t of useTiers) {
    const sub = trades.filter((x) => x.notional >= t);
    const buy = sum(sub.filter((x) => x.side === 'buy').map((x) => x.notional));
    const sell = sum(sub.filter((x) => x.side === 'sell').map((x) => x.notional));
    tierStats[tierLabel(t)] = {
      thresholdUsdt: t, count: sub.length, buyUsdt: buy, sellUsdt: sell,
      deltaUsdt: buy - sell,
      buyCount: sub.filter((x) => x.side === 'buy').length,
      sellCount: sub.filter((x) => x.side === 'sell').length,
    };
  }

  const whales = trades.filter((t) => t.notional >= useTiers[0]);
  const buy = sum(whales.filter((t) => t.side === 'buy').map((t) => t.notional));
  const sell = sum(whales.filter((t) => t.side === 'sell').map((t) => t.notional));
  const total = buy + sell;
  const imbalance = total ? (buy - sell) / total : 0;

  let weighted = 0, weightSum = 0;
  useTiers.forEach((t, i) => {
    const st = tierStats[tierLabel(t)];
    const tot = st.buyUsdt + st.sellUsdt;
    if (tot <= 0) return;
    const w = Math.pow(i + 1, 1.5);
    weighted += (st.deltaUsdt / tot) * w;
    weightSum += w;
  });
  const weightedImb = weightSum ? weighted / weightSum : imbalance;

  const icebergs = detectIceberg(trades, cfg);
  let iceBias = 0;
  if (icebergs.length) {
    const ib = sum(icebergs.filter((i) => i.side === 'buy').map((i) => i.totalNotional));
    const isl = sum(icebergs.filter((i) => i.side === 'sell').map((i) => i.totalNotional));
    if (ib + isl > 0) iceBias = (ib - isl) / (ib + isl);
  }

  return {
    available: true, market, tiers: tierStats, tierScaling: scaling,
    whaleBuyUsdt: buy, whaleSellUsdt: sell, whaleDeltaUsdt: buy - sell,
    imbalancePct: imbalance * 100, weightedImbalance: weightedImb, whaleCount: whales.length,
    largestTrades: whales.slice().sort((a, b) => b.notional - a.notional).slice(0, 10),
    icebergs,
    score: clamp(weightedImb * 1.4 * 0.8 + iceBias * 0.2),
    state: imbalance > 0.15 ? 'BİRİKİM' : imbalance < -0.15 ? 'DAĞITIM' : 'NÖTR',
  };
}

export function whaleEngine(futTrades, spotTrades, cfg) {
  const w = cfg.whale;
  const fut = analyzeWhaleMarket(futTrades, w.tiers, w, 'futures');
  const spotW = analyzeWhaleMarket(spotTrades, w.tiers, w, 'spot');

  const scores = [], weights = [];
  if (fut.available) { scores.push(fut.score); weights.push(0.55); }
  if (spotW.available) { scores.push(spotW.score); weights.push(0.45); }
  const score = scores.length ? clamp(scores.reduce((s, v, i) => s + v * weights[i], 0) / sum(weights)) : 0;
  const totalDelta = (fut.whaleDeltaUsdt || 0) + (spotW.whaleDeltaUsdt || 0);

  const parts = [];
  if (fut.available) {
    if (fut.tierScaling.scaled) parts.push(`Eşik sembole göre ölçeklendi (≥${Math.round(fut.tierScaling.base).toLocaleString('tr-TR')} USDT)`);
    parts.push(`Vadeli balina deltası ${fut.whaleDeltaUsdt.toFixed(0)} USDT (${fut.whaleCount} işlem, ${fut.state})`);
  }
  if (spotW.available) parts.push(`Spot balina deltası ${spotW.whaleDeltaUsdt.toFixed(0)} USDT (${spotW.state})`);
  const ice = [...(fut.icebergs || []), ...(spotW.icebergs || [])];
  if (ice.length) parts.push(`${ice.length} iceberg şüphesi`);

  return {
    available: fut.available || spotW.available, score,
    futures: fut, spot: spotW, totalWhaleDeltaUsdt: totalDelta,
    state: score > 0.2 ? 'BİRİKİM' : score < -0.2 ? 'DAĞITIM' : 'NÖTR',
    summary: parts.join(' · ') || 'Balina aktivitesi yok',
  };
}

// ===========================================================================
// 6) ORDER BOOK ENGINE
// ===========================================================================
function walls(levels, mid, multiplier, side) {
  if (!levels.length) return [];
  const notionals = levels.map(([p, q]) => p * q);
  const avg = mean(notionals);
  if (avg <= 0) return [];
  const out = [];
  levels.forEach(([price, qty], i) => {
    if (notionals[i] >= avg * multiplier) {
      out.push({
        side, price, qty, notional: notionals[i],
        xAverage: notionals[i] / avg,
        distancePct: ((price - mid) / mid) * 100,
      });
    }
  });
  return out.sort((a, b) => b.notional - a.notional).slice(0, 6);
}

function compareWalls(prevWalls, curLevels, trades, side, cfg) {
  const spoofs = [], absorptions = [];
  if (!prevWalls?.length) return { spoofs, absorptions };
  const curMap = new Map(curLevels.map(([p, q]) => [p, q]));

  for (const w of prevWalls) {
    if (w.notional < cfg.spoofMinNotional) continue;
    const nowQty = curMap.get(w.price) || 0;
    const shrink = w.qty ? 1 - nowQty / w.qty : 0;

    let tradedHere = 0;
    if (trades?.length) {
      const tol = w.price * 0.0006;
      tradedHere = sum(trades.filter((t) => t.price >= w.price - tol && t.price <= w.price + tol).map((t) => t.qty));
    }

    if (shrink >= cfg.spoofVanishPct) {
      const consumed = w.qty * shrink ? tradedHere / (w.qty * shrink) : 0;
      if (consumed < 0.25) {
        spoofs.push({ ...w, shrinkPct: shrink * 100, tradedQty: tradedHere, verdict: 'İşlem görmeden çekildi (spoof şüphesi)' });
      } else {
        absorptions.push({ ...w, shrinkPct: shrink * 100, tradedQty: tradedHere, verdict: 'Emirler yenmiş (gerçek likidite)' });
      }
    } else if (tradedHere > w.qty * 0.5 && shrink < 0.3) {
      absorptions.push({ ...w, shrinkPct: shrink * 100, tradedQty: tradedHere, verdict: 'Duvar yenilendi — absorption' });
    }
  }
  return { spoofs, absorptions };
}

function bookIcebergs(prevLevels, curLevels, side) {
  if (!prevLevels?.length) return [];
  const prevMap = new Map(prevLevels.map(([p, q]) => [p, q]));
  const out = [];
  for (const [price, qty] of curLevels) {
    const pq = prevMap.get(price);
    if (pq != null && qty > 0 && Math.abs(pq - qty) / Math.max(qty, 1e-12) < 0.02 && price * qty > 50000) {
      out.push({ side, price, qty, notional: price * qty, note: 'Seviye miktarı sabit kalıyor — yenilenen gizli emir' });
    }
  }
  return out.slice(0, 4);
}

export function orderBookEngine(book, cfg, futTrades, prevSnapshot) {
  const ob = cfg.orderbook;
  const { bids, asks } = book;
  if (!bids.length || !asks.length) return { available: false, score: 0 };

  const bestBid = bids[0][0], bestAsk = asks[0][0];
  const mid = (bestBid + bestAsk) / 2;
  const spreadPct = ((bestAsk - bestBid) / mid) * 100;

  const band = ob.imbalanceDepthPct / 100;
  const lo = mid * (1 - band), hi = mid * (1 + band);
  const bidNear = sum(bids.filter(([p]) => p >= lo).map(([p, q]) => p * q));
  const askNear = sum(asks.filter(([p]) => p <= hi).map(([p, q]) => p * q));
  const nearTotal = bidNear + askNear;
  const nearImb = nearTotal ? (bidNear - askNear) / nearTotal : 0;

  const bidTotal = sum(bids.map(([p, q]) => p * q));
  const askTotal = sum(asks.map(([p, q]) => p * q));
  const fullImb = bidTotal + askTotal ? (bidTotal - askTotal) / (bidTotal + askTotal) : 0;

  const bidWalls = walls(bids, mid, ob.wallMultiplier, 'bid');
  const askWalls = walls(asks, mid, ob.wallMultiplier, 'ask');

  let spoofs = [], absorptions = [], icebergs = [];
  let compareNote = 'Karşılaştırma için ikinci tarama bekleniyor';
  if (prevSnapshot) {
    const pBidWalls = walls(prevSnapshot.bids, prevSnapshot.mid, ob.wallMultiplier, 'bid');
    const pAskWalls = walls(prevSnapshot.asks, prevSnapshot.mid, ob.wallMultiplier, 'ask');
    const r1 = compareWalls(pBidWalls, bids, futTrades, 'bid', ob);
    const r2 = compareWalls(pAskWalls, asks, futTrades, 'ask', ob);
    spoofs = [...r1.spoofs, ...r2.spoofs];
    absorptions = [...r1.absorptions, ...r2.absorptions];
    icebergs = [...bookIcebergs(prevSnapshot.bids, bids, 'bid'), ...bookIcebergs(prevSnapshot.asks, asks, 'ask')];
    const mins = Math.round((Date.now() - prevSnapshot.ts) / 60000);
    compareNote = `Önceki fotoğrafla karşılaştırıldı (${mins} dk önce)`;
  }

  let score = clamp(nearImb * 2) * 0.55 + clamp(fullImb * 2) * 0.20;
  let wallBias = 0;
  if (bidWalls.length || askWalls.length) {
    const bw = sum(bidWalls.map((w) => w.notional));
    const aw = sum(askWalls.map((w) => w.notional));
    if (bw + aw > 0) wallBias = (bw - aw) / (bw + aw);
  }
  score += clamp(wallBias) * 0.15;
  for (const s of spoofs) score += s.side === 'bid' ? -0.08 : 0.08;
  for (const a of absorptions) score += a.side === 'ask' ? 0.08 : -0.08;
  score = clamp(score);

  const parts = [`Yakın likidite dengesi %${(nearImb * 100).toFixed(1)}`];
  if (bidWalls.length) parts.push(`${bidWalls.length} bid duvarı`);
  if (askWalls.length) parts.push(`${askWalls.length} ask duvarı`);
  if (spoofs.length) parts.push(`${spoofs.length} spoof şüphesi`);
  if (absorptions.length) parts.push(`${absorptions.length} absorption`);

  return {
    available: true, score, midPrice: mid, bestBid, bestAsk, spreadPct,
    levelsRead: bids.length, nearBandPct: ob.imbalanceDepthPct,
    bidLiquidityNear: bidNear, askLiquidityNear: askNear, nearImbalancePct: nearImb * 100,
    bidLiquidityTotal: bidTotal, askLiquidityTotal: askTotal, fullImbalancePct: fullImb * 100,
    bidWalls, askWalls, spoofs, absorptions, icebergs, compareNote,
    state: nearImb > 0.1 ? 'ALICI AĞIRLIKLI' : nearImb < -0.1 ? 'SATICI AĞIRLIKLI' : 'DENGELİ',
    summary: parts.join(' · '),
    depthChart: { bids, asks },
  };
}
