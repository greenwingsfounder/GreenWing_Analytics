# src/models/aircraft_performance.py

"""
GreenWing Analytics — Uçak Aerodinamik Performans Modeli
═══════════════════════════════════════════════════════════

Bu dosya uçağın AERODİNAMİK performansını hesaplar.

YAKIT HESAPLARI BURADA DEĞİL:
─────────────────────────────
    Yakıt hesapları fuel_model.py'a taşındı.
    Bu dosya sadece kaldırma, sürükleme ve verimlilik hesaplar.

    Neden ayrıldı?
        • fuel_model tüm sistemin merkezi
        • emission, optimization, calibration hepsi fuel'e bağlı
        • Tek merkezde olması tutarlılık garanti eder
        • Bu dosya sadece aerodinamik "ne kadar drag var?" sorusunu cevaplar
        • fuel_model "ne kadar yakıt yakar?" sorusunu cevaplar

BU DOSYA NE YAPIYOR:
────────────────────
    1. CL (kaldırma katsayısı) hesabı
    2. CD (sürükleme katsayısı) hesabı — drag polar
    3. L/D (kaldırma/sürükleme oranı)
    4. Drag kuvveti (Newton)
    5. Dinamik basınç (q)
    6. Optimum CL (minimum drag)
    7. Uçak bilgi özeti

FİZİK TEMELİ:
──────────────
    Drag Polar: CD = CD0 + K × CL²

    CD0: Parasitic drag (gövde, kanat profil, antenler)
         Uçak yaşıyla artar, kanat yıkamayla azalır
         Kalibrasyon ile güncellenir (cd0_factor)

    K: İndüktif drag faktörü = 1/(π × e × AR)
       Winglet ile azalır
       Geometrik sabit (değişmez)

    Seviye uçuş: Lift = Weight → CL = W×g / (q×S)
    Drag = q × S × CD
    Level flight: Thrust = Drag

KULLANIM:
─────────
    from src.models.aircraft_performance import AircraftPerformance

    ac = AircraftPerformance('B738')
    cl = ac.lift_coefficient(65000, 35000, 0.785)
    cd = ac.drag_coefficient(cl)
    ld = ac.lift_to_drag_ratio(65000, 35000, 0.785)
    drag = ac.cruise_drag(65000, 35000, 0.785)
    ac.summary()

Kaynak:
───────
    Anderson, J.D. — Introduction to Flight
    Roskam & Lan — Airplane Aerodynamics and Performance
    Boeing 737 FCOM / Performance Engineer's Manual
    BADA Performance Model (Eurocontrol)
"""

from __future__ import annotations

import os
import numpy as np
import yaml

from src.models.atmosphere import ISAAtmosphere


# ═══════════════════════════════════════════════════════════
# SABİTLER
# ═══════════════════════════════════════════════════════════

_GRAVITY = 9.80665   # m/s²


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class AircraftPerformance:
    """
    Uçak aerodinamik performans hesaplayıcı.

    Drag polar, kaldırma katsayısı, sürükleme katsayısı ve
    L/D oranı hesaplar.

    Yakıt hesapları bu sınıfta YOK → fuel_model.py kullan.

    Args:
        aircraft_type: ICAO uçak tipi kodu ('B738', 'A320', 'B77W', ...)
        delta_isa    : ISA sapması (°C). Sıcak gün: +15, soğuk: -10
        cd0_factor   : CD0 kalibrasyon çarpanı. 1.0 = yeni uçak.
                       >1.0 = yaşlı/kirli uçak. Kalibrasyon ile belirlenir.

    Kullanım:
        ac = AircraftPerformance('B738')
        cl = ac.lift_coefficient(65000, 35000, 0.785)
        cd = ac.drag_coefficient(cl)
        drag = ac.cruise_drag(65000, 35000, 0.785)
    """

    def __init__(
        self,
        aircraft_type: str = 'B738',
        delta_isa: float = 0.0,
        cd0_factor: float = 1.0,
    ) -> None:
        self.ac_type    = aircraft_type
        self.delta_isa  = delta_isa
        self.cd0_factor = cd0_factor

        # Atmosfer modeli
        self.atm = ISAAtmosphere(delta_isa)

        # Uçak veritabanından parametreleri yükle
        self.params = self._load_aircraft_params(aircraft_type)

        # Kalibrasyon uygulanmış CD0
        self._effective_cd0 = self.params['CD0'] * cd0_factor

    # ──────────────────────────────────────────────────────
    # BÖLÜM 0: UÇAK PARAMETRELERİ YÜKLEME
    # ──────────────────────────────────────────────────────

    def _load_aircraft_params(self, ac_type: str) -> dict:
        """
        aircraft_database.yaml'dan uçak parametrelerini oku.

        Args:
            ac_type: ICAO uçak tipi kodu

        Returns:
            dict: Uçak parametreleri

        Raises:
            ValueError: Bilinmeyen uçak tipi
            FileNotFoundError: YAML dosyası bulunamadı
        """
        config_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'config', 'aircraft_database.yaml'
        )

        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"aircraft_database.yaml bulunamadı: {config_path}"
            )

        with open(config_path, 'r', encoding='utf-8') as f:
            db = yaml.safe_load(f)

        if ac_type not in db.get('aircraft_types', {}):
            available = sorted(db.get('aircraft_types', {}).keys())
            raise ValueError(
                f"Bilinmeyen uçak tipi: '{ac_type}'. "
                f"Desteklenen: {available}"
            )

        return db['aircraft_types'][ac_type]

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: KALDIRMA KATSAYISI (CL)
    # ──────────────────────────────────────────────────────

    def lift_coefficient(
        self,
        weight_kg: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Seviye uçuşta gerekli kaldırma katsayısını hesapla.

        Seviye uçuşta: Lift = Weight
        Lift = q × S × CL → CL = (W × g) / (q × S)
        q = 0.5 × ρ × V²

        Neden ÖNEMLİ:
            CL yüksekse → CD yüksek → drag yüksek → yakıt yüksek
            CL çok yüksekse → buffet riski (FAR 25.251)
            Optimum CL → minimum drag → minimum yakıt

        Args:
            weight_kg  : Uçak ağırlığı (kg)
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: CL (boyutsuz)

        Tipik değerler:
            B738 cruise: CL = 0.40-0.55
            Hafif uçak: CL düşük
            Ağır uçak: CL yüksek
            Yüksek irtifa: CL yüksek (düşük yoğunluk)
            Alçak irtifa: CL düşük (yüksek yoğunluk)

        Doğrulama:
            CL < 0.3: Çok düşük (çok hızlı veya çok alçak)
            CL 0.3-0.6: Normal cruise
            CL > 0.6: Yüksek (buffet riski)
            CL > 0.7: Tehlikeli
        """
        rho = self.atm.density(altitude_ft)
        V   = self.atm.true_airspeed(mach, altitude_ft)
        S   = self.params['wing_area']

        q  = 0.5 * rho * V ** 2
        CL = (weight_kg * _GRAVITY) / (q * S)

        return float(CL)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: SÜRÜKLEME KATSAYISI (CD)
    # ──────────────────────────────────────────────────────

    def drag_coefficient(self, CL: float) -> float:
        """
        Drag polar'dan toplam sürükleme katsayısını hesapla.

        Formül: CD = CD0 + K × CL²

        Bu denklem bir PARABOL çizer:
            CL düşük → CD ≈ CD0 (parasitic drag dominat)
            CL yüksek → K×CL² büyüyor (indüktif drag dominat)
            Minimum drag → CL_opt = √(CD0/K)
            Minimum noktada L/D maksimum

        CD0 kalibrasyon faktörüyle çarpılmış hali kullanılır.
        cd0_factor > 1.0 → yaşlı/kirli uçak → daha çok drag

        Args:
            CL: Kaldırma katsayısı (boyutsuz)

        Returns:
            float: CD (boyutsuz)

        Tipik değerler:
            B738 cruise: CD = 0.028-0.040
            CD0 = 0.022 (yeni), 0.025 (yaşlı)
            K = 0.045 (winglet ile)

        İlişki:
            CD = CD0 + K × CL²
            Örnek: CL=0.50 → CD = 0.022 + 0.045 × 0.25 = 0.0333
        """
        CD = self._effective_cd0 + self.params['K'] * CL ** 2
        return float(CD)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: KALDIRMA / SÜRÜKLEME ORANI (L/D)
    # ──────────────────────────────────────────────────────

    def lift_to_drag_ratio(
        self,
        weight_kg: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        L/D (Lift-to-Drag) oranı — aerodinamik verimlilik.

        L/D = CL / CD

        Neden ÖNEMLİ:
            Breguet menzil denklemi: R = (V/SFC) × (L/D) × ln(Wi/Wf)
            L/D iki katına çıksa → menzil iki katı
            veya: aynı menzil → yakıt yarıya iner

        Tipik değerler:
            B738: (L/D)max ≈ 16-17
            B777: (L/D)max ≈ 19-20
            A350: (L/D)max ≈ 20-21
            B787: (L/D)max ≈ 20-21

        AMA: Uçak tam olarak (L/D)max'ta uçMAZ.
            Çünkü (L/D)max'taki hız çok düşük.
            Long Range Cruise'da L/D ≈ %98-99 (L/D)max.

        Args:
            weight_kg  : Uçak ağırlığı (kg)
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: L/D (boyutsuz)
        """
        CL = self.lift_coefficient(weight_kg, altitude_ft, mach)
        CD = self.drag_coefficient(CL)

        if CD <= 0:
            return 0.0

        return float(CL / CD)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: DRAG KUVVETİ
    # ──────────────────────────────────────────────────────

    def cruise_drag(
        self,
        weight_kg: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Cruise'da toplam drag kuvveti (Newton).

        Formül: D = q × S × CD

        Seviye uçuşta: Thrust = Drag
        Motor bu kadar thrust üretmek zorunda.
        Motor bu thrust'ı üretirken yakıt yakıyor.

        Args:
            weight_kg  : Uçak ağırlığı (kg)
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: Drag kuvveti (Newton)

        Tipik değerler:
            B738 @ 65000 kg FL350 M0.785:
            D ≈ 33000-36000 N (iki motor toplam thrust'ı)
        """
        rho = self.atm.density(altitude_ft)
        V   = self.atm.true_airspeed(mach, altitude_ft)
        S   = self.params['wing_area']

        q  = 0.5 * rho * V ** 2
        CL = (weight_kg * _GRAVITY) / (q * S)
        CD = self.drag_coefficient(CL)
        D  = q * S * CD

        return float(D)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: DİNAMİK BASINÇ
    # ──────────────────────────────────────────────────────

    def dynamic_pressure(
        self,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """
        Dinamik basınç q (Pascal).

        Formül: q = 0.5 × ρ × V²

        Her aerodinamik kuvvetin temelidir:
            Lift = q × S × CL
            Drag = q × S × CD

        Args:
            altitude_ft: İrtifa (feet)
            mach       : Mach sayısı

        Returns:
            float: Dinamik basınç (Pa)

        Tipik değerler:
            FL350 M0.785: q ≈ 10000-10500 Pa
            SL M0.3:      q ≈ 6500 Pa
        """
        rho = self.atm.density(altitude_ft)
        V   = self.atm.true_airspeed(mach, altitude_ft)
        return float(0.5 * rho * V ** 2)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 6: OPTİMUM DEĞERLER
    # ──────────────────────────────────────────────────────

    def cl_for_max_ld(self) -> float:
        """
        Maksimum L/D noktasındaki CL değeri.

        Formül: CL_opt = √(CD0 / K)

        Bu noktada:
            Parasitic drag = İndüktif drag
            CD_parasitic = CD_induced
            CD0 = K × CL²
            CL = √(CD0/K)

        Returns:
            float: Optimum CL (boyutsuz)

        Tipik:
            B738: CL_opt ≈ √(0.022/0.045) ≈ 0.699
        """
        return float(np.sqrt(self._effective_cd0 / self.params['K']))

    def max_lift_to_drag(self) -> float:
        """
        Teorik maksimum L/D oranı.

        Formül: (L/D)max = 1 / (2 × √(CD0 × K))

        Bu uçağın "aerodinamik DNA"sıdır.
        Tasarım kararlarının sonucu.

        Returns:
            float: (L/D)max (boyutsuz)

        Tipik:
            B738: (L/D)max ≈ 1/(2×√(0.022×0.045)) ≈ 15.9
            B777: (L/D)max ≈ 17.7
            A350: (L/D)max ≈ 20.6
        """
        return float(
            1.0 / (2.0 * np.sqrt(self._effective_cd0 * self.params['K']))
        )

    def optimum_altitude(
        self,
        weight_kg: float,
        mach: float,
    ) -> int:
        """
        Teorik optimum cruise irtifasını bul.

        Brute-force: FL250-FL_max arası her 1000 ft'i dener.
        En yüksek L/D noktasını seçer.

        NOT:
            Bu TEORİK optimum. Gerçek dünya kısıtları yok.
            RVSM, yön kuralı, buffet → altitude_optimizer.py'da.

        Args:
            weight_kg: Uçak ağırlığı (kg)
            mach     : Cruise Mach sayısı

        Returns:
            int: Optimum irtifa (feet), 1000 ft kademelerde
        """
        max_alt  = min(self.params.get('max_altitude', 41000), 43000)
        best_ld  = 0.0
        best_alt = 25000

        for alt in range(25000, max_alt + 1, 1000):
            try:
                CL = self.lift_coefficient(weight_kg, alt, mach)

                # CL çok yüksekse bu irtifa uygun değil
                if CL > 0.65:
                    continue

                ld = self.lift_to_drag_ratio(weight_kg, alt, mach)

                if ld > best_ld:
                    best_ld  = ld
                    best_alt = alt

            except (ValueError, ZeroDivisionError):
                continue

        return best_alt

    # ──────────────────────────────────────────────────────
    # BÖLÜM 7: BİLGİ VE YARDIMCI
    # ──────────────────────────────────────────────────────

    def summary(self) -> None:
        """Uçak bilgi özeti yazdır."""
        p = self.params
        max_ld = self.max_lift_to_drag()
        cl_opt = self.cl_for_max_ld()

        print(f"\n{'='*55}")
        print(f"  {p.get('name', self.ac_type)} ({self.ac_type})")
        print(f"{'='*55}")
        print(f"  Üretici       : {p.get('manufacturer', '?')}")
        print(f"  Motor         : {p.get('engine_type', '?')} × {p.get('num_engines', 2)}")
        print(f"  MTOW          : {p.get('mtow', 0):,} kg")
        print(f"  OEW           : {p.get('oew', 0):,} kg")
        print(f"  Max Fuel      : {p.get('max_fuel', 0):,} kg")
        print(f"  Kanat alanı   : {p.get('wing_area', 0)} m²")
        print(f"  Wingspan      : {p.get('wingspan', 0)} m")
        print(f"  AR            : {p.get('AR', 0):.2f}")
        print(f"  Cruise Mach   : {p.get('cruise_mach', 0)}")
        print(f"  Max Altitude  : {p.get('max_altitude', 0):,} ft")
        print(f"  Range         : {p.get('range_nm', 0):,} Nm")
        print(f"  Pax (typical) : {p.get('passengers_typical', 0)}")
        print(f"  ─── Aerodinamik ───")
        print(f"  CD0 (efektif) : {self._effective_cd0:.4f} (factor: {self.cd0_factor})")
        print(f"  K             : {p.get('K', 0)}")
        print(f"  e (Oswald)    : {p.get('e', 0)}")
        print(f"  (L/D)max      : {max_ld:.2f}")
        print(f"  CL @ (L/D)max : {cl_opt:.4f}")
        print(f"  ISA Δ         : {self.delta_isa:+.1f}°C")
        print(f"{'='*55}\n")

    def get_params(self) -> dict:
        """Uçak parametrelerini dict olarak döndür."""
        return self.params.copy()

    def __repr__(self) -> str:
        return (
            f"AircraftPerformance('{self.ac_type}', "
            f"cd0_factor={self.cd0_factor}, "
            f"delta_isa={self.delta_isa})"
        )


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_aircraft_performance() -> bool:
    """
    Aircraft Performance doğrulama testleri.

    Çalıştırma:
        python -m src.models.aircraft_performance
    """
    print("\n" + "=" * 60)
    print("  AIRCRAFT_PERFORMANCE.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests = 0

    def check(name: str, actual: float, expected: float, tol: float) -> None:
        nonlocal tests
        tests += 1
        diff = abs(actual - expected)
        if diff > tol:
            errors.append(f"{name}: {actual:.6f} ≠ {expected:.6f} (Δ={diff:.6f})")
            print(f"  ❌ {name}: {actual:.6f} (beklenen {expected:.6f})")
        else:
            print(f"  ✅ {name} = {actual:.6f}")

    def check_range(name: str, actual: float, lo: float, hi: float) -> None:
        nonlocal tests
        tests += 1
        if lo <= actual <= hi:
            print(f"  ✅ {name} = {actual:.4f} [{lo}, {hi}]")
        else:
            errors.append(f"{name}: {actual} dışı [{lo}, {hi}]")
            print(f"  ❌ {name} = {actual} [{lo}, {hi}]")

    # ─── [1] Oluşturma ───────────────────────────────────
    print("\n  [1] AircraftPerformance Oluşturma")

    tests += 1
    try:
        ac = AircraftPerformance('B738')
        print(f"  ✅ B738 oluşturuldu: {repr(ac)}")
    except Exception as e:
        errors.append(f"B738 oluşturma: {e}")
        print(f"  ❌ B738: {e}")
        return False

    ac.summary()

    # Geçersiz tip
    tests += 1
    try:
        AircraftPerformance('XXXX')
        errors.append("XXXX hata vermedi")
        print("  ❌ XXXX hata vermedi")
    except ValueError:
        print("  ✅ AircraftPerformance('XXXX') → ValueError")

    # Parametreler yüklendi mi?
    tests += 1
    p = ac.get_params()
    if p.get('name') == 'Boeing 737-800' and p.get('mtow') == 79016:
        print("  ✅ Parametreler doğru yüklendi")
    else:
        errors.append(f"Parametreler yanlış: {p.get('name')}, {p.get('mtow')}")

    # ─── [2] CL hesabı ───────────────────────────────────
    print("\n  [2] Kaldırma Katsayısı (CL)")

    cl = ac.lift_coefficient(65000, 35000, 0.785)
    check_range("CL @ 65000kg FL350 M0.785", cl, 0.35, 0.60)

    # Ağır → yüksek CL
    cl_heavy = ac.lift_coefficient(75000, 35000, 0.785)
    cl_light = ac.lift_coefficient(55000, 35000, 0.785)

    tests += 1
    if cl_heavy > cl_light:
        print(f"  ✅ CL ağır({cl_heavy:.4f}) > hafif({cl_light:.4f})")
    else:
        errors.append("CL ağırlık ilişkisi yanlış")

    # Yüksek irtifa → yüksek CL
    cl_high = ac.lift_coefficient(65000, 39000, 0.785)
    cl_low  = ac.lift_coefficient(65000, 30000, 0.785)

    tests += 1
    if cl_high > cl_low:
        print(f"  ✅ CL yüksek FL({cl_high:.4f}) > alçak FL({cl_low:.4f})")
    else:
        errors.append("CL irtifa ilişkisi yanlış")

    # CL pozitif
    tests += 1
    if cl > 0:
        print(f"  ✅ CL pozitif: {cl:.4f}")
    else:
        errors.append("CL negatif olamaz")

    # ─── [3] CD hesabı ───────────────────────────────────
    print("\n  [3] Sürükleme Katsayısı (CD)")

    cd = ac.drag_coefficient(cl)
    check_range("CD @ CL={:.4f}".format(cl), cd, 0.020, 0.060)

    # CD > CD0 her zaman
    tests += 1
    if cd > ac._effective_cd0:
        print(f"  ✅ CD({cd:.5f}) > CD0({ac._effective_cd0:.5f})")
    else:
        errors.append("CD < CD0 fiziksel olarak imkansız")

    # CD0 doğrudan
    cd_zero_cl = ac.drag_coefficient(0.0)
    check("CD @ CL=0", cd_zero_cl, ac._effective_cd0, 0.0001)

    # Yüksek CL → yüksek CD (karesel)
    cd_low_cl  = ac.drag_coefficient(0.3)
    cd_high_cl = ac.drag_coefficient(0.6)

    tests += 1
    if cd_high_cl > cd_low_cl:
        print(f"  ✅ CD CL=0.6({cd_high_cl:.5f}) > CL=0.3({cd_low_cl:.5f})")
    else:
        errors.append("CD CL ilişkisi yanlış")

    # ─── [4] L/D hesabı ──────────────────────────────────
    print("\n  [4] Kaldırma/Sürükleme Oranı (L/D)")

    ld = ac.lift_to_drag_ratio(65000, 35000, 0.785)
    check_range("L/D @ 65000kg FL350", ld, 13.0, 20.0)

    # L/D = CL/CD kontrolü
    tests += 1
    calculated_ld = cl / cd
    if abs(calculated_ld - ld) < 0.01:
        print(f"  ✅ L/D = CL/CD tutarlı: {ld:.2f} ≈ {calculated_ld:.2f}")
    else:
        errors.append(f"L/D tutarsız: {ld} ≠ {calculated_ld}")

    # Teorik (L/D)max
    ld_max = ac.max_lift_to_drag()
    check_range("(L/D)max teorik", ld_max, 14.0, 22.0)

    # Cruise L/D < (L/D)max
    tests += 1
    if ld <= ld_max * 1.05:  # %5 tolerans
        print(f"  ✅ L/D({ld:.2f}) ≤ (L/D)max({ld_max:.2f})")
    else:
        errors.append(f"L/D > (L/D)max: {ld} > {ld_max}")

    # CL @ (L/D)max
    cl_opt = ac.cl_for_max_ld()
    check_range("CL @ (L/D)max", cl_opt, 0.50, 0.85)

    # ─── [5] Drag kuvveti ─────────────────────────────────
    print("\n  [5] Drag Kuvveti")

    drag = ac.cruise_drag(65000, 35000, 0.785)
    check_range("Drag @ 65000kg FL350", drag, 28000, 42000)

    # Ağır → daha çok drag
    drag_heavy = ac.cruise_drag(75000, 35000, 0.785)
    drag_light = ac.cruise_drag(55000, 35000, 0.785)

    tests += 1
    if drag_heavy > drag_light:
        print(f"  ✅ Drag ağır({drag_heavy:.0f}N) > hafif({drag_light:.0f}N)")
    else:
        errors.append("Drag ağırlık ilişkisi yanlış")

    # Drag pozitif
    tests += 1
    if drag > 0:
        print(f"  ✅ Drag pozitif: {drag:.0f} N")
    else:
        errors.append("Drag negatif olamaz")

    # ─── [6] Dinamik basınç ───────────────────────────────
    print("\n  [6] Dinamik Basınç")

    q = ac.dynamic_pressure(35000, 0.785)
    check_range("q @ FL350 M0.785", q, 9000, 12000)

    # q pozitif
    tests += 1
    if q > 0:
        print(f"  ✅ q pozitif: {q:.0f} Pa")
    else:
        errors.append("q negatif olamaz")

    # ─── [7] Optimum irtifa ───────────────────────────────
    print("\n  [7] Optimum İrtifa")

    opt_heavy = ac.optimum_altitude(75000, 0.785)
    opt_light = ac.optimum_altitude(55000, 0.785)

    check_range("Opt alt @ 75000kg", float(opt_heavy), 30000, 42000)
    check_range("Opt alt @ 55000kg", float(opt_light), 30000, 42000)

    # Hafif → daha yüksek optimum
    tests += 1
    if opt_light >= opt_heavy:
        print(f"  ✅ Hafif({opt_light}ft) ≥ Ağır({opt_heavy}ft)")
    else:
        errors.append(f"Optimum irtifa ilişkisi yanlış: hafif({opt_light}) < ağır({opt_heavy})")

    # ─── [8] Kalibrasyon etkisi ───────────────────────────
    print("\n  [8] CD0 Kalibrasyon Etkisi")

    ac_degraded = AircraftPerformance('B738', cd0_factor=1.05)

    drag_new  = ac.cruise_drag(65000, 35000, 0.785)
    drag_old  = ac_degraded.cruise_drag(65000, 35000, 0.785)

    tests += 1
    if drag_old > drag_new:
        pct = (drag_old - drag_new) / drag_new * 100
        print(f"  ✅ Degraded drag({drag_old:.0f}) > New({drag_new:.0f}) (+%{pct:.1f})")
    else:
        errors.append("CD0 kalibrasyon etkisi yanlış")

    ld_new = ac.lift_to_drag_ratio(65000, 35000, 0.785)
    ld_old = ac_degraded.lift_to_drag_ratio(65000, 35000, 0.785)

    tests += 1
    if ld_old < ld_new:
        print(f"  ✅ Degraded L/D({ld_old:.2f}) < New({ld_new:.2f})")
    else:
        errors.append("L/D kalibrasyon etkisi yanlış")

    # ─── [9] delta_ISA etkisi ─────────────────────────────
    print("\n  [9] delta_ISA Etkisi")

    ac_hot  = AircraftPerformance('B738', delta_isa=20)
    ac_cold = AircraftPerformance('B738', delta_isa=-15)

    drag_hot  = ac_hot.cruise_drag(65000, 35000, 0.785)
    drag_cold = ac_cold.cruise_drag(65000, 35000, 0.785)
    drag_std  = ac.cruise_drag(65000, 35000, 0.785)

    tests += 1
    if drag_hot != drag_std:
        print(f"  ✅ ISA etkisi: hot={drag_hot:.0f}N, std={drag_std:.0f}N, cold={drag_cold:.0f}N")
    else:
        errors.append("delta_ISA drag'ı etkilemiyor")

    # ─── [10] Çoklu uçak tipi ────────────────────────────
    print("\n  [10] Çoklu Uçak Tipi")

    for ac_type in ['A320', 'B77W', 'A350']:
        tests += 1
        try:
            ac_test = AircraftPerformance(ac_type)
            ld_test = ac_test.lift_to_drag_ratio(
                ac_test.params.get('mtow', 79016) * 0.75,
                35000,
                ac_test.params.get('cruise_mach', 0.78)
            )
            if 10 < ld_test < 25:
                print(f"  ✅ {ac_type}: L/D = {ld_test:.2f}")
            else:
                errors.append(f"{ac_type} L/D aralık dışı: {ld_test}")
                print(f"  ❌ {ac_type}: L/D = {ld_test}")
        except Exception as e:
            errors.append(f"{ac_type}: {e}")
            print(f"  ❌ {ac_type}: {e}")

    # Geniş gövde daha düşük CD0 (göreceli)
    tests += 1
    ac_b738 = AircraftPerformance('B738')
    ac_b777 = AircraftPerformance('B77W')
    if ac_b777.params['CD0'] <= ac_b738.params['CD0']:
        print(f"  ✅ B77W CD0({ac_b777.params['CD0']}) ≤ B738 CD0({ac_b738.params['CD0']})")
    else:
        # Bu normal olabilir, sadece bilgi
        print(f"  ℹ B77W CD0({ac_b777.params['CD0']}) > B738 CD0({ac_b738.params['CD0']})")

    # ─── [11] repr ────────────────────────────────────────
    tests += 1
    r = repr(ac)
    if 'AircraftPerformance' in r and 'B738' in r:
        print(f"\n  ✅ repr: {r}")
    else:
        errors.append(f"repr yanlış: {r}")

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
    validate_aircraft_performance()
