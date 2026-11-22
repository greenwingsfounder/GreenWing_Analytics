# GreenWing Analytics — Baştan Sona Teknik & Bilimsel Denetim Raporu

**Tarih:** 22 Kasım 2026
**Kapsam:** 42 dosya, ~40.000 satır kod — satır satır
**Yöntem:** Kod okuma + **sayısal doğrulama** (referans değerlerle karşılaştırma) + cross-module tutarlılık testleri + uçtan uca (end-to-end) rapor üretimi
**Denetçi duruşu:** Bağımsız teknik denetim (bir yatırımcı/denetçi/müşteri gibi davrandım)

---

## 0. YÖNETİCİ ÖZETİ (60 saniye)

Bu proje **iyi mimariye** ve **gerçek mühendislik emeğine** sahip. Atmosfer modeli, birim sistemi, uçak veritabanı, havalimanı veritabanı **doğru**. Ancak ticari iddianın **çekirdeğinde kritik bir sorun** var:

> **Tasarruf sayıları, fizik modelinden değil, kod içindeki `random.uniform()` çağrılarından üretiliyor.**
> Ardından aynı simülasyon verisi **"Kalite: A — Mükemmel, Veriler güvenilir"** olarak raporlanıyor.

Bu bir yazılım hatası değil, **bir bütünlük (integrity) sorunudur.** Denetim/ordu gereği bu, projeyi satmadan önce **zorunlu** olarak düzeltilmelidir. Aksi halde müşteri/denetçi önünde ciddi itibar ve hukuki risk doğar.

### Genel not tablosu

| Katman | Durum | Puan |
|---|---|---|
| Atmosfer / birim / uçak DB / havalimanı DB | ✅ Sağlam, doğrulandı | 9/10 |
| Yakıt modeli fiziği | 🟡 Yapı doğru, kalibrasyon sapmalı | 6/10 |
| **Tasarruf hesaplama** | 🔴 **Uydurma + çift sayım** | **2/10** |
| Veri kaynağı dürüstlüğü (provenance) | 🔴 **Sentetik → "Kalite A"** | **1/10** |
| Raporlama / pazarlama iddiaları | 🔴 Aşırı iddialı | 3/10 |
| Optimizasyon ekonomisi (CI, tankering) | 🟡 Mantık var, kalibrasyon zayıf | 5/10 |
| Güvenlik | ✅ Düzeltildi (önceki tur) | 8/10 |

---

## 1. GİZLİ ANAHTAR / GÜVENLİK DURUMU (önceki tur)

Önceki turda tespit edilip düzeltilenler **doğrulandı**:

- ✅ `credentials.json` kaldırıldı; `config/secrets.py` ile env-var tabanlı yönetime geçildi.
- ✅ `.gitignore` mevcut, sır dosyaları hariç.
- ✅ Dashboard debug varsayılanı `False`, host `127.0.0.1`.
- ✅ 18 güvenlik testi + Bandit: **0 MEDIUM/HIGH**.
- ⚠️ **Aksiyon bekliyor:** OpenSky client secret OpenSky panelinden **rotate edilmeli** (sen sıfırladığını söyledin — teyit et).

Bu turda **yeni** bir güvenlik açığı bulunmadı. Odak bilimsel/ticari doğruluğa kaydı.

---

## 2. MİMARİ HARİTASI (nasıl ilerliyor)

```
┌─────────────────────────────────────────────────────────────────┐
│  VERİ GİRİŞİ                                                     │
│  scripts/01_collect_data.py → src/data_collection/opensky        │
│     ├── GERÇEK: OpenSky ADS-B API                                │
│     └── YEDEK:  data/archive/opensky_real (SENTETİK, üretilmiş)  │
│  scripts/07,08: ADSB.lol canlı scraper                            │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  ANALİZ (fizik çekirdeği)                                        │
│  src/analysis/phase_segmentation → flight_analyzer               │
│    ├── src/models/atmosphere (ISA) ✅                            │
│    ├── src/units (birim/ISA) ✅                                  │
│    └── src/models/fuel_model (aero + SFC) 🟡                     │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  OPTİMİZASYON                                                    │
│  altitude_optimizer / cost_index / tankering / model_calibrator  │
│    → "tasarruf" üretir  🔴 (kısmen random)                       │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  BATCH + RAPOR                                                   │
│  scripts/02 → reports/optimizations/batch_results.json           │
│  scripts/03 → fleet report + CORSIA + case study                 │
│  scripts/04 → professional demo (random üretir) 🔴               │
│  fleet_analyzer / report_generator → HTML/JSON                   │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
                    dashboard/app.py
```

**Kritik gözlem:** Fizik zinciri (atmosphere → units → fuel_model) **sağlam**. Sorun zincirin **sonunda**: optimizasyon → tasarruf → rapor aşamasında fizik terk edilip **rastgele sayı** devreye giriyor.

---

## 3. MODÜL MODÜL DETAYLI İNCELEME

### 3.1 `src/models/atmosphere.py` — ✅ DOĞRU

ISA formülleri ICAO Doc 7488 ile uyumlu. `units.py` ile **bit-bit aynı** sonuç veriyor:

```
FL350, ISA: T=218.81 K, P=23841.9 Pa, ρ=0.3796 kg/m³  (referansla uyumlu ✓)
```

- Tropopoz geçişi (11 km) doğru.
- `delta_ISA` davranışı fiziksel (sıcak gün → yoğunluk düşer → doğru).
- **Not (DRY ihlali):** Aynı fizik `atmosphere.py` ve `units.py`'da iki kez var. Şu an tutarlı ama ileride ayrışma riski. Öneri: `units.py` `atmosphere.py`'ı sarmalasın.

### 3.2 `src/units.py` — ✅ DOĞRU

83 dahili test geçiyor. Yakıt yoğunluk-sıcaklık modeli (ASTM D1655) makul. Haversine, outlier tespiti, phase-aware interpolasyon doğru.

### 3.3 `config/aircraft_database.yaml` — 🟡 VERİ DOĞRU, YORUM YANLIŞ

Parametreler (B738: MTOW 79016, OEW 41413, S 124.6 m², CD0 0.022, TSFC 1.78e-5) **gerçek TCDS değerleriyle uyumlu**.

⚠️ **Ama bir yorum hatası var (satır ~128):**
```
#   Bu REFERANS değer. İrtifa ve Mach ile düzeltilir:
#     SFC = tsfc_cruise × √(θ/δ) × (1 - 0.10 × (M - 0.80))
```
Bu **BADA klasik** denklemidir ve değer bu formülle kullanılırsa **deniz seviyesi** referanslı olur. Ama `fuel_model.py` bunu uygulamıyor; onun yerine ±%1-2'lik "ince düzeltme" kullanıyor. **Yorum ile kod çelişiyor.** Bu, bir sonraki bakım yapan geliştiriciyi kesin yanlış yola sokar.

### 3.4 `src/models/fuel_model.py` — 🟡 YAPI DOĞRU, KALİBRASYON SAPMALI

**Doğru olan:**
- Drag polar: CD = CD0 + K·CL² ✓
- L = W·g = q·S·CL, Thrust = Drag ✓
- FF = SFC × Drag ✓
- Numerik entegrasyon (`fuel_for_distance`) ağırlık azalmasını dikkate alıyor ✓
- Breguet denklemi doğru ✓

**Ölçülen sapma (gerçek dünya verisiyle):**

| Uçak | Model FF (kg/h) | Gerçek ticari (kg/h) | Oran |
|---|---|---|---|
| B738 | 2.855 | ~2.300–2.500 | **1.19×** |
| A320 | 2.906 | ~2.200–2.400 | **1.26×** |
| A321 | 3.426 | ~2.500–2.800 | **1.37×** |
| B77W | 9.937 | ~7.000–8.000 | **1.32×** |
| A350 | 6.714 | ~5.500–6.000 | **1.16×** |

Model **sistematik olarak %16–37 fazla yakıt** yakıyor. Bu, tek başına ölümcül değil (kalibre edilebilir) ama:

1. **Benchmark bunu yakalamıyor** — çünkü `_FUEL_FLOW_RANGES['B738'] = (2000, 3200)` bandı 2855'i "normal" sayıyor. Bant çok geniş.
2. Tüm tasarruf/CO₂/yıllık projeksiyon bu hatalı mutlak değerden türüyor. **Tasarruf %'si** kısmen daha az etkilenir ama **mutlak kg/USD** doğrudan şişiyor.

**Öneri:** `cd0_factor` / `sfc_factor` kullanarak gerçek blok yakıtla kalibre et; benchmark bandını model çıktısının ±%10'una daralt.

### 3.5 `src/optimization/altitude_optimizer.py` — 🟡 MANTIK İYİ, KÜÇÜK HATALAR

**Doğru:** RVSM seviyeleri, buffet CL tablosu, thrust availability (δ·0.95), step climb planı, SAR karşılaştırması.

**Hatalar:**

1. **Docstring/kod çelişkisi `max_thrust_sl`:** Modül docstring "motor başına thrust" diyor; kod yorumu "bu değeri motor başına yorumluyoruz" diyor; ama `aircraft_database.yaml` (B738 `max_thrust_sl: 121400`) **iki motorun toplamı** olarak da okunabilir. Sonuçta `_evaluate_altitude` `thrust_per_engine × n_engines` yapıyor → **2× şişirme**. Fizik olarak bu, thrust kısıtını çok gevşek bırakıyor (feasibility'yi etkiler).

2. **`fuel_for_distance` erken `break`:** `current_weight < oew` olunca döngü kırılıyor ama `completed = True` ve `distance_completed_nm = distance_nm` **kalmış** (satır ~522). Yani uçak yakıtı bitip düşse bile "tamamlandı" diyor. Bu bir doğruluk/rapor hatası.

3. **`saving_vs_baseline` = baseline − step_total.** Baseline FL350'de uçulurken step climb **daha yüksek** irtifalara çıkıyor. Eğer `find_optimum_altitude` step sırasında baseline'dan **daha düşük** bir FL döndürürse (ağır uçakta olur), toplam yakıt baseline'dan **fazla** çıkar ve tasarruf negatif olur. Kod bunu `max(0, ...)` ile gizliyor (uyarı var ama yalnızca bir yerde).

### 3.6 `src/optimization/cost_index_optimizer.py` — 🟡

**Doğru:** Mach taramasıyla yakıt+zaman maliyeti dengesi mantığı.

**Sorunlar:**
- `ci_value = time_cost / fuel_price / 100` — **boyut analizi zayıf**. Bu ampirik bir kestirim; gerçek CI (Boeing CF = cost/fuel ratio) farklı ölçeklenir. Değer 15-40 aralığına düşüyor (gerçekçi görünüyor) ama formül "kanıtlanmış" değil.
- `baseline_mach` tanımı fonksiyon içinde görünmüyor → gecikme senaryosunda `NameError` riski. Testte `delay_minutes=0` kullanıldığı için ortaya çıkmamış olabilir.

### 3.7 `src/optimization/tankering_optimizer.py` — 🟠 KALİBRASYON HATASI

Carriage factor (taşıma cezası) tablosu **çok yüksek**:

| Mesafe | Modelde CF | Gerçek CF (fizik) |
|---|---|---|
| 1000–2000 Nm | **%12** | ~%3–5 |
| Modellenen örnek | 2000 kg'ta 240 kg yakılır | ~150 kg (fizik testiyle ölçtüm) |

Yani model, **taşıma cezasını ~1.6× abartıp** tankering'i gereğinden az kârlı gösteriyor. İyi haber: bu, tasarrufu **şişirmiyor**, aksine **azaltıyor**. Yine de yanlış.

Doğrulama:
```
LTAI→EDDF, +2000 kg: model ceza 240 kg der; gerçek fizik 150 kg.
Net tasarruf: model $67/uçuş, gerçek $157/uçuş.
```

### 3.8 `src/analysis/flight_analyzer.py` — 🔴 ÇİFT SAYIM + SABİT VARSAYIM

`_identify_savings()` fonksiyonu **tasarrufları uyduruyor ve üst üste ekliyor**:

```python
# Step climb — HİÇBİR FİZİK YOK:
fuel_save_step = total_fuel * 0.015      # sabit %1.5

# Toplam — çift sayım:
total = max(altitude_saving, step_saving) + route_saving + holding_saving
```

Test çıktısı (8000 kg'lık uçuş):
```
ALTITUDE_OPTIMIZATION  = 240 kg   (SAR %3'ten türetilmiş)
STEP_CLIMB             = 120 kg   (SABİT %1.5 — fizik yok)
ROUTE_OPTIMIZATION     = 250 kg
HOLDING_AVOIDANCE      = 300 kg
TOPLAM                 = 790 kg = %9.88  → yıllık $301,168
```

**Sorun:** `altitude` + `step climb` aynı fiziksel etkiyi (irtifa) iki kez sayabilir; `route` + `holding` de tamamlayıcı değilse toplam fiziksel üst sınırı aşar. Projenin **kendi yorumu** bile "çift sayımı önlemek için büyüğünü al" diyor ama yalnız `altitude/step` için; diğerleri **ekleniyor**.

Ayrıca her yerde **sabit `0.85 $/kg`** yakıt fiyatı kullanılıyor (`fleet_analyzer`, `flight_analyzer`, `altitude_optimizer`). `Assumptions.fuel_price()` mevcut ama analiz katmanı onu kullanmıyor → **tutarsızlık**.

### 3.9 `scripts/04_generate_professional_demo.py` — 🔴 EN KRİTİK DOSYA

Bu script, `batch_results.json`'ı üretiyor; ardından `03_generate_outputs.py` bunu okuyup her rapora koyuyor. İşte sorun:

```python
# 17 adet random.uniform / random.randint çağrısı

# satır 482-486: "minimum gerçekçi tasarruf" — UYDURMA
min_saving = total_fuel * 0.012
if fuel_optimization < min_saving:
    fuel_optimization = total_fuel * random.uniform(0.015, 0.025)   # ⛔

# satır 416-418: step climb başarısızsa random ile doldur
step_saving = total_fuel * random.uniform(0.010, 0.015)            # ⛔

# satır 460: tankering başarısızsa
tank_amount = random.randint(500, 1500)                             # ⛔

# satır 504: route efficiency
'route_efficiency_pct': round(random.uniform(94.0, 98.5), 1)        # ⛔
```

**Etkisi (batch_results.json üzerinde ölçüldü):**

```
Toplam iddia edilen tasarruf  = 35.920 kg
Fizik modelinin verdiği       = 17.993 kg
Uydurma miktar                = 17.927 kg  (%100 fazla!)

Uydurmanın uygulandığı uçuş: 155/231 (%67)
  - 134 uçuşta uydurma > fizik
  - 21 uçuşta fizik SIFIR → tamamen uydurma
  - 76 uçuşta fizik tabanlı (kabul edilebilir)
```

**Daha da kritik:** İlk kayıtta `FL360→FL360` (irtifa değişimi YOK) ama kayıt "129 kg tasarruf" diyor. Fizik "0 kg" diyor. **Sayı tamamen kurgu.**

### 3.10 `scripts/03_generate_outputs.py` + `data_quality` — 🔴 EN TEHLİKELİ RAPOR KAPISI

`run_data_quality_check()` yalnızca **"partial uçuş oranına"** bakıyor:

```python
if partial_pct < 10:
    grade = 'A'
    desc  = 'Mükemmel — Veriler güvenilir'
```

`collection_method = 'demo_simulation'` **hiç kontrol edilmiyor.** Sonuç — kendi çıktım:

```
batch_results.json:        231 kayıt, TÜMÜ 'demo_simulation' / 'SIMULATED'
data_quality raporu:       grade='A', desc='Mükemmel — Veriler güvenilir'
üretilen HTML raporu:      "Veri Kalitesi A — Güvenilir" + "±2–3%"
```

Yani **simülasyon verisi, denetçiye/müşteriye 'Grade A — güvenilir' olarak sunuluyor.** Bu, projenin en ciddi ticari/hukuki riskidir.

### 3.11 `src/analysis/benchmark.py` — 🟠 ÇOK GENİŞ BANTLAR

Bantlar (`B738 fuel_flow (2000,3200)`, `kg/NM (6,12)`, `saving (0,15%)`, `annual (0,$5M)`) o kadar geniş ki **neredeyse her değer "PASS"**. Test:

```
%2 tasarruf  → PASS
%5 tasarruf  → PASS
%10 tasarruf → PASS   ← gerçek demo tam burada (%9.9)
%25 tasarruf → FAIL
$3,000,000/yıl → PASS
```

Sektör gerçeği: irtifa+step climb toplam etkisi **%0.5–2** aralığında. Bant bunu **%15'e** kadar "normal" sayıyor. Validation'ın işi hatayı yakalamak; burada yakalamıyor.

### 3.12 `src/models/emission_model.py` — ✅ ÇEKİRDEK DOĞRU

- CO₂ = fuel × 3.16 (ICAO CORSIA) ✓
- H₂O = 1.24, SO₂ = 0.001 ✓
- CO₂/pax/km hesabı doğru (birkaç kayıtta mesafe kaynağı farklı olduğu için %3-11 tutarsızlık var — bkz. 3.13)

### 3.13 `batch_results.json` veri tutarlılığı — 🟠

| Kontrol | Sonuç |
|---|---|
| `co2_kg == fuel × 3.16` | ✅ (max hata %0.003) |
| `annual_realistic == annual_raw × RF` | ✅ (0/231 uyumsuz) |
| `annual scale = 345/30 gün` | ✅ (formül doğru) |
| `fuel_optimization == max(alt,step)` | 🔴 **0/231 uyumlu** (155 uydurma) |
| `co2_per_pax_km` kendi verisiyle | 🟠 **200/231 tutarsız** (%3-11) — iki farklı mesafe/pax kaynağı |

`co2_per_pax_km` tutarsızlığı büyük ihtimalle `emission_model` kendi tipik yolcu sayısını kullanırken, kayıtta farklı `passengers` olmasından. Küçük ama profesyonel raporda göze batar.

### 3.14 `src/models/blockchain_sealer.py` — 🔴 YANLIŞ BEYAN RİSKİ

Modül adı "blockchain" ama **hiçbir ağa bağlanmıyor**. Sadece `sha256(json)` + `uuid` + sahte `tx_id` üretip `"verification_status": "VERIFIED_ON_LEDGER"` ve `verification_url: https://verify.greenwinganalytics.com/tx/...` yazıyor. O URL'nin arkasında bir ledger/servis yok.

Bu, **CORSIA denetim bağlamında** "blockchain'e kaydedildi/dogrulandı" izlenimi veriyor. Bir müşteri/denetçi bunu kontrol ettiğinde itibar kaybı olur. Öneri: ya gerçek bir anchor (VeChain/Hedera/OpenTimestamps) bağla, ya da adını "hash seal — internal integrity" yapıp `VERIFIED_ON_LEDGER` iddiasını kaldır.

### 3.15 Dashboard & pazarlama — 🟠

- **Kimlik doğrulama YOK.** Dashboard tüm ağa açık olduğunda herkes müşteri verisini görebilir.
- KPI kartlarında tasarruf $\$$ ve CO₂ tonu gösteriliyor — bu sayılar **3.9/3.8'deki uydurma zincirden** geliyor.
- `report_generator` altbilgisi: **"±2–3% doğruluk"** diyor. Bu, modelin gerçek (kalibre değilken) hatası %16-37 iken **iddialı**; ayrıca simülasyon verisinde hiç geçerli değil.

---

## 4. MATEMATİKSEL / FİZİKSEL TUTARLILIK SKORKARTI

| Kriter | Durum | Not |
|---|---|---|
| ISA atmosfer doğruluğu | ✅ | Referansla birebir |
| Breguet / drag polar | ✅ | Klasik ve doğru |
| Birim dönüşümleri | ✅ | 83 test geçti |
| Kütle dengesi (W azalır) | ✅ | Numerik entegrasyon doğru |
| Yakıt akışı mutlak doğruluk | 🟠 | %16-37 fazla |
| Tasarruf üretimi | 🔴 | Fizik değil, random |
| Çift sayım önleme | 🔴 | route+holding+step ekleniyor |
| Ekonomik tutarlılık (CI, tankering) | 🟠 | Mantık var, katsayılar sapmalı |
| Sensör/veri kaynağı dürüstlüğü | 🔴 | Sentetik → Grade A |
| Denetim/izlenebilirlik | 🟡 | `AnalysisTracer` var (iyi) ama rapora yansımıyor |

---

## 5. PAZARLAMA / KONUMLANDIRMA ANALİZİ

**Projenin gerçek değer önerisi (dürüstçe):**
> "ADS-B + fizik modeliyle uçuş başına yakıt/karbon tahmini yapan, 4 eksende (irtifa, step climb, cost index, tankering) **fırsat taraması** yapan bir analiz platformu. Sonuçlar **yönlendirici** (indicative) olup operatör QAR/FDR verisiyle kalibre edildiğinde doğruluk artar."

**Şu anki iddia ile aradaki fark (riskli kısımlar):**

| İddia | Gerçek | Risk |
|---|---|---|
| "Real ADS-B verisi" (sabit subtitle) | `demo_simulation` | 🔴 Yanıltıcı reklam |
| "Kalite A — Mükemmel" | Simülasyon (grade kuralı kaynak bakmıyor) | 🔴 Denetim ihlali |
| "±2–3% doğruluk" | Kalibrasyonsuz model %16-37 sapma | 🟠 Aşırı iddia |
| "$359K/yıl tasarruf" | Fizik $~180K, gerisi random | 🔴 |

**Öneri (satış için daha güçlü ve savunulabilir konumlandırma):**
1. Her rapora **"Data Provenance" kutusu**: simülasyon mu, ADS-B mi, müşteri QAR mı? + güven düzeyi.
2. Tasarrufu **üç ayrı kutu** olarak sun: (a) fizik motorunun verdiği, (b) operasyonel gerçekleşme faktörü uygulanmış, (c) **belirsizlik aralığı**.
3. "Blockchain" iddiasını gerçek anchor'a bağla ya da kaldır.
4. Dashboard'a kimlik doğrulama + "müşteri verisi" etiketi.

---

## 6. ÖNCELİKLİ DÜZELTME PLANI (yapılabilir sıralama)

### P0 — Ticari iddia için zorunlu (bu hafta)
1. **`04_generate_professional_demo.py`'den tüm `random.uniform` tasarruf üretimini kaldır.** Fizik ne veriyorsa onu yaz; 0 ise 0. (17 random çağrısı → 0)
2. **`run_data_quality_check`'e provenance kontrolü ekle.** `collection_method` sentetikse grade `'SIMULATED'` olsun, rapor "Simülasyon — gerçek değil" desin.
3. **`_identify_savings` çift sayımı düzelt.** `max(alt, step)` + `route` ve `holding`'i de birbirine bağımlı hesapla; toplamı fiziksel üst sınırla kelepçele.
4. **`step_climb_saving = total*0.015` sabitini sil.** Gerçek step climb fiziği (`estimate_climb_fuel` + SAR farkı) kullan.
5. **`blockchain_sealer`** → `VERIFIED_ON_LEDGER` iddiasını kaldır.

### P1 — Doğruluk (2 hafta)
6. **Yakıt modelini kalibre et.** `cd0_factor`/`sfc_factor`'ü gerçek blok yakıt ile ayarla; hedef B738 ~2400 kg/h yap.
7. **Benchmark bantlarını daralt.** B738 FF `(2200, 2700)`, kg/NM `(5.5, 8.5)`, tasarruf `(0, 6%)`.
8. **Her yerde `Assumptions.fuel_price()` kullan**, sabit `0.85`'i kaldır.
9. **Tankering CF tablosunu** gerçek fizikle değiştir (~%0.3-1 taşıma cezası, mesafeye göre).
10. **`fuel_for_distance` erken break** → `completed=False`, `distance_completed_nm` gerçek değeri yazsın.
11. **`max_thrust_sl` birim belirsizliğini** tek anlamlı yap.

### P2 — Güven & ürün (1 ay)
12. Her rapora `data_provenance` bloğu + güven aralığı.
13. Dashboard'a basit auth (reverse proxy veya Flask-Login).
14. `co2_per_pax_km` tek kaynaktan hesaplansın.
15. `±2–3%` iddiasını "kalibrasyon sonrası hedef" olarak etiketle, şu anki haliyle sunma.
16. Atmosfer/units DRY birleştirmesi.

---

## 7. EK: DOĞRULAMA KOMUTLARI

Bu rapordaki tüm sayılar şu şekilde üretildi (tekrar çalıştırılabilir):

```bash
# 1. Atmosfer doğruluğu
python -m src.models.atmosphere

# 2. Birim sistemi
python -m src.units

# 3. Yakıt modeli gerçek dünya karşılaştırması
python -c "
from src.models.fuel_model import FuelModel
fm=FuelModel('B738')
print('FF kg/h:', fm.cruise_fuel_flow_kg_hr(69000,35000,0.785))  # gerçek ~2400
"

# 4. Tasarruf uydurması kanıtı
python -c "
import json
d=json.load(open('reports/optimizations/batch_results.json'))
uydurma=sum(1 for r in d if r['fuel_optimization_kg']>max(r['altitude_saving_kg'],r['step_climb_saving_kg'])+2)
print(f'{uydurma}/{len(d)} kayıtta uydurma tasarruf')
"

# 5. Veri kalitesi çelişkisi
python scripts/03_generate_outputs.py
cat reports/case_studies/data_quality_*.json | grep quality_grade   # 'A' (oysa demo_simulation)
```

---

## 8. SON SÖZ

Bu proje **çöp değil** — aksine, doğru katmanlardan (ISA, aero, birimler, veritabanları) oluşmuş sağlam bir iskelet. Sorun, iskeletin üzerine konan **"satış katmanı"**nın fizikten kopmuş olması. İyi haber: bu, **tahmin edilemeyen bir bilim problemi değil**, cerrahi bir temizlik problemi. `04`'teki 17 random çağrısını kaldırıp, veri kalitesi kapısını düzeltip, çift sayımı giderirsen — elinde **gerçekten savunulabilir** bir ürün olur.

Denetim tamamlandı. Bir sonraki adım: **P0 maddelerini uygulamamı ister misin?** Onaylarsan `04`, `03` ve `flight_analyzer`'ı temizleyip, önce/sonra kanıtıyla tekrar rapor üretirim.
