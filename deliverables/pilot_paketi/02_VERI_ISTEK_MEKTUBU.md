# Pilot Veri Talebi — [Havayolu]

**Kimden:** GreenWing Analytics
**Kime:** [Havayolu] — Yakıt Yönetimi / Uçuş Operasyonları
**Tarih:** 22.11.2026
**Konu:** 30 uçuşluk doğruluk pilotu için veri talebi

---

## 1 · Ne istiyoruz ve neden

GreenWing, uçuş bazında yakıt tüketimini **fizik modeliyle** hesaplayan
bir karar destek sistemidir (aerodinamik polar + motor TSFC + ISA
atmosferi). Bugüne kadar model **sentetik** uçuş profilleriyle
doğrulandı; gerçek uçuşla kıyaslanmadı.

Doğruluk iddiasında bulunabilmemiz için **30 uçuşun gerçek yakıt
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
- **30 uçuş**, son 3 ay içinden
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
