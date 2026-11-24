# data/openap/ — OpenAPI referans verisi

**Kaynak:** [OpenAP](https://github.com/junzis/openap) — MIT lisansı,
TU Delft / Junzi Sun. Açık kaynak uçak performans veritabanı.

**Ne var:**
- `aircraft/*.yml` — 11 tip: MTOW, OEW, kanat alanı, açıklık, VMO/MMO,
  motor, sürükleme poları (CD0, K)
- `engine/engines.csv` — motor itki/yakıt tablosu
- `fuel/fuel_models.csv` — yakıt akışı modelleri

**Neden burada:** `config/aircraft_database.yaml` içindeki değerlerin
**kaynak izi**. Bir sayının OpenAP'tan mı, Boeing ACAP'tan mı,
ICAO EDB'den mi geldiği bu dosyalarla doğrulanabilir.

**Doğrulama:**
```bash
python tools/openap_reference.py      # referans karşılaştırma
python tests/test_aircraft_data_provenance.py
```

⚠️ OpenAP değerleri **kendisi de** bir modeldir (uçuş verisinden fit
edilmiş). Birincil kaynak değil, ikincil doğrulama kaynağıdır.
Polar için asıl kaynak: ICAO EDB (motor sertifikasyon verisi).
