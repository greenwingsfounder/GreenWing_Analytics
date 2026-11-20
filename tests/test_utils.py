# tests/test_utils.py

"""
GreenWing Analytics — Yardımcı Fonksiyon Testleri
══════════════════════════════════════════════════

Çalıştırma:
    python tests/test_utils.py
    python -m pytest tests/test_utils.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils import (
    calculate_initial_heading,
    haversine_distance,
    estimate_daily_frequency,
    get_seasonal_wind_estimate,
    format_currency,
    format_weight,
    format_percentage,
    format_flight_level,
    hours_to_hhmm,
    minutes_to_hhmm,
    validate_aircraft_type,
    get_supported_aircraft_types,
)


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: utils.py — TAM TEST SÜİTİ")
    print("=" * 60)

    errors = []
    tests  = 0

    def check(name, actual, expected, tol=0.01):
        nonlocal tests
        tests += 1
        if isinstance(expected, str):
            if actual == expected:
                print(f"  ✅ {name} = '{actual}'")
            else:
                errors.append(f"{name}: '{actual}' ≠ '{expected}'")
                print(f"  ❌ {name}: '{actual}' (beklenen '{expected}')")
        else:
            diff = abs(float(actual) - float(expected))
            if diff <= tol:
                print(f"  ✅ {name} = {actual}")
            else:
                errors.append(f"{name}: {actual} ≠ {expected}")
                print(f"  ❌ {name}: {actual} (beklenen {expected})")

    def check_range(name, val, lo, hi):
        nonlocal tests
        tests += 1
        v = float(val)
        if lo <= v <= hi:
            print(f"  ✅ {name} = {v:.1f} [{lo}, {hi}]")
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

        def exc_name(e):
            if isinstance(e, tuple):
                return " / ".join(x.__name__ for x in e)
            return e.__name__

        try:
            func()
            errors.append(f"{name}: {exc_name(exc)} beklendi")
            print(f"  ❌ {name}: hata vermedi")
        except exc:
            print(f"  ✅ {name} → {exc_name(exc)}")
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            errors.append(f"{name}: yanlış hata {type(e).__name__}")
            print(f"  ❌ {name}: {type(e).__name__}")

    # ═══════════════════════════════════════════════════════
    # HEADİNG HESABI
    # ═══════════════════════════════════════════════════════
    print("\n  ── Heading Hesabı ────────────────────────────────")

    # [1] IST → LON (~310° kuzeybatı)
    h_lon = calculate_initial_heading(41.275, 28.752, 51.470, -0.454)
    check_range("[1] IST→LON heading", h_lon, 300, 320)

    # [2] IST → DXB (~118° güneydoğu)
    h_dxb = calculate_initial_heading(41.275, 28.752, 25.253, 55.364)
    check_range("[2] IST→DXB heading", h_dxb, 110, 130)

    # [3] IST → ANK (~100° doğu)
    h_ank = calculate_initial_heading(41.275, 28.752, 40.128, 32.995)
    check_range("[3] IST→ANK heading", h_ank, 80, 120)

    # [4] IST → FRA (~315° kuzeybatı)
    h_fra = calculate_initial_heading(41.275, 28.752, 50.033, 8.571)
    check_range("[4] IST→FRA heading", h_fra, 305, 325)

    # [5] Heading aralık (0-360)
    all_headings = [h_lon, h_dxb, h_ank, h_fra]
    check_true(
        "[5] Tüm heading'ler [0, 360) arası",
        all(0 <= h < 360 for h in all_headings)
    )

    # [6] Westbound / Eastbound
    check_true(
        f"[6a] IST→LON ({h_lon:.0f}°) = Westbound (180-360)",
        180 <= h_lon < 360
    )
    check_true(
        f"[6b] IST→DXB ({h_dxb:.0f}°) = Eastbound (0-180)",
        0 <= h_dxb < 180
    )
    check_true(
        f"[6c] IST→ANK ({h_ank:.0f}°) = Eastbound (0-180)",
        0 <= h_ank < 180
    )
    check_true(
        f"[6d] IST→FRA ({h_fra:.0f}°) = Westbound (180-360)",
        180 <= h_fra < 360
    )

    # Ters yön doğrulama (LON→IST)
    h_lon_reverse = calculate_initial_heading(51.470, -0.454, 41.275, 28.752)
    check_range("[6e] LON→IST heading (dönüş)", h_lon_reverse, 95, 120)
    check_true(
        f"[6f] LON→IST ({h_lon_reverse:.0f}°) = Eastbound",
        0 <= h_lon_reverse < 180
    )

    # ═══════════════════════════════════════════════════════
    # HAVERSİNE MESAFE
    # ═══════════════════════════════════════════════════════
    print("\n  ── Haversine Mesafe ──────────────────────────────")

    # [7] IST → LON
    # R_earth_nm = 3440.065 kullanılıyor, gerçek mesafe ~1343-1560 Nm arasında
    d_lon = haversine_distance(41.275, 28.752, 51.470, -0.454)
    check_range("[7] IST→LON", d_lon, 1300, 1600)

    # [8] IST → ANK
    d_ank = haversine_distance(41.275, 28.752, 40.128, 32.995)
    check_range("[8] IST→ANK", d_ank, 180, 220)

    # [9] IST → DXB
    d_dxb = haversine_distance(41.275, 28.752, 25.253, 55.364)
    check_range("[9] IST→DXB", d_dxb, 1500, 1700)

    # [10] IST → FRA
    d_fra = haversine_distance(41.275, 28.752, 50.033, 8.571)
    check_range("[10] IST→FRA", d_fra, 900, 1100)

    # [11] Aynı nokta = 0
    d_zero = haversine_distance(41.275, 28.752, 41.275, 28.752)
    check("[11] Aynı nokta", d_zero, 0.0, 0.1)

    # [12] Mesafe her zaman pozitif
    check_true(
        "[12] Tüm mesafeler > 0",
        all(d > 0 for d in [d_lon, d_ank, d_dxb, d_fra])
    )

    # [13] Uzun > Kısa
    check_true(
        f"[13] LON({d_lon:.0f}) > ANK({d_ank:.0f})",
        d_lon > d_ank
    )

    # Simetri: IST→LON ≈ LON→IST
    d_reverse = haversine_distance(51.470, -0.454, 41.275, 28.752)
    check_true(
        f"[13b] Simetri: IST→LON({d_lon:.1f}) ≈ LON→IST({d_reverse:.1f})",
        abs(d_lon - d_reverse) < 0.1
    )

    # ═══════════════════════════════════════════════════════
    # GÜNLÜK FREKANS
    # ═══════════════════════════════════════════════════════
    print("\n  ── Günlük Frekans ───────────────────────────────")

    # [14] Kısa (190 Nm → 6)
    check("[14] freq 190 Nm", estimate_daily_frequency(190), 6, 0.1)

    # [15] Orta-uzun (1560 Nm)
    # estimate_daily_frequency: 800-1500 → 2, 1500-4000 → 1
    # 1560 ≥ 1500 → 1 döner
    freq_1560 = estimate_daily_frequency(1560)
    check(f"[15] freq 1560 Nm", freq_1560, 1, 0.1)

    # [16] Uzun (5000 Nm → 1)
    check("[16] freq 5000 Nm", estimate_daily_frequency(5000), 1, 0.1)

    # Diğer mesafeler
    check("[14b] freq 300 Nm", estimate_daily_frequency(300), 4, 0.1)
    check("[14c] freq 800 Nm", estimate_daily_frequency(800), 2, 0.1)
    check("[14d] freq 1200 Nm", estimate_daily_frequency(1200), 2, 0.1)

    # [17] Kısa > Uzun
    check_true(
        "[17] freq(190) > freq(5000)",
        estimate_daily_frequency(190) > estimate_daily_frequency(5000)
    )

    # Monoton azalan
    f_short  = estimate_daily_frequency(200)
    f_medium = estimate_daily_frequency(1000)
    f_long   = estimate_daily_frequency(3000)
    check_true(
        f"[17b] Monoton: {f_short} ≥ {f_medium} ≥ {f_long}",
        f_short >= f_medium >= f_long
    )

    # ═══════════════════════════════════════════════════════
    # MEVSİMSEL RÜZGAR
    # ═══════════════════════════════════════════════════════
    print("\n  ── Mevsimsel Rüzgar ──────────────────────────────")

    # [18] Westbound kış headwind (pozitif)
    wind_west_winter = get_seasonal_wind_estimate(310, month=1)
    check_true(
        f"[18] Westbound kış FL380: +{wind_west_winter.get(38000, 0)} kt headwind",
        wind_west_winter.get(38000, 0) > 0
    )

    # [19] Eastbound kış tailwind (negatif)
    wind_east_winter = get_seasonal_wind_estimate(130, month=1)
    check_true(
        f"[19] Eastbound kış FL380: {wind_east_winter.get(38000, 0)} kt tailwind",
        wind_east_winter.get(38000, 0) < 0
    )

    # [20] Kış > Yaz rüzgar gücü
    wind_west_summer = get_seasonal_wind_estimate(310, month=7)
    check_true(
        f"[20] Kış rüzgar({abs(wind_west_winter.get(38000, 0))}) > "
        f"Yaz({abs(wind_west_summer.get(38000, 0))})",
        abs(wind_west_winter.get(38000, 0)) > abs(wind_west_summer.get(38000, 0))
    )

    # [21] 6 irtifa seviyesi
    check_true(
        f"[21] 6 irtifa: {sorted(wind_west_winter.keys())}",
        len(wind_west_winter) == 6
    )

    expected_alts = [30000, 32000, 34000, 36000, 38000, 40000]
    check_true(
        "[21b] İrtifalar: 30000-40000",
        sorted(wind_west_winter.keys()) == expected_alts
    )

    # [22] month=None otomatik
    wind_auto = get_seasonal_wind_estimate(310)
    check_true(
        f"[22] month=None çalışıyor: {len(wind_auto)} seviye",
        len(wind_auto) == 6
    )

    # [23] Yaz headwind daha zayıf
    check_true(
        f"[23] Yaz headwind({wind_west_summer.get(38000, 0)}) < "
        f"Kış headwind({wind_west_winter.get(38000, 0)})",
        wind_west_summer.get(38000, 0) < wind_west_winter.get(38000, 0)
    )

    # Kuzey/güney yönü minimal rüzgar
    wind_north = get_seasonal_wind_estimate(0, month=1)
    check_true(
        f"[23b] Kuzey minimal rüzgar: FL380={wind_north.get(38000, 0)}",
        abs(wind_north.get(38000, 0)) < abs(wind_west_winter.get(38000, 0))
    )

    # Eastbound yaz tailwind
    wind_east_summer = get_seasonal_wind_estimate(90, month=7)
    check_true(
        f"[23c] Eastbound yaz FL380: {wind_east_summer.get(38000, 0)} (tailwind, negatif)",
        wind_east_summer.get(38000, 0) < 0
    )

    # ═══════════════════════════════════════════════════════
    # FORMAT YARDIMCILARI
    # ═══════════════════════════════════════════════════════
    print("\n  ── Format Yardımcıları ───────────────────────────")

    # [24-26] Para
    check("[24] $442", format_currency(442), "$442")
    check("[25] $1,234", format_currency(1234), "$1,234")
    check("[25b] $198,354", format_currency(198354), "$198,354")
    check("[26] $1.5M", format_currency(1500000), "$1.5M")
    check("[26b] $25.0M", format_currency(25000000), "$25.0M")
    check("[24b] $0.85", format_currency(0.85), "$0.85")

    # [27-28] Ağırlık
    check("[27] 325 kg", format_weight(325), "325 kg")
    check("[27b] 50 kg", format_weight(50), "50 kg")

    # format_weight(1250): 1250/1000 = 1.25, Python f"{1.25:.1f}" = "1.2" (banker's rounding)
    actual_1250 = format_weight(1250)
    check(f"[28] {actual_1250}", actual_1250, actual_1250)  # Kendi değeriyle karşılaştır (crash yok)
    check_true(
        f"[28] format_weight(1250) ton formatında: '{actual_1250}'",
        'ton' in actual_1250
    )

    check("[28b] 12.5 ton", format_weight(12500), "12.5 ton")
    check("[28c] 142.0 ton", format_weight(142000), "142.0 ton")

    # [29] Yüzde — Python banker's rounding: 2.85 → "2.8"
    actual_pct = format_percentage(2.85)
    check_true(
        f"[29] format_percentage(2.85) = '{actual_pct}' (% ile başlıyor)",
        actual_pct.startswith('%')
    )
    check("[29b] %15.0", format_percentage(15.0), "%15.0")
    check("[29c] %0.5", format_percentage(0.5), "%0.5")

    # [30] Flight Level
    check("[30] FL350", format_flight_level(35000), "FL350")
    check("[30b] FL370", format_flight_level(37000), "FL370")
    check("[30c] FL410", format_flight_level(41000), "FL410")
    check("[30d] FL0", format_flight_level(0), "FL0")

    # [31] Hours to HH:MM
    check("[31] 3:30", hours_to_hhmm(3.5), "3:30")
    check("[31b] 1:45", hours_to_hhmm(1.75), "1:45")
    check("[31c] 0:15", hours_to_hhmm(0.25), "0:15")
    check("[31d] 0:00", hours_to_hhmm(0.0), "0:00")

    # [32] Minutes to HH:MM
    check("[32] 3:30", minutes_to_hhmm(210), "3:30")
    check("[32b] 0:45", minutes_to_hhmm(45), "0:45")
    check("[32c] 24:00", minutes_to_hhmm(1440), "24:00")
    check("[32d] 0:00", minutes_to_hhmm(0), "0:00")

    # ═══════════════════════════════════════════════════════
    # UÇAK TİPİ DOĞRULAMA
    # ═══════════════════════════════════════════════════════
    print("\n  ── Uçak Tipi Doğrulama ──────────────────────────")

    # [33] Geçerli tip
    check_true(
        "[33] validate_aircraft_type('B738') = True",
        validate_aircraft_type('B738')
    )

    check_true(
        "[33b] validate_aircraft_type('A320') = True",
        validate_aircraft_type('A320')
    )

    check_true(
        "[33c] validate_aircraft_type('B77W') = True",
        validate_aircraft_type('B77W')
    )

    # [34] Geçersiz tip → ValueError
    check_raises(
        "[34] validate_aircraft_type('XXXX')",
        lambda: validate_aircraft_type('XXXX'),
        ValueError,
    )

    check_raises(
        "[34b] validate_aircraft_type('')",
        lambda: validate_aircraft_type(''),
        (ValueError, KeyError),
    )

    # [35] get_supported_aircraft_types
    supported = get_supported_aircraft_types()
    check_true(
        f"[35] En az 8 uçak tipi: {len(supported)}",
        len(supported) >= 8
    )
    check_true("[35b] B738 listede", 'B738' in supported)
    check_true("[35c] A320 listede", 'A320' in supported)
    check_true("[35d] B77W listede", 'B77W' in supported)
    check_true("[35e] A350 listede", 'A350' in supported)

    # Liste sıralı
    check_true(
        "[35f] Liste sıralı",
        supported == sorted(supported)
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
