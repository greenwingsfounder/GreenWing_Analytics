# config/__init__.py

"""
GreenWing Analytics — Configuration Package

Bu paket proje ayarlarını ve varsayımlarını içerir:
    settings.py          → Fizik sabitleri, sistem ayarları
    aircraft_database.yaml → Uçak parametreleri (11 tip)
    assumptions.py       → Operasyonel varsayımlar (override edilebilir)

Kullanım:
    from config.settings import GRAVITY, EI_CO2, ISA_T0
    from config.assumptions import Assumptions
"""
