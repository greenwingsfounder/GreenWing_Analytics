#!/usr/bin/env python3
"""
GreenWing Analytics — Pilot Müşteri Veri Paketi Üreteci
═══════════════════════════════════════════════════════════════════════════

TİCARİ AŞAMA 1'İN İLK SOMUT ADIMI
──────────────────────────────────
Bir havayoluna "veri ver" demek yetmez; **ne isteyeceğini** bilmen gerek.
Bu script üç dosya üretir:

  1. `01_YAKIT_VERISI_SABLONU.csv`  — müşterinin dolduracağı dosya
  2. `02_VERI_ISTEK_MEKTUBU.md`     — veri talebini açıklayan mektup
  3. `03_KABUL_KRITERLERI.md`       — doğruluk taahhüdünün ölçütü

NEDEN BU ÜÇÜ
─────────────
Aşama 1'in kabul ölçütü "model gerçek yakıta ±%10 uysun"dur. Bunu
kanıtlamak için:
  • Gerçek yakıt (fiş/OFP) → şablon
  • Modelin aynı uçuşu hesaplaması → aynı şablon
  • İkisinin farkı → kabul kriteri

Bu dosyalar olmadan pilot başlamaz; olanla pilot 2 haftada biter.

KULLANIM
────────
    python tools/build_pilot_data_package.py
    python tools/build_pilot_data_package.py --airline "Pegasus" --routes 30
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'deliverables' / 'pilot_paketi'

# ── Şablon kolonları ─────────────────────────────────────────────────
# Üç grup: ZORUNLU (bu olmadan hesap yok) · ÖNERİLEN (doğruluğu artırır)
#          OPSİYONEL (faydalı ama bloklamaz)
COLUMNS = [
    # (kolon, örnek, grup, açıklama)
    ('ucus_no', 'PC1201', 'ZORUNLU', 'Uçuş numarası (callsign)'),
    ('tarih', '2026-11-15', 'ZORUNLU', 'Kalkış tarihi (YYYY-AA-GG)'),
    ('kalkis', 'LTFJ', 'ZORUNLU', 'Kalkış meydanı ICAO'),
    ('varis', 'EHAM', 'ZORUNLU', 'Varış meydanı ICAO'),
    ('ucak_tipi', 'B738', 'ZORUNLU', 'ICAO tip kodu (B738, A20N...)'),
    ('kuyruk_no', 'TC-CPN', 'ÖNERİLEN', 'Tescil (dijital ikiz için)'),
    ('kalkis_zamani', '2026-11-15T07:35Z', 'ZORUNLU', 'Gerçek kalkış (UTC)'),
    ('varis_zamani', '2026-11-15T11:10Z', 'ZORUNLU', 'Gerçek iniş (UTC)'),
    ('taksi_yakiti_kg', '180', 'ÖNERİLEN', 'Taksi yakıtı (kg)'),
    ('blok_yakit_kg', '6450', 'ZORUNLU', 'Blok yakıt: kalkış öncesi − iniş sonrası'),
    ('ucus_yakiti_kg', '6270', 'ÖNERİLEN', 'Havada tüketilen (blok − taksi)'),
    ('cruise_irtifasi_ft', '37000', 'ZORUNLU', 'Seyir irtifası (ortalama veya ilk)'),
    ('ortalama_mach', '0.785', 'ÖNERİLEN', 'Ortalama cruise Mach'),
    ('ziyaret_yuku_kg', '14800', 'ÖNERİLEN', 'Kalkıştaki payload (yolcu+kargo)'),
    ('yakit_fiyati_usd_kg', '0.82', 'ÖNERİLEN', 'O uçuşun gerçek yakıt fiyatı'),
    ('planlanan_yakit_kg', '6380', 'OPSİYONEL', 'OFP planı (sapma analizi için)'),
    ('notlar', '', 'OPSİYONEL', 'Anomali, holding, diversion vb.'),
]

EXAMPLE_ROWS = [
    ['PC1201', '2026-11-15', 'LTFJ', 'EHAM', 'B738', 'TC-CPN',
     '2026-11-15T07:35Z', '2026-11-15T11:10Z', '180', '6450', '6270',
     '37000', '0.785', '14800', '0.82', '6380', ''],
    ['PC1202', '2026-11-15', 'LTFJ', 'EDDF', 'B738', 'TC-CPP',
     '2026-11-15T12:20Z', '2026-11-15T15:05Z', '175', '5620', '5445',
     '35000', '0.780', '13900', '0.82', '5580', ''],
    ['PC1203', '2026-11-16', 'LTFJ', 'LTAI', 'A20N', 'TC-NBA',
     '2026-11-16T06:10Z', '2026-11-16T07:25Z', '145', '3180', '3035',
     '33000', '0.770', '16200', '0.86', '3110', 'kısa sektör'],
]

LETTER = """# Pilot Veri Talebi — {airline}

**Kimden:** GreenWing Analytics
**Kime:** {airline} — Yakıt Yönetimi / Uçuş Operasyonları
**Tarih:** {date}
**Konu:** {routes} uçuşluk doğruluk pilotu için veri talebi

---

## 1 · Ne istiyoruz ve neden

GreenWing, uçuş bazında yakıt tüketimini **fizik modeliyle** hesaplayan
bir karar destek sistemidir (aerodinamik polar + motor TSFC + ISA
atmosferi). Bugüne kadar model **sentetik** uçuş profilleriyle
doğrulandı; gerçek uçuşla kıyaslanmadı.

Doğruluk iddiasında bulunabilmemiz için **{routes} uçuşun gerçek yakıt
verisine** ihtiyacımız var. Karşılığında:

- **Ücretsiz pilot analiz** — tüm uçuşlar için tasarruf raporu
- **Doğruluk raporu** — modelin sizin verinizde ne kadar saptığı,
  uçuş bazında açıkça yazılmış
- **Belirsizlik analizi** — hangi varsayım ne kadar etkiliyor, sayısal
- Veri kullanımı **yalnızca bu pilot için**; üçüncü tarafla paylaşılmaz

## 2 · Neye ihtiyacımız var

Ekli `01_YAKIT_VERISI_SABLONU.csv` dosyasını doldurmanız yeterli.
Toplam **16 kolon**, bunların **8'i zorunlu**:

| Grup | Kolon sayısı | Not |
|---|---|---|
| Zorunlu | 8 | Bu olmadan hesap yapılamaz |
| Önerilen | 6 | Doğruluğu belirgin artırır |
| Opsiyonel | 2 | Faydalı ama bloklamaz |

**En kritik 3 veri:**
1. `blok_yakit_kg` — gerçek tüketim (fiş veya ACARS)
2. `cruise_irtifasi_ft` — seyir irtifası
3. `ucak_tipi` — tip kodu

## 3 · Hangi uçuşlar

Tercihen:
- **{routes} uçuş**, son 3 ay içinden
- **Aynı rota grubu** (örn. İstanbul–Batı Avrupa) — kalibrasyon daha temiz
- **Farklı sezon** mümkünse (kış/yaz rüzgâr farkı için)
- Anomali (diversion, uzun holding) varsa `notlar` sütununa yazın;
  hariç tutabiliriz

## 4 · Veri formatı

CSV yeterli. Excel'den "Farklı Kaydet → CSV (virgülle ayrılmış)"
yeterlidir. Birimler:

| Alan | Birim |
|---|---|
| Yakıt | **kg** (ton ise belirtin, dönüştürürüz) |
| İrtifa | **feet** |
| Zaman | **UTC** (ISO 8601) |
| Fiyat | USD/kg |

## 5 · Gizlilik ve sözleşme

- Veri **yalnızca** model doğrulaması için kullanılır
- Üçüncü tarafla paylaşılmaz, yayınlanmaz
- Pilot sonunda veri **silinir** (talep ederseniz; aksi halde kalibrasyon
  için saklanır)
- Gerekirse NDA imzalanır — şablonumuz hazır
- KVKK/GDPR veri işleme sözleşmesi (DPA) eklenebilir

## 6 · Zaman planı

| Hafta | Ne |
|---|---|
| 1 | Veri alışverişi, şablon doldurma |
| 2 | Model çalıştırma, kalibrasyon |
| 3 | Doğruluk raporu + tasarruf analizi teslimi |
| 4 | Sonuç sunumu, geri bildirim |

## 7 · İletişim

[İsim]
[E-posta]
[Telefon]

---

**Ekler:**
- `01_YAKIT_VERISI_SABLONU.csv` — doldurulacak dosya
- `03_KABUL_KRITERLERI.md` — doğruluğu nasıl ölçeceğimiz
"""

CRITERIA = """# Pilot Kabul Kriterleri

**Amaç:** "Model doğru mu?" sorusuna **ölçülebilir** cevap vermek.
Bu belge, pilot sonunda tarafların üzerinde anlaşacağı eşikleri
tanımlar. Aşama 2'de sözleşmeye girecek doğruluk beyanının temeli budur.

## 1 · Karşılaştırma yöntemi

Her uçuş için:

```
sapma_% = (model_yakit − gercek_yakit) / gercek_yakit × 100
```

Model, müşteri verisindeki **aynı** girdileri kullanır:
uçak tipi, rota, kalkış ağırlığı, cruise irtifası, Mach.
Rüzgâr GFS'ten (varsa) veya mevsimselden gelir — hangisi kullanıldıysa
raporda yazılır.

## 2 · Kabul eşikleri

| Metrik | Eşik | Anlamı |
|---|---|---|
| **Ortalama mutlak sapma (MAPE)** | **≤ %10** | Uçuş başına ortalama hata |
| **Toplam sapma** | **≤ %5** | Filo toplamında yanlılık (bias) |
| **En kötü tek uçuş** | ≤ %15 | Aykırı değer sınırı |
| **Sistematik yanlılık** | \|bias\| ≤ %3 | Hep aynı yöne sapmamalı |

**Neden iki farklı eşik:** MAPE uçuş bazında hata büyüklüğünü ölçer;
toplam sapma ise "fleet-wide" doğruluğu. İlki operasyonel güven,
ikincisi finansal taahhüt için gerekir. %10 MAPE + %5 toplam, sektörde
kabul görmüş bir aralıktır (OFP planlama doğruluğu tipik %3-8).

## 3 · Raporlanacaklar

1. Uçuş bazında tablo: gerçek / model / sapma / rüzgâr kaynağı
2. Özet: MAPE, toplam sapma, bias, en iyi/en kötü uçuş
3. Hata ayrıştırma: sapmanın ne kadarı rüzgârdan, ne kadarı modelden
4. Belirsizlik aralığı: modelin kendi ±%'si ile gerçek sapma kıyası
5. **Başarısızlık durumu:** eşik aşılırsa neden, ve düzeltme planı

## 4 · Eşik aşılırsa

Bu bir başarısızlık değil, **bilgi**dir. Süreç:

1. Sapan uçuşları incele (rüzgâr? yanlış tip? eksik veri?)
2. Kalibrasyonu yeniden çalıştır (`model_calibrator.py`)
3. Bir tur daha ölç (2 hafta)
4. Hâlâ aşılıyorsa: eşiği **gerçekçi** seviyeye çek ve sözleşmeye
   **o** aralığı yaz. Yanlış taahhüt, taahhütsüzlükten kötüdür.

## 5 · Sözleşmeye girecek cümle (taslak)

> GreenWing Analytics, analiz edilen uçuşların toplam yakıt tahmininde
> gerçek tüketime göre **±%5**, uçuş bazında **±%10** doğruluk taahhüt
> eder. Bu aralık, [tarih] tarihli pilot çalışmasında ölçülmüştür ve
> ölçüm raporu sözleşme ekinde yer alır. Belirtilen aralığın dışında
> kalan tahminler için [yaptırım/iade] uygulanır.

**Not:** Bu cümleyi yazabilmek için önce **ölçmüş** olman gerek.
Bugün ölçemezsin çünkü karşılaştıracak gerçek veri yok. Pilot tam
bunu çözer.
"""


def build(airline: str, routes: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # 1) CSV şablonu
    csv_path = OUT / '01_YAKIT_VERISI_SABLONU.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow([c[0] for c in COLUMNS])
        w.writerow(['# ÖRNEK SATIR — silin'])  # yanlışlıkla doldurulmasın
        for r in EXAMPLE_ROWS:
            w.writerow(r)
        w.writerow([])
        w.writerow(['# KOLON AÇIKLAMALARI'])
        for name, ex, grp, desc in COLUMNS:
            w.writerow(['#', name, grp, desc, f'örnek: {ex}'])

    # 2) Mektup
    letter_path = OUT / '02_VERI_ISTEK_MEKTUBU.md'
    letter_path.write_text(
        LETTER.format(airline=airline, routes=routes,
                      date=datetime.now().strftime('%d.%m.%Y')),
        encoding='utf-8')

    # 3) Kabul kriterleri
    crit_path = OUT / '03_KABUL_KRITERLERI.md'
    crit_path.write_text(CRITERIA, encoding='utf-8')

    # 4) Okuma dosyası
    req = [c for c in COLUMNS if c[2] == 'ZORUNLU']
    opt = [c for c in COLUMNS if c[2] == 'ÖNERİLEN']
    xs = [c for c in COLUMNS if c[2] == 'OPSİYONEL']
    (OUT / 'OKU.md').write_text(f"""# Pilot Veri Paketi — {airline}

Bu klasörde üç dosya var:

| Dosya | Ne için |
|---|---|
| `01_YAKIT_VERISI_SABLONU.csv` | Müşterinin dolduracağı dosya |
| `02_VERI_ISTEK_MEKTUBU.md` | Veri talebini açıklayan mektup |
| `03_KABUL_KRITERLERI.md` | Doğruluğu nasıl ölçeceğimiz |

## Hızlı özet

- **{len(COLUMNS)} kolon**, {len(req)} zorunlu · {len(opt)} önerilen · {len(xs)} opsiyonel
- Hedef: **{routes} uçuş**, son 3 ay
- En kritik 3 veri: `blok_yakit_kg`, `cruise_irtifasi_ft`, `ucak_tipi`
- Kabul eşiği: MAPE ≤ %10, toplam sapma ≤ %5

## Sıra

1. Mektubu müşteriye gönder (`02_...md`)
2. Müşteri şablonu doldurur (`01_...csv`)
3. `python -m src.ingestion.customer_fuel_ingestor --csv <dosya> --tenant <id>`
4. Kalibrasyon: `python -m src.optimization.model_calibrator`
5. Doğruluk raporu (`03_...md`'deki metriklere göre)

Üretim: {datetime.now():%d.%m.%Y %H:%M}
""", encoding='utf-8')

    print(f'✓ Pilot veri paketi: {OUT}')
    for f in sorted(OUT.iterdir()):
        print(f'  {f.name:36s} {f.stat().st_size:>6,} B')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--airline', default='[Havayolu]')
    ap.add_argument('--routes', type=int, default=30)
    a = ap.parse_args()
    build(a.airline, a.routes)
