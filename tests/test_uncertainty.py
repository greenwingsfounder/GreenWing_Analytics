# tests/test_uncertainty.py

"""
GreenWing Analytics — Belirsizlik Takibi Testleri
══════════════════════════════════════════════════

Kapsamlı test süiti:

UncertainValue:
    1.  Temel oluşturma (value, pct, abs, lower, upper)
    2.  Confidence range
    3.  Scalar çarpma — değer
    4.  Scalar çarpma — belirsizlik korunur
    5.  Scalar çarpma — birim ve kaynak
    6.  Belirsiz × belirsiz — değer
    7.  Belirsiz × belirsiz — birleşik belirsizlik √(a²+b²)
    8.  Bölme — değer
    9.  Bölme — birleşik belirsizlik
    10. Sıfıra bölme → unc=999
    11. Toplama — değer
    12. Toplama — mutlak belirsizlik yayılımı
    13. Çıkarma — değer
    14. Çıkarma — belirsizlik büyür (katastrofik iptal)
    15. Negatif belirsizlik → mutlak değer alınır
    16. Sıfır değer — uncertainty_abs = 0
    17. to_dict — gerekli alanlar
    18. __str__ formatı (±, %)
    19. __repr__ formatı
    20. Zincir hesaplama: weight → fuel → CO₂ → cost
    21. Zincir: belirsizlik büyüme yönü

UncertaintyTracker:
    22. Temel oluşturma
    23. track() — adım ekleme
    24. get_summary() — total_steps
    25. get_summary() — max_uncertainty_pct
    26. get_summary() — dominant_step
    27. get_summary() — growth_factor
    28. get_summary() — note var
    29. print_chain() — çalışıyor
    30. get_dominant_source()
    31. clear() — sıfırlama
    32. Boş tracker — summary
    33. step_count property
    34. repr

Edge Cases:
    35. Çok büyük değer formatı
    36. Çok küçük değer formatı
    37. %100 belirsizlik
    38. Sıfır belirsizlik (%0)
    39. Uzun zincir (8+ adım)
    40. Birden fazla belirsizlik kaynağı sıralaması

Çalıştırma:
    python tests/test_uncertainty.py
    python -m pytest tests/test_uncertainty.py -v
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.analysis.uncertainty import UncertainValue, UncertaintyTracker


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: uncertainty.py — TAM TEST SÜİTİ")
    print("=" * 60)

    errors = []
    tests  = 0

    def check(name, actual, expected, tol=0.1):
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
    # BÖLÜM 1: UNCERTAINVALUE
    # ═══════════════════════════════════════════════════════
    print("\n  ── UncertainValue ─────────────────────────────────")

    # ─── 1. TEMEL OLUŞTURMA ──────────────────────────────
    print("\n  [1] Temel Oluşturma")

    fuel = UncertainValue(12450, 8.0, "model_estimate", "kg")

    check("[1a] value", fuel.value, 12450, 0.01)
    check("[1b] uncertainty_pct", fuel.uncertainty_pct, 8.0, 0.01)
    check("[1c] uncertainty_abs", fuel.uncertainty_abs, 996.0, 1.0)
    check("[1d] lower_bound", fuel.lower_bound, 11454.0, 1.0)
    check("[1e] upper_bound", fuel.upper_bound, 13446.0, 1.0)

    # Fiziksel tutarlılık
    check_true(
        "[1f] lower < value < upper",
        fuel.lower_bound < fuel.value < fuel.upper_bound
    )
    check_true(
        "[1g] abs = value × pct / 100",
        abs(fuel.uncertainty_abs - fuel.value * 8.0 / 100) < 0.01
    )

    # ─── 2. CONFIDENCE RANGE ─────────────────────────────
    print("\n  [2] Confidence Range")

    lo, hi = fuel.confidence_range()
    check("[2a] lo = lower_bound", lo, fuel.lower_bound, 0.01)
    check("[2b] hi = upper_bound", hi, fuel.upper_bound, 0.01)
    check_true("[2c] lo < hi", lo < hi)

    # ─── 3. SCALAR ÇARPMA — DEĞER ────────────────────────
    print("\n  [3] Scalar Çarpma — Değer")

    co2 = fuel.multiply_scalar(3.16, result_unit="kg CO2")
    check("[3a] co2 value", co2.value, 12450 * 3.16, 1.0)

    cost = fuel.multiply_scalar(0.85, result_unit="USD")
    check("[3b] cost value", cost.value, 12450 * 0.85, 1.0)

    # Negatif scalar
    neg = fuel.multiply_scalar(-1)
    check("[3c] negatif scalar value", neg.value, -12450, 0.01)

    # Sıfır scalar
    zero = fuel.multiply_scalar(0)
    check("[3d] sıfır scalar", zero.value, 0.0, 0.01)

    # ─── 4. SCALAR ÇARPMA — BELİRSİZLİK KORUNUR ─────────
    print("\n  [4] Scalar Çarpma — Belirsizlik Korunur")

    check("[4a] co2 unc = fuel unc", co2.uncertainty_pct, 8.0, 0.01)
    check("[4b] cost unc = fuel unc", cost.uncertainty_pct, 8.0, 0.01)

    # CO₂ güven aralığı
    co2_lo, co2_hi = co2.confidence_range()
    check("[4c] co2 lower", co2_lo, fuel.lower_bound * 3.16, 5.0)
    check("[4d] co2 upper", co2_hi, fuel.upper_bound * 3.16, 5.0)

    # ─── 5. SCALAR ÇARPMA — BİRİM VE KAYNAK ─────────────
    print("\n  [5] Scalar Çarpma — Birim ve Kaynak")

    check_true("[5a] co2 unit = 'kg CO2'", co2.unit == "kg CO2")
    check_true("[5b] cost unit = 'USD'", cost.unit == "USD")
    check_true(
        "[5c] co2 source contains fuel source",
        "model_estimate" in co2.source or "3.16" in co2.source
    )

    # ─── 6. BELİRSİZ × BELİRSİZ — DEĞER ─────────────────
    print("\n  [6] Belirsiz × Belirsiz — Değer")

    price = UncertainValue(0.85, 3.0, "price", "USD/kg")
    total_cost = fuel.multiply(price, result_unit="USD")
    check("[6a] cost value", total_cost.value, 12450 * 0.85, 1.0)

    distance = UncertainValue(1560, 2.0, "GPS", "Nm")
    fuel_nm = fuel.divide(distance, result_unit="kg/Nm")
    check("[6b] fuel/Nm value", fuel_nm.value, 12450 / 1560, 0.01)

    # ─── 7. BELİRSİZ × BELİRSİZ — BİRLEŞİK ─────────────
    print("\n  [7] Belirsiz × Belirsiz — Birleşik Belirsizlik")

    # √(8² + 3²) = √(64 + 9) = √73 ≈ 8.544
    expected_unc = float(np.sqrt(8**2 + 3**2))
    check(
        "[7a] fuel×price unc = √(8²+3²)",
        total_cost.uncertainty_pct,
        expected_unc,
        0.1
    )

    # Bağımsız hatalar kare kök toplamı ilişkisi
    check_true(
        "[7b] Birleşik unc > her ikisinden büyük",
        total_cost.uncertainty_pct > fuel.uncertainty_pct and
        total_cost.uncertainty_pct > price.uncertainty_pct
    )

    check_true(
        "[7c] Birleşik unc < ikisinin toplamı",
        total_cost.uncertainty_pct < fuel.uncertainty_pct + price.uncertainty_pct
    )

    # ─── 8. BÖLME — DEĞER ────────────────────────────────
    print("\n  [8] Bölme — Değer")

    check("[8a] fuel/distance value", fuel_nm.value, 12450 / 1560, 0.01)

    # Büyük / küçük
    big   = UncertainValue(1000, 5.0, "big")
    small = UncertainValue(10, 5.0, "small")
    div_result = big.divide(small)
    check("[8b] 1000/10", div_result.value, 100.0, 0.01)

    # ─── 9. BÖLME — BİRLEŞİK BELİRSİZLİK ────────────────
    print("\n  [9] Bölme — Birleşik Belirsizlik")

    # √(8² + 2²) = √(64 + 4) = √68 ≈ 8.246
    expected_div_unc = float(np.sqrt(8**2 + 2**2))
    check(
        "[9a] fuel/distance unc = √(8²+2²)",
        fuel_nm.uncertainty_pct,
        expected_div_unc,
        0.2
    )

    # ─── 10. SIFIRA BÖLME ────────────────────────────────
    print("\n  [10] Sıfıra Bölme")

    zero_val = UncertainValue(0, 0, "zero")
    div_zero = fuel.divide(zero_val)
    check("[10a] Sıfıra bölme unc=999", div_zero.uncertainty_pct, 999, 0.01)

    # Sonuç sıfır olmalı
    check("[10b] Sıfıra bölme value=0", div_zero.value, 0.0, 0.01)

    # ─── 11. TOPLAMA — DEĞER ─────────────────────────────
    print("\n  [11] Toplama — Değer")

    a = UncertainValue(8000, 5.0, "cruise", "kg")
    b = UncertainValue(4000, 10.0, "non_cruise", "kg")
    total = a.add(b, result_unit="kg")

    check("[11a] 8000+4000", total.value, 12000, 0.01)
    check_true("[11b] total unit = 'kg'", total.unit == "kg")

    # Sıfır ekleme
    zero_add = UncertainValue(0, 0)
    same = a.add(zero_add)
    check("[11c] a + 0 = a", same.value, a.value, 0.01)

    # ─── 12. TOPLAMA — MUTLAK BELİRSİZLİK YAYILIMI ──────
    print("\n  [12] Toplama — Mutlak Belirsizlik Yayılımı")

    abs_a = 8000 * 5.0 / 100    # 400
    abs_b = 4000 * 10.0 / 100   # 400
    expected_abs = float(np.sqrt(abs_a**2 + abs_b**2))
    expected_pct = expected_abs / 12000 * 100

    check(
        "[12a] add uncertainty_pct",
        total.uncertainty_pct,
        expected_pct,
        0.5
    )

    # Toplama'da belirsizlik, bileşenlerden büyük mü?
    # (mutlak birleşim = kare kök, göreceli büyük olabilir)
    check_true(
        "[12b] Toplam abs unc > en büyük bileşen abs unc",
        total.uncertainty_abs > max(a.uncertainty_abs, b.uncertainty_abs)
    )

    # ─── 13. ÇIKARMA — DEĞER ─────────────────────────────
    print("\n  [13] Çıkarma — Değer")

    actual_fuel  = UncertainValue(12450, 8.0, "actual", "kg")
    optimal_fuel = UncertainValue(11800, 8.0, "optimal", "kg")
    saving = actual_fuel.subtract(optimal_fuel, result_unit="kg")

    check("[13a] 12450-11800", saving.value, 650, 0.01)

    # ─── 14. ÇIKARMA — BELİRSİZLİK BÜYÜR ────────────────
    print("\n  [14] Çıkarma — Belirsizlik Büyür")

    # Katastrofik iptal: birbirine yakın değerlerin çıkarmasında
    # göreceli belirsizlik büyür
    check_true(
        f"[14a] Saving unc({saving.uncertainty_pct:.1f}%) > "
        f"Actual unc({actual_fuel.uncertainty_pct:.1f}%)",
        saving.uncertainty_pct > actual_fuel.uncertainty_pct
    )

    # Mutlak belirsizlik toplamı (bağımsız hatalar)
    abs_actual  = actual_fuel.uncertainty_abs
    abs_optimal = optimal_fuel.uncertainty_abs
    expected_abs_diff = float(np.sqrt(abs_actual**2 + abs_optimal**2))
    check(
        "[14b] Çıkarma abs unc = √(a²+b²)",
        saving.uncertainty_abs,
        expected_abs_diff,
        5.0
    )

    # ─── 15. NEGATİF BELİRSİZLİK ─────────────────────────
    print("\n  [15] Negatif Belirsizlik → Mutlak Değer")

    neg_unc = UncertainValue(100, -5.0, "test")
    check_true(
        "[15a] Negatif unc → pozitif",
        neg_unc.uncertainty_pct == 5.0
    )
    check_true(
        "[15b] uncertainty_abs > 0",
        neg_unc.uncertainty_abs > 0
    )

    # ─── 16. SIFIR DEĞER ─────────────────────────────────
    print("\n  [16] Sıfır Değer")

    zero_v = UncertainValue(0, 5.0, "zero_test")
    check("[16a] value = 0", zero_v.value, 0.0, 0.01)
    check("[16b] uncertainty_abs = 0 × 0.05 = 0", zero_v.uncertainty_abs, 0.0, 0.01)
    check("[16c] lower = upper = 0", zero_v.lower_bound, zero_v.upper_bound, 0.01)

    # ─── 17. TO_DICT ─────────────────────────────────────
    print("\n  [17] to_dict")

    d = fuel.to_dict()
    required_keys = ['value', 'uncertainty_pct', 'uncertainty_abs',
                     'lower_bound', 'upper_bound', 'unit', 'source']
    for key in required_keys:
        check_true(f"[17] '{key}' in dict", key in d)

    # Değerler doğru
    check("[17b] dict value", d['value'], 12450, 1.0)
    check("[17c] dict lower", d['lower_bound'], fuel.lower_bound, 1.0)

    # ─── 18. STR FORMATI ─────────────────────────────────
    print("\n  [18] __str__ Formatı")

    s = str(fuel)
    check_true("[18a] '±' in str", '±' in s)
    check_true("[18b] '8.0%' in str", '8.0%' in s)
    check_true("[18c] '12,450' in str", '12,450' in s or '12450' in s)

    # Küçük değer
    small_uv = UncertainValue(0.097, 5.0, "sar", "Nm/kg")
    s_small = str(small_uv)
    check_true("[18d] Küçük değer '0.097' in str", '0.097' in s_small)

    # ─── 19. REPR FORMATI ────────────────────────────────
    print("\n  [19] __repr__ Formatı")

    r = repr(fuel)
    check_true("[19a] 'UncertainValue' in repr", 'UncertainValue' in r)
    check_true("[19b] '8.0' in repr", '8.0' in r)
    check_true("[19c] 'kg' in repr", 'kg' in r)

    # ─── 20. ZİNCİR HESAPLAMA ────────────────────────────
    print("\n  [20] Zincir Hesaplama: weight → fuel → CO₂ → cost")

    weight_uv = UncertainValue(72000, 5.0, "weight_assumption", "kg")
    fuel_uv   = UncertainValue(12450, 8.0, "fuel_model", "kg")

    co2_uv  = fuel_uv.multiply_scalar(3.16, result_unit="kg CO2",
                                       result_source="CO2=fuel×3.16")
    cost_uv = fuel_uv.multiply_scalar(0.85, result_unit="USD",
                                       result_source="cost=fuel×price")

    # CO₂ belirsizliği = yakıt belirsizliği (sabit çarpan)
    check("[20a] CO₂ unc = fuel unc", co2_uv.uncertainty_pct, 8.0, 0.01)

    # Cost belirsizliği = yakıt belirsizliği
    check("[20b] cost unc = fuel unc", cost_uv.uncertainty_pct, 8.0, 0.01)

    # Güven aralıkları ölçekleniyor mu?
    check(
        "[20c] CO₂ lower = fuel lower × 3.16",
        co2_uv.lower_bound,
        fuel_uv.lower_bound * 3.16,
        5.0
    )

    # ─── 21. ZİNCİR: BELİRSİZLİK BÜYÜME YÖNÜ ────────────
    print("\n  [21] Zincir: Belirsizlik Büyüme Yönü")

    # fuel × price (iki belirsiz değer) → belirsizlik artmalı
    fuel_a  = UncertainValue(12450, 8.0, "fuel", "kg")
    price_a = UncertainValue(0.85, 3.0, "price", "USD/kg")
    cost_a  = fuel_a.multiply(price_a, result_unit="USD")

    check_true(
        f"[21a] Combined unc({cost_a.uncertainty_pct:.2f}) > "
        f"fuel unc({fuel_a.uncertainty_pct:.2f})",
        cost_a.uncertainty_pct > fuel_a.uncertainty_pct
    )
    check_true(
        f"[21b] Combined unc({cost_a.uncertainty_pct:.2f}) > "
        f"price unc({price_a.uncertainty_pct:.2f})",
        cost_a.uncertainty_pct > price_a.uncertainty_pct
    )

    # Çıkarma'da belirsizlik en çok büyür (katastrofik iptal)
    close_a = UncertainValue(12450, 8.0, "a", "kg")
    close_b = UncertainValue(12400, 8.0, "b", "kg")  # Çok yakın!
    diff_ab = close_a.subtract(close_b)
    check_true(
        f"[21c] Yakın değerler çıkarma unc({diff_ab.uncertainty_pct:.1f}%) "
        f"> bileşen unc({close_a.uncertainty_pct:.1f}%)",
        diff_ab.uncertainty_pct > close_a.uncertainty_pct
    )

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 2: UNCERTAINTYTRACKER
    # ═══════════════════════════════════════════════════════
    print("\n  ── UncertaintyTracker ─────────────────────────────")

    # ─── 22. TEMEL OLUŞTURMA ─────────────────────────────
    print("\n  [22] Temel Oluşturma")

    tracker = UncertaintyTracker()
    check_true("[22a] isinstance", isinstance(tracker, UncertaintyTracker))
    check_true("[22b] step_count = 0", tracker.step_count == 0)

    # ─── 23. TRACK() ─────────────────────────────────────
    print("\n  [23] track()")

    tracker.track("weight",    UncertainValue(72000, 5.0, "assumption", "kg"))
    tracker.track("CL",        UncertainValue(0.498, 5.2, "weight→CL", ""))
    tracker.track("drag",      UncertainValue(34200, 6.1, "CL→drag", "N"))
    tracker.track("fuel_flow", UncertainValue(2347, 6.8, "drag×SFC", "kg/hr"))
    tracker.track("cruise_fuel", UncertainValue(7488, 7.5, "FF×time", "kg"))
    tracker.track("total_fuel",  UncertainValue(12450, 8.0, "all_phases", "kg"))
    tracker.track("co2",        UncertainValue(39342, 8.0, "fuel×3.16", "kg CO2"))
    tracker.track("saving_usd", UncertainValue(442, 12.5, "optimization", "USD"))

    check_true("[23a] step_count = 8", tracker.step_count == 8)

    # ─── 24. GET_SUMMARY — TOTAL_STEPS ───────────────────
    print("\n  [24] get_summary — total_steps")

    summary = tracker.get_summary()
    check_true(f"[24a] total_steps = 8", summary.get('total_steps') == 8)

    # ─── 25. GET_SUMMARY — MAX_UNCERTAINTY ───────────────
    print("\n  [25] get_summary — max_uncertainty_pct")

    check(
        "[25a] max_uncertainty_pct = 12.5",
        summary.get('max_uncertainty_pct', 0),
        12.5,
        0.01
    )

    # ─── 26. GET_SUMMARY — DOMINANT_STEP ─────────────────
    print("\n  [26] get_summary — dominant_step")

    check_true(
        f"[26a] dominant_step = 'saving_usd': {summary.get('dominant_step')}",
        summary.get('dominant_step') == 'saving_usd'
    )

    # ─── 27. GET_SUMMARY — GROWTH_FACTOR ─────────────────
    print("\n  [27] get_summary — growth_factor")

    growth = summary.get('growth_factor', 0)
    check_true(
        f"[27a] growth_factor > 1: {growth:.2f}",
        growth > 1
    )

    first_unc = summary.get('first_uncertainty', 0)
    final_unc = summary.get('final_uncertainty', 0)
    check_true(
        f"[27b] final({final_unc:.1f}%) > first({first_unc:.1f}%)",
        final_unc > first_unc
    )

    # ─── 28. GET_SUMMARY — NOTE ──────────────────────────
    print("\n  [28] get_summary — note")

    check_true("[28a] note var", 'note' in summary and len(summary['note']) > 0)
    check_true("[28b] chain var", 'chain' in summary)
    check_true("[28c] chain 8 adım", len(summary.get('chain', [])) == 8)

    # ─── 29. PRINT_CHAIN() ───────────────────────────────
    print("\n  [29] print_chain()")

    try:
        tracker.print_chain()
        tests += 1
        print("  ✅ [29] print_chain() çalışıyor")
    except Exception as e:
        tests += 1
        errors.append(f"[29] print_chain: {e}")
        print(f"  ❌ [29] print_chain: {e}")

    # ─── 30. GET_DOMINANT_SOURCE() ────────────────────────
    print("\n  [30] get_dominant_source()")

    dom = tracker.get_dominant_source()
    check_true(
        f"[30a] dominant = 'optimization': {dom}",
        dom == "optimization"
    )

    # ─── 31. CLEAR() ─────────────────────────────────────
    print("\n  [31] clear()")

    tracker.clear()
    check_true("[31a] step_count = 0 after clear", tracker.step_count == 0)

    # Clear sonrası summary güvenli çalışmalı
    summary_empty = tracker.get_summary()
    check_true(
        "[31b] Boş tracker summary: max=0",
        summary_empty.get('max_uncertainty_pct', -1) == 0
    )
    check_true(
        "[31c] Boş tracker note var",
        'note' in summary_empty
    )

    # ─── 32. BOŞ TRACKER ─────────────────────────────────
    print("\n  [32] Boş Tracker")

    empty_tracker = UncertaintyTracker()
    empty_sum = empty_tracker.get_summary()

    check_true("[32a] max_unc = 0", empty_sum.get('max_uncertainty_pct', -1) == 0)
    check_true("[32b] total_steps = 0 veya yok", empty_sum.get('total_steps', 0) == 0)
    check_true("[32c] chain boş", len(empty_sum.get('chain', [0])) == 0)

    # print_chain boş tracker'da çalışmalı
    try:
        empty_tracker.print_chain()
        tests += 1
        print("  ✅ [32d] Boş print_chain() çalışıyor")
    except Exception as e:
        tests += 1
        errors.append(f"[32d] Boş print_chain: {e}")
        print(f"  ❌ [32d] {e}")

    # ─── 33. STEP_COUNT PROPERTY ─────────────────────────
    print("\n  [33] step_count property")

    t = UncertaintyTracker()
    check_true("[33a] başlangıçta 0", t.step_count == 0)

    t.track("adım1", UncertainValue(100, 5.0, "test"))
    check_true("[33b] 1 adımdan sonra 1", t.step_count == 1)

    t.track("adım2", UncertainValue(200, 8.0, "test"))
    check_true("[33c] 2 adımdan sonra 2", t.step_count == 2)

    t.clear()
    check_true("[33d] clear sonrası 0", t.step_count == 0)

    # ─── 34. REPR ────────────────────────────────────────
    print("\n  [34] repr")

    t2 = UncertaintyTracker()
    t2.track("x", UncertainValue(1.0, 1.0, "src"))
    r = repr(t2)
    check_true(
        f"[34] repr: {r}",
        'UncertaintyTracker' in r and '1' in r
    )

    # ═══════════════════════════════════════════════════════
    # BÖLÜM 3: EDGE CASES
    # ═══════════════════════════════════════════════════════
    print("\n  ── Edge Cases ──────────────────────────────────────")

    # ─── 35. ÇOK BÜYÜK DEĞER FORMATI ─────────────────────
    print("\n  [35] Çok Büyük Değer")

    big_val = UncertainValue(1_234_567, 5.0, "big", "kg")
    s_big = str(big_val)
    check_true(
        "[35a] Büyük değer formatı: '1,234,567' içeriyor",
        '1,234,567' in s_big or '1234567' in s_big
    )

    # ─── 36. ÇOK KÜÇÜK DEĞER FORMATI ─────────────────────
    print("\n  [36] Çok Küçük Değer")

    small_val = UncertainValue(0.000097, 5.0, "tiny", "Nm/kg")
    s_tiny = str(small_val)
    check_true("[36a] Küçük değer '0.000097' içeriyor", '0.000097' in s_tiny)

    # ─── 37. %100 BELİRSİZLİK ────────────────────────────
    print("\n  [37] %100 Belirsizlik")

    full_unc = UncertainValue(1000, 100.0, "fully_uncertain")
    check_true("[37a] unc = 100%", full_unc.uncertainty_pct == 100.0)
    check("[37b] lower = 0", full_unc.lower_bound, 0.0, 0.01)
    check("[37c] upper = 2000", full_unc.upper_bound, 2000.0, 0.01)

    # ─── 38. SIFIR BELİRSİZLİK (%0) ─────────────────────
    print("\n  [38] Sıfır Belirsizlik (%0)")

    exact = UncertainValue(12450, 0.0, "exact_measurement")
    check("[38a] unc_abs = 0", exact.uncertainty_abs, 0.0, 0.01)
    check("[38b] lower = value", exact.lower_bound, exact.value, 0.01)
    check("[38c] upper = value", exact.upper_bound, exact.value, 0.01)

    # Kesin değerle çarpma — belirsizlik korunur (sıfır)
    co2_exact = exact.multiply_scalar(3.16)
    check("[38d] exact×scalar unc = 0", co2_exact.uncertainty_pct, 0.0, 0.01)

    # ─── 39. UZUN ZİNCİR (8+ ADIM) ───────────────────────
    print("\n  [39] Uzun Zincir (10 adım)")

    tracker3 = UncertaintyTracker()
    steps = [
        ("input_A",    UncertainValue(1000, 2.0,  "sensor_A", "m")),
        ("input_B",    UncertainValue(500,  3.0,  "sensor_B", "kg")),
        ("calc_1",     UncertainValue(1500, 3.6,  "A+B", "kg")),
        ("calc_2",     UncertainValue(4500, 3.6,  "×3", "kg")),
        ("calc_3",     UncertainValue(22500, 5.0, "model", "kg")),
        ("fuel_est",   UncertainValue(12450, 7.0, "fuel_model", "kg")),
        ("co2_est",    UncertainValue(39342, 7.0, "CO2", "kg")),
        ("saving_est", UncertainValue(300, 10.0,  "saving", "kg")),
        ("cost_est",   UncertainValue(255, 10.0,  "cost_saving", "USD")),
        ("annual",     UncertainValue(186000, 12.0, "annual", "USD")),
    ]

    for name, uv in steps:
        tracker3.track(name, uv)

    check_true("[39a] step_count = 10", tracker3.step_count == 10)

    sum3 = tracker3.get_summary()
    check_true("[39b] max = 12.0%", sum3.get('max_uncertainty_pct') == 12.0)
    check_true("[39c] dominant = annual", sum3.get('dominant_step') == 'annual')
    check_true("[39d] growth > 1", sum3.get('growth_factor', 0) > 1)

    # ─── 40. DOMINANT KAYNAK SIRALAMASSI ─────────────────
    print("\n  [40] Dominant Kaynak Sıralaması")

    tracker4 = UncertaintyTracker()
    tracker4.track("az_belirsiz",    UncertainValue(100, 2.0, "iyi_sensor"))
    tracker4.track("orta_belirsiz",  UncertainValue(200, 8.0, "orta_model"))
    tracker4.track("cok_belirsiz",   UncertainValue(300, 15.0, "zayif_tahmin"))
    tracker4.track("yine_az",        UncertainValue(400, 3.0, "iyi_olcum"))

    sum4 = tracker4.get_summary()
    check_true(
        f"[40a] dominant = 'cok_belirsiz': {sum4.get('dominant_step')}",
        sum4.get('dominant_step') == 'cok_belirsiz'
    )
    check(
        "[40b] max = 15.0",
        sum4.get('max_uncertainty_pct', 0),
        15.0,
        0.01
    )
    check_true(
        "[40c] dominant_source = 'zayif_tahmin'",
        sum4.get('dominant_source') == 'zayif_tahmin'
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
