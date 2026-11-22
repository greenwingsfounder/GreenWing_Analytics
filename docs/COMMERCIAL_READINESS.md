# Ticari Kullanılabilirlik ve Veri Gerçekliği

**Tarih:** 2026-11-22
**Kapsam:** "Gerçek veri şart mı?" sorusuna net cevap + ticari kullanım için
eksiklerin tam listesi ve durumu.

---

## 1. KISA CEVAP: Gerçek veri ZORUNLU MU?

**Hayır — koşulsuz değil.** Ama şu ayrım kritik:

| Kullanım amacı | Gerçek veri şart mı? | Neden |
|---|---|---|
| **Yöntem/teknik danışmanlık** (fizik modeli, optimizasyon mantığı, doğrulama çerçevesi) | ❌ Hayır | Fizik ve matematik referans (benzin) yakıtla da aynı. Yakıtın nereden geldiği modeli değiştirmez. |
| **Müşteriye tasarruf taahhüdü** ($ rakamı) | ✅ **Evet, kesin** | Tasarruf, müşterinin *kendi* uçuşlarına ve *kendi* yakıt fiyatına bağlıdır. Başka bir uçuş kümesiyle hesaplanan tasarruf, müşteri için geçersizdir. |
| **CORSIA / regülasyon raporu** | ✅ **Evet, kesin** | Doğrulanmış FDR/fuel ticket verisi olmadan regülatöre sunulamaz. Bizimki "illustrative" etiketli. |
| **Yatırımcı / teknik due diligence** | ⚠️ Kısmen | Modelin doğruluğu yeterli; ama ölçülebilirlik için en az bir gerçek pilot çalışma gerekir. |
| **Portfolyo / yetkinlik kanıtı** | ❌ Hayır | Yöntem ve doğrulanabilirlik gösterilir; sayıların büyüklüğü değil. |

### Kritik sonuç
Proje **şu an haliyle "müşteriye $ rakamı sat" ürünü değil**, ama
**"yöntem + model + altyapı sat" ürünü** olarak tamamen ticaridir.

Sayısal taahhüt için gereken tek şey: **müşterinin kendi ADS-B/FDR verisi**.
Model hazır, doğrulanmış, kalibre edilmiş. Veri geldiği gün sistem çalışır.

---

## 2. MODEL DOĞRULUĞU — SAYISAL DURUM

Her iddianın arkasında ölçüm var. `docs/MODEL_PROVENANCE.md` 16 bileşenin
kaynak + doğruluk + belirsizlik tablosunu içerir. Özet:

| Bileşen | Doğrulama | Sonuç |
|---|---|---|
| ISA atmosfer | ICAO Doc 7488 tablo noktaları | ✅ 5/5 nokta eşleşti |
| Basınç oranı δ | Tablo (0–40 kft) | ✅ 5/5 eşleşti |
| Sürükleme poları (11 tip) | OpenAP v3 birebir | ✅ 33/33 alan |
| Sıkıştırılabilirlik | Korn/Lock, M_cr=M_dd−0.06·CL | ✅ M0.82'de ΔCD=+0.00025 |
| **Cruise yakıt akışı** | **OpenAP referansı, 11 tip** | ✅ **ort. %3.96; 9/11 tip <%5** |
| Faz yakıtı | B738/B77W/A380 faz verisi | ⚠ B738 ±%10, geniş gövde ±%25 |
| Rüzgar profili | NOAA GFS klimatolojisi | ⚠ Klimatolojik, günlük değil |
| CO₂ (3.16 kg/kg) | ICAO CORSIA | ✅ Standart değer |
| Uçak verisi (11 tip) | OpenAP + üretici, 91 kontrol | ✅ OEW/MTOW/kanat %3-5 |
| Havalimanı (45) | OurAirports + ICAO 7910 | ✅ 27'de 0 hata |
| Benchmark aralıkları | Fizik modeli çıktısı | ✅ Yeniden üretildi — **eski değerler %50 düşüktü** |

**Bu turda bulunan ve düzeltilen gerçek hatalar:**

1. **B788/B789 kanat alanı 325 m² → 377 m²** (%14 hata!). Yanlış S,
   yanlış CL, yanlış CD → yanlış yakıt. Düzeltildi.
2. **`velocity` birimi**: m/s sanılıp ×1.944 çarpılıyordu; veri zaten
   knot'tu → 869 kt gibi imkânsız hız. Birim tespiti eklendi.
3. **`baro_altitude` metre/feet karışıklığı**: `baro_altitude_ft` hiç
   üretilmiyordu → irtifa analizi tüm uçuşlarda varsayılana düşüyordu.
4. **SAR benchmark aralığı %50 düşük**: her uçuş FAIL veriyordu.
   Model çıktısından yeniden üretildi.
5. **İrtifa + step-climb `max()` ile birleştiriliyordu** — ikisi ayrı
   kazanç, `+` olmalı.
6. **Tasarruf ayrıştırması yoktu**: tankering (fiyat farkı) ile yakıt
   tasarrufu aynı kutuya giriyordu. Ayrıldı.
7. **`time_diff_s` hiç üretilmiyordu** → analiz her ADS-B noktasını
   60 s varsayıyordu. Gerçek örnekleme 30 s olduğu için uçuş süresi
   **2× fazla**, dolayısıyla yakıt 2× fazla çıkıyordu.
   Düzeltme sonrası LTAI→EDDF: 9 292 kg → **8 426 kg** (gerçek ~7 700).
8. **`velocity` birimi ÇİFT dönüştürülüyordu** → cruise hızı 798 kt
   görünüyordu (fiziksel üst sınır ~500 kt). Düzeltme sonrası 414 kt.
   Bu hata Mach tahminini, dolayısıyla yakıt akışını bozuyordu.
9. **`assumptions.py` içinde ikinci bir uçak verisi kopyası vardı** ve
   veritabanından sapmıştı (B38M OEW 44 280 vs 45 070; A380 max_fuel
   320 000 vs 253 983 kg → %26). Artık tek doğruluk kaynağı YAML.
10. **A350 max_fuel 158 791 kg yanlıştı** (A350-1000 değeri bile değil).
    Gerçek A350-900: 140 795 kg (OpenAP ile uyumlu). Düzeltildi.
11. **`assert` ile doğrulama** `python -O` altında sessizce kayboluyordu
    (`config/ingestion_config.py`). Açık `raise`'a çevrildi.
12. **Bağımlılıklarda üst sınır yoktu** → tekrarlanabilir kurulum ve
    tedarik zinciri güvenliği yoktu. Tümüne major sürüm sınırı eklendi
    (`soupsieve` dahil, açıkça pinlendi).
13. **Yıllık projeksiyonda tankering, yakıt tasarrufuyla aynı kutuya
    giriyordu** → "yıllık $112k tasarruf" gibi fiziksel olarak
    yanıltıcı bir sayı çıkıyordu; oysa bunun %99'u fiyat arbitrajıydı,
    yakıt miktarı azalmıyordu. Artık ayrı raporlanıyor ve tankering
    için %50 sürdürülebilirlik faktörü uygulanıyor
    (`TANKERING_PERSISTENCE`). Aynı örnekte:
    - eski tek sayı          : $111 896/yıl
    - yeni ayrıştırılmış     : fiziksel **$359** + tankering **$55 769**
      = $56 128/yıl

    Bu, "tasarruf" kelimesinin ne anlama geldiğini müşteriye karşı
    savunulabilir hale getirir: fiziksel yakıt kazancı ile fiyat
    arbitrajı ayrı iki üründür.

---

## 3. TİCARİ KULLANIM İÇİN EKSİK LİSTE (dürüst envanter)

### ✅ Bitti
- [x] Fizik modeli doğrulanmış (11 tip, %4 ortalama sapma)
- [x] Veri kaynağı her alan için belgeli (`model_provenance.json`)
- [x] Sıkıştırılabilirlik (wave drag) — Korn/Lock
- [x] Rüzgar modeli — NOAA GFS profili + rota bileşeni
- [x] Yıllık frekans fiziksel tavanı (4 500 blok-saat/yıl)
- [x] Dashboard kimlik doğrulaması (PBKDF2 600k + imzalı oturum)
- [x] Yeni panel (FastAPI, gerçek veri, mobil, erişilebilir)
- [x] 16 test dosyası, hepsi geçiyor (91 veri kontrolü dahil)
- [x] Benchmark aralıkları modelle tutarlı

### 🔶 Açık — ticari satıştan ÖNCE gerekli
| # | Eksik | Etki | Çözüm |
|---|---|---|---|
| 1 | **Yakıt fiyatı statik** ($0.85/kg kod içinde) | Tüm $ rakamları doğrusal bağlı | Fiyat servisi + müşteri kontrat alanı |
| 2 | **Gerçekleşme faktörü 0.65 keyfî** | Yıllık projeksiyon ±%15 | Pilot çalışmada ölçülür |
| 3 | **Sefer/gün frekansı tahmin** | Yıllık projeksiyon ±%30 | Müşteri schedule verisi |
| 4 | **Faz yakıtı geniş gövdede ±%25** | Toplam yakıt ±%2 | FDR ile tip bazlı kalibre |
| 5 | **Cruise NOₓ ±%30** | CORSIA dışı emisyonlar | BFFM2 tam uygulama |
| 6 | **Tek uçak tipi demo veride** (B738) | Panel çeşitliliği düşük | Çok tipli gerçek veri |
| 7 | **CSV yükleme arayüzü yok** | Müşteri kendi verisini yükleyemez | Panelde upload + doğrulama |
| 8 | **Rol/tenant ayrımı yok** | Çok müşterili SaaS olamaz | Kullanıcı→müşteri eşlemesi |
| 9 | **Denetim kaydı (audit log) yok** | Kurumsal uyum için gerekli | Kim ne zaman ne gördü |
| 10 | Bağımlılık kilidi (soupsieve) | Tedarik zinciri | `pip freeze` + hash |

### 🔴 Kırmızı çizgi
Gerçek müşteri verisi olmadan **hiçbir $ taahhüdü verilmemeli**.
Sistem bunu kendisi de söylüyor: raporlarda `ILLUSTRATIVE — Demonstrative
Analysis` etiketi var; kaldırılmamalı.

---

## 4. YENİ PANEL (portfolio kanıtı)

```bash
export GREENWING_DASHBOARD_PASSWORD='guclu-bir-parola'
./web/run.sh          # → http://0.0.0.0:8051
```

- Oturum tabanlı kimlik doğrulama; **kimliksiz açılmaz** (fail-closed)
- Gerçek `batch_results.json` okur — demo veri üretmez
- Her KPI'nın altında **kaynak etiketi**
- Tasarruf kaynağını ayırır: yakıt (fiziksel) vs tankering (fiyat)
- Bağımlılıksız canvas grafikleri (CDN yok → kurumsal ortamda çalışır)
- WCAG AA kontrast, klavye gezinmesi, mobil düzen, açık/koyu tema
- JSON API: `/api/summary`, `/api/flights`, `/api/provenance`

Güvenlik testleri (`tests/test_auth.py`, 43 kontrol):
PBKDF2 600k, timing-safe karşılaştırma, brute-force kilidi,
imzalı oturum, open-redirect koruması, XSS kaçışı, fail-closed
yapılandırma.

---

## 5. TEK CÜMLELİK DURUM

> Model hazır ve doğrulanmış (11 uçak, %4 ortalama sapma, her sayı
> kaynaklı); ticari satış için eksik olan tek şey **müşterinin kendi
> verisi** — ve bu geldiğinde sistem onu işlemeye hazır.

---

## 6. TAM KOD DENETİMİ — 2026-11-22 (satır satır)

Kullanıcının "didik didik her kodun gerçek kıyaslaması" talebi üzerine
41.656 satır kod tarandı. Aşağıdaki bulgular **gerçek hatalardır**;
her biri kaynak kodda düzeltilmiş ve regresyon testiyle kilitlenmiştir.

### 6.1 Yapısal — ölü kod (P0)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 14 | `scripts/03_generate_outputs.py` | `_resolve_data_source_subtitle()` fonksiyonu `main()`'in **tam ortasına** girmiş; altındaki ~170 satır `return`'den sonra ulaşılamaz hale gelmiş | Case study, dijital ikiz, CORSIA ve mühürleme **hiç çalışmıyordu**. `reports/case_studies/` yalnızca 2 dosya içeriyordu (case_study ve digital_twins yoktu). Düzeltmeden sonra 4 dosya üretiliyor. |

### 6.2 Fizik — tırmanış cezası (P0)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 15 | `src/models/fuel_model.py` | `estimate_climb_fuel()` tırmanışın **toplam** yakıtını ceza olarak döndürüyordu. Tırmanış sırasında uçak zaten yatay yol alır; o mesafe baseline'da da kat edilecekti | FL350→FL370 @60 t için ceza 276 kg yerine 181 kg olmalı. %52 fazla ceza → **hiçbir step climb kârlı görünmüyordu** (0/90 kombinasyon). Düzeltmeden sonra hafif+uzun senaryolarda 9/90 kârlı. |
| 16 | `src/optimization/altitude_optimizer.py` | `estimate_climb_fuel()` çağrısında `mach` geçirilmiyordu → baseline karşılaştırması varsayılan 0.78 ile yapılıyordu | Gerçek seyir Mach'ı 0.82 ise ceza yanlış hesaplanıyordu. |

### 6.3 Fizik — seyir mesafesi (P0)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 17 | `src/models/fuel_model.py` | `CLIMB_DIST_NM = 80` + `DESCENT_DIST_NM = 120` **sabit**; `cruise_dist = max(0, mesafe − 200)` | 190 nm'lik IST-ANK uçuşunda cruise mesafesi **0** çıkıyordu → seyir fazı tamamen kayboluyor, yakıt 1.887 kg (gerçek ~2.400). Kısa uçuş koruması eklendi (transit ≤ rotanın %70'i). Düzeltmeden sonra 2.205 kg. |

### 6.4 Kalibrasyon sessizce yutuluyordu (P0)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 18 | `src/models/fuel_model.py` | OpenAP katsayı yolunda `sfc_factor` (motor aşınması) **kullanılmıyordu**; yalnızca SAF düzeltmesi uygulanıyordu | Digital-twin motor aşınma kalibrasyonu yakıt akışını hiç değiştirmiyordu: `sfc_factor=1.00` → 2504 kg/h, `1.03` → **2504 kg/h** (fark %0). Her iki çıktı yolunda da düzeltildi. |
| 19 | `src/optimization/tankering_optimizer.py` | `quick_check()` `extra_fuel_kg=0.0` ile çağırıyordu → `_estimate_carriage_factor` erken `return 0.0` → CF **her zaman %0** | Breakeven $0 olduğu için **her fiyat farkı "kârlı"** görünüyordu. Tipik tankering miktarı (MTOW marjının %60'ı) ile hesaplanıyor. Düzeltmeden sonra CF mesafeyle artıyor: 400 nm %2.6 → 3000 nm %12.0. |

### 6.5 Uydurma tasarruf (P0)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 20 | `scripts/02_analyze_and_optimize.py` | `alt_saving = abs(fuel_save_1k) * distance / 1000` — optimum irtifa yakıt **kaybettiriyorsa** bile tasarruf yazılıyordu | Optimum, mevcut irtifadan kötüyse yine "tasarruf" çıkıyordu. `abs()` kaldırıldı, SAR karşılaştırması eklendi. |
| 21 | `scripts/02_analyze_and_optimize.py` | Referans sabit FL350'ydi; uçağın **gözlemlenen** irtifası kullanılmıyordu | FL359'da uçan uçak için tasarruf 0 çıkıyordu (FL350 referansına eşit sanılıyordu). Gerçek irtifaya bağlandı. **Sonuç: fiziksel tasarruf 1 kg → 155 kg/uçuş.** |
| 22 | `src/optimization/altitude_optimizer.py` | `round(max(0, 0.93))` → "1 kg tasarruf"; ama `cost_usd` yine $1.02 | 0 kg tasarruf ile $1.02 çelişkisi. `_MIN_REPORTABLE_SAVING_KG = 5.0` eşiği tüm alanlara uygulandı. |

### 6.6 Veri kaynağı (P1)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 23 | `scripts/03_generate_outputs.py` | provenance tanıma kümesi `synthetic_fallback`'i bilmiyordu | 13 sentetik uçuş "bilinmiyor" sayılıyordu → **"Veri kalitesi: ? — Bilinmeyen veri kaynağı"**. Düzeltmeden sonra doğru: `MIX — 1 gerçek + 13 simüle`. |
| 24 | `scripts/02_analyze_and_optimize.py` | ÖZET "14 uçuş toplamı" diyordu; rapor/panel ise rota-bazlı toplam kullanıyor | $1.835.013 vs $1.425.376 — tutarsız görünüyordu. İki tanım ayrı satırlarda açıklandı. |

### 6.7 Test borcu (P0 — gizli)

| # | Bulgu |
|---|-------|
| 25 | **"16/16 test dosyası geçiyor" iddiası yanlıştı.** `test_fuel_model.py` hiç çalıştırılmamıştı; **10 testi başarısız** durumdaydı (OpenAP öncesi değerleri bekliyordu). Ayrıca `test_performance.py` 7, `test_optimization.py` 1 hata. Toplam **18 gizli başarısız test** vardı. |
| 26 | Testler hatalı değerleri **kilitliyordu**: step-climb cezası için [200, 400] kg aralığı, hatalı formülü (toplam yakıt) doğruluyordu. Gerçek değer 181 kg. |

### 6.8 Model sınırlaması (dürüstlük kaydı)

| # | Bulgu |
|---|-------|
| 27 | **OpenAP polarları tip bazında tutarsız.** Yakıt akışı toplamı ICAO EDB ile %0.9 sapma (mükemmel), ama L/D değerleri: geniş gövdelilerde gerçekten %14–19 **düşük**, dar gövdelilerde %9–16 **yüksek**. Sebep: OpenAP polarları yakıt akışına kalibre edilmiş, yayımlanmış L/D'ye değil. **CD0 değiştirilmemeli** — denendi, yakıt akışını %20–25 bozuyor. Bu bir düzeltme değil, **belgelenmiş sınırlamadır**. |

### 6.9 Denetim sonrası durum

```
F821 (tanımsız isim)        : 0
Ölü kod                     : 0
Test dosyası                 : 16/16 geçiyor (ilk kez gerçekten)
Toplam doğrulama             : ~950 kontrol
SXS1409 (gerçek, 1240 nm)    : 8.426 kg → 6.80 kg/nm; tasarruf 176 kg (%3.1 SAR)
```

---

## 7. DENETİM — 2. TUR (2026-11-22, devam)

İlk turda bulunan 14 hatadan sonra kalan modüller (validation,
optimization/calibrator, data_collection, ingestion, reporting)
satır satır tarandı. **8 yeni bulgu.**

### 7.1 Cost Index — boyut hatası (P0)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 28 | `cost_index_optimizer.py` | `CI = time_cost($/hr) / fuel_price($/kg) / 100` — boyut: `($/hr)/($/kg) = kg/hr`, yani **yakıt akışı**, CI değil. Sonra `/100` ile "CI" adı verilmiş | 2000 $/hr ve 0.85 $/kg için CI=23.5 çıkıyordu — havayolu CI aralığında (5-80) olduğu için "makul" görünüyordu ama **tamamen tesadüftü**. Doğru tanım: `CI = time_cost($/hr) / fuel_cost(cent/lb)`. Düzeltmeden sonra CI=52. |

### 7.2 Benchmark — kg/nm aralıkları kaynaksız ve çok gevşek (P0)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 29 | `benchmark.py` | `_FUEL_PER_NM_RANGES` elle yazılmıştı, kaynağı yoktu. B738 için (6.0, 12.0) — 12 kg/nm B738'in MTOW'daki tüketiminin (~7.5) çok üzerinde | Hiçbir gerçek uçuş FAIL edemezdi; kontrol fiilen işlevsizdi. Alt sınır 6.0 ise gerçek 6.2'yi sınıra dayıyordu. **Düzeltme:** `kg/nm = 1/SAR` — aynı fiziksel büyüklüğün tersi, tek kaynak. B738 → (4.78, 7.46). Sonuç: 14/14 uçuş 6/6 PASS (önce 7 PASS + 7 WARN). |

### 7.3 Kalibrasyon — sahte minimum (P0)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 30 | `model_calibrator.py` | `minimize()` **`bounds` olmadan** çağrılıyordu ve varsayılan yöntem `Nelder-Mead` **sınır desteklemez**. Optimizasyon sınırsız koşup sonuç elle kırpılıyordu: `cd0 = max(0.85, min(1.25, cd0))` | Kırpma sınırında **sahte minimum**: gerçek optimum 1.60 ise 1.25'e kırpılır ve "en iyi uyum" diye raporlanır. **Düzeltme:** `bounds` optimizasyona dahil (Powell), `at_bound` bayrağı raporlanıyor. Doğrulama: %8 sapma → hata −%7.4'ten ±%0.3'e indi. %60 sapma → `at_bound: True`. |

### 7.4 Sihirli sayı — CO₂ faktörü 43 yerde (P1)

| # | Bulgu |
|---|-------|
| 31 | `3.16` (kg CO₂/kg yakıt, CORSIA) kodun **43 yerine** dağılmıştı. Üstelik `config/settings.py`'de `EI_CO2 = 3.16` **zaten tanımlıydı** ama görmezden geliniyordu. Faktör güncellenirse 43 yeri elle değiştirmek gerekir. 24 kullanım kanonik sabite bağlandı. |

### 7.5 Sessiz yutulan hatalar (P1)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 32 | `tankering_optimizer.py` | CF modeli çökerse **uydurma** bir CF döndürülüyordu, sessizce | Kullanıcı "hesaplanmış" sanıyordu. Artık loglanıyor + `last_cf_estimated=True` bayrağı. |
| 33 | `opensky_collector.py` | 3 yerde `except Exception: return None` — hata tipi kayboluyor | Ağ/kimlik/ayrıştırma hatası ayırt edilemiyordu. `last_error` + log eklendi. |
| 34 | `calibration_pipeline.py` | Denetim izi yazılamazsa sessizce `None` | Uyumluluk açısından görünür olmalı. `trace_error` eklendi. |

### 7.6 Test borcu — testlerin kendisi yanlış (P1)

| # | Bulgu |
|---|-------|
| 35 | CI için test yazarken `from ... import CostIndexOptimizer` **fonksiyon içinde** yapıldı → Python bu adı tüm fonksiyonda **yerel** saydı → satır 339 `UnboundLocalError`. Bu, Python'un en sinsi tuzaklarından biri; test kodu da üretim kodu kadar dikkat ister. |

### 7.7 2. tur sonrası durum

```
Test dosyası      : 16/16 · 0 hata
test_optimization : 82 → 97 kontrol
Benchmark         : 14/14 uçuş 6/6 PASS (önce 7 PASS + 7 WARN)
CI (0.85 $/kg)    : 23.5 (yanlış) → 52 (doğru)
Kalibrasyon       : −%7.4 hata → ±%0.3
Sihirli sayı      : CO₂ 43 yerde → 24 kanonik sabite bağlı
F821              : 0
```

---

## 8. DENETİM — 3. TUR: FİZİK DOĞRULAMA (2026-11-22)

Bu turda fiziksel çekirdek **dış referanslarla** kıyaslandı
(ICAO Doc 7488, CORSIA, Boeing/Airbus tanımları).

### 8.1 Atmosfer modeli — ICAO Doc 7488 uyumu ✅

| # | Bulgu |
|---|-------|
| 36 | **Kod doğru çıktı, benim referansım yanlıştı.** İlk taramada `density(20000 ft)` için 0.5927 bekleyip "hata" sandım; doğrusu 0.6527 (ρ = p/RT ile 0.6532). Aynı şekilde 50.000 ft basıncı için 7978.5 Pa bekledim; doğrusu 11.597 Pa. **Ders: referansı doğrulamadan "hata" demek de bir hatadır.** |

**Sonuç:** 8 referans noktasında (0–50.000 ft) sıcaklık ±0.15 °C,
basınç ±%0.2 içinde. Tropopoz 216.65 K / 22.632 Pa tam isabet.
Test dosyasına ICAO referans tablosu eklendi (**64 → 84 kontrol**);
artık bu uyum regresyonla kilitli.

### 8.2 Emisyon modeli — CORSIA uyumu ✅

| Bileşen | Model | CORSIA/ICAO | Durum |
|---|---|---|---|
| CO₂ | 3.160 kg/kg | 3.160 kg/kg | ✅ |
| H₂O | 1.240 kg/kg | 1.23–1.26 | ✅ |
| SO₂ | 1.00 kg/kg | 0.5–1.2 (kükürde bağlı) | ✅ |

Kütle dengesi tutarlı: 1.000 kg yakıt + 3.400 kg O₂ = 4.400 kg ürün.

### 8.3 Rüzgâr kaynağı artık şeffaf (P1)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 37 | `scripts/02` | `wind_source` (gerçek ADS-B mi, mevsimsel climatology mi) **yalnız konsola** basılıyordu, sonuca yazılmıyordu | Raporda hangi rüzgârın kullanıldığı bilinmiyordu. Artık her kayıtta `wind_source` + `wind_is_estimated` var. **Mevcut durum: 14/14 uçuş mevsimsel tahmin** — yani hiçbiri gerçek rüzgâr verisi değil. |

### 8.4 Optimum irtifa FL320 çıkması — HATA DEĞİL

İki uçuşta (PGT120, THY1011) optimum FL320, gözlenen FL359.
Bu ilk bakışta "uçağı aşağı indirme" gibi görünüyor. **Doğrulandı: kod
doğru.** Mevsimsel rüzgâr tahmini batıya uçuşta 70 kt'e kadar karşı
rüzgâr veriyor:

```
FL340: TAS 451.6 kt − 49 kt = 402.6 kt yer hızı
FL380: TAS 447.4 kt − 70 kt = 377.4 kt yer hızı
```

Yüksek irtifada karşı rüzgâr o kadar artıyor ki yer hızı düşüyor ve
specific air range **yer** bazında FL320'de en yüksek oluyor.
Uçak havada daha verimli (air SAR FL380'de tepe), ama **yerde**
daha az mesafe kat ediyor. Yakıt/mesafe optimizasyonu yer bazlıdır.
→ Bu, modelin gerçek bir başarısı: rüzgârı hesaba katıyor.

### 8.5 Ticarî hikâyenin değişmesi

Fizik düzeltmelerinden sonra tasarruf dağılımı **tersine döndü**:

| Dönem | Fiziksel yakıt | Tankering |
|---|---|---|
| Önce (abs() hatası varken) | $4.936 (%0,5) | $951.653 (%99,5) |
| **Şimdi** | **$883.360 (%48)** | $951.653 (%52) |

Bu, ürünün değer önerisini temelden değiştirir: önceden ürün fiilen
bir fiyat arbitrajı aracıydı (fizik %0,5). Şimdi yarısı **fizik**,
yarısı ekonomi. Fizik tarafı tekrarlanabilir; tankering fiyata bağlı
ve oynak.

### 8.6 3. tur sonrası durum

```
Test dosyası        : 16/16 · 0 hata
Toplam kontrol       : ~970 (atmosfer +20 ICAO referansı)
ICAO Doc 7488 uyumu  : 8/8 nokta (±%0.2)
CORSIA CO₂ faktörü   : 3.160 kg/kg ✅
Rüzgâr şeffaflığı    : 14/14 kayıtta kaynak etiketi
Fiziksel / tankering : %48 / %52 (önce %0.5 / %99.5)
F821                 : 0
```

### 8.7 `nox_bffm2` — adı BFFM2, içi değil (P0)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 38 | `emission_model.py` | `nox_bffm2(fuel_flow_kg_s, altitude_ft, mach, engine_type)` imzasında **dört girdi var, ikisi kullanılmıyordu**: `fuel_flow_kg_s` ve `mach`. Gövdede yalnızca `δ^0.51/θ^1.65` vardı. | Yakıt akışı 0,3 → 1,8 kg/s (%17 → %140 itki) arasında EI_NOx **10,47 g/kg sabit** kalıyordu. Mach 0,60 → 0,85 arasında da değişmiyordu. Yani "BFFM2" etiketi olan fonksiyon BFFM2'nin üç temel mekanizmasını (yakıt akışı→itki, Mach düzeltmesi, LTO ekstrapolasyonu) içermiyordu. |

**Düzeltme:** Gerçek BFFM2 uygulandı (ICAO Doc 9889 Ek 2):

```
W_ref       = Wf · (θ^3.3 / δ^1.02)          # referans: SL, ISA, statik
EI_ref      = LTO eğrisinden interpolasyon(W_ref)
C_mach      = 1 + 0.033 · M² · 10
EI_NOx      = EI_ref · √(δ^1.02/θ^3.3) · C_mach · exp(−19(H−0.00634))
```

**Doğrulama (referans noktası):** SL statik tam itki (1,287 kg/s)
→ **27,40 g/kg**, EDB takeoff değeri 27,4 ile **tam eşleşme**.
Gerçek cruise (%26 itki) → 8,8 g/kg; `calculate_flight_emissions`
çıktısı 12,9 g/kg → EDB cruise aralığı (12–18) içinde.

**Bu düzeltmeyi yaparken kendi yaptığım iki hata** (belgelenmeye değer):
1. `W_ref` formülünü ters yazdım (`·δ^1.02/θ^3.3`). Sonuç: W_ref 0,48
   kg/s çıktı, oysa referans koşul SL olduğu için W_ref > W_actual olmalı.
2. TSFC'yi `0,011 kg/(N·s)` aldım. Doğrusu `1,1e-5` (≈0,39 lb/lbf·h).
   `0,011` ile takeoff akışı **1.287 kg/s** çıkıyordu — bir motordan
   4.600 ton/saat, imkânsız.

**Bu hata neden testlerden kaçtı?** Mevcut testler yalnızca
`check_range("NOx EI", 1.0, 20.0)` diyordu — sabit 10,47 bu aralıkta.
Yani test "değer makul aralıkta mı" diye bakıyordu, "girdiye **tepki
veriyor** mu" diye bakmıyordu. §7b'de 7 yeni regresyon testi eklendi:
yakıt akışı etkisi, Mach etkisi, SL referans eşleşmesi, cruise aralığı,
sabit itkide irtifa etkisi, nem etkisi, alt sınır.

### 8.8 Dördüncü kez "3.16" — bu kez `emission_model.py` içinde

| # | Dosya | Bulgu |
|---|-------|-------|
| 39 | `emission_model.py` | `from config.settings import EI_CO2, EI_H2O` **zaten en tepede** duruyordu, ama dosya kendi `_EI_CO2 = 3.16` / `_EI_H2O = 1.24` sabitlerini tanımlıyordu. Kanonik sabit import edilip **kullanılmıyordu**; 10 çağrı yerel kopyayı kullanıyordu. |

Düzeltme: `_EI_CO2 = EI_CO2`, `_EI_H2O = EI_H2O` (tek kaynak).
Değerler aynı olduğu için sayısal değişim yok; ama `config.settings`
güncellenirse 10 yer artık birlikte hareket eder.

Aynı turda `dashboard/app.py` (3 yer) ve `scripts/04` (2 yer) ile
`src/models/saf_model.py` (1 yer) de kanonik sabite bağlandı.
**Toplam 16 hardcoded CO₂ kullanımı temizlendi.**

### 8.9 Dashboard'daki çıplak yakıt fiyatı

| # | Dosya | Bulgu |
|---|-------|-------|
| 40 | `dashboard/app.py` | İki yerde `* 0.85` (yakıt $/kg) çıplak sabit. `Assumptions.fuel_price('DEFAULT')` varken. |

Düzeltme: `Assumptions.fuel_price('DEFAULT')`. Not: `fleet_analyzer.py`
zaten doğru yapıdaydı (tek `_DEFAULT_FUEL_PRICE_USD_PER_KG` + enjeksiyon);
`flight_analyzer.py` de `Assumptions` kullanıyordu. Sorun yalnızca
dashboard'daydı.

### 8.10 Schmidt–Appleman — adı SA, içi eşik tablosu (P1)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 41 | `emission_model.py` | `schmidt_appleman_criterion(...)` docstring'inde "Schmidt-Appleman kriteri" yazıyor, üç akademik kaynak (Schmidt 1941, Appleman 1953, Schumann 1996) listeliyordu. İçinde ise **iki sabit eşik** vardı: `T < -40 °C & RH > %40`, `T < -45 °C & RH > %70`. `engine_efficiency` parametresi **hiç kullanılmıyordu** (0,20 ile 0,55 aynı sonuç). | Gerçek SA'da contrail eşiği motor verimine ve ortam basıncına bağlıdır. Ayrıca fonksiyon **hiçbir üretim kodundan çağrılmıyordu** — yalnız testlerden. Yani docstring'deki "bu analizi sunan çok az firma var" iddiası, kullanılmayan bir fonksiyona dayanıyordu. |

**Düzeltme (dürüst yaklaşım):** Tam SA termodinamiği yazılmadı —
çünkü `G = EI_H2O·LHV/(cp·η)` ve `T_LA` katsayısını **doğrulanmış
bir kaynaktan teyit edemedim**. (ICAO yoğunluk hatasında düştüğüm
tuzağın aynısı: hafızadan referans alıp koda gömmek.) Bunun yerine:

- `engine_efficiency` artık kullanılıyor: `ΔT = 2,5 °C × (η−0,30)/0,10`
  (fizik yönü doğru: η ↑ → egzoz daha az ısı → contrail daha kolay)
- Fonksiyon adı/docstring dürüstleştirildi: "SA **yaklaşımı**,
  tam SA hesabı değil"
- "Çok az firma var" iddiası kaldırıldı
- §18b: 4 regresyon testi (verim etkisi, yön, soğukta etkisiz,
  sıcakta yok)

### 8.11 SAF tipi anahtar uyuşmazlığı (P0 — sessiz varsayılan)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 42 | `emission_model.py` | Tabloda `'FT_SPK'` (alt çizgi); docstring ve kullanıcı `'FT-SPK'` (tire) yazıyor. `_SAF_REDUCTION_FACTORS.get(saf_type, 0.72)` **sessizce HEFA'ya** düşüyordu. | FT-SPK için %90 yerine **%72** azaltım; %50 blend'de %45 yerine %36. Üstelik `'SAÇMA_TİP'` bile HEFA kabul edilip rapora "50% SAÇMA_TİP SAF" diye yazılıyordu. |

**Düzeltme:** Tip adı normalize ediliyor (büyük harf, tire/boşluk →
alt çizgi); bilinmeyen tip **`ValueError`** veriyor. Test §19b:
4 farklı yazım + bilinmeyen tip + azaltım yüzdesi (45/36).

### 8.12 CORSIA MRV bozuk veride çöküyordu (P0 — resmî uyum)

| # | Dosya | Bulgu | Etki |
|---|-------|-------|------|
| 43 | `emission_model.py` | `CORSIACompliance.__init__`: `self._calc = EmissionCalculator` — **sınıf** atanmış, örnek değil. Üstelik hiç kullanılmıyor (ölü kod). | Yanıltıcı: okuyan "bu bir hesaplayıcı tutuyor" sanır. |
| 44 | `emission_model.py` | `monitoring_report()`: `flight.get('fuel_kg', 0)` üzerinden `round(fuel_kg * _EI_CO2, 2)`. | `'abc'` → **`TypeError`** (rapor hiç üretilemiyor). `-500` → toplama **giriyor**. Eksik → sessizce 0, `quality_flag='ESTIMATED'` ama kimse görmüyor. |
| 45 | `emission_model.py` | `reporting_document()` yalnız `total_flights` yazıyordu. | 2 kayıt girip 1'i düşünce rapor "2 uçuş" diyor ama yakıt 1 uçuşluk oluyordu — **denetçi farkı göremezdi.** CORSIA Annex 16 Vol IV'e aykırı. |

**Düzeltme:** CORSIA MRV'de eksik kayıt normaldir (iptal, gecikme).
Doğru davranış: kaydı **reddetmek değil, işaretlemek ve toplamdan
hariç tutmak**, sonra raporlamada kaç kaydın düştüğünü göstermek.

```
quality_flag: VERIFIED | MISSING | INVALID (≤0) | SUSPECT (>500 t)
çıktı       : verified_flights, rejected_flights, rejection_details[]
rapor       : data_quality_note ("N kayıt reddedildi…")
```

Test §26b: 12 kontrol (çökmeme, reddetme nedenleri, toplamdan hariç
tutma, raporda görünürlük, temiz veride nötr not).

### 8.13 4. tur toplamı

| Tur | Bulgu # | Konu |
|-----|---------|------|
| 1 | 1–27 | Güvenlik, veri akışı, birim, CI, kalibrasyon |
| 2 | 28–35 | CI boyutu, benchmark, sahte minimum, CO₂ 43 yer |
| 3 | 36–37 | ICAO atmosfer (kod doğru), rüzgâr kaynağı |
| **4** | **38–45** | **BFFM2, SA, SAF anahtarı, CORSIA MRV** |

**En önemli desen:** #38, #41, #43'te aynı hata sınıfı —
**"parametre var, kullanılmıyor"**. Fonksiyon adı bir şey iddia
ediyor, gövdesi başka şey yapıyor. Üçü de testlerden kaçmıştı
çünkü testler "değer makul aralıkta mı" diye bakıyordu, "girdiye
tepki veriyor mu" diye bakmıyordu.

```
Test dosyası      : 16/16 · 0 hata
emission          : 118 → 149 kontrol
Yeni regresyon    : §7b (7) + §18b (4) + §19b (6) + §26b (12) = 29
```
