"""
GreenWing Analytics — Güvenlik Regresyon Testleri
══════════════════════════════════════════════════

Bu test dosyası, güvenlik denetiminde düzeltilen açıkların
GERİ GELMEMESİNİ garanti eder:

    1. Depoda gizli anahtar / kimlik bilgisi bulunmaması
    2. .gitignore'un hassas dosyaları dışlaması
    3. OpenSky kimlik bilgileri nesnesinin sırları maskelemesi
    4. Dashboard debug modunun güvenli varsayılanı
    5. callsign giriş doğrulaması (path traversal / komut enjeksiyonu)
    6. Rapor HTML kaçışlaması (XSS) ve dosya adı temizliği (path traversal)
    7. Sentetik yedek verinin 'gerçek' olarak etiketlenmemesi

Çalıştırma:
    python tests/test_security.py
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════
# 1. DEPO HİJYENİ
# ═══════════════════════════════════════════════════════════

class TestRepositoryHygiene(unittest.TestCase):
    """Depoda sır sızıntısı olmadığını doğrular."""

    FORBIDDEN_FILES = [
        "credentials.json",
        ".env",
        "secrets.yaml",
    ]

    # Gerçekçi sır desenleri (yer tutucular hariç)
    SECRET_PATTERNS = [
        (r"clientSecret\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", "hardcoded clientSecret"),
        (r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "private key block"),
        (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
        (r"\bghp_[A-Za-z0-9]{20,}\b", "GitHub token"),
        (r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b", "Slack token"),
        (r"\bsk-[A-Za-z0-9]{20,}\b", "OpenAI-style key"),
    ]

    def _iter_source_files(self):
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv",
                     "data", "reports", "greenWing_env", ".pytest_cache"}
        for root, dirs, files in os.walk(_PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for name in files:
                if name.endswith((".py", ".json", ".yaml", ".yml", ".md", ".cfg", ".ini")):
                    yield Path(root) / name

    def test_no_credentials_file_committed(self):
        for fname in self.FORBIDDEN_FILES:
            self.assertFalse(
                (_PROJECT_ROOT / fname).exists(),
                f"Hassas dosya depoda olmamalı: {fname}",
            )

    def test_no_hardcoded_secrets_in_source(self):
        findings = []
        for path in self._iter_source_files():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern, label in self.SECRET_PATTERNS:
                if re.search(pattern, text):
                    findings.append(f"{label} → {path.relative_to(_PROJECT_ROOT)}")
        self.assertEqual(findings, [], f"Kaynak kodda sır bulundu: {findings}")

    def test_gitignore_protects_secrets(self):
        gitignore = _PROJECT_ROOT / ".gitignore"
        self.assertTrue(gitignore.exists(), ".gitignore bulunamadı")
        content = gitignore.read_text(encoding="utf-8").lower()
        for entry in [".env", "credentials.json", "*.pem", "__pycache__"]:
            self.assertIn(entry.lower(), content, f".gitignore '{entry}' içermiyor")

    def test_env_example_only_has_empty_values(self):
        example = _PROJECT_ROOT / ".env.example"
        self.assertTrue(example.exists(), ".env.example bulunamadı")
        for line in example.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            # Hassas anahtarların değeri boş olmalı
            if any(t in key.upper() for t in ("SECRET", "PASSWORD", "TOKEN", "KEY")):
                self.assertEqual(
                    value.strip(), "",
                    f".env.example içinde '{key}' gerçek değer içermemeli",
                )


# ═══════════════════════════════════════════════════════════
# 2. KİMLİK BİLGİSİ YÖNETİMİ
# ═══════════════════════════════════════════════════════════

class TestSecretsManagement(unittest.TestCase):
    def test_credentials_are_masked_in_repr(self):
        from config.credentials import OpenSkyCredentials

        creds = OpenSkyCredentials(
            client_id="my-client-id",
            client_secret="super-secret-value-1234567890",
            username="user",
            password="hunter2",
        )
        text = repr(creds)
        self.assertNotIn("super-secret-value", text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("my-client-id", text)

    def test_credentials_from_environment(self):
        from config.credentials import get_opensky_credentials

        os.environ["OPENSKY_CLIENT_ID"] = "env-client"
        os.environ["OPENSKY_CLIENT_SECRET"] = "env-secret"
        try:
            creds = get_opensky_credentials()
            self.assertEqual(creds.client_id, "env-client")
            self.assertTrue(creds.oauth_ready)
        finally:
            del os.environ["OPENSKY_CLIENT_ID"]
            del os.environ["OPENSKY_CLIENT_SECRET"]

    def test_empty_credentials_mean_anonymous(self):
        from config.credentials import OpenSkyCredentials

        creds = OpenSkyCredentials()
        self.assertFalse(creds.is_authenticated)
        self.assertFalse(creds.oauth_ready)
        self.assertFalse(creds.basic_ready)


# ═══════════════════════════════════════════════════════════
# 3. YAPILANDIRMA GÜVENLİĞİ
# ═══════════════════════════════════════════════════════════

class TestSecureDefaults(unittest.TestCase):
    def test_debug_mode_defaults_to_false(self):
        # DASHBOARD_DEBUG env değişkenini geçici olarak kaldır
        saved = os.environ.pop("DASHBOARD_DEBUG", None)
        try:
            import importlib

            import config.settings as settings

            importlib.reload(settings)
            self.assertFalse(
                settings.DASHBOARD_DEBUG,
                "Dashboard debug varsayılan olarak KAPALI olmalı (RCE riski)",
            )
        finally:
            if saved is not None:
                os.environ["DASHBOARD_DEBUG"] = saved

    def test_dashboard_binds_localhost_by_default(self):
        from config.settings import DASHBOARD_HOST

        self.assertIn(DASHBOARD_HOST, {"127.0.0.1", "localhost"})


# ═══════════════════════════════════════════════════════════
# 4. GİRDİ DOĞRULAMA (PATH TRAVERSAL / ENJEKSİYON)
# ═══════════════════════════════════════════════════════════

class TestInputValidation(unittest.TestCase):
    def setUp(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "scrapper07", _PROJECT_ROOT / "scripts" / "07_live_flight_scrapper.py"
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_valid_callsign_accepted(self):
        self.assertEqual(self.module.sanitize_callsign("THY1"), "THY1")
        self.assertEqual(self.module.sanitize_callsign(" pgt120 "), "PGT120")

    def test_path_traversal_rejected(self):
        for bad in ["../../etc/passwd", "../secret", "a/b", "x\\y"]:
            with self.assertRaises(ValueError, msg=f"'{bad}' reddedilmeliydi"):
                self.module.sanitize_callsign(bad)

    def test_shell_metacharacters_rejected(self):
        for bad in ["THY1; rm -rf /", "a$(whoami)", "a|b", "a&b", "a`id`"]:
            with self.assertRaises(ValueError, msg=f"'{bad}' reddedilmeliydi"):
                self.module.sanitize_callsign(bad)

    def test_empty_and_oversized_rejected(self):
        for bad in ["", " ", "A" * 20, "AB"]:
            with self.assertRaises(ValueError):
                self.module.sanitize_callsign(bad)


# ═══════════════════════════════════════════════════════════
# 5. RAPOR GÜVENLİĞİ (XSS + PATH TRAVERSAL)
# ═══════════════════════════════════════════════════════════

class TestReportSecurity(unittest.TestCase):
    def test_escape_html(self):
        from src.reporting.report_generator import escape_html

        self.assertEqual(escape_html("<script>x</script>"), "&lt;script&gt;x&lt;/script&gt;")
        self.assertEqual(escape_html('" onmouseover="x'), "&quot; onmouseover=&quot;x")
        self.assertEqual(escape_html(None), "")

    def test_sanitize_filename_blocks_traversal(self):
        from src.reporting.report_generator import sanitize_filename

        self.assertNotIn("..", sanitize_filename("../../etc/passwd"))
        self.assertNotIn("/", sanitize_filename("../../etc/passwd"))
        self.assertEqual(sanitize_filename(""), "report")
        self.assertEqual(
            sanitize_filename("GreenWing_Report_20260101"),
            "GreenWing_Report_20260101",
        )

    def test_report_html_escapes_airline_name(self):
        from src.reporting.report_generator import ReportGenerator

        gen = ReportGenerator()
        summary = {
            "fleet_summary": {"fleet_efficiency_score": 80},
            "report_metadata": {"total_flights_analyzed": 1},
        }
        payload = "<img src=x onerror=alert(1)>"
        res = gen.generate_fleet_report(summary, airline_name=payload,
                                        output_filename="sec_probe")
        try:
            html = Path(res["html_path"]).read_text(encoding="utf-8")
            self.assertNotIn("<img", html, "XSS payload kaçışlanmamış")
            self.assertIn("&lt;img", html)
        finally:
            Path(res["html_path"]).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════
# 6. VERİ KAYNAĞI (PROVENANCE) DÜRÜSTLÜĞÜ
# ═══════════════════════════════════════════════════════════

class TestDataProvenance(unittest.TestCase):
    def test_synthetic_fallback_is_labeled(self):
        import pandas as pd

        from src.data_collection.opensky_collector import OpenSkyCollector

        df = OpenSkyCollector._mark_synthetic(
            pd.DataFrame({"time": ["2025-01-01 00:00:00"], "callsign": ["THY1"]})
        )
        self.assertEqual(df["collection_method"].iloc[0], "synthetic_fallback")
        self.assertEqual(df["data_provenance"].iloc[0], "synthetic_simulation")
        self.assertTrue(bool(df["is_synthetic"].iloc[0]))

    def test_case_study_subtitle_reflects_synthetic_data(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gen03", _PROJECT_ROOT / "scripts" / "03_generate_outputs.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        synthetic = module._resolve_data_source_subtitle(
            [{"collection_method": "demo_simulation"}]
        )
        self.assertIn("Synthetic", synthetic)
        self.assertNotIn("Real ADS-B", synthetic)

        real = module._resolve_data_source_subtitle(
            [{"collection_method": "arrivals"}]
        )
        self.assertIn("Real ADS-B", real)


# ═══════════════════════════════════════════════════════════
# ÇALIŞTIRICI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
