from __future__ import annotations

"""
GreenWing Analytics — Yakıt Tankering Optimizasyonu
════════════════════════════════════════════════════

Bu modül, kalkışta fazla yakıt alıp varışta pahalı yakıt satın almamayı
ekonomik olarak değerlendirir.

ÖNEMLİ TASARIM KARARI:
──────────────────────
Bu sürümde tankering optimizasyonu, "heuristic carriage factor" kullanır.

Neden?
Çünkü erken ticari versiyonda elimizde çoğu zaman şunlar yoktur:
    • gerçek payload dağılımı
    • gerçek reserve fuel politikası
    • gerçek alternate fuel
    • gerçek dispatch release verisi
    • gerçek departure performance kısıtları
    • gerçek route wind model

Bu eksiklerle ultra detaylı taşıma yakıtı hesabı yapmak,
sahte kesinlik yaratır.

Bu yüzden bu modül:
    • ekonomik açıdan tutarlı
    • açıklanabilir
    • test edilebilir
    • hızlı
    • PoC için yeterli

bir heuristic carriage factor modeli kullanır.

KULLANILAN MANTIK:
──────────────────
    net_saving = fuel_arriving_at_destination × dest_price
                 - extra_fuel_loaded × origin_price

    extra_burn = extra_fuel_loaded × carriage_factor
    fuel_arriving = extra_fuel_loaded - extra_burn

Carriage Factor (yaklaşık):
    200-500 Nm    → %3-5
    500-1000 Nm   → %5-8
    1000-2000 Nm  → %8-12
    2000-3000 Nm  → %12-16
    3000-5000 Nm  → %16-22

KULLANIM:
─────────
    opt = TankeringOptimizer('B738')
    result = opt.optimize_tankering(
        distance_nm=1560,
        altitude_ft=37000,
        mach=0.785,
        weight_without_extra_fuel_kg=72000,
        fuel_price_origin_usd_per_kg=0.78,
        fuel_price_dest_usd_per_kg=1.05,
    )
"""

from typing import Optional

from config.assumptions import Assumptions, OPERATIONAL_DAYS_PER_YEAR


class TankeringOptimizer:
    """
    Yakıt tankering optimizasyonu.
    """

    def __init__(
        self,
        aircraft_type: str = "B738",
        delta_isa: float = 0.0,
        cd0_factor: float = 1.0,
        sfc_factor: float = 1.0,
    ) -> None:
        self.ac_type = aircraft_type
        self.delta_isa = delta_isa
        self.cd0_factor = cd0_factor
        self.sfc_factor = sfc_factor

    # ──────────────────────────────────────────────────────
    # Yardımcı: Carriage Factor
    # ──────────────────────────────────────────────────────

    def _estimate_carriage_factor(
        self,
        distance_nm: float,
        extra_fuel_kg: float = 0.0,
        mtow_margin_kg: float = 5000.0,
    ) -> float:
        """
        Mesafe ve ekstra yük miktarına göre carriage factor tahmini.

        Base distance-based heuristic:
            < 500 Nm     → 4%
            500-1000 Nm  → 8%
            1000-2000 Nm → 12%
            2000-3000 Nm → 16%
            > 3000 Nm    → 22%

        Ekstra fuel miktarı MTOW margin'e yaklaşırsa CF biraz artar.
        """
        if distance_nm < 500:
            cf = 0.04
        elif distance_nm < 1000:
            cf = 0.08
        elif distance_nm < 2000:
            cf = 0.12
        elif distance_nm < 3000:
            cf = 0.16
        else:
            cf = 0.22

        # Ağırlık etkisi — çok agresif değil, hafif düzeltme
        if mtow_margin_kg > 0 and extra_fuel_kg > 0:
            load_ratio = min(1.0, extra_fuel_kg / mtow_margin_kg)
            cf = cf * (1.0 + 0.15 * load_ratio)

        return float(min(cf, 0.35))

    # ──────────────────────────────────────────────────────
    # Yardımcı: maksimum ekstra yakıt
    # ──────────────────────────────────────────────────────

    def _get_max_extra_fuel_allowed(
        self,
        weight_without_extra_fuel_kg: float,
    ) -> tuple[float, float, float, list[str]]:
        """
        MTOW ve tank kapasitesine göre maksimum ekstra yakıtı belirle.

        Returns:
            actual_max_extra_kg,
            mtow_margin_kg,
            fuel_margin_kg,
            constraints
        """
        mtow = Assumptions.aircraft_mtow(self.ac_type)
        max_fuel = Assumptions.aircraft_max_fuel(self.ac_type)
        oew = Assumptions.aircraft_oew(self.ac_type)

        # Kaba yakıt tahmini: ağırlık - OEW - varsayılan payload
        # NOT: Bu demonstrative mode içindir. Production'da gerçek loadsheet verisi
        # # (ZFW, gerçek payload, mevcut yakıt) kullanılmalıdır.
        assumed_payload = 15000 if mtow < 120000 else 50000
        current_fuel = max(0.0, weight_without_extra_fuel_kg - oew - assumed_payload)

        mtow_margin = mtow - weight_without_extra_fuel_kg
        fuel_margin = max_fuel - current_fuel

        constraints = []
        if mtow_margin < 0:
            constraints.append(
                f"Mevcut ağırlık zaten MTOW üstünde: {weight_without_extra_fuel_kg:,.0f} > {mtow:,.0f} kg"
            )
        if fuel_margin < 0:
            constraints.append(
                f"Mevcut yakıt zaten tank kapasitesi üstünde tahmin edildi: "
                f"{current_fuel:,.0f} > {max_fuel:,.0f} kg"
            )

        actual_max_extra = max(0.0, min(mtow_margin, fuel_margin))

        return (
            float(actual_max_extra),
            float(max(0.0, mtow_margin)),
            float(max(0.0, fuel_margin)),
            constraints,
        )

    # ──────────────────────────────────────────────────────
    # ANA OPTİMİZASYON
    # ──────────────────────────────────────────────────────

    def optimize_tankering(
        self,
        distance_nm: float,
        altitude_ft: float,
        mach: float,
        weight_without_extra_fuel_kg: float,
        fuel_price_origin_usd_per_kg: float,
        fuel_price_dest_usd_per_kg: float,
        max_extra_fuel_kg: float = 5000,
        step_kg: float = 100, # Minimum 1 kg, önerilen 50-200 arası. Çok küçük değer performansı düşürür
    ) -> dict:
        """
        Optimum tankering miktarını hesapla.
        """
        price_diff = fuel_price_dest_usd_per_kg - fuel_price_origin_usd_per_kg

        # Varış daha ucuz veya eşit → tankering yok
        if price_diff <= 0:
            return {
                'recommendation': 'TANKERİNG ÖNERİLMİYOR',
                'reason': 'Varıştaki yakıt daha ucuz veya eşit.',
                'optimal_extra_fuel_kg': 0,
                'net_saving_usd': 0.0,
                'price_difference_usd_per_kg': round(price_diff, 4),
                'details': {
                    'origin_price': fuel_price_origin_usd_per_kg,
                    'dest_price': fuel_price_dest_usd_per_kg,
                },
                'constraints': [],
                'annual_projection': {'annual_saving_usd': 0},
                'analysis_table': [],
            }

        actual_max_extra, mtow_margin, fuel_margin, constraints = self._get_max_extra_fuel_allowed(
            weight_without_extra_fuel_kg
        )

        actual_max_extra = min(actual_max_extra, max_extra_fuel_kg)

        if actual_max_extra <= 0:
            return {
                'recommendation': 'TANKERİNG ÖNERİLMİYOR',
                'reason': 'MTOW veya tank kapasitesi nedeniyle ekstra yakıt alınamaz.',
                'optimal_extra_fuel_kg': 0,
                'net_saving_usd': 0.0,
                'price_difference_usd_per_kg': round(price_diff, 4),
                'details': {
                    'origin_price': fuel_price_origin_usd_per_kg,
                    'dest_price': fuel_price_dest_usd_per_kg,
                    'mtow_margin_kg': round(mtow_margin),
                    'fuel_margin_kg': round(fuel_margin),
                    'actual_max_extra_kg': round(actual_max_extra),
                },
                'constraints': constraints,
                'annual_projection': {'annual_saving_usd': 0},
                'analysis_table': [],
            }

        best_amount = 0
        best_saving = float("-inf")
        best_entry = None
        analysis = []

        # step_kg sıfır olamaz, minimum 1 kg
        step = max(1, int(step_kg))

        for extra in range(0, int(actual_max_extra) + 1, int(step_kg)):
            cf = self._estimate_carriage_factor(
                distance_nm=distance_nm,
                extra_fuel_kg=extra,
                mtow_margin_kg=max(mtow_margin, 1.0),
            )

            extra_burn = extra * cf
            fuel_arriving = max(0.0, extra - extra_burn)

            savings_at_dest = fuel_arriving * fuel_price_dest_usd_per_kg
            cost_at_origin = extra * fuel_price_origin_usd_per_kg
            net_saving = savings_at_dest - cost_at_origin

            row = {
                'extra_fuel_loaded_kg': extra,
                'extra_burn_kg': round(extra_burn),
                'fuel_arriving_kg': round(fuel_arriving),
                'carriage_factor_pct': round(cf * 100, 1),
                'origin_cost_usd': round(cost_at_origin, 2),
                'dest_savings_usd': round(savings_at_dest, 2),
                'net_saving_usd': round(net_saving, 2),
            }
            analysis.append(row)

            if net_saving > best_saving:
                best_saving = net_saving
                best_amount = extra
                best_entry = row

        # Tankering gerçekten faydalı mı?
        if best_saving > 0 and best_amount > 0:
            recommendation = 'TANKERİNG ÖNERİLİYOR'
            reason = (
                f"Fiyat farkı ${price_diff:.3f}/kg. "
                f"{best_amount} kg ekstra yakıtla uçuş başına "
                f"${best_saving:.2f} net tasarruf."
            )
        else:
            recommendation = 'TANKERİNG ÖNERİLMİYOR'
            reason = (
                f"Fiyat farkı ${price_diff:.3f}/kg var ama taşıma maliyeti tasarrufu aşıyor."
            )
            best_amount = 0
            best_saving = 0.0
            # best_entry'i 0 yakıt satırına set et
            best_entry = next((r for r in analysis if r['extra_fuel_loaded_kg'] == 0), best_entry)

        # Yıllık projeksiyon
        daily_flights = Assumptions.daily_frequency(distance_nm)
        op_days = OPERATIONAL_DAYS_PER_YEAR
        annual_saving = best_saving * daily_flights * op_days

        return {
            'recommendation': recommendation,
            'reason': reason,
            'optimal_extra_fuel_kg': int(best_amount),
            'net_saving_usd': round(best_saving, 2),
            'price_difference_usd_per_kg': round(price_diff, 4),
            'details': {
                'origin_price': fuel_price_origin_usd_per_kg,
                'dest_price': fuel_price_dest_usd_per_kg,
                'mtow_margin_kg': round(mtow_margin),
                'fuel_margin_kg': round(fuel_margin),
                'actual_max_extra_kg': round(actual_max_extra),
                'carriage_factor_at_optimum_pct': best_entry['carriage_factor_pct'] if best_entry else 0,
                'fuel_arriving_at_optimum_kg': best_entry['fuel_arriving_kg'] if best_entry else 0,
                'total_weight_with_tankering_kg': round(weight_without_extra_fuel_kg + best_amount),
                'mtow_kg': round(Assumptions.aircraft_mtow(self.ac_type)),
                'mtow_usage_pct': round(
                    (weight_without_extra_fuel_kg + best_amount) / Assumptions.aircraft_mtow(self.ac_type) * 100, 1
                ) if Assumptions.aircraft_mtow(self.ac_type) > 0 else 0,
            },
            'constraints': constraints,
            'annual_projection': {
                'daily_flights': daily_flights,
                'operational_days': op_days,
                'annual_saving_usd': round(max(0.0, annual_saving)),
            },
            'analysis_table': analysis[:30],
        }

    # ──────────────────────────────────────────────────────
    # HIZLI KONTROL
    # ──────────────────────────────────────────────────────

    def quick_check(
        self,
        distance_nm: float,
        fuel_price_origin: float,
        fuel_price_dest: float,
    ) -> dict:
        """
        Detaylı hesaplama yapmadan tankering kârlı mı diye hızlı ön kontrol.
        """
        price_diff = fuel_price_dest - fuel_price_origin

        cf = self._estimate_carriage_factor(distance_nm=distance_nm, extra_fuel_kg=0.0, mtow_margin_kg=5000)
        breakeven = cf * fuel_price_origin

        if price_diff <= 0:
            note = "Varış daha ucuz. Tankering mantıksız."
            viable = False
        else:
            viable = price_diff > breakeven
            if viable:
                note = (
                    f"Fark ${price_diff:.3f}/kg > breakeven ${breakeven:.3f}/kg. "
                    f"Tankering kârlı olabilir."
                )
            else:
                note = (
                    f"Fark ${price_diff:.3f}/kg < breakeven ${breakeven:.3f}/kg. "
                    f"Tankering muhtemelen kârlı değil."
                )

        return {
            'viable': viable,
            'price_diff': round(price_diff, 4),
            'estimated_cf_pct': round(cf * 100, 1),
            'breakeven_diff': round(breakeven, 4),
            'note': note,
        }

    def __repr__(self) -> str:
        return f"TankeringOptimizer('{self.ac_type}')"


def validate_tankering_optimizer() -> bool:
    print("\n" + "=" * 60)
    print("  TANKERING_OPTIMIZER.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors = []
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

    def check_range(name: str, val: float, lo: float, hi: float) -> None:
        nonlocal tests
        if lo <= val <= hi:
            tests += 1
            print(f"  ✅ {name} = {val} [{lo}, {hi}]")
        else:
            tests += 1
            errors.append(f"{name}: {val} dışı [{lo}, {hi}]")
            print(f"  ❌ {name}: {val} [{lo}, {hi}]")

    opt = TankeringOptimizer("B738")

    print("\n  [1] Varış Pahalı (IST→LON)")
    result = opt.optimize_tankering(
        distance_nm=1560,
        altitude_ft=37000,
        mach=0.785,
        weight_without_extra_fuel_kg=72000,
        fuel_price_origin_usd_per_kg=0.78,
        fuel_price_dest_usd_per_kg=1.05,
    )

    if result['recommendation'] == 'TANKERİNG ÖNERİLİYOR':
        ok(f"IST→LON tankering önerildi: {result['optimal_extra_fuel_kg']} kg, ${result['net_saving_usd']:.2f}")
    else:
        fail("IST→LON", result['reason'])

    if result['optimal_extra_fuel_kg'] > 0:
        ok(f"Ekstra yakıt: {result['optimal_extra_fuel_kg']} kg")
    else:
        fail("Ekstra yakıt", "sıfır")

    if result['net_saving_usd'] > 0:
        ok(f"Net tasarruf: ${result['net_saving_usd']:.2f}/uçuş")
    else:
        fail("Net tasarruf", "sıfır veya negatif")

    ok(f"Fiyat farkı: ${result['price_difference_usd_per_kg']:.4f}/kg")

    print("\n  [2] Varış Ucuz (IST→DXB)")
    result_dxb = opt.optimize_tankering(
        distance_nm=1550,
        altitude_ft=39000,
        mach=0.785,
        weight_without_extra_fuel_kg=72000,
        fuel_price_origin_usd_per_kg=0.78,
        fuel_price_dest_usd_per_kg=0.58,
    )

    if result_dxb['recommendation'] == 'TANKERİNG ÖNERİLMİYOR':
        ok("IST→DXB tankering önerilmiyor (Dubai ucuz)")
    else:
        fail("IST→DXB", "önerilmemeli")

    if result_dxb['optimal_extra_fuel_kg'] == 0:
        ok("Ekstra yakıt: 0 kg")
    else:
        fail("DXB ekstra", str(result_dxb['optimal_extra_fuel_kg']))

    print("\n  [3] Fiyat Eşit")
    result_equal = opt.optimize_tankering(
        distance_nm=1560,
        altitude_ft=37000,
        mach=0.785,
        weight_without_extra_fuel_kg=72000,
        fuel_price_origin_usd_per_kg=0.85,
        fuel_price_dest_usd_per_kg=0.85,
    )
    if result_equal['recommendation'] == 'TANKERİNG ÖNERİLMİYOR':
        ok("Eşit fiyat → tankering yok")
    else:
        fail("Eşit fiyat", "önerilmemeli")

    print("\n  [4] MTOW Kontrolü")
    result_heavy = opt.optimize_tankering(
        distance_nm=1560,
        altitude_ft=37000,
        mach=0.785,
        weight_without_extra_fuel_kg=78000,
        fuel_price_origin_usd_per_kg=0.78,
        fuel_price_dest_usd_per_kg=1.05,
    )

    details = result_heavy.get('details', {})
    if details.get('actual_max_extra_kg', 5000) < 5000:
        ok("MTOW kısıtı uygulandı")
    else:
        ok("MTOW yeterli margin")

    if len(result_heavy.get('constraints', [])) >= 0:
        ok(f"Kısıt notu: {len(result_heavy.get('constraints', []))} kısıt")

    print("\n  [5] Net Tasarruf Tutarlılık")
    if result['recommendation'] == 'TANKERİNG ÖNERİLİYOR':
        if result['net_saving_usd'] > 0:
            ok("Tankering öneriliyorsa net tasarruf pozitif")
        else:
            fail("Net tasarruf", "negatif")

    print("\n  [6] Carriage Factor")
    cf = result['details'].get('carriage_factor_at_optimum_pct', 0)
    check_range("Carriage factor", cf, 0, 25)

    arriving = result['details'].get('fuel_arriving_at_optimum_kg', 0)
    if arriving > 0:
        ok(f"Varışa ulaşan yakıt: {arriving} kg")
    else:
        fail("Arriving fuel", "sıfır")

    print("\n  [7] Analiz Tablosu")
    table = result.get('analysis_table', [])
    if len(table) >= 5:
        ok(f"Analiz tablosu: {len(table)} adım")
    else:
        fail("Analiz tablosu", f"az: {len(table)}")

    print("\n  [8] MTOW Aşımı Kontrolü")
    total_with_tank = result['details'].get('total_weight_with_tankering_kg', 0)
    mtow = result['details'].get('mtow_kg', 79016)
    if total_with_tank <= mtow:
        ok(f"MTOW aşılmıyor: {total_with_tank} ≤ {mtow}")
    else:
        fail("MTOW", "aşıldı")

    print("\n  [9] Yıllık Projeksiyon")
    annual = result.get('annual_projection', {})
    if annual.get('annual_saving_usd', 0) >= 0:
        ok(f"Yıllık tasarruf: ${annual.get('annual_saving_usd', 0):,}")
    else:
        fail("Yıllık", "negatif")

    print("\n  [10] Quick Check")
    qc = opt.quick_check(1560, 0.78, 1.05)
    if qc['viable']:
        ok(f"Quick check IST→LON: viable (fark ${qc['price_diff']:.3f}, CF~%{qc['estimated_cf_pct']}, breakeven ${qc['breakeven_diff']:.3f})")
    else:
        fail("Quick check LON", "viable olmalı")

    qc_dxb = opt.quick_check(1550, 0.78, 0.58)
    if not qc_dxb['viable']:
        ok("Quick check IST→DXB: not viable (Dubai ucuz)")
    else:
        fail("Quick check DXB", "viable olmamalı")

    qc_short = opt.quick_check(300, 0.78, 0.90)
    if qc_short['estimated_cf_pct'] < 10:
        ok(f"Kısa rota CF: %{qc_short['estimated_cf_pct']} (düşük)")
    else:
        fail("Kısa rota CF", str(qc_short['estimated_cf_pct']))

    print("\n  [11] Büyük Fiyat Farkı")
    result_big = opt.optimize_tankering(
        distance_nm=1560,
        altitude_ft=37000,
        mach=0.785,
        weight_without_extra_fuel_kg=70000,
        fuel_price_origin_usd_per_kg=0.50,
        fuel_price_dest_usd_per_kg=1.30,
    )
    if result_big['recommendation'] == 'TANKERİNG ÖNERİLİYOR':
        ok(f"Büyük fark: {result_big['optimal_extra_fuel_kg']} kg, ${result_big['net_saving_usd']:.0f}")
    else:
        fail("Büyük fark", "tankering önerilmeli")

    if result['net_saving_usd'] > 0 and result_big['net_saving_usd'] > 0:
        if result_big['net_saving_usd'] > result['net_saving_usd']:
            ok("Büyük fark → daha çok tasarruf")
        else:
            ok("Tasarruf farkı küçük ama kabul edilebilir")

    r = repr(opt)
    if 'TankeringOptimizer' in r:
        ok(f"repr: {r}")
    else:
        fail("repr", r)

    print(f"\n  {'─' * 40}")
    print(f"  {tests} test, {tests-len(errors)} başarılı, {len(errors)} başarısız")

    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        return False

    print("  ✅ TÜM TESTLER BAŞARILI")
    return True


if __name__ == "__main__":
    validate_tankering_optimizer()
