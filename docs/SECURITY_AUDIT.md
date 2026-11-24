# GreenWing Analytics — Güvenlik Denetimi Raporu

**Tarih:** 22 Kasım 2026
**Kapsam:** Tüm depo (83 dosya, ~24.000 satır Python + YAML + HTML + JSON)
**Yöntem:** Manuel kod incelemesi + Bandit (SAST) + pip-audit (SCA) + yüksek-entropi sır taraması + git geçmişi taraması

---

## 🔴 ACİL — HEMEN YAPILMASI GEREKEN

### Sır rotasyonu (Rotate now)

Depo **herkese açık** (`github.com/greenwingsfounder/GreenWing_Analytics`, `private: false`).
`credentials.json` içindeki OpenSky OAuth2 istemci sırrı **halka açık biçimde yayınlandı**.

```
clientId     : emrecrkc-api-client
clientSecret : ehRNCoYIsKMVsI6O9yEUA1CFJMMvqnNA   ← ARTIK GÜVENİLMEZ
```

Dosya depodan ve çalışma dizininden kaldırıldı, ancak **git geçmişinde duruyor**
(`c9414f3`) ve dosya zaten bir kez halka açık olarak yayınlandı. Bu yüzden:

1. ✅ **OpenSky panelinden bu istemci sırrını HEMEN iptal et / rotate et.**
   <https://opensky-network.org/my-opensky/account>
2. Yeni sırrı yalnızca `.env` dosyasına yaz (artık `.gitignore`'da).
3. Public repoda sır **kalıcı olarak** kalacağı için git geçmişini temizlemek
   tek başına yeterli olmaz — rotasyon zorunludur.
4. (Opsiyonel ama önerilir) Depoyu geçici olarak `private` yap ve GitHub
   **Secret Scanning / Push Protection**'ı aç.

> Ders: sızıntı **yalnızca kaynak dosyada değil**, git geçmişinde de yaşar.
> Sır bir kez commit'lendiyse "sırrı silmek" ≠ "sırrı güvene almak".

---

## 📊 ÖZET TABLO

| # | Önem | Bulgu | Durum |
|---|------|-------|-------|
| 1 | 🔴 Kritik | Depoda commit edilmiş OAuth2 gizli anahtarı | ✅ Kaldırıldı + rotasyon gerekli |
| 2 | 🔴 Kritik | `.gitignore` yok → tüm sırlar/veriler takip edilebilir | ✅ Oluşturuldu |
| 3 | 🟠 Yüksek | Dashboard debug varsayılan `True` → uzaktan kod çalıştırma (RCE) | ✅ Varsayılan `False` |
| 4 | 🟠 Yüksek | **Veri bütünlüğü**: sentetik veri "gerçek radar verisi" olarak etiketleniyordu | ✅ Provenance damgası eklendi |
| 5 | 🟠 Yüksek | Rapor üretecinde XSS (kaçışlanmamış havayolu adı) | ✅ `escape_html` |
| 6 | 🟠 Yüksek | Rapor dosya adında path traversal | ✅ `sanitize_filename` |
| 7 | 🟡 Orta | CLI/API `callsign` → dosya adı + URL enjeksiyonu | ✅ Katı doğrulama |
| 8 | 🟡 Orta | `09_clean_and_backup.py` onaysız geri dönüşsüz veri siliyor | ✅ `--yes-i-am-sure` zorunlu |
| 9 | 🟡 Orta | Bağımlılık CVE'leri (eski minimum sürümler) | ✅ Sürümler yükseltildi |
| 10 | 🟡 Orta | Vaka çalışmasında sabit "Real ADS-B" iddiası | ✅ Dinamik alt başlık |
| 11 | 🟢 Düşük | `except:` çıplak yakalama (hata gizleme) | ✅ Belirgin istisnalar |
| 12 | 🟢 Düşük | `setup.py`'de yanlış repo URL / optimize edilemeyen `assert` kontrolleri | ⚠️ Not edildi |

---

## 🔍 BULGULARIN DETAYI

### 1. 🔴 Gizli anahtar (`credentials.json`)

**Ne bulundu:** Depo kökünde düz metin OAuth2 istemci kimliği + sırrı. Hiçbir
kod bu dosyayı okumuyordu (collector zaten `.env` kullanıyordu) — yani dosya
tamamen gereksiz bir sızıntıydı.

**Düzeltme:**
- Dosya `git rm --cached` + diskten silindi.
- Yeni `config/secrets.py`: kimlik bilgileri yalnızca ortam değişkeninden okunur;
  `__repr__` sırları maskeler (yanlış loglamada bile ifşa olmaz).
- `OpenSkyCollector` artık bu modülü kullanıyor.
- `tests/test_security.py` sır sızarsa testi kırar.

### 2. 🔴 `.gitignore` yokluğu

Her türlü `.env`, anahtar, müşteri yakıt verisi ve üretilen rapor commit'e açıktı.
Kapsamlı `.gitignore` eklendi (`.env*`, `credentials*.json`, `*.pem`, `*.key`,
`data/customer_fuel/`, `data/calibrations/`, vb.) ve `.env.example` şablonu
(boş değerlerle) oluşturuldu.

### 3. 🟠 Dashboard debug modu (CWE-94 / CWE-489)

`DASHBOARD_DEBUG` varsayılanı `True` idi. Dash/Flask'ta `debug=True`, Werkzeug
etkileşimli hata ayıklayıcısını açar; bu, ağa açık bir kurulumda **uzaktan
keyfi kod çalıştırma** demektir. Varsayılan `False` yapıldı, README ve
`.env.example` uyarıldı.

### 4. 🟠 Veri bütünlüğü / "greenwashing" riski (en önemli bulgu)

Bu bir klasik güvenlik açığı değil ama **hukuki ve itibar riski** açısından en
ciddi bulgu:

- `scripts/06_seed_real_data.py` dosyaları **matematiksel olarak üretiyor** (simülasyon).
- `opensky_collector.py` bu dosyaları `'data/archive/opensky_real/'` altından
  yüklüyor, ardından:
  - `"✨ Gerçek Radar Uçuş Kaydı Yüklendi"` diye logluyordu,
  - zaman damgalarını **"canlıymış gibi" ileri kaydırıyordu** (live time-shifting),
  - `collection_method`'ı `'arrivals'`/`'active_flight'` (gerçek) olarak işaretliyordu.
- `03_generate_outputs.py` her vaka çalışmasına sabit
  `"Based on Real ADS-B Flight Data"` alt başlığını koyuyordu — `batch_results.json`
  ise **231 kaydın tamamı `demo_simulation`** idi.

**Sonuç:** Bir müşteriye/denetçiye sunulan raporda simülasyon verisi "gerçek uçuş
verisi" olarak beyan ediliyordu. CORSIA/denetim bağlamında bu ciddi bir uyum
(compliance) ve güven sorunudur.

**Düzeltme:**
- Yedek veri artık `collection_method="synthetic_fallback"`,
  `data_provenance="synthetic_simulation"`, `is_synthetic=True` damgalarıyla işaretlenir.
- Zaman kaydırma (time-shifting) **kaldırıldı** — orijinal zaman damgaları korunur.
- Vaka çalışması alt başlığı artık veriye göre dinamik:
  sentetikse `"Synthetic Simulation Data — Not Real Flight Records"`.
- `06_seed_real_data.py` docstring'i dürüstçe "sentetik üreteç" olarak düzeltildi.

### 5. 🟠 XSS — Rapor üretimi (CWE-79)

`generate_fleet_report(airline_name=...)` serbest metni doğrudan HTML f-string'ine
gömüyordu. Zararlı bir havayolu adı rapora `<script>` enjekte edebilirdi.
`escape_html()` eklendi; tüm serbest metinler kaçışlanıyor.

### 6. 🟠 Path traversal — Rapor dosya adı (CWE-22)

`output_filename` doğrulanmadan `os.path.join`'e giriyordu; `../../x` ile proje
dışına yazılabilirdi. `sanitize_filename()` eklendi (test edildi: `../../etc/passwd` → `x`).

### 7. 🟡 Girdi doğrulama — `callsign` (CWE-22 / CWE-918)

`scripts/07` ve `08`: `callsign` hem URL yoluna (`/v2/callsign/{callsign}`) hem
dosya adına giriyordu. `../../etc/passwd` veya `THY1; rm -rf /` gibi girdiler
sorun yaratabilirdi. `^[A-Z0-9]{3,8}$` deseniyle katı doğrulama eklendi.

### 8. 🟡 Yıkıcı temizleme script'i

`09_clean_and_backup.py --mode clean` yedek almadan dosya siliyor ve
`--target` argümanı hiç kullanılmıyordu. Yıkıcı modlar artık `--yes-i-am-sure`
onayı ister; çıplak `except:` yerine `except OSError:` kullanılır.

### 9. 🟡 Bağımlılık CVE'leri (SCA)

`pip-audit` yalnızca geçişli (transitive) bir paket sorunu gösterdi; ancak
`requirements.txt` çok eski minimumları (`dash>=2.0.0`, `jinja2>=3.0.0`,
`pyyaml>=5.4.0`, `requests>=2.26.0`) kabul ediyordu. Bu aralıklar bilinen CVE'li
sürümleri (Jinja2 sandbox kaçışları, PyYAML eski yükleyiciler, requests
`.netrc` sızıntısı) içerir. Minimumlar güvenli sürümlere yükseltildi
(`jinja2>=3.1.5`, `requests>=2.32.4`, `pyyaml>=6.0.1`, `dash>=2.15.0`).
`setup.py` senkronize edildi.

### 10. 🟡 Sabit "Real ADS-B" iddiası

Bulgu #4 ile aynı kökten. `_resolve_data_source_subtitle()` eklendi.

### 11. 🟢 `except:` çıplak yakalamalar

`KeyboardInterrupt` dahil her şeyi yutuyordu. Belirgin istisna türleriyle değiştirildi.

---

## ✅ DOĞRULAMA

Tüm değişikliklerden sonra:

```
Bandit (SAST)          : 0 MEDIUM, 0 HIGH  (yalnızca 27 LOW: assert/random/try-pass)
pip-audit (SCA)        : uygulama bağımlılıklarında doğrudan CVE yok
Test paketi            : 14/14 dosya PASS
  ├─ 13 mevcut test     : PASS
  └─ test_security.py   : 18/18 yeni güvenlik testi PASS
Dashboard import       : OK (231 satır yüklendi)
```

**Kontrol edilip temiz bulunan alanlar** (ek önlem gerekmedi):

- `eval` / `exec` / `os.system` / `subprocess(shell=True)` → **yok**
- `pickle` / `marshal` / `shelve` deserialization → **yok**
- YAML yüklemeleri → tümü `safe_load` ✅
- `verify=False` (TLS kapatma) → **yok**
- SQL enjeksiyonu → SQL veritabanı yok
- Sabit kodlanmış parola/token → **yok** (B105 uyarıları yalnızca `'✅'` emojisi — false positive)
- HMAC/sır karşılaştırması → kriptografik doğrulama yok (yalnızca bütünlük için SHA-256; uygun)

---

## 📋 SENİN YAPMAN GEREKENLER (kontrol listesi)

- [ ] **OpenSky istemci sırrını iptal/rotate et** (en acil)
- [ ] Yeni sırrı yalnızca yerel `.env` dosyasına koy (`OPENSKY_CLIENT_SECRET=...`)
- [ ] Git geçmişini temizlemek istersen: `git filter-repo` veya BFG Repo-Cleaner
      (not: sır zaten yayınlandığı için rotasyon yine zorunlu)
- [ ] GitHub → Settings → Code security → **Secret scanning + Push protection** aç
- [ ] Üretimde `DASHBOARD_DEBUG=false` ve `DASHBOARD_HOST=127.0.0.1` (ters proxy arkası)
- [ ] CI'a `python tests/test_security.py` + `bandit -ll` + `pip-audit` ekle

---

## 🔭 SONRAKİ ADIM ÖNERİLERİ (güvenlik dışı, ilerleme için)

1. **Provenance'ı raporlara yay:** `03_generate_outputs.py` dışında kalan rapor
   şablonlarında da `data_provenance` alanını görünür kıl.
2. **`batch_results.json` yeniden üret:** Mevcut dosya `demo_simulation`; gerçek
   veriyle yenilendiğinde alt başlık otomatik "Real ADS-B" olacak.
3. **Kimlik doğrulama katmanı:** Dashboard'a erişim kontrolü (temel auth / ters
   proxy) ekle — şu an herkes okuyabilir.
4. **CI/CD:** GitHub Actions ile test + Bandit + pip-audit + secret scan otomasyonu.
5. **Bağımlılık kilitleme:** `requirements.txt`'i `pip-compile` ile hash'li
   `requirements.lock`'a çevir (tedarik zinciri güvenliği).
