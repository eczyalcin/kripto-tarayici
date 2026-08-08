// Sinyal Günlüğü — üretilen her trade setup'ı kaydeder ve sonucunu
// piyasa verisinden otomatik ölçer.
//
// Amaç: "olasılık %71" gibi bir tahmini, gerçek istatistiğe çevirmek.
// Yeterli kayıt biriktiğinde şunu söyleyebiliriz:
//   "Skoru 70+ olan 34 sinyalin 21'i TP1'e ulaştı (%62)"
//
// ÖLÇÜM KURALLARI (dürüstlük için önemli):
//  1. Başarı ölçütü ikili: TP1 mi önce geldi, stop mu?
//  2. Kâr/zarar simüle EDİLMEZ. Gerçek kazanç, modellemediğimiz pozisyon
//     yönetimine (kısmi çıkış, stop taşıma) bağlıdır. Bunun yerine ulaşılan
//     en yüksek R (MFE) ve en kötü geri çekilme (MAE) ayrıca kaydedilir.
//  3. Aynı mumda hem stop hem TP dokunulduysa STOP önce sayılır. Mum
//     verisinden sıra bilinemez; kötümser taraf seçilir ki istatistik şişmesin.
//  4. Giriş bir bölgedir (limit emir mantığı). Fiyat bölgeye gelmediyse sinyal
//     "giriş olmadı" sayılır ve başarı istatistiğine katılmaz.

import { klinesSince } from './binance.js';

const KEY = 'kripto.journal.v1';

export const AYARLAR = {
  girisGecerlilikSaat: 24,      // bu süre içinde giriş olmazsa sinyal düşer
  islemGecerlilikSaat: 168,     // 7 gün: bu süre sonunda hâlâ açıksa kapatılır
  kontrolAraligiDk: 5,          // aynı sinyal bu süreden önce tekrar ölçülmez
  mumAraligi: '15m',
};

export const DURUM = {
  BEKLIYOR: 'BEKLİYOR',        // giriş bölgesine henüz gelinmedi
  ACIK: 'AÇIK',                // girildi, işlem sürüyor
  TP1: 'TP1', TP2: 'TP2', TP3: 'TP3',
  STOP: 'STOP',
  GIRIS_OLMADI: 'GİRİŞ OLMADI',
  ZAMAN_ASIMI: 'ZAMAN AŞIMI',
  IPTAL: 'İPTAL',              // yön değişti, sinyal geçersiz
};

const KAPALI = [DURUM.TP1, DURUM.TP2, DURUM.TP3, DURUM.STOP,
                DURUM.GIRIS_OLMADI, DURUM.ZAMAN_ASIMI, DURUM.IPTAL];

export const acikMi = (s) => !KAPALI.includes(s.durum);

/**
 * ÖNEMLİ — `sonuc` ile `durum` neden ayrı?
 *
 * İşlem, TP3'e ya da stop'a kadar açık kalır. Ama başarı sorusu ("TP1 mi önce
 * geldi, stop mu?") çok daha erken cevaplanır. İkisi ayrılmazsa şu sapma oluşur:
 * kaybedenler stop'a çarpıp hemen kapanır, kazananlar TP3'ü beklerken açık kalır
 * ve istatistiğe girmez — başarı oranı olduğundan düşük görünür.
 *
 * Bu yüzden `sonuc` alanı TP1 veya STOP'un ilki gerçekleştiği anda sabitlenir ve
 * istatistik bunu kullanır. `durum` ise kullanıcıya gösterilen güncel hâldir.
 */
export const SONUC = {
  TP1: 'TP1', STOP: 'STOP',
  GIRIS_OLMADI: 'GİRİŞ OLMADI',
  ZAMAN_ASIMI: 'ZAMAN AŞIMI',
};

/** Listelerde gösterilecek etiket: hem güncel durum hem ulaşılan en iyi hedef. */
export function durumEtiketi(s) {
  if (s.durum === DURUM.ACIK && s.enIyiHedef) return `AÇIK · ${s.enIyiHedef} ✓`;
  return s.durum;
}

// ------------------------------------------------------------------ saklama
function oku() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]');
  } catch {
    return [];
  }
}

function yaz(list) {
  try {
    // Kota dolarsa en eski kapalı kayıtları at
    localStorage.setItem(KEY, JSON.stringify(list));
    return true;
  } catch {
    const kirp = list.filter(acikMi).concat(list.filter((s) => !acikMi(s)).slice(-200));
    try { localStorage.setItem(KEY, JSON.stringify(kirp)); return true; } catch { return false; }
  }
}

export const tumSinyaller = () => oku().sort((a, b) => b.ts - a.ts);
export const acikSinyaller = () => oku().filter(acikMi).sort((a, b) => b.ts - a.ts);

export function sil(id) {
  yaz(oku().filter((s) => s.id !== id));
}

export function hepsiniSil() {
  localStorage.removeItem(KEY);
}

// ------------------------------------------------------------------- kayıt
/**
 * Taramadan çıkan setup'ı günlüğe ekler.
 * Aynı parite için açık sinyal varsa yenisi eklenmez (aynı fırsat iki kez sayılmasın).
 * Yön değiştiyse eski sinyal İPTAL edilip yenisi açılır.
 */
export function kaydet(snapshot) {
  const setup = snapshot.setup;
  if (!setup?.available) return null;

  const list = oku();
  const acik = list.find((s) => s.symbol === snapshot.symbol && acikMi(s));

  if (acik) {
    if (acik.yon === setup.direction) {
      // Aynı yönde zaten açık sinyal var — sadece son görülen skoru güncelle
      acik.sonSkor = snapshot.score.longScore;
      acik.gorulme = (acik.gorulme || 1) + 1;
      yaz(list);
      return null;
    }
    acik.durum = DURUM.IPTAL;
    acik.kapanis = Date.now();
    acik.not = 'Yön değişti, sinyal geçersiz kaldı';
  }

  const kayit = {
    id: `${snapshot.symbol}-${Date.now()}`,
    symbol: snapshot.symbol,
    ts: Date.parse(snapshot.timestamp) || Date.now(),
    yon: setup.direction,
    giris: setup.entry,
    girisBolgesi: setup.entryZone,
    stop: setup.stop,
    hedefler: setup.targets.map((t) => ({ ad: t.name, fiyat: t.price, r: t.rMultiple })),
    // Sinyal anındaki durum — kalibrasyon bu alanlara göre yapılır
    longSkor: snapshot.score.longScore,
    guven: snapshot.score.confidence,
    olasilik: setup.probability,
    risk: snapshot.risk.level,
    trend: snapshot.trend.label,
    baglam: {
      funding: setup.context?.funding, oi: setup.context?.oi,
      cvd: setup.context?.cvd, balina: setup.context?.whales,
    },
    fiyatSinyalde: snapshot.price,
    durum: DURUM.BEKLIYOR,
    girisOldu: false, girisZamani: null,
    mfeR: 0, maeR: 0,
    tp1: false, tp2: false, tp3: false, stopOldu: false,
    sonKontrol: 0, kapanis: null, gorulme: 1,
  };
  list.push(kayit);
  yaz(list);
  return kayit;
}

// ------------------------------------------------------------------ ölçüm
// Dışa açık: ölçüm mantığı sentetik mumlarla doğrulanabilsin diye.
export function mumlariYurut(kayit, mumlar) {
  const long = kayit.yon === 'LONG';
  const R = Math.abs(kayit.giris - kayit.stop);
  if (!R) return kayit;

  const tp = kayit.hedefler.map((h) => h.fiyat);
  const girisSonu = kayit.ts + AYARLAR.girisGecerlilikSaat * 3600_000;
  const islemSonu = kayit.ts + AYARLAR.islemGecerlilikSaat * 3600_000;

  let girildi = kayit.girisOldu;
  let girisZamani = kayit.girisZamani;
  let mfe = kayit.mfeR || 0, mae = kayit.maeR || 0;
  let tp1 = kayit.tp1, tp2 = kayit.tp2, tp3 = kayit.tp3;
  let durum = kayit.durum;
  let sonuc = kayit.sonuc || null;      // istatistiğin kullandığı erken karar
  let stopOldu = kayit.stopOldu || false;
  let kapanis = null;

  for (const m of mumlar) {
    if (m.t < kayit.ts) continue;

    if (!girildi) {
      if (m.t > girisSonu) {
        durum = DURUM.GIRIS_OLMADI; sonuc = SONUC.GIRIS_OLMADI; kapanis = girisSonu; break;
      }
      // LONG: fiyat giriş seviyesine kadar indi mi? SHORT: yükseldi mi?
      const doldu = long ? m.l <= kayit.giris : m.h >= kayit.giris;
      if (!doldu) continue;
      girildi = true;
      girisZamani = m.t;
      durum = DURUM.ACIK;
    }

    // Girildikten sonra: R cinsinden en iyi ve en kötü noktalar
    const lehte = long ? (m.h - kayit.giris) / R : (kayit.giris - m.l) / R;
    const aleyhte = long ? (m.l - kayit.giris) / R : (kayit.giris - m.h) / R;
    if (lehte > mfe) mfe = lehte;
    if (aleyhte < mae) mae = aleyhte;

    const stopDokundu = long ? m.l <= kayit.stop : m.h >= kayit.stop;
    const tpDokundu = tp.map((p) => (long ? m.h >= p : m.l <= p));

    // Aynı mumda ikisi de olduysa STOP önce sayılır (kötümser varsayım).
    // Bu yüzden stop kontrolü TP kontrolünden önce gelir.
    if (stopDokundu) {
      stopOldu = true;
      if (!sonuc) sonuc = SONUC.STOP;          // TP1 daha önce gelmediyse başarısız
      durum = tp3 ? DURUM.TP3 : tp2 ? DURUM.TP2 : tp1 ? DURUM.TP1 : DURUM.STOP;
      kapanis = m.t;
      break;
    }

    if (tpDokundu[0] && !tp1) {
      tp1 = true;
      if (!sonuc) sonuc = SONUC.TP1;           // başarı burada sabitlenir
    }
    if (tpDokundu[1]) tp2 = true;
    if (tpDokundu[2]) {
      tp3 = true;
      durum = DURUM.TP3;
      kapanis = m.t;
      break;
    }

    if (m.t > islemSonu) {
      durum = tp2 ? DURUM.TP2 : tp1 ? DURUM.TP1 : DURUM.ZAMAN_ASIMI;
      if (!sonuc) sonuc = SONUC.ZAMAN_ASIMI;
      kapanis = islemSonu;
      break;
    }
  }

  return {
    ...kayit,
    girisOldu: girildi, girisZamani,
    mfeR: +mfe.toFixed(2), maeR: +mae.toFixed(2),
    tp1, tp2, tp3, stopOldu, sonuc,
    enIyiHedef: tp3 ? 'TP3' : tp2 ? 'TP2' : tp1 ? 'TP1' : null,
    durum, kapanis: kapanis ?? kayit.kapanis,
    sonKontrol: Date.now(),
  };
}

/** Açık sinyalleri piyasa verisiyle karşılaştırıp sonuçlarını günceller. */
export async function sonuclariGuncelle({ onProgress = () => {} } = {}) {
  const list = oku();
  const acikList = list.filter(acikMi);
  const simdi = Date.now();
  const kontrolEdilecek = acikList.filter(
    (s) => simdi - (s.sonKontrol || 0) > AYARLAR.kontrolAraligiDk * 60_000);

  if (!kontrolEdilecek.length) return { kontrol: 0, kapanan: 0 };

  let kapanan = 0;
  for (let i = 0; i < kontrolEdilecek.length; i++) {
    const s = kontrolEdilecek[i];
    onProgress(`Sinyal sonucu ölçülüyor ${i + 1}/${kontrolEdilecek.length}: ${s.symbol}`);
    try {
      const mumlar = await klinesSince(s.symbol, AYARLAR.mumAraligi, s.ts, 1000);
      const yeni = mumlariYurut(s, mumlar);
      const idx = list.findIndex((x) => x.id === s.id);
      if (idx >= 0) {
        list[idx] = yeni;
        if (!acikMi(yeni)) kapanan++;
      }
    } catch (e) {
      console.warn('Sinyal ölçülemedi:', s.symbol, e);
    }
  }
  yaz(list);
  return { kontrol: kontrolEdilecek.length, kapanan };
}

// -------------------------------------------------------------- istatistik
// Başarı oranı = TP1 / (TP1 + STOP). "Zaman aşımı" (7 günde ne TP ne stop) ayrı
// raporlanır; ne kazanç ne kayıp olduğu için orana katmak yanıltıcı olurdu.
const basarili = (s) => s.sonuc === SONUC.TP1;
const kararlandi = (s) => s.sonuc === SONUC.TP1 || s.sonuc === SONUC.STOP;

function ozet(kayitlar) {
  const karar = kayitlar.filter(kararlandi);
  const n = karar.length;
  const zamanAsimi = kayitlar.filter((s) => s.sonuc === SONUC.ZAMAN_ASIMI).length;
  if (!n) return { adet: 0, zamanAsimi };
  const kazanan = karar.filter(basarili).length;
  return {
    adet: n,
    kazanan,
    kaybeden: n - kazanan,
    zamanAsimi,
    basariOrani: (kazanan / n) * 100,
    tp2Orani: (karar.filter((s) => s.tp2).length / n) * 100,
    tp3Orani: (karar.filter((s) => s.tp3).length / n) * 100,
    ortMfe: karar.reduce((a, s) => a + (s.mfeR || 0), 0) / n,
    ortMae: karar.reduce((a, s) => a + (s.maeR || 0), 0) / n,
  };
}

/**
 * Kalibrasyon: skor bandına göre gerçek başarı oranı.
 * Sistemin "olasılık" tahmininin tutup tutmadığını burada görürüz.
 */
export function istatistik() {
  const hepsi = oku();
  // Sonucu belli olanlar: TP1 mi STOP mu önce geldi. İşlem hâlâ açık olabilir —
  // başarı sorusu zaten cevaplanmıştır.
  const bitmis = hepsi.filter(kararlandi);
  const girisOlmayan = hepsi.filter((s) => s.sonuc === SONUC.GIRIS_OLMADI).length;

  const bantlar = [
    { ad: '75+ (Strong)', alt: 75, ust: 101 },
    { ad: '62-75 (Long)', alt: 62, ust: 75 },
    { ad: '55-62 (Weak Long)', alt: 55, ust: 62 },
    { ad: '38-45 (Weak Short)', alt: 38, ust: 45 },
    { ad: '25-38 (Short)', alt: 25, ust: 38 },
    { ad: '25 altı (Strong Short)', alt: -1, ust: 25 },
  ];

  const bantIstatistik = bantlar.map((b) => {
    const grup = bitmis.filter((s) => s.longSkor >= b.alt && s.longSkor < b.ust);
    const o = ozet(grup);
    // Sistemin o banttaki ortalama tahmini
    const tahmin = grup.length ? grup.reduce((a, s) => a + (s.olasilik || 0), 0) / grup.length : null;
    return { ...b, ...o, tahmin, fark: o.adet ? o.basariOrani - tahmin : null };
  }).filter((b) => b.adet > 0);

  const yone = ['LONG', 'SHORT'].map((y) => ({
    yon: y, ...ozet(bitmis.filter((s) => s.yon === y)),
  })).filter((x) => x.adet > 0);

  // Pariteye göre (en az 3 kayıt olanlar)
  const pariteler = {};
  for (const s of bitmis) (pariteler[s.symbol] ||= []).push(s);
  const pariteIstatistik = Object.entries(pariteler)
    .map(([symbol, g]) => ({ symbol, ...ozet(g) }))
    .filter((x) => x.adet >= 3)
    .sort((a, b) => b.basariOrani - a.basariOrani);

  return {
    toplam: hepsi.length,
    acik: hepsi.filter(acikMi).length,
    bitmis: bitmis.length,
    girisOlmayan,
    genel: ozet(bitmis),
    bantlar: bantIstatistik,
    yone,
    pariteler: pariteIstatistik,
    yeterliVeri: bitmis.length >= 20,
  };
}
