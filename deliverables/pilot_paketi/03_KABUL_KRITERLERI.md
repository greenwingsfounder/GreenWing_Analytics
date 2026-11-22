# Pilot Kabul Kriterleri

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
