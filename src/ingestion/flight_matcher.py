"""
GreenWing Professional Flight Matcher (v2.1)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import pandas as pd

from config.ingestion_config import DEFAULT_INGESTION_CONFIG
from src.logging_config import get_logger

logger = get_logger("ingestion.matcher")  # Central logging (consistent)

class FlightMatcher:
    def __init__(self, tenant_id="default", tolerance_days=None, config: Any | None = None):
        self.tenant_id = tenant_id
        self.cfg = config or DEFAULT_INGESTION_CONFIG
        self.tolerance_days = tolerance_days or self.cfg.DEFAULT_TOLERANCE_DAYS

    def match_customer_fuel_to_trajectories(self, fuel_df: pd.DataFrame, trajs: list[dict]) -> list[dict]:
        if fuel_df.empty: return []
        # DENETİM #92: 'used' set'i her trajectory'yi YALNIZCA BİR KEZ
        # eşleştiriyordu. Ama aynı uçuş (ör. PGT120) birden çok günde
        # yapılır ve müşteri CSV'sinde her gün ayrı satırdır.
        # Sonuç: 14 uçuşluk veri havuzunda yalnızca 4 eşleşme çıkıyordu
        # ve kalibrasyon kapısı (>=15) hiç açılamıyordu.
        #
        # DOĞRU KURAL: bir trajectory bir GÜNE aittir. Aynı çağrı
        # işareti + AYNI TARİH yalnızca bir kez eşleşir; farklı
        # tarihler serbesttir. Anahtar: (callsign, date).
        matched, used = [], set()
        for _, f in fuel_df.iterrows():
            best_score, best = -1, None
            for i, t in enumerate(trajs):
                _t_key = (str(t.get('callsign', '')).upper(),
                          str(t.get('flight_date') or
                              t.get('timestamp', ''))[:10])
                if _t_key in used:      # aynı uçuş + aynı gün → tekrar yok
                    continue
                sc = 0
                if str(f.get("callsign","")).upper() == str(t.get("callsign","")).upper():
                    if abs(self._dd(str(f.get("flight_date","")), str(t.get("flight_date",t.get("timestamp",""))))) <= self.tolerance_days:
                        sc = self.cfg.MATCH_SCORE_EXACT
                elif (str(f.get("origin","")) == str(t.get("origin_airport","")) and str(f.get("dest","")) == str(t.get("dest_airport",""))):
                    sc = self.cfg.MATCH_SCORE_FUZZY_ROUTE
                elif abs(float(t.get("distance_nm",0)) - float(f.get("distance_nm",0))) / max(float(t.get("distance_nm",1)),1) < 0.09:
                    # === CRITICAL PRE-REAL HARDENING (no real data required) ===
                    # Pure distance-only matching is EXTREMELY DANGEROUS.
                    #
                    # Deep reason (as the founder you must understand):
                    # - Two unrelated flights can have almost identical great-circle distance
                    #   (e.g. IST-EDDF ~1240 Nm and ANK-EDDF ~1240 Nm).
                    # - But actual block fuel can differ 10-25% because of:
                    #     * payload (pax + cargo + belly)
                    #     * head/tail wind
                    #     * ATC constraints, step climbs, holding, reroutes
                    #     * aircraft age, engine condition, winglet status, paint
                    #     * crew fuel policy and procedures
                    # - Assigning the wrong actual_fuel_kg to the wrong trajectory
                    #   poisons the calibration objective function.
                    # - Result: wrong cd0_factor / sfc_factor → completely wrong
                    #   savings numbers shown to the airline → loss of credibility.
                    #
                    # For real customer fuel data we MUST use:
                    #   1. callsign + date (EXACT, score=92)
                    #   2. origin + dest (FUZZY ROUTE, score=70)
                    #
                    # By default (ALLOW_DISTANCE_ONLY_MATCH=False) we SKIP this branch entirely.
                    if not getattr(self.cfg, "ALLOW_DISTANCE_ONLY_MATCH", False):
                        continue   # Completely disable distance-only matching
                    sc = 30
                    # This line is only reached if someone explicitly sets
                    # ALLOW_DISTANCE_ONLY_MATCH=True (strongly discouraged)
                if sc > best_score:
                    best_score, best = sc, {"match_quality":"EXACT" if sc>90 else "FUZZY" if sc>65 else "DISTANCE", "match_score":sc, "trajectory":t, "customer_fuel":dict(f)}
            if best and best_score >= self.cfg.MIN_ACCEPTABLE_MATCH_SCORE:
                used.add((str(best['trajectory'].get('callsign', '')).upper(),
                          str(best['trajectory'].get('flight_date') or
                              best['trajectory'].get('timestamp', ''))[:10]))
                t = best["trajectory"]
                pred = t.get("estimated_fuel_kg", float(t.get("distance_nm",1200))*6.8)
                matched.append({
                    "match_id": str(uuid.uuid4())[:8], "tenant_id": self.tenant_id,
                    "match_quality": best["match_quality"], "match_score": best["match_score"],
                    "flight_date": best["customer_fuel"].get("flight_date"),
                    "callsign": best["customer_fuel"].get("callsign"),
                    "origin": best["customer_fuel"].get("origin"), "dest": best["customer_fuel"].get("dest"),
                    "aircraft_type": best["customer_fuel"].get("aircraft_type","B738"),
                    "distance_nm": float(t.get("distance_nm",0)),
                    "actual_fuel_kg": float(best["customer_fuel"].get("actual_fuel_kg",0)),
                    "predicted_fuel_kg": round(float(pred),1),
                })
        return matched

    def _dd(self, d1, d2):
        try:
            dt1 = datetime.strptime(d1[:10], "%Y-%m-%d")
            dt2 = datetime.strptime(d2[:10], "%Y-%m-%d")
            return (dt1-dt2).days
        except (ValueError, TypeError, IndexError):
            return 999

    def get_match_statistics(self, m):
        return {"total_matched": len(m)}

    def __repr__(self): return f"FlightMatcher({self.tenant_id})"
