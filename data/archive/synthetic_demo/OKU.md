# ⚠️ BU KLASÖRDEKİ VERİ GERÇEK DEĞİLDİR

**Eski adı:** `opensky_real/` — **yanıltıcıydı**, 2026-11-22'de
`docs/FULL_TECHNICAL_AUDIT.md` #79 bulgusuyla düzeltildi.

## Ne var burada?

15 uçuş izi, **tamamı bilgisayarda üretilmiş (sentetik)**.

Üretici: `scripts/06_seed_real_data.py`
Bu script'in kendi docstring'i zaten şöyle diyor:

> "Bu script GERÇEK radar/ADS-B verisi toplamaz. Matematiksel olarak
> SENTETİK (simüle) uçuş yolları ÜRETİR."

## Neden "gerçek" değil — kanıt

| Test | Sentetik (burada) | Gerçek ADSB olurdu |
|---|---|---|
| Zaman aralığı | **her örnek tam 30,0 s** (std = 0,0000) | 1–60 s, düzensiz |
| Hız profili | pürüzsüz eğri, sıçrama yok | gürültülü |
| Eksik nokta | yok | her uçuşta vardır |
| Maks hız | 446,9 m/s = 1.609 km/h | ~255 m/s (M0,85) |

Son satır ayrıca bir **kalite sorunudur**: yol üreticisi 900 km/h
yerine 1.600 km/h hıza çıkabiliyor. Sentetik veri olduğu için model
sonucu etkilemiyor ama gerçek veri geldiğinde bu düzeltilmeli.

## Gerçek veri nerede?

**YOK.** Şu anda depoda gerçek uçuş verisi bulunmuyor (0 kayıt).
Gerçek veri için:

```bash
python -m src.data_collection.opensky_collector   # OpenSky API
python scripts/07_live_flight_scrapper.py         # ADSB.lol canlı
```

## Bu klasör ne işe yarar?

1. Boru hattını uçtan uca test etmek (CSV → analiz → rapor → site)
2. Regresyon testi: kod değişince sonuçlar bozuluyor mu?
3. Kullanıcıya "sistem nasıl çalışır" göstermek

**Müşteriye gösterilmez.** Pilot veri paketi (`deliverables/`)
gerçek veri bekler.
