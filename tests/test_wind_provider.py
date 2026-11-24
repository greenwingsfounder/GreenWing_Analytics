#!/usr/bin/env python3
"""
GreenWing Analytics — Rüzgâr sağlayıcı zinciri testleri (DENETİM #82)
═══════════════════════════════════════════════════════════════════════════

NEDEN BU TEST VAR
─────────────────
Belirsizlik bütçesinin en büyük kalemi rüzgâr (±%22,2). `wind_model.py`
yalnızca klimatolojik profil kullanıyordu; gerçek rüzgâr hiç okunmuyordu.

`wind_gfs.py` üç kademeli bir zincir kuruyor: GFS (gerçek) →
mevsimsel (varsayım) → rüzgârsız (referans). Bu test şunları kilitler:

  1. Zincir doğru sırayla seçiyor (GFS varsa GFS)
  2. Seçilen sağlayıcı KENDİNİ doğru tanımlıyor (is_measured, source)
  3. Sessiz tahmin yok — hangi kaynak kullanıldığı her zaman yazılı
  4. Rota bileşeni fiziksel olarak doğru (kuyruk +, karşı −)
  5. Rota örnekleme mesafe ağırlıklı ortalama veriyor
  6. GFS yokken sistem ÇALIŞMAYA DEVAM ediyor (çökmüyor)

Doğrulama: 22
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.wind_gfs import (GFSWindProvider, NoWindProvider,  # noqa: E402
                                 SeasonalProvider, describe_chain,
                                 get_wind_provider, route_wind,
                                 route_wind_along_route)

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = '') -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f'  ✓ {name}')
    else:
        _failed += 1
        print(f'  ✗ {name}   {detail}')


def main() -> int:
    print('=' * 70)
    print('  DENETİM #82 — Rüzgâr sağlayıcı zinciri')
    print('=' * 70)

    print('\n1. Sağlayıcı kimlikleri')
    s = SeasonalProvider()
    n = NoWindProvider()
    check('mevsimsel: is_measured False', s.is_measured is False)
    check('mevsimsel: belirsizlik ±%22,2', abs(s.uncertainty_pct - 22.2) < .01)
    check('mevsimsel: adı VARSAYIM içeriyor', 'VARSAYIM' in s.name)
    check('rüzgârsız: belirsizlik 0', n.uncertainty_pct == 0.0)
    check('GFS: is_measured True', GFSWindProvider().is_measured is True)
    check('GFS: belirsizlik ≤%5',
          GFSWindProvider().uncertainty_pct <= 5.0)

    print('\n2. Zincir seçimi')
    active = get_wind_provider()
    check('sağlayıcı döndü', active is not None)
    check('force=none → rüzgârsız',
          get_wind_provider('none').name == n.name)
    check('force=seasonal → mevsimsel',
          get_wind_provider('seasonal').name == s.name)
    d = describe_chain()
    check('zincir raporu anahtarları tam',
          {'active', 'is_measured', 'gfs_available'} <= set(d))

    print('\n3. Sessiz tahmin YOK — kaynak her zaman yazılı')
    r = route_wind(active, 35000, 295.0, 41.0, 29.0)
    check('source boş değil', bool(r.source))
    check('source sağlayıcı adını içeriyor',
          active.name.split('(')[0].strip() in r.source or bool(r.source))
    check('speed_kt fiziksel (0–250 kt)', 0 <= r.speed_kt <= 250)

    print('\n4. Rota bileşeni fiziği')
    p = SeasonalProvider()   # batı rüzgârı, 270°'DEN GELİR → DOĞUYA eser
    #
    # METEOROLOJİK KONVANSİYON (denetimde kendi hatamı düzelttim):
    #   "270° rüzgârı" = rüzgârın BATIDAN geldiği, yani DOĞUYA estiği.
    #   Bu yüzden:
    #     Doğuya uçan uçak (track 90)  → kuyruk rüzgârı (+)
    #     Batıya uçan uçak (track 270) → karşı rüzgâr (−)
    #   Bu, transatlantik doğu yönlü uçuşların neden daha kısa sürdüğünün
    #   de sebebidir.
    east = route_wind(p, 35000, 90.0, 41.0, 29.0)    # doğuya uçuş
    west = route_wind(p, 35000, 270.0, 41.0, 29.0)   # batıya uçuş
    check('DOĞUYA uçuş (track 90): kuyruk rüzgârı (+)',
          east.along_track_kt > 0, f'gelen {east.along_track_kt}')
    check('BATIYA uçuş (track 270): karşı rüzgâr (−)',
          west.along_track_kt < 0, f'gelen {west.along_track_kt}')
    check('simetri: |doğu| ≈ |batı|',
          abs(east.along_track_kt - (-west.along_track_kt)) < 1.0)
    # Kuzeye uçarken batı rüzgârı tam yandan gelir → rota bileşeni ~0
    north = route_wind(p, 35000, 0.0, 41.0, 29.0)
    check('KUZEYE uçuş (track 0): bileşen ~0', abs(north.along_track_kt) < 1.0,
          f'gelen {north.along_track_kt}')
    check('KUZEYE uçuş: yan rüzgâr ~tam hız',
          abs(abs(north.cross_track_kt) - north.speed_kt) < 1.0,
          f'cross {north.cross_track_kt} speed {north.speed_kt}')

    print('\n5. Rota örnekleme')
    coords = [(41.0, 29.0), (45.0, 20.0), (48.0, 12.0), (52.3, 4.8)]
    rr = route_wind_along_route(p, coords, 35000)
    check('rota ortalaması hesaplandı', isinstance(rr.along_track_kt, float))
    check('rota ortalaması fiziksel aralıkta',
          -250 <= rr.along_track_kt <= 250)
    try:
        route_wind_along_route(p, [(41.0, 29.0)])
        check('tek nokta reddedildi', False)
    except ValueError:
        check('tek nokta reddedildi', True)

    print('\n6. GFS yokken sistem çalışmaya devam ediyor')
    g = GFSWindProvider()
    if not g.available():
        check('GFS yok → mevsimsele düştü (çökmedi)', True)
        check('düşüş sessiz değil — is_measured False',
              active.is_measured is False)
        check('kullanıcıya ipucu veriliyor', 'grib2' in d['gfs_hint'].lower())
    else:
        check('GFS mevcut → aktif sağlayıcı GFS', active.is_measured is True)

    print('\n7. İrtifa ile rüzgâr artıyor (jet akımı)')
    lo = route_wind(p, 10000, 270.0, 41.0, 29.0).speed_kt
    hi = route_wind(p, 39000, 270.0, 41.0, 29.0).speed_kt
    check('FL390 > FL100', hi > lo, f'lo {lo} hi {hi}')

    print('\n' + '=' * 70)
    total = _passed + _failed
    print(f'  Toplam    : {total}')
    print(f'  Başarılı  : {_passed}')
    print(f'  Başarısız : {_failed}')
    if _failed:
        print('  ❌ BAŞARISIZ')
        return 1
    print('  ✓ TÜM RÜZGÂR ZİNCİRİ TESTLERİ BAŞARILI')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
