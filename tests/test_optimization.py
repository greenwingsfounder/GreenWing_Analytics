# tests/test_optimization.py

"""
GreenWing Analytics — Optimizasyon Modülleri Testleri
═════════════════════════════════════════════════════

Kapsamlı test süiti:

AltitudeOptimizer:
    1.  Temel optimum irtifa
    2.  Westbound yön kuralı (çift FL)
    3.  Eastbound yön kuralı (tek FL)
    4.  Buffet marjı pozitif
    5.  Top 3 alternatif
    6.  Ağır uçak → alçak optimum
    7.  Hafif uçak → yüksek optimum
    8.  Rüzgarlı optimizasyon
    9.  Rüzgar metric: ground SAR
    10. Tam uçuş step climb planı
    11. Step climb sayısı ≤ 4
    12. Step climb savings pozitif
    13. Step climb dispatcher talimatı
    14. Kısa rota (step climb az)
    15. Uzun rota B77W

CostIndexOptimizer:
    16. Temel CI optimizasyonu
    17. Optimum maliyet ≤ min fuel maliyeti
    18. Optimum maliyet ≤ min time maliyeti
    19. MinFuel Mach ≤ MinTime Mach
    20. LCC vs Premium CI karşılaştırması
    21. Yakıt fiyatı etkisi
    22. Gecikme telafisi (delay_minutes)
    23. Rota CI tablosu

TankeringOptimizer:
    24. IST→LON tankering kârlı
    25. IST→DXB tankering değil
    26. Fiyat eşit → tankering yok
    27. MTOW kısıtı
    28. Net tasarruf pozitif
    29. Carriage factor makul
    30. Yıllık projeksiyon
    31. Quick check kârlı
    32. Quick check kârsız

ModelCalibrator:
    33. Temel kalibrasyon
    34. CD0 factor makul aralık
    35. SFC factor makul aralık
    36. Kalibrasyon sonrası hata azaldı
    37. Model kalitesi belirlendi
    38. Yorumlar var
    39. Öneriler var
    40. Kalibre edilmiş FM üret
    41. get_factors
    42. reset()
    43. Yetersiz veri → ERROR
    44. Geçersiz veri → ERROR
    45. repr

Çalıştırma:
    python tests/test_optimization.py
    python -m pytest tests/test_optimization.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.optimization.altitude_optimizer import (
    AltitudeOptimizer,
    _EASTBOUND_LEVELS,
    _WESTBOUND_LEVELS,
)
from src.optimization.cost_index_optimizer import CostIndexOptimizer
from src.optimization.tankering_optimizer import TankeringOptimizer
from src.optimization.model_calibrator import ModelCalibrator


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: optimization modülleri — TAM TEST SÜİTİ")
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
    # ALTITUDE OPTIMIZER
    # ═══════════════════════════════════════════════════════

    alt_opt = AltitudeOptimizer('B738')
    print("\n  ── AltitudeOptimizer ──────────────────────────────")

    # ─── 1. TEMEL OPTİMUM İRTİFA ─────────────────────────
    print("\n  [1] Temel Optimum İrtifa")

    result = alt_opt.find_optimum_altitude(65000, 0.785)
    check_true(
        f"status=SUCCESS: {result.get('status')}",
        result.get('status') == 'SUCCESS'
    )

    if result.get('status') == 'SUCCESS':
        opt = result['optimum']
        check_range("Optimum irtifa", float(opt['altitude_ft']), 30000, 41000)
        check_true(f"FL format: {opt['flight_level']}", opt['flight_level'].startswith('FL'))

    # ─── 2. WESTBOUND YÖN KURALI ──────────────────────────
    print("\n  [2] Westbound Yön Kuralı (Heading 310°)")

    result_west = alt_opt.find_optimum_altitude(65000, 0.785, heading_deg=310)
    if result_west.get('status') == 'SUCCESS':
        alt_west = result_west['optimum']['altitude_ft']
        check_true(
            f"Westbound FL{alt_west//100} → çift FL listesinde",
            alt_west in _WESTBOUND_LEVELS
        )
        check_true(
            f"direction=Westbound",
            result_west.get('direction') == 'Westbound'
        )

    # ─── 3. EASTBOUND YÖN KURALI ──────────────────────────
    print("\n  [3] Eastbound Yön Kuralı (Heading 130°)")

    result_east = alt_opt.find_optimum_altitude(65000, 0.785, heading_deg=130)
    if result_east.get('status') == 'SUCCESS':
        alt_east = result_east['optimum']['altitude_ft']
        check_true(
            f"Eastbound FL{alt_east//100} → tek FL listesinde",
            alt_east in _EASTBOUND_LEVELS
        )
        check_true(
            f"direction=Eastbound",
            result_east.get('direction') == 'Eastbound'
        )

    # ─── 4. BUFFET MARJI ──────────────────────────────────
    print("\n  [4] Buffet Marjı")

    if result.get('status') == 'SUCCESS':
        buffet = result['optimum']['buffet_margin_pct']
        check_true(f"Buffet marjı pozitif: {buffet:.1f}%", buffet > 0)

    # ─── 5. TOP 3 ALTERNATİF ─────────────────────────────
    print("\n  [5] Top 3 Alternatif")

    if result.get('status') == 'SUCCESS':
        alts = result.get('top_3_alternatives', [])
        check_true(
            f"{len(alts)} alternatif",
            len(alts) >= 2
        )
        if len(alts) >= 2:
            check_true(
                "Alternatifler SAR'a göre sıralı",
                alts[0]['sar'] >= alts[1]['sar']
            )

    # ─── 6. AĞIR UÇAK → ALÇAK OPTİMUM ────────────────────
    print("\n  [6] Ağır Uçak → Alçak Optimum")

    result_heavy = alt_opt.find_optimum_altitude(75000, 0.785, heading_deg=310)
    result_light = alt_opt.find_optimum_altitude(55000, 0.785, heading_deg=310)

    if result_heavy.get('status') == 'SUCCESS' and result_light.get('status') == 'SUCCESS':
        alt_heavy = result_heavy['optimum']['altitude_ft']
        alt_light = result_light['optimum']['altitude_ft']
        check_true(
            f"Hafif FL{alt_light//100} ≥ Ağır FL{alt_heavy//100}",
            alt_light >= alt_heavy
        )

    # ─── 7. BUFFET KISITI (ÇOK AĞIR) ─────────────────────
    print("\n  [7] Çok Ağır Uçak — Buffet Kısıtı")

    result_very_heavy = alt_opt.find_optimum_altitude(78000, 0.785, heading_deg=310)
    check_true(
        f"Çok ağır uçak işlendi: {result_very_heavy.get('status')}",
        result_very_heavy.get('status') in ('SUCCESS', 'ERROR')
    )
    if result_very_heavy.get('status') == 'SUCCESS':
        alt_vh = result_very_heavy['optimum']['altitude_ft']
        check_true(
            f"Çok ağır için alçak FL: FL{alt_vh//100} ≤ FL380",
            alt_vh <= 38000
        )

    # ─── 8. RÜZGARLI OPTİMİZASYON ────────────────────────
    print("\n  [8] Rüzgarlı Optimizasyon")

    wind = {
        30000: 20, 32000: 15, 34000: 5,
        36000: -10, 38000: -25, 40000: -20,
    }
    result_wind = alt_opt.find_optimum_altitude(65000, 0.785, heading_deg=310, wind_at_levels=wind)
    check_true(
        f"Rüzgarlı optimizasyon: {result_wind.get('status')}",
        result_wind.get('status') == 'SUCCESS'
    )

    # ─── 9. RÜZGAR METRİK: GROUND SAR ────────────────────
    print("\n  [9] Rüzgar → Ground SAR Metriği")

    if result_wind.get('status') == 'SUCCESS':
        check_true(
            f"optimization_metric=ground_sar",
            result_wind.get('optimization_metric') == 'ground_sar'
        )
        check_true(
            f"ground_sar > 0",
            result_wind['optimum']['ground_sar'] > 0
        )

    # ─── 10. TAM UÇUŞ STEP CLIMB PLANI ───────────────────
    print("\n  [10] Step Climb Planı — IST-LON")

    flight = alt_opt.optimize_full_flight(
        distance_nm=1560,
        initial_weight_kg=75000,
        payload_kg=15000,
        mach=0.785,
        heading_deg=310,
    )

    check_true("scenarios var", 'scenarios' in flight)
    check_true("savings var", 'savings' in flight)

    sc = flight['scenarios']
    check_true(
        f"Baseline FL350 fuel > 0: {sc['baseline_fl350']['total_fuel_kg']:,}",
        sc['baseline_fl350']['total_fuel_kg'] > 0
    )

    # ─── 11. STEP CLIMB SAYISI ≤ 4 ───────────────────────
    print("\n  [11] Step Climb Sayısı ≤ 4")

    n_steps = flight['scenarios']['step_climb']['num_steps']
    check_true(
        f"Step sayısı: {n_steps} (max 4)",
        n_steps <= 4
    )

    # ─── 12. STEP CLIMB SAVINGS POZİTİF ──────────────────
    print("\n  [12] Step Climb Savings")

    sv = flight['savings']['per_flight']
    check_true(
        f"Fuel saving ≥ 0: {sv['fuel_kg']} kg",
        sv['fuel_kg'] >= 0
    )
    check_true(
        f"Cost saving ≥ 0: ${sv['cost_usd']:.0f}",
        sv['cost_usd'] >= 0
    )

    # ─── 13. DİSPATCHER TALİMATI ─────────────────────────
    print("\n  [13] Dispatcher Talimatı")

    instruction = flight.get('dispatcher_instruction', '')
    check_true(
        f"Dispatcher talimatı > 50 karakter",
        len(instruction) > 50
    )

    # ─── 14. KISA ROTA (STEP AZ) ──────────────────────────
    print("\n  [14] Kısa Rota — IST-ANK (190 Nm)")

    flight_short = alt_opt.optimize_full_flight(
        distance_nm=190,
        initial_weight_kg=65000,
        payload_kg=10000,
        mach=0.785,
        heading_deg=100,
    )
    n_short = flight_short['scenarios']['step_climb']['num_steps']
    check_true(
        f"Kısa rotada step: {n_short} (az beklenir)",
        n_short <= 2
    )

    # ─── 15. UZUN ROTA — B77W ─────────────────────────────
    print("\n  [15] Uzun Rota — B77W (5000 Nm)")

    alt_opt_777 = AltitudeOptimizer('B77W')
    flight_long = alt_opt_777.optimize_full_flight(
        distance_nm=5000,
        initial_weight_kg=300000,
        payload_kg=50000,
        mach=0.84,
        heading_deg=270,
    )
    n_long = flight_long['scenarios']['step_climb']['num_steps']
    check_true(
        f"Uzun rotada step: {n_long} (max 4)",
        n_long <= 4
    )
    check_true(
        f"B77W baseline fuel > 0: {flight_long['scenarios']['baseline_fl350']['total_fuel_kg']:,}",
        flight_long['scenarios']['baseline_fl350']['total_fuel_kg'] > 0
    )

    # ═══════════════════════════════════════════════════════
    # COST INDEX OPTIMIZER
    # ═══════════════════════════════════════════════════════

    ci_opt = CostIndexOptimizer('B738')
    print("\n  ── CostIndexOptimizer ─────────────────────────────")

    # ─── 16. TEMEL CI OPTİMİZASYONU ──────────────────────
    print("\n  [16] Temel CI Optimizasyonu")

    ci_result = ci_opt.optimize_cost_index(
        distance_nm=1560, altitude_ft=37000, weight_kg=68000,
        fuel_price_usd_per_kg=0.85, time_cost_usd_per_hr=2000,
    )
    check_true(f"status=SUCCESS", ci_result.get('status') == 'SUCCESS')

    if ci_result.get('status') == 'SUCCESS':
        o = ci_result['optimum']
        check_range("CI", float(o['cost_index']), 0, 999)
        check_range("Mach", o['mach'], 0.70, 0.86)
        check_true(f"Total cost > 0: ${o['total_cost_usd']:,}", o['total_cost_usd'] > 0)
        check_true(f"Fuel > 0: {o['fuel_kg']:,}", o['fuel_kg'] > 0)
        check_true(f"Time > 0: {o['flight_time_hr']:.2f}", o['flight_time_hr'] > 0)

    # ─── 17. OPTIMUM ≤ MIN FUEL MALİYETİ ─────────────────
    print("\n  [17] Optimum ≤ Min Fuel Maliyeti")

    if ci_result.get('status') == 'SUCCESS':
        comp = ci_result['comparison']
        check_true(
            f"Optimum(${o['total_cost_usd']:,}) ≤ MinFuel(${comp['min_fuel_cost_usd']:,})",
            o['total_cost_usd'] <= comp['min_fuel_cost_usd'] + 10
        )

    # ─── 18. OPTIMUM ≤ MIN TIME MALİYETİ ─────────────────
    print("\n  [18] Optimum ≤ Min Time Maliyeti")

    if ci_result.get('status') == 'SUCCESS':
        check_true(
            f"Optimum(${o['total_cost_usd']:,}) ≤ MinTime(${comp['min_time_cost_usd']:,})",
            o['total_cost_usd'] <= comp['min_time_cost_usd'] + 10
        )

    # ─── 19. MINFUEL MACH ≤ MINTIME MACH ─────────────────
    print("\n  [19] MinFuel Mach ≤ MinTime Mach")

    if ci_result.get('status') == 'SUCCESS':
        check_true(
            f"MinFuel M{comp['min_fuel_mach']} ≤ MinTime M{comp['min_time_mach']}",
            comp['min_fuel_mach'] <= comp['min_time_mach']
        )

    # ─── 20. LCC vs PREMIUM CI ────────────────────────────
    print("\n  [20] LCC vs Premium CI")

    ci_lcc = ci_opt.optimize_cost_index(
        1560, 37000, 68000, 0.85, time_cost_usd_per_hr=1000
    )
    ci_premium = ci_opt.optimize_cost_index(
        1560, 37000, 68000, 0.85, time_cost_usd_per_hr=3000
    )

    if ci_lcc.get('status') == 'SUCCESS' and ci_premium.get('status') == 'SUCCESS':
        ci_lcc_val     = ci_lcc['optimum']['cost_index']
        ci_premium_val = ci_premium['optimum']['cost_index']
        check_true(
            f"Premium CI({ci_premium_val}) ≥ LCC CI({ci_lcc_val})",
            ci_premium_val >= ci_lcc_val
        )

        mach_lcc     = ci_lcc['optimum']['mach']
        mach_premium = ci_premium['optimum']['mach']
        check_true(
            f"Premium Mach({mach_premium}) ≥ LCC Mach({mach_lcc})",
            mach_premium >= mach_lcc
        )

    # ─── 21. YAKIT FİYATI ETKİSİ ─────────────────────────
    print("\n  [21] Yakıt Fiyatı Etkisi")

    ci_cheap = ci_opt.optimize_cost_index(
        1560, 37000, 68000, fuel_price_usd_per_kg=0.50, time_cost_usd_per_hr=2000
    )
    ci_expensive = ci_opt.optimize_cost_index(
        1560, 37000, 68000, fuel_price_usd_per_kg=1.20, time_cost_usd_per_hr=2000
    )

    if ci_cheap.get('status') == 'SUCCESS' and ci_expensive.get('status') == 'SUCCESS':
        ci_cheap_val     = ci_cheap['optimum']['cost_index']
        ci_expensive_val = ci_expensive['optimum']['cost_index']
        check_true(
            f"Pahalı yakıt CI({ci_expensive_val}) ≤ Ucuz CI({ci_cheap_val})",
            ci_expensive_val <= ci_cheap_val
        )

    # ─── 22. GECİKME TELAFİSİ ────────────────────────────
    print("\n  [22] Gecikme Telafisi (delay_minutes=30)")

    ci_normal  = ci_opt.optimize_cost_index(1560, 37000, 68000, delay_minutes=0)
    ci_delayed = ci_opt.optimize_cost_index(1560, 37000, 68000, delay_minutes=30)

    if ci_normal.get('status') == 'SUCCESS' and ci_delayed.get('status') == 'SUCCESS':
        mach_normal  = ci_normal['optimum']['mach']
        mach_delayed = ci_delayed['optimum']['mach']
        check_true(
            f"Gecikmeli Mach({mach_delayed}) ≥ Normal Mach({mach_normal})",
            mach_delayed >= mach_normal
        )

        # all_options'da delay_benefit hesaplanmış mı?
        opts = ci_delayed.get('all_options', [])
        has_benefit = any(o.get('delay_benefit_usd', 0) > 0 for o in opts)
        check_true("Gecikme faydası hesaplandı", has_benefit)

    # ─── 23. ROTA CI TABLOSU ──────────────────────────────
    print("\n  [23] Rota CI Tablosu")

    routes = [
        {'origin': 'LTFM', 'destination': 'EGLL',
         'distance_nm': 1560, 'altitude_ft': 37000, 'weight_kg': 68000},
        {'origin': 'LTFM', 'destination': 'LTAC',
         'distance_nm': 190, 'altitude_ft': 33000, 'weight_kg': 62000},
        {'origin': 'LTFM', 'destination': 'EDDF',
         'distance_nm': 1000, 'altitude_ft': 37000, 'weight_kg': 66000},
    ]

    table = ci_opt.generate_route_ci_table(routes)
    check_true(f"Rota tablosu: {len(table)} satır", len(table) >= 2)

    if len(table) >= 2:
        short_route = next((r for r in table if r['distance_nm'] < 300), None)
        long_route  = next((r for r in table if r['distance_nm'] > 1000), None)
        if short_route and long_route:
            check_true(
                f"Kısa CI({short_route['optimum_ci']}) ≥ Uzun CI({long_route['optimum_ci']})",
                short_route['optimum_ci'] >= long_route['optimum_ci']
            )

    # ═══════════════════════════════════════════════════════
    # TANKERING OPTIMIZER
    # ═══════════════════════════════════════════════════════

    tank_opt = TankeringOptimizer('B738')
    print("\n  ── TankeringOptimizer ─────────────────────────────")

    # ─── 24. IST→LON TANKERİNG KÂRLI ─────────────────────
    print("\n  [24] IST→LON Tankering Kârlı")

    tank_lon = tank_opt.optimize_tankering(
        1560, 37000, 0.785, 72000,
        fuel_price_origin_usd_per_kg=0.78,
        fuel_price_dest_usd_per_kg=1.05,
    )
    check_true(
        f"IST→LON: {tank_lon['recommendation']}",
        tank_lon['recommendation'] == 'TANKERİNG ÖNERİLİYOR'
    )
    check_true(
        f"Ekstra > 0: {tank_lon['optimal_extra_fuel_kg']} kg",
        tank_lon['optimal_extra_fuel_kg'] > 0
    )
    check_true(
        f"Net saving > 0: ${tank_lon['net_saving_usd']:.2f}",
        tank_lon['net_saving_usd'] > 0
    )

    # ─── 25. IST→DXB TANKERİNG DEĞİL ─────────────────────
    print("\n  [25] IST→DXB Tankering Değil")

    tank_dxb = tank_opt.optimize_tankering(
        1550, 39000, 0.785, 72000,
        fuel_price_origin_usd_per_kg=0.78,
        fuel_price_dest_usd_per_kg=0.58,
    )
    check_true(
        f"IST→DXB: {tank_dxb['recommendation']}",
        tank_dxb['recommendation'] == 'TANKERİNG ÖNERİLMİYOR'
    )
    check_true(
        f"Ekstra = 0: {tank_dxb['optimal_extra_fuel_kg']} kg",
        tank_dxb['optimal_extra_fuel_kg'] == 0
    )

    # ─── 26. FİYAT EŞİT → TANKERİNG YOK ─────────────────
    print("\n  [26] Fiyat Eşit → Tankering Yok")

    tank_equal = tank_opt.optimize_tankering(
        1560, 37000, 0.785, 72000,
        fuel_price_origin_usd_per_kg=0.85,
        fuel_price_dest_usd_per_kg=0.85,
    )
    check_true(
        f"Eşit fiyat: {tank_equal['recommendation']}",
        tank_equal['recommendation'] == 'TANKERİNG ÖNERİLMİYOR'
    )

    # ─── 27. MTOW KISITI ──────────────────────────────────
    print("\n  [27] MTOW Kısıtı")

    tank_heavy = tank_opt.optimize_tankering(
        1560, 37000, 0.785, 78000,  # MTOW'a yakın
        fuel_price_origin_usd_per_kg=0.78,
        fuel_price_dest_usd_per_kg=1.05,
    )
    details = tank_heavy.get('details', {})
    actual_max = details.get('actual_max_extra_kg', 5000)
    check_true(
        f"MTOW kısıtı: max={actual_max:.0f} < 5000",
        actual_max < 5000
    )

    # MTOW kısıtı varsa constraints listesi dolu
    if actual_max < 5000:
        check_true(
            f"Constraints listesi dolu",
            len(tank_heavy.get('constraints', [])) > 0
        )

    # ─── 28. NET TASARRUF POZİTİF ─────────────────────────
    print("\n  [28] Net Tasarruf Pozitif")

    if tank_lon['recommendation'] == 'TANKERİNG ÖNERİLİYOR':
        check_true(
            f"Net saving ≥ 0",
            tank_lon['net_saving_usd'] >= 0
        )

    # ─── 29. CARRIAGE FACTOR MAKUL ────────────────────────
    print("\n  [29] Carriage Factor")

    if tank_lon['recommendation'] == 'TANKERİNG ÖNERİLİYOR':
        cf = tank_lon['details'].get('carriage_factor_at_optimum_pct', -1)
        check_range("Carriage factor", cf, 0, 25)

    # ─── 30. YILLIK PROJEKSİYON ───────────────────────────
    print("\n  [30] Yıllık Projeksiyon")

    annual = tank_lon.get('annual_projection', {})
    check_true("annual_saving_usd ≥ 0", annual.get('annual_saving_usd', 0) >= 0)

    # ─── 31. QUICK CHECK KÂRLI ────────────────────────────
    print("\n  [31] Quick Check Kârlı")

    qc = tank_opt.quick_check(1560, 0.78, 1.05)
    check_true(f"IST→LON viable: {qc['viable']}", qc['viable'])
    check_true(f"price_diff > 0: {qc['price_diff']:.3f}", qc['price_diff'] > 0)
    check_range("CF tahmini", qc['estimated_cf_pct'], 5, 20)

    # ─── 32. QUICK CHECK KÂRSIZ ───────────────────────────
    print("\n  [32] Quick Check Kârsız")

    qc_dxb = tank_opt.quick_check(1550, 0.78, 0.58)
    check_true(f"IST→DXB not viable: {not qc_dxb['viable']}", not qc_dxb['viable'])
    check_true(f"price_diff < 0: {qc_dxb['price_diff']:.3f}", qc_dxb['price_diff'] < 0)

    # ═══════════════════════════════════════════════════════
    # MODEL CALIBRATOR
    # ═══════════════════════════════════════════════════════

    cal = ModelCalibrator('B738')
    print("\n  ── ModelCalibrator ────────────────────────────────")

    ACTUAL_FLIGHTS = [
        {'distance_nm': 1560, 'actual_fuel_kg': 12800, 'cruise_altitude_ft': 37000},
        {'distance_nm': 1560, 'actual_fuel_kg': 12500, 'cruise_altitude_ft': 37000},
        {'distance_nm': 1560, 'actual_fuel_kg': 13100, 'cruise_altitude_ft': 35000},
        {'distance_nm': 1000, 'actual_fuel_kg': 8900,  'cruise_altitude_ft': 37000},
        {'distance_nm': 1000, 'actual_fuel_kg': 8600,  'cruise_altitude_ft': 37000},
        {'distance_nm': 190,  'actual_fuel_kg': 3400,  'cruise_altitude_ft': 33000},
        {'distance_nm': 190,  'actual_fuel_kg': 3200,  'cruise_altitude_ft': 35000},
        {'distance_nm': 300,  'actual_fuel_kg': 4300,  'cruise_altitude_ft': 35000},
        {'distance_nm': 1550, 'actual_fuel_kg': 12200, 'cruise_altitude_ft': 39000},
        {'distance_nm': 780,  'actual_fuel_kg': 7500,  'cruise_altitude_ft': 35000},
    ]

    # ─── 33. TEMEL KALİBRASYON ───────────────────────────
    print("\n  [33] Temel Kalibrasyon")

    result = cal.calibrate(ACTUAL_FLIGHTS)
    check_true(f"status=SUCCESS", result.get('status') == 'SUCCESS')

    # ─── 34. CD0 FACTOR MAKUL ─────────────────────────────
    print("\n  [34] CD0 Factor Aralığı")

    if result.get('status') == 'SUCCESS':
        cd0_f = result['calibration_factors']['cd0_factor']
        check_range("cd0_factor", cd0_f, 0.85, 1.25)

    # ─── 35. SFC FACTOR MAKUL ─────────────────────────────
    print("\n  [35] SFC Factor Aralığı")

    if result.get('status') == 'SUCCESS':
        sfc_f = result['calibration_factors']['sfc_factor']
        check_range("sfc_factor", sfc_f, 0.90, 1.15)

    # ─── 36. KALİBRASYON SONRASI HATA AZALDI ─────────────
    print("\n  [36] Hata Azaldı")

    if result.get('status') == 'SUCCESS':
        acc = result['accuracy']
        check_true(
            f"Hata azaldı: %{acc['avg_error_before_pct']:.1f} → %{acc['avg_error_after_pct']:.1f}",
            acc['avg_error_after_pct'] <= acc['avg_error_before_pct']
        )
        check_true(
            f"İyileşme ≥ 0: %{acc['improvement_pct']:.2f}",
            acc['improvement_pct'] >= 0
        )

    # ─── 37. MODEL KALİTESİ BELİRLENDİ ──────────────────
    print("\n  [37] Model Kalitesi")

    if result.get('status') == 'SUCCESS':
        quality = result.get('model_quality', '')
        check_true(
            f"Model kalitesi belirlendi: {quality}",
            quality in ('EXCELLENT', 'GOOD', 'FAIR', 'POOR')
        )

    # ─── 38. YORUMLAR VAR ─────────────────────────────────
    print("\n  [38] Yorumlar")

    if result.get('status') == 'SUCCESS':
        interps = result.get('interpretations', [])
        check_true(
            f"En az 1 yorum: {len(interps)}",
            len(interps) >= 1
        )

    # ─── 39. ÖNERİLER VAR ────────────────────────────────
    print("\n  [39] Öneriler")

    if result.get('status') == 'SUCCESS':
        recs = result.get('recommendations', [])
        check_true(
            f"En az 1 öneri: {len(recs)}",
            len(recs) >= 1
        )
        # Her öneride zorunlu alanlar
        for rec in recs:
            check_true(
                f"Öneri alanları: {rec.get('action', '?')}",
                all(k in rec for k in ['action', 'priority', 'rationale'])
            )

    # ─── 40. KALİBRE EDİLMİŞ FM ──────────────────────────
    print("\n  [40] Kalibre Edilmiş FuelModel")

    if result.get('status') == 'SUCCESS':
        fm_cal = cal.get_calibrated_fuel_model()
        check_true(
            f"cd0_factor uygulandı: {fm_cal.cd0_factor}",
            fm_cal.cd0_factor == cd0_f
        )
        check_true(
            f"sfc_factor uygulandı: {fm_cal.sfc_factor}",
            fm_cal.sfc_factor == sfc_f
        )

    # ─── 41. GET_FACTORS ──────────────────────────────────
    print("\n  [41] get_factors()")

    if result.get('status') == 'SUCCESS':
        factors = cal.get_factors()
        check_true(
            f"cd0_factor == {cd0_f}",
            factors.get('cd0_factor') == cd0_f
        )
        check_true(
            f"sfc_factor == {sfc_f}",
            factors.get('sfc_factor') == sfc_f
        )

    # ─── 42. RESET() ──────────────────────────────────────
    print("\n  [42] reset()")

    cal.reset()
    check("cd0 sıfırlandı", cal.calibration_factors['cd0_factor'], 1.0, 0.001)
    check("sfc sıfırlandı", cal.calibration_factors['sfc_factor'], 1.0, 0.001)

    # Sıfırladıktan sonra get_factors da 1.0
    factors_reset = cal.get_factors()
    check("get_factors cd0 reset", factors_reset['cd0_factor'], 1.0, 0.001)

    # ─── 43. YETERSİZ VERİ → ERROR ───────────────────────
    print("\n  [43] Yetersiz Veri → ERROR")

    result_short = cal.calibrate([
        {'distance_nm': 1560, 'actual_fuel_kg': 12500},
        {'distance_nm': 1000, 'actual_fuel_kg': 8900},
    ])
    check_true(
        f"2 uçuş → ERROR (min 3)",
        result_short.get('status') == 'ERROR'
    )

    result_empty = cal.calibrate([])
    check_true(
        f"Boş liste → ERROR",
        result_empty.get('status') == 'ERROR'
    )

    # ─── 44. GEÇERSİZ VERİ → ERROR ───────────────────────
    print("\n  [44] Geçersiz Veri → ERROR")

    result_invalid = cal.calibrate([
        {'distance_nm': 0,    'actual_fuel_kg': 0},
        {'distance_nm': -100, 'actual_fuel_kg': 5000},
        {'distance_nm': 1560, 'actual_fuel_kg': -1000},
    ])
    check_true(
        f"Geçersiz veriler → ERROR",
        result_invalid.get('status') == 'ERROR'
    )

    # ─── 45. REPR ─────────────────────────────────────────
    print("\n  [45] Repr")

    r = repr(cal)
    check_true(f"repr: {r}", 'ModelCalibrator' in r and 'B738' in r)

    r_alt = repr(alt_opt)
    check_true(f"AltOpt repr: {r_alt}", 'AltitudeOptimizer' in r_alt)

    r_ci = repr(ci_opt)
    check_true(f"CI repr: {r_ci}", 'CostIndexOptimizer' in r_ci)

    r_tank = repr(tank_opt)
    check_true(f"Tank repr: {r_tank}", 'TankeringOptimizer' in r_tank)

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

