# tests/test_logging.py

"""
GreenWing Analytics — Loglama ve İzlenebilirlik Testleri
═══════════════════════════════════════════════════════

Kapsamlı test süiti:

AnalysisTracer:
    1.  Temel oluşturma (ID, description)
    2.  Otomatik ID üretimi
    3.  log_input — tek girdi
    4.  log_input — birden fazla girdi
    5.  log_input — kaynak bilgisi
    6.  log_assumption — temel
    7.  log_assumption — uncertainty_pct
    8.  log_assumption — can_override
    9.  log_step — formül ve girdiler
    10. log_step — step_no sıralı
    11. log_step — modül bilgisi
    12. log_validation — PASS
    13. log_validation — WARNING → sayaç
    14. log_validation — FAIL → sayaç + has_errors
    15. log_uncertainty — temel
    16. log_uncertainty — lower/upper bound
    17. log_uncertainty — propagated_from
    18. log_optimization — karar gerekçesi
    19. log_optimization — alternatifler ve kısıtlar
    20. log_optimization — saving değerleri
    21. log_warning — temel
    22. log_warning — severity levels
    23. log_warning — action_required
    24. get_trace — tam yapı
    25. get_trace — summary alanları
    26. get_trace — has_fails
    27. get_trace_json — JSON serileştirme
    28. get_trace_json — numpy tip desteği
    29. save_trace — dosya yazma
    30. save_trace — klasör oluşturma
    31. save_trace — yükleme doğrulama
    32. print_summary — çalışıyor
    33. get_assumptions_report — içerik
    34. get_validation_report — PASS/FAIL gösteriyor
    35. get_uncertainty_summary — dominant
    36. has_errors / has_warnings property
    37. step_count property
    38. analysis_id property
    39. repr

Edge Cases:
    40. Boş tracer (hiç log yok)
    41. Çok uzun trace (50+ adım)
    42. Unicode karakter desteği
    43. Büyük sayı serileştirme

Çalıştırma:
    python tests/test_logging.py
    python -m pytest tests/test_logging.py -v
"""

import sys
import os
import json
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.logging_config import AnalysisTracer


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: logging_config.py — TAM TEST SÜİTİ")
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
                print(f"  ❌ {name}: {actual}")

    def check_true(name, condition):
        nonlocal tests
        tests += 1
        if condition:
            print(f"  ✅ {name}")
        else:
            errors.append(name)
            print(f"  ❌ {name}")

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 1: TEMEL OLUŞTURMA
    # ═══════════════════════════════════════════════════════
    print("\n  ── Temel Oluşturma ───────────────────────────────")

    # [1] ID ve description
    tracer = AnalysisTracer("TEST_001", "Doğrulama testi")
    check("[1a] analysis_id", tracer.analysis_id, "TEST_001")
    check_true("[1b] isinstance", isinstance(tracer, AnalysisTracer))

    # [2] Otomatik ID
    tracer_auto = AnalysisTracer()
    check_true(
        f"[2] Otomatik ID: {tracer_auto.analysis_id}",
        len(tracer_auto.analysis_id) > 0
    )
    check_true(
        "[2b] Farklı ID'ler",
        tracer.analysis_id != tracer_auto.analysis_id
    )

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 2: LOG_INPUT
    # ═══════════════════════════════════════════════════════
    print("\n  ── log_input ─────────────────────────────────────")

    # [3] Tek girdi
    tracer.log_input("weight_kg", 72000, "kg", "assumption:80%_load")
    check_true("[3] 1 input kaydedildi", len(tracer._inputs) == 1)

    # [4] Birden fazla girdi
    tracer.log_input("altitude_ft", 35000, "ft", "opensky_adsb")
    tracer.log_input("mach", 0.785, "", "aircraft_database")
    tracer.log_input("fuel_price", 0.78, "USD/kg", "assumption", "2025-Q1 tahmini")
    check_true("[4] 4 input kaydedildi", len(tracer._inputs) == 4)

    # [5] Kaynak bilgisi
    inp = tracer._inputs[0]
    check("[5a] name", inp['name'], "weight_kg")
    check("[5b] value", inp['value'], 72000, 0.01)
    check("[5c] unit", inp['unit'], "kg")
    check("[5d] source", inp['source'], "assumption:80%_load")
    check_true("[5e] timestamp var", 'timestamp' in inp and len(inp['timestamp']) > 0)

    # Not alanı
    inp4 = tracer._inputs[3]
    check("[5f] note", inp4['note'], "2025-Q1 tahmini")

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 3: LOG_ASSUMPTION
    # ═══════════════════════════════════════════════════════
    print("\n  ── log_assumption ────────────────────────────────")

    # [6] Temel varsayım
    tracer.log_assumption("payload_kg", 15000, "kg",
                          "150 pax × 100 kg, %80 doluluk",
                          uncertainty_pct=15.0)
    check_true("[6] 1 assumption kaydedildi", len(tracer._assumptions) == 1)

    # [7] uncertainty_pct
    asm = tracer._assumptions[0]
    check("[7] uncertainty_pct", asm['uncertainty_pct'], 15.0, 0.01)

    # [8] can_override
    tracer.log_assumption("realization_factor", 0.65, "",
                          "Varsayılan", uncertainty_pct=15.0,
                          can_override=True)
    asm2 = tracer._assumptions[1]
    check_true("[8] can_override = True", asm2['can_override'] == True)
    check("[8b] value", asm2['value'], 0.65, 0.001)
    check_true("[8c] rationale var", len(asm2['rationale']) > 0)

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 4: LOG_STEP
    # ═══════════════════════════════════════════════════════
    print("\n  ── log_step ──────────────────────────────────────")

    # [9] Formül ve girdiler
    tracer.log_step(
        "cruise_fuel_flow",
        formula="FF = SFC × Drag",
        inputs={"SFC_kg_Ns": 0.0000184, "Drag_N": 35420},
        outputs={"fuel_flow_kg_s": 0.652, "fuel_flow_kg_hr": 2347},
        module="fuel_model"
    )
    check_true("[9] 1 step kaydedildi", len(tracer._steps) == 1)

    step = tracer._steps[0]
    check("[9b] step_name", step['step_name'], "cruise_fuel_flow")
    check("[9c] formula", step['formula'], "FF = SFC × Drag")
    check_true("[9d] inputs dict", 'SFC_kg_Ns' in step['inputs'])
    check_true("[9e] outputs dict", 'fuel_flow_kg_hr' in step['outputs'])
    check("[9f] module", step['module'], "fuel_model")

    # [10] step_no sıralı
    tracer.log_step("sar_calc", formula="SAR=V/FF",
                    inputs={"V": 230}, outputs={"SAR": 0.097})
    tracer.log_step("annual_proj", formula="annual=pf×df×od×rf",
                    inputs={"pf": 442}, outputs={"annual": 198354})

    check("[10a] step_no 1", tracer._steps[0]['step_no'], 1, 0.01)
    check("[10b] step_no 2", tracer._steps[1]['step_no'], 2, 0.01)
    check("[10c] step_no 3", tracer._steps[2]['step_no'], 3, 0.01)

    # [11] step_count property
    check("[11] step_count", tracer.step_count, 3, 0.01)

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 5: LOG_VALIDATION
    # ═══════════════════════════════════════════════════════
    print("\n  ── log_validation ────────────────────────────────")

    # [12] PASS
    tracer.log_validation("PhysicsValidator", "CL_range", "PASS",
                          value=0.498, expected_range="[0.01, 1.5]",
                          detail="Normal cruise CL")
    check_true("[12] 1 validation kaydedildi", len(tracer._validations) == 1)

    # [13] WARNING → sayaç
    initial_warn = tracer._warning_count
    tracer.log_validation("BusinessValidator", "buffet_margin", "WARNING",
                          value=12.3, expected_range=">15%",
                          detail="Düşük buffet marjı")
    check_true(
        f"[13] warning_count artı: {tracer._warning_count} > {initial_warn}",
        tracer._warning_count > initial_warn
    )

    # [14] FAIL → sayaç + has_errors
    initial_err = tracer._error_count
    tracer.log_validation("BusinessValidator", "MTOW_check", "FAIL",
                          value=80500, expected_range="≤79016",
                          detail="MTOW aşıldı!")
    check_true(
        f"[14a] error_count arttı: {tracer._error_count} > {initial_err}",
        tracer._error_count > initial_err
    )
    check_true("[14b] has_errors = True", tracer.has_errors)
    check_true("[14c] has_warnings = True", tracer.has_warnings)

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 6: LOG_UNCERTAINTY
    # ═══════════════════════════════════════════════════════
    print("\n  ── log_uncertainty ───────────────────────────────")

    # [15] Temel
    tracer.log_uncertainty("estimated_fuel_kg", 12450, 8.0,
                           "Ağırlık ±5% + SFC ±3%",
                           propagated_from=["weight_kg", "sfc_factor"])
    check_true("[15] 1 uncertainty kaydedildi", len(tracer._uncertainties) == 1)

    # [16] lower/upper bound
    unc = tracer._uncertainties[0]
    check("[16a] value", unc['value'], 12450, 1.0)
    check("[16b] uncertainty_pct", unc['uncertainty_pct'], 8.0, 0.01)

    expected_lower = 12450 * (1 - 8.0 / 100)
    expected_upper = 12450 * (1 + 8.0 / 100)
    check("[16c] lower_bound", unc['lower_bound'], expected_lower, 1.0)
    check("[16d] upper_bound", unc['upper_bound'], expected_upper, 1.0)
    check_true("[16e] lower < value < upper",
               unc['lower_bound'] < unc['value'] < unc['upper_bound'])

    # [17] propagated_from
    check_true(
        "[17] propagated_from: weight_kg + sfc_factor",
        'weight_kg' in unc.get('propagated_from', []) and
        'sfc_factor' in unc.get('propagated_from', [])
    )

    tracer.log_uncertainty("annual_saving", 198354, 22.0,
                           "Yakıt ±8% + RF ±15%",
                           propagated_from=["fuel", "realization_factor"])
    check_true("[17b] 2 uncertainty", len(tracer._uncertainties) == 2)

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 7: LOG_OPTIMIZATION
    # ═══════════════════════════════════════════════════════
    print("\n  ── log_optimization ──────────────────────────────")

    # [18] Karar gerekçesi
    tracer.log_optimization(
        opt_type="altitude",
        selected="FL380",
        reason="Max Ground SAR. Rüzgar dahil FL380 en iyi.",
        saving_kg=180, saving_usd=153,
    )
    check_true("[18] 1 optimization kaydedildi", len(tracer._optimizations) == 1)

    opt = tracer._optimizations[0]
    check("[18b] opt_type", opt['opt_type'], "altitude")
    check("[18c] selected", opt['selected'], "FL380")
    check_true("[18d] reason var", len(opt['reason']) > 0)

    # [19] Alternatifler ve kısıtlar
    tracer.log_optimization(
        opt_type="step_climb",
        selected="FL350→FL370 @ 400Nm",
        reason="Ağırlık azaldı, SAR iyileşti.",
        alternatives={"FL360": 0.0951, "FL370": 0.0968, "FL380": 0.0972},
        constraints_applied=["RVSM westbound", "Buffet %12.3"],
        saving_kg=145, saving_usd=123,
    )
    opt2 = tracer._optimizations[1]
    check_true("[19a] alternatives var", len(opt2['alternatives']) >= 2)
    check_true("[19b] constraints var", len(opt2['constraints_applied']) >= 1)

    # [20] Saving değerleri
    check("[20a] saving_kg", opt['saving_kg'], 180, 0.01)
    check("[20b] saving_usd", opt['saving_usd'], 153, 0.01)

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 8: LOG_WARNING
    # ═══════════════════════════════════════════════════════
    print("\n  ── log_warning ───────────────────────────────────")

    # [21] Temel
    tracer.log_warning("Buffet marjı düşük: %12.3")
    check_true("[21] warning kaydedildi", len(tracer._warnings) >= 1)

    # [22] Severity
    tracer.log_warning("RF varsayılan 0.65 kullanılıyor", severity="INFO")
    tracer.log_warning("MTOW sınırına çok yakın!", severity="CRITICAL",
                       action_required=True)

    warn_last = tracer._warnings[-1]
    check("[22a] severity", warn_last['severity'], "CRITICAL")

    # [23] action_required
    check_true("[23] action_required = True", warn_last['action_required'] == True)

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 9: GET_TRACE
    # ═══════════════════════════════════════════════════════
    print("\n  ── get_trace ─────────────────────────────────────")

    # [24] Tam yapı
    trace = tracer.get_trace()
    required_sections = ['meta', 'summary', 'inputs', 'assumptions',
                         'steps', 'validations', 'uncertainties',
                         'optimizations', 'warnings']
    missing = [s for s in required_sections if s not in trace]
    check_true(
        f"[24] {len(required_sections)} bölüm var",
        len(missing) == 0
    )
    if missing:
        print(f"      Eksik: {missing}")

    # [25] Summary alanları
    summ = trace['summary']
    check("[25a] total_inputs", summ['total_inputs'], 4, 0.01)
    check("[25b] total_assumptions", summ['total_assumptions'], 2, 0.01)
    check("[25c] total_steps", summ['total_steps'], 3, 0.01)
    check("[25d] total_validations", summ['total_validations'], 3, 0.01)
    check("[25e] total_uncertainties", summ['total_uncertainties'], 2, 0.01)
    check("[25f] total_optimizations", summ['total_optimizations'], 2, 0.01)

    # [26] has_fails
    check_true("[26] has_fails = True", summ['has_fails'] == True)

    # Meta bilgileri
    meta = trace['meta']
    check("[26b] analysis_id", meta['analysis_id'], "TEST_001")
    check_true("[26c] started_at var", len(meta['started_at']) > 0)
    check_true("[26d] completed_at var", len(meta['completed_at']) > 0)
    check_true("[26e] system_version var", len(meta['system_version']) > 0)

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 10: JSON SERİLEŞTİRME
    # ═══════════════════════════════════════════════════════
    print("\n  ── JSON Serileştirme ──────────────────────────────")

    # [27] JSON string
    json_str = tracer.get_trace_json()
    check_true("[27a] JSON string > 0", len(json_str) > 100)

    # Parse edilebilir mi?
    parsed = json.loads(json_str)
    check_true("[27b] JSON parse edilebilir", parsed['meta']['analysis_id'] == "TEST_001")

    # [28] numpy tip desteği
    tracer2 = AnalysisTracer("TEST_NP")
    tracer2.log_input("np_int", np.int64(35000), "ft", "test")
    tracer2.log_input("np_float", np.float64(0.785), "", "test")
    tracer2.log_input("np_array", np.array([1.0, 2.0, 3.0]), "", "test")
    tracer2.log_input("np_bool", np.bool_(True), "", "test")

    try:
        js2 = tracer2.get_trace_json()
        json.loads(js2)
        tests += 1
        print("  ✅ [28] numpy tipler JSON'a serileşti")
    except Exception as e:
        tests += 1
        errors.append(f"[28] numpy JSON: {e}")
        print(f"  ❌ [28] numpy JSON: {e}")

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 11: DOSYA KAYDETME
    # ═══════════════════════════════════════════════════════
    print("\n  ── Dosya Kaydetme ────────────────────────────────")

    # [29] Dosyaya yaz
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "sub", "test_trace.json")

        # [30] Klasör otomatik oluşturulur
        saved_path = tracer.save_trace(filepath)
        check_true("[29] Dosya oluşturuldu", os.path.exists(saved_path))

        check_true("[30] Alt klasör oluşturuldu", os.path.exists(os.path.dirname(saved_path)))

        # [31] Yükleme doğrulama
        with open(saved_path, encoding='utf-8') as f:
            loaded = json.load(f)

        check_true(
            "[31a] Yüklenen ID doğru",
            loaded['meta']['analysis_id'] == "TEST_001"
        )
        check_true(
            "[31b] Yüklenen inputs var",
            len(loaded['inputs']) == 4
        )

        size_kb = os.path.getsize(saved_path) / 1024
        check_true(f"[31c] Dosya boyutu: {size_kb:.1f} KB", size_kb > 0)

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 12: PRINT_SUMMARY
    # ═══════════════════════════════════════════════════════
    print("\n  ── print_summary ─────────────────────────────────")

    # [32]
    try:
        tracer.print_summary()
        tests += 1
        print("  ✅ [32] print_summary çalışıyor")
    except Exception as e:
        tests += 1
        errors.append(f"[32] print_summary: {e}")
        print(f"  ❌ [32] print_summary: {e}")

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 13: RAPOR METODLARI
    # ═══════════════════════════════════════════════════════
    print("\n  ── Rapor Metodları ───────────────────────────────")

    # [33] Assumptions report
    asm_report = tracer.get_assumptions_report()
    check_true(
        "[33a] assumptions report > 50 karakter",
        len(asm_report) > 50
    )
    check_true(
        "[33b] 'VARSAYIMLAR' veya 'payload' içeriyor",
        'payload' in asm_report.lower() or 'varsayım' in asm_report.lower()
    )

    # [34] Validation report
    val_report = tracer.get_validation_report()
    check_true("[34a] 'PASS' içeriyor", 'PASS' in val_report)
    check_true("[34b] 'FAIL' içeriyor", 'FAIL' in val_report)
    check_true("[34c] '✅' veya '❌' içeriyor", '✅' in val_report or '❌' in val_report)

    # [35] Uncertainty summary
    unc_sum = tracer.get_uncertainty_summary()
    check("[35a] max_uncertainty_pct", unc_sum['max_uncertainty_pct'], 22.0, 0.01)
    check_true(
        f"[35b] dominant_parameter var: {unc_sum.get('dominant_parameter', '')}",
        'dominant_parameter' in unc_sum
    )
    check_true(
        "[35c] uncertainties listesi var",
        len(unc_sum.get('uncertainties', [])) == 2
    )

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 14: PROPERTY'LER
    # ═══════════════════════════════════════════════════════
    print("\n  ── Property'ler ──────────────────────────────────")

    # [36] has_errors / has_warnings
    check_true("[36a] has_errors = True", tracer.has_errors)
    check_true("[36b] has_warnings = True", tracer.has_warnings)

    # Temiz tracer
    clean = AnalysisTracer("CLEAN")
    check_true("[36c] Clean has_errors = False", not clean.has_errors)
    check_true("[36d] Clean has_warnings = False", not clean.has_warnings)

    # [37] step_count
    check("[37] step_count", tracer.step_count, 3, 0.01)

    # [38] analysis_id
    check("[38] analysis_id", tracer.analysis_id, "TEST_001")

    # [39] repr
    r = repr(tracer)
    check_true("[39a] 'AnalysisTracer' in repr", 'AnalysisTracer' in r)
    check_true("[39b] 'TEST_001' in repr", 'TEST_001' in r)
    check_true("[39c] 'steps' in repr", 'steps' in r)

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 15: EDGE CASES
    # ═══════════════════════════════════════════════════════
    print("\n  ── Edge Cases ────────────────────────────────────")

    # [40] Boş tracer
    empty = AnalysisTracer("EMPTY")
    empty_trace = empty.get_trace()
    check("[40a] Boş inputs", empty_trace['summary']['total_inputs'], 0, 0.01)
    check("[40b] Boş steps", empty_trace['summary']['total_steps'], 0, 0.01)
    check_true("[40c] Boş has_fails = False", empty_trace['summary']['has_fails'] == False)

    try:
        empty.print_summary()
        tests += 1
        print("  ✅ [40d] Boş print_summary çalışıyor")
    except Exception as e:
        tests += 1
        errors.append(f"[40d] Boş print_summary: {e}")

    empty_asm = empty.get_assumptions_report()
    check_true("[40e] Boş assumptions report", len(empty_asm) > 0)

    empty_val = empty.get_validation_report()
    check_true("[40f] Boş validation report", len(empty_val) > 0)

    empty_unc = empty.get_uncertainty_summary()
    check("[40g] Boş max_unc = 0", empty_unc['max_uncertainty_pct'], 0.0, 0.01)

    # [41] Çok uzun trace (50+ adım)
    long_tracer = AnalysisTracer("LONG")
    for i in range(50):
        long_tracer.log_step(
            f"step_{i}",
            formula=f"y = f(x_{i})",
            inputs={f"x_{i}": float(i)},
            outputs={f"y_{i}": float(i * 2)},
        )
    check("[41a] 50 step", long_tracer.step_count, 50, 0.01)

    try:
        long_json = long_tracer.get_trace_json()
        json.loads(long_json)
        tests += 1
        print(f"  ✅ [41b] 50 step JSON: {len(long_json):,} karakter")
    except Exception as e:
        tests += 1
        errors.append(f"[41b] Uzun JSON: {e}")

    # [42] Unicode karakter
    unicode_tracer = AnalysisTracer("UNICODE")
    unicode_tracer.log_input("sıcaklık", 15.0, "°C", "ISA")
    unicode_tracer.log_assumption("ağırlık", 72000, "kg", "Varsayılan ağırlık tahmini")
    unicode_tracer.log_warning("İrtifa çok yüksek — dikkat!")

    try:
        uc_json = unicode_tracer.get_trace_json()
        parsed_uc = json.loads(uc_json)
        tests += 1
        if parsed_uc['inputs'][0]['name'] == 'sıcaklık':
            print("  ✅ [42] Unicode desteği çalışıyor")
        else:
            errors.append("[42] Unicode kayıp")
            print("  ❌ [42] Unicode kayıp")
    except Exception as e:
        tests += 1
        errors.append(f"[42] Unicode: {e}")

    # [43] Büyük sayı
    big_tracer = AnalysisTracer("BIG")
    big_tracer.log_input("huge", 1_234_567_890, "kg", "test")
    big_tracer.log_input("tiny", 0.000000001, "kg/(N·s)", "test")

    try:
        big_json = big_tracer.get_trace_json()
        parsed_big = json.loads(big_json)
        tests += 1
        print(f"  ✅ [43] Büyük/küçük sayı serileşti")
    except Exception as e:
        tests += 1
        errors.append(f"[43] Büyük sayı: {e}")

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
