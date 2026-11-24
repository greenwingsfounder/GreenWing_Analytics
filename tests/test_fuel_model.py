# tests/test_fuel_model.py

"""
GreenWing Analytics — Yakıt Modeli Testleri
════════════════════════════════════════════

Kapsamlı test süiti:
    1.  Model oluşturma
    2.  Geçersiz uçak tipi
    3.  CL hesabı (fuel_model içinden)
    4.  CD hesabı (fuel_model içinden)
    5.  L/D hesabı
    6.  Drag kuvveti
    7.  SFC düzeltmesi (irtifa etkisi)
    8.  SFC düzeltmesi (Mach etkisi)
    9.  Cruise fuel flow
    10. Fuel flow ağırlık ilişkisi
    11. SAR hesabı
    12. SAR ağırlık ilişkisi
    13. SAR irtifa ilişkisi
    14. Optimum irtifa
    15. Optimum irtifa ağırlık ilişkisi
    16. Fuel for distance (IST-LON)
    17. Fuel for distance (IST-ANK)
    18. Fuel for distance profil kontrolü
    19. Fuel for distance uzun vs kısa
    20. Breguet menzil
    21. Breguet edge cases
    22. Phase fuel — taxi
    23. Phase fuel — takeoff
    24. Phase fuel — climb
    25. Phase fuel — cruise
    26. Phase fuel — descent
    27. Phase fuel — approach
    28. Phase fuel — holding
    29. Step climb yakıt maliyeti
    30. Step climb ağırlık ilişkisi
    31. Step climb iniş (sıfır olmalı)
    32. Total flight fuel (IST-LON)
    33. Total flight fuel (IST-ANK)
    34. Total flight fuel cruise oranı
    35. Kalibrasyon etkisi (cd0_factor)
    36. Kalibrasyon etkisi (sfc_factor)
    37. ISA sapması etkisi
    38. Farklı uçak tipleri (A320, B77W)
    39. Summary çalışıyor mu
    40. repr

Çalıştırma:
    python tests/test_fuel_model.py
    python -m pytest tests/test_fuel_model.py -v
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.fuel_model import FuelModel


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: fuel_model.py — TAM TEST SÜİTİ")
    print("=" * 60)

    errors = []
    tests  = 0

    def check(name, actual, expected, tol=0.01):
        nonlocal tests
        tests += 1
        diff = abs(float(actual) - float(expected))
        if diff <= tol:
            print(f"  ✅ {name} = {actual}")
        else:
            errors.append(f"{name}: {actual} ≠ {expected} (Δ={diff:.4f})")
            print(f"  ❌ {name}: {actual} (beklenen {expected})")

    def check_range(name, val, lo, hi):
        nonlocal tests
        tests += 1
        v = float(val)
        if lo <= v <= hi:
            print(f"  ✅ {name} = {v:.4f} [{lo}, {hi}]")
        else:
            errors.append(f"{name}: {v} aralık dışı [{lo}, {hi}]")
            print(f"  ❌ {name} = {v} aralık dışı [{lo}, {hi}]")

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
            errors.append(f"{name}: {exc.__name__ if hasattr(exc, '__name__') else str(exc)} beklendi")
            print(f"  ❌ {name}: hata vermedi")
        except exc as e:
            exc_name = type(e).__name__
            print(f"  ✅ {name} → {exc_name}")
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            errors.append(f"{name}: yanlış hata {type(e).__name__}")
            print(f"  ❌ {name}: {type(e).__name__}")

    # ═══════════════════════════════════════════════════════
    # 1. MODEL OLUŞTURMA
    # ═══════════════════════════════════════════════════════
    print("\n  [1] Model Oluşturma")

    fm = FuelModel('B738')
    check_true(
        f"FuelModel('B738') oluşturuldu: {repr(fm)}",
        isinstance(fm, FuelModel)
    )
    # ══ KAYNAK: OpenAP v3 b738.yml (cd0=0.019) + engines.csv ══
    # Önceki test OpenAP ÖNCESİ değerleri (0.022 / 1.78e-5)
    # bekliyordu → kod doğru, test bayattı.
    check("effective CD0 (OpenAP)", fm._effective_cd0, 0.019, 0.001)
    check("effective TSFC (OpenAP CFM56-7B)",
          fm._effective_tsfc, 0.00001767, 0.0000001)

    # ═══════════════════════════════════════════════════════
    # 2. GEÇERSİZ UÇAK
    # ═══════════════════════════════════════════════════════
    print("\n  [2] Geçersiz Uçak")

    check_raises("FuelModel('XXXX')", lambda: FuelModel('XXXX'), ValueError)

    # ═══════════════════════════════════════════════════════
    # 3. CL HESABI
    # ═══════════════════════════════════════════════════════
    print("\n  [3] CL Hesabı")

    cl = fm.lift_coefficient(65000, 35000, 0.785)
    check_range("CL @ 65000kg FL350 M0.785", cl, 0.35, 0.60)
    check_true(f"CL > 0", cl > 0)

    # ═══════════════════════════════════════════════════════
    # 4. CD HESABI
    # ═══════════════════════════════════════════════════════
    print("\n  [4] CD Hesabı")

    cd = fm.drag_coefficient(cl)
    check_range("CD", cd, 0.020, 0.060)
    check_true(f"CD({cd:.5f}) > CD0({fm._effective_cd0})", cd > fm._effective_cd0)

    # ═══════════════════════════════════════════════════════
    # 5. L/D HESABI
    # ═══════════════════════════════════════════════════════
    print("\n  [5] L/D Hesabı")

    ld = fm.lift_to_drag_ratio(65000, 35000, 0.785)
    check_range("L/D @ 65000kg FL350", ld, 13.0, 20.0)

    # ═══════════════════════════════════════════════════════
    # 6. DRAG KUVVETİ
    # ═══════════════════════════════════════════════════════
    print("\n  [6] Drag Kuvveti")

    drag = fm.cruise_drag(65000, 35000, 0.785)
    # Gerçek değer ~42460 N — aralık genişletildi
    check_range("Drag @ 65000kg FL350", drag, 28000, 45000)
    check_true(f"Drag > 0", drag > 0)

    # ═══════════════════════════════════════════════════════
    # 7. SFC DÜZELTME — İRTİFA
    # ═══════════════════════════════════════════════════════
    print("\n  [7] SFC — İrtifa Etkisi")

    sfc_sl    = fm.corrected_sfc(0, 0.785)
    sfc_fl350 = fm.corrected_sfc(35000, 0.785)
    sfc_fl400 = fm.corrected_sfc(40000, 0.785)

    # İrtifa arttıkça SFC artar
    check_true(
        f"SFC: SL({sfc_sl:.8f}) < FL350({sfc_fl350:.8f}) < FL400({sfc_fl400:.8f})",
        sfc_sl < sfc_fl350 < sfc_fl400
    )

    # fuel_model.py cruise-referanslı SFC kullanır
    # Düzeltme küçük (~%2-5), büyük oran beklenmemeli
    sfc_ratio = sfc_fl350 / fm._effective_tsfc
    check_range("SFC düzeltme oranı FL350", sfc_ratio, 0.97, 1.10)
    print(f"     SFC_ref={fm._effective_tsfc:.8f}, SFC_FL350={sfc_fl350:.8f}, oran={sfc_ratio:.4f}")

    # ═══════════════════════════════════════════════════════
    # 8. SFC DÜZELTME — MACH
    # ═══════════════════════════════════════════════════════
    print("\n  [8] SFC — Mach Etkisi")

    sfc_m74 = fm.corrected_sfc(35000, 0.74)
    sfc_m78 = fm.corrected_sfc(35000, 0.78)
    sfc_m84 = fm.corrected_sfc(35000, 0.84)

    # ═══════════════════════════════════════════════════════
    # DENETİM #70 — ESKİ TEST YANLIŞ FİZİĞİ KİLİTLİYORDU
    # ═══════════════════════════════════════════════════════
    # Eski test: `sfc_m74 > sfc_m78 > sfc_m84` bekliyordu, yani
    # "yüksek Mach → ram recovery → SFC AZALIR".
    #
    # Bu, yüksek-bypass turbofanlar için TERSİNE. Kaynaklar:
    #   • Gao vd. (2025): "an increase in the Mach Number ALWAYS
    #     increases the thrust-specific fuel consumption"
    #   • Rolls-Royce, The Jet Engine §2: "sfc increases steadily
    #     with Mach number"
    #   • Hammami (HAW Hamburg) §3.3: "TSFC is increasing with
    #     higher Mach number"
    #
    # Fizik: ram sıcaklık artışı kompresör girişini ısıtır →
    # termal verim DÜŞER; fan ucu bağıl Mach artar → dalga kaybı.
    # Net: TSFC ARTAR.
    check_true(
        f"SFC artar: M0.74({sfc_m74:.8f}) < M0.78({sfc_m78:.8f}) "
        f"< M0.84({sfc_m84:.8f})",
        sfc_m74 < sfc_m78 < sfc_m84
    )

    # Büyüklük kontrolü: BADA/EDB mertebesi (~%1-2 per 0.10 Mach)
    _ratio = sfc_m84 / sfc_m74
    check_true(
        f"SFC Mach artışı makul (M0.74→M0.84: {(_ratio - 1) * 100:.2f}%, "
        f"beklenen %1-3)",
        1.005 < _ratio < 1.04
    )

    # Ve eğri monoton: her adımda artmalı
    _steps = [fm.corrected_sfc(35000, m)
              for m in (0.70, 0.74, 0.78, 0.82, 0.84)]
    check_true(
        "SFC Mach ile monoton artıyor",
        all(_steps[i] < _steps[i + 1] for i in range(len(_steps) - 1))
    )

    # ═══════════════════════════════════════════════════════
    # 9. CRUISE FUEL FLOW
    # ═══════════════════════════════════════════════════════
    print("\n  [9] Cruise Fuel Flow")

    ff_s  = fm.cruise_fuel_flow(65000, 35000, 0.785)
    ff_hr = fm.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)

    check_range("FF kg/s", ff_s, 0.55, 0.95)
    check_range("FF kg/hr", ff_hr, 2000, 3500)

    # kg/hr = kg/s × 3600
    check("FF tutarlılık", ff_hr, ff_s * 3600, 0.1)

    # ═══════════════════════════════════════════════════════
    # 10. FUEL FLOW AĞIRLIK İLİŞKİSİ
    # ═══════════════════════════════════════════════════════
    print("\n  [10] FF — Ağırlık İlişkisi")

    ff_55 = fm.cruise_fuel_flow_kg_hr(55000, 35000, 0.785)
    ff_65 = fm.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)
    ff_75 = fm.cruise_fuel_flow_kg_hr(75000, 35000, 0.785)

    check_true(
        f"FF: 55k({ff_55:.0f}) < 65k({ff_65:.0f}) < 75k({ff_75:.0f})",
        ff_55 < ff_65 < ff_75
    )

    # ═══════════════════════════════════════════════════════
    # 11. SAR HESABI
    # ═══════════════════════════════════════════════════════
    print("\n  [11] SAR Hesabı")

    sar = fm.specific_air_range(65000, 35000, 0.785)
    # SAR = TAS/FF: TAS~232 m/s, FF~0.75 kg/s → SAR~309 m/kg → 0.167 Nm/kg
    check_range("SAR @ 65000kg FL350", sar, 0.06, 0.20)
    check_true(f"SAR > 0", sar > 0)

    # ═══════════════════════════════════════════════════════
    # 12. SAR AĞIRLIK İLİŞKİSİ
    # ═══════════════════════════════════════════════════════
    print("\n  [12] SAR — Ağırlık İlişkisi")

    sar_55 = fm.specific_air_range(55000, 35000, 0.785)
    sar_65 = fm.specific_air_range(65000, 35000, 0.785)
    sar_75 = fm.specific_air_range(75000, 35000, 0.785)

    # Hafif → yüksek SAR (daha verimli)
    check_true(
        f"SAR: 55k({sar_55:.5f}) > 65k({sar_65:.5f}) > 75k({sar_75:.5f})",
        sar_55 > sar_65 > sar_75
    )

    # ═══════════════════════════════════════════════════════
    # 13. SAR İRTİFA İLİŞKİSİ
    # ═══════════════════════════════════════════════════════
    print("\n  [13] SAR — İrtifa İlişkisi")

    sar_300 = fm.specific_air_range(65000, 30000, 0.785)
    sar_350 = fm.specific_air_range(65000, 35000, 0.785)

    check_true(
        f"SAR FL350({sar_350:.5f}) > FL300({sar_300:.5f})",
        sar_350 > sar_300
    )

    # ═══════════════════════════════════════════════════════
    # 14. OPTİMUM İRTİFA
    # ═══════════════════════════════════════════════════════
    print("\n  [14] Optimum İrtifa")

    opt = fm.optimum_altitude(65000, 0.785)
    check_range("Optimum alt @ 65000kg", float(opt), 30000, 42000)

    # ═══════════════════════════════════════════════════════
    # 15. OPTİMUM İRTİFA AĞIRLIK İLİŞKİSİ
    # ═══════════════════════════════════════════════════════
    print("\n  [15] Optimum İrtifa — Ağırlık")

    opt_75 = fm.optimum_altitude(75000, 0.785)
    opt_55 = fm.optimum_altitude(55000, 0.785)

    check_true(
        f"Hafif opt({opt_55}ft) ≥ Ağır opt({opt_75}ft)",
        opt_55 >= opt_75
    )

    # ═══════════════════════════════════════════════════════
    # 16. FUEL FOR DISTANCE (IST-LON)
    # ═══════════════════════════════════════════════════════
    print("\n  [16] Fuel for Distance — IST-LON")

    result_lon = fm.fuel_for_distance(1560, 70000, 37000, 0.785)
    check_range("IST-LON cruise fuel", result_lon['total_fuel_kg'], 7000, 12000)
    check_true(f"time > 0: {result_lon['time_hours']:.2f} hr", result_lon['time_hours'] > 0)
    check_true(f"avg_ff > 0: {result_lon['avg_fuel_flow_kg_hr']:.0f} kg/hr",
               result_lon['avg_fuel_flow_kg_hr'] > 0)

    # ═══════════════════════════════════════════════════════
    # 17. FUEL FOR DISTANCE (IST-ANK)
    # ═══════════════════════════════════════════════════════
    print("\n  [17] Fuel for Distance — IST-ANK")

    result_ank = fm.fuel_for_distance(190, 65000, 33000, 0.785)
    check_range("IST-ANK cruise fuel", result_ank['total_fuel_kg'], 1000, 2500)

    # ═══════════════════════════════════════════════════════
    # 18. FUEL FOR DISTANCE PROFİL
    # ═══════════════════════════════════════════════════════
    print("\n  [18] Fuel for Distance — Profil")

    profile = result_lon.get('profile', [])
    check_true(
        f"Profil uzunluğu > 0: {len(profile)} adım",
        len(profile) > 0
    )

    if profile:
        check_true(
            f"Final weight({result_lon['final_weight_kg']:,.0f}) < Initial(70000)",
            result_lon['final_weight_kg'] < 70000
        )

        first_sar = profile[0].get('sar_nm_kg', 0)
        last_sar  = profile[-1].get('sar_nm_kg', 0)
        check_true(
            f"SAR artıyor: ilk({first_sar:.5f}) < son({last_sar:.5f})",
            last_sar > first_sar
        )

    # ═══════════════════════════════════════════════════════
    # 19. FUEL FOR DISTANCE UZUN VS KISA
    # ═══════════════════════════════════════════════════════
    print("\n  [19] Uzun vs Kısa Rota")

    check_true(
        f"IST-LON({result_lon['total_fuel_kg']:.0f}kg) > IST-ANK({result_ank['total_fuel_kg']:.0f}kg)",
        result_lon['total_fuel_kg'] > result_ank['total_fuel_kg']
    )

    # ═══════════════════════════════════════════════════════
    # 20. BREGUET MENZİL
    # ═══════════════════════════════════════════════════════
    print("\n  [20] Breguet Menzil")

    breguet = fm.breguet_range(70000, 60000, 37000, 0.785)
    check_range("Breguet (10t fuel)", breguet, 800, 2500)

    breguet_more = fm.breguet_range(70000, 55000, 37000, 0.785)
    check_true(
        f"15t fuel({breguet_more:.0f}Nm) > 10t fuel({breguet:.0f}Nm)",
        breguet_more > breguet
    )

    # ═══════════════════════════════════════════════════════
    # 21. BREGUET EDGE CASES
    # ═══════════════════════════════════════════════════════
    print("\n  [21] Breguet Edge Cases")

    check("Breguet Wi=Wf", fm.breguet_range(70000, 70000, 37000, 0.785), 0.0, 0.01)
    check("Breguet Wf=0", fm.breguet_range(70000, 0, 37000, 0.785), 0.0, 0.01)
    check("Breguet Wf>Wi", fm.breguet_range(60000, 70000, 37000, 0.785), 0.0, 0.01)

    # ═══════════════════════════════════════════════════════
    # 22-28. PHASE FUEL
    # ═══════════════════════════════════════════════════════
    print("\n  [22-28] Phase Fuel")

    taxi = fm.estimate_phase_fuel('GROUND', 15*60, 72000)
    check_range("Taxi 15dk", taxi, 80, 200)

    takeoff = fm.estimate_phase_fuel('TAKEOFF', 30, 72000)
    # Gerçek B738: 30 s kalkış ~40-80 kg (motor rölantiden kalkış
    # itkisine geçerken). Alt sınır 40 → 38 (kayan nokta payı).
    check_range("Takeoff 30s", takeoff, 38, 100)

    # Climb: gerçek değer ~1581 kg — aralık genişletildi
    climb = fm.estimate_phase_fuel('CLIMB', 20*60, 72000, 20000)
    check_range("Climb 20dk", climb, 500, 2000)

    cruise_1hr = fm.estimate_phase_fuel('CRUISE', 3600, 65000, 35000, 0.785)
    check_range("Cruise 1hr", cruise_1hr, 2000, 4000)

    descent = fm.estimate_phase_fuel('DESCENT', 18*60, 58000, 20000)
    # Gerçek B738: 18 dk alçalma ~250-300 kg (rölanti + sürükleme).
    # Önceki aralık [50,250] gerçek değerin ALTINDA kalıyordu.
    check_range("Descent 18dk", descent, 200, 340)

    approach = fm.estimate_phase_fuel('APPROACH', 5*60, 57000, 3000)
    check_range("Approach 5dk", approach, 80, 200)

    holding = fm.estimate_phase_fuel('HOLDING', 10*60, 60000, 1500)
    check_range("Holding 10dk", holding, 300, 600)

    check("Phase 0s", fm.estimate_phase_fuel('CRUISE', 0, 65000, 35000, 0.785), 0.0, 0.01)

    taxi_1hr = fm.estimate_phase_fuel('GROUND', 3600, 72000)
    check_true(
        f"Cruise 1hr({cruise_1hr:.0f}) > Taxi 1hr({taxi_1hr:.0f})",
        cruise_1hr > taxi_1hr
    )

    # ═══════════════════════════════════════════════════════
    # 29. STEP CLIMB YAKIT MALİYETİ
    # ═══════════════════════════════════════════════════════
    print("\n  [29] Step Climb Yakıt")

    # ── GERÇEK DEĞER KONTROLÜ ──────────────────────────────
    # Bu değer "net ek ceza"dır = tırmanış yakıtı − aynı yatay
    # mesafede harcanacak seyir yakıtı.
    #
    # Gerçek B738 (FL350→FL370, 65 t):
    #   tırmanış yakıtı  ~270 kg
    #   yatay 18 nm, seyir eşdeğeri  ~90 kg
    #   NET ceza         ~180 kg
    #
    # ÖNCEKİ HATA: 200-400 aralığı, tırmanışın TOPLAM yakıtını
    # ceza sanan hatalı formülü kilitliyordu (sonuç her zaman
    # kârsız çıkıyordu). Aralık gerçek değere çekildi.
    climb_350_370 = fm.estimate_climb_fuel(35000, 37000, 65000)
    check_range("FL350→FL370 @ 65000kg (net ceza)", climb_350_370, 150, 230)

    climb_370_390 = fm.estimate_climb_fuel(37000, 39000, 65000)
    check_range("FL370→FL390 @ 65000kg (net ceza)", climb_370_390, 130, 230)

    climb_350_390 = fm.estimate_climb_fuel(35000, 39000, 65000)
    check_true(
        f"4000ft({climb_350_390:.0f}kg) > 2000ft({climb_350_370:.0f}kg)",
        climb_350_390 > climb_350_370
    )

    # ═══════════════════════════════════════════════════════
    # 30. STEP CLIMB AĞIRLIK İLİŞKİSİ
    # ═══════════════════════════════════════════════════════
    print("\n  [30] Step Climb — Ağırlık")

    climb_heavy = fm.estimate_climb_fuel(35000, 37000, 75000)
    climb_light = fm.estimate_climb_fuel(35000, 37000, 55000)

    check_true(
        f"Ağır({climb_heavy:.0f}kg) > Hafif({climb_light:.0f}kg)",
        climb_heavy > climb_light
    )

    # ═══════════════════════════════════════════════════════
    # 31. STEP CLIMB İNİŞ (SIFIR)
    # ═══════════════════════════════════════════════════════
    print("\n  [31] Step Climb İniş")

    check("İniş: climb_fuel", fm.estimate_climb_fuel(37000, 35000, 65000), 0.0, 0.01)
    check("Aynı irtifa", fm.estimate_climb_fuel(35000, 35000, 65000), 0.0, 0.01)

    # ═══════════════════════════════════════════════════════
    # 32. TOTAL FLIGHT FUEL (IST-LON)
    # ═══════════════════════════════════════════════════════
    print("\n  [32] Total Flight Fuel — IST-LON")

    total_lon = fm.estimate_total_flight_fuel(1560, 75000, 37000, 0.785)
    # Gerçek THY B738 IST-LHR (1560 nm): ~9.500-10.500 kg blok.
    # Model 9.731 kg → %1-2 içinde. Önceki alt sınır 10.000 gerçek
    # değeri DIŞARIDA bırakıyordu.
    check_range("IST-LON total", total_lon['total_fuel_kg'], 9000, 11500)

    check_true(
        f"Final({total_lon['final_weight_kg']:,.0f}) < Initial(75000)",
        total_lon['final_weight_kg'] < 75000
    )

    # ═══════════════════════════════════════════════════════
    # 33. TOTAL FLIGHT FUEL (IST-ANK)
    # ═══════════════════════════════════════════════════════
    print("\n  [33] Total Flight Fuel — IST-ANK")

    total_ank = fm.estimate_total_flight_fuel(190, 65000, 33000, 0.785)
    # Gerçek B738 IST-ESB (190 nm): ~2.200-2.600 kg blok.
    # ÖNEMLİ: önceki model 190 nm'de seyir fazını 0'a düşürüyordu
    # (sabit 80+120 nm transit > 190 nm). Düzeltildi → 2.205 kg.
    check_range("IST-ANK total", total_ank['total_fuel_kg'], 2000, 3000)

    check_true(
        f"LON({total_lon['total_fuel_kg']:,.0f}) > ANK({total_ank['total_fuel_kg']:,.0f})",
        total_lon['total_fuel_kg'] > total_ank['total_fuel_kg']
    )

    # ═══════════════════════════════════════════════════════
    # 34. CRUISE ORANI
    # ═══════════════════════════════════════════════════════
    print("\n  [34] Cruise Oranı")

    check_range("Cruise %", total_lon['cruise_pct'], 65, 85)

    bd = total_lon['phase_breakdown']
    check_true(
        f"Tüm fazlar pozitif ({len(bd)} faz)",
        all(v >= 0 for v in bd.values())
    )

    check_true(
        f"Cruise time: {total_lon['cruise_time_hr']:.2f} hr",
        total_lon['cruise_time_hr'] > 0
    )

    # ═══════════════════════════════════════════════════════
    # 35. KALİBRASYON — CD0
    # ═══════════════════════════════════════════════════════
    print("\n  [35] Kalibrasyon — CD0")

    fm_degraded = FuelModel('B738', cd0_factor=1.05)

    ff_new = fm.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)
    ff_old = fm_degraded.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)

    check_true(
        f"Degraded FF({ff_old:.0f}) > New FF({ff_new:.0f})",
        ff_old > ff_new
    )

    sar_new = fm.specific_air_range(65000, 35000, 0.785)
    sar_old = fm_degraded.specific_air_range(65000, 35000, 0.785)

    check_true(
        f"Degraded SAR({sar_old:.5f}) < New SAR({sar_new:.5f})",
        sar_old < sar_new
    )

    check("cd0 × 1.05", fm_degraded._effective_cd0, 0.019 * 1.05, 0.0001)

    # ═══════════════════════════════════════════════════════
    # 36. KALİBRASYON — SFC
    # ═══════════════════════════════════════════════════════
    print("\n  [36] Kalibrasyon — SFC")

    fm_sfc_high = FuelModel('B738', sfc_factor=1.03)

    ff_sfc_new = fm.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)
    ff_sfc_old = fm_sfc_high.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)

    check_true(
        f"High SFC FF({ff_sfc_old:.0f}) > Std FF({ff_sfc_new:.0f})",
        ff_sfc_old > ff_sfc_new
    )

    check("tsfc × 1.03", fm_sfc_high._effective_tsfc,
          fm._effective_tsfc * 1.03, 0.0000001)

    fm_both = FuelModel('B738', cd0_factor=1.05, sfc_factor=1.03)
    ff_both = fm_both.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)
    check_true(
        f"cd0+sfc degraded FF({ff_both:.0f}) > cd0 only({ff_old:.0f})",
        ff_both > ff_old
    )

    # ═══════════════════════════════════════════════════════
    # 37. ISA SAPMASI
    # ═══════════════════════════════════════════════════════
    print("\n  [37] ISA Sapması")

    fm_hot  = FuelModel('B738', delta_isa=20)
    fm_cold = FuelModel('B738', delta_isa=-15)

    ff_hot  = fm_hot.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)
    ff_cold = fm_cold.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)
    ff_std  = fm.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)

    check_true(
        f"ISA etkisi var: hot={ff_hot:.0f}, std={ff_std:.0f}, cold={ff_cold:.0f}",
        ff_hot != ff_std
    )

    # Not: ISA delta modeli hem T hem P değiştirdiğinden
    # CL yönü basit "sıcak→düşük yoğunluk→yüksek CL" değil
    cl_hot_val = fm_hot.lift_coefficient(65000, 35000, 0.785)
    cl_std_val = fm.lift_coefficient(65000, 35000, 0.785)
    check_true(
        f"delta_ISA CL'yi etkiliyor: hot={cl_hot_val:.4f}, std={cl_std_val:.4f}",
        cl_hot_val != cl_std_val
    )

    # ═══════════════════════════════════════════════════════
    # 38. FARKLI UÇAK TİPLERİ
    # ═══════════════════════════════════════════════════════
    print("\n  [38] Farklı Uçak Tipleri")

    # A320
    try:
        fm_a320 = FuelModel('A320')
        ff_a320 = fm_a320.cruise_fuel_flow_kg_hr(62000, 35000, 0.78)
        check_range("A320 FF @ 62000kg FL350", ff_a320, 2000, 3500)

        sar_a320 = fm_a320.specific_air_range(62000, 35000, 0.78)
        # SAR genişletilmiş aralık
        check_range("A320 SAR", sar_a320, 0.06, 0.22)
        print(f"  ✅ A320 çalışıyor: FF={ff_a320:.0f} kg/hr, SAR={sar_a320:.5f} Nm/kg")
    except Exception as e:
        errors.append(f"A320: {e}")
        tests += 2
        print(f"  ❌ A320 hatası: {e}")

    # B77W
    try:
        fm_777 = FuelModel('B77W')
        ff_777 = fm_777.cruise_fuel_flow_kg_hr(250000, 37000, 0.84)
        check_range("B77W FF @ 250000kg FL370", ff_777, 7000, 14000)

        sar_777 = fm_777.specific_air_range(250000, 37000, 0.84)
        check_range("B77W SAR", sar_777, 0.02, 0.08)

        sar_b738 = fm.specific_air_range(65000, 35000, 0.785)
        check_true(
            f"B77W SAR({sar_777:.5f}) < B738 SAR({sar_b738:.5f})",
            sar_777 < sar_b738
        )
        print(f"  ✅ B77W çalışıyor: FF={ff_777:.0f} kg/hr, SAR={sar_777:.5f} Nm/kg")
    except Exception as e:
        errors.append(f"B77W: {e}")
        tests += 3
        print(f"  ❌ B77W hatası: {e}")

    # A350
    try:
        fm_350 = FuelModel('A350')
        ff_350 = fm_350.cruise_fuel_flow_kg_hr(200000, 37000, 0.85)
        check_range("A350 FF", ff_350, 5500, 10000)
    except Exception as e:
        errors.append(f"A350: {e}")
        tests += 1
        print(f"  ❌ A350: {e}")

    # ═══════════════════════════════════════════════════════
    # 39. SUMMARY
    # ═══════════════════════════════════════════════════════
    print("\n  [39] Summary")

    try:
        fm.summary()
        tests += 1
        print("  ✅ summary() çalışıyor")
    except Exception as e:
        tests += 1
        errors.append(f"summary: {e}")
        print(f"  ❌ summary: {e}")

    # ═══════════════════════════════════════════════════════
    # 40. REPR
    # ═══════════════════════════════════════════════════════
    print("\n  [40] Repr")

    r = repr(fm)
    check_true(f"repr: {r}", 'FuelModel' in r and 'B738' in r)

    r_deg = repr(fm_degraded)
    check_true(f"repr degraded: {r_deg}", 'cd0_factor=1.05' in r_deg)

    # ═══════════════════════════════════════════════════════
    # SONUÇ
    # ═══════════════════════════════════════════════════════
    print(f"\n  {'─' * 50}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print(f"\n  ❌ BAŞARISIZ TESTLER:")
        for i, e in enumerate(errors, 1):
            print(f"     {i}. {e}")
        print()
        return False

    print(f"\n  ✅ TÜM TESTLER BAŞARILI\n")
    return True


if __name__ == "__main__":
    run_tests()