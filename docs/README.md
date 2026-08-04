# Kripto Panel — telefon sürümü (web uygulaması)

Bu klasör, Python programının **tarayıcıda çalışan** sürümüdür. GitHub Pages'te
yayınlanır ve telefonun kendisi Binance'e bağlanır — arada sunucu yoktur.

## Neden ayrı bir sürüm?

GitHub Pages sadece hazır dosya (HTML/JS) yayınlar, Python çalıştıramaz. Binance'in
tüm market-data uçları `Access-Control-Allow-Origin: *` gönderdiği için tarama
mantığı JavaScript'e çevrildiğinde hesaplama doğrudan telefonda yapılabiliyor.

Sonuç: Mac kapalıyken, mobil veriyle, dünyanın her yerinden çalışır.

## Python sürümüyle farkı

| | Python (Mac/Pi/VPS) | Bu sürüm (telefon) |
|---|---|---|
| 9 analiz motoru | ✅ | ✅ |
| Tüm piyasa taraması | ✅ | ✅ |
| Skor · risk · trade setup | ✅ | ✅ |
| Spoof / absorption | ✅ | ✅ (ikinci taramadan sonra) |
| Likidasyon geçmişi | ✅ | ❌ 7/24 websocket ister |
| Otomatik tarama + alarm | ✅ | ❌ sadece elle tarama |
| Telegram / e-posta | ✅ | ❌ |
| Sunucu gerekir mi | Evet | **Hayır** |

Likidasyon bileşeni "veri yok" sayılır; skor bunu bilir ve güven oranını düşürür.

## Doğruluk

Aynı anda çalıştırılan iki sürümün karşılaştırması (1000SHIBUSDT):

| Gösterge | JavaScript | Python |
|---|---|---|
| ADX | 20.7 | 20.7 |
| RSI | 55.93 | 55.93 |
| ATR % | 0.922 | 0.922 |
| EMA20 | 0.00499038928 | 0.00499038930 |
| OI 1s | −0.177 | −0.177 |
| Funding | %0.00447 | %0.00447 |
| Büyük hesap L/S | 1.5287 | 1.5287 |
| Karar | WEAK LONG 57.1 | WEAK LONG 57.9 |

Deterministik göstergeler birebir aynı. Küçük skor farkı, order book ve son
işlemlerin iki çağrı arasında değişmesinden kaynaklanır.

## Dosyalar

```
docs/
├── index.html          arayüz iskeleti + PWA meta etiketleri
├── manifest.json       ana ekrana ekleme bilgileri
├── sw.js               service worker (uygulama kabuğu önbelleği)
├── css/style.css       koyu/açık tema, mobil öncelikli
├── icons/              uygulama simgeleri
└── js/
    ├── binance.js      API istemcisi (fetch + TTL önbellek + tekrar deneme)
    ├── indicators.js   EMA, RSI, MACD, ATR, ADX, SuperTrend, VWAP, swing
    ├── engines.js      Trend · Smart Money · Derivatives · Order Flow · Whale · Order Book
    ├── scoring.js      AI skor · risk · trade setup
    ├── scan.js         tarama hattı + piyasa ön elemesi
    ├── store.js        localStorage (order book geçmişi, skor geçmişi)
    ├── charts.js       bağımlılıksız SVG grafikler
    ├── config.js       varsayılan ayarlar
    └── app.js          arayüz
```

Harici kütüphane yok, derleme adımı yok. `docs/` klasörünü herhangi bir statik
sunucuda açmak yeterli.

## Yerelde denemek

```bash
cd docs && python3 -m http.server 8600
```

Sonra `http://localhost:8600` adresini açın.

## Ölçülen süreler (masaüstü, fiber)

| İşlem | Süre | Veri |
|---|---:|---:|
| Tek parite tam tarama | ~12 sn | ~1.5 MB |
| Piyasa ön elemesi (196 parite) | ~43 sn | ~1 MB |
| Ön eleme + 10 parite derin tarama | ~3 dk | ~5 MB |

Mobil veride biraz daha uzun sürer. Ayarlar sekmesinden "işlem akışı sayfası"
değerini 1'e düşürerek veri kullanımını yarıya indirebilirsiniz.
