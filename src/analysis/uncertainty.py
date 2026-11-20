# src/analysis/uncertainty.py

"""
GreenWing Analytics — Belirsizlik Takibi ve Güven Aralığı
═════════════════════════════════════════════════════════════

Bu dosya "fuel = 12,450 kg" yerine "fuel = 12,450 ± 996 kg (±8%)"
formatında sonuç üretir.

NEDEN KRİTİK:
─────────────
    Müşteriye "$442 tasarruf" demek yetersiz.
    "$442 ± $55 tasarruf" demek daha dürüst ve güvenilir.

    Ayrıca:
        • Hangi verinin en çok etkili olduğunu gösterir
        • "Gerçek ağırlık verisi gelirse belirsizlik yarıya düşer"
          → müşteriyi veri paylaşmaya motive eder
        • Rakiplerden FARK yaratır (hiçbir rakip bunu yapmıyor)

BELİRSİZLİK YAYILIMI:
──────────────────────
    Bağımsız hatalar için:
        σ_total = √(σ₁² + σ₂² + σ₃² + ...)

    Örnek:
        Ağırlık belirsizliği: ±5%
        SFC belirsizliği: ±3%
        Toplam yakıt belirsizliği: √(5² + 3²) = √34 ≈ ±5.8%

    Çarpma/bölme için:
        f = a × b → σ_f/f = √((σ_a/a)² + (σ_b/b)²)

    Toplama/çıkarma için:
        f = a + b → σ_f = √(σ_a² + σ_b²)

KULLANIM:
─────────
    from src.analysis.uncertainty import UncertainValue, UncertaintyTracker

    # Belirsiz değer oluştur
    weight = UncertainValue(72000, uncertainty_pct=5.0, source="assumption")
    fuel   = UncertainValue(12450, uncertainty_pct=8.0, source="model")

    # Hesapla (belirsizlik otomatik yayılır)
    co2 = fuel.multiply_scalar(3.16)
    # co2 = 39342 ± 3147 kg (±8.0%)

    cost = fuel.multiply_scalar(0.85)
    # cost = 10582 ± 847 $ (±8.0%)

    # Güven aralığı
    print(fuel)  # "12,450 ± 996 kg (±8.0%)"
    lo, hi = fuel.confidence_range()  # (11454, 13446)

    # Tracker ile zincir izleme
    tracker = UncertaintyTracker()
    tracker.track("weight", weight)
    tracker.track("fuel", fuel)
    tracker.track("co2", co2)
    summary = tracker.get_summary()

Kaynak:
───────
    JCGM 100:2008 (GUM) — Guide to Uncertainty in Measurement
    ISO/IEC 17025 — Lab uncertainty requirements
"""

from __future__ import annotations

import numpy as np
from typing import Optional


# ═══════════════════════════════════════════════════════════
# BELİRSİZ DEĞER SINIFI
# ═══════════════════════════════════════════════════════════

class UncertainValue:
    """
    Belirsizliğiyle birlikte taşınan değer.

    Hesaplamalar sırasında belirsizlik otomatik yayılır.
    Her sonuç "değer ± hata" formatında sunulur.

    Args:
        value          : Merkez değer
        uncertainty_pct: Belirsizlik yüzdesi (±%)
        source         : Belirsizlik kaynağı açıklaması
        unit           : Birim ('kg', 'USD', 'Nm/kg', ...)

    Kullanım:
        fuel = UncertainValue(12450, 8.0, "model_estimate", "kg")
        co2  = fuel.multiply_scalar(3.16)
        print(fuel)  # "12,450 ± 996 kg (±8.0%)"
    """

    def __init__(
        self,
        value: float,
        uncertainty_pct: float = 0.0,
        source: str = "",
        unit: str = "",
    ) -> None:
        self.value           = float(value)
        self.uncertainty_pct  = float(abs(uncertainty_pct))
        self.source          = source
        self.unit            = unit

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: TEMEL ÖZELLİKLER
    # ──────────────────────────────────────────────────────

    @property
    def uncertainty_abs(self) -> float:
        """Mutlak belirsizlik (±değer)."""
        return self.value * self.uncertainty_pct / 100

    @property
    def lower_bound(self) -> float:
        """Alt sınır (değer - belirsizlik)."""
        return self.value - self.uncertainty_abs

    @property
    def upper_bound(self) -> float:
        """Üst sınır (değer + belirsizlik)."""
        return self.value + self.uncertainty_abs

    def confidence_range(self) -> tuple[float, float]:
        """
        Güven aralığı (alt, üst).

        Returns:
            tuple: (lower_bound, upper_bound)

        Örnekler:
            fuel = UncertainValue(12450, 8.0)
            lo, hi = fuel.confidence_range()
            # (11454.0, 13446.0)
        """
        return (self.lower_bound, self.upper_bound)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: ARİTMETİK İŞLEMLER (BELİRSİZLİK YAYILIMI)
    # ──────────────────────────────────────────────────────

    def multiply_scalar(
        self,
        scalar: float,
        result_unit: str = "",
        result_source: str = "",
    ) -> UncertainValue:
        """
        Sabit ile çarpma. Belirsizlik yüzdesi KORUNUR.

        f = a × c  →  σ_f/f = σ_a/a  (c sabit, hatası yok)

        Args:
            scalar       : Çarpan (sabit, belirsizliği yok)
            result_unit  : Sonucun birimi
            result_source: Sonucun kaynağı

        Returns:
            UncertainValue: Yeni belirsiz değer

        Örnekler:
            fuel = UncertainValue(12450, 8.0, unit="kg")
            co2  = fuel.multiply_scalar(3.16, result_unit="kg")
            # co2.value = 39342, co2.uncertainty_pct = 8.0%
        """
        new_value  = self.value * scalar
        new_source = result_source or f"{self.source} × {scalar}"

        return UncertainValue(
            value=new_value,
            uncertainty_pct=self.uncertainty_pct,
            source=new_source,
            unit=result_unit or self.unit,
        )

    def multiply(
        self,
        other: UncertainValue,
        result_unit: str = "",
        result_source: str = "",
    ) -> UncertainValue:
        """
        Başka belirsiz değerle çarpma. Belirsizlikler BİRLEŞİR.

        f = a × b  →  σ_f/f = √((σ_a/a)² + (σ_b/b)²)

        Args:
            other        : Diğer belirsiz değer
            result_unit  : Sonucun birimi
            result_source: Sonucun kaynağı

        Returns:
            UncertainValue: Yeni belirsiz değer

        Örnekler:
            fuel  = UncertainValue(12450, 8.0, unit="kg")
            price = UncertainValue(0.85, 3.0, unit="USD/kg")
            cost  = fuel.multiply(price, result_unit="USD")
            # cost.uncertainty_pct = √(8² + 3²) = √73 ≈ 8.5%
        """
        new_value = self.value * other.value

        # Bağımsız hatalar: kare kök toplamı
        combined_pct = float(np.sqrt(
            self.uncertainty_pct ** 2 + other.uncertainty_pct ** 2
        ))

        new_source = result_source or f"({self.source}) × ({other.source})"

        return UncertainValue(
            value=new_value,
            uncertainty_pct=combined_pct,
            source=new_source,
            unit=result_unit,
        )

    def divide(
        self,
        other: UncertainValue,
        result_unit: str = "",
        result_source: str = "",
    ) -> UncertainValue:
        """
        Başka belirsiz değere bölme. Belirsizlikler BİRLEŞİR.

        f = a / b  →  σ_f/f = √((σ_a/a)² + (σ_b/b)²)

        Args:
            other: Bölen (belirsiz değer)

        Returns:
            UncertainValue
        """
        if other.value == 0:
            return UncertainValue(0, 999, "division_by_zero", result_unit)

        new_value    = self.value / other.value
        combined_pct = float(np.sqrt(
            self.uncertainty_pct ** 2 + other.uncertainty_pct ** 2
        ))

        new_source = result_source or f"({self.source}) / ({other.source})"

        return UncertainValue(
            value=new_value,
            uncertainty_pct=combined_pct,
            source=new_source,
            unit=result_unit,
        )

    def add(
        self,
        other: UncertainValue,
        result_unit: str = "",
        result_source: str = "",
    ) -> UncertainValue:
        """
        Toplama. Mutlak belirsizlikler birleşir.

        f = a + b  →  σ_f = √(σ_a² + σ_b²)

        Args:
            other: Eklenecek belirsiz değer

        Returns:
            UncertainValue
        """
        new_value = self.value + other.value

        # Mutlak belirsizliklerin kare kök toplamı
        abs_unc = float(np.sqrt(
            self.uncertainty_abs ** 2 + other.uncertainty_abs ** 2
        ))

        # Yüzdeye çevir
        new_pct = (abs_unc / abs(new_value) * 100) if new_value != 0 else 0

        new_source = result_source or f"({self.source}) + ({other.source})"

        return UncertainValue(
            value=new_value,
            uncertainty_pct=new_pct,
            source=new_source,
            unit=result_unit or self.unit,
        )

    def subtract(
        self,
        other: UncertainValue,
        result_unit: str = "",
        result_source: str = "",
    ) -> UncertainValue:
        """
        Çıkarma. Mutlak belirsizlikler birleşir.

        f = a - b  →  σ_f = √(σ_a² + σ_b²)

        Not: Çıkarma'da göreceli belirsizlik BÜYÜR.
        Yakın değerler çıkarıldığında belirsizlik çok artabilir.

        Args:
            other: Çıkarılacak belirsiz değer

        Returns:
            UncertainValue
        """
        new_value = self.value - other.value

        abs_unc = float(np.sqrt(
            self.uncertainty_abs ** 2 + other.uncertainty_abs ** 2
        ))

        new_pct = (abs_unc / abs(new_value) * 100) if new_value != 0 else 999

        new_source = result_source or f"({self.source}) - ({other.source})"

        return UncertainValue(
            value=new_value,
            uncertainty_pct=min(new_pct, 999),
            source=new_source,
            unit=result_unit or self.unit,
        )

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: SERİLEŞTİRME
    # ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """JSON serileştirme."""
        return {
            'value'          : round(self.value, 4),
            'uncertainty_pct': round(self.uncertainty_pct, 2),
            'uncertainty_abs': round(self.uncertainty_abs, 4),
            'lower_bound'    : round(self.lower_bound, 4),
            'upper_bound'    : round(self.upper_bound, 4),
            'unit'           : self.unit,
            'source'         : self.source,
        }

    def __str__(self) -> str:
        if abs(self.value) >= 1000:
            val_str = f"{self.value:,.0f}"
            unc_str = f"{self.uncertainty_abs:,.0f}"
        elif abs(self.value) >= 1:
            val_str = f"{self.value:.2f}"
            unc_str = f"{self.uncertainty_abs:.2f}"
        else:
            val_str = f"{self.value:.6f}"
            unc_str = f"{self.uncertainty_abs:.6f}"

        unit_str = f" {self.unit}" if self.unit else ""

        return f"{val_str} ± {unc_str}{unit_str} (±{self.uncertainty_pct:.1f}%)"

    def __repr__(self) -> str:
        return (
            f"UncertainValue({self.value}, ±{self.uncertainty_pct}%, "
            f"unit='{self.unit}')"
        )


# ═══════════════════════════════════════════════════════════
# BELİRSİZLİK İZLEYİCİ
# ═══════════════════════════════════════════════════════════

class UncertaintyTracker:
    """
    Hesaplama zinciri boyunca belirsizlikleri izle.

    Her adımda belirsizliğin nasıl büyüdüğünü gösterir.
    Dominant belirsizlik kaynağını belirler.

    Kullanım:
        tracker = UncertaintyTracker()
        tracker.track("weight", UncertainValue(72000, 5.0, "assumption", "kg"))
        tracker.track("fuel", UncertainValue(12450, 8.0, "model", "kg"))
        tracker.track("co2", UncertainValue(39342, 8.0, "fuel×3.16", "kg"))
        tracker.track("saving", UncertainValue(442, 12.5, "optimization", "USD"))

        summary = tracker.get_summary()
        tracker.print_chain()
    """

    def __init__(self) -> None:
        self._chain: list[dict] = []

    def track(
        self,
        step_name: str,
        uncertain_value: UncertainValue,
    ) -> None:
        """
        Belirsiz değeri zincire ekle.

        Args:
            step_name      : Hesaplama adımı adı
            uncertain_value: Belirsiz değer
        """
        self._chain.append({
            'step'           : step_name,
            'value'          : uncertain_value.value,
            'uncertainty_pct': uncertain_value.uncertainty_pct,
            'uncertainty_abs': uncertain_value.uncertainty_abs,
            'lower_bound'    : uncertain_value.lower_bound,
            'upper_bound'    : uncertain_value.upper_bound,
            'unit'           : uncertain_value.unit,
            'source'         : uncertain_value.source,
        })

    def get_summary(self) -> dict:
        """
        Belirsizlik özeti.

        Returns:
            dict:
                chain              : tüm adımlar
                max_uncertainty_pct: en yüksek belirsizlik
                dominant_source    : en büyük belirsizlik kaynağı
                dominant_step      : hangi adımda
                growth_factor      : ilk adımdan sona belirsizlik büyümesi
        """
        if not self._chain:
            return {
                'chain'              : [],
                'max_uncertainty_pct': 0,
                'dominant_source'    : 'N/A',
                'dominant_step'      : 'N/A',
                'growth_factor'      : 1.0,
                'note'               : 'Hiç belirsizlik kaydedilmedi.',
            }

        max_unc  = max(self._chain, key=lambda x: x['uncertainty_pct'])
        first    = self._chain[0]['uncertainty_pct']
        last     = self._chain[-1]['uncertainty_pct']
        growth   = (last / first) if first > 0 else 1.0

        return {
            'chain'              : self._chain,
            'total_steps'        : len(self._chain),
            'max_uncertainty_pct': round(max_unc['uncertainty_pct'], 2),
            'dominant_source'    : max_unc['source'],
            'dominant_step'      : max_unc['step'],
            'first_uncertainty'  : round(first, 2),
            'final_uncertainty'  : round(last, 2),
            'growth_factor'      : round(growth, 2),
            'note': (
                f"Belirsizlik {first:.1f}%'den {last:.1f}%'ye "
                f"{'arttı' if last > first else 'azaldı'} "
                f"({growth:.1f}x). "
                f"Dominant kaynak: {max_unc['source']}."
            ),
        }

    def print_chain(self) -> None:
        """Belirsizlik zincirini ekrana yazdır."""
        if not self._chain:
            print("  Belirsizlik kaydı yok.")
            return

        print(f"\n  {'─'*65}")
        print(f"  BELİRSİZLİK ZİNCİRİ")
        print(f"  {'─'*65}")
        print(f"  {'Adım':<20} {'Değer':>12} {'Belirsizlik':>15} {'Aralık':>18}")
        print(f"  {'─'*65}")

        for entry in self._chain:
            val = entry['value']
            pct = entry['uncertainty_pct']
            lo  = entry['lower_bound']
            hi  = entry['upper_bound']
            u   = entry['unit']

            if abs(val) >= 1000:
                val_s = f"{val:>10,.0f}"
                rng_s = f"{lo:,.0f}–{hi:,.0f}"
            else:
                val_s = f"{val:>10.2f}"
                rng_s = f"{lo:.2f}–{hi:.2f}"

            print(
                f"  {entry['step']:<20} "
                f"{val_s} {u:<4} "
                f"±{pct:>5.1f}% "
                f"  {rng_s}"
            )

        summary = self.get_summary()
        print(f"  {'─'*65}")
        print(f"  Dominant: {summary['dominant_step']} ({summary['dominant_source']})")
        print(f"  Büyüme: {summary['first_uncertainty']:.1f}% → {summary['final_uncertainty']:.1f}%")
        print(f"  {'─'*65}")

    def get_dominant_source(self) -> str:
        """En büyük belirsizlik kaynağı."""
        summary = self.get_summary()
        return summary.get('dominant_source', 'N/A')

    def clear(self) -> None:
        """Zinciri temizle."""
        self._chain.clear()

    @property
    def step_count(self) -> int:
        """Kaydedilen adım sayısı."""
        return len(self._chain)

    def __repr__(self) -> str:
        return f"UncertaintyTracker(steps={self.step_count})"


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_uncertainty() -> bool:
    """
    Uncertainty modülü doğrulama testleri.

    Çalıştırma:
        python -m src.analysis.uncertainty
    """
    print("\n" + "=" * 60)
    print("  UNCERTAINTY.PY — DOĞRULAMA TESTLERİ")
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

    def check(name: str, actual: float, expected: float, tol: float) -> None:
        nonlocal tests
        tests += 1
        if abs(actual - expected) <= tol:
            print(f"  ✅ {name} = {actual:.4f}")
        else:
            errors.append(f"{name}: {actual} ≠ {expected}")
            print(f"  ❌ {name}: {actual} ≠ {expected}")

    # ─── [1] UncertainValue oluşturma ─────────────────────
    print("\n  [1] UncertainValue Oluşturma")

    fuel = UncertainValue(12450, 8.0, "model_estimate", "kg")

    check("value", fuel.value, 12450, 0.01)
    check("uncertainty_pct", fuel.uncertainty_pct, 8.0, 0.01)
    check("uncertainty_abs", fuel.uncertainty_abs, 996.0, 1.0)
    check("lower_bound", fuel.lower_bound, 11454, 1.0)
    check("upper_bound", fuel.upper_bound, 13446, 1.0)

    lo, hi = fuel.confidence_range()
    check("conf_range_lo", lo, 11454, 1.0)
    check("conf_range_hi", hi, 13446, 1.0)

    tests += 1
    s = str(fuel)
    if '12,450' in s and '±' in s and '8.0%' in s:
        ok(f"str: {s}")
    else:
        fail("str", s)

    # ─── [2] Scalar çarpma ────────────────────────────────
    print("\n  [2] Scalar Çarpma")

    co2 = fuel.multiply_scalar(3.16, result_unit="kg CO2")

    check("co2 value", co2.value, 39342, 1.0)
    check("co2 uncertainty", co2.uncertainty_pct, 8.0, 0.01)

    tests += 1
    if co2.unit == "kg CO2":
        ok(f"co2 unit: {co2.unit}")
    else:
        fail("co2 unit", co2.unit)

    cost = fuel.multiply_scalar(0.85, result_unit="USD")
    check("cost value", cost.value, 10582.5, 1.0)
    check("cost uncertainty", cost.uncertainty_pct, 8.0, 0.01)

    # ─── [3] Belirsiz × belirsiz ──────────────────────────
    print("\n  [3] Belirsiz × Belirsiz Çarpma")

    fuel_val  = UncertainValue(12450, 8.0, "fuel", "kg")
    price_val = UncertainValue(0.85, 3.0, "price", "USD/kg")

    total_cost = fuel_val.multiply(price_val, result_unit="USD")

    check("cost value", total_cost.value, 10582.5, 1.0)

    # √(8² + 3²) = √(64 + 9) = √73 ≈ 8.544
    expected_unc = float(np.sqrt(8**2 + 3**2))
    check("combined uncertainty", total_cost.uncertainty_pct, expected_unc, 0.1)

    # ─── [4] Bölme ───────────────────────────────────────
    print("\n  [4] Bölme")

    distance = UncertainValue(1560, 2.0, "GPS", "Nm")
    fuel_per_nm = fuel_val.divide(distance, result_unit="kg/Nm")

    check("fuel/Nm value", fuel_per_nm.value, 12450 / 1560, 0.01)

    expected_unc_div = float(np.sqrt(8**2 + 2**2))
    check("divide uncertainty", fuel_per_nm.uncertainty_pct, expected_unc_div, 0.1)

    # Sıfıra bölme
    zero_val = UncertainValue(0, 0, "zero")
    div_zero = fuel_val.divide(zero_val)
    tests += 1
    if div_zero.uncertainty_pct == 999:
        ok("Sıfıra bölme → uncertainty=999")
    else:
        fail("Sıfıra bölme", f"{div_zero.uncertainty_pct}")

    # ─── [5] Toplama ──────────────────────────────────────
    print("\n  [5] Toplama")

    fuel_a = UncertainValue(8000, 5.0, "cruise", "kg")
    fuel_b = UncertainValue(4000, 10.0, "non_cruise", "kg")

    total = fuel_a.add(fuel_b, result_unit="kg")

    check("total value", total.value, 12000, 0.01)

    # Mutlak belirsizlikler: √(400² + 400²) = √(320000) ≈ 565.7
    abs_a = 8000 * 5 / 100   # 400
    abs_b = 4000 * 10 / 100  # 400
    expected_abs = float(np.sqrt(abs_a**2 + abs_b**2))
    expected_pct = expected_abs / 12000 * 100

    check("add uncertainty_pct", total.uncertainty_pct, expected_pct, 0.5)

    # ─── [6] Çıkarma ─────────────────────────────────────
    print("\n  [6] Çıkarma")

    actual_fuel  = UncertainValue(12450, 8.0, "actual", "kg")
    optimal_fuel = UncertainValue(11800, 8.0, "optimal", "kg")

    saving = actual_fuel.subtract(optimal_fuel, result_unit="kg")

    check("saving value", saving.value, 650, 0.01)

    # Çıkarmada göreceli belirsizlik büyür
    tests += 1
    if saving.uncertainty_pct > actual_fuel.uncertainty_pct:
        ok(f"Çıkarma belirsizliği büyüdü: {saving.uncertainty_pct:.1f}% > {actual_fuel.uncertainty_pct:.1f}%")
    else:
        fail("Çıkarma belirsizlik", "büyümeli")

    # ─── [7] to_dict ──────────────────────────────────────
    print("\n  [7] Serileştirme")

    d = fuel.to_dict()
    tests += 1
    if all(k in d for k in ['value', 'uncertainty_pct', 'lower_bound', 'upper_bound']):
        ok(f"to_dict: {len(d)} alan")
    else:
        fail("to_dict", f"eksik alan: {d.keys()}")

    # ─── [8] UncertaintyTracker ───────────────────────────
    print("\n  [8] UncertaintyTracker")

    tracker = UncertaintyTracker()

    tracker.track("weight", UncertainValue(72000, 5.0, "assumption", "kg"))
    tracker.track("CL", UncertainValue(0.498, 5.2, "weight→CL", ""))
    tracker.track("drag", UncertainValue(34200, 6.1, "CL→drag", "N"))
    tracker.track("fuel_flow", UncertainValue(2347, 6.8, "drag×SFC", "kg/hr"))
    tracker.track("cruise_fuel", UncertainValue(7488, 7.5, "FF×time", "kg"))
    tracker.track("total_fuel", UncertainValue(12450, 8.0, "all_phases", "kg"))
    tracker.track("co2", UncertainValue(39342, 8.0, "fuel×3.16", "kg"))
    tracker.track("saving_usd", UncertainValue(442, 12.5, "optimization", "USD"))

    tests += 1
    if tracker.step_count == 8:
        ok(f"Tracker: {tracker.step_count} adım")
    else:
        fail("Tracker adım", f"{tracker.step_count}")

    summary = tracker.get_summary()

    tests += 1
    if summary['max_uncertainty_pct'] == 12.5:
        ok(f"Max belirsizlik: ±{summary['max_uncertainty_pct']}%")
    else:
        fail("Max belirsizlik", f"{summary['max_uncertainty_pct']}")

    tests += 1
    if summary['dominant_step'] == 'saving_usd':
        ok(f"Dominant: {summary['dominant_step']}")
    else:
        fail("Dominant", summary['dominant_step'])

    tests += 1
    if summary['growth_factor'] > 1:
        ok(f"Büyüme: {summary['growth_factor']}x ({summary['first_uncertainty']}% → {summary['final_uncertainty']}%)")
    else:
        fail("Büyüme", f"{summary['growth_factor']}")

    tests += 1
    if summary['note']:
        ok(f"Not: {summary['note'][:60]}...")
    else:
        fail("Not", "boş")

    # print_chain
    tests += 1
    try:
        tracker.print_chain()
        ok("print_chain çalışıyor")
    except Exception as e:
        fail("print_chain", str(e))

    # get_dominant_source
    tests += 1
    dom = tracker.get_dominant_source()
    if dom == 'optimization':
        ok(f"Dominant source: {dom}")
    else:
        fail("Dominant source", dom)

    # ─── [9] Tracker clear ────────────────────────────────
    print("\n  [9] Tracker Clear")

    tracker.clear()
    tests += 1
    if tracker.step_count == 0:
        ok("Clear sonrası 0 adım")
    else:
        fail("Clear", f"{tracker.step_count}")

    # Boş tracker summary
    empty_summary = tracker.get_summary()
    tests += 1
    if empty_summary['max_uncertainty_pct'] == 0:
        ok("Boş tracker → max=0")
    else:
        fail("Boş tracker", f"{empty_summary['max_uncertainty_pct']}")

    # ─── [10] Zincir hesaplama ────────────────────────────
    print("\n  [10] Zincir Hesaplama")

    # weight → fuel → co2 → cost zinciri
    w    = UncertainValue(72000, 5.0, "weight_assumption", "kg")
    f    = UncertainValue(12450, 8.0, "fuel_model", "kg")
    c    = f.multiply_scalar(3.16, result_unit="kg CO2", result_source="CO2=fuel×3.16")
    cost = f.multiply_scalar(0.85, result_unit="USD", result_source="cost=fuel×price")

    # CO2 belirsizliği = fuel belirsizliği (sabit çarpan)
    check("CO2 unc = fuel unc", c.uncertainty_pct, f.uncertainty_pct, 0.01)

    # Saving hesabı
    baseline = UncertainValue(13000, 8.0, "baseline", "kg")
    sav      = baseline.subtract(f, result_unit="kg", result_source="saving")

    tests += 1
    if sav.value == 550:
        ok(f"Saving: {sav}")
    else:
        fail("Saving value", f"{sav.value}")

    # ─── [11] Edge case: sıfır değer ─────────────────────
    print("\n  [11] Edge Cases")

    zero = UncertainValue(0, 5.0)
    tests += 1
    if zero.uncertainty_abs == 0:
        ok("Sıfır değer → sıfır mutlak belirsizlik")
    else:
        fail("Sıfır", f"{zero.uncertainty_abs}")

    # Negatif belirsizlik → mutlak değer alınır
    neg_unc = UncertainValue(100, -5.0)
    tests += 1
    if neg_unc.uncertainty_pct == 5.0:
        ok("Negatif unc → pozitif yapıldı")
    else:
        fail("Negatif unc", f"{neg_unc.uncertainty_pct}")

    # Küçük değer formatı
    small = UncertainValue(0.097, 5.0, unit="Nm/kg")
    tests += 1
    s_str = str(small)
    if '0.097' in s_str:
        ok(f"Küçük değer format: {s_str}")
    else:
        fail("Küçük format", s_str)

    # ─── [12] repr ────────────────────────────────────────
    tests += 1
    r = repr(fuel)
    if 'UncertainValue' in r:
        ok(f"UncertainValue repr: {r}")
    else:
        fail("repr", r)

    tests += 1
    r2 = repr(tracker)
    if 'UncertaintyTracker' in r2:
        ok(f"Tracker repr: {r2}")
    else:
        fail("Tracker repr", r2)

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
    validate_uncertainty()
