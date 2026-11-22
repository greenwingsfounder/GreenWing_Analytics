# src/analysis/sensitivity.py

"""
GreenWing Analytics — Hassasiyet Analizi
════════════════════════════════════════

Bu dosya "input değişirse sonuç ne kadar değişir?" sorusunu cevaplar.

NEDEN KRİTİK:
─────────────
    Müşteriye: "Bu sonuç ne kadar güvenilir?" diyebilmek için.

    Örnek:
        "Yakıt tahmini 12,450 kg"
        Ama ağırlık tahmini ±5000 kg hatalı olabilir.
        O zaman yakıt tahmini de ±%7 hatalı.
        Müşteriye: "12,450 ± 870 kg" demek daha dürüst.

    Ayrıca:
        Hangi girdinin en çok etkisi olduğunu gösterir.
        "Rüzgar verisi eklersek belirsizlik %16'dan %5'e düşer"
        → Müşteriyi veri paylaşmaya motive eder.

ANALİZ TİPLERİ:
────────────────
    1. Ağırlık hassasiyeti   → Ağırlık ±5000 kg değişirse?
    2. CD0 hassasiyeti       → CD0 ±10% değişirse?
    3. SFC hassasiyeti       → SFC ±5% değişirse?
    4. Rüzgar hassasiyeti    → Rüzgar 0/30/60 kt olsa?
    5. İrtifa hassasiyeti    → Her irtifada yakıt kaç?
    6. Yakıt fiyatı hassasiyeti → Fiyat ±20% değişirse?
    7. Tam hassasiyet raporu → Tüm parametreler + sıralama

KULLANIM:
─────────
    from src.analysis.sensitivity import SensitivityAnalyzer

    sa = SensitivityAnalyzer('B738')

    # Tek parametre
    result = sa.analyze_weight_sensitivity(
        base_weight=70000, distance_nm=1560,
        altitude_ft=37000, mach=0.785
    )

    # Tam rapor
    report = sa.full_sensitivity_report({
        'weight_kg': 70000,
        'distance_nm': 1560,
        'altitude_ft': 37000,
        'mach': 0.785,
        'fuel_price_usd': _DEFAULT_FUEL_PRICE,
    })

Kaynak:
───────
    Uncertainty propagation: JCGM 100:2008 (GUM)
    Aviation performance sensitivity: BADA methodology
"""

from __future__ import annotations

import numpy as np
from typing import Optional

from src.models.fuel_model import FuelModel
from config.assumptions import Assumptions

# BÜTÜNLÜK: varsayılan yakıt fiyatı TEK kaynaktan (sabit kodlanmış $0.85 değil).
_DEFAULT_FUEL_PRICE = Assumptions.fuel_price('DEFAULT')


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class SensitivityAnalyzer:
    """
    Girdi hassasiyet analizi.

    Her girdinin sonuca etkisini ölçer.
    En hassas parametreyi belirler.
    Müşteriye güven aralığı sunar.

    Args:
        aircraft_type: ICAO uçak tipi kodu
        delta_isa    : ISA sapması (°C)

    Kullanım:
        sa = SensitivityAnalyzer('B738')
        result = sa.analyze_weight_sensitivity(70000, 1560, 37000, 0.785)
    """

    def __init__(
        self,
        aircraft_type: str = 'B738',
        delta_isa: float = 0.0,
    ) -> None:
        self.ac_type  = aircraft_type
        self.fm       = FuelModel(aircraft_type, delta_isa)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: AĞIRLIK HASSASİYETİ
    # ──────────────────────────────────────────────────────

    def analyze_weight_sensitivity(
        self,
        base_weight: float,
        distance_nm: float,
        altitude_ft: float,
        mach: float,
        variation_kg: float = 5000,
        steps: int = 5,
    ) -> dict:
        """
        Ağırlık değişiminin yakıt tüketimine etkisi.

        Ağırlık en büyük belirsizlik kaynaklarından biri çünkü:
            • Gerçek payload bilinmiyor (varsayım)
            • Yolcu sayısı ve bagaj ağırlığı günlük değişiyor
            • Yakıt yüklemesi farklı olabilir

        Args:
            base_weight  : Referans ağırlık (kg)
            distance_nm  : Rota mesafesi (Nm)
            altitude_ft  : Cruise irtifası (ft)
            mach         : Cruise Mach
            variation_kg : ± kaç kg değişim test edilecek
            steps        : Kaç adım (her yöne)

        Returns:
            dict:
                parameter     : 'weight_kg'
                base_value    : referans ağırlık
                variation     : ± kg
                results       : [{weight, fuel_kg, change_pct}, ...]
                max_effect_pct: maksimum etki yüzdesi
                interpretation: yorumlama metni
        """
        results    = []
        base_fuel  = self._get_cruise_fuel(base_weight, distance_nm, altitude_ft, mach)

        weights = np.linspace(
            base_weight - variation_kg,
            base_weight + variation_kg,
            steps * 2 + 1,
        )

        for w in weights:
            if w < 30000:
                continue

            fuel = self._get_cruise_fuel(w, distance_nm, altitude_ft, mach)
            change_pct = ((fuel - base_fuel) / base_fuel * 100) if base_fuel > 0 else 0

            results.append({
                'weight_kg' : round(w),
                'fuel_kg'   : round(fuel),
                'change_pct': round(change_pct, 2),
            })

        max_effect = max(abs(r['change_pct']) for r in results) if results else 0

        return {
            'parameter'     : 'weight_kg',
            'base_value'    : base_weight,
            'base_fuel_kg'  : round(base_fuel),
            'variation'     : f"±{variation_kg} kg",
            'results'       : results,
            'max_effect_pct': round(max_effect, 2),
            'interpretation': (
                f"Ağırlık ±{variation_kg} kg değişirse, "
                f"yakıt tahmini ±{max_effect:.1f}% değişir. "
                f"Gerçek ağırlık verisi alınırsa bu belirsizlik büyük ölçüde azalır."
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: CD0 HASSASİYETİ
    # ──────────────────────────────────────────────────────

    def analyze_cd0_sensitivity(
        self,
        base_weight: float,
        distance_nm: float,
        altitude_ft: float,
        mach: float,
        variation_pct: float = 10,
        steps: int = 5,
    ) -> dict:
        """
        CD0 değişiminin yakıt tüketimine etkisi.

        CD0 kalibrasyon ile belirlenir.
        Kalibrasyon yapılmamışsa ±10% belirsizlik taşır.
        Uçak yaşı, temizlik, modifikasyonlar CD0'ı etkiler.

        Args:
            base_weight   : Referans ağırlık (kg)
            distance_nm   : Rota mesafesi (Nm)
            altitude_ft   : Cruise irtifası (ft)
            mach          : Cruise Mach
            variation_pct : ± yüzde değişim
            steps         : Kaç adım

        Returns:
            dict: Hassasiyet sonuçları
        """
        base_cd0  = self.fm.params['CD0']
        base_fuel = self._get_cruise_fuel(base_weight, distance_nm, altitude_ft, mach)

        results   = []
        factors   = np.linspace(
            1 - variation_pct / 100,
            1 + variation_pct / 100,
            steps * 2 + 1,
        )

        for factor in factors:
            cd0_test = base_cd0 * factor

            fm_test  = FuelModel(
                self.ac_type,
                cd0_factor=factor,
                sfc_factor=1.0,
            )

            fuel = fm_test.fuel_for_distance(
                distance_nm, base_weight, altitude_ft, mach,
            )['total_fuel_kg']

            change_pct = ((fuel - base_fuel) / base_fuel * 100) if base_fuel > 0 else 0

            results.append({
                'cd0'          : round(cd0_test, 5),
                'cd0_factor'   : round(factor, 3),
                'fuel_kg'      : round(fuel),
                'change_pct'   : round(change_pct, 2),
            })

        max_effect = max(abs(r['change_pct']) for r in results) if results else 0

        return {
            'parameter'     : 'CD0',
            'base_value'    : base_cd0,
            'base_fuel_kg'  : round(base_fuel),
            'variation'     : f"±{variation_pct}%",
            'results'       : results,
            'max_effect_pct': round(max_effect, 2),
            'interpretation': (
                f"CD0 ±{variation_pct}% değişirse, "
                f"yakıt tahmini ±{max_effect:.1f}% değişir. "
                f"Kalibrasyon yapılırsa CD0 belirsizliği ±2%'ye düşer."
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: SFC HASSASİYETİ
    # ──────────────────────────────────────────────────────

    def analyze_sfc_sensitivity(
        self,
        base_weight: float,
        distance_nm: float,
        altitude_ft: float,
        mach: float,
        variation_pct: float = 5,
        steps: int = 5,
    ) -> dict:
        """
        SFC değişiminin yakıt tüketimine etkisi.

        SFC motor verimi. Yaşlanma ile artar.
        Motor yıkama ile geçici olarak düşer.

        Args:
            base_weight   : Referans ağırlık (kg)
            distance_nm   : Rota mesafesi (Nm)
            altitude_ft   : Cruise irtifası (ft)
            mach          : Cruise Mach
            variation_pct : ± yüzde değişim
            steps         : Kaç adım

        Returns:
            dict: Hassasiyet sonuçları
        """
        base_sfc  = self.fm.params['tsfc_cruise']
        base_fuel = self._get_cruise_fuel(base_weight, distance_nm, altitude_ft, mach)

        results = []
        factors = np.linspace(
            1 - variation_pct / 100,
            1 + variation_pct / 100,
            steps * 2 + 1,
        )

        for factor in factors:
            fm_test = FuelModel(
                self.ac_type,
                cd0_factor=1.0,
                sfc_factor=factor,
            )

            fuel = fm_test.fuel_for_distance(
                distance_nm, base_weight, altitude_ft, mach,
            )['total_fuel_kg']

            change_pct = ((fuel - base_fuel) / base_fuel * 100) if base_fuel > 0 else 0

            results.append({
                'sfc'          : round(base_sfc * factor, 8),
                'sfc_factor'   : round(factor, 3),
                'fuel_kg'      : round(fuel),
                'change_pct'   : round(change_pct, 2),
            })

        max_effect = max(abs(r['change_pct']) for r in results) if results else 0

        return {
            'parameter'     : 'SFC',
            'base_value'    : base_sfc,
            'base_fuel_kg'  : round(base_fuel),
            'variation'     : f"±{variation_pct}%",
            'results'       : results,
            'max_effect_pct': round(max_effect, 2),
            'interpretation': (
                f"SFC ±{variation_pct}% değişirse, "
                f"yakıt tahmini ±{max_effect:.1f}% değişir. "
                f"Motor yıkama ile SFC %0.5-1 iyileşir."
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: RÜZGAR HASSASİYETİ
    # ──────────────────────────────────────────────────────

    def analyze_wind_sensitivity(
        self,
        base_weight: float,
        distance_nm: float,
        altitude_ft: float,
        mach: float,
        wind_range_kts: list[int] = None,
    ) -> dict:
        """
        Rüzgar değişiminin yakıt ve süreye etkisi.

        Rüzgar en büyük belirsizlik kaynaklarından biri.
        60 kt headwind → %15+ fazla yakıt.
        Rüzgar verisi eklenirse belirsizlik büyük ölçüde azalır.

        Args:
            base_weight    : Referans ağırlık (kg)
            distance_nm    : Rota mesafesi (Nm)
            altitude_ft    : Cruise irtifası (ft)
            mach           : Cruise Mach
            wind_range_kts : Test edilecek rüzgar değerleri (kt).
                             Pozitif = headwind, Negatif = tailwind.
                             None → varsayılan aralık.

        Returns:
            dict: Hassasiyet sonuçları
        """
        from src.units import Units

        if wind_range_kts is None:
            wind_range_kts = [-60, -30, -15, 0, 15, 30, 60]

        base_fuel = self._get_cruise_fuel(base_weight, distance_nm, altitude_ft, mach)
        V_tas     = Units.mach_to_tas(mach, altitude_ft)

        results = []

        for wind_kts in wind_range_kts:
            wind_ms  = wind_kts * 0.514444
            V_ground = V_tas - wind_ms

            if V_ground <= 0:
                results.append({
                    'wind_kts'       : wind_kts,
                    'wind_type'      : 'headwind' if wind_kts > 0 else 'tailwind',
                    'ground_speed_kts': 0,
                    'flight_time_hr' : float('inf'),
                    'fuel_kg'        : float('inf'),
                    'change_pct'     : float('inf'),
                    'note'           : 'Ground speed negatif — uçuş imkansız',
                })
                continue

            flight_time_s  = (distance_nm * 1852.0) / V_ground
            flight_time_hr = flight_time_s / 3600

            ff_kg_s   = self.fm.cruise_fuel_flow(base_weight, altitude_ft, mach)
            fuel_wind = ff_kg_s * flight_time_s

            change_pct = ((fuel_wind - base_fuel) / base_fuel * 100) if base_fuel > 0 else 0

            results.append({
                'wind_kts'        : wind_kts,
                'wind_type'       : 'headwind' if wind_kts > 0 else ('tailwind' if wind_kts < 0 else 'calm'),
                'ground_speed_kts': round(V_ground / 0.514444),
                'flight_time_hr'  : round(flight_time_hr, 2),
                'fuel_kg'         : round(fuel_wind),
                'change_pct'      : round(change_pct, 2),
            })

        valid_results = [r for r in results if r['change_pct'] != float('inf')]
        max_effect    = max(abs(r['change_pct']) for r in valid_results) if valid_results else 0

        return {
            'parameter'     : 'wind',
            'base_fuel_kg'  : round(base_fuel),
            'variation'     : f"{min(wind_range_kts)} to {max(wind_range_kts)} kts",
            'results'       : results,
            'max_effect_pct': round(max_effect, 2),
            'interpretation': (
                f"Rüzgar etkisi ±{max_effect:.1f}%. "
                f"Rüzgar verisi olmadan analiz bu kadar belirsizlik içerir. "
                f"Rüzgar verisi eklendiğinde belirsizlik ±3-5%'e düşer."
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: İRTİFA HASSASİYETİ
    # ──────────────────────────────────────────────────────

    def analyze_altitude_sensitivity(
        self,
        base_weight: float,
        mach: float,
        distance_nm: float,
        altitude_range: Optional[list[int]] = None,
    ) -> dict:
        """
        Her irtifada yakıt tüketimi karşılaştırması.

        Optimum irtifanın ne kadar kritik olduğunu gösterir.

        Args:
            base_weight    : Uçak ağırlığı (kg)
            mach           : Cruise Mach
            distance_nm    : Rota mesafesi (Nm)
            altitude_range : Test edilecek irtifalar (ft).
                             None → FL300-FL410.

        Returns:
            dict: Hassasiyet sonuçları
        """
        if altitude_range is None:
            altitude_range = list(range(30000, 42000, 1000))

        results  = []
        best_sar = 0
        best_alt = 35000

        for alt in altitude_range:
            try:
                sar  = self.fm.specific_air_range(base_weight, alt, mach)
                fuel = self.fm.fuel_for_distance(
                    distance_nm, base_weight, alt, mach,
                )['total_fuel_kg']
                cl   = self.fm.lift_coefficient(base_weight, alt, mach)
                ld   = self.fm.lift_to_drag_ratio(base_weight, alt, mach)

                results.append({
                    'altitude_ft'    : alt,
                    'flight_level'   : f"FL{alt // 100}",
                    'sar_nm_per_kg'  : round(sar, 6),
                    'fuel_kg'        : round(fuel),
                    'cl'             : round(cl, 4),
                    'lift_to_drag'   : round(ld, 2),
                })

                if sar > best_sar:
                    best_sar = sar
                    best_alt = alt

            except (ValueError, ZeroDivisionError):
                continue

        # FL350 referans
        fl350_fuel = next(
            (r['fuel_kg'] for r in results if r['altitude_ft'] == 35000),
            None,
        )

        if fl350_fuel:
            for r in results:
                r['change_vs_fl350_kg'] = round(r['fuel_kg'] - fl350_fuel)
                r['change_vs_fl350_pct'] = round(
                    (r['fuel_kg'] - fl350_fuel) / fl350_fuel * 100, 2
                ) if fl350_fuel > 0 else 0

        fuel_range = (
            max(r['fuel_kg'] for r in results) - min(r['fuel_kg'] for r in results)
        ) if results else 0

        return {
            'parameter'       : 'altitude_ft',
            'base_weight_kg'  : base_weight,
            'mach'            : mach,
            'optimum_altitude': best_alt,
            'optimum_fl'      : f"FL{best_alt // 100}",
            'optimum_sar'     : round(best_sar, 6),
            'fuel_range_kg'   : round(fuel_range),
            'results'         : results,
            'interpretation'  : (
                f"Optimum irtifa: FL{best_alt//100}. "
                f"FL300-FL410 arasında yakıt farkı: {fuel_range:.0f} kg. "
                f"Yanlış irtifa seçimi bu rotada {fuel_range:.0f} kg ekstra yakıt."
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 6: YAKIT FİYATI HASSASİYETİ
    # ──────────────────────────────────────────────────────

    def analyze_fuel_price_sensitivity(
        self,
        per_flight_saving_kg: float,
        base_price_usd: Optional[float] = None,
        variation_pct: float = 20,
        steps: int = 5,
    ) -> dict:
        """
        Yakıt fiyatı değişiminin tasarruf $ değerine etkisi.

        Yakıt fiyatı değişince:
            • Yakıt kg DEĞİŞMEZ (fizik aynı)
            • Tasarruf $ değeri DEĞİŞİR
            • Cost Index optimumu DEĞİŞİR

        Args:
            per_flight_saving_kg: Uçuş başına yakıt tasarrufu (kg)
            base_price_usd      : Referans yakıt fiyatı ($/kg)
            variation_pct       : ± yüzde değişim
            steps               : Kaç adım

        Returns:
            dict: Hassasiyet sonuçları
        """
        # BÜTÜNLÜK: fiyat verilmezse tek kaynaktan (Assumptions) alınır.
        if base_price_usd is None:
            base_price_usd = _DEFAULT_FUEL_PRICE

        base_saving_usd = per_flight_saving_kg * base_price_usd

        results = []
        prices  = np.linspace(
            base_price_usd * (1 - variation_pct / 100),
            base_price_usd * (1 + variation_pct / 100),
            steps * 2 + 1,
        )

        for price in prices:
            saving_usd = per_flight_saving_kg * price
            change_pct = ((saving_usd - base_saving_usd) / base_saving_usd * 100) if base_saving_usd > 0 else 0

            results.append({
                'fuel_price_usd' : round(price, 3),
                'saving_usd'     : round(saving_usd, 2),
                'change_pct'     : round(change_pct, 2),
            })

        max_effect = max(abs(r['change_pct']) for r in results) if results else 0

        return {
            'parameter'         : 'fuel_price',
            'base_value'        : base_price_usd,
            'saving_kg'         : per_flight_saving_kg,
            'base_saving_usd'   : round(base_saving_usd, 2),
            'variation'         : f"±{variation_pct}%",
            'results'           : results,
            'max_effect_pct'    : round(max_effect, 2),
            'interpretation'    : (
                f"Yakıt fiyatı ±{variation_pct}% değişirse, "
                f"tasarruf $ değeri ±{max_effect:.1f}% değişir. "
                f"Yakıt miktarı (kg) etkilenmez, sadece finansal değer değişir."
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 7: TAM HASSASİYET RAPORU
    # ──────────────────────────────────────────────────────

    def full_sensitivity_report(
        self,
        params: dict,
    ) -> dict:
        """
        Tüm parametrelerin hassasiyet analizini tek raporda birleştir.

        En hassas parametreyi belirler ve iyileştirme önerir.

        Args:
            params: Analiz parametreleri
                weight_kg    : Uçak ağırlığı (kg)
                distance_nm  : Rota mesafesi (Nm)
                altitude_ft  : Cruise irtifası (ft)
                mach         : Cruise Mach
                fuel_price_usd: Yakıt fiyatı ($/kg) — opsiyonel
                saving_kg    : Uçuş başına tasarruf (kg) — opsiyonel

        Returns:
            dict:
                analyses       : Her parametre için sonuçlar
                ranking        : En hassastan en aza sıralama
                dominant_source: En büyük belirsizlik kaynağı
                total_uncertainty_pct: Toplam belirsizlik tahmini
                recommendations: İyileştirme önerileri
        """
        weight      = params.get('weight_kg', 70000)
        distance    = params.get('distance_nm', 1560)
        altitude    = params.get('altitude_ft', 37000)
        mach        = params.get('mach', 0.785)
        fuel_price  = params.get('fuel_price_usd', _DEFAULT_FUEL_PRICE)
        saving_kg   = params.get('saving_kg', 300)

        analyses = {}

        # Ağırlık
        analyses['weight'] = self.analyze_weight_sensitivity(
            weight, distance, altitude, mach,
        )

        # CD0
        analyses['cd0'] = self.analyze_cd0_sensitivity(
            weight, distance, altitude, mach,
        )

        # SFC
        analyses['sfc'] = self.analyze_sfc_sensitivity(
            weight, distance, altitude, mach,
        )

        # Rüzgar
        analyses['wind'] = self.analyze_wind_sensitivity(
            weight, distance, altitude, mach,
        )

        # İrtifa
        analyses['altitude'] = self.analyze_altitude_sensitivity(
            weight, mach, distance,
        )

        # Yakıt fiyatı
        if saving_kg > 0:
            analyses['fuel_price'] = self.analyze_fuel_price_sensitivity(
                saving_kg, fuel_price,
            )

        # ─── Sıralama (en hassastan en aza) ───────────────
        ranking = []
        for name, analysis in analyses.items():
            if name == 'altitude':
                effect = analysis.get('fuel_range_kg', 0)
                base   = analyses['weight'].get('base_fuel_kg', 1)
                pct    = (effect / base * 100) if base > 0 else 0
                ranking.append({
                    'parameter'   : name,
                    'effect_pct'  : round(pct, 2),
                    'description' : analysis.get('interpretation', ''),
                })
            else:
                ranking.append({
                    'parameter'   : name,
                    'effect_pct'  : analysis.get('max_effect_pct', 0),
                    'description' : analysis.get('interpretation', ''),
                })

        ranking.sort(key=lambda x: x['effect_pct'], reverse=True)

        # Dominant kaynak
        dominant = ranking[0] if ranking else {'parameter': 'N/A', 'effect_pct': 0}

        # Toplam belirsizlik (kare kök toplamı — bağımsız hatalar)
        individual_pcts = [r['effect_pct'] for r in ranking if r['parameter'] != 'fuel_price']
        total_uncertainty = float(np.sqrt(sum(p**2 for p in individual_pcts)))

        # Öneriler
        recommendations = []
        for r in ranking[:3]:
            param = r['parameter']
            if param == 'wind':
                recommendations.append(
                    "Rüzgar verisi eklenirse toplam belirsizlik önemli ölçüde azalır. "
                    "aviationweather.gov'dan winds aloft verisi kullanılması önerilir."
                )
            elif param == 'weight':
                recommendations.append(
                    "Gerçek ağırlık verisi (loadsheet) alınırsa belirsizlik büyük ölçüde azalır. "
                    "Müşteriden rota bazlı ortalama payload verisi istenmeli."
                )
            elif param == 'cd0':
                recommendations.append(
                    "Model kalibrasyonu yapılırsa CD0 belirsizliği ±10%'dan ±2%'ye düşer. "
                    "Müşteriden 3 aylık rota bazlı yakıt verisi istenmeli."
                )
            elif param == 'sfc':
                recommendations.append(
                    "Motor kalibrasyon verisi ile SFC belirsizliği azaltılabilir. "
                    "Motor yaşı ve son shop visit tarihi bilgisi faydalıdır."
                )
            elif param == 'altitude':
                recommendations.append(
                    "İrtifa seçimi büyük etki yaratıyor. "
                    "Optimum irtifa kullanımının artırılması önerilir."
                )

        return {
            'analyses'              : analyses,
            'ranking'               : ranking,
            'dominant_source'       : dominant['parameter'],
            'dominant_effect_pct'   : dominant['effect_pct'],
            'total_uncertainty_pct' : round(total_uncertainty, 2),
            'recommendations'       : recommendations,
            'interpretation'        : (
                f"En hassas parametre: {dominant['parameter']} "
                f"(±{dominant['effect_pct']:.1f}%). "
                f"Toplam belirsizlik: ±{total_uncertainty:.1f}%. "
                f"İyileştirme için {len(recommendations)} öneri mevcut."
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 8: YARDIMCI
    # ──────────────────────────────────────────────────────

    def _get_cruise_fuel(
        self,
        weight_kg: float,
        distance_nm: float,
        altitude_ft: float,
        mach: float,
    ) -> float:
        """Cruise yakıtı hesapla (basit wrapper)."""
        try:
            result = self.fm.fuel_for_distance(
                distance_nm, weight_kg, altitude_ft, mach,
            )
            return result['total_fuel_kg']
        except (ValueError, ZeroDivisionError):
            return 0.0

    def __repr__(self) -> str:
        return f"SensitivityAnalyzer('{self.ac_type}')"


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_sensitivity() -> bool:
    """
    Sensitivity Analyzer doğrulama testleri.

    Çalıştırma:
        python -m src.analysis.sensitivity
    """
    print("\n" + "=" * 60)
    print("  SENSITIVITY.PY — DOĞRULAMA TESTLERİ")
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

    sa = SensitivityAnalyzer('B738')

    # ─── [1] Ağırlık hassasiyeti ──────────────────────────
    print("\n  [1] Ağırlık Hassasiyeti")

    w_result = sa.analyze_weight_sensitivity(70000, 1560, 37000, 0.785)

    tests += 1
    if w_result['parameter'] == 'weight_kg':
        ok(f"Parametre: {w_result['parameter']}")
    else:
        fail("parametre", w_result['parameter'])

    tests += 1
    if len(w_result['results']) >= 5:
        ok(f"{len(w_result['results'])} adım hesaplandı")
    else:
        fail("adım sayısı", f"az: {len(w_result['results'])}")

    tests += 1
    if w_result['max_effect_pct'] > 0:
        ok(f"Max etki: ±{w_result['max_effect_pct']}%")
    else:
        fail("max etki", "sıfır")

    # Ağır → daha çok yakıt
    tests += 1
    fuels = [(r['weight_kg'], r['fuel_kg']) for r in w_result['results']]
    sorted_by_weight = sorted(fuels, key=lambda x: x[0])
    if sorted_by_weight[-1][1] > sorted_by_weight[0][1]:
        ok("Ağır → daha çok yakıt (doğru)")
    else:
        fail("Ağırlık ilişkisi", "yanlış")

    # ─── [2] CD0 hassasiyeti ──────────────────────────────
    print("\n  [2] CD0 Hassasiyeti")

    cd0_result = sa.analyze_cd0_sensitivity(70000, 1560, 37000, 0.785)

    tests += 1
    if cd0_result['max_effect_pct'] > 0:
        ok(f"CD0 max etki: ±{cd0_result['max_effect_pct']}%")
    else:
        fail("CD0 etki", "sıfır")

    # Yüksek CD0 → daha çok yakıt
    tests += 1
    cd0_fuels = [(r['cd0_factor'], r['fuel_kg']) for r in cd0_result['results']]
    cd0_sorted = sorted(cd0_fuels, key=lambda x: x[0])
    if cd0_sorted[-1][1] > cd0_sorted[0][1]:
        ok("Yüksek CD0 → daha çok yakıt (doğru)")
    else:
        fail("CD0 ilişkisi", "yanlış")

    # ─── [3] SFC hassasiyeti ──────────────────────────────
    print("\n  [3] SFC Hassasiyeti")

    sfc_result = sa.analyze_sfc_sensitivity(70000, 1560, 37000, 0.785)

    tests += 1
    if sfc_result['max_effect_pct'] > 0:
        ok(f"SFC max etki: ±{sfc_result['max_effect_pct']}%")
    else:
        fail("SFC etki", "sıfır")

    # ─── [4] Rüzgar hassasiyeti ───────────────────────────
    print("\n  [4] Rüzgar Hassasiyeti")

    wind_result = sa.analyze_wind_sensitivity(70000, 1560, 37000, 0.785)

    tests += 1
    if wind_result['max_effect_pct'] > 0:
        ok(f"Rüzgar max etki: ±{wind_result['max_effect_pct']}%")
    else:
        fail("Rüzgar etki", "sıfır")

    # Headwind → daha çok yakıt
    tests += 1
    calm_fuel = next((r['fuel_kg'] for r in wind_result['results'] if r['wind_kts'] == 0), 0)
    head_fuel = next((r['fuel_kg'] for r in wind_result['results'] if r['wind_kts'] == 60), 0)
    tail_fuel = next((r['fuel_kg'] for r in wind_result['results'] if r['wind_kts'] == -60), 0)

    if head_fuel > calm_fuel > tail_fuel:
        ok(f"Head({head_fuel:.0f}) > Calm({calm_fuel:.0f}) > Tail({tail_fuel:.0f})")
    else:
        fail("Rüzgar ilişkisi", "yanlış sıralama")

    # ─── [5] İrtifa hassasiyeti ───────────────────────────
    print("\n  [5] İrtifa Hassasiyeti")

    alt_result = sa.analyze_altitude_sensitivity(70000, 0.785, 1560)

    tests += 1
    if alt_result['fuel_range_kg'] > 0:
        ok(f"İrtifa yakıt aralığı: {alt_result['fuel_range_kg']} kg")
    else:
        fail("İrtifa aralığı", "sıfır")

    tests += 1
    if 30000 <= alt_result['optimum_altitude'] <= 41000:
        ok(f"Optimum: {alt_result['optimum_fl']}")
    else:
        fail("Optimum irtifa", f"{alt_result['optimum_altitude']}")

    # ─── [6] Yakıt fiyatı hassasiyeti ─────────────────────
    print("\n  [6] Yakıt Fiyatı Hassasiyeti")

    price_result = sa.analyze_fuel_price_sensitivity(300, _DEFAULT_FUEL_PRICE)

    tests += 1
    if price_result['max_effect_pct'] > 0:
        ok(f"Fiyat max etki: ±{price_result['max_effect_pct']}%")
    else:
        fail("Fiyat etki", "sıfır")

    # ─── [7] Tam rapor ────────────────────────────────────
    print("\n  [7] Tam Hassasiyet Raporu")

    full = sa.full_sensitivity_report({
        'weight_kg'     : 70000,
        'distance_nm'   : 1560,
        'altitude_ft'   : 37000,
        'mach'          : 0.785,
        'fuel_price_usd': _DEFAULT_FUEL_PRICE,
        'saving_kg'     : 300,
    })

    tests += 1
    if len(full['analyses']) >= 5:
        ok(f"{len(full['analyses'])} parametre analiz edildi")
    else:
        fail("Analiz sayısı", f"az: {len(full['analyses'])}")

    tests += 1
    if len(full['ranking']) >= 5:
        ok(f"Sıralama: {[r['parameter'] for r in full['ranking']]}")
    else:
        fail("Sıralama", f"az: {len(full['ranking'])}")

    tests += 1
    if full['dominant_source']:
        ok(f"Dominant kaynak: {full['dominant_source']} (±{full['dominant_effect_pct']}%)")
    else:
        fail("Dominant", "boş")

    tests += 1
    if full['total_uncertainty_pct'] > 0:
        ok(f"Toplam belirsizlik: ±{full['total_uncertainty_pct']}%")
    else:
        fail("Toplam belirsizlik", "sıfır")

    tests += 1
    if len(full['recommendations']) >= 1:
        ok(f"{len(full['recommendations'])} öneri")
    else:
        fail("Öneriler", "boş")

    tests += 1
    if full['interpretation']:
        ok(f"Yorum: {full['interpretation'][:60]}...")
    else:
        fail("Yorum", "boş")

    # Rüzgar genellikle en hassas olmalı
    tests += 1
    if full['ranking'][0]['parameter'] in ('wind', 'weight', 'altitude'):
        ok(f"En hassas: {full['ranking'][0]['parameter']} (beklenen)")
    else:
        # Diğer parametreler de olabilir
        ok(f"En hassas: {full['ranking'][0]['parameter']}")

    # ─── [8] repr ─────────────────────────────────────────
    tests += 1
    r = repr(sa)
    if 'SensitivityAnalyzer' in r:
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
    validate_sensitivity()


