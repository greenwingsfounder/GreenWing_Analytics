"""
Dashboard kimlik doğrulama — oturum tabanlı, güvenli varsayılanlar.

TASARIM KARARLARI
-----------------
1. **Varsayılan olarak KAPALI DEĞİL, AÇIK.** Dashboard ticari bir
   üründür; kimlik doğrulamasız bir dashboard, müşteri verisinin
   (uçuş, yakıt maliyeti, rota) herkese açık olması demektir.
2. **Parola düz metin saklanmaz.** PBKDF2-HMAC-SHA256, 600 000 iterasyon
   (OWASP 2023 önerisi), kullanıcı başına rastgele salt.
3. **Sabit-zamanlı karşılaştırma** (`hmac.compare_digest`) — timing
   saldırısını engeller.
4. **Brute-force koruması**: kullanıcı/IP başına kayan pencere
   (5 deneme / 5 dk) → 15 dk kilit.
5. **Oturumlar imzalı** (HMAC-SHA256) — sunucuda durum tutmaz,
   çoklu instance'ta çalışır. Oturum çerezi HttpOnly + SameSite=Lax
   (+ HTTPS'te Secure).
6. **Parola kaynağı**: ortam değişkeni `GREENWING_DASHBOARD_PASSWORD`
   veya `config/secrets.yaml` (git'e girmez). İkisi de yoksa
   dashboard AÇILMAZ ve net hata verir — sessizce açık başlamaz.
7. **Yol enjeksiyonu koruması**: giriş sonrası dönüş adresi yalnızca
   yerel (aynı origin) yollara izin verir.

KULLANIM
--------
    from src.security.auth import DashboardAuth
    auth = DashboardAuth.from_env()
    if not auth.verify(username, password):
        ...
    cookie = auth.issue_session(username)
    ok, user = auth.validate_session(cookie)

Parola hash'i üretmek için:
    python -m src.security.auth --hash
"""

from __future__ import annotations

# ── ROLLER VE KİRACILAR (denetim #84 — ticarileşme P0) ─────────────
# Ticari üründe her müşteri bir "kiracı"dır (tenant) ve her kullanıcının
# bir rolü vardır. Bunlar olmadan:
#   • Bir müşteri diğerinin uçuş/yakıt verisini görebilir → KVKK/GDPR ihlali
#   • Yakıt müdürü ile stajyer aynı yetkiye sahip olur
#   • "Bu raporu kim üretti" sorusu cevapsız kalır
#
# Rol yetkileri (küçükten büyüğe):
#   viewer  : yalnızca okuma (rapor görüntüleme)
#   analyst : okuma + analiz çalıştırma + kalibrasyon
#   admin   : tam yetki (kullanıcı yönetimi, veri silme, sırlar)
ROLES = ('viewer', 'analyst', 'admin')
ROLE_LEVEL = {'viewer': 1, 'analyst': 2, 'admin': 3}
DEFAULT_TENANT = 'varsayilan'


import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# ── Kriptografik parametreler ────────────────────────────────
_PBKDF2_ITERATIONS = 600_000       # OWASP 2023: PBKDF2-HMAC-SHA256 ≥ 600k
_PBKDF2_ALGO = 'sha256'
_SALT_BYTES = 16
_SESSION_TTL_S = 8 * 3600          # 8 saat
_MAX_ATTEMPTS = 5
_ATTEMPT_WINDOW_S = 300            # 5 dakika
_LOCKOUT_S = 900                   # 15 dakika

ROOT = Path(__file__).resolve().parents[2]
_SECRETS_FILE = ROOT / 'config' / 'secrets.yaml'


class AuthConfigError(RuntimeError):
    """Kimlik doğrulama yapılandırılmamış — dashboard açılmamalı."""


@dataclass
class _Attempt:
    count: int = 0
    window_start: float = 0.0
    locked_until: float = 0.0


def safe_next_url(next_url: Optional[str], default: str = '/') -> str:
    """
    Giriş sonrası dönüş adresini doğrula (open-redirect koruması).

    Yalnızca kök-göreli yollara izin verir: '/abc', '/' → OK
    '//evil.com', 'http://evil.com' → default
    """
    if not next_url:
        return default
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return default
    if not next_url.startswith('/') or next_url.startswith('//'):
        return default
    return next_url


@dataclass
class DashboardAuth:
    """Oturum tabanlı dashboard kimlik doğrulaması."""

    users: dict[str, dict]                  # kullanıcı → {salt, hash}
    session_secret: bytes
    cookie_name: str = 'gw_session'
    secure_cookie: bool = True
    _attempts: dict[str, _Attempt] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ── Kurulum ────────────────────────────────────────────
    @classmethod
    def from_env(cls) -> 'DashboardAuth':
        """
        Kimlik bilgilerini ortamdan / secrets dosyasından yükle.

        Öncelik sırası:
            1. GREENWING_USERS  = JSON  {kullanıcı: "pbkdf2$iter$salt$hash"}
            2. GREENWING_DASHBOARD_PASSWORD (tek kullanıcı '__admin__')
            3. config/secrets.yaml (users: {...})
            4. GREENWING_ALLOW_INSECURE_DEMO=1 → demo parola (SADECE demo)

        Hiçbiri yoksa AuthConfigError — dashboard açılmaz.
        """
        raw_users: dict[str, object] = {}

        env_users = os.environ.get('GREENWING_USERS', '').strip()
        if env_users:
            try:
                raw_users = {str(k): str(v)
                             for k, v in json.loads(env_users).items()}
            except json.JSONDecodeError as exc:
                raise AuthConfigError(
                    f'GREENWING_USERS geçerli JSON değil: {exc}') from exc

        if not raw_users:
            pw = os.environ.get('GREENWING_DASHBOARD_PASSWORD')
            if pw:
                raw_users = {'__admin__': DashboardAuth.hash_password(pw)}

        if not raw_users and _SECRETS_FILE.exists():
            try:
                import yaml
                data = yaml.safe_load(_SECRETS_FILE.read_text(encoding='utf-8')) or {}
                # Değer düz hash VEYA {hash, role, tenant} olabilir.
                # Ticari kurulumda rol/kiracı BURADAN gelir.
                parsed: dict[str, object] = {}
                for k, v in (data.get('users') or {}).items():
                    if isinstance(v, dict):
                        parsed[str(k)] = {
                            'hash': str(v.get('hash') or v.get('password') or ''),
                            'role': str(v.get('role') or 'admin').lower(),
                            'tenant': str(v.get('tenant') or DEFAULT_TENANT),
                        }
                    else:
                        parsed[str(k)] = str(v)
                raw_users = parsed
            except Exception as exc:  # noqa: BLE001
                raise AuthConfigError(
                    f'{_SECRETS_FILE} okunamadı — geçerli YAML ve users: '
                    f'bölümü gerekli ({exc})') from exc

        if not raw_users and os.environ.get('GREENWING_ALLOW_INSECURE_DEMO') == '1':
            raw_users = {'demo': DashboardAuth.hash_password('demo')}
            print('⚠  GÜVENSİZ DEMO MODU: kullanıcı=demo parola=demo. '
                  'Üretimde GREENWING_ALLOW_INSECURE_DEMO KULLANMAYIN.')

        if not raw_users:
            raise AuthConfigError(
                'Dashboard kimlik doğrulaması yapılandırılmamış.\n'
                'En az birini tanımlayın:\n'
                '  • GREENWING_DASHBOARD_PASSWORD=<parola>   (tek kullanıcı)\n'
                '  • GREENWING_USERS=\'{"ali":"pbkdf2$...", ...}\'\n'
                '  • config/secrets.yaml → users: {ali: "pbkdf2$..."}\n'
                'Hash üretmek için: python -m src.security.auth --hash')

        secret_env = os.environ.get('GREENWING_SESSION_SECRET', '').strip()
        secret = (secret_env.encode() if secret_env else secrets.token_bytes(32))
        if not secret_env:
            print('ℹ  GREENWING_SESSION_SECRET verilmedi → her başlatmada yeni '
                  'oturum anahtarı (yeniden başlatmada oturumlar düşer).')

        secure = os.environ.get('GREENWING_INSECURE_COOKIE') != '1'
        return cls(users=raw_users, session_secret=secret, secure_cookie=secure)

    # ── Parola ─────────────────────────────────────────────
    @staticmethod
    def hash_password(password: str,
                      *,
                      iterations: int = _PBKDF2_ITERATIONS) -> str:
        """Parolayı 'pbkdf2$iterasyon$salt$hash' biçiminde hash'le."""
        if not password:
            raise ValueError('Parola boş olamaz')
        salt = secrets.token_bytes(_SALT_BYTES)
        dk = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode('utf-8'),
                                 salt, iterations)
        return (f'pbkdf2${iterations}${base64.b64encode(salt).decode()}'
                f'${base64.b64encode(dk).decode()}')

    @staticmethod
    def _verify_hash(password: str, stored: str) -> bool:
        try:
            algo, iters, salt_b64, hash_b64 = stored.split('$', 3)
            if algo != 'pbkdf2':
                return False
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
            dk = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode('utf-8'),
                                     salt, int(iters))
            return hmac.compare_digest(dk, expected)
        except (ValueError, TypeError):
            return False

    # ── Brute-force koruması ───────────────────────────────
    def _key(self, username: str, ip: str = '') -> str:
        return f'{username}|{ip}'

    def is_locked(self, username: str, ip: str = '') -> bool:
        key = self._key(username, ip)
        now = time.time()
        with self._lock:
            rec = self._attempts.get(key)
            if rec and rec.locked_until > now:
                return True
            if rec and rec.locked_until:
                self._attempts.pop(key, None)
        return False

    def _register_failure(self, username: str, ip: str = '') -> None:
        key = self._key(username, ip)
        now = time.time()
        with self._lock:
            rec = self._attempts.setdefault(key, _Attempt(window_start=now))
            if now - rec.window_start > _ATTEMPT_WINDOW_S:
                rec.count, rec.window_start = 0, now
            rec.count += 1
            if rec.count >= _MAX_ATTEMPTS:
                rec.locked_until = now + _LOCKOUT_S
                rec.count = 0

    def _register_success(self, username: str, ip: str = '') -> None:
        with self._lock:
            self._attempts.pop(self._key(username, ip), None)

    def remaining_lockout(self, username: str, ip: str = '') -> int:
        with self._lock:
            rec = self._attempts.get(self._key(username, ip))
            if rec and rec.locked_until > time.time():
                return int(rec.locked_until - time.time())
        return 0

    # ── Giriş ──────────────────────────────────────────────
    def verify(self, username: str, password: str, ip: str = '') -> bool:
        """Kullanıcı adı + parola doğrula (brute-force korumalı)."""
        username = (username or '').strip()
        if self.is_locked(username, ip):
            return False
        stored_raw = self.users.get(username)
        if not stored_raw:
            # Kullanıcı yoksa da hash süresi harcayarak enumeration'ı zorlaştır
            self._verify_hash(password or '', self.hash_password('dummy'))
            self._register_failure(username, ip)
            return False
        # Kullanıcı kaydı düz string (eski biçim) veya sözlük olabilir
        stored = (stored_raw.get('hash')
                  if isinstance(stored_raw, dict) else stored_raw)
        if not stored:
            self._register_failure(username, ip)
            return False
        if self._verify_hash(password or '', stored):
            self._register_success(username, ip)
            return True
        self._register_failure(username, ip)
        return False

    # ── Oturum ─────────────────────────────────────────────
    # ── Profil (rol / kiracı) ──────────────────────────────
    def profile(self, username: str) -> dict:
        """
        Kullanıcının rolü ve kiracısı.

        Geriye dönük uyum: `users` değeri düz hash string ise kullanıcı
        admin + varsayılan kiracı sayılır (tek kullanıcılı kurulum).
        """
        raw = self.users.get(username)
        if isinstance(raw, dict):
            role = str(raw.get('role') or 'admin').lower()
            tenant = str(raw.get('tenant') or DEFAULT_TENANT)
        else:
            role, tenant = 'admin', DEFAULT_TENANT
        if role not in ROLES:
            role = 'viewer'
        return {'username': username, 'role': role, 'tenant': tenant,
                'level': ROLE_LEVEL[role]}

    def can(self, username: str, required: str) -> bool:
        """Kullanıcı `required` seviyesini karşılıyor mu?"""
        return self.profile(username)['level'] >= ROLE_LEVEL.get(required, 99)

    def users_of_tenant(self, tenant: str) -> list[str]:
        """Bir kiracıya bağlı kullanıcıları listele."""
        return [u for u in self.users if self.profile(u)['tenant'] == tenant]

    def issue_session(self, username: str) -> str:
        """İmzalı oturum çerezi üret (padding'siz base64url)."""
        payload = {
            'u': username,
            'exp': int(time.time()) + _SESSION_TTL_S,
            'n': _b64e(secrets.token_bytes(9)),
        }
        body = _b64e(json.dumps(payload, separators=(',', ':')).encode())
        sig = hmac.new(self.session_secret, body.encode(), hashlib.sha256).digest()
        return f'{body}.{_b64e(sig)}'

    def validate_session(self, cookie: Optional[str]) -> tuple[bool, Optional[str]]:
        """Oturum çerezini doğrula → (geçerli, kullanıcı)."""
        if not cookie or '.' not in cookie:
            return False, None
        body, _, sig_b64 = cookie.strip('"').rpartition('.')
        try:
            sig = _b64d(sig_b64)
        except (ValueError, TypeError):
            return False, None
        expected = hmac.new(self.session_secret, body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return False, None
        try:
            payload = json.loads(_b64d(body))
        except (ValueError, TypeError):
            return False, None
        if int(payload.get('exp', 0)) < time.time():
            return False, None
        user = payload.get('u')
        if user not in self.users:
            return False, None
        return True, user


def _b64e(raw: bytes) -> str:
    """
    base64url kodla, PADDING'SİZ.

    NEDEN: '=' karakteri HTTP cookie değerinde geçersizdir (RFC 6265
    cookie-octet tanımı). Starlette bunu görünce değeri TIRNAK İÇİNE
    alır (``gw_session="..."``); bazı proxy/tarayıcı kombinasyonları
    tırnaklı değeri bozar ve oturum her istekte geçersiz olur →
    sonsuz login döngüsü. Padding'i atarak yalnızca [A-Za-z0-9_-]
    kalır; hepsi geçerli cookie-octet'tir.
    """
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _b64d(text: str) -> bytes:
    """_b64e'nin tersi (eksik padding'i geri ekler)."""
    pad = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# ── CLI: hash üret ─────────────────────────────────────────
def _main() -> int:
    import argparse
    import getpass

    ap = argparse.ArgumentParser(
        description='GreenWing dashboard kimlik doğrulama aracı')
    ap.add_argument('--hash', action='store_true', help="Parola hash'i üret")
    ap.add_argument('--user', default='admin', help='Kullanıcı adı')
    args = ap.parse_args()

    if args.hash:
        pw = getpass.getpass('Parola: ')
        if getpass.getpass('Tekrar: ') != pw:
            print('Parolalar eşleşmiyor')
            return 1
        print(f'\n{args.user}: {DashboardAuth.hash_password(pw)}')
        print("\nKullanım: GREENWING_USERS='{\"%s\":\"<yukarıdaki>\"}'" % args.user)
        return 0
    print('Kullanım: python -m src.security.auth --hash [--user ali]')
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
