# src/validation/business_validator.py

"""
GreenWing Analytics — İş Mantığı Doğrulayıcı
═══════════════════════════════════════════════

KATMAN 3 / 3: İş Mantığı

Bu dosya SONUÇLARIN iş/operasyonel mantıkla
uyumlu olup olmadığını kontrol eder.

Sorular:
    • Yıllık tasarruf tek rota için makul mü?
    • Tasarruf yüzdesi gerçekçi mi?
    • CO2/pax/km sektör normlarında mı?
    • MTOW aşılıyor mu?
    • Tankering negatif tasarruf üretiyor mu?
    • Step climb sayısı mantıklı mı?

KULLANIM:
─────────
    from src.validation.business_validator import BusinessValidator

    result = BusinessValidator.validate_optimization_result(...)
    result = BusinessValidator.validate_mtow(...)
    result = BusinessValidator.validate_annual_projection(...)
"""

from __future__ import annotations
from config.settings import EI_CO2  # CORSIA: 3.16 kg CO₂/kg yakıt

from src.validation.data_validator import ValidationResult


# ═══════════════════════════════════════════════════════════
# İŞ MANTIĞI SINIRLARI
# ═══════════════════════════════════════════════════════════

# Gerçekçi tasarruf oranları (sektör gözlemine dayalı)
_SAVING_LIMITS = {
    "saving_pct_per_flight"   : (0.0, 15.0),    # Max %15 tek uçuşta
    "annual_saving_usd_single": (0, 5_000_000),  # Max $5M tek rota
    "SAR_nm_per_kg"           : (0.02, 0.25),
    "co2_pax_km_g"            : (30, 250),       # g CO2 / pax / km
    "fuel_per_nm_kg"          : (1.0, 50.0),     # kg/Nm (tüm uçak tipleri)
    "step_climb_count"        : (0, 4),           # Max 4 step climb
    "step_climb_interval_nm"  : (150, None),      # Min 150 Nm aralık
}

# Uçak tipine göre tipik fuel/Nm değerleri
_TYPICAL_FUEL_PER_NM = {
    'B738': (6.0, 11.0),
    'A320': (5.5, 10.5),
    'B77W': (20.0, 35.0),
    'B788': (13.0, 22.0),
    'A350': (13.0, 22.0),
    'DEFAULT': (3.0, 50.0),
}


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class BusinessValidator:
    """
    İş mantığı doğrulama sınıfı.

    Optimizasyon sonuçlarının gerçekçi ve
    uygulanabilir olup olmadığını kontrol eder.

    Kullanım:
        result = BusinessValidator.validate_optimization_result(...)
    """

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: OPTİMİZASYON SONUCU DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_optimization_result(
        saving_kg: float,
        total_fuel_kg: float,
        annual_saving_usd: float,
        aircraft_type: str = 'B738',
    ) -> ValidationResult:
        """
        Optimizasyon tasarruf sonucunu doğrula.

        Args:
            saving_kg        : Uçuş başına yakıt tasarrufu (kg)
            total_fuel_kg    : Toplam yakıt (kg)
            annual_saving_usd: Yıllık tasarruf (USD)
            aircraft_type    : ICAO uçak tipi

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        # Negatif tasarruf
        if saving_kg < 0:
            result.add_error(
                f"Negatif tasarruf: {saving_kg:.0f} kg. "
                f"Optimizasyon hatası veya mantık sorunu."
            )
            return result

        # Tasarruf yüzdesi
        if total_fuel_kg > 0:
            saving_pct = saving_kg / total_fuel_kg * 100
            lo, hi = _SAVING_LIMITS["saving_pct_per_flight"]
            if saving_pct > hi:
                result.add_error(
                    f"Tasarruf oranı çok yüksek: %{saving_pct:.1f}. "
                    f"Maksimum beklenen: %{hi}. "
                    f"Hesaplama hatası veya çift sayım olabilir."
                )
            elif saving_pct > 8:
                result.add_warning(
                    f"Tasarruf oranı yüksek: %{saving_pct:.1f}. "
                    f"Gerçekçilik kontrolü önerilir."
                )
            else:
                result.add_info(f"Tasarruf: {saving_kg:.0f} kg (%{saving_pct:.1f})")
            result.stats["saving_pct"] = round(saving_pct, 2)

        # Yıllık tasarruf
        lo_y, hi_y = _SAVING_LIMITS["annual_saving_usd_single"]
        if annual_saving_usd < lo_y:
            result.add_warning(
                f"Yıllık tasarruf sıfır veya negatif: ${annual_saving_usd:,.0f}."
            )
        elif annual_saving_usd > hi_y:
            result.add_warning(
                f"Yıllık tasarruf çok yüksek: ${annual_saving_usd:,.0f}. "
                f"Tek rota için beklenen maksimum: ${hi_y:,.0f}. "
                f"Gerçekleşme faktörü uygulandı mı?"
            )

        result.stats.update({
            "saving_kg"        : saving_kg,
            "total_fuel_kg"    : total_fuel_kg,
            "annual_saving_usd": annual_saving_usd,
        })

        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: MTOW DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_mtow(
        oew_kg: float,
        payload_kg: float,
        fuel_kg: float,
        extra_fuel_kg: float = 0,
        aircraft_type: str = 'B738',
    ) -> ValidationResult:
        """
        Toplam ağırlığın MTOW'u aşıp aşmadığını kontrol et.

        Args:
            oew_kg       : Operating Empty Weight (kg)
            payload_kg   : Yük ağırlığı (kg)
            fuel_kg      : Yakıt (kg)
            extra_fuel_kg: Ekstra yakıt (tankering vb.)
            aircraft_type: ICAO uçak tipi

        Returns:
            ValidationResult
        """
        from config.assumptions import Assumptions

        result = ValidationResult()

        mtow = Assumptions.aircraft_mtow(aircraft_type)
        max_fuel = Assumptions.aircraft_max_fuel(aircraft_type)

        total_weight = oew_kg + payload_kg + fuel_kg + extra_fuel_kg
        total_fuel   = fuel_kg + extra_fuel_kg

        # MTOW kontrolü
        if total_weight > mtow:
            result.add_error(
                f"MTOW aşıldı! Toplam: {total_weight:,.0f} kg > "
                f"MTOW: {mtow:,.0f} kg. "
                f"Fark: {total_weight - mtow:,.0f} kg. "
                f"Tankering azaltılmalı veya payload düşürülmeli."
            )
        elif total_weight > mtow * 0.98:
            result.add_warning(
                f"MTOW'a çok yakın: {total_weight:,.0f} / {mtow:,.0f} kg "
                f"(%{total_weight/mtow*100:.1f}). "
                f"Pist performansı kısıtlama yaratabilir."
            )
        else:
            result.add_info(
                f"MTOW uygun: {total_weight:,.0f} / {mtow:,.0f} kg "
                f"(%{total_weight/mtow*100:.1f})"
            )

        # Yakıt kapasitesi kontrolü
        if total_fuel > max_fuel:
            result.add_error(
                f"Yakıt kapasitesi aşıldı! "
                f"{total_fuel:,.0f} kg > {max_fuel:,.0f} kg. "
                f"Tank kapasitesi sınırı."
            )

        result.stats.update({
            "total_weight_kg" : total_weight,
            "mtow_kg"         : mtow,
            "mtow_margin_kg"  : mtow - total_weight,
            "mtow_usage_pct"  : round(total_weight / mtow * 100, 1),
            "total_fuel_kg"   : total_fuel,
            "max_fuel_kg"     : max_fuel,
        })

        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: STEP CLIMB DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_step_climb_plan(
        step_plan: list[dict],
        total_distance_nm: float,
    ) -> ValidationResult:
        """
        Step climb planını doğrula.

        Args:
            step_plan         : Step climb listesi
                                [{'distance': 400, 'from': 'FL350',
                                  'to': 'FL370', 'net_saving': 85}, ...]
            total_distance_nm : Toplam rota uzunluğu (Nm)

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        if not step_plan:
            result.add_info("Step climb planı yok.")
            return result

        n_steps = len(step_plan)
        lo_n, hi_n = _SAVING_LIMITS["step_climb_count"]

        # Step sayısı
        if n_steps > hi_n:
            result.add_error(
                f"Step climb sayısı çok fazla: {n_steps}. "
                f"Maksimum: {hi_n}. ATC gerçekçi kabul etmez."
            )
        elif n_steps > 3:
            result.add_warning(
                f"Step climb sayısı: {n_steps}. Yüksek. ATC uygunluğunu doğrulayın."
            )

        # Step aralıkları
        min_interval = _SAVING_LIMITS["step_climb_interval_nm"][0]
        for i in range(1, len(step_plan)):
            interval = step_plan[i]['distance'] - step_plan[i-1]['distance']
            if interval < min_interval:
                result.add_error(
                    f"Step {i+1}: Aralık çok kısa: {interval:.0f} Nm "
                    f"(minimum {min_interval} Nm). "
                    f"Bir önceki step'e çok yakın."
                )

        # Son step ile rota sonu aralığı
        if step_plan:
            last_step_nm = step_plan[-1]['distance']
            remaining_nm = total_distance_nm - last_step_nm
            if remaining_nm < 150:
                result.add_warning(
                    f"Son step climb'dan sonra yalnızca {remaining_nm:.0f} Nm kaldı. "
                    f"Bu kadar kısa mesafede tırmanma maliyeti geri kazanılamayabilir."
                )

        # Her step'te pozitif net tasarruf
        for i, step in enumerate(step_plan):
            net = step.get('net_saving', 0)
            if net <= 0:
                result.add_warning(
                    f"Step {i+1} ({step.get('from')}→{step.get('to')}): "
                    f"Net tasarruf sıfır veya negatif ({net} kg). "
                    f"Bu step gereksiz olabilir."
                )

        result.stats["step_count"] = n_steps

        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: YAKIT VERİMLİLİĞİ DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_fuel_efficiency(
        fuel_kg: float,
        distance_nm: float,
        co2_kg: float,
        aircraft_type: str = 'B738',
        passengers: int = 150,
    ) -> ValidationResult:
        """
        Yakıt verimliliği metriklerini doğrula.

        Args:
            fuel_kg      : Toplam yakıt (kg)
            distance_nm  : Rota uzunluğu (Nm)
            co2_kg       : CO2 emisyonu (kg)
            aircraft_type: ICAO uçak tipi
            passengers   : Yolcu sayısı

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        if distance_nm <= 0:
            result.add_error("distance_nm sıfır veya negatif.")
            return result

        # kg/Nm metriği
        fuel_per_nm = fuel_kg / distance_nm
        lo_t, hi_t  = _TYPICAL_FUEL_PER_NM.get(
            aircraft_type, _TYPICAL_FUEL_PER_NM['DEFAULT']
        )

        lo_g, hi_g = _SAVING_LIMITS["fuel_per_nm_kg"]
        if fuel_per_nm < lo_g or fuel_per_nm > hi_g:
            result.add_error(
                f"fuel/Nm={fuel_per_nm:.2f} kg/Nm fiziksel aralık dışı "
                f"[{lo_g}, {hi_g}]."
            )
        elif fuel_per_nm < lo_t or fuel_per_nm > hi_t:
            result.add_warning(
                f"fuel/Nm={fuel_per_nm:.2f} kg/Nm, "
                f"{aircraft_type} için tipik [{lo_t:.1f}, {hi_t:.1f}] dışında."
            )

        # CO2 tutarlılığı
        expected_co2 = fuel_kg * EI_CO2
        if abs(expected_co2 - co2_kg) / expected_co2 > 0.01:
            result.add_warning(
                f"CO2 tutarsızlık: hesaplanan={expected_co2:.0f} kg, "
                f"verilen={co2_kg:.0f} kg "
                f"(fark %{abs(expected_co2-co2_kg)/expected_co2*100:.1f})."
            )

        # CO2/pax/km
        if passengers > 0:
            distance_km    = distance_nm * 1.852
            co2_pax_km_g   = (co2_kg * 1000) / (passengers * distance_km)
            lo_c, hi_c     = _SAVING_LIMITS["co2_pax_km_g"]

            if co2_pax_km_g < lo_c or co2_pax_km_g > hi_c:
                result.add_warning(
                    f"CO2/pax/km={co2_pax_km_g:.1f} g, "
                    f"beklenen [{lo_c}, {hi_c}] g dışında."
                )

            result.stats["co2_per_pax_per_km_g"] = round(co2_pax_km_g, 1)

        result.stats.update({
            "fuel_per_nm_kg": round(fuel_per_nm, 3),
            "expected_co2_kg": round(expected_co2, 0),
        })

        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: YILLIK PROJEKSİYON DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_annual_projection(
        raw_annual_usd: float,
        realistic_annual_usd: float,
        realization_factor: float,
        daily_flights: int,
    ) -> ValidationResult:
        """
        Yıllık tasarruf projeksiyonunu doğrula.

        Args:
            raw_annual_usd       : Teorik yıllık tasarruf
            realistic_annual_usd : Gerçekçi yıllık tasarruf
            realization_factor   : Gerçekleşme faktörü
            daily_flights        : Günlük sefer sayısı

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        # Gerçekçi ≤ teorik olmalı
        if realistic_annual_usd > raw_annual_usd:
            result.add_error(
                f"Gerçekçi tasarruf ({realistic_annual_usd:,.0f}) > "
                f"Teorik ({raw_annual_usd:,.0f}). "
                f"realization_factor > 1.0 olamaz."
            )

        # Realization factor kontrolü
        if not (0.0 < realization_factor <= 1.0):
            result.add_error(
                f"realization_factor={realization_factor} "
                f"geçersiz aralık (0, 1]."
            )

        # Tutarlılık: raw × RF ≈ realistic
        if raw_annual_usd > 0 and realization_factor > 0:
            expected_realistic = raw_annual_usd * realization_factor
            if abs(expected_realistic - realistic_annual_usd) > 100:
                result.add_warning(
                    f"Projeksiyon tutarsızlık: "
                    f"{raw_annual_usd:,.0f} × {realization_factor} = "
                    f"{expected_realistic:,.0f} ≠ {realistic_annual_usd:,.0f}."
                )

        # Günlük sefer mantıklı mı?
        if daily_flights < 1 or daily_flights > 20:
            result.add_warning(
                f"Günlük sefer sayısı olağandışı: {daily_flights}. "
                f"Gerçek schedule ile karşılaştırın."
            )

        # $5M üstü uyarı
        lo_y, hi_y = _SAVING_LIMITS["annual_saving_usd_single"]
        if realistic_annual_usd > hi_y:
            result.add_warning(
                f"Gerçekçi yıllık tasarruf çok yüksek: "
                f"${realistic_annual_usd:,.0f}. "
                f"Tek rota için beklenen maksimum: ${hi_y:,.0f}."
            )

        result.stats.update({
            "raw_annual_usd"       : raw_annual_usd,
            "realistic_annual_usd" : realistic_annual_usd,
            "realization_factor"   : realization_factor,
            "daily_flights"        : daily_flights,
        })

        return result
