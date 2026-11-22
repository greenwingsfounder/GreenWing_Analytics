"""
GreenWing Analytics — Duyarlılık Analizi Testleri
══════════════════════════════════════════════════

DENETİM #63: `src/analysis/sensitivity.py` içinde `validate_sensitivity()`
adında 40 kontrollük bir test bloğu vardı ama `tests/` altında karşılığı
YOKTU. Yani "16/16 test dosyası geçiyor" taramasına girmiyordu — modülün
testleri hiçbir CI/tarama adımında çalışmıyordu.

Bu dosya, modül içindeki doğrulamayı `tests/` ailesine taşır ve
denetimde eklenen sözleşmeleri kilitler:

    [A] Modül içi validate_sensitivity() — 40 kontrol
    [B] DENETİM #62: params None / sıfır girdi / varsayılan şeffaflığı
    [C] Fiziksel sıralama: rüzgâr en büyük belirsizlik kaynağı olmalı
    [D] Fiyat duyarlılığı lineerliği ve kg değişmezliği

Çalıştırma:
    python tests/test_sensitivity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.analysis.sensitivity import (  # noqa: E402
    SensitivityAnalyzer,
    validate_sensitivity,
)


def run_tests() -> bool:
    print("\n" + "=" * 58)
    print("  TEST: sensitivity.py — DUYARLILIK ANALİZİ")
    print("=" * 58)

    errors: list[str] = []
    tests = 0

    def ok(name: str) -> None:
        nonlocal tests
        tests += 1
        print(f"  \u2705 {name}")

    def fail(name: str, detail: str = "") -> None:
        nonlocal tests
        tests += 1
        print(f"  \u274c {name} — {detail}")
        errors.append(f"{name}: {detail}")

    def check(name: str, actual: float, expected: float, tol: float = 0.01) -> None:
        if abs(float(actual) - float(expected)) <= tol:
            ok(f"{name} = {float(actual):.4f}")
        else:
            fail(name, f"{actual} != {expected} (±{tol})")

    def check_true(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            ok(name)
        else:
            fail(name, detail)

    # ═══════════════════════════════════════════════════
    # [A] MODÜL İÇİ DOĞRULAMA (mevcut 40 kontrol)
    # ═══════════════════════════════════════════════════
    print("\n  [A] Modül içi validate_sensitivity()")
    mod_ok = validate_sensitivity()
    check_true("validate_sensitivity() tümü geçti", mod_ok)

    sa = SensitivityAnalyzer()

    # ═══════════════════════════════════════════════════
    # [B] DENETİM #62 — GİRDİ SÖZLEŞMESİ
    # ═══════════════════════════════════════════════════
    print("\n  [B] Girdi sözleşmesi (denetim #62)")

    # (a) None → açık ValueError (eskiden AttributeError)
    _none_raised = False
    try:
        sa.full_sensitivity_report(None)
    except ValueError:
        _none_raised = True
    except AttributeError:
        _none_raised = False
    check_true("params=None → ValueError (AttributeError değil)",
               _none_raised)

    # (b) dict olmayan → TypeError
    _type_raised = False
    try:
        sa.full_sensitivity_report([('weight_kg', 65000)])
    except TypeError:
        _type_raised = True
    check_true("params=list → TypeError", _type_raised)

    # (c) Sıfır/negatif fiziksel girdiler → ValueError (eskiden ZeroDivision)
    for _bad in ({'distance_nm': 0}, {'weight_kg': 0}, {'mach': 0},
                 {'distance_nm': -500}, {'fuel_price_usd': -1}):
        _raised = False
        try:
            sa.full_sensitivity_report(_bad)
        except (ValueError, TypeError):
            _raised = True
        check_true(f"geçersiz girdi {_bad} → hata (çökmüyor)", _raised)

    # (d) Varsayılanlar şeffaf: hangi parametre varsayılan?
    _full = sa.full_sensitivity_report({})
    check_true(
        "{} → 6 varsayılan bildiriliyor",
        len(_full['used_default_params']) == 6,
        str(_full['used_default_params'])
    )
    _partial = sa.full_sensitivity_report(
        {'weight_kg': 65000, 'distance_nm': 1240})
    check_true(
        "kısmi params → yalnız 4 varsayılan bildiriliyor",
        len(_partial['used_default_params']) == 4,
        str(_partial['used_default_params'])
    )
    check_true(
        "analysis_inputs gerçek kullanılan değerleri taşıyor",
        _partial['analysis_inputs']['weight_kg'] == 65000.0
        and _partial['analysis_inputs']['distance_nm'] == 1240.0
    )

    # (e) Tam params → hiç varsayılan yok
    _complete = sa.full_sensitivity_report({
        'weight_kg': 65000, 'distance_nm': 1240, 'altitude_ft': 37000,
        'mach': 0.78, 'fuel_price_usd': 0.85, 'saving_kg': 155,
    })
    check_true(
        "tam params → varsayılan yok",
        len(_complete['used_default_params']) == 0,
        str(_complete['used_default_params'])
    )

    # ═══════════════════════════════════════════════════
    # [C] FİZİKSEL SIRALAMA
    # ═══════════════════════════════════════════════════
    print("\n  [C] Fiziksel sıralama mantığı")

    _rep = sa.full_sensitivity_report({
        'weight_kg': 65000, 'distance_nm': 1240, 'altitude_ft': 37000,
        'mach': 0.78, 'saving_kg': 155,
    })
    _ranked = [r['parameter'] for r in _rep['ranking']]

    # Rüzgâr en büyük belirsizlik olmalı (sektör gerçeği:
    # rüzgâr tahmini ±%20-25, diğerleri daha küçük)
    check_true(
        f"rüzgâr baskın ({_ranked[0]})",
        _ranked[0] == 'wind',
        str(_ranked)
    )
    check_true(
        "6 parametre sıralanmış",
        len(_ranked) == 6,
        str(_ranked)
    )
    # Sıralama monoton azalan olmalı
    _effects = [r['effect_pct'] for r in _rep['ranking']]
    check_true(
        "sıralama azalan",
        all(_effects[i] >= _effects[i + 1] for i in range(len(_effects) - 1)),
        str([round(e, 2) for e in _effects])
    )
    # Toplam belirsizlik en büyük tekil etkiden büyük olmalı (RSS)
    check_true(
        f"toplam ({_rep['total_uncertainty_pct']:.1f}) > tek kaynak "
        f"({_rep['dominant_effect_pct']:.1f})",
        _rep['total_uncertainty_pct'] > _rep['dominant_effect_pct']
    )
    check_true(
        "baskın kaynak ranking[0] ile aynı",
        _rep['dominant_source'] == _ranked[0]
    )

    # ═══════════════════════════════════════════════════
    # [D] FİYAT DUYARLILIĞI
    # ═══════════════════════════════════════════════════
    print("\n  [D] Fiyat duyarlılığı")

    _p = sa.analyze_fuel_price_sensitivity(per_flight_saving_kg=155)
    check("base_saving_usd = 155 × 0,85", _p['base_saving_usd'], 131.75, 0.01)
    check("baz fiyat kanonik (Assumptions)", _p['base_value'], 0.85, 0.001)

    # Lineerlik: fiyat -%20 → tasarruf -%20
    _rows = _p['results']
    _lo = next(r for r in _rows if abs(r['change_pct'] + 20) < 0.01)
    check("fiyat -%20 → tasarruf -%20",
          _lo['saving_usd'], 131.75 * 0.80, 0.5)

    # Yakıt kg DEĞİŞMEZ (fizik fiyattan bağımsız)
    check("yakıt kg fiyattan bağımsız", _p['saving_kg'], 155, 0.01)

    # ±%20 için etki tam %20 olmalı
    check("max_effect_pct = 20", _p['max_effect_pct'], 20.0, 0.01)

    # ═══════════════════════════════════════════════════
    # SONUÇ
    # ═══════════════════════════════════════════════════
    print(f"\n  {'─' * 50}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print("\n  \u274c BAŞARISIZ TESTLER:")
        for i, e in enumerate(errors, 1):
            print(f"     {i}. {e}")
        return False

    print("  \u2705 TÜM DUYARLILIK TESTLERİ BAŞARILI\n")
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
