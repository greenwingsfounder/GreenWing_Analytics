"""
GreenWing Analytics — Enterprise Veri Yönetimi, Yedekleme ve Pre-Real → Real Transition Reset Sistemi
v2.1.0-enterprise-pre-real

KULLANIM (SOLO DEV / AIRLINE PITCH / GERÇEK VERİ GEÇİŞİ):
--------------------------------------------------------------
# Sadece demo/mock kalıntılarını temizle (güvenli)
python scripts/09_clean_and_backup.py --mode clean-demos

# Tam temizlik (eski ADS-B + raporlar)
python scripts/09_clean_and_backup.py --mode clean

# YENİ: GERÇEK VERİ İÇİN SIFIRLA (karman çorman istemiyorsan BUNU KULLAN)
#   - Bütün demo/mock/calibration/customer_fuel/mocks kalıntılarını SİLER
#   - batch_results.json'i (simüle trajectory kaynağı) KORUR (gerçek ADS-B gelene kadar)
#   - Gerçek veri geldiğinde "gıcır gıcır sıfır" başlangıç sağlar
#   - Tüm yedeklenir
python scripts/09_clean_and_backup.py --mode reset-for-real

# Gerçek veri ile demo çalıştır (reset'ten sonra)
python scripts/10_pre_real_ingestion_demo.py   # use_mock=True varsayılan
# Veya gerçek CSV ile:
# python -c "
# from scripts._10_pre_real_ingestion_demo import run_pre_real_demo
# run_pre_real_demo(use_mock=False, customer_fuel_path='data/customer_fuel/THY_REAL_BLOCK_2026-07.csv')
# "
"""

import os
import shutil
import argparse
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEMO_KEYWORDS = ["demo", "test", "mock", "verify", "kopya", "final_copy", "pitch_ready", "audit", "sunexpress", "thy_"]
PROTECT_REAL = ["real_", "thy_real", "block_fuel_real", "qar_", "fdr_"]

def is_demo_file(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in DEMO_KEYWORDS) or any(k in n for k in ["_final_", "_demo_"])

def should_protect_real(name: str) -> bool:
    n = name.lower()
    return any(x in n for x in PROTECT_REAL) or "real" in n and ("fuel" in n or "qar" in n or "block" in n)

def backup_dir(src: Path, backup_root: Path) -> int:
    if not src.exists():
        return 0
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = backup_root / f"backup_{src.name}_{ts}"
    bdir.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in list(src.glob("*")):
        if f.is_file():
            shutil.copy2(f, bdir / f.name)
            count += 1
    return count

def clean_demos(backup_root: Path):
    """Eski demo/mock temizliği (09'un orijinal mantığı + iyileştirme)"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_root / f"demo_cleanup_{ts}"
    backup.mkdir(parents=True, exist_ok=True)

    folders = [
        Path("data/calibrations"),
        Path("data/customer_fuel"),
        Path("data/mocks")
    ]
    deleted = 0
    protected = 0

    for folder in folders:
        if not folder.exists():
            continue
        for f in list(folder.glob("*")):
            if not f.is_file():
                continue
            if should_protect_real(f.name):
                protected += 1
                continue
            if not is_demo_file(f.name):
                protected += 1
                continue
            shutil.copy2(f, backup / f.name)
            f.unlink()
            deleted += 1

    print(f"  ✅ clean-demos tamam: {deleted} demo dosyası silindi, {protected} korundu")
    print(f"  📦 Yedek: {backup}")

def reset_for_real_data(backup_root: Path):
    """
    GERÇEK VERİ GEÇİŞİ İÇİN TAM SIFIRLA
    - Demo, mock, eski calibration, customer_fuel kalıntılarını SİLER
    - batch_results.json KORUNUR (ADS-B trajectory kaynağı olarak)
    - data/raw/opensky eski dosyalar temizlenir
    - reports/optimizations içindeki eski JSON'lar temizlenir (ama batch_results.json hariç)
    - Gerçek veri geldiğinde "gıcır gıcır sıfır" + sadece live ingestion kalır
    """
    print("\n" + "="*72)
    print("  GREENWING — RESET-FOR-REAL (PRE-REAL → REAL TRANSITION)")
    print("  Bu mod: Bütün demo/mock kalıntılarını SİLER. Gerçek veri için temiz başlangıç.")
    print("  batch_results.json (231 simüle trajectory) KORUNUR (gerçek ADS-B'ye kadar).")
    print("="*72 + "\n")

    # 1. Yedekle
    folders_to_clean = [
        Path("data/calibrations"),
        Path("data/customer_fuel"),
        Path("data/mocks"),
        Path("data/raw/opensky"),
    ]
    total_backed = 0
    for f in folders_to_clean:
        total_backed += backup_dir(f, backup_root)

    # 2. Sil (demo/mock + eski customer fuel)
    deleted = 0
    for folder in folders_to_clean:
        if folder.exists():
            for f in list(folder.glob("*")):
                if f.is_file():
                    if should_protect_real(f.name):
                        continue  # gerçekleri koru
                    try:
                        f.unlink()
                        deleted += 1
                    except:
                        pass

    # 3. batch_results.json'i KORU (önemli: trajectory kaynağı)
    batch_path = Path("reports/optimizations/batch_results.json")
    if batch_path.exists():
        print(f"  ✅ batch_results.json korundu (gerçek ADS-B + real fuel'e kadar kullanılır)")

    # 4. Eski rapor kalıntılarını temizle (ama batch_results hariç)
    if Path("reports/optimizations").exists():
        for f in list(Path("reports/optimizations").glob("*.json")):
            if f.name != "batch_results.json" and is_demo_file(f.name):
                try:
                    f.unlink()
                    deleted += 1
                except:
                    pass

    # 5. Runtime data dir'leri temiz tut (ama silme, sadece içeriği)
    for d in ["data/calibrations", "data/customer_fuel", "data/mocks"]:
        Path(d).mkdir(parents=True, exist_ok=True)

    print(f"\n  ✅ RESET-FOR-REAL tamam")
    print(f"     Silinen demo/mock/kalintı dosyası: {deleted}")
    print(f"     Yedeklenen: {total_backed}")
    print(f"     batch_results.json korundu (trajectory kaynağı)")
    print(f"     Artık 10_pre_real_ingestion_demo.py ile gerçek CSV verebilirsin.")
    print(f"     Örnek: gerçek veri geldiğinde 'data/customer_fuel/THY_REAL_*.csv' koy + use_mock=False")
    print("  ⚠️  PRE-REAL → REAL geçişi: Sadece live ingestion + real adapters kalacak.")
    print("="*72 + "\n")

def clean_and_backup(mode="clean", target=""):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = _PROJECT_ROOT / "data" / "archive"
    backup_root.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*70}")
    print(f"  GREENWING — VERİ YÖNETİMİ  |  Mod: {mode.upper()}")
    print(f"  Tarih: {ts}")
    print(f"{'='*70}")

    if mode == "clean-demos":
        clean_demos(backup_root)
        return

    if mode == "reset-for-real":
        reset_for_real_data(backup_root)
        return

    # Normal clean / backup (eski ADS-B + raporlar)
    if mode in ["clean", "backup"]:
        raw_dir = _PROJECT_ROOT / "data" / "raw" / "opensky"
        raw_files = list(raw_dir.glob("*.csv")) if raw_dir.exists() else []

        if mode == "clean":
            for f in raw_files:
                try:
                    f.unlink()
                except:
                    pass
            print("  ✅ data/raw/opensky/ temizlendi")

            batch = _PROJECT_ROOT / "reports" / "optimizations" / "batch_results.json"
            if batch.exists():
                # batch_results.json'i SIFIRLA değil, KORU (önemli)
                print("  ℹ️  batch_results.json korundu (trajectory kaynağı)")

    print(f"{'='*70}\n")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="GreenWing Enterprise Clean & Reset Tool")
    p.add_argument("--mode", default="clean", choices=["clean", "backup", "restore", "clean-demos", "reset-for-real"])
    p.add_argument("--target", default="")
    args = p.parse_args()
    clean_and_backup(args.mode, args.target)
