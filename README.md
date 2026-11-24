# ✈️ GreenWing Analytics

**Havayolu yakıt verimliliği ve emisyon zekâsı platformu**

Uçuş verisinden yakıt tüketimini fizik modeliyle hesaplar, tasarruf
fırsatlarını dolar ve CO₂ cinsinden gösterir, CORSIA raporlamasına
hazırlar.

> **Durum (2026-11-22):** Çekirdek motor **doğrulanmış** (228 denetim
> kontrolü · 1.501 test · 0 hata). **Gerçek uçuş verisi: 0** — model
> henüz gerçek bir yakıt faturasıyla karşılaştırılmadı.
> Bu yüzden her ekranda "taahhüt değil, gösterge" yazar.

---

## 🚀 Hızlı başlangıç (3 dakika)

```bash
# 1. Kurulum
pip install -r requirements.txt

# 2. Ortam değişkeni (parola)
export GREENWING_DASHBOARD_PASSWORD='GucluBirSifre!'

# 3. Siteyi başlat
python -m uvicorn webapp.app:app --host 0.0.0.0 --port 8052

# 4. Aç
#    http://localhost:8052
```

**Tek giriş noktası var: `webapp/app.py`.** (Eski `web/` ve `dashboard/`
`archive/` altında, kullanılmıyor.)

---

## 📚 Dokümantasyon — nereden başlamalı?

| Soru | Dosya |
|---|---|
| **Bu sistem ne yapar, ne yapamaz?** | [`docs/KOD_ATLASI.md`](docs/KOD_ATLASI.md) |
| **Hangi dosya ne işe yarar?** | [`docs/YAPI_AGACI.md`](docs/YAPI_AGACI.md) |
| **Her sayının kaynağı ne?** | [`docs/MODEL_PROVENANCE.md`](docs/MODEL_PROVENANCE.md) |
| **Hangi hatalar bulundu, nasıl düzeltildi?** | [`docs/FULL_TECHNICAL_AUDIT.md`](docs/FULL_TECHNICAL_AUDIT.md) |
| **Müşteriye ne göndereceğim?** | [`deliverables/pilot_paketi/OKU.md`](deliverables/pilot_paketi/OKU.md) |
| **Ticari olarak hazır mıyım?** | [`docs/COMMERCIAL_READINESS.md`](docs/COMMERCIAL_READINESS.md) |
| **Kod okumadan anlamak istiyorum** | Site → `/basit` sayfası |

---

## 🛠 Gerçek teknoloji yığını

| Bileşen | Teknoloji | Not |
|---|---|---|
| Çekirdek | Python 3.11 | |
| Fizik | ISA (ICAO Doc 7488) · OpenAP polar · ICAO EDB | Her sayı kaynaklı |
| Web | FastAPI + Uvicorn | Tek uygulama, 10 sayfa |
| PDF | ReportLab | El kitabı + teknik rapor |
| Veri | pandas / numpy / PyYAML | |
| **Kullanılmayan** | ~~Dash~~ ~~Jinja şablonları~~ | `archive/` altında |

---

## 🎯 Ne yapıyor?

| Yetenek | Açıklama |
|---|---|
| **Yakıt verimliliği** | Rota bazlı tüketim, benchmark karşılaştırma |
| **İrtifa optimizasyonu** | Optimum seyir irtifası; buffet + RVSM + yön kısıtı |
| **Step climb** | Ağırlığa göre kademeli tırmanış planı |
| **Cost index** | CI/Mach dengesi: yakıt maliyeti vs zaman maliyeti |
| **Tankering** | Yakıt fiyat farkı arbitrajı (MTOW güvenlik kontrolü) |
| **CORSIA** | MRV uyumlu emisyon raporu |
| **SAF** | Sürdürülebilir yakıt yaşam döngüsü ve maliyet |
| **Belirsizlik** | Her sonuç "değer ± hata" biçiminde |
| **Kalibrasyon** | Müşteri verisiyle model yeniden ayarı |

---

## 🗺️ Mimari (tek yönlü bağımlılık)

```
   Radar / CSV
        │
        ▼
   VERİ         src/data_collection · src/ingestion · src/validation
        │
        ▼
   FİZİK        src/models   (atmosphere → performance → fuel → emission)
        │
        ▼
   ANALİZ       src/analysis · src/optimization
        │
        ▼
   SUNUM        src/reporting · webapp
```

**Kural:** Üst katman alt katmanı import eder, tersi olmaz.
`src/units.py` hiçbir şeyi import etmez — her şeyin tek kaynağı
olabilmesinin nedeni budur.

Tam ağaç: [`docs/YAPI_AGACI.md`](docs/YAPI_AGACI.md)
(`python tools/build_tree.py --md` ile yenilenir)

---

## 🧪 Doğrulama — kendin kontrol et

```bash
# 7 katmanlı tam denetim (228 kontrol)
python tools/full_audit.py

# Belirli bir katman
python tools/full_audit.py --layer K5     # fizik

# Tüm testler
python tests/test_webapp.py
python tests/test_aircraft_data_provenance.py

# Yapı ağacını yenile
python tools/build_tree.py --md
```

**Beklenen:** `228/228 · 0 FAIL · HİÇ HATA YOK`

---

## 📊 Boru hattı

```bash
python scripts/02_analyze_and_optimize.py   # ★ ana analiz
python scripts/03_generate_outputs.py       # rapor üret
python scripts/01_collect_data.py           # gerçek veri topla (ağ gerekli)
```

`02` çıktısı sana **dürüst** şekilde şunu söyler:

```
Veri kaynağı : {'synthetic_fallback': 14}
⛔ GERÇEK VERİ YOK — 14 sentetik.
   Ticari taahhüt için gerçek veri şart (0 kayıt).
```

---

## ⚠️ Bilinen sınırlar (gizlemeden)

| Konu | Durum | Etki |
|---|---|---|
| Gerçek uçuş verisi | **0** (14 sentetik) | Model doğrulanmadı |
| Rüzgâr | GFS kodu hazır, GRIB2 yok | Belirsizlik ±%22,2 |
| A20N yakıtı | ICAO EDB'de yok → tahmin | ±%20 sapma riski |
| Geniş gövde poları | +%63 sapma | B77W/B789/A350 dikkatli |
| Veritabanı | Dosya tabanlı | 50+ kullanıcıda DB gerekli |
| MFA | Yok | Kurumsal satışta istenir |
| SLA / yedekleme | Yok | Üretim için gerekli |

---

## 🔐 Kimlik doğrulama

```bash
# Tek kullanıcı
export GREENWING_DASHBOARD_PASSWORD='GucluBirSifre!'

# Çok kullanıcı + rol + kiracı (ticari)
# config/secrets.yaml:
#   users:
#     ali:   {hash: "pbkdf2$...", role: admin,   tenant: thy}
#     veli:  {hash: "pbkdf2$...", role: analyst, tenant: thy}
#     denetci: {hash: "pbkdf2$...", role: viewer, tenant: thy}
```

Hash üretimi: `python -m src.security.auth --hash`

Roller: `viewer` (okuma) < `analyst` (+analiz) < `admin` (tam).

---

## 📄 Lisans / veri kaynakları

- OpenAP: MIT (Junzi Sun, TU Delft)
- ICAO EDB: kamuya açık motor sertifikasyon verisi
- ISA: ICAO Doc 7488/3
- Jet A-1 özellikleri: ASTM D1655

**Gerçek uçuş verisi bulunmuyor** — pilot paketi gerçek veri bekliyor.
