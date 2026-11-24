"""
GreenWing Analytics — Mach Fiziği Regresyon Testleri
══════════════════════════════════════════════════════

DENETİM #69 ve #70'in kalıcı kilitleri.

BULGU #70 — TSFC'nin Mach bağımlılığı TERS İŞARETLİYDİ
────────────────────────────────────────────────────────
Kod: `mach_correction = 1.0 - 0.10 * (mach - mach_ref)`
      M0.70 → 1.0115 · M0.785 → 1.003 · M0.82 → 0.9995

Yani "hızlı uçmak motoru DAHA VERİMLİ yapar" diyordu. Yorumu
da "ram recovery → termal verim artar → SFC düşer".

Yüksek-bypass turbofanda işaret TERSİDİR:
  • Ram sıcaklık artışı (M0.82'de ~+26 K) kompresör girişini
    ısıtır → termal verim DÜŞER
  • Fan ucu bağıl Mach artar → fan dalga kaybı
  • Nozzle basınç oranı düşer

Kaynaklar:
  • Gao vd. (2025), "High-bypass Ratio, Separate-exhaust
    Turbofan engine" — "an increase in the Mach Number ALWAYS
    increases the thrust-specific fuel consumption"
  • Rolls-Royce, "The Jet Engine" (5. baskı) §2 — "sfc
    increases steadily with Mach number"
  • Hammami (HAW Hamburg) §3.3 — "TSFC is increasing with
    higher Mach number"

BULGU #69 — DALGA SÜRÜKLEMESİ 46 KAT ZAYIFTI
─────────────────────────────────────────────
`ΔCD = 20·(M − M_cr)⁴` idi. Modelin kendi tanımı:
  _critical_mach docstring: "M_dd = MMO − 0.03 ... drag
  divergence tipik olarak MMO'nun hemen altındadır"
  dCD/dM tanımı (Raymer §12.5): 0.1
  Model: 4·20·(0.03)³ = 0.00216 → hedefin 1/46'sı

SONUÇ (düzeltme öncesi, B738 1240 nm 65 t FL370):
  M0.70 6959 kg → M0.82 6400 kg   (−%8,0)
  Yani "hızlı uç, DAHA AZ yak" — fizik ihlali.

DÜZELTME:
  TSFC : +0.12 × ΔM  (BADA mertebesi, M0.70→M0.82 +%1.44)
  Dalga: A = 200      (gerçek uçuş verisiyle kalibre:
                        M0.82/M0.78 = +%6,2 vs gerçek +%6-9)

SONUÇ (sonra):
  M0.70 6959 → M0.78 6478 ← OPTİMUM → M0.82 6879
  Gerçek B738: M0.70 +%7-8, M0.82 +%6-9  ✓

TİCARİ ETKİ (aynı 14 uçuş, aynı veri):
  Fiziksel yakıt tasarrufu  $883.360 → $605.799  (−%31,4)
  Tankering (arbitraj)      $951.653 → $944.199  (−%0,8)
  Yıllık toplam           $1.835.013 → $1.549.998 (−%15,5)
  Yani önceki rakam %15,5 ŞİŞMİŞTİ.

Çalıştırma:
    python tests/test_mach_physics.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.models.fuel_model import FuelModel  # noqa: E402
from src.optimization.cost_index_optimizer import (  # noqa: E402
    CostIndexOptimizer,
)


def run_tests() -> bool:
    print("\n" + "=" * 58)
    print("  TEST: Mach fiziği — #69 dalga + #70 TSFC")
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

    def check_true(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            ok(name)
        else:
            fail(name, detail)

    fm = FuelModel('B738')

    # ═══════════════════════════════════════════════════
    # [A] TSFC — MACH İLE ARTAR (#70)
    # ═══════════════════════════════════════════════════
    print("\n  [A] TSFC Mach bağımlılığı (#70)")

    _machs = (0.70, 0.74, 0.78, 0.785, 0.80, 0.82)
    _sfcs = [fm.corrected_sfc(37000, m) for m in _machs]

    check_true(
        "TSFC Mach ile artıyor (işaret doğru)",
        all(_sfcs[i] < _sfcs[i + 1] for i in range(len(_sfcs) - 1)),
        str([round(s, 9) for s in _sfcs])
    )

    _ratio = _sfcs[-1] / _sfcs[0]
    check_true(
        f"M0.70→M0.82 TSFC artışı {(_ratio - 1) * 100:.2f}% "
        f"(BADA mertebesi %1-2)",
        1.005 < _ratio < 1.025,
        f"{_ratio:.5f}"
    )

    # Eski (yanlış) davranış KİLİTLİ OLMAMALI
    check_true(
        "eski ters işaret geri gelmedi (M0.84 > M0.74)",
        fm.corrected_sfc(35000, 0.84) > fm.corrected_sfc(35000, 0.74)
    )

    # ═══════════════════════════════════════════════════
    # [B] YAKIT–MACH EĞRİSİ U ŞEKLİNDE (#69)
    # ═══════════════════════════════════════════════════
    print("\n  [B] Yakıt–Mach eğrisi (#69)")

    _f = {
        m: fm.fuel_for_distance(1240, 65000, 37000, m)['total_fuel_kg']
        for m in (0.70, 0.74, 0.78, 0.80, 0.82)
    }

    _opt_mach = min(_f, key=_f.get)
    check_true(
        f"optimum içeride (M{_opt_mach:.2f}), köşede değil",
        0.74 < _opt_mach < 0.82,
        str({k: round(v) for k, v in _f.items()})
    )

    check_true(
        f"M0.82 > M0.78 (hızlı uçmak daha çok yakar): "
        f"{_f[0.82]:.0f} > {_f[0.78]:.0f}",
        _f[0.82] > _f[0.78]
    )

    _r82 = _f[0.82] / _f[0.78]
    check_true(
        f"M0.82/M0.78 = +%{(_r82 - 1) * 100:.1f} (gerçek B738 +%6-9)",
        1.03 <= _r82 <= 1.10,
        f"{_r82:.4f}"
    )

    _r70 = _f[0.70] / _f[0.78]
    check_true(
        f"M0.70/M0.78 = +%{(_r70 - 1) * 100:.1f} (gerçek +%7-8)",
        1.03 <= _r70 <= 1.12,
        f"{_r70:.4f}"
    )

    # ═══════════════════════════════════════════════════
    # [C] CI OPTİMİZASYONU KÖŞE ÇÖZÜMÜ VERMİYOR
    # ═══════════════════════════════════════════════════
    print("\n  [C] CI optimizasyonu köşe çözümü")

    for _ac in ('B738', 'A320'):
        ci = CostIndexOptimizer(aircraft_type=_ac)
        r = ci.optimize_cost_index(1240, 37000, 65000)
        _machs_searched = [o['mach'] for o in r['all_options']]
        _m_opt = r['optimum']['mach']

        check_true(
            f"{_ac}: optimum {_m_opt:.3f} < taranan max "
            f"{max(_machs_searched):.3f} (köşe değil)",
            _m_opt < max(_machs_searched) - 1e-9,
            f"M{_m_opt:.3f} vs M{max(_machs_searched):.3f}"
        )

    # ═══════════════════════════════════════════════════
    # [D] MMO GERÇEK VERİDEN GELİYOR (#67/#68)
    # ═══════════════════════════════════════════════════
    print("\n  [D] MMO kaynağı (#67/#68)")

    check_true(
        "B738 MMO = 0.82 (OpenAP)",
        abs(float(fm.params.get('mmo', 0)) - 0.82) < 1e-9,
        str(fm.params.get('mmo'))
    )
    check_true(
        "B77W MMO = 0.89 (OpenAP)",
        abs(float(FuelModel('B77W').params.get('mmo', 0)) - 0.89) < 1e-9
    )

    ci = CostIndexOptimizer(aircraft_type='B738')
    r = ci.optimize_cost_index(1240, 37000, 65000, mach_max=0.84)
    lim = r['mach_limit']

    check_true(
        f"MMO 0.82 tarandı (float hatası #68 çözüldü)",
        any(abs(o['mach'] - 0.82) < 1e-9 for o in r['all_options']),
        f"son nokta {max(o['mach'] for o in r['all_options']):.3f}"
    )
    check_true(
        "mach_max=0.84 MMO ile kırpıldı ve BİLDİRİLDİ",
        lim['capped_by_mmo'] is True and lim['note'] is not None,
        str(lim)
    )
    check_true(
        "kırpma kaynağı 'openap'",
        lim['source'] == 'openap',
        lim['source']
    )

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

    print("  \u2705 TÜM MACH FİZİĞİ TESTLERİ BAŞARILI\n")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
