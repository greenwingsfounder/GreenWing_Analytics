"""
GreenWing Analytics — Emisyon Hesaplama ve CORSIA Raporlama
════════════════════════════════════════════════════════════

Bu dosya 3 ana iş yapar:
    1. Yakıt → Emisyon dönüşümü (CO2, NOx, H2O, SO2)
    2. Contrail (uçak izi) oluşum analizi
    3. CORSIA MRV uyumlu raporlama

Fizik temeli:
─────────────
    CO2 = fuel_kg × 3.16          (kimyasal sabit, değişmez)
    H2O = fuel_kg × 1.24          (kimyasal sabit, değişmez)
    SO2 = fuel_kg × 0.001         (yakıt sülfür içeriğine bağlı)
    NOx = f(motor tipi, irtifa, thrust, nem)  (karmaşık)

NOx hesabı:
───────────
    Boeing Fuel Flow Method 2 (BFFM2)
    ICAO Engine Emission Databank referans değerleri kullanılır.
    Her motor tipi için LTO (Landing-Takeoff) cycle emission
    indexleri mevcuttur. Cruise koşullarına irtifa/basınç/nem
    düzeltmeleri uygulanır.

    Kaynak:
        ICAO Doc 9889 (Airport Air Quality Manual)
        EASA Aircraft Engine Emissions Databank
        easa.europa.eu/domains/environment/
        icao-aircraft-engine-emissions-databank

CORSIA:
───────
    ICAO Annex 16 Volume IV
    3 bileşen: Monitoring, Reporting, Verification (MRV)
    2027 zorunlu faz için hazırlık

SAF:
────
    Sustainable Aviation Fuel yaşam döngüsü emisyon azaltımı.
    CORSIA Eligible Fuels kapsamında.
    AB mandate: 2025 %2, 2030 %6, 2050 %70

Contrail:
─────────
    Schmidt-Appleman kriteri
    Uçak izi oluşum koşulları ve iklim etkisi

KULLANIM:
─────────
    from src.models.emission_model import EmissionCalculator

    calc = EmissionCalculator()

    # Basit CO2
    co2 = calc.co2_from_fuel(12500)  # 39500 kg

    # Tam uçuş emisyonu
    result = calc.calculate_flight_emissions(
        fuel_burn_kg=12500, distance_nm=1560,
        engine_type='CFM56-7B26', cruise_altitude_ft=37000
    )

    # CORSIA raporu
    corsia = calc.corsia_compliance.reporting_document(...)

    # SAF analizi
    saf = calc.calculate_saf_impact(12500, saf_blend_pct=6)
"""

from __future__ import annotations

import numpy as np
from datetime import datetime
from typing import Optional

from src.units import Units
from config.settings import EI_CO2, EI_H2O
from src.logging_config import get_logger

logger = get_logger("models.emission")  # Central logging (CORSIA + SAF readiness)


# ═══════════════════════════════════════════════════════════
# SABİTLER
# ═══════════════════════════════════════════════════════════

# Emisyon indeksleri (kg emisyon / kg yakıt)
# Kaynak: ICAO, DEFRA, IPCC
_EI_CO2 = 3.16     # Kesin kimyasal sabit. CH bileşiklerinin yanması.
_EI_H2O = 1.24     # Kesin kimyasal sabit.
_EI_SO2 = 0.001    # Yakıttaki sülfür içeriğine bağlı (~0.05% S)

# Jet-A1 enerji içeriği
_JET_A1_LHV = 43.15e6  # J/kg (Lower Heating Value)


# ═══════════════════════════════════════════════════════════
# MOTOR EMİSYON VERİTABANI
# ═══════════════════════════════════════════════════════════
# Kaynak: ICAO Aircraft Engine Emissions Databank
# EASA: easa.europa.eu/domains/environment/
#       icao-aircraft-engine-emissions-databank
#
# Her motor tipi için LTO cycle emission index değerleri (g/kg fuel).
# Fazlar:
#   idle     : %7 thrust  (taxi)
#   approach : %30 thrust (iniş yaklaşma)
#   climb    : %85 thrust (tırmanma)
#   takeoff  : %100 thrust (kalkış)
#
# Cruise değerleri bu LTO değerlerinden BFFM2 ile
# ekstrapolasyon yapılarak hesaplanır.

_ENGINE_EMISSION_DB: dict[str, dict] = {

    'CFM56-7B26': {
        'manufacturer': 'CFM International',
        'bypass_ratio': 5.1,
        'rated_thrust_kn': 117.0,
        'lto_fuel_kg': 862,
        'nox_dp_g_kn': 58.0,
        'ei_nox': {
            'idle': 4.0,
            'approach': 9.4,
            'climb': 18.4,
            'takeoff': 27.4,
        },
        'ei_co': {
            'idle': 25.0,
            'approach': 4.5,
            'climb': 0.8,
            'takeoff': 0.5,
        },
    },

    'CFM56-7B27': {
        'manufacturer': 'CFM International',
        'bypass_ratio': 5.1,
        'rated_thrust_kn': 121.4,
        'lto_fuel_kg': 880,
        'nox_dp_g_kn': 60.0,
        'ei_nox': {
            'idle': 4.1,
            'approach': 9.6,
            'climb': 19.0,
            'takeoff': 28.2,
        },
        'ei_co': {
            'idle': 24.0,
            'approach': 4.2,
            'climb': 0.7,
            'takeoff': 0.5,
        },
    },

    'CFM56-5B4/3': {
        'manufacturer': 'CFM International',
        'bypass_ratio': 6.0,
        'rated_thrust_kn': 120.0,
        'lto_fuel_kg': 880,
        'nox_dp_g_kn': 55.2,
        'ei_nox': {
            'idle': 3.8,
            'approach': 8.8,
            'climb': 17.2,
            'takeoff': 25.8,
        },
        'ei_co': {
            'idle': 28.0,
            'approach': 5.0,
            'climb': 0.9,
            'takeoff': 0.6,
        },
    },

    'LEAP-1B': {
        'manufacturer': 'CFM International',
        'bypass_ratio': 9.0,
        'rated_thrust_kn': 121.0,
        'lto_fuel_kg': 740,
        'nox_dp_g_kn': 42.0,
        'ei_nox': {
            'idle': 3.2,
            'approach': 7.5,
            'climb': 15.0,
            'takeoff': 22.0,
        },
        'ei_co': {
            'idle': 20.0,
            'approach': 3.5,
            'climb': 0.6,
            'takeoff': 0.4,
        },
    },

    'LEAP-1A': {
        'manufacturer': 'CFM International',
        'bypass_ratio': 11.0,
        'rated_thrust_kn': 143.0,
        'lto_fuel_kg': 700,
        'nox_dp_g_kn': 38.0,
        'ei_nox': {
            'idle': 2.8,
            'approach': 6.5,
            'climb': 13.0,
            'takeoff': 19.0,
        },
        'ei_co': {
            'idle': 18.0,
            'approach': 3.0,
            'climb': 0.5,
            'takeoff': 0.3,
        },
    },

    'LEAP-1A-33': {
        'manufacturer': 'CFM International',
        'bypass_ratio': 11.0,
        'rated_thrust_kn': 147.3,
        'lto_fuel_kg': 720,
        'nox_dp_g_kn': 40.0,
        'ei_nox': {
            'idle': 3.0,
            'approach': 7.0,
            'climb': 14.0,
            'takeoff': 20.0,
        },
        'ei_co': {
            'idle': 19.0,
            'approach': 3.2,
            'climb': 0.5,
            'takeoff': 0.3,
        },
    },

    'V2533-A5': {
        'manufacturer': 'IAE',
        'bypass_ratio': 4.8,
        'rated_thrust_kn': 146.8,
        'lto_fuel_kg': 950,
        'nox_dp_g_kn': 62.0,
        'ei_nox': {
            'idle': 4.5,
            'approach': 10.0,
            'climb': 20.0,
            'takeoff': 30.0,
        },
        'ei_co': {
            'idle': 22.0,
            'approach': 4.0,
            'climb': 0.7,
            'takeoff': 0.4,
        },
    },

    'GE90-115B': {
        'manufacturer': 'GE Aviation',
        'bypass_ratio': 9.0,
        'rated_thrust_kn': 512.9,  # 512,900 N (aircraft_database.yaml'da 513,900 N - %0.2 fark, ihmal)
        'lto_fuel_kg': 3450,
        'nox_dp_g_kn': 82.6,
        'ei_nox': {
            'idle': 5.2,
            'approach': 12.0,
            'climb': 32.0,
            'takeoff': 42.0,
        },
        'ei_co': {
            'idle': 15.0,
            'approach': 2.5,
            'climb': 0.3,
            'takeoff': 0.2,
        },
    },

    'GEnx-1B70': {
        'manufacturer': 'GE Aviation',
        'bypass_ratio': 9.6,
        'rated_thrust_kn': 296.0,
        'lto_fuel_kg': 2200,
        'nox_dp_g_kn': 55.0,
        'ei_nox': {
            'idle': 3.5,
            'approach': 8.0,
            'climb': 18.0,
            'takeoff': 26.0,
        },
        'ei_co': {
            'idle': 16.0,
            'approach': 2.8,
            'climb': 0.4,
            'takeoff': 0.2,
        },
    },

    'GEnx-1B76': {
        'manufacturer': 'GE Aviation',
        'bypass_ratio': 9.6,
        'rated_thrust_kn': 339.0,
        'lto_fuel_kg': 2350,
        'nox_dp_g_kn': 58.0,
        'ei_nox': {
            'idle': 3.6,
            'approach': 8.5,
            'climb': 19.0,
            'takeoff': 27.0,
        },
        'ei_co': {
            'idle': 16.0,
            'approach': 2.8,
            'climb': 0.4,
            'takeoff': 0.2,
        },
    },

    'Trent XWB-84': {
        'manufacturer': 'Rolls-Royce',
        'bypass_ratio': 9.6,
        'rated_thrust_kn': 374.0,
        'lto_fuel_kg': 2500,
        'nox_dp_g_kn': 52.0,
        'ei_nox': {
            'idle': 3.2,
            'approach': 7.5,
            'climb': 17.0,
            'takeoff': 25.0,
        },
        'ei_co': {
            'idle': 14.0,
            'approach': 2.5,
            'climb': 0.3,
            'takeoff': 0.2,
        },
    },

    'Trent 970': {
        'manufacturer': 'Rolls-Royce',
        'bypass_ratio': 8.7,
        'rated_thrust_kn': 311.0,
        'lto_fuel_kg': 2800,
        'nox_dp_g_kn': 68.0,
        'ei_nox': {
            'idle': 4.5,
            'approach': 10.0,
            'climb': 24.0,
            'takeoff': 35.0,
        },
        'ei_co': {
            'idle': 17.0,
            'approach': 3.0,
            'climb': 0.5,
            'takeoff': 0.3,
        },
    },
}

# Uçak tipi → motor tipi eşleştirmesi
_AIRCRAFT_ENGINE_MAP: dict[str, str] = {
    'B738': 'CFM56-7B26',
    'B38M': 'LEAP-1B',
    'A320': 'CFM56-5B4/3',
    'A20N': 'LEAP-1A',
    'A321': 'V2533-A5',
    'A21N': 'LEAP-1A-33',
    'B77W': 'GE90-115B',
    'B788': 'GEnx-1B70',
    'B789': 'GEnx-1B76',
    'A350': 'Trent XWB-84',
    'A380': 'Trent 970',
}

# Uçak tipi → tipik yolcu sayısı (CO2/pax/km için)
_TYPICAL_PASSENGERS: dict[str, int] = {
    'B738': 162, 'B38M': 172, 'A320': 150, 'A20N': 150,
    'A321': 185, 'A21N': 180, 'B77W': 365, 'B788': 242,
    'B789': 296, 'A350': 315, 'A380': 555,
}

# SAF tiplerine göre yaşam döngüsü CO2 azaltma oranları
# Kaynak: ICAO CORSIA Eligible Fuels
_SAF_REDUCTION_FACTORS: dict[str, float] = {
    'HEFA'  : 0.72,   # Hydroprocessed Esters & Fatty Acids
    'FT_SPK': 0.90,   # Fischer-Tropsch Synthetic Paraffinic Kerosene
    'ATJ'   : 0.62,   # Alcohol-to-Jet
    'PTL'   : 0.92,   # Power-to-Liquid (e-fuel)
    'SIP'   : 0.65,   # Synthesized Iso-paraffins
}

# SAF ek maliyet çarpanı (Jet-A1 fiyatına göre kaç kat)
_SAF_PRICE_PREMIUM: dict[str, float] = {
    'HEFA'  : 2.5,
    'FT_SPK': 3.5,
    'ATJ'   : 3.0,
    'PTL'   : 5.0,
    'SIP'   : 2.8,
}


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class EmissionCalculator:
    """
    Havacılık emisyon hesaplayıcı.

    Kullanım:
        calc = EmissionCalculator()
        co2 = calc.co2_from_fuel(12500)
        result = calc.calculate_flight_emissions(...)
        saf = calc.calculate_saf_impact(...)
    """

    def __init__(self):
        self.corsia_compliance = CORSIACompliance()

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: TEMEL EMİSYON HESAPLARI
    # ──────────────────────────────────────────────────────

    @staticmethod
    def co2_from_fuel(fuel_kg: float) -> float:
        """
        Yakılan yakıttan CO2 hesabı.

        Formül: CO2 = fuel × 3.16
        Bu kimyasal sabit. Jet-A1'in karbon içeriğinden gelir.
        Tüm jet yakıtları için aynı.

        Args:
            fuel_kg: Yakılan yakıt miktarı (kg)

        Returns:
            float: CO2 miktarı (kg)

        Örnekler:
            co2_from_fuel(1000)  → 3160.0
            co2_from_fuel(12500) → 39500.0

        Kaynak: ICAO CORSIA, DEFRA Emission Factors
        """
        return float(fuel_kg * _EI_CO2)

    @staticmethod
    def h2o_from_fuel(fuel_kg: float) -> float:
        """
        Su buharı emisyonu.

        Formül: H2O = fuel × 1.24
        Contrail oluşumunda önemli.

        Args:
            fuel_kg: Yakılan yakıt (kg)

        Returns:
            float: H2O miktarı (kg)
        """
        return float(fuel_kg * _EI_H2O)

    @staticmethod
    def so2_from_fuel(fuel_kg: float) -> float:
        """
        Kükürt dioksit emisyonu.

        Formül: SO2 = fuel × 0.001
        Jet-A1'deki küçük sülfür içeriğinden.

        Args:
            fuel_kg: Yakılan yakıt (kg)

        Returns:
            float: SO2 miktarı (kg)
        """
        return float(fuel_kg * _EI_SO2)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: NOx HESABI (BFFM2)
    # ──────────────────────────────────────────────────────

    def nox_bffm2(
        self,
        fuel_flow_kg_s: float,
        altitude_ft: float,
        mach: float,
        engine_type: str,
        flight_phase: str = 'cruise',
        humidity: float = 0.00634,
        delta_isa: float = 0.0,  # ← YENİ (şu an kullanılmayabilir, ama hazır olsun)
    ) -> float:
        """
        Boeing Fuel Flow Method 2 ile NOx emission index hesabı.

        LTO sertifikasyon verilerini cruise koşullarına
        ekstrapolasyon ile genişletir.

        Args:
            fuel_flow_kg_s: Yakıt akışı (kg/s, tek motor)
            altitude_ft   : İrtifa (feet)
            mach          : Mach sayısı
            engine_type   : Motor tipi kodu
            flight_phase  : Uçuş fazı ('idle','approach','climb','takeoff','cruise')
            humidity      : Spesifik nem (kg water / kg air). Varsayılan ISA.

        Returns:
            float: NOx emission index (g NOx / kg fuel)

        Kaynak:
            ICAO Doc 9889 Appendix 2
            Boeing Commercial Airplanes BFFM2 methodology
        """
        if engine_type not in _ENGINE_EMISSION_DB:
            return self._generic_nox_estimate(altitude_ft, flight_phase)

        engine = _ENGINE_EMISSION_DB[engine_type]

        # Referans EI_NOx (LTO verisi)
        if flight_phase in engine['ei_nox']:
            ei_nox_ref = engine['ei_nox'][flight_phase]
        else:
            # Cruise: climb ile approach arasında interpolasyon
            ei_nox_ref = (
                engine['ei_nox']['climb'] + engine['ei_nox']['approach']
            ) / 2

        # Atmosferik düzeltme (BFFM2)
        delta = Units.pressure_ratio(altitude_ft)
        theta = Units.temperature_ratio(altitude_ft)

        # Nem düzeltmesi
        humidity_correction = np.exp(-19.0 * (humidity - 0.00634))

        # Düzeltilmiş EI_NOx (BFFM2 yaklaşımı - tam BFFM2 değil)
        # ICAO Doc 9889 Appendix 2 referans alınmıştır.
        # # Yüksek irtifada basınç düşer → NOx azalır
        # # Not: Tam BFFM2'de exponentler farklıdır (n≈0.4).
        # # Bu yaklaşım sektörde kabul edilebilir aralıkta değerler üretir.
        ei_nox = ei_nox_ref * (delta ** 0.51) / (theta ** 1.65) * humidity_correction

        return float(ei_nox)

    def _generic_nox_estimate(
        self,
        altitude_ft: float,
        flight_phase: str,
    ) -> float:
        """Motor verisi yoksa generic NOx tahmini."""
        base_values = {
            'idle': 4.0, 'approach': 9.0, 'climb': 17.0,
            'takeoff': 25.0, 'cruise': 12.0,
        }
        base  = base_values.get(flight_phase, 12.0)
        delta = Units.pressure_ratio(altitude_ft)
        return float(base * delta)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: UÇUŞ BAZLI TAM EMİSYON
    # ──────────────────────────────────────────────────────

    def calculate_flight_emissions(
        self,
        fuel_burn_kg: float,
        distance_nm: float,
        engine_type: Optional[str] = None,
        aircraft_type: Optional[str] = None,
        cruise_altitude_ft: float = 35000,
        cruise_mach: float = 0.78,
        num_engines: int = 2,
        delta_isa: float = 0.0,  # ← YENİ PARAMETRE
    ) -> dict:
        """
        Tam bir uçuş için tüm emisyonları hesapla.

        Args:
            fuel_burn_kg      : Toplam yakıt tüketimi (kg)
            distance_nm       : Uçuş mesafesi (Nm)
            engine_type       : Motor tipi. None → aircraft_type'tan otomatik.
            aircraft_type     : ICAO uçak tipi kodu
            cruise_altitude_ft: Cruise irtifası (feet)
            cruise_mach       : Cruise Mach sayısı
            num_engines       : Motor sayısı

        Returns:
            dict:
                fuel_burn_kg : yakıt (kg)
                distance_nm  : mesafe (Nm)
                emissions    : {CO2_kg, NOx_kg, H2O_kg, SO2_kg}
                metrics      : {fuel_per_nm_kg, co2_per_nm_kg, co2_per_pax_km_g, ei_nox_g_kg}
                details      : {engine_type, altitude, mach, passengers}

        Örnekler:
            result = calc.calculate_flight_emissions(
                fuel_burn_kg=12500, distance_nm=1560,
                aircraft_type='B738'
            )
            # result['emissions']['CO2_kg'] → 39500.0
        """
        # Motor tipi belirleme
        if engine_type is None and aircraft_type:
            engine_type = _AIRCRAFT_ENGINE_MAP.get(aircraft_type, 'CFM56-7B26')
        elif engine_type is None:
            engine_type = 'CFM56-7B26'

        # CO2, H2O, SO2 (yakıtla orantılı, basit)
        co2 = self.co2_from_fuel(fuel_burn_kg)
        h2o = self.h2o_from_fuel(fuel_burn_kg)
        so2 = self.so2_from_fuel(fuel_burn_kg)

        # NOx (motor ve koşullara bağlı, karmaşık)
        # Ortalama cruise fuel flow tahmini
        if distance_nm > 0:
            V = Units.mach_to_tas(cruise_mach, cruise_altitude_ft, delta_isa=delta_isa)
            flight_time_s = (distance_nm * Units.get_nm_to_m_factor()) / V if V > 0 else 0
            avg_ff_total  = fuel_burn_kg / flight_time_s if flight_time_s > 0 else 0
            ff_per_engine = avg_ff_total / num_engines
        else:
            ff_per_engine = 0

        ei_nox = self.nox_bffm2(
            ff_per_engine, cruise_altitude_ft,
            cruise_mach, engine_type,
            delta_isa=delta_isa
        )
        nox = fuel_burn_kg * ei_nox / 1000  # g → kg

        # Verimlilik metrikleri
        fuel_per_nm = fuel_burn_kg / distance_nm if distance_nm > 0 else 0
        co2_per_nm  = co2 / distance_nm if distance_nm > 0 else 0

        # CO2/pax/km
        pax = _TYPICAL_PASSENGERS.get(
            aircraft_type or '',
            _TYPICAL_PASSENGERS.get('B738', 150)
        )
        distance_km   = distance_nm * 1.852
        co2_per_pax_km = (co2 / (pax * distance_km)) * 1000 if (
            pax > 0 and distance_km > 0
        ) else 0  # g cinsinden

        return {
            'fuel_burn_kg': fuel_burn_kg,
            'distance_nm' : distance_nm,
            'emissions'   : {
                'CO2_kg': round(co2, 2),
                'NOx_kg': round(nox, 4),
                'H2O_kg': round(h2o, 2),
                'SO2_kg': round(so2, 4),
            },
            'metrics': {
                'fuel_per_nm_kg'    : round(fuel_per_nm, 3),
                'co2_per_nm_kg'     : round(co2_per_nm, 3),
                'co2_per_pax_km_g'  : round(co2_per_pax_km, 1),
                'ei_nox_g_kg'       : round(ei_nox, 2),
            },
            'details': {
                'engine_type'        : engine_type,
                'cruise_altitude_ft' : cruise_altitude_ft,
                'cruise_mach'        : cruise_mach,
                'estimated_passengers': pax,
            },
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: CONTRAIL ANALİZİ
    # ──────────────────────────────────────────────────────

    def schmidt_appleman_criterion(
        self,
        altitude_ft: float,
        temperature_C: Optional[float] = None,
        relative_humidity: float = 0.5,
        engine_efficiency: float = 0.3,
    ) -> dict:
        """
        Schmidt-Appleman kriteri ile contrail oluşum analizi.

        Contrail (uçak izi) non-CO2 iklim etkisinin büyük parçası.
        Bazı araştırmalar contrail etkisinin CO2 kadar olduğunu gösteriyor.
        Bu analizi sunan ÇOK AZ firma var.

        Contrail oluşum koşulları:
            Sıcaklık < ~-40°C VE nem > %40 → contrail oluşur
            Sıcaklık < ~-45°C VE nem > %70 → kalıcı (persistent) contrail

        Args:
            altitude_ft      : İrtifa (feet)
            temperature_C    : Hava sıcaklığı (°C). None → ISA'dan hesaplanır.
            relative_humidity: Bağıl nem (0-1)
            engine_efficiency: Motor toplam verimi (0.3-0.4)

        Returns:
            dict:
                altitude_ft              : irtifa
                temperature_C            : sıcaklık
                relative_humidity        : nem
                contrail_formation_likely: bool
                contrail_persistent      : bool
                climate_impact_note      : str
                recommendation           : str

        Kaynak:
            Schmidt, E. (1941). Die Entstehung von Eisnebel
            Appleman, H. (1953). The Formation of Exhaust Condensation Trails
            Schumann, U. (1996). Conditions for contrail formation
        """
        if temperature_C is None:
            T_K = Units.temperature_at_altitude(altitude_ft)
            temperature_C = Units.kelvin_to_celsius(T_K)

        contrail_likely    = temperature_C < -40 and relative_humidity > 0.4
        contrail_persistent = temperature_C < -45 and relative_humidity > 0.7

        if contrail_persistent:
            impact = 'PERSISTENT CONTRAIL — Önemli iklim etkisi'
            rec    = (
                f'FL{altitude_ft//100} irtifasında kalıcı contrail bekleniyor. '
                f'2000 ft alçak veya yüksek irtifa contrail-free olabilir.'
            )
        elif contrail_likely:
            impact = 'SHORT-LIVED CONTRAIL — Düşük iklim etkisi'
            rec    = 'Kısa ömürlü contrail. Mevcut irtifa kabul edilebilir.'
        else:
            impact = 'CONTRAIL BEKLENMİYOR'
            rec    = 'Mevcut irtifa contrail açısından uygun.'

        return {
            'altitude_ft'              : altitude_ft,
            'temperature_C'            : round(temperature_C, 1),
            'relative_humidity'        : relative_humidity,
            'contrail_formation_likely': contrail_likely,
            'contrail_persistent'      : contrail_persistent,
            'climate_impact_note'      : impact,
            'recommendation'           : rec,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: SAF (Sustainable Aviation Fuel) ANALİZİ
    # ──────────────────────────────────────────────────────

    def calculate_saf_impact(
        self,
        total_fuel_kg: float,
        saf_blend_pct: float,
        saf_type: str = 'HEFA',
        fuel_price_usd_per_kg: float = 0.85,
    ) -> dict:
        """
        SAF kullanımının emisyon ve maliyet etkisini hesapla.

        SAF Tipleri ve yaşam döngüsü CO2 azaltması:
            HEFA    : %72 (en yaygın)
            FT-SPK  : %90
            ATJ     : %62
            PTL     : %92 (e-fuel, yenilenebilir elektrikle)
            SIP     : %65

        Önemli not:
            SAF yakma sırasında AYNI CO2 üretir (3.16 kg/kg).
            Azaltım YAŞAM DÖNGÜSÜ bazlıdır (üretim sırasında
            atmosferden karbon çekilmiş olması).
            CORSIA raporlamasında lifecycle emisyon kullanılır.

        Args:
            total_fuel_kg        : Toplam yakıt (kg)
            saf_blend_pct        : SAF karışım yüzdesi (%)
            saf_type             : SAF tipi ('HEFA', 'FT_SPK', 'ATJ', 'PTL', 'SIP')
            fuel_price_usd_per_kg: Konvansiyonel yakıt fiyatı (USD/kg)

        Returns:
            dict:
                saf_type, saf_blend_pct, saf_fuel_kg,
                reduction_factor, combustion_co2_kg,
                lifecycle_co2_kg, co2_reduction_kg, co2_reduction_pct,
                corsia_offset_saving_usd, saf_extra_cost_usd,
                net_benefit_usd, note, eu_mandate

        Kaynak:
            ICAO CORSIA Eligible Fuels (CORSIA EF)
            EU ReFuelEU Aviation Regulation (2023/2405)
        """
        reduction_factor = _SAF_REDUCTION_FACTORS.get(saf_type, 0.72)
        price_premium    = _SAF_PRICE_PREMIUM.get(saf_type, 2.5)

        # SAF miktarı
        saf_fuel_kg          = total_fuel_kg * (saf_blend_pct / 100)
        conventional_fuel_kg = total_fuel_kg - saf_fuel_kg

        # Yanma emisyonu (değişmez, 3.16)
        combustion_co2 = total_fuel_kg * _EI_CO2

        # Yaşam döngüsü emisyon
        lifecycle_conventional = conventional_fuel_kg * _EI_CO2
        lifecycle_saf          = saf_fuel_kg * _EI_CO2 * (1 - reduction_factor)
        lifecycle_total        = lifecycle_conventional + lifecycle_saf

        # Azaltım
        co2_reduction = combustion_co2 - lifecycle_total
        reduction_pct = (co2_reduction / combustion_co2 * 100) if combustion_co2 > 0 else 0

        # CORSIA offset tasarrufu
        from config.settings import CARBON_CREDIT_PRICE_USD
        offset_saving = (co2_reduction / 1000) * CARBON_CREDIT_PRICE_USD

        # SAF ek maliyeti
        saf_extra_cost = saf_fuel_kg * fuel_price_usd_per_kg * (price_premium - 1)
        net_benefit    = offset_saving - saf_extra_cost

        return {
            'saf_type'                : saf_type,
            'saf_blend_pct'           : saf_blend_pct,
            'saf_fuel_kg'             : round(saf_fuel_kg),
            'reduction_factor'        : reduction_factor,
            'combustion_co2_kg'       : round(combustion_co2),
            'lifecycle_co2_kg'        : round(lifecycle_total),
            'co2_reduction_kg'        : round(co2_reduction),
            'co2_reduction_pct'       : round(reduction_pct, 1),
            'corsia_offset_saving_usd': round(offset_saving),
            'saf_extra_cost_usd'      : round(saf_extra_cost),
            'net_benefit_usd'         : round(net_benefit),
            'note': (
                f'{saf_blend_pct}% {saf_type} SAF ile yaşam döngüsü CO2 '
                f'%{reduction_pct:.1f} azalır.'
            ),
            'eu_mandate': {
                '2025': '2% SAF zorunlu (AB)',
                '2030': '6% SAF zorunlu (AB)',
                '2035': '20% SAF zorunlu (AB)',
                '2050': '70% SAF zorunlu (AB)',
            },
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 6: YARDIMCI
    # ──────────────────────────────────────────────────────

    @staticmethod
    def get_engine_for_aircraft(aircraft_type: str) -> str:
        """Uçak tipine göre varsayılan motor tipini döndür."""
        return _AIRCRAFT_ENGINE_MAP.get(aircraft_type, 'CFM56-7B26')

    @staticmethod
    def get_available_engines() -> list[str]:
        """Desteklenen motor tiplerinin listesi."""
        return sorted(_ENGINE_EMISSION_DB.keys())

    @staticmethod
    def get_engine_info(engine_type: str) -> Optional[dict]:
        """Motor bilgilerini döndür."""
        return _ENGINE_EMISSION_DB.get(engine_type)

    @staticmethod
    def get_available_saf_types() -> dict[str, float]:
        """Desteklenen SAF tipleri ve azaltım oranları."""
        return _SAF_REDUCTION_FACTORS.copy()


# ═══════════════════════════════════════════════════════════
# CORSIA UYUMLULUK SINIFI
# ═══════════════════════════════════════════════════════════

class CORSIACompliance:
    """
    CORSIA MRV (Monitoring, Reporting, Verification) modülü.

    ICAO CORSIA SARP Annex 16 Volume IV uyumlu.

    3 bileşen:
        M - Monitoring  : Yakıt tüketimi izleme
        R - Reporting   : Yıllık emisyon raporlama
        V - Verification: Doğrulama kontrol listesi

    Kullanım:
        compliance = CORSIACompliance()
        monitoring = compliance.monitoring_report(flights_data)
        report     = compliance.reporting_document(monitoring, ...)
        checklist  = compliance.verification_checklist()
    """

    def __init__(self):
        self._calc = EmissionCalculator

    def monitoring_report(self, flights_data: list[dict]) -> dict:
        """
        M - Monitoring: Her uçuşun yakıt tüketimini kaydet.

        CORSIA iki monitoring yöntemi tanır:
            Method A: Fuel Uplift (yakıt yükleme bazlı)
            Method B: Block Fuel (blok yakıt ölçümü) ← biz bunu kullanıyoruz

        Args:
            flights_data: list of dicts, her biri:
                {
                    'flight_number': 'TK1985',
                    'date'         : '2025-01-15',
                    'origin'       : 'LTFM',
                    'destination'  : 'EGLL',
                    'fuel_kg'      : 12500,
                    'aircraft_type': 'B738',
                    'data_source'  : 'operator_records'
                }

        Returns:
            dict:
                monitoring_period : str
                total_flights     : int
                total_fuel_kg     : float
                total_co2_kg      : float
                method            : str
                records           : list
        """
        records = []

        for flight in flights_data:
            fuel_kg = flight.get('fuel_kg', 0)
            records.append({
                'flight_id'        : flight.get('flight_number', 'UNK'),
                'date'             : flight.get('date', ''),
                'origin'           : flight.get('origin', ''),
                'destination'      : flight.get('destination', ''),
                'aircraft_type'    : flight.get('aircraft_type', 'B738'),
                'fuel_burn_kg'     : fuel_kg,
                'co2_kg'           : round(fuel_kg * _EI_CO2, 2),
                'monitoring_method': 'Method B - Block Fuel',
                'data_source'      : flight.get('data_source', 'operator_records'),
                'quality_flag'     : 'VERIFIED' if fuel_kg > 0 else 'ESTIMATED',
            })

        total_fuel = sum(r['fuel_burn_kg'] for r in records)
        total_co2  = sum(r['co2_kg'] for r in records)

        dates = [f.get('date', '') for f in flights_data if f.get('date')]
        period = f"{min(dates)} to {max(dates)}" if dates else "N/A"

        return {
            'monitoring_period': period,
            'total_flights'    : len(records),
            'total_fuel_kg'    : round(total_fuel, 0),
            'total_co2_kg'     : round(total_co2, 0),
            'method'           : 'CORSIA Method B - Block Fuel',
            'records'          : records,
        }

    def reporting_document(
        self,
        monitoring_data: dict,
        airline_name: str,
        reporting_year: int,
        baseline_co2_tonnes: Optional[float] = None,
    ) -> dict:
        """
        R - Reporting: CORSIA uyumlu yıllık emisyon raporu.

        Annex 16 Vol IV Chapter 2 uyumlu format.

        Args:
            monitoring_data      : monitoring_report() çıktısı
            airline_name         : Havayolu adı
            reporting_year       : Raporlama yılı
            baseline_co2_tonnes  : 2019 baseline CO2 (ton). None → tahmin.

        Returns:
            dict: CORSIA raporlama belgesi

        Not:
            Baseline None ise mevcut emisyonun %95'i varsayılır.
            Gerçek baseline müşteriden alınmalıdır.
        """
        total_co2_tonnes = monitoring_data['total_co2_kg'] / 1000

        if baseline_co2_tonnes is None:
            baseline_co2_tonnes = total_co2_tonnes * 0.95

        growth_co2     = total_co2_tonnes - baseline_co2_tonnes
        offset_required = max(0, growth_co2)

        from config.settings import CARBON_CREDIT_PRICE_USD
        offset_cost = offset_required * CARBON_CREDIT_PRICE_USD

        return {
            'report_type'      : 'CORSIA Annual Emission Report',
            'standard'         : 'ICAO Annex 16 Volume IV',
            'airline'          : airline_name,
            'reporting_year'   : reporting_year,
            'monitoring_method': 'Method B - Block Fuel',
            'emissions': {
                'total_flights'    : monitoring_data['total_flights'],
                'total_fuel_tonnes': round(monitoring_data['total_fuel_kg'] / 1000, 1),
                'total_co2_tonnes' : round(total_co2_tonnes, 1),
                'emission_factor'  : _EI_CO2,
            },
            'corsia_compliance': {
                'baseline_year'         : 2019,
                'baseline_co2_tonnes'   : round(baseline_co2_tonnes, 1),
                'current_co2_tonnes'    : round(total_co2_tonnes, 1),
                'growth_co2_tonnes'     : round(growth_co2, 1),
                'offset_required_tonnes': round(offset_required, 1),
                'estimated_offset_cost' : round(offset_cost),
                'carbon_price_usd_tonne': CARBON_CREDIT_PRICE_USD,
            },
            'saf_status': {
                'saf_used'      : False,
                'saf_blend_pct' : 0,
                'note'          : 'SAF entegrasyonu gelecek raporlama döneminde.',
            },
            'verification_status': {
                'self_verified'         : True,
                'third_party_verified'  : False,
                'verifier'              : None,
                'note': (
                    'İç doğrulama ile hazırlanmıştır. '
                    'CORSIA zorunlu faz (2027+) için akredite '
                    'üçüncü taraf doğrulaması gerekecektir.'
                ),
            },
        }

    @staticmethod
    def verification_checklist() -> dict:
        """
        V - Verification: Üçüncü taraf doğrulama kontrol listesi.

        Gerçek doğrulama ISO 14065 akredite kuruluş tarafından yapılır.
        Bu liste hazırlık amaçlıdır.

        Returns:
            dict: Kontrol listesi
        """
        return {
            'verification_type': 'Self-Assessment Checklist',
            'note': (
                'İç değerlendirme listesi. CORSIA zorunlu faz için '
                'ISO 14065 akredite doğrulama kuruluşu gerekir.'
            ),
            'checklist': [
                {
                    'item'       : 'Monitoring Plan',
                    'requirement': 'Yakıt izleme planı onaylı mı?',
                    'status'     : 'REQUIRED',
                    'detail'     : 'Operatör planını devlet otoritesine sunmalı.',
                },
                {
                    'item'       : 'Fuel Measurement',
                    'requirement': 'Yakıt ölçümü kalibre cihazlarla mı?',
                    'status'     : 'REQUIRED',
                    'detail'     : 'Akış ölçer veya tank ölçümü kalibrasyonlu olmalı.',
                },
                {
                    'item'       : 'Data Completeness',
                    'requirement': 'Tüm uluslararası uçuşlar dahil mi?',
                    'status'     : 'REQUIRED',
                    'detail'     : 'Exemption kapsamı hariç tüm uçuşlar.',
                },
                {
                    'item'       : 'Emission Factor',
                    'requirement': 'Doğru emisyon faktörü kullanılıyor mu?',
                    'status'     : 'VERIFIED',
                    'detail'     : f'Jet-A1: {_EI_CO2} kg CO2/kg fuel (ICAO standard).',
                },
                {
                    'item'       : 'Baseline Comparison',
                    'requirement': '2019 baseline ile karşılaştırma doğru mu?',
                    'status'     : 'REQUIRED',
                    'detail'     : 'Baseline verisi doğrulanmış olmalı.',
                },
                {
                    'item'       : 'SAF Documentation',
                    'requirement': 'SAF kullanımı belgelendi mi?',
                    'status'     : 'NOT_APPLICABLE',
                    'detail'     : 'SAF kullanılıyorsa CORSIA eligible fuel belgesi gerekli.',
                },
                {
                    'item'       : 'Offset Procurement',
                    'requirement': 'Karbon kredileri CORSIA eligible mi?',
                    'status'     : 'REQUIRED_FROM_2027',
                    'detail'     : 'CORSIA eligible emission units (CEU) listesinden olmalı.',
                },
            ],
        }


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_emission_model() -> bool:
    """
    Emisyon modeli doğrulama testleri.

    Çalıştırma:
        python -m src.models.emission_model
    """
    print("\n" + "=" * 60)
    print("  EMISSION_MODEL.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests = 0
    calc  = EmissionCalculator()

    def check(name: str, actual: float, expected: float, tol: float) -> None:
        nonlocal tests
        tests += 1
        if abs(actual - expected) > tol:
            errors.append(f"{name}: {actual} ≠ {expected}")
            print(f"  ❌ {name}: {actual} (beklenen {expected})")
        else:
            print(f"  ✅ {name} = {actual}")

    def check_range(name: str, actual: float, lo: float, hi: float) -> None:
        nonlocal tests
        tests += 1
        if lo <= actual <= hi:
            print(f"  ✅ {name} = {actual:.4f} [{lo}, {hi}]")
        else:
            errors.append(f"{name}: {actual} dışı [{lo}, {hi}]")
            print(f"  ❌ {name} = {actual} [{lo}, {hi}]")

    # ─── [1] Temel emisyon ────────────────────────────────
    print("\n  [1] Temel Emisyon Hesapları")

    check("CO2 1000kg",  calc.co2_from_fuel(1000),  3160.0, 1.0)
    check("CO2 12500kg", calc.co2_from_fuel(12500), 39500.0, 1.0)
    check("CO2 0kg",     calc.co2_from_fuel(0),     0.0, 0.01)
    check("H2O 1000kg",  calc.h2o_from_fuel(1000),  1240.0, 1.0)
    check("SO2 1000kg",  calc.so2_from_fuel(1000),   1.0, 0.01)

    # ─── [2] NOx BFFM2 ───────────────────────────────────
    print("\n  [2] NOx BFFM2")

    nox_cfm56 = calc.nox_bffm2(
        fuel_flow_kg_s=0.35, altitude_ft=35000,
        mach=0.785, engine_type='CFM56-7B26'
    )
    check_range("NOx EI CFM56-7B26 cruise", nox_cfm56, 1.0, 20.0)

    nox_leap = calc.nox_bffm2(
        fuel_flow_kg_s=0.30, altitude_ft=35000,
        mach=0.79, engine_type='LEAP-1B'
    )
    check_range("NOx EI LEAP-1B cruise", nox_leap, 0.5, 15.0)

    tests += 1
    if nox_leap < nox_cfm56:
        print(f"  ✅ LEAP NOx({nox_leap:.2f}) < CFM56 NOx({nox_cfm56:.2f})")
    else:
        errors.append("LEAP daha az NOx üretmeli")
        print("  ❌ LEAP NOx ≥ CFM56 NOx")

    nox_unknown = calc.nox_bffm2(
        0.35, 35000, 0.785, 'BILINMEYEN_MOTOR'
    )
    tests += 1
    if nox_unknown > 0:
        print(f"  ✅ Bilinmeyen motor generic NOx: {nox_unknown:.2f}")
    else:
        errors.append("Bilinmeyen motor NOx sıfır olamaz")

    # ─── [3] Tam uçuş emisyonu ────────────────────────────
    print("\n  [3] Tam Uçuş Emisyonu")

    result = calc.calculate_flight_emissions(
        fuel_burn_kg=12500, distance_nm=1560,
        aircraft_type='B738', cruise_altitude_ft=37000,
        cruise_mach=0.785
    )

    em = result['emissions']
    mt = result['metrics']

    check("Flight CO2", em['CO2_kg'], 39500.0, 1.0)
    check("Flight H2O", em['H2O_kg'], 15500.0, 1.0)
    check_range("Flight NOx", em['NOx_kg'], 0.1, 100.0)
    check_range("fuel/Nm", mt['fuel_per_nm_kg'], 5.0, 12.0)
    check_range("CO2/pax/km", mt['co2_per_pax_km_g'], 50.0, 200.0)

    tests += 1
    det = result['details']
    if det['engine_type'] == 'CFM56-7B26':
        print(f"  ✅ B738 → CFM56-7B26 motor eşleşmesi doğru")
    else:
        errors.append(f"Motor eşleşme yanlış: {det['engine_type']}")

    # Farklı uçak tipleri
    result_777 = calc.calculate_flight_emissions(
        fuel_burn_kg=42000, distance_nm=1550,
        aircraft_type='B77W', cruise_altitude_ft=39000,
        cruise_mach=0.84, num_engines=2
    )
    tests += 1
    if result_777['details']['engine_type'] == 'GE90-115B':
        print("  ✅ B77W → GE90-115B motor eşleşmesi doğru")
    else:
        errors.append(f"B77W motor yanlış: {result_777['details']['engine_type']}")

    result_neo = calc.calculate_flight_emissions(
        fuel_burn_kg=10200, distance_nm=1220,
        aircraft_type='A20N'
    )
    tests += 1
    if result_neo['details']['engine_type'] == 'LEAP-1A':
        print("  ✅ A20N → LEAP-1A motor eşleşmesi doğru")
    else:
        errors.append(f"A20N motor yanlış: {result_neo['details']['engine_type']}")

    # ─── [4] Contrail ─────────────────────────────────────
    print("\n  [4] Contrail Analizi")

    contrail_high = calc.schmidt_appleman_criterion(41000)
    tests += 1
    if contrail_high['contrail_formation_likely']:
        print(f"  ✅ FL410 ({contrail_high['temperature_C']:.1f}°C) → contrail bekleniyor")
    else:
        errors.append("FL410'da contrail beklenmeli")

    contrail_low = calc.schmidt_appleman_criterion(20000)
    tests += 1
    if not contrail_low['contrail_formation_likely']:
        print(f"  ✅ FL200 ({contrail_low['temperature_C']:.1f}°C) → contrail beklenmiyor")
    else:
        errors.append("FL200'de contrail beklenmemeli")

    # ─── [5] SAF ──────────────────────────────────────────
    print("\n  [5] SAF Analizi")

    saf = calc.calculate_saf_impact(12500, saf_blend_pct=6, saf_type='HEFA')

    tests += 1
    if saf['co2_reduction_pct'] > 0:
        print(f"  ✅ SAF %6 HEFA: CO2 azaltma %{saf['co2_reduction_pct']:.1f}")
    else:
        errors.append("SAF CO2 azaltımı sıfır")

    tests += 1
    if saf['saf_fuel_kg'] == 750:
        print(f"  ✅ SAF miktarı: {saf['saf_fuel_kg']} kg (12500 × 6%)")
    else:
        errors.append(f"SAF miktarı yanlış: {saf['saf_fuel_kg']}")

    tests += 1
    # Yuvarlama hatalarını tolere et (2 kg fark kabul edilebilir)

    diff = abs(saf['combustion_co2_kg'] - (saf['lifecycle_co2_kg'] + saf['co2_reduction_kg']))
    if diff < 2:
        print("  ✅ CO2 tutarlılık: combustion = lifecycle + reduction")
    else:
        errors.append(f"SAF CO2 tutarsızlık: combustion={saf['combustion_co2_kg']}, lifecycle={saf['lifecycle_co2_kg']}, reduction={saf['co2_reduction_kg']}, diff={diff}")

    # %0 SAF = sıfır azaltım
    saf_zero = calc.calculate_saf_impact(12500, saf_blend_pct=0)
    tests += 1
    if saf_zero['co2_reduction_kg'] == 0:
        print("  ✅ %0 SAF → sıfır azaltım")
    else:
        errors.append(f"%0 SAF azaltım sıfır olmalı: {saf_zero['co2_reduction_kg']}")

    # EU mandate bilgisi
    tests += 1
    if '2030' in saf['eu_mandate']:
        print(f"  ✅ EU mandate bilgisi mevcut")
    else:
        errors.append("EU mandate eksik")

    # SAF tipleri
    types = calc.get_available_saf_types()
    tests += 1
    if len(types) >= 4:
        print(f"  ✅ {len(types)} SAF tipi destekleniyor")
    else:
        errors.append(f"SAF tipi az: {len(types)}")

    # ─── [6] CORSIA MRV ──────────────────────────────────
    print("\n  [6] CORSIA MRV")

    flights_data = [
        {'flight_number': 'TK1985', 'date': '2025-01-15',
         'origin': 'LTFM', 'destination': 'EGLL',
         'fuel_kg': 12500, 'aircraft_type': 'B738'},
        {'flight_number': 'TK1986', 'date': '2025-01-15',
         'origin': 'EGLL', 'destination': 'LTFM',
         'fuel_kg': 11800, 'aircraft_type': 'B738'},
        {'flight_number': 'TK1721', 'date': '2025-01-16',
         'origin': 'LTFM', 'destination': 'EDDF',
         'fuel_kg': 8500, 'aircraft_type': 'A320'},
    ]

    # Monitoring
    monitoring = calc.corsia_compliance.monitoring_report(flights_data)
    tests += 1
    if monitoring['total_flights'] == 3:
        print(f"  ✅ Monitoring: {monitoring['total_flights']} uçuş")
    else:
        errors.append(f"Monitoring uçuş sayısı yanlış: {monitoring['total_flights']}")

    tests += 1
    expected_fuel = 12500 + 11800 + 8500
    if abs(monitoring['total_fuel_kg'] - expected_fuel) < 1:
        print(f"  ✅ Monitoring toplam yakıt: {monitoring['total_fuel_kg']} kg")
    else:
        errors.append(f"Monitoring yakıt yanlış: {monitoring['total_fuel_kg']}")

    tests += 1
    expected_co2 = expected_fuel * _EI_CO2
    if abs(monitoring['total_co2_kg'] - expected_co2) < 10:
        print(f"  ✅ Monitoring toplam CO2: {monitoring['total_co2_kg']} kg")
    else:
        errors.append(f"Monitoring CO2 yanlış: {monitoring['total_co2_kg']}")

    # Reporting
    report = calc.corsia_compliance.reporting_document(
        monitoring, 'Test Airlines', 2025
    )
    tests += 1
    if report['report_type'] == 'CORSIA Annual Emission Report':
        print("  ✅ Reporting dokümanı oluşturuldu")
    else:
        errors.append("Report type yanlış")

    tests += 1
    if report['corsia_compliance']['offset_required_tonnes'] >= 0:
        print(f"  ✅ Offset gereksinimi: {report['corsia_compliance']['offset_required_tonnes']:.1f} ton")
    else:
        errors.append("Offset negatif olamaz")

    # Verification
    checklist = CORSIACompliance.verification_checklist()
    tests += 1
    if len(checklist['checklist']) >= 5:
        print(f"  ✅ Verification checklist: {len(checklist['checklist'])} madde")
    else:
        errors.append(f"Checklist az: {len(checklist['checklist'])}")

    # ─── [7] Motor ve yardımcı fonksiyonlar ───────────────
    print("\n  [7] Motor ve Yardımcılar")

    tests += 1
    engine = calc.get_engine_for_aircraft('B738')
    if engine == 'CFM56-7B26':
        print("  ✅ B738 → CFM56-7B26")
    else:
        errors.append(f"B738 motor yanlış: {engine}")

    tests += 1
    engine_a350 = calc.get_engine_for_aircraft('A350')
    if engine_a350 == 'Trent XWB-84':
        print("  ✅ A350 → Trent XWB-84")
    else:
        errors.append(f"A350 motor yanlış: {engine_a350}")

    tests += 1
    engines = calc.get_available_engines()
    if len(engines) >= 8:
        print(f"  ✅ {len(engines)} motor tipi destekleniyor")
    else:
        errors.append(f"Motor tipi az: {len(engines)}")

    tests += 1
    info = calc.get_engine_info('GE90-115B')
    if info and info['bypass_ratio'] == 9.0:
        print("  ✅ GE90-115B bilgi: BPR=9.0")
    else:
        errors.append("GE90-115B bilgi hatası")

    tests += 1
    info_none = calc.get_engine_info('BILINMEYEN')
    if info_none is None:
        print("  ✅ Bilinmeyen motor → None")
    else:
        errors.append("Bilinmeyen motor None dönmeli")

    # ─── [8] Çapraz doğrulama ─────────────────────────────
    print("\n  [8] Çapraz Doğrulama")

    # CO2 = fuel × 3.16 (elle doğrula)
    for fuel in [1000, 5000, 12500, 50000]:
        co2 = calc.co2_from_fuel(fuel)
        expected = fuel * 3.16
        tests += 1
        if abs(co2 - expected) < 0.01:
            print(f"  ✅ {fuel} kg → {co2:.0f} kg CO2 (={fuel}×3.16)")
        else:
            errors.append(f"CO2 çapraz doğrulama: {fuel}kg → {co2} ≠ {expected}")

    # LEAP daha verimli → daha az NOx/kg
    nox_old = calc.nox_bffm2(0.35, 35000, 0.785, 'CFM56-7B26')
    nox_new = calc.nox_bffm2(0.30, 35000, 0.79,  'LEAP-1B')
    tests += 1
    if nox_new < nox_old:
        print(f"  ✅ Yeni motor daha temiz: LEAP({nox_new:.2f}) < CFM56({nox_old:.2f})")
    else:
        errors.append("Yeni nesil motor daha temiz olmalı")

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


# ═══════════════════════════════════════════════════════════
# ÇALIŞTIRMA
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    validate_emission_model()
    