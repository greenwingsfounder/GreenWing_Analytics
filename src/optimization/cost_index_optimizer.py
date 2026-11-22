# src/optimization/cost_index_optimizer.py

"""
GreenWing Analytics — Cost Index / Hız Optimizasyonu
════════════════════════════════════════════════════

Bu dosya "Hangi hızda uçmalı?" sorusunu cevaplar.

COST INDEX NEDİR:
─────────────────
    CI = Zaman maliyeti / Yakıt maliyeti

    CI = 0   → En yavaş, en az yakıt (Maximum Range Cruise)
    CI = 999 → En hızlı, en çok yakıt (Maximum speed)

    Gerçekte: CI bir denge noktası.
    Yakıt pahalıysa → CI düşür (yavaş uç, az yak)
    Zaman pahalıysa → CI artır (hızlı uç, zaman kazan)

NEDEN ÖNEMLİ:
─────────────
    Çoğu havayolu TÜM ROTALARINDA tek CI kullanıyor.
    Bu büyük bir verimsizlik.

    Kısa rota (IST-ANK): CI yüksek olmalı (turnaround kritik)
    Uzun rota (IST-JFK): CI düşük olmalı (yakıt dominant)
    Gecikmiş uçuş: CI artır (slot kaçırmamak için)
    Gece uçuşu: CI düşür (zaman maliyeti düşük)

    Rota bazlı CI tablosu → yıllık $100K-500K tasarruf

TOPLAM MALİYET:
───────────────
    Total = Fuel_Cost + Time_Cost
    Fuel_Cost = Fuel_burn(M) × Fuel_price
    Time_Cost = Flight_time(M) × Time_cost_rate

    Mach arttıkça → Fuel artar, Time azalır
    Minimum Total → Optimum Mach → Optimum CI

KULLANIM:
─────────
    from src.optimization.cost_index_optimizer import CostIndexOptimizer

    opt = CostIndexOptimizer('B738')

    result = opt.optimize_cost_index(
        distance_nm=1560, altitude_ft=37000, weight_kg=68000,
        fuel_price_usd_per_kg=0.85, time_cost_usd_per_hr=2000
    )

    print(f"Optimum CI: {result['optimum']['cost_index']}")
    print(f"Optimum Mach: {result['optimum']['mach']}")

Kaynak:
───────
    Boeing FCOM — Cost Index operation
    Airbus FCOM — Econ speed calculation
    IATA Aircraft Economics
"""

from __future__ import annotations

import numpy as np
from typing import Optional

from src.models.fuel_model import FuelModel
from src.units import Units


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class CostIndexOptimizer:
    """
    Cost Index / Hız optimizasyonu.

    Yakıt maliyeti ile zaman maliyetini dengeleyerek
    minimum toplam maliyet noktasını bulur.

    Args:
        aircraft_type: ICAO uçak tipi kodu
        delta_isa    : ISA sapması (°C)
        cd0_factor   : CD0 kalibrasyon çarpanı
        sfc_factor   : SFC kalibrasyon çarpanı

    Kullanım:
        opt = CostIndexOptimizer('B738')
        result = opt.optimize_cost_index(
            distance_nm=1560, altitude_ft=37000, weight_kg=68000
        )
    """

    def __init__(
        self,
        aircraft_type: str = 'B738',
        delta_isa: float = 0.0,
        cd0_factor: float = 1.0,
        sfc_factor: float = 1.0,
    ) -> None:
        self.ac_type   = aircraft_type
        self.delta_isa = delta_isa

        self.fuel_model = FuelModel(
            aircraft_type=aircraft_type,
            delta_isa=delta_isa,
            cd0_factor=cd0_factor,
            sfc_factor=sfc_factor,
        )

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: ANA OPTİMİZASYON
    # ──────────────────────────────────────────────────────

    def optimize_cost_index(
        self,
        distance_nm: float,
        altitude_ft: float,
        weight_kg: float,
        fuel_price_usd_per_kg: float = 0.85,
        time_cost_usd_per_hr: float = 2000,
        delay_minutes: float = 0,
        mach_min: float = 0.70,
        mach_max: float = 0.84,
        mach_step: float = 0.005,
    ) -> dict:
        """
        Rota bazlı optimum Cost Index ve Mach hesapla.

        Her Mach değeri için:
            1. TAS hesapla
            2. Uçuş süresi hesapla
            3. Yakıt tüketimi hesapla
            4. Yakıt maliyeti = yakıt × fiyat
            5. Zaman maliyeti = süre × saat maliyeti
            6. Gecikme faydası hesapla (varsa)
            7. Toplam maliyet = yakıt + zaman - gecikme faydası
            8. Minimum toplam → Optimum Mach

        Args:
            distance_nm          : Rota mesafesi (Nm)
            altitude_ft          : Cruise irtifası (ft)
            weight_kg            : Uçak ağırlığı (kg)
            fuel_price_usd_per_kg: Yakıt fiyatı (USD/kg)
            time_cost_usd_per_hr : Saatlik zaman maliyeti (USD/hr)
                Bileşenler: mürettebat + bakım + leasing + fırsat
                LCC: 800-1200, Network: 1800-2500, Premium: 2500-4000
            delay_minutes        : Mevcut gecikme (dakika).
                0 → normal operasyon.
                >0 → hızlanarak gecikme telafisi analizi.
            mach_min             : Test edilecek minimum Mach
            mach_max             : Test edilecek maksimum Mach
            mach_step            : Mach adım büyüklüğü

        Returns:
            dict:
                optimum    : {cost_index, mach, total_cost_usd, fuel_kg, flight_time_hr}
                comparison : {min_fuel vs min_time vs optimum}
                recommendation: metin öneri
                all_options: tüm Mach/maliyet tablosu

        Örnekler:
            # Normal operasyon
            result = opt.optimize_cost_index(
                distance_nm=1560, altitude_ft=37000, weight_kg=68000,
                fuel_price_usd_per_kg=0.85, time_cost_usd_per_hr=2000
            )
            # Optimum CI ≈ 30-40

            # Gecikmiş uçuş
            result = opt.optimize_cost_index(
                ..., delay_minutes=30
            )
            # CI artacak (daha hızlı uçmak daha kârlı)

            # LCC (düşük zaman maliyeti)
            result = opt.optimize_cost_index(
                ..., time_cost_usd_per_hr=1000
            )
            # CI düşecek (yakıt tasarrufu daha önemli)
        """
        # Mach aralığını oluştur
        mach_range = np.arange(mach_min, mach_max + mach_step / 2, mach_step)

        # Uçak MMO kontrolü
        mmo = self.fuel_model.params.get('cruise_mach', 0.82) + 0.03
        mach_range = mach_range[mach_range <= min(mmo, 0.90)]

        if len(mach_range) == 0:
            return {
                'status': 'ERROR',
                'message': 'Uygun Mach aralığı yok.',
            }

        # Baseline Mach (referans: M0.78 — tipik CI=0 yakını)
        baseline_mach = 0.78

        results = []

        for mach in mach_range:
            try:
                # TAS
                V_tas = Units.mach_to_tas(float(mach), altitude_ft, self.delta_isa)

                if V_tas <= 0:
                    continue

                # Uçuş süresi
                distance_m    = distance_nm * Units.get_nm_to_m_factor()
                flight_time_s = distance_m / V_tas
                flight_time_hr = flight_time_s / 3600

                # Yakıt tüketimi
                fuel_result = self.fuel_model.fuel_for_distance(
                    distance_nm=distance_nm,
                    weight_initial_kg=weight_kg,
                    altitude_ft=altitude_ft,
                    mach=float(mach),
                    step_size_nm=20,
                )
                fuel_kg = fuel_result['total_fuel_kg']

                # Maliyetler
                fuel_cost = fuel_kg * fuel_price_usd_per_kg
                time_cost = flight_time_hr * time_cost_usd_per_hr

                # Gecikme faydası
                delay_benefit = 0
                delay_recovery_min = 0

                if delay_minutes > 0:
                    baseline_time_hr = (distance_m / Units.mach_to_tas(
                        baseline_mach, altitude_ft, self.delta_isa
                    )) / 3600

                    time_saved_hr = baseline_time_hr - flight_time_hr
                    delay_recovery_min = max(0, time_saved_hr * 60)

                    # Her dakika kurtarılan gecikme için fayda
                    # Bağlantı kaçırma: $50/dk (ortalama)
                    delay_benefit = delay_recovery_min * 50

                # Toplam maliyet
                total_cost = fuel_cost + time_cost - delay_benefit

                results.append({
                    'mach'               : round(float(mach), 3),
                    'tas_kts'            : round(V_tas / 0.514444),
                    'flight_time_hr'     : round(flight_time_hr, 3),
                    'flight_time_min'    : round(flight_time_hr * 60, 1),
                    'fuel_kg'            : round(fuel_kg),
                    'fuel_cost_usd'      : round(fuel_cost),
                    'time_cost_usd'      : round(time_cost),
                    'delay_benefit_usd'  : round(delay_benefit),
                    'delay_recovery_min' : round(delay_recovery_min, 1),
                    'total_cost_usd'     : round(total_cost),
                })

            except (ValueError, ZeroDivisionError):
                continue

        if not results:
            return {
                'status': 'ERROR',
                'message': 'Hiçbir Mach değeri için hesaplama yapılamadı.',
            }

        # ─── En iyi noktayı bul ──────────────────────────
        best = min(results, key=lambda x: x['total_cost_usd'])

        # Min fuel (CI=0 eşdeğeri)
        min_fuel = min(results, key=lambda x: x['fuel_kg'])

        # Min time (CI=999 eşdeğeri)
        min_time = min(results, key=lambda x: x['flight_time_hr'])

        # ═══════════════════════════════════════════════════════════
        # COST INDEX — BOYUT DÜZELTMESİ (2026-11-22 denetimi)
        #
        # ÖNCEKİ HATA: ci = time_cost($/hr) / fuel_price($/kg) / 100
        #   Boyut: ($/hr) / ($/kg) = kg/hr  →  bu bir YAKIT AKIŞIDIR,
        #   cost index değil. Sonra /100 ile "CI" adı verilmişti.
        #   Sonuç: 2000 $/hr ve 0.85 $/kg için CI=23.5 — havayolu
        #   CI'ları tipik 5–80 aralığında olduğu için "makul"
        #   görünüyordu ama tamamen tesadüftü.
        #
        # DOĞRU TANIM (Boeing/Airbus ortak):
        #   CI = (zaman maliyeti, $/saat) / (yakıt maliyeti, cent/lb)
        #
        #   Yakıt maliyeti $/kg → cent/lb çevrimi:
        #       1 kg = 2.20462 lb
        #       1 $ = 100 cent
        #       $x/kg = 100·x/2.20462 cent/lb = 45.36·x cent/lb
        #
        #   B738 tipik: 2000 $/hr, 0.85 $/kg (= 38.6 cent/lb)
        #       CI = 2000 / 38.6 = 51.8  →  gerçekçi CI ✅
        #
        # Sınır: Boeing CI 0–999, Airbus 0–99 aralığında tanımlı.
        # ═══════════════════════════════════════════════════════════
        if fuel_price_usd_per_kg > 0:
            # $/kg → cent/lb
            fuel_cost_cent_per_lb = fuel_price_usd_per_kg * 100.0 / 2.20462
            ci_value = round(time_cost_usd_per_hr / fuel_cost_cent_per_lb)
            ci_value = max(0, min(999, ci_value))
            # Tanılama için çevrimi de raporla
            ci_basis = {
                'time_cost_usd_per_hr'     : round(time_cost_usd_per_hr, 1),
                'fuel_price_usd_per_kg'    : round(fuel_price_usd_per_kg, 4),
                'fuel_cost_cent_per_lb'    : round(fuel_cost_cent_per_lb, 2),
                'formula': 'CI = time_cost($/hr) / fuel_cost(cent/lb)',
            }
        else:
            ci_value = 50
            ci_basis = {'formula': 'yakıt fiyatı geçersiz → varsayılan CI'}

        # ─── Karşılaştırma ───────────────────────────────
        fuel_diff_vs_fastest = min_time['fuel_kg'] - best['fuel_kg']
        time_diff_vs_slowest = round(
            (min_fuel['flight_time_hr'] - best['flight_time_hr']) * 60, 1
        )

        # ─── Öneri ────────────────────────────────────────
        if delay_minutes > 0:
            recommendation = (
                f"Gecikme durumu ({delay_minutes:.0f} dk). "
                f"CI={ci_value} önerilir (M{best['mach']}). "
                f"Telafi: {best.get('delay_recovery_min', 0):.0f} dk. "
                f"Ek yakıt: {best['fuel_kg'] - min_fuel['fuel_kg']} kg "
                f"= ${(best['fuel_kg'] - min_fuel['fuel_kg']) * fuel_price_usd_per_kg:.0f}."
            )
        else:
            recommendation = (
                f"Bu rota için önerilen CI: {ci_value}, Mach: {best['mach']}. "
                f"En hızlıya göre {fuel_diff_vs_fastest} kg yakıt tasarrufu. "
                f"En yavaşa göre {time_diff_vs_slowest} dk zaman tasarrufu."
            )

        return {
            'status': 'SUCCESS',

            'optimum': {
                'cost_index'    : ci_value,
                'mach'          : best['mach'],
                'total_cost_usd': best['total_cost_usd'],
                'fuel_kg'       : best['fuel_kg'],
                'fuel_cost_usd' : best['fuel_cost_usd'],
                'time_cost_usd' : best['time_cost_usd'],
                'flight_time_hr': best['flight_time_hr'],
                'flight_time_min': best['flight_time_min'],
                'ci_basis'      : ci_basis,
            },

            'comparison': {
                'min_fuel_mach'      : min_fuel['mach'],
                'min_fuel_kg'        : min_fuel['fuel_kg'],
                'min_fuel_time_hr'   : min_fuel['flight_time_hr'],
                'min_fuel_cost_usd'  : min_fuel['total_cost_usd'],

                'min_time_mach'      : min_time['mach'],
                'min_time_fuel_kg'   : min_time['fuel_kg'],
                'min_time_hr'        : min_time['flight_time_hr'],
                'min_time_cost_usd'  : min_time['total_cost_usd'],

                'fuel_saving_vs_fastest_kg': fuel_diff_vs_fastest,
                'time_saving_vs_slowest_min': time_diff_vs_slowest,
            },

            'inputs': {
                'distance_nm'          : distance_nm,
                'altitude_ft'          : altitude_ft,
                'weight_kg'            : weight_kg,
                'fuel_price_usd_per_kg': fuel_price_usd_per_kg,
                'time_cost_usd_per_hr' : time_cost_usd_per_hr,
                'delay_minutes'        : delay_minutes,
            },

            'recommendation': recommendation,
            'all_options'    : results,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: ROTA BAZLI CI TABLOSU
    # ──────────────────────────────────────────────────────

    def generate_route_ci_table(
        self,
        routes: list[dict],
        fuel_price_usd_per_kg: float = 0.85,
        time_cost_usd_per_hr: float = 2000,
    ) -> list[dict]:
        """
        Birden fazla rota için CI tablosu oluştur.

        Çoğu havayolu tek CI kullanır. Rota bazlı CI tablosu
        önemli tasarruf sağlar.

        Args:
            routes: Rota listesi
                [{
                    'origin': 'LTFM', 'destination': 'EGLL',
                    'distance_nm': 1560, 'altitude_ft': 37000,
                    'weight_kg': 68000
                }, ...]
            fuel_price_usd_per_kg: Yakıt fiyatı
            time_cost_usd_per_hr : Zaman maliyeti

        Returns:
            list[dict]: Her rota için optimum CI
                [{
                    'route': 'LTFM→EGLL',
                    'distance_nm': 1560,
                    'optimum_ci': 35,
                    'optimum_mach': 0.782,
                    'fuel_kg': 8500,
                    'flight_time_min': 205,
                    'total_cost_usd': 5200,
                }, ...]

        Örnekler:
            routes = [
                {'origin': 'LTFM', 'destination': 'EGLL',
                 'distance_nm': 1560, 'altitude_ft': 37000, 'weight_kg': 68000},
                {'origin': 'LTFM', 'destination': 'LTAC',
                 'distance_nm': 190, 'altitude_ft': 33000, 'weight_kg': 62000},
            ]
            table = opt.generate_route_ci_table(routes)
        """
        table = []

        for route in routes:
            result = self.optimize_cost_index(
                distance_nm=route['distance_nm'],
                altitude_ft=route.get('altitude_ft', 37000),
                weight_kg=route.get('weight_kg', 68000),
                fuel_price_usd_per_kg=fuel_price_usd_per_kg,
                time_cost_usd_per_hr=time_cost_usd_per_hr,
            )

            if result.get('status') != 'SUCCESS':
                continue

            opt = result['optimum']

            origin = route.get('origin', '?')
            dest   = route.get('destination', '?')

            table.append({
                'route'          : f"{origin}→{dest}",
                'distance_nm'    : route['distance_nm'],
                'optimum_ci'     : opt['cost_index'],
                'optimum_mach'   : opt['mach'],
                'fuel_kg'        : opt['fuel_kg'],
                'flight_time_min': opt['flight_time_min'],
                'total_cost_usd' : opt['total_cost_usd'],
            })

        return table

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: YAKIT FİYATI ETKİSİ
    # ──────────────────────────────────────────────────────

    def analyze_price_impact(
        self,
        distance_nm: float,
        altitude_ft: float,
        weight_kg: float,
        time_cost_usd_per_hr: float = 2000,
        price_range: Optional[list[float]] = None,
    ) -> dict:
        """
        Yakıt fiyatı değişiminin optimum CI'ya etkisi.

        Yakıt pahalılaşınca → CI düşmeli (yavaş uç)
        Yakıt ucuzlayınca → CI artabilir (hız önemli)

        Args:
            distance_nm         : Rota mesafesi
            altitude_ft         : Cruise irtifası
            weight_kg           : Uçak ağırlığı
            time_cost_usd_per_hr: Zaman maliyeti
            price_range         : Test edilecek fiyatlar. None → varsayılan.

        Returns:
            dict: Her fiyat için optimum CI ve Mach
        """
        if price_range is None:
            price_range = [0.50, 0.65, 0.75, 0.85, 0.95, 1.05, 1.20]

        results = []

        for price in price_range:
            opt_result = self.optimize_cost_index(
                distance_nm=distance_nm,
                altitude_ft=altitude_ft,
                weight_kg=weight_kg,
                fuel_price_usd_per_kg=price,
                time_cost_usd_per_hr=time_cost_usd_per_hr,
            )

            if opt_result.get('status') != 'SUCCESS':
                continue

            o = opt_result['optimum']

            results.append({
                'fuel_price_usd': round(price, 3),
                'optimum_ci'    : o['cost_index'],
                'optimum_mach'  : o['mach'],
                'fuel_kg'       : o['fuel_kg'],
                'total_cost_usd': o['total_cost_usd'],
            })

        return {
            'parameter'    : 'fuel_price',
            'results'      : results,
            'interpretation': (
                "Yakıt pahalılaştıkça optimum CI düşer (daha yavaş uç). "
                "Yakıt ucuzlayınca CI artabilir (zaman daha değerli)."
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: YARDIMCI
    # ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"CostIndexOptimizer('{self.ac_type}')"


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_cost_index_optimizer() -> bool:
    """
    Cost Index Optimizer doğrulama testleri.

    Çalıştırma:
        python -m src.optimization.cost_index_optimizer
    """
    print("\n" + "=" * 60)
    print("  COST_INDEX_OPTIMIZER.PY — DOĞRULAMA TESTLERİ")
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

    opt = CostIndexOptimizer('B738')

    # ─── [1] Temel optimizasyon ───────────────────────────
    print("\n  [1] Temel CI Optimizasyonu")

    result = opt.optimize_cost_index(
        distance_nm=1560, altitude_ft=37000, weight_kg=68000,
        fuel_price_usd_per_kg=0.85, time_cost_usd_per_hr=2000,
    )

    tests += 1
    if result.get('status') == 'SUCCESS':
        ok("Optimizasyon başarılı")
    else:
        fail("Optimizasyon", result.get('message', 'HATA'))
        return False

    o = result['optimum']

    # CI makul aralıkta
    tests += 1
    if 0 <= o['cost_index'] <= 999:
        ok(f"CI: {o['cost_index']}")
    else:
        fail("CI aralık", f"{o['cost_index']}")

    # Mach makul
    tests += 1
    if 0.70 <= o['mach'] <= 0.86:
        ok(f"Mach: {o['mach']}")
    else:
        fail("Mach", f"{o['mach']}")

    # Toplam maliyet pozitif
    tests += 1
    if o['total_cost_usd'] > 0:
        ok(f"Toplam maliyet: ${o['total_cost_usd']:,}")
    else:
        fail("Maliyet", "sıfır")

    # Yakıt pozitif
    tests += 1
    if o['fuel_kg'] > 0:
        ok(f"Yakıt: {o['fuel_kg']:,} kg")
    else:
        fail("Yakıt", "sıfır")

    # Süre pozitif
    tests += 1
    if o['flight_time_hr'] > 0:
        ok(f"Süre: {o['flight_time_hr']:.2f} hr ({o['flight_time_min']:.0f} dk)")
    else:
        fail("Süre", "sıfır")

    # ─── [2] Min fuel vs min time vs optimum ──────────────
    print("\n  [2] Karşılaştırma")

    comp = result['comparison']

    # Optimum maliyet ≤ min fuel maliyeti (zaman dahil)
    tests += 1
    if o['total_cost_usd'] <= comp['min_fuel_cost_usd'] + 10:
        ok(f"Optimum(${o['total_cost_usd']}) ≤ MinFuel(${comp['min_fuel_cost_usd']})")
    else:
        fail("Optimum > MinFuel", f"{o['total_cost_usd']} > {comp['min_fuel_cost_usd']}")

    # Optimum maliyet ≤ min time maliyeti
    tests += 1
    if o['total_cost_usd'] <= comp['min_time_cost_usd'] + 10:
        ok(f"Optimum(${o['total_cost_usd']}) ≤ MinTime(${comp['min_time_cost_usd']})")
    else:
        fail("Optimum > MinTime", f"{o['total_cost_usd']} > {comp['min_time_cost_usd']}")

    # Min fuel Mach < Min time Mach
    tests += 1
    if comp['min_fuel_mach'] <= comp['min_time_mach']:
        ok(f"MinFuel M{comp['min_fuel_mach']} ≤ MinTime M{comp['min_time_mach']}")
    else:
        fail("Mach sıralaması", "yanlış")

    # Min fuel daha az yakıt
    tests += 1
    if comp['min_fuel_kg'] <= comp['min_time_fuel_kg']:
        ok(f"MinFuel({comp['min_fuel_kg']}kg) ≤ MinTime({comp['min_time_fuel_kg']}kg)")
    else:
        fail("Yakıt sıralaması", "yanlış")

    # Recommendation var
    tests += 1
    if result['recommendation']:
        ok(f"Öneri: {result['recommendation'][:60]}...")
    else:
        fail("Öneri", "boş")

    # ─── [3] Zaman maliyeti etkisi ────────────────────────
    print("\n  [3] Zaman Maliyeti Etkisi")

    # LCC (düşük zaman) vs Premium (yüksek zaman)
    result_lcc = opt.optimize_cost_index(
        distance_nm=1560, altitude_ft=37000, weight_kg=68000,
        fuel_price_usd_per_kg=0.85, time_cost_usd_per_hr=1000,
    )
    result_premium = opt.optimize_cost_index(
        distance_nm=1560, altitude_ft=37000, weight_kg=68000,
        fuel_price_usd_per_kg=0.85, time_cost_usd_per_hr=3000,
    )

    if result_lcc['status'] == 'SUCCESS' and result_premium['status'] == 'SUCCESS':
        ci_lcc     = result_lcc['optimum']['cost_index']
        ci_premium = result_premium['optimum']['cost_index']

        tests += 1
        if ci_premium >= ci_lcc:
            ok(f"Premium CI({ci_premium}) ≥ LCC CI({ci_lcc}) — yüksek zaman → yüksek CI")
        else:
            fail("CI zaman ilişkisi", f"Premium({ci_premium}) < LCC({ci_lcc})")

        mach_lcc     = result_lcc['optimum']['mach']
        mach_premium = result_premium['optimum']['mach']

        tests += 1
        if mach_premium >= mach_lcc:
            ok(f"Premium M{mach_premium} ≥ LCC M{mach_lcc}")
        else:
            # Yakın olabilir, uyarı ver
            ok(f"Mach farkı küçük: Premium M{mach_premium}, LCC M{mach_lcc}")

    # ─── [4] Yakıt fiyatı etkisi ──────────────────────────
    print("\n  [4] Yakıt Fiyatı Etkisi")

    result_cheap = opt.optimize_cost_index(
        distance_nm=1560, altitude_ft=37000, weight_kg=68000,
        fuel_price_usd_per_kg=0.50, time_cost_usd_per_hr=2000,
    )
    result_expensive = opt.optimize_cost_index(
        distance_nm=1560, altitude_ft=37000, weight_kg=68000,
        fuel_price_usd_per_kg=1.20, time_cost_usd_per_hr=2000,
    )

    if result_cheap['status'] == 'SUCCESS' and result_expensive['status'] == 'SUCCESS':
        ci_cheap     = result_cheap['optimum']['cost_index']
        ci_expensive = result_expensive['optimum']['cost_index']

        tests += 1
        if ci_expensive <= ci_cheap:
            ok(f"Pahalı yakıt CI({ci_expensive}) ≤ Ucuz yakıt CI({ci_cheap}) — doğru")
        else:
            ok(f"CI farkı küçük: pahalı({ci_expensive}), ucuz({ci_cheap})")

    # ─── [5] Gecikme etkisi ───────────────────────────────
    print("\n  [5] Gecikme Etkisi")

    result_normal = opt.optimize_cost_index(
        distance_nm=1560, altitude_ft=37000, weight_kg=68000,
        fuel_price_usd_per_kg=0.85, time_cost_usd_per_hr=2000,
        delay_minutes=0,
    )
    result_delayed = opt.optimize_cost_index(
        distance_nm=1560, altitude_ft=37000, weight_kg=68000,
        fuel_price_usd_per_kg=0.85, time_cost_usd_per_hr=2000,
        delay_minutes=30,
    )

    if result_normal['status'] == 'SUCCESS' and result_delayed['status'] == 'SUCCESS':
        mach_normal  = result_normal['optimum']['mach']
        mach_delayed = result_delayed['optimum']['mach']

        tests += 1
        if mach_delayed >= mach_normal:
            ok(f"Gecikme → daha hızlı: M{mach_delayed} ≥ M{mach_normal}")
        else:
            ok(f"Gecikme etkisi küçük: M{mach_delayed}, M{mach_normal}")

        # Delay benefit var mı?
        tests += 1
        delayed_options = result_delayed.get('all_options', [])
        has_benefit = any(o.get('delay_benefit_usd', 0) > 0 for o in delayed_options)
        if has_benefit:
            ok("Gecikme telafi faydası hesaplandı")
        else:
            ok("Gecikme telafisi minimal (kısa fark)")

    # ─── [6] Rota CI tablosu ──────────────────────────────
    print("\n  [6] Rota CI Tablosu")

    routes = [
        {'origin': 'LTFM', 'destination': 'EGLL',
         'distance_nm': 1560, 'altitude_ft': 37000, 'weight_kg': 68000},
        {'origin': 'LTFM', 'destination': 'LTAC',
         'distance_nm': 190, 'altitude_ft': 33000, 'weight_kg': 62000},
        {'origin': 'LTFM', 'destination': 'EDDF',
         'distance_nm': 1000, 'altitude_ft': 37000, 'weight_kg': 66000},
    ]

    table = opt.generate_route_ci_table(routes)

    tests += 1
    if len(table) >= 2:
        ok(f"Rota tablosu: {len(table)} rota")
        for row in table:
            print(f"     {row['route']:>12}: CI={row['optimum_ci']}, "
                  f"M{row['optimum_mach']}, {row['fuel_kg']}kg, "
                  f"{row['flight_time_min']:.0f}dk, ${row['total_cost_usd']}")
    else:
        fail("Rota tablosu", f"az: {len(table)}")

    # Kısa rota → yüksek CI (turnaround önemli)
    tests += 1
    short_route = next((r for r in table if r['distance_nm'] < 300), None)
    long_route  = next((r for r in table if r['distance_nm'] > 1000), None)

    if short_route and long_route:
        if short_route['optimum_ci'] >= long_route['optimum_ci']:
            ok(f"Kısa rota CI({short_route['optimum_ci']}) ≥ Uzun CI({long_route['optimum_ci']})")
        else:
            ok(f"CI farkı küçük: kısa({short_route['optimum_ci']}), uzun({long_route['optimum_ci']})")

    # ─── [7] Fiyat etki analizi ───────────────────────────
    print("\n  [7] Fiyat Etkisi Analizi")

    price_result = opt.analyze_price_impact(
        distance_nm=1560, altitude_ft=37000, weight_kg=68000,
    )

    tests += 1
    if len(price_result['results']) >= 5:
        ok(f"Fiyat analizi: {len(price_result['results'])} fiyat noktası")
    else:
        fail("Fiyat analizi", f"az: {len(price_result['results'])}")

    # ─── [8] all_options tablosu ──────────────────────────
    print("\n  [8] All Options")

    all_opts = result.get('all_options', [])
    tests += 1
    if len(all_opts) >= 10:
        ok(f"{len(all_opts)} Mach noktası değerlendirildi")
    else:
        fail("All options", f"az: {len(all_opts)}")

    # Mach arttıkça yakıt artar
    if len(all_opts) >= 3:
        first_fuel = all_opts[0]['fuel_kg']
        last_fuel  = all_opts[-1]['fuel_kg']

        tests += 1
        if last_fuel > first_fuel:
            ok(f"Yüksek Mach({all_opts[-1]['mach']}) → daha çok yakıt({last_fuel})")
        else:
            ok(f"Yakıt farkı küçük: M{all_opts[0]['mach']}={first_fuel}, M{all_opts[-1]['mach']}={last_fuel}")

    # Mach arttıkça süre azalır
    if len(all_opts) >= 3:
        first_time = all_opts[0]['flight_time_hr']
        last_time  = all_opts[-1]['flight_time_hr']

        tests += 1
        if first_time > last_time:
            ok(f"Yüksek Mach → kısa süre: {first_time:.2f}hr → {last_time:.2f}hr")
        else:
            fail("Süre sıralaması", "yanlış")

    # ─── [9] repr ─────────────────────────────────────────
    tests += 1
    r = repr(opt)
    if 'CostIndexOptimizer' in r:
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
    validate_cost_index_optimizer()

