# tests/test_thermal_model.py

"""
GreenWing Analytics — SAF Termal Modelleme Testleri
═══════════════════════════════════════════════════

Bu test süiti:
    1.  TAT aerodinamik ısınma hesaplama doğruluğunu,
    2.  Zaman bazlı yakıt soğuma integrasyon simülasyonunu,
    3.  Donma limiti aşım tespiti ve kaçınma cezası (penalty) hesaplamalarını
test eder.

Çalıştırma:
    python tests/test_thermal_model.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.analysis.fuel_thermal_model import FuelThermalModel


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: fuel_thermal_model.py — TERMAL MODEL TEST SÜİTİ")
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

    # 1. TAT HESABI DOĞRULAMASI
    print("\n  [1] Aerodinamik Isınma (TAT) Doğrulaması")
    
    # SAT = -60°C, Mach = 0.78, r = 0.89
    # sat_k = 213.15 K
    # tat_k = 213.15 * (1 + 0.2 * 0.89 * 0.78^2) = 213.15 * (1 + 0.178 * 0.6084) = 213.15 * 1.10829 = 236.23 K
    # tat_c = 236.23 - 273.15 = -36.91°C
    model_std = FuelThermalModel(freezing_point_c=-47.0, cooling_coefficient=0.25)
    tat = model_std.calculate_tat(sat_c=-60.0, mach=0.78)
    check("Aerodinamik ısınma (SAT -60, M0.78)", tat, -36.91, 0.1)

    # ── [1b] DENETİM REFERANSLARI (2026-11-22) ──
    # Denetimde bu formülü "ram rise 3 kat fazla" diye şüphelendim;
    # bağımsız olarak doğrulayınca KODUN DOĞRU olduğu görüldü:
    #   FL380'de gerçek TAT değerleri -30…-35 °C arasındadır.
    #   SAT -56.5 °C, M0.78, r=0.89 → TAT -33.0 °C  ✓
    #   (Tam kurtarma r=1.0 olsaydı 26.4 K ram rise → -30.1 °C)
    #
    # Referans 1: FL380 tipik
    check("TAT referans: FL380 (SAT -56.5, M0.78)",
          model_std.calculate_tat(-56.5, 0.78), -33.04, 0.05)

    # Referans 2: statik hâl → ram rise YOK
    check("TAT statik (M0) = SAT",
          model_std.calculate_tat(15.0, 0.0), 15.0, 0.001)

    # Referans 3: Kelvin zorunlu — °C ile çarpılırsa saçma çıkar
    # İki farklı SAT ama aynı ram rise (K cinsinden sabit)
    _rr1 = model_std.calculate_tat(-56.5, 0.80) - (-56.5)
    _rr2 = model_std.calculate_tat(-40.0, 0.80) - (-40.0)
    # SAT daha sıcak → SAT_K büyük → ram rise büyük (fizik)
    check_true(
        f"ram rise SAT ile artar ({_rr1:.2f} < {_rr2:.2f})",
        _rr2 > _rr1
    )

    # Referans 4: r=1.0 tam kurtarma üst sınırdır
    _perfect = FuelThermalModel(recovery_factor=1.0)
    _rr_perfect = _perfect.calculate_tat(-56.5, 0.78) - (-56.5)
    check_true(
        f"r=1.0 ram rise ({_rr_perfect:.2f}) ≥ r=0.89",
        _rr_perfect > 23.0
    )
    
    # 2. SİMÜLASYON VE SOĞUMA KANUNU
    print("\n  [2] Newton Soğuma Kanunu Entegrasyon Simülasyonu")
    
    # 12 saatlik kutupsal uçuş, SAT = -80°C, Mach = 0.78
    # TAT = -58.2°C (yakıt donma limitini geçecek şekilde)
    sat_profile = [-80.0] * 144
    mach_profile = [0.78] * 144
    
    # Standart Jet A-1 Donma noktası -47°C (Emniyet limiti -44°C)
    sim_ref = model_std.simulate_flight_cooling(
        duration_hours=12.0,
        sat_c_profile=sat_profile,
        mach_profile=mach_profile,
        initial_fuel_temp_c=10.0
    )
    
    check_true("Referans simülasyon tamamlandı", len(sim_ref['fuel_temperatures_c']) > 0)
    check_true("Yakıt donma limitini aştı", sim_ref['limit_violated'])
    print(f"     Standart Jet A-1 Yakıt Limit Sıcaklığı: {sim_ref['limit_temperature_c']}°C")
    print(f"     Uçuş Sonu Yakıt Sıcaklığı             : {sim_ref['final_fuel_temp_c']:.2f}°C")
    print(f"     Donma Limitini Aşma Süresi            : {sim_ref['violation_time_mins']} dakika")

    # 3. SAF DONMA NOKTASI FAYDASI
    print("\n  [3] Profesörün Düşük Donma Noktalı Prototipli SAF'ının Analizi")
    
    # Profesörün SAF donma noktası -65°C olsun (Emniyet limiti -62°C)
    # TAT = -58.2°C olduğundan, -62°C limitini geçmez!
    model_prof = FuelThermalModel(freezing_point_c=-65.0, cooling_coefficient=0.25)
    sim_prof = model_prof.simulate_flight_cooling(
        duration_hours=12.0,
        sat_c_profile=sat_profile,
        mach_profile=mach_profile,
        initial_fuel_temp_c=10.0
    )
    
    check_true("Profesörün SAF'ı donma limitini aşmadı", not sim_prof['limit_violated'])
    print(f"     Profesörün SAF Limit Sıcaklığı: {sim_prof['limit_temperature_c']}°C")
    print(f"     Uçuş Sonu Yakıt Sıcaklığı     : {sim_prof['final_fuel_temp_c']:.2f}°C")

    # 4. OPERASYONEL KAÇINMA PENALTY HESABI
    print("\n  [4] Operasyonel Kaçınma Manevrası Yakıt Cezası (Penalty) Analizi")
    
    # Standart yakıtta kaçınma cezası (irtifa düşürme veya hızlanma)
    penalty_ref = model_std.evaluate_freezing_mitigation_penalty(
        base_altitude_ft=37000,
        mach=0.78,
        sat_c=-80.0,
        initial_fuel_temp_c=10.0,
        flight_duration_hrs=12.0
    )
    
    # Profesörün yakıtında kaçınma cezası
    penalty_prof = model_prof.evaluate_freezing_mitigation_penalty(
        base_altitude_ft=37000,
        mach=0.78,
        sat_c=-80.0,
        initial_fuel_temp_c=10.0,
        flight_duration_hrs=12.0
    )
    
    check_true("Standart yakıt operasyonel müdahale gerektiriyor", penalty_ref['requires_mitigation'])
    check_true("Profesörün SAF'ı operasyonel müdahale gerektirmiyor", not penalty_prof['requires_mitigation'])
    
    print(f"     Standart Yakıt İrtifa Cezası: {penalty_ref['desc_altitude_penalty_kg']} kg")
    print(f"     Profesörün SAF'ı İrtifa Cezası: {penalty_prof['desc_altitude_penalty_kg']} kg (KAYIP ENGELLENDİ!)")
    
    check("Profesörün SAF tasarrufu (Cezadan kurtulma)", 
          penalty_ref['desc_altitude_penalty_kg'] - penalty_prof['desc_altitude_penalty_kg'], 
          penalty_ref['desc_altitude_penalty_kg'], 
          0.1)

    # ═══════════════════════════════════════════════════════
    # SONUÇ
    # ═══════════════════════════════════════════════════════
    print(f"\n  {'─' * 50}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print(f"\n  ❌ BAŞARISIZ TERMAL TESTLER:")
        for i, e in enumerate(errors, 1):
            print(f"     {i}. {e}")
        return False
    print("  ✅ TÜM TERMAL MODEL TESTLERİ BAŞARILI\n")
    return True


if __name__ == "__main__":
    run_tests()
