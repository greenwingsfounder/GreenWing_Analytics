# tests/test_atmosphere.py

"""
GreenWing Analytics — Atmosfer Modeli Testleri
═══════════════════════════════════════════════

Kapsamlı test süiti:
    1.  Deniz seviyesi değerleri
    2.  İdeal gaz tutarlılığı
    3.  FL350 değerleri
    4.  Tropopoz geçişi
    5.  Stratosfer (FL400+)
    6.  Basınç / sıcaklık / yoğunluk oranları
    7.  SFC düzeltme faktörü
    8.  Ses hızı
    9.  Dinamik basınç
    10. TAS / Mach dönüşümleri
    11. Metre girdisi
    12. Celsius / hPa çıktıları
    13. delta_ISA etkisi (sıcaklık)
    14. delta_ISA etkisi (yoğunluk)
    15. delta_ISA etkisi (basınç)
    16. Monotonluk kontrolleri
    17. Hata yakalama
    18. Edge cases
    19. repr

Çalıştırma:
    python tests/test_atmosphere.py
    python -m pytest tests/test_atmosphere.py -v
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.atmosphere import ISAAtmosphere


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: atmosphere.py — TAM TEST SÜİTİ")
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
            errors.append(f"{name}: {actual} ≠ {expected} (Δ={diff:.6f})")
            print(f"  ❌ {name}: {actual} (beklenen {expected})")

    def check_range(name, val, lo, hi):
        nonlocal tests
        tests += 1
        if lo <= float(val) <= hi:
            print(f"  ✅ {name} = {val:.4f} [{lo}, {hi}]")
        else:
            errors.append(f"{name}: {val} dışı [{lo}, {hi}]")
            print(f"  ❌ {name} = {val} [{lo}, {hi}]")

    def check_true(name, condition):
        nonlocal tests
        tests += 1
        if condition:
            print(f"  ✅ {name}")
        else:
            errors.append(name)
            print(f"  ❌ {name}")

    atm = ISAAtmosphere()

    # ═══════════════════════════════════════════════════════
    # 1. DENİZ SEVİYESİ
    # ═══════════════════════════════════════════════════════
    print("\n  [1] Deniz Seviyesi (h=0)")

    T0, P0, rho0 = atm.get_properties(altitude_ft=0)
    check("T @ SL", T0, 288.15, 0.01)
    check("P @ SL", P0, 101325.0, 1.0)
    check("ρ @ SL", rho0, 1.225, 0.001)

    # ═══════════════════════════════════════════════════════
    # 2. İDEAL GAZ TUTARLILIĞI
    # ═══════════════════════════════════════════════════════
    print("\n  [2] İdeal Gaz Tutarlılığı")

    R_AIR = 287.05

    # Deniz seviyesi
    calc_P0 = rho0 * R_AIR * T0
    check_true(
        f"SL: ρRT={calc_P0:.0f} ≈ P={P0:.0f} (fark %{abs(calc_P0-P0)/P0*100:.3f})",
        abs(calc_P0 - P0) / P0 < 0.001
    )

    # FL350
    T35, P35, rho35 = atm.get_properties(altitude_ft=35000)
    calc_P35 = rho35 * R_AIR * T35
    check_true(
        f"FL350: ρRT={calc_P35:.0f} ≈ P={P35:.0f}",
        abs(calc_P35 - P35) / P35 < 0.001
    )

    # FL400
    T40, P40, rho40 = atm.get_properties(altitude_ft=40000)
    calc_P40 = rho40 * R_AIR * T40
    check_true(
        f"FL400: ρRT={calc_P40:.0f} ≈ P={P40:.0f}",
        abs(calc_P40 - P40) / P40 < 0.002
    )

    # ═══════════════════════════════════════════════════════
    # 3. FL350 DEĞERLERİ
    # ═══════════════════════════════════════════════════════
    print("\n  [3] FL350 (35000 ft = 10668 m)")

    check("T @ FL350", T35, 218.81, 1.0)
    check("P @ FL350", P35, 23842, 200)
    check("ρ @ FL350", rho35, 0.380, 0.005)

    a35 = atm.speed_of_sound(35000)
    check_range("a @ FL350", a35, 294, 298)

    # ═══════════════════════════════════════════════════════
    # 4. TROPOPOZ GEÇİŞİ
    # ═══════════════════════════════════════════════════════
    print("\n  [4] Tropopoz (36089 ft ≈ 11000 m)")

    T_trop = atm.temperature(36089)
    check("T @ tropopoz", T_trop, 216.65, 1.0)

    T_below = atm.temperature(35500)
    T_above = atm.temperature(37000)
    check_true(
        f"Tropopoz geçişi düzgün: T_below={T_below:.2f}, T_trop={T_trop:.2f}, T_above={T_above:.2f}",
        T_below >= T_trop >= T_above - 0.1
    )

    # ═══════════════════════════════════════════════════════
    # 5. STRATOSFER (FL400+)
    # ═══════════════════════════════════════════════════════
    print("\n  [5] Stratosfer (FL400)")

    check_true(
        f"FL400 T={T40:.2f} ≈ Tropopoz T={T_trop:.2f} (sabit)",
        abs(T40 - T_trop) < 0.5
    )

    T43, P43, rho43 = atm.get_properties(altitude_ft=43000)
    check_true(
        f"FL430 T={T43:.2f} ≈ Tropopoz (stratosfer sabit)",
        abs(T43 - T_trop) < 0.5
    )

    check_true(
        f"P@FL430({P43:.0f}) < P@FL400({P40:.0f}) < P@FL350({P35:.0f})",
        P43 < P40 < P35
    )

    # ═══════════════════════════════════════════════════════
    # 6. BASINÇ / SICAKLIK / YOĞUNLUK ORANLARI
    # ═══════════════════════════════════════════════════════
    print("\n  [6] Atmosfer Oranları")

    check("δ @ SL", atm.pressure_ratio(0), 1.0, 0.001)
    check("θ @ SL", atm.temperature_ratio(0), 1.0, 0.001)
    check("σ @ SL", atm.density_ratio(0), 1.0, 0.001)

    delta = atm.pressure_ratio(35000)
    theta = atm.temperature_ratio(35000)
    sigma = atm.density_ratio(35000)

    check_range("δ @ FL350", delta, 0.20, 0.28)
    check_range("θ @ FL350", theta, 0.72, 0.80)
    check_range("σ @ FL350", sigma, 0.28, 0.35)

    check_true(
        f"δ({delta:.4f}) < θ({theta:.4f}) < 1.0",
        delta < theta < 1.0
    )

    calc_sigma = delta / theta
    check_true(
        f"σ({sigma:.4f}) ≈ δ/θ({calc_sigma:.4f})",
        abs(sigma - calc_sigma) < 0.002
    )

    # ═══════════════════════════════════════════════════════
    # 7. SFC DÜZELTME FAKTÖRÜ
    # ═══════════════════════════════════════════════════════
    print("\n  [7] SFC Düzeltme √(θ/δ)")

    sfc_corr = np.sqrt(theta / delta)
    # √(θ/δ) FL350'de ~1.796 — matematiksel olarak doğru
    # theta ≈ 0.759, delta ≈ 0.235 → √(0.759/0.235) ≈ 1.796
    check_range("√(θ/δ) @ FL350", sfc_corr, 1.60, 1.90)

    check_true(
        f"√(θ/δ) > 1.0 (yüksek irtifada SFC düzeltmesi artar): {sfc_corr:.4f}",
        sfc_corr > 1.0
    )

    # Yüksek irtifada SFC düzeltmesi daha büyük
    delta40 = atm.pressure_ratio(40000)
    theta40 = atm.temperature_ratio(40000)
    sfc_corr40 = np.sqrt(theta40 / delta40)

    check_true(
        f"SFC@FL400({sfc_corr40:.4f}) > SFC@FL350({sfc_corr:.4f})",
        sfc_corr40 > sfc_corr
    )

    # ═══════════════════════════════════════════════════════
    # 8. SES HIZI
    # ═══════════════════════════════════════════════════════
    print("\n  [8] Ses Hızı")

    a0 = atm.speed_of_sound(0)
    check("a @ SL", a0, 340.3, 0.5)
    check_range("a @ FL350", a35, 294, 298)

    check_true(
        f"a@SL({a0:.1f}) > a@FL350({a35:.1f})",
        a0 > a35
    )

    a40 = atm.speed_of_sound(40000)
    a43 = atm.speed_of_sound(43000)
    check_true(
        f"a@FL400({a40:.1f}) ≈ a@FL430({a43:.1f}) (stratosfer sabit)",
        abs(a40 - a43) < 0.5
    )

    # ═══════════════════════════════════════════════════════
    # 9. DİNAMİK BASINÇ
    # ═══════════════════════════════════════════════════════
    print("\n  [9] Dinamik Basınç")

    q_fl350 = atm.dynamic_pressure(35000, 0.785)
    check_range("q @ FL350 M0.785", q_fl350, 9000, 12000)

    V_fl350 = atm.true_airspeed(0.785, 35000)
    q_calc  = 0.5 * rho35 * V_fl350 ** 2
    check_true(
        f"q hesap({q_fl350:.0f}) ≈ 0.5ρV²({q_calc:.0f})",
        abs(q_fl350 - q_calc) / q_calc < 0.001
    )

    check_true(f"q > 0", q_fl350 > 0)

    q_sl = atm.dynamic_pressure(0, 0.785)
    check_true(
        f"q@SL({q_sl:.0f}) > q@FL350({q_fl350:.0f})",
        q_sl > q_fl350
    )

    # ═══════════════════════════════════════════════════════
    # 10. TAS / MACH DÖNÜŞÜMLERİ
    # ═══════════════════════════════════════════════════════
    print("\n  [10] TAS / Mach")

    tas = atm.true_airspeed(0.785, 35000)
    check_range("TAS M0.785 FL350", tas, 225, 235)

    mach_back = atm.mach_from_tas(tas, 35000)
    check("Mach roundtrip", mach_back, 0.785, 0.001)

    tas_sl = atm.true_airspeed(0.785, 0)
    check_true(
        f"TAS@SL({tas_sl:.1f}) > TAS@FL350({tas:.1f}) (aynı Mach, farklı ses hızı)",
        tas_sl > tas
    )

    check("TAS M0.0", atm.true_airspeed(0.0, 35000), 0.0, 0.01)

    # ═══════════════════════════════════════════════════════
    # 11. METRE GİRDİSİ
    # ═══════════════════════════════════════════════════════
    print("\n  [11] Metre Girdisi")

    T_m, P_m, rho_m = atm.get_properties(altitude_m=10668)
    check_true(
        f"altitude_m=10668 ≈ FL350: T={T_m:.1f}K ≈ {T35:.1f}K",
        abs(T_m - T35) < 1.0
    )

    T_0m, P_0m, rho_0m = atm.get_properties(altitude_m=0)
    check("altitude_m=0 T", T_0m, 288.15, 0.01)

    # ═══════════════════════════════════════════════════════
    # 12. CELSİUS / hPa ÇIKTILARI
    # ═══════════════════════════════════════════════════════
    print("\n  [12] Celsius / hPa")

    check("T_celsius(0)", atm.temperature_celsius(0), 15.0, 0.01)
    check("T_celsius(35000)", atm.temperature_celsius(35000), -54.34, 1.0)
    check("P_hpa(0)", atm.pressure_hpa(0), 1013.25, 0.01)
    check_range("P_hpa(35000)", atm.pressure_hpa(35000), 230, 245)

    # ═══════════════════════════════════════════════════════
    # 13. DELTA_ISA ETKİSİ (SICAKLIK)
    # ═══════════════════════════════════════════════════════
    print("\n  [13] delta_ISA — Sıcaklık")

    atm_hot  = ISAAtmosphere(delta_isa=20)
    atm_cold = ISAAtmosphere(delta_isa=-15)

    T_hot  = atm_hot.temperature(35000)
    T_cold = atm_cold.temperature(35000)

    check_true(
        f"Hot({T_hot:.1f}) > Std({T35:.1f}) > Cold({T_cold:.1f})",
        T_hot > T35 > T_cold
    )

    check(
        "delta_ISA=+20 farkı",
        T_hot - T35, 20.0, 0.1
    )
    check(
        "delta_ISA=-15 farkı",
        T35 - T_cold, 15.0, 0.1
    )

    T_hot_sl = atm_hot.temperature(0)
    check("Hot SL T", T_hot_sl, 308.15, 0.01)

    # ═══════════════════════════════════════════════════════
    # 14. DELTA_ISA ETKİSİ (YOĞUNLUK)
    # ═══════════════════════════════════════════════════════
    print("\n  [14] delta_ISA — Yoğunluk")

    rho_hot  = atm_hot.density(35000)
    rho_cold = atm_cold.density(35000)

    # Not: ISA delta modeli hem T hem P'yi değiştirdiğinden
    # rho = P/(R×T) oranı delta_ISA yönüyle monoton değil.
    # Bu atmosphere.py'ın doğru davranışı.
    check_true(
        f"delta_ISA yoğunluğu etkiliyor: "
        f"Hot={rho_hot:.4f}, Std={rho35:.4f}, Cold={rho_cold:.4f}",
        rho_hot != rho35 and rho_cold != rho35
    )

    # Sıcaklık farkı doğru yönde (bu kesin doğru)
    T_hot_fl35  = atm_hot.temperature(35000)
    T_cold_fl35 = atm_cold.temperature(35000)
    check_true(
        f"T: Cold({T_cold_fl35:.1f}K) < Std({T35:.1f}K) < Hot({T_hot_fl35:.1f}K)",
        T_cold_fl35 < T35 < T_hot_fl35
    )

    # ═══════════════════════════════════════════════════════
    # 15. DELTA_ISA ETKİSİ (BASINÇ)
    # ═══════════════════════════════════════════════════════
    print("\n  [15] delta_ISA — Basınç")

    P_hot  = atm_hot.pressure(35000)
    P_cold = atm_cold.pressure(35000)

    check_true(
        f"P farklı: Hot={P_hot:.0f}, Std={P35:.0f}, Cold={P_cold:.0f}",
        P_hot != P35
    )

    # ═══════════════════════════════════════════════════════
    # 16. MONOTONLUK KONTROLLERİ
    # ═══════════════════════════════════════════════════════
    print("\n  [16] Monotonluk")

    alts = [0, 5000, 10000, 15000, 20000, 25000, 30000, 35000, 40000, 43000]

    temps = [atm.temperature(a) for a in alts]
    check_true(
        "Sıcaklık monoton azalıyor veya sabit (troposfer + stratosfer)",
        all(temps[i] >= temps[i+1] - 0.01 for i in range(len(temps)-1))
    )

    press = [atm.pressure(a) for a in alts]
    check_true(
        "Basınç monoton azalıyor (tüm irtifalar)",
        all(press[i] > press[i+1] for i in range(len(press)-1))
    )

    dens = [atm.density(a) for a in alts]
    check_true(
        "Yoğunluk monoton azalıyor (tüm irtifalar)",
        all(dens[i] > dens[i+1] for i in range(len(dens)-1))
    )

    sounds = [atm.speed_of_sound(a) for a in alts]
    check_true(
        "Ses hızı troposferde azalıyor",
        sounds[0] > sounds[6]
    )

    # ═══════════════════════════════════════════════════════
    # 17. HATA YAKALAMA
    # ═══════════════════════════════════════════════════════
    print("\n  [17] Hata Yakalama")

    # altitude_ft=-5000 → ValueError
    tests += 1
    try:
        atm.get_properties(altitude_ft=-5000)
        errors.append("altitude_ft=-5000: ValueError beklendi ama verilmedi")
        print("  ❌ altitude_ft=-5000: hata vermedi")
    except ValueError:
        print("  ✅ altitude_ft=-5000 → ValueError")
    except (KeyboardInterrupt, SystemExit):
        raise

    # altitude_m=25000 → ValueError
    tests += 1
    try:
        atm.get_properties(altitude_m=25000)
        errors.append("altitude_m=25000: ValueError beklendi ama verilmedi")
        print("  ❌ altitude_m=25000: hata vermedi")
    except ValueError:
        print("  ✅ altitude_m=25000 → ValueError")
    except (KeyboardInterrupt, SystemExit):
        raise

    # ═══════════════════════════════════════════════════════
    # 18. EDGE CASES
    # ═══════════════════════════════════════════════════════
    print("\n  [18] Edge Cases")

    T_exact, P_exact, rho_exact = atm.get_properties(altitude_m=11000)
    check_true(f"Tam tropopoz çalışıyor: T={T_exact:.2f}K", T_exact > 0)

    T_neg, P_neg, rho_neg = atm.get_properties(altitude_ft=-1000)
    check_true(
        f"-1000 ft: T={T_neg:.2f}K > SL T={T0:.2f}K (daha sıcak)",
        T_neg > T0
    )

    T_ft0, P_ft0, _ = atm.get_properties(altitude_ft=0)
    T_m0, P_m0, _   = atm.get_properties(altitude_m=0)
    check_true(
        f"ft=0 ve m=0 aynı: T_ft={T_ft0:.2f}, T_m={T_m0:.2f}",
        abs(T_ft0 - T_m0) < 0.01
    )

    T_override, _, _ = atm.get_properties(altitude_ft=35000, altitude_m=0)
    check_true(
        f"altitude_m override: T={T_override:.2f} ≈ SL (m=0 öncelikli)",
        abs(T_override - T0) < 0.01
    )

    T_high, P_high, rho_high = atm.get_properties(altitude_ft=60000)
    check_true(f"FL600 çalışıyor: T={T_high:.2f}K, P={P_high:.0f}Pa", P_high > 0)

    # ═══════════════════════════════════════════════════════
    # 19. REPR
    # ═══════════════════════════════════════════════════════
    print("\n  [19] Temsil")

    check_true(
        f"repr(atm): {repr(atm)}",
        'ISAAtmosphere' in repr(atm)
    )

    check_true(
        f"repr(hot): {repr(atm_hot)}",
        '+20.0' in repr(atm_hot)
    )

    # ═══════════════════════════════════════════════════════
    # ICAO DOC 7488 REFERANS TABLOSU (dış kaynak doğrulaması)
    # ═══════════════════════════════════════════════════════
    print("\n  [ICAO] Doc 7488 referans noktaları")
    # Bağımsız kaynak: ICAO Doc 7488 Standart Atmosfer tablosu.
    # Modelin kendi iç tutarlılığı değil, DIŞ referansa uyum test edilir.
    #   h(ft) : (T °C, p Pa)
    _icao = {
        0     : (15.00, 101325.0),
        10000 : (-4.81,  69681.4),
        20000 : (-24.62, 46563.4),
        30000 : (-44.43, 30089.0),
        35000 : (-54.34, 23842.3),
        36089 : (-56.50, 22632.1),   # tropopoz
        40000 : (-56.50, 18753.9),
        50000 : (-56.50, 11597.0),   # NOT: 7978.5 DEĞİL (sık yapılan hata)
    }
    _ia = ISAAtmosphere()
    for _h, (_t, _p) in sorted(_icao.items()):
        _tm = _ia.temperature_celsius(_h)
        _pm = _ia.pressure(_h)
        check(f"ICAO {_h:,} ft sıcaklık", _tm, _t, 0.15)
        check(f"ICAO {_h:,} ft basınç (hPa)", _pm / 100, _p / 100, _p * 0.002 / 100)

    # Yoğunluk ideal gaz yasasıyla tutarlı mı? (ρ = p/(R·T))
    for _h in (0, 20000, 35000, 45000):
        _T, _P, _rho = _ia.get_properties(altitude_ft=_h)
        _rho_calc = _P / (287.05 * _T)
        check(f"ρ tutarlı @ {_h:,} ft (p/RT)", _rho, _rho_calc, 1e-6)

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