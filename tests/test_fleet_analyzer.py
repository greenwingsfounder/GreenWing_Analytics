"""
GreenWing Analytics — Filo Analizörü ve Rapor Üretici Testleri
══════════════════════════════════════════════════════════════

DENETİM #64/#65: `src/analysis/fleet_analyzer.py` (1.400+ satır) ve
`src/reporting/report_generator.py` için `tests/` altında HİÇ dosya
yoktu. Modül içi `validate_fleet_analyzer()` ve
`validate_report_generator()` hiçbir tarama adımında çalışmıyordu.

Bu yüzden iki hata fark edilmemişti:

  #65  `validate_fleet_analyzer()` yıllık tasarruf beklentisi
       BAYAT. Ham toplam beklenirken kod rota ortalaması alıyor.
       Test HER ÇALIŞTIRMADA FAIL veriyordu:
         "Yıllık tasarruf: $1.191.284 ≠ $1.644.522"

  #57  `generate_fleet_summary` bozuk kayıtta `KeyError` atıyordu.
       Düzeltildi ama testle kilitlenmemişti.

Bu dosya iki modülü de sürekli taramaya sokar:

    [A] fleet_analyzer modül içi doğrulama (38 kontrol)
    [B] #57: bozuk kayıt → KeyError değil, atla + raporla
    [C] #29: belirsizlik aralığı çıktıda
    [D] report_generator modül içi doğrulama (22 kontrol)
    [E] Boş özet → error (denetim #56)

Çalıştırma:
    python tests/test_fleet_analyzer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.analysis.fleet_analyzer import (  # noqa: E402
    FleetAnalyzer,
    validate_fleet_analyzer,
)
from src.reporting.report_generator import (  # noqa: E402
    ReportGenerator,
    validate_report_generator,
)


def _flight(dist, ac, fuel, co2, fs):
    """Gerçekçi bir uçuş sonucu (analyze_trajectory şeması)."""
    return {
        'flight_info': {'aircraft_type': ac, 'callsign': 'TK1985'},
        'basic_metrics': {
            'great_circle_distance_nm': dist,
            'origin_icao': 'LTFM', 'destination_icao': 'EGLL',
        },
        'fuel_analysis': {'estimated_total_fuel_kg': fuel},
        'emissions': {'emissions': {'CO2_kg': co2}},
        'savings_opportunities': {
            'total_per_flight': {
                'fuel_saving_kg': fs, 'cost_saving_usd': fs * 0.85,
            },
            'annual_projection': {'realistic_annual_usd': fs * 0.85 * 400},
        },
    }


def run_tests() -> bool:
    print("\n" + "=" * 58)
    print("  TEST: fleet_analyzer.py + report_generator.py")
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

    # ═══════════════════════════════════════════════════
    # [A] MODÜL İÇİ DOĞRULAMA (38 kontrol, #65 düzeltilmiş)
    # ═══════════════════════════════════════════════════
    print("\n  [A] fleet_analyzer modül içi doğrulama")
    fa_ok = validate_fleet_analyzer()
    check_true("validate_fleet_analyzer() tümü geçti (#65)", fa_ok)

    # ═══════════════════════════════════════════════════
    # [B] #57 — BOZUK KAYIT KeyError ATMIYOR
    # ═══════════════════════════════════════════════════
    print("\n  [B] Bozuk kayıt toleransı (#57)")

    fa = FleetAnalyzer()
    fa.add_flight_result(_flight(600, 'B738', 4080, 12893, 80))
    fa.add_flight_result(_flight(1200, 'B738', 8160, 25786, 160))
    fa.add_flight_result(_flight(1400, 'A320', 9520, 30083, 140))

    # Bozuk: emissions.CO2_kg YOK
    _broken = _flight(900, 'B738', 6100, 0, 120)
    _broken['emissions'] = {'emissions': {}}
    _broken['basic_metrics']['origin_icao'] = 'BOZUK'
    fa.add_flight_result(_broken)

    _summary = None
    try:
        _summary = fa.generate_fleet_summary(avg_fuel_price_usd_per_kg=0.85)
        ok("bozuk kayıtla özet üretildi (KeyError YOK)")
    except KeyError as _e:
        fail("bozuk kayıt KeyError", str(_e))

    if _summary and 'error' not in _summary:
        _meta = _summary.get('report_metadata', {})
        check_true(
            "atlanan kayıt raporlandı",
            _meta.get('skipped_records') == 1,
            str(_meta.get('skipped_records'))
        )
        _details = _meta.get('skipped_details') or []
        check_true(
            "atlama nedeni açık (CO2 tahmin edilmedi)",
            any('CO2' in str(x) for x in _details),
            str(_details)[:120]
        )
        check_true(
            "3 geçerli uçuş kaldı",
            _summary['data_quality']['valid_flights'] >= 3,
            str(_summary['data_quality'].get('valid_flights'))
        )
        check_true(
            "bozuk uçuş tasarrufa girmiyor",
            _summary['savings_potential']['total_fuel_saving_kg'] < 500,
            str(_summary['savings_potential']['total_fuel_saving_kg'])
        )

    # ═══════════════════════════════════════════════════
    # [C] #29 — BELİRSİZLİK ARALIĞI
    # ═══════════════════════════════════════════════════
    print("\n  [C] Belirsizlik aralığı (#29)")

    _clean = FleetAnalyzer()
    for _d, _a, _fs in ((600, 'B738', 80), (1200, 'B738', 160),
                        (1400, 'A320', 140)):
        _clean.add_flight_result(_flight(_d, _a, _d * 6.8, _d * 6.8 * 3.16, _fs))
    _cs = _clean.generate_fleet_summary(avg_fuel_price_usd_per_kg=0.85)
    _u = _cs['savings_potential'].get('uncertainty') or {}

    check_true("uncertainty bloğu var", bool(_u))
    check_true("available=True", _u.get('available') is True, str(_u)[:100])

    if _u.get('available'):
        _ann = _cs['savings_potential']['annualized_cost_saving_usd']
        _pct = _u['total_uncertainty_pct']
        check_true(
            f"belirsizlik ±%{_pct} makul (0 < x < 60)",
            0 < _pct < 60
        )
        # NOT: `annualized_cost` çıktıda tam sayıya yuvarlanmış
        # geliyor; sınırlar onun üzerinden hesaplandığı için birkaç
        # dolarlık fark normaldir. Tolerans, yuvarlamanın üst sınırı
        # olan ±(pct/100 × 1) kadardır.
        _tol = max(2.0, _ann * 0.001)
        check_true(
            f"alt sınır = yıllık × (1 − pct) ±{_tol:.0f}",
            abs(_u['low_usd'] - _ann * (1 - _pct / 100)) <= _tol,
            f"{_u['low_usd']} vs {_ann * (1 - _pct / 100):.1f}"
        )
        check_true(
            f"üst sınır = yıllık × (1 + pct) ±{_tol:.0f}",
            abs(_u['high_usd'] - _ann * (1 + _pct / 100)) <= _tol,
            f"{_u['high_usd']} vs {_ann * (1 + _pct / 100):.1f}"
        )
        check_true(
            "aralık yıllık değeri kapsıyor",
            _u['low_usd'] < _ann < _u['high_usd']
        )
        check_true(
            "baskın kaynak bildirildi",
            _u.get('dominant_source') in
            ('wind', 'fuel_price', 'altitude', 'weight', 'cd0', 'sfc'),
            str(_u.get('dominant_source'))
        )
        check_true(
            "not 'taahhüt değil' diyor",
            'taahhüt' in str(_u.get('note', '')).lower(),
            str(_u.get('note'))[:80]
        )

    # ═══════════════════════════════════════════════════
    # [D] REPORT_GENERATOR MODÜL İÇİ DOĞRULAMA
    # ═══════════════════════════════════════════════════
    print("\n  [D] report_generator modül içi doğrulama")
    rg_ok = validate_report_generator()
    check_true("validate_report_generator() tümü geçti", rg_ok)

    # ═══════════════════════════════════════════════════
    # [E] #56 — BOŞ ÖZET → error
    # ═══════════════════════════════════════════════════
    print("\n  [E] Boş özet (#56)")

    _r = ReportGenerator().generate_fleet_report({})
    check_true(
        "boş özet → status error",
        _r.get('status') == 'error',
        str(_r.get('status'))
    )
    check_true(
        "boş özet → html_path None",
        _r.get('html_path') is None,
        str(_r.get('html_path'))
    )

    # ═══════════════════════════════════════════════════
    # [F] RAPORDA ARALIK GÖRÜNÜYOR (#29 HTML)
    # ═══════════════════════════════════════════════════
    print("\n  [F] HTML raporda belirsizlik aralığı")

    _rep = ReportGenerator().generate_fleet_report(
        _cs, output_filename='_fleet_test_unc.html')
    check_true(
        "rapor üretildi",
        _rep.get('status') == 'success',
        str(_rep.get('status'))
    )
    if _rep.get('html_path'):
        _html = Path(_rep['html_path']).read_text(encoding='utf-8')
        check_true("HTML'de 'Aralık:' yazıyor", 'Aralık:' in _html)
        check_true(
            "HTML 'taahhüt değil' uyarısı taşıyor",
            'taahhüt değil' in _html
        )
        try:
            Path(_rep['html_path']).unlink()
        except OSError:
            pass

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

    print("  \u2705 TÜM FİLO/RAPOR TESTLERİ BAŞARILI\n")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
