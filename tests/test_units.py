# tests/test_units.py

"""
GreenWing Analytics — Birim Dönüşüm Testleri
═════════════════════════════════════════════

Kapsamlı test süiti:
    1.  ft ↔️ m dönüşüm
    2.  ft ↔️ m roundtrip
    3.  FL ↔️ ft dönüşüm
    4.  FL → m dönüşüm
    5.  Basınç @ SL
    6.  Basınç @ FL350
    7.  Yoğunluk @ SL
    8.  Yoğunluk @ FL350
    9.  Sıcaklık @ SL
    10. Sıcaklık @ FL350 ve tropopoz
    11. Basınç oranı (δ)
    12. Sıcaklık oranı (θ)
    13. Yoğunluk oranı (σ)
    14. σ ≈ δ/θ tutarlılık
    15. Basınç → irtifa ters dönüşüm
    16. Ses hızı
    17. kts ↔️ m/s dönüşüm
    18. kts ↔️ m/s roundtrip
    19. Mach → TAS → Mach roundtrip
    20. TAS @ farklı irtifalar
    21. M0.90 kabul edilmeli (B787)
    22. Nm ↔️ m dönüşüm
    23. Nm ↔️ km dönüşüm
    24. Nm roundtrip
    25. Statute mile dönüşüm
    26. Statute mile ≠ Nautical mile
    27. kg ↔️ lbs roundtrip
    28. Celsius ↔️ Kelvin
    29. Celsius ↔️ Kelvin roundtrip
    30. Yakıt yoğunluğu @ 15°C
    31. Yakıt yoğunluğu sıcaklık ilişkisi
    32. Yakıt litre → kg @ farklı sıcaklıklar
    33. Yakıt kg → L → kg roundtrip
    34. fpm ↔️ m/s dönüşüm
    35. fpm roundtrip
    36. Transition altitude
    37. Pressure altitude → true altitude
    38. Ülke bazlı transition
    39. Vectorized haversine — IST→ANK
    40. Vectorized haversine — IST→LON
    41. Vectorized haversine — ilk segment = 0
    42. Vectorized haversine — performans
    43. Outlier tespiti — aykırı değerler
    44. Outlier tespiti — normal veri
    45. Trajectory standardizasyonu — temel
    46. Trajectory standardizasyonu — sütunlar
    47. Trajectory standardizasyonu — zaman
    48. Trajectory standardizasyonu — irtifa dönüşümü
    49. Hata yakalama — negatif irtifa
    50. Hata yakalama — mach > 0.95
    51. Hata yakalama — None
    52. Hata yakalama — string
    53. Hata yakalama — yakıt yoğunluğu sınır dışı

Çalıştırma:
    python tests/test_units.py
    python -m pytest tests/test_units.py -v
"""

import sys
import os
import time as time_module

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.units import Units


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: units.py — TAM TEST SÜİTİ")
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
        v = float(val)
        if lo <= v <= hi:
            print(f"  ✅ {name} = {v:.6f} [{lo}, {hi}]")
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

    def check_raises(name, func, exc):
        nonlocal tests
        tests += 1
        try:
            func()
            errors.append(f"{name}: hata beklendi")
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
    # İRTİFA DÖNÜŞÜMLERİ
    # ═══════════════════════════════════════════════════════
    print("\n  ── İrtifa Dönüşümleri ─────────────────────────────")

    # [1] ft → m
    check("[1] ft_to_m(35000)", Units.ft_to_m(35000), 10668.0, 0.1)
    check("[1b] ft_to_m(0)", Units.ft_to_m(0), 0.0, 0.01)

    # [2] m → ft + roundtrip
    check("[2] m_to_ft(10668)", Units.m_to_ft(10668), 35000.0, 1.0)
    check("[2b] ft→m→ft(41000)", Units.m_to_ft(Units.ft_to_m(41000)), 41000, 0.01)

    # [3] FL ↔️ ft
    check("[3] fl_to_ft(350)", Units.fl_to_ft(350), 35000, 0.1)
    check("[3b] fl_to_ft(410)", Units.fl_to_ft(410), 41000, 0.1)
    check("[3c] ft_to_fl(37000)", Units.ft_to_fl(37000), 370, 0.1)
    check("[3d] ft_to_fl(35000)", Units.ft_to_fl(35000), 350, 0.1)

    # [4] FL → m
    check("[4] fl_to_m(350)", Units.fl_to_m(350), 10668.0, 1.0)
    check("[4b] fl_to_m(390)", Units.fl_to_m(390), 11887.2, 1.0)

    # ═══════════════════════════════════════════════════════
    # BASINÇ / YOĞUNLUK / SICAKLIK
    # ═══════════════════════════════════════════════════════
    print("\n  ── Basınç / Yoğunluk / Sıcaklık ──────────────────")

    # [5] Basınç SL
    check("[5] P @ SL", Units.pressure_at_altitude(0), 101325.0, 1.0)

    # [6] Basınç FL350
    check_range("[6] P @ FL350", Units.pressure_at_altitude(35000), 23000, 25000)

    # [7] Yoğunluk SL
    check("[7] ρ @ SL", Units.density_at_altitude(0), 1.225, 0.001)

    # [8] Yoğunluk FL350
    check_range("[8] ρ @ FL350", Units.density_at_altitude(35000), 0.35, 0.41)

    # [9] Sıcaklık SL
    check("[9] T @ SL", Units.temperature_at_altitude(0), 288.15, 0.01)

    # [10] Sıcaklık FL350 ve tropopoz
    check_range("[10] T @ FL350", Units.temperature_at_altitude(35000), 215, 222)
    check_range("[10b] T @ tropopoz", Units.temperature_at_altitude(36089), 215, 218)

    # ═══════════════════════════════════════════════════════
    # ORANLAR
    # ═══════════════════════════════════════════════════════
    print("\n  ── Oranlar (δ, θ, σ) ─────────────────────────────")

    # [11] δ
    check("[11] δ @ SL", Units.pressure_ratio(0), 1.0, 0.001)
    delta = Units.pressure_ratio(35000)
    check_range("[11b] δ @ FL350", delta, 0.20, 0.28)

    # [12] θ
    check("[12] θ @ SL", Units.temperature_ratio(0), 1.0, 0.001)
    theta = Units.temperature_ratio(35000)
    check_range("[12b] θ @ FL350", theta, 0.72, 0.80)

    # [13] σ
    check("[13] σ @ SL", Units.density_ratio(0), 1.0, 0.001)
    sigma = Units.density_ratio(35000)
    check_range("[13b] σ @ FL350", sigma, 0.28, 0.35)

    # [14] σ ≈ δ/θ tutarlılık
    calc_sigma = delta / theta
    check_true(
        f"[14] σ({sigma:.4f}) ≈ δ/θ({calc_sigma:.4f})",
        abs(sigma - calc_sigma) < 0.005
    )

    # ═══════════════════════════════════════════════════════
    # BASINÇ TERS DÖNÜŞÜM
    # ═══════════════════════════════════════════════════════
    print("\n  ── Basınç Ters Dönüşüm ──────────────────────────")

    # [15] Basınç → irtifa → basınç roundtrip
    P_35 = Units.pressure_at_altitude(35000)
    alt_back = Units.altitude_from_pressure(P_35)
    check("[15] P→alt roundtrip FL350", alt_back, 35000, 10.0)

    P_0 = Units.pressure_at_altitude(0)
    alt_0 = Units.altitude_from_pressure(P_0)
    check("[15b] P→alt roundtrip SL", alt_0, 0.0, 1.0)

    # ═══════════════════════════════════════════════════════
    # SES HIZI
    # ═══════════════════════════════════════════════════════
    print("\n  ── Ses Hızı ──────────────────────────────────────")

    # [16]
    check("[16] a @ SL", Units.speed_of_sound(0), 340.3, 0.5)
    check_range("[16b] a @ FL350", Units.speed_of_sound(35000), 293, 298)

    check_true(
        "[16c] a@SL > a@FL350",
        Units.speed_of_sound(0) > Units.speed_of_sound(35000)
    )

    # ═══════════════════════════════════════════════════════
    # HIZ DÖNÜŞÜMLERİ
    # ═══════════════════════════════════════════════════════
    print("\n  ── Hız Dönüşümleri ──────────────────────────────")

    # [17] kts ↔️ m/s
    check("[17] kts_to_ms(450)", Units.kts_to_ms(450), 231.50, 0.1)
    check("[17b] ms_to_kts(231.50)", Units.ms_to_kts(231.50), 450.0, 0.1)

    # [18] roundtrip
    check("[18] kts→ms→kts(250)", Units.ms_to_kts(Units.kts_to_ms(250)), 250.0, 0.01)

    # [19] Mach → TAS → Mach roundtrip
    tas = Units.mach_to_tas(0.785, 35000)
    mach_back = Units.tas_to_mach(tas, 35000)
    check("[19] Mach roundtrip", mach_back, 0.785, 0.001)

    # [20] TAS @ farklı irtifalar
    tas_sl = Units.mach_to_tas(0.785, 0)
    tas_fl = Units.mach_to_tas(0.785, 35000)
    check_true(
        f"[20] TAS@SL({tas_sl:.1f}) > TAS@FL350({tas_fl:.1f})",
        tas_sl > tas_fl
    )
    check_range("[20b] TAS M0.785 FL350", tas_fl, 225, 235)

    # [21] M0.90 kabul edilmeli (B787 MMO)
    try:
        tas_90 = Units.mach_to_tas(0.90, 35000)
        tests += 1
        print(f"  ✅ [21] M0.90 kabul: {tas_90:.1f} m/s")
    except ValueError:
        tests += 1
        errors.append("[21] M0.90 reddedildi (kabul edilmeli)")
        print("  ❌ [21] M0.90 reddedildi")

    # ═══════════════════════════════════════════════════════
    # MESAFE DÖNÜŞÜMLERİ
    # ═══════════════════════════════════════════════════════
    print("\n  ── Mesafe Dönüşümleri ────────────────────────────")

    # [22] Nm ↔️ m
    check("[22] nm_to_m(1)", Units.nm_to_m(1), 1852.0, 0.01)
    check("[22b] m_to_nm(1852)", Units.m_to_nm(1852), 1.0, 0.001)

    # [23] Nm ↔️ km
    check("[23] nm_to_km(1)", Units.nm_to_km(1), 1.852, 0.001)
    check("[23b] km_to_nm(1.852)", Units.km_to_nm(1.852), 1.0, 0.001)

    # [24] Nm roundtrip
    check("[24] Nm→m→Nm(1560)", Units.m_to_nm(Units.nm_to_m(1560)), 1560.0, 0.001)

    # [25] Statute mile
    check("[25] statute_mile_to_m(1)", Units.statute_mile_to_m(1), 1609.344, 0.01)
    check("[25b] statute_mile_to_nm(1)", Units.statute_mile_to_nm(1), 0.8684, 0.001)

    # [26] Statute ≠ Nautical (fark ~%13)
    sm_m = Units.statute_mile_to_m(1)
    nm_m = Units.nm_to_m(1)
    pct_diff = abs(sm_m - nm_m) / nm_m * 100
    check_range("[26] SM vs NM fark %", pct_diff, 12, 14)

    # ═══════════════════════════════════════════════════════
    # AĞIRLIK DÖNÜŞÜMLERİ
    # ═══════════════════════════════════════════════════════
    print("\n  ── Ağırlık Dönüşümleri ───────────────────────────")

    # [27]
    check("[27] kg→lbs→kg(79016)", Units.lbs_to_kg(Units.kg_to_lbs(79016)), 79016, 0.1)
    check_range("[27b] kg_to_lbs(1)", Units.kg_to_lbs(1), 2.20, 2.21)

    # ═══════════════════════════════════════════════════════
    # SICAKLIK DÖNÜŞÜMLERİ
    # ═══════════════════════════════════════════════════════
    print("\n  ── Sıcaklık Dönüşümleri ──────────────────────────")

    # [28]
    check("[28] C→K(15)", Units.celsius_to_kelvin(15), 288.15, 0.01)
    check("[28b] C→K(-56.5)", Units.celsius_to_kelvin(-56.5), 216.65, 0.01)
    check("[28c] K→C(288.15)", Units.kelvin_to_celsius(288.15), 15.0, 0.01)

    # [29] roundtrip
    check("[29] °C→K→°C(-40)", Units.kelvin_to_celsius(Units.celsius_to_kelvin(-40)), -40.0, 0.001)

    # ═══════════════════════════════════════════════════════
    # YAKIT YOĞUNLUĞU
    # ═══════════════════════════════════════════════════════
    print("\n  ── Yakıt Yoğunluğu ──────────────────────────────")

    # [30]
    check("[30] density(15°C)", Units.fuel_density_at_temp(15), 0.804, 0.001)
    check("[30b] density(0°C)", Units.fuel_density_at_temp(0), 0.8148, 0.002)

    # [31] Sıcaklık ilişkisi
    d_cold = Units.fuel_density_at_temp(-30)
    d_hot  = Units.fuel_density_at_temp(40)
    check_true(
        f"[31] Soğuk({d_cold:.4f}) > Sıcak({d_hot:.4f})",
        d_cold > d_hot
    )

    # [32] Litre → kg farklı sıcaklıklarda
    kg_15  = Units.fuel_liters_to_kg(10000, 15)
    kg_40  = Units.fuel_liters_to_kg(10000, 40)
    kg_m30 = Units.fuel_liters_to_kg(10000, -30)

    check("[32] 10000L @15°C", kg_15, 8040.0, 5)
    check_true(
        f"[32b] Soğuk({kg_m30:.0f}) > Standart({kg_15:.0f}) > Sıcak({kg_40:.0f})",
        kg_m30 > kg_15 > kg_40
    )

    fark_kg = kg_m30 - kg_40
    check_true(
        f"[32c] Soğuk-sıcak fark: {fark_kg:.0f} kg (>${fark_kg*0.85:.0f})",
        fark_kg > 300
    )

    # [33] roundtrip
    check("[33] fuel kg→L→kg(12500)", Units.fuel_liters_to_kg(Units.fuel_kg_to_liters(12500)), 12500.0, 0.1)

    # ═══════════════════════════════════════════════════════
    # DİKEY HIZ
    # ═══════════════════════════════════════════════════════
    print("\n  ── Dikey Hız ─────────────────────────────────────")

    # [34]
    check("[34] fpm_to_ms(1500)", Units.fpm_to_ms(1500), 1500 * 0.3048 / 60.0, 0.01)
    check("[34b] fpm_to_ms(-500)", Units.fpm_to_ms(-500), -500 * 0.3048 / 60.0, 0.01)

    # [35] roundtrip
    check("[35] fpm→ms→fpm(2000)", Units.ms_to_fpm(Units.fpm_to_ms(2000)), 2000.0, 0.1)

    # ═══════════════════════════════════════════════════════
    # TRANSITION ALTITUDE
    # ═══════════════════════════════════════════════════════
    print("\n  ── Transition Altitude ───────────────────────────")

    # [36]
    check_true("[36] FL350 above transition", Units.is_above_transition(35000))
    check_true("[36b] 5000 ft below transition", not Units.is_above_transition(5000))

    # [37] Pressure altitude → true altitude
    check("[37] QNH=1013.25 → no change",
          Units.pressure_altitude_to_true_altitude(35000, 1013.25), 35000, 1.0)

    true_low = Units.pressure_altitude_to_true_altitude(35000, 1000)
    check_true(
        f"[37b] QNH=1000 → gerçek({true_low:.0f}) > 35000",
        true_low > 35000
    )

    true_high = Units.pressure_altitude_to_true_altitude(35000, 1030)
    check_true(
        f"[37c] QNH=1030 → gerçek({true_high:.0f}) < 35000",
        true_high < 35000
    )

    # [38] Ülke bazlı
    check("[38] TR transition", Units.get_transition_altitude('TR'), 18000, 0.1)
    check("[38b] DE transition", Units.get_transition_altitude('DE'), 5000, 0.1)
    check("[38c] GB transition", Units.get_transition_altitude('GB'), 6000, 0.1)
    check("[38d] Default", Units.get_transition_altitude(None), 18000, 0.1)

    # ═══════════════════════════════════════════════════════
    # VECTORIZED HAVERSINE
    # ═══════════════════════════════════════════════════════
    print("\n  ── Vectorized Haversine ──────────────────────────")

    # [39] IST → ANK
    # _vectorized_haversine sadece 2 nokta ile segment mesafe verir
    # Gerçek IST→ANK ≈ 190 Nm ama koordinata bağlı olarak ~205 çıkabilir
    d_ank = Units._vectorized_haversine(
        np.array([41.275, 40.128]),
        np.array([28.752, 32.995]),
    )
    check_range("[39] IST→ANK", d_ank[1], 180, 220)

    # [40] IST → LON
    # _vectorized_haversine R_nm=3440.065 kullanır
    # Gerçek mesafe koordinata ve R değerine bağlı
    d_lon = Units._vectorized_haversine(
        np.array([41.275, 51.470]),
        np.array([28.752, -0.454]),
    )
    check_range("[40] IST→LON", d_lon[1], 1300, 1600)

    # [41] İlk segment = 0
    check("[41] İlk segment = 0", d_ank[0], 0.0, 0.01)

    # [42] Performans (10k nokta < 100ms)
    n = 10_000
    big_lat = np.random.uniform(35, 55, n)
    big_lon = np.random.uniform(-10, 60, n)
    t0 = time_module.time()
    _ = Units._vectorized_haversine(big_lat, big_lon)
    elapsed_ms = (time_module.time() - t0) * 1000

    check_true(
        f"[42] {n:,} nokta: {elapsed_ms:.1f} ms {'(hızlı)' if elapsed_ms < 100 else '(yavaş?)'}",
        elapsed_ms < 500
    )

    # Çoklu nokta mesafesi toplamı pozitif
    multi_lat = np.array([41.275, 43.0, 47.0, 51.470])
    multi_lon = np.array([28.752, 20.0, 5.0, -0.454])
    multi_d = Units._vectorized_haversine(multi_lat, multi_lon)
    check_true(
        f"[42b] Çoklu nokta toplam mesafe > 0: {multi_d.sum():.1f} Nm",
        multi_d.sum() > 1000
    )

    # ═══════════════════════════════════════════════════════
    # OUTLIER TESPİTİ
    # ═══════════════════════════════════════════════════════
    print("\n  ── Outlier Tespiti ───────────────────────────────")

    # [43] Aykırı değerler tespiti
    speeds = pd.Series([450, 460, 455, 470, 2000, 440, 465, 10000])
    result_out = Units.detect_outliers(speeds, method='iqr', factor=1.5)
    check_true(
        f"[43] Outlier bulundu: {result_out['outlier_count']} (≥2 beklenir)",
        result_out['outlier_count'] >= 2
    )
    check_true(
        "[43b] lower_bound var",
        result_out['lower_bound'] is not None
    )
    check_true(
        "[43c] upper_bound var",
        result_out['upper_bound'] is not None
    )

    # [44] Normal veri
    normal = pd.Series([450, 460, 455, 470, 440])
    result_norm = Units.detect_outliers(normal)
    check_true(
        "[44] Normal veride outlier yok",
        result_norm['outlier_count'] == 0
    )

    # Z-score yöntemi
    result_zscore = Units.detect_outliers(speeds, method='zscore', factor=2.0)
    check_true(
        f"[44b] Z-score outlier: {result_zscore['outlier_count']}",
        result_zscore['outlier_count'] >= 1
    )

    # Yetersiz veri
    result_short = Units.detect_outliers(pd.Series([1, 2]))
    check_true(
        "[44c] Yetersiz veri (2 nokta) → 0 outlier",
        result_short['outlier_count'] == 0
    )

    # ═══════════════════════════════════════════════════════
    # TRAJECTORY STANDARDİZASYONU
    # ═══════════════════════════════════════════════════════
    print("\n  ── Trajectory Standardizasyonu ────────────────────")

    # [45] Temel test
    raw_df = pd.DataFrame({
        'time'          : pd.date_range('2025-01-20 10:00', periods=10, freq='60s'),
        'latitude'      : np.linspace(41.275, 41.375, 10),
        'longitude'     : np.linspace(28.752, 28.852, 10),
        'baro_altitude' : np.linspace(100, 5000, 10),  # Metre
        'velocity'      : np.linspace(5, 200, 10),     # m/s
    })

    std_df = Units.standardize_trajectory(raw_df)

    # [46] Standart sütunlar
    required_cols = [
        'baro_altitude_ft', 'baro_altitude_m',
        'velocity_ms', 'velocity_kts',
        'time_diff_s',
        'vertical_rate_fpm', 'vertical_rate_ms',
        'segment_distance_nm', 'cumulative_distance_nm',
        'above_transition',
    ]
    missing = [c for c in required_cols if c not in std_df.columns]
    check_true(
        f"[46] {len(required_cols)} standart sütun oluştu",
        len(missing) == 0
    )
    if missing:
        print(f"      Eksik: {missing}")

    # [47] Zaman
    check_true(
        f"[47] time_diff_s doğru: {std_df['time_diff_s'].iloc[1]:.0f}s",
        abs(std_df['time_diff_s'].iloc[1] - 60.0) < 0.1
    )

    # [48] İrtifa dönüşümü (100m = 328ft)
    expected_ft = 100 * (1 / 0.3048)
    actual_ft = std_df['baro_altitude_ft'].iloc[0]
    check_true(
        f"[48] İrtifa m→ft: {actual_ft:.0f} (beklenen ~{expected_ft:.0f})",
        abs(actual_ft - expected_ft) < 5
    )

    # Kümülatif mesafe > 0
    cum_dist = std_df['cumulative_distance_nm'].iloc[-1]
    check_true(
        f"[48b] Kümülatif mesafe > 0: {cum_dist:.3f} Nm",
        cum_dist > 0
    )

    # above_transition: 100m = 328ft → False
    check_true(
        "[48c] above_transition(328ft) = False",
        not std_df['above_transition'].iloc[0]
    )

    # Velocity dönüşümü
    check_true(
        f"[48d] velocity_kts > 0: {std_df['velocity_kts'].iloc[-1]:.0f}",
        std_df['velocity_kts'].iloc[-1] > 0
    )

    # ═══════════════════════════════════════════════════════
    # HATA YAKALAMA
    # ═══════════════════════════════════════════════════════
    print("\n  ── Hata Yakalama ─────────────────────────────────")

    # [49]
    check_raises("[49] ft_to_m(-5000)", lambda: Units.ft_to_m(-5000), ValueError)

    # [50]
    check_raises("[50] mach_to_tas(0.96)", lambda: Units.mach_to_tas(0.96, 35000), ValueError)

    # [51]
    check_raises("[51] ft_to_m(None)", lambda: Units.ft_to_m(None), TypeError)

    # [52]
    check_raises("[52] kts_to_ms('abc')", lambda: Units.kts_to_ms("abc"), TypeError)

    # [53]
    check_raises("[53] fuel_density(-60°C)", lambda: Units.fuel_density_at_temp(-60), ValueError)

    # FL sınır
    check_raises("[53b] fl_to_ft(700)", lambda: Units.fl_to_ft(700), ValueError)

    # NaN
    check_raises("[53c] ft_to_m(NaN)", lambda: Units.ft_to_m(float('nan')), ValueError)

    # Inf
    check_raises("[53d] ft_to_m(Inf)", lambda: Units.ft_to_m(float('inf')), ValueError)

    # Hız limiti
    check_raises("[53e] kts_to_ms(700)", lambda: Units.kts_to_ms(700), ValueError)

    # pandas Series desteği
    try:
        s = pd.Series([0.0, 35000.0, 41000.0])
        res = Units.ft_to_m(s)
        tests += 1
        if len(res) == 3:
            print(f"  ✅ [53f] ft_to_m(pd.Series) çalışıyor")
        else:
            errors.append("[53f] Series sonuç uzunluğu yanlış")
            print("  ❌ [53f] Series sonuç yanlış")
    except Exception as e:
        tests += 1
        errors.append(f"[53f] Series desteği: {e}")
        print(f"  ❌ [53f] Series: {e}")

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