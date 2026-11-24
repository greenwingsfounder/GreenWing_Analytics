"""Script sözleşmesi testleri — DENETİM #95.

NEDEN BU DOSYA VAR
==================
`scripts/` altındaki 10 betik bugüne kadar HİÇ birlikte test edilmedi.
Her biri tek başına "çalışıyor" görünüyordu; ama SIRAYLA çalıştırılınca
birbirinin çıktısını eziyordu.

Somut olay (24 Kasım, bu testin doğuşu):
    scripts/02 → batch_results.json (14 kayıt, `origin` alanlı)
    scripts/10 → 13/13 eşleşme  ✓ sorunsuz
    scripts/04 → batch_results.json'ı 235 kayıtla EZER (`origin` YOK)
    scripts/10 → 5/30 eşleşme  ✗ zincir çöktü

Yani pipeline'ın çalışması, "hangi scripti en son çalıştırdığına"
bağlıydı. Bu bir sözleşme ihlaliydi: aynı dosya, iki farklı şema.

Bu testler, o sözleşmeyi kilitler:
  • Her betiğin ne ürettiği sabit ve belgeli olmalı
  • Paylaşılan dosyaya farklı şema yazan iki betik olmamalı
  • Kalibrasyon zinciri, araya hangi betik girerse girsin çalışmalı

Çalıştırma:
    python -m pytest tests/test_script_contract.py -v
"""
import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCRIPTS = ROOT / "scripts"
OPT = ROOT / "reports" / "optimizations"


def _write_targets(path: Path) -> set[str]:
    """Betik hangi dosyalara YAZIYOR? (kaynak koddan çıkarılır)"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return set()

    out = set()
    for node in ast.walk(tree):
        # json.dump(..., open(X, 'w')) / open(X, 'w')
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in ("dump", "write_text", "savefig", "to_csv", "to_json"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value.endswith((".json", ".csv", ".html")):
                            out.add(arg.value)
            # open('x.json', 'w')
            if name == "open" and len(node.args) >= 2:
                a0, a1 = node.args[0], node.args[1]
                if (isinstance(a0, ast.Constant)
                        and isinstance(a0.value, str)
                        and isinstance(a1, ast.Constant)
                        and "w" in str(a1.value)):
                    out.add(a0.value)
    return out


# ─────────────────────────────────────────────────────────────
# 1 — İki betik aynı JSON'a farklı şema yazmamalı (#95'in özü)
# ─────────────────────────────────────────────────────────────
def test_02_and_04_do_not_share_output_file():
    """02 (analiz) ve 04 (demo) AYRI dosyalara yazmalı.

    Aynı dosyaya yazdıklarında 04, 02'nin şemasını (origin/destination)
    eziyor; kalibrasyon zinciri 13/13 → 5/30 düşüyordu."""
    src_02 = (SCRIPTS / "02_analyze_and_optimize.py").read_text(
        encoding="utf-8", errors="ignore")
    src_04 = (SCRIPTS / "04_generate_professional_demo.py").read_text(
        encoding="utf-8", errors="ignore")

    assert "batch_results.json" in src_02, "02 artık yazmıyor?"
    assert "demo_batch_results.json" in src_04, (
        "04 kendi dosyasına yazmıyor — 02'ninkini ezip zinciri "
        "bozabilir (#95 geri geldi)")
    # 04, batch_results.json'a yazan bir dosya yolu KURMAMALI
    for line in src_04.splitlines():
        if "batch_results.json" in line and "demo_batch" not in line:
            if "results_path" in line or "os.path.join" in line:
                pytest.fail(f"04 hâlâ batch_results.json hedefliyor: "
                            f"{line.strip()}")


# ─────────────────────────────────────────────────────────────
# 2 — Kalibrasyon kaynağı doğru dosyayı seçmeli
# ─────────────────────────────────────────────────────────────
def test_mock_ingestor_prefers_analysis_output():
    """Mock üretici 02'nin çıktısını ÖNCE denemeli, demoyu sonra."""
    src = (ROOT / "src" / "ingestion" / "customer_fuel_ingestor.py").read_text(
        encoding="utf-8")
    assert "batch_results.json" in src
    assert "demo_batch_results.json" in src

    i_analiz = src.find("'batch_results.json'")
    i_demo = src.find("'demo_batch_results.json'")
    assert 0 < i_analiz < i_demo, (
        "öncelik sırası bozulmuş: analiz çıktısı önce denenmeli")


# ─────────────────────────────────────────────────────────────
# 3 — 02'nin şeması tam olmalı (eşleştiricinin ihtiyacı)
# ─────────────────────────────────────────────────────────────
def test_analysis_output_schema_complete():
    """02 eşleştiricinin okuduğu TÜM alanları yazmalı."""
    p = OPT / "batch_results.json"
    if not p.exists():
        pytest.skip("batch_results.json yok")

    data = json.loads(p.read_text(encoding="utf-8"))
    assert data
    for key in ("callsign", "origin", "destination", "flight_date",
                "distance_nm", "aircraft_type"):
        assert key in data[0], f"02 şemasında '{key}' yok"


# ─────────────────────────────────────────────────────────────
# 4 — Zincir: sıra ne olursa olsun eşleşmeli
# ─────────────────────────────────────────────────────────────
def test_chain_survives_demo_script():
    """02 → 10 çalışırken araya 04 girse bile 10 eşleşmeye devam etmeli."""
    p = OPT / "batch_results.json"
    demo = OPT / "demo_batch_results.json"
    if not p.exists():
        pytest.skip("önce scripts/02 çalıştırılmalı")

    # demoyu üretilmiş say (04'ün çıktısı gibi)
    if not demo.exists():
        demo.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")

    from src.ingestion.customer_fuel_ingestor import CustomerFuelIngestor

    path = CustomerFuelIngestor(tenant_id="pytest_contract").\
        generate_mock_fuel_data(n_flights=20)
    import pandas as pd

    df = pd.read_csv(path)
    # demo dosyası da mevcutken mock, ANALİZ dosyasından türetilmeli
    with open(p, encoding="utf-8") as f:
        analiz = json.load(f)
    gercek = {str(r.get("callsign", "")).upper() for r in analiz
              if r.get("callsign")}
    mock = {str(c).upper() for c in df["callsign"].unique()}

    assert mock <= gercek, (
        "mock, analiz dosyası yerine demo dosyasından türetilmiş — "
        "demo 235 sentetik uçuş içeriyor")


# ─────────────────────────────────────────────────────────────
# 5 — Her betiğin docstring'i olmalı (ne işe yaradığı belgeli)
# ─────────────────────────────────────────────────────────────
def test_every_script_documents_itself():
    """10 betiğin hepsi ilk satırda ne yaptığını söylemeli."""
    missing = []
    for p in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        if not ast.get_docstring(tree):
            missing.append(p.name)
    assert not missing, f"docstring yok: {missing}"


def test_scripts_numbered_without_gaps():
    """01..10 arası numaralandırma boşluksuz olmalı."""
    nums = sorted(int(p.name[:2]) for p in SCRIPTS.glob("[0-9][0-9]_*.py"))
    assert nums == list(range(1, len(nums) + 1)), f"boşluk var: {nums}"
