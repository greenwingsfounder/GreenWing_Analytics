# Pilot Veri Paketi — [Havayolu]

Bu klasörde üç dosya var:

| Dosya | Ne için |
|---|---|
| `01_YAKIT_VERISI_SABLONU.csv` | Müşterinin dolduracağı dosya |
| `02_VERI_ISTEK_MEKTUBU.md` | Veri talebini açıklayan mektup |
| `03_KABUL_KRITERLERI.md` | Doğruluğu nasıl ölçeceğimiz |

## Hızlı özet

- **17 kolon**, 9 zorunlu · 6 önerilen · 2 opsiyonel
- Hedef: **30 uçuş**, son 3 ay
- En kritik 3 veri: `blok_yakit_kg`, `cruise_irtifasi_ft`, `ucak_tipi`
- Kabul eşiği: MAPE ≤ %10, toplam sapma ≤ %5

## Sıra

1. Mektubu müşteriye gönder (`02_...md`)
2. Müşteri şablonu doldurur (`01_...csv`)
3. `python -m src.ingestion.customer_fuel_ingestor --csv <dosya> --tenant <id>`
4. Kalibrasyon: `python -m src.optimization.model_calibrator`
5. Doğruluk raporu (`03_...md`'deki metriklere göre)

Üretim: 22.11.2026 18:04
