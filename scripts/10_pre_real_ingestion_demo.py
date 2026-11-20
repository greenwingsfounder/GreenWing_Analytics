#!/usr/bin/env python3
"""
GreenWing — Enterprise Pre-Real-Data Ingestion + Calibration Demo (v2.1.0-enterprise-pre-real)
===============================================================================================

COMPLETE PROFESSIONAL RUN SCRIPT FOR AIRLINE PITCHES

COPY-PASTE INSTRUCTIONS (VS Code / new machine / solo dev):
-----------------------------------------------------------
1. Copy the minimal folder structure to target machine:
   config/
     - ingestion_config.py
     - settings.py
     - aircraft_database.yaml
   src/
     - ingestion/ (all 4 files)
     - optimization/model_calibrator.py
     - models/fuel_model.py
   scripts/10_pre_real_ingestion_demo.py
   reports/optimizations/batch_results.json   <--- CRITICAL

2. pip install pandas numpy scipy pyyaml python-dotenv

3. cd /your/project
   python scripts/10_pre_real_ingestion_demo.py

   For pitch (recommended 25 flights):
   python -c "
   from pathlib import Path
   import sys
   sys.path.insert(0, str(Path('.').resolve()))
   from scripts._10_pre_real_ingestion_demo import run_pre_real_demo
   run_pre_real_demo(tenant_id='thy_honeywell', n_flights=25)
   "

4. To use REAL data (when QAR arrives):
   result = pipe.run_full_pipeline(
       customer_fuel_path='data/customer_fuel/real_block_fuel.csv',
       use_mock=False
   )
   # All gates and provenance stay identical.

batch_results.json ROLE:
- Provides the 231 simulated flight trajectories (distance_nm, estimated_fuel_kg, callsign, airports)
- Used inside CalibrationPipeline._load_demo_trajectories()
- Simulates the ADS-B part (from script 08) while customer fuel is mocked
- When real data arrives: replace this loader with live ADS-B + real fuel ingestion adapters
- Location: reports/optimizations/batch_results.json (always copy it)

DISCLAIMER (MANDATORY):
PRE-REAL-DATA DEMO ONLY. Not for operational or regulatory use without real QAR/FDR validation.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# === PORTABLE ROOT (fixes all Path + import errors) ===
# Run from anywhere: VS Code, terminal, scripts dir, project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.ingestion import CalibrationPipeline
from config.ingestion_config import DEFAULT_INGESTION_CONFIG
from src.logging_config import setup_logging, get_logger

# Central logging setup (pre-real best practice)
setup_logging(level="INFO")
logger = get_logger(__name__)
logger.info("GreenWing pre-real demo starting...")


def run_pre_real_demo(tenant_id: str = "sunexpress_demo", n_flights: int = 30):
    print("=" * 82)
    print(" GREENWING ENTERPRISE — PRE-REAL-DATA INGESTION + CALIBRATION DEMO")
    print(f" Tenant            : {tenant_id}")
    print(f" Requested flights : {n_flights}")
    print(f" Pipeline version  : {DEFAULT_INGESTION_CONFIG.PIPELINE_VERSION}")
    print(f" Min flights gate  : {DEFAULT_INGESTION_CONFIG.MIN_FLIGHTS_FOR_CALIBRATION}")
    print(f" Date (UTC)        : {datetime.now(timezone.utc).isoformat()}")
    print("=" * 82)
    print("⚠️  PRE-REAL-DATA DEMO ONLY — NOT FOR OPERATIONAL / REGULATORY / CORSIA USE")
    print("=" * 82)

    pipe = CalibrationPipeline(tenant_id=tenant_id, config=DEFAULT_INGESTION_CONFIG)

    result = pipe.run_full_pipeline(
        use_mock=True,
        n_mock_flights=n_flights,
        aircraft_type="B738",
    )

    if result.get("status") != "SUCCESS":
        print("\n❌ PIPELINE REJECTED (strict enterprise gates)")
        print(f"   Message: {result.get('message')}")
        print("   Action: use more flights (>=15) or real data with better quality.")
        return result

    print("\n[1] CUSTOMER FUEL INGESTION + FLIGHT MATCHER")
    print(f"    Matched flights : {result['full_matched_count']}")
    print(f"    Match statistics: {result.get('matching')}")

    cal = result["calibration"]
    acc = result["accuracy_improvement"]

    print("\n[2] MODEL CALIBRATOR (Nelder-Mead)")
    print(f"    cd0_factor      : {cal['factors']['cd0_factor']:.4f}")
    print(f"    sfc_factor      : {cal['factors']['sfc_factor']:.4f}")
    print(f"    Accuracy before : {acc['before_pct']:.2f}%")
    print(f"    Accuracy after  : {acc['after_pct']:.2f}%")
    print(f"    Improvement     : +{acc['improvement_pct']:.1f}%")

    # === NEW: Honest test-set metrics (pre-real scientific integrity) ===
    tsm = result.get("test_set_metrics") or cal.get("test_set_metrics")
    if tsm:
        print("\n[2b] TEST SET (honest hold-out — pre-real credibility)")
        print(f"    avg_error_before: {tsm.get('avg_error_before_pct', 'N/A')}%")
        print(f"    avg_error_after : {tsm.get('avg_error_after_pct', 'N/A')}%")
        print(f"    improvement     : +{tsm.get('improvement_pct', 'N/A')}%")
        print(f"    n_test          : {tsm.get('n_test_flights', 'N/A')}")
    else:
        print("\n[2b] TEST SET: not computed (small dataset or legacy)")

    split = result.get("split_info") or cal.get("split_info")
    if split:
        print(f"    split_info      : {split}")

    saved = pipe.save_calibration()
    print(f"\n[3] SAVED CALIBRATION ARTIFACT (full provenance)")
    print(f"    File                 : {saved}")
    print(f"    config_snapshot_hash : {result.get('config_snapshot_hash')}")
    print(f"    pipeline_version     : {result['pipeline_version']}")
    print(f"    pre_real_data        : {result.get('pre_real_data')}")
    print(f"    trace_id             : {result.get('trace_id')}")
    print(f"    trace_file           : {result.get('trace_file')}")

    print("\n[4] HOW batch_results.json IS USED")
    print("    File: reports/optimizations/batch_results.json")
    print("    Purpose: supplies real-trajectory-like data (distance_nm + estimated_fuel_kg)")
    print("    Loaded in: CalibrationPipeline._load_demo_trajectories()")
    print("    231 entries from script 04 (simulated)")
    print("    When real data arrives: replace with script 08 live ADS-B + real fuel parser")

    print("\n" + "=" * 82)
    print("✅ SUCCESS — PRE-REAL PIPELINE IS ENTERPRISE READY")
    print("   When real QAR/block fuel arrives → only live ingestion + adapters remain.")
    print("   Copy the calibration JSON + this output to your airline pitch deck.")
    print("=" * 82 + "\n")

    return result, saved


if __name__ == "__main__":
    run_pre_real_demo()
