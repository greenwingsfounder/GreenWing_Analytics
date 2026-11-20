# src/__init__.py

"""
GreenWing Analytics — Source Package

Ana kaynak kod paketi. Tüm modüller buradan erişilir.

Alt paketler:
    models/          → Fizik motorları (atmosfer, performans, yakıt, emisyon)
    data_collection/ → Veri toplama (OpenSky API, havalimanı DB)
    analysis/        → Analiz motorları (uçuş, filo, faz, benchmark)
    optimization/    → Optimizasyon (irtifa, CI, tankering, kalibrasyon)
    validation/      → 3 katmanlı doğrulama (veri, fizik, iş mantığı)
    reporting/       → Rapor üretimi (HTML/PDF)

Yardımcı modüller:
    units.py          → Birim dönüşüm merkezi
    logging_config.py → Hesaplama izleme ve kayıt
"""
