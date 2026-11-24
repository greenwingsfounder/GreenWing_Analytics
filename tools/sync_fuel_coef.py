"""
IAO EDB (OpenAP) yakıt katsayılarını uçak veritabanına yazar.

Ek olarak: katsayılar 'default × ff_to' yoluyla türetildiyse bu, katsayının
kendisiyle birlikte yorum olarak da yazılır — böylece kaynağı okunabilir.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'openap'

TYPE_MAP = {'B738': 'B738', 'B38M': 'B38M', 'A320': 'A320', 'A20N': 'A20N',
            'A321': 'A321', 'A21N': 'A21N', 'B77W': 'B77W', 'B788': 'B788',
            'B789': 'B789', 'A350': 'A359', 'A380': 'A388'}
ENGINE_MAP = {
    'B738': 'CFM56-7B26E', 'B38M': 'LEAP-1B27', 'A320': 'CFM56-5B4/P',
    'A20N': 'LEAP-1A26/26E1', 'A321': 'V2533-A5',
    'A21N': 'LEAP-1A35A/33/33B2/32/30', 'B77W': 'GE90-115B',
    'B788': 'GENX-1B70', 'B789': 'GENX-1B70', 'A350': 'TRENT XWB-84',
    'A380': 'TRENT 970-84',
}


def main() -> int:
    fuel = {r['typecode'].upper(): (float(r['c1']), float(r['c2']), float(r['c3']))
            for r in csv.DictReader(open(DATA / 'fuel' / 'fuel_models.csv', encoding='utf-8'))}
    eng = {r['name'].upper(): float(r['ff_to'])
           for r in csv.DictReader(open(DATA / 'engine' / 'engines.csv', encoding='utf-8'))}
    dflt = fuel['DEFAULT']

    lines = (ROOT / 'config' / 'aircraft_database.yaml').read_text(encoding='utf-8').split('\n')
    cur, n = None, 0
    for i, line in enumerate(lines):
        m = re.match(r'^  ([A-Z][0-9A-Z]{2,3}):\s*$', line)
        if m and m.group(1) in TYPE_MAP:
            cur = m.group(1)
        if cur and line.strip().startswith('fuel_coef:'):
            tc = TYPE_MAP[cur]
            if tc in fuel:
                c1, c2, c3 = fuel[tc]
                origin = f'doğrudan ICAO EDB ({tc})'
            else:
                ff_to = eng[ENGINE_MAP[cur].upper()]
                c1, c2, c3 = dflt[0] * ff_to, dflt[1], dflt[2]
                origin = f'default × ff_to({ENGINE_MAP[cur]}) = {ff_to}'
            lines[i] = (f'    # Kaynak: ICAO EDB / OpenAP — {origin}\n'
                        f'    fuel_coef: [{c1:.6f}, {c2:.6f}, {c3:.6f}]')
            n += 1
    (ROOT / 'config' / 'aircraft_database.yaml').write_text('\n'.join(lines), encoding='utf-8')
    print(f"fuel_coef: {n} tip güncellendi")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
