"""
GreenWing Enterprise Calibration Pipeline (v2.1)
"""
from __future__ import annotations
import json, hashlib, logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd
from src.ingestion.customer_fuel_ingestor import CustomerFuelIngestor
from src.ingestion.flight_matcher import FlightMatcher
from src.optimization.model_calibrator import ModelCalibrator
from config.ingestion_config import DEFAULT_INGESTION_CONFIG
from config.settings import _PROJECT_ROOT

# === CENTRAL PROVENANCE: AnalysisTracer (pre-real scientific integrity) ===
# This is the "kara kutu". Every critical ingestion/calibration step is now recorded.
# When real data arrives, we just add more log_input/log_step calls.
# No redesign needed.
try:
    from src.logging_config import AnalysisTracer
except ImportError:
    AnalysisTracer = None  # graceful for environments without it (should not happen)

from src.logging_config import get_logger
logger = get_logger("ingestion.pipeline")

CALIBRATIONS_DIR = Path(_PROJECT_ROOT) / "data" / "calibrations"
CALIBRATIONS_DIR.mkdir(parents=True, exist_ok=True)

class CalibrationPipeline:
    def __init__(self, tenant_id: str = "default", config: Optional[Any] = None):
        self.tenant_id = tenant_id
        self.cfg = config or DEFAULT_INGESTION_CONFIG
        self.ingestor = CustomerFuelIngestor(tenant_id, config=self.cfg)
        self.matcher = FlightMatcher(tenant_id, config=self.cfg)
        self.calibrator = None
        self.last_result = {}

    def run_full_pipeline(self, customer_fuel_path=None, trajectories=None, use_mock=True, n_mock_flights=30, aircraft_type="B738"):
        # === CENTRAL PROVENANCE TRACER (pre-real scientific integrity) ===
        # Every key step is now logged with AnalysisTracer.
        # This directly addresses "Provenance kâfi değil".
        # When real data comes, we only add more log_input/log_step calls.
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tracer = None
        if AnalysisTracer:
            tracer = AnalysisTracer(
                analysis_id=f"PRE_REAL_{self.tenant_id}_{ts}",
                description="Pre-real ingestion + calibration pipeline run (v2.1.0-enterprise-pre-real)"
            )
            tracer.log_input("config_snapshot_hash", self.cfg.snapshot_hash(), "", "ingestion_config")
            tracer.log_input("min_flights_gate", self.cfg.MIN_FLIGHTS_FOR_CALIBRATION, "", "config")
            tracer.log_input("pipeline_version", self.cfg.PIPELINE_VERSION, "", "config")
            tracer.log_assumption(
                "pre_real_disclaimer", True, "",
                "FORCE_PRE_REAL_DISCLAIMER active — no real QAR/FDR used",
                uncertainty_pct=0.0, can_override=False
            )

        if customer_fuel_path and Path(customer_fuel_path).exists():
            ing = self.ingestor.ingest_csv(customer_fuel_path, source="real")
            logger.info(f"[{self.tenant_id}] Ingested real CSV: loaded={ing.get('records_loaded')}, rejected={ing.get('records_rejected')}")
            if tracer:
                tracer.log_input("customer_fuel_path", str(customer_fuel_path), "", "real")
        elif use_mock:
            mock = self.ingestor.generate_mock_fuel_data(n_flights=n_mock_flights)
            ing = self.ingestor.ingest_csv(mock, source="mock")
            logger.info(f"[{self.tenant_id}] Generated + ingested mock data: {n_mock_flights} flights")
            if tracer:
                tracer.log_input("mock_path", str(mock), "", "generated")
        else:
            return {"status":"ERROR"}

        fuel_df = self.ingestor.get_tenant_fuel_data()
        trajs = trajectories or self._load_trajs(n_mock_flights)
        matched = self.matcher.match_customer_fuel_to_trajectories(fuel_df, trajs)
        logger.info(f"[{self.tenant_id}] Matching complete: {len(matched)} matched out of {len(fuel_df)} fuel records")

        if tracer:
            tracer.log_step(
                "flight_matching",
                formula="exact(callsign+date) or fuzzy(route) — distance_only explicitly disabled unless ALLOW_DISTANCE_ONLY_MATCH=True",
                inputs={"fuel_rows": len(fuel_df), "trajectories": len(trajs)},
                outputs={"matched": len(matched)},
                module="flight_matcher"
            )

        if len(matched) < self.cfg.MIN_FLIGHTS_FOR_CALIBRATION:
            logger.warning(f"[{self.tenant_id}] Gate failed: only {len(matched)} matched (need >= {self.cfg.MIN_FLIGHTS_FOR_CALIBRATION})")
            if tracer:
                tracer.log_validation("CalibrationPipeline", "min_flights_gate", "FAIL",
                                      value=len(matched),
                                      expected_range=f">={self.cfg.MIN_FLIGHTS_FOR_CALIBRATION}",
                                      detail="Strict gate enforced for credibility")
            return {"status":"REJECTED", "message": f"Only {len(matched)} matched (need >= {self.cfg.MIN_FLIGHTS_FOR_CALIBRATION})"}

        calib_in = [{"distance_nm":m["distance_nm"], "actual_fuel_kg":m["actual_fuel_kg"]} for m in matched]
        cal = ModelCalibrator(aircraft_type)
        cres = cal.calibrate(calib_in)
        before = cres["accuracy"]["avg_error_before_pct"]
        after = cres["accuracy"]["avg_error_after_pct"]
        imp = cres["accuracy"]["improvement_pct"]
        logger.info(f"[{self.tenant_id}] Calibration complete: cd0={cres['calibration_factors']['cd0_factor']:.4f}, "
                    f"sfc={cres['calibration_factors']['sfc_factor']:.4f}, improvement={imp:.1f}% (test={cres.get('test_set_metrics',{}).get('improvement_pct') if cres.get('test_set_metrics') else 'N/A'})")

        if tracer:
            tracer.log_step(
                "model_calibration",
                formula="Nelder-Mead minimize Σ((pred-actual)/actual)² on 70% train; full+test metrics reported",
                inputs={"n_matched": len(matched), "train_size": int(len(matched)*0.7) if len(matched)>=8 else len(matched)},
                outputs={
                    "cd0_factor": cres["calibration_factors"]["cd0_factor"],
                    "sfc_factor": cres["calibration_factors"]["sfc_factor"],
                    "test_set_metrics": cres.get("test_set_metrics"),
                    "split_info": cres.get("split_info")
                },
                module="model_calibrator"
            )

        if imp < self.cfg.MIN_IMPROVEMENT_PCT or after > self.cfg.MAX_ACCEPTABLE_ERROR_AFTER_PCT:
            logger.warning(f"[{self.tenant_id}] Quality gate FAILED: imp={imp:.1f}%, after={after:.1f}%")
            if tracer:
                tracer.log_validation("CalibrationPipeline", "quality_gate", "FAIL",
                                      value=imp, expected_range=f">={self.cfg.MIN_IMPROVEMENT_PCT}% and after<={self.cfg.MAX_ACCEPTABLE_ERROR_AFTER_PCT}%")
            return {"status":"REJECTED", "message": f"Quality gate failed (imp={imp:.1f}%, after={after:.1f}%)"}

        if tracer:
            tracer.log_validation("CalibrationPipeline", "quality_gate", "PASS",
                                  value=imp, expected_range=f">={self.cfg.MIN_IMPROVEMENT_PCT}%")
            tracer.log_validation("CalibrationPipeline", "min_flights_gate", "PASS",
                                  value=len(matched), expected_range=f">={self.cfg.MIN_FLIGHTS_FOR_CALIBRATION}")

        self.last_result = {
            "status": "SUCCESS", "tenant_id": self.tenant_id,
            "full_matched_count": len(matched),
            "calibration": {
                "factors": cres["calibration_factors"],
                "accuracy": cres["accuracy"],
                # Honest test-set metrics (pre-real scientific integrity)
                "test_set_metrics": cres.get("test_set_metrics"),
            },
            "accuracy_improvement": {"before_pct": before, "after_pct": after, "improvement_pct": imp},
            "matched_flights_for_calib": matched[:3],
            "pre_real_data": True,
            "disclaimer": "PRE-REAL-DATA DEMO ONLY",
            "pipeline_version": self.cfg.PIPELINE_VERSION,
            "config_snapshot_hash": self.cfg.snapshot_hash(),
            "split_info": cres.get("split_info"),
            # === NEW: Full provenance trace ===
            "trace_id": tracer.analysis_id if tracer else None,
            "test_set_metrics": cres.get("test_set_metrics"),  # top-level for easy access
        }

        if tracer:
            try:
                trace_path = tracer.save_trace(
                    str(CALIBRATIONS_DIR / f"trace_{self.tenant_id}_{ts}.json")
                )
                self.last_result["trace_file"] = trace_path
                self.last_result["tracer_summary"] = tracer.get_trace()["summary"]
            except Exception:
                self.last_result["trace_file"] = None

        return self.last_result

    def _load_trajs(self, n):
        batch = Path(_PROJECT_ROOT) / "reports" / "optimizations" / "batch_results.json"
        if not batch.exists():
            # CRITICAL: Fail open was a security/credibility hole.
            # For PRE-REAL: we allow a minimal fallback only if explicitly in demo mode.
            # For REAL data path: caller must supply trajectories or this will raise.
            raise FileNotFoundError(
                "batch_results.json missing. In pre-real demo this is expected; "
                "for real data you MUST provide trajectories= or real ADS-B loader. "
                "Never silently use hardcoded dummies in production."
            )
        import json
        data = json.load(open(batch))
        return [{k: d.get(k) for k in ["callsign","flight_date","origin_airport","dest_airport","aircraft_type","distance_nm","estimated_fuel_kg"]} for d in data[:n]]

    def save_calibration(self):
        if not self.last_result: raise RuntimeError("run first")
        p = CALIBRATIONS_DIR / f"{self.tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(p, "w", encoding="utf-8") as f: json.dump(self.last_result, f, indent=2, ensure_ascii=False)
        return str(p)
