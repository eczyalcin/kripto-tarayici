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

### En kısa yol: çift tıkla

Finder'da proje klasörünü açıp çift tıklayın:

| Dosya | Ne yapar |
|---|---|
| **Sistemi-Baslat.command** | Toplayıcı + zamanlayıcı + paneli birlikte başlatır (asıl kullanım) |
| **Panel-Ac.command** | Sadece paneli açar |
| **Tarama-Yap.command** | Tek tarama yapıp sonucu gösterir |

> İlk çift tıklamada macOS "geliştirici doğrulanamadı" diyebilir: dosyaya sağ tıklayıp
> **Aç** deyin, bir kez onayladıktan sonra bir daha sormaz.

### Terminalden: `./kripto`

```bash
cd "/Users/yalcinbakir/claude codes/kripto tarayacısı"
```

```bash
./kripto tara
```

| Kısa komut | Karşılığı |
|---|---|
| `./kripto tara [SEMBOL]` | Tek parite taraması |
| `./kripto piyasa` | Binance vadelideki **tüm** pariteleri tara |
| `./kripto panel` | Paneli aç |
| `./kripto panel --lan` | Paneli telefon/diğer bilgisayarlara aç |
| `./kripto sistem` | Toplayıcı + zamanlayıcı + panel birlikte |
| `./kripto sirala` | İzleme listesini skorla ve sırala |
| `./kripto check` | Bağlantı testi |

Her yerden sadece `kripto` yazabilmek için (bir kez çalıştırın, sonra yeni terminal açın):

```bash
echo "alias kripto='\"/Users/yalcinbakir/claude codes/kripto tarayacısı/kripto\"'" >> ~/.zshrc
```

Ardından hangi klasörde olursanız olun `kripto tara`, `kripto panel --lan` çalışır.

Sıfırdan kurulum gerekirse:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

---

## Komutların tamamı

| Komut | Açıklama |
|---|---|
| `run.py scan [SEMBOL]` | Tek parite için tam tarama, terminalde detaylı rapor |
| `run.py rank [SEMBOLLER...]` | Tüm pariteleri tarar, Long/Short skoruna göre sıralar |
| `run.py watch` | Zamanlayıcıyı başlatır: saatlik tam tarama + 5 dk türev kontrolü + alarmlar |
| `run.py collect` | Likidasyon WebSocket toplayıcısı (ayrı terminalde sürekli çalışmalı) |
| `run.py report` | Günlük raporu üretir (`reports/` klasörüne Markdown olarak yazar) |
| `run.py serve [--lan] [--port N]` | Streamlit arayüzünü açar (varsayılan http://localhost:8501) |
| `run.py check` | Tüm Binance uç noktalarını ve spot eşleşmesini test eder |

`./sistem-baslat.sh` üçünü birden çalıştırır; Ctrl+C hepsini kapatır.

---

## Tüm piyasa taraması

Binance vadelide **530 USDT sürekli paritesi** var. Hepsini 9 motorla taramak sembol
başına ~15 istek, toplam ~8.000 istek demek — Binance dakikada 2400 ağırlık verdiği için
bu yaklaşık 20 dakika sürer ve IP yasağı riski taşır. Bu yüzden tarama iki aşamalı:

**1. Ön eleme — tüm piyasa, saniyeler içinde**

Toplu uç noktalar tek istekte bütün sembolleri döndürür:

| Uç nokta | Ağırlık | Ne verir |
|---|---:|---|
| `/fapi/v1/ticker/24hr` | 40 | 530 paritenin fiyatı, 24s değişimi, hacmi |
| `/fapi/v1/premiumIndex` | 10 | 530 paritenin funding oranı |
| `/futures/data/openInterestHist` | 1 (sembol başına) | OI **ve** fiyat değişimi birlikte |

Her parite için **dikkat skoru** (0-100) üretilir. Bu skor yön değil *hareketlilik*
ölçer — "şu an bakmaya değer mi?" sorusunu yanıtlar: fiyat hareketi, OI değişimi,
funding aşırılığı, likidite ve OI/fiyat uyumsuzluğu. Ayrıca ucuz veriden bir **ön
eğilim** (LONG/SHORT/NÖTR) çıkarılır.

**2. Derin tarama — sadece öne çıkanlar**

Dikkat skoru en yüksek N parite (varsayılan 20) + izleme listeniz, tam 9 motorlu
hattan geçer ve gerçek Long/Short skorunu alır.

### Komutlar

```bash
./kripto piyasa
```

Ön eleme + en dikkat çekici 20 paritenin derin taraması.

```bash
./kripto piyasa --no-deep
```

Sadece ön eleme — bütün piyasaya ~16 saniyede göz atmak için.

```bash
./kripto piyasa --all --no-deep
```

Hacim filtresi olmadan **530 paritenin tamamı** (~40 saniye).

```bash
./kripto piyasa --top 40 --list 60
```

40 pariteyi derin tara, ön eleme tablosunda 60 satır göster.

### Ölçülen süreler

| Kapsam | Parite | Süre |
|---|---:|---:|
| Ön eleme (varsayılan 3M hacim filtresi) | 206 | ~16 sn |
| Ön eleme (`--all`, filtresiz) | 530 | ~41 sn |
| Ön eleme + 20 parite derin tarama | 530 → 20 | ~3 dk |

### Ayarlar (`config.yaml` → `market`)

```yaml
market:
  min_quote_volume_usdt: 3000000   # 1M→408 parite · 5M→160 · 10M→106 · 20M→67
  oi_enrich_top: 250               # kaç parite için OI verisi çekilsin
  deep_scan_top: 20                # kaç parite tam taransın
  always_include_watchlist: true   # `symbols` listeniz her zaman derin taransın
```

Zamanlayıcı (`./kripto sistem`) bu taramayı 4 saatte bir kendiliğinden yapar
(`scheduler.market_scan_hours`, 0 yazarsanız kapanır).

Panelde **🌍 Tüm Piyasa** sekmesinden sonucu filtreleyerek görebilir, düğmeyle yeniden
tarayabilirsiniz.

> Binance ağırlık limitini istemci kendisi takip eder: limitin %80'ine gelindiğinde
> dakika penceresi dolana kadar otomatik bekler, böylece IP yasağı riski oluşmaz.

---

## Telefondan ve diğer bilgisayarlardan erişim

### A) Aynı Wi-Fi ağındayken (en kolay, ücretsiz)

Mac'te paneli ağa açın:

```bash
./kripto panel --lan
```

Komut ekrana şuna benzer bir adres yazar — telefonunuzun veya Windows PC'nizin
tarayıcısına bu adresi girin:

```
http://192.168.1.103:8501
```

iPhone'da Safari → Paylaş → **Ana Ekrana Ekle** derseniz uygulama gibi açılır.

Bilinmesi gerekenler: Mac açık ve uyanık olmalı (Sistem Ayarları → Kilit Ekranı →
"ekran kapalıyken otomatik uyku" kapatılabilir), IP adresi router yeniden başlayınca
değişebilir, ve panel yerel ağdaki herkese açıktır — bu yüzden parola koyun:

```bash
cp .env.example .env
```

`.env` içindeki `DASHBOARD_PASSWORD=` satırına bir parola yazın. Panel açılışta
parola sorar.

### B) Ev dışındayken — Tailscale (önerilen)

Ücretsiz, kurulumu birkaç dakika, port yönlendirme veya sabit IP gerekmez. Cihazlarınız
arasında şifreli özel bir ağ kurar; panel internete açılmaz.

1. [tailscale.com](https://tailscale.com) → ücretsiz hesap
2. Mac'e, telefona ve Windows PC'lere Tailscale uygulamasını kurup aynı hesapla girin
3. Mac'te `./kripto panel --lan` çalıştırın
4. Tailscale'in Mac'e verdiği adresi kullanın: `http://100.x.x.x:8501`

Artık dünyanın neresinde olursanız olun panele erişirsiniz.

### C) Windows PC'de programın kendisini çalıştırmak

Panel yerine programın tamamını Windows'ta çalıştırmak isterseniz — Mac'e hiç bağlı
olmadan, kendi taramasını yapar:

1. [python.org/downloads](https://www.python.org/downloads/) → Python 3.11+ kurun.
   Kurulumda **"Add python.exe to PATH"** kutusunu işaretleyin.
2. Projeyi Windows'a kopyalayın (GitHub bölümüne bakın)
3. `windows\kurulum.bat` dosyasına çift tıklayın — sanal ortamı kurar, paketleri
   indirir, bağlantı testi yapar
4. Sonrasında: `windows\Sistemi-Baslat.bat` · `windows\Panel-Ac.bat` ·
   `windows\Tarama-Yap.bat`

Veritabanı her makinede ayrıdır; Windows PC kendi taramalarını kendi `data/market.db`
dosyasına yazar.

---

## GitHub ile senkronizasyon

Kod tek yerde dursun, Windows PC'lere ve ileride başka makinelere kolayca gitsin diye
proje git deposu olarak hazırlandı (ilk commit atıldı). `.gitignore` sayesinde `.env`,
`.venv/`, veritabanı ve loglar depoya **girmez**.

GitHub'da **private** bir repo açın, sonra:

```bash
git remote add origin https://github.com/KULLANICI_ADIN/kripto-tarayici.git
```

```bash
git branch -M main && git push -u origin main
```

Windows PC'de:

```bash
git clone https://github.com/KULLANICI_ADIN/kripto-tarayici.git
```

Sonra `windows\kurulum.bat`. Değişiklik yaptığınızda Mac'te `git push`, Windows'ta
`git pull` yeterli.

> Repoyu **private** açın. Kod gizli bilgi içermiyor (API anahtarı kullanılmıyor) ama
> ayarlarınız, izlediğiniz pariteler ve stratejik eşikleriniz herkese açık olmasın.

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
