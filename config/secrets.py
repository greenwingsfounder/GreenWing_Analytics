"""
GreenWing Analytics — Gizli Anahtar Yönetimi (Secrets Management)
══════════════════════════════════════════════════════════════════

GÜVENLİK KURALI:
───────────────
Depoda gizli anahtar, şifre veya token TUTULMAZ. Kimlik bilgileri
yalnızca ortam değişkenleri (.env — .gitignore'da) veya işletim
sistemi ortam değişkenleri üzerinden okunur.

Eski "credentials.json" yaklaşımı KALDIRILDI çünkü kimlik bilgileri
kaynak kod ile birlikte commit ediliyordu. Bu modül, kimlik
bilgilerini tek yerden, kod içine gömmeden sağlar.

OKUMA ÖNCELİĞİ:
──────────────
    1. Açıkça verilen argüman          (test edilebilirlik için)
    2. Ortam değişkeni (.env dahil)
    3. Boş string → anonim erişim

KULLANIM:
─────────
    from config.secrets import get_opensky_credentials

    creds = get_opensky_credentials()
    if creds.oauth_ready:
        ...
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

# .env dosyasını proje kökünden yükle (varsa). Dosya yoksa sessiz geç.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"), override=True)


@dataclass(frozen=True)
class OpenSkyCredentials:
    """
    OpenSky Network kimlik bilgileri.

    NOT: __repr__ bilerek gizlenmiştir; yanlışlıkla loglanan bir
    nesne bile sırları ifşa etmez.
    """

    client_id: str = ""
    client_secret: str = ""
    username: str = ""
    password: str = ""

    @property
    def oauth_ready(self) -> bool:
        """OAuth2 (client credentials) kullanılabilir mi?"""
        return bool(self.client_id and self.client_secret)

    @property
    def basic_ready(self) -> bool:
        """Basic auth (kullanıcı adı/şifre) kullanılabilir mi?"""
        return bool(self.username and self.password)

    @property
    def is_authenticated(self) -> bool:
        """Herhangi bir kimlik doğrulama yöntemi mevcut mu?"""
        return self.oauth_ready or self.basic_ready

    def __repr__(self) -> str:  # pragma: no cover - güvenlik amaçlı
        def mask(value: str) -> str:
            if not value:
                return "<empty>"
            return f"{'*' * 8}(len={len(value)})"

        return (
            "OpenSkyCredentials("
            f"client_id={mask(self.client_id)}, "
            f"client_secret={mask(self.client_secret)}, "
            f"username={mask(self.username)}, "
            f"password={mask(self.password)})"
        )


def get_opensky_credentials(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> OpenSkyCredentials:
    """
    OpenSky kimlik bilgilerini güvenli biçimde topla.

    Açık argümanlar verilmişse onlar kullanılır; aksi halde
    ortam değişkenlerine bakılır.
    """
    return OpenSkyCredentials(
        client_id=(client_id or os.getenv("OPENSKY_CLIENT_ID", "") or "").strip(),
        client_secret=(client_secret or os.getenv("OPENSKY_CLIENT_SECRET", "") or "").strip(),
        username=(username or os.getenv("OPENSKY_USERNAME", "") or "").strip(),
        password=(password or os.getenv("OPENSKY_PASSWORD", "") or "").strip(),
    )


def get_setting(name: str, default: str = "") -> str:
    """Herhangi bir ortam değişkenini tek noktadan, güvenli biçimde oku."""
    return (os.getenv(name, default) or "").strip()
