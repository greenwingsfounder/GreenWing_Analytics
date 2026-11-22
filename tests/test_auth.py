"""src/security/auth.py testleri — parola, oturum, brute-force, açık yönlendirme."""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.security.auth import (AuthConfigError, DashboardAuth,  # noqa: E402
                               safe_next_url)

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = '') -> None:
    if cond:
        print(f'  ✓ {name}')
    else:
        _fails.append(name)
        print(f'  ✗ {name} {detail}')


print('\n' + '=' * 62)
print('  KİMLİK DOĞRULAMA TESTLERİ')
print('=' * 62)

# ── 1. Parola hash'leme ────────────────────────────────────
print('\n1. Parola hash\'leme')
pw = 'S3cret-Pass!'
h1 = DashboardAuth.hash_password(pw)
h2 = DashboardAuth.hash_password(pw)

check('format pbkdf2$iter$salt$hash', h1.startswith('pbkdf2$600000$'))
check('aynı parola → farklı hash (salt)', h1 != h2)
check('doğru parola doğrulanır', DashboardAuth._verify_hash(pw, h1))
check('yanlış parola reddedilir', not DashboardAuth._verify_hash('yanlis', h1))
check('boş parola reddedilir', not DashboardAuth._verify_hash('', h1))
check('bozuk hash çökmez', not DashboardAuth._verify_hash(pw, 'bozuk'))
check('truncated hash çökmez', not DashboardAuth._verify_hash(pw, 'pbkdf2$600000$abc'))
check('hash içinde düz parola yok', pw not in h1)
check('iterasyon sayısı ≥ 600k (OWASP)', '600000' in h1)

# ── 2. Doğrulama ───────────────────────────────────────────
print('\n2. Kullanıcı doğrulama')
auth = DashboardAuth(users={'ali': h1, 'veli': DashboardAuth.hash_password('Veli123')},
                     session_secret=b'K' * 32)
check('doğru kimlik', auth.verify('ali', pw))
check('yanlış parola', not auth.verify('ali', 'yanlis'))
check('olmayan kullanıcı', not auth.verify('yok', pw))
check('boş kullanıcı', not auth.verify('', pw))
check('boşluklu kullanıcı normalize', auth.verify('  ali  ', pw))

# ── 3. Oturum ──────────────────────────────────────────────
print('\n3. Oturum çerezleri')
cookie = auth.issue_session('ali')
check('çerez formatı body.sig', cookie.count('.') == 1)
ok, user = auth.validate_session(cookie)
check('geçerli oturum kullanıcıyı döndürür', ok and user == 'ali')
check('imza bozulursa reddedilir', not auth.validate_session(cookie[:-4] + 'AAAA')[0])
check('gövde bozulursa reddedilir', not auth.validate_session('bozuk' + cookie[6:])[0])
check('boş çerez reddedilir', not auth.validate_session('')[0])
check('None çerez reddedilir', not auth.validate_session(None)[0])

other = DashboardAuth(users={'ali': h1}, session_secret=b'F' * 32)
check('farklı anahtarla imzalanmış çerez reddedilir',
      not other.validate_session(cookie)[0])

check('kullanıcı silinirse oturum düşer',
      not DashboardAuth(users={}, session_secret=b'K' * 32).validate_session(cookie)[0])
check('iki oturum birbirinden farklı (nonce)', auth.issue_session('ali') != cookie)

# ── 4. Brute-force ─────────────────────────────────────────
print('\n4. Brute-force koruması')
bf = DashboardAuth(users={'ali': h1}, session_secret=b'B' * 32)
for _ in range(4):
    bf.verify('ali', 'yanlis')
check('4 hatadan sonra kilitli değil', not bf.is_locked('ali'))
bf.verify('ali', 'yanlis')
check('5 hatadan sonra kilitli', bf.is_locked('ali'))
check('kilitliyken DOĞRU parola da reddedilir', not bf.verify('ali', pw))
check('kalan süre > 0', bf.remaining_lockout('ali') > 0)
check('diğer kullanıcı etkilenmez', not bf.is_locked('veli'))
check('farklı IP etkilenmez', not bf.is_locked('ali', '10.0.0.9'))

# Başarılı giriş sayacı sıfırlar
ok2 = DashboardAuth(users={'ali': h1}, session_secret=b'C' * 32)
for _ in range(4):
    ok2.verify('ali', 'yanlis')
check('başarılı giriş sayacı sıfırlar',
      ok2.verify('ali', pw) and not ok2.is_locked('ali'))

# ── 5. Açık yönlendirme ────────────────────────────────────
print('\n5. Açık yönlendirme (open-redirect) koruması')
check('yerel yol korunur', safe_next_url('/dashboard?x=1') == '/dashboard?x=1')
for bad in ('https://evil.com', '//evil.com', 'http://evil.com/x', 'evil.com', ''):
    check(f'reddedilir: {bad!r}', safe_next_url(bad) == '/')
check('None → varsayılan', safe_next_url(None) == '/')

# ── 6. Yapılandırma zorunluluğu ────────────────────────────
print('\n6. Yapılandırma zorunluluğu (fail-closed)')
saved = {k: os.environ.pop(k, None) for k in
         ('GREENWING_USERS', 'GREENWING_DASHBOARD_PASSWORD',
          'GREENWING_ALLOW_INSECURE_DEMO', 'GREENWING_SESSION_SECRET')}
try:
    try:
        DashboardAuth.from_env()
        check('yapılandırma yoksa hata verir', False, '(hata vermedi!)')
    except AuthConfigError as exc:
        check('yapılandırma yoksa hata verir', True)
        check('hata mesajı yol gösterir', 'GREENWING_DASHBOARD_PASSWORD' in str(exc))

    os.environ['GREENWING_DASHBOARD_PASSWORD'] = 'Test123!'
    os.environ['GREENWING_SESSION_SECRET'] = 'x' * 32
    env_auth = DashboardAuth.from_env()
    check('ortam parolası ile kurulur', env_auth.verify('__admin__', 'Test123!'))
    check('Secure çerez varsayılan açık', env_auth.secure_cookie)

    os.environ['GREENWING_USERS'] = '{"a": "bozuk-json-degil-ama"}'
    u = DashboardAuth.from_env()
    check('GREENWING_USERS okunur', 'a' in u.users)
    check('geçersiz hash ile giriş olmaz', not u.verify('a', 'x'))

    os.environ['GREENWING_USERS'] = '{bozuk'
    try:
        DashboardAuth.from_env()
        check('bozuk JSON hata verir', False)
    except AuthConfigError:
        check('bozuk JSON hata verir', True)
finally:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ── 7. HTTP cookie güvenliği (7. bölüm) ───────────────────
print('\n7. Çerez biçimi ve Secure bayrağı — preview uyumu')
import re as _re
from pathlib import Path as _Path
ROOT = _Path(__file__).resolve().parents[1]

_c = auth.issue_session('ali')
check("çerez değeri yalnızca geçerli cookie-octet içerir",
      bool(_re.fullmatch(r'[A-Za-z0-9_.\-]+', _c)), f'gelen {_c[:20]}')
check("çerezde '=' padding YOK (RFC 6265)", '=' not in _c)
check("çerezde tırnak YOK", '"' not in _c and "'" not in _c)
check("padding'siz çerez doğrulanır", auth.validate_session(_c)[0])
check("tırnaklı gelen çerez de kabul edilir (proxy toleransı)",
      auth.validate_session('"' + _c + '"')[0])
check("uzunluk < 4 KB (tarayıcı sınırı)", len(_c) < 4096)

print('\n8. __next__ gölgeleme tuzağı (gerçek hata)')
# FastAPI endpoint parametresi 'next' olursa builtin next() ezilir.
# web/app.py içinde parametre adı 'next_url' olmalı.
import pathlib as _pl
# #84: test 'web/app.py'yi okuyordu — o uygulama arşivlendi.
# Depoda iki paralel uygulama vardı; test ESKİ olanı denetliyordu,
# yani canlı kodun bu tuzağa düşüp düşmediğini HİÇ kontrol etmiyordu.
# (Dosya arşivlenince test FileNotFoundError ile çöktü — o zaman fark ettim.)
_src = (ROOT / 'webapp' / 'app.py').read_text(encoding='utf-8')
check("login_page imzasında 'next:' parametresi YOK",
      "def login_page(request: Request, next: str" not in _src)
# NOT: webapp'te fonksiyon adı login_get/login_post (web/ v1'de login_page).
check("giriş handler'ı 'next_url' kullanıyor (güvenli yönlendirme)",
      "next_url=safe_next_url(next)" in _src)
# Gölgeleme riski METİN aramayla ölçülemez: aynı dosyada başka bir
# kapsamda next() çağrısı olabilir (webapp'te var: _Auth içinde).
# Doğru ölçüm AST ile: parametresi 'next' olan bir fonksiyonun
# GÖVDESİNDE next() çağrısı var mı?
import ast as _ast
_shadow = []
for _node in _ast.walk(_ast.parse(_src)):
    if isinstance(_node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
        _args = {a.arg for a in _node.args.args + _node.args.kwonlyargs}
        if 'next' in _args:
            for _inner in _ast.walk(_node):
                if (isinstance(_inner, _ast.Call)
                        and isinstance(_inner.func, _ast.Name)
                        and _inner.func.id == 'next'):
                    _shadow.append(f'{_node.name}():{_inner.lineno}')
check('parametresi next olan fonksiyonda next() çağrısı YOK (AST)',
      not _shadow, ', '.join(_shadow))
check("builtin next() gölgelenmiyor (webapp)",
      "next(iter(users))" in _src or "sorted(auth.users)" in _src)

# ── ROL / KİRACI (denetim #84) ────────────────────────────────
print('\n9. Rol ve kiracı (ticarileşme P0)')
from src.security.auth import ROLES, ROLE_LEVEL, DEFAULT_TENANT
_H = DashboardAuth.hash_password
_a = DashboardAuth(
    users={'adm': {'hash': _H('p1'), 'role': 'admin', 'tenant': 'thy'},
           'ana': {'hash': _H('p2'), 'role': 'analyst', 'tenant': 'thy'},
           'vw': {'hash': _H('p3'), 'role': 'viewer', 'tenant': 'pg'},
           'old': _H('p4')},
    session_secret=b'z' * 32, secure_cookie=False)
check('3 rol tanımlı', ROLES == ('viewer', 'analyst', 'admin'))
check('seviye sırası 1<2<3', ROLE_LEVEL['viewer'] < ROLE_LEVEL['analyst']
      < ROLE_LEVEL['admin'])
check('admin seviye 3', _a.profile('adm')['level'] == 3)
check('analyst seviye 2', _a.profile('ana')['level'] == 2)
check('viewer seviye 1', _a.profile('vw')['level'] == 1)
check('admin → admin yetkisi', _a.can('adm', 'admin'))
check('analyst → admin DEĞİL', not _a.can('ana', 'admin'))
check('analyst → analyst yetkisi', _a.can('ana', 'analyst'))
check('viewer → analyst DEĞİL', not _a.can('vw', 'analyst'))
check('viewer → viewer yetkisi', _a.can('vw', 'viewer'))
check('düz hash geriye dönük admin', _a.profile('old')['role'] == 'admin')
check('düz hash varsayılan kiracı',
      _a.profile('old')['tenant'] == DEFAULT_TENANT)
check('thy kiracısı [adm, ana]',
      sorted(_a.users_of_tenant('thy')) == ['adm', 'ana'])
check('pg kiracısı [vw]', _a.users_of_tenant('pg') == ['vw'])
check('parola + rol birlikte doğrulanır', _a.verify('ana', 'p2'))
check('yanlış parola reddedilir', not _a.verify('ana', 'xxx'))
_t = _a.issue_session('ana')
check('rol çerezde GÖMÜLÜ değil', 'admin' not in _t and 'analyst' not in _t)
# DİKKAT: token sabit uzunlukta değil — son karakteri değiştir,
# ekleme/çıkarma YAPMA (ilk denemem 4 karakter ekliyordu ve base64
# çözümü çöp üretiyordu; kod doğruydu, test yanlıştı).
_bad = _t[:-1] + ('A' if _t[-1] != 'A' else 'B')
check('bozuk imza reddedilir', not _a.validate_session(_bad)[0])
check('bozuk gövde reddedilir',
      not _a.validate_session('X' + _t[1:])[0])
check('imzasız token reddedilir', not _a.validate_session(_t.split('.')[0])[0])

print('\n' + '=' * 62)
if _fails:
    print(f'  ✗ {len(_fails)} TEST BAŞARISIZ: ' + ', '.join(_fails))
    raise SystemExit(1)
print('  ✅ TÜM KİMLİK DOĞRULAMA TESTLERİ BAŞARILI')
print('=' * 62)
