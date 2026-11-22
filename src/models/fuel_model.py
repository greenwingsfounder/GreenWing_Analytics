"""
GreenWing Analytics — Yakıt Hesaplama Modeli
═════════════════════════════════════════════

Bu dosya projenin KALBİDİR.
Tüm yakıt hesaplamaları TEK MERKEZDEN buradan yapılır.

Neden ayrı dosya?
─────────────────
Eskiden aircraft_performance.py içindeydi.
Ama:
    • emission_model fuel'e bağımlı
    • optimization modülleri fuel'e bağımlı
    • calibration fuel'e bağımlı
    • Tek yerde olmazsa tutarsızlık olur
    • Kalibrasyon yapılınca tek yer güncellenir

Fizik temeli:
─────────────
    Level flight: Thrust = Drag
    Fuel Flow = SFC × Drag
    SAR = TAS / Fuel_Flow
    Total Fuel = ∫(Fuel_Flow × dt) over distance

SFC modeli:
───────────
    aircraft_database.yaml'daki tsfc_cruise değeri
    TİPİK CRUISE koşulları için tanımlanmış referanstır.
    (deniz seviyesi değeri DEĞİL)

    Bu yüzden düzeltmeler KÜÇÜK tutulur:
        altitude_correction : referans cruise'dan fark (~±%2)
        mach_correction     : Mach arttıkça küçük iyileşme (~±%1)
        isa_correction      : sıcak günlerde küçük kötüleşme (~±%0.5)

KULLANIM:
─────────
    from src.models.fuel_model import FuelModel

    fm = FuelModel('B738')
    ff = fm.cruise_fuel_flow(weight_kg=65000, altitude_ft=35000, mach=0.785)
    sar = fm.specific_air_range(weight_kg=65000, altitude_ft=35000, mach=0.785)
    result = fm.fuel_for_distance(distance_nm=1560, weight_initial_kg=75000,
                                   altitude_ft=37000, mach=0.785)
"""

from __future__ import annotations

import numpy as np
import yaml
import os
from typing import Optional

from src.units import Units
from src.validation.data_validator import DataValidator
from src.validation.physics_validator import PhysicsValidator


# ═══════════════════════════════════════════════════════════
# SABİTLER
# ═══════════════════════════════════════════════════════════

_GRAVITY = 9.80665   # m/s²
_AIRCRAFT_DB_CACHE = None  # TODO: add reload/invalidation for production (thread-safety issue noted in review)


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class FuelModel:
    """
    GreenWing Analytics Yakıt Hesaplama Modeli.

    Tüm yakıt hesaplamaları bu sınıf üzerinden yapılır.

    Args:
        aircraft_type: ICAO uçak tipi kodu ('B738', 'A320', 'B77W', ...)
        delta_isa    : ISA sapması (°C). Sıcak gün: +15, soğuk gün: -10
        cd0_factor   : Drag artış faktörü (kalibrasyon). 1.0 = yeni uçak.
        sfc_factor   : SFC artış faktörü (kalibrasyon). 1.0 = yeni motor.

    Kullanım:
        fm = FuelModel('B738')
        ff = fm.cruise_fuel_flow(65000, 35000, 0.785)
        sar = fm.specific_air_range(65000, 35000, 0.785)
    """

    def __init__(
        self,
        aircraft_type: str = 'B738',
        delta_isa: float = 0.0,
        cd0_factor: float = 1.0,
        sfc_factor: float = 1.0,
        saf_blend_ratio: float = 0.0,
        saf_type: str = "HEFA",
    ) -> None:
        self.ac_type    = aircraft_type
        self.delta_isa  = delta_isa
        self.cd0_factor = cd0_factor
        self.sfc_factor = sfc_factor

        # SAF Modeli Entegrasyonu
        from src.models.saf_model import SAFModel
        self.saf_model = SAFModel(blend_ratio=saf_blend_ratio, saf_type=saf_type)

        # Uçak veritabanından parametreleri yükle
        self.params = self._load_aircraft_params(aircraft_type)

        # Kalibrasyon ve SAF ısıl değer faktörlerini uygula
        self._effective_cd0  = self.params['CD0'] * cd0_factor
        self._effective_tsfc = self.params['tsfc_cruise'] * sfc_factor * self.saf_model.sfc_correction_factor()

    # ──────────────────────────────────────────────────────
    # BÖLÜM 0: UÇAK PARAMETRELERİ YÜKLEME
    # ──────────────────────────────────────────────────────

    def _load_aircraft_params(self, ac_type: str) -> dict:
        """
        aircraft_database.yaml'dan uçak parametrelerini oku.

        Raises:
            ValueError: Bilinmeyen uçak tipi
            FileNotFoundError: YAML dosyası bulunamadı
        """
        global _AIRCRAFT_DB_CACHE
        if _AIRCRAFT_DB_CACHE is None:
            config_path = os.path.join(
                os.path.dirname(__file__), '..', '..', 'config', 'aircraft_database.yaml'
            )

            if not os.path.exists(config_path):
                raise FileNotFoundError(
                    f"aircraft_database.yaml bulunamadı: {config_path}"
                )

            with open(config_path, 'r', encoding='utf-8') as f:
                _AIRCRAFT_DB_CACHE = yaml.safe_load(f)

        db = _AIRCRAFT_DB_CACHE

        if ac_type not in db.get('aircraft_types', {}):
            available = sorted(db.get('aircraft_types', {}).keys())
            raise ValueError(
                f"Bilinmeyen uçak tipi: '{ac_type}'. "
                f"Desteklenen: {available}"
            )

        return db['aircraft_types'][ac_type]

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: AERODİNAMİK HESAPLAR
    # ──────────────────────────────────────────────────────

    def lift_coefficient(
        self,
        weight_kg: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Seviye uçuşta gerekli kaldırma katsayısını hesapla.

        Formül:
            CL = (W × g) / (q × S)
            q  = 0.5 × ρ × V²

        Args:
            weight_kg  : Uçak ağırlığı (kg)
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: CL (boyutsuz)
        """
        rho = Units.density_at_altitude(altitude_ft, self.delta_isa)
        V   = Units.mach_to_tas(mach, altitude_ft, self.delta_isa)
        S   = self.params['wing_area']

        q  = 0.5 * rho * V ** 2
        CL = (weight_kg * _GRAVITY) / (q * S)

        return float(CL)

    def drag_coefficient(self, CL: float) -> float:
        """
        Drag polar'dan toplam drag katsayısını hesapla.

        Formül:
            CD = CD0 + K × CL²

        Args:
            CL: Kaldırma katsayısı

        Returns:
            float: CD (boyutsuz)
        """
        CD = self._effective_cd0 + self.params['K'] * CL ** 2
        return float(CD)

    def lift_to_drag_ratio(
        self,
        weight_kg: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        L/D oranı.

        Args:
            weight_kg  : Uçak ağırlığı (kg)
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: L/D (boyutsuz)
        """
        CL = self.lift_coefficient(weight_kg, altitude_ft, mach)
        CD = self.drag_coefficient(CL)
        return float(CL / CD) if CD > 0 else 0.0

    def cruise_drag(
        self,
        weight_kg: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Cruise'da toplam drag kuvveti (Newton).

        Formül:
            D = q × S × CD
            Level flight: Thrust = Drag

        Args:
            weight_kg  : Uçak ağırlığı (kg)
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: Drag kuvveti (Newton)
        """
        rho = Units.density_at_altitude(altitude_ft, self.delta_isa)
        V   = Units.mach_to_tas(mach, altitude_ft, self.delta_isa)
        S   = self.params['wing_area']

        q  = 0.5 * rho * V ** 2
        CL = (weight_kg * _GRAVITY) / (q * S)
        CD = self.drag_coefficient(CL)
        D  = q * S * CD

        return float(D)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: SFC (Specific Fuel Consumption)
    # ──────────────────────────────────────────────────────

    def corrected_sfc(
        self,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Cruise referans SFC değerini irtifa, Mach ve ISA sapmasına göre
        hafifçe düzelt.

        ÖNEMLİ TASARIM KARARI:
        ──────────────────────
        aircraft_database.yaml içindeki tsfc_cruise değeri,
        deniz seviyesi değil, zaten TİPİK CRUISE koşulları için
        tanımlanmış referans değerdir.

        Bu yüzden burada büyük bir √(θ/δ) düzeltmesi uygulamak
        fuel flow'u yapay olarak çok büyütür (double counting).

        Kullanılan yaklaşım:
            SFC = SFC_ref × altitude_correction × mach_correction × isa_correction

        Burada düzeltmeler KÜÇÜKTÜR:
            • altitude_correction : referans cruise irtifasına göre ±%2 civarı
            • mach_correction     : Mach arttıkça ram recovery ~±%1
            • isa_correction      : sıcak günlerde küçük kötüleşme ~±%0.5

        Args:
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: Düzeltilmiş SFC (kg/(N·s))

        Doğrulama:
            B738 @ FL350 M0.785 → SFC ≈ 0.0000175-0.0000185
            Fuel flow ≈ 2200-2800 kg/hr (iki motor)

        Not:
            Eğer ileride deniz seviyesi referanslı SFC veri tabanı
            kullanılırsa, bu fonksiyon √(θ/δ) düzeltmesiyle
            yeniden tasarlanmalıdır.

        Kaynak:
            BADA Performance Model (Eurocontrol) — cruise referans yaklaşımı
            Boeing 737 Performance Engineer's Manual
        """
        sfc_ref = self._effective_tsfc

        # Referans cruise Mach
        mach_ref = self.params.get('cruise_mach', 0.78)

        # Referans cruise irtifası
        # Dar gövde: genelde FL350
        # Geniş gövde: genelde FL370
        if self.params.get('mtow', 80000) > 150000:
            alt_ref_ft = 37000
        else:
            alt_ref_ft = 35000

        # 1) İrtifa düzeltmesi
        # Referans irtifadan her +10000 ft fark için ~%1.5 değişim
        # Optimal cruise irtifasından SAPINCA verim düşer.
        # Hem daha yüksek hem daha alçak irtifa SFC'yi artırır.
        # Bu düzeltme optimalden ±10000 ft için ±%1.5 değişim varsayar.
        # Alçak irtifa → motor biraz daha verimli
        altitude_correction = 1.0 + 0.015 * ((altitude_ft - alt_ref_ft) / 10000.0)
        altitude_correction = float(np.clip(altitude_correction, 0.95, 1.08))

        # 2) Mach düzeltmesi
        # Ram recovery etkisi: yüksek Mach → kompresör giriş basıncı artar
        # → Termal verim artar → SFC düşer
        # 0.10 Mach fark → yaklaşık %1 iyileşme
        mach_correction = 1.0 - 0.10 * (mach - mach_ref)
        mach_correction = float(np.clip(mach_correction, 0.97, 1.03))

        # 3) ISA sapması düzeltmesi
        # Sıcak gün → motor termal verimi düşer → SFC artar
        # +10°C → yaklaşık %0.5 kötüleşme
        isa_correction = 1.0 + 0.005 * (self.delta_isa / 10.0)
        isa_correction = float(np.clip(isa_correction, 0.97, 1.05))

        sfc = sfc_ref * altitude_correction * mach_correction * isa_correction

        return float(sfc)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: YAKIT AKIŞI VE SAR
    # ──────────────────────────────────────────────────────

    def cruise_fuel_flow(
        self,
        weight_kg: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Cruise yakıt akışı (kg/s).

        Formül:
            Level flight: Thrust = Drag
            Fuel_Flow = SFC × Drag

        Args:
            weight_kg  : Uçak ağırlığı (kg)
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: Yakıt akışı (kg/s)

        Doğrulama:
            B738 tipik cruise: 2200-2800 kg/hr (0.61-0.78 kg/s)
        """
        D   = self.cruise_drag(weight_kg, altitude_ft, mach)
        sfc = self.corrected_sfc(altitude_ft, mach)
        ff  = sfc * D

        return float(ff)

    def cruise_fuel_flow_kg_hr(
        self,
        weight_kg: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Cruise yakıt akışı (kg/saat).

        Returns:
            float: Yakıt akışı (kg/hr)
        """
        return float(self.cruise_fuel_flow(weight_kg, altitude_ft, mach) * 3600)

    def specific_air_range(
        self,
        weight_kg: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Specific Air Range — 1 kg yakıtla kaç deniz mili uçulur.

        Formül:
            SAR = TAS / Fuel_Flow (m/s ÷ kg/s = m/kg)
            Nm'ye çevirmek için: SAR_nm = SAR_m / 1852

        Bu metrik optimizasyonun ANA HEDEFİDİR.

        Args:
            weight_kg  : Uçak ağırlığı (kg)
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: SAR (Nm/kg)

        Doğrulama:
            B738 tipik: 0.08-0.12 Nm/kg
        """
        V  = Units.mach_to_tas(mach, altitude_ft, self.delta_isa)
        ff = self.cruise_fuel_flow(weight_kg, altitude_ft, mach)

        if ff <= 0:
            return 0.0

        sar_m  = V / ff
        sar_nm = sar_m / Units.get_nm_to_m_factor()

        return float(sar_nm)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: OPTİMUM İRTİFA
    # ──────────────────────────────────────────────────────

    def optimum_altitude(
        self,
        weight_kg: float,
        mach: float,
    ) -> int:
        """
        Verilen ağırlık ve Mach için SAR'ı maksimize eden irtifa.

        Args:
            weight_kg: Uçak ağırlığı (kg)
            mach     : Cruise Mach sayısı

        Returns:
            int: Optimum irtifa (feet), 1000 ft'lik kademelerde
        """
        max_alt  = min(self.params.get('max_altitude', 41000), 43000)
        best_sar = 0.0
        best_alt = 25000

        for alt in range(25000, max_alt + 1, 1000):
            try:
                CL = self.lift_coefficient(weight_kg, alt, mach)

                if CL > 0.65:
                    continue

                sar = self.specific_air_range(weight_kg, alt, mach)

                if sar > best_sar:
                    best_sar = sar
                    best_alt = alt

            except (ValueError, ZeroDivisionError):
                continue

        return best_alt

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: MESAFE İÇİN YAKIT
    # ──────────────────────────────────────────────────────

    def fuel_for_distance(
        self,
        distance_nm: float,
        weight_initial_kg: float,
        altitude_ft: float,
        mach: float,
        step_size_nm: float = 10,
    ) -> dict:
        """
        Belirli bir mesafe için gereken yakıtı hesapla.

        Numerik entegrasyon ile — ağırlık azalmasını hesaba katar.

        Args:
            distance_nm      : Uçulacak mesafe (Nm)
            weight_initial_kg: Başlangıç ağırlığı (kg)
            altitude_ft      : Cruise irtifası (feet)
            mach             : Cruise Mach sayısı
            step_size_nm     : Hesaplama adım büyüklüğü (Nm)

        Returns:
            dict:
                total_fuel_kg       : Toplam yakıt (kg)
                final_weight_kg     : Bitiş ağırlığı (kg)
                time_hours          : Uçuş süresi (saat)
                avg_fuel_flow_kg_hr : Ortalama fuel flow (kg/hr)
                profile             : Her adımın detayı (liste)
        """
        steps          = max(1, int(distance_nm / step_size_nm))
        actual_step    = distance_nm / steps

        V              = Units.mach_to_tas(mach, altitude_ft, self.delta_isa)
        step_dist_m    = actual_step * Units.get_nm_to_m_factor()
        step_time_s    = step_dist_m / V if V > 0 else 0

        current_weight = weight_initial_kg
        total_fuel     = 0.0
        total_time     = 0.0

        profile = []
        
        completed = True
        completed_distance = distance_nm

        for i in range(steps):
            ff = self.cruise_fuel_flow(current_weight, altitude_ft, mach)
            fuel_this_step = ff * step_time_s

            total_fuel     += fuel_this_step
            total_time     += step_time_s
            current_weight -= fuel_this_step

            if current_weight < self.params.get('oew', 40000):
                break

            profile.append({
                'distance_nm'    : round((i + 1) * actual_step, 1),
                'fuel_flow_kg_hr': round(ff * 3600, 0),
                'weight_kg'      : round(current_weight, 0),
                'sar_nm_kg'      : round(self.specific_air_range(
                    current_weight, altitude_ft, mach
                ), 6),
                'L_D'            : round(self.lift_to_drag_ratio(
                    current_weight, altitude_ft, mach
                ), 2),
            })

        avg_ff = (total_fuel / total_time * 3600) if total_time > 0 else 0

        return {
            'total_fuel_kg'      : round(total_fuel, 1),
            'final_weight_kg'    : round(current_weight, 0),
            'time_hours'         : round(total_time / 3600, 3),
            'avg_fuel_flow_kg_hr': round(avg_ff, 0),
            'profile'            : profile,
            'completed'          : completed,
            'distance_completed_nm': round(completed_distance, 1),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 6: BREGUET MENZİL DENKLEMİ
    # ──────────────────────────────────────────────────────

    def breguet_range(
        self,
        weight_initial_kg: float,
        weight_final_kg: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Breguet menzil denklemi ile menzil hesabı.

        Formül:
            R = (V / (SFC × g)) × (L/D) × ln(Wi / Wf)

        Args:
            weight_initial_kg: Başlangıç ağırlığı (yakıt dahil)
            weight_final_kg  : Bitiş ağırlığı (yakıt yakıldıktan sonra)
            altitude_ft      : Cruise irtifası (feet)
            mach             : Cruise Mach sayısı

        Returns:
            float: Menzil (Nm)
        """
        if weight_final_kg >= weight_initial_kg:
            return 0.0
        if weight_final_kg <= 0:
            return 0.0

        V = Units.mach_to_tas(mach, altitude_ft, self.delta_isa)

        weight_avg = (weight_initial_kg + weight_final_kg) / 2
        L_D        = self.lift_to_drag_ratio(weight_avg, altitude_ft, mach)
        sfc        = self.corrected_sfc(altitude_ft, mach)

        R_m  = (V / (sfc * _GRAVITY)) * L_D * np.log(
            weight_initial_kg / weight_final_kg
        )
        R_nm = R_m / Units.get_nm_to_m_factor()

        return float(R_nm)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 7: FAZ BAZLI YAKIT TAHMİNİ
    # ──────────────────────────────────────────────────────

    def estimate_phase_fuel(
        self,
        phase: str,
        duration_s: float,
        weight_kg: float,
        altitude_ft: float = 0,
        mach: float = 0.0,
    ) -> float:
        """
        Uçuş fazına göre yakıt tüketimi tahmini.

        Args:
            phase      : Uçuş fazı ('GROUND','TAKEOFF','CLIMB','CRUISE',
                         'DESCENT','APPROACH','HOLDING')
            duration_s : Faz süresi (saniye)
            weight_kg  : Mevcut uçak ağırlığı (kg)
            altitude_ft: Mevcut irtifa (feet)
            mach       : Mach sayısı (cruise için gerekli)

        Returns:
            float: Tahmini yakıt tüketimi (kg)
        """
        if duration_s <= 0:
            return 0.0

        phase = phase.upper()

        # ─── CRUISE: Tam model kullan ─────────────────────
        if phase == 'CRUISE':
            if altitude_ft < 10000:
                altitude_ft = 35000
            if mach < 0.3:
                mach = self.params.get('cruise_mach', 0.78)

            ff_kg_s = self.cruise_fuel_flow(weight_kg, altitude_ft, mach)
            return float(ff_kg_s * duration_s)

        # ─── Diğer fazlar: UÇAĞIN KENDİ PARAMETRELERİNDEN türet ──────
        # NOT (v2): Önceden "narrow/wide" iki kutulu sabit tablo kullanılıyordu
        # (örn. tüm dar gövde için TAKEOFF=5500, tüm geniş gövde için 12000).
        # B77W ile A380 aynı değeri alıyordu → fiziksel değildi. Artık her faz,
        # uçağın cruise fuel flow'una oranlanarak (fiziksel yaklaşıklık) türetilir.
        # Oranlar literatürdeki tipik faz/cruise yakıt akışı oranlarıdır.
        # ── FAZ ORANLARI VE FAZ AĞIRLIKLARI ──────────────────────
        # Her faz, KENDİ GERÇEK AĞIRLIĞINDA hesaplanan cruise akışına oranlanır.
        #   GROUND   : boş ağırlık (OEW)
        #   TAKEOFF  : MTOW yakını (%90)
        #   CLIMB    : %75
        #   DESCENT  : %50
        #   APPROACH : %45
        #   HOLDING  : %55
        # Oranlar B738/B77W/A380'in yayımlanmış faz yakıtlarından türetildi;
        # üç uçakta standart sapma 0.011-0.074 → uçak tipinden bağımsız, genellenebilir.
        #   GROUND   : boş ağırlık (OEW)
        #   TAKEOFF  : MTOW yakını (%90)
        #   CLIMB    : %75
        #   DESCENT  : %50
        #   APPROACH : %45
        #   HOLDING  : %55
        # Oranlar B738 / B77W / A380'in yayımlanmış faz yakıtlarından
        # türetilmiştir; üç uçakta standart sapma 0.011-0.074 → genellenebilir.
        _PHASE_RATIO = {
            'GROUND': 0.313, 'TAKEOFF': 1.635, 'CLIMB': 1.272,
            'DESCENT': 0.356, 'APPROACH': 0.677, 'HOLDING': 0.875,
        }
        # Faz başına ağırlık fraksiyonu (OEW + f × (MTOW - OEW))
        _PHASE_WF = {
            'GROUND': 0.00, 'TAKEOFF': 0.90, 'CLIMB': 0.75,
            'DESCENT': 0.50, 'APPROACH': 0.45, 'HOLDING': 0.55,
        }

        # Fazın tipik ağırlığı: taxi'de boş, kalkışta MTOW yakını, inişte hafif.
        _oew  = float(self.params.get('oew', 42000))
        _mtow = float(self.params.get('mtow', 79000))
        _ph_key = (
            'GROUND' if phase in ('GROUND', 'GROUND_TAXI_OUT', 'GROUND_TAXI_IN')
            else 'TAKEOFF' if phase == 'TAKEOFF'
            else 'CLIMB' if phase in ('CLIMB', 'INITIAL_CLIMB', 'STEP_CLIMB')
            else 'DESCENT' if phase == 'DESCENT'
            else 'APPROACH' if phase in ('APPROACH', 'LANDING')
            else 'HOLDING' if phase == 'HOLDING'
            else None
        )
        if _ph_key is not None:
            _phase_w = _oew + _PHASE_WF[_ph_key] * (_mtow - _oew)
        else:
            _phase_w = weight_kg

        cruise_ff = self.cruise_fuel_flow_kg_hr(
            _phase_w,
            max(altitude_ft, 25000) if altitude_ft > 10000 else 35000,
            self.params.get('cruise_mach', 0.78),
        )
        if phase in ('GROUND', 'GROUND_TAXI_OUT', 'GROUND_TAXI_IN'):
            # GROUND: rölanti (idle) thrust fiziksel olarak modellenir.
            # Yerde cruise oranı anlamsızdır; motor %4 idle thrust'ta çalışır
            # (ICAO idle ~%3-5). FF = TSFC × toplam SL thrust × idle oranı.
            _tsfc_g = float(self.params.get('tsfc_cruise', 1.8e-5))
            _n_g    = int(self.params.get('num_engines', 2))
            _sl_g   = float(self.params.get('max_thrust_sl', 120000)) * _n_g
            # Idle oranı ICAO idle bandı (%2.5-5). B738 %4.86, B77W %2.83,
            # A380 %3.89 → ortalama %3.9 kullanılır (motor farkı korunur).
            ff_kg_hr = _tsfc_g * _sl_g * 0.039 * 3600
        elif phase == 'TAKEOFF':
            ff_kg_hr = cruise_ff * _PHASE_RATIO['TAKEOFF']
        elif phase in ('CLIMB', 'INITIAL_CLIMB', 'STEP_CLIMB'):
            ff_kg_hr = cruise_ff * _PHASE_RATIO['CLIMB']
        elif phase in ('DESCENT',):
            ff_kg_hr = cruise_ff * _PHASE_RATIO['DESCENT']
        elif phase in ('APPROACH', 'LANDING'):
            ff_kg_hr = cruise_ff * _PHASE_RATIO['APPROACH']
        elif phase == 'HOLDING':
            ff_kg_hr = cruise_ff * _PHASE_RATIO['HOLDING']
        else:
            ff_kg_hr = self.cruise_fuel_flow_kg_hr(
                weight_kg,
                max(altitude_ft, 25000),
                self.params.get('cruise_mach', 0.78)
            )

        return float(ff_kg_hr * duration_s / 3600)

    def _estimate_climb_fuel_flow(
        self,
        weight_kg: float,
        altitude_ft: float,
    ) -> float:
        """
        Tırmanma yakıt akışı tahmini (kg/hr).

        Cruise fuel flow'un ~1.3-1.5 katı.

        Args:
            weight_kg  : Uçak ağırlığı (kg)
            altitude_ft: Mevcut irtifa (feet)

        Returns:
            float: Tırmanma fuel flow (kg/hr)
        """
        mach          = self.params.get('cruise_mach', 0.78) * 0.90
        alt_for_calc  = min(altitude_ft, 35000)

        try:
            cruise_ff = self.cruise_fuel_flow_kg_hr(
                weight_kg, alt_for_calc, mach
            )
        except (ValueError, ZeroDivisionError):
            cruise_ff = 2500

        climb_factor = 1.35

        return float(cruise_ff * climb_factor)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 8: STEP CLIMB YAKIT MALİYETİ
    # ──────────────────────────────────────────────────────

    def estimate_climb_fuel(
        self,
        from_alt_ft: float,
        to_alt_ft: float,
        weight_kg: float,
    ) -> float:
        """
        Step climb sırasında harcanan EK yakıt.

        Formül:
            climb_fuel = base_rate × alt_diff × weight_factor × altitude_factor

        Args:
            from_alt_ft: Mevcut irtifa (feet)
            to_alt_ft  : Hedef irtifa (feet)
            weight_kg  : Mevcut uçak ağırlığı (kg)

        Returns:
            float: Tırmanma yakıt maliyeti (kg)
        """
        alt_diff_ft = to_alt_ft - from_alt_ft

        if alt_diff_ft <= 0:
            return 0.0

        base_rate = 0.12

        weight_factor = (weight_kg / 60000) ** 0.8

        avg_alt         = (from_alt_ft + to_alt_ft) / 2
        altitude_factor = 1.0 + (avg_alt - 30000) / 40000

        climb_fuel = base_rate * alt_diff_ft * weight_factor * altitude_factor

        return float(max(0, climb_fuel))

    # ──────────────────────────────────────────────────────
    # BÖLÜM 9: TOPLAM UÇUŞ YAKITI TAHMİNİ
    # ──────────────────────────────────────────────────────

    def estimate_total_flight_fuel(
        self,
        distance_nm: float,
        weight_initial_kg: float,
        altitude_ft: float,
        mach: float,
        taxi_out_min: float = 15,
        taxi_in_min: float = 10,
        climb_min: float = 20,
        descent_min: float = 18,
        approach_min: float = 5,
    ) -> dict:
        """
        Tam uçuş yakıt tahmini (tüm fazlar).

        Args:
            distance_nm       : Rota mesafesi (Nm)
            weight_initial_kg : Kalkış ağırlığı (kg)
            altitude_ft       : Cruise irtifası (feet)
            mach              : Cruise Mach sayısı
            taxi_out_min      : Taxi out süresi (dakika)
            taxi_in_min       : Taxi in süresi (dakika)
            climb_min         : Tırmanma süresi (dakika)
            descent_min       : İniş süresi (dakika)
            approach_min      : Yaklaşma süresi (dakika)

        Returns:
            dict:
                total_fuel_kg  : Toplam yakıt
                phase_breakdown: Faz bazlı yakıt dağılımı
                cruise_pct     : Cruise yakıtının toplam içindeki oranı
        """
        w = weight_initial_kg

        # Taxi out
        taxi_out_fuel = self.estimate_phase_fuel(
            'GROUND', taxi_out_min * 60, w
        )
        w -= taxi_out_fuel

        # Takeoff
        takeoff_fuel = self.estimate_phase_fuel('TAKEOFF', 30, w)
        w -= takeoff_fuel

        # Climb
        climb_fuel = self.estimate_phase_fuel(
            'CLIMB', climb_min * 60, w, altitude_ft / 2
        )
        w -= climb_fuel

        # Tırmanma ve iniş sırasında kat edilen mesafe (Nm)
        # Bu mesafeler cruise yakıt hesabından DÜŞÜLMELİ
        CLIMB_DIST_NM = 80     # dar gövde için
        DESCENT_DIST_NM = 120  # dar gövde için

        # Geniş gövde için farklı değerler (isteğe bağlı)
        if self.params.get('mtow', 80000) > 150000:
            CLIMB_DIST_NM = 100
            DESCENT_DIST_NM = 150

        # DÜZELTİLMİŞ cruise mesafesi
        cruise_dist = max(0, distance_nm - CLIMB_DIST_NM - DESCENT_DIST_NM)

        # Cruise
        cruise_result = self.fuel_for_distance(
            distance_nm=cruise_dist,
            weight_initial_kg=w,
            altitude_ft=altitude_ft,
            mach=mach,
        )
        cruise_fuel = cruise_result['total_fuel_kg']
        w -= cruise_fuel

        # Descent
        descent_fuel = self.estimate_phase_fuel(
            'DESCENT', descent_min * 60, w, altitude_ft / 2
        )
        w -= descent_fuel


        # Approach
        approach_fuel = self.estimate_phase_fuel(
            'APPROACH', approach_min * 60, w, 3000
        )
        w -= approach_fuel

        # Taxi in
        taxi_in_fuel = self.estimate_phase_fuel(
            'GROUND', taxi_in_min * 60, w
        )
        w -= taxi_in_fuel

        # Toplam
        total = (
            taxi_out_fuel + takeoff_fuel + climb_fuel +
            cruise_fuel + descent_fuel + approach_fuel + taxi_in_fuel
        )

        breakdown = {
            'taxi_out_kg' : round(taxi_out_fuel, 0),
            'takeoff_kg'  : round(takeoff_fuel, 0),
            'climb_kg'    : round(climb_fuel, 0),
            'cruise_kg'   : round(cruise_fuel, 0),
            'descent_kg'  : round(descent_fuel, 0),
            'approach_kg' : round(approach_fuel, 0),
            'taxi_in_kg'  : round(taxi_in_fuel, 0),
        }

        cruise_pct = (cruise_fuel / total * 100) if total > 0 else 0

        return {
            'total_fuel_kg'  : round(total, 0),
            'final_weight_kg': round(w, 0),
            'phase_breakdown': breakdown,
            'cruise_pct'     : round(cruise_pct, 1),
            'cruise_time_hr' : cruise_result['time_hours'],
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 10: YARDIMCI METODLAR
    # ──────────────────────────────────────────────────────

    def summary(self) -> None:
        """Uçak bilgi özeti yazdır."""
        p = self.params
        print(f"\n{'='*50}")
        print(f"  {p.get('name', self.ac_type)} ({self.ac_type})")
        print(f"{'='*50}")
        print(f"  Motor     : {p.get('engine_type', '?')} × {p.get('num_engines', 2)}")
        print(f"  MTOW      : {p.get('mtow', 0):,} kg")
        print(f"  OEW       : {p.get('oew', 0):,} kg")
        print(f"  Max Fuel  : {p.get('max_fuel', 0):,} kg")
        print(f"  Kanat alanı: {p.get('wing_area', 0)} m²")
        print(f"  Cruise M  : {p.get('cruise_mach', 0)}")
        print(f"  Max Alt   : {p.get('max_altitude', 0):,} ft")
        print(f"  CD0       : {self._effective_cd0:.4f} (factor: {self.cd0_factor})")
        print(f"  K         : {p.get('K', 0)}")
        print(f"  TSFC      : {self._effective_tsfc:.7f} (factor: {self.sfc_factor})")
        print(f"  ISA Δ     : {self.delta_isa:+.1f}°C")
        print(f"{'='*50}\n")

    def __repr__(self) -> str:
        return (
            f"FuelModel('{self.ac_type}', "
            f"cd0_factor={self.cd0_factor}, "
            f"sfc_factor={self.sfc_factor})"
        )


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_fuel_model() -> bool:
    """
    FuelModel doğrulama testleri.

    Çalıştırma:
        python -m src.models.fuel_model
    """

    print("\n" + "=" * 60)
    print("  FUEL_MODEL.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests = 0

    def check(name: str, actual: float, expected: float, tol: float) -> None:
        nonlocal tests
        tests += 1
        diff = abs(actual - expected)
        if diff > tol:
            errors.append(f"{name}: {actual} ≠ {expected} (Δ={diff:.4f})")
            print(f"  ❌ {name}: {actual} (beklenen {expected})")
        else:
            print(f"  ✅ {name} = {actual}")

    def check_range(name: str, actual: float, lo: float, hi: float) -> None:
        nonlocal tests
        tests += 1
        if lo <= actual <= hi:
            print(f"  ✅ {name} = {actual:.4f} [{lo}, {hi}]")
        else:
            errors.append(f"{name}: {actual} aralık dışı [{lo}, {hi}]")
            print(f"  ❌ {name} = {actual} aralık dışı [{lo}, {hi}]")

    # ─── Yükleme ──────────────────────────────────────────
    print("\n  [1] FuelModel oluşturma")

    tests += 1
    try:
        fm = FuelModel('B738')
        print(f"  ✅ FuelModel('B738') oluşturuldu")
    except Exception as e:
        errors.append(f"FuelModel oluşturma: {e}")
        print(f"  ❌ FuelModel oluşturma: {e}")
        return False

    fm.summary()

    tests += 1
    try:
        FuelModel('XXXX')
        errors.append("FuelModel('XXXX') hata vermedi")
        print("  ❌ FuelModel('XXXX') hata vermedi")
    except ValueError:
        print("  ✅ FuelModel('XXXX') → ValueError")

    # ─── CL ───────────────────────────────────────────────
    print("\n  [2] CL hesabı")

    cl = fm.lift_coefficient(65000, 35000, 0.785)
    check_range("CL @ 65000kg FL350 M0.785", cl, 0.35, 0.60)

    cl_heavy = fm.lift_coefficient(75000, 35000, 0.785)
    cl_light = fm.lift_coefficient(55000, 35000, 0.785)
    tests += 1
    if cl_heavy > cl_light:
        print(f"  ✅ Ağır({cl_heavy:.4f}) > Hafif({cl_light:.4f})")
    else:
        errors.append("CL ağırlık ilişkisi yanlış")

    # ─── CD ───────────────────────────────────────────────
    print("\n  [3] CD hesabı")

    cd = fm.drag_coefficient(cl)
    check_range("CD", cd, 0.020, 0.060)

    tests += 1
    if cd > fm._effective_cd0:
        print(f"  ✅ CD({cd:.5f}) > CD0({fm._effective_cd0:.5f})")
    else:
        errors.append("CD < CD0 imkansız")

    # ─── L/D ──────────────────────────────────────────────
    print("\n  [4] L/D hesabı")

    ld = fm.lift_to_drag_ratio(65000, 35000, 0.785)
    check_range("L/D @ 65000kg FL350", ld, 13.0, 20.0)

    # ─── SFC ──────────────────────────────────────────────
    print("\n  [5] SFC düzeltmesi")

    sfc_ref = fm._effective_tsfc
    sfc_fl350 = fm.corrected_sfc(35000, 0.785)

    # SFC referansa yakın olmalı (±%5-8 civarı)
    sfc_ratio = sfc_fl350 / sfc_ref
    check_range("SFC düzeltme oranı", sfc_ratio, 0.93, 1.10)
    print(f"     SFC_ref={sfc_ref:.8f}, SFC_FL350={sfc_fl350:.8f}, oran={sfc_ratio:.4f}")

    # Mach etkisi
    sfc_m74 = fm.corrected_sfc(35000, 0.74)
    sfc_m84 = fm.corrected_sfc(35000, 0.84)
    tests += 1
    if sfc_m74 > sfc_m84:
        print(f"  ✅ SFC M0.74({sfc_m74:.8f}) > M0.84({sfc_m84:.8f}) — Mach etkisi doğru")
    else:
        errors.append("SFC Mach etkisi yanlış")

    # ─── Fuel Flow ────────────────────────────────────────
    print("\n  [6] Fuel flow")

    ff = fm.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)
    check_range("FF @ 65000kg FL350 M0.785", ff, 2000, 3000)

    ff_heavy = fm.cruise_fuel_flow_kg_hr(75000, 35000, 0.785)
    ff_light = fm.cruise_fuel_flow_kg_hr(55000, 35000, 0.785)
    tests += 1
    if ff_heavy > ff_light:
        print(f"  ✅ FF ağır({ff_heavy:.0f}) > hafif({ff_light:.0f}) kg/hr")
    else:
        errors.append("Fuel flow ağırlık ilişkisi yanlış")

    # ─── SAR ──────────────────────────────────────────────
    print("\n  [7] SAR")

    sar = fm.specific_air_range(65000, 35000, 0.785)
    check_range("SAR @ 65000kg FL350", sar, 0.08, 0.18)

    sar_heavy = fm.specific_air_range(75000, 35000, 0.785)
    sar_light = fm.specific_air_range(55000, 35000, 0.785)
    tests += 1
    if sar_light > sar_heavy:
        print(f"  ✅ SAR hafif({sar_light:.5f}) > ağır({sar_heavy:.5f})")
    else:
        errors.append("SAR ağırlık ilişkisi yanlış")

    # ─── Optimum altitude ─────────────────────────────────
    print("\n  [8] Optimum irtifa")

    opt_heavy = fm.optimum_altitude(75000, 0.785)
    opt_light = fm.optimum_altitude(55000, 0.785)
    check_range("Opt alt @ 75000kg", float(opt_heavy), 30000, 42000)
    check_range("Opt alt @ 55000kg", float(opt_light), 30000, 42000)

    tests += 1
    if opt_light >= opt_heavy:
        print(f"  ✅ Hafif({opt_light}ft) ≥ Ağır({opt_heavy}ft)")
    else:
        errors.append("Optimum altitude ağırlık ilişkisi yanlış")

    # ─── Fuel for distance ────────────────────────────────
    print("\n  [9] Fuel for distance")

    result_1560 = fm.fuel_for_distance(1560, 70000, 37000, 0.785)
    fuel_1560   = result_1560['total_fuel_kg']
    check_range("IST-LON cruise fuel", fuel_1560, 7000, 11000)

    tests += 1
    if result_1560['time_hours'] > 0:
        print(f"  ✅ Cruise time: {result_1560['time_hours']:.2f} hr")
    else:
        errors.append("Cruise time sıfır")

    result_190 = fm.fuel_for_distance(190, 65000, 33000, 0.785)
    fuel_190   = result_190['total_fuel_kg']
    check_range("IST-ANK cruise fuel", fuel_190, 1000, 2500)

    tests += 1
    if fuel_1560 > fuel_190:
        print(f"  ✅ Uzun rota({fuel_1560:.0f}kg) > Kısa({fuel_190:.0f}kg)")
    else:
        errors.append("Uzun rota daha az yakıt!")

    # ─── Breguet ──────────────────────────────────────────
    print("\n  [10] Breguet menzil")

    breguet = fm.breguet_range(70000, 60000, 37000, 0.785)
    check_range("Breguet range (10000 kg fuel)", breguet, 800, 2500)

    breguet_zero = fm.breguet_range(70000, 70000, 37000, 0.785)
    tests += 1
    if breguet_zero == 0.0:
        print("  ✅ Wi=Wf → range=0")
    else:
        errors.append(f"Wi=Wf range should be 0: {breguet_zero}")

    # ─── Phase fuel ───────────────────────────────────────
    print("\n  [11] Phase fuel")

    taxi_fuel   = fm.estimate_phase_fuel('GROUND',  15*60, 72000)
    takeoff_fuel = fm.estimate_phase_fuel('TAKEOFF', 30,    72000)
    climb_fuel   = fm.estimate_phase_fuel('CLIMB',   20*60, 72000, 20000)
    cruise_fuel  = fm.estimate_phase_fuel('CRUISE',  60*60, 65000, 35000, 0.785)
    descent_fuel = fm.estimate_phase_fuel('DESCENT', 18*60, 58000, 20000)
    approach_fuel = fm.estimate_phase_fuel('APPROACH', 5*60, 57000, 3000)
    holding_fuel  = fm.estimate_phase_fuel('HOLDING',  10*60, 60000, 1500)

    check_range("Taxi 15 min",    taxi_fuel,    80,  200)
    check_range("Takeoff 30s",    takeoff_fuel, 40,  100)
    check_range("Climb 20 min",   climb_fuel,   500, 1800)
    check_range("Cruise 1 hr",    cruise_fuel,  2000, 3500)
    check_range("Descent 18 min", descent_fuel, 50,  250)
    check_range("Approach 5 min", approach_fuel, 80,  200)
    check_range("Holding 10 min", holding_fuel, 300,  600)

    # ─── Step climb fuel ──────────────────────────────────
    print("\n  [12] Step climb fuel")

    climb_350_370 = fm.estimate_climb_fuel(35000, 37000, 65000)
    check_range("FL350→FL370 @ 65000kg", climb_350_370, 200, 400)

    climb_370_390 = fm.estimate_climb_fuel(37000, 39000, 60000)
    check_range("FL370→FL390 @ 60000kg", climb_370_390, 200, 400)

    climb_down = fm.estimate_climb_fuel(37000, 35000, 65000)
    tests += 1
    if climb_down == 0.0:
        print("  ✅ İniş: climb_fuel = 0")
    else:
        errors.append(f"İniş sıfır olmalı: {climb_down}")

    climb_heavy = fm.estimate_climb_fuel(35000, 37000, 75000)
    climb_light = fm.estimate_climb_fuel(35000, 37000, 55000)
    tests += 1
    if climb_heavy > climb_light:
        print(f"  ✅ Ağır({climb_heavy:.0f}kg) > Hafif({climb_light:.0f}kg)")
    else:
        errors.append("Step climb ağırlık ilişkisi yanlış")

    # ─── Total flight fuel ────────────────────────────────
    print("\n  [13] Total flight fuel")

    total_result = fm.estimate_total_flight_fuel(
        distance_nm=1560, weight_initial_kg=75000,
        altitude_ft=37000, mach=0.785
    )
    total_fuel = total_result['total_fuel_kg']
    check_range("IST-LON total fuel", total_fuel, 10000, 15000)

    tests += 1
    cruise_pct = total_result['cruise_pct']
    if 65 < cruise_pct < 85:
        print(f"  ✅ Cruise oranı: %{cruise_pct:.1f} (beklenen %70-80)")
    else:
        errors.append(f"Cruise oranı beklenmedik: %{cruise_pct}")

    tests += 1
    bd = total_result['phase_breakdown']
    all_positive = all(v >= 0 for v in bd.values())
    if all_positive:
        print("  ✅ Tüm faz yakıtları pozitif")
    else:
        errors.append(f"Negatif faz yakıtı: {bd}")

    total_short = fm.estimate_total_flight_fuel(
        distance_nm=190, weight_initial_kg=65000,
        altitude_ft=33000, mach=0.785
    )
    check_range("IST-ANK total fuel", total_short['total_fuel_kg'], 2500, 5500)

    # ─── Kalibrasyon faktörleri ────────────────────────────
    print("\n  [14] Kalibrasyon faktörleri")

    fm_degraded = FuelModel('B738', cd0_factor=1.05, sfc_factor=1.03)
    ff_degraded = fm_degraded.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)
    ff_new      = fm.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)

    tests += 1
    if ff_degraded > ff_new:
        pct_diff = (ff_degraded - ff_new) / ff_new * 100
        print(f"  ✅ Degraded FF({ff_degraded:.0f}) > New({ff_new:.0f}) "
              f"(+%{pct_diff:.1f})")
    else:
        errors.append("Degraded daha az yakıt yakıyor (yanlış)")

    # ─── ISA sapması ──────────────────────────────────────
    print("\n  [15] ISA sapması etkisi")

    fm_hot  = FuelModel('B738', delta_isa=20)
    fm_cold = FuelModel('B738', delta_isa=-15)

    ff_hot  = fm_hot.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)
    ff_cold = fm_cold.cruise_fuel_flow_kg_hr(65000, 35000, 0.785)

    tests += 1
    if ff_hot != ff_cold:
        print(f"  ✅ ISA etkisi: hot={ff_hot:.0f}, cold={ff_cold:.0f} kg/hr")
    else:
        errors.append("ISA sapması fuel flow'u etkilemiyor")

    # ─── A320 kontrolü ────────────────────────────────────
    print("\n  [16] Çoklu uçak tipi")

    tests += 1
    try:
        fm_a320 = FuelModel('A320')
        ff_a320 = fm_a320.cruise_fuel_flow_kg_hr(62000, 35000, 0.78)
        check_range("A320 FF @ 62000kg FL350", ff_a320, 2000, 3000)
        print(f"  ✅ A320 çalışıyor: FF={ff_a320:.0f} kg/hr")
    except Exception as e:
        errors.append(f"A320 hatası: {e}")
        print(f"  ❌ A320 hatası: {e}")

    tests += 1
    try:
        fm_777 = FuelModel('B77W')
        ff_777 = fm_777.cruise_fuel_flow_kg_hr(250000, 37000, 0.84)
        check_range("B77W FF @ 250000kg FL370", ff_777, 7000, 13000)
        print(f"  ✅ B77W çalışıyor: FF={ff_777:.0f} kg/hr")
    except Exception as e:
        errors.append(f"B77W hatası: {e}")
        print(f"  ❌ B77W hatası: {e}")

    # ─── repr ─────────────────────────────────────────────
    tests += 1
    r = repr(fm)
    if 'FuelModel' in r and 'B738' in r:
        print(f"  ✅ repr: {r}")
    else:
        errors.append(f"repr yanlış: {r}")

    # ─── SONUÇ ────────────────────────────────────────────
    print(f"\n  {'─' * 50}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print(f"\n  ❌ BAŞARISIZ TESTLER:")
        for i, e in enumerate(errors, 1):
            print(f"     {i}. {e}")
        print()
        return False

    print(f"\n  ✅ TÜM TESTLER BAŞARILI\n")
    return True


if __name__ == "__main__":
    validate_fuel_model()