"""
OpenAP parametrelerini uçak veritabanına senkronize eder
========================================================

NE YAPAR
--------
data/openap/ altındaki OpenAP verisinden her uçak tipi için
CD0, k (=K) ve e değerlerini okur; config/aircraft_database.yaml
içindeki ilgili alanları günceller ve config/aircraft_polar_sources.yaml
kaynak kaydını yeniden yazar.

BÖYLECE
-------
Her uçak parametresinin kaynağı bellidir (OpenAP = ADS-B verisinden
türetilmiş, TU Delft, açık kaynak). "Nereden geldi?" sorusunun cevabı
tek dosyada durur ve kod ile veri arasında kayma olamaz.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / 'data' / 'openap_reference.json'
DB = ROOT / 'config' / 'aircraft_database.yaml'
SRC = ROOT / 'config' / 'aircraft_polar_sources.yaml'


def main() -> int:
    ref = {r['ac']: r for r in json.loads(REF.read_text(encoding='utf-8'))['rows']}

    lines = DB.read_text(encoding='utf-8').split('\n')
    cur = None
    changed = 0
    for i, line in enumerate(lines):
        m = re.match(r'^  ([A-Z][0-9A-Z]{2,3}):\s*$', line)
        if m and m.group(1) in ref:
            cur = m.group(1)
        if cur and re.match(r'^\s+(CD0|K|e):\s', line):
            key = line.strip().split(':')[0]
            val = ref[cur][{'CD0': 'cd0', 'K': 'k', 'e': 'e_polar'}[key]]
            if val is None:
                continue
            if key == 'CD0':
                txt = f'    CD0: {val:.4f}'
            elif key == 'K':
                txt = f'    K: {val:.5f}'
            else:
                txt = f'    e: {val:.4f}'
            if line.strip() != txt.strip():
                lines[i] = txt
                changed += 1
    DB.write_text('\n'.join(lines), encoding='utf-8')
    print(f"aircraft_database.yaml: {changed} alan güncellendi")

    # Kaynak kaydını yeniden yaz
    out = {
        'version': '2026-11-22',
        'method': 'OpenAP (TU Delft) drag polar — ADS-B verisinden türetilmiş',
        'primary_source': {
            'name': 'OpenAP v3',
            'authors': 'Junzi Sun, Jacco Hoekstra (TU Delft)',
            'url': 'https://github.com/junzis/openap',
            'data': 'openap/data/dragpolar/<type>.yml',
            'structure': 'CD = CD0 + k·CL²  (BADA 3 ile aynı yapı)',
            'derivation': 'ADS-B uçuş verisinden MCMC ile tahmin',
            'license': 'Açık kaynak (MIT) — kullanım kısıtı yok',
        },
        'secondary_source': {
            'name': 'Sun et al., Aircraft Drag Polar Estimation (SESAR JU)',
            'note': 'OpenAP ile aynı yazarlar; çapraz doğrulama için',
        },
        'per_type': {},
    }
    for ac, r in ref.items():
        out['per_type'][ac] = {
            'openap_type': r['openap_type'],
            'CD0': r['cd0'],
            'K': r['k'],
            'e': r['e_polar'],
            'reference_kg_per_nm': round(r['kg_per_nm'], 2),
            'reference_ff_kg_hr': round(r['ff_kg_hr']),
            'source': 'OpenAP dragpolar yml',
        }
    SRC.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True,
                                 default_flow_style=False), encoding='utf-8')
    print(f"aircraft_polar_sources.yaml yeniden yazıldı ({len(ref)} tip)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
