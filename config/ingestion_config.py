"""
GreenWing Enterprise Ingestion Configuration (v2.1)
All thresholds, gates, and versioning for professional pre-real-data pipeline.
Comparable to Honeywell / Lufthansa Systems fuel SaaS standards.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Any, Dict
from datetime import datetime
import hashlib, json

@dataclass(frozen=True)
class IngestionConfig:
    PIPELINE_VERSION: str = "2.1.0-enterprise-pre-real"
    CALIBRATION_SCHEMA_VERSION: str = "1.3"
    CONFIG_GENERATED_AT: str = "2026-07-11T00:00:00Z"  # Fixed for stable snapshot_hash across runs / machines

    # Professional gates
    MIN_FLIGHTS_FOR_CALIBRATION: int = 15
    RECOMMENDED_FLIGHTS_FOR_SALES: int = 25
    MIN_IMPROVEMENT_PCT: float = 4.0
    MAX_ACCEPTABLE_ERROR_AFTER_PCT: float = 6.5

    # Matching
    MATCH_SCORE_EXACT: int = 92
    MATCH_SCORE_FUZZY_ROUTE: int = 70
    MATCH_SCORE_DISTANCE: int = 55
    ALLOW_DISTANCE_ONLY_MATCH: bool = False   # CRITICAL PRE-REAL: Set True only for extreme fallback. Recommended: False
    MIN_ACCEPTABLE_MATCH_SCORE: int = 55
    DEFAULT_TOLERANCE_DAYS: int = 1

    # Data quality
    MIN_FUEL_PER_NM_KG: float = 3.8
    MAX_FUEL_PER_NM_KG: float = 13.5
    MIN_FUEL_KG: float = 800.0
    MAX_FUEL_KG: float = 185000.0

    # Reproducibility & audit
    MOCK_RANDOM_SEED: int = 42
    FORCE_PRE_REAL_DISCLAIMER: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def snapshot_hash(self) -> str:
        data = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(data.encode('utf-8')).hexdigest()[:16]

    def validate(self) -> None:
        assert self.MIN_FLIGHTS_FOR_CALIBRATION >= 12
        assert self.MIN_IMPROVEMENT_PCT >= 2.0

DEFAULT_INGESTION_CONFIG = IngestionConfig()
DEFAULT_INGESTION_CONFIG.validate()
