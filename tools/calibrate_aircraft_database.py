"""
GreenWing Analytics — Uçak veritabanı kalibrasyon aracı
========================================================

AMAÇ
----
Her uçak tipi için CD0 ve K'yı, YAYINLANMIŞ iki uçak-düzeyi niceliği
birebir yeniden üretecek şekilde çözer:

  (1) L/D_max      : maksimum kaldırma/sürükleme oranı (üretici ACAP /
                     BADA / bağımsız performans yayınları)
  (2) kg/nm (cruise): tipik cruise özgül menzil (yayınlanmış blok
                     yakıt bölü mesafe; ağırlıktan bağımsız)

Böylece e (Oswald) GİRDİ DEĞİL, ÇIKTI olur: e = 1/(π·K·AR).
AR ise geometriden kesin hesaplanır: AR = b²/S.

MATEMATİK
---------
Bilinen:  S, b, AR=b²/S, MTOW, OEW, referans ağırlık W, irtifa, Mach,
          TSFC, hedef L/D_max, hedef kg/nm.

  q  = 0.5·ρ·V²                       (ISA, verilen irtifa)
  CL = W·g/(q·S)
  V' = V·1.94384                      (kt)
  CD_req = (kg/nm)·V'/(TSFC·q·S·1852) (özgül menzilden gerekli CD)

  P = 1/(4·(L/D_max)²)                (L/D_max tanımından: CD0·K = P)

  CD0² − CD_req·CD0 + P·CL² = 0
  CD0 = [CD_req − √(CD_req² − 4·P·CL²)] / 2      (fiziksel kök)
  K   = P / CD0

Fiziksel kökün varlığı (diskriminant ≥ 0) bir TUTARLILIK TESTİDİR:
yayınlanmış L/D_max ile yayınlanmış kg/nm aynı uçakta birlikte
gerçekleşebiliyor mu? Gerçekleşmiyorsa girdi seti çelişkilidir ve
araç bunu HATA olarak bildirir — sessizce "düzeltmez".
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.units import Units  # noqa: E402

# ─────────────────────────────────────────────────────────────
# GİRDİLER — her biri kaynağıyla
# ─────────────────────────────────────────────────────────────
# ref_w_frac : referans ağırlık = OEW + frac·(MTOW−OEW)
#              (kg/nm yayınları tipik olarak orta-ağır cruise'a karşılık gelir)
#
# ld_max     : L/D_max. Kaynak: BADA 3.x SYSCONF/OPF dosyaları ve üretici
#              ACAP belgelerinde verilen cruise L/D aralıklarının üst ucu.
#              (Uçak düzeyi, yayınlanmış.)
#
# kg_per_nm  : Tipik cruise özgül yakıt. Kaynak: üretici/operatör yayınlanmış
#              blok yakıt değerleri bölü mesafe; ağırlıktan bağımsız
#              karşılaştırma için standart metrik.
#
# tsfc       : Motor cruise TSFC [kg/(N·s)]. Kaynak: motor üreticisi
#              yayınlanmış cruise SFC değerleri (lb/(lbf·h) → SI).
#              1 lb/(lbf·h) = 0.45359237/(4.4482216·3600) = 2.8325e-5 kg/(N·s)
#
CASES = {
    'B738': dict(ld_max=17.5, kg_per_nm=5.90, tsfc=1.70e-5, ref_w_frac=0.75, alt_ft=35000),
    'B38M': dict(ld_max=18.0, kg_per_nm=5.20, tsfc=1.56e-5, ref_w_frac=0.75, alt_ft=35000),
    'A320': dict(ld_max=16.8, kg_per_nm=5.80, tsfc=1.70e-5, ref_w_frac=0.75, alt_ft=35000),
    'A20N': dict(ld_max=17.4, kg_per_nm=5.20, tsfc=1.56e-5, ref_w_frac=0.75, alt_ft=35000),
    'A321': dict(ld_max=16.8, kg_per_nm=6.80, tsfc=1.70e-5, ref_w_frac=0.75, alt_ft=35000),
    'A21N': dict(ld_max=17.4, kg_per_nm=6.15, tsfc=1.55e-5, ref_w_frac=0.75, alt_ft=35000),
    'B77W': dict(ld_max=19.8, kg_per_nm=19.50, tsfc=1.55e-5, ref_w_frac=0.75, alt_ft=35000),
    'B788': dict(ld_max=20.5, kg_per_nm=12.20, tsfc=1.47e-5, ref_w_frac=0.75, alt_ft=35000),
    'B789': dict(ld_max=21.0, kg_per_nm=13.20, tsfc=1.50e-5, ref_w_frac=0.75, alt_ft=35000),
    'A350': dict(ld_max=21.5, kg_per_nm=13.20, tsfc=1.45e-5, ref_w_frac=0.75, alt_ft=35000),
    'A380': dict(ld_max=19.5, kg_per_nm=32.00, tsfc=1.52e-5, ref_w_frac=0.75, alt_ft=35000),
}


def solve(ac: str, p: dict, c: dict) -> dict:
    S = float(p['wing_area'])
    b = float(p['wingspan'])
    AR = b * b / S                       # geometriden, kesin

    W = p['oew'] + c['ref_w_frac'] * (p['mtow'] - p['oew'])
    alt = c['alt_ft']
    mach = float(p['cruise_mach'])

    rho = Units.density_at_altitude(alt)
    V = Units.mach_to_tas(mach, alt)     # m/s
    V_kt = V * 1.94384
    q = 0.5 * rho * V * V
    CL = W * 9.80665 / (q * S)

    tsfc = c['tsfc']
    # kg/nm = tsfc·(q·S·CD)/V · 1852   →   CD_req
    CD_req = c['kg_per_nm'] * V / (tsfc * q * S * 1852.0)

    P = 1.0 / (4.0 * c['ld_max'] ** 2)
    disc = CD_req ** 2 - 4.0 * P * CL * CL
    if disc < 0:
        raise ValueError(
            f"{ac}: ÇELİŞKİLİ GİRDİ. Yayınlanmış L/D_max={c['ld_max']} ile "
            f"kg/nm={c['kg_per_nm']} aynı uçakta birlikte gerçekleşemez "
            f"(diskriminant={disc:.3e}). Girdilerden biri hatalı."
        )
    CD0 = (CD_req - math.sqrt(disc)) / 2.0
    K = P / CD0
    e = 1.0 / (math.pi * K * AR)         # ÇIKTI, girdi değil

    # Doğrulama: hedefleri birebir yeniden üretiyor mu?
    CD_at_ref = CD0 + K * CL * CL
    kpnm_check = tsfc * q * S * CD_at_ref / V * 1852.0
    ld_at_ref = CL / CD_at_ref
    ld_max_check = 1.0 / (2.0 * math.sqrt(CD0 * K))

    return dict(
        ac=ac, AR=AR, W=W, CL=CL, CD0=CD0, K=K, e=e, tsfc=tsfc,
        kpnm=kpnm_check, kpnm_target=c['kg_per_nm'],
        ld_ref=ld_at_ref, ld_max=ld_max_check, ld_max_target=c['ld_max'],
        CD_req=CD_req,
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    db_path = root / 'config' / 'aircraft_database.yaml'
    db = yaml.safe_load(db_path.read_text(encoding='utf-8'))['aircraft_types']

    print(f"{'AC':>5} {'AR(b²/S)':>9} {'CL':>6} {'CD0':>8} {'K':>8} "
          f"{'e(çıktı)':>9} {'LD_max':>7} {'kg/nm':>7} {'hata':>6}")
    results = {}
    ok = True
    for ac, c in CASES.items():
        try:
            r = solve(ac, db[ac], c)
        except ValueError as exc:
            print(f"  ✗ {ac}: {exc}")
            ok = False
            continue
        results[ac] = r
        err = (r['kpnm'] - c['kg_per_nm']) / c['kg_per_nm'] * 100
        print(f"{ac:>5} {r['AR']:>9.3f} {r['CL']:>6.3f} {r['CD0']:>8.5f} "
              f"{r['K']:>8.5f} {r['e']:>9.4f} {r['ld_max']:>7.2f} "
              f"{r['kpnm']:>7.2f} {err:>5.2f}%")

    # Fiziksel makullük kontrolleri
    print("\nFiziksel makullük:")
    for ac, r in results.items():
        flags = []
        if not (0.70 <= r['e'] <= 0.92):
            flags.append(f"e={r['e']:.3f} beklenen 0.70-0.92")
        if not (0.010 <= r['CD0'] <= 0.032):
            flags.append(f"CD0={r['CD0']:.4f} beklenen 0.010-0.032")
        if r['ld_ref'] >= r['ld_max']:
            flags.append("cruise L/D >= L/D_max")
        print(f"  {ac:>5} {'✓' if not flags else '⚠ ' + '; '.join(flags)}")
        if flags:
            ok = False

    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
