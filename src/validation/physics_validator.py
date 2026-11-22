# src/validation/physics_validator.py

"""
GreenWing Analytics — Fizik Doğrulayıcı
═════════════════════════════════════════

KATMAN 2 / 3: Fiziksel Mantık

Bu dosya HESAPLAMA SONUÇLARININ fiziksel
olarak mantıklı olup olmadığını kontrol eder.

Sorular:
    • Mach > 1 mi? (süpersonik)
    • CL buffet sınırını aşıyor mu?
    • L/D makul aralıkta mı?
    • Fuel flow gerçekçi mi?
    • SAR aralık dışında mı?
    • Tırmanma hızı fiziksel mi?

KULLANIM:
─────────
    from src.validation.physics_validator import PhysicsValidator

    result = PhysicsValidator.validate_aerodynamics(
        CL=0.498, CD=0.033, L_D=15.1, altitude_ft=35000, mach=0.785
    )
    result = PhysicsValidator.validate_fuel_flow(
        fuel_flow_kg_hr=2347, aircraft_type='B738', altitude_ft=35000
    )
"""

from __future__ import annotations

from src.validation.data_validator import ValidationResult


# ═══════════════════════════════════════════════════════════
# FİZİKSEL SINIRLAR
# ═══════════════════════════════════════════════════════════

# Aerodinamik değerler için fiziksel sınırlar
# Kaynak: Havacılık mühendisliği literatürü + gerçek uçak verileri
_PHYSICS_LIMITS = {
    # Kaldırma/sürükleme
    "CL"             : (0.01,   1.40),   # Max stall CL ~1.5 ama cruise'da
    "CD"             : (0.005,  0.15),
    "L_D"            : (5.0,    30.0),
    "CD0"            : (0.005,  0.050),
    "K"              : (0.020,  0.080),

    # Motor/yakıt
    "fuel_flow_kg_hr": (100.0,  15000.0),  # Tek ve çift motor
    "tsfc"           : (0.000005, 0.00005),
    "SAR_nm_per_kg"  : (0.02,   0.25),

    # Uçuş dinamiği
    "mach"           : (0.0,    0.95),
    "climb_rate_fpm" : (-6000,  6000),
    "vertical_rate_ms": (-30,   30),

    # Atmosfer
    "temperature_K"  : (180,    340),
    "pressure_Pa"    : (1000,   110000),
    "density_kg_m3"  : (0.05,   1.35),
}

# Buffet onset CL değerleri — uçak tipine ve Mach'a göre
# Kaynak: Airplane Flight Manual referans değerleri (yaklaşık)
_BUFFET_CL = {
    'B738': {0.70: 0.72, 0.74: 0.68, 0.78: 0.62, 0.80: 0.58, 0.82: 0.54},
    'A320': {0.70: 0.74, 0.74: 0.70, 0.78: 0.64, 0.80: 0.60, 0.82: 0.56},
    'B77W': {0.80: 0.65, 0.82: 0.62, 0.84: 0.57, 0.86: 0.52},
    'B788': {0.82: 0.66, 0.84: 0.62, 0.86: 0.58, 0.88: 0.54},
    'A350': {0.82: 0.68, 0.84: 0.64, 0.86: 0.60, 0.88: 0.56},
    # Varsayılan (bilinmeyen uçak tipi)
    'DEFAULT': {0.70: 0.70, 0.74: 0.66, 0.78: 0.60, 0.80: 0.56, 0.82: 0.52},
}

# FAR 25.251 gereği minimum buffet marjı
FAR_25_251_BUFFET_MARGIN = 1.3  # 1.3g marjı


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class PhysicsValidator:
    """
    Fiziksel mantık doğrulama sınıfı.

    Hesaplama sonuçlarının fizik yasalarıyla uyumlu
    olup olmadığını kontrol eder.

    Kullanım:
        result = PhysicsValidator.validate_aerodynamics(...)
        result = PhysicsValidator.validate_fuel_flow(...)
        result = PhysicsValidator.validate_atmosphere(...)
    """

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: AERODİNAMİK DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_aerodynamics(
        CL: float,
        CD: float,
        L_D: float,
        altitude_ft: float,
        mach: float,
        aircraft_type: str = 'DEFAULT',
    ) -> ValidationResult:
        """
        Aerodinamik katsayıları doğrula.

        Args:
            CL          : Kaldırma katsayısı
            CD          : Sürükleme katsayısı
            L_D         : Kaldırma/sürükleme oranı
            altitude_ft : İrtifa (ft)
            mach        : Mach sayısı
            aircraft_type: ICAO uçak tipi kodu

        Returns:
            ValidationResult

        Kontroller:
            • CL makul aralıkta mı?
            • CD makul aralıkta mı?
            • L/D = CL/CD tutarlı mı?
            • Buffet marjı yeterli mi? (FAR 25.251)
        """
        result = ValidationResult()

        # CL aralığı
        lo, hi = _PHYSICS_LIMITS["CL"]
        if CL < lo or CL > hi:
            result.add_error(
                f"CL={CL:.4f} fiziksel aralık dışı [{lo}, {hi}]."
            )
        elif CL > 0.70:
            result.add_warning(
                f"CL={CL:.4f} yüksek. Cruise'da tipik 0.35-0.60 aralığı."
            )

        # CD aralığı
        lo, hi = _PHYSICS_LIMITS["CD"]
        if CD < lo or CD > hi:
            result.add_error(
                f"CD={CD:.5f} fiziksel aralık dışı [{lo}, {hi}]."
            )

        # L/D tutarlılığı
        if CD > 0:
            calculated_ld = CL / CD
            if abs(calculated_ld - L_D) > 0.1:
                result.add_warning(
                    f"L/D tutarsızlık: verilen={L_D:.2f}, "
                    f"CL/CD={calculated_ld:.2f}."
                )

        lo, hi = _PHYSICS_LIMITS["L_D"]
        if L_D < lo or L_D > hi:
            result.add_error(
                f"L/D={L_D:.2f} fiziksel aralık dışı [{lo}, {hi}]."
            )

        # Buffet marjı (FAR 25.251)
        buffet_result = PhysicsValidator.check_buffet_margin(
            CL, mach, aircraft_type
        )
        result.merge(buffet_result)

        result.stats.update({
            "CL": CL, "CD": CD, "L_D": L_D,
            "altitude_ft": altitude_ft, "mach": mach,
        })

        return result

    @staticmethod
    def check_buffet_margin(
        CL: float,
        mach: float,
        aircraft_type: str = 'DEFAULT',
        required_margin: float = FAR_25_251_BUFFET_MARGIN,
    ) -> ValidationResult:
        """
        Buffet marjını kontrol et (FAR 25.251).

        Args:
            CL             : Mevcut kaldırma katsayısı
            mach           : Mach sayısı
            aircraft_type  : ICAO uçak tipi
            required_margin: Gerekli g marjı (varsayılan 1.3)

        Returns:
            ValidationResult

        Not:
            FAR 25.251: Uçak cruise'da minimum 1.3g manevra yükünde
            buffet onset'e girmemeli.

            DENETİM #46 — BOYUT HATASI:
            Eski kod `cl_limit = cl_buffet_onset / required_margin`
            kullanıyordu, yani 0.62 / 1.3 = 0.4769. Bu YANLIŞ: 1g
            buffet onset CL'i 0.62 olan bir kanat, 1.3g'de 1.3 katı
            kaldırma üretir → o noktada 1g CL'i 0.62 × 1.3 = 0.806
            olan uçuş buffet'a girer. Yani limit ÇARPILMALI.

            Sonuç: eski kod B738'in FL350/M0.78'deki NORMAL seyir
            CL'sini (0.48–0.55) "far exceed" diye HATA olarak
            işaretliyordu. Tüm normal uçuşlar "güvensiz" görünüyordu.

            Formül: CL_operating ≤ CL_onset,1g · required_margin
        """
        result = ValidationResult()

        # Buffet onset CL tablosunu seç
        buffet_table = _BUFFET_CL.get(aircraft_type, _BUFFET_CL['DEFAULT'])

        # En yakın Mach değerini bul
        mach_keys = sorted(buffet_table.keys())
        closest_mach = min(mach_keys, key=lambda m: abs(m - mach))
        cl_buffet_onset = buffet_table[closest_mach]

        # Gerekli CL limiti — ÇARPIM (denetim #46: bölme yanlıştı)
        # 1g buffet onset CL'i olan kanat, n_g manevrada n_g katı
        # kaldırma üretir → izin verilen 1g CL = onset × n_g
        cl_limit = cl_buffet_onset * required_margin

        # Marj hesabı
        margin_pct = (cl_limit - CL) / cl_limit * 100 if cl_limit > 0 else 0

        result.stats["cl_buffet_onset"]  = cl_buffet_onset
        result.stats["cl_limit_far25"]   = round(cl_limit, 4)
        result.stats["buffet_margin_pct"] = round(margin_pct, 1)
        result.stats["reference_mach"]   = closest_mach

        # DENETİM #46b — KONTROL SIRASI HATASI
        # Eski kod önce `CL > cl_buffet_onset` (1g onset) kontrolü
        # yapıp HATA veriyordu; `CL > cl_limit` (1.3g = onset×1.3)
        # kontrolü ise elif olduğu için HİÇ ÇALIŞMIYORDU.
        # Sonuç: onset ile FAR limiti arasındaki bölge (0.62–0.806)
        # hem "güvenli" (FAR marjı var) hem "hata" (onset üstü)
        # sayılıyordu — çelişki.
        #
        # Doğru sıralama: önce FAR limiti (1.3g), sonra onset.
        #   CL > cl_limit          → HATA (FAR 25.251 ihlali)
        #   cl_onset < CL ≤ limit  → UYARI (1g onset üstü, marj ince)
        #   CL ≤ cl_onset          → bilgi
        if CL > cl_limit:
            result.add_error(
                f"CL={CL:.4f} FAR 25.251 limitini ({cl_limit:.4f}) aşıyor! "
                f"1.3g manevrada buffet. Mach={mach:.3f}, {aircraft_type}."
            )
        elif CL > cl_buffet_onset:
            result.add_warning(
                f"CL={CL:.4f} 1g buffet onset ({cl_buffet_onset:.4f}) üstünde "
                f"ama FAR limiti ({cl_limit:.4f}) içinde. "
                f"1.3g marjı yalnız %{margin_pct:.1f} — dikkat."
            )
        elif margin_pct < 15:
            result.add_warning(
                f"Buffet marjı düşük: %{margin_pct:.1f}. "
                f"Turbülanslı havada dikkat. "
                f"Daha alçak irtifa veya daha hafif ağırlık önerilir."
            )
        else:
            result.add_info(
                f"Buffet marjı yeterli: %{margin_pct:.1f}."
            )

        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: YAKIT AKIŞI DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_fuel_flow(
        fuel_flow_kg_hr: float,
        aircraft_type: str = 'B738',
        altitude_ft: float = 35000,
        phase: str = 'cruise',
    ) -> ValidationResult:
        """
        Yakıt akışını doğrula.

        Args:
            fuel_flow_kg_hr: Yakıt akışı (kg/saat)
            aircraft_type  : ICAO uçak tipi
            altitude_ft    : İrtifa (ft)
            phase          : Uçuş fazı

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        # Genel sınır
        lo, hi = _PHYSICS_LIMITS["fuel_flow_kg_hr"]
        if fuel_flow_kg_hr < lo or fuel_flow_kg_hr > hi:
            result.add_error(
                f"Fuel flow={fuel_flow_kg_hr:.0f} kg/hr "
                f"fiziksel aralık dışı [{lo}, {hi}]."
            )
            return result

        # Uçak tipine özgü tipik aralıklar
        TYPICAL_CRUISE_FF = {
            'B738': (2000, 3000),
            'B38M': (1800, 2700),
            'A320': (2000, 2900),
            'A20N': (1700, 2500),
            'B77W': (7000, 12000),
            'B788': (5000, 8000),
            'B789': (5500, 9000),
            'A350': (5500, 9000),
        }

        if aircraft_type in TYPICAL_CRUISE_FF and phase == 'cruise':
            lo_typ, hi_typ = TYPICAL_CRUISE_FF[aircraft_type]
            if fuel_flow_kg_hr < lo_typ or fuel_flow_kg_hr > hi_typ:
                result.add_warning(
                    f"Fuel flow={fuel_flow_kg_hr:.0f} kg/hr, "
                    f"{aircraft_type} cruise için tipik aralık "
                    f"[{lo_typ}, {hi_typ}] kg/hr dışında."
                )

        result.stats["fuel_flow_kg_hr"] = fuel_flow_kg_hr
        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: SAR DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_sar(
        sar_nm_per_kg: float,
        aircraft_type: str = 'B738',
        altitude_ft: float = 35000,
        mach: float = 0.785,
    ) -> ValidationResult:
        """
        Specific Air Range (SAR) değerini doğrula.

        Args:
            sar_nm_per_kg: SAR değeri (Nm/kg)
            aircraft_type: ICAO uçak tipi
            altitude_ft  : İrtifa (ft)
            mach         : Mach sayısı

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        lo, hi = _PHYSICS_LIMITS["SAR_nm_per_kg"]
        if sar_nm_per_kg < lo or sar_nm_per_kg > hi:
            result.add_error(
                f"SAR={sar_nm_per_kg:.5f} Nm/kg "
                f"fiziksel aralık dışı [{lo}, {hi}]."
            )
            return result

        # Tipik SAR aralıkları
        TYPICAL_SAR = {
            'B738': (0.065, 0.130),
            'A320': (0.070, 0.135),
            'B77W': (0.025, 0.055),
            'B788': (0.040, 0.080),
            'A350': (0.042, 0.082),
        }

        if aircraft_type in TYPICAL_SAR:
            lo_t, hi_t = TYPICAL_SAR[aircraft_type]
            if sar_nm_per_kg < lo_t or sar_nm_per_kg > hi_t:
                result.add_warning(
                    f"SAR={sar_nm_per_kg:.5f} Nm/kg, "
                    f"{aircraft_type} için tipik [{lo_t:.3f}, {hi_t:.3f}] dışında. "
                    f"Ağırlık veya irtifa kontrol edin."
                )

        result.stats["SAR_nm_per_kg"] = sar_nm_per_kg
        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: ATMOSFER DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_atmosphere(
        temperature_K: float,
        pressure_Pa: float,
        density_kg_m3: float,
        altitude_ft: float,
    ) -> ValidationResult:
        """
        Atmosfer değerlerini doğrula.

        Args:
            temperature_K : Sıcaklık (Kelvin)
            pressure_Pa   : Basınç (Pascal)
            density_kg_m3 : Yoğunluk (kg/m³)
            altitude_ft   : İrtifa (ft) — referans için

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        for name, value, (lo, hi) in [
            ("temperature_K",   temperature_K,  _PHYSICS_LIMITS["temperature_K"]),
            ("pressure_Pa",     pressure_Pa,    _PHYSICS_LIMITS["pressure_Pa"]),
            ("density_kg_m3",   density_kg_m3,  _PHYSICS_LIMITS["density_kg_m3"]),
        ]:
            if value < lo or value > hi:
                result.add_error(
                    f"{name}={value:.4f} fiziksel aralık dışı [{lo}, {hi}]."
                )

        # İdeal gaz yasası tutarlılığı: P = ρ × R × T
        R_AIR = 287.05
        if temperature_K > 0 and density_kg_m3 > 0:
            expected_P = density_kg_m3 * R_AIR * temperature_K
            if abs(expected_P - pressure_Pa) / pressure_Pa > 0.01:
                result.add_warning(
                    f"İdeal gaz tutarsızlığı: "
                    f"ρRT={expected_P:.0f} Pa ≠ P={pressure_Pa:.0f} Pa "
                    f"(fark %{abs(expected_P-pressure_Pa)/pressure_Pa*100:.1f})."
                )

        result.stats.update({
            "temperature_K": temperature_K,
            "pressure_Pa"  : pressure_Pa,
            "density_kg_m3": density_kg_m3,
            "altitude_ft"  : altitude_ft,
        })

        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: UÇUŞ DİNAMİĞİ DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_flight_dynamics(
        climb_rate_fpm: float,
        mach: float,
        altitude_ft: float,
    ) -> ValidationResult:
        """
        Uçuş dinamiği değerlerini doğrula.

        Args:
            climb_rate_fpm: Dikey hız (fpm, pozitif=tırmanma)
            mach          : Mach sayısı
            altitude_ft   : İrtifa (ft)

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        lo, hi = _PHYSICS_LIMITS["climb_rate_fpm"]
        if climb_rate_fpm < lo or climb_rate_fpm > hi:
            result.add_error(
                f"climb_rate={climb_rate_fpm:.0f} fpm "
                f"fiziksel aralık dışı [{lo}, {hi}]."
            )

        lo, hi = _PHYSICS_LIMITS["mach"]
        if mach < lo or mach > hi:
            result.add_error(
                f"Mach={mach:.3f} fiziksel aralık dışı [{lo}, {hi}]."
            )
        elif mach > 0.90:
            result.add_warning(
                f"Mach={mach:.3f} çok yüksek. "
                f"Ticari jetler için M0.90 üstü nadir."
            )

        result.stats.update({
            "climb_rate_fpm": climb_rate_fpm,
            "mach"          : mach,
            "altitude_ft"   : altitude_ft,
        })

        return result

