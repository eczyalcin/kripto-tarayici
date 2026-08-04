// Teknik göstergeler — Python sürümündeki core/indicators.py'nin birebir karşılığı.
// Wilder yumuşatması kullanılır; RSI/ATR/ADX değerleri TradingView ile uyumludur.

export function ema(values, period) {
  const k = 2 / (period + 1);
  const out = new Array(values.length);
  let prev = values[0];
  for (let i = 0; i < values.length; i++) {
    prev = i === 0 ? values[0] : values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

// Wilder (RMA) yumuşatması: alpha = 1/period
export function wilder(values, period) {
  const a = 1 / period;
  const out = new Array(values.length);
  let prev = values[0];
  for (let i = 0; i < values.length; i++) {
    prev = i === 0 ? values[0] : values[i] * a + prev * (1 - a);
    out[i] = prev;
  }
  return out;
}

export function sma(values, period) {
  const out = new Array(values.length);
  let acc = 0;
  for (let i = 0; i < values.length; i++) {
    acc += values[i];
    if (i >= period) acc -= values[i - period];
    out[i] = acc / Math.min(i + 1, period);
  }
  return out;
}

export function rsi(closes, period = 14) {
  const gains = [0], losses = [0];
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gains.push(Math.max(d, 0));
    losses.push(Math.max(-d, 0));
  }
  const ag = wilder(gains, period);
  const al = wilder(losses, period);
  return closes.map((_, i) => {
    if (al[i] === 0) return 100;
    const rs = ag[i] / al[i];
    const v = 100 - 100 / (1 + rs);
    return isFinite(v) ? v : 50;
  });
}

export function macd(closes, fast = 12, slow = 26, signal = 9) {
  const ef = ema(closes, fast), es = ema(closes, slow);
  const line = closes.map((_, i) => ef[i] - es[i]);
  const sig = ema(line, signal);
  return { macd: line, signal: sig, hist: line.map((v, i) => v - sig[i]) };
}

export function trueRange(candles) {
  return candles.map((c, i) => {
    if (i === 0) return c.h - c.l;
    const pc = candles[i - 1].c;
    return Math.max(c.h - c.l, Math.abs(c.h - pc), Math.abs(c.l - pc));
  });
}

export function atr(candles, period = 14) {
  return wilder(trueRange(candles), period);
}

export function adx(candles, period = 14) {
  const plusDM = [0], minusDM = [0];
  for (let i = 1; i < candles.length; i++) {
    const up = candles[i].h - candles[i - 1].h;
    const down = candles[i - 1].l - candles[i].l;
    plusDM.push(up > down && up > 0 ? up : 0);
    minusDM.push(down > up && down > 0 ? down : 0);
  }
  const tr = wilder(trueRange(candles), period);
  const pdi = wilder(plusDM, period).map((v, i) => (tr[i] ? (100 * v) / tr[i] : 0));
  const mdi = wilder(minusDM, period).map((v, i) => (tr[i] ? (100 * v) / tr[i] : 0));
  const dx = pdi.map((p, i) => {
    const s = p + mdi[i];
    return s ? (100 * Math.abs(p - mdi[i])) / s : 0;
  });
  return { adx: wilder(dx, period), plusDi: pdi, minusDi: mdi };
}

export function supertrend(candles, period = 10, multiplier = 3.0) {
  const a = atr(candles, period);
  const n = candles.length;
  const finalUb = new Array(n), finalLb = new Array(n);
  const dir = new Array(n).fill(1), st = new Array(n).fill(0);

  for (let i = 0; i < n; i++) {
    const hl2 = (candles[i].h + candles[i].l) / 2;
    const ub = hl2 + multiplier * a[i];
    const lb = hl2 - multiplier * a[i];
    if (i === 0) {
      finalUb[i] = ub; finalLb[i] = lb; st[i] = ub;
      continue;
    }
    finalUb[i] = ub < finalUb[i - 1] || candles[i - 1].c > finalUb[i - 1] ? ub : finalUb[i - 1];
    finalLb[i] = lb > finalLb[i - 1] || candles[i - 1].c < finalLb[i - 1] ? lb : finalLb[i - 1];
    if (st[i - 1] === finalUb[i - 1]) dir[i] = candles[i].c <= finalUb[i] ? -1 : 1;
    else dir[i] = candles[i].c >= finalLb[i] ? 1 : -1;
    st[i] = dir[i] === 1 ? finalLb[i] : finalUb[i];
  }
  return { supertrend: st, direction: dir };
}

// anchor: 'D' günlük, 'W' haftalık (pazartesi 00:00 UTC)
export function anchoredVwap(candles, anchor = 'D') {
  const out = new Array(candles.length);
  let key = null, cumTpv = 0, cumVol = 0;
  for (let i = 0; i < candles.length; i++) {
    const d = new Date(candles[i].t);
    let k;
    if (anchor === 'D') {
      k = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
    } else {
      const day = (d.getUTCDay() + 6) % 7; // pazartesi = 0
      k = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - day);
    }
    if (k !== key) { key = k; cumTpv = 0; cumVol = 0; }
    const tp = (candles[i].h + candles[i].l + candles[i].c) / 3;
    cumTpv += tp * candles[i].v;
    cumVol += candles[i].v;
    out[i] = cumVol ? cumTpv / cumVol : candles[i].c;
  }
  return out;
}

// Fraktal pivotlar: solunda ve sağında `lookback` mum bulunan tepe/dipler
export function swingPoints(candles, lookback = 3) {
  const n = candles.length;
  const isHigh = new Array(n).fill(false);
  const isLow = new Array(n).fill(false);
  for (let i = lookback; i < n - lookback; i++) {
    let hi = true, lo = true;
    for (let j = i - lookback; j <= i + lookback; j++) {
      if (j === i) continue;
      if (candles[j].h >= candles[i].h) hi = false;
      if (candles[j].l <= candles[i].l) lo = false;
    }
    isHigh[i] = hi;
    isLow[i] = lo;
  }
  return { isHigh, isLow };
}

export function marketStructure(candles, lookback = 3) {
  const sw = swingPoints(candles, lookback);
  const points = [];
  for (let i = 0; i < candles.length; i++) {
    if (sw.isHigh[i]) points.push({ idx: i, type: 'high', price: candles[i].h, time: candles[i].t });
    else if (sw.isLow[i]) points.push({ idx: i, type: 'low', price: candles[i].l, time: candles[i].t });
  }

  const labeled = [];
  let lastHigh = null, lastLow = null;
  for (const p of points) {
    let label = null;
    if (p.type === 'high') {
      if (lastHigh != null) label = p.price > lastHigh ? 'HH' : 'LH';
      lastHigh = p.price;
    } else {
      if (lastLow != null) label = p.price > lastLow ? 'HL' : 'LL';
      lastLow = p.price;
    }
    if (label) labeled.push({ ...p, label });
  }

  const recent = labeled.slice(-4).map((p) => p.label);
  const last2 = recent.slice(-2).join(',');
  let state;
  if (last2 === 'HH,HL' || last2 === 'HL,HH') state = 'BULLISH';
  else if (last2 === 'LL,LH' || last2 === 'LH,LL') state = 'BEARISH';
  else if (recent.length && ['HH', 'HL'].includes(recent[recent.length - 1])) state = 'BULLISH';
  else if (recent.length && ['LL', 'LH'].includes(recent[recent.length - 1])) state = 'BEARISH';
  else state = 'RANGE';

  return { points: labeled, state, recentLabels: recent, lastSwingHigh: lastHigh, lastSwingLow: lastLow, swings: sw };
}

// Bir mum dizisine tüm temel göstergeleri ekler
export function enrich(candles, cfg) {
  const closes = candles.map((c) => c.c);
  const out = { candles, closes };
  out.ema = {};
  for (const p of cfg.emaPeriods) out.ema[p] = ema(closes, p);
  out.rsi = rsi(closes, cfg.rsiPeriod);
  const m = macd(closes, cfg.macd.fast, cfg.macd.slow, cfg.macd.signal);
  out.macd = m.macd; out.macdSignal = m.signal; out.macdHist = m.hist;
  out.atr = atr(candles, cfg.atrPeriod);
  const a = adx(candles, cfg.adxPeriod);
  out.adx = a.adx; out.plusDi = a.plusDi; out.minusDi = a.minusDi;
  const st = supertrend(candles, cfg.supertrend.period, cfg.supertrend.multiplier);
  out.supertrend = st.supertrend; out.stDir = st.direction;
  out.vwapD = anchoredVwap(candles, 'D');
  out.vwapW = anchoredVwap(candles, 'W');
  out.volMa20 = sma(candles.map((c) => c.v), 20);
  return out;
}
