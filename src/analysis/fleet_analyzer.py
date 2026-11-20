# NOT: Bu dosya Sorun 3 düzeltmesiyle son halini alıyor.
# Önceki tam versiyon (fleet_analyzer — Sorun 1+2 çözümüyle) baz alınmış,
# yalnızca annualized hesabı ve savings_potential bloğu güncellenmiştir.

"""
GreenWing Analytics — Filo Analizi ve Benchmark
════════════════════════════════════════════════

Bu dosya birden fazla uçuşu birleştirip "büyük resmi" gösterir.

TEK UÇUŞ: "Bu uçuş nasıldı?"
FİLO: "Tüm uçuşlarım nasıl? Hangi rota problem?
       Sektöre göre neredeyim? Yılda ne kadar tasarruf mümkün?"

ÇIKTILAR:
─────────
    1. Filo özeti (toplam yakıt, CO2, verimlilik skoru)
    2. Rota sıralaması (en verimsiz → en verimli)
    3. Benchmark karşılaştırması (sektör ortalaması ve en iyi)
    4. Tutarlılık analizi (aynı rotadaki yakıt farkları)
    5. İrtifa performansı (SAR kaybı, step climb oranı)
    6. Tasarruf potansiyeli (yıllık projeksiyon)
    7. CORSIA yıllık rapor
    8. Veri kalitesi izleme (partial flight tespiti)

TASARRUF HESABI MANTIĞI:
─────────────────────────
    02 scripti her uçuş için şunları hesaplar:
        fuel_optimization_kg  → uçuş başına yakıt tasarrufu
        total_cost_saving_usd → uçuş başına maliyet tasarrufu
        annual_realistic_usd  → o rotanın yıllık projeksiyonu
                                (gerçekleşme faktörü uygulanmış)

    FleetAnalyzer bu değerleri toplar:
        total_savings_fuel = Σ fuel_optimization_kg
        total_savings_cost = Σ total_cost_saving_usd
        total_annual_usd   = Σ annual_realistic_usd

    Yıllık projeksiyon "annualized_cost_saving_usd" için
    total_annual_usd doğrudan kullanılır.
    
    Yıllık yakıt tasarrufu "annualized_fuel_saving_tonnes" için:
    total_annual_usd / avg_fuel_price_usd_per_kg / 1000
    (böylece para ile tutarlı)

VERİ KALİTESİ:
──────────────
    Partial flight'lar benchmark dışı tutulur.
    Tasarruf projeksiyonunda tüm uçuşlar dahil edilir
    ama partial flag'li olanlar is_partial_flight=True ile işaretlenir.
    Rapor bunu şeffaf gösterir.

Kaynak:
───────
    IATA Fuel Efficiency Report (benchmark değerleri)
    ICAO CORSIA SARP Annex 16 Vol IV
    Eurocontrol Performance Review Report
    JCGM 100:2008 (belirsizlik ve veri kalitesi)
"""

from __future__ import annotations

import numpy as np
from collections import defaultdict
from datetime import datetime
from typing import Optional

from src.models.emission_model import EmissionCalculator
from config.settings import EI_CO2, CARBON_CREDIT_PRICE_USD


# ═══════════════════════════════════════════════════════════
# SEKTÖR BENCHMARK VERİLERİ
# ═══════════════════════════════════════════════════════════

_INDUSTRY_BENCHMARKS: dict[str, dict] = {
    'B738': {
        'name': 'Boeing 737-800',
        'avg_fuel_per_nm_kg': 6.6,
        'best_fuel_per_nm_kg': 5.8,
        'avg_co2_per_pax_km_g': 95,
        'best_co2_per_pax_km_g': 75,
        'avg_route_efficiency_pct': 94,
        'data_source': 'IATA/ICAO composite estimate 2024',
    },
    'B38M': {
        'name': 'Boeing 737 MAX 8',
        'avg_fuel_per_nm_kg': 5.8,
        'best_fuel_per_nm_kg': 5.2,
        'avg_co2_per_pax_km_g': 82,
        'best_co2_per_pax_km_g': 65,
        'avg_route_efficiency_pct': 95,
        'data_source': 'IATA/ICAO composite estimate 2024',
    },
    'A320': {
        'name': 'Airbus A320-200',
        'avg_fuel_per_nm_kg': 6.4,
        'best_fuel_per_nm_kg': 5.6,
        'avg_co2_per_pax_km_g': 90,
        'best_co2_per_pax_km_g': 70,
        'avg_route_efficiency_pct': 94,
        'data_source': 'IATA/ICAO composite estimate 2024',
    },
    'A20N': {
        'name': 'Airbus A320neo',
        'avg_fuel_per_nm_kg': 5.6,
        'best_fuel_per_nm_kg': 5.0,
        'avg_co2_per_pax_km_g': 78,
        'best_co2_per_pax_km_g': 62,
        'avg_route_efficiency_pct': 95,
        'data_source': 'IATA/ICAO composite estimate 2024',
    },
    'B77W': {
        'name': 'Boeing 777-300ER',
        'avg_fuel_per_nm_kg': 28.0,
        'best_fuel_per_nm_kg': 24.0,
        'avg_co2_per_pax_km_g': 85,
        'best_co2_per_pax_km_g': 68,
        'avg_route_efficiency_pct': 96,
        'data_source': 'IATA/ICAO composite estimate 2024',
    },
    'B788': {
        'name': 'Boeing 787-8',
        'avg_fuel_per_nm_kg': 20.0,
        'best_fuel_per_nm_kg': 17.0,
        'avg_co2_per_pax_km_g': 75,
        'best_co2_per_pax_km_g': 60,
        'avg_route_efficiency_pct': 96,
        'data_source': 'IATA/ICAO composite estimate 2024',
    },
    'A350': {
        'name': 'Airbus A350-900',
        'avg_fuel_per_nm_kg': 19.0,
        'best_fuel_per_nm_kg': 16.0,
        'avg_co2_per_pax_km_g': 72,
        'best_co2_per_pax_km_g': 58,
        'avg_route_efficiency_pct': 96,
        'data_source': 'IATA/ICAO composite estimate 2024',
    },
    'DEFAULT': {
        'name': 'Generic Narrowbody',
        'avg_fuel_per_nm_kg': 8.5,
        'best_fuel_per_nm_kg': 7.0,
        'avg_co2_per_pax_km_g': 100,
        'best_co2_per_pax_km_g': 80,
        'avg_route_efficiency_pct': 93,
        'data_source': 'Industry average estimate',
    },
}

# Partial flight eşik değerleri (kg/Nm)
_PARTIAL_FLIGHT_THRESHOLD_KG_PER_NM: dict[str, float] = {
    'B738': 5.5,
    'B38M': 4.8,
    'A320': 5.2,
    'A20N': 4.5,
    'A321': 5.8,
    'A21N': 5.2,
    'B77W': 18.0,
    'B788': 12.0,
    'B789': 12.0,
    'A350': 12.0,
    'A380': 22.0,
    'DEFAULT': 5.0,
}

_UNKNOWN_DESTINATION_MARKERS = {'UNK', 'UNKN', '', 'N/A', 'NONE', None}

# Ortalama yakıt fiyatı (annualized fuel ton hesabı için)
_DEFAULT_FUEL_PRICE_USD_PER_KG = 0.85


# ═══════════════════════════════════════════════════════════
# YARDIMCI: PARTIAL FLIGHT TESPİTİ
# ═══════════════════════════════════════════════════════════

def _detect_partial_flight(
    fuel_kg: float,
    distance_nm: float,
    aircraft_type: str,
    destination_icao: str,
    data_source: str = '',
) -> dict:
    """
    Uçuşun tam veya partial olduğunu tespit eder.
    """
    fuel_per_nm = fuel_kg / max(distance_nm, 1.0)
    threshold   = _PARTIAL_FLIGHT_THRESHOLD_KG_PER_NM.get(
        aircraft_type,
        _PARTIAL_FLIGHT_THRESHOLD_KG_PER_NM['DEFAULT'],
    )

    reasons = []
    partial_signals = 0

    if fuel_per_nm < threshold:
        partial_signals += 2
        reasons.append(
            f"Yakıt/Nm {fuel_per_nm:.2f} < eşik {threshold:.2f} "
            f"({aircraft_type} için minimum operasyonel değerin altında)"
        )

    if str(destination_icao).strip().upper() in {
        str(m).upper() if m else 'NONE'
        for m in _UNKNOWN_DESTINATION_MARKERS
    }:
        partial_signals += 1
        reasons.append("Varış havalimanı tespit edilemedi (UNK)")

    if 'opensky' in str(data_source).lower() or 'active' in str(data_source).lower():
        if fuel_per_nm < threshold * 1.2:
            partial_signals += 1
            reasons.append("ADS-B aktif uçuş verisi — trajectory eksik olabilir")

    if partial_signals >= 3:
        is_partial = True
        confidence = 'HIGH'
    elif partial_signals == 2:
        is_partial = True
        confidence = 'MEDIUM'
    elif partial_signals == 1:
        is_partial = True
        confidence = 'LOW'
    else:
        is_partial = False
        confidence = 'HIGH'
        reasons = ['Tüm kalite kontrolleri geçti']

    return {
        'is_partial'          : is_partial,
        'confidence'          : confidence,
        'reasons'             : reasons,
        'fuel_per_nm'         : round(fuel_per_nm, 3),
        'threshold_kg_per_nm' : threshold,
        'partial_signals'     : partial_signals,
    }


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class FleetAnalyzer:
    """
    Filo bazlı analiz ve raporlama.

    Tasarruf hesabı mantığı:
        Her uçuşun annual_realistic_usd alanı
        02_analyze_and_optimize.py tarafından hesaplanır.
        FleetAnalyzer bu değerleri toplayarak filo geneli
        yıllık tasarruf potansiyelini gösterir.

        annualized_cost_saving_usd = Σ annual_realistic_usd
        annualized_fuel_saving_tonnes = annualized_cost / avg_fuel_price / 1000
    """

    def __init__(self) -> None:
        self.flight_results: list[dict] = []
        self._emission_calc = EmissionCalculator()

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: UÇUŞ EKLEME
    # ──────────────────────────────────────────────────────

    def add_flight_result(self, analysis_result: dict) -> None:
        """
        SingleFlightAnalyzer.analyze_trajectory() çıktısını ekle.
        """
        if analysis_result is None:
            return

        fuel_kg     = analysis_result.get('fuel_analysis', {}).get('estimated_total_fuel_kg', 0)
        distance_nm = analysis_result.get('basic_metrics', {}).get('great_circle_distance_nm', 0)
        ac_type     = analysis_result.get('flight_info', {}).get('aircraft_type', 'B738')
        dest_icao   = analysis_result.get('basic_metrics', {}).get('destination_icao', 'UNK')
        data_src    = analysis_result.get('flight_info', {}).get('data_source', '')

        quality = _detect_partial_flight(fuel_kg, distance_nm, ac_type, dest_icao, data_src)

        result = dict(analysis_result)
        result['_data_quality'] = quality

        self.flight_results.append(result)

    def add_manual_flight(
        self,
        origin: str,
        destination: str,
        fuel_kg: float,
        distance_nm: float,
        aircraft_type: str = 'B738',
        flight_number: str = '',
        cruise_altitude_ft: float = 35000,
        date: Optional[str] = None,
        # ── Tasarruf alanları ──────────────────────────────
        fuel_saving_kg: float = 0.0,
        cost_saving_usd: float = 0.0,
        annual_saving_usd: float = 0.0,
        # ── Optimizasyon detayları ─────────────────────────
        optimum_fl: str = '',
        buffet_margin_pct: float = 0.0,
        sar_loss_pct: float = 0.0,
        step_climb_saving_kg: float = 0.0,
        step_plan: Optional[list] = None,
        optimum_ci: int = 0,
        optimum_mach: float = 0.0,
        tankering_amount_kg: int = 0,
        tankering_saving_usd: float = 0.0,
        altitude_saving_kg: float = 0.0,
        altitude_deviation_ft: float = 0.0,
        step_climb_applied: bool = False,
        # ── Veri kalitesi ──────────────────────────────────
        is_partial_flight: Optional[bool] = None,
        data_source: str = 'manual_entry',
        coverage_note: str = '',
    ) -> None:
        """
        Manuel uçuş verisi ekle (trajectory olmadan).

        Tasarruf alanları (fuel_saving_kg, cost_saving_usd,
        annual_saving_usd) 02_analyze_and_optimize.py çıktısından
        mutlaka geçirilmelidir. Aksi hâlde raporda $0 görünür.
        """
        if date is None:
            date = datetime.now().isoformat()

        # Partial flight tespiti
        if is_partial_flight is None:
            quality = _detect_partial_flight(
                fuel_kg, distance_nm, aircraft_type,
                destination, data_source,
            )
        else:
            quality = {
                'is_partial'          : is_partial_flight,
                'confidence'          : 'MANUAL',
                'reasons'             : ['Kullanıcı tarafından belirlendi'],
                'fuel_per_nm'         : round(fuel_kg / max(distance_nm, 1), 3),
                'threshold_kg_per_nm' : _PARTIAL_FLIGHT_THRESHOLD_KG_PER_NM.get(
                    aircraft_type, _PARTIAL_FLIGHT_THRESHOLD_KG_PER_NM['DEFAULT']
                ),
                'partial_signals'     : 0,
            }

        if coverage_note:
            quality['coverage_note'] = coverage_note

        # Emisyon hesabı
        emissions = self._emission_calc.calculate_flight_emissions(
            fuel_burn_kg=fuel_kg,
            distance_nm=distance_nm,
            aircraft_type=aircraft_type,
            cruise_altitude_ft=cruise_altitude_ft,
        )

        # Yıllık tasarruf: dışarıdan geçirilmemişse kaba projeksiyon
        if annual_saving_usd == 0.0 and cost_saving_usd > 0:
            from config.assumptions import Assumptions, OPERATIONAL_DAYS_PER_YEAR
            daily_flights     = Assumptions.daily_frequency(distance_nm)
            rf                = Assumptions.realization_factor()
            annual_saving_usd = round(
                cost_saving_usd * daily_flights * OPERATIONAL_DAYS_PER_YEAR * rf
            )

        result = {
            'flight_info': {
                'aircraft_type'      : aircraft_type,
                'aircraft_name'      : '',
                'analysis_timestamp' : date,
                'data_source'        : data_source,
                'data_points'        : 0,
                'estimated_weight_kg': 0,
            },
            'basic_metrics': {
                'callsign'                 : flight_number or 'MANUAL',
                'great_circle_distance_nm' : distance_nm,
                'actual_distance_nm'       : distance_nm * 1.03,
                'route_efficiency_pct'     : 97.0,
                'extra_distance_nm'        : distance_nm * 0.03,
                'total_flight_time_hr'     : distance_nm / 450,
                'total_flight_time_min'    : distance_nm / 450 * 60,
                'heading_deg'              : 0,
                'origin_icao'              : origin,
                'destination_icao'         : destination,
                'phase_durations_min'      : {},
            },
            'fuel_analysis': {
                'estimated_total_fuel_kg': fuel_kg,
                'phase_breakdown'        : {},
                'initial_weight_kg'      : 0,
                'final_weight_kg'        : 0,
                'accuracy_note'          : (
                    'Manuel girdi — operatör kayıtlarından.'
                    if data_source == 'customer_records'
                    else 'Tahmin modeli — QAR/FDR ile doğrulama önerilir.'
                ),
            },
           'altitude_analysis': {
                'avg_cruise_altitude_ft'   : cruise_altitude_ft,
                'max_cruise_altitude_ft'   : cruise_altitude_ft,
                'min_cruise_altitude_ft'   : cruise_altitude_ft,
                'optimum_altitude_ft'      : cruise_altitude_ft + altitude_deviation_ft,
                'altitude_deviation_ft'    : altitude_deviation_ft,   # ✅ ARTIK 0 DEĞİL
                'avg_cruise_mach'          : optimum_mach or 0.785,
                'sar_at_actual_alt'        : 0,
                'sar_at_optimum_alt'       : 0,
                'sar_loss_pct'             : sar_loss_pct,
                'step_climbs_detected'     : (
                    1 if (step_climb_applied or step_climb_saving_kg > 0) else 0
                ),                                               # ✅ YENİ MANTIK
                'step_climb_details'       : step_plan or [],
                'step_climb_recommended'   : False,
                'optimum_fl'               : optimum_fl,
                'buffet_margin_pct'        : buffet_margin_pct,
           },
            'route_analysis': {
                'great_circle_distance_nm' : distance_nm,
                'actual_distance_nm'       : distance_nm * 1.03,
                'extra_distance_nm'        : distance_nm * 0.03,
                'route_efficiency_pct'     : 97.0,
                'extra_distance_fuel_kg'   : 0,
                'holding_detected'         : False,
                'holding_count'            : 0,
                'holding_duration_min'     : 0,
                'holding_fuel_estimate_kg' : 0,
                'holding_details'          : [],
                'assessment'               : 'Manuel veri — rota verimliliği varsayılan',
            },
            'emissions': emissions,
            'optimum_comparison': {
                'actual_estimated_fuel_kg'   : fuel_kg,
                'optimum_estimated_fuel_kg'  : max(0, fuel_kg - fuel_saving_kg),
                'fuel_difference_kg'         : fuel_saving_kg,
                'fuel_saving_potential_pct'  : round(
                    fuel_saving_kg / fuel_kg * 100, 2
                ) if fuel_kg > 0 else 0,
                'co2_saving_potential_kg'    : round(fuel_saving_kg * 3.16),
                'cost_saving_usd'            : cost_saving_usd,
                'optimum_conditions': {
                    'altitude_ft'  : cruise_altitude_ft,
                    'mach'         : optimum_mach or 0.785,
                    'sar_nm_per_kg': 0,
                    'flight_level' : optimum_fl,
                },
            },
            'savings_opportunities': {
                'opportunities': self._build_opportunities(
                    fuel_saving_kg       = fuel_saving_kg,
                    cost_saving_usd      = cost_saving_usd,
                    altitude_saving_kg   = altitude_saving_kg,
                    step_climb_saving_kg = step_climb_saving_kg,
                    tankering_saving_usd = tankering_saving_usd,
                    tankering_amount_kg  = tankering_amount_kg,
                    optimum_fl           = optimum_fl,
                    sar_loss_pct         = sar_loss_pct,
                    step_plan            = step_plan,
                ),
                'total_per_flight': {
                    'fuel_saving_kg' : round(fuel_saving_kg),
                    'co2_saving_kg'  : round(fuel_saving_kg * 3.16),
                    'cost_saving_usd': round(cost_saving_usd, 2),
                },
                'annual_projection': {
                    'fuel_saving_tonnes'  : round(fuel_saving_kg * 345 / 1000, 2),
                    'co2_saving_tonnes'   : round(fuel_saving_kg * 3.16 * 345 / 1000, 2),
                    'cost_saving_usd'     : round(annual_saving_usd),
                    'realistic_annual_usd': round(annual_saving_usd),
                },
                'summary': (
                    f"{round(fuel_saving_kg)} kg yakıt (${round(cost_saving_usd, 0):.0f}) "
                    f"uçuş başına tasarruf potansiyeli. "
                    f"Yıllık projeksiyon: ${round(annual_saving_usd):,}."
                ) if fuel_saving_kg > 0 else 'Tasarruf verisi henüz eklenmedi.',
                'note': (
                    'Altitude ve step climb tasarrufları çift sayım önlemek için '
                    'büyük olanı alınmıştır.'
                ),
            },
            '_data_quality': quality,
        }

        self.flight_results.append(result)

    @staticmethod
    def _build_opportunities(
        fuel_saving_kg: float,
        cost_saving_usd: float,
        altitude_saving_kg: float,
        step_climb_saving_kg: float,
        tankering_saving_usd: float,
        tankering_amount_kg: int,
        optimum_fl: str,
        sar_loss_pct: float,
        step_plan: Optional[list],
    ) -> list[dict]:
        """
        Tasarruf fırsatları listesini oluştur.
        """
        opps = []

        if altitude_saving_kg > 0:
            opps.append({
                'category'                 : 'ALTITUDE_OPTIMIZATION',
                'priority'                 : 'HIGH' if sar_loss_pct > 2 else 'MEDIUM',
                'title'                    : 'Cruise İrtifa Optimizasyonu',
                'description'              : (
                    f"Mevcut cruise irtifası optimumdan sapıyor. "
                    f"{optimum_fl or 'Daha yüksek FL'} önerilir. "
                    f"SAR kaybı: %{sar_loss_pct:.1f}."
                ),
                'estimated_fuel_saving_kg' : round(altitude_saving_kg),
                'estimated_co2_saving_kg'  : round(altitude_saving_kg * 3.16),
                'estimated_cost_saving_usd': round(altitude_saving_kg * 0.85, 2),
                'implementation'           : 'Dispatcher briefing ile uygulanabilir',
                'difficulty'               : 'LOW',
            })

        if step_climb_saving_kg > 0:
            n_steps = len(step_plan) if step_plan else 1
            opps.append({
                'category'                 : 'STEP_CLIMB',
                'priority'                 : 'MEDIUM',
                'title'                    : f'Step Climb Optimizasyonu ({n_steps} adım)',
                'description'              : (
                    f"Yakıt azaldıkça optimum irtifa yükselir. "
                    f"{n_steps} step climb önerilir."
                ),
                'estimated_fuel_saving_kg' : round(step_climb_saving_kg),
                'estimated_co2_saving_kg'  : round(step_climb_saving_kg * 3.16),
                'estimated_cost_saving_usd': round(step_climb_saving_kg * 0.85, 2),
                'implementation'           : 'ATC koordinasyonu gerektirir',
                'difficulty'               : 'MEDIUM',
            })

        if tankering_saving_usd > 0:
            opps.append({
                'category'                 : 'TANKERING',
                'priority'                 : 'HIGH',
                'title'                    : f'Yakıt Tankering ({tankering_amount_kg} kg)',
                'description'              : (
                    f"Kalkış havalimanında yakıt daha ucuz. "
                    f"{tankering_amount_kg} kg ekstra yakıt alınması önerilir."
                ),
                'estimated_fuel_saving_kg' : 0,
                'estimated_co2_saving_kg'  : 0,
                'estimated_cost_saving_usd': round(tankering_saving_usd, 2),
                'implementation'           : 'Dispatcher / loadsheet koordinasyonu',
                'difficulty'               : 'LOW',
            })

        return opps

    @property
    def flight_count(self) -> int:
        return len(self.flight_results)

    @property
    def valid_flight_count(self) -> int:
        return sum(
            1 for r in self.flight_results
            if not r.get('_data_quality', {}).get('is_partial', False)
        )

    @property
    def partial_flight_count(self) -> int:
        return self.flight_count - self.valid_flight_count

    def clear(self) -> None:
        self.flight_results.clear()

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: VERİ KALİTESİ RAPORU
    # ──────────────────────────────────────────────────────

    def get_data_quality_report(self) -> dict:
        """
        Filo verisinin kalite raporu.
        """
        n = len(self.flight_results)
        if n == 0:
            return {
                'total_flights'     : 0,
                'valid_flights'     : 0,
                'partial_flights'   : 0,
                'partial_pct'       : 0,
                'unk_destinations'  : 0,
                'quality_grade'     : 'N/A',
                'benchmark_eligible': False,
                'details'           : [],
                'recommendations'   : ['Hiç uçuş verisi eklenmemiş'],
            }

        partial_count  = 0
        unk_dest_count = 0
        details        = []

        for result in self.flight_results:
            quality      = result.get('_data_quality', {})
            is_partial   = quality.get('is_partial', False)
            dest         = result.get('basic_metrics', {}).get('destination_icao', 'UNK')
            callsign     = result.get('basic_metrics', {}).get('callsign', '?')
            fuel_kg      = result.get('fuel_analysis', {}).get('estimated_total_fuel_kg', 0)
            dist_nm      = result.get('basic_metrics', {}).get('great_circle_distance_nm', 0)

            if is_partial:
                partial_count += 1

            if str(dest).upper() in {
                str(m).upper() if m else 'NONE'
                for m in _UNKNOWN_DESTINATION_MARKERS
            }:
                unk_dest_count += 1

            details.append({
                'callsign'    : callsign,
                'destination' : dest,
                'fuel_kg'     : fuel_kg,
                'distance_nm' : dist_nm,
                'fuel_per_nm' : quality.get('fuel_per_nm', 0),
                'is_partial'  : is_partial,
                'confidence'  : quality.get('confidence', 'N/A'),
                'reasons'     : quality.get('reasons', []),
            })

        partial_pct = partial_count / n * 100

        if partial_pct < 10:
            grade = 'A'
        elif partial_pct < 30:
            grade = 'B'
        elif partial_pct < 60:
            grade = 'C'
        else:
            grade = 'D'

        benchmark_eligible = (n - partial_count) >= 3

        recommendations = []
        if partial_pct > 30:
            recommendations.append(
                f"Veri kalitesi düşük: %{partial_pct:.0f} partial flight. "
                f"01_collect_data.py'da arrivals endpoint kullanın."
            )
        if unk_dest_count > 0:
            recommendations.append(
                f"{unk_dest_count} uçuşta varış bilinmiyor. "
                f"Rota analizi bu uçuşlar için 'UNK' gösterecek."
            )
        if partial_pct <= 10:
            recommendations.append(
                "Veri kalitesi yüksek. Benchmark ve rota analizi güvenilir."
            )

        return {
            'total_flights'     : n,
            'valid_flights'     : n - partial_count,
            'partial_flights'   : partial_count,
            'partial_pct'       : round(partial_pct, 1),
            'unk_destinations'  : unk_dest_count,
            'quality_grade'     : grade,
            'benchmark_eligible': benchmark_eligible,
            'details'           : details,
            'recommendations'   : recommendations,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: FİLO ÖZETİ
    # ──────────────────────────────────────────────────────
    def generate_fleet_summary(
        self,
        exclude_partial_from_benchmark: bool = True,
        avg_fuel_price_usd_per_kg: float = _DEFAULT_FUEL_PRICE_USD_PER_KG,
    ) -> dict:
        """
        Tüm uçuşların filo özet raporunu üret.
        """
        if not self.flight_results:
            return {'error': 'Hiç uçuş verisi eklenmemiş'}

        n_flights      = len(self.flight_results)
        quality_report = self.get_data_quality_report()

        # ─── Metrik toplama ───────────────────────────────
        total_fuel         = 0.0
        total_distance     = 0.0
        total_co2          = 0.0
        total_savings_fuel = 0.0
        total_savings_cost = 0.0
        total_annual_usd   = 0.0

        route_data    = defaultdict(lambda: {
            'flights': 0, 'total_fuel': 0, 'total_distance': 0,
            'total_co2': 0, 'fuel_list': [], 'efficiency_list': [],
            'total_saving_fuel': 0, 'total_saving_cost': 0,
            'annual_list': [],
        })
        aircraft_data = defaultdict(lambda: {
            'flights': 0, 'total_fuel': 0, 'total_co2': 0,
            'total_saving_usd': 0,
        })

        altitude_deviations = []
        route_efficiencies  = []
        sar_losses          = []
        step_climb_count    = 0

        bm_fuel_list     = []
        bm_distance_list = []

        for result in self.flight_results:
            is_partial = result.get(
                '_data_quality', {}
            ).get('is_partial', False)

            fuel     = float(result['fuel_analysis']['estimated_total_fuel_kg'])
            distance = float(result['basic_metrics']['great_circle_distance_nm'])
            co2      = float(result['emissions']['emissions']['CO2_kg'])
            ac_type  = result['flight_info']['aircraft_type']

            total_fuel     += fuel
            total_distance += distance
            total_co2      += co2

            savings_tf  = result['savings_opportunities']['total_per_flight']
            savings_ann = result['savings_opportunities'].get(
                'annual_projection', {}
            )

            flight_fuel_save = float(savings_tf.get('fuel_saving_kg', 0))
            flight_cost_save = float(savings_tf.get('cost_saving_usd', 0))
            flight_annual    = float(
                savings_ann.get(
                    'realistic_annual_usd',
                    savings_ann.get('cost_saving_usd', 0)
                )
            )

            total_savings_fuel += flight_fuel_save
            total_savings_cost += flight_cost_save
            total_annual_usd   += flight_annual

            # Rota
            origin    = result['basic_metrics'].get('origin_icao', 'UNK')
            dest      = result['basic_metrics'].get('destination_icao', 'UNK')
            route_key = f"{origin}-{dest}"

            rd = route_data[route_key]
            rd['flights']           += 1
            rd['total_fuel']        += fuel
            rd['total_distance']    += distance
            rd['total_co2']         += co2
            rd['fuel_list'].append(fuel)
            rd['efficiency_list'].append(
                result['route_analysis'].get('route_efficiency_pct', 95)
            )
            rd['total_saving_fuel'] += flight_fuel_save
            rd['total_saving_cost'] += flight_cost_save
            rd['annual_list'].append(flight_annual)

            # Uçak tipi
            ad = aircraft_data[ac_type]
            ad['flights']          += 1
            ad['total_fuel']       += fuel
            ad['total_co2']        += co2
            ad['total_saving_usd'] += flight_cost_save

            # ─── İrtifa sapması ───────────────────────────
            # Önce altitude_analysis içine bak
            # Yoksa direkt result'tan al (batch_results.json formatı)
            alt_dev = float(
                result.get('altitude_analysis', {}).get(
                    'altitude_deviation_ft'
                )
                or result.get('altitude_deviation_ft', 0)
            )
            altitude_deviations.append(alt_dev)

            # ─── Rota verimliliği ─────────────────────────
            route_eff = float(
                result.get('route_analysis', {}).get(
                    'route_efficiency_pct', 95
                )
            )
            route_efficiencies.append(route_eff)

            # ─── SAR kaybı ────────────────────────────────
            sar_loss = float(
                result.get('altitude_analysis', {}).get('sar_loss_pct')
                or result.get('sar_loss_pct', 0)
            )
            sar_losses.append(sar_loss)

            # ─── Step climb ───────────────────────────────
            step_detected = (
                result.get('altitude_analysis', {}).get(
                    'step_climbs_detected', 0
                )
                or (1 if result.get('step_climb_applied', False) else 0)
            )
            if step_detected > 0:
                step_climb_count += 1

            # Benchmark için tam uçuşlar
            if not is_partial or not exclude_partial_from_benchmark:
                bm_fuel_list.append(fuel)
                bm_distance_list.append(distance)

        # ─── Rota sıralaması ──────────────────────────────
        route_rankings = []
        for route, data in route_data.items():
            n_r          = data['flights']
            avg_fuel     = data['total_fuel'] / n_r
            avg_distance = data['total_distance'] / n_r
            fuel_per_nm  = avg_fuel / avg_distance if avg_distance > 0 else 0
            fuel_std     = float(
                np.std(data['fuel_list'])
            ) if len(data['fuel_list']) > 1 else 0
            avg_eff      = float(np.mean(data['efficiency_list']))

            route_rankings.append({
                'route'                : route,
                'flights'              : n_r,
                'avg_fuel_kg'          : round(avg_fuel),
                'total_fuel_kg'        : round(data['total_fuel']),
                'total_co2_kg'         : round(data['total_co2']),
                'avg_distance_nm'      : round(avg_distance),
                'fuel_per_nm'          : round(fuel_per_nm, 2),
                'fuel_consistency_std' : round(fuel_std),
                'avg_route_efficiency' : round(avg_eff, 1),
                'avg_fuel_saving_kg'   : round(
                    data['total_saving_fuel'] / n_r
                ),
                'avg_cost_saving_usd'  : round(
                    data['total_saving_cost'] / n_r, 2
                ),
            })

        route_rankings.sort(
            key=lambda x: x['fuel_per_nm'], reverse=True
        )

        # ─── Verimlilik skoru ─────────────────────────────
        avg_route_eff = float(
            np.mean(route_efficiencies)
        ) if route_efficiencies else 95
        avg_sar_loss  = float(
            np.mean(sar_losses)
        ) if sar_losses else 0
        avg_alt_dev   = float(
            np.mean(np.abs(altitude_deviations))
        ) if altitude_deviations else 0

        # Calculate deviation percentage dynamically
        deviated_count = sum(1 for d in altitude_deviations if abs(d) > 100)
        deviation_pct = round(deviated_count / len(altitude_deviations) * 100) if altitude_deviations else 55

        efficiency_score = (
            avg_route_eff * 0.4 +
            max(0, 100 - avg_sar_loss * 20) * 0.3 +
            max(0, 100 - avg_alt_dev / 100) * 0.3
        )

        # ─── Benchmark ────────────────────────────────────
        primary_ac_type = max(
            aircraft_data,
            key=lambda x: aircraft_data[x]['flights'],
        )
        benchmark_ref = _INDUSTRY_BENCHMARKS.get(
            primary_ac_type,
            _INDUSTRY_BENCHMARKS['DEFAULT'],
        )

        if bm_fuel_list and bm_distance_list:
            bm_fuel_per_nm = sum(bm_fuel_list) / sum(bm_distance_list)
        else:
            bm_fuel_per_nm = (
                total_fuel / total_distance
                if total_distance > 0 else 0
            )

        bm_n_valid = len(bm_fuel_list)

        if bm_fuel_per_nm <= benchmark_ref['best_fuel_per_nm_kg']:
            benchmark_rating = "EXCELLENT — Sektörün en iyileri arasında"
        elif bm_fuel_per_nm <= benchmark_ref['avg_fuel_per_nm_kg']:
            benchmark_rating = "GOOD — Sektör ortalamasının üzerinde"
        elif bm_fuel_per_nm <= benchmark_ref['avg_fuel_per_nm_kg'] * 1.1:
            benchmark_rating = "AVERAGE — Sektör ortalaması civarında"
        else:
            benchmark_rating = (
                "BELOW AVERAGE — İyileştirme potansiyeli yüksek"
            )

        gap_to_best = (
            (bm_fuel_per_nm - benchmark_ref['best_fuel_per_nm_kg']) /
            benchmark_ref['best_fuel_per_nm_kg'] * 100
        ) if benchmark_ref['best_fuel_per_nm_kg'] > 0 else 0

        partial_pct = quality_report['partial_pct']
        if partial_pct > 50 and exclude_partial_from_benchmark:
            benchmark_rating += ' (⚠️ Sınırlı tam veri)'
            benchmark_data_warning = (
                f"Dikkat: Veri setinin %{partial_pct:.0f}'i "
                f"partial trajectory. Benchmark {bm_n_valid} tam "
                f"uçuşa dayanmaktadır."
            )
        else:
            benchmark_data_warning = None

        # ─── Yıllık tasarruf ──────────────────────────────
        # Rota bazlı mükerrer sayımı engelle (Dinamik ve Gerçekçi Tasarruf)
        is_demo = any(r.get('flight_info', {}).get('data_source') == 'demo_simulation' for r in self.flight_results)
        if is_demo:
            # Demo simülasyonu: 04 scripti her haftalık uçuş için tasarrufu yazmıştır, basitçe topla
            total_annual_usd = sum(sum(rd['annual_list']) for rd in route_data.values() if rd.get('annual_list'))
        else:
            # Gerçek canlı uçuşlar: Mükerrerliği önlemek için benzersiz rotaların ortalama tasarruflarını topla
            total_annual_usd = sum(np.mean(rd['annual_list']) for rd in route_data.values() if rd.get('annual_list'))
        
        annualized_cost        = total_annual_usd
        annualized_fuel_tonnes = (
            annualized_cost / avg_fuel_price_usd_per_kg / 1000
        ) if avg_fuel_price_usd_per_kg > 0 else 0
        annualized_co2_tonnes  = annualized_fuel_tonnes * 3.16

        avg_fuel_per_nm = (
            total_fuel / total_distance
            if total_distance > 0 else 0
        )

        return {
            'report_metadata': {
                'generated_at'           : datetime.now().isoformat(),
                'total_flights_analyzed' : n_flights,
                'valid_flights'          : quality_report['valid_flights'],  # ✅ bm_n_valid değil
                'partial_flights'        : quality_report['partial_flights'],
                'reporting_standard'     : (
                    'GreenWing Analytics Fleet Report v1.0'
                ),
                'benchmark_basis': (
                    f"{bm_n_valid} tam uçuş"
                    if exclude_partial_from_benchmark
                    else f"{n_flights} uçuş (partial dahil)"
                ),
                'avg_fuel_price_used': avg_fuel_price_usd_per_kg,
            },
            'fleet_summary': {
                'total_fuel_kg'          : round(total_fuel),
                'total_fuel_tonnes'      : round(total_fuel / 1000, 1),
                'total_distance_nm'      : round(total_distance),
                'total_co2_tonnes'       : round(total_co2 / 1000, 1),
                'avg_fuel_per_flight_kg' : (
                    round(total_fuel / n_flights)
                    if n_flights > 0 else 0
                ),
                'avg_fuel_per_nm'        : round(avg_fuel_per_nm, 2),
                'fleet_efficiency_score' : round(efficiency_score, 1),
            },
            'route_analysis': {
                'total_routes'           : len(route_rankings),
                'rankings'               : route_rankings,
                'least_efficient_routes' : route_rankings[:5],
                'most_efficient_routes'  : (
                    route_rankings[-5:][::-1]
                    if len(route_rankings) >= 5 else []
                ),
            },
            'aircraft_analysis': dict(aircraft_data),
            'altitude_performance': {
                'avg_deviation_from_optimum_ft': round(avg_alt_dev),
                'avg_sar_loss_pct'             : round(avg_sar_loss, 2),
                'flights_with_step_climb'      : step_climb_count,
                'deviation_pct'                : deviation_pct,
            },
            'benchmark': {
                'reference'                : benchmark_ref,
                'fleet_fuel_per_nm'        : round(bm_fuel_per_nm, 2),
                'industry_avg_fuel_per_nm' : benchmark_ref[
                    'avg_fuel_per_nm_kg'
                ],
                'industry_best_fuel_per_nm': benchmark_ref[
                    'best_fuel_per_nm_kg'
                ],
                'rating'                   : benchmark_rating,
                'gap_to_best_pct'          : round(gap_to_best, 1),
                'based_on_n_flights'       : bm_n_valid,
                'data_quality_warning'     : benchmark_data_warning,
            },
            'savings_potential': {
                'total_fuel_saving_kg'          : round(total_savings_fuel),
                'total_cost_saving_usd'         : round(total_savings_cost),
                'total_co2_saving_kg'           : round(
                    total_savings_fuel * 3.16
                ),
                'annualized_cost_saving_usd'    : round(annualized_cost),
                'annualized_fuel_saving_tonnes' : round(
                    annualized_fuel_tonnes, 1
                ),
                'annualized_co2_saving_tonnes'  : round(
                    annualized_co2_tonnes, 1
                ),
                'projection_note': (
                    'Yıllık projeksiyon, her uçuşun rota frekansı ve '
                    'gerçekleşme faktörü dikkate alınarak hesaplanmıştır. '
                    f'Ortalama yakıt fiyatı: '
                    f'${avg_fuel_price_usd_per_kg:.2f}/kg.'
                ),
            },
            'data_quality': {
                'quality_grade'      : quality_report['quality_grade'],
                'total_flights'      : n_flights,
                'valid_flights'      : quality_report['valid_flights'],
                'partial_flights'    : quality_report['partial_flights'],
                'partial_pct'        : quality_report['partial_pct'],
                'unk_destinations'   : quality_report['unk_destinations'],
                'benchmark_eligible' : quality_report['benchmark_eligible'],
                'recommendations'    : quality_report['recommendations'],
            },
        }
     

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: CORSIA RAPORU
    # ──────────────────────────────────────────────────────

    def generate_corsia_report(
        self,
        airline_name: str = "Demo Airline",
        reporting_year: int = 2025,
        baseline_co2_tonnes: Optional[float] = None,
    ) -> dict:
        """
        CORSIA uyumlu yıllık emisyon raporu üret.

        CORSIA OFFSET HESABI MANTIĞI:
        ──────────────────────────────
        Baseline: 2019 referans yılı CO2 miktarı.
                  Müşteriden alınmalıdır.
                  Yoksa mevcut emisyonun %95'i tahminen kullanılır.

        Offset zorunluluğu:
                  max(0, current_co2 - baseline_co2)

        Offset maliyeti:
                  offset_tonnes × carbon_credit_price

        NOT: Bu hesap resmi CORSIA yükümlülüğü değildir.
             ISO 14065 akredite doğrulama gerektirir.
        """
        summary = self.generate_fleet_summary()

        if 'error' in summary:
            return summary

        total_co2_tonnes = summary['fleet_summary']['total_co2_tonnes']
        data_quality     = summary['data_quality']

        if baseline_co2_tonnes is None:
            baseline_co2_tonnes   = total_co2_tonnes * 0.95
            baseline_is_estimated = True
        else:
            baseline_is_estimated = False

        # Offset: mevcut ile baseline farkı
        excess_co2   = max(0.0, total_co2_tonnes - baseline_co2_tonnes)
        offset_cost  = excess_co2 * CARBON_CREDIT_PRICE_USD

        # Tasarrufların CORSIA'ya katkısı
        sv = summary.get('savings_potential', {})
        co2_reduction_potential = sv.get('annualized_co2_saving_tonnes', 0)
        potential_offset_avoidance = co2_reduction_potential * CARBON_CREDIT_PRICE_USD

        corsia_data_note = None
        if data_quality['partial_pct'] > 20:
            corsia_data_note = (
                f"Bu analizin veri setinin %{data_quality['partial_pct']:.0f}'i "
                f"partial ADS-B trajectory içeriyor. "
                f"Resmi CORSIA raporlaması için block fuel yöntemi (Method B) ve "
                f"operatör kayıtları kullanılmalıdır. "
                f"Bu değerler illustrative amaçlıdır."
            )

        return {
            'report_type'     : 'CORSIA Annual Emission Report',
            'standard'        : 'ICAO CORSIA SARP Annex 16 Volume IV',
            'airline'         : airline_name,
            'reporting_year'  : reporting_year,
            'report_status'   : (
                'ILLUSTRATIVE — Demonstrative Analysis'
                if baseline_is_estimated or data_quality['partial_pct'] > 20
                else 'PRELIMINARY'
            ),
            'emissions_summary': {
                'total_co2_tonnes'     : round(total_co2_tonnes, 1),
                'baseline_co2_tonnes'  : round(baseline_co2_tonnes, 1),
                'baseline_is_estimated': baseline_is_estimated,
                'excess_co2_tonnes'    : round(excess_co2, 1),
                'total_flights'        : summary['report_metadata']['total_flights_analyzed'],
                'total_fuel_tonnes'    : summary['fleet_summary']['total_fuel_tonnes'],
            },
            'offset_requirements': {
                'co2_to_offset_tonnes'      : round(excess_co2, 1),
                'estimated_offset_cost_usd' : round(offset_cost),
                'carbon_price_usd_per_tonne': CARBON_CREDIT_PRICE_USD,
                'note': (
                    'Illustrative estimate. '
                    'Gerçek CORSIA yükümlülüğü doğrulanmış baseline verisi ve '
                    'ISO 14065 akredite üçüncü taraf doğrulaması gerektirir.'
                ),
            },
            'reduction_opportunities': {
                'achievable_co2_reduction_tonnes_per_year': round(co2_reduction_potential, 1),
                'potential_offset_cost_avoidance_usd'     : round(potential_offset_avoidance),
                'projection_basis': sv.get('projection_note', ''),
                'note': (
                    'Yakıt verimliliği iyileştirmeleri hem operasyonel '
                    'maliyeti hem de CORSIA offset maruziyetini azaltır. '
                    f'Her 1000 ton CO₂ azaltma = '
                    f'${1000 * CARBON_CREDIT_PRICE_USD:,.0f} offset tasarrufu.'
                ),
            },
            'data_quality': {
                'quality_grade'   : data_quality['quality_grade'],
                'valid_flights'   : data_quality['valid_flights'],
                'partial_flights' : data_quality['partial_flights'],
                'corsia_data_note': corsia_data_note,
            },
            'methodology_notes': [
                f'CO₂ = Fuel Burn × {EI_CO2} kg/kg (ICAO standard emission factor)',
                'Fuel monitoring method: Block fuel (Method B) — where applicable',
                f'Baseline year: 2019 (CORSIA standard)',
                f'Baseline source: {"Operator records" if not baseline_is_estimated else "Estimated (95% of current — VERIFY WITH OPERATOR)"}',
                f'Report generated: {datetime.now().isoformat()}',
                f'Data quality grade: {data_quality["quality_grade"]}',
                (
                    f'⚠ {corsia_data_note}'
                    if corsia_data_note else
                    '✅ Data quality sufficient for illustrative CORSIA reporting.'
                ),
            ],
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: YARDIMCI
    # ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"FleetAnalyzer("
            f"total={self.flight_count}, "
            f"valid={self.valid_flight_count}, "
            f"partial={self.partial_flight_count})"
        )


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_fleet_analyzer() -> bool:
    """
    Fleet Analyzer doğrulama testleri.
    """
    print("\n" + "=" * 60)
    print("  FLEET_ANALYZER.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests  = 0

    def ok(name: str) -> None:
        nonlocal tests
        tests += 1
        print(f"  ✅ {name}")

    def fail(name: str, detail: str) -> None:
        nonlocal tests
        tests += 1
        errors.append(f"{name}: {detail}")
        print(f"  ❌ {name}: {detail}")

    # ─── [1] Oluşturma ───────────────────────────────────
    print("\n  [1] FleetAnalyzer Oluşturma")

    fleet = FleetAnalyzer()

    tests += 1
    if fleet.flight_count == 0:
        ok("Boş fleet oluşturuldu")
    else:
        fail("Boş fleet", f"flight_count={fleet.flight_count}")

    # ─── [2] Manuel uçuş ekleme (tasarruf dahil) ─────────
    print("\n  [2] Uçuş Ekleme (Tasarruf Dahil)")

    demo_flights = [
        # (origin, dest, fuel, dist, ac, fn, alt, saving_kg, cost_usd, annual_usd)
        ('LTFM','EGLL', 12500,1560,'B738','TK1985',37000,  325, 276.0, 189351),
        ('LTFM','EGLL', 12800,1560,'B738','TK1985',35000,  290, 246.5, 169583),
        ('EGLL','LTFM', 11500,1560,'B738','TK1986',37000,  310, 263.5, 181208),
        ('LTFM','EDDF',  8500,1000,'B738','TK1721',37000,  210, 178.5, 122633),
        ('LTFM','EDDF',  8900,1000,'B738','TK1721',35000,  185, 157.25,108078),
        ('EDDF','LTFM',  8200,1000,'B738','TK1722',37000,  220, 187.0, 128513),
        ('LTFM','OMDB', 42000,1550,'B77W','TK764', 39000,  980, 833.0, 287385),
        ('LTFM','LTAC',  3200, 190,'B738','TK2124',33000,   85,  72.25,149603),
        ('LTFM','LTAC',  3400, 190,'B738','TK2124',31000,   95,  80.75,167228),
        ('LTFM','LTAI',  4200, 300,'A320','TK2410',35000,  120, 102.0, 140940),
    ]

    for f in demo_flights:
        fleet.add_manual_flight(
            origin=f[0], destination=f[1],
            fuel_kg=f[2], distance_nm=f[3],
            aircraft_type=f[4], flight_number=f[5],
            cruise_altitude_ft=f[6],
            fuel_saving_kg=f[7],
            cost_saving_usd=f[8],
            annual_saving_usd=f[9],
        )

    tests += 1
    if fleet.flight_count == len(demo_flights):
        ok(f"{fleet.flight_count} uçuş eklendi")
    else:
        fail("Uçuş sayısı", f"{fleet.flight_count} ≠ {len(demo_flights)}")

    # ─── [3] Tasarruf mapping kontrolü ───────────────────
    print("\n  [3] Tasarruf Mapping")

    first = fleet.flight_results[0]
    sv_tf = first['savings_opportunities']['total_per_flight']

    tests += 1
    if sv_tf['fuel_saving_kg'] == 325:
        ok(f"fuel_saving_kg: {sv_tf['fuel_saving_kg']} kg ✓")
    else:
        fail("fuel_saving_kg", f"{sv_tf['fuel_saving_kg']} ≠ 325")

    tests += 1
    if sv_tf['cost_saving_usd'] == 276.0:
        ok(f"cost_saving_usd: ${sv_tf['cost_saving_usd']} ✓")
    else:
        fail("cost_saving_usd", f"{sv_tf['cost_saving_usd']} ≠ 276.0")

    sv_ann = first['savings_opportunities']['annual_projection']
    tests += 1
    if sv_ann['realistic_annual_usd'] == 189351:
        ok(f"annual_saving_usd: ${sv_ann['realistic_annual_usd']:,} ✓")
    else:
        fail("annual_saving", f"{sv_ann['realistic_annual_usd']} ≠ 189351")

    # ─── [4] Filo özeti tasarruf tutarlılığı ─────────────
    print("\n  [4] Tasarruf Tutarlılığı (Sorun 3)")

    summary = fleet.generate_fleet_summary(avg_fuel_price_usd_per_kg=0.85)

    tests += 1
    if 'error' not in summary:
        ok("Filo özeti üretildi")
    else:
        fail("Özet", summary.get('error'))
        return False

    sv = summary['savings_potential']

    # toplam yakıt tasarrufu
    expected_fuel_save = sum(f[7] for f in demo_flights)
    tests += 1
    if abs(sv['total_fuel_saving_kg'] - expected_fuel_save) < 5:
        ok(f"Toplam yakıt tasarrufu: {sv['total_fuel_saving_kg']:,} kg ✓")
    else:
        fail("Yakıt tasarrufu", f"{sv['total_fuel_saving_kg']} ≠ {expected_fuel_save}")

    # yıllık maliyet
    expected_annual = sum(f[9] for f in demo_flights)
    tests += 1
    if abs(sv['annualized_cost_saving_usd'] - expected_annual) < 10:
        ok(f"Yıllık tasarruf: ${sv['annualized_cost_saving_usd']:,} ✓")
    else:
        fail("Yıllık tasarruf", f"${sv['annualized_cost_saving_usd']:,} ≠ ${expected_annual:,}")

    # annualized_fuel_saving_tonnes tutarlı mı?
    tests += 1
    expected_fuel_tonnes = sv['annualized_cost_saving_usd'] / 0.85 / 1000
    if abs(sv['annualized_fuel_saving_tonnes'] - expected_fuel_tonnes) < 5:
        ok(f"Yıllık yakıt tasarrufu: {sv['annualized_fuel_saving_tonnes']} ton ✓")
    else:
        fail(
            "Yıllık yakıt ton",
            f"{sv['annualized_fuel_saving_tonnes']} ≠ {expected_fuel_tonnes:.1f}"
        )

    # CO2 tutarlı mı?
    tests += 1
    expected_co2_tonnes = sv['annualized_fuel_saving_tonnes'] * 3.16
    if abs(sv['annualized_co2_saving_tonnes'] - expected_co2_tonnes) < 2:
        ok(f"Yıllık CO2 azaltma: {sv['annualized_co2_saving_tonnes']} ton ✓")
    else:
        fail(
            "Yıllık CO2 ton",
            f"{sv['annualized_co2_saving_tonnes']} ≠ {expected_co2_tonnes:.1f}"
        )

    # Para ve ton arasında orantısız "67 ton → $6.1M" olmadığını doğrula
    tests += 1
    cost_per_fuel_kg = (
        sv['annualized_cost_saving_usd'] /
        (sv['annualized_fuel_saving_tonnes'] * 1000)
        if sv['annualized_fuel_saving_tonnes'] > 0 else 0
    )
    if 0.50 <= cost_per_fuel_kg <= 1.50:
        ok(
            f"Para/yakıt oranı mantıklı: ${cost_per_fuel_kg:.2f}/kg "
            f"({sv['annualized_fuel_saving_tonnes']} ton → "
            f"${sv['annualized_cost_saving_usd']:,})"
        )
    else:
        fail(
            "Para/yakıt oranı",
            f"${cost_per_fuel_kg:.2f}/kg mantıksız — "
            f"tasarruf tutarsızlığı!"
        )

    # ─── [5] CORSIA offset mantığı ───────────────────────
    print("\n  [5] CORSIA Offset Mantığı (Sorun 3)")

    corsia = fleet.generate_corsia_report("Test Airlines", 2025)

    es      = corsia['emissions_summary']
    offsets = corsia['offset_requirements']

    tests += 1
    total_co2   = es['total_co2_tonnes']
    baseline    = es['baseline_co2_tonnes']
    excess      = offsets['co2_to_offset_tonnes']
    offset_cost = offsets['estimated_offset_cost_usd']

    expected_excess = max(0, total_co2 - baseline)
    if abs(excess - expected_excess) < 1:
        ok(
            f"Offset mantıklı: {total_co2:.0f} - {baseline:.0f} = "
            f"{excess:.0f} ton (${offset_cost:,})"
        )
    else:
        fail("Offset hesabı", f"{excess} ≠ {expected_excess:.0f}")

    # Offset maliyeti = excess × carbon_price
    tests += 1
    expected_cost = round(excess * CARBON_CREDIT_PRICE_USD)
    if abs(offset_cost - expected_cost) < 10:
        ok(f"Offset maliyeti tutarlı: {excess:.1f} ton × ${CARBON_CREDIT_PRICE_USD} = ${offset_cost:,}")
    else:
        fail("Offset maliyet", f"${offset_cost:,} ≠ ${expected_cost:,}")

    # ─── [6] Benchmark ───────────────────────────────────
    print("\n  [6] Benchmark")

    bm = summary['benchmark']
    tests += 1
    if bm['rating']:
        ok(f"Rating: {bm['rating']}")
    else:
        fail("Rating", "boş")

    tests += 1
    if bm['based_on_n_flights'] > 0:
        ok(f"Benchmark {bm['based_on_n_flights']} uçuşa dayandı")
    else:
        fail("Benchmark n", "sıfır")

    # ─── [7] Boş fleet ve edge case ───────────────────────
    print("\n  [7] Edge Cases")

    empty_fleet = FleetAnalyzer()
    tests += 1
    if 'error' in empty_fleet.generate_fleet_summary():
        ok("Boş fleet → error mesajı")
    else:
        fail("Boş fleet", "hata vermeli")

    fleet.clear()
    tests += 1
    if fleet.flight_count == 0:
        ok("clear() sonrası 0 uçuş")
    else:
        fail("clear", f"{fleet.flight_count}")

    # ─── [8] repr ─────────────────────────────────────────
    tests += 1
    r = repr(fleet)
    if 'FleetAnalyzer' in r:
        ok(f"repr: {r}")
    else:
        fail("repr", r)

    # ─── SONUÇ ────────────────────────────────────────────
    print(f"\n  {'─' * 50}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print(f"\n  ❌ BAŞARISIZ:")
        for i, e in enumerate(errors, 1):
            print(f"     {i}. {e}")
        print()
        return False

    print(f"\n  ✅ TÜM TESTLER BAŞARILI\n")
    return True


if __name__ == "__main__":
    validate_fleet_analyzer()
