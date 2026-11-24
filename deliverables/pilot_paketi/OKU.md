# Pilot Veri Paketi — [Havayolu]

Bu klasörde dört dosya var:

| Dosya | Ne için | Kim okur |
|---|---|---|
| `01_YAKIT_VERISI_SABLONU.csv` | Müşterinin dolduracağı dosya | Veri sahibi |
| `02_VERI_ISTEK_MEKTUBU.md` | Veri talebini açıklayan mektup | Yakıt verimliliği müdürü |
| `03_KABUL_KRITERLERI.md` | Doğruluğu nasıl ölçeceğimiz | Karar verici |
| **`04_PILOTLA_KONUSMA_REHBERI.md`** | **Sahada pilotla nasıl konuşulur** | **Sen** |

## Hızlı özet

- **17 kolon**, 9 zorunlu · 6 önerilen · 2 opsiyonel
- Hedef: **30 uçuş**, son 3 ay
- En kritik 3 veri: `blok_yakit_kg`, `cruise_irtifasi_ft`, `ucak_tipi`
- Kabul eşiği: MAPE ≤ %10, toplam sapma ≤ %5

## Hangi belgeyi kime vereceksin

```
Pilotla konuşuyorsan  → 04'ü OKU (kendin), kimseye verme
Yakıt verimliliği müd. → 02 mektup + 01 şablon
CFO / karar verici    → 03 kabul kriterleri
Veri gelecekse        → 01 şablon
```

`04` bir satış belgesi değil — **senin saha notun.** Pilotla konuşmadan
önce bir kez oku, 9. bölümdeki tek sayfalık özeti ezberle.

## Sıra

1. Mektubu müşteriye gönder (`02_...md`)
2. Müşteri şablonu doldurur (`01_...csv`)
3. `python -m src.ingestion.customer_fuel_ingestor --csv <dosya> --tenant <id>`
4. Kalibrasyon: `python -m src.optimization.model_calibrator`
5. Doğruluk raporu (`03_...md`'deki metriklere göre)

Üretim: 22.11.2026 18:04
