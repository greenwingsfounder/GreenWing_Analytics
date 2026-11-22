# tests/test_emission.py

"""
GreenWing Analytics — Emisyon Modeli Testleri
═════════════════════════════════════════════

Kapsamlı test süiti:
    1.  CO₂ temel hesapları
    2.  H₂O hesabı
    3.  SO₂ hesabı
    4.  CO₂ sıfır yakıt
    5.  CO₂ çapraz doğrulama
    6.  NOx — CFM56 motoru
    7.  NOx — LEAP motoru (daha temiz olmalı)
    8.  NOx — generic fallback (bilinmeyen motor)
    9.  NOx — irtifa etkisi
    10. Tam uçuş emisyonu — temel
    11. Tam uçuş — B738→motor eşleşmesi
    12. Tam uçuş — A350→motor eşleşmesi
    13. Tam uçuş — CO₂/pax/km
    14. Tam uçuş — fuel/Nm metriği
    15. CO₂ tutarlılık (fuel × 3.16)
    16. Contrail — yüksek irtifa (oluşmalı)
    17. Contrail — alçak irtifa (oluşmamalı)
    18. Contrail — persistent kontrolü
    19. SAF — temel (%6 HEFA)
    20. SAF — miktar doğrulama (12500 × 0.06 = 750 kg)
    21. SAF — CO₂ azaltım pozitif
    22. SAF — EU mandate içeriği
    23. SAF — farklı tipler (HEFA, FT_SPK, ATJ, PTL)
    24. SAF — %0 = sıfır azaltım
    25. CORSIA monitoring — temel
    26. CORSIA monitoring — CO₂ hesabı
    27. CORSIA reporting_document
    28. CORSIA verification_checklist
    29. get_engine_for_aircraft (B738, A350, B77W)
    30. get_available_engines
    31. get_available_saf_types
    32. get_engine_info (GE90-115B)
    33. Bilinmeyen motor — None döner

Çalıştırma:
    python tests/test_emission.py
    python -m pytest tests/test_emission.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.emission_model import EmissionCalculator, CORSIACompliance


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: emission_model.py — TAM TEST SÜİTİ")
    print("=" * 60)

    errors = []
    tests  = 0
    calc   = EmissionCalculator()

    def check(name, actual, expected, tol=1.0):
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
            errors.append(f"{name}: {v} dışı [{lo}, {hi}]")
            print(f"  ❌ {name} = {v} [{lo}, {hi}]")

    def check_true(name, condition):
        nonlocal tests
        tests += 1
        if condition:
            print(f"  ✅ {name}")
        else:
            errors.append(name)
            print(f"  ❌ {name}")

    # ═══════════════════════════════════════════════════════
    # 1. CO₂ TEMEL HESAPLARI
    # ═══════════════════════════════════════════════════════
    print("\n  [1] CO₂ Temel Hesapları")

    check("CO₂ 1000 kg", calc.co2_from_fuel(1000), 3160.0, 1.0)
    check("CO₂ 12500 kg", calc.co2_from_fuel(12500), 39500.0, 1.0)
    check("CO₂ 50000 kg", calc.co2_from_fuel(50000), 158000.0, 1.0)

    # ═══════════════════════════════════════════════════════
    # 2. H₂O HESABI
    # ═══════════════════════════════════════════════════════
    print("\n  [2] H₂O Hesabı")

    check("H₂O 1000 kg", calc.h2o_from_fuel(1000), 1240.0, 1.0)
    check("H₂O 12500 kg", calc.h2o_from_fuel(12500), 15500.0, 1.0)

    # ═══════════════════════════════════════════════════════
    # 3. SO₂ HESABI
    # ═══════════════════════════════════════════════════════
    print("\n  [3] SO₂ Hesabı")

    check("SO₂ 1000 kg", calc.so2_from_fuel(1000), 1.0, 0.01)
    check("SO₂ 10000 kg", calc.so2_from_fuel(10000), 10.0, 0.01)

    # ═══════════════════════════════════════════════════════
    # 4. SIFIR YAKIT
    # ═══════════════════════════════════════════════════════
    print("\n  [4] Sıfır Yakıt")

    check("CO₂ 0 kg", calc.co2_from_fuel(0), 0.0, 0.01)
    check("H₂O 0 kg", calc.h2o_from_fuel(0), 0.0, 0.01)
    check("SO₂ 0 kg", calc.so2_from_fuel(0), 0.0, 0.01)

    # ═══════════════════════════════════════════════════════
    # 5. CO₂ ÇAPRAZ DOĞRULAMA
    # ═══════════════════════════════════════════════════════
    print("\n  [5] CO₂ Çapraz Doğrulama")

    EI_CO2 = 3.16
    for fuel_kg in [500, 1000, 5000, 12500, 50000]:
        expected = fuel_kg * EI_CO2
        actual   = calc.co2_from_fuel(fuel_kg)
        check(f"CO₂ = {fuel_kg}×3.16", actual, expected, 0.01)

    # ═══════════════════════════════════════════════════════
    # 6. NOx — CFM56 MOTORU
    # ═══════════════════════════════════════════════════════
    print("\n  [6] NOx — CFM56-7B26")

    nox_cfm56 = calc.nox_bffm2(0.35, 35000, 0.785, 'CFM56-7B26')
    check_range("NOx EI CFM56 cruise", nox_cfm56, 1.0, 20.0)
    check_true(f"NOx CFM56 > 0: {nox_cfm56:.3f}", nox_cfm56 > 0)

    # Farklı fazlarda NOx değerleri
    nox_idle     = calc.nox_bffm2(0.1, 0, 0.0, 'CFM56-7B26', 'idle')
    nox_takeoff  = calc.nox_bffm2(0.8, 0, 0.0, 'CFM56-7B26', 'takeoff')

    check_true(
        f"Takeoff NOx({nox_takeoff:.2f}) > Idle NOx({nox_idle:.2f})",
        nox_takeoff > nox_idle
    )

    # ═══════════════════════════════════════════════════════
    # 7. NOx — LEAP MOTORU (DAHA TEMİZ)
    # ═══════════════════════════════════════════════════════
    print("\n  [7] NOx — LEAP-1B (Daha Temiz)")

    nox_leap = calc.nox_bffm2(0.30, 35000, 0.79, 'LEAP-1B')
    check_range("NOx EI LEAP cruise", nox_leap, 0.5, 15.0)
    check_true(f"NOx LEAP > 0: {nox_leap:.3f}", nox_leap > 0)

    # LEAP yeni nesil → CFM56'dan daha az NOx
    nox_cfm_same_cond = calc.nox_bffm2(0.30, 35000, 0.79, 'CFM56-7B26')
    check_true(
        f"LEAP NOx({nox_leap:.3f}) ≤ CFM56 NOx({nox_cfm_same_cond:.3f})",
        nox_leap <= nox_cfm_same_cond
    )

    # ═══════════════════════════════════════════════════════
    # 7b. [BFFM2] GERÇEK DAVRANIŞ — denetim #38 regresyonu
    # ═══════════════════════════════════════════════════════
    print("\n  [7b] [BFFM2] Yakıt akışı / Mach / referans doğrulaması")

    # DENETİM #38: Bu fonksiyonun adı "BFFM2" idi ama iki temel
    # girdisi (yakıt akışı, Mach) HİÇ KULLANILMIYORDU. Yakıt akışı
    # 0,3 → 1,8 kg/s arasında EI sabit 10,47 kalıyordu.
    # Aşağıdaki testler bu mekanizmaları kilitler.

    _e = calc

    # (a) Yakıt akışı EI_NOx'i DEĞİŞTİRMELİ (pozitif eğim)
    _ff_lo = _e.nox_bffm2(0.20, 35000, 0.785, 'CFM56-7B26')
    _ff_hi = _e.nox_bffm2(0.60, 35000, 0.785, 'CFM56-7B26')
    check_true(
        f"BFFM2 yakıt akışı etkili: 0.20→{_ff_lo:.2f}, "
        f"0.60→{_ff_hi:.2f} g/kg (artmalı)",
        _ff_hi > _ff_lo * 1.5
    )

    # (b) Mach EI_NOx'i DEĞİŞTİRMELİ
    _m_lo = _e.nox_bffm2(0.33, 35000, 0.60, 'CFM56-7B26')
    _m_hi = _e.nox_bffm2(0.33, 35000, 0.85, 'CFM56-7B26')
    check_true(
        f"BFFM2 Mach etkili: M0.60→{_m_lo:.2f}, M0.85→{_m_hi:.2f} (artmalı)",
        _m_hi > _m_lo
    )

    # (c) Referans noktası: SL statik tam itki = EDB takeoff EI
    #     (TSFC 1.1e-5 kg/(N·s) → 117 kN × 1.1e-5 = 1.287 kg/s)
    _sl_ref = _e.nox_bffm2(1.287, 0, 0.0, 'CFM56-7B26')
    check_true(
        f"BFFM2 SL statik tam itki = EDB takeoff ({_sl_ref:.2f} ≈ 27.4)",
        abs(_sl_ref - 27.4) < 1.0
    )

    # (d) Gerçekçi cruise: %25-30 itki → 8-15 g/kg aralığında
    #     (EDB cruise EI_NOx tipik 10-20; eski kod 10,5 sabit veriyordu)
    _cruise = _e.nox_bffm2(0.335, 35000, 0.785, 'CFM56-7B26')
    check_range("BFFM2 gerçekçi cruise EI (26% itki)", _cruise, 8.0, 15.0)

    # (e) AYNI İTKİDE irtifa etkisi.
    #     DİKKAT: "aynı yakıt akışında" testi yanıltıcı — alçakta
    #     aynı akış çok daha düşük itki demektir (W_ref = W·θ^3.3/δ^1.02),
    #     o yüzden EI düşük çıkar. Doğru kıyas: SABİT W_ref (sabit itki).
    from src.units import Units as _U
    def _ff_for_ref(ref_flow, alt):
        d = _U.pressure_ratio(alt); t = _U.temperature_ratio(alt)
        return ref_flow * (d ** 1.02 / t ** 3.3)
    _ref = 0.386  # approach seviyesi sabit itki
    _hi_alt = _e.nox_bffm2(_ff_for_ref(_ref, 41000), 41000, 0.785, 'CFM56-7B26')
    _lo_alt = _e.nox_bffm2(_ff_for_ref(_ref, 25000), 25000, 0.785, 'CFM56-7B26')
    check_true(
        f"BFFM2 sabit itkide irtifa etkisi: 41k→{_hi_alt:.2f} < 25k→{_lo_alt:.2f}",
        _lo_alt > _hi_alt
    )

    # (f) Nem EI'yi DÜŞÜRMELİ (BFFM2 nem düzeltmesi)
    _dry = _e.nox_bffm2(0.335, 35000, 0.785, 'CFM56-7B26', humidity=0.0)
    _wet = _e.nox_bffm2(0.335, 35000, 0.785, 'CFM56-7B26', humidity=0.02)
    check_true(
        f"BFFM2 nem etkisi: kuru {_dry:.2f} > nemli {_wet:.2f}",
        _dry > _wet
    )

    # (g) EI_NOx hiçbir koşulda negatif olmamalı
    _weird = _e.nox_bffm2(0.001, 43000, 0.0, 'CFM56-7B26')
    check_true(f"BFFM2 EI alt sınırı pozitif: {_weird:.3f}", _weird > 0)

    # ═══════════════════════════════════════════════════════
    # 8. NOx — GENERIC FALLBACK
    # ═══════════════════════════════════════════════════════
    print("\n  [8] NOx — Generic Fallback")

    nox_unknown = calc.nox_bffm2(0.35, 35000, 0.785, 'BILINMEYEN_MOTOR_XYZ')
    check_true(
        f"Bilinmeyen motor generic NOx: {nox_unknown:.3f} > 0",
        nox_unknown > 0
    )

    # ═══════════════════════════════════════════════════════
    # 9. NOx — İRTİFA ETKİSİ
    # ═══════════════════════════════════════════════════════
    print("\n  [9] NOx — İrtifa Etkisi")

    nox_sl    = calc.nox_bffm2(0.35, 0, 0.0, 'CFM56-7B26')
    nox_fl350 = calc.nox_bffm2(0.35, 35000, 0.785, 'CFM56-7B26')

    check_true(
        f"Yüksek irtifada NOx azalır: SL({nox_sl:.3f}) vs FL350({nox_fl350:.3f})",
        nox_sl != nox_fl350
    )

    # ═══════════════════════════════════════════════════════
    # 10. TAM UÇUŞ EMİSYONU — TEMEL
    # ═══════════════════════════════════════════════════════
    print("\n  [10] Tam Uçuş Emisyonu")

    result = calc.calculate_flight_emissions(
        fuel_burn_kg=12500,
        distance_nm=1560,
        aircraft_type='B738',
        cruise_altitude_ft=37000,
        cruise_mach=0.785,
    )

    em = result['emissions']
    mt = result['metrics']

    check("CO₂ kg", em['CO2_kg'], 39500.0, 1.0)
    check("H₂O kg", em['H2O_kg'], 15500.0, 1.0)
    check_true(f"NOx > 0: {em['NOx_kg']:.4f}", em['NOx_kg'] > 0)
    check_true(f"SO₂ > 0: {em['SO2_kg']:.4f}", em['SO2_kg'] > 0)
    check_range("fuel/Nm", mt['fuel_per_nm_kg'], 5.0, 12.0)

    # ═══════════════════════════════════════════════════════
    # 11. B738 → MOTOR EŞLEŞMESİ
    # ═══════════════════════════════════════════════════════
    print("\n  [11] B738 → Motor Eşleşmesi")

    check_true(
        f"B738 → CFM56-7B26: {result['details']['engine_type']}",
        result['details']['engine_type'] == 'CFM56-7B26'
    )

    # ═══════════════════════════════════════════════════════
    # 12. A350 → MOTOR EŞLEŞMESİ
    # ═══════════════════════════════════════════════════════
    print("\n  [12] A350 → Motor Eşleşmesi")

    result_a350 = calc.calculate_flight_emissions(
        fuel_burn_kg=20000,
        distance_nm=2000,
        aircraft_type='A350',
    )
    check_true(
        f"A350 → Trent XWB-84: {result_a350['details']['engine_type']}",
        result_a350['details']['engine_type'] == 'Trent XWB-84'
    )

    # B77W → GE90
    result_777 = calc.calculate_flight_emissions(
        fuel_burn_kg=42000,
        distance_nm=1550,
        aircraft_type='B77W',
    )
    check_true(
        f"B77W → GE90-115B: {result_777['details']['engine_type']}",
        result_777['details']['engine_type'] == 'GE90-115B'
    )

    # ═══════════════════════════════════════════════════════
    # 13. CO₂/PAX/KM
    # ═══════════════════════════════════════════════════════
    print("\n  [13] CO₂/pax/km")

    check_range("CO₂/pax/km (g)", mt['co2_per_pax_km_g'], 50.0, 200.0)

    # ═══════════════════════════════════════════════════════
    # 14. FUEL/NM METRİĞİ
    # ═══════════════════════════════════════════════════════
    print("\n  [14] Fuel/Nm Metriği")

    expected_fuel_nm = 12500 / 1560
    check("fuel/Nm", mt['fuel_per_nm_kg'], expected_fuel_nm, 0.01)

    # ═══════════════════════════════════════════════════════
    # 15. CO₂ TUTARLILIK (FUEL × 3.16)
    # ═══════════════════════════════════════════════════════
    print("\n  [15] CO₂ Tutarlılık")

    expected_co2 = 12500 * 3.16
    check("CO₂ = fuel × 3.16", em['CO2_kg'], expected_co2, 1.0)

    # CO₂ oranı sabit olmalı
    for fuel_kg in [5000, 10000, 20000]:
        res = calc.calculate_flight_emissions(fuel_kg, 1000)
        expected = fuel_kg * 3.16
        diff_pct = abs(res['emissions']['CO2_kg'] - expected) / expected * 100

        check_true(
            f"CO₂ oranı sabit @ {fuel_kg}kg: {diff_pct:.3f}% fark",
            diff_pct < 0.01
        )

    # ═══════════════════════════════════════════════════════
    # 16. CONTRAİL — YÜKSEK İRTİFA (OLUŞMALI)
    # ═══════════════════════════════════════════════════════
    print("\n  [16] Contrail — Yüksek İrtifa")

    contrail_high = calc.schmidt_appleman_criterion(41000)
    check_true(
        f"FL410 contrail oluşuyor: T={contrail_high['temperature_C']:.1f}°C",
        contrail_high['contrail_formation_likely']
    )
    check_true(
        "'contrail_formation_likely' alanı var",
        'contrail_formation_likely' in contrail_high
    )
    check_true(
        "'recommendation' alanı var",
        'recommendation' in contrail_high
    )

    # ═══════════════════════════════════════════════════════
    # 17. CONTRAİL — ALÇAK İRTİFA (OLUŞMAMALI)
    # ═══════════════════════════════════════════════════════
    print("\n  [17] Contrail — Alçak İrtifa")

    contrail_low = calc.schmidt_appleman_criterion(20000)
    check_true(
        f"FL200 contrail oluşmuyor: T={contrail_low['temperature_C']:.1f}°C",
        not contrail_low['contrail_formation_likely']
    )

    # ═══════════════════════════════════════════════════════
    # 18. CONTRAİL — PERSISTENT KONTROLÜ
    # ═══════════════════════════════════════════════════════
    print("\n  [18] Contrail — Persistent Kontrolü")

    contrail_dry = calc.schmidt_appleman_criterion(41000, relative_humidity=0.2)
    contrail_wet = calc.schmidt_appleman_criterion(41000, relative_humidity=0.9)

    check_true(
        f"Nem > 0.7 → persistent kontrolü yapılıyor",
        'contrail_persistent' in contrail_wet
    )

    # ═══════════════════════════════════════════════════════
    # 18b. [SA] MOTOR VERİMİ ETKİSİ — denetim #41 regresyonu
    # ═══════════════════════════════════════════════════════
    print("\n  [18b] [SA] Motor verimi contrail eşiğini kaydırmalı")

    # DENETİM #41: engine_efficiency parametresi HİÇ kullanılmıyordu
    # (0.20 ile 0.55 aynı sonucu veriyordu). Ayrıca fonksiyon "tam
    # Schmidt-Appleman" değildir — eşik tabanlı yaklaşımdır ve
    # docstring artık bunu söylüyor. Bu testler verim etkisini kilitler.

    # (a) Sınır sıcaklığında verim sonucu DEĞİŞTİRMELİ
    _sa_low  = calc.schmidt_appleman_criterion(35000, -42.0, 0.5, 0.20)
    _sa_high = calc.schmidt_appleman_criterion(35000, -42.0, 0.5, 0.50)
    check_true(
        f"SA verim etkisi: eta=0.20 contrail={_sa_low['contrail_formation_likely']} "
        f"≠ eta=0.50 contrail={_sa_high['contrail_formation_likely']}",
        _sa_low['contrail_formation_likely'] != _sa_high['contrail_formation_likely']
    )

    # (b) Yön doğru: yüksek verim → egzoz daha az ısı → contrail daha kolay
    check_true(
        f"SA yüksek verimde contrail daha kolay "
        f"(eta 0.50 → {_sa_high['contrail_formation_likely']})",
        _sa_high['contrail_formation_likely'] is True
    )

    # (c) Çok soğukta verim fark etmez — hep contrail
    _sa_cold_low  = calc.schmidt_appleman_criterion(35000, -60.0, 0.5, 0.20)
    _sa_cold_high = calc.schmidt_appleman_criterion(35000, -60.0, 0.5, 0.50)
    check_true(
        "SA -60°C'de verimden bağımsız contrail",
        _sa_cold_low['contrail_formation_likely']
        and _sa_cold_high['contrail_formation_likely']
    )

    # (d) Sıcak havada verim yüksek olsa bile contrail yok
    _sa_warm = calc.schmidt_appleman_criterion(35000, -20.0, 0.9, 0.50)
    check_true(
        f"SA -20°C'de contrail yok (T={_sa_warm['temperature_C']})",
        not _sa_warm['contrail_formation_likely']
    )

    # ═══════════════════════════════════════════════════════
    # 19. SAF — TEMEL (%6 HEFA)
    # ═══════════════════════════════════════════════════════
    print("\n  [19] SAF — Temel (%6 HEFA)")

    saf = calc.calculate_saf_impact(12500, saf_blend_pct=6, saf_type='HEFA')

    check_range("SAF CO₂ azaltım %", saf['co2_reduction_pct'], 1.0, 10.0)
    check_true(f"Net benefit hesaplandı", 'net_benefit_usd' in saf)

    # ═══════════════════════════════════════════════════════
    # 19b. [SAF] ANAHTAR NORMALİZASYONU — denetim #42 regresyonu
    # ═══════════════════════════════════════════════════════
    print("\n  [19b] [SAF] Tip adı normalizasyonu + bilinmeyen tip")

    # DENETİM #42: Tabloda 'FT_SPK' var, docstring 'FT-SPK' yazıyordu.
    # `.get(x, 0.72)` SESSİZCE HEFA'ya düşüyordu → %90 yerine %72
    # azaltım, hiç uyarı yok. Bu test üç yazımı da kilitler.

    _ft_canon = calc.calculate_saf_impact(10000, 50, 'FT_SPK')
    check("SAF FT_SPK kanonik factor", _ft_canon['reduction_factor'], 0.90, 0.001)

    for _spelling in ('FT-SPK', 'FT SPK', 'ft-spk', 'Ft_Spk'):
        _r = calc.calculate_saf_impact(10000, 50, _spelling)
        check_true(
            f"SAF {_spelling!r} → 0.90 (normalize edildi: "
            f"{_r['reduction_factor']})",
            abs(_r['reduction_factor'] - 0.90) < 0.001
        )

    # Bilinmeyen tip SESSİZCE kabul edilmemeli
    _raised = False
    try:
        calc.calculate_saf_impact(10000, 50, 'SAÇMA_TİP_XYZ')
    except ValueError:
        _raised = True
    check_true("SAF bilinmeyen tip ValueError veriyor", _raised)

    # Azaltım yüzdesi = blend × reduction_factor (kütle bazlı)
    # %50 × 0.90 = %45.0 ; %50 × 0.72 = %36.0
    check("SAF FT_SPK %50 blend azaltım", _ft_canon['co2_reduction_pct'], 45.0, 0.05)
    _hefa = calc.calculate_saf_impact(10000, 50, 'HEFA')
    check("SAF HEFA %50 blend azaltım", _hefa['co2_reduction_pct'], 36.0, 0.05)

    # ═══════════════════════════════════════════════════════
    # 20. SAF — MİKTAR DOĞRULAMA
    # ═══════════════════════════════════════════════════════
    print("\n  [20] SAF — Miktar Doğrulama")

    # 12500 × 6% = 750 kg SAF
    check("SAF yakıt miktarı", saf['saf_fuel_kg'], 750, 1.0)

    # Yanma CO₂ sabit (3.16)
    expected_combustion = 12500 * 3.16
    check("Yanma CO₂", saf['combustion_co2_kg'], expected_combustion, 1.0)

    # Lifecycle CO₂ < Yanma CO₂ (SAF fayda sağlıyor)
    check_true(
        f"Lifecycle CO₂({saf['lifecycle_co2_kg']:.0f}) < Combustion CO₂({saf['combustion_co2_kg']:.0f})",
        saf['lifecycle_co2_kg'] < saf['combustion_co2_kg']
    )

    # ═══════════════════════════════════════════════════════
    # 21. SAF — CO₂ AZARIM POZİTİF
    # ═══════════════════════════════════════════════════════
    print("\n  [21] SAF — CO₂ Azaltımı Pozitif")

    check_true(f"CO₂ azaltım > 0: {saf['co2_reduction_kg']}", saf['co2_reduction_kg'] > 0)
    check_true(f"CO₂ azaltım % > 0: {saf['co2_reduction_pct']}", saf['co2_reduction_pct'] > 0)

    # Matematiksel tutarlılık
    check_true(
        f"combustion = lifecycle + reduction: {saf['combustion_co2_kg']:.0f} ≈ "
        f"{saf['lifecycle_co2_kg'] + saf['co2_reduction_kg']:.0f}",
        abs(saf['combustion_co2_kg'] - saf['lifecycle_co2_kg'] - saf['co2_reduction_kg']) < 1
    )

    # ═══════════════════════════════════════════════════════
    # 22. SAF — EU MANDATE İÇERİĞİ
    # ═══════════════════════════════════════════════════════
    print("\n  [22] SAF — EU Mandate")

    mandate = saf.get('eu_mandate', {})
    check_true("'2025' var", '2025' in mandate)
    check_true("'2030' var", '2030' in mandate)
    check_true("'2050' var", '2050' in mandate)

    # 2025: %2, 2050: %70
    check_true(
        f"2025 mandate: {mandate.get('2025', '')}",
        '2%' in mandate.get('2025', '')
    )
    check_true(
        f"2050 mandate: {mandate.get('2050', '')}",
        '70%' in mandate.get('2050', '')
    )

    # ═══════════════════════════════════════════════════════
    # 23. SAF — FARKLI TİPLER
    # ═══════════════════════════════════════════════════════
    print("\n  [23] SAF — Farklı Tipler")

    saf_types = {
        'HEFA'  : (0.60, 0.80),
        'FT_SPK': (0.82, 0.96),
        'ATJ'   : (0.50, 0.75),
        'PTL'   : (0.85, 0.97),
    }

    for saf_type, (lo, hi) in saf_types.items():
        saf_t = calc.calculate_saf_impact(10000, 10, saf_type)
        check_range(
            f"{saf_type} reduction_factor",
            saf_t['reduction_factor'],
            lo,
            hi,
        )
        check_true(
            f"{saf_type} CO₂ azaltım > 0",
            saf_t['co2_reduction_kg'] > 0
        )

    # FT_SPK en yüksek azaltım
    saf_hefa   = calc.calculate_saf_impact(10000, 10, 'HEFA')
    saf_ft     = calc.calculate_saf_impact(10000, 10, 'FT_SPK')
    check_true(
        f"FT_SPK({saf_ft['co2_reduction_pct']:.1f}%) > HEFA({saf_hefa['co2_reduction_pct']:.1f}%)",
        saf_ft['co2_reduction_pct'] > saf_hefa['co2_reduction_pct']
    )

    # ═══════════════════════════════════════════════════════
    # 24. SAF — %0 = SIFIR AZARIM
    # ═══════════════════════════════════════════════════════
    print("\n  [24] SAF — %0 Blend")

    saf_zero = calc.calculate_saf_impact(12500, saf_blend_pct=0)
    check("SAF %0: azaltım", saf_zero['co2_reduction_kg'], 0.0, 0.01)
    check("SAF %0: pct", saf_zero['co2_reduction_pct'], 0.0, 0.01)
    check("SAF %0: yakıt", saf_zero['saf_fuel_kg'], 0, 0.01)

    # ═══════════════════════════════════════════════════════
    # 25. CORSIA MONITORING — TEMEL
    # ═══════════════════════════════════════════════════════
    print("\n  [25] CORSIA Monitoring — Temel")

    flights_data = [
        {'flight_number': 'TK1985', 'date': '2025-01-15',
         'origin': 'LTFM', 'destination': 'EGLL',
         'fuel_kg': 12500, 'aircraft_type': 'B738'},
        {'flight_number': 'TK1986', 'date': '2025-01-15',
         'origin': 'EGLL', 'destination': 'LTFM',
         'fuel_kg': 11800, 'aircraft_type': 'B738'},
        {'flight_number': 'TK1721', 'date': '2025-01-16',
         'origin': 'LTFM', 'destination': 'EDDF',
         'fuel_kg': 8500, 'aircraft_type': 'A320'},
    ]

    monitoring = calc.corsia_compliance.monitoring_report(flights_data)
    check("Monitoring toplam uçuş", monitoring['total_flights'], 3, 0.01)
    check_true(
        "'Method B' metodu",
        'Method B' in monitoring['method']
    )

    # ═══════════════════════════════════════════════════════
    # 26. CORSIA MONITORING — CO₂ HESABI
    # ═══════════════════════════════════════════════════════
    print("\n  [26] CORSIA Monitoring — CO₂")

    total_fuel_expected = 12500 + 11800 + 8500
    check("Monitoring toplam yakıt", monitoring['total_fuel_kg'], total_fuel_expected, 1.0)

    expected_co2 = total_fuel_expected * 3.16
    check("Monitoring toplam CO₂", monitoring['total_co2_kg'], expected_co2, 10.0)

    # Her kayıt CO₂ içeriyor mu?
    records = monitoring.get('records', [])
    check_true(
        f"{len(records)} kayıt var",
        len(records) == 3
    )
    check_true(
        "Her kayıtta co2_kg var",
        all('co2_kg' in r for r in records)
    )
    check_true(
        "Her kayıtta quality_flag var",
        all('quality_flag' in r for r in records)
    )

    # ═══════════════════════════════════════════════════════
    # 26b. [CORSIA] BOZUK VERİ — denetim #44/#45 regresyonu
    # ═══════════════════════════════════════════════════════
    print("\n  [26b] [CORSIA] Bozuk veri reddedilmeli, çökmemeli")

    # DENETİM #44: fuel_kg='abc' → TypeError; -500 → toplama
    # giriyordu; eksik → sessizce 0. DENETİM #45: rapor
    # "2 uçuş" diyor ama yakıt 1 uçuşluk, fark görünmüyordu.

    _dirty = [
        {'flight_number': 'OK1',  'date': '2024-01-01', 'fuel_kg': 12000},
        {'flight_number': 'STR1', 'date': '2024-01-02', 'fuel_kg': 'abc'},
        {'flight_number': 'NEG1', 'date': '2024-01-03', 'fuel_kg': -500},
        {'flight_number': 'MISS1'},
        {'flight_number': 'HUGE1','date': '2024-01-05', 'fuel_kg': 900000},
    ]

    _mon = calc.corsia_compliance.monitoring_report(_dirty)

    # Çökmemeli ve yalnız geçerli kaydı saymalı
    check("CORSIA bozuk veri: doğrulanmış kayıt", _mon['verified_flights'], 1, 0.01)
    check("CORSIA bozuk veri: reddedilen kayıt", _mon['rejected_flights'], 4, 0.01)
    check("CORSIA bozuk veri: yakıt yalnız geçerli", _mon['total_fuel_kg'], 12000, 1.0)
    check("CORSIA bozuk veri: toplam kayıt", _mon['total_flights'], 5, 0.01)

    # Reddetme nedenleri görünmeli
    _reasons = {r['flight_id']: r['reason'] for r in _mon['rejection_details']}
    check_true(f"CORSIA 'abc' → MISSING ({_reasons.get('STR1')})",
               _reasons.get('STR1') == 'MISSING')
    check_true(f"CORSIA -500 → INVALID ({_reasons.get('NEG1')})",
               'INVALID' in str(_reasons.get('NEG1')))
    check_true(f"CORSIA 900t → SUSPECT ({_reasons.get('HUGE1')})",
               'SUSPECT' in str(_reasons.get('HUGE1')))

    # Raporda düşen kayıt sayısı AÇIKÇA yazmalı
    _rep = calc.corsia_compliance.reporting_document(_mon, 'Test Air', 2024)
    check("CORSIA raporda verified_flights", _rep['emissions']['verified_flights'], 1, 0.01)
    check("CORSIA raporda rejected_flights", _rep['emissions']['rejected_flights'], 4, 0.01)
    check_true(
        "CORSIA raporda veri kalitesi notu var",
        'reddedildi' in _rep['emissions']['data_quality_note']
    )

    # Temiz veride rejected = 0, note nötr olmalı
    _clean = calc.corsia_compliance.monitoring_report(
        [{'flight_number': 'C1', 'date': '2024-01-01', 'fuel_kg': 5000}]
    )
    check("CORSIA temiz veri: rejected 0", _clean['rejected_flights'], 0, 0.01)
    _rep_clean = calc.corsia_compliance.reporting_document(_clean, 'Test', 2024)
    check_true(
        "CORSIA temiz veride not nötr",
        'Tüm kayıtlar doğrulandı' in _rep_clean['emissions']['data_quality_note']
    )

    # ═══════════════════════════════════════════════════════
    # 27. CORSIA REPORTING_DOCUMENT
    # ═══════════════════════════════════════════════════════
    print("\n  [27] CORSIA Reporting Document")

    report = calc.corsia_compliance.reporting_document(
        monitoring, 'Test Airlines', 2025
    )

    check_true(
        f"report_type: {report.get('report_type', '')}",
        report.get('report_type') == 'CORSIA Annual Emission Report'
    )
    check_true(
        f"standard: {report.get('standard', '')}",
        'Annex 16' in report.get('standard', '')
    )
    check_true(
        "emissions bölümü var",
        'emissions' in report
    )
    check_true(
        "corsia_compliance bölümü var",
        'corsia_compliance' in report
    )
    check_true(
        "verification_status bölümü var",
        'verification_status' in report
    )

    # Offset non-negative
    offset = report['corsia_compliance'].get('offset_required_tonnes', -1)
    check_true(f"Offset ≥ 0: {offset}", offset >= 0)

    # CO₂ raporda doğru
    total_co2_report = report['emissions'].get('total_co2_tonnes', 0)
    check_range(
        f"Rapor CO₂ (ton)",
        total_co2_report,
        expected_co2 / 1000 * 0.9,
        expected_co2 / 1000 * 1.1,
    )

    # ═══════════════════════════════════════════════════════
    # 28. CORSIA VERIFICATION_CHECKLIST
    # ═══════════════════════════════════════════════════════
    print("\n  [28] CORSIA Verification Checklist")

    checklist = CORSIACompliance.verification_checklist()

    check_true(
        "'checklist' alanı var",
        'checklist' in checklist
    )
    check_true(
        f"En az 5 madde: {len(checklist['checklist'])}",
        len(checklist['checklist']) >= 5
    )
    check_true(
        "'verification_type' var",
        'verification_type' in checklist
    )

    # Her madde zorunlu alanları içeriyor mu?
    for item in checklist['checklist']:
        check_true(
            f"Madde '{item.get('item', '?')}' gerekli alanlara sahip",
            all(k in item for k in ['item', 'requirement', 'status'])
        )

    # ═══════════════════════════════════════════════════════
    # 29. GET_ENGINE_FOR_AIRCRAFT
    # ═══════════════════════════════════════════════════════
    print("\n  [29] get_engine_for_aircraft")

    engine_map = {
        'B738': 'CFM56-7B26',
        'A350': 'Trent XWB-84',
        'B77W': 'GE90-115B',
        'B38M': 'LEAP-1B',
        'A20N': 'LEAP-1A',
    }

    for ac_type, expected_engine in engine_map.items():
        engine = calc.get_engine_for_aircraft(ac_type)
        check_true(
            f"{ac_type} → {expected_engine}: {engine}",
            engine == expected_engine
        )

    # ═══════════════════════════════════════════════════════
    # 30. GET_AVAILABLE_ENGINES
    # ═══════════════════════════════════════════════════════
    print("\n  [30] get_available_engines")

    engines = calc.get_available_engines()
    check_true(
        f"En az 8 motor tipi: {len(engines)}",
        len(engines) >= 8
    )
    check_true("CFM56-7B26 listede", 'CFM56-7B26' in engines)
    check_true("LEAP-1B listede", 'LEAP-1B' in engines)
    check_true("GE90-115B listede", 'GE90-115B' in engines)
    check_true("Trent XWB-84 listede", 'Trent XWB-84' in engines)

    # ═══════════════════════════════════════════════════════
    # 31. GET_AVAILABLE_SAF_TYPES
    # ═══════════════════════════════════════════════════════
    print("\n  [31] get_available_saf_types")

    saf_types_dict = calc.get_available_saf_types()
    check_true(
        f"En az 4 SAF tipi: {len(saf_types_dict)}",
        len(saf_types_dict) >= 4
    )
    check_true("HEFA var", 'HEFA' in saf_types_dict)
    check_true("FT_SPK var", 'FT_SPK' in saf_types_dict)
    check_true("ATJ var", 'ATJ' in saf_types_dict)

    # Tüm değerler 0-1 arası
    for saf_type, factor in saf_types_dict.items():
        check_range(f"{saf_type} factor", factor, 0.0, 1.0)

    # ═══════════════════════════════════════════════════════
    # 32. GET_ENGINE_INFO
    # ═══════════════════════════════════════════════════════
    print("\n  [32] get_engine_info")

    info_ge90 = calc.get_engine_info('GE90-115B')
    check_true("GE90-115B bilgisi var", info_ge90 is not None)
    if info_ge90:
        check_true(
            f"GE90 manufacturer: {info_ge90.get('manufacturer', '')}",
            info_ge90.get('manufacturer') == 'GE Aviation'
        )
        check_true(
            f"GE90 BPR: {info_ge90.get('bypass_ratio', 0)}",
            info_ge90.get('bypass_ratio', 0) > 5
        )
        check_true(
            "'ei_nox' var",
            'ei_nox' in info_ge90
        )

    info_leap = calc.get_engine_info('LEAP-1B')
    check_true("LEAP-1B bilgisi var", info_leap is not None)
    if info_leap:
        check_true(
            f"LEAP-1B BPR: {info_leap.get('bypass_ratio', 0)} > GE90: {info_ge90.get('bypass_ratio', 0) if info_ge90 else 0}",
            info_leap.get('bypass_ratio', 0) > 5
        )

    # ═══════════════════════════════════════════════════════
    # 33. BİLİNMEYEN MOTOR — NONE
    # ═══════════════════════════════════════════════════════
    print("\n  [33] Bilinmeyen Motor — None")

    info_unknown = calc.get_engine_info('BILINMEYEN_XYZ')
    check_true("Bilinmeyen motor → None", info_unknown is None)

    # Bilinmeyen uçak tipi → default motor
    engine_unknown = calc.get_engine_for_aircraft('BILINMEYEN_AC')
    check_true(
        f"Bilinmeyen AC → fallback motor: {engine_unknown}",
        len(engine_unknown) > 0
    )

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
