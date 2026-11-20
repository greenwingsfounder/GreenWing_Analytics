# src/analysis/fuel_thermal_model.py

"""
GreenWing Analytics — SAF Termal Modelleme ve Donma Noktası Analiz Sistemi
══════════════════════════════════════════════════════════════════════════════

Bu modül, SAF'ın fizikokimyasal özelliklerinden biri olan "Donma Noktası" (Freezing Point)
parametresinin, uzun menzilli uçuşlarda yarattığı operasyonel ve termal etkileri modeller.

FİZİKSEL VE TERMODİNAMİK TEMEL:
───────────────────────────────
    1. Aerodinamik Isınma (Total Air Temperature - TAT):
       Yüksek hızda uçan uçağın kanat yüzeyi kinetik sürtünme ile ısınır. Kanat dışındaki havanın
       gerçek sıcaklığı (Static Air Temperature - SAT) çok soğuk olsa da, kanat yüzeyinin hissettiği
       sıcaklık (TAT) daha yüksektir:
       
       TAT = SAT * (1 + 0.2 * r * Mach²)
       (Burada r = Kurtarma Faktörü / Recovery Factor, dar gövdede ~0.89 alınır).
       
    2. Yakıt Soğuma Hızı (Fuel Thermal Cooling Rate):
       Kanat tanklarındaki yakıt, dış ortama (TAT) doğru ısı kaybeder. Soğuma hızı Newton'un Soğuma
       Kanunu uyarınca tanktaki yakıt hacmi, kanat yüzey alanı ve zamanla ilişkilidir:
       
       dT_fuel/dt = -K_cool * (T_fuel - TAT)
       (Burada K_cool = Soğuma Katsayısı, Boeing 737 için yaklaşık 0.08 - 0.15 hr⁻¹ arasındadır).
       
    3. Operasyonel Kısıt ve Müdahale (Freezing Margin):
       Uçuş emniyeti kuralları gereği, yakıt sıcaklığı donma noktasının en fazla 3°C üzerine kadar
       yaklaşabilir (T_fuel_limit = T_freeze + 3°C). Yakıt bu sınıra ulaşırsa mürettebat:
       
       A. Daha alçak ve sıcak bir irtifaya (FL) inmeli (Bu durumda drag artar, Ground SAR düşer, yakıt tüketimi artar!)
       B. Veya hızı (Mach) artırarak TAT'yi kinetik olarak yükseltmeli (Bu durumda da motor verimi bozulur ve drag artar!)

KAYNAKLAR:
──────────
    • Boeing Aero Magazine - "Cold Fuel Operations"
    • ASTM D1655 (Standard Specification for Aviation Turbine Fuels)
    • ASTM D7566 (Standard Specification for Synthesized Kerosene)
"""

from __future__ import annotations

import numpy as np
from typing import Dict, Any, List


class FuelThermalModel:
    """
    Uzun menzilli uçuşlarda yakıt termal davranışını ve donma noktası kısıtlarını
    modelleme sınıfı.
    """

    def __init__(
        self,
        freezing_point_c: float = -47.0,  # Standart Jet A-1 donma noktası (°C)
        recovery_factor: float = 0.89,     # Kanat aerodinamik sıcaklık kurtarma katsayısı
        cooling_coefficient: float = 0.08  # Saatteki yakıt soğuma katsayısı (hr^-1)
    ) -> None:
        self.freeze_point = freezing_point_c
        self.r = recovery_factor
        self.K_cool = cooling_coefficient
        self.safety_margin = 3.0  # ICAO/FAA emniyet marjı (°C)
        self.temp_limit = self.freeze_point + self.safety_margin

    def calculate_tat(self, sat_c: float, mach: float) -> float:
        """
        Static Air Temperature (SAT) ve Mach sayısına göre Total Air Temperature (TAT) hesaplar.
        
        TAT, uçağın kanadının maruz kaldığı gerçek dış termal sınırdır.
        """
        sat_k = sat_c + 273.15
        tat_k = sat_k * (1.0 + 0.2 * self.r * mach ** 2)
        return float(tat_k - 273.15)

    def simulate_flight_cooling(
        self,
        duration_hours: float,
        sat_c_profile: List[float],
        mach_profile: List[float],
        initial_fuel_temp_c: float = 15.0,
        time_step_mins: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Uçuş boyunca yakıtın sıcaklık değişimini simüle eder.
        
        Args:
            duration_hours     : Uçuş süresi (saat)
            sat_c_profile      : Her zaman adımı için SAT profil listesi (°C)
            mach_profile       : Her zaman adımı için Mach sayısı profili
            initial_fuel_temp_c: Yakıtın kalkıştaki ilk sıcaklığı (°C) (Genelde yer sıcaklığına yakın)
            time_step_mins     : Entegrasyon adım süresi (dakika)
        """
        dt_hr = time_step_mins / 60.0
        steps = int(duration_hours / dt_hr)
        
        # Profil uzunluklarını eşitle
        if len(sat_c_profile) < steps:
            sat_c_profile = sat_c_profile + [sat_c_profile[-1]] * (steps - len(sat_c_profile))
        if len(mach_profile) < steps:
            mach_profile = mach_profile + [mach_profile[-1]] * (steps - len(mach_profile))

        time_axis = [i * time_step_mins for i in range(steps + 1)]
        fuel_temps = [initial_fuel_temp_c]
        tat_temps = []
        
        limit_violated = False
        violation_time_mins = None
        
        current_fuel_temp = initial_fuel_temp_c

        for i in range(steps):
            sat = sat_c_profile[i]
            mach = mach_profile[i]
            
            # TAT hesapla
            tat = self.calculate_tat(sat, mach)
            tat_temps.append(tat)
            
            # Newton'un Soğuma Kanunu diferansiyel entegrasyonu:
            # dT_fuel = -K_cool * (T_fuel - TAT) * dt
            dT = -self.K_cool * (current_fuel_temp - tat) * dt_hr
            current_fuel_temp += dT
            fuel_temps.append(current_fuel_temp)
            
            # Limit kontrolü
            if not limit_violated and current_fuel_temp <= self.temp_limit:
                limit_violated = True
                violation_time_mins = (i + 1) * time_step_mins

        # Son TAT'yi ekle
        tat_temps.append(tat_temps[-1])

        return {
            'time_mins'          : time_axis,
            'fuel_temperatures_c': fuel_temps,
            'tat_temperatures_c' : tat_temps,
            'limit_temperature_c': self.temp_limit,
            'limit_violated'     : limit_violated,
            'violation_time_mins': violation_time_mins,
            'final_fuel_temp_c'  : current_fuel_temp
        }

    def evaluate_freezing_mitigation_penalty(
        self,
        base_altitude_ft: float,
        mach: float,
        sat_c: float,
        initial_fuel_temp_c: float,
        flight_duration_hrs: float,
    ) -> Dict[str, Any]:
        """
        Eğer yakıt sıcaklığı limitin altına düşerse, uygulanacak kaçınma manevralarının
        (İrtifa düşürme veya hız artırma) yakıt tüketimine olan cezasını (penalty) modeller.
        
        SAF'ın donma noktası daha düşükse (-55°C gibi), bu cezalardan kaçınılır ve tasarruf sağlanır!
        """
        # Standart simülasyonu çalıştır
        sat_profile = [sat_c] * 100
        mach_profile = [mach] * 100
        
        sim_base = self.simulate_flight_cooling(
            flight_duration_hrs, sat_profile, mach_profile, initial_fuel_temp_c
        )
        
        requires_mitigation = sim_base['limit_violated']
        
        desc_alt_penalty_kg = 0.0
        speed_up_penalty_kg = 0.0
        desc_reason = ""
        speed_reason = ""

        if requires_mitigation:
            # Kaçınma Manevrası 1: FL irtifasını düşürme (Sıcak havaya inme)
            # Standart Troposferde her 1000 ft düşüş sıcaklığı ~2.0°C artırır.
            # Donma emniyeti sağlamak için genellikle 4000 ft (FL350 -> FL310) alçalınır.
            # FL310'da hava yoğundur, drag yaklaşık %8-12 artar, yakıt akışı (FF) artar.
            temp_need_c = self.temp_limit - sim_base['final_fuel_temp_c']
            alt_drop_needed_ft = max(2000.0, min(10000.0, (temp_need_c / 2.0) * 1000.0))
            
            # Saatte yaklaşık ek %10 yakıt cezası (Daha yoğun hava / yüksek drag nedeniyle)
            time_spent_in_violation_hrs = flight_duration_hrs - (sim_base['violation_time_mins'] / 60.0)
            # Kaba yakıt tüketim cezası tahmini (Narrow-body için saatte ~2600 kg tüketimde %10 ek tüketim)
            desc_alt_penalty_kg = 2600.0 * 0.10 * time_spent_in_violation_hrs
            desc_reason = (
                f"Yakıt donma limitine yaklaştığı için FL{base_altitude_ft//100:.0f} 'den "
                f"FL{(base_altitude_ft - alt_drop_needed_ft)//100:.0f} 'e alçalındı (+%10 fuel flow penalty)."
            )

            # Kaçınma Manevrası 2: Hızı (Mach) artırma (Aerodinamik kinetik ısıtma)
            # Mach 0.78 -> 0.82 yapılırsa TAT yaklaşık 2.5°C ısınır.
            # Drag dalgası (wave drag) nedeniyle saatte yaklaşık %12 ek yakıt harcanır.
            speed_up_penalty_kg = 2600.0 * 0.12 * time_spent_in_violation_hrs
            speed_reason = (
                f"Aerodinamik ısınmayı artırmak için Mach {mach:.3f} 'den "
                f"Mach {mach + 0.04:.3f} 'e çıkıldı (+%12 fuel flow penalty)."
            )

        return {
            'requires_mitigation'    : requires_mitigation,
            'base_final_fuel_temp_c' : round(sim_base['final_fuel_temp_c'], 2),
            'limit_temperature_c'    : self.temp_limit,
            'desc_altitude_penalty_kg': round(desc_alt_penalty_kg),
            'desc_reason'            : desc_reason,
            'speed_up_penalty_kg'    : round(speed_up_penalty_kg),
            'speed_reason'           : speed_reason,
        }
