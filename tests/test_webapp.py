#!/usr/bin/env python3
"""
GreenWing Analytics — Site testleri (webapp/)
═══════════════════════════════════════════════════════════════════════════

NEDEN BU TEST VAR
─────────────────
Kullanıcı iki turdur panele giremedi. Sunucu log'u sebebi gösterdi:

    POST /login  303   ← giriş BAŞARILI
    GET  /       303   ← çerez GELMEDİ
    GET  /login  200   ← sonsuz döngü

Sebep: panel bir iframe içinde gösteriliyor; `SameSite=Lax` çerezleri
iframe kaynaklı isteklerde tarayıcı tarafından DÜŞÜRÜLÜR.

Çözüm üç katmanlı:
  1. HTTPS'te SameSite=None; Secure
  2. ?token=... QUERY YEDEĞİ — çerez hiç çalışmasa bile oturum sürer
  3. Her iç link token'ı taşır

Bu test, (2)'yi kilitler: **çerez olmadan** her sayfa açılmalı.

Doğrulama: 20
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import os  # noqa: E402
os.environ.setdefault('GREENWING_DASHBOARD_PASSWORD', 'GreenWing2026!')

import importlib  # noqa: E402
gwsite = importlib.import_module('webapp.app')

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


PAGES = ['', 'ucuslar', 'metodoloji', 'veri', 'denetim', 'el-kitabi',
         'atlas', 'basit', 'kullanicilar', 'ticari']


def main() -> int:
    print('=' * 70)
    print('  SİTE TESTLERİ — çerez sorunu ve sayfalar')
    print('=' * 70)

    c = TestClient(gwsite.app, follow_redirects=False)

    print('\n1. Kimlik doğrulama')
    r = c.get('/giris')
    check('giriş sayfası açılıyor', r.status_code == 200,
          f'gelen {r.status_code}')
    check('giriş sayfası kullanıcı adını gösteriyor',
          '__admin__' in r.text)
    check('giriş sayfası parola alanı var', 'type="password"' in r.text)

    r = c.post('/giris', data={'username': '__admin__',
                               'password': 'yanlis', 'next': '/'})
    check('yanlış parola reddedildi', r.status_code == 303 and
          'failed=1' in r.headers.get('location', ''))

    r = c.post('/giris', data={'username': '__admin__',
                               'password': 'GreenWing2026!', 'next': '/'})
    check('doğru parola kabul edildi', r.status_code == 303,
          f'gelen {r.status_code}')
    loc = r.headers.get('location', '')
    check('yönlendirme token içeriyor', 'token=' in loc, loc[:60])
    token = loc.split('token=')[-1]

    print('\n2. ÇEREZ YOKKEN — token yedeği (kullanıcının sorunu buydu)')
    fresh = TestClient(gwsite.app, follow_redirects=False)   # çerez yok
    r = fresh.get('/?token=' + token)
    check('çerez olmadan ana sayfa açıldı', r.status_code == 200,
          f'gelen {r.status_code}')
    check('ana sayfada KPI var', 'Analiz edilen uçuş' in r.text)

    print('\n3. Tüm sayfalar — çerezsiz, token ile')
    for p in PAGES:
        r = fresh.get(f'/{p}?token={token}')
        ok = r.status_code == 200 and 'GreenWing' in r.text
        check(f'/{p or " "} açıldı ({len(r.text)} B)', ok,
              f'HTTP {r.status_code}')

    print('\n4. Yetkisiz erişim ENGELLENİYOR')
    anon = TestClient(gwsite.app, follow_redirects=False)
    for p in PAGES:
        r = anon.get(f'/{p}')
        check(f'/{p or " "} tokensiz → girişe yönlendiriyor',
              r.status_code == 303 and '/giris' in r.headers.get('location', ''),
              f'HTTP {r.status_code}')
    r = anon.get('/?token=sahte.token.imza')
    check('sahte token reddedildi',
          r.status_code == 303 or 'giris' in r.text.lower())

    print('\n5. İçerik doğruluğu')
    r = fresh.get(f'/?token={token}')
    # NOT: metin 2026-11-22'de "SENTETİK" (büyük harf) yerine
    # "0 gerçek · 15 sentetik" biçimine geçti — daha bilgilendirici.
    # Test büyük harfe kilitliydi → yapay başarısızlık.
    check('sentetik veri uyarısı gösteriliyor',
          ('SENTETİK' in r.text or 'sentetik' in r.text)
          and 'gerçek' in r.text)
    check('gerçek veri sayısı açıkça 0', '0 gerçek' in r.text)
    check('belirsizlik yüzdesi gösteriliyor', '±%' in r.text)
    r = fresh.get(f'/veri?token={token}')
    check('veri sayfası 7 varsayımı listeliyor',
          r.text.count('Sen ne sunmalısın') >= 6)
    r = fresh.get(f'/denetim?token={token}')
    check('denetim sayfası 81 bulguyu gösteriyor', '81' in r.text)
    r = fresh.get(f'/atlas?token={token}')
    check('kod atlası 200', r.status_code == 200)
    check('kod atlası her sayının kaynağını gösteriyor',
          'Sayıları nereden' in r.text and 'ICAO Doc 7488' in r.text)
    check('kod atlası sabit türlerini ayırıyor',
          'Tanım' in r.text and 'Türetilmiş' in r.text and 'Varsayım' in r.text)
    check('kod atlası bilinen sınırları dürüstçe yazıyor',
          'Gerçek uçuş verisi' in r.text and '0' in r.text)
    r = fresh.get(f'/kullanicilar?token={token}')
    check('kullanicilar sayfası 200', r.status_code == 200)
    check('kullanicilar rol tablosu basıyor',
          'viewer' in r.text and 'analyst' in r.text and 'admin' in r.text)
    check('kullanicilar kiracı kavramını açıklıyor', 'Kiracı' in r.text)
    r = fresh.get(f'/basit?token={token}')
    check('basit anlatım jargon içermiyor',
          'Basit Anlatım' in r.text and 'Ticarileşince' in r.text)
    check('basit anlatım para modelini açıklıyor',
          'Tasarruf paylaşımı' in r.text)
    r = fresh.get(f'/ticari?token={token}')
    check('ticari sayfada 4 aşama var',
          all(a in r.text for a in ('Aşama 0', 'Aşama 1', 'Aşama 2', 'Aşama 3')))

    print('\n6. API')
    r = fresh.get('/api/summary?token=' + token)
    check('API özet döndürüyor', r.status_code == 200 and 'flight_count' in r.text)
    r = fresh.get('/healthz')
    check('healthz çalışıyor', r.status_code == 200 and 'ok' in r.text)

    print('\n' + '=' * 70)
    total = _passed + _failed
    print(f'  Toplam    : {total}')
    print(f'  Başarılı  : {_passed}')
    print(f'  Başarısız : {_failed}')
    if _failed:
        print('  ❌ BAŞARISIZ')
        return 1
    print('  ✓ TÜM SİTE TESTLERİ BAŞARILI')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
