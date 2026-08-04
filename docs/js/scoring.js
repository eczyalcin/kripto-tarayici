// AI Skor Sistemi · Risk Engine · Trade Setup Engine
// Python sürümündeki engines/scoring.py, risk.py, trade_setup.py karşılığı.

import { macdScore, rsiScore } from './engines.js';
import { clamp, trLower } from './util.js';

const LABELS = {
  trend: 'Trend',
  open_interest: 'Open Interest',
  funding: 'Funding',
  cvd: 'CVD / Order Flow',
  rsi: 'RSI',
  macd: 'MACD',
  orderbook: 'Order Book',
  whale: 'Whale',
  liquidation: 'Likidasyon',
  smart_money: 'Smart Money',
};

function oiDetail(d) {
  const oi = d.openInterest || {};
  if (oi.change1hPct == null) return 'OI verisi yok';
  let txt = `OI 1s %${oi.change1hPct.toFixed(2)} — ${oi.interpretation1h?.state || ''}`;
  if (d.longShort?.topPositionsRatio) txt += ` | Büyük hesap L/S ${d.longShort.topPositionsRatio.toFixed(2)}`;
  return txt;
}

function fundingDetail(d) {
  const f = d.funding || {};
  if (f.currentPct == null) return 'Veri yok';
  return `%${f.currentPct.toFixed(4)} (${f.health}, yıllık ~%${f.annualizedPct.toFixed(1)}) · ${f.bias}`;
}

export function collectComponents(e) {
  const { trend, derivatives: d, orderFlow: flow, orderbook: book, whale, smartMoney: sm } = e;
  const rsiPart = rsiScore(trend);
  const macdPart = macdScore(trend);

  const oiComponent = clamp((d.openInterest?.score ?? 0) * 0.7 + (d.longShort?.score ?? 0) * 0.3);
  const cvdComponent = clamp((flow.score ?? 0) * 0.7 + (d.taker?.score ?? 0) * 0.3);

  return {
    trend: { raw: clamp(trend.score), detail: trend.summary, available: !!trend.timeframes },
    open_interest: { raw: oiComponent, detail: oiDetail(d), available: d.openInterest?.change1hPct != null },
    funding: { raw: clamp(d.funding?.score ?? 0), detail: fundingDetail(d), available: d.funding?.currentPct != null },
    cvd: { raw: cvdComponent, detail: flow.summary, available: !!flow.available },
    rsi: { raw: clamp(rsiPart.score), detail: `RSI ${rsiPart.value?.toFixed(1)} — ${rsiPart.state}`, available: rsiPart.value != null },
    macd: { raw: clamp(macdPart.score), detail: `MACD ${macdPart.state}`, available: macdPart.state !== 'NA' },
    orderbook: { raw: clamp(book.score ?? 0), detail: book.summary, available: !!book.available },
    whale: { raw: clamp(whale.score ?? 0), detail: whale.summary, available: !!whale.available },
    liquidation: { raw: 0, detail: d.liquidations?.note || 'Veri yok', available: false },
    smart_money: { raw: clamp(sm.score ?? 0), detail: sm.summary, available: !!sm.available },
  };
}

function decide(longScore, t) {
  if (longScore >= t.strongLong) return 'STRONG LONG';
  if (longScore >= t.long) return 'LONG';
  if (longScore >= t.weakLong) return 'WEAK LONG';
  if (longScore <= t.strongShort) return 'STRONG SHORT';
  if (longScore <= t.short) return 'SHORT';
  if (longScore <= t.weakShort) return 'WEAK SHORT';
  return 'NÖTR';
}

function answer(e, decision, longScore) {
  const oiState = e.derivatives.openInterest?.interpretation1h?.state;
  const ls = e.derivatives.longShort?.topPositionsRatio;
  const bits = [];
  if (oiState && oiState !== 'NA') bits.push(`pozisyonlanma: ${trLower(oiState)}`);
  if (ls) bits.push(`büyük hesaplar ${ls > 1 ? 'long' : 'short'} ağırlıklı (L/S ${ls.toFixed(2)})`);
  if (e.whale.state && e.whale.state !== 'NÖTR') bits.push(`balinalar ${trLower(e.whale.state)} yapıyor`);
  if (e.orderFlow.divergenceNote) bits.push(trLower(e.orderFlow.divergenceNote));
  return `${decision} (Long ${longScore.toFixed(0)}/100) — ${bits.join('; ') || 'belirgin bir yön yok'}.`;
}

export function scoreEngine(engines, cfg) {
  const weights = cfg.scoring.weights;
  const comps = collectComponents(engines);
  const rows = [];
  let totalWeight = 0, weightedSum = 0, availableWeight = 0;

  for (const [key, w] of Object.entries(weights)) {
    const c = comps[key];
    if (!c) continue;
    const raw = c.available ? c.raw : 0;
    const points = raw * w;
    weightedSum += points;
    totalWeight += w;
    if (c.available) availableWeight += w;
    rows.push({
      key, name: LABELS[key] || key, weight: w, raw, points, maxPoints: w,
      available: c.available, detail: c.detail,
      direction: raw > 0.05 ? 'LONG' : raw < -0.05 ? 'SHORT' : 'NÖTR',
    });
  }

  const net = totalWeight ? weightedSum / totalWeight : 0;
  const longScore = Math.max(0, Math.min(100, 50 + 50 * net));
  const shortScore = 100 - longScore;
  const decision = decide(longScore, cfg.scoring.thresholds);

  const coverage = totalWeight ? availableWeight / totalWeight : 0;
  const dirs = rows.filter((r) => r.available && Math.abs(r.raw) > 0.05).map((r) => r.raw);
  const agree = dirs.length ? dirs.filter((d) => d > 0 === net > 0).length / dirs.length : 0.5;
  const confidence = clamp(coverage * 0.5 + agree * 0.5, 0, 1) * 100;

  return {
    longScore, shortScore, net, decision, confidence,
    coveragePct: coverage * 100, agreementPct: agree * 100,
    components: rows,
    topDrivers: rows.slice().sort((a, b) => Math.abs(b.points) - Math.abs(a.points)).slice(0, 4),
    totalPoints: weightedSum, totalWeight,
    answer: answer(engines, decision, longScore),
  };
}

// ===========================================================================
// RISK ENGINE
// ===========================================================================
export function riskEngine(engines, cfg) {
  const r = cfg.risk;
  const { trend, derivatives: d, orderbook: book } = engines;
  const factors = [];
  let points = 0;

  const atrPct = trend.atrPct;
  if (atrPct != null) {
    const hv = r.highVolatilityAtrPct;
    let p, state;
    if (atrPct >= hv * 1.5) { p = 3; state = 'ÇOK YÜKSEK'; }
    else if (atrPct >= hv) { p = 2; state = 'YÜKSEK'; }
    else if (atrPct >= hv * 0.5) { p = 1; state = 'NORMAL'; }
    else { p = 0; state = 'DÜŞÜK'; }
    points += p;
    factors.push({ factor: 'Volatilite (ATR%)', value: `%${atrPct.toFixed(2)}`, state, points: p });
  }

  const cur = d.funding?.currentPct;
  if (cur != null) {
    const ex = r.extremeFunding;
    const a = Math.abs(cur);
    let p, state;
    if (a >= ex * 2) { p = 3; state = 'AŞIRI'; }
    else if (a >= ex) { p = 2; state = 'YÜKSEK'; }
    else if (a >= ex / 2) { p = 1; state = 'ARTIYOR'; }
    else { p = 0; state = 'SAĞLIKLI'; }
    points += p;
    factors.push({ factor: 'Funding maliyeti', value: `%${cur.toFixed(4)}`, state, points: p });
  }

  const ls = d.longShort?.topPositionsRatio;
  if (ls) {
    const c = r.crowdedLsRatio;
    let p, state;
    if (ls >= c || ls <= 1 / c) { p = 2; state = 'KALABALIK'; }
    else if (ls >= c * 0.75 || ls <= 1 / (c * 0.75)) { p = 1; state = 'YOĞUNLAŞIYOR'; }
    else { p = 0; state = 'DENGELİ'; }
    points += p;
    factors.push({ factor: 'Pozisyon kalabalığı', value: `L/S ${ls.toFixed(2)}`, state, points: p });
  }

  if (book?.available) {
    const spread = book.spreadPct;
    let p, state;
    if (spread > 0.08) { p = 2; state = 'GENİŞ SPREAD'; }
    else if (spread > 0.03) { p = 1; state = 'ORTA'; }
    else { p = 0; state = 'DERİN'; }
    points += p;
    factors.push({ factor: 'Order book likiditesi', value: `%${spread.toFixed(4)} spread`, state, points: p });
    if (book.spoofs?.length) {
      points += 1;
      factors.push({ factor: 'Spoof aktivitesi', value: `${book.spoofs.length} şüpheli duvar`, state: 'MANİPÜLASYON ŞÜPHESİ', points: 1 });
    }
  }

  if (trend.timeframes && !trend.mtfAligned) {
    points += 1;
    factors.push({ factor: 'Zaman dilimi uyumu', value: 'Uyumsuz', state: 'KARARSIZ', points: 1 });
  }

  const level = points >= 6 ? 'YÜKSEK' : points >= 3 ? 'ORTA' : 'DÜŞÜK';
  const riskUsdt = (r.accountSizeUsdt * r.riskPerTradePct) / 100;
  const levFactor = { DÜŞÜK: 1.0, ORTA: 0.6, YÜKSEK: 0.3 }[level];

  return {
    level, points, factors,
    accountSizeUsdt: r.accountSizeUsdt, riskPerTradePct: r.riskPerTradePct, riskUsdt,
    suggestedMaxLeverage: Math.max(1, Math.round(r.maxLeverage * levFactor)),
    summary: `Risk ${level} (${points} puan) · ` + factors.slice(0, 3).map((f) => `${f.factor}: ${f.state}`).join(' · '),
  };
}

// ===========================================================================
// TRADE SETUP ENGINE
// ===========================================================================
function roundTick(value, tick, precision) {
  if (!value) return value;
  let v = value;
  if (tick && tick > 0) v = Math.round(v / tick) * tick;
  return +v.toFixed(precision);
}

function nearestZones(sm, direction, price) {
  const out = [];
  const want = direction === 'LONG' ? 'bullish' : 'bearish';
  for (const f of sm.fvg?.open || []) {
    if (f.direction !== want) continue;
    if (direction === 'LONG' && f.top <= price * 1.002) out.push({ kind: 'FVG', low: f.bottom, high: f.top, distancePct: f.distancePct });
    else if (direction === 'SHORT' && f.bottom >= price * 0.998) out.push({ kind: 'FVG', low: f.bottom, high: f.top, distancePct: f.distancePct });
  }
  for (const o of sm.orderBlocks?.fresh || []) {
    if (o.direction !== want) continue;
    if (direction === 'LONG' && o.top <= price * 1.002) out.push({ kind: 'OB', low: o.bottom, high: o.top, distancePct: o.distancePct });
    else if (direction === 'SHORT' && o.bottom >= price * 0.998) out.push({ kind: 'OB', low: o.bottom, high: o.top, distancePct: o.distancePct });
  }
  return out.sort((a, b) => Math.abs(a.distancePct) - Math.abs(b.distancePct)).slice(0, 3);
}

function snapTarget(target, candidates, direction, tolerancePct = 1.2) {
  for (const c of candidates) {
    if (!c) continue;
    if ((Math.abs(c - target) / target) * 100 <= tolerancePct) {
      return c * (direction === 'LONG' ? 0.999 : 1.001);
    }
  }
  return target;
}

export function tradeSetupEngine(symbol, engines, score, risk, cfg, meta) {
  const s = cfg.setup;
  const { trend, smartMoney: sm, derivatives: d, orderbook: book } = engines;
  const price = trend.price ?? book.midPrice;
  const mtf = trend.timeframes?.mtf;
  const atr = mtf?.atr?.value;
  const tick = meta?.tickSize ?? 0;
  const precision = meta?.pricePrecision ?? 8;

  let direction, conviction;
  if (score.longScore >= s.minScoreForSetup) { direction = 'LONG'; conviction = score.longScore; }
  else if (score.shortScore >= s.minScoreForSetup) { direction = 'SHORT'; conviction = score.shortScore; }
  else {
    return {
      available: false, direction: 'NONE', recommendation: 'BEKLE',
      reason: `Skor nötr bölgede (Long ${score.longScore.toFixed(0)}/100). Setup için en az ${s.minScoreForSetup} gerekiyor.`,
    };
  }
  if (!price || !atr || atr <= 0) {
    return { available: false, direction, recommendation: 'BEKLE', reason: 'Fiyat/ATR verisi eksik' };
  }

  const zones = nearestZones(sm, direction, price);
  const pullback = s.entryPullbackAtr * atr;
  const vwapD = mtf.vwap?.daily;
  let entryLow, entryHigh, entryBasis;

  if (zones.length) {
    const z = zones[0];
    entryLow = Math.min(z.low, z.high);
    entryHigh = Math.max(z.low, z.high);
    entryBasis = `${z.kind} bölgesi`;
  } else if (direction === 'LONG') {
    entryHigh = price;
    entryLow = price - pullback;
    if (vwapD && price > vwapD && vwapD > price - 2 * atr) entryLow = Math.min(entryLow, vwapD);
    entryBasis = 'ATR geri çekilmesi' + (vwapD ? ' + Günlük VWAP' : '');
  } else {
    entryLow = price;
    entryHigh = price + pullback;
    if (vwapD && price < vwapD && vwapD < price + 2 * atr) entryHigh = Math.max(entryHigh, vwapD);
    entryBasis = 'ATR geri çekilmesi' + (vwapD ? ' + Günlük VWAP' : '');
  }
  const entry = (entryLow + entryHigh) / 2;

  const swingLow = mtf.structure?.lastSwingLow;
  const swingHigh = mtf.structure?.lastSwingHigh;
  let stop, stopBasis;
  if (direction === 'LONG') {
    const atrStop = entry - s.stopAtrMultiplier * atr;
    const structStop = swingLow && swingLow < entry ? swingLow - 0.25 * atr : null;
    stop = structStop != null ? Math.min(atrStop, structStop) : atrStop;
    stopBasis = structStop != null && structStop <= atrStop ? 'Swing low altı' : `${s.stopAtrMultiplier}x ATR`;
  } else {
    const atrStop = entry + s.stopAtrMultiplier * atr;
    const structStop = swingHigh && swingHigh > entry ? swingHigh + 0.25 * atr : null;
    stop = structStop != null ? Math.max(atrStop, structStop) : atrStop;
    stopBasis = structStop != null && structStop >= atrStop ? 'Swing high üstü' : `${s.stopAtrMultiplier}x ATR`;
  }

  const rDistance = Math.abs(entry - stop);
  if (rDistance <= 0) {
    return { available: false, direction, recommendation: 'BEKLE', reason: 'Geçersiz stop mesafesi' };
  }

  const structural = [];
  if (direction === 'LONG') {
    if (swingHigh) structural.push(swingHigh);
    for (const f of sm.fvg?.open || []) if (f.direction === 'bearish' && f.bottom > entry) structural.push(f.bottom);
    for (const w of book.askWalls || []) if (w.price > entry) structural.push(w.price);
  } else {
    if (swingLow) structural.push(swingLow);
    for (const f of sm.fvg?.open || []) if (f.direction === 'bullish' && f.top < entry) structural.push(f.top);
    for (const w of book.bidWalls || []) if (w.price < entry) structural.push(w.price);
  }

  const targets = s.tpRMultiples.map((m, i) => {
    const raw = direction === 'LONG' ? entry + rDistance * m : entry - rDistance * m;
    const snapped = snapTarget(raw, structural, direction);
    return {
      name: `TP${i + 1}`, price: roundTick(snapped, tick, precision), rMultiple: m,
      gainPct: ((snapped - entry) / entry) * 100 * (direction === 'LONG' ? 1 : -1),
      snapped: Math.abs(snapped - raw) > 1e-12,
    };
  });

  const entryR = roundTick(entry, tick, precision);
  const stopR = roundTick(stop, tick, precision);
  const dist = Math.abs(entryR - stopR);
  const qty = dist ? risk.riskUsdt / dist : 0;

  const invalidation = [];
  if (direction === 'LONG') {
    if (swingLow) invalidation.push(`1H swing low ${roundTick(swingLow, tick, precision)} altında kapanış`);
    invalidation.push("SuperTrend yönünün DOWN'a dönmesi");
    invalidation.push('OI artarken fiyatın düşmesi (yeni short girişi)');
  } else {
    if (swingHigh) invalidation.push(`1H swing high ${roundTick(swingHigh, tick, precision)} üstünde kapanış`);
    invalidation.push("SuperTrend yönünün UP'a dönmesi");
    invalidation.push('OI artarken fiyatın yükselmesi (yeni long girişi)');
  }

  return {
    available: true, symbol, direction, recommendation: score.decision,
    trend: trend.label,
    probability: Math.min(95, 0.65 * conviction + 0.35 * score.confidence),
    confidence: score.confidence, price,
    entry: entryR,
    entryZone: [roundTick(Math.min(entryLow, entryHigh), tick, precision), roundTick(Math.max(entryLow, entryHigh), tick, precision)],
    entryBasis, stop: stopR, stopBasis,
    stopDistancePct: entryR ? (dist / entryR) * 100 : 0,
    targets, riskReward: targets[0]?.rMultiple ?? 0,
    rrOk: (targets[0]?.rMultiple ?? 0) >= s.minRr,
    position: {
      riskUsdt: risk.riskUsdt, qty, notionalUsdt: qty * entryR,
      suggestedMaxLeverage: risk.suggestedMaxLeverage,
    },
    context: {
      funding: d.funding?.health ?? 'NA', fundingPct: d.funding?.currentPct,
      oi: d.openInterest?.trend ?? 'NA', oiChange1h: d.openInterest?.change1hPct,
      cvd: engines.orderFlow.label ?? 'NA', whales: engines.whale.state ?? 'NA',
      risk: risk.level, atrPct: mtf.atr?.pct,
    },
    invalidation,
  };
}
