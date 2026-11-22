

from __future__ import annotations
from config.settings import EI_CO2  # CORSIA: 3.16 kg CO₂/kg yakıt

"""
GreenWing Analytics — İrtifa ve Step Climb Optimizasyonu
═══════════════════════════════════════════════════════════

Bu modül 3 ana işi yapar:

1. Verilen uçak ağırlığı, Mach ve heading için optimum cruise irtifasını bulur
2. Uzun rotalarda step climb planı üretir
3. Dispatcher / operasyon ekibine sunulabilir talimat oluşturur

TEMEL FİKİR:
────────────
Yakıt verimliliğinin temel metriği SAR'dır:

    SAR = TAS / Fuel_Flow   [Nm/kg]

SAR ne kadar yüksekse, uçak 1 kg yakıtla o kadar fazla yol alır.

İrtifa arttıkça:
    • hava yoğunluğu düşer
    • drag azalır
    • SAR genelde artar

Ama aynı zamanda:
    • aynı kaldırma için CL artar
    • buffet riski artar
    • thrust yeterliliği azalır

Bu yüzden "en yüksek irtifa" değil, "en uygun irtifa" vardır.

BU MODÜLÜN KISITLARI:
─────────────────────
1. Buffet sınırı
2. Motor thrust yeterliliği
3. Uçağın maksimum operasyonel irtifası
4. RVSM / flight level kuralı
5. Doğu-batı heading'e göre FL seçimi
6. Step climb sayısı ve aralık kısıtları

NOT:
────
Bu modülde kullanılan `max_thrust_sl` değeri
aircraft_database.yaml içinde **motor başına thrust** olarak yorumlanır.

Örnek:
    B738 → 121400 N / motor
    toplam thrust = 2 × 121400 = 242800 N
"""

import numpy as np
from typing import Optional

from src.models.fuel_model import FuelModel
from src.units import Units
from config.assumptions import Assumptions, OPERATIONAL_DAYS_PER_YEAR


# ═══════════════════════════════════════════════════════════
# SABİTLER
# ═══════════════════════════════════════════════════════════

# RVSM flight levels
_RVSM_LEVELS = list(range(29000, 42000, 1000))

# ICAO semi-circular / hemispherical rule
# 0-179°   → Eastbound → tek FL
# 180-359° → Westbound → çift FL
_EASTBOUND_LEVELS = [31000, 33000, 35000, 37000, 39000, 41000]
_WESTBOUND_LEVELS = [30000, 32000, 34000, 36000, 38000, 40000]

# Step climb mantık sınırları
_MAX_STEP_CLIMBS = 4
_MIN_STEP_INTERVAL_NM = 200
_MIN_NET_SAVING_KG = 50
# Raporlanabilir en küçük tasarruf — altında 0 gösterilir (yuvarlama artığı)
_MIN_REPORTABLE_SAVING_KG = 5.0
_MIN_REMAINING_NM = 200

# Buffet guard band
# Sertifikasyon seviyesinde 1.3g marjı için çok daha detaylı AFM/FCOM
# verisi gerekir. Bu optimizer seviyesinde onset CL'nin %90'ı operasyonel
# screening limiti olarak kullanılır.
_BUFFET_OPERATIONAL_FACTOR = 0.90

# Buffet onset CL referansları
# Yaklaşık operasyonel tablo. Uçak tipi ve Mach'a göre değişir.
_BUFFET_CL = {
    'B738': {0.70: 0.72, 0.74: 0.68, 0.78: 0.62, 0.80: 0.58, 0.82: 0.54},
    'B38M': {0.70: 0.73, 0.74: 0.69, 0.78: 0.63, 0.80: 0.59, 0.82: 0.55},
    'A320': {0.70: 0.74, 0.74: 0.70, 0.78: 0.64, 0.80: 0.60, 0.82: 0.56},
    'A20N': {0.70: 0.75, 0.74: 0.71, 0.78: 0.65, 0.80: 0.61, 0.82: 0.57}, 
    'B77W': {0.80: 0.65, 0.82: 0.62, 0.84: 0.57, 0.86: 0.52},
    'B788': {0.82: 0.66, 0.84: 0.62, 0.86: 0.58, 0.88: 0.54},
    'B789': {0.82: 0.66, 0.84: 0.62, 0.86: 0.58, 0.88: 0.54},
    'A350': {0.82: 0.68, 0.84: 0.64, 0.86: 0.60, 0.88: 0.56},
    'A380': {0.82: 0.67, 0.84: 0.63, 0.86: 0.59, 0.88: 0.55},
    'DEFAULT': {0.70: 0.70, 0.74: 0.66, 0.78: 0.60, 0.80: 0.56, 0.82: 0.52},
}


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class AltitudeOptimizer:
    """
    İrtifa ve step climb optimizasyonu.

    Args:
        aircraft_type: ICAO uçak tipi
        delta_isa    : ISA sapması (°C)
        cd0_factor   : Drag kalibrasyon çarpanı
        sfc_factor   : SFC kalibrasyon çarpanı
    """

    def __init__(
        self,
        aircraft_type: str = "B738",
        delta_isa: float = 0.0,
        cd0_factor: float = 1.0,
        sfc_factor: float = 1.0,
    ) -> None:
        self.ac_type = aircraft_type
        self.delta_isa = delta_isa

        self.fuel_model = FuelModel(
            aircraft_type=aircraft_type,
            delta_isa=delta_isa,
            cd0_factor=cd0_factor,
            sfc_factor=sfc_factor,
        )

    # ──────────────────────────────────────────────────────
    # YARDIMCI: Mach için buffet CL interpolation
    # ──────────────────────────────────────────────────────

    def _interpolate_buffet_cl(self, mach: float) -> float:
        """
        Verilen Mach için buffet onset CL'yi lineer interpolate eder.
        """
        table = _BUFFET_CL.get(self.ac_type, _BUFFET_CL["DEFAULT"])
        mach_keys = sorted(table.keys())

        if mach <= mach_keys[0]:
            return float(table[mach_keys[0]])

        if mach >= mach_keys[-1]:
            return float(table[mach_keys[-1]])

        for i in range(len(mach_keys) - 1):
            m1 = mach_keys[i]
            m2 = mach_keys[i + 1]
            if m1 <= mach <= m2:
                cl1 = table[m1]
                cl2 = table[m2]
                frac = (mach - m1) / (m2 - m1)
                return float(cl1 + frac * (cl2 - cl1))

        return float(table[mach_keys[-1]])

    # ──────────────────────────────────────────────────────
    # YARDIMCI: Tek bir FL değerlendir
    # ──────────────────────────────────────────────────────

    def _evaluate_altitude(
        self,
        alt_ft: float,
        weight_kg: float,
        mach: float,
        wind_at_levels: Optional[dict[int, float]] = None,
    ) -> dict:
        """
        Tek bir irtifayı değerlendir.

        Çıktı:
            feasible?
            CL
            L/D
            drag
            fuel flow
            air_sar
            ground_sar
            buffet_margin
            reason (uygunsuzsa)
        """
        try:
            cl = self.fuel_model.lift_coefficient(weight_kg, alt_ft, mach)
            cd = self.fuel_model.drag_coefficient(cl)
            ld = cl / cd if cd > 0 else 0.0
            drag_n = self.fuel_model.cruise_drag(weight_kg, alt_ft, mach)
        except (ValueError, ZeroDivisionError) as e:
            return {
                "altitude_ft": alt_ft,
                "feasible": False,
                "reason": f"Hesaplama hatası: {e}",
                "cl": 0.0,
                "buffet_margin_pct": 0.0,
                "air_sar": 0.0,
                "ground_sar": 0.0,
                "fuel_flow_kg_hr": 0.0,
                "lift_to_drag": 0.0,
            }

        # ─── Buffet kontrolü
        cl_buffet = self._interpolate_buffet_cl(mach)
        cl_limit = cl_buffet * _BUFFET_OPERATIONAL_FACTOR
        buffet_margin = ((cl_limit - cl) / cl_limit * 100.0) if cl_limit > 0 else 0.0

        if cl > cl_limit:
            return {
                "altitude_ft": alt_ft,
                "feasible": False,
                "reason": (
                    f"Buffet limiti aşıldı: CL={cl:.4f} > "
                    f"limit={cl_limit:.4f} (onset={cl_buffet:.4f})"
                ),
                "cl": float(cl),
                "buffet_margin_pct": float(buffet_margin),
                "air_sar": 0.0,
                "ground_sar": 0.0,
                "fuel_flow_kg_hr": 0.0,
                "lift_to_drag": float(ld),
            }

        # ─── Thrust yeterliliği
        delta = Units.pressure_ratio(alt_ft, self.delta_isa)

        # max_thrust_sl değerini MOTOR BAŞINA thrust olarak yorumluyoruz
        thrust_per_engine = self.fuel_model.params.get("max_thrust_sl", 120000)
        n_engines = self.fuel_model.params.get("num_engines", 2)
        total_sl_thrust = thrust_per_engine * n_engines

        # Basit available thrust modeli
        # Not: Gerçek motor thrust'ı sıcaklık, Mach, bypass ratio'dan etkilenir.
        # # Bu basit model yüksek irtifada (FL350+) kabul edilebilir düzeydedir.
        # # Düşük irtifada veya çok ağır uçaklarda hata payı büyüyebilir.
        max_thrust_available = total_sl_thrust * delta * 0.95

        if drag_n > max_thrust_available:
            return {
                "altitude_ft": alt_ft,
                "feasible": False,
                "reason": (
                    f"Thrust yetersiz: Drag={drag_n:.0f}N > "
                    f"Available={max_thrust_available:.0f}N"
                ),
                "cl": float(cl),
                "buffet_margin_pct": float(buffet_margin),
                "air_sar": 0.0,
                "ground_sar": 0.0,
                "fuel_flow_kg_hr": 0.0,
                "lift_to_drag": float(ld),
            }

        # ─── Yakıt / SAR
        ff_kg_s = self.fuel_model.cruise_fuel_flow(weight_kg, alt_ft, mach)
        ff_kg_hr = ff_kg_s * 3600.0
        air_sar = self.fuel_model.specific_air_range(weight_kg, alt_ft, mach)

        # ─── Rüzgar
        wind_kts = 0
        if wind_at_levels:
            if alt_ft in wind_at_levels:
                wind_kts = wind_at_levels[alt_ft]
            else:
                nearest_alt = min(wind_at_levels.keys(), key=lambda a: abs(a - alt_ft))
                if abs(nearest_alt - alt_ft) <= 2000:
                    wind_kts = wind_at_levels[nearest_alt]

        V_tas = Units.mach_to_tas(mach, alt_ft, self.delta_isa)
        V_ground = V_tas - wind_kts * 0.514444

        if V_ground <= 0:
            return {
                "altitude_ft": alt_ft,
                "feasible": False,
                "reason": f"Ground speed negatif (wind={wind_kts} kt)",
                "cl": float(cl),
                "buffet_margin_pct": float(buffet_margin),
                "air_sar": float(air_sar),
                "ground_sar": 0.0,
                "fuel_flow_kg_hr": float(ff_kg_hr),
                "lift_to_drag": float(ld),
            }

        ground_sar = (V_ground / ff_kg_s) / Units.get_nm_to_m_factor() if ff_kg_s > 0 else 0.0

        return {
            "altitude_ft": alt_ft,
            "feasible": True,
            "cl": float(cl),
            "cd": float(cd),
            "lift_to_drag": float(ld),
            "drag_N": float(drag_n),
            "fuel_flow_kg_hr": float(ff_kg_hr),
            "air_sar": float(air_sar),
            "ground_sar": float(ground_sar),
            "wind_kts": int(wind_kts),
            "buffet_margin_pct": float(buffet_margin),
            "temperature_K": float(Units.temperature_at_altitude(alt_ft, self.delta_isa)),
            "density_kg_m3": float(Units.density_at_altitude(alt_ft, self.delta_isa)),
        }

    # ──────────────────────────────────────────────────────
    # ANA: optimum FL
    # ──────────────────────────────────────────────────────

    def find_optimum_altitude(
        self,
        weight_kg: float,
        mach: float,
        heading_deg: Optional[float] = None,
        wind_at_levels: Optional[dict[int, float]] = None,
    ) -> dict:
        """
        Verilen ağırlık / Mach / heading için optimum irtifayı bulur.
        """
        if heading_deg is not None:
            if 0 <= heading_deg < 180:
                available_levels = _EASTBOUND_LEVELS.copy()
                direction = "Eastbound"
            else:
                available_levels = _WESTBOUND_LEVELS.copy()
                direction = "Westbound"
        else:
            available_levels = _RVSM_LEVELS.copy()
            direction = "All"

        max_alt = self.fuel_model.params.get("max_altitude", 41000)
        available_levels = [fl for fl in available_levels if fl <= max_alt]

        if not available_levels:
            return {
                "status": "ERROR",
                "message": f"Uygun FL yok. Max altitude: FL{max_alt // 100}",
                "weight_kg": weight_kg,
            }

        evaluations = []
        for alt_ft in available_levels:
            evaluations.append(
                self._evaluate_altitude(
                    alt_ft=alt_ft,
                    weight_kg=weight_kg,
                    mach=mach,
                    wind_at_levels=wind_at_levels,
                )
            )

        feasible = [e for e in evaluations if e["feasible"]]

        if not feasible:
            return {
                "status": "ERROR",
                "message": "Hiçbir irtifa fiziksel olarak uygun değil. Ağırlık çok yüksek veya koşullar uygunsuz.",
                "weight_kg": weight_kg,
                "all_evaluations": evaluations,
            }

        metric = "ground_sar" if wind_at_levels else "air_sar"
        best = max(feasible, key=lambda x: x[metric])
        alternatives = sorted(feasible, key=lambda x: x[metric], reverse=True)

        fl350_eval = next((e for e in feasible if e["altitude_ft"] == 35000), None)

        if fl350_eval:
            sar_improvement = (
                (best[metric] - fl350_eval[metric]) / fl350_eval[metric] * 100
            ) if fl350_eval[metric] > 0 else 0.0

            fuel_saving_1000nm = (
                1000 / fl350_eval[metric] - 1000 / best[metric]
            ) if fl350_eval[metric] > 0 and best[metric] > 0 else 0.0
        else:
            sar_improvement = 0.0
            fuel_saving_1000nm = 0.0

        return {
            "status": "SUCCESS",
            "optimization_metric": metric,
            "direction": direction,
            "weight_kg": weight_kg,
            "mach": mach,
            "optimum": {
                "altitude_ft": best["altitude_ft"],
                "flight_level": f"FL{best['altitude_ft'] // 100}",
                "air_sar": round(best["air_sar"], 6),
                "ground_sar": round(best["ground_sar"], 6),
                "fuel_flow_kg_hr": round(best["fuel_flow_kg_hr"], 0),
                "lift_to_drag": round(best["lift_to_drag"], 2),
                "cl": round(best["cl"], 4),
                "buffet_margin_pct": round(best["buffet_margin_pct"], 1),
                "wind_component_kts": best.get("wind_kts", 0),
            },
            "vs_fl350": {
                "sar_improvement_pct": round(sar_improvement, 2),
                "fuel_saving_per_1000nm_kg": round(fuel_saving_1000nm, 1),
            },
            "top_3_alternatives": [
                {
                    "flight_level": f"FL{a['altitude_ft'] // 100}",
                    "sar": round(a[metric], 6),
                    "fuel_flow_kg_hr": round(a["fuel_flow_kg_hr"], 0),
                    "cl": round(a["cl"], 4),
                    "buffet_margin_pct": round(a["buffet_margin_pct"], 1),
                }
                for a in alternatives[:3]
            ],
            "all_evaluations": evaluations,
        }

    # ──────────────────────────────────────────────────────
    # Step climb kârlılık değerlendirmesi
    # ──────────────────────────────────────────────────────

    def _evaluate_step_climb(
        self,
        current_alt_ft: float,
        new_alt_ft: float,
        weight_kg: float,
        mach: float,
        remaining_distance_nm: float,
    ) -> dict:
        # DİKKAT: mach MUTLAKA geçirilmeli. Geçirilmezse baseline
        # karşılaştırması varsayılan 0.78 ile yapılır ve gerçek
        # seyir Mach'ından farklı bir ceza çıkar.
        climb_fuel = self.fuel_model.estimate_climb_fuel(
            current_alt_ft, new_alt_ft, weight_kg, mach
        )

        sar_old = self.fuel_model.specific_air_range(weight_kg, current_alt_ft, mach)
        sar_new = self.fuel_model.specific_air_range(weight_kg, new_alt_ft, mach)

        if sar_old > 0 and sar_new > 0:
            fuel_old = remaining_distance_nm / sar_old
            fuel_new = remaining_distance_nm / sar_new
            net_saving = (fuel_old - fuel_new) - climb_fuel
            sar_improvement = (sar_new - sar_old) / sar_old * 100
        else:
            fuel_old = 0.0
            fuel_new = 0.0
            net_saving = 0.0
            sar_improvement = 0.0

        return {
            # AD: net ek ceza (tırmanış yakıtı - aynı mesafedeki seyir yakıtı).
            # Eski ad "climb_fuel_kg" idi ve tırmanışın TOPLAM yakıtı sanılıyordu.
            "climb_fuel_kg": climb_fuel,
            "fuel_old_remaining": round(fuel_old, 1),
            "fuel_new_remaining": round(fuel_new, 1),
            "net_saving_kg": round(net_saving, 1),
            "sar_old": sar_old,
            "sar_new": sar_new,
            "sar_improvement_pct": round(sar_improvement, 2),
        }

    # ──────────────────────────────────────────────────────
    # Tam uçuş step climb optimizasyonu
    # ──────────────────────────────────────────────────────

    def optimize_full_flight(
        self,
        distance_nm: float,
        initial_weight_kg: float,
        payload_kg: float,
        mach: float,
        heading_deg: float,
        wind_profile: Optional[dict[int, float]] = None,
        step_interval_nm: Optional[float] = None,
    ) -> dict:
        """
        Tam uçuş için FL350 baseline, optimum sabit FL ve step climb
        senaryolarını karşılaştırır.
        """
        if step_interval_nm is None:
            if distance_nm < 500:
                step_interval_nm = distance_nm
            elif distance_nm < 1000:
                step_interval_nm = max(250, distance_nm / 3)
            elif distance_nm < 3000:
                step_interval_nm = 300
            else:
                step_interval_nm = 400

        # Baseline FL350
        baseline_alt = 35000
        baseline_result = self.fuel_model.fuel_for_distance(
            distance_nm=distance_nm,
            weight_initial_kg=initial_weight_kg,
            altitude_ft=baseline_alt,
            mach=mach,
        )
        baseline_fuel = baseline_result["total_fuel_kg"]

        # Optimum sabit FL
        mid_weight = initial_weight_kg - baseline_fuel / 2
        fixed_opt = self.find_optimum_altitude(
            mid_weight, mach, heading_deg, wind_profile
        )

        if fixed_opt["status"] == "SUCCESS":
            opt_fixed_alt = fixed_opt["optimum"]["altitude_ft"]
        else:
            opt_fixed_alt = baseline_alt

        fixed_result = self.fuel_model.fuel_for_distance(
            distance_nm=distance_nm,
            weight_initial_kg=initial_weight_kg,
            altitude_ft=opt_fixed_alt,
            mach=mach,
        )
        opt_fixed_fuel = fixed_result["total_fuel_kg"]

        # Step climb
        n_segments = max(1, int(distance_nm / step_interval_nm))
        actual_interval = distance_nm / n_segments

        current_weight = initial_weight_kg
        current_alt = baseline_alt
        total_step_fuel = 0.0
        step_plan = []
        step_count = 0

        for seg in range(n_segments):
            seg_start_nm = seg * actual_interval
            seg_distance = min(actual_interval, distance_nm - seg_start_nm)

            if seg_distance <= 0:
                break

            seg_opt = self.find_optimum_altitude(
                current_weight, mach, heading_deg, wind_profile
            )

            if seg_opt["status"] == "SUCCESS":
                new_alt = seg_opt["optimum"]["altitude_ft"]

                if new_alt > current_alt and step_count < _MAX_STEP_CLIMBS:
                    enough_distance = True

                    if step_plan:
                        last_step_nm = step_plan[-1]["distance_nm"]
                        if seg_start_nm - last_step_nm < _MIN_STEP_INTERVAL_NM:
                            enough_distance = False

                    remaining = distance_nm - seg_start_nm
                    if remaining < _MIN_REMAINING_NM:
                        enough_distance = False

                    if enough_distance:
                        step_result = self._evaluate_step_climb(
                            current_alt, new_alt, current_weight, mach, remaining
                        )

                        if step_result["net_saving_kg"] >= _MIN_NET_SAVING_KG:
                            step_plan.append({
                                "distance_nm": round(seg_start_nm),
                                "from_fl": f"FL{current_alt // 100}",
                                "to_fl": f"FL{new_alt // 100}",
                                "weight_kg": round(current_weight),
                                "climb_fuel_penalty_kg": round(step_result["climb_fuel_kg"]),
                                "expected_net_saving_kg": round(step_result["net_saving_kg"]),
                                "sar_improvement_pct": round(step_result["sar_improvement_pct"], 2),
                                "reason": (
                                    f"Ağırlık {current_weight:,.0f} kg. "
                                    f"SAR {step_result['sar_old']:.5f} → "
                                    f"{step_result['sar_new']:.5f} Nm/kg "
                                    f"(%{step_result['sar_improvement_pct']:.1f} iyileşme)."
                                ),
                            })

                            total_step_fuel += step_result["climb_fuel_kg"]
                            current_weight -= step_result["climb_fuel_kg"]
                            current_alt = new_alt
                            step_count += 1

            seg_result = self.fuel_model.fuel_for_distance(
                distance_nm=seg_distance,
                weight_initial_kg=current_weight,
                altitude_ft=current_alt,
                mach=mach,
                step_size_nm=5,
            )

            total_step_fuel += seg_result["total_fuel_kg"]
            current_weight -= seg_result["total_fuel_kg"]

        # Sonuçlar
        saving_vs_baseline = baseline_fuel - total_step_fuel
        saving_pct = (saving_vs_baseline / baseline_fuel * 100) if baseline_fuel > 0 else 0.0
        cost_saving = saving_vs_baseline * 0.85
        co2_saving = saving_vs_baseline * EI_CO2

        daily_flights = Assumptions.daily_frequency(distance_nm)
        op_days = OPERATIONAL_DAYS_PER_YEAR

        annual_fuel = saving_vs_baseline * daily_flights * op_days
        annual_cost = cost_saving * daily_flights * op_days
        annual_co2 = co2_saving * daily_flights * op_days

        return {
            "route": {
                "distance_nm": distance_nm,
                "heading_deg": heading_deg,
                "initial_weight_kg": initial_weight_kg,
                "mach": mach,
            },
            "scenarios": {
                "baseline_fl350": {
                    "description": "Sabit FL350 (mevcut operasyon)",
                    "altitude_ft": baseline_alt,
                    "total_fuel_kg": round(baseline_fuel),
                    "flight_time_hr": round(baseline_result["time_hours"], 2),
                },
                "optimum_fixed": {
                    "description": f"Sabit optimum FL{opt_fixed_alt // 100}",
                    "altitude_ft": opt_fixed_alt,
                    "total_fuel_kg": round(opt_fixed_fuel),
                    "saving_vs_baseline_kg": round(baseline_fuel - opt_fixed_fuel),
                },
                "step_climb": {
                    "description": "Step climb optimizasyonu",
                    "total_fuel_kg": round(total_step_fuel),
                    "step_plan": step_plan,
                    "num_steps": len(step_plan),
                },
            },
            "savings": {
                "per_flight": {
                    # ÖNEMLİ: round() tek başına 0.93 kg'ı 1 kg'a
                    # yuvarlıyordu → "1 kg tasarruf" gibi görünen
                    # anlamsız bir değer çıkıyordu. Eşik altı → 0.
                    "fuel_kg": (round(saving_vs_baseline)
                                if saving_vs_baseline >= _MIN_REPORTABLE_SAVING_KG
                                else 0),
                    # Aynı eşik maliyet ve CO₂'ye de uygulanır;
                    # aksi halde "0 kg tasarruf = $1.02" gibi
                    # kendi kendisiyle çelişen çıktı oluşur.
                    "fuel_pct": (round(max(0, saving_pct), 2)
                                 if saving_vs_baseline >= _MIN_REPORTABLE_SAVING_KG
                                 else 0.0),
                    "cost_usd": (round(max(0, cost_saving), 2)
                                 if saving_vs_baseline >= _MIN_REPORTABLE_SAVING_KG
                                 else 0.0),
                    "co2_kg": (round(max(0, co2_saving))
                               if saving_vs_baseline >= _MIN_REPORTABLE_SAVING_KG
                               else 0),
                },
                "annual_projection": {
                    "assumed_daily_flights": daily_flights,
                    "fuel_tonnes": round(max(0, annual_fuel) / 1000, 1),
                    "cost_usd": round(max(0, annual_cost)),
                    "co2_tonnes": round(max(0, annual_co2) / 1000, 1),
                },
                # SADECE BU SATIRI EKLE (negatifse uyarı, değilse hiçbir şey)
                **({"warning": f"Step climb önerisi {saving_vs_baseline:.0f} kg ek yakıt gerektiriyor. Sabit optimum irtifa tercih edilmeli."} if saving_vs_baseline < 0 else {}),
            },
            "dispatcher_instruction": self._generate_dispatcher_instruction(
                step_plan, distance_nm, mach, baseline_alt
            ),
        }
    

    # ──────────────────────────────────────────────────────
    # Dispatcher talimatı
    # ──────────────────────────────────────────────────────

    def _generate_dispatcher_instruction(
        self,
        step_plan: list[dict],
        distance_nm: float,
        mach: float,
        initial_alt: int,
    ) -> str:
        if not step_plan:
            return (
                f"ÖNERİLEN İRTİFA PROFİLİ ({distance_nm:.0f} Nm, M{mach}):\n"
                f"{'=' * 55}\n\n"
                f"• Cruise: FL{initial_alt//100}\n"
                f"• Step climb önerilmiyor (mevcut profil optimuma yakın).\n"
            )

        instruction = (
            f"ÖNERİLEN İRTİFA PROFİLİ ({distance_nm:.0f} Nm, M{mach}):\n"
            f"{'=' * 55}\n\n"
            f"• Kalkış sonrası ilk cruise: FL{initial_alt//100}\n\n"
        )

        for step in step_plan:
            instruction += (
                f"• {step['distance_nm']} Nm'de: "
                f"{step['from_fl']} → {step['to_fl']} step climb\n"
                f"  Sebep: {step['reason']}\n"
                f"  Tırmanma yakıtı: {step['climb_fuel_penalty_kg']} kg\n"
                f"  Beklenen net tasarruf: {step['expected_net_saving_kg']} kg\n\n"
            )

        total_saving = sum(s['expected_net_saving_kg'] for s in step_plan)
        instruction += (
            f"TOPLAM BEKLENEN TASARRUF: {total_saving} kg yakıt "
            f"(${total_saving * 0.85:.0f})\n\n"
            f"NOT:\n"
            f"• ATC izni gereklidir. İzin alınamazsa mevcut irtifada devam.\n"
            f"• Alternatif FL'ler kabul edilebilir.\n"
            f"• Turbülans durumunda güvenlik önceliklidir.\n"
        )

        return instruction

    def __repr__(self) -> str:
        return (
            f"AltitudeOptimizer('{self.ac_type}', "
            f"delta_isa={self.delta_isa}, "
            f"cd0={self.fuel_model.cd0_factor}, "
            f"sfc={self.fuel_model.sfc_factor})"
        )


def validate_altitude_optimizer() -> bool:
    print("\n" + "=" * 60)
    print("  ALTITUDE_OPTIMIZER.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors = []
    tests = 0

    def ok(name: str) -> None:
        nonlocal tests
        tests += 1
        print(f"  ✅ {name}")

    def fail(name: str, detail: str) -> None:
        nonlocal tests
        tests += 1
        errors.append(f"{name}: {detail}")
        print(f"  ❌ {name}: {detail}")

    def check_range(name: str, val: float, lo: float, hi: float) -> None:
        nonlocal tests
        tests += 1
        if lo <= val <= hi:
            print(f"  ✅ {name} = {val} [{lo}, {hi}]")
        else:
            errors.append(f"{name}: {val} dışı [{lo}, {hi}]")
            print(f"  ❌ {name}: {val} [{lo}, {hi}]")

    print("\n  [1] Optimizer Oluşturma")
    opt = AltitudeOptimizer('B738')
    ok(f"AltitudeOptimizer oluşturuldu: {repr(opt)}")

    print("\n  [2] Optimum İrtifa Bulma")
    result = opt.find_optimum_altitude(65000, 0.785, heading_deg=310)
    if result.get('status') == 'SUCCESS':
        ok(f"Optimum bulundu: {result['optimum']['flight_level']}")
        check_range("SAR", result['optimum']['air_sar'], 0.05, 0.25)
        check_range("FF", result['optimum']['fuel_flow_kg_hr'], 1500, 5000)
    else:
        fail("optimum", result.get('message', 'HATA'))

    print("\n  [3] Ağırlık Etkisi")
    heavy = opt.find_optimum_altitude(75000, 0.785, heading_deg=310)
    light = opt.find_optimum_altitude(55000, 0.785, heading_deg=310)
    if heavy.get('status') == 'SUCCESS' and light.get('status') == 'SUCCESS':
        if light['optimum']['altitude_ft'] >= heavy['optimum']['altitude_ft']:
            ok("Hafif uçak daha yüksek optimum FL")
        else:
            fail("ağırlık etkisi", "ters")

    print("\n  [4] Yön Kuralı (RVSM)")
    east = opt.find_optimum_altitude(65000, 0.785, heading_deg=100)
    west = opt.find_optimum_altitude(65000, 0.785, heading_deg=310)
    if east.get('status') == 'SUCCESS':
        if east['optimum']['altitude_ft'] in _EASTBOUND_LEVELS:
            ok(f"Eastbound FL doğru: {east['optimum']['flight_level']}")
        else:
            fail("eastbound", east['optimum']['flight_level'])
    if west.get('status') == 'SUCCESS':
        if west['optimum']['altitude_ft'] in _WESTBOUND_LEVELS:
            ok(f"Westbound FL doğru: {west['optimum']['flight_level']}")
        else:
            fail("westbound", west['optimum']['flight_level'])

    print("\n  [5] Rüzgar Etkisi")
    wind = {30000: 20, 32000: 15, 34000: 5, 36000: -10, 38000: -25, 40000: -15}
    result_wind = opt.find_optimum_altitude(65000, 0.785, heading_deg=310, wind_at_levels=wind)
    if result_wind.get('status') == 'SUCCESS':
        if result_wind.get('optimization_metric') == 'ground_sar':
            ok("Rüzgar varken ground_sar optimize edildi")
        else:
            fail("rüzgar metriği", result_wind.get('optimization_metric'))

    print("\n  [6] Çok Ağır Uçak")
    very_heavy = opt.find_optimum_altitude(78000, 0.785, heading_deg=310)
    if very_heavy.get('status') in ('SUCCESS', 'ERROR'):
        ok(f"Çok ağır uçak işlendi: {very_heavy.get('status')}")
    else:
        fail("çok ağır", "beklenmeyen status")

    print("\n  [7] Tam Uçuş Optimizasyonu")
    flight = opt.optimize_full_flight(
        distance_nm=1560,
        initial_weight_kg=75000,
        payload_kg=15000,
        mach=0.785,
        heading_deg=310,
    )

    if flight['scenarios']['baseline_fl350']['total_fuel_kg'] > 0:
        ok(f"Baseline yakıt: {flight['scenarios']['baseline_fl350']['total_fuel_kg']} kg")
    else:
        fail("baseline", "yakıt sıfır")

    n_steps = flight['scenarios']['step_climb']['num_steps']
    if n_steps <= _MAX_STEP_CLIMBS:
        ok(f"Step sayısı: {n_steps}")
    else:
        fail("step sayısı", str(n_steps))

    if flight['savings']['per_flight']['fuel_kg'] >= 0:
        ok(f"Tasarruf: {flight['savings']['per_flight']['fuel_kg']} kg")
    else:
        fail("tasarruf", "negatif")

    instruction = flight.get('dispatcher_instruction', '')
    if len(instruction) > 50:
        ok("Dispatcher talimatı üretildi")
    else:
        fail("dispatcher", "çok kısa")

    print(f"\n  {'─' * 40}")
    print(f"  {tests} test, {tests-len(errors)} başarılı, {len(errors)} başarısız")

    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        return False

    print("  ✅ TÜM TESTLER BAŞARILI")
    return True


if __name__ == "__main__":
    validate_altitude_optimizer()