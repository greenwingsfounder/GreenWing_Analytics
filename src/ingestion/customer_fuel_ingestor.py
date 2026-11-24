"""
GreenWing Ingestion — Professional Customer Fuel Ingestor (v2.1)
"""
from __future__ import annotations
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import pandas as pd
from config.ingestion_config import DEFAULT_INGESTION_CONFIG
from config.settings import _PROJECT_ROOT
from src.logging_config import get_logger

logger = get_logger("ingestion.ingestor")  # Central logging (consistent across project)

CUSTOMER_FUEL_DIR = Path(_PROJECT_ROOT) / "data" / "customer_fuel"
CUSTOMER_FUEL_DIR.mkdir(parents=True, exist_ok=True)
MOCK_DATA_DIR = Path(_PROJECT_ROOT) / "data" / "mocks"
MOCK_DATA_DIR.mkdir(parents=True, exist_ok=True)

class CustomerFuelIngestor:
    def __init__(self, tenant_id: str = "default", config: Optional[Any] = None):
        self.tenant_id = tenant_id
        self.cfg = config or DEFAULT_INGESTION_CONFIG

    def ingest_csv(self, csv_path: str | Path, source="airline", validate=True):
        p = Path(csv_path)
        if not p.exists():
            return {"status": "ERROR", "message": "not found"}

        df = pd.read_csv(p)
        df = self._norm(df)

        recs = []
        rejected = 0
        rejection_reasons = []

        for idx, r in df.iterrows():
            try:
                rec = {
                    "tenant_id": self.tenant_id,
                    "flight_date": str(r.get("flight_date", "")),
                    "callsign": str(r.get("callsign", "")).upper(),
                    "origin": str(r.get("origin", "")).upper(),
                    "dest": str(r.get("dest", "")).upper(),
                    "actual_fuel_kg": float(r.get("actual_fuel_kg", 0)) if pd.notna(r.get("actual_fuel_kg")) else None,
                    "aircraft_type": str(r.get("aircraft_type", "B738")).upper(),
                    "distance_nm": float(r.get("distance_nm", 0)) if pd.notna(r.get("distance_nm")) else None,
                    "fuel_unit_raw": str(r.get("fuel_unit_raw", "")) if "fuel_unit_raw" in r else None,
                }

                if validate:
                    schema_errors = self._validate_schema(rec)
                    if schema_errors:
                        rejected += 1
                        rejection_reasons.append(f"row_{idx}: schema_error={'|'.join(schema_errors)}")
                        continue

                    dist = rec.get("distance_nm") or 1200
                    fuel_kg = rec.get("actual_fuel_kg") or 0
                    fpn = fuel_kg / max(dist, 1)
                    if not (self.cfg.MIN_FUEL_PER_NM_KG <= fpn <= self.cfg.MAX_FUEL_PER_NM_KG):
                        rejected += 1
                        rejection_reasons.append(f"row_{idx}: fuel_per_nm={fpn:.2f} out of range")
                        continue

                recs.append(rec)
            except Exception as e:
                rejected += 1
                rejection_reasons.append(f"row_{idx}: parse_error={str(e)[:50]}")

        out = CUSTOMER_FUEL_DIR / f"{self.tenant_id}_{uuid.uuid4().hex[:6]}.csv"
        pd.DataFrame(recs).to_csv(out, index=False)

        result = {
            "status": "SUCCESS",
            "records_loaded": len(recs),
            "records_rejected": rejected,
            "file_path": str(out),
            "source": source,
        }
        if rejected > 0:
            result["rejection_sample"] = rejection_reasons[:5]
            logger.warning(f"[{self.tenant_id}] {rejected} rows rejected during ingestion (sample: {rejection_reasons[:2]})")
        else:
            logger.info(f"[{self.tenant_id}] Successfully ingested {len(recs)} records")

        return result

    def _norm(self, df):
        """Normalize common airline CSV column variants (pre-real).
        Priority: actual_fuel_kg > block_fuel_kg > block_fuel_lbs (converted).
        Handles mixed columns, NaNs, comma decimals (EU), USG/lbs/litre stubs.
        This is CRITICAL pre-real hardening — real airline exports are messy.
        """
        m = {
            "date": "flight_date", "flight_date": "flight_date",
            "callsign": "callsign", "origin": "origin", "dest": "dest",
            "actual_fuel_kg": "actual_fuel_kg", "block_fuel_kg": "actual_fuel_kg",
            "block_fuel_lbs": "block_fuel_lbs_raw", "fuel_lbs": "block_fuel_lbs_raw",
            "fuel_kg": "actual_fuel_kg", "fuel": "actual_fuel_kg",
            "aircraft_type": "aircraft_type", "ac_type": "aircraft_type", "ac": "aircraft_type",
            "distance_nm": "distance_nm", "dist_nm": "distance_nm", "distance": "distance_nm",
            "fuel_usg": "fuel_usg", "usg": "fuel_usg", "gallons": "fuel_usg",
            "block_fuel_usg": "fuel_usg"
        }
        df.columns = [str(c).lower().strip() for c in df.columns]
        df = df.rename(columns={k: v for k, v in m.items() if k in df.columns})

        # Resolve fuel value with priority + unit detection
        if "actual_fuel_kg" in df.columns:
            fuel_col = "actual_fuel_kg"
            unit_hint = "kg"
        elif "block_fuel_lbs_raw" in df.columns:
            fuel_col = "block_fuel_lbs_raw"
            unit_hint = "lbs"
        elif "fuel_usg" in df.columns:
            fuel_col = "fuel_usg"
            unit_hint = "usg"
        else:
            fuel_col = None
            unit_hint = None

        if fuel_col:
            def parse_fuel_value(v, hint=unit_hint):
                """Robust fuel parser for real airline CSVs.
                - Handles comma decimals (European): "12.345,6" or "12,345.6"
                - Detects lbs vs kg via value + column hint
                - Stub for USG (common in US carriers): rough conversion
                - Returns None on failure (will be rejected)
                """
                if pd.isna(v) or v is None or str(v).strip() == "":
                    return None
                s = str(v).strip().replace(" ", "")
                # Handle European comma decimal (e.g. 12.345,67 → 12345.67)
                if "," in s and "." in s:
                    if s.rfind(",") > s.rfind("."):
                        s = s.replace(".", "").replace(",", ".")
                    else:
                        s = s.replace(",", "")
                elif "," in s:
                    s = s.replace(",", ".")
                try:
                    val = float(s)
                except (ValueError, TypeError):
                    return None

                # Unit resolution (pre-real robustness)
                col_lower = str(fuel_col).lower() if fuel_col else ""
                if hint == "usg" or "usg" in col_lower or "gallon" in col_lower:
                    # Jet-A density ~0.8 kg/L, 3.785 L/USG → ~3.028 kg/USG
                    return round(val * 3.028, 1)
                elif hint == "lbs" or "lbs" in col_lower or val > 18000:
                    # Strong lbs signal
                    return round(val * 0.45359237, 1)
                elif val > 18000 and "kg" not in col_lower:
                    # Heuristic fallback
                    return round(val * 0.45359237, 1)
                return round(val, 1)

            df["actual_fuel_kg"] = df[fuel_col].apply(parse_fuel_value)
            df["fuel_unit_raw"] = fuel_col  # for audit/provenance

        # Clean distance
        if "distance_nm" in df.columns:
            df["distance_nm"] = pd.to_numeric(df["distance_nm"], errors="coerce")

        return df

    def _validate_schema(self, row: dict) -> list[str]:
        """Lightweight schema validation stub (pre-real).
        Returns list of error strings. Empty list = OK.
        Can be strengthened later without changing pipeline contract.
        """
        errors = []
        if not row.get("flight_date"):
            errors.append("missing flight_date")
        if not row.get("callsign") and not (row.get("origin") and row.get("dest")):
            errors.append("missing callsign or route")
        fuel = row.get("actual_fuel_kg")
        if fuel is None or fuel <= 0:
            errors.append("invalid actual_fuel_kg")
        dist = row.get("distance_nm")
        if dist is not None and dist <= 0:
            errors.append("invalid distance_nm")
        return errors

    def generate_mock_fuel_data(self, n_flights=20, airline="SXS"):
        """
        Fiziksel temelli mock yakıt verisi üret.
        
        v2.2 DÜZELTME:
        ─────────────────────────────────────────────
        ESKİ: fuel = dist * 6.9 + gauss(0, 150) → lineer, fiziksel değil
              Calibrator bu mock'a overfitting yapıyordu.
        
        YENİ: Gerçek fiziksel faktörler dahil:
              - Weight effect (ağır uçak = daha çok yakıt, non-lineer)
              - Wind effect (headwind/tailwind ±%15 varyasyon)
              - Phase-of-flight dağılımı (kısa/uzun rota)
              - ISA sapması (sıcak/soğuk gün)
              - Crew fuel policy (contingency, reserve)
              - Uçak yaşı degradasyonu (cd0, sfc)
        
        Bu mock'a calibrate edilen model, gerçek veriye geldiğinde
        çok daha az sapma üretecek. Çünkü mock'un dağılımı gerçek
        verinin dağılımına benziyor.
        """
        import random
        from datetime import timedelta
        random.seed(self.cfg.MOCK_RANDOM_SEED)
        
        # Rota havuzu (gerçekçi dağılım)
        bases = [
            # Kısa rota — cruise %40-50
            {"callsign": f"{airline}1409", "origin": "LTAI", "dest": "EDDF",
             "distance_nm": 1241, "ac": "B738", "route_type": "medium"},
            # Orta rota — cruise %65-75
            {"callsign": f"{airline}120", "origin": "LTAI", "dest": "LCLK",
             "distance_nm": 410, "ac": "B738", "route_type": "short"},
            # Uzun rota — cruise %80-85
            {"callsign": f"{airline}802", "origin": "LTAI", "dest": "OMDB",
             "distance_nm": 1618, "ac": "B738", "route_type": "long"},
        ]
        
        # ── GERÇEK UÇUŞLARDAN TÜRET (denetim #92) ─────────────
        # Eskiden rota/çağrı işareti havuzu SABİTTİ (SXS1409, SXS120,
        # SXS802) ve tarih 2025-06-01'den başlıyordu. Depodaki gerçek
        # uçuşlar ise PGT120 / THY501 / SXS1409... farklı çağrı
        # işaretleri ve farklı tarihler taşıyordu → eşleştirici
        # HİÇBİR kaydı eşleştiremiyordu (0/30) ve kalibrasyon kapısı
        # (min 15 uçuş) asla açılmıyordu.
        #
        # ÇÖZÜM: batch_results.json varsa ondan türet (çağrı işareti,
        # rota, mesafe, tarih). Yoksa sabit havuza düş.
        try:
            import json as _json
            # DENETİM #95: 02 (analiz) ve 04 (demo) FARKLI şemalar
            # üretiyor. Öncelik 02'nin çıktısında; yoksa demoya düş.
            # İkisini karıştırmak 13/13 → 5/30 düşüşüne yol açıyordu.
            _opt = Path(_PROJECT_ROOT) / 'reports' / 'optimizations'
            _batch = None
            for _cand in ('batch_results.json', 'demo_batch_results.json'):
                _p = _opt / _cand
                if _p.exists():
                    _batch = _p
                    break
            if _batch is None:
                _batch = _opt / 'batch_results.json'
            if _batch.exists():
                _data = _json.loads(_batch.read_text(encoding='utf-8'))
                _derived = [
                    {'callsign': d.get('callsign'),
                     'origin': (d.get('origin')
                                or d.get('origin_airport')),
                     'dest': (d.get('destination')
                              or d.get('dest_airport')),
                     'distance_nm': float(d.get('distance_nm') or 0),
                     'ac': d.get('aircraft_type') or 'B738',
                     'flight_date': str(d.get('flight_date') or '')[:10],
                     'route_type': ('short'
                                    if float(d.get('distance_nm') or 0) < 600
                                    else 'medium'
                                    if float(d.get('distance_nm') or 0) < 1400
                                    else 'long')}
                    for d in _data if d.get('callsign')]
                if _derived:
                    bases = _derived
                    logger.info(
                        f"[mock] {len(bases)} uçuş batch_results'tan "
                        'türetildi (çağrı işareti + rota + tarih uyumlu)')
        except Exception as _e:      # türetme başarısızsa sabit havuz
            logger.warning(f'[mock] batch_results türetilemedi: {_e}')

        recs = []
        d0 = datetime(2025, 6, 1)
        
        # DENETİM #92: aynı (çağrı işareti, tarih) çifti iki kez
        # üretilirse eşleştirici ikincisini reddediyor (doğru davranış)
        # ve kalibrasyon kapısı boşa düşüyor. Tekrar üretme.
        _seen = set()
        _tries = 0
        while len(recs) < n_flights and _tries < n_flights * 30:
            _tries += 1
            b = random.choice(bases)
            _date = b.get("flight_date") or (
                d0 + timedelta(days=len(recs) % 28)).strftime("%Y-%m-%d")
            _key = (b["callsign"], _date)
            if _key in _seen:
                continue
            _seen.add(_key)
            dist = b["distance_nm"]
            route_type = b["route_type"]
            
            # ─── 1. Uçak ağırlığı (payload varyasyonu) ─────────
            # Her uçuşta farklı load factor (gerçekçi dağılım)
            load_factor = random.gauss(0.82, 0.08)  # ortalama %82, std %8
            load_factor = max(0.55, min(0.98, load_factor))
            
            # B738 referans: OEW=41413, seats=162, pax_weight=95kg
            pax_weight = 162 * load_factor * random.gauss(95, 10)
            cargo_weight = random.gauss(1500, 500)
            payload = pax_weight + cargo_weight
            oew = 41413
            dry_weight = oew + payload  # Yakıtsız ağırlık
            
            # ─── 2. Yakıt tahmini (SAR bazlı) ──────────────────
            # Tipik SAR: B738 için ~0.095 Nm/kg cruise
            sar_base = 0.095
            cruise_fuel_est = dist / sar_base
            
            # ─── 3. Faz dağılımı (route_type'a göre) ───────────
            if route_type == "short":
                cruise_pct = random.gauss(0.45, 0.05)  # %45 cruise
                climb_pct = 0.30
                descent_pct = 0.12
            elif route_type == "medium":
                cruise_pct = random.gauss(0.70, 0.04)  # %70 cruise
                climb_pct = 0.18
                descent_pct = 0.08
            else:  # long
                cruise_pct = random.gauss(0.82, 0.03)  # %82 cruise
                climb_pct = 0.12
                descent_pct = 0.05
            
            # Taxi + takeoff + approach (sabit, küçük)
            non_cruise_fixed = 2200  # kg (taxi_out + T/O + approach + taxi_in)
            
            # ─── 4. Wind effect (±%15 varyasyon) ───────────────
            # Headwind → daha çok yakıt, tailwind → daha az
            wind_effect = random.gauss(1.0, 0.08)  # ortalama 1.0, std %8
            wind_effect = max(0.82, min(1.20, wind_effect))
            
            # ─── 5. Weight effect (non-lineer) ─────────────────
            # Ağır uçak = daha çok drag = daha çok yakıt
            # Ama non-lineer: her kg başına aynı etki değil
            weight_ref = oew + 14000  # Tipik referans ağırlık
            weight_ratio = dry_weight / weight_ref
            weight_effect = weight_ratio ** 0.85  # Non-lineer (0.85 üs)
            
            # ─── 6. ISA sapması (sıcak/soğuk gün) ──────────────
            # Sıcak gün → motor verimi düşer → SFC artar
            isa_deviation = random.gauss(0, 8)  # °C, std ±8
            isa_effect = 1.0 + 0.003 * isa_deviation  # +10°C → %3
            isa_effect = max(0.95, min(1.06, isa_effect))
            
            # ─── 7. Uçak yaşı degradasyonu (sfc_factor) ────────
            # Bazı uçaklar daha yaşlı → daha çok yakıt
            age_factor = random.gauss(1.0, 0.03)  # std %3
            age_factor = max(0.95, min(1.10, age_factor))
            
            # ─── 8. Contingency + reserve ──────────────────────
            # Crew fuel policy: %5 contingency + %30 min reserve (30 dk holding)
            contingency_pct = random.gauss(0.05, 0.01)
            
            # ─── TOPLAM YAKIT ──────────────────────────────────
            base_fuel = cruise_fuel_est * cruise_pct  # Cruise yakıtı
            climb_fuel = cruise_fuel_est * climb_pct * 1.35  # Climb daha verimsiz
            descent_fuel = cruise_fuel_est * descent_pct * 0.4  # Descent az yakıt
            
            # Etkileri uygula
            total_fuel = (base_fuel + climb_fuel + descent_fuel + non_cruise_fixed)
            total_fuel *= wind_effect      # Rüzgar etkisi
            total_fuel *= weight_effect    # Ağırlık etkisi
            total_fuel *= isa_effect       # Sıcaklık etkisi
            total_fuel *= age_factor       # Yaş degradasyonu
            total_fuel *= (1 + contingency_pct)  # Contingency
            
            # Son kontrol: fiziksel makul aralıkta mı?
            min_fuel = dist * 4.5   # Absolute minimum (imkansız ama alt sınır)
            max_fuel = dist * 10.0  # Absolute maximum (çok verimsiz)
            total_fuel = max(min_fuel, min(max_fuel, total_fuel))
            
            recs.append({
                # DENETİM #92: tarih sabit d0'dan üretiliyordu → her
                # zaman 2025-06-xx. Türetilen tarih (gerçek uçuşun
                # tarihi) VARSA onu kullan; yoksa geriye dönük d0.
                "flight_date": (b.get("flight_date")
                                or (d0 + timedelta(days=len(recs) % 28))
                                .strftime("%Y-%m-%d")),
                "callsign": b["callsign"],
                "origin": b["origin"],
                "dest": b["dest"],
                "actual_fuel_kg": int(total_fuel),
                "aircraft_type": b["ac"],
                "distance_nm": dist,
                # Bonus: provenance için (ileride kullanılabilir)
                "_debug_load_factor": round(load_factor, 3),
                "_debug_wind_effect": round(wind_effect, 3),
                "_debug_weight_effect": round(weight_effect, 3),
            })
        
        out = MOCK_DATA_DIR / f"mock_{self.tenant_id}_{n_flights}.csv"
        pd.DataFrame(recs).to_csv(out, index=False)
        return str(out)

    def get_tenant_fuel_data(self):
        files = list(CUSTOMER_FUEL_DIR.glob(f"{self.tenant_id}_*.csv"))
        if not files:
            return pd.DataFrame()
        dfs = []
        for f in files:
            try:
                dfs.append(pd.read_csv(f))
            except Exception as e:
                logger.warning(f"Skipping bad file {f}: {e}")
        return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
