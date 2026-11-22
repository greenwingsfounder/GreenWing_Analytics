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
