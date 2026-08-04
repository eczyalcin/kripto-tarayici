// Ortak yardımcılar — Python sürümündeki core/indicators.py yardımcılarının karşılığı.

export const clamp = (v, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, v));

export function pctChange(nw, old) {
  if (old === 0 || old == null || nw == null || !isFinite(old) || !isFinite(nw)) return 0;
  return ((nw - old) / Math.abs(old)) * 100;
}

// Türkçe küçük harf (I → ı, İ → i)
export const trLower = (s) => String(s).replace(/I/g, 'ı').replace(/İ/g, 'i').toLowerCase();

export function fmt(v, d = 2, suffix = '') {
  if (v == null || !isFinite(v)) return '—';
  return v.toLocaleString('tr-TR', { minimumFractionDigits: d, maximumFractionDigits: d }) + suffix;
}

// Fiyatları anlamlı basamakla göster (0.000004918 gibi değerler için)
export function fmtPrice(v) {
  if (v == null || !isFinite(v)) return '—';
  const a = Math.abs(v);
  let d = 2;
  if (a < 0.00001) d = 9;
  else if (a < 0.001) d = 7;
  else if (a < 0.1) d = 6;
  else if (a < 10) d = 4;
  else if (a < 1000) d = 3;
  return v.toLocaleString('tr-TR', { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function fmtUsd(v, d = 0) {
  if (v == null || !isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(0) + 'k';
  return v.toFixed(d);
}

export const signed = (v, d = 2) => (v > 0 ? '+' : '') + fmt(v, d);

export function mean(arr) {
  const a = arr.filter((x) => isFinite(x));
  return a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0;
}

export function sum(arr) {
  return arr.reduce((s, x) => s + (isFinite(x) ? x : 0), 0);
}

export function percentile(arr, p) {
  const a = arr.filter((x) => isFinite(x)).sort((x, y) => x - y);
  if (!a.length) return 0;
  const idx = (p / 100) * (a.length - 1);
  const lo = Math.floor(idx), hi = Math.ceil(idx);
  return lo === hi ? a[lo] : a[lo] + (a[hi] - a[lo]) * (idx - lo);
}

export function nowIso() {
  return new Date().toISOString();
}

export function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return 'az önce';
  if (diff < 3600) return `${Math.floor(diff / 60)} dk önce`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} sa önce`;
  return `${Math.floor(diff / 86400)} gün önce`;
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Eşzamanlı istekleri sınırlayarak çalıştırır (mobil bağlantıyı boğmamak için)
export async function pool(items, worker, concurrency = 4, onProgress = null) {
  const results = new Array(items.length);
  let idx = 0, done = 0;
  const runners = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (idx < items.length) {
      const i = idx++;
      try {
        results[i] = await worker(items[i], i);
      } catch (e) {
        results[i] = null;
      }
      done++;
      if (onProgress) onProgress(done, items.length);
    }
  });
  await Promise.all(runners);
  return results;
}
