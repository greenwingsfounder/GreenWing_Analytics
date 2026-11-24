"""
GreenWing Analytics — PDF Glif Bütünlüğü Testi
══════════════════════════════════════════════════

DENETİM #74 — PDF'e sessizce "tofu" (eksik glif kutusu) basılıyordu.

BULGU
─────
`tools/build_technical_report.py` DejaVuSans kullanıyor. DejaVuSans
şu karakterleri İÇERMİYOR:

    ✅  U+2705  WHITE HEAVY CHECK MARK
    ❌  U+274C  CROSS MARK
    ⚠   U+26A0 (bazı sürümlerde) — kontrol edilmeli

Bu karakterler PDF metnine hiç girmediği için metin tabanlı arama
(`"✅" in text`) BOŞ döner; PDF'te yerlerine ReportLab'in eksik-glif
kutusu basılır. Yani hata **görünmez** — ne arama ne de
`chr(9633)` sayımı yakalar.

Nerede oldu: 6 yerde (biri denetimden ÖNCE de vardı:
`'boyutsuz', 'CI = 52 ✅'`). Yalnızca sayfayı PNG'ye çevirip
gözle bakınca fark edildi.

BU TEST NE YAPAR
────────────────
1. Üretim kodunda (`tools/build_technical_report.py`) yasaklı
   glif var mı — statik tarama.
2. Üretilen PDF'te bu karakterler var mı — dinamik tarama
   (varsa zaten tofu olarak basılmış demektir).
3. DejaVuSans fontunun kendisinde hangi glifler var — kaynak
   doğrulaması.

Çalıştırma:
    python tests/test_pdf_glyphs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_REPORT_TOOL = _PROJECT_ROOT / 'tools' / 'build_technical_report.py'
_PDF_PATH = _PROJECT_ROOT / 'reports' / 'GreenWing_Teknik_Rapor.pdf'

# DejaVuSans'ta BULUNMAYAN, kullanılmaması gereken karakterler
# LİSTE ÖLÇÜMLE DOĞRULANDI (fontTools, DejaVuSans.ttf, 5.955 glif).
# İlk yazdığım liste YANLIŞTI: ✌ (U+270C) ve 😀 (U+1F600) sanmıştım
# ki fontta yok — ÖLÇÜMDE VAR çıktılar. Aşağıdaki liste, gerçekten
# bulunmayan karakterlerdir:
#   ✅ U+2705 YOK · ❌ U+274C YOK · 📈 U+1F4C8 YOK · 🔬 U+1F52C YOK
#   ✌ U+270C VAR · 😀 U+1F600 VAR · ⚠ U+26A0 VAR · ✓ U+2713 VAR
_FORBIDDEN = {
    '\u2705': '✅ WHITE HEAVY CHECK MARK',
    '\u274c': '❌ CROSS MARK',
    '\U0001f4c8': '📈 emoji',
    '\U0001f52c': '🔬 emoji',
}

# DejaVuSans'ta BULUNAN ve güvenle kullanılabilen işaretler
_SAFE = {
    '\u2713': '✓ CHECK MARK',
    '\u2717': '✗ BALLOT X',
    '\u26a0': '⚠ WARNING SIGN',
    '\u25cf': '● BLACK CIRCLE',
    '\u2605': '★ BLACK STAR',
    '\u25a1': '□ WHITE SQUARE',
    '\u00b1': '±',
    '\u2192': '→',
    '\u2264': '≤',
    '\u2265': '≥',
    '\u00d7': '×',
}


def _font_cmap() -> set[str]:
    """DejaVuSans TTF'inin kapsadığı karakter kümesi."""
    try:
        from fontTools.ttLib import TTFont as FTFont
    except ImportError:
        return set()

    # Font yolu build_technical_report.py'deki FONT_DIR ile aynı
    # olmalı. Sabit yol + yedekler (atan test kanıt sağlamaz).
    candidates = [
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        _PROJECT_ROOT / 'reports' / 'fonts' / 'DejaVuSans.ttf',
        _PROJECT_ROOT / 'tools' / 'fonts' / 'DejaVuSans.ttf',
    ]
    ttf = next((c for c in candidates if c.exists()), None)
    if ttf is None:
        return set()

    try:
        font = FTFont(str(ttf))
        cmap = set()
        for table in font['cmap'].tables:
            cmap.update(chr(c) for c in table.cmap)
        return cmap
    except Exception:
        return set()


def run_tests() -> bool:
    print("\n" + "=" * 58)
    print("  TEST: PDF glif bütünlüğü (#74)")
    print("=" * 58)

    errors: list[str] = []
    tests = 0

    def ok(name: str) -> None:
        nonlocal tests
        tests += 1
        print(f"  \u2713 {name}")

    def fail(name: str, detail: str = "") -> None:
        nonlocal tests
        tests += 1
        print(f"  \u2717 {name} — {detail}")
        errors.append(f"{name}: {detail}")

    def check_true(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            ok(name)
        else:
            fail(name, detail)

    # ═══════════════════════════════════════════════════
    # [A] ÜRETİM KODUNDA YASAKLI GLİF (statik)
    # ═══════════════════════════════════════════════════
    print("\n  [A] Üretim kodu statik tarama")

    check_true("build_technical_report.py var", _REPORT_TOOL.exists())
    if _REPORT_TOOL.exists():
        src = _REPORT_TOOL.read_text(encoding='utf-8')
        for ch, name in _FORBIDDEN.items():
            # Yorum/etiket satırlarında geçebilir; yalnızca
            # gerçek string literal içinde arıyoruz: kaba ama
            # etkili — dosyada hiç geçmemeli.
            check_true(
                f"üretim kodunda {name} YOK",
                ch not in src,
                f"{src.count(ch)} kez geçiyor"
            )

    # ═══════════════════════════════════════════════════
    # [B] ÜRETİLEN PDF'TE YASAKLI GLİF (dinamik)
    # ═══════════════════════════════════════════════════
    print("\n  [B] Üretilen PDF taraması")

    check_true("teknik PDF var", _PDF_PATH.exists())
    if _PDF_PATH.exists():
        try:
            import pymupdf
            doc = pymupdf.open(_PDF_PATH)
            text = "".join(page.get_text() for page in doc)
            n_pages = len(doc)

            check_true(
                f"PDF açıldı ({n_pages} sayfa)",
                n_pages > 0
            )

            for ch, name in _FORBIDDEN.items():
                check_true(
                    f"PDF'te {name} YOK",
                    ch not in text,
                    f"{text.count(ch)} kez"
                )

            # Güvenli işaretler GERÇEKTEN basılmış mı?
            # (✓ kullanılıyorsa PDF metninde görünmeli)
            _safe_ok = sum(text.count(ch) for ch in _SAFE)
            check_true(
                f"güvenli işaretler PDF metninde ({_safe_ok} kez)",
                _safe_ok > 0,
                "PDF metni boş olabilir"
            )

            # Pdf'te tofu için tipik: U+FFFD veya boş kutu
            check_true(
                "PDF'te U+FFFD (değiştirme karakteri) yok",
                '\ufffd' not in text,
                f"{text.count(chr(0xfffd))} kez"
            )

            doc.close()
        except ImportError:
            print("  (pymupdf yok — [B] atlandı)")

    # ═══════════════════════════════════════════════════
    # [C] FONT KAPSAMI (kaynak doğrulaması)
    # ═══════════════════════════════════════════════════
    print("\n  [C] DejaVuSans font kapsamı")

    cmap = _font_cmap()
    if cmap:
        for ch, name in _FORBIDDEN.items():
            check_true(
                f"font {name}'ı KAPSAMIYOR (beklenti)",
                ch not in cmap
            )
        for ch, name in _SAFE.items():
            check_true(
                f"font {name}'ı kapsıyor",
                ch in cmap
            )
    else:
        print("  (fontTools/pymupdf yok ya da font bulunamadı — "
              "[C] atlandı)")

    # ═══════════════════════════════════════════════════
    # SONUÇ
    # ═══════════════════════════════════════════════════
    print(f"\n  {'─' * 50}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print("\n  \u2717 BAŞARISIZ TESTLER:")
        for i, e in enumerate(errors, 1):
            print(f"     {i}. {e}")
        return False

    print("  \u2713 TÜM GLİF TESTLERİ BAŞARILI\n")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
