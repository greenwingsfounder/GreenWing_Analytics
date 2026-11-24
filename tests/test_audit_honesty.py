"""Denetim dürüstlük testleri — DENETİM #94.

NEDEN BU DOSYA VAR
==================
`tools/full_audit.py` K7 (arayüz) katmanı, 8052 portunda sunucu
bekliyordu. Sunucu kapalıysa `warn()` çağırıyordu — ve **`warn()`
`passed` sayacını ARTIRIYORDU.**

Sonuç: sunucu kapalıyken denetim "228/228 · HİÇ HATA YOK — sistem
temiz" diyordu. Gerçekte **8 arayüz kontrolü hiç yapılmamıştı.**

Bu, projenin en tehlikeli hata sınıfı: **denetlenmemiş yeşil.**
Test edilmemiş bir alanı "geçti" saymak, hiç test etmemekten daha
kötüdür — çünkü sahte güven yaratır.

Bu dosya, o davranışın geri gelmesini engeller.

Çalıştırma:
    python -m pytest tests/test_audit_honesty.py -v
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AUDIT = ROOT / "tools" / "full_audit.py"


def _audit_source() -> str:
    return AUDIT.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# 1 — skip() var ve passed'ı ARTIRMIYOR
# ─────────────────────────────────────────────────────────────
def test_layer_has_skip_method():
    """Atlanan kontrol için ayrı bir yol olmalı."""
    src = _audit_source()
    assert "def skip(" in src, (
        "Layer.skip() yok — atlanan kontroller 'geçti' sayılabilir "
        "(#94 geri geldi)")


def test_skip_does_not_increment_passed():
    """skip() sayaçlara 'geçti' yazmamalı — yalnızca 'atlandı'."""
    tree = ast.parse(_audit_source())

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "skip":
            # yalnızca kendi gövdesine bak
            body_src = ast.get_source_segment(_audit_source(), node) or ""
            assert "self.passed" not in body_src, (
                "skip() hâlâ self.passed artırıyor — sahte yeşil")
            assert "SKIP" in body_src, "skip() SKIP kaydı üretmiyor"
            return
    raise AssertionError("skip() bulunamadı")


# ─────────────────────────────────────────────────────────────
# 2 — K7 (arayüz) sunucu kapalıyken WARN değil SKIP demeli
# ─────────────────────────────────────────────────────────────
def test_ui_layer_skips_when_server_down():
    """Arayüz katmanı erişilemezse 'warn' (geçti) değil 'skip'
    (atlandı) demeli."""
    src = _audit_source()

    # layer_ui gövdesini çıkar
    start = src.index("def layer_ui()")
    end = src.index("\ndef report()", start)
    ui = src[start:end]

    assert "lay.skip(" in ui, "K7 erişilemezlikte skip() kullanmıyor"
    # eski hatalı desen geri gelmemeli
    assert "lay.warn('site erişilemiyor'" not in ui, (
        "K7 yine 'warn' kullanıyor — sunucu kapalıyken YEŞİL görünür")


def test_ui_layer_has_configurable_port():
    """Port sabit 8052 olmamalı — test ortamı farklı port kullanabilir."""
    src = _audit_source()
    assert "GREENWING_AUDIT_PORT" in src, (
        "port ortamdan okunmuyor — farklı portta çalışan sunucu "
        "denetlenemez, sahte 'atlandı' riski")


# ─────────────────────────────────────────────────────────────
# 3 — Rapor ATLANDI sayısını görünür kılmalı
# ─────────────────────────────────────────────────────────────
def test_report_prints_skipped_count():
    """Rapor '0 atlandı' yazmalı; yoksa kullanıcı neyin test
    edilmediğini bilemez."""
    src = _audit_source()
    start = src.index("def report()")
    end = src.index("\ndef main()", start)
    rep = src[start:end]

    assert "ATLANDI" in rep, "rapor atlanan kontrol sayısını yazmıyor"
    assert "total_s" in rep, "atlanan sayacı raporda kullanılmıyor"


def test_clean_message_requires_all_tested():
    """'temiz' ifadesi ancak hiç atlanan yoksa çıkmalı."""
    src = _audit_source()
    start = src.index("def report()")
    end = src.index("\ndef main()", start)
    rep = src[start:end]

    # temiz mesajı total_s == 0 koşuluna bağlı olmalı
    assert "total_s == 0" in rep or "total_s == 0 else" in rep, (
        "'temiz' mesajı atlanan kontrol varken de çıkabilir")


# ─────────────────────────────────────────────────────────────
# 4 — JSON'da skipped alanı
# ─────────────────────────────────────────────────────────────
def test_json_records_skipped():
    src = _audit_source()
    assert "'skipped': total_s" in src, (
        "JSON çıktısında 'skipped' yok — otomasyon 'temiz' sanır")


# ─────────────────────────────────────────────────────────────
# 5 — warn() hâlâ var (meşru kullanım için) ama K7'de değil
# ─────────────────────────────────────────────────────────────
def test_warn_still_exists_for_real_warnings():
    """warn() tamamen kaldırılmamalı — 'sorun yok ama not var'
    durumları için meşru. Yasak olan, TEST EDİLMEMİŞ alanı
    geçti saymaktır."""
    src = _audit_source()
    assert "def warn(" in src
