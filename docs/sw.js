// Service worker — uygulama kabuğunu önbelleğe alır, böylece ana ekrandan
// dokununca anında açılır. Binance verisi ASLA önbelleğe alınmaz; her tarama
// canlı veri çeker.

// Sürüm değişince eski önbellek silinir ve kullanıcıya "yeni sürüm" bildirimi gider.
// Kod güncellendiğinde bu numarayı artırın — js/app.js içindeki SURUM ile AYNI olmalı.
const VERSION = '1.3.1';
const CACHE = `kripto-${VERSION}`;
const SHELL = [
  './',
  './index.html',
  './css/style.css',
  './js/app.js',
  './js/binance.js',
  './js/charts.js',
  './js/config.js',
  './js/engines.js',
  './js/indicators.js',
  './js/journal.js',
  './js/scan.js',
  './js/scoring.js',
  './js/store.js',
  './js/util.js',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Binance istekleri doğrudan ağa gider — önbelleğe alınmaz
  if (url.hostname.endsWith('binance.com')) return;
  if (e.request.method !== 'GET') return;

  // Uygulama dosyaları: önce ağ (güncel kalsın), olmazsa önbellek.
  // GitHub Pages dosyaları tarayıcıda 10 dk önbellekte tutuluyor; 'no-cache'
  // her açılışta sunucuya "değişti mi?" diye sorar (değişmediyse veri inmez),
  // böylece yayınlanan düzeltme 10 dk beklemeden gelir.
  e.respondWith(
    fetch(e.request, { cache: 'no-cache' })
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match('./index.html')))
  );
});

// Sayfa, çalışan service worker'ın sürümünü sorar; kendi sürümünden farklıysa
// "yeni sürüm" şeridini gösterir (güncelleme olayı kaçırılmış olsa bile).
self.addEventListener('message', (e) => {
  if (e.data?.tip === 'surum') e.source?.postMessage({ tip: 'surum', surum: VERSION });
});
