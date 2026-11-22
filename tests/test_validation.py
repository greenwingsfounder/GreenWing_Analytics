# tests/test_validation.py

"""
Validation katmanı testleri.

Çalıştırma:
    python -m pytest tests/test_validation.py -v
    veya:
    python tests/test_validation.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd

from src.validation.data_validator     import DataValidator, ValidationResult
from src.validation.physics_validator  import PhysicsValidator
from src.validation.business_validator import BusinessValidator


def run_all_tests():
    """Tüm validation testlerini çalıştır."""

    print("\n" + "=" * 65)
    print("  VALIDATION KATMANI — TAM TEST SÜİTİ")
    print("=" * 65)

    errors: list[str] = []
    tests  = 0

    # ─── Yardımcılar ─────────────────────────────────────
    def ok(name: str) -> None:
        nonlocal tests
        tests += 1
        print(f"  ✅ {name}")

    def fail(name: str, detail: str) -> None:
        nonlocal tests
        tests += 1
        errors.append(f"{name}: {detail}")
        print(f"  ❌ {name}: {detail}")

    def assert_check(name, cond, detail=''):
        if cond:
            ok(name)
        else:
            fail(name, detail)

    # ═══════════════════════════════════════════════════════════
    # TANKERING AYRIŞTIRMASI — fiziksel vs fiyat arbitrajı
    # ═══════════════════════════════════════════════════════════
    from config.assumptions import TANKERING_PERSISTENCE, Assumptions

    print("\n" + "-" * 62)
    print("  Tankering ayrıştırması (fiziksel yakıt vs fiyat arbitrajı)")
    print("-" * 62)

    _a = Assumptions.annual_projection(
        249.49, 1240, tankering_usd_per_flight=248.69)

    assert_check("fiziksel yakıt payı hesaplanır",
          abs(_a['fuel_saving_usd'] - 0.80 * 2 * 345 * 0.65) < 1.0,
          f"gelen {_a['fuel_saving_usd']}")
    assert_check("tankering payı %50 sürdürülebilirlikle hesaplanır",
          abs(_a['tankering_usd'] - 248.69 * 2 * 345 * 0.65
              * TANKERING_PERSISTENCE) < 2.0,
          f"gelen {_a['tankering_usd']}")
    assert_check("toplam = fiziksel + tankering",
          abs(_a['realistic_annual_usd']
              - (_a['fuel_saving_usd'] + _a['tankering_usd'])) <= 1,
          f"{_a['realistic_annual_usd']} vs "
          f"{_a['fuel_saving_usd'] + _a['tankering_usd']}")
    assert_check("SÜRDÜRÜLEBİLİRLİK: tankering payı tekrarlanabilir yakıttan büyük",
          _a['tankering_usd'] > _a['fuel_saving_usd'])
    assert_check("tankering olmadan toplam = yalnızca fiziksel",
          Assumptions.annual_projection(10.0, 800)['tankering_usd'] == 0)
    assert_check("TANKERING_PERSISTENCE 0-1 arası",
          0.0 < TANKERING_PERSISTENCE <= 1.0)
    assert_check("persistence %50 muhafazakâr",
          TANKERING_PERSISTENCE == 0.50)

    print("\n" + "-" * 62)
    print("  Blok-saat fiziksel tavanı")
    print("-" * 62)

    # 8000 nm rotada 1 sefer/gün fiziksel değil → kırpılmalı
    _cap = Assumptions.annual_projection(100.0, 8000)
    assert_check("8000 nm: frekans kırpıldı", _cap['capacity_capped'])
    assert_check("8000 nm: yıllık blok-saat ≤ 4500",
          _cap['annual_block_hours'] <= 4500.5,
          f"gelen {_cap['annual_block_hours']}")
    _short = Assumptions.annual_projection(100.0, 400)
    assert_check("400 nm: kırpma yok", not _short['capacity_capped'])
    assert_check("400 nm: blok-saat makul",
          1000 <= _short['annual_block_hours'] <= 4500,
          f"gelen {_short['annual_block_hours']}")



    def check_pass(name: str, result: ValidationResult) -> None:
        if result.is_valid:
            ok(name)
        else:
            fail(name, f"PASS beklendi: {result.errors}")

    def check_fail(name: str, result: ValidationResult) -> None:
        if not result.is_valid:
            ok(name)
        else:
            fail(name, "FAIL beklendi ama PASS döndü")

    def check_warning(name: str, result: ValidationResult) -> None:
        if result.warnings:
            ok(name)
        else:
            fail(name, "WARNING beklendi ama yok")

    # ═══════════════════════════════════════════════════
    # DATA VALIDATOR
    # ═══════════════════════════════════════════════════
    print("\n  [DataValidator]")

    # ─── validate_scalar ─────────────────────────────────
    # Not: _DATA_LIMITS'te "altitude_ft" yok, "baro_altitude_ft" var
    # "altitude_ft" bilinmeyen anahtar → sınır kontrolü yapılmaz → PASS döner
    # Bu beklenen davranış — burada baro_altitude_ft kullanıyoruz
    check_pass("scalar: baro_altitude 35000 ft",
               DataValidator.validate_scalar("baro_altitude_ft", 35000))
    check_pass("scalar: mach 0.785",
               DataValidator.validate_scalar("mach", 0.785))
    check_pass("scalar: velocity 450 kts",
               DataValidator.validate_scalar("velocity_kts", 450))

    check_fail("scalar: mach 1.5 (süpersonik)",
               DataValidator.validate_scalar("mach", 1.5))
    check_fail("scalar: velocity 700 kts",
               DataValidator.validate_scalar("velocity_kts", 700))
    check_fail("scalar: baro_altitude -5000 ft",
               DataValidator.validate_scalar("baro_altitude_ft", -5000))
    check_fail("scalar: None",
               DataValidator.validate_scalar("baro_altitude_ft", None))
    check_fail("scalar: string",
               DataValidator.validate_scalar("baro_altitude_ft", "yüksek"))
    check_fail("scalar: NaN",
               DataValidator.validate_scalar("baro_altitude_ft", float('nan')))
    check_fail("scalar: Inf",
               DataValidator.validate_scalar("baro_altitude_ft", float('inf')))

    # ─── validate_trajectory ─────────────────────────────
    def make_traj(n=20, add_time=True, add_alt=True, add_vel=True):
        data = {
            'latitude' : np.linspace(41.27, 51.47, n),
            'longitude': np.linspace(28.75, -0.45, n),
        }
        if add_time:
            data['time'] = pd.date_range('2025-01-20 10:00', periods=n, freq='60s')
        if add_alt:
            data['baro_altitude_m'] = np.linspace(100, 10000, n)
        if add_vel:
            data['velocity'] = np.linspace(50, 230, n)
        return pd.DataFrame(data)

    check_pass("trajectory: normal veri",
               DataValidator.validate_trajectory(make_traj()))

    # Boş / None
    check_fail("trajectory: None",
               DataValidator.validate_trajectory(None))
    check_fail("trajectory: boş DataFrame",
               DataValidator.validate_trajectory(pd.DataFrame()))

    # Yetersiz satır
    check_fail("trajectory: 3 satır (min 5)",
               DataValidator.validate_trajectory(make_traj(n=3)))

    # Geçersiz koordinat
    bad_coord = make_traj()
    bad_coord.loc[0, 'latitude'] = 200  # geçersiz
    check_fail("trajectory: geçersiz latitude (200)",
               DataValidator.validate_trajectory(bad_coord))

    # Temizlenmiş veri
    tests += 1
    result = DataValidator.validate_trajectory(make_traj())
    if result.cleaned_data is not None:
        ok("trajectory: cleaned_data dolu")
    else:
        fail("trajectory: cleaned_data", "None döndü")

    # NaN ağırlıklı trajectory
    nan_traj = make_traj(n=20)
    nan_traj.loc[3:16, 'baro_altitude_m'] = np.nan  # %65 NaN
    result_nan = DataValidator.validate_trajectory(nan_traj)
    tests += 1
    if result_nan.warnings or not result_nan.is_valid:
        ok("trajectory: yüksek NaN → uyarı/hata")
    else:
        fail("trajectory: yüksek NaN", "uyarı beklendi")

    # ─── validate_flight_inputs ───────────────────────────
    check_pass("flight_inputs: normal",
               DataValidator.validate_flight_inputs(1560, 72000, 0.785, 35000))

    check_fail("flight_inputs: geçersiz mach",
               DataValidator.validate_flight_inputs(1560, 72000, 1.5, 35000))
    check_fail("flight_inputs: negatif mesafe",
               DataValidator.validate_flight_inputs(-100, 72000, 0.785))
    check_fail("flight_inputs: payload > weight",
               DataValidator.validate_flight_inputs(1560, 72000, 0.785,
                                                    payload_kg=80000))

    check_warning("flight_inputs: çok düşük irtifa",
                  DataValidator.validate_flight_inputs(1560, 72000, 0.785,
                                                       altitude_ft=500))

    # ─── validate_customer_dataframe ─────────────────────
    good_cdf = pd.DataFrame({
        'origin'     : ['LTFM', 'EGLL'],
        'destination': ['EGLL', 'LTFM'],
        'fuel_kg'    : [12500, 11800],
    })
    check_pass("customer_df: normal",
               DataValidator.validate_customer_dataframe(good_cdf))

    bad_cdf = pd.DataFrame({
        'origin': ['LTFM'],
        # destination ve fuel_kg eksik
    })
    check_fail("customer_df: eksik zorunlu sütun",
               DataValidator.validate_customer_dataframe(bad_cdf))

    neg_fuel_cdf = pd.DataFrame({
        'origin'     : ['LTFM'],
        'destination': ['EGLL'],
        'fuel_kg'    : [-1000],
    })
    check_fail("customer_df: negatif fuel_kg",
               DataValidator.validate_customer_dataframe(neg_fuel_cdf))

    # ─── quick_check ─────────────────────────────────────
    tests += 1
    info = DataValidator.quick_check(make_traj())
    if info['rows'] == 20 and 'columns' in info:
        ok("quick_check: çalışıyor")
    else:
        fail("quick_check", f"Beklenmeyen çıktı: {info}")

    tests += 1
    info_empty = DataValidator.quick_check(pd.DataFrame())
    if info_empty['rows'] == 0:
        ok("quick_check: boş DataFrame")
    else:
        fail("quick_check boş", f"{info_empty}")

    # ═══════════════════════════════════════════════════
    # PHYSICS VALIDATOR
    # ═══════════════════════════════════════════════════
    print("\n  [PhysicsValidator]")

    # ─── validate_aerodynamics ───────────────────────────
    # Not: CL=0.498 M0.785 DEFAULT buffet tablosuyla FAR 25.251 sınırını
    # aşabilir. B738 tablosu kullanarak test ediyoruz.
    check_pass("aerodynamics: normal cruise (B738)",
               PhysicsValidator.validate_aerodynamics(
                   CL=0.40, CD=0.029, L_D=13.8,
                   altitude_ft=35000, mach=0.785,
                   aircraft_type='B738'
               ))

    # Yüksek CL → buffet uyarısı
    result_high_cl = PhysicsValidator.validate_aerodynamics(
        CL=0.65, CD=0.042, L_D=15.5,
        altitude_ft=39000, mach=0.785,
        aircraft_type='B738'
    )
    tests += 1
    if result_high_cl.warnings or not result_high_cl.is_valid:
        ok("aerodynamics: yüksek CL → uyarı/hata")
    else:
        fail("aerodynamics yüksek CL", "uyarı beklendi")

    # Geçersiz değerler
    check_fail("aerodynamics: CL > 1.4",
               PhysicsValidator.validate_aerodynamics(
                   CL=1.5, CD=0.033, L_D=45.0,
                   altitude_ft=35000, mach=0.785
               ))

    # ─── [46] FAR 25.251 BOYUT DOĞRULAMASI ───────────────
    # DENETİM #46: Eski kod `cl_limit = cl_buffet_onset / 1.3`
    # kullanıyordu. Bu BOYUT HATASI: 1g buffet onset CL'i 0.62
    # olan kanat, 1.3g'de 1.3 KAT kaldırma üretir → izin verilen
    # 1g CL = 0.62 × 1.3 = 0.806. Bölünce 0.477 çıkıyor ve
    # B738'in NORMAL seyir CL'si (0.48–0.55) "güvensiz" oluyordu.
    #
    # Not: yukarıdaki "normal cruise" testi CL=0.40 kullanıyor —
    # tam da bu hata yüzünden düşürülmüş bir değer. Aşağıdaki
    # testler GERÇEK seyir CL'lerini kilitler.

    _bm_real = PhysicsValidator.check_buffet_margin(0.52, 0.785, 'B738')
    check_pass("buffet_margin: B738 gerçek seyir CL=0.52 (limit 0.806)", _bm_real)
    assert_check(
        "buffet FAR limiti = onset × 1.3",
        abs(_bm_real.stats['cl_limit_far25'] - 0.62 * 1.3) < 0.001,
        f"limit={_bm_real.stats['cl_limit_far25']}, beklenen={0.62*1.3:.3f}"
    )

    # Aynı CL, ama limit ONSET'i aşan bir uçuş → gerçekten hata olmalı
    _bm_over = PhysicsValidator.check_buffet_margin(0.85, 0.785, 'B738')
    check_fail("buffet_margin: CL=0.85 onset üstü hata", _bm_over)

    # Limit ile onset arasında: hata yok, uyarı var
    # Limit ile onset arası: HATA yok ama UYARI olmalı
    _bm_mid = PhysicsValidator.check_buffet_margin(0.78, 0.785, 'B738')
    assert_check(
        f"buffet_margin: CL=0.78 hata YOK "
        f"(marj %{_bm_mid.stats['buffet_margin_pct']})",
        _bm_mid.is_valid
    )
    assert_check(
        "buffet_margin: CL=0.78 uyarı var (1g onset üstü)",
        len(_bm_mid.warnings) > 0
    )
    # Onset altı: CL=0.52 hem geçerli hem UYARISIZ olmalı
    _bm_ok = PhysicsValidator.check_buffet_margin(0.52, 0.785, 'B738')
    assert_check("buffet_margin: CL=0.52 uyarısız", len(_bm_ok.warnings) == 0)

    # Yön kontrolü: CL arttıkça marj AZALMALI
    _m1 = PhysicsValidator.check_buffet_margin(0.40, 0.785, 'B738').stats['buffet_margin_pct']
    _m2 = PhysicsValidator.check_buffet_margin(0.60, 0.785, 'B738').stats['buffet_margin_pct']
    assert_check(
        f"buffet marjı CL ile azalıyor (%{_m1:.1f} > %{_m2:.1f})", _m1 > _m2)

    # Optimizer ile tutarlılık: ikisi de CL_onset'in ALTINDA limit vermeli
    # (optimizer 0.90×onset operasyonel; validator 1.3×onset FAR)
    # → FAR limiti daha gevşek olmalı, yoksa optimizer gereksiz kısıtlar
    _far_limit = _bm_real.stats['cl_limit_far25']
    assert_check(
        f"FAR limiti ({_far_limit:.3f}) operasyonel limitten (0.90×0.62=0.558) gevşek",
        _far_limit > 0.62 * 0.90
    )

    # ─── check_buffet_margin ─────────────────────────────
    # CL=0.35 düşük CL → buffet marjı rahat, B738 ile
    result_bm = PhysicsValidator.check_buffet_margin(0.35, 0.785, 'B738')
    check_pass("buffet_margin: düşük CL=0.35 B738", result_bm)

    # Yüksek CL sınırda
    result_bm_warn = PhysicsValidator.check_buffet_margin(0.55, 0.82, 'B738')
    tests += 1
    if result_bm_warn.warnings or not result_bm_warn.is_valid:
        ok("buffet_margin: yüksek CL M0.82 → uyarı/hata")
    else:
        fail("buffet_margin yüksek", "uyarı beklendi")

    # ─── validate_fuel_flow ──────────────────────────────
    check_pass("fuel_flow: B738 cruise normal",
               PhysicsValidator.validate_fuel_flow(2500, 'B738', 35000, 'cruise'))
    check_fail("fuel_flow: çok düşük (50 kg/hr)",
               PhysicsValidator.validate_fuel_flow(50, 'B738', 35000))
    check_fail("fuel_flow: çok yüksek (20000 kg/hr)",
               PhysicsValidator.validate_fuel_flow(20000, 'B738', 35000))

    # ─── validate_sar ────────────────────────────────────
    check_pass("SAR: B738 normal (0.097)",
               PhysicsValidator.validate_sar(0.097, 'B738', 35000, 0.785))
    check_fail("SAR: çok düşük (0.01)",
               PhysicsValidator.validate_sar(0.01))
    check_fail("SAR: çok yüksek (0.30)",
               PhysicsValidator.validate_sar(0.30))

    # ─── validate_atmosphere ─────────────────────────────
    check_pass("atmosphere: FL350 normal",
               PhysicsValidator.validate_atmosphere(
                   temperature_K=218.8, pressure_Pa=23842,
                   density_kg_m3=0.380, altitude_ft=35000
               ))
    check_fail("atmosphere: geçersiz sıcaklık",
               PhysicsValidator.validate_atmosphere(
                   temperature_K=100, pressure_Pa=23842,
                   density_kg_m3=0.380, altitude_ft=35000
               ))

    # ─── validate_flight_dynamics ────────────────────────
    check_pass("flight_dynamics: normal",
               PhysicsValidator.validate_flight_dynamics(1500, 0.785, 35000))
    check_fail("flight_dynamics: çok hızlı tırmanma",
               PhysicsValidator.validate_flight_dynamics(9000, 0.785, 35000))
    check_fail("flight_dynamics: mach > 0.95",
               PhysicsValidator.validate_flight_dynamics(0, 0.97, 35000))

    # ═══════════════════════════════════════════════════
    # BUSINESS VALIDATOR
    # ═══════════════════════════════════════════════════
    print("\n  [BusinessValidator]")

    # ─── validate_optimization_result ────────────────────
    check_pass("optimization: normal tasarruf",
               BusinessValidator.validate_optimization_result(
                   saving_kg=325, total_fuel_kg=12450,
                   annual_saving_usd=198000
               ))

    # Negatif tasarruf
    check_fail("optimization: negatif tasarruf",
               BusinessValidator.validate_optimization_result(
                   saving_kg=-100, total_fuel_kg=12450,
                   annual_saving_usd=-65000
               ))

    # Çok yüksek tasarruf oranı
    result_high = BusinessValidator.validate_optimization_result(
        saving_kg=3000, total_fuel_kg=12450,
        annual_saving_usd=1_000_000
    )
    tests += 1
    if not result_high.is_valid or result_high.warnings:
        ok("optimization: yüksek tasarruf → uyarı/hata")
    else:
        fail("optimization yüksek", "uyarı/hata beklendi")

    # ─── validate_mtow ───────────────────────────────────
    check_pass("MTOW: normal",
               BusinessValidator.validate_mtow(41413, 15000, 12500, 0, 'B738'))

    check_fail("MTOW: aşıldı",
               BusinessValidator.validate_mtow(41413, 15000, 18000, 5000, 'B738'))

    # MTOW'a yakın → uyarı
    result_near = BusinessValidator.validate_mtow(
        41413, 15000, 22000, 0, 'B738'  # ~78413, MTOW 79016
    )
    tests += 1
    if result_near.warnings or not result_near.is_valid:
        ok("MTOW: sınıra yakın → uyarı/hata")
    else:
        fail("MTOW yakın", "uyarı beklendi")

    # ─── validate_step_climb_plan ─────────────────────────
    good_plan = [
        {'distance': 400, 'from': 'FL350', 'to': 'FL370', 'net_saving': 85},
        {'distance': 900, 'from': 'FL370', 'to': 'FL390', 'net_saving': 60},
    ]
    check_pass("step_climb: normal plan",
               BusinessValidator.validate_step_climb_plan(good_plan, 1560))

    # Boş plan
    check_pass("step_climb: boş plan",
               BusinessValidator.validate_step_climb_plan([], 1560))

    # Çok fazla step
    many_steps = [
        {'distance': d, 'from': f'FL{310+i*20}', 'to': f'FL{330+i*20}',
         'net_saving': 50}
        for i, d in enumerate(range(200, 1400, 200))
    ]
    result_many = BusinessValidator.validate_step_climb_plan(many_steps, 1560)
    tests += 1
    if not result_many.is_valid:
        ok("step_climb: çok fazla step → FAIL")
    else:
        fail("step_climb fazla", "FAIL beklendi")

    # Çok kısa aralık
    short_interval = [
        {'distance': 300, 'from': 'FL350', 'to': 'FL370', 'net_saving': 80},
        {'distance': 350, 'from': 'FL370', 'to': 'FL390', 'net_saving': 50},
    ]
    check_fail("step_climb: çok kısa aralık (50 Nm)",
               BusinessValidator.validate_step_climb_plan(short_interval, 1560))

    # ─── validate_fuel_efficiency ────────────────────────
    co2 = 12500 * 3.16
    check_pass("fuel_efficiency: normal B738",
               BusinessValidator.validate_fuel_efficiency(
                   12500, 1560, co2, 'B738', 162
               ))

    # CO2 tutarsız
    result_co2 = BusinessValidator.validate_fuel_efficiency(
        12500, 1560, 25000, 'B738', 162  # CO2 çok düşük
    )
    tests += 1
    if result_co2.warnings or not result_co2.is_valid:
        ok("fuel_efficiency: CO2 tutarsız → uyarı")
    else:
        fail("fuel_efficiency CO2", "uyarı beklendi")

    # ─── validate_annual_projection ──────────────────────
    check_pass("annual_projection: normal",
               BusinessValidator.validate_annual_projection(
                   raw_annual_usd=305160, realistic_annual_usd=198354,
                   realization_factor=0.65, daily_flights=2
               ))

    # Gerçekçi > teorik
    check_fail("annual_projection: gerçekçi > teorik",
               BusinessValidator.validate_annual_projection(
                   raw_annual_usd=100000, realistic_annual_usd=200000,
                   realization_factor=0.65, daily_flights=2
               ))

    # Geçersiz RF
    check_fail("annual_projection: RF=1.5",
               BusinessValidator.validate_annual_projection(
                   raw_annual_usd=300000, realistic_annual_usd=200000,
                   realization_factor=1.5, daily_flights=2
               ))

    # ─── ValidationResult merge ──────────────────────────
    tests += 1
    r1 = ValidationResult()
    r1.add_error("Hata 1")
    r2 = ValidationResult()
    r2.add_warning("Uyarı 1")
    r1.merge(r2)
    if not r1.is_valid and r1.warnings:
        ok("ValidationResult.merge çalışıyor")
    else:
        fail("merge", "Beklenen durum yok")

    # ─── ValidationResult summary ────────────────────────
    tests += 1
    r = ValidationResult()
    r.add_error("test")
    s = r.summary()
    if "FAIL" in s:
        ok("ValidationResult.summary: FAIL gösteriyor")
    else:
        fail("summary", f"'FAIL' beklendi: {s}")

    # ═══════════════════════════════════════════════════
    # SONUÇ
    # ═══════════════════════════════════════════════════
    def assert_check(name: str, cond: bool, detail: str = '') -> None:
        if cond:
            ok(name)
        else:
            fail(name, detail)

    try:
        from src.models.fuel_model import FuelModel as _FM
    except Exception:
        _FM = None

    # ══ TIRMANIŞ CEZASI: GERÇEK B738 VERİSİYLE KIYAS ══════════
    print('\n── Tırmanış cezası (gerçek B738 kıyası) ──')
    try:
        from src.models.fuel_model import FuelModel as _FM
        _fm = _FM(aircraft_type='B738')

        # Gerçek: B738 FL350→FL370 @60 t
        #   tırmanış yakıtı ~260 kg, 18 nm yatay, seyir eşdeğeri ~95 kg
        #   NET ek ceza ~165-200 kg
        _pen = _fm.estimate_climb_fuel(35000, 37000, 60000, 0.78)
        assert_check(f'tırmanış cezası FL350→370 @60t = {_pen:.0f} kg (150-220)',
              150 <= _pen <= 220, f'{_pen:.0f} kg')

        _pen80 = _fm.estimate_climb_fuel(35000, 37000, 76000, 0.78)
        assert_check(f'ağır uçakta ceza daha yüksek', _pen80 > _pen)
        assert_check('tırmanış cezası negatif değil',
              _fm.estimate_climb_fuel(35000, 37000, 40000, 0.78) >= 0)
        assert_check('alçalma cezası 0',
              _fm.estimate_climb_fuel(37000, 35000, 60000, 0.78) == 0)
    except Exception as _e:
        assert_check('tırmanış cezası hesaplanabilir', False, repr(_e))

    # ══ STEP CLIMB KÂRLILIK FİZİĞİ ═════════════════════════════
    print('\n── Step climb kârlılık fiziği ──')
    try:
        from src.optimization.altitude_optimizer import AltitudeOptimizer as _AO
        _ao = _AO(aircraft_type='B738')

        _r1 = _ao._evaluate_step_climb(33000, 35000, 54000, 0.78, 1600)
        assert_check(f'hafif+uzun → kârlı (net={_r1["net_saving_kg"]:.0f} kg)',
              _r1['net_saving_kg'] >= 50)
        _r2 = _ao._evaluate_step_climb(35000, 37000, 74000, 0.78, 500)
        assert_check(f'ağır+kısa → kârsız (net={_r2["net_saving_kg"]:.0f} kg)',
              _r2['net_saving_kg'] < 0)
        _a = _ao._evaluate_step_climb(35000, 37000, 60000, 0.78, 600)['net_saving_kg']
        _b = _ao._evaluate_step_climb(35000, 37000, 60000, 0.78, 1400)['net_saving_kg']
        assert_check(f'kalan mesafe ↑ → tasarruf ↑ ({_a:.0f} → {_b:.0f})', _b > _a)
        _c = _ao._evaluate_step_climb(35000, 37000, 52000, 0.78, 1200)['net_saving_kg']
        _d = _ao._evaluate_step_climb(35000, 37000, 72000, 0.78, 1200)['net_saving_kg']
        assert_check(f'ağırlık ↑ → tasarruf ↓ ({_c:.0f} → {_d:.0f})', _c > _d)
    except Exception as _e:
        assert_check('step climb fiziği test edilebilir', False, repr(_e))

    print(f"\n  {'─' * 55}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print(f"\n  ❌ BAŞARISIZ TESTLER:")
        for i, e in enumerate(errors, 1):
            print(f"     {i}. {e}")
        return False

    print(f"\n  ✅ TÜM TESTLER BAŞARILI\n")
    return True


if __name__ == "__main__":
    run_all_tests()