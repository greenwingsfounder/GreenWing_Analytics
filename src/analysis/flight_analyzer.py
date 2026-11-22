# src/analysis/flight_analyzer.py

"""
GreenWing Analytics — Tek Uçuş Analiz Motoru
═════════════════════════════════════════════

Bu dosya TEK BİR UÇUŞU baştan sona analiz eder.
Projenin tüm modüllerini bir araya getirir.

İŞ AKIŞI:
─────────
    1. Trajectory verisini al (OpenSky veya müşteri)
    2. Birimleri standartlaştır (units.py)
    3. Uçuş fazlarını belirle (phase_segmentation.py)
    4. Her faz için yakıt tüketimi hesapla (fuel_model.py)
    5. İrtifa verimliliğini analiz et
    6. Rota verimliliğini analiz et
    7. Emisyon hesapla (emission_model.py)
    8. Optimum ile karşılaştır
    9. Tasarruf fırsatlarını belirle ve önceliklendir
   10. Sonuçları döndür

ÇIKTI:
──────
    Her analiz şunları içerir:
        • Uçuş bilgileri (uçak tipi, mesafe, süre)
        • Yakıt analizi (toplam, faz bazlı dağılım)
        • İrtifa verimliliği (SAR kaybı, optimum FL)
        • Rota verimliliği (great circle sapması, holding)
        • Emisyon profili (CO2, NOx, contrail)
        • Tasarruf fırsatları (öncelikli liste, $ değerleri)
        • Yıllık projeksiyon

KULLANIM:
─────────
    from src.analysis.flight_analyzer import SingleFlightAnalyzer

    analyzer = SingleFlightAnalyzer('B738')
    result = analyzer.analyze_trajectory(trajectory_df)

    # Sonuçlar
    print(result['fuel_analysis']['estimated_total_fuel_kg'])
    print(result['savings_opportunities']['summary'])

Kaynak:
───────
    ICAO performance methodology
    BADA fuel consumption model
    FAR 25.251 (buffet margin)
"""

from __future__ import annotations
from config.settings import EI_CO2  # CORSIA: 3.16 kg CO₂/kg yakıt

import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

from src.units import Units
from src.utils import haversine_distance, calculate_initial_heading
from src.models.fuel_model import FuelModel
from src.models.emission_model import EmissionCalculator
from src.analysis.phase_segmentation import (
    FlightPhaseSegmenter,
    PHASE_GROUND_TAXI_OUT, PHASE_GROUND_TAXI_IN,
    PHASE_TAKEOFF, PHASE_INITIAL_CLIMB, PHASE_CLIMB,
    PHASE_CRUISE, PHASE_STEP_CLIMB,
    PHASE_DESCENT, PHASE_APPROACH, PHASE_LANDING,
    PHASE_HOLDING, PHASE_UNKNOWN,
)


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class SingleFlightAnalyzer:
    """
    Tek uçuş analiz motoru.

    Trajectory verisinden tam uçuş analizi üretir:
    yakıt tahmini, irtifa verimliliği, rota verimliliği,
    emisyon ve tasarruf fırsatları.

    Args:
        aircraft_type: ICAO uçak tipi kodu ('B738', 'A320', ...)
        delta_isa    : ISA sapması (°C)
        cd0_factor   : CD0 kalibrasyon çarpanı
        sfc_factor   : SFC kalibrasyon çarpanı

    Kullanım:
        analyzer = SingleFlightAnalyzer('B738')
        result = analyzer.analyze_trajectory(trajectory_df)
    """

    def __init__(
        self,
        aircraft_type: str = 'B738',
        delta_isa: float = 0.0,
        cd0_factor: float = 1.0,
        sfc_factor: float = 1.0,
    ) -> None:
        self.ac_type   = aircraft_type
        self.delta_isa = delta_isa

        self.fuel_model    = FuelModel(aircraft_type, delta_isa, cd0_factor, sfc_factor)
        self.emission_calc = EmissionCalculator()
        self.segmenter     = FlightPhaseSegmenter()

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: ANA ANALİZ
    # ──────────────────────────────────────────────────────

    def analyze_trajectory(
        self,
        trajectory_df: pd.DataFrame,
        estimated_weight_kg: Optional[float] = None,
        payload_kg: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Trajectory verisinden tam uçuş analizi yap.

        Args:
            trajectory_df      : Trajectory DataFrame
                                 Gerekli: time, latitude, longitude
                                 Opsiyonel: baro_altitude, velocity, on_ground
            estimated_weight_kg: Tahmini uçak ağırlığı (kg).
                                 None → mesafeden otomatik tahmin.
            payload_kg         : Yük ağırlığı (kg).
                                 None → varsayılan kullanılır.

        Returns:
            dict: Tam analiz sonucu veya None (başarısız)

            Yapı:
                flight_info           : uçak tipi, zaman damgası, veri noktası sayısı
                basic_metrics         : mesafe, süre, rota verimliliği
                fuel_analysis         : yakıt tahmini, faz dağılımı
                altitude_analysis     : irtifa verimliliği, SAR kaybı, step climb
                route_analysis        : rota verimliliği, holding
                emissions             : CO2, NOx, H2O, CO2/pax/km
                optimum_comparison    : gerçek vs optimum karşılaştırma
                savings_opportunities : tasarruf fırsatları listesi + yıllık projeksiyon
        """
        df = trajectory_df.copy()

        if df.empty or len(df) < 5:
            return None

        # ─── Adım 1: Standartlaştır ──────────────────────
        df = Units.standardize_trajectory(df)

        # ─── Adım 2: Fazları belirle ─────────────────────
        df = self.segmenter.segment_trajectory(df)

        # ─── Adım 3: Temel metrikler ─────────────────────
        basic_metrics = self._calculate_basic_metrics(df)

        if basic_metrics['great_circle_distance_nm'] < 1:
            return None

        # ─── Adım 4: Ağırlık tahmini ─────────────────────
        if estimated_weight_kg is None:
            estimated_weight_kg = self._estimate_weight(
                basic_metrics['great_circle_distance_nm'],
                payload_kg,
            )

        # ─── Adım 5: Yakıt tahmini ───────────────────────
        fuel_analysis = self._estimate_fuel_consumption(
            df, estimated_weight_kg, basic_metrics,
        )

        # ─── Adım 6: İrtifa analizi ──────────────────────
        altitude_analysis = self._analyze_altitude_efficiency(
            df, estimated_weight_kg,
        )

        # ─── Adım 7: Rota analizi ────────────────────────
        route_analysis = self._analyze_route_efficiency(df, basic_metrics)

        # ─── Adım 8: Emisyon ──────────────────────────────
        emissions = self.emission_calc.calculate_flight_emissions(
            fuel_burn_kg=fuel_analysis['estimated_total_fuel_kg'],
            distance_nm=basic_metrics['great_circle_distance_nm'],
            aircraft_type=self.ac_type,
            cruise_altitude_ft=altitude_analysis.get('avg_cruise_altitude_ft', 35000),
            cruise_mach=altitude_analysis.get('avg_cruise_mach', 0.78),
        )

        # ─── Adım 9: Optimum karşılaştırma ───────────────
        optimum_comparison = self._compare_with_optimum(
            basic_metrics, fuel_analysis, altitude_analysis,
            estimated_weight_kg,
        )

        # ─── Adım 10: Tasarruf fırsatları ────────────────
        savings = self._identify_savings(
            fuel_analysis, altitude_analysis,
            route_analysis, optimum_comparison,
            basic_metrics,
        )

        return {
            'flight_info': {
                'aircraft_type'      : self.ac_type,
                'aircraft_name'      : self.fuel_model.params.get('name', self.ac_type),
                'analysis_timestamp' : datetime.now().isoformat(),
                'data_points'        : len(df),
                'estimated_weight_kg': round(estimated_weight_kg),
            },
            'basic_metrics'        : basic_metrics,
            'fuel_analysis'        : fuel_analysis,
            'altitude_analysis'    : altitude_analysis,
            'route_analysis'       : route_analysis,
            'emissions'            : emissions,
            'optimum_comparison'   : optimum_comparison,
            'savings_opportunities': savings,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: TEMEL METRİKLER
    # ──────────────────────────────────────────────────────

    def _calculate_basic_metrics(self, df: pd.DataFrame) -> dict:
        """Uçuşun temel metriklerini hesapla."""

        # Kalkış ve varış noktaları
        if 'on_ground' in df.columns:
            ground = df[df['on_ground'] == True]
            if len(ground) >= 2:
                origin_lat = ground.iloc[0]['latitude']
                origin_lon = ground.iloc[0]['longitude']
                dest_lat   = ground.iloc[-1]['latitude']
                dest_lon   = ground.iloc[-1]['longitude']
            else:
                origin_lat = df.iloc[0]['latitude']
                origin_lon = df.iloc[0]['longitude']
                dest_lat   = df.iloc[-1]['latitude']
                dest_lon   = df.iloc[-1]['longitude']
        else:
            origin_lat = df.iloc[0]['latitude']
            origin_lon = df.iloc[0]['longitude']
            dest_lat   = df.iloc[-1]['latitude']
            dest_lon   = df.iloc[-1]['longitude']

        # Great circle mesafe
        gc_distance = haversine_distance(
            origin_lat, origin_lon, dest_lat, dest_lon
        )

        # Gerçek uçulan mesafe
        if 'cumulative_distance_nm' in df.columns:
            actual_distance = float(df['cumulative_distance_nm'].iloc[-1])
        elif 'segment_distance_nm' in df.columns:
            actual_distance = float(df['segment_distance_nm'].sum())
        else:
            actual_distance = gc_distance * 1.03

        if actual_distance < gc_distance:
            actual_distance = gc_distance * 1.02

        # Uçuş süresi
        if 'time' in df.columns:
            total_time = (df.iloc[-1]['time'] - df.iloc[0]['time']).total_seconds()
        elif 'time_diff_s' in df.columns:
            total_time = df['time_diff_s'].sum()
        else:
            total_time = 0

        # Rota verimliliği
        route_eff = (gc_distance / actual_distance * 100) if actual_distance > 0 else 0

        # Callsign
        callsign = ''
        if 'callsign' in df.columns:
            cs = df.iloc[0].get('callsign', '')
            if isinstance(cs, str):
                callsign = cs.strip()

        # Heading
        heading = calculate_initial_heading(
            origin_lat, origin_lon, dest_lat, dest_lon
        )

        # Faz süreleri
        phase_durations = {}
        if 'flight_phase' in df.columns and 'time_diff_s' in df.columns:
            for phase in df['flight_phase'].unique():
                mask = df['flight_phase'] == phase
                phase_durations[phase] = round(float(df.loc[mask, 'time_diff_s'].sum()) / 60, 1)

        return {
            'callsign'                : callsign,
            'origin_coords'           : (round(origin_lat, 4), round(origin_lon, 4)),
            'destination_coords'      : (round(dest_lat, 4), round(dest_lon, 4)),
            'heading_deg'             : round(heading, 1),
            'great_circle_distance_nm': round(gc_distance, 1),
            'actual_distance_nm'      : round(actual_distance, 1),
            'route_efficiency_pct'    : round(route_eff, 1),
            'extra_distance_nm'       : round(actual_distance - gc_distance, 1),
            'total_flight_time_min'   : round(total_time / 60, 1),
            'total_flight_time_hr'    : round(total_time / 3600, 2),
            'phase_durations_min'     : phase_durations,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: AĞIRLIK TAHMİNİ
    # ──────────────────────────────────────────────────────

    def _estimate_weight(
        self,
        distance_nm: float,
        payload_kg: Optional[float] = None,
    ) -> float:
        """Mesafe ve uçak tipine göre kalkış ağırlığını tahmin et."""

        params = self.fuel_model.params

        if payload_kg is None:
            max_payload = params.get('max_payload', 15000)
            payload_kg  = max_payload * 0.75

        # Yakıt tahmini (mesafe bazlı kaba tahmin)
        if distance_nm < 500:
            fuel_factor = 10
        elif distance_nm < 1500:
            fuel_factor = 8.5
        else:
            fuel_factor = 7.5

        estimated_fuel = distance_nm * fuel_factor
        # Reserve yakıt bileşenleri:
        # %5 contingency fuel (estimated_fuel × 0.05)
        # Alternate fuel: 200 Nm × fuel_factor (kg/Nm)
        # Holding reserve: 30 dakika × 2500 kg/hr (dar gövde varsayımı)
        reserve        = estimated_fuel * 0.05 + 200 * fuel_factor + 30 / 60 * 2500
        total_fuel     = min(estimated_fuel + reserve, params.get('max_fuel', 20000))

        weight = params.get('oew', 42000) + payload_kg + total_fuel
        weight = min(weight, params.get('mtow', 79000))

        return round(weight)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: YAKIT TÜKETİM TAHMİNİ
    # ──────────────────────────────────────────────────────

    def _estimate_fuel_consumption(
        self,
        df: pd.DataFrame,
        weight_kg: float,
        basic_metrics: dict,
    ) -> dict:
        """Trajectory verisinden yakıt tüketimini tahmin et."""

        total_fuel     = 0.0
        phase_fuel     = {}
        current_weight = weight_kg

        has_phase = 'flight_phase' in df.columns
        has_alt   = 'baro_altitude_ft' in df.columns
        has_time  = 'time_diff_s' in df.columns

        for i in range(1, len(df)):
            row = df.iloc[i]

            dt = float(row.get('time_diff_s', 60)) if has_time else 60
            if dt <= 0 or dt > 600:
                continue
            if dt > 600:
                dt = 600  # 10 dakikayı aşan boşlukları en fazla 10 dakika olarak kabul et (tahmin)

            alt_ft = float(row.get('baro_altitude_ft', 35000)) if has_alt else 35000
            phase  = row.get('flight_phase', PHASE_CRUISE) if has_phase else PHASE_CRUISE

            # Mach tahmini
            mach = self._estimate_mach(alt_ft, row.get('velocity_ms'))

            # Faz bazlı yakıt
            ff_kg = self.fuel_model.estimate_phase_fuel(
                phase=phase,
                duration_s=dt,
                weight_kg=current_weight,
                altitude_ft=alt_ft,
                mach=mach,
            )

            total_fuel     += ff_kg
            current_weight -= ff_kg

            # Faz bazlı toplam
            if phase not in phase_fuel:
                phase_fuel[phase] = 0
            phase_fuel[phase] += ff_kg

        # Faz yüzdeleri
        phase_fuel_pct = {}
        for phase, fuel in phase_fuel.items():
            phase_fuel_pct[phase] = {
                'fuel_kg'   : round(fuel, 1),
                'percentage': round(fuel / total_fuel * 100, 1) if total_fuel > 0 else 0,
            }

        return {
            'estimated_total_fuel_kg': round(total_fuel, 0),
            'phase_breakdown'        : phase_fuel_pct,
            'initial_weight_kg'      : round(weight_kg),
            'final_weight_kg'        : round(current_weight),
            # BÜTÜNLÜK: doğruluk yüzdesi GARANTİ EDİLMEZ. Önceki metin
            # ("±5-10%" ve "±2-3% hedeflenir") doğrulanmamış bir iddiaydı.
            # Doğruluk, veriye ve kalibrasyona bağlıdır; burada sayı verilmez.
            'accuracy_note': (
                'Fizik tabanlı tahmin (ICAO ISA + uçak tipi parametreleri). '
                'Doğruluk; trajectory verisinin çözünürlüğüne, ağırlık '
                'tahminine ve varsa QAR/FDR kalibrasyonuna bağlıdır. '
                'Sayısal bir doğruluk yüzdesi garanti edilmez; gerçek '
                'operasyonel veriyle karşılaştırma önerilir.'
            ),
        }

    def _estimate_mach(
        self,
        altitude_ft: float,
        ground_speed_ms: Optional[float] = None,
    ) -> float:
        """İrtifa ve hızdan Mach tahmini."""

        if ground_speed_ms and ground_speed_ms > 50:
            try:
                a    = Units.speed_of_sound(altitude_ft)
                mach = ground_speed_ms / a
                return max(0.60, min(0.86, mach))
            except (ValueError, ZeroDivisionError):
                pass

        return self.fuel_model.params.get('cruise_mach', 0.78)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: İRTİFA VERİMLİLİK ANALİZİ
    # ──────────────────────────────────────────────────────

    def _analyze_altitude_efficiency(
        self,
        df: pd.DataFrame,
        weight_kg: float,
        distance_nm: float = 1500,
    ) -> dict:
        """İrtifa profili verimlilik analizi."""

        # Cruise verisi
        cruise_phases = [PHASE_CRUISE, PHASE_STEP_CLIMB]

        if 'flight_phase' in df.columns:
            cruise_df = df[df['flight_phase'].isin(cruise_phases)].copy()
        else:
            if 'baro_altitude_ft' in df.columns:
                cruise_df = df[df['baro_altitude_ft'] > 20000].copy()
            else:
                return self._default_altitude_result()

        if cruise_df.empty:
            return self._default_altitude_result()

        if 'baro_altitude_ft' not in cruise_df.columns:
            return self._default_altitude_result()

        avg_alt = float(cruise_df['baro_altitude_ft'].mean())
        max_alt = float(cruise_df['baro_altitude_ft'].max())
        min_alt = float(cruise_df['baro_altitude_ft'].min())

        # Mach tahmini
        mach = self.fuel_model.params.get('cruise_mach', 0.78)

        # Optimum irtifa
        # Uçuş ortası ağırlık tahmini (mesafeye bağlı)
        # Kısa mesafede yakıt tüketimi düşük olduğu için çarpan daha yüksek
        gc_dist = distance_nm
        
        if gc_dist < 500:
            weight_factor = 0.97      # Kısa mesafe: ~%3 yakıt tüketimi
        elif gc_dist < 1000:
            weight_factor = 0.95      # Orta-kısa: ~%5 yakıt tüketimi
        elif gc_dist < 2000:
            weight_factor = 0.92      # Orta: ~%8 yakıt tüketimi
        else:
            weight_factor = 0.90      # Uzun: ~%10 yakıt tüketimi

        mid_weight = weight_kg * weight_factor
        opt_alt    = self.fuel_model.optimum_altitude(mid_weight, mach)

        # SAR karşılaştırması
        sar_actual  = self.fuel_model.specific_air_range(mid_weight, avg_alt, mach)
        sar_optimum = self.fuel_model.specific_air_range(mid_weight, opt_alt, mach)

        sar_loss_pct = (
            (sar_optimum - sar_actual) / sar_optimum * 100
        ) if sar_optimum > 0 else 0

        alt_deviation = avg_alt - opt_alt

        # Step climb tespiti
        step_climbs = FlightPhaseSegmenter.get_step_climbs_detected(df)
        step_count  = len(step_climbs)

        return {
            'avg_cruise_altitude_ft' : round(avg_alt),
            'max_cruise_altitude_ft' : round(max_alt),
            'min_cruise_altitude_ft' : round(min_alt),
            'optimum_altitude_ft'    : opt_alt,
            'altitude_deviation_ft'  : round(alt_deviation),
            'avg_cruise_mach'        : mach,
            'sar_at_actual_alt'      : round(sar_actual, 6),
            'sar_at_optimum_alt'     : round(sar_optimum, 6),
            'sar_loss_pct'           : round(max(0, sar_loss_pct), 2),
            'step_climbs_detected'   : step_count,
            'step_climb_details'     : step_climbs,
            'step_climb_recommended' : step_count == 0 and abs(alt_deviation) > 1500,
        }

    def _default_altitude_result(self) -> dict:
        """Cruise verisi yoksa varsayılan sonuç."""
        return {
            'avg_cruise_altitude_ft' : 35000,
            'max_cruise_altitude_ft' : 35000,
            'min_cruise_altitude_ft' : 35000,
            'optimum_altitude_ft'    : 35000,
            'altitude_deviation_ft'  : 0,
            'avg_cruise_mach'        : 0.78,
            'sar_at_actual_alt'      : 0,
            'sar_at_optimum_alt'     : 0,
            'sar_loss_pct'           : 0,
            'step_climbs_detected'   : 0,
            'step_climb_details'     : [],
            'step_climb_recommended' : False,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 6: ROTA VERİMLİLİK ANALİZİ
    # ──────────────────────────────────────────────────────

    def _analyze_route_efficiency(
        self,
        df: pd.DataFrame,
        basic_metrics: dict,
    ) -> dict:
        """Rota verimliliği analizi."""

        gc_dist     = basic_metrics['great_circle_distance_nm']
        actual_dist = basic_metrics['actual_distance_nm']
        extra_dist  = actual_dist - gc_dist
        efficiency  = basic_metrics['route_efficiency_pct']

        # Holding tespiti
        holdings     = FlightPhaseSegmenter.detect_holdings_detailed(df)
        holding_time = FlightPhaseSegmenter.holding_duration_minutes(df)

        # Holding yakıt tahmini — BÜTÜNLÜK: 2-kutu sabit yerine uçağın
        # kendi modelinden (HOLDING faz oranı × cruise akışı).
        holding_fuel = 0.0
        if holding_time > 0:
            _hw = self.fuel_model.params.get('oew', 42000) + 0.55 * (
                self.fuel_model.params.get('mtow', 79000)
                - self.fuel_model.params.get('oew', 42000))
            holding_fuel = self.fuel_model.estimate_phase_fuel(
                phase='HOLDING',
                duration_s=holding_time * 60,
                weight_kg=_hw,
                altitude_ft=10000,
                mach=0.45,
            )

        # Fazla mesafe yakıt maliyeti — BÜTÜNLÜK: sabit 8 kg/nm yerine
        # uçağın kendi SAR'ından marjinal yakıt.
        extra_fuel = 0.0
        if extra_dist > 5:
            _ew = self.fuel_model.params.get('oew', 42000) + 0.70 * (
                self.fuel_model.params.get('mtow', 79000)
                - self.fuel_model.params.get('oew', 42000))
            _sar = self.fuel_model.specific_air_range(
                _ew, 35000, self.fuel_model.params.get('cruise_mach', 0.78))
            extra_fuel = extra_dist / _sar if _sar > 0 else 0.0

        # Değerlendirme
        if efficiency >= 98:
            assessment = "EXCELLENT — Rota çok verimli"
        elif efficiency >= 95:
            assessment = "GOOD — Rota verimli"
        elif efficiency >= 90:
            assessment = "FAIR — Orta verimlilik, ATC kısıtları muhtemel"
        elif efficiency >= 85:
            assessment = "BELOW AVERAGE — Önemli sapma, optimizasyon potansiyeli"
        else:
            assessment = "POOR — Büyük verimsizlik, acil inceleme"

        return {
            'great_circle_distance_nm' : gc_dist,
            'actual_distance_nm'       : actual_dist,
            'extra_distance_nm'        : round(extra_dist, 1),
            'route_efficiency_pct'     : round(efficiency, 1),
            'extra_distance_fuel_kg'   : round(extra_fuel, 0),
            'holding_detected'         : len(holdings) > 0,
            'holding_count'            : len(holdings),
            'holding_duration_min'     : round(holding_time, 1),
            'holding_fuel_estimate_kg' : round(holding_fuel, 0),
            'holding_details'          : holdings,
            'assessment'               : assessment,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 7: OPTİMUM KARŞILAŞTIRMA
    # ──────────────────────────────────────────────────────

    def _compare_with_optimum(
        self,
        basic_metrics: dict,
        fuel_analysis: dict,
        altitude_analysis: dict,
        weight_kg: float,
    ) -> dict:
        """Gerçek uçuş vs optimum teorik uçuş karşılaştırması."""

        distance = basic_metrics['great_circle_distance_nm']
        mach     = altitude_analysis.get('avg_cruise_mach', 0.78)
        opt_alt  = altitude_analysis.get('optimum_altitude_ft', 37000)

        # Optimum cruise yakıtı
        optimum_result = self.fuel_model.fuel_for_distance(
            distance_nm=distance,
            weight_initial_kg=weight_kg,
            altitude_ft=opt_alt,
            mach=mach,
        )

        # BÜTÜNLÜK DÜZELTMESİ: Önceden cruise_fraction hesaplanıyor ama
        # KULLANILMIYORDU (ölü kod) ve toplam yakıt sabit /0.75 ile tahmin
        # ediliyordu. Artık mesafeye göre hesaplanan oran kullanılıyor.
        if distance < 500:
            cruise_fraction = 0.65      # Kısa mesafe
        elif distance < 1000:
            cruise_fraction = 0.70      # Orta-kısa mesafe
        elif distance < 2000:
            cruise_fraction = 0.75      # Orta mesafe
        else:
            cruise_fraction = 0.77      # Uzun mesafe

        # optimum_result sadece cruise segmentini kapsar; toplam yakıta çevir.
        estimated_total_optimum = optimum_result['total_fuel_kg'] / cruise_fraction

        actual_fuel    = fuel_analysis['estimated_total_fuel_kg']
        fuel_diff      = actual_fuel - estimated_total_optimum
        fuel_saving_pct = (fuel_diff / actual_fuel * 100) if actual_fuel > 0 else 0

        from config.assumptions import Assumptions
        _price = Assumptions.fuel_price('DEFAULT')

        return {
            'actual_estimated_fuel_kg'  : round(actual_fuel),
            'optimum_estimated_fuel_kg' : round(estimated_total_optimum),
            'fuel_difference_kg'        : round(max(0, fuel_diff)),
            'fuel_saving_potential_pct'  : round(max(0, fuel_saving_pct), 1),
            'co2_saving_potential_kg'    : round(max(0, fuel_diff) * EI_CO2),
            'cost_saving_usd'           : round(max(0, fuel_diff) * _price, 2),
            'optimum_conditions': {
                'altitude_ft': opt_alt,
                'mach'       : mach,
                'sar_nm_per_kg': round(
                    self.fuel_model.specific_air_range(weight_kg, opt_alt, mach), 6
                ),
            },
            'comparison_note': (
                'Bu karşılaştırma teorik optimum ile tahmini gerçek '
                'değerler arasındadır. Gerçek QAR verisi ile doğruluk artırılır.'
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 8: TASARRUF FIRSATLARI
    # ──────────────────────────────────────────────────────

    def _identify_savings(
        self,
        fuel_analysis: dict,
        altitude_analysis: dict,
        route_analysis: dict,
        optimum_comparison: dict,
        basic_metrics: dict,
    ) -> dict:
        """Somut tasarruf fırsatlarını belirle ve önceliklendir."""

        savings = []
        total_fuel = fuel_analysis['estimated_total_fuel_kg']

        # BÜTÜNLÜK: Yakıt fiyatı tek kaynaktan (Assumptions), sabit koda gömülü DEĞİL.
        from config.assumptions import Assumptions
        fuel_price_usd_kg = Assumptions.fuel_price('DEFAULT')

        # BÜTÜNLÜK: Fiziksel tasarruflar YALNIZCA cruise segmentine uygulanır.
        # (İrtifa/step climb cruise'da etkilidir; taxi/tırmanma/inişte değil.)
        phase_bd = fuel_analysis.get('phase_breakdown', {})
        cruise_phases = [PHASE_CRUISE, PHASE_STEP_CLIMB]
        cruise_fuel = sum(
            v.get('fuel_kg', 0) for k, v in phase_bd.items()
            if k in cruise_phases and isinstance(v, dict)
        )
        if cruise_fuel <= 0:
            # Faz dökümü yoksa muhafazakâr: cruise payını %70 varsay
            cruise_fuel = total_fuel * 0.70

        # ─── 1. İrtifa optimizasyonu ──────────────────────
        # SAR iyileşmesi cruise yakıtının AYNI yüzdesi kadar tasarruf sağlar.
        sar_loss = altitude_analysis.get('sar_loss_pct', 0)

        if sar_loss > 0.5:
            alt_dev       = altitude_analysis.get('altitude_deviation_ft', 0)
            fuel_save_alt = cruise_fuel * sar_loss / 100

            savings.append({
                'category'    : 'ALTITUDE_OPTIMIZATION',
                'priority'    : 'HIGH' if sar_loss > 2 else 'MEDIUM',
                'title'       : 'Cruise İrtifa Optimizasyonu',
                'description' : (
                    f"Ortalama cruise irtifası optimumdan "
                    f"{abs(alt_dev):.0f} ft sapıyor. "
                    f"FL{altitude_analysis.get('optimum_altitude_ft', 0)//100} "
                    f"irtifasında SAR %{sar_loss:.1f} daha iyi."
                ),
                'estimated_fuel_saving_kg' : round(fuel_save_alt),
                'estimated_co2_saving_kg'  : round(fuel_save_alt * EI_CO2),
                'estimated_cost_saving_usd': round(fuel_save_alt * fuel_price_usd_kg, 2),
                'implementation'           : 'Dispatcher briefing ile uygulanabilir',
                'difficulty'               : 'LOW',
            })

        # ─── 2. Step climb ────────────────────────────────
        # BÜTÜNLÜK: Sabit %1.5 yerine GERÇEK SAR farkı (cruise yakıtı üzerinden).
        # Step climb'ın faydası, uçuş ortasında optimum irtifaya geçiştir.
        if altitude_analysis.get('step_climb_recommended', False):
            sar_actual  = altitude_analysis.get('sar_at_actual_alt', 0)
            sar_optimum = altitude_analysis.get('sar_at_optimum_alt', 0)
            if sar_actual > 0 and sar_optimum > 0:
                # Mevcut SAR ile optimum SAR arasındaki göreli fark
                step_gain_pct = max(0.0, (sar_optimum - sar_actual) / sar_optimum * 100)
            else:
                step_gain_pct = 0.0
            # İrtifa farkıyla sınırla (fiziksel üst sınır değil, muhafazakâr tavan)
            step_gain_pct = min(step_gain_pct, 3.0)
            fuel_save_step = cruise_fuel * step_gain_pct / 100

            savings.append({
                'category'    : 'STEP_CLIMB',
                'priority'    : 'MEDIUM',
                'title'       : 'Step Climb Uygulaması',
                'description' : (
                    "Uçuş boyunca step climb yapılmamış. "
                    "Yakıt yakıldıkça optimum irtifa yükselir. "
                    "200-300 Nm aralıklarla 2000 ft step climb önerilir."
                ),
                'estimated_fuel_saving_kg' : round(fuel_save_step),
                'estimated_co2_saving_kg'  : round(fuel_save_step * EI_CO2),
                'estimated_cost_saving_usd': round(fuel_save_step * fuel_price_usd_kg, 2),
                'implementation'           : 'ATC koordinasyonu gerektirir',
                'difficulty'               : 'MEDIUM',
            })

        # ─── 3. Rota optimizasyonu ────────────────────────
        extra_dist = route_analysis.get('extra_distance_nm', 0)

        if extra_dist > 10:
            fuel_save_route = route_analysis.get('extra_distance_fuel_kg', 0)

            savings.append({
                'category'    : 'ROUTE_OPTIMIZATION',
                'priority'    : 'MEDIUM' if extra_dist < 30 else 'HIGH',
                'title'       : 'Rota Kısaltma',
                'description' : (
                    f"Uçuş, great circle rotasından {extra_dist:.0f} Nm "
                    f"fazla mesafe katetmiş (%{route_analysis.get('route_efficiency_pct', 0):.1f}). "
                    f"Direct routing talep edilmesi önerilir."
                ),
                'estimated_fuel_saving_kg' : round(fuel_save_route),
                'estimated_co2_saving_kg'  : round(fuel_save_route * EI_CO2),
                'estimated_cost_saving_usd': round(fuel_save_route * fuel_price_usd_kg, 2),
                'implementation'           : 'ATC ile direkt rota talebi',
                'difficulty'               : 'LOW',
            })

        # ─── 4. Holding kaçınma ───────────────────────────
        if route_analysis.get('holding_detected', False):
            holding_fuel = route_analysis.get('holding_fuel_estimate_kg', 0)

            savings.append({
                'category'    : 'HOLDING_AVOIDANCE',
                'priority'    : 'HIGH',
                'title'       : 'Holding Pattern Kaçınma',
                'description' : (
                    f"{route_analysis.get('holding_duration_min', 0):.0f} dakika "
                    f"holding tespit edildi. Slot yönetimi ile azaltılabilir."
                ),
                'estimated_fuel_saving_kg' : round(holding_fuel),
                'estimated_co2_saving_kg'  : round(holding_fuel * EI_CO2),
                'estimated_cost_saving_usd': round(holding_fuel * fuel_price_usd_kg, 2),
                'implementation'           : 'Operasyonel planlama iyileştirmesi',
                'difficulty'               : 'MEDIUM',
            })

        # ─── Toplam ───────────────────────────────────────
        # Çift sayım önleme: altitude ve step climb'dan büyüğünü al
        alt_saving  = next((s['estimated_fuel_saving_kg'] for s in savings
                           if s['category'] == 'ALTITUDE_OPTIMIZATION'), 0)
        step_saving = next((s['estimated_fuel_saving_kg'] for s in savings
                           if s['category'] == 'STEP_CLIMB'), 0)

        # İkisinden büyüğü + rota + holding
        fuel_optimization = max(alt_saving, step_saving)

        route_saving   = next((s['estimated_fuel_saving_kg'] for s in savings
                              if s['category'] == 'ROUTE_OPTIMIZATION'), 0)
        holding_saving = next((s['estimated_fuel_saving_kg'] for s in savings
                              if s['category'] == 'HOLDING_AVOIDANCE'), 0)

        total_fuel_saving = fuel_optimization + route_saving + holding_saving
        total_co2_saving  = total_fuel_saving * EI_CO2
        total_cost_saving = total_fuel_saving * fuel_price_usd_kg

        # Yıllık projeksiyon
        from config.assumptions import Assumptions
        annual = Assumptions.annual_projection(total_cost_saving,
                     basic_metrics['great_circle_distance_nm'])

        return {
            'opportunities': savings,
            'total_per_flight': {
                'fuel_saving_kg' : round(total_fuel_saving),
                'co2_saving_kg'  : round(total_co2_saving),
                'cost_saving_usd': round(total_cost_saving, 2),
            },
            'annual_projection': annual,
            'summary': (
                f"{len(savings)} tasarruf fırsatı tespit edildi. "
                f"Uçuş başına tahmini {total_fuel_saving:.0f} kg yakıt "
                f"(${total_cost_saving:.0f}) tasarrufu mümkün. "
                f"Yıllık gerçekçi beklenti: ${annual['realistic_annual_usd']:,}."
            ),
            'note': (
                'Altitude ve step climb tasarrufları çift sayım önlemek için '
                'büyük olanı alınmıştır. Rota ve holding tasarrufları ayrıdır.'
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 9: YARDIMCI
    # ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"SingleFlightAnalyzer('{self.ac_type}', "
            f"delta_isa={self.delta_isa})"
        )


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_flight_analyzer() -> bool:
    """
    Flight Analyzer doğrulama testleri.

    Simüle trajectory ile tam analiz döngüsünü test eder.

    Çalıştırma:
        python -m src.analysis.flight_analyzer
    """
    print("\n" + "=" * 60)
    print("  FLIGHT_ANALYZER.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
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

    # ─── Simüle trajectory ────────────────────────────────
    def make_trajectory(n=200):
        """IST→LON benzeri simüle uçuş."""
        data = {
            'time'          : pd.date_range('2025-01-20 10:00', periods=n, freq='60s'),
            'latitude'      : np.zeros(n),
            'longitude'     : np.zeros(n),
            'baro_altitude' : np.zeros(n),
            'velocity'      : np.zeros(n),
            'on_ground'     : np.zeros(n, dtype=bool),
        }

        for i in range(n):
            frac = i / n

            if i < 10:
                data['baro_altitude'][i] = 100
                data['velocity'][i]      = 5
                data['on_ground'][i]     = True
                data['latitude'][i]      = 41.275 + i * 0.001
                data['longitude'][i]     = 28.752
            elif i < 15:
                f = (i - 10) / 5
                data['baro_altitude'][i] = 100 + f * 1400
                data['velocity'][i]      = 100 + f * 100
                data['latitude'][i]      = 41.280 + f * 0.02
                data['longitude'][i]     = 28.755 + f * 0.02
            elif i < 25:
                f = (i - 15) / 10
                data['baro_altitude'][i] = 1500 + f * 8500
                data['velocity'][i]      = 200
                data['latitude'][i]      = 41.30 + f * 0.5
                data['longitude'][i]     = 28.77 + f * 0.5
            elif i < 50:
                f = (i - 25) / 25
                data['baro_altitude'][i] = 10000 + f * 668
                data['velocity'][i]      = 230
                data['latitude'][i]      = 41.80 + f * 2.0
                data['longitude'][i]     = 29.27 - f * 5.0
            elif i < 150:
                f = (i - 50) / 100
                data['baro_altitude'][i] = 10668 + np.random.normal(0, 5)
                data['velocity'][i]      = 230 + np.random.normal(0, 2)
                data['latitude'][i]      = 43.80 + f * 7.67
                data['longitude'][i]     = 24.27 - f * 24.72
            elif i < 175:
                f = (i - 150) / 25
                data['baro_altitude'][i] = 10668 * (1 - f)
                data['velocity'][i]      = 200 - f * 50
                data['latitude'][i]      = 51.47 - f * 0.3
                data['longitude'][i]     = -0.45 + f * 0.1
            elif i < 190:
                f = (i - 175) / 15
                data['baro_altitude'][i] = 10668 * 0.0 + (1 - f) * 3000
                data['velocity'][i]      = 120 - f * 50
                data['latitude'][i]      = 51.47
                data['longitude'][i]     = -0.45
            elif i == 190:
                data['baro_altitude'][i] = 25
                data['velocity'][i]      = 30
                data['on_ground'][i]     = True
                data['latitude'][i]      = 51.470
                data['longitude'][i]     = -0.454
            else:
                data['baro_altitude'][i] = 25
                data['velocity'][i]      = 5
                data['on_ground'][i]     = True
                data['latitude'][i]      = 51.470
                data['longitude'][i]     = -0.454

        df = pd.DataFrame(data)
        df['callsign'] = 'PGT1234'
        return df

    # ─── [1] Oluşturma ───────────────────────────────────
    print("\n  [1] Analyzer Oluşturma")

    analyzer = SingleFlightAnalyzer('B738')
    tests += 1
    if isinstance(analyzer, SingleFlightAnalyzer):
        ok(f"Oluşturuldu: {repr(analyzer)}")
    else:
        fail("oluşturma", "başarısız")
        return False

    # ─── [2] Tam analiz ───────────────────────────────────
    print("\n  [2] Tam Analiz")

    traj   = make_trajectory()
    result = analyzer.analyze_trajectory(traj)

    tests += 1
    if result is not None:
        ok("Analiz tamamlandı")
    else:
        fail("Analiz", "None döndü")
        return False

    # ─── [3] Flight info ──────────────────────────────────
    print("\n  [3] Uçuş Bilgisi")

    fi = result['flight_info']

    tests += 1
    if fi['aircraft_type'] == 'B738':
        ok(f"Uçak tipi: {fi['aircraft_type']}")
    else:
        fail("Uçak tipi", fi['aircraft_type'])

    tests += 1
    if fi['data_points'] == 200:
        ok(f"Veri noktası: {fi['data_points']}")
    else:
        fail("Veri noktası", f"{fi['data_points']}")

    tests += 1
    if fi['estimated_weight_kg'] > 50000:
        ok(f"Tahmini ağırlık: {fi['estimated_weight_kg']:,} kg")
    else:
        fail("Ağırlık", f"çok düşük: {fi['estimated_weight_kg']}")

    # ─── [4] Temel metrikler ──────────────────────────────
    print("\n  [4] Temel Metrikler")

    bm = result['basic_metrics']

    tests += 1
    if bm['great_circle_distance_nm'] > 100:
        ok(f"GC mesafe: {bm['great_circle_distance_nm']} Nm")
    else:
        fail("GC mesafe", f"çok kısa: {bm['great_circle_distance_nm']}")

    tests += 1
    if 80 <= bm['route_efficiency_pct'] <= 100:
        ok(f"Rota verimliliği: %{bm['route_efficiency_pct']}")
    else:
        fail("Rota verimliliği", f"%{bm['route_efficiency_pct']}")

    tests += 1
    if bm['total_flight_time_min'] > 0:
        ok(f"Uçuş süresi: {bm['total_flight_time_min']:.0f} dk")
    else:
        fail("Uçuş süresi", "sıfır")

    tests += 1
    if bm['callsign'] == 'PGT1234':
        ok(f"Callsign: {bm['callsign']}")
    else:
        fail("Callsign", bm['callsign'])

    # ─── [5] Yakıt analizi ────────────────────────────────
    print("\n  [5] Yakıt Analizi")

    fa = result['fuel_analysis']

    tests += 1
    if fa['estimated_total_fuel_kg'] > 0:
        ok(f"Toplam yakıt: {fa['estimated_total_fuel_kg']:,.0f} kg")
    else:
        fail("Yakıt", "sıfır")

    tests += 1
    if fa['phase_breakdown']:
        phases = list(fa['phase_breakdown'].keys())
        ok(f"Faz dağılımı: {len(phases)} faz")
    else:
        fail("Faz dağılımı", "boş")

    tests += 1
    if fa['initial_weight_kg'] > fa['final_weight_kg']:
        ok(f"Ağırlık azaldı: {fa['initial_weight_kg']:,} → {fa['final_weight_kg']:,} kg")
    else:
        fail("Ağırlık", "azalmadı (yakıt yakılmamış?)")

    # ─── [6] İrtifa analizi ───────────────────────────────
    print("\n  [6] İrtifa Analizi")

    aa = result['altitude_analysis']

    tests += 1
    if aa['avg_cruise_altitude_ft'] > 10000:
        ok(f"Cruise irtifa: FL{aa['avg_cruise_altitude_ft']/100:.0f}")
    else:
        fail("Cruise irtifa", f"çok düşük: {aa['avg_cruise_altitude_ft']}")

    tests += 1
    if aa['sar_loss_pct'] >= 0:
        ok(f"SAR kaybı: %{aa['sar_loss_pct']}")
    else:
        fail("SAR kaybı", "negatif")

    # ─── [7] Rota analizi ─────────────────────────────────
    print("\n  [7] Rota Analizi")

    ra = result['route_analysis']

    tests += 1
    if ra['assessment']:
        ok(f"Değerlendirme: {ra['assessment']}")
    else:
        fail("Değerlendirme", "boş")

    # ─── [8] Emisyon ──────────────────────────────────────
    print("\n  [8] Emisyon")

    em = result['emissions']

    tests += 1
    if em['emissions']['CO2_kg'] > 0:
        ok(f"CO2: {em['emissions']['CO2_kg']:,.0f} kg")
    else:
        fail("CO2", "sıfır")

    tests += 1
    expected_co2 = fa['estimated_total_fuel_kg'] * EI_CO2
    if abs(em['emissions']['CO2_kg'] - expected_co2) < 100:
        ok(f"CO2 = fuel × EI_CO2 tutarlı")
    else:
        fail("CO2 tutarlılık", f"{em['emissions']['CO2_kg']} ≠ {expected_co2:.0f}")

    # ─── [9] Tasarruf fırsatları ──────────────────────────
    print("\n  [9] Tasarruf Fırsatları")

    sv = result['savings_opportunities']

    tests += 1
    if sv['total_per_flight']['fuel_saving_kg'] >= 0:
        ok(f"Toplam tasarruf: {sv['total_per_flight']['fuel_saving_kg']} kg")
    else:
        fail("Tasarruf", "negatif")

    tests += 1
    if sv['summary']:
        ok(f"Özet: {sv['summary'][:60]}...")
    else:
        fail("Özet", "boş")

    tests += 1
    if 'note' in sv:
        ok("Çift sayım notu var")
    else:
        fail("Not", "çift sayım notu eksik")

    # ─── [10] Boş veri ────────────────────────────────────
    print("\n  [10] Edge Cases")

    empty_result = analyzer.analyze_trajectory(pd.DataFrame())
    tests += 1
    if empty_result is None:
        ok("Boş DataFrame → None")
    else:
        fail("Boş DataFrame", "None dönmeli")

    short_df = pd.DataFrame({
        'latitude': [41.27, 41.28],
        'longitude': [28.75, 28.76],
    })
    short_result = analyzer.analyze_trajectory(short_df)
    tests += 1
    if short_result is None:
        ok("2 satır → None (minimum 5)")
    else:
        fail("Kısa veri", "None dönmeli")

    # ─── [11] Farklı uçak tipi ───────────────────────────
    print("\n  [11] Farklı Uçak Tipi")

    tests += 1
    try:
        analyzer_a320 = SingleFlightAnalyzer('A320')
        result_a320   = analyzer_a320.analyze_trajectory(traj)
        if result_a320 and result_a320['flight_info']['aircraft_type'] == 'A320':
            ok("A320 analizi çalışıyor")
        else:
            fail("A320", "None veya yanlış tip")
    except Exception as e:
        fail("A320", str(e))

    # ─── [12] repr ────────────────────────────────────────
    tests += 1
    r = repr(analyzer)
    if 'SingleFlightAnalyzer' in r:
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
    validate_flight_analyzer()

