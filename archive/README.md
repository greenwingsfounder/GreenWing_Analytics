# Arşiv — çalışmayan / değiştirilmiş kod

Bu klasördeki dosyalar **canlı sistemin parçası değildir**. Silinmediler
çünkü geçmiş kaydı ve karşılaştırma değeri taşıyorlar.

## `web_v1/` — ilk web paneli (v1)

**Durum:** KULLANIM DIŞI (2026-11-22'den itibaren)

**Neden arşivlendi:** Depoda **iki paralel web uygulaması** vardı:

| | `web_v1/` (eski) | `webapp/` (yeni) |
|---|---|---|
| Satır | 525 | 1.738 |
| Sayfa | 1 panel + API | **9 sayfa** + API |
| Kimlik | oturum, **rol yok** | oturum **+ rol + kiracı** |
| Site | Jinja şablonu | inline HTML/CSS |
| Test | yok | 34 test |

Aynı `GREENWING_DASHBOARD_PASSWORD` değişkenini okuyup aynı port
şemasında çalışabildikleri için "hangi uygulama açık?" sorusu
belirsizdi. Bu, bir müşteriye teslim edilecek bir depoda kabul
edilemez çünkü:

1. Hata düzeltmesi yalnızca birine girer, diğeri sessizce eski kalır.
2. Güvenlik açığı iki yerde ayrı ayrı kapatılmalıdır.
3. Yeni geliştirici yanlış dosyayı düzenler.

**Taşınan tek özellik:** `/rapor.pdf` (teknik rapor indirme) →
`webapp/app.py` içinde `/rapor/teknik.pdf` ve `/rapor/elkitabi.pdf`
olarak yeniden yazıldı, kimlik doğrulaması korundu.

**Çalıştırmak isterseniz** (tavsiye edilmez):
```bash
cd archive/web_v1 && ./run.sh
```

**Geri dönüş:** `git mv archive/web_v1 web` — ancak `web` paket adı
Python'un `web` modülüyle çakışabilir; `webapp` adı bu yüzden seçildi.
