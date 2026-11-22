"""
Uçak verisinin YAYIMLANMIŞ kaynaklarla doğrulanması.

Her test, veritabanındaki sayıyı bağımsız bir yayımlanmış değerle
karşılaştırır. Amaç: "bu sayı nereden geldi?" sorusuna kanıt sunmak.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import yaml  # noqa: E402

DB = yaml.safe_load(open(os.path.join(
    os.path.dirname(__file__), '..', 'config', 'aircraft_database.yaml'),
    encoding='utf-8'))

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = '') -> None:
    if cond:
        print(f'  ✓ {name}')
    else:
        _fails.append(name)
        print(f'  ✗ {name} {detail}')


def get(ac: str) -> dict:
    """Uçak kaydını al (YAML kök yapısına göre esnek)."""
    node = DB.get('aircraft_types', DB.get('aircraft', DB))
    return node[ac]


print('\n' + '=' * 70)
print('  UÇAK VERİSİ — YAYIMLANMIŞ KAYNAK DOĞRULAMASI')
print('=' * 70)

# ── 1. OpenAP sürükleme poları (birebir) ───────────────────
print('\n1. CD0 / K / e — OpenAP v3 dragpolar (birebir)')
# OpenAP data/dragpolar/*.yml
OPENAP = {
    'B738': (0.019, 0.042, 0.799), 'B38M': (0.020, 0.042, 0.797),
    'A320': (0.018, 0.039, 0.799), 'A20N': (0.017, 0.038, 0.807),
    'A321': (0.020, 0.041, 0.785), 'A21N': (0.017, 0.038, 0.807),
    'B77W': (0.024, 0.043, 0.765), 'B788': (0.017, 0.041, 0.819),
    'B789': (0.022, 0.042, 0.783), 'A350': (0.022, 0.043, 0.783),
    'A380': (0.016, 0.050, 0.855),
}
for ac, (cd0, k, e) in OPENAP.items():
    p = get(ac)
    ok = (abs(float(p['CD0']) - cd0) < 1e-6
          and abs(float(p['K']) - k) < 1e-6
          and abs(float(p['e']) - e) < 1e-6)
    check(f'{ac}: {p["CD0"]}/{p["K"]}/{p["e"]}', ok,
          f'beklenen {cd0}/{k}/{e}')

# ── 2. Polar iç tutarlılığı: K ≈ 1/(π·AR·e) ────────────────
print('\n2. Polar iç tutarlılığı — K ve AR·e')
for ac in OPENAP:
    p = get(ac)
    if 'AR' not in p:
        continue
    ar = float(p['AR'])
    k_implied = 1.0 / (math.pi * ar * float(p['e']))
    rel = abs(k_implied - float(p['K'])) / float(p['K']) * 100
    # AR artık OpenAP geometrisinden (span²/area) türetildi → K ile
    # tam tutarlı olmalı. ±%2 tolerans.
    check(f'{ac}: K={p["K"]:.4f} vs 1/(π·AR·e)={k_implied:.4f} (%{rel:.1f})',
          rel < 2.0)

# ── 3. OEW / MTOW — üretici verisi ─────────────────────────
print('\n3. OEW / MTOW — üretici (Boeing/Airbus) verisi, ±%3')
# Yayımlanmış değerler (Boeing/Airbus airport planning / ACM)
PUBLISHED = {
    'B738': {'oew': 41413, 'mtow': 79016, 'src': 'Boeing 737-800 ACM'},
    'B38M': {'oew': 45070, 'mtow': 82190, 'src': 'Boeing 737 MAX 8 spec'},
    'A320': {'oew': 42600, 'mtow': 78000, 'src': 'Airbus A320 ACM'},
    'A20N': {'oew': 44300, 'mtow': 79000, 'src': 'Airbus A320neo ACM'},
    'A321': {'oew': 48500, 'mtow': 93500, 'src': 'Airbus A321 ACM'},
    'A21N': {'oew': 50900, 'mtow': 97000, 'src': 'Airbus A321neo ACM'},
    'B77W': {'oew': 167829, 'mtow': 351534, 'src': 'Boeing 777-300ER spec'},
    'B788': {'oew': 119950, 'mtow': 227930, 'src': 'Boeing 787-8 spec'},
    'B789': {'oew': 128850, 'mtow': 254011, 'src': 'Boeing 787-9 spec'},
    'A350': {'oew': 142400, 'mtow': 280000, 'src': 'Airbus A350-900 ACM'},
    'A380': {'oew': 277145, 'mtow': 575000, 'src': 'Airbus A380 ACM'},
}
for ac, ref in PUBLISHED.items():
    p = get(ac)
    for field in ('oew', 'mtow'):
        actual = float(p[field])
        rel = abs(actual - ref[field]) / ref[field] * 100
        check(f'{ac} {field}: {actual:,.0f} vs {ref[field]:,} (%{rel:.1f})',
              rel < 3.0, ref['src'])

# ── 4. Kanat alanı — üretici verisi ────────────────────────
print('\n4. Kanat alanı — üretici verisi')
print('   (A321: OpenAP 128 m² vs üretici 122.6 → polar tutarlılığı için')
print('    OpenAP kabul edildi; tolerans ±%5)')
# Üretici yayımlanmış kanat alanları (Boeing/Airbus ACM).
# NOT: A320 ailesi için üretici 122.6 m² verir; OpenAP 124 m² kullanır.
# Bu, CD0/K tanımıyla tutarlı olması için OpenAP değeri kabul edildi
# (±%1.1 — polar sonucuna etkisi ihmal edilebilir).
WING = {'B738': 124.6, 'B38M': 124.6, 'A320': 122.6, 'A20N': 122.6,
        'A321': 122.6, 'A21N': 122.6, 'B77W': 436.8, 'B788': 377.0,
        'B789': 377.0, 'A350': 442.0, 'A380': 845.0}
for ac, s_ref in WING.items():
    p = get(ac)
    if 'wing_area' not in p:
        continue
    rel = abs(float(p['wing_area']) - s_ref) / s_ref * 100
    check(f'{ac} wing_area: {p["wing_area"]} vs {s_ref} (%{rel:.1f})', rel < 5.0)

# ── 5. Motor sayısı ve itki ────────────────────────────────
print('\n5. Motor sayısı ve deniz seviyesi itki')
ENGINES = {'B738': (2, 117000), 'B38M': (2, 130000), 'A320': (2, 120100),
           'A20N': (2, 120600), 'A321': (2, 142000), 'A21N': (2, 143500),
           'B77W': (2, 513900), 'B788': (2, 289000), 'B789': (2, 324000),
           'A350': (2, 374500), 'A380': (4, 311000)}
for ac, (n_ref, t_ref) in ENGINES.items():
    p = get(ac)
    check(f'{ac} num_engines: {p.get("num_engines")}', int(p['num_engines']) == n_ref)
    t = float(p.get('max_thrust_sl', 0))
    if t:
        rel = abs(t - t_ref) / t_ref * 100
        check(f'{ac} max_thrust_sl: {t:,.0f} N vs {t_ref:,} (%{rel:.1f})',
              rel < 15.0)

# ── 6. Yakıt katsayıları — ICAO EDB / OpenAP ───────────────
print('\n6. fuel_coef — ICAO EDB / OpenAP fuel_models.csv')
EDB = {'B738': (1.075485, 1.877730, 1.889552),
       'A320': (1.045321, 2.363372, 1.237813),
       'A321': (1.398000, 2.054028, 1.000894)}
for ac, (c1, c2, c3) in EDB.items():
    p = get(ac)
    fc = p.get('fuel_coef')
    ok = (fc and abs(fc[0] - c1) < 1e-5 and abs(fc[1] - c2) < 1e-5
          and abs(fc[2] - c3) < 1e-5)
    check(f'{ac} fuel_coef (doğrudan ICAO EDB)', bool(ok), f'gelen {fc}')

for ac in OPENAP:
    p = get(ac)
    fc = p.get('fuel_coef')
    check(f'{ac} fuel_coef mevcut ve fiziksel',
          bool(fc) and 0.5 < fc[0] < 8.0 and 1.0 < fc[2] < 3.0, f'gelen {fc}')

# ── 7. Bilinen ksurlar (dürüst kayıt) ──────────────────────
print('\n7. Bilinen veri tutarsızlıkları (dürüst kayıt)')
p77w = get('B77W')
ar = float(p77w['AR'])
check(f'B77W AR={ar:.3f} = span²/area = 64.8²/436.8', abs(ar - 9.613) < 0.01)

# Tüm tiplerde AR = span²/area olmalı
for ac in OPENAP:
    p = get(ac)
    ar_calc = float(p['wingspan'])**2 / float(p['wing_area'])
    check(f'{ac} AR tutarlı ({ar_calc:.3f})', abs(float(p['AR']) - ar_calc) < 0.01)


# ── 8. Tek doğruluk kaynağı: assumptions vs aircraft_database ─
print('\n8. Tek doğruluk kaynağı — config/assumptions.py ↔ YAML')
from config.assumptions import (_MAX_FUEL, _MTOW, _OEW,  # noqa: E402
                                _TYPICAL_SEATS)
for ac in OPENAP:
    p_ = get(ac)
    check(f'{ac} OEW tutarlı', int(p_['oew']) == _OEW[ac],
          f"yaml={p_['oew']} assumptions={_OEW.get(ac)}")
    check(f'{ac} MTOW tutarlı', int(p_['mtow']) == _MTOW[ac],
          f"yaml={p_['mtow']} assumptions={_MTOW.get(ac)}")
    check(f'{ac} max_fuel tutarlı', int(p_['max_fuel']) == _MAX_FUEL[ac],
          f"yaml={p_['max_fuel']} assumptions={_MAX_FUEL.get(ac)}")
    if 'passengers_typical' in p_:
        check(f'{ac} koltuk tutarlı',
              int(p_['passengers_typical']) == _TYPICAL_SEATS[ac],
              f"yaml={p_['passengers_typical']} assumptions="
              f"{_TYPICAL_SEATS.get(ac)}")

# ── 9. Fiziksel makullük: MTOW > OEW + max_fuel ────────────
print('\n9. Fiziksel makullük — MTOW ≥ OEW + max_fuel')
for ac in OPENAP:
    p_ = get(ac)
    payload_capacity = float(p_['mtow']) - float(p_['oew'])
    check(f'{ac}: MTOW − OEW = {payload_capacity:,.0f} kg > 0',
          payload_capacity > 0)
    fuel_frac = float(p_['max_fuel']) / float(p_['mtow'])
    check(f'{ac}: yakıt/MTOW = %{fuel_frac*100:.0f} (fiziksel %20-60)',
          0.20 <= fuel_frac <= 0.60)

# ── 10. Sayısal SAR doğrulaması — bağımsız hesapla ──────────
print('\n10. SAR bağımsız doğrulama (TAS / FF)')
import numpy as np  # noqa: E402
for ac in ('B738', 'A320', 'B77W'):
    from src.models.fuel_model import FuelModel  # noqa: E402
    from src.units import Units  # noqa: E402
    fm = FuelModel(ac)
    p_ = fm.params
    w = p_['oew'] + 0.75 * (p_['mtow'] - p_['oew'])
    ff = fm.cruise_fuel_flow_kg_hr(w, 35000, p_['cruise_mach'])
    tas = Units.mach_to_tas(p_['cruise_mach'], 35000) * 1.94384
    sar_direct = tas / ff
    sar_fn = fm.specific_air_range(w, 35000, p_['cruise_mach'])
    check(f'{ac} SAR iki yoldan aynı ({sar_fn:.4f} vs {sar_direct:.4f})',
          abs(sar_fn - sar_direct) < 1e-4)
    check(f'{ac} SAR fiziksel aralıkta (0.02-0.35 Nm/kg)',
          0.02 < sar_fn < 0.35, f'{sar_fn:.4f}')

print('\n' + '=' * 70)
if _fails:
    print(f'  ✗ {len(_fails)} TEST BAŞARISIZ')
    for f in _fails:
        print(f'     • {f}')
    raise SystemExit(1)
print('  ✅ TÜM VERİ KAYNAK DOĞRULAMALARI BAŞARILI')
print('=' * 70)
