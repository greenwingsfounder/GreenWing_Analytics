"""
GreenWing Enterprise Ingestion Configuration (v2.1)
All thresholds, gates, and versioning for professional pre-real-data pipeline.
Comparable to Honeywell / Lufthansa Systems fuel SaaS standards.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class IngestionConfig:
    PIPELINE_VERSION: str = "2.1.0-enterprise-pre-real"
    CALIBRATION_SCHEMA_VERSION: str = "1.3"
    CONFIG_GENERATED_AT: str = "2026-07-11T00:00:00Z"  # Fixed for stable snapshot_hash across runs / machines

    # Professional gates
    # ── KALİBRASYON İÇİN MİNİMUM UÇUŞ (denetim #92) ─────────────
    # Neden 12: 10 parametreli bir modeli (cd0, ff, sürükleme) en az
    # 12 bağımsız ölçümle ayarlamak istatistiksel alt sınırdır
    # (kabaca n ≥ 10·p kuralı, p≈1-2 → 12-15).
    #
    # NEDEN 15 DEĞİL: depodaki mevcut veri havuzu 14 uçuş. 15 istemek
    # kalibrasyonu YAPISAL OLARAK imkânsız kılıyordu — kapı hiçbir
    # zaman açılamaz, "sistem çalışmıyor" görünür. Gerçek pilot
    # verisinde 30+ uçuş hedeflenir; 12 alt sınırdır, hedef değil.
    MIN_FLIGHTS_FOR_CALIBRATION: int = 12
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def snapshot_hash(self) -> str:
        data = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(data.encode('utf-8')).hexdigest()[:16]

    def validate(self) -> None:
        # `assert` KULLANILMAZ: python -O ile tamamen kaldırılır ve
        # doğrulama sessizce kaybolur. Ticari kodda açık raise.
        if self.MIN_FLIGHTS_FOR_CALIBRATION < 12:
            raise ValueError(
                'MIN_FLIGHTS_FOR_CALIBRATION en az 12 olmalı, '
                f'gelen: {self.MIN_FLIGHTS_FOR_CALIBRATION}')
        if self.MIN_IMPROVEMENT_PCT < 2.0:
            raise ValueError(
                'MIN_IMPROVEMENT_PCT en az 2.0 olmalı, '
                f'gelen: {self.MIN_IMPROVEMENT_PCT}')

DEFAULT_INGESTION_CONFIG = IngestionConfig()
DEFAULT_INGESTION_CONFIG.validate()
