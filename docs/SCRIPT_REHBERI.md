# 10 Script — Ne İşe Yarar, Ne Zaman Çalıştırılır

> Bu belge `scripts/` klasöründeki 10 betiğin **sözleşmesidir**.
> Her betiğin ne okuduğu, ne yazdığı ve hangi sırada çalıştığı burada.
>
> Neden gerekli: 24 Kasım'da fark edildi ki `02` ve `04` **aynı dosyaya
> farklı şema** yazıyordu. Sırayla çalıştırınca biri diğerini eziyor ve
> kalibrasyon zinciri bozuluyordu. Artık ayrı dosyalar + test
> (`tests/test_script_contract.py`).

---

## Tek bakışta

| # | Script | Ne yapar | Ağ | Çıktı |
|---|---|---|---|---|
| **01** | `collect_data.py` | OpenSky'dan **gerçek** uçuş izi toplar | ✅ gerekli | `data/raw/opensky/*.csv` |
| **02** | `analyze_and_optimize.py` | **★ ANA ANALİZ** — yakıt, CO₂, 4 optimizasyon | ❌ | `batch_results.json` |
| **03** | `generate_outputs.py` | Müşteriye sunulabilir HTML/JSON rapor | ❌ | `reports/*.html`, `*.json` |
| **04** | `generate_professional_demo.py` | 235 sentetik uçuşla **demo** üretir | ❌ | `demo_batch_results.json` |
| **05** | `saf_scenario_analysis.py` | SAF karışım senaryoları (%10–%50) | ❌ | ekran + tablo |
| **06** | `seed_real_data.py` | **SENTETİK** uçuş izi üretir (gerçek değil!) | ❌ | `data/raw/opensky/*.csv` |
| **07** | `live_flight_scrapper.py` | Tek uçuşu **canlı** ADSB.lol'dan izler | ✅ gerekli | `data/raw/opensky/ARR_LIVE_*.csv` |
| **08** | `automated_fleet_tracker.py` | PGT/THY/SXS filosunu **canlı** izler | ✅ gerekli | `data/raw/opensky/ARR_*.csv` |
| **09** | `clean_and_backup.py` | Temizlik / yedek / gerçek-veriye geçiş | ❌ | yedek arşivi |
| **10** | `10_pre_real_ingestion_demo.py` | **★ MÜŞTERİ VERİSİ → KALİBRASYON** | ❌ | `data/calibrations/*.json` |

★ = asıl işi yapan iki script. Diğerleri bunları besler veya raporlar.

---

## Hangi sırada çalıştırılır

### Senaryo A — Elimde hiçbir şey yok, sistemi görmek istiyorum

```bash
python scripts/02_analyze_and_optimize.py      # 14 hazır uçuşu analiz et
python scripts/03_generate_outputs.py          # rapor üret
python scripts/10_pre_real_ingestion_demo.py   # kalibrasyon zincirini gör
```

Bu üç komut **ağsız** çalışır ve tüm sistemi gösterir. Sunum öncesi
hızlı kontrol için bunu kullan.

### Senaryo B — Gerçek veri toplamak istiyorum

```bash
# 1) Ya tek seferlik toplama (OpenSky, hesap gerekir)
python scripts/01_collect_data.py

# 2) Ya da canlı filo takibi (hesap GEREKMEZ, ADSB.lol)
python scripts/08_automated_fleet_tracker.py --airlines PGT,THY,SXS

# 3) Sonra analiz
python scripts/02_analyze_and_optimize.py
```

`01` ve `08` **internet ister**. Sandbox'ta çalışmaz, kendi makinende
çalışır.

### Senaryo C — Müşteri yakıt verisi geldi (asıl ticari akış)

```bash
# 1) Müşterinin CSV'sini doğrula + yükle
python -m src.ingestion.customer_fuel_ingestor \
    --csv data/customer_fuel/musteri.csv --tenant pegasus

# 2) Kalibrasyon zinciri
python scripts/10_pre_real_ingestion_demo.py

# 3) Kalibre edilmiş modelle yeniden analiz
python scripts/02_analyze_and_optimize.py
```

`10` üç kapıdan geçirir: **≥12 eşleşme → ≥%4 iyileşme → ≤%6,5 kalan
sapma.** Biri düşerse `REJECTED` der — bu doğru davranış.

---

## Her script tek tek

### 01 — `collect_data.py` · Gerçek uçuş izi toplama

**Ne yapar:** OpenSky Network API'sinden **tamamlanmış** uçuşları
(arrivals) çeker. Planlanan değil, gerçekleşmiş.

**Neden arrivals:** Kalkış verisi yarım kalır (uçuş bitmemişse yakıt
bilinmez). Varış verisi tam profili verir.

**Girdi:** OpenSky hesabı (`.env` içinde `OPENSKY_USER/PASS`)
**Çıktı:** `data/raw/opensky/ARR_<CALLSIGN>_<ORIG>_<DEST>.csv`
**Ağ:** Gerekli · **Süre:** ~1–2 dk / uçuş başına

```bash
python scripts/01_collect_data.py --help
```

> ⚠️ Bugün depoda bu klasördeki dosyalar **sentetik** (bkz. `06`).
> Gerçek toplama yapıldığında üzerine yazılır.

---

### 02 — `analyze_and_optimize.py` · ★ ANA ANALİZ

**Ne yapar:** Her uçuş için fizik modelini çalıştırır:

1. Yakıt tüketimi (Breguet + polar + ağırlık)
2. CO₂ emisyonu (EI faktörleri)
3. **4 optimizasyon:**
   - İrtifa (optimum FL, step climb)
   - Cost Index (hız)
   - Tankering (yakıt nereden alınmalı)
   - Rota verimliliği
4. Dürüstlük etiketi (`GERÇEK VERİ YOK` / `synthetic_fallback`)

**Girdi:** `data/raw/opensky/*.csv`
**Çıktı:** `reports/optimizations/batch_results.json`
**Ağ:** Gerekmez · **Süre:** ~20 sn (14 uçuş)

```bash
python scripts/02_analyze_and_optimize.py
# → ⛔ GERÇEK VERİ YOK — 14 sentetik.
# → 💾 Kaydedildi: reports/optimizations/batch_results.json
```

> **Kritik:** Bu dosya **kalibrasyon zincirinin** girdisidir. Şeması
> bozulursa `10` çalışmaz. `tests/test_script_contract.py` bunu korur.

---

### 03 — `generate_outputs.py` · Rapor üretimi

**Ne yapar:** `02`'nin çıktısını müşteriye sunulabilir hâle getirir:

- Filo raporu (HTML → PDF)
- CORSIA/MRV uyumlu emisyon raporu
- Vaka çalışması özeti
- Veri kalitesi değerlendirmesi
- (Bonus) LinkedIn post + cold email taslakları

**Girdi:** `batch_results.json`
**Çıktı:** `reports/GreenWing_Fleet_Report_*.html`,
`GreenWing_CaseStudy_*.html`, `data_quality_*.json`
**Ağ:** Gerekmez · **Süre:** ~1 sn

```bash
python scripts/03_generate_outputs.py
# → HTML'i tarayıcıda aç → Ctrl+P → PDF
```

> Tarihli çıktılar `.gitignore`'da — depo kirlenmez, yeniden üretilebilir.

---

### 04 — `generate_professional_demo.py` · Demo üretici

**Ne yapar:** **235 sentetik uçuş** üretir (SunExpress/Pegasus/THY
gerçek rotaları üzerinde). Amaç: sunumda dolu ekran göstermek.

**Girdi:** Yok (rota tablosu koda gömülü)
**Çıktı:** `reports/optimizations/demo_batch_results.json`
**Ağ:** Gerekmez · **Süre:** ~80 sn

> ⚠️ **Bu çıktı DEMO'dur, analiz değildir.** Daha önce `02` ile aynı
> dosyaya yazıyordu ve analizi eziyordu (#95). Artık ayrı dosya.
> `10` kalibrasyonu **her zaman** `02`'nin çıktısından beslenir.

---

### 05 — `saf_scenario_analysis.py` · SAF senaryoları

**Ne yapar:** Sürdürülebilir havacılık yakıtı (SAF) karışım oranlarını
(%10, %20, %30, %50 HEFA + PtL) simüle eder. Şunları hesaplar:

- Kütlesel yakıt tüketim değişimi (LHV farkından)
- Egzoz CO₂ vs **LCA (Well-to-Wake)** CO₂ ayrımı
- CORSIA/EU-ETS ofset etkisi
- Maliyet
- **ASTM D7566 aromatik limiti** uyarısı (%8 altına düşerse)

**Girdi:** Yok
**Çıktı:** Ekran tablosu
**Ağ:** Gerekmez · **Süre:** <1 sn

```bash
python scripts/05_saf_scenario_analysis.py
```

> Bu script projenin **en teknik olarak sağlam** parçalarından biri:
> egzoz CO₂ ile LCA CO₂'yi ayırıyor ve saf SAF'ın aromatik limiti
> nedeniyle blend edilmesi ZORUNLU olduğunu söylüyor. Havayolunda
> sürdürülebilirlik ekibi bunu duyunca ciddiye alır.

---

### 06 — `seed_real_data.py` · Sentetik seeder (⚠️ dikkat)

**Ne yapar:** **GERÇEK VERİ DEĞİL.** Matematiksel olarak sentetik uçuş
profilleri üretir (tırmanma, cruise, alçalma, holding, step climb).

**Girdi:** Yok
**Çıktı:** `data/raw/opensky/ARR_*.csv` (15 uçuş)
**Ağ:** Gerekmez · **Süre:** <1 sn

```bash
python scripts/06_seed_real_data.py
# → 🎉 Toplam 15 adet gerçekçi uçuş verisi başarıyla arşivlendi.
```

> ⚠️ **"gerçekçi" ≠ "gerçek".** Script bunu kendi docstring'inde
> söylüyor ama çıktı mesajı yanıltıcı: "gerçekçi uçuş verisi".
> Bu, denetim #89'un (sentetik veri gizleme) küçük bir kalıntısı.
> Veri `collection_method` alanında `synthetic` olarak işaretlenir ve
> `02` çıktısında `⛔ GERÇEK VERİ YOK` görünür — yani sonuçta
> yanıltmıyor, ama mesaj düzeltilmeli.

**Ne zaman kullanılır:** Test/demo verisi gerektiğinde. Gerçek analiz
için **asla.**

---

### 07 — `live_flight_scrapper.py` · Tek uçuş canlı izleme

**Ne yapar:** Belirli bir çağrı işaretini (ör. `PGT120`) ADSB.lol
üzerinden **canlı** izler, pozisyonları CSV'ye yazar.

**Girdi:** `--callsign`
**Çıktı:** `data/raw/opensky/ARR_LIVE_<CALLSIGN>_<TS>.csv`
**Ağ:** Gerekli (API anahtarı GEREKMEZ) · **Süre:** uçuş bitene kadar

```bash
python scripts/07_live_flight_scrapper.py --callsign PGT120 --interval 30
```

> Uçağın **o anda havada** olması gerekir. Sandbox'ta ağ kapalı →
> `SSLZeroReturnError` verir. Kendi makinende çalışır.

---

### 08 — `automated_fleet_tracker.py` · Filo takibi

**Ne yapar:** PGT/THY/SXS filosunun **tüm aktif uçuşlarını** arka planda
izler, iniş tespit edince dosyayı kapatır. `07`'nin çoklu-uçuş sürümü.

**Girdi:** `--airlines`, `--min-pts`, `--timeout`, `--interval`
**Çıktı:** `data/raw/opensky/ARR_<AIRLINE>_<CALLSIGN>_*.csv`
**Ağ:** Gerekli · **Süre:** saatler (sürekli)

```bash
python scripts/08_automated_fleet_tracker.py --airlines PGT,THY,SXS
```

> Gerçek veri biriktirmenin **en pratik yolu** bu. Bir gece çalıştır,
> sabaha 50+ gerçek uçuşun olur. Sonra `02` → gerçek analiz.
>
> **Not:** ADS-B pozisyon verir, **yakıt vermez.** Yakıt, fizik modeliyle
> hesaplanır. Gerçek yakıt için havayolundan veri gerekir (`10`).

---

### 09 — `clean_and_backup.py` · Temizlik ve geçiş

**Ne yapar:** 5 mod:

| Mod | Ne yapar |
|---|---|
| `backup` | Veriyi tarihli arşive yedekler |
| `restore` | Yedekten geri yükler |
| `clean` | Geçici/bozuk dosyaları temizler |
| `clean-demos` | Demo/mock kalıntılarını siler (güvenli) |
| `reset-for-real` | **Gerçek veri gelince** demo verisini tamamen temizler |

**Girdi:** `--mode`, `--target`
**Çıktı:** Yedek arşivi
**Ağ:** Gerekmez

```bash
python scripts/09_clean_and_backup.py --mode backup
python scripts/09_clean_and_backup.py --mode clean-demos --yes-i-am-sure
```

> `--yes-i-am-sure` **veri silen** modlar için zorunlu — kazara silmeyi
> engeller.

**Ne zaman kullanılır:** Bir havayoluyla anlaşıp gerçek veri aldığında
`reset-for-real` ile tüm sentetik veriyi temizle. Sunumda "bu 14 sentetik
uçuş" demek zorunda kalmamak için değil — **doğru** olduğu için.

---

### 10 — `10_pre_real_ingestion_demo.py` · ★ MÜŞTERİ → KALİBRASYON

**Ne yapar:** Ticari iddianın **kalbi**. Müşterinin yakıt verisini alır,
kendi uçuş izleriyle eşleştirir, modeli kalibre eder, doğruluğu ölçer.

**Üç kapı (biri düşerse REJECTED):**

| Kapı | Eşik | Ne demek |
|---|---|---|
| Eşleşme | ≥ 12 uçuş | Müşteri satırı ↔ uçuş izi eşleşmeli |
| Model iyileşmesi | ≥ %4 | Kalibrasyon hatayı gerçekten azaltmalı |
| Kalan sapma | ≤ %6,5 | Kalibrasyon sonrası ortalama hata |

**Girdi:** `data/customer_fuel/*.csv` (veya `--mock`)
**Çıktı:** `data/calibrations/*.json`
**Ağ:** Gerekmez · **Süre:** ~12 sn

```bash
python scripts/10_pre_real_ingestion_demo.py
```

**Bugünkü durum:**

```
Matching complete: 13 matched out of 13 fuel records   ✓ %100 eşleşme
Calibration complete: cd0=1.2495, sfc=1.1500, +17.2%    ✓ çalışıyor
Quality gate FAILED: imp=17.2%, after=22.6%             ✗ sahte veri
→ ❌ PIPELINE REJECTED
```

Son satır **doğru davranış**: sentetik veriyle kalibrasyonu kabul
etmiyor. Gerçek veri geldiğinde aynı komut `SUCCESS` verecek.

---

## Bağımlılık haritası

```
  01 (OpenSky) ──┐
                 ├──► data/raw/opensky/*.csv ──► 02 ──► batch_results.json
  06 (sentetik) ─┤                                  │
  07 (canlı) ────┤                                  ├──► 03 (rapor)
  08 (filo) ─────┘                                  └──► 10 (kalibrasyon)
                                                        ▲
  04 (demo) ──► demo_batch_results.json  ──(YALNIZ yoksa)──┘
```

**Kritik kural:** `02`'nin çıktısı varsa `10` onu kullanır. `04`'ün
demoyu 235 uçuşla ezmesi **artık mümkün değil** (#95 + test).

---

## Hangi script ne zaman ÇALIŞTIRILMAZ

| Script | Çalıştırma | Neden |
|---|---|---|
| `06` | Gerçek analizden önce | Sentetik veriyi gerçek sanabilirsin |
| `09 --reset-for-real` | Yedek almadan | Geri dönüşü yok |
| `04` | Müşteri sunumu sonrası | Demo verisi kalibrasyonu boşuna kirletir |

---

## Bilinen sınırlar

| Konu | Durum |
|---|---|
| `01`, `07`, `08` | Ağ gerekir — sandbox'ta çalışmaz |
| `06` çıktı mesajı | "gerçekçi" diyor, "sentetik" demeli (düzeltilecek) |
| `03` HTML | PDF'e çevirme manuel (Ctrl+P) |
| Gerçek yakıt | Hiçbir script vermez — havayolundan gelir |

---

## Doğrulama

```bash
# Script sözleşmesi (6 test) — #95 geri gelmesin
python -m pytest tests/test_script_contract.py -v

# Kalibrasyon zinciri (7 test)
python -m pytest tests/test_ingestion_pipeline.py -v
```
