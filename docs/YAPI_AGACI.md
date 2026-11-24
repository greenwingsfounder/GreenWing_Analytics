# GreenWing Analytics — Proje Yapı Ağacı

> Otomatik üretildi: `python tools/build_tree.py`  
> **166 dosya** · **94 Python modülü** · **51.430 satır kod**

**İşaretler:** ★ = kritik dosya · ⚠️ = dikkat · (0 byte) = silinecek

```
├── config/   (18 dosya)
│   ├── __init__.py  — Configuration Package
│   ├── aircraft_database.yaml  — ★ 14 uçak tipi: ağırlık, kanat, polar
│   ├── aircraft_polar_sources.yaml  — Polar değerlerin kaynak izi
│   ├── assumptions.py  — İş varsayımları (fiyat, gerçekleşme)
│   ├── credentials.py  — Sır okuma (env önceliği, depoda sır YOK)
│   ├── demo_scenarios.yaml  — Demo senaryoları (ticari kullanılmaz)
│   ├── ingestion_config.py  — Müşteri verisi kabul kuralları
│   ├── phase_thrust_table.yaml  — Faz bazlı itki tablosu
│   ├── saf_database.yaml  — SAF türleri ve özellikleri
│   └── settings.py  — Sistem ayarları (units.py'den okur)
├── data/   (62 dosya)
│   ├── calibrations/   (1 dosya)
│   │   └── OKU.md
│   ├── customer_fuel/   (1 dosya)
│   │   └── OKU.md
│   ├── mocks/   (1 dosya)
│   │   └── OKU.md
│   ├── openap/   (14 dosya)
│   │   ├── aircraft/
│   │   │   ├── a20n.yml
│   │   │   ├── a21n.yml
│   │   │   ├── a320.yml
│   │   │   ├── a321.yml
│   │   │   ├── a359.yml
│   │   │   ├── a388.yml
│   │   │   ├── b38m.yml
│   │   │   ├── b738.yml
│   │   │   ├── b77w.yml
│   │   │   ├── b788.yml
│   │   │   └── b789.yml
│   │   ├── engine/
│   │   │   └── engines.csv
│   │   ├── fuel/
│   │   │   └── fuel_models.csv
│   │   └── OKU.md
│   ├── raw/   (14 dosya)
│   │   └── opensky/
│   │       ├── ARR_PGT_PGT120_20261122_121625.csv
│   │       ├── ARR_PGT_PGT501_20261122_121559.csv
│   │       ├── ARR_PGT_PGT802_20261122_121651.csv
│   │       ├── ARR_SXS_SXS1409_20261122_121559.csv
│   │       ├── ARR_SXS_SXS1409_LTAI_EDDF.csv
│   │       ├── ARR_SXS_SXS5720_20261122_121612.csv
│   │       ├── ARR_SXS_SXS6381_20261122_121559.csv
│   │       ├── ARR_THY_THY1011_20261122_121638.csv
│   │       ├── ARR_THY_THY1587_20261122_121559.csv
│   │       ├── ARR_THY_THY1629_20261122_121612.csv
│   │       ├── ARR_THY_THY1865_20261122_121651.csv
│   │       ├── ARR_THY_THY1951_20261122_121625.csv
│   │       ├── ARR_THY_THY501_20261122_121559.csv
│   │       └── ARR_THY_THY764_20261122_121612.csv
│   └── openap_reference.json [6 KB]
├── deliverables/   (4 dosya)
│   └── pilot_paketi/   (4 dosya)
│       ├── 01_YAKIT_VERISI_SABLONU.csv  — ★ Müşteriden istenecek CSV
│       ├── 02_VERI_ISTEK_MEKTUBU.md  — ★ Havayoluna gönderilecek mektup
│       ├── 03_KABUL_KRITERLERI.md  — ★ Başarı ölçütleri (MAPE ≤ %10)
│       └── OKU.md  — ★ Pilot paketi: nasıl kullanılır
├── docs/   (8 dosya)
│   ├── COMMERCIAL_READINESS.md  — Ticarileşme hazırlık değerlendirmesi
│   ├── FULL_TECHNICAL_AUDIT.md  — Tam teknik denetim bulguları
│   ├── KOD_ATLASI.md  — ★ Her modül + her sayının kaynağı
│   ├── model_provenance.json [14 KB]  — Aynı, makine okunur
│   ├── MODEL_PROVENANCE.md  — Model kaynak envanteri
│   ├── NASIL_KULLANIRIM.md
│   ├── SECURITY_AUDIT.md  — Güvenlik denetimi
│   └── YAPI_AGACI.md  — ★ Bu ağaç (bu dosya)
├── reports/   (16 dosya)
│   ├── audit/   (1 dosya)
│   │   └── full_audit.json [1 KB]
│   ├── case_studies/   (8 dosya)
│   │   ├── case_study_20261122.json [33 KB]
│   │   ├── case_study_20261124.json [33 KB]
│   │   ├── corsia_report_20261122.json [2 KB]
│   │   ├── corsia_report_20261124.json [2 KB]
│   │   ├── data_quality_20261122.json [4 KB]
│   │   ├── data_quality_20261124.json [4 KB]
│   │   ├── fleet_digital_twins_20261122.json [0 KB]
│   │   └── fleet_digital_twins_20261124.json [0 KB]
│   ├── optimizations/   (1 dosya)
│   │   └── batch_results.json [25 KB]
│   ├── GreenWing_CaseStudy_20261122.html
│   ├── GreenWing_CaseStudy_20261124.html
│   ├── GreenWing_Fleet_Report_20261122.html
│   ├── GreenWing_Proje_El_Kitabi.pdf [116 KB]
│   ├── GreenWing_Teknik_Rapor.pdf [138 KB]
│   └── QA_rapor3.html
├── scripts/   (20 dosya)
│   ├── 01_collect_data.py  — ① Veri topla (OpenSky/ADSB.lol)
│   ├── 02_analyze_and_optimize.py  — ② ★ Ana boru hattı: analiz + optimizasyon
│   ├── 03_generate_outputs.py  — ③ Rapor üret (HTML/JSON)
│   ├── 04_generate_professional_demo.py  — ④ Demo verisi üret (sentetik)
│   ├── 05_saf_scenario_analysis.py  — ⑤ SAF senaryo analizi
│   ├── 06_seed_real_data.py  — ⑥ Sentetik uçuş yolu üret (demo)
│   ├── 07_live_flight_scrapper.py  — ⑦ Canlı radar (ADSB.lol)
│   ├── 08_automated_fleet_tracker.py  — ⑧ Otomatik filo takibi
│   ├── 09_clean_and_backup.py  — ⑨ Temizlik + yedekleme
│   └── 10_pre_real_ingestion_demo.py  — ⑩ Müşteri verisi kabul demo
├── src/   (87 dosya)
│   ├── analysis/   (16 dosya)
│   │   ├── __init__.py  — Analysis Package
│   │   ├── benchmark.py  — Bağımsız kaynakla karşılaştırma
│   │   ├── fleet_analyzer.py  — Filo geneli: yakıt, tasarruf, CO₂
│   │   ├── flight_analyzer.py  — Tek uçuş analizi
│   │   ├── fuel_thermal_model.py  — Termal model yardımcısı
│   │   ├── phase_segmentation.py  — Uçuşu fazlara ayır
│   │   ├── sensitivity.py  — Hassasiyet: hangi parametre ne kadar etkiler
│   │   └── uncertainty.py  — ★ Belirsizlik bütçesi / güven aralığı
│   ├── data_collection/   (6 dosya)
│   │   ├── __init__.py  — Data Collection Package
│   │   ├── airport_database.py  — 60+ havalimanı + eşleştirme
│   │   └── opensky_collector.py  — OpenSky OAuth2 + tarihsel veri
│   ├── ingestion/   (8 dosya)
│   │   ├── __init__.py
│   │   ├── calibration_pipeline.py  — Uçtan uca kalibrasyon akışı
│   │   ├── customer_fuel_ingestor.py  — Müşteri yakıt CSV → normalize
│   │   └── flight_matcher.py  — Yakıt kaydı ↔ radar izi eşleştirme
│   ├── models/   (18 dosya)
│   │   ├── __init__.py  — Physics Models Package
│   │   ├── aircraft_performance.py  — Kaldırma, sürükleme, L/D, buffet
│   │   ├── atmosphere.py  — ISA standart atmosfer: T/P/ρ/ses hızı
│   │   ├── blockchain_sealer.py  — Sonuç değiştirilemezlik mührü (SHA-256)
│   │   ├── emission_model.py  — CO₂/H₂O/SO₂/NOₓ + CORSIA raporu
│   │   ├── fuel_model.py  — ★ Yakıt akışı — EDB veya tahmin yolu
│   │   ├── saf_model.py  — SAF karışımı ve CO₂ azaltımı
│   │   ├── wind_gfs.py  — GFS rüzgârı (3 kademeli zincir)
│   │   └── wind_model.py  — Rüzgâr profili (ölçüm DEĞİL, varsayım)
│   ├── optimization/   (12 dosya)
│   │   ├── __init__.py  — Optimization Package
│   │   ├── altitude_optimizer.py  — Optimum irtifa + step climb
│   │   ├── cost_index_optimizer.py  — CI → hız optimizasyonu
│   │   ├── model_calibrator.py  — Modeli müşteri verisine göre ayarla
│   │   ├── tail_performance_calibrator.py  — Kuyruk bazlı dijital ikiz
│   │   └── tankering_optimizer.py  — Yakıt tankering kararı
│   ├── reporting/   (7 dosya)
│   │   ├── templates/
│   │   │   ├── corsia_report_template.html
│   │   │   ├── fleet_report_template.html
│   │   ├── __init__.py  — Reporting Package
│   │   └── report_generator.py  — HTML/JSON rapor + CORSIA belgesi
│   ├── security/   (4 dosya)
│   │   ├── __init__.py  — Güvenlik yardımcıları — dashboard kimlik doğrulama.
│   │   └── auth.py  — ★ Oturum + rol + kiracı
│   ├── validation/   (8 dosya)
│   │   ├── __init__.py  — Validation Package
│   │   ├── business_validator.py  — İş mantığı tutarlı mı
│   │   ├── data_validator.py  — Girdi verisi sağlıklı mı
│   │   └── physics_validator.py  — ★ Fizik yasalarına uyuyor mu
│   ├── __init__.py  — Source Package
│   ├── logging_config.py  — Hesaplama izleme / log sistemi
│   ├── units.py  — ★ Birim dönüşümü + fizik sabitleri — TEK KAYNAK
│   └── utils.py  — Ortak yardımcılar (haversine, biçimlendirme)
├── tests/   (68 dosya)
│   ├── __init__.py  — Test Package
│   ├── test_aircraft_data_provenance.py  — ★ Uçak verisi kaynak doğrulaması
│   ├── test_atmosphere.py  — ISA atmosfer (ICAO elle hesap)
│   ├── test_auth.py  — Kimlik: parola, oturum, rol, kiracı
│   ├── test_emission.py  — Emisyon + CORSIA
│   ├── test_fleet_analyzer.py  — Filo analizi
│   ├── test_fuel_model.py  — Yakıt modeli fizik
│   ├── test_fuel_model_estimate_flag.py  — Tahmin bayrağı
│   ├── test_logging.py  — Log sistemi
│   ├── test_mach_physics.py  — Mach fiziği
│   ├── test_optimization.py  — Optimizasyon
│   ├── test_pdf_glyphs.py  — PDF Türkçe karakter
│   ├── test_performance.py  — Aerodinamik performans
│   ├── test_saf_model.py  — SAF modeli
│   ├── test_security.py  — Güvenlik: sırlar, XSS, enjeksiyon
│   ├── test_sensitivity.py  — Hassasiyet
│   ├── test_tail_calibrator.py  — Kuyruk kalibrasyonu
│   ├── test_thermal_model.py  — Termal model
│   ├── test_uncertainty.py  — Belirsizlik
│   ├── test_units.py  — Birim dönüşümleri
│   ├── test_utils.py  — Yardımcılar
│   ├── test_validation.py  — Doğrulayıcılar
│   ├── test_webapp.py  — Site: 10 sayfa, API, PDF, rol
│   └── test_wind_provider.py  — Rüzgâr zinciri
├── tools/   (22 dosya)
│   ├── build_handbook.py  — PDF: proje el kitabı
│   ├── build_pilot_data_package.py  — Pilot veri paketi üretir
│   ├── build_provenance.py  — Model kaynak envanteri
│   ├── build_technical_report.py  — PDF: teknik rapor
│   ├── build_tree.py  — Bu ağacı üreten script
│   ├── calibrate_aircraft_database.py  — Polar katsayı kalibrasyonu
│   ├── calibrate_phase_thrust.py  — Faz itkisi kalibrasyonu
│   ├── full_audit.py  — ★ 7 katmanlı tam denetim (228 kontrol)
│   ├── openap_reference.py  — OpenAP referans karşılaştırması
│   ├── sync_fuel_coef.py  — Yakıt katsayısı senkron
│   └── sync_openap_params.py  — OpenAP → YAML senkron
├── webapp/   (2 dosya)
│   └── app.py  — ★ 10 sayfalı site + API + PDF indirme
├── README.md  — Giriş: ne bu, nasıl çalıştırılır
├── requirements.txt  — Python bağımlılıkları
└── setup.py  — Paket kurulumu (pip install -e .)
```
