"""
Faz thrust oranlarını (T_faz / T_SL) yayımlanmış faz yakıtlarından geri çözer.

YÖNTEM
------
Her faz için, o fazın saatlik yakıt tüketimini üreten thrust oranı r,
uçağın KENDİ ICAO EDB yakıt modeli (c1,c2,c3) üzerinden bisection ile
çözülür:

    FF(r)/motor [kg/s] = c1 − exp(−c2·(r·e^(c3·r) − ln(c1)/c2))

REFERANS FAZ YAKITLARI (yayımlanmış, üç uçak ailesi)
----------------------------------------------------
B738  : Ground 750, Takeoff 4 800, Climb 3 500, Descent 900,
        Approach 1 650, Holding 2 300  [kg/h]
B77W  : Ground 1 800, Takeoff 16 000, Climb 11 500, Descent 2 800,
        Approach 5 200, Holding 7 000  [kg/h]
A380  : Ground 3 000, Takeoff 28 000, Climb 20 000, Descent 4 800,
        Approach 9 000, Holding 12 000  [kg/h]

Bu değerler SEGMENT ORTALAMASIDIR (derate + geçiş dahil), tam takeoff
itkisindeki anlık akış değil. Bu yüzden çözülen r değerleri de
segment-ortalama thrust oranlarıdır.

ÇIKTI: config/phase_thrust_table.yaml + doğrulama raporu
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.fuel_model import FuelModel  # noqa: E402

REFERENCE = {
    'B738': {'GROUND': 750, 'TAKEOFF': 4_800, 'CLIMB': 3_500,
             'DESCENT': 900, 'APPROACH': 1_650, 'HOLDING': 2_300},
    'B77W': {'GROUND': 1_800, 'TAKEOFF': 16_000, 'CLIMB': 11_500,
             'DESCENT': 2_800, 'APPROACH': 5_200, 'HOLDING': 7_000},
    'A380': {'GROUND': 3_000, 'TAKEOFF': 28_000, 'CLIMB': 20_000,
             'DESCENT': 4_800, 'APPROACH': 9_000, 'HOLDING': 12_000},
}


def solve_r(params: dict, target_kg_hr: float) -> float:
    """Verilen saatlik yakıtı üreten thrust oranını bisection ile çöz."""
    c1, c2, c3 = params['fuel_coef']
    n = int(params['num_engines'])

    def flow(r: float) -> float:
        return float(c1 - np.exp(-c2 * (r * np.exp(c3 * r) - np.log(c1) / c2))) * n * 3600.0

    lo, hi = 1e-3, 1.2
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if flow(mid) < target_kg_hr:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def main() -> int:
    phases = ['GROUND', 'TAKEOFF', 'CLIMB', 'DESCENT', 'APPROACH', 'HOLDING']
    table: dict[str, dict[str, float]] = {}
    print(f"{'phase':>9} " + " ".join(f"{a:>7}" for a in REFERENCE) +
          f" {'median':>7} {'stdev':>6}")
    for ph in phases:
        vals = {ac: solve_r(FuelModel(ac).params, REFERENCE[ac][ph])
                for ac in REFERENCE}
        arr = np.array(list(vals.values()))
        table[ph] = {'median': float(np.median(arr)),
                     'mean': float(arr.mean()),
                     'stdev': float(arr.std(ddof=1)),
                     'per_aircraft': {k: round(v, 4) for k, v in vals.items()},
                     'physical_range': f"{arr.min():.3f}–{arr.max():.3f}"}
        print(f"{ph:>9} " + " ".join(f"{v:>7.3f}" for v in vals.values()) +
              f" {np.median(arr):>7.3f} {arr.std(ddof=1):>6.3f}")

    out = {
        'source': 'Yayımlanmış faz yakıtlarından geri çözüm (B738/B77W/A380)',
        'method': 'r = solve(FF_EDB(r) == FF_faz_yayımlanmış)',
        'note': ('Değerler segment-ortalama thrust oranlarıdır. '
                 'Belirsizlik: ±1σ (uçak ailesi yayılımı).'),
        'uncertainty': 'phase fuel ±25 % (1σ); toplam görev yakıtında etki ±2 %',
        'phases': table,
    }
    dest = ROOT / 'config' / 'phase_thrust_table.yaml'
    dest.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False),
                    encoding='utf-8')
    print(f"\n→ {dest}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
