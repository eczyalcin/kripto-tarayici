# Crypto Intelligence Dashboard

Binance vadeli işlemler piyasasını periyodik olarak tarayıp tek bir soruya veri odaklı
cevap veren karar destek sistemi:

> **"1000SHIBUSDT'de şu anda büyük para ne yapıyor?"**

Grafik yorumu değil, ölçülebilir veri: Open Interest, funding, taker akışı, spot/vadeli
CVD ayrışması, balina işlemleri, order book duvarları, likidasyonlar ve smart-money
yapı kırılımları tek bir skorda birleştirilir.

```
Crypto Intelligence Dashboard
├── Trend Engine          EMA20/50/100/200, Daily+Weekly VWAP, ATR, ADX, SuperTrend, HH/HL/LH/LL
├── Smart Money Engine    Liquidity Sweep, FVG, Order Block, BOS/CHOCH
├── Order Flow Engine     Spot CVD vs Futures CVD, agresif alıcı/satıcı, ayrışma
├── Derivatives Engine    OI (1s/4s/24s), Funding, Long/Short, Taker, Likidasyon, Basis
├── Whale Engine          100k+/250k+/500k+/1M+ emirler, iceberg tespiti
├── Order Book Engine     İlk 100 seviye, bid/ask duvarı, absorption, spoof
├── Risk Engine           Volatilite, funding maliyeti, kalabalıklık, pozisyon boyutu
├── Trade Setup Engine    Giriş bölgesi, stop, TP1/TP2/TP3, R/R, kaldıraç
└── AI Decision Engine    Ağırlıklı skor → Long/Short 0-100 → karar
```

---

## Hızlı Başlangıç

```bash
cd "/Users/yalcinbakir/claude codes/kripto tarayacısı"
```

Kurulum zaten yapıldı (`.venv` klasörü hazır). Sıfırdan kurmak gerekirse:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Veri kaynaklarını test edin:

```bash
.venv/bin/python run.py check
```

İlk taramayı çalıştırın:

```bash
.venv/bin/python run.py scan 1000SHIBUSDT
```

Arayüzü açın:

```bash
.venv/bin/python run.py serve
```

---

## Komutlar

| Komut | Açıklama |
|---|---|
| `run.py scan [SEMBOL]` | Tek parite için tam tarama, terminalde detaylı rapor |
| `run.py rank [SEMBOLLER...]` | Tüm pariteleri tarar, Long/Short skoruna göre sıralar |
| `run.py watch` | Zamanlayıcıyı başlatır: saatlik tam tarama + 5 dk türev kontrolü + alarmlar |
| `run.py collect` | Likidasyon WebSocket toplayıcısı (ayrı terminalde sürekli çalışmalı) |
| `run.py report` | Günlük raporu üretir (`reports/` klasörüne Markdown olarak yazar) |
| `run.py serve` | Streamlit arayüzünü açar (varsayılan http://localhost:8501) |
| `run.py check` | Tüm Binance uç noktalarını ve spot eşleşmesini test eder |

Sürekli çalıştırma için iki terminal:

```bash
.venv/bin/python run.py collect
```

```bash
.venv/bin/python run.py watch
```

---

## Skor sistemi nasıl çalışıyor?

Her motor **−1 ile +1** arasında ham skor üretir, `config.yaml` içindeki ağırlıkla
çarpılır ve toplam 0–100 aralığına normalize edilir.

| Gösterge | Ağırlık | Ne ölçer |
|---|---:|---|
| Trend | 18 | EMA dizilimi, ADX, SuperTrend, VWAP, yapı — 3 zaman dilimi (15m/1h/4h) |
| Open Interest | 15 | OI/fiyat matrisi (yeni long, yeni short, short covering, long tasfiye) + büyük hesap L/S |
| Funding | 10 | Sağlık ve kalabalıklaşma; aşırı pozitif funding kontra sinyal üretir |
| CVD / Order Flow | 12 | Spot + vadeli kümülatif delta ve Binance taker buy/sell dengesi |
| RSI | 6 | Momentum; 70+ aşırı alımda katkı azaltılır |
| MACD | 8 | Kesişim yönü + histogram ivmesi |
| Order Book | 14 | Yakın likidite dengesi, duvarlar, spoof, absorption |
| Whale | 11 | Büyük işlemlerin yön dengesi (büyük dilimler daha ağır) + iceberg |
| Likidasyon | 8 | Long/short likidasyon baskınlığı, squeeze tespiti |
| Smart Money | 12 | Likidite süpürme, BOS/CHOCH, yakın FVG'ler |

Karar eşikleri: `≥75 STRONG LONG · ≥62 LONG · ≥55 WEAK LONG · 45-55 NÖTR · ≤45 WEAK SHORT · ≤38 SHORT · ≤25 STRONG SHORT`

**Güven (confidence)** iki şeyin bileşimidir: kaç motorun veri üretebildiği (kapsama) ve
motorların birbiriyle ne kadar uyumlu olduğu (uzlaşma). Örneğin likidasyon toplayıcısı
çalışmıyorsa kapsama düşer ve güven azalır.

---

## Bilmeniz gereken üç teknik ayrıntı

**1. Likidasyon verisi WebSocket gerektirir.**
Binance likidasyonları REST ile vermiyor (`allForceOrders` kapatıldı); sadece
`<symbol>@forceOrder` akışından yayınlıyor. Bu yüzden `run.py collect` ayrı bir süreç
olarak sürekli çalışmalı — topladığı veriyi SQLite'a yazar, Derivatives Engine oradan
okur. Toplayıcı çalışmıyorsa likidasyon bileşeni "veri yok" der ve skora 0 katkı verir.

**2. Spot eşleşmesi otomatik çözülür.**
`1000SHIBUSDT` vadelide işlem görür ama spotta `SHIBUSDT` olarak, 1000 kat küçük fiyatla
listelenir. Sistem bu eşlemeyi (`1000`, `10000`, `1000000` önekleri dahil) otomatik
kurar ve karşılaştırmaları USDT cinsinden yapar — böylece spot/vadeli CVD kıyası doğru
ölçekte olur.

**3. Balina eşikleri sembole göre ölçeklenir.**
1000SHIBUSDT'de tek bir agg-trade nadiren 100.000 USDT'yi aşar; sabit eşiklerle balina
motoru sürekli boş dönerdi. `whale.auto_scale` açıkken, sabit eşiği yeterli işlem
aşmıyorsa eşikler o sembolün işlem dağılımının %99'luk dilimine göre yeniden hesaplanır
(taban alt sınırı 5.000 USDT). Arayüzde ve raporda ölçeklenmiş eşik açıkça belirtilir.
BTCUSDT gibi likit paritelerde sabit 100k/250k/500k/1M eşikleri kullanılmaya devam eder.

---

## Yapılandırma (`config.yaml`)

Tüm eşikler, ağırlıklar ve periyotlar buradan ayarlanır; kod değiştirmeye gerek yok.

```yaml
symbols: [1000SHIBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT]
primary_symbol: 1000SHIBUSDT

timeframes: {ltf: 15m, mtf: 1h, htf: 4h}   # mtf ana skorlama zaman dilimi

scheduler:
  scan_interval_minutes: 60      # tam tarama periyodu
  fast_interval_minutes: 5       # türev verisi hızlı kontrol
  daily_report_hour: 8

risk:
  account_size_usdt: 1000        # pozisyon boyutu hesabı için
  risk_per_trade_pct: 1.0
```

Yeni parite eklemek için `symbols` listesine yazmanız yeterli.

---

## Alarmlar

`config.yaml` → `alerts.rules` altında eşikler tanımlı:

- OI 1 saatte %10 değişirse
- Funding mutlak değeri %0.02'yi aşarsa
- Son 1 saatte 250.000 USDT üstü likidasyon
- Short/Long squeeze başlangıcı
- Balina alımı / satımı (eşik sembole göre ölçeklenir)
- BOS / CHOCH oluşumu
- Yeni FVG
- Likidite süpürülmesi
- AI kararının bölge değiştirmesi (3 puanlık histerezisle)

Aynı kural `cooldown_minutes` (varsayılan 45 dk) içinde tekrar tetiklenmez.

**Telegram/e-posta:** `.env.example` dosyasını `.env` olarak kopyalayıp doldurun, sonra
`config.yaml` içinde `alerts.channels.telegram` veya `.email` değerini `true` yapın.
Market verisi için API anahtarı gerekmez — bunlar sadece bildirim içindir.

---

## Dosya yapısı

```
core/       config, Binance REST istemcisi, göstergeler, SQLite depolama, loglama
engines/    trend, smart_money, derivatives, order_flow, whale, orderbook,
            risk, scoring, trade_setup
alerts/     kural motoru + konsol/Telegram/e-posta dağıtımı
collectors/ likidasyon WebSocket toplayıcısı
dashboard/  Streamlit arayüzü (8 sekme, Plotly grafikleri)
pipeline.py tarama hattı — tüm motorları çalıştırıp snapshot üretir
scheduler.py APScheduler görevleri
report.py   günlük Markdown raporu
run.py      komut satırı arayüzü
data/       SQLite veritabanı (snapshot, likidasyon, order book, balina, alarm geçmişi)
reports/    üretilen günlük raporlar
```

---

## Teknoloji notları

Önerdiğiniz yığından bilinçli olarak ayrıldığım üç nokta:

- **TA-Lib yerine saf pandas/numpy.** TA-Lib C kütüphanesi derleme gerektirir ve kurulum
  sık kırılır. Göstergeler `core/indicators.py` içinde Wilder yumuşatmasıyla yazıldı;
  RSI/ATR/ADX değerleri TradingView ile uyumludur.
- **PostgreSQL+TimescaleDB yerine SQLite.** Tek makinede saatlik tarama için fazlasıyla
  yeterli ve sıfır kurulum gerektiriyor. Şema standart SQL; hacim büyüyünce
  `core/storage.py` içindeki bağlantıyı değiştirmek yeterli.
- **CCXT yerine doğrudan REST.** İhtiyaç duyulan uçların çoğu (`openInterestHist`,
  `topLongShortPositionRatio`, `takerlongshortRatio`) CCXT'nin birleşik arayüzünde yok;
  zaten doğrudan çağırmak gerekiyordu.

Redis önbelleği yerine süreç içi TTL önbelleği kullanılıyor (`data.cache_ttl_seconds`);
tek süreçli çalışmada aynı işi görüyor.

---

## Sınırlar

- Sistem **karar desteği** üretir, otomatik emir göndermez. Borsa API anahtarı hiç
  kullanılmaz; sadece halka açık market verisi okunur.
- "Olasılık %" değeri geçmiş sonuçlarla kalibre edilmiş istatistiksel bir olasılık
  değil, skor ve güvenin bileşiminden türetilen göreli bir güç ölçüsüdür.
- Spoof ve absorption tespiti iki ardışık order book fotoğrafının karşılaştırılmasına
  dayanır; ilk taramada "karşılaştırma için ikinci tarama bekleniyor" uyarısı normaldir.
- Üretilen çıktılar otomatik veri özetidir, yatırım tavsiyesi değildir.
