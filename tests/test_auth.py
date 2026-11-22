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
_src = (ROOT / 'web' / 'app.py').read_text(encoding='utf-8')
check("login_page imzasında 'next:' parametresi YOK",
      "def login_page(request: Request, next: str" not in _src)
check("login_page 'next_url' kullanıyor",
      "def login_page(request: Request, next_url: str" in _src)
check("builtin next() gölgelenmiyor",
      "next(iter(users))" in _src)

print('\n' + '=' * 62)
if _fails:
    print(f'  ✗ {len(_fails)} TEST BAŞARISIZ: ' + ', '.join(_fails))
    raise SystemExit(1)
print('  ✅ TÜM KİMLİK DOĞRULAMA TESTLERİ BAŞARILI')
print('=' * 62)
