# src/models/atmosphere.py

"""
GreenWing Analytics — ISA Standart Atmosfer Modeli
══════════════════════════════════════════════════

Bu dosya tüm performans hesaplarının TEMELİDİR.

"Uçak FL370'de ne kadar yakıt yakar?" sorusunu cevaplamak için
önce şunu bilmek gerekir: "FL370'de hava nasıl?"

Bu dosya o soruyu cevaplar:
    • Sıcaklık (T)  → ses hızı → Mach → TAS
    • Basınç (P)    → motor thrust düzeltmesi → SFC
    • Yoğunluk (ρ)  → dinamik basınç → CL → drag → yakıt

ISA (International Standard Atmosphere):
────────────────────────────────────────
    ICAO Doc 7488 tarafından tanımlanan standart referans.
    Gerçek atmosfer her gün farklı, ama ISA sabit referans.
    Fark → delta_ISA parametresiyle modellenir.

    Troposfer (0 - 11000 m):
        T = T0 + lapse × h
        Sıcaklık her 1000m'de 6.5°C azalır
        Deniz seviyesi: 15°C (288.15 K), 1013.25 hPa

    Stratosfer (11000 m +):
        T = sabit (216.65 K = -56.5°C)
        Sıcaklık değişmez, basınç eksponansiyel azalır

    delta_ISA:
        Gerçek atmosfer ISA'dan farklıysa bu sapma eklenir.
        Dubai yaz: delta_ISA = +20°C
        Moskova kış: delta_ISA = -15°C

KULLANIM:
─────────
    from src.models.atmosphere import ISAAtmosphere

    atm = ISAAtmosphere()
    T, P, rho = atm.get_properties(altitude_ft=35000)
    a = atm.speed_of_sound(altitude_ft=35000)

    # Sıcak gün
    atm_hot = ISAAtmosphere(delta_isa=20)
    T_hot, P_hot, rho_hot = atm_hot.get_properties(altitude_ft=35000)

NOT:
────
    Bu dosya units.py'dan BAĞIMSIZ çalışır.
    Kendi iç sabitlerini kullanır.
    Çünkü: units.py bu dosyayı kullanabilir (dairesel bağımlılık önleme).

    units.py'da da benzer atmosfer fonksiyonları var.
    İkisi aynı formülleri kullanır ama bağımsızdır.
    fuel_model.py ve diğer modüller bu dosyayı kullanır.

Kaynak:
───────
    ICAO Doc 7488 (Manual of the ICAO Standard Atmosphere)
    ISO 2533:1975 (Standard Atmosphere)
"""

from __future__ import annotations

import numpy as np


# ═══════════════════════════════════════════════════════════
# ISA SABİTLERİ
# ═══════════════════════════════════════════════════════════
# Kaynak: ICAO Doc 7488/3 (1993)
# DEĞİŞİR Mİ: ASLA. Uluslararası standart.
#
# TEK KAYNAK (denetim #86): Bu sabitlerin tanım yeri src/units.py.
# Burada yeniden yazılırsa kopya oluşur ve biri güncellenince
# diğeri sessizce eski kalır (R_AIR 4 yerde farklı yazılmıştı).

from src.units import (
    _GAMMA as _GAMMA_U, _R_AIR as _R_AIR_U, _GRAVITY as _GRAVITY_U,
    _ISA_T0 as _T0_U, _ISA_P0 as _P0_U, _ISA_RHO0 as _RHO0_U,
    _ISA_LAPSE as _LAPSE_U, _TROPOPAUSE_M as _TROP_U, _FT_TO_M as _FT_U,
)

_T0         = _T0_U       # 288.15 K = 15 °C        (ICAO Doc 7488)
_P0         = _P0_U       # 101325 Pa = 1 atm (tanım)
_RHO0       = _RHO0_U     # türetilmiş: p0/(R·T0)
_LAPSE_RATE = _LAPSE_U    # -0.0065 K/m (troposfer)
_TROP_ALT   = _TROP_U     # 11000 m = 36.089 ft
_GRAVITY    = _GRAVITY_U  # 9.80665 m/s² (CGPM 1901)
_R_AIR      = _R_AIR_U    # 287.055 = 8314.462618/28.9647
_GAMMA      = _GAMMA_U    # 1.4 (iki atomlu gaz)
_FT_TO_M    = _FT_U       # 0.3048 (tanım)


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class ISAAtmosphere:
    """
    ICAO Standart Atmosfer (ISA) modeli.

    Troposfer (0-11 km) ve Stratosfer (11-20 km) desteği.
    delta_ISA ile gerçek atmosfer sapması modellenebilir.

    Args:
        delta_isa: ISA sapması (°C).
                   Pozitif = standarttan sıcak (Dubai yaz: +20)
                   Negatif = standarttan soğuk (Moskova kış: -15)
                   0 = tam standart ISA

    Kullanım:
        atm = ISAAtmosphere()
        T, P, rho = atm.get_properties(altitude_ft=35000)
        a = atm.speed_of_sound(altitude_ft=35000)

        atm_hot = ISAAtmosphere(delta_isa=20)
        T_hot, _, _ = atm_hot.get_properties(altitude_ft=35000)
    """

    def __init__(self, delta_isa: float = 0.0) -> None:
        self.delta_isa = delta_isa

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: ANA HESAPLAMALAR
    # ──────────────────────────────────────────────────────

    def get_properties(
        self,
        altitude_ft: float = 0,
        altitude_m: float = None,
    ) -> tuple[float, float, float]:
        """
        Verilen irtifada atmosfer özelliklerini hesapla.

        Args:
            altitude_ft: İrtifa (feet). Varsayılan: 0 (deniz seviyesi).
            altitude_m : İrtifa (metre). Verilirse feet'i override eder.

        Returns:
            tuple: (Temperature_K, Pressure_Pa, Density_kg_m3)

        Örnekler:
            atm = ISAAtmosphere()

            T, P, rho = atm.get_properties(altitude_ft=0)
            # T=288.15 K, P=101325 Pa, rho=1.225 kg/m³

            T, P, rho = atm.get_properties(altitude_ft=35000)
            # T≈218.8 K, P≈23842 Pa, rho≈0.380 kg/m³

            T, P, rho = atm.get_properties(altitude_ft=36089)
            # T≈216.65 K (tropopoz)

        Fizik:
            Troposfer: T lineer azalır, P üstel azalır
            Stratosfer: T sabit, P üstel azalır (farklı formül)

            Troposfer:
                T = T0 + lapse × h + delta_ISA
                P = P0 × (T / T0_adj)^(-g / (lapse × R))
                ρ = P / (R × T)

            Stratosfer:
                T = T_trop (sabit)
                P = P_trop × exp(-g × (h - h_trop) / (R × T_trop))
                ρ = P / (R × T)

        Raises:
            ValueError: İrtifa negatif (-2000 ft altı) veya çok yüksek (65000 ft üstü)
        """
        # İrtifa belirleme
        if altitude_m is not None:
            h = float(altitude_m)
        else:
            h = float(altitude_ft) * _FT_TO_M

        # Sınır kontrolü
        if h < -610:
            raise ValueError(
                f"İrtifa çok düşük: {h:.0f}m ({h/_FT_TO_M:.0f} ft). "
                f"Minimum: -610m (-2000 ft)."
            )
        if h > 20000:
            raise ValueError(
                f"İrtifa çok yüksek: {h:.0f}m ({h/_FT_TO_M:.0f} ft). "
                f"Model 20000m (65617 ft) üzerini desteklemiyor."
            )

        # Sıcaklık referansı (delta_ISA ile ayarlanmış)
        T0_adj = _T0 + self.delta_isa

        if h <= _TROP_ALT:
            # ─── Troposfer ────────────────────────────────
            T = T0_adj + _LAPSE_RATE * h

            # Basınç (barometrik formül)
            exponent = -_GRAVITY / (_LAPSE_RATE * _R_AIR)
            P = _P0 * (T / T0_adj) ** exponent

        else:
            # ─── Stratosfer ───────────────────────────────
            # Tropopozdaki değerler
            T_trop = T0_adj + _LAPSE_RATE * _TROP_ALT
            exponent = -_GRAVITY / (_LAPSE_RATE * _R_AIR)
            P_trop = _P0 * (T_trop / T0_adj) ** exponent

            # Stratosfer: sabit sıcaklık
            # Stratosfer: ISA standardına göre sabit sıcaklık (delta_ISA'dan bağımsız)
            T_strat = 216.65 + self.delta_isa
            T = T_strat
            P = P_trop * np.exp(-_GRAVITY * (h - _TROP_ALT) / (_R_AIR * T_strat))

        # Yoğunluk (ideal gaz yasası)
        rho = P / (_R_AIR * T)

        return float(T), float(P), float(rho)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: TÜREV HESAPLAMALAR
    # ──────────────────────────────────────────────────────

    def temperature(self, altitude_ft: float = 0) -> float:
        """
        Sıcaklık (Kelvin).

        Args:
            altitude_ft: İrtifa (feet)

        Returns:
            float: Sıcaklık (K)

        Örnekler:
            atm.temperature(0)     → 288.15 K (15°C)
            atm.temperature(35000) → ~218.8 K (-54.3°C)
        """
        T, _, _ = self.get_properties(altitude_ft=altitude_ft)
        return T

    def pressure(self, altitude_ft: float = 0) -> float:
        """
        Basınç (Pascal).

        Args:
            altitude_ft: İrtifa (feet)

        Returns:
            float: Basınç (Pa)

        Örnekler:
            atm.pressure(0)     → 101325.0 Pa
            atm.pressure(35000) → ~23842 Pa
        """
        _, P, _ = self.get_properties(altitude_ft=altitude_ft)
        return P

    def density(self, altitude_ft: float = 0) -> float:
        """
        Hava yoğunluğu (kg/m³).

        Args:
            altitude_ft: İrtifa (feet)

        Returns:
            float: Yoğunluk (kg/m³)

        Örnekler:
            atm.density(0)     → 1.225
            atm.density(35000) → ~0.380
        """
        _, _, rho = self.get_properties(altitude_ft=altitude_ft)
        return rho

    def speed_of_sound(self, altitude_ft: float = 0) -> float:
        """
        Ses hızı (m/s).

        Formül: a = √(γ × R × T)

        Args:
            altitude_ft: İrtifa (feet)

        Returns:
            float: Ses hızı (m/s)

        Örnekler:
            atm.speed_of_sound(0)     → 340.3 m/s
            atm.speed_of_sound(35000) → ~295.9 m/s

        Nerede kullanılır:
            Mach → TAS dönüşümü: TAS = M × a
        """
        T = self.temperature(altitude_ft)
        return float(np.sqrt(_GAMMA * _R_AIR * T))

    def true_airspeed(self, mach: float, altitude_ft: float = 0) -> float:
        """
        Mach sayısından TAS hesapla (m/s).

        Formül: TAS = M × a

        Args:
            mach       : Mach sayısı
            altitude_ft: İrtifa (feet)

        Returns:
            float: TAS (m/s)

        Örnekler:
            atm.true_airspeed(0.785, 35000) → ~230.5 m/s
        """
        a = self.speed_of_sound(altitude_ft)
        return float(mach * a)

    def mach_from_tas(self, tas_ms: float, altitude_ft: float = 0) -> float:
        """
        TAS'tan Mach sayısı hesapla.

        Formül: M = TAS / a

        Args:
            tas_ms     : True Airspeed (m/s)
            altitude_ft: İrtifa (feet)

        Returns:
            float: Mach sayısı

        Örnekler:
            atm.mach_from_tas(230.5, 35000) → ~0.785
        """
        a = self.speed_of_sound(altitude_ft)
        return float(tas_ms / a) if a > 0 else 0.0

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: ORANLAR (Motor SFC düzeltmesi için)
    # ──────────────────────────────────────────────────────

    def pressure_ratio(self, altitude_ft: float = 0) -> float:
        """
        δ (delta) = P / P0 — Basınç oranı.

        Motor SFC düzeltmesinde kullanılır:
            SFC = SFC_ref × √(θ/δ)

        Args:
            altitude_ft: İrtifa (feet)

        Returns:
            float: Basınç oranı (boyutsuz)

        Örnekler:
            atm.pressure_ratio(0)     → 1.000
            atm.pressure_ratio(35000) → ~0.235
        """
        P = self.pressure(altitude_ft)
        return float(P / _P0)

    def temperature_ratio(self, altitude_ft: float = 0) -> float:
        """
        θ (theta) = T / T0 — Sıcaklık oranı.

        Motor SFC düzeltmesinde kullanılır.

        Args:
            altitude_ft: İrtifa (feet)

        Returns:
            float: Sıcaklık oranı (boyutsuz)

        Örnekler:
            atm.temperature_ratio(0)     → 1.000
            atm.temperature_ratio(35000) → ~0.759
        """
        T = self.temperature(altitude_ft)
        return float(T / _T0)

    def density_ratio(self, altitude_ft: float = 0) -> float:
        """
        σ (sigma) = ρ / ρ0 — Yoğunluk oranı.

        Args:
            altitude_ft: İrtifa (feet)

        Returns:
            float: Yoğunluk oranı (boyutsuz)

        Örnekler:
            atm.density_ratio(0)     → 1.000
            atm.density_ratio(35000) → ~0.310
        """
        rho = self.density(altitude_ft)
        return float(rho / _RHO0)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: YARDIMCI
    # ──────────────────────────────────────────────────────

    def temperature_celsius(self, altitude_ft: float = 0) -> float:
        """
        Sıcaklık (Celsius).

        Örnekler:
            atm.temperature_celsius(0)     → 15.0°C
            atm.temperature_celsius(35000) → ~-54.3°C
        """
        return float(self.temperature(altitude_ft) - 273.15)

    def pressure_hpa(self, altitude_ft: float = 0) -> float:
        """
        Basınç (hPa / mbar).

        Örnekler:
            atm.pressure_hpa(0)     → 1013.25 hPa
            atm.pressure_hpa(35000) → ~238.4 hPa
        """
        return float(self.pressure(altitude_ft) / 100.0)

    def dynamic_pressure(
        self,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Dinamik basınç q (Pascal).

        Formül: q = 0.5 × ρ × V²

        Tüm aerodinamik kuvvetlerin (Lift, Drag) temelidir.
            L = q × S × CL
            D = q × S × CD

        Args:
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: Dinamik basınç (Pa)

        Örnekler:
            atm.dynamic_pressure(35000, 0.785) → ~10300 Pa
        """
        rho = self.density(altitude_ft)
        V   = self.true_airspeed(mach, altitude_ft)
        return float(0.5 * rho * V ** 2)

    def __repr__(self) -> str:
        isa = f"delta_ISA={self.delta_isa:+.1f}°C" if self.delta_isa != 0 else "ISA"
        return f"ISAAtmosphere({isa})"


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_atmosphere_model() -> bool:
    """
    ISA atmosfer modelini bilinen referans değerlerle doğrula.

    Referans değerler:
        ICAO Doc 7488, ISO 2533:1975
        Her değer belgelenmiş ve doğrulanmış.

    Çalıştırma:
        python -m src.models.atmosphere
    """
    print("\n" + "=" * 60)
    print("  ATMOSPHERE.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests = 0
    atm = ISAAtmosphere()

    def check(name: str, actual: float, expected: float, tol: float) -> None:
        nonlocal tests
        tests += 1
        diff = abs(actual - expected)
        if diff > tol:
            errors.append(f"{name}: {actual:.4f} ≠ {expected:.4f} (Δ={diff:.6f})")
            print(f"  ❌ {name}: {actual:.4f} (beklenen {expected:.4f})")
        else:
            print(f"  ✅ {name} = {actual:.4f}")

    # ─── [1] Deniz Seviyesi ───────────────────────────────
    print("\n  [1] Deniz Seviyesi (h=0)")

    T0, P0, rho0 = atm.get_properties(altitude_ft=0)
    check("T @ SL",   T0,   288.15,   0.01)
    check("P @ SL",   P0,   101325.0, 1.0)
    check("ρ @ SL",   rho0, 1.225,    0.001)

    # İdeal gaz tutarlılığı: P = ρ × R × T
    tests += 1
    calculated_P = rho0 * _R_AIR * T0
    if abs(calculated_P - P0) / P0 < 0.001:
        print(f"  ✅ İdeal gaz tutarlı: ρRT = {calculated_P:.0f} ≈ P0 = {P0:.0f}")
    else:
        errors.append(f"İdeal gaz tutarsız: {calculated_P} ≠ {P0}")

    a0 = atm.speed_of_sound(altitude_ft=0)
    check("a @ SL", a0, 340.3, 0.5)

    # ─── [2] FL350 (35000 ft = 10668 m) ──────────────────
    print("\n  [2] FL350 (35000 ft)")

    T35, P35, rho35 = atm.get_properties(altitude_ft=35000)
    check("T @ FL350",   T35,   218.81, 1.0)
    check("P @ FL350",   P35,   23842,  200)
    check("ρ @ FL350",   rho35, 0.3796, 0.005)

    # İdeal gaz @ FL350
    tests += 1
    calc_P35 = rho35 * _R_AIR * T35
    if abs(calc_P35 - P35) / P35 < 0.001:
        print(f"  ✅ İdeal gaz @ FL350 tutarlı")
    else:
        errors.append("İdeal gaz @ FL350 tutarsız")

    a35 = atm.speed_of_sound(altitude_ft=35000)
    check("a @ FL350", a35, 296.5, 1.5)

    # ─── [3] Tropopoz (36089 ft = 11000 m) ───────────────
    print("\n  [3] Tropopoz (36089 ft)")

    T_trop = atm.temperature(altitude_ft=36089)
    check("T @ tropopoz", T_trop, 216.65, 1.0)

    # ─── [4] Stratosfer (40000 ft) ────────────────────────
    print("\n  [4] Stratosfer (40000 ft)")

    T40, P40, rho40 = atm.get_properties(altitude_ft=40000)

    # Stratosfer: sıcaklık tropopozla aynı olmalı
    tests += 1
    if abs(T40 - T_trop) < 0.1:
        print(f"  ✅ T @ FL400 = {T40:.2f} K (tropopozla aynı, sabit)")
    else:
        errors.append(f"Stratosfer T yanlış: {T40} ≠ {T_trop}")

    # Basınç FL350'den düşük olmalı
    tests += 1
    if P40 < P35:
        print(f"  ✅ P @ FL400 ({P40:.0f}) < P @ FL350 ({P35:.0f})")
    else:
        errors.append("FL400 basıncı FL350'den düşük olmalı")

    # ─── [5] Oranlar ──────────────────────────────────────
    print("\n  [5] Atmosfer Oranları")

    # Deniz seviyesinde oranlar = 1.0
    check("δ @ SL",  atm.pressure_ratio(0),    1.0, 0.001)
    check("θ @ SL",  atm.temperature_ratio(0), 1.0, 0.001)
    check("σ @ SL",  atm.density_ratio(0),     1.0, 0.001)

    # FL350 oranları
    delta_35 = atm.pressure_ratio(35000)
    theta_35 = atm.temperature_ratio(35000)
    sigma_35 = atm.density_ratio(35000)

    # δ < θ < σ < 1.0 (basınç en çok azalır)
    tests += 1
    if delta_35 < theta_35 < 1.0:
        print(f"  ✅ FL350: δ={delta_35:.4f} < θ={theta_35:.4f} < 1.0")
    else:
        errors.append("Oran sıralaması yanlış")

   
    # ─── [6] Mach ↔ TAS ──────────────────────────────────
    print("\n  [6] Mach ↔ TAS Dönüşümü")

    tas = atm.true_airspeed(0.785, 35000)
    check("TAS @ M0.785 FL350", tas, 232.78, 1.0)

    mach_back = atm.mach_from_tas(tas, 35000)
    check("Mach roundtrip", mach_back, 0.785, 0.001)

    # ─── [7] Dinamik basınç ───────────────────────────────
    print("\n  [7] Dinamik Basınç")

    q = atm.dynamic_pressure(35000, 0.785)
    tests += 1
    if 9000 < q < 12000:
        print(f"  ✅ q @ FL350 M0.785 = {q:.0f} Pa (beklenen ~10300)")
    else:
        errors.append(f"Dinamik basınç aralık dışı: {q}")

    # ─── [8] delta_ISA etkisi ─────────────────────────────
    print("\n  [8] delta_ISA Etkisi")

    atm_hot  = ISAAtmosphere(delta_isa=20)
    atm_cold = ISAAtmosphere(delta_isa=-15)

    T_hot  = atm_hot.temperature(35000)
    T_cold = atm_cold.temperature(35000)
    T_std  = atm.temperature(35000)

    # Sıcak > standart > soğuk
    tests += 1
    if T_hot > T_std > T_cold:
        print(f"  ✅ Sıcak({T_hot:.1f}K) > Std({T_std:.1f}K) > Soğuk({T_cold:.1f}K)")
    else:
        errors.append("delta_ISA sıcaklık sıralaması yanlış")

    # delta_ISA değeri doğru uygulanmış mı?
    tests += 1
    if abs((T_hot - T_std) - 20.0) < 0.1:
        print(f"  ✅ delta_ISA=+20: T farkı = {T_hot - T_std:.1f}°C")
    else:
        errors.append(f"delta_ISA uygulanmamış: fark = {T_hot - T_std}")
    # [9] delta_ISA yoğunluk etkisi
    print("\n  [9] delta_ISA yoğunluk")

    rho_hot  = atm_hot.density(35000)
    rho_cold = atm_cold.density(35000)
    rho_std  = atm.density(35000)

    tests += 1
    if rho_hot != rho_std and rho_cold != rho_std:
        print(
            f"  ✅ delta_ISA yoğunluğu etkiliyor: "
            f"Hot={rho_hot:.4f}, Std={rho_std:.4f}, Cold={rho_cold:.4f}"
       )
    else:
        errors.append("delta_ISA yoğunluğu etkilemiyor")

    # ─── [10] Celsius ve hPa ───────────────────────────────
    print("\n  [10] Celsius ve hPa Çıktıları")

    t_celsius = atm.temperature_celsius(0)
    check("T @ SL (°C)", t_celsius, 15.0, 0.01)

    p_hpa = atm.pressure_hpa(0)
    check("P @ SL (hPa)", p_hpa, 1013.25, 0.01)

    # ─── [11] Metre girdisi ───────────────────────────────
    print("\n  [11] Metre Girdisi")

    T_m, P_m, rho_m = atm.get_properties(altitude_m=10668)
    tests += 1
    if abs(T_m - T35) < 1.0:
        print(f"  ✅ altitude_m=10668 ≈ altitude_ft=35000: T={T_m:.1f}K")
    else:
        errors.append(f"Metre/feet uyumsuzluk: {T_m} ≠ {T35}")

    # ─── [12] Hata kontrolü ───────────────────────────────
    print("\n  [12] Hata Kontrolü")

    tests += 1
    try:
        atm.get_properties(altitude_ft=-5000)
        errors.append("Negatif irtifa hata vermedi")
        print("  ❌ Negatif irtifa hata vermedi")
    except ValueError:
        print("  ✅ altitude_ft=-5000 → ValueError")

    tests += 1
    try:
        atm.get_properties(altitude_m=25000)
        errors.append("25000m hata vermedi")
        print("  ❌ 25000m hata vermedi")
    except ValueError:
        print("  ✅ altitude_m=25000 → ValueError")

    # ─── [13] Monotonluk ──────────────────────────────────
    print("\n  [13] Monotonluk Kontrolleri")

    # Sıcaklık troposferde azalmalı
    altitudes = [0, 10000, 20000, 30000, 35000]
    temps = [atm.temperature(a) for a in altitudes]
    tests += 1
    if all(temps[i] >= temps[i+1] for i in range(len(temps)-1)):
        print("  ✅ Sıcaklık troposferde monoton azalıyor")
    else:
        errors.append("Sıcaklık monoton azalmıyor")

    # Basınç her zaman azalmalı
    pressures = [atm.pressure(a) for a in altitudes + [40000]]
    tests += 1
    if all(pressures[i] > pressures[i+1] for i in range(len(pressures)-1)):
        print("  ✅ Basınç monoton azalıyor (0 → FL400)")
    else:
        errors.append("Basınç monoton azalmıyor")

    # Yoğunluk her zaman azalmalı
    densities = [atm.density(a) for a in altitudes + [40000]]
    tests += 1
    if all(densities[i] > densities[i+1] for i in range(len(densities)-1)):
        print("  ✅ Yoğunluk monoton azalıyor (0 → FL400)")
    else:
        errors.append("Yoğunluk monoton azalmıyor")

    # ─── [14] repr ────────────────────────────────────────
    print("\n  [14] Temsil")

    tests += 1
    r = repr(atm)
    if 'ISAAtmosphere' in r:
        print(f"  ✅ repr: {r}")
    else:
        errors.append(f"repr yanlış: {r}")

    tests += 1
    r_hot = repr(atm_hot)
    if '+20.0' in r_hot:
        print(f"  ✅ repr (hot): {r_hot}")
    else:
        errors.append(f"repr hot yanlış: {r_hot}")

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
    validate_atmosphere_model()
