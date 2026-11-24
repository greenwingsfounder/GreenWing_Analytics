# Kodlarımı Nasıl Kullanırım?

> Sıfırdan başlayan biri için. Her adımı kopyala-yapıştır yapabilirsin.

---

## 0. Önce: bu proje nerede?

Kod **GitHub'da**: `greenwingsfounder/GreenWing_Analytics`

Ama **çalışması için bilgisayarına indirmen gerekir.** GitHub'da
"Create PR" gibi düğmeler görürsün — onlar **koda katkı** için,
**çalıştırmak** için değil. Karıştırma.

---

## 1. Bilgisayarına indir (2 dakika)

```bash
# Git kurulu mu?
git --version
# yoksa: https://git-scm.com/downloads

# İndir
git clone https://github.com/greenwingsfounder/GreenWing_Analytics.git
cd GreenWing_Analytics
```

**Alternatif (git bilmiyorsan):** GitHub sayfasında yeşil
`Code` düğmesi → `Download ZIP` → aç.

---

## 2. Python kur (5 dakika)

```bash
python --version     # 3.11 veya üstü olmalı
```

Yoksa: https://python.org/downloads

---

## 3. Bağımlılıkları kur (3 dakika)

```bash
pip install -r requirements.txt
```

Hata alırsan sanal ortam kullan:

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## 4. Siteyi aç (30 saniye)

```bash
# Parola belirle (Windows'ta: set GREENWING...)
export GREENWING_DASHBOARD_PASSWORD='GucluBirSifre!'

python -m uvicorn webapp.app:app --host 0.0.0.0 --port 8052
```

Tarayıcıda aç: **http://localhost:8052**
Kullanıcı: `__admin__` · Parola: `GucluBirSifre!`

✅ **Bu kadar. 10 sayfalık site çalışıyor.**

---

## 5. Hata var mı, kontrol et (30 saniye)

```bash
python tools/full_audit.py
```

Beklenen çıktı:

```
K1 · Statik analiz        10/10
K2 · Import bütünlüğü     56/56
K3 · Sınıf örnekleme      45/45
K4 · Çağrı izi            28/28
K5 · Fizik tutarlılığı    51/51
K6 · Uçtan uca akış       28/28
K7 · Arayüz               10/10
TOPLAM: 228/228 kontrol geçti · 0 FAIL
✓ HİÇ HATA YOK — sistem temiz
```

---

## 6. Analiz çalıştır (1 dakika)

```bash
python scripts/02_analyze_and_optimize.py
```

Çıktıda **şunu göreceksin** (bu iyi bir şey, dürüstlük):

```
Veri kaynağı : {'synthetic_fallback': 14}
⛔ GERÇEK VERİ YOK — 14 sentetik.
```

Yani: hesap makinesi çalışıyor ama henüz **gerçek faturayla
karşılaştırılmadı**.

Sonra rapor üret:

```bash
python scripts/03_generate_outputs.py
```
→ `reports/GreenWing_CaseStudy_*.html` aç (tarayıcıda)

---

## 7. PDF'ler nerede?

İki yerde var:

| Nerede | Nasıl |
|---|---|
| **Depoda hazır** | `reports/GreenWing_Teknik_Rapor.pdf`<br>`reports/GreenWing_Proje_El_Kitabi.pdf` |
| **Siteden indir** | `/rapor/teknik.pdf` · `/rapor/elkitabi.pdf`<br>(giriş yapınca) |

Yeniden üretmek istersen:

```bash
python tools/build_technical_report.py
python tools/build_handbook.py
```

---

## 8. Kendi verinle denemek

Müşteriden yakıt verisi aldığında:

```bash
# 1. Şablonu al
deliverables/pilot_paketi/01_YAKIT_VERISI_SABLONU.csv

# 2. Doldur (16 kolon, 8 zorunlu — başlık satırına bak)

# 3. data/customer_fuel/ içine koy

# 4. Kalibrasyonu çalıştır
python scripts/10_pre_real_ingestion_demo.py

# 5. Yeniden analiz
python scripts/02_analyze_and_optimize.py
```

Sonuçta `data/calibrations/` içinde modelin ayarlanmış hâli çıkar.

### Bu betiğin GERÇEKTE ne yaptığı (dürüst hâli)

Boru hattı **üç kapıdan** geçer; biri düşerse kalibrasyonu
KABUL ETMEZ ve yazar. Bu kasıtlıdır — kötü kalibrasyonu sessizce
kabul eden bir sistem havayoluna veri satamaz.

| Kapı | Eşik | Ne demek |
|---|---|---|
| Eşleşme | **≥ 12 uçuş** | Müşteri yakıt satırı ile uçuş izi eşleşmeli |
| Model iyileşmesi | **≥ %4** | Kalibrasyon hatayı gerçekten azaltmalı |
| Kalan sapma | **≤ %6,5** | Kalibrasyon sonrası ortalama hata |

Eşikler `config/ingestion_config.py` içinde, **gerekçeleriyle**
yazılıdır. Neden 12: 10 parametreli modelde n ≥ ~10·p kuralının alt
sınırı. Hedef 30+ uçuştur; 12 yalnızca "bu veriyle konuşulabilir mi"
sınırıdır.

**Şu anki durum:** Depoda 14 uçuş var; mock bu 14 uçuştan türetiliyor
ve 13/13 eşleşiyor. Ama mock **sentetik** olduğu için kalibrasyon
modeli %22,6 sapmayla bitiyor → üçüncü kapı reddediyor. Bu doğru
davranış: sentetik veri kalibrasyon için temsili değildir. Gerçek
pilot verisi geldiğinde aynı komut aynı yerde çalışır.

Çıktının anlamı:

```
❌ PIPELINE REJECTED
   Message: Quality gate failed (imp=17.2%, after=22.6%)
   Action: model sapması eşiğin üstünde. BU İYİ BİR ŞEY —
           sistem kötü kalibrasyonu KABUL ETMİYOR.
```

`SUCCESS` görürsen kalibrasyon kabul edildi ve
`data/calibrations/*.json` yazıldı demektir.

---

## 9. Sık yapılan hatalar

| Hata | Neden | Çözüm |
|---|---|---|
| `ModuleNotFoundError: src` | Yanlış klasördesin | `cd GreenWing_Analytics` |
| `GreenWing parola yok` | Ortam değişkeni unutuldu | `export GREENWING_DASHBOARD_PASSWORD=...` |
| `Address already in use` | Port 8052 dolu | `--port 8053` dene |
| `ImportError: randbits` | `config/` dizinindesin | `cd ..` (kök dizine dön) |
| Bağlantı yok | Sunucu `0.0.0.0` dinlemiyor | `--host 0.0.0.0` ekle |

---

## 10. Hangi dosya ne yapar? (hızlı bakış)

```
webapp/app.py            ← SİTE (açtığın şey)
src/units.py             ← tüm sabitlerin kaynağı
src/models/fuel_model.py ← yakıt hesabı (kalp)
config/aircraft_database.yaml ← uçak verileri
scripts/02_analyze...py  ← ana analiz
tools/full_audit.py      ← hata kontrolü
deliverables/pilot_paketi/ ← müşteriye gidecekler
docs/KOD_ATLASI.md       ← her dosya + her sayının kaynağı
docs/YAPI_AGACI.md       ← tam ağaç
```

---

## 11. Sırada ne var?

1. `docs/KOD_ATLASI.md` oku — her modülün ne yaptığını anla
2. `/basit` sayfasını oku — jargonsuz özet
3. `deliverables/pilot_paketi/02_VERI_ISTEK_MEKTUBU.md` — havayoluna
   göndereceğin mektup hazır
4. Gerçek veri gelince: `data/customer_fuel/` → `scripts/10_...`

---

## 12. Yardım

```bash
python tools/full_audit.py          # ne bozuk?
python tools/build_tree.py --md     # ağaç
python tests/test_webapp.py         # site çalışıyor mu?
```

Her dokümanda "neden böyle" yazılı. Emin olmadığın bir sayı görürsen
`grep -B8 "SAYI" dosya.py` ile kaynağını bulabilirsin.
