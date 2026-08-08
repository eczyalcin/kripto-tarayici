// Arayüz — Python sürümündeki dashboard/app.py karşılığı.

import * as charts from './charts.js';
import { DEFAULTS, loadConfig, resetConfig, saveConfig } from './config.js';
import { pickCandidates, scanMarket, scanSymbol, screenMarket } from './scan.js';
import * as store from './store.js';
import { fmt, fmtPrice, fmtUsd, signed, timeAgo } from './util.js';

let cfg = loadConfig();
let snap = null;
let busy = false;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
const decClass = (d) => 'd-' + String(d).toLowerCase().replace('nötr', 'notr').replace(/\s+/g, '-');
const tone = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : 'flat');

// ===========================================================================
// Genel iskelet
// ===========================================================================
function setBusy(on, text = '') {
  busy = on;
  $('scanBtn').disabled = on;
  $('progress').classList.toggle('hidden', !on);
  if (text) $('progressText').textContent = text;
}

function showError(msg) {
  const box = $('errorBox');
  box.innerHTML = `<b>Bir sorun oluştu</b><br>${esc(msg)}`;
  box.classList.remove('hidden');
  setTimeout(() => box.classList.add('hidden'), 12000);
}

function fillSymbols() {
  const sel = $('symbolSelect');
  sel.innerHTML = cfg.symbols.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
  const saved = localStorage.getItem('kripto.lastSymbol');
  sel.value = cfg.symbols.includes(saved) ? saved : cfg.primarySymbol;
}

// headers: [{ label, num, m }] — m:false olan sütunlar telefonda gizlenir,
// böylece tablolar yatay kaydırma gerektirmeden ekrana sığar.
function table(headers, rows, opts = {}) {
  if (!rows.length) return `<div class="empty">${esc(opts.empty || 'Kayıt yok')}</div>`;
  const cls = (h, extra = '') =>
    [h.num ? 'num' : '', h.m === false ? 'hide-m' : '', extra].filter(Boolean).join(' ');
  const th = headers.map((h) => `<th class="${cls(h)}">${esc(h.label)}</th>`).join('');
  const tb = rows.map((r) => {
    const tds = r.cells.map((c, i) =>
      `<td class="${cls(headers[i] || {}, c.wrap ? 'wrap' : '')}">${c.html ?? esc(c.text ?? c)}</td>`).join('');
    return `<tr class="${r.click ? 'clickable' : ''}" ${r.click ? `data-click="${esc(r.click)}"` : ''}>${tds}</tr>`;
  }).join('');
  return `<div class="tbl-wrap"><table><thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table></div>`;
}

// ===========================================================================
// Başlık + KPI
// ===========================================================================
function renderHeadline() {
  const el = $('headline');
  if (!snap) return;
  const s = snap.score;
  el.className = 'headline';
  el.style.borderLeftColor = getComputedStyle(document.documentElement)
    .getPropertyValue(s.longScore >= 55 ? '--green' : s.longScore <= 45 ? '--red' : '--yellow');
  el.innerHTML = `
    <h2>${esc(snap.symbol)} · ${fmtPrice(snap.price)}</h2>
    <div class="decision ${decClass(s.decision)}">${esc(s.decision)} —
      Long ${s.longScore.toFixed(1)}/100 · Short ${s.shortScore.toFixed(1)}/100 ·
      güven %${s.confidence.toFixed(0)}</div>
    <p class="answer">${esc(s.answer)}</p>`;
  $('lastScan').textContent = `${snap.symbol} · ${timeAgo(snap.timestamp)}`;
}

function renderKpis() {
  if (!snap) return;
  const oi = snap.derivatives.openInterest || {};
  const f = snap.derivatives.funding || {};
  const flow = snap.orderFlow, w = snap.whale;
  const items = [
    ['Open Interest (1s)', `%${fmt(oi.change1hPct)}`, oi.interpretation1h?.state || '—', 'flat'],
    ['Funding', `%${fmt(f.currentPct, 4)}`, f.health || '—', 'flat'],
    ['Vadeli CVD', fmtUsd(flow.futures?.delta), flow.label || '—', tone(flow.futures?.delta)],
    ['Spot CVD', flow.spot?.available ? fmtUsd(flow.spot.delta) : '—', flow.divergence || '—', tone(flow.spot?.delta)],
    ['Balina deltası', fmtUsd(w.totalWhaleDeltaUsdt), w.state || '—', tone(w.totalWhaleDeltaUsdt)],
    ['Risk', snap.risk.level, `${snap.risk.points} risk puanı`, 'flat'],
  ];
  $('kpis').innerHTML = items.map(([l, v, s, t]) =>
    `<div class="kpi"><div class="l">${esc(l)}</div><div class="v">${esc(v)}</div>
     <div class="s ${t}">${esc(s)}</div></div>`).join('');
}

// ===========================================================================
// 1) KARAR
// ===========================================================================
function renderKarar() {
  const el = $('tab-karar');
  if (!snap) { el.innerHTML = '<div class="card"><div class="empty">Önce bir tarama yapın.</div></div>'; return; }
  const s = snap.score, setup = snap.setup, risk = snap.risk;

  // Telefonda yatay kaydırma olmasın diye tablo yerine dikey liste:
  // her gösterge kendi satırında, mini çubuk + açıklama alt alta.
  const compList = s.components.map((c) => {
    const pct = Math.min(Math.abs(c.points) / c.maxPoints, 1) * 100;
    const col = !c.available ? '#5b6675' : c.points > 0 ? 'var(--green)' : c.points < 0 ? 'var(--red)' : '#8892a4';
    return `<div class="comp">
      <div class="comp-top">
        <span class="comp-name">${esc(c.name)}</span>
        <span class="comp-pts ${tone(c.points)}">${signed(c.points, 1)}<span class="comp-max"> / ${c.maxPoints}</span></span>
      </div>
      <div class="comp-bar ${c.points < 0 ? 'neg' : ''}"><i style="width:${pct.toFixed(0)}%;background:${col}"></i></div>
      <div class="comp-detail">${esc(c.available ? c.detail : 'veri yok')}</div>
    </div>`;
  }).join('');

  let setupHtml;
  if (setup.available) {
    const rows = [
      ['Yön', `<span class="${setup.direction === 'LONG' ? 'up' : 'down'}"><b>${setup.direction}</b></span>`],
      ['Olasılık', `<b>%${setup.probability.toFixed(1)}</b>`],
      ['Giriş bölgesi', `<b>${fmtPrice(setup.entryZone[0])} – ${fmtPrice(setup.entryZone[1])}</b>`],
      ['Giriş', `<b>${fmtPrice(setup.entry)}</b>`],
      ['Stop', `<b>${fmtPrice(setup.stop)}</b> <span class="muted">(%${fmt(setup.stopDistancePct)})</span>`],
      ...setup.targets.map((t) => [t.name, `<b>${fmtPrice(t.price)}</b> <span class="muted">(${t.rMultiple}R, %${signed(t.gainPct)})</span>`]),
      ['R/R', `<b>${setup.riskReward}</b>${setup.rrOk ? '' : ' <span class="badge red">düşük</span>'}`],
      ['Pozisyon', `<b>${fmt(setup.position.qty, 4)}</b> <span class="muted">(~${fmtUsd(setup.position.notionalUsdt)} USDT)</span>`],
      ['Maks kaldıraç', `<b>${setup.position.suggestedMaxLeverage}x</b>`],
      ['Giriş dayanağı', `<span class="muted">${esc(setup.entryBasis)}</span>`],
      ['Stop dayanağı', `<span class="muted">${esc(setup.stopBasis)}</span>`],
    ];
    setupHtml = rows.map(([k, v]) => `<div class="setup-row"><span class="muted">${esc(k)}</span><span>${v}</span></div>`).join('') +
      `<div class="note"><b>Geçersizlik:</b> ${esc(setup.invalidation.join('; '))}</div>`;
  } else {
    setupHtml = `<div class="empty">${esc(setup.reason)}</div>`;
  }

  const hist = store.scanHistory(snap.symbol);
  const histHtml = hist.length > 1
    ? charts.multiLineChart([{ points: hist.map((h, i) => ({ x: i, y: h.longScore })), color: '#26a65b' }], { h: 150, zeroLine: false }) +
      `<div class="legend"><span><i style="background:#26a65b"></i>Long skoru (son ${hist.length} tarama)</span></div>`
    : '<div class="empty">Skor geçmişi için en az iki tarama gerekiyor.</div>';

  el.innerHTML = `
    <div class="grid2">
      <div class="card">
        <h3>Skor Dağılımı</h3>
        ${charts.gauge(s.longScore)}
        <div class="note" style="text-align:center">Long ${s.longScore.toFixed(1)} · kapsama %${s.coveragePct.toFixed(0)} · uzlaşma %${s.agreementPct.toFixed(0)}</div>
      </div>
      <div class="card">
        <h3>AI Trade Setup</h3>
        ${setupHtml}
      </div>
    </div>
    <div class="card">
      <h3>Gösterge Detayları</h3>
      <div class="comp-list">${compList}</div>
      <div class="comp-total">
        <span>Toplam</span>
        <span class="${tone(s.totalPoints)}">${signed(s.totalPoints, 1)} / ${s.totalWeight}</span>
      </div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Risk Faktörleri</h3>
        <div class="comp-list">
          ${risk.factors.map((f) => `<div class="comp">
            <div class="comp-top"><span class="comp-name">${esc(f.factor)}</span>
              <span class="comp-pts ${f.points >= 2 ? 'down' : f.points >= 1 ? 'flat' : 'up'}">${esc(f.state)}</span></div>
            <div class="comp-detail">${esc(f.value)}${f.note ? ' · ' + esc(f.note) : ''}</div>
          </div>`).join('') || '<div class="empty">Risk faktörü yok</div>'}
        </div>
        <div class="note">${esc(risk.summary)}</div>
      </div>
      <div class="card"><h3>Skor Geçmişi</h3>${histHtml}</div>
    </div>`;
}

// ===========================================================================
// 2) TREND
// ===========================================================================
function renderTrend() {
  const el = $('tab-trend');
  if (!snap) { el.innerHTML = '<div class="card"><div class="empty">Önce bir tarama yapın.</div></div>'; return; }
  const t = snap.trend;
  const names = { ltf: cfg.timeframes.ltf, mtf: cfg.timeframes.mtf, htf: cfg.timeframes.htf };

  const rows = Object.entries(names).filter(([k]) => t.timeframes[k]?.available).map(([k, name]) => {
    const tf = t.timeframes[k];
    return {
      cells: [name, tf.label, tf.emaAlignment,
        `${tf.adx.value.toFixed(1)} (${tf.adx.strength})`,
        tf.supertrend.direction + (tf.supertrend.flipped ? ' ⚡' : ''),
        tf.structure.state, (tf.structure.recentLabels || []).join(' → ') || '—',
        tf.rsi.toFixed(1), fmt(tf.atr.pct), fmt(tf.vwap.vsDaily), fmt(tf.vwap.vsWeekly)],
    };
  });

  // Uygulama kapatılıp açıldığında snapshot localStorage'dan gelir ve ham mumlar
  // içinde olmaz (kota nedeniyle saklanmıyor). Bu durumda mumları arka planda
  // yeniden çekip grafiği tamamlıyoruz — yeniden tarama gerekmesin.
  let chartHtml = '<div class="empty">Grafik yükleniyor...</div>';
  const candles = snap._candles?.mtf;
  const mtf = t.timeframes.mtf;
  if (!candles?.length || !mtf?._enriched) {
    if (!renderTrend._loading) {
      renderTrend._loading = true;
      loadCandlesForChart(snap.symbol).finally(() => { renderTrend._loading = false; });
    }
  }
  if (candles?.length && mtf?._enriched) {
    const view = candles.slice(-140);
    const off = candles.length - view.length;
    const e = mtf._enriched;
    const zones = [
      ...(snap.smartMoney.fvg?.open || []).slice(0, 5).map((f) => ({ top: f.top, bottom: f.bottom, color: f.direction === 'bullish' ? '#26a65b' : '#e04b4b' })),
      ...(snap.smartMoney.orderBlocks?.fresh || []).slice(0, 4).map((o) => ({ top: o.top, bottom: o.bottom, color: o.direction === 'bullish' ? '#4fc3f7' : '#ef8c3f' })),
    ];
    chartHtml = charts.candleChart(view, {
      h: 300, zones,
      emaLines: [
        { values: e.ema[20].slice(off), color: '#4fc3f7' },
        { values: e.ema[50].slice(off), color: '#ab47bc' },
        { values: e.ema[200].slice(off), color: '#ef5350' },
      ],
      vwap: e.vwapD.slice(off),
    }) + `<div class="legend">
      <span><i style="background:#4fc3f7"></i>EMA20</span>
      <span><i style="background:#ab47bc"></i>EMA50</span>
      <span><i style="background:#ef5350"></i>EMA200</span>
      <span><i style="background:#26c6da"></i>Günlük VWAP</span>
      <span><i style="background:#26a65b"></i>Bullish FVG</span>
      <span><i style="background:#e04b4b"></i>Bearish FVG</span></div>`;
  }

  const pts = mtf?.structure?.points || [];
  el.innerHTML = `
    <div class="card"><h3>Zaman Dilimleri</h3>
      ${table([{ label: 'TF' }, { label: 'Yön' }, { label: 'EMA dizilimi', m: false }, { label: 'ADX', m: false },
               { label: 'SuperTrend', m: false }, { label: 'Yapı' }, { label: 'Son etiketler', m: false },
               { label: 'RSI', num: true }, { label: 'ATR %', num: true, m: false },
               { label: 'VWAP-D %', num: true }, { label: 'VWAP-W %', num: true, m: false }], rows)}
      <div class="note">${esc(t.summary)}</div>
    </div>
    <div class="card"><h3>${esc(names.mtf)} Grafiği</h3>${chartHtml}</div>
    <div class="card"><h3>Market Structure (HH / HL / LH / LL)</h3>
      ${table([{ label: 'Zaman' }, { label: 'Tip', m: false }, { label: 'Fiyat', num: true }, { label: 'Etiket' }],
        pts.slice().reverse().map((p) => ({
          cells: [new Date(p.time).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' }),
            p.type === 'high' ? 'tepe' : 'dip', fmtPrice(p.price),
            { html: `<span class="badge ${['HH', 'HL'].includes(p.label) ? 'green' : 'red'}">${p.label}</span>` }],
        })), { empty: 'Swing noktası bulunamadı' })}
    </div>`;
}

// Önbellekten okunan snapshot için mumları tamamlar (grafik çizilebilsin diye)
async function loadCandlesForChart(symbol) {
  try {
    const [{ klines }, { analyzeTimeframe }] = await Promise.all([
      import('./binance.js'), import('./engines.js'),
    ]);
    const c = await klines(symbol, cfg.timeframes.mtf, cfg.timeframes.klinesLimit);
    if (!snap || snap.symbol !== symbol) return;
    snap._candles = { ...(snap._candles || {}), mtf: c };
    snap.trend.timeframes.mtf = { ...snap.trend.timeframes.mtf, ...analyzeTimeframe(c, cfg.trend) };
    renderTrend();
  } catch (e) {
    const el = $('tab-trend').querySelector('.empty');
    if (el) el.textContent = 'Grafik yüklenemedi: ' + (e.message || e);
  }
}

// ===========================================================================
// 3) SMART MONEY
// ===========================================================================
function renderSmart() {
  const el = $('tab-smart');
  if (!snap) { el.innerHTML = '<div class="card"><div class="empty">Önce bir tarama yapın.</div></div>'; return; }
  const sm = snap.smartMoney;
  if (!sm.available) { el.innerHTML = '<div class="card"><div class="empty">Smart money verisi yok.</div></div>'; return; }

  const sweeps = (sm.liquiditySweeps || []).slice().reverse().map((s) => ({
    cells: [{ html: `<span class="badge ${s.direction === 'bullish' ? 'green' : 'red'}">${s.type}</span>` },
      fmtPrice(s.sweptLevel), fmt(s.wickRatio, 2),
      s.volumeRatio ? `x${fmt(s.volumeRatio, 2)}` : '—',
      s.volumeConfirmed ? 'evet' : 'hayır', `${s.barsAgo} mum`],
  }));

  const breaks = (sm.structureBreaks || []).slice().reverse().map((b) => ({
    cells: [{ html: `<span class="badge ${b.direction === 'bullish' ? 'green' : 'red'}">${b.type}</span>` },
      b.direction === 'bullish' ? 'yukarı' : 'aşağı', fmtPrice(b.brokenLevel), `${b.barsAgo} mum`],
  }));

  const fvgs = (sm.fvg?.open || []).map((f) => ({
    cells: [{ html: `<span class="badge ${f.direction === 'bullish' ? 'green' : 'red'}">${f.type}</span>` },
      fmtPrice(f.bottom), fmtPrice(f.top), fmt(f.sizeAtr, 2), signed(f.distancePct),
      f.mitigated ? 'dokunuldu' : 'temiz', `${f.barsAgo} mum`],
  }));

  const obs = (sm.orderBlocks?.fresh || []).map((o) => ({
    cells: [{ html: `<span class="badge ${o.direction === 'bullish' ? 'green' : 'red'}">${o.type}</span>` },
      fmtPrice(o.bottom), fmtPrice(o.top), `${fmt(o.displacementAtr, 2)}x`, signed(o.distancePct), `${o.barsAgo} mum`],
  }));

  el.innerHTML = `
    <div class="card"><h3>Özet</h3><p>${esc(sm.summary)}</p>
      <div class="note">Skor: ${signed(sm.score, 2)} · ${esc(sm.label)}</div></div>
    <div class="grid2">
      <div class="card"><h3>Likidite Süpürmeleri</h3>
        ${table([{ label: 'Tip' }, { label: 'Süpürülen', num: true }, { label: 'Fitil', num: true, m: false },
                 { label: 'Hacim', num: true, m: false }, { label: 'Teyit', m: false }, { label: 'Ne zaman' }], sweeps,
                { empty: 'Tespit edilen süpürme yok' })}</div>
      <div class="card"><h3>Yapı Kırılımları (BOS / CHOCH)</h3>
        ${table([{ label: 'Tip' }, { label: 'Yön', m: false }, { label: 'Kırılan', num: true }, { label: 'Ne zaman' }], breaks,
                { empty: 'Kırılım yok' })}</div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Açık Fair Value Gap</h3>
        ${table([{ label: 'Tip' }, { label: 'Alt', num: true }, { label: 'Üst', num: true },
                 { label: 'Boyut(ATR)', num: true, m: false }, { label: 'Uzaklık %', num: true },
                 { label: 'Durum', m: false }, { label: 'Ne zaman', m: false }], fvgs, { empty: 'Açık FVG yok' })}</div>
      <div class="card"><h3>Taze Order Block</h3>
        ${table([{ label: 'Tip' }, { label: 'Alt', num: true }, { label: 'Üst', num: true },
                 { label: 'Hareket', num: true, m: false }, { label: 'Uzaklık %', num: true }, { label: 'Ne zaman', m: false }], obs,
                { empty: 'Taze order block yok' })}</div>
    </div>`;
}

// ===========================================================================
// 4) TÜREV
// ===========================================================================
function renderTurev() {
  const el = $('tab-turev');
  if (!snap) { el.innerHTML = '<div class="card"><div class="empty">Önce bir tarama yapın.</div></div>'; return; }
  const d = snap.derivatives;
  const oi = d.openInterest, f = d.funding, ls = d.longShort, tk = d.taker, b = d.basis;

  const oiSeries = (oi.series || []).slice(-96).map((p, i) => ({ x: i, y: p.oiUsd }));
  const fundBars = (f.history || []).slice(-24).map((h) => h.rate * 100);
  const lsSeries = (ls.series || []).map((p, i) => ({ x: i, y: p.ratio }));

  el.innerHTML = `
    <div class="grid2">
      <div class="card"><h3>Open Interest</h3>
        ${oiSeries.length > 1 ? charts.lineChart(oiSeries, { h: 160, color: '#4fc3f7', zeroLine: false, label: 'OI (USDT) — son 8 saat' }) : '<div class="empty">OI serisi yok</div>'}
        <dl class="kv">
          <dt>Şu an</dt><dd>${fmtUsd(oi.currentUsd)} USDT</dd>
          <dt>1 saat</dt><dd class="${tone(oi.change1hPct)}">%${fmt(oi.change1hPct)}</dd>
          <dt>4 saat</dt><dd class="${tone(oi.change4hPct)}">%${fmt(oi.change4hPct)}</dd>
          <dt>24 saat</dt><dd class="${tone(oi.change24hPct)}">%${fmt(oi.change24hPct)}</dd>
          <dt>Fiyat 1s</dt><dd class="${tone(oi.priceChange1hPct)}">%${fmt(oi.priceChange1hPct)}</dd>
        </dl>
        <div class="note"><b>${esc(oi.interpretation1h?.state)}</b> — ${esc(oi.interpretation1h?.meaning)}</div>
      </div>
      <div class="card"><h3>Funding</h3>
        ${fundBars.length ? charts.barChart(fundBars, { h: 150 }) : '<div class="empty">Funding geçmişi yok</div>'}
        <dl class="kv">
          <dt>Şu an</dt><dd class="${tone(f.currentPct)}">%${fmt(f.currentPct, 4)}</dd>
          <dt>Ortalama</dt><dd>%${fmt(f.avgPct, 4)}</dd>
          <dt>Tahmini</dt><dd>%${fmt(f.predictedPct, 4)}</dd>
          <dt>Yıllık</dt><dd>%${fmt(f.annualizedPct, 1)}</dd>
          <dt>Durum</dt><dd>${esc(f.health)} · ${esc(f.trend)}</dd>
        </dl>
        <div class="note">${esc(f.bias)}</div>
      </div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Long / Short Oranları</h3>
        ${lsSeries.length > 1 ? charts.lineChart(lsSeries, { h: 140, color: '#ab47bc', zeroLine: false, label: 'Büyük hesap L/S' }) : ''}
        <dl class="kv">
          <dt>Büyük hesap (pozisyon)</dt><dd>${fmt(ls.topPositionsRatio)}</dd>
          <dt>Büyük hesap (hesap)</dt><dd>${fmt(ls.topAccountsRatio)}</dd>
          <dt>Global hesap</dt><dd>${fmt(ls.globalAccountsRatio)}</dd>
          <dt>6 bar değişim</dt><dd class="${tone(ls.topPositionsDeltaPct)}">%${fmt(ls.topPositionsDeltaPct)}</dd>
        </dl>
        ${(ls.notes || []).map((n) => `<div class="note">• ${esc(n)}</div>`).join('')}
      </div>
      <div class="card"><h3>Taker Buy / Sell</h3>
        ${tk.available ? charts.barChart(tk.series.map((r) => r.buy - r.sell), { h: 140 }) : ''}
        ${tk.available ? `<dl class="kv">
          <dt>Alım hacmi</dt><dd>${fmtUsd(tk.buyVolume)}</dd>
          <dt>Satım hacmi</dt><dd>${fmtUsd(tk.sellVolume)}</dd>
          <dt>Delta</dt><dd class="${tone(tk.delta)}">${fmtUsd(tk.delta)}</dd>
          <dt>Dengesizlik</dt><dd class="${tone(tk.imbalancePct)}">%${fmt(tk.imbalancePct)}</dd>
          <dt>Durum</dt><dd>${esc(tk.state)}</dd></dl>` : '<div class="empty">Taker verisi yok</div>'}
      </div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Basis (Perpetual − Spot)</h3>
        ${b.available ? `<dl class="kv">
          <dt>Perp mark</dt><dd>${fmtPrice(b.perpMark)}</dd>
          <dt>Spot</dt><dd>${fmtPrice(b.spotPrice)}</dd>
          <dt>Fark</dt><dd class="${tone(b.basisPct)}">%${fmt(b.basisPct, 4)}</dd>
          <dt>Durum</dt><dd>${esc(b.state)}</dd></dl>` : '<div class="empty">Spot karşılığı bulunamadı</div>'}
      </div>
      <div class="card"><h3>Likidasyonlar</h3>
        <div class="empty">${esc(d.liquidations.note)}</div>
        <div class="note">Bu bileşen skorda "veri yok" sayılır ve güven oranını düşürür.
          Likidasyon geçmişi isteyen kullanıcılar Mac/Pi üzerindeki Python sürümünü
          <code>run.py collect</code> ile çalıştırabilir.</div>
      </div>
    </div>`;
}

// ===========================================================================
// 5) ORDER FLOW
// ===========================================================================
function renderAkis() {
  const el = $('tab-akis');
  if (!snap) { el.innerHTML = '<div class="card"><div class="empty">Önce bir tarama yapın.</div></div>'; return; }
  const flow = snap.orderFlow;
  const series = [];
  if (flow.futures?.series?.length > 1) series.push({ points: flow.futures.series.map((p, i) => ({ x: i, y: p.cvd })), color: '#4fc3f7' });
  if (flow.spot?.series?.length > 1) series.push({ points: flow.spot.series.map((p, i) => ({ x: i, y: p.cvd })), color: '#ef8c3f' });

  const rows = [];
  if (flow.futures?.available) rows.push({ cells: ['Vadeli', fmtUsd(flow.futures.buy), fmtUsd(flow.futures.sell), { html: `<span class="${tone(flow.futures.delta)}">${fmtUsd(flow.futures.delta)}</span>` }, `%${fmt(flow.futures.imbalancePct)}`, String(flow.futures.trades)] });
  if (flow.spot?.available) rows.push({ cells: ['Spot', fmtUsd(flow.spot.buy), fmtUsd(flow.spot.sell), { html: `<span class="${tone(flow.spot.delta)}">${fmtUsd(flow.spot.delta)}</span>` }, `%${fmt(flow.spot.imbalancePct)}`, String(flow.spot.trades)] });

  el.innerHTML = `
    <div class="card"><h3>Kümülatif Delta (CVD)</h3>
      ${series.length ? charts.multiLineChart(series, { h: 220 }) : '<div class="empty">Akış verisi yok</div>'}
      <div class="legend">
        <span><i style="background:#4fc3f7"></i>Vadeli CVD</span>
        ${flow.spot?.available ? '<span><i style="background:#ef8c3f"></i>Spot CVD</span>' : ''}
      </div>
      <div class="note">Pencere: son ${fmt(flow.futures?.windowMinutes, 0)} dakika · ${flow.futures?.trades ?? 0} vadeli işlem</div>
    </div>
    <div class="card"><h3>Agresif Alıcı / Satıcı</h3>
      ${table([{ label: 'Piyasa' }, { label: 'Alım', num: true }, { label: 'Satım', num: true },
               { label: 'Delta', num: true }, { label: 'Dengesizlik', num: true, m: false }, { label: 'İşlem', num: true, m: false }], rows)}
      <div class="note"><b>${esc(flow.divergence)}</b> — ${esc(flow.divergenceNote || 'Spot karşılığı olmadığı için karşılaştırma yapılamadı')}</div>
    </div>`;
}

// ===========================================================================
// 6) BALİNA & KİTAP
// ===========================================================================
function renderBalina() {
  const el = $('tab-balina');
  if (!snap) { el.innerHTML = '<div class="card"><div class="empty">Önce bir tarama yapın.</div></div>'; return; }
  const w = snap.whale, b = snap.orderbook;

  let tierHtml = '';
  for (const [key, name] of [['futures', 'Vadeli'], ['spot', 'Spot']]) {
    const m = w[key];
    if (!m?.available) continue;
    const rows = Object.entries(m.tiers).map(([label, v]) => ({
      cells: [label, fmtUsd(v.thresholdUsdt), String(v.count), fmtUsd(v.buyUsdt), fmtUsd(v.sellUsdt),
        { html: `<span class="${tone(v.deltaUsdt)}">${fmtUsd(v.deltaUsdt)}</span>` }],
    }));
    tierHtml += `<h4>${name} — ${m.state} (delta ${fmtUsd(m.whaleDeltaUsdt)} USDT)</h4>` +
      table([{ label: 'Dilim' }, { label: 'Eşik', num: true, m: false }, { label: 'İşlem', num: true },
             { label: 'Alım', num: true, m: false }, { label: 'Satım', num: true, m: false }, { label: 'Delta', num: true }], rows);
    if (m.tierScaling?.scaled) {
      tierHtml += `<div class="note">⚙️ Bu paritede tek işlem 100k USDT'yi nadiren aştığı için eşikler
        otomatik ölçeklendi (taban ≈ ${fmtUsd(m.tierScaling.base)} USDT).</div>`;
    }
  }

  const big = (w.futures?.largestTrades || []).slice(0, 10).map((t) => ({
    cells: [new Date(t.time).toLocaleTimeString('tr-TR'),
      { html: `<span class="${t.side === 'buy' ? 'up' : 'down'}">${t.side === 'buy' ? 'ALIM' : 'SATIM'}</span>` },
      fmtPrice(t.price), fmt(t.qty, 2), fmtUsd(t.notional)],
  }));

  const ice = [...(w.futures?.icebergs || []), ...(w.spot?.icebergs || [])].map((i) => ({
    cells: [fmt(i.qty, 2), i.side === 'buy' ? 'alım' : 'satım', String(i.repeats),
      fmtUsd(i.totalNotional), fmtPrice(i.avgPrice), `${fmt(i.spanSeconds, 0)} sn`],
  }));

  const wallRows = [...(b.bidWalls || []), ...(b.askWalls || [])].map((x) => ({
    cells: [{ html: `<span class="${x.side === 'bid' ? 'up' : 'down'}">${x.side === 'bid' ? 'BID' : 'ASK'}</span>` },
      fmtPrice(x.price), fmt(x.qty, 2), fmtUsd(x.notional), `x${fmt(x.xAverage, 1)}`, signed(x.distancePct)],
  }));

  el.innerHTML = `
    <div class="card"><h3>Balina Dilimleri</h3>${tierHtml || '<div class="empty">Balina verisi yok</div>'}</div>
    <div class="grid2">
      <div class="card"><h3>En Büyük İşlemler (vadeli)</h3>
        ${table([{ label: 'Saat' }, { label: 'Yön' }, { label: 'Fiyat', num: true },
                 { label: 'Miktar', num: true, m: false }, { label: 'USDT', num: true }], big)}</div>
      <div class="card"><h3>Iceberg Şüphesi</h3>
        ${table([{ label: 'Miktar', num: true, m: false }, { label: 'Yön' }, { label: 'Tekrar', num: true },
                 { label: 'Toplam', num: true }, { label: 'Ort. fiyat', num: true, m: false }, { label: 'Süre', num: true, m: false }], ice,
                { empty: 'Iceberg tespit edilmedi' })}</div>
    </div>
    <div class="card"><h3>Order Book Derinliği</h3>
      ${b.available && b.depthChart
        ? charts.depthChart(b.depthChart.bids, b.depthChart.asks, { h: 200 })
        : '<div class="empty">Derinlik grafiği anlık veridir ve saklanmaz — güncel görüntü için yeni tarama yapın. Aşağıdaki değerler son taramaya aittir.</div>'}
      <dl class="kv">
        <dt>Durum</dt><dd>${esc(b.state)}</dd>
        <dt>Yakın denge (±%${b.nearBandPct})</dt><dd class="${tone(b.nearImbalancePct)}">%${fmt(b.nearImbalancePct)}</dd>
        <dt>Toplam denge</dt><dd class="${tone(b.fullImbalancePct)}">%${fmt(b.fullImbalancePct)}</dd>
        <dt>Spread</dt><dd>%${fmt(b.spreadPct, 4)}</dd>
        <dt>Okunan seviye</dt><dd>${b.levelsRead}</dd>
      </dl>
      <h4>Duvarlar</h4>
      ${table([{ label: 'Taraf' }, { label: 'Fiyat', num: true }, { label: 'Miktar', num: true, m: false },
               { label: 'USDT', num: true }, { label: 'Ort. kat', num: true, m: false }, { label: 'Uzaklık %', num: true }], wallRows,
              { empty: 'Belirgin duvar yok' })}
      ${b.spoofs?.length ? `<h4>⚠️ Spoof şüphesi</h4>${table([{ label: 'Taraf' }, { label: 'Fiyat', num: true }, { label: 'USDT', num: true }, { label: 'Erime %', num: true }],
        b.spoofs.map((s) => ({ cells: [s.side, fmtPrice(s.price), fmtUsd(s.notional), fmt(s.shrinkPct, 0)] })))}` : ''}
      ${b.absorptions?.length ? `<h4>Absorption</h4>${table([{ label: 'Taraf' }, { label: 'Fiyat', num: true }, { label: 'Yorum' }],
        b.absorptions.map((a) => ({ cells: [a.side, fmtPrice(a.price), { text: a.verdict, wrap: true }] })))}` : ''}
      <div class="note">${esc(b.compareNote)}</div>
    </div>`;
}

// ===========================================================================
// 7) SIRALAMA (izleme listesi)
// ===========================================================================
function renderSiralama() {
  const el = $('tab-siralama');
  const snaps = store.allSnapshots(cfg.symbols).sort((a, b) => b.score.longScore - a.score.longScore);
  const rows = snaps.map((s, i) => ({
    click: s.symbol,
    cells: [String(i + 1), s.symbol, fmtPrice(s.price),
      { html: `<b>${s.score.longScore.toFixed(0)}</b>` }, s.score.shortScore.toFixed(0),
      { html: `<span class="${decClass(s.score.decision)}">${s.score.decision}</span>` },
      `%${s.score.confidence.toFixed(0)}`, s.trend.label,
      `%${fmt(s.derivatives.openInterest?.change1hPct)}`,
      `%${fmt(s.derivatives.funding?.currentPct, 4)}`,
      s.orderFlow.label, s.whale.state, s.risk.level,
      timeAgo(s.timestamp)],
  }));

  el.innerHTML = `
    <div class="card">
      <h3>İzleme Listesi Sıralaması</h3>
      <button class="btn wide" id="scanAllBtn">Listedeki ${cfg.symbols.length} pariteyi tara</button>
      <div class="note">Her parite ~10-15 sn sürer. Sonuçlar cihazda saklanır.</div>
    </div>
    <div class="card">
      ${table([{ label: '#' }, { label: 'Parite' }, { label: 'Fiyat', num: true, m: false },
               { label: 'Long', num: true }, { label: 'Short', num: true, m: false }, { label: 'Karar' },
               { label: 'Güven', num: true, m: false }, { label: 'Trend', m: false },
               { label: 'OI 1s', num: true }, { label: 'Funding', num: true, m: false },
               { label: 'CVD', m: false }, { label: 'Balina', m: false },
               { label: 'Risk' }, { label: 'Tarama', m: false }], rows,
              { empty: 'Henüz tarama yok — yukarıdaki düğmeye basın.' })}
    </div>`;

  $('scanAllBtn')?.addEventListener('click', scanWatchlist);
  wireRowClicks(el);
}

// ===========================================================================
// 8) TÜM PİYASA
// ===========================================================================
let marketFilter = { minInterest: 0, state: '', bias: '' };

function renderPiyasa() {
  const el = $('tab-piyasa');
  const scr = store.latestScreening();

  const controls = `
    <div class="card">
      <h3>Tüm Piyasa Taraması</h3>
      <p class="muted" style="font-size:.84rem">Binance vadelideki tüm sürekli pariteler
        ucuz toplu veriyle taranır. <b>Dikkat</b> skoru yön değil hareketlilik ölçer.</p>
      <div class="row-actions">
        <button class="btn" id="screenBtn">Ön eleme (~45 sn)</button>
        <button class="btn primary" id="deepBtn">Ön eleme + derin tarama</button>
      </div>
      <div class="note">Ön eleme ~200 pariteyi tarar (~45 sn, ~1 MB veri). Derin tarama
        ayrıca dikkat skoru en yüksek ${cfg.market.deepScanTop} pariteyi 9 motorla
        inceler (~2-3 dk, ~5 MB).</div>
    </div>`;

  if (!scr) {
    el.innerHTML = controls + '<div class="card"><div class="empty">Henüz piyasa taraması yapılmadı.</div></div>';
    wireMarketButtons();
    return;
  }

  const states = [...new Set(scr.records.map((r) => r.oiState).filter(Boolean))].sort();
  let view = scr.records.filter((r) => (r.interest ?? 0) >= marketFilter.minInterest);
  if (marketFilter.state) view = view.filter((r) => r.oiState === marketFilter.state);
  if (marketFilter.bias) view = view.filter((r) => r.biasLabel === marketFilter.bias);

  const rows = view.slice(0, 200).map((r, i) => ({
    click: r.symbol,
    cells: [String(i + 1), r.symbol, fmtPrice(r.lastPrice),
      { html: `<span class="${tone(r.priceChangePercent)}">%${fmt(r.priceChangePercent)}</span>` },
      { html: `<b>${(r.interest ?? 0).toFixed(0)}</b>` },
      { html: `<span class="${tone(r.oiChange1h)}">%${fmt(r.oiChange1h)}</span>` },
      { html: `<span class="${tone(r.priceChange1h)}">%${fmt(r.priceChange1h)}</span>` },
      r.oiState || '—', `%${fmt(r.fundingPct, 4)}`, fmtUsd(r.quoteVolume),
      { html: `<span class="${r.biasLabel === 'LONG EĞİLİM' ? 'up' : r.biasLabel === 'SHORT EĞİLİM' ? 'down' : 'flat'}">${r.biasLabel || '—'}</span>` }],
  }));

  const top = scr.records.slice(0, 15).map((r) => ({
    label: r.symbol, value: r.interest ?? 0, max: 100,
    text: (r.interest ?? 0).toFixed(0),
    color: r.biasLabel === 'LONG EĞİLİM' ? '#26a65b' : r.biasLabel === 'SHORT EĞİLİM' ? '#e04b4b' : '#8892a4',
  }));

  el.innerHTML = controls + `
    <div class="card">
      <div class="note">Son tarama: ${timeAgo(new Date(scr.ts).toISOString())} · ${scr.total} parite</div>
      <div class="grid2" style="margin-top:10px">
        <div class="field"><label>En düşük dikkat skoru: <b id="minIntVal">${marketFilter.minInterest}</b></label>
          <input type="range" id="minInt" min="0" max="100" step="5" value="${marketFilter.minInterest}"></div>
        <div class="field"><label>OI durumu</label>
          <select id="stateSel"><option value="">(hepsi)</option>
            ${states.map((s) => `<option ${marketFilter.state === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></div>
        <div class="field"><label>Ön eğilim</label>
          <select id="biasSel"><option value="">(hepsi)</option>
            ${['LONG EĞİLİM', 'SHORT EĞİLİM', 'NÖTR'].map((s) => `<option ${marketFilter.bias === s ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
      </div>
      ${table([{ label: '#' }, { label: 'Parite' }, { label: 'Fiyat', num: true, m: false },
               { label: '24s %', num: true }, { label: 'Dikkat', num: true },
               { label: 'OI 1s %', num: true }, { label: 'Fiyat 1s %', num: true, m: false },
               { label: 'OI Durumu' }, { label: 'Funding', num: true, m: false },
               { label: '24s Hacim', num: true, m: false }, { label: 'Ön eğilim', m: false }], rows)}
      <div class="note">${view.length} parite gösteriliyor. Satıra dokununca o parite taranır.</div>
    </div>
    <div class="card"><h3>En Dikkat Çekici 15 Parite</h3>${charts.hBarChart(top, { rowH: 26 })}</div>`;

  wireMarketButtons();
  $('minInt')?.addEventListener('input', (e) => {
    marketFilter.minInterest = +e.target.value;
    $('minIntVal').textContent = marketFilter.minInterest;
  });
  $('minInt')?.addEventListener('change', renderPiyasa);
  $('stateSel')?.addEventListener('change', (e) => { marketFilter.state = e.target.value; renderPiyasa(); });
  $('biasSel')?.addEventListener('change', (e) => { marketFilter.bias = e.target.value; renderPiyasa(); });
  wireRowClicks(el);
}

function wireMarketButtons() {
  $('screenBtn')?.addEventListener('click', () => runMarket(false));
  $('deepBtn')?.addEventListener('click', () => runMarket(true));
}

function wireRowClicks(root) {
  root.querySelectorAll('tr[data-click]').forEach((tr) => {
    tr.addEventListener('click', () => {
      const sym = tr.dataset.click;
      if (!cfg.symbols.includes(sym)) {
        cfg = saveConfig({ symbols: [...cfg.symbols, sym] });
        fillSymbols();
      }
      $('symbolSelect').value = sym;
      runScan(sym);
    });
  });
}

// ===========================================================================
// 9) AYARLAR
// ===========================================================================
function renderAyarlar() {
  const el = $('tab-ayarlar');
  const info = store.storageInfo();
  el.innerHTML = `
    <div class="card"><h3>İzleme Listesi</h3>
      <div class="field"><label>Pariteler (virgülle ayırın)</label>
        <input id="symbolsInput" value="${esc(cfg.symbols.join(', '))}"></div>
      <div class="field"><label>Varsayılan parite</label>
        <input id="primaryInput" value="${esc(cfg.primarySymbol)}"></div>
    </div>
    <div class="card"><h3>Risk ve Pozisyon</h3>
      <div class="grid2">
        <div class="field"><label>Hesap büyüklüğü (USDT)</label>
          <input id="acctInput" type="number" value="${cfg.risk.accountSizeUsdt}"></div>
        <div class="field"><label>İşlem başına risk (%)</label>
          <input id="riskInput" type="number" step="0.1" value="${cfg.risk.riskPerTradePct}"></div>
        <div class="field"><label>Maksimum kaldıraç</label>
          <input id="levInput" type="number" value="${cfg.risk.maxLeverage}"></div>
      </div>
    </div>
    <div class="card"><h3>Veri ve Hız</h3>
      <div class="grid2">
        <div class="field"><label>İşlem akışı sayfası (1 sayfa ≈ 1000 işlem, ~350 KB)</label>
          <input id="pagesInput" type="number" min="1" max="5" value="${cfg.data.aggTradesPages}"></div>
        <div class="field"><label>Mum sayısı</label>
          <input id="klinesInput" type="number" min="200" max="1000" step="50" value="${cfg.timeframes.klinesLimit}"></div>
        <div class="field"><label>Piyasa taraması: min 24s hacim (USDT)</label>
          <input id="minVolInput" type="number" step="1000000" value="${cfg.market.minQuoteVolumeUsdt}"></div>
        <div class="field"><label>Piyasa taraması: derin taranacak parite</label>
          <input id="deepTopInput" type="number" min="3" max="40" value="${cfg.market.deepScanTop}"></div>
      </div>
    </div>
    <div class="card"><h3>Kayıtlı Veri</h3>
      <p class="muted" style="font-size:.84rem">Bu cihazda ${info.count} kayıt · ${info.kb} KB.
        Veriler sadece telefonunuzda tutulur, hiçbir sunucuya gönderilmez.</p>
      <div class="row-actions">
        <button class="btn primary" id="saveSettings">Ayarları kaydet</button>
        <button class="btn ghost" id="resetSettings">Varsayılanlara dön</button>
        <button class="btn danger" id="clearData">Kayıtlı verileri sil</button>
      </div>
    </div>`;

  $('saveSettings').addEventListener('click', () => {
    const syms = $('symbolsInput').value.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
    cfg = saveConfig({
      symbols: syms.length ? syms : DEFAULTS.symbols,
      primarySymbol: $('primaryInput').value.trim().toUpperCase() || syms[0],
      risk: {
        accountSizeUsdt: +$('acctInput').value || 1000,
        riskPerTradePct: +$('riskInput').value || 1,
        maxLeverage: +$('levInput').value || 10,
      },
      data: { aggTradesPages: Math.max(1, Math.min(5, +$('pagesInput').value || 2)) },
      timeframes: { klinesLimit: Math.max(200, Math.min(1000, +$('klinesInput').value || 400)) },
      market: {
        minQuoteVolumeUsdt: +$('minVolInput').value || 0,
        deepScanTop: Math.max(3, Math.min(40, +$('deepTopInput').value || 10)),
      },
    });
    fillSymbols();
    renderAyarlar();
    alert('Ayarlar kaydedildi.');
  });

  $('resetSettings').addEventListener('click', () => {
    if (!confirm('Tüm ayarlar varsayılana dönecek. Emin misiniz?')) return;
    cfg = resetConfig();
    fillSymbols();
    renderAyarlar();
  });

  $('clearData').addEventListener('click', () => {
    if (!confirm('Kayıtlı tüm tarama geçmişi silinecek. Emin misiniz?')) return;
    store.clearAll();
    snap = null;
    cfg = loadConfig();
    fillSymbols();
    renderAll();
  });
}

// ===========================================================================
// Tarama akışları
// ===========================================================================
async function runScan(symbol) {
  if (busy) return;
  symbol = symbol || $('symbolSelect').value;
  localStorage.setItem('kripto.lastSymbol', symbol);
  setBusy(true, `${symbol} taranıyor...`);
  try {
    snap = await scanSymbol(symbol, cfg, { onProgress: (m) => setBusy(true, `${symbol} — ${m}`) });
    renderAll();
    switchTab('karar');
  } catch (e) {
    showError(e.message || String(e));
  } finally {
    setBusy(false);
  }
}

async function scanWatchlist() {
  if (busy) return;
  setBusy(true, 'İzleme listesi taranıyor...');
  try {
    for (let i = 0; i < cfg.symbols.length; i++) {
      const sym = cfg.symbols[i];
      setBusy(true, `${sym} (${i + 1}/${cfg.symbols.length}) taranıyor...`);
      try {
        snap = await scanSymbol(sym, cfg, { onProgress: (m) => setBusy(true, `${sym} (${i + 1}/${cfg.symbols.length}) — ${m}`) });
      } catch (e) {
        console.warn(sym, e);
      }
    }
    renderAll();
    switchTab('siralama');
  } catch (e) {
    showError(e.message || String(e));
  } finally {
    setBusy(false);
  }
}

async function runMarket(deep) {
  if (busy) return;
  setBusy(true, 'Tüm piyasa taranıyor...');
  try {
    if (deep) {
      const res = await scanMarket(cfg, { deep: true, onProgress: (m) => setBusy(true, m) });
      if (res.snapshots.length) snap = res.snapshots[0];
    } else {
      await screenMarket(cfg, { onProgress: (m) => setBusy(true, m) });
    }
    renderAll();
    switchTab(deep ? 'siralama' : 'piyasa');
  } catch (e) {
    showError(e.message || String(e));
  } finally {
    setBusy(false);
  }
}

// ===========================================================================
// Yönlendirme
// ===========================================================================
function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('active', p.id === `tab-${name}`));
  localStorage.setItem('kripto.lastTab', name);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderAll() {
  if (snap) { renderHeadline(); renderKpis(); }
  renderKarar(); renderTrend(); renderSmart(); renderTurev();
  renderAkis(); renderBalina(); renderSiralama(); renderPiyasa(); renderAyarlar();
}

// Yeni sürüm yayınlandığında telefonun eski sürümde kalmaması için:
// service worker güncellemeyi bulunca üstte "yenile" şeridi çıkar.
function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('sw.js').then((reg) => {
    reg.addEventListener('updatefound', () => {
      const nw = reg.installing;
      if (!nw) return;
      nw.addEventListener('statechange', () => {
        if (nw.state === 'installed' && navigator.serviceWorker.controller) showUpdateBar();
      });
    });
    // Uygulama her açılışta güncelleme var mı diye bakar
    setTimeout(() => reg.update().catch(() => {}), 3000);
  }).catch(() => {});
}

function showUpdateBar() {
  if (document.getElementById('updateBar')) return;
  const bar = document.createElement('div');
  bar.id = 'updateBar';
  bar.className = 'update-bar';
  bar.innerHTML = `<span>Yeni sürüm hazır</span><button class="btn primary" id="reloadBtn">Yenile</button>`;
  document.body.appendChild(bar);
  document.getElementById('reloadBtn').addEventListener('click', async () => {
    const regs = await navigator.serviceWorker.getRegistrations();
    await Promise.all(regs.map((r) => r.unregister()));
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => caches.delete(k)));
    location.reload(true);
  });
}

function init() {
  fillSymbols();
  document.querySelectorAll('.tab').forEach((t) =>
    t.addEventListener('click', () => switchTab(t.dataset.tab)));
  $('scanBtn').addEventListener('click', () => runScan());
  $('symbolSelect').addEventListener('change', (e) => {
    const s = e.target.value;
    localStorage.setItem('kripto.lastSymbol', s);
    const cached = store.latestSnapshot(s);
    if (cached) { snap = cached; renderAll(); }
  });

  const last = store.latestSnapshot($('symbolSelect').value);
  if (last) snap = last;
  renderAll();

  const savedTab = localStorage.getItem('kripto.lastTab');
  if (savedTab && document.getElementById(`tab-${savedTab}`)) switchTab(savedTab);

  registerServiceWorker();
}

init();
