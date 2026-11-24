# GreenWing Analytics — Kod Atlası

> **Bu doküman ne için:** Depodaki her modülün **ne işe yaradığını** ve
> kullandığı **sayıların nereden geldiğini** tek yerde gösterir.
> "Bu 0.85 nereden çıktı?" sorusunun cevabı burada.
>
> **Kural:** Kaynağı yazılı olmayan sayısal sabit kabul edilmez.
> `python tools/full_audit.py --layer K5` bunu otomatik denetler
> (K5 kontrol listesinde "kaynaksız sabit" maddesi).

Son güncelleme: 2026-11-22 · 92 dosya / ~50.000 satır / 33 çekirdek modül

---

## 0. Bir dakikada mimari

```
                    ┌──────────────────────────────┐
   Radar / CSV ────►│ VERİ KATMANI                 │
   (OpenSky,        │ src/data_collection/         │
    ADSB.lol,       │ src/ingestion/               │
    müşteri CSV)    │ src/validation/              │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │ FİZİK KATMANI                │
                    │ src/models/                  │
                    │  atmosphere → aircraft_perf  │
                    │  → fuel_model → emission     │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │ ANALİZ KATMANI               │
                    │ src/analysis/ (faz, uçuş,    │
                    │  filo, belirsizlik, benchmark)│
                    │ src/optimization/ (irtifa,   │
                    │  hız, tankering, kalibrasyon)│
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │ SUNUM KATMANI                │
                    │ src/reporting/, webapp/      │
                    └──────────────────────────────┘
```

**Tek yönlü bağımlılık kuralı:** Üst katman alt katmanı import eder,
tersi olmaz. `src/units.py` hiçbir şeyi import etmez — herkes onu okur.
Bu yüzden tek kaynak olabiliyor.

---

## 1. Temel taşlar (her şeyin dayandığı 4 dosya)

| Dosya | Satır | Ne yapar | Sayıları nereden |
|---|---:|---|---|
| `src/units.py` | 2.338 | Birim dönüşümü + fizik sabitleri (**tek kaynak**) | Tanımlar (0.3048 ft, 1852 m nmi) ve türetmeler (1852/3600 kn) |
| `src/models/atmosphere.py` | 733 | ISA standart atmosfer: T, P, ρ, ses hızı | ICAO Doc 7488/3 — `units.py`'den okur |
| `config/assumptions.py` | 1.185 | İş varsayımları: fiyat, gerçekleşme oranı, blok saat | IATA Fuel Monitor, literatür bandı |
| `config/aircraft_database.yaml` | 1.100 | 14 uçak tipi: ağırlık, kanat, polar, motor | Boeing/Airbus ACAP, OpenAP, ICAO EDB |

### 1.1 Neden `units.py` bu kadar önemli?

Aynı sabit daha önce **5 ayrı dosyada** elle yazılıydı:

```
src/units.py              0.514444
config/settings.py        0.514444
src/models/atmosphere.py  0.3048
src/models/fuel_model.py  9.80665
src/utils.py              0.3048
```

İkisinde yuvarlama vardı (`2.20462` vs `2.20462262`). Bir gün birini
düzeltip diğerini unutmak "aynı hesap iki farklı sonuç veriyor"
hatasına yol açar. **Denetim #86** bunu tek kaynağa indirdi.

### 1.2 Sabit türleri

| Tür | Örnek | Değişir mi? |
|---|---|---|
| **Tanım** (anlaşmayla) | 0.3048 m/ft, 1852 m/nmi, 9.80665 m/s² | **ASLA** |
| **Türetilmiş** | 1852/3600 = 0.5144444 kn, p₀/(R·T₀) = 1.225 | Kaynağı değişirse |
| **Ölçüm/standart** | Jet A-1 0.804 kg/L, EI(CO₂) 3.16 | Yeni standarda göre |
| **Varsayım** | yakıt fiyatı 0.85 $/kg, gerçekleşme %65 | Pazar/veri ile |

---

## 2. `src/models/` — Fizik

| Dosya | Satır | Ne yapar | Kritik sayılar ve kaynağı |
|---|---:|---|---|
| `atmosphere.py` | 733 | T/P/ρ/ses hızı; ISA + sapma | ICAO Doc 7488/3 |
| `aircraft_performance.py` | 822 | Kaldırma, sürükleme, L/D, buffet | OpenAP polar, FAR 25.251 |
| `fuel_model.py` | 1.725 | Yakıt akışı; EDB veya tahmin yolu | ICAO EDB, OpenAP `ff_to` |
| `emission_model.py` | 1.630 | CO₂/H₂O/SO₂/NOₓ + CORSIA | EI(CO₂)=3.16 (CORSIA), EI(SO₂)=0.8 g/kg |
| `wind_model.py` | 210 | Rüzgâr profili + rota bileşeni | Kuşak ortalaması; `is_measured=False` |
| `wind_gfs.py` | 368 | 3 kademeli zincir (GFS → Seasonal → NoWind) | GFS 0.25° GRIB2 |
| `saf_model.py` | 251 | SAF karışım oranı ve CO₂ azaltımı | CORSIA SAF kılavuzu |
| `fuel_thermal_model.py` | 219 | Yakıt sıcaklığı, donma noktası | Jet A-1 −47 °C (ASTM D1655) |
| `blockchain_sealer.py` | 117 | Sonuçların değiştirilemez mührü (SHA-256 zincir) | — |

### 2.1 Kullanılan her sayının kaynağı

| Sayı | Değer | Nerede | Kaynak ve türetimi |
|---|---|---|---|
| `_GRAVITY` | 9.80665 m/s² | units.py | CGPM 1901 — **tanım** |
| `_R_AIR` | 287.055 J/(kg·K) | units.py | 8.314462618 / 0.0289647 (CODATA 2018 + US Std Atm 1976) |
| `_ISA_RHO0` | 1.22499 | units.py | 101325/(287.055×288.15) — **türetilmiş** (elle 1.225 yazmak 10 ppm kayar) |
| `_KTS_TO_MS` | 0.5144444… | units.py | 1852/3600 — **türetilmiş** (0.514444 yazmak 0,86 ppm kayar) |
| `_KG_TO_LBS` | 2.20462262 | units.py | 1/0.45359237 (1959 anlaşması) |
| EI(CO₂) | 3,16 kg/kg | emission_model | CORSIA ETM: Jet A-1 yanması, karbon kütle dengesi |
| EI(H₂O) | 1,24 kg/kg | emission_model | H/C oranından (≈1.92) stokiyometri |
| EI(SO₂) | 0,799 g/kg | emission_model | (64.066/32.065) × 0.4 g S/kg — **türetilmiş** (denetim #87) |
| `_JET_A1_LHV` | 43,15 MJ/kg | emission_model | CRC Handbook / ASTM D1655 |
| Jet A-1 yoğunluk | 0,804 kg/L | units.py | ASTM D1655 (0.775–0.840 bandı) |
| Polar `K`, `e` | tip bazlı | aircraft_database.yaml | OpenAP dragpolar (uçuş verisinden fit) |
| `AR` | span²/S | aircraft_database.yaml | Boeing/Airbus ACAP geometrisi |
| `AR_aerodynamic` | 9,453 (B738) | aircraft_database.yaml | OpenAP fit bazı: **winglet'siz** 34,32 m (denetim #85) |

> **Uyarı (denetim #85):** B738'in iki AR'si var ve ikisi de doğru:
> geometrik 10,280 (winglet dahil 35,79 m) ve aerodinamik 9,453
> (winglet'siz 34,32 m, poların fit bazı). Karıştırılırsa K/e
> tutarsızlığı %7,7 çıkar. Kural `tests/test_aircraft_data_provenance.py`
> içinde kilitli.

---

## 3. `src/data_collection/` + `src/ingestion/` — Veri

| Dosya | Satır | Ne yapar | Kritik sayılar |
|---|---:|---|---|
| `airport_database.py` | 1.042 | 60+ havalimanı; uçak→havalimanı eşleştirme | 8/15/25 NM yarıçapları (ICAO Doc 8168 SID/STAR konisi) |
| `opensky_collector.py` | 975 | OpenSky OAuth2 + tarihsel veri | 30 s timeout, saatte 400 istek (OpenSky docs) |
| `customer_fuel_ingestor.py` | 341 | Müşteri yakıt CSV'sini al ve normalize et | 16 kolon / 8 zorunlu |
| `flight_matcher.py` | 92 | Gerçek yakıt kaydı ↔ radar izi eşleştirme | skor eşiği 30 |
| `calibration_pipeline.py` | 190 | Uçtan uca kalibrasyon akışı | min 30 uçuş (istatistiksel anlamlılık) |

### 3.1 Neden `tenant_id` her yerde var?

Ticari üründe her havayolu ayrı bir kiracıdır. Aynı kod tabanı birden
fazla müşteriye hizmet eder; veri yolları `tenant_id` ile ayrışır.
Bu olmadan 2. müşteri geldiğinde veriler karışır → KVKK/GDPR ihlali.

---

## 4. `src/analysis/` — Analiz

| Dosya | Satır | Ne yapar | Kritik sayılar |
|---|---:|---|---|
| `fleet_analyzer.py` | 1.646 | Filo geneli: toplam yakıt, tasarruf, CO₂ | yakıt fiyatı 0,85 $/kg (IATA Monitor) |
| `phase_segmentation.py` | 1.222 | İzi fazlara ayır (taksi/kalkış/tırmanış/seyir/alçalma) | 500 fpm, 10.000 ft, 15.000 ft (ICAO Doc 8168) |
| `flight_analyzer.py` | 1.199 | Tek uçuş: yakıt dengesi, step climb kazancı | ağırlık faktörü 0,97/0,95/0,92/0,90 |
| `sensitivity.py` | 1.037 | Hangi parametre sonucu ne kadar etkiler | ±%10 tarama aralığı |
| `uncertainty.py` | 836 | Güven aralığı; belirsizlik bütçesi | rüzgâr ±%22,2 (ölçülmemişse) |
| `benchmark.py` | 835 | Sonucu bağımsız kaynakla karşılaştır | ICAO EDB referans yakıtı |
| `fuel_thermal_model.py` | 219 | Yakıt sıcaklık profili | −47 °C donma (ASTM D1655) |

### 4.1 Belirsizlik nasıl hesaplanıyor?

Her sonuç **tek sayı değil, aralık** olarak sunulur:

```
yakıt = 6.450 kg ± %22,2    ← rüzgâr ölçülmemişse (GFS yok)
yakıt = 6.450 kg ± %4       ← GFS rüzgârı varsa
```

Belirsizlik bütçesi bileşenleri (`uncertainty.py`):
- Rüzgâr: `is_measured` bayrağına göre ±%22,2 veya ±%4
- Motor verisi: EDB'de mi yoksa tahmin mi (`estimate_flag`)
- Ağırlık tahmini: ±%2
- Sıcaklık sapması (ISA dışı): ±%3

> Bu yüzden sitede her rakamın yanında aralık var. **Tek sayı vermek
> sahtekârlıktır** — modelin ne kadar emin olduğunu saklamak olur.

---

## 5. `src/optimization/` — Optimizasyon

| Dosya | Satır | Ne yapar | Kritik sayılar |
|---|---:|---|---|
| `cost_index_optimizer.py` | 906 | CI → hız; yakıt vs zaman dengesi | CI 0–200 aralığı |
| `altitude_optimizer.py` | 864 | Optimum seyir irtifası + step climb | 4 adım, 200 NM ara, 50 kg eşik |
| `tankering_optimizer.py` | 647 | Ucuz yerde fazla yakıt almanın net kazancı | taşıma ceza katsayısı |
| `model_calibrator.py` | 849 | Modeli müşteri verisine göre ayarla | min 30 uçuş |
| `tail_performance_calibrator.py` | 352 | Kuyruk bazlı dijital ikiz (motor aşınması) | — |

### 5.1 Step climb neden 4 adımla sınırlı?

Fiziksel olarak 10 adım da yapılabilir. Ama her seyir seviyesi
değişikliği **ATC talebi** demektir. 8–10 saatlik bir uçuşta tipik
olarak 2–4 kademe yapılır; fazlası pratikte reddedilir.
Model bunu bilmezse "50 kg kazandıran 12 adım" önerir — pilot uygulamaz,
tasarruf gerçekleşmez, ürün güvenilirliği düşer.

---

## 6. `src/validation/` — Doğrulama

| Dosya | Satır | Ne yapar |
|---|---:|---|
| `data_validator.py` | 861 | Girdi verisi sağlıklı mı (boşluk, aykırı değer, birim) |
| `business_validator.py` | 574 | İş mantığı tutarlı mı (yakıt > MTOW olamaz) |
| `physics_validator.py` | 495 | Fizik yasalarına uyuyor mu (kaldırma = ağırlık) |

`physics_validator.py` **en kritik dosyadır**: modelin kendi kendini
kandırmasını engeller. Örneğin "1.179 NM'lik uçuşta 500 kg yakıt"
derse ve bu fiziksel olarak imkânsızsa burada yakalanır.

---

## 7. `src/reporting/` + `src/security/`

| Dosya | Satır | Ne yapar |
|---|---:|---|
| `report_generator.py` | 1.252 | HTML/JSON rapor, CORSIA belgesi, vaka çalışması |
| `auth.py` | 403 | Oturum + rol (viewer/analyst/admin) + kiracı |

**`auth.py` güvenlik sayıları:**

| Sayı | Değer | Kaynak |
|---|---|---|
| PBKDF2 iterasyon | 600.000 | OWASP Password Storage Cheat Sheet (2023) |
| Tuz boyu | 16 bayt | RFC 8018 (PKCS#5 v2.2) |
| Deneme / pencere | 5 / 300 s | NIST SP 800-63B §5.2.2 |
| Kilit süresi | 900 s | Aynı — kısa kilit saldırgana zaman verir |

---

## 8. `webapp/app.py` — Arayüz (1.790 satır)

| Sayfa | Ne gösterir |
|---|---|
| `/` | Genel bakış, KPI'lar, veri kaynağı etiketi |
| `/ucuslar` | 14 uçuşun tek tek analizi |
| `/metodoloji` | Her formül ve katsayının kaynağı |
| `/veri` | Hangi veri gerçek, hangisi sentetik (dürüstlük) |
| `/denetim` | 81+ bulgu ve durumu |
| `/el-kitabi` | Nasıl kullanılır, sorun giderme |
| `/kullanicilar` | Rol + kiracı yönetimi (admin) |
| `/basit` | Jargonsuz anlatım |
| `/ticari` | Ticarileşme yol haritası |

---

## 9. `tools/` — Denetim ve üretim

| Dosya | Ne yapar |
|---|---|
| `full_audit.py` | **7 katmanlı tam denetim** (227 kontrol) |
| `build_pilot_data_package.py` | Pilot veri paketi üretir |
| `build_handbook.py` / `build_technical_report.py` | PDF üretir |
| `calibrate_aircraft_database.py` | Polar ağırlıklarını kalibre eder |
| `openap_reference.py` | OpenAP referans değerleriyle karşılaştırma |

### 9.1 `full_audit.py` katmanları

| Katman | Ne yapar | Kontrol |
|---|---|---:|
| K1 | Derleme, ruff, yasaklı desen, TODO | 10 |
| K2 | Her modül import edilebiliyor mu | 56 |
| K3 | Her public sınıf örneklenebiliyor mu | 45 |
| K4 | Her public metot gerçekten çağrılabiliyor mu | 28 |
| K5 | Fizik: elle hesap vs model + **kaynaksız sabit** | 51 |
| K6 | Uçtan uca: CSV → analiz → site → API | 28 |
| K7 | Arayüz: giriş, 9 sayfa, yetkisiz erişim | 10 |

---

## 10. Bilinen sınırlar (dürüst liste)

| Konu | Durum | Etki |
|---|---|---|
| Gerçek uçuş verisi | **0** (14 sentetik) | Model doğrulanmadı |
| Rüzgâr | GFS kodu hazır, GRIB2 yok | Belirsizlik ±%22,2 |
| A20N yakıtı | ICAO EDB'de yok → tahmin | ±%20 sapma riski (#77) |
| Geniş gövde poları | +%63 sapma | B77W/B789/A350 dikkatli |
| Veritabanı | Dosya tabanlı | 50+ kullanıcıda DB gerekli |
| MFA | Yok | Kurumsal satışta istenir |
| SLA / yedekleme | Yok | Üretim için gerekli |

---

## 11. Bir sayıyı nasıl doğrularım?

```bash
# 1. Belirli bir katmanı çalıştır
python tools/full_audit.py --layer K5

# 2. Belirli bir sabitin kaynağını gör
grep -B8 "_GRAVITY" src/units.py

# 3. Uçak verisinin kaynağını doğrula
python tests/test_aircraft_data_provenance.py

# 4. Her şeyi çalıştır
python tools/full_audit.py
```

**Kural:** Bir sayının kaynağını gösteremiyorsan o sayıyı kullanma.
Bu depoda her modül düzeyi sabit, bir tanım veya bir standarda dayanır
ya da türetilmiştir — ve bu, denetimle zorlanır.
