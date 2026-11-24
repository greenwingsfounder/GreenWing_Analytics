"""
GreenWing Analytics — Profesyonel Demo Veri Üreticisi
═════════════════════════════════════════════════════

Bu script SunExpress gerçek rotaları üzerinde
fizik bazlı simülasyon yaparak profesyonel
bir demo analiz üretir.

OPERASYONEL VARYANS MODELİ:
────────────────────────────
    Gerçek operasyonda her uçuş tam optimum FL'de
    uçamaz. Stokastik operasyonel modelleme:

    ATC kısıtı          → %55 uçuşta FL sapması
    Traffic separation  → ortalama 1,000-2,500 ft aşağı
    Slot yönetimi       → cruise profile değişimi
    Company SOP         → standart FL tercihi

    Kaynak: BADA methodology, Eurocontrol PRR,
            ICAO Doc 9613, Boeing FPM

STEP CLIMB MODELİ:
───────────────────
    Step climb tüm rotalarda değil,
    mesafe ve ağırlık profiline göre:
    < 700 Nm  → step climb genellikle değmez
    700-1000  → %30-40 uçuşta değer
    > 1000 Nm → %60-80 uçuşta değer

ÇALIŞTIRMA:
───────────
    python scripts/04_generate_professional_demo.py
    python scripts/03_generate_outputs.py
"""

import sys
import os
import json
import numpy as np
from datetime import datetime, timedelta
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.fuel_model import FuelModel
from src.models.emission_model import EmissionCalculator
from src.optimization.altitude_optimizer import AltitudeOptimizer
from src.optimization.cost_index_optimizer import CostIndexOptimizer
from src.optimization.tankering_optimizer import TankeringOptimizer
from src.data_collection.airport_database import AirportDatabase
from src.utils import calculate_initial_heading, get_seasonal_wind_estimate
from config.assumptions import Assumptions
from config.settings import REPORTS_OPTIMIZATIONS, EI_CO2


# ═══════════════════════════════════════════════════════════
# SunExpress GERÇEK ROTA VERİSİ
# ═══════════════════════════════════════════════════════════

SUNEXPRESS_ROUTES = [
    {
        "origin": "LTAI", "destination": "EDDF",
        "origin_name": "Antalya", "dest_name": "Frankfurt",
        "weekly_freq": 14, "load_factor": 0.92,
        "notes": "Ana Frankfurt rotası — en yoğun"
    },
    {
        "origin": "LTAI", "destination": "EDDUS",
        "origin_name": "Antalya", "dest_name": "Düsseldorf",
        "weekly_freq": 10, "load_factor": 0.91,
        "notes": "NRW bölgesi charter rotası"
    },
    {
        "origin": "LTAI", "destination": "EDDM",
        "origin_name": "Antalya", "dest_name": "Münih",
        "weekly_freq": 7, "load_factor": 0.90,
        "notes": "Güney Almanya rotası"
    },
    {
        "origin": "LTAI", "destination": "EDDB",
        "origin_name": "Antalya", "dest_name": "Berlin",
        "weekly_freq": 7, "load_factor": 0.89,
        "notes": "Kuzey Almanya rotası"
    },
    {
        "origin": "LTBJ", "destination": "EDDF",
        "origin_name": "İzmir", "dest_name": "Frankfurt",
        "weekly_freq": 7, "load_factor": 0.88,
        "notes": "İzmir-Frankfurt scheduled"
    },
    {
        "origin": "LTBJ", "destination": "EDDUS",
        "origin_name": "İzmir", "dest_name": "Düsseldorf",
        "weekly_freq": 5, "load_factor": 0.87,
        "notes": "İzmir-Düsseldorf charter"
    },
    {
        "origin": "LTFM", "destination": "EDDF",
        "origin_name": "İstanbul", "dest_name": "Frankfurt",
        "weekly_freq": 14, "load_factor": 0.85,
        "notes": "İstanbul-Frankfurt scheduled"
    },
    {
        "origin": "LTFM", "destination": "EDDM",
        "origin_name": "İstanbul", "dest_name": "Münih",
        "weekly_freq": 7, "load_factor": 0.84,
        "notes": "İstanbul-Münih scheduled"
    },
]

EXTRA_AIRPORTS = {
    "EDDUS": {
        "lat": 51.2895, "lon": 6.7668,
        "name": "Düsseldorf", "iata": "DUS"
    },
    "EDDB": {
        "lat": 52.3667, "lon": 13.5033,
        "name": "Berlin Brandenburg", "iata": "BER"
    },
}

# BÜTÜNLÜK: Ayrı bir yakıt fiyatı tablosu TUTMA. Tek kaynak: Assumptions.
# (Önceden burada kopya bir tablo vardı; config ile çelişme riski taşıyordu,
#  ayrıca "EDDUS" gibi geçersiz bir ICAO kodu içeriyordu.)
def _price(icao: str) -> float:
    return Assumptions.fuel_price(icao)

AIRCRAFT_TYPE   = "B738"
CRUISE_MACH     = 0.785
PAYLOAD_PER_PAX = 100
SEATS_B738      = 189
SIMULATION_DAYS = 30

ANNUAL_SCALE_FACTOR = 345 / SIMULATION_DAYS   # 11.5
REALIZATION_FACTOR  = 0.65


# ═══════════════════════════════════════════════════════════
# OPERASYONEL VARYANS PARAMETRELERİ
# ═══════════════════════════════════════════════════════════
# Kaynak: Eurocontrol PRR 2023, ICAO Doc 9613,
#         Boeing FPM, BADA methodology

# ATC kısıtı nedeniyle FL sapması olasılığı
_ATC_CONSTRAINT_PROBABILITY = 0.55   # %55 uçuşta kısıt

# FL sapması dağılımı (ft) — normal dağılım
_FL_DEVIATION_MEAN_FT  = 1200   # ortalama 1200 ft aşağı
_FL_DEVIATION_STD_FT   = 600    # standart sapma 600 ft

# Step climb eşikleri (mesafeye göre)
_STEP_CLIMB_PROB_SHORT  = 0.15   # < 700 Nm → %15 ihtimal
_STEP_CLIMB_PROB_MEDIUM = 0.35   # 700-1000 Nm → %35 ihtimal
_STEP_CLIMB_PROB_LONG   = 0.70   # > 1000 Nm → %70 ihtimal


# ═══════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════

def get_route_distance(
    origin: str,
    destination: str,
    db: AirportDatabase,
) -> float:
    origin_data = db.get(origin) or EXTRA_AIRPORTS.get(origin)
    dest_data   = db.get(destination) or EXTRA_AIRPORTS.get(destination)
    if not origin_data or not dest_data:
        return 0.0
    return db._haversine(
        origin_data['lat'], origin_data['lon'],
        dest_data['lat'],   dest_data['lon'],
    )


def get_heading(
    origin: str,
    destination: str,
    db: AirportDatabase,
) -> float:
    origin_data = db.get(origin) or EXTRA_AIRPORTS.get(origin)
    dest_data   = db.get(destination) or EXTRA_AIRPORTS.get(destination)
    if not origin_data or not dest_data:
        return 0.0
    return calculate_initial_heading(
        origin_data['lat'], origin_data['lon'],
        dest_data['lat'],   dest_data['lon'],
    )


def simulate_atc_altitude_deviation() -> int:
    """
    ATC kısıtı nedeniyle FL sapmasını simüle et.

    Stokastik model:
        %55 ihtimalle kısıt oluşur.
        Kısıt oluşursa: normal dağılım (μ=1200, σ=600 ft)
        Minimum 500, maksimum 3000 ft sapma.

    Kaynak:
        Eurocontrol PRR 2023 — "Vertical flight efficiency"
        ICAO Doc 9750 — Global Air Navigation Plan
    """
    if random.random() > _ATC_CONSTRAINT_PROBABILITY:
        return 0  # Kısıt yok, tam optimum FL

    deviation = int(np.random.normal(
        _FL_DEVIATION_MEAN_FT,
        _FL_DEVIATION_STD_FT
    ))
    # 500-3000 ft arasına sınırla
    deviation = max(500, min(3000, abs(deviation)))

    # 1000'in katına yuvarla (gerçek FL seçimi)
    deviation = round(deviation / 1000) * 1000
    deviation = max(1000, deviation)  # Minimum 1000 ft

    return deviation


def should_apply_step_climb(distance_nm: float) -> bool:
    """
    Bu rotada step climb uygulanmalı mı?

    Mesafe bazlı stokastik karar:
        < 700 Nm  → %15 ihtimal (kısa rota — değmez)
        700-1000  → %35 ihtimal (orta rota — bazen değer)
        > 1000 Nm → %70 ihtimal (uzun rota — çoğunlukla değer)

    Kaynak:
        ICAO Doc 9613 — PBN Manual
        BADA 4 — Step climb methodology
    """
    if distance_nm < 700:
        prob = _STEP_CLIMB_PROB_SHORT
    elif distance_nm < 1000:
        prob = _STEP_CLIMB_PROB_MEDIUM
    else:
        prob = _STEP_CLIMB_PROB_LONG

    return random.random() < prob


# ═══════════════════════════════════════════════════════════
# ANA SİMÜLASYON FONKSİYONU
# ═══════════════════════════════════════════════════════════

def simulate_single_flight(
    route: dict,
    distance_nm: float,
    heading: float,
    flight_number: str,
    flight_date: str,
    fm: FuelModel,
    em: EmissionCalculator,
    alt_opt: AltitudeOptimizer,
    ci_opt: CostIndexOptimizer,
    tank_opt: TankeringOptimizer,
) -> dict:
    """
    Tek bir SunExpress uçuşunu fizik modeliyle simüle et.

    Operasyonel gerçekçilik için:
        - ATC kısıtı nedeniyle FL sapması modeli
        - Mesafeye bağlı step climb olasılık modeli
        - Load factor ve yakıt varyasyonu
    """
    origin      = route['origin']
    destination = route['destination']

    # ─── 1. AĞIRLIK VE PAYLOAD ────────────────────────────
    load_factor = route['load_factor'] * random.uniform(0.95, 1.05)
    load_factor = min(max(load_factor, 0.75), 0.98)
    pax         = int(SEATS_B738 * load_factor)
    payload_kg  = pax * PAYLOAD_PER_PAX

    oew  = Assumptions.aircraft_oew(AIRCRAFT_TYPE)
    mtow = Assumptions.aircraft_mtow(AIRCRAFT_TYPE)

    # Cruise irtifası (mesafeye göre)
    if distance_nm < 500:
        base_cruise_alt = 33000
    elif distance_nm < 800:
        base_cruise_alt = 35000
    else:
        base_cruise_alt = 37000

    # ─── 2. ATC KISITI — FL SAPMASI ──────────────────────
    # Stokastik operasyonel model
    # %55 uçuşta ATC kısıtı → optimumdan sapma
    altitude_deviation_ft = simulate_atc_altitude_deviation()

    # Gerçekte uçulan irtifa
    actual_cruise_alt = base_cruise_alt - altitude_deviation_ft

    # SAR kaybı hesabı
    # (optimumdan sapma → daha düşük SAR → daha fazla yakıt)
    sar_loss = 0.0
    if altitude_deviation_ft > 0:
        try:
            rough_fuel_est = distance_nm * 8.5
            rough_tow      = min(oew + payload_kg + rough_fuel_est, mtow)
            mid_w_rough    = rough_tow * 0.92

            sar_actual  = fm.specific_air_range(
                mid_w_rough, actual_cruise_alt, CRUISE_MACH
            )
            sar_optimum = fm.specific_air_range(
                mid_w_rough, base_cruise_alt, CRUISE_MACH
            )

            if sar_optimum > 0 and sar_actual > 0:
                sar_loss = max(0, (sar_optimum - sar_actual) / sar_optimum * 100)
        except Exception:
            # Kaba tahmin: her 1000 ft sapma ~%0.5 SAR kaybı
            sar_loss = (altitude_deviation_ft / 1000) * 0.5

    # ─── 3. YAKIT (7 FAZ) ─────────────────────────────────
    # BÜTÜNLÜK: kaba TOW tahmini deterministik (gürültü kaldırıldı).
    rough_fuel     = distance_nm * 8.5
    rough_fuel     = min(rough_fuel, Assumptions.aircraft_max_fuel(AIRCRAFT_TYPE))
    takeoff_weight = min(oew + payload_kg + rough_fuel, mtow)

    try:
        fuel_result = fm.estimate_total_flight_fuel(
            distance_nm       = distance_nm,
            weight_initial_kg = takeoff_weight,
            altitude_ft       = actual_cruise_alt,  # Gerçek irtifa
            mach              = CRUISE_MACH,
            taxi_out_min      = random.uniform(12, 20),
            taxi_in_min       = random.uniform(8, 15),
            climb_min         = max(15, distance_nm / 60),
            descent_min       = max(15, distance_nm / 70),
            approach_min      = 5,
        )
        # BÜTÜNLÜK: ±%3 rastgele gürültü KALDIRILDI. Fizik modeli ne dediyse o.
        total_fuel     = fuel_result['total_fuel_kg']
        flight_time_hr = fuel_result['cruise_time_hr'] + 0.75
    except Exception:
        total_fuel     = rough_fuel
        flight_time_hr = distance_nm / 430 + 0.75

    total_fuel     = round(max(total_fuel, 3000))
    takeoff_weight = min(oew + payload_kg + total_fuel, mtow)
    mid_weight     = takeoff_weight - total_fuel * 0.5

    # ─── 4. İRTİFA OPTİMİZASYONU ─────────────────────────
    opt_fl        = f"FL{base_cruise_alt // 100}"
    buffet_margin = 15.0
    alt_saving    = 0.0

    try:
        wind_est       = get_seasonal_wind_estimate(heading)
        opt_alt_result = alt_opt.find_optimum_altitude(
            weight_kg      = mid_weight,
            mach           = CRUISE_MACH,
            heading_deg    = heading,
            wind_at_levels = wind_est,
        )

        if opt_alt_result.get('status') == 'SUCCESS':
            opt_data      = opt_alt_result['optimum']
            opt_fl        = opt_data['flight_level']
            buffet_margin = float(opt_data['buffet_margin_pct'])
            opt_alt_ft    = int(opt_fl.replace('FL', '')) * 100

            # Tasarruf = gerçek irtifadan optimuma geçiş
            sar_actual_fl  = fm.specific_air_range(mid_weight, actual_cruise_alt, CRUISE_MACH)
            sar_optimum_fl = fm.specific_air_range(mid_weight, opt_alt_ft, CRUISE_MACH)

            if sar_optimum_fl > 0 and sar_actual_fl > 0:
                fuel_at_actual  = distance_nm / sar_actual_fl
                fuel_at_optimum = distance_nm / sar_optimum_fl
                alt_saving      = max(0, fuel_at_actual - fuel_at_optimum)

    except Exception:
        # Fizik bazlı varsayılan
        alt_saving = total_fuel * (sar_loss / 100) if sar_loss > 0 else 0

    # ─── 5. STEP CLIMB ────────────────────────────────────
    # Mesafeye bağlı stokastik model
    step_saving = 0.0
    step_plan   = []

    apply_step = should_apply_step_climb(distance_nm)

    if apply_step:
        try:
            step_result = alt_opt.optimize_full_flight(
                distance_nm       = distance_nm,
                initial_weight_kg = takeoff_weight,
                payload_kg        = payload_kg,
                mach              = CRUISE_MACH,
                heading_deg       = heading,
            )
            step_saving = float(
                step_result.get('savings', {})
                           .get('per_flight', {})
                           .get('fuel_kg', 0)
            )
            step_plan = [
                {
                    'distance'  : s['distance_nm'],
                    'from'      : s['from_fl'],
                    'to'        : s['to_fl'],
                    'net_saving': s['expected_net_saving_kg'],
                }
                for s in step_result.get('scenarios', {})
                                   .get('step_climb', {})
                                   .get('step_plan', [])
            ]
        except Exception:
            # BÜTÜNLÜK: Başarısız hesapta TAHMİN ÜRETME. 0 kabul et.
            # (Önceden random.uniform ile uyduruluyordu — kaldırıldı.)
            step_saving = 0.0

    # ─── 6. COST INDEX ────────────────────────────────────
    origin_price = _price(origin)
    time_cost    = Assumptions.time_cost('SXS')
    opt_ci       = 20
    opt_mach     = CRUISE_MACH

    try:
        ci_result = ci_opt.optimize_cost_index(
            distance_nm           = distance_nm,
            altitude_ft           = actual_cruise_alt,
            weight_kg             = mid_weight,
            fuel_price_usd_per_kg = origin_price,
            time_cost_usd_per_hr  = time_cost,
        )
        if ci_result.get('status') == 'SUCCESS':
            opt_ci   = int(ci_result['optimum']['cost_index'])
            opt_mach = float(ci_result['optimum']['mach'])
    except Exception:
        pass

    # ─── 7. TANKERING ─────────────────────────────────────
    dest_price  = _price(destination)
    tank_amount = 0
    tank_saving = 0.0

    try:
        tank_result = tank_opt.optimize_tankering(
            distance_nm                  = distance_nm,
            altitude_ft                  = actual_cruise_alt,
            mach                         = CRUISE_MACH,
            weight_without_extra_fuel_kg = takeoff_weight,
            fuel_price_origin_usd_per_kg = origin_price,
            fuel_price_dest_usd_per_kg   = dest_price,
            max_extra_fuel_kg            = 2000,
        )
        tank_amount = int(tank_result.get('optimal_extra_fuel_kg', 0))
        tank_saving = float(tank_result.get('net_saving_usd', 0))
    except Exception:
        # BÜTÜNLÜK: tankering hesabı başarısızsa uydurma. 0.
        tank_amount = 0
        tank_saving = 0.0

    # ─── 8. EMİSYON ──────────────────────────────────────
    try:
        emissions  = em.calculate_flight_emissions(
            fuel_burn_kg       = total_fuel,
            distance_nm        = distance_nm,
            aircraft_type      = AIRCRAFT_TYPE,
            cruise_altitude_ft = actual_cruise_alt,
            cruise_mach        = CRUISE_MACH,
        )
        co2        = float(emissions['emissions']['CO2_kg'])
        co2_pax_km = float(emissions['metrics']['co2_per_pax_km_g'])
    except Exception:
        co2        = total_fuel * EI_CO2
        dist_km    = distance_nm * 1.852
        co2_pax_km = (co2 * 1000) / (pax * dist_km) if pax > 0 and dist_km > 0 else 0

    # ─── 9. TASARRUF ──────────────────────────────────────
    # BÜTÜNLÜK KURALI: Tasarruf YALNIZCA fizik modelinden gelir.
    # Fizik "0" diyorsa 0'dır. Uydurma/eşik-minimum YOKTUR.
    #
    # Önceden burada:
    #   min_saving = total_fuel * 0.012
    #   if fuel_optimization < min_saving:
    #       fuel_optimization = total_fuel * random.uniform(0.015, 0.025)  # UYDURMA
    # vardı. Bu, 231 uçuşun 155'inde ($17.9t) hayali tasarruf üretiyordu.
    # KALDIRILDI.
    fuel_optimization = max(0.0, max(alt_saving, step_saving))

    per_flight_cost_saving = fuel_optimization * origin_price + tank_saving

    return {
        'filename'               : f"DEMO_SXS_{flight_number}_{flight_date}.csv",
        'callsign'               : f"SXS{flight_number}",
        'airline_code'           : 'SXS',
        'aircraft_type'          : AIRCRAFT_TYPE,
        'origin_airport'         : origin,
        'dest_airport'           : destination,
        'route_validity'         : 'HIGH',
        'route_resolution_source': 'demo_simulation',
        'route_warnings'         : [],
        'collection_method'      : 'demo_simulation',
        'distance_nm'            : round(distance_nm),
        'estimated_fuel_kg'      : total_fuel,
        'cruise_altitude_ft'     : actual_cruise_alt,
        'route_efficiency_pct'   : None,  # BÜTÜNLÜK: hesaplanmadı (büyük daire=gerçek rota). Uydurma yok.
        'heading_deg'            : round(heading),
        'flight_time_min'        : round(flight_time_hr * 60),
        'passengers'             : pax,
        'load_factor_pct'        : round(load_factor * 100, 1),
        'payload_kg'             : payload_kg,
        'optimum_fl'             : opt_fl,
        'actual_cruise_alt_ft'   : actual_cruise_alt,
        'altitude_deviation_ft'  : altitude_deviation_ft,
        'buffet_margin_pct'      : round(buffet_margin, 1),
        'sar_loss_pct'           : round(sar_loss, 2),
        'altitude_saving_kg'     : round(alt_saving),
        'step_climb_applied'     : apply_step,
        'step_climb_saving_kg'   : round(step_saving),
        'step_plan'              : step_plan,
        'optimum_ci'             : opt_ci,
        'optimum_mach'           : round(opt_mach, 3),
        'tankering_amount_kg'    : tank_amount,
        'tankering_saving_usd'   : round(tank_saving, 2),
        'origin_fuel_price'      : origin_price,
        'dest_fuel_price'        : dest_price,
        'fuel_optimization_kg'   : round(fuel_optimization),
        'total_cost_saving_usd'  : round(per_flight_cost_saving, 2),
        'co2_kg'                 : round(co2),
        'co2_per_pax_km_g'       : round(co2_pax_km, 1),
        'data_quality': {
            'is_partial'   : False,
            'quality_grade': 'SIMULATED',
            'warnings'     : [
                'Physics-based simulation — ICAO ISA + B738 TCDS parameters',
                'Operational variance model — stochastic ATC constraint simulation',
                'Not real QAR/FDR data — demonstrative analysis',
            ],
            'fuel_per_nm'  : round(total_fuel / max(distance_nm, 1), 2),
        },
        'is_partial_flight'      : False,
        'fuel_per_nm'            : round(total_fuel / max(distance_nm, 1), 2),
        'benchmark_status'       : '✅ Physics-based ICAO model + stochastic operational variance',
        'timestamp'              : datetime.now().isoformat(),
        'flight_date'            : flight_date,
        'simulation_note': (
            'GreenWing Analytics fizik modeli + stokastik operasyonel varyans modeli '
            'ile üretilmiştir. ATC kısıtı, traffic separation ve slot yönetimi '
            'nedeniyle FL sapması modellenmiştir. '
            'Kaynak: ICAO ISA, B738 TCDS, BADA methodology, Eurocontrol PRR 2023.'
        ),
    }


# ═══════════════════════════════════════════════════════════
# ANA FONKSİYON
# ═══════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 65)
    print(f"  GreenWing Analytics — SunExpress Demo Simülasyonu")
    print(f"  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)

    print(f"""
  DEMO PARAMETRELERİ:
  ─────────────────────────────────────────────────────────
  Havayolu          : SunExpress (SXS)
  Uçak tipi         : Boeing 737-800 (B738)
  Rota sayısı       : {len(SUNEXPRESS_ROUTES)} rota
  Simülasyon süresi : {SIMULATION_DAYS} gün
  Yıllık ölçek      : ×{ANNUAL_SCALE_FACTOR} (345 op.gün / {SIMULATION_DAYS})
  Gerçekleşme faktörü: %{int(REALIZATION_FACTOR*100)}
  Fizik modeli      : ICAO ISA + Drag Polar + BFFM2
  Operasyonel model : Stokastik ATC kısıtı + Step climb olasılığı
  Emisyon standardı : CORSIA SARP Annex 16 Vol IV
  ─────────────────────────────────────────────────────────
    """)

    random.seed(42)
    np.random.seed(42)

    fm       = FuelModel(AIRCRAFT_TYPE)
    em       = EmissionCalculator()
    alt_opt  = AltitudeOptimizer(AIRCRAFT_TYPE)
    ci_opt   = CostIndexOptimizer(AIRCRAFT_TYPE)
    tank_opt = TankeringOptimizer(AIRCRAFT_TYPE)
    db       = AirportDatabase()

    all_results = []

    for route in SUNEXPRESS_ROUTES:
        origin      = route['origin']
        destination = route['destination']

        distance_nm = get_route_distance(origin, destination, db)
        if distance_nm < 50:
            print(f"  ⚠ {origin}→{destination}: Koordinat bulunamadı")
            continue

        heading    = get_heading(origin, destination, db)
        daily_freq = route['weekly_freq'] / 7

        print(f"\n  {'─'*60}")
        print(
            f"  ✈ {origin}→{destination} "
            f"({route['origin_name']}→{route['dest_name']})"
        )
        print(
            f"     Mesafe: {distance_nm:.0f} Nm | "
            f"Heading: {heading:.0f}° | "
            f"Frekans: {route['weekly_freq']}x/hafta"
        )
        print(f"  {'─'*60}")

        flight_count = 0
        start_date   = datetime(2025, 3, 1)

        for day in range(SIMULATION_DAYS):
            flight_date = (start_date + timedelta(days=day)).strftime('%Y-%m-%d')

            if random.random() > daily_freq:
                continue

            flight_num   = f"{random.randint(1000, 9999)}"
            flight_count += 1

            try:
                result = simulate_single_flight(
                    route         = route,
                    distance_nm   = distance_nm,
                    heading       = heading,
                    flight_number = flight_num,
                    flight_date   = flight_date,
                    fm            = fm,
                    em            = em,
                    alt_opt       = alt_opt,
                    ci_opt        = ci_opt,
                    tank_opt      = tank_opt,
                )
                all_results.append(result)
            except Exception as e:
                print(f"    ⚠ Simülasyon hatası: {e}")
                continue

        print(f"  ✅ {origin}→{destination}: {flight_count} uçuş simüle edildi")

    # ─── Yıllık Projeksiyon (Merkezi Hesap) ───────────────
    n                      = len(all_results)
    total_fuel_saving_kg   = sum(r['fuel_optimization_kg'] for r in all_results)
    total_cost_saving_30d  = sum(r['total_cost_saving_usd'] for r in all_results)
    step_climb_count       = sum(1 for r in all_results if r.get('step_climb_applied', False))

    annual_fuel_saving_kg  = total_fuel_saving_kg  * ANNUAL_SCALE_FACTOR
    annual_cost_saving_usd = total_cost_saving_30d * ANNUAL_SCALE_FACTOR * REALIZATION_FACTOR
    annual_co2_saving_kg   = annual_fuel_saving_kg * EI_CO2

    for r in all_results:
        r['annual_raw_usd']       = round(r['total_cost_saving_usd'] * ANNUAL_SCALE_FACTOR)
        r['annual_realistic_usd'] = round(r['total_cost_saving_usd'] * ANNUAL_SCALE_FACTOR * REALIZATION_FACTOR)
        r['realization_factor']   = REALIZATION_FACTOR

    # ─── Sonuçlar ─────────────────────────────────────────
    print(f"\n{'═'*65}")
    print(f"  SONUÇLAR")
    print(f"{'═'*65}")

    if not all_results:
        print("  ❌ Hiç sonuç üretilemedi!")
        return

    total_flights = len(all_results)
    total_fuel    = sum(r['estimated_fuel_kg'] for r in all_results)
    total_co2     = sum(r['co2_kg'] for r in all_results)
    avg_fuel      = total_fuel / total_flights

    # Operasyonel varyans istatistikleri
    deviations    = [r['altitude_deviation_ft'] for r in all_results]
    avg_deviation = float(np.mean(deviations))
    flights_with_deviation = sum(1 for d in deviations if d > 0)

    print(f"\n  {'Rota':<18} {'Uçuş':>5} {'Ort.Yakıt':>10} "
          f"{'kg/Nm':>7} {'FL Sapma':>9} {'Step':>5}")
    print(f"  {'─'*62}")

    routes_summary = {}
    for r in all_results:
        key = f"{r['origin_airport']}→{r['dest_airport']}"
        if key not in routes_summary:
            routes_summary[key] = {
                'count': 0, 'fuel': 0, 'dist': 0,
                'deviation': 0, 'step': 0,
            }
        routes_summary[key]['count']    += 1
        routes_summary[key]['fuel']     += r['estimated_fuel_kg']
        routes_summary[key]['dist']     += r['distance_nm']
        routes_summary[key]['deviation'] += r['altitude_deviation_ft']
        routes_summary[key]['step']     += 1 if r.get('step_climb_applied') else 0

    for rk, data in routes_summary.items():
        n_r      = data['count']
        avg_f    = data['fuel'] / n_r
        avg_d    = data['dist'] / n_r
        fnm      = avg_f / avg_d if avg_d > 0 else 0
        avg_dev  = data['deviation'] / n_r
        step_pct = data['step'] / n_r * 100
        print(
            f"  {rk:<18} {n_r:>5} {avg_f:>9,.0f}kg "
            f"{fnm:>6.2f} {avg_dev:>7.0f}ft {step_pct:>4.0f}%"
        )

    print(f"\n  FILO ÖZET (30 gün):")
    print(f"  {'─'*55}")
    print(f"  Toplam uçuş                  : {total_flights}")
    print(f"  Toplam yakıt                 : {total_fuel/1000:.1f} ton")
    print(f"  Toplam CO₂                   : {total_co2/1000:.1f} ton")
    print(f"  Ort. yakıt/uçuş              : {avg_fuel:,.0f} kg")
    print(f"  {'─'*55}")
    print(f"  OPERASYONEL VARYANS:")
    print(f"  ATC kısıtlı uçuş oranı       : %{flights_with_deviation/total_flights*100:.0f}")
    print(f"  Ort. FL sapması              : {avg_deviation:.0f} ft")
    print(f"  Step climb uygulanan         : {step_climb_count}/{total_flights} (%{step_climb_count/total_flights*100:.0f})")
    print(f"  {'─'*55}")
    print(f"  YILLIK PROJEKSİYON:")
    print(f"  Yakıt tasarrufu              : {annual_fuel_saving_kg/1000:.1f} ton/yıl")
    print(f"  CO₂ azaltma                  : {annual_co2_saving_kg/1000:.1f} ton/yıl")
    print(f"  Maliyet tasarrufu            : ${annual_cost_saving_usd:,.0f}/yıl")
    print(f"  (8 rota, %{int(REALIZATION_FACTOR*100)} gerçekleşme)")

    # Gerçekçilik kontrolü
    print(f"\n  GERÇEKÇİLİK KONTROL:")
    # B738 blok yakıtı 6.0-7.5 kg/nm'dir (blok hız ~400-420 kt, ~2,550 kg/saat).
    avg_fpm = float(np.mean([r['fuel_per_nm'] for r in all_results]))
    s1 = '✅' if 5.8 <= avg_fpm <= 8.0 else '⚠'
    print(f"  Ort. yakıt/Nm                : {avg_fpm:.2f} kg/Nm {s1}")

    # BÜTÜNLÜK: Dar gövde (B738, 189 koltuk, %90+ doluluk) gerçek aralığı
    # 60-90 g/pax/km'dir (IATA/Atmosfair). Önceki 70-120 eşiği dar gövde için
    # yanlıştı ve doğru sonucu '⚠' diye işaretliyordu.
    avg_co2p = float(np.mean([r['co2_per_pax_km_g'] for r in all_results]))
    s2 = '✅' if 55 <= avg_co2p <= 100 else '⚠'
    print(f"  CO₂/pax/km                   : {avg_co2p:.1f} g {s2}")

    save_pcts = [
        r['fuel_optimization_kg'] / r['estimated_fuel_kg'] * 100
        for r in all_results if r['estimated_fuel_kg'] > 0
    ]
    avg_sp = float(np.mean(save_pcts))
    s3 = '✅' if 0.5 <= avg_sp <= 6.0 else '⚠'
    print(f"  Tasarruf oranı               : %{avg_sp:.1f} {s3}")

    s4 = '✅' if 100_000 <= annual_cost_saving_usd <= 2_000_000 else '⚠'
    print(f"  Yıllık toplam tasarruf       : ${annual_cost_saving_usd:,.0f} {s4}")

    s5 = '✅' if 200 <= avg_deviation <= 2000 else '⚠'
    print(f"  Ort. ATC FL sapması          : {avg_deviation:.0f} ft {s5}")

    s6 = '✅' if 30 <= step_climb_count/total_flights*100 <= 75 else '⚠'
    print(f"  Step climb oranı             : %{step_climb_count/total_flights*100:.0f} {s6}")

    # JSON kaydet
    os.makedirs(REPORTS_OPTIMIZATIONS, exist_ok=True)
    # DENETİM #95: bu şema 02'ninkinden FARKLI (origin/destination YOK,
    # flight_date farklı anlamda). Aynı dosyaya yazınca 02'nin çıktısını
    # EZİYORDU ve kalibrasyon zinciri 13/13'ten 5/30'a düşüyordu.
    # Ayrı dosya + aynı alan adları.
    for _r in all_results:
        _r.setdefault('origin', _r.get('origin_airport'))
        _r.setdefault('destination', _r.get('dest_airport'))
    results_path = os.path.join(REPORTS_OPTIMIZATIONS,
                                "demo_batch_results.json")

    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, default=str, ensure_ascii=False)

    print(f"\n  💾 Kaydedildi: {results_path}")
    print(f"  Toplam kayıt : {len(all_results)} uçuş")

    print(f"""
  ✅ SONRAKI ADIM:
  ────────────────
  python scripts/03_generate_outputs.py
    """)


if __name__ == "__main__":
    main()
