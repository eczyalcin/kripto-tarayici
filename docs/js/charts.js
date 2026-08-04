// Bağımlılıksız SVG grafikler — harici kütüphane yok, telefonda hızlı çalışır.

const NS = 'http://www.w3.org/2000/svg';
const esc = (s) => String(s).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));

function svgWrap(w, h, inner, cls = '') {
  return `<svg class="chart ${cls}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" xmlns="${NS}">${inner}</svg>`;
}

function scale(vals, size, pad = 0) {
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  return {
    min, max, span,
    to: (v) => size - pad - ((v - min) / span) * (size - pad * 2),
  };
}

// ---------------------------------------------------------------- çizgi grafik
export function lineChart(points, { w = 700, h = 180, color = '#4fc3f7', fill = true, zeroLine = false, label = '' } = {}) {
  if (!points || points.length < 2) return '<div class="empty">Grafik için yeterli veri yok</div>';
  const vals = points.map((p) => p.y);
  const ys = scale(zeroLine ? [...vals, 0] : vals, h, 12);
  const stepX = w / (points.length - 1);
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${(i * stepX).toFixed(1)},${ys.to(p.y).toFixed(1)}`).join('');
  const area = fill ? `<path d="${d}L${w},${h}L0,${h}Z" fill="${color}" opacity="0.13"/>` : '';
  const zero = zeroLine && ys.min < 0 && ys.max > 0
    ? `<line x1="0" y1="${ys.to(0).toFixed(1)}" x2="${w}" y2="${ys.to(0).toFixed(1)}" stroke="currentColor" opacity="0.25" stroke-dasharray="4 4"/>` : '';
  const lbl = label ? `<text x="6" y="14" class="chart-label">${esc(label)}</text>` : '';
  return svgWrap(w, h, `${area}${zero}<path d="${d}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/>${lbl}`);
}

// ------------------------------------------------------------ çoklu çizgi
export function multiLineChart(series, { w = 700, h = 200, zeroLine = true } = {}) {
  const valid = series.filter((s) => s.points?.length > 1);
  if (!valid.length) return '<div class="empty">Grafik için yeterli veri yok</div>';
  const all = valid.flatMap((s) => s.points.map((p) => p.y));
  const ys = scale(zeroLine ? [...all, 0] : all, h, 12);
  let inner = '';
  if (zeroLine && ys.min < 0 && ys.max > 0) {
    inner += `<line x1="0" y1="${ys.to(0).toFixed(1)}" x2="${w}" y2="${ys.to(0).toFixed(1)}" stroke="currentColor" opacity="0.25" stroke-dasharray="4 4"/>`;
  }
  for (const s of valid) {
    const stepX = w / (s.points.length - 1);
    const d = s.points.map((p, i) => `${i ? 'L' : 'M'}${(i * stepX).toFixed(1)},${ys.to(p.y).toFixed(1)}`).join('');
    inner += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
  }
  return svgWrap(w, h, inner);
}

// ----------------------------------------------------------------- mum grafik
export function candleChart(candles, opts = {}) {
  const { w = 700, h = 300, emaLines = [], zones = [], vwap = null } = opts;
  if (!candles?.length) return '<div class="empty">Mum verisi yok</div>';
  const lows = candles.map((c) => c.l), highs = candles.map((c) => c.h);
  const extra = [...emaLines.flatMap((e) => e.values.filter(isFinite)), ...(vwap || []).filter(isFinite)];
  const ys = scale([...lows, ...highs, ...extra], h, 10);
  const cw = w / candles.length;
  const bodyW = Math.max(cw * 0.62, 0.8);

  let inner = '';
  for (const z of zones) {
    const y1 = ys.to(z.top), y2 = ys.to(z.bottom);
    inner += `<rect x="0" y="${Math.min(y1, y2).toFixed(1)}" width="${w}" height="${Math.abs(y2 - y1).toFixed(1)}" fill="${z.color}" opacity="0.13"/>`;
  }
  candles.forEach((c, i) => {
    const x = i * cw + cw / 2;
    const up = c.c >= c.o;
    const col = up ? '#26a65b' : '#e04b4b';
    const yo = ys.to(c.o), yc = ys.to(c.c);
    inner += `<line x1="${x.toFixed(1)}" y1="${ys.to(c.h).toFixed(1)}" x2="${x.toFixed(1)}" y2="${ys.to(c.l).toFixed(1)}" stroke="${col}" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
    inner += `<rect x="${(x - bodyW / 2).toFixed(1)}" y="${Math.min(yo, yc).toFixed(1)}" width="${bodyW.toFixed(1)}" height="${Math.max(Math.abs(yc - yo), 0.6).toFixed(1)}" fill="${col}"/>`;
  });
  for (const e of emaLines) {
    const d = e.values.map((v, i) => (isFinite(v) ? `${i ? 'L' : 'M'}${(i * cw + cw / 2).toFixed(1)},${ys.to(v).toFixed(1)}` : '')).join('');
    inner += `<path d="${d}" fill="none" stroke="${e.color}" stroke-width="1.4" vector-effect="non-scaling-stroke" opacity="0.9"/>`;
  }
  if (vwap) {
    const d = vwap.map((v, i) => (isFinite(v) ? `${i ? 'L' : 'M'}${(i * cw + cw / 2).toFixed(1)},${ys.to(v).toFixed(1)}` : '')).join('');
    inner += `<path d="${d}" fill="none" stroke="#26c6da" stroke-width="1.4" stroke-dasharray="5 4" vector-effect="non-scaling-stroke"/>`;
  }
  return svgWrap(w, h, inner, 'candles');
}

// ------------------------------------------------------------- yatay bar
export function hBarChart(items, { w = 700, rowH = 30, showValue = true } = {}) {
  if (!items?.length) return '<div class="empty">Veri yok</div>';
  const h = items.length * rowH + 6;
  const maxAbs = Math.max(...items.map((i) => Math.abs(i.max ?? i.value)), 1);
  const midX = w * 0.42;
  let inner = `<line x1="${midX}" y1="0" x2="${midX}" y2="${h}" stroke="currentColor" opacity="0.2"/>`;

  items.forEach((it, i) => {
    const y = i * rowH + 4;
    const half = w - midX - 60;
    const len = (Math.abs(it.value) / maxAbs) * half;
    const pos = it.value >= 0;
    const x = pos ? midX : midX - len;
    inner += `<text x="${midX - 8}" y="${y + rowH * 0.55}" text-anchor="end" class="bar-label">${esc(it.label)}</text>`;
    inner += `<rect x="${x.toFixed(1)}" y="${y + 4}" width="${Math.max(len, 1).toFixed(1)}" height="${rowH - 12}" rx="2" fill="${it.color || (pos ? '#26a65b' : '#e04b4b')}"/>`;
    if (showValue) {
      inner += `<text x="${(pos ? midX + len + 6 : midX + 6).toFixed(1)}" y="${y + rowH * 0.55}" class="bar-value">${esc(it.text ?? it.value.toFixed(1))}</text>`;
    }
  });
  return svgWrap(w, h, inner, 'hbar');
}

// ------------------------------------------------------------- dikey bar
export function barChart(values, { w = 700, h = 150, colors = null } = {}) {
  if (!values?.length) return '<div class="empty">Veri yok</div>';
  const ys = scale([...values, 0], h, 8);
  const bw = w / values.length;
  let inner = `<line x1="0" y1="${ys.to(0).toFixed(1)}" x2="${w}" y2="${ys.to(0).toFixed(1)}" stroke="currentColor" opacity="0.25"/>`;
  values.forEach((v, i) => {
    const y0 = ys.to(0), y1 = ys.to(v);
    const col = colors ? colors[i] : v >= 0 ? '#26a65b' : '#e04b4b';
    inner += `<rect x="${(i * bw + bw * 0.15).toFixed(1)}" y="${Math.min(y0, y1).toFixed(1)}" width="${(bw * 0.7).toFixed(1)}" height="${Math.max(Math.abs(y1 - y0), 1).toFixed(1)}" fill="${col}"/>`;
  });
  return svgWrap(w, h, inner);
}

// ---------------------------------------------------------- derinlik grafiği
export function depthChart(bids, asks, { w = 700, h = 200 } = {}) {
  if (!bids?.length || !asks?.length) return '<div class="empty">Order book verisi yok</div>';
  let cb = 0, ca = 0;
  const bidPts = bids.map(([p, q]) => { cb += p * q; return { x: p, y: cb }; });
  const askPts = asks.map(([p, q]) => { ca += p * q; return { x: p, y: ca }; });
  const xs = [...bidPts, ...askPts].map((p) => p.x);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const spanX = maxX - minX || 1;
  const maxY = Math.max(cb, ca) || 1;
  const X = (v) => ((v - minX) / spanX) * w;
  const Y = (v) => h - (v / maxY) * (h - 10);

  const bd = bidPts.map((p, i) => `${i ? 'L' : 'M'}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join('');
  const ad = askPts.map((p, i) => `${i ? 'L' : 'M'}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join('');
  const bidFill = `${bd}L${X(bidPts[bidPts.length - 1].x).toFixed(1)},${h}L${X(bidPts[0].x).toFixed(1)},${h}Z`;
  const askFill = `${ad}L${X(askPts[askPts.length - 1].x).toFixed(1)},${h}L${X(askPts[0].x).toFixed(1)},${h}Z`;

  return svgWrap(w, h,
    `<path d="${bidFill}" fill="#26a65b" opacity="0.22"/><path d="${bd}" fill="none" stroke="#26a65b" stroke-width="2" vector-effect="non-scaling-stroke"/>` +
    `<path d="${askFill}" fill="#e04b4b" opacity="0.22"/><path d="${ad}" fill="none" stroke="#e04b4b" stroke-width="2" vector-effect="non-scaling-stroke"/>`);
}

// -------------------------------------------------------------- skor göstergesi
export function gauge(longScore, { w = 260, h = 130 } = {}) {
  const cx = w / 2, cy = h - 10, r = Math.min(w / 2 - 12, h - 24);
  const ang = Math.PI * (1 - longScore / 100);
  const px = cx + r * Math.cos(ang), py = cy - r * Math.sin(ang);
  const arc = (from, to, color) => {
    const a1 = Math.PI * (1 - from / 100), a2 = Math.PI * (1 - to / 100);
    const x1 = cx + r * Math.cos(a1), y1 = cy - r * Math.sin(a1);
    const x2 = cx + r * Math.cos(a2), y2 = cy - r * Math.sin(a2);
    return `<path d="M${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 0 1 ${x2.toFixed(1)},${y2.toFixed(1)}" fill="none" stroke="${color}" stroke-width="12" stroke-linecap="butt"/>`;
  };
  return svgWrap(w, h,
    arc(0, 38, '#e04b4b') + arc(38, 45, '#ef8c3f') + arc(45, 55, '#d8b430') +
    arc(55, 62, '#8bc34a') + arc(62, 100, '#26a65b') +
    `<line x1="${cx}" y1="${cy}" x2="${px.toFixed(1)}" y2="${py.toFixed(1)}" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>` +
    `<circle cx="${cx}" cy="${cy}" r="5" fill="currentColor"/>`, 'gauge');
}
