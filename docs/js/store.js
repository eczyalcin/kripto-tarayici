// localStorage tabanlı yerel saklama — Python sürümündeki SQLite'ın karşılığı.
// Telefonda kalıcıdır; uygulama kapansa bile veri durur.
//
// Saklananlar:
//   depth:<SEMBOL>   → son order book fotoğrafı (spoof/absorption karşılaştırması)
//   scans:<SEMBOL>   → skor geçmişi (grafik için)
//   snapshot:<SEMBOL>→ son tam tarama sonucu
//   screening        → son piyasa ön elemesi

const P = 'kripto.';
const MAX_SCANS = 120;

function get(key, fallback = null) {
  try {
    const raw = localStorage.getItem(P + key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function set(key, value) {
  try {
    localStorage.setItem(P + key, JSON.stringify(value));
    return true;
  } catch (e) {
    // Kota dolduysa en eski taramaları temizleyip bir kez daha dene
    if (e.name === 'QuotaExceededError') {
      pruneOldest();
      try {
        localStorage.setItem(P + key, JSON.stringify(value));
        return true;
      } catch { /* vazgeç */ }
    }
    return false;
  }
}

function pruneOldest() {
  for (const k of Object.keys(localStorage)) {
    if (k.startsWith(P + 'snapshot:')) localStorage.removeItem(k);
  }
}

// ------------------------------------------------------------- order book
export const saveDepth = (symbol, mid, bids, asks) =>
  set(`depth:${symbol}`, { ts: Date.now(), mid, bids, asks });

export function previousDepth(symbol, maxAgeMinutes = 180) {
  const d = get(`depth:${symbol}`);
  if (!d) return null;
  if (Date.now() - d.ts > maxAgeMinutes * 60000) return null;
  return d;
}

// ---------------------------------------------------------- tarama geçmişi
export function addScan(symbol, entry) {
  const list = get(`scans:${symbol}`, []);
  list.push(entry);
  set(`scans:${symbol}`, list.slice(-MAX_SCANS));
}

export const scanHistory = (symbol) => get(`scans:${symbol}`, []);

// -------------------------------------------------------------- snapshot
export const saveSnapshot = (symbol, snap) => set(`snapshot:${symbol}`, snap);
export const latestSnapshot = (symbol) => get(`snapshot:${symbol}`);

// ------------------------------------------------------------- ön eleme
export const saveScreening = (records) =>
  set('screening', { ts: Date.now(), total: records.length, records });
export const latestScreening = () => get('screening');

// --------------------------------------------------------------- sıralama
export function allSnapshots(symbols) {
  return symbols.map((s) => latestSnapshot(s)).filter(Boolean);
}

export function clearAll() {
  for (const k of Object.keys(localStorage)) {
    if (k.startsWith(P)) localStorage.removeItem(k);
  }
}

export function storageInfo() {
  let bytes = 0, count = 0;
  for (const k of Object.keys(localStorage)) {
    if (k.startsWith(P)) { bytes += (localStorage.getItem(k) || '').length; count++; }
  }
  return { bytes, count, kb: Math.round(bytes / 1024) };
}
