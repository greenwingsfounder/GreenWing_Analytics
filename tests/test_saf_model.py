# tests/test_saf_model.py

"""
GreenWing Analytics — Sürdürülebilir Havacılık Yakıtı (SAF) Modeli Testleri
══════════════════════════════════════════════════════════════════════════

Kapsamlı test süiti:
    1.  SAFModel oluşturma ve veritabanı yükleme doğrulaması
    2.  Blend LHV ve Yoğunluk interpolasyonu testleri
    3.  Aromatik bileşen sınır kontrolü (min %8 ASTM kısıtı)
    4.  SFC düzeltme katsayısı doğrulaması (ısıl değer artışı etkisi)
    5.  CORSIA / LCA (yaşam döngüsü) karbon emisyon azaltım hesabı
    6.  Ekonomik analiz (Green Premium vs Ofset Kazancı)
    7.  Bilinmeyen SAF tipleri için hata fırlatma testi
    8.  ASTM %50 karışım üst sınır koruması testi

Çalıştırma:
    python tests/test_saf_model.py
    python -m pytest tests/test_saf_model.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.saf_model import SAFModel


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: saf_model.py — SAF MODELİ TEST SÜİTİ")
    print("=" * 60)

    errors = []
    tests  = 0

    def check(name, actual, expected, tol=0.01):
        nonlocal tests
        tests += 1
        diff = abs(float(actual) - float(expected))
        if diff <= tol:
            print(f"  ✅ {name} = {actual:.4f}")
        else:
            errors.append(f"{name}: {actual:.4f} ≠ {expected:.4f} (Δ={diff:.4f})")
            print(f"  ❌ {name}: {actual:.4f} (beklenen {expected:.4f})")

    def check_true(name, condition):
        nonlocal tests
        tests += 1
        if condition:
            print(f"  ✅ {name}")
        else:
            errors.append(name)
            print(f"  ❌ {name}")

    def check_raises(name, func, exc):
        nonlocal tests
        tests += 1
        try:
            func()
            errors.append(f"{name}: {exc.__name__} beklendi")
            print(f"  ❌ {name}: hata vermedi")
        except exc:
            print(f"  ✅ {name} → {exc.__name__}")
        except Exception as e:
            errors.append(f"{name}: yanlış hata fırlatıldı {type(e).__name__}")
            print(f"  ❌ {name}: {type(e).__name__}")

    # ═══════════════════════════════════════════════════════
    # 1. MODEL OLUŞTURMA & VARSAYILAN KONTROLÜ
    # ═══════════════════════════════════════════════════════
    print("\n  [1] Model Oluşturma ve Varsayılan Değerler")
    
    # Sıfır karışım (Tamamen Jet A-1)
    saf_ref = SAFModel(blend_ratio=0.0, saf_type="HEFA")
    check("Blend LHV (0% blend)", saf_ref.get_blend_lhv(), 43.15, 0.001)
    check("Blend Density (0% blend)", saf_ref.get_blend_density(), 800.0, 0.01)
    check("Blend Aromatics (0% blend)", saf_ref.get_blend_aromatics(), 18.0, 0.01)
    check("SFC Correction Factor (0% blend)", saf_ref.sfc_correction_factor(), 1.0, 0.0001)
    check("LCA CO2 Reduction (0% blend)", saf_ref.get_lifecycle_co2_reduction_pct(), 0.0, 0.01)

    # ═══════════════════════════════════════════════════════
    # 2. ASTM KARIŞIM SINIRI KONTROLÜ
    # ═══════════════════════════════════════════════════════
    print("\n  [2] ASTM D7566 Karışım Sınır Koruması (%50)")
    
    # %70 karışım verilirse %50'ye tırpanlamalı
    saf_high = SAFModel(blend_ratio=0.70, saf_type="HEFA")
    check("Cap blend ratio at 0.50", saf_high.blend_ratio, 0.50, 0.001)

    # Negatif karışım verilirse 0.0'a tırpanlamalı
    saf_neg = SAFModel(blend_ratio=-0.10, saf_type="HEFA")
    check("Cap blend ratio at 0.00", saf_neg.blend_ratio, 0.0, 0.001)

    # ═══════════════════════════════════════════════════════
    # 3. KARIŞIM HESAPLARI (%30 HEFA)
    # ═══════════════════════════════════════════════════════
    print("\n  [3] %30 HEFA Karışım Hesapları")
    
    saf_30 = SAFModel(blend_ratio=0.30, saf_type="HEFA")
    
    # LHV: (0.7 * 43.15) + (0.3 * 44.10) = 30.205 + 13.23 = 43.435
    check("LHV (30% HEFA)", saf_30.get_blend_lhv(), 43.435, 0.01)
    
    # Density: (0.7 * 800) + (0.3 * 755) = 560 + 226.5 = 786.5
    check("Density (30% HEFA)", saf_30.get_blend_density(), 786.5, 0.1)
    
    # Aromatics: (0.7 * 18.0) + (0.3 * 0.0) = 12.6%
    check("Aromatics (30% HEFA)", saf_30.get_blend_aromatics(), 12.6, 0.01)
    check_true("Seal integrity constraint (aromatics >= 8.0%)", saf_30.get_blend_aromatics() >= 8.0)

    # SFC Correction Factor: 43.15 / 43.435 = 0.9934 (Yakıt tüketiminde %0.66 azalma)
    check("SFC factor (30% HEFA)", saf_30.sfc_correction_factor(), 43.15 / 43.435, 0.0001)

    # ═══════════════════════════════════════════════════════
    # 4. EMİSYON AZALTIMI & CORSIA UYUMLULUĞU
    # ═══════════════════════════════════════════════════════
    print("\n  [4] Emisyon ve CORSIA Yaşam Döngüsü (LCA) Analizi")
    
    # %30 HEFA LCA CO2 reduction pct:
    # Jet A-1 LCA: 89 g/MJ
    # HEFA LCA: 16 g/MJ
    # Blend LCA: 0.7 * 89 + 0.3 * 16 = 62.3 + 4.8 = 67.1 g/MJ
    # Azalma: (89 - 67.1) / 89 = 24.606%
    check("LCA reduction (30% HEFA)", saf_30.get_lifecycle_co2_reduction_pct(), 24.6067, 0.01)

    # PtL (e-Fuel) %50 karışım
    saf_ptl_50 = SAFModel(blend_ratio=0.50, saf_type="PTL")
    # PTL LCA: 4.5 g/MJ
    # Blend LCA: 0.5 * 89 + 0.5 * 4.5 = 44.5 + 2.25 = 46.75
    # Azalma: (89 - 46.75) / 89 = 47.47%
    check("LCA reduction (50% PtL)", saf_ptl_50.get_lifecycle_co2_reduction_pct(), 47.4719, 0.01)

    # ═══════════════════════════════════════════════════════
    # 5. EKONOMİK ANALİZ (GREEN PREMIUM VS OFFSET)
    # ═══════════════════════════════════════════════════════
    print("\n  [5] Ekonomik Trade-Off Analizi")
    
    # 10,000 kg yakıt yakan bir uçuş için analiz
    economic_analysis = saf_30.analyze_economic_tradeoff(
        flight_fuel_consumption_kg=10000.0,
        carbon_credit_price_usd_tonne=30.0
    )
    
    check_true("SXS flight analysis output contains expected keys", 
               all(k in economic_analysis for k in ['base_fuel_cost_usd', 'saf_fuel_cost_usd', 
                                                   'green_premium_usd', 'co2_saved_lifecycle_tonnes', 
                                                   'offset_saving_usd', 'net_financial_impact_usd']))
    
    print(f"     Jet A-1 Yakıt Maliyeti : ${economic_analysis['base_fuel_cost_usd']:.0f}")
    print(f"     SAF Karışım Maliyeti   : ${economic_analysis['saf_fuel_cost_usd']:.0f}")
    print(f"     Net Green Premium      : ${economic_analysis['green_premium_usd']:.0f}")
    print(f"     LCA CO2 Tasarrufu      : {economic_analysis['co2_saved_lifecycle_tonnes']:.2f} ton")
    print(f"     Karbon Ofset Tasarrufu : ${economic_analysis['offset_saving_usd']:.0f}")
    print(f"     Net Finansal Etki      : ${economic_analysis['net_financial_impact_usd']:.0f}")

    # ═══════════════════════════════════════════════════════
    # 6. GEÇERSİZ PARAMETRELER VE HATA FIRLATMA
    # ═══════════════════════════════════════════════════════
    print("\n  [6] Geçersiz Parametre Kontrolleri")
    
    check_raises(
        "SAFModel('GEÇERSİZ_TİP')",
        lambda: SAFModel(blend_ratio=0.10, saf_type="GEÇERSİZ"),
        ValueError
    )

    # ═══════════════════════════════════════════════════════
    # SONUÇ
    # ═══════════════════════════════════════════════════════
    print(f"\n  {'─' * 50}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print(f"\n  ❌ BAŞARISIZ SAF TESTLERİ:")
        for i, e in enumerate(errors, 1):
            print(f"     {i}. {e}")
        return False
    print("  ✅ TÜM SAF TESTLERİ BAŞARILI\n")
    return True


if __name__ == "__main__":
    run_tests()
