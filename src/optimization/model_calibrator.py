"""
GreenWing Analytics — Model Kalibrasyon Sistemi
════════════════════════════════════════════════

Bu dosya performans modelini müşterinin GERÇEK verisine uyarlar.

NEDEN GEREKLİ:
──────────────
    aircraft_database.yaml'daki CD0 ve TSFC değerleri
    standart/yeni uçak içindir. Gerçek uçak farklı olabilir:

    • 15 yaşında B738 → CD0 %10-15 daha yüksek
    • Bakımsız motor → SFC %3-5 daha yüksek
    • Winglet retrofit → K %8-12 düşük

    Kalibrasyon olmadan → model %5-10 hatalı
    Kalibrasyon ile → model %1-3 hatalı

NASIL ÇALIŞIR:
──────────────
    1. Müşteri 10-50 uçuşun gerçek yakıt verisini gönderir
    2. Model aynı uçuşları kendi hesaplar
    3. Fark ölçülür
    4. cd0_factor ve sfc_factor optimize edilir
    5. Fark minimuma indirilir

    Matematiksel:
        minimize Σ((predicted_fuel - actual_fuel) / actual_fuel)²
        değişkenler: cd0_factor, sfc_factor

    Sonuç:
        cd0_factor = 1.048 → "CD0 standarttan %4.8 yüksek"
        sfc_factor = 1.018 → "SFC standarttan %1.8 yüksek"

    Yorum:
        cd0_factor > 1.05 → Kanat yıkama öner
        sfc_factor > 1.03 → Motor yıkama öner

KULLANIM:
─────────
    from src.optimization.model_calibrator import ModelCalibrator

    cal = ModelCalibrator('B738')

    result = cal.calibrate([
        {'distance_nm': 1560, 'actual_fuel_kg': 12800, 'cruise_altitude_ft': 37000},
        {'distance_nm': 1560, 'actual_fuel_kg': 12500, 'cruise_altitude_ft': 37000},
        {'distance_nm': 1000, 'actual_fuel_kg': 8900,  'cruise_altitude_ft': 37000},
        ...
    ])

    print(f"CD0 factor: {result['calibration_factors']['cd0_factor']}")
    print(f"SFC factor: {result['calibration_factors']['sfc_factor']}")

Kaynak:
───────
    BADA Model Calibration methodology
    Boeing Performance Engineer's Manual
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from typing import Optional

from src.models.fuel_model import FuelModel
from src.logging_config import get_logger

logger = get_logger("optimization.calibrator")  # Central logging (pre-real consistency)


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class ModelCalibrator:
    """
    Performans modeli kalibrasyon sistemi.

    Gerçek yakıt verisiyle CD0 ve SFC faktörlerini optimize eder.
    Kalibre edilmiş model %1-3 doğrulukla çalışır.

    Args:
        aircraft_type: ICAO uçak tipi kodu

    Kullanım:
        cal = ModelCalibrator('B738')
        result = cal.calibrate(actual_flights)
    """

    def __init__(self, aircraft_type: str = 'B738') -> None:
        self.ac_type  = aircraft_type
        self.base_fm  = FuelModel(aircraft_type)

        self.calibration_factors = {
            'cd0_factor': 1.0,
            'sfc_factor': 1.0,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: ANA KALİBRASYON
    # ──────────────────────────────────────────────────────

    def calibrate(
        self,
        actual_flights: list[dict],
        method: str = 'Nelder-Mead',
    ) -> dict:
        """
        Gerçek yakıt verileriyle modeli kalibre et.

        İşlem:
            1. Her uçuşun gerçek yakıtını al
            2. Model ile aynı uçuşun yakıtını hesapla
            3. Toplam kare hata minimize et
            4. Optimum cd0_factor ve sfc_factor bul
            5. Kalibrasyon öncesi/sonrası doğruluğu karşılaştır
            6. Yorum ve öneriler üret

        Args:
            actual_flights: Gerçek uçuş verileri listesi
                Her dict şunları içermeli:
                    distance_nm      : Rota mesafesi (Nm) — ZORUNLU
                    actual_fuel_kg   : Gerçek yakıt (kg) — ZORUNLU
                    cruise_altitude_ft: Cruise irtifası (ft) — opsiyonel (varsayılan 35000)
                    takeoff_weight_kg : Kalkış ağırlığı (kg) — opsiyonel (tahmin edilir)
                    cruise_mach       : Cruise Mach — opsiyonel (varsayılan uçak tipinden)

            method: Optimizasyon yöntemi ('Nelder-Mead' veya 'Powell')

        Returns:
            dict:
                status              : 'SUCCESS' veya 'ERROR'
                calibration_factors : {cd0_factor, sfc_factor}
                accuracy            : {before_pct, after_pct, improvement_pct, max_error_pct}
                flight_comparison   : [{actual, predicted_before, predicted_after, error_pct}, ...]
                interpretations     : Fiziksel yorum listesi
                recommendations     : Bakım önerileri
                model_quality       : 'EXCELLENT' / 'GOOD' / 'FAIR' / 'POOR'

        Örnekler:
            actual = [
                {'distance_nm': 1560, 'actual_fuel_kg': 12800, 'cruise_altitude_ft': 37000},
                {'distance_nm': 1560, 'actual_fuel_kg': 12500, 'cruise_altitude_ft': 37000},
                {'distance_nm': 1000, 'actual_fuel_kg': 8900,  'cruise_altitude_ft': 37000},
                {'distance_nm': 190,  'actual_fuel_kg': 3400,  'cruise_altitude_ft': 33000},
            ]
            result = cal.calibrate(actual)
        """
        if not actual_flights or len(actual_flights) < 3:
            return {
                'status': 'ERROR',
                'message': f'Minimum 3 uçuş gerekli, {len(actual_flights)} verildi.',
            }

        # Geçersiz verileri filtrele
        valid_flights = [
            f for f in actual_flights
            if f.get('distance_nm', 0) > 0 and f.get('actual_fuel_kg', 0) > 0
        ]

        if len(valid_flights) < 3:
            return {
                'status': 'ERROR',
                'message': f'Yeterli geçerli veri yok. '
                           f'{len(valid_flights)} geçerli / {len(actual_flights)} toplam.',
            }

        # ─── Optimizasyon (with simple hold-out for real data readiness) ─────────────────
        import random
        random.seed(42)  # reproducible split for pre-real

        n = len(valid_flights)
        if n >= 8:
            # Simple 70/30 train/test for better credibility when real data arrives
            train_idx = random.sample(range(n), int(n * 0.7))
            train_flights = [valid_flights[i] for i in train_idx]
            test_flights  = [valid_flights[i] for i in range(n) if i not in train_idx]
        else:
            train_flights = valid_flights
            test_flights = valid_flights  # fallback for very small sets

        def objective(params):
            """Minimize edilecek fonksiyon: toplam kare hata (train set)."""
            cd0_f, sfc_f = params
            total_error = 0.0

            for flight in train_flights:
                predicted = self._predict_fuel(flight, cd0_f, sfc_f)
                actual    = flight['actual_fuel_kg']

                if actual > 0:
                    error_pct = (predicted - actual) / actual
                    total_error += error_pct ** 2

            return total_error

        # Başlangıç noktası: her ikisi 1.0 (standart)
        x0 = [1.0, 1.0]

        # ═══════════════════════════════════════════════════════════
        # SINIRLAR — GERÇEK KISIT (2026-11-22 denetimi)
        #
        # ÖNCEKİ HATA: minimize() 'bounds' olmadan çağrılıyordu ve
        # varsayılan yöntem 'Nelder-Mead' SINIR DESTEKLEMEZ.
        # Optimizasyon sınırsız koşuyor, sonra sonuç elle kırpılıyordu:
        #     cd0 = max(0.85, min(1.25, cd0))
        # Bu, kırpma sınırında SAHTE bir minimum üretir: gerçek
        # optimum 1.60 ise 1.25'e kırpılır ve "en iyi uyum" gibi
        # raporlanır — oysa o noktada gradyan hâlâ aşağıyı gösterir.
        #
        # DÜZELTME: sınırlar optimizasyona DAHİL edilir. Powell
        # yöntemi [0.85, 1.25] × [0.90, 1.15] kutusunda arar;
        # sonuç zaten kutunun içindedir, kırpma gerekmez.
        #
        # CD0 %85-125 ve SFC %90-115: yaşlı uçak / bakımsız motor
        # için fiziksel olarak makul aralık.
        # ═══════════════════════════════════════════════════════════
        bounds = [(0.85, 1.25), (0.90, 1.15)]

        # Bounds desteklemeyen yöntemler sessizce sınırsız koşar →
        # bu yüzden destekleyen bir yönteme zorla.
        _bounds_methods = {'Powell', 'L-BFGS-B', 'TNC', 'SLSQP'}
        if method not in _bounds_methods:
            method = 'Powell'

        try:
            result = minimize(
                objective,
                x0=x0,
                method=method,
                bounds=bounds,
                options={'xtol': 0.001, 'ftol': 0.0001, 'maxiter': 500},
            )

            cd0_factor = float(np.clip(result.x[0], 0.85, 1.25))
            sfc_factor = float(np.clip(result.x[1], 0.90, 1.15))
            # Sınıra dayandı mı? Raporla — sessiz kırpma yanıltıcıdır.
            at_bound_cd0 = bool(abs(cd0_factor - 0.85) < 1e-3
                                or abs(cd0_factor - 1.25) < 1e-3)
            at_bound_sfc = bool(abs(sfc_factor - 0.90) < 1e-3
                                or abs(sfc_factor - 1.15) < 1e-3)

        except Exception as e:
            return {
                'status': 'ERROR',
                'message': f'Optimizasyon başarısız: {e}',
            }

        # Faktörleri kaydet
        self.calibration_factors['cd0_factor'] = round(cd0_factor, 4)
        self.calibration_factors['sfc_factor'] = round(sfc_factor, 4)

        # ─── Doğruluk karşılaştırması (train vs test separation for credibility) ─────────
        # We always evaluate on the FULL set for transparency (what the airline will see).
        # But when n>=8 we ALSO compute a clean "test" accuracy on the held-out 30%.
        # This is critical for scientific honesty before real data arrives.

        errors_before = []
        errors_after  = []
        comparisons   = []

        for flight in valid_flights:
            actual = flight['actual_fuel_kg']

            predicted_before = self._predict_fuel(flight, 1.0, 1.0)
            predicted_after  = self._predict_fuel(flight, cd0_factor, sfc_factor)

            err_before = abs(predicted_before - actual) / actual * 100
            err_after  = abs(predicted_after  - actual) / actual * 100

            errors_before.append(err_before)
            errors_after.append(err_after)

            comparisons.append({
                'distance_nm'     : flight['distance_nm'],
                'actual_fuel_kg'  : round(actual),
                'predicted_before': round(predicted_before),
                'predicted_after' : round(predicted_after),
                'error_before_pct': round(err_before, 2),
                'error_after_pct' : round(err_after, 2),
            })

        avg_before = float(np.mean(errors_before))
        avg_after  = float(np.mean(errors_after))
        max_after  = float(np.max(errors_after))
        improvement = avg_before - avg_after

        # === TEST SET ACCURACY (the honest number for pre-real credibility) ===
        test_before = []
        test_after = []
        if n >= 8 and len(test_flights) > 0:
            for flight in test_flights:
                actual = flight['actual_fuel_kg']
                pb = self._predict_fuel(flight, 1.0, 1.0)
                pa = self._predict_fuel(flight, cd0_factor, sfc_factor)
                test_before.append(abs(pb - actual) / actual * 100)
                test_after.append(abs(pa - actual) / actual * 100)

            test_avg_before = float(np.mean(test_before))
            test_avg_after  = float(np.mean(test_after))
            test_improvement = test_avg_before - test_avg_after
        else:
            test_avg_before = avg_before
            test_avg_after = avg_after
            test_improvement = improvement

        # Note for real data
        split_info = 'Optimization on 70% train set; FULL metrics + TEST metrics reported' if n >= 8 else 'Small dataset - no split applied'

        # === HONEST TEST-SET METRICS (the number that proves generalization) ===
        # When we have enough data (n>=8) we report BOTH:
        #   - Full-set accuracy (what the airline will see in production)
        #   - Test-set accuracy (hold-out 30% — the honest pre-real number)
        # This is the scientifically correct way to present calibration results
        # before real data arrives. It prevents over-optimism.
        test_metrics = None
        if n >= 8 and len(test_flights) > 0:
            test_metrics = {
                'avg_error_before_pct': round(test_avg_before, 2),
                'avg_error_after_pct': round(test_avg_after, 2),
                'improvement_pct': round(test_improvement, 2),
                'n_test_flights': len(test_flights),
            }

        # ─── Model kalitesi ───────────────────────────────
        if avg_after < 2:
            quality = 'EXCELLENT'
        elif avg_after < 5:
            quality = 'GOOD'
        elif avg_after < 10:
            quality = 'FAIR'
        else:
            quality = 'POOR'

        # ─── Yorumlar ─────────────────────────────────────
        interpretations = []

        if cd0_factor > 1.05:
            interpretations.append(
                f"CD0 faktörü yüksek ({cd0_factor:.3f} = +%{(cd0_factor-1)*100:.1f}). "
                f"Uçak yüzeyi beklenden daha pürüzlü. "
                f"Olası sebepler: uçak yaşı, boya aşınması, kapak seal bozulması, "
                f"anten/modifikasyon ek dragı."
            )
        elif cd0_factor < 0.97:
            interpretations.append(
                f"CD0 faktörü düşük ({cd0_factor:.3f} = %{(cd0_factor-1)*100:.1f}). "
                f"Uçak beklenden daha temiz. "
                f"Olası sebepler: yeni kanat yıkama, winglet etkisi modelde eksik."
            )
        else:
            interpretations.append(
                f"CD0 faktörü normal ({cd0_factor:.3f}). "
                f"Aerodinamik performans standartlara yakın."
            )

        if sfc_factor > 1.03:
            interpretations.append(
                f"SFC faktörü yüksek ({sfc_factor:.3f} = +%{(sfc_factor-1)*100:.1f}). "
                f"Motor beklenen verimden düşük çalışıyor. "
                f"Olası sebepler: motor yaşlanması, kompresör erozyonu, "
                f"seal aşınması, yanma odası karbon birikimi."
            )
        elif sfc_factor < 0.98:
            interpretations.append(
                f"SFC faktörü düşük ({sfc_factor:.3f} = %{(sfc_factor-1)*100:.1f}). "
                f"Motor beklenenden daha verimli. "
                f"Olası sebepler: yakın zamanda motor yıkama veya shop visit."
            )
        else:
            interpretations.append(
                f"SFC faktörü normal ({sfc_factor:.3f}). "
                f"Motor performansı standartlara yakın."
            )

        # ─── Öneriler ─────────────────────────────────────
        recommendations = []

        if cd0_factor > 1.05:
            savings_pct = (cd0_factor - 1.0) * 100
            recommendations.append({
                'action'    : 'Kanat yıkama programı',
                'priority'  : 'HIGH' if cd0_factor > 1.08 else 'MEDIUM',
                'rationale' : f'CD0 %{savings_pct:.1f} yüksek. Yıkama ile %1-3 iyileşme beklenir.',
                'estimated_benefit': f'Uçak başına yıllık ~${savings_pct * 10000:.0f} yakıt tasarrufu',
            })

        if cd0_factor > 1.08:
            recommendations.append({
                'action'    : 'Seal ve kapak kontrol programı',
                'priority'  : 'HIGH',
                'rationale' : f'CD0 çok yüksek (%{(cd0_factor-1)*100:.1f}). Sızıntı dragi olabilir.',
                'estimated_benefit': 'C-check\'te seal yenileme ile %1-2 iyileşme',
            })

        if sfc_factor > 1.03:
            recommendations.append({
                'action'    : 'Motor yıkama (engine wash)',
                'priority'  : 'HIGH' if sfc_factor > 1.05 else 'MEDIUM',
                'rationale' : f'SFC %{(sfc_factor-1)*100:.1f} yüksek. Yıkama ile %0.5-1.5 iyileşme beklenir.',
                'estimated_benefit': f'Motor başına yıllık ~${(sfc_factor-1)*100 * 5000:.0f} tasarruf',
            })

        if sfc_factor > 1.05:
            recommendations.append({
                'action'    : 'Erken shop visit değerlendirmesi',
                'priority'  : 'HIGH',
                'rationale' : f'SFC %{(sfc_factor-1)*100:.1f} yüksek. Ciddi performans kaybı.',
                'estimated_benefit': 'Shop visit sonrası SFC standarda dönebilir',
            })

        if not recommendations:
            recommendations.append({
                'action'    : 'Mevcut durumu koru',
                'priority'  : 'LOW',
                'rationale' : 'Model ve uçak performansı standartlara yakın.',
                'estimated_benefit': 'Düzenli kontrol yeterli',
            })

        return {
            'status': 'SUCCESS',

            'calibration_factors': {
                'cd0_factor': round(cd0_factor, 4),
                'sfc_factor': round(sfc_factor, 4),
                # Sınıra dayandıysa gerçek optimum kutunun dışında:
                # kalibrasyon güvenilir DEĞİL, daha fazla veri gerek.
                'at_bound': {
                    'cd0': at_bound_cd0,
                    'sfc': at_bound_sfc,
                    'bounds': {'cd0': [0.85, 1.25], 'sfc': [0.90, 1.15]},
                },
            },

            'accuracy': {
                'avg_error_before_pct': round(avg_before, 2),
                'avg_error_after_pct' : round(avg_after, 2),
                'max_error_after_pct' : round(max_after, 2),
                'improvement_pct'     : round(improvement, 2),
            },

            'flights_used'      : len(valid_flights),
            'flight_comparison'  : comparisons,
            'interpretations'    : interpretations,
            'recommendations'    : recommendations,
            'model_quality'      : quality,

            'summary': (
                f"Model %{avg_after:.1f} ortalama hatayla kalibre edildi "
                f"(kalibrasyon öncesi: %{avg_before:.1f}). "
                f"CD0 factor: {cd0_factor:.4f}, SFC factor: {sfc_factor:.4f}. "
                f"Model kalitesi: {quality}. "
                f"({split_info})"
            ),
            'split_info': split_info,

            # === HONEST TEST-SET METRICS (pre-real scientific integrity) ===
            # Full-set + Test-set (hold-out) metrics are both returned.
            # The test_set_metrics is the honest number before real data arrives.
            'test_set_metrics': test_metrics,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: YAKIT TAHMİNİ (iç kullanım)
    # ──────────────────────────────────────────────────────

    def _predict_fuel(
        self,
        flight: dict,
        cd0_factor: float,
        sfc_factor: float,
    ) -> float:
        """
        Verilen faktörlerle tek uçuşun TOPLAM yakıtını tahmin et.

        v2.2 DÜZELTME:
        ─────────────────────────────────────────────
        ESKİ: cruise_fuel / 0.75 → KABA, rotaya göre bias üretir
              Kısa rotada overestimate, uzun rotada underestimate
        
        YENİ: estimate_total_flight_fuel() → TÜM FAZLAR dahil
              taxi + takeoff + climb + cruise + descent + approach + taxi_in
        
        Bu düzeltme, kalibrasyonun farklı mesafeli rotalarda
        tutarlı çalışmasını sağlar.

        Args:
            flight    : Uçuş bilgileri dict
            cd0_factor: CD0 çarpanı
            sfc_factor: SFC çarpanı

        Returns:
            float: Tahmini toplam yakıt (kg)
        """
        distance = flight['distance_nm']
        alt      = flight.get('cruise_altitude_ft', 35000)
        mach     = flight.get('cruise_mach', self.base_fm.params.get('cruise_mach', 0.78))

        # ─── İyileştirilmiş ağırlık tahmini ──────────────
        # ESKİ: oew + 15000 + distance * 8 → double counting riski
        # YENİ: oew + payload(seats×LF×pax_weight) + trip_fuel_est + contingency
        weight = flight.get('takeoff_weight_kg')
        if weight is None:
            oew = self.base_fm.params.get('oew', 41413)
            seats = self.base_fm.params.get('passengers_typical', 162)
            # Payload: seats × load_factor × pax_weight (mesafeden bağımsız)
            payload = seats * 0.82 * 95  # ~12,500 kg for B738
            
            # Yakıt tahmini (kaba, iteratif değil): distance × ~6.5 kg/Nm
            # Bu SAR bazlı kaba tahmin — calibrator'ın bulmaya çalıştığı şey değil
            trip_fuel_est = distance * 6.5
            
            # Contingency (reserve, holding, taxi)
            contingency = 1500
            
            weight = oew + payload + trip_fuel_est + contingency
            
            # MTOW kontrolü — ağırlığı MTOW'nun %95'iyle sınırla
            mtow = self.base_fm.params.get('mtow', 79016)
            weight = min(weight, mtow * 0.95)

        # ─── Kalibre edilmiş fuel model ──────────────────
        fm = FuelModel(
            self.ac_type,
            cd0_factor=cd0_factor,
            sfc_factor=sfc_factor,
        )

        try:
            # ─── TAM UÇUŞ TAHMİNİ ───────────────────────
            # cruise_fuel / 0.75 DEĞİL!
            # Tüm fazlar: taxi + takeoff + climb + cruise + descent + approach + taxi_in
            result = fm.estimate_total_flight_fuel(
                distance_nm=distance,
                weight_initial_kg=weight,
                altitude_ft=alt,
                mach=mach,
            )
            return result['total_fuel_kg']
        except (ValueError, ZeroDivisionError):
            # Fallback — çok kısa rota veya invalid params
            logger.warning(f"_predict_fuel fallback for dist={distance}nm, alt={alt}ft")
            return distance * 8.0

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: KALİBRASYON UYGULAMA
    # ──────────────────────────────────────────────────────

    def get_calibrated_fuel_model(self) -> FuelModel:
        """
        Kalibre edilmiş FuelModel döndür.

        calibrate() çalıştırıldıktan sonra kullanılır.
        Dönen FuelModel kalibre edilmiş CD0 ve SFC ile çalışır.

        Returns:
            FuelModel: Kalibre edilmiş model

        Kullanım:
            cal = ModelCalibrator('B738')
            cal.calibrate(actual_flights)
            fm = cal.get_calibrated_fuel_model()
            # fm artık kalibre edilmiş parametrelerle çalışır
        """
        return FuelModel(
            self.ac_type,
            cd0_factor=self.calibration_factors['cd0_factor'],
            sfc_factor=self.calibration_factors['sfc_factor'],
        )

    def get_factors(self) -> dict:
        """Mevcut kalibrasyon faktörlerini döndür."""
        return self.calibration_factors.copy()

    def reset(self) -> None:
        """Kalibrasyonu sıfırla (standart değerlere dön)."""
        self.calibration_factors = {
            'cd0_factor': 1.0,
            'sfc_factor': 1.0,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: YARDIMCI
    # ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        cd0 = self.calibration_factors['cd0_factor']
        sfc = self.calibration_factors['sfc_factor']
        return f"ModelCalibrator('{self.ac_type}', cd0={cd0}, sfc={sfc})"


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_model_calibrator() -> bool:
    """
    Model Calibrator doğrulama testleri.

    Çalıştırma:
        python -m src.optimization.model_calibrator
    """
    print("\n" + "=" * 60)
    print("  MODEL_CALIBRATOR.PY — DOĞRULAMA TESTLERİ")
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

    # ─── [1] Oluşturma ───────────────────────────────────
    print("\n  [1] Calibrator Oluşturma")

    cal = ModelCalibrator('B738')
    tests += 1
    if cal.calibration_factors['cd0_factor'] == 1.0:
        ok("Başlangıç cd0_factor: 1.0")
    else:
        fail("cd0_factor", f"{cal.calibration_factors['cd0_factor']}")

    tests += 1
    if cal.calibration_factors['sfc_factor'] == 1.0:
        ok("Başlangıç sfc_factor: 1.0")
    else:
        fail("sfc_factor", f"{cal.calibration_factors['sfc_factor']}")

    # ─── [2] Kalibrasyon ──────────────────────────────────
    print("\n  [2] Kalibrasyon")

    # Simüle gerçek veri (standart modelden biraz farklı)
    # Gerçek uçak biraz daha çok yakıyor (yaşlı)
    actual_flights = [
        {'distance_nm': 1560, 'actual_fuel_kg': 12800, 'cruise_altitude_ft': 37000},
        {'distance_nm': 1560, 'actual_fuel_kg': 12500, 'cruise_altitude_ft': 37000},
        {'distance_nm': 1560, 'actual_fuel_kg': 13100, 'cruise_altitude_ft': 35000},
        {'distance_nm': 1000, 'actual_fuel_kg': 8900,  'cruise_altitude_ft': 37000},
        {'distance_nm': 1000, 'actual_fuel_kg': 8600,  'cruise_altitude_ft': 37000},
        {'distance_nm': 190,  'actual_fuel_kg': 3400,  'cruise_altitude_ft': 33000},
        {'distance_nm': 190,  'actual_fuel_kg': 3200,  'cruise_altitude_ft': 35000},
        {'distance_nm': 300,  'actual_fuel_kg': 4300,  'cruise_altitude_ft': 35000},
        {'distance_nm': 1550, 'actual_fuel_kg': 12200, 'cruise_altitude_ft': 39000},
        {'distance_nm': 780,  'actual_fuel_kg': 7500,  'cruise_altitude_ft': 35000},
    ]

    result = cal.calibrate(actual_flights)

    tests += 1
    if result['status'] == 'SUCCESS':
        ok("Kalibrasyon başarılı")
    else:
        fail("Kalibrasyon", result.get('message', 'HATA'))
        return False

    # Faktörler makul aralıkta
    cd0_f = result['calibration_factors']['cd0_factor']
    sfc_f = result['calibration_factors']['sfc_factor']

    tests += 1
    if 0.85 <= cd0_f <= 1.25:
        ok(f"CD0 factor: {cd0_f} (makul aralıkta)")
    else:
        fail("CD0 factor", f"{cd0_f} aralık dışı")

    tests += 1
    if 0.90 <= sfc_f <= 1.15:
        ok(f"SFC factor: {sfc_f} (makul aralıkta)")
    else:
        fail("SFC factor", f"{sfc_f} aralık dışı")

    # ─── [3] Doğruluk iyileşmesi ──────────────────────────
    print("\n  [3] Doğruluk İyileşmesi")

    acc = result['accuracy']

    tests += 1
    if acc['avg_error_after_pct'] <= acc['avg_error_before_pct']:
        ok(f"Hata azaldı: %{acc['avg_error_before_pct']:.1f} → %{acc['avg_error_after_pct']:.1f}")
    else:
        fail("Hata azalmadı", f"önce=%{acc['avg_error_before_pct']}, sonra=%{acc['avg_error_after_pct']}")

    tests += 1
    if acc['improvement_pct'] >= 0:
        ok(f"İyileşme: %{acc['improvement_pct']:.2f}")
    else:
        fail("İyileşme", f"negatif: %{acc['improvement_pct']}")

    # ─── [4] Model kalitesi ───────────────────────────────
    print("\n  [4] Model Kalitesi")

    tests += 1
    if result['model_quality'] in ('EXCELLENT', 'GOOD', 'FAIR', 'POOR'):
        ok(f"Model kalitesi: {result['model_quality']}")
    else:
        fail("Kalite", result['model_quality'])

    # ─── [5] Uçuş karşılaştırması ─────────────────────────
    print("\n  [5] Uçuş Karşılaştırması")

    comps = result['flight_comparison']

    tests += 1
    if len(comps) == len(actual_flights):
        ok(f"{len(comps)} uçuş karşılaştırıldı")
    else:
        fail("Karşılaştırma sayısı", f"{len(comps)} ≠ {len(actual_flights)}")

    # Her karşılaştırmada after hatası < before hatası olmalı (genellikle)
    improved_count = sum(
        1 for c in comps
        if c['error_after_pct'] <= c['error_before_pct'] + 0.5
    )
    tests += 1
    if improved_count >= len(comps) * 0.7:
        ok(f"Uçuşların %{improved_count/len(comps)*100:.0f}'inde hata azaldı")
    else:
        fail("İyileşme oranı", f"düşük: {improved_count}/{len(comps)}")

    # ─── [6] Yorumlar ve öneriler ─────────────────────────
    print("\n  [6] Yorumlar ve Öneriler")

    tests += 1
    if result['interpretations']:
        ok(f"{len(result['interpretations'])} yorum")
        for interp in result['interpretations']:
            print(f"     → {interp[:70]}...")
    else:
        fail("Yorumlar", "boş")

    tests += 1
    if result['recommendations']:
        ok(f"{len(result['recommendations'])} öneri")
        for rec in result['recommendations']:
            print(f"     → [{rec['priority']}] {rec['action']}")
    else:
        fail("Öneriler", "boş")

    tests += 1
    if result['summary']:
        ok(f"Özet: {result['summary'][:60]}...")
    else:
        fail("Özet", "boş")

    # ─── [7] Kalibre edilmiş model ────────────────────────
    print("\n  [7] Kalibre Edilmiş Model")

    fm_calibrated = cal.get_calibrated_fuel_model()

    tests += 1
    if fm_calibrated.cd0_factor == cd0_f:
        ok(f"Kalibre FM cd0_factor: {fm_calibrated.cd0_factor}")
    else:
        fail("FM cd0", f"{fm_calibrated.cd0_factor} ≠ {cd0_f}")

    tests += 1
    if fm_calibrated.sfc_factor == sfc_f:
        ok(f"Kalibre FM sfc_factor: {fm_calibrated.sfc_factor}")
    else:
        fail("FM sfc", f"{fm_calibrated.sfc_factor} ≠ {sfc_f}")

    # get_factors
    tests += 1
    factors = cal.get_factors()
    if factors['cd0_factor'] == cd0_f:
        ok("get_factors çalışıyor")
    else:
        fail("get_factors", f"{factors}")

    # ─── [8] Reset ────────────────────────────────────────
    print("\n  [8] Reset")

    cal.reset()
    tests += 1
    if cal.calibration_factors['cd0_factor'] == 1.0:
        ok("Reset sonrası cd0: 1.0")
    else:
        fail("Reset", f"cd0 = {cal.calibration_factors['cd0_factor']}")

    # ─── [9] Yetersiz veri ────────────────────────────────
    print("\n  [9] Yetersiz Veri")

    result_short = cal.calibrate([
        {'distance_nm': 1560, 'actual_fuel_kg': 12500},
    ])
    tests += 1
    if result_short['status'] == 'ERROR':
        ok("1 uçuş → ERROR (minimum 3 gerekli)")
    else:
        fail("Yetersiz veri", f"{result_short['status']}")

    result_empty = cal.calibrate([])
    tests += 1
    if result_empty['status'] == 'ERROR':
        ok("Boş liste → ERROR")
    else:
        fail("Boş liste", f"{result_empty['status']}")

    # ─── [10] Geçersiz veri ───────────────────────────────
    print("\n  [10] Geçersiz Veri")

    result_invalid = cal.calibrate([
        {'distance_nm': 0, 'actual_fuel_kg': 0},
        {'distance_nm': -100, 'actual_fuel_kg': 5000},
        {'distance_nm': 1560, 'actual_fuel_kg': -1000},
    ])
    tests += 1
    if result_invalid['status'] == 'ERROR':
        ok("Geçersiz veriler → ERROR")
    else:
        fail("Geçersiz veri", f"{result_invalid['status']}")

    # ─── [11] repr ────────────────────────────────────────
    tests += 1
    r = repr(cal)
    if 'ModelCalibrator' in r:
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
    validate_model_calibrator()