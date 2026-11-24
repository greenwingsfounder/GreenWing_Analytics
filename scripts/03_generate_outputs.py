# scripts/03_generate_outputs.py

"""
GreenWing Analytics — Çıktı Üretim Scripti
═══════════════════════════════════════════

Bu script analiz sonuçlarını müşteriye sunulabilir
profesyonel çıktılara dönüştürür.

NE YAPIYOR:
───────────
    1. batch_results.json'u yükler ve kalite kontrolü yapar
    2. Veri kalitesini değerlendirir (partial flight tespiti)
    3. Fleet raporu üretir (HTML → PDF)
    4. CORSIA raporu üretir (MRV uyumlu)
    5. Case study özeti oluşturur
    6. LinkedIn post taslağı üretir
    7. Cold email taslakları üretir

VERİ KALİTESİ YÖNETİMİ:
─────────────────────────
    02_analyze_and_optimize.py artık şu alanları yazıyor:
        fuel_optimization_kg   → fleet_analyzer'a geçirilir
        total_cost_saving_usd  → fleet_analyzer'a geçirilir
        annual_realistic_usd   → fleet_analyzer'a geçirilir
        origin_airport         → rota için
        dest_airport           → rota için
        is_partial_flight      → benchmark kararı için
        collection_method      → kalite göstergesi

TASARRUF MAPPING:
──────────────────
    02 script alanı          → add_manual_flight() parametresi
    fuel_optimization_kg     → fuel_saving_kg
    total_cost_saving_usd    → cost_saving_usd
    annual_realistic_usd     → annual_saving_usd

ÇALIŞTIRMA:
───────────
    python scripts/03_generate_outputs.py

GİRDİ:
──────
    reports/optimizations/batch_results.json

ÇIKTILAR:
─────────
    reports/GreenWing_CaseStudy_YYYYMMDD.html
    reports/case_studies/case_study_YYYYMMDD.json
    reports/case_studies/data_quality_YYYYMMDD.json
    reports/case_studies/corsia_report_YYYYMMDD.json
    reports/case_studies/linkedin_post_YYYYMMDD.txt
    reports/case_studies/email_{CODE}_YYYYMMDD.txt
"""

import sys
import os
import json
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.analysis.fleet_analyzer import FleetAnalyzer
from src.reporting.report_generator import ReportGenerator
from src.models.blockchain_sealer import BlockchainSealer
from src.optimization.tail_performance_calibrator import TailPerformanceCalibrator
from config.settings import REPORTS_OPTIMIZATIONS, REPORTS_CASE_STUDIES


# ═══════════════════════════════════════════════════════════
# AYARLAR
# ═══════════════════════════════════════════════════════════

AIRLINE_NAME  = "SunExpress Airlines — B738 Fleet Fuel Efficiency Analysis"
REPORT_PERIOD = f"Demonstrative Analysis — Q2 {datetime.now().year} (Physics-Based Simulation)"
DEFAULT_AC_TYPE        = 'B738'
DEFAULT_ORIGIN         = 'LTFM'
DEFAULT_FUEL_PRICE_USD = 0.85

EMAIL_TARGETS = [
    {"name": "Pegasus Airlines",  "code": "PGT", "contact": "VP Operations"},
    {"name": "FlyDubai",          "code": "FDB", "contact": "Director Flight Operations"},
    {"name": "Air Arabia",        "code": "ABY", "contact": "VP Operations"},
    {"name": "Jazeera Airways",   "code": "JAZ", "contact": "Chief Operating Officer"},
    {"name": "RwandAir",          "code": "RWD", "contact": "VP Operations"},
    {"name": "SunExpress",        "code": "SXS", "contact": "VP Operations"},
]


# ═══════════════════════════════════════════════════════════
# YARDIMCI FONKSIYONLAR
# ═══════════════════════════════════════════════════════════

def safe_float(r: dict, key: str, default: float = 0.0) -> float:
    """batch_results kaydından güvenli float oku."""
    val = r.get(key, default)
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def safe_int(r: dict, key: str, default: int = 0) -> int:
    """batch_results kaydından güvenli int oku."""
    val = r.get(key, default)
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def safe_str(r: dict, key: str, default: str = '') -> str:
    """batch_results kaydından güvenli str oku."""
    val = r.get(key, default)
    return str(val).strip() if val is not None else default


def run_data_quality_check(results: list[dict]) -> dict:
    """
    Tüm batch_results için kalite raporu üret.

    Returns:
        dict: quality_grade, partial_count, valid_count, vb.
    """
    n              = len(results)
    partial_count  = 0
    unk_dest_count = 0
    details        = []

    for r in results:
        fuel_kg  = safe_float(r, 'estimated_fuel_kg')
        dist_nm  = safe_float(r, 'distance_nm', 1.0)
        dest     = safe_str(r, 'dest_airport', 'UNK')
        ac_type  = safe_str(r, 'aircraft_type', DEFAULT_AC_TYPE)

        # is_partial_flight alanı 02 scriptinden geliyor
        is_partial = r.get('is_partial_flight', False)
        if is_partial is None:
            is_partial = False

        if is_partial:
            partial_count += 1
        if dest.upper() in {'UNK', 'UNKN', '', 'N/A'}:
            unk_dest_count += 1

        fuel_per_nm = fuel_kg / max(dist_nm, 1.0)
        details.append({
            'callsign'     : safe_str(r, 'callsign', '?'),
            'origin'       : safe_str(r, 'origin_airport', 'UNK'),
            'destination'  : dest,
            'fuel_kg'      : fuel_kg,
            'distance_nm'  : dist_nm,
            'fuel_per_nm'  : round(fuel_per_nm, 2),
            'is_partial'   : is_partial,
            'method'       : safe_str(r, 'collection_method', 'unknown'),
            'quality_grade': safe_str(r, 'data_quality.quality_grade', '?')
                             if isinstance(r.get('data_quality'), str)
                             else r.get('data_quality', {}).get('quality_grade', '?'),
        })

    partial_pct = partial_count / n * 100 if n > 0 else 0

    # ──────────────────────────────────────────────────────────────
    # PROVENANCE GATE (BÜTÜNLÜK — P0)
    # ──────────────────────────────────────────────────────────────
    # Önceki sürüm YALNIZCA kısmi-uçuş yüzdesine bakıyordu. Simüle
    # edilmiş (demo_simulation) veri de 'A — Veriler güvenilir' notu
    # alıyordu. Bu, bir havayolu müşterisine "gerçek veri" izlenimi
    # vermek açısından yanıltıcıydı.
    #
    # Kural: Not, verinin KAYNAĞINA (provenance) bağlıdır.
    #   REAL  (opensky/adsb/customer_qar) → kısmi yüzdesine göre A..D
    #   SIM   (demo_simulation)          → SIM (en fazla 'Simülasyon')
    #   MIX   (karışık)                  → MIX — ayrıştırılmalı
    # ══════════════════════════════════════════════════════════════
    # ÖNCEKİ HATA (2026-11-22 denetimi): 'synthetic_fallback'
    # etiketi tanınmıyordu. 01_collect_data.py veri toplayamayınca
    # bu etiketi yazıyor; sonuç:
    #     n_real = 1 (arrivals), n_sim = 0, n_unk = 13
    #     → provenance = 'UNKNOWN' → not '?' (Bilinmeyen veri kaynağı)
    # Yani 13 sentetik uçuş "bilinmiyor" sayılıyordu. Bu, panelde
    # ve raporda veri kaynağı bilgisini KAYBEDİYORDU.
    # ══════════════════════════════════════════════════════════════
    REAL_METHODS = {'opensky', 'adsb', 'opensky_adsb', 'arrivals', 'departures',
                    'active_flight', 'customer_qar', 'customer_fuel',
                    'qar', 'fdr'}
    methods = [safe_str(r, 'collection_method', 'unknown').lower() for r in results]
    n_real = sum(1 for m in methods if m in REAL_METHODS)
    n_sim  = sum(1 for m in methods
                 if ('simulation' in m or 'synthetic' in m
                     or 'mock' in m or 'demo' in m))
    n_unk  = n - n_real - n_sim

    if n_real == n:
        provenance = 'REAL'
    elif n_sim == n:
        provenance = 'SIMULATED'
    elif n_real + n_sim == n:
        provenance = 'MIXED'
    else:
        provenance = 'UNKNOWN'

    if provenance == 'SIMULATED':
        grade = 'SIM'
        desc  = ('SİMÜLASYON — Fizik modeli çıktısı; gerçek uçuş verisi DEĞİL. '
                 'Doğrulama için QAR/FDR veya müşteri yakıt verisi gerekir.')
    elif provenance == 'UNKNOWN':
        grade = '?'
        desc  = 'Bilinmeyen veri kaynağı — provenance etiketi eksik.'
    elif provenance == 'MIXED':
        grade = 'MIX'
        desc  = (f'KARIŞIK — {n_real} gerçek + {n_sim} simüle uçuş. '
                 'İstatistikler ayrıştırılarak raporlanmalı.')
    else:  # REAL
        if partial_pct < 10:
            grade = 'A'
            desc  = 'Mükemmel — Gerçek veri, kısmi uçuş oranı düşük'
        elif partial_pct < 30:
            grade = 'B'
            desc  = 'İyi — Gerçek veri, çoğu kullanılabilir'
        elif partial_pct < 60:
            grade = 'C'
            desc  = 'Orta — Gerçek veri, dikkatli yorum'
        else:
            grade = 'D'
            desc  = 'Düşük — Arrivals endpoint önerilir'

    recommendations = []
    if partial_pct > 20:
        recommendations.append(
            "Arrivals endpoint kullanıldığından emin ol "
            "(01_collect_data.py)."
        )
    if unk_dest_count > 0:
        recommendations.append(
            f"{unk_dest_count} uçuşta varış bilinmiyor. "
            "Callsign bazlı tahmin veya müşteri schedule verisi ekle."
        )
    if provenance == 'SIMULATED':
        recommendations.insert(0,
            "Bu çıktı SİMÜLASYONDUR. Müşteri sunumu öncesi gerçek "
            "QAR/FDR veya müşteri yakıt verisiyle değiştirilmelidir. "
            "Aksi halde yalnızca 'demonstrasyon' olarak sunulabilir.")
    elif provenance == 'MIXED':
        recommendations.insert(0,
            "Karışık veri kaynağı: gerçek ve simüle uçuşlar ayrı "
            "raporlanmalı, birleşik istatistik SUNULMAMALIDIR.")
    elif provenance == 'REAL' and partial_pct <= 10:
        recommendations.append("Veri kalitesi yüksek.")

    return {
        'total'          : n,
        'valid'          : n - partial_count,
        'partial'        : partial_count,
        'unk_destination': unk_dest_count,
        'partial_pct'    : round(partial_pct, 1),
        'quality_grade'  : grade,
        'quality_desc'   : desc,
        'provenance'     : provenance,
        'n_real'         : n_real,
        'n_simulated'    : n_sim,
        'n_unknown'      : n_unk,
        'details'        : details,
        'recommendations': recommendations,
    }


# ═══════════════════════════════════════════════════════════
# ANA FONKSİYON
# ═══════════════════════════════════════════════════════════

def main():
    """Ana çıktı üretim fonksiyonu."""

    print("\n" + "=" * 65)
    print(f"  GreenWing Analytics — Çıktı Üretimi")
    print(f"  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    date_str  = datetime.now().strftime('%Y%m%d')

    # ─── Sonuçları yükle ──────────────────────────────────
    results_path = os.path.join(REPORTS_OPTIMIZATIONS, "batch_results.json")

    if not os.path.exists(results_path):
        print(f"\n  ❌ Sonuç dosyası bulunamadı: {results_path}")
        print(f"  Önce çalıştır: python scripts/02_analyze_and_optimize.py")
        return

    with open(results_path, encoding='utf-8') as f:
        results = json.load(f)

    if not results:
        print(f"\n  ❌ Sonuç dosyası boş!")
        return

    print(f"\n  📥 {len(results)} uçuş sonucu yüklendi")

    # ─── Dinamik Havayolu ve Uçak Tipi Belirleme ───────────
    airlines_found = set()
    ac_types_found = set()
    for r in results:
        call = str(r.get('callsign', '')).strip().upper()
        ac = str(r.get('aircraft_type', 'B738')).strip().upper()
        ac_types_found.add(ac)
        
        if call.startswith(('THY', 'TK')):
            airlines_found.add('Turkish Airlines (THY)')
        elif call.startswith(('PGT', 'PC')):
            airlines_found.add('Pegasus Airlines (PGT)')
        elif call.startswith(('SXS', 'XQ')):
            airlines_found.add('SunExpress (SXS)')
        else:
            prefix = call[:3]
            if prefix and prefix.isalpha():
                airlines_found.add(f"Airline {prefix}")

    if len(airlines_found) == 1:
        detected_airline = list(airlines_found)[0]
    elif len(airlines_found) > 1:
        short_names = []
        for name in sorted(list(airlines_found)):
            if "(" in name:
                short_names.append(name.split("(")[1].replace(")", ""))
            else:
                short_names.append(name[:3])
        detected_airline = "Multi-Airline (" + ", ".join(short_names) + ")"
    else:
        detected_airline = "SunExpress (SXS)"

    if len(ac_types_found) == 1:
        detected_ac = list(ac_types_found)[0]
    else:
        detected_ac = "Multi-Aircraft"

    global AIRLINE_NAME
    AIRLINE_NAME = f"{detected_airline} — {detected_ac} Fleet Fuel Efficiency Analysis"

    os.makedirs(REPORTS_CASE_STUDIES, exist_ok=True)

    # ═══════════════════════════════════════════════════════
    # ADIM 0: VERİ KALİTESİ KONTROLÜ
    # ═══════════════════════════════════════════════════════

    print(f"\n{'─'*65}")
    print(f"  🔍 0. Veri Kalitesi Kontrolü")
    print(f"{'─'*65}")

    quality_report = run_data_quality_check(results)

    print(f"\n  Toplam  : {quality_report['total']} uçuş")
    print(f"  Tam     : {quality_report['valid']} uçuş")
    print(f"  Partial : {quality_report['partial']} uçuş (%{quality_report['partial_pct']:.0f})")
    print(f"  Kalite  : {quality_report['quality_grade']} — {quality_report['quality_desc']}")

    print(f"\n  Uçuş Detayı:")
    for q in quality_report['details']:
        icon = '⚠' if q['is_partial'] else '✅'
        print(
            f"    {icon} {q['callsign']:<12} "
            f"{q['origin']}→{q['destination']:<5} "
            f"{q['fuel_per_nm']:.2f} kg/Nm "
            f"[{q['method']}]"
        )

    # Kalite raporunu kaydet
    quality_path = os.path.join(
        REPORTS_CASE_STUDIES, f"data_quality_{date_str}.json"
    )
    with open(quality_path, 'w', encoding='utf-8') as f:
        json.dump(quality_report, f, indent=2, default=str, ensure_ascii=False)
    print(f"\n  💾 Kalite raporu: {quality_path}")

    # ═══════════════════════════════════════════════════════
    # ADIM 1: FLEET RAPORU
    # ═══════════════════════════════════════════════════════

    print(f"\n{'─'*65}")
    print(f"  📄 1. Fleet Raporu Üretimi")
    print(f"{'─'*65}")

    fleet = FleetAnalyzer()

    print(f"\n  Uçuşlar ekleniyor...")

    for i, r in enumerate(results):
        # ─── Temel alanlar ────────────────────────────────
        callsign      = safe_str(r, 'callsign', f'FLT{i+1:03d}')
        dest_airport  = safe_str(r, 'dest_airport', 'UNK')
        origin_airport = safe_str(r, 'origin_airport', DEFAULT_ORIGIN)
        ac_type       = safe_str(r, 'aircraft_type', DEFAULT_AC_TYPE)
        fuel_kg       = safe_float(r, 'estimated_fuel_kg')
        dist_nm       = safe_float(r, 'distance_nm')
        cruise_alt    = safe_float(r, 'cruise_altitude_ft', 35000)

        # Geçerlilik kontrol
        if fuel_kg <= 0 or dist_nm <= 0:
            print(f"    ⚠ {callsign}: Geçersiz yakıt/mesafe, atlanıyor")
            continue

        # ─── TASARRUF ALANLARI (kritik mapping) ───────────
        # 02 scriptindeki alan     →  add_manual_flight() parametresi
        # fuel_optimization_kg     →  fuel_saving_kg
        # total_cost_saving_usd    →  cost_saving_usd
        # annual_realistic_usd     →  annual_saving_usd
        fuel_saving_kg    = safe_float(r, 'fuel_optimization_kg', 0.0)
        cost_saving_usd   = safe_float(r, 'total_cost_saving_usd', 0.0)
        annual_saving_usd = safe_float(r, 'annual_realistic_usd', 0.0)

        # ─── Optimizasyon detayları ───────────────────────
        optimum_fl           = safe_str(r, 'optimum_fl', '')
        buffet_margin_pct    = safe_float(r, 'buffet_margin_pct', 0.0)
        sar_loss_pct         = safe_float(r, 'sar_loss_pct', 0.0)
        step_climb_saving_kg = safe_float(r, 'step_climb_saving_kg', 0.0)
        step_plan            = r.get('step_plan', []) or []
        optimum_ci           = safe_int(r, 'optimum_ci', 0)
        optimum_mach         = safe_float(r, 'optimum_mach', 0.0)
        tankering_amount_kg  = safe_int(r, 'tankering_amount_kg', 0)
        tankering_saving_usd = safe_float(r, 'tankering_saving_usd', 0.0)
        altitude_saving_kg   = safe_float(r, 'altitude_saving_kg', 0.0)

        # ─── Veri kalitesi ────────────────────────────────
        is_partial  = r.get('is_partial_flight', False) or False
        data_source = safe_str(r, 'collection_method', 'opensky_adsb')

        # ─── Ekle ─────────────────────────────────────────
        fleet.add_manual_flight(
            origin               = origin_airport,
            destination          = dest_airport,
            fuel_kg              = fuel_kg,
            distance_nm          = dist_nm,
            aircraft_type        = ac_type,
            flight_number        = callsign,
            cruise_altitude_ft   = cruise_alt,
            fuel_saving_kg       = fuel_saving_kg,
            cost_saving_usd      = cost_saving_usd,
            annual_saving_usd    = annual_saving_usd,
            optimum_fl           = optimum_fl,
            buffet_margin_pct    = buffet_margin_pct,
            sar_loss_pct         = sar_loss_pct,
            step_climb_saving_kg = step_climb_saving_kg,
            step_plan            = step_plan,
            optimum_ci           = optimum_ci,
            optimum_mach         = optimum_mach,
            tankering_amount_kg  = tankering_amount_kg,
            tankering_saving_usd = tankering_saving_usd,
            altitude_saving_kg   = altitude_saving_kg,
            altitude_deviation_ft = safe_float(r, 'altitude_deviation_ft', 0.0),  # ✅
            step_climb_applied    = bool(r.get('step_climb_applied', False)),     # ✅
            is_partial_flight    = is_partial,
            data_source          = data_source,
            # BÜTÜNLÜK: provenance aktarımı (yoksa kalite notu yanlış).
            collection_method    = safe_str(r, 'collection_method', 'unknown'),
            # BÜTÜNLÜK: tek fiyat kaynağı (sabit $0.85 gömülü değil).
            fuel_price_usd_kg    = DEFAULT_FUEL_PRICE_USD,
        )

        icon = '⚠' if is_partial else '✅'
        print(
            f"    {icon} {callsign:<12} "
            f"{origin_airport}→{dest_airport:<5} "
            f"{dist_nm:>5.0f}Nm {fuel_kg:>6,.0f}kg "
            f"→ save: {fuel_saving_kg:>4.0f}kg "
            f"${cost_saving_usd:>5.0f} "
            f"ann: ${annual_saving_usd:>8,.0f}"
            + (' [PARTIAL]' if is_partial else '')
        )

    print(
        f"\n  Eklendi: {fleet.flight_count} uçuş "
        f"({fleet.valid_flight_count} tam, "
        f"{fleet.partial_flight_count} partial)"
    )

    # ─── Filo özeti ───────────────────────────────────────
    summary = fleet.generate_fleet_summary(
        exclude_partial_from_benchmark=True,
        avg_fuel_price_usd_per_kg=DEFAULT_FUEL_PRICE_USD,
    )

    if 'error' in summary:
        print(f"\n  ❌ Filo özeti üretimi başarısız: {summary['error']}")
        return

    # Tasarruf özeti
    sv = summary['savings_potential']
    print(f"\n  📊 Tasarruf Özeti:")
    print(f"     Yakıt     : {sv['total_fuel_saving_kg']:,} kg")
    print(f"     Maliyet   : ${sv['total_cost_saving_usd']:,}")
    print(f"     CO₂       : {sv['total_co2_saving_kg']:,} kg")
    print(f"     Yıllık    : ${sv['annualized_cost_saving_usd']:,}")
    print(f"     Yakıt/yıl : {sv['annualized_fuel_saving_tonnes']} ton")
    print(f"     CO₂/yıl   : {sv['annualized_co2_saving_tonnes']} ton")

    if sv['annualized_cost_saving_usd'] == 0:
        print(f"\n  ⚠ Yıllık tasarruf sıfır!")
        print(f"     batch_results.json içinde 'annual_realistic_usd' var mı?")
        print(f"     02_analyze_and_optimize.py yeniden çalıştırın.")

    # Rapor dönemi
    if not REPORT_PERIOD:
        report_period = (
            f"ADS-B Demonstrative Analysis — "
            f"{datetime.now().strftime('%B %Y')}"
        )
    else:
        report_period = REPORT_PERIOD

    # HTML raporu
    gen = ReportGenerator()
    report_result = gen.generate_fleet_report(
        fleet_summary    = summary,
        airline_name     = AIRLINE_NAME,
        reporting_period = report_period,
        output_filename  = f"GreenWing_CaseStudy_{date_str}",
    )

    if report_result.get('status') == 'success':
        size_kb = os.path.getsize(report_result['html_path']) / 1024
        print(f"\n  ✅ Fleet raporu: {report_result['html_path']} ({size_kb:.0f} KB)")
        print(f"     → Tarayıcıda aç → Ctrl+P → PDF")
    else:
        print(f"\n  ❌ Fleet raporu üretimi başarısız")

    # ═══════════════════════════════════════════════════════
    # ADIM 2: CORSIA RAPORU
    # ═══════════════════════════════════════════════════════

    print(f"\n{'─'*65}")
    print(f"  🌍 2. CORSIA Raporu")
    print(f"{'─'*65}")

    corsia = fleet.generate_corsia_report(AIRLINE_NAME, datetime.now().year)
    
    # 🔗 ENTERPRISE: Raporu kriptografik olarak mühürle (Blockchain Sealing)
    sealer = BlockchainSealer()
    corsia = sealer.seal_document(corsia, block_number=501)

    corsia_path = os.path.join(
        REPORTS_CASE_STUDIES, f"corsia_report_{date_str}.json"
    )
    with open(corsia_path, 'w', encoding='utf-8') as f:
        json.dump(corsia, f, indent=2, default=str, ensure_ascii=False)

    es       = corsia.get('emissions_summary', {})
    offsets  = corsia.get('offset_requirements', {})

    print(f"\n  ✅ CORSIA raporu: {corsia_path}")
    print(f"     Durum    : {corsia.get('report_status', 'N/A')}")
    print(f"     CO₂      : {es.get('total_co2_tonnes', 0):.1f} ton")
    print(f"     Baseline : {es.get('baseline_co2_tonnes', 0):.1f} ton")
    print(f"     Offset   : {offsets.get('co2_to_offset_tonnes', 0):.1f} ton "
          f"(~${offsets.get('estimated_offset_cost_usd', 0):,})")

    # ═══════════════════════════════════════════════════════
    # ADIM 3: CASE STUDY ÖZETİ
    # ═══════════════════════════════════════════════════════

    print(f"\n{'─'*65}")
    print(f"  📋 3. Case Study Özetİ")
    print(f"{'─'*65}")

    avg_saving   = float(np.mean([r['total_cost_saving_usd'] for r in results])) if results else 0
    avg_fuel_opt = float(np.mean([r['fuel_optimization_kg'] for r in results])) if results else 0
    avg_annual   = float(np.mean([r['annual_realistic_usd'] for r in results])) if results else 0
    total_co2    = sum(r.get('co2_kg', 0) for r in results)

    airlines = {}
    for r in results:
        code = r.get('airline_code', 'UNK')
        if code not in airlines:
            airlines[code] = []
        airlines[code].append(r)

    flights_with_step = sum(1 for r in results if r.get('step_climb_saving_kg', 0) > 0)
    flights_with_tank = sum(1 for r in results if r.get('tankering_saving_usd', 0) > 0)

    ci_values = [r.get('optimum_ci', 0) for r in results if r.get('optimum_ci', 0) > 0]
    avg_ci    = float(np.mean(ci_values)) if ci_values else 0

    sar_vals = [r.get('sar_loss_pct', 0) for r in results]
    avg_sar  = float(np.mean(sar_vals)) if sar_vals else 0

    case_study = {
        'title'      : 'Aviation Fuel Optimization — Demonstrative Case Study',
        # GÜVENLİK/DOĞRULUK: Alt başlık artık veri kaynağını DİNAMİK olarak yansıtır.
        # Eski sabit "Real ADS-B" ifadesi, batch_results 'demo_simulation' içerdiğinde
        # yanlış beyandı (greenwashing/false advertising riski).
        'subtitle'   : _resolve_data_source_subtitle(results),
        'generated'  : datetime.now().isoformat(),
        'methodology': (
            'OpenSky ADS-B + ICAO ISA Performance Model + '
            '4-Axis Optimization (Altitude, Step Climb, Cost Index, Tankering)'
        ),
        'data_quality': {
            # BÜTÜNLÜK: rapor üreticisi 'quality_grade' okuyordu ama burada
            # 'grade' yazılıyordu → her zaman 'N/A' görünüyordu (sessiz bug).
            'grade'          : quality_report['quality_grade'],
            'quality_grade'  : quality_report['quality_grade'],
            'description'    : quality_report['quality_desc'],
            'quality_desc'   : quality_report['quality_desc'],
            'provenance'     : quality_report.get('provenance'),
            'total_flights'  : quality_report['total'],
            'valid_flights'  : quality_report['valid'],
            'partial_flights': quality_report['partial'],
            'partial_pct'    : quality_report['partial_pct'],
            'recommendations': quality_report.get('recommendations', []),
        },
        'flights_analyzed'  : len(results),
        'airlines_analyzed' : sorted(airlines.keys()),
        'summary': {
            'avg_fuel_saving_per_flight_kg'  : round(avg_fuel_opt),
            'avg_cost_saving_per_flight_usd' : round(avg_saving, 2),
            'avg_annual_realistic_usd'       : round(avg_annual),
            'total_co2_analyzed_kg'          : round(total_co2),
            'annualized_cost_saving_usd'     : sv['annualized_cost_saving_usd'],
            'annualized_fuel_saving_tonnes'  : sv['annualized_fuel_saving_tonnes'],
            'annualized_co2_saving_tonnes'   : sv['annualized_co2_saving_tonnes'],
        },
        'optimization_breakdown': {
            'altitude': {
                'avg_sar_loss_pct': round(avg_sar, 2),
            },
            'step_climb': {
                'flights_with_benefit': flights_with_step,
                'total_flights'       : len(results),
            },
            'cost_index': {
                'avg_optimum_ci': round(avg_ci),
            },
            'tankering': {
                'flights_with_benefit': flights_with_tank,
            },
        },
        'per_flight_details': results,
        'quality_details'   : quality_report['details'],
    }

    case_study_path = os.path.join(
        REPORTS_CASE_STUDIES, f"case_study_{date_str}.json"
    )
    # 🔗 ENTERPRISE: Case Study Raporunu da mühürle
    case_study = sealer.seal_document(case_study, block_number=502)
    with open(case_study_path, 'w', encoding='utf-8') as f:
        json.dump(case_study, f, indent=2, default=str, ensure_ascii=False)

    print(f"\n  ✅ Case study: {case_study_path} (Kriptografik Mühürlü 🔗)")
    
    # 🧬 ENTERPRISE: Kuyruk tesciline özel Dijital İkiz ve Aşınma Kalibrasyon Motorunu çalıştır!
    print(f"\n{'─'*65}")
    print(f"  🧬 4. Kuyruk Bazlı Dijital İkiz ve Aşınma Analizi")
    print(f"{'─'*65}")
    
    calibrator = TailPerformanceCalibrator()
    # DENETİM #54: bu çağrı eskiden demo_mode olmadan yapılıyordu ve
    # faktörler TESCİL HARFİNDEN uyduruluyordu (yayınlanmış
    # fleet_digital_twins_*.json içinde TC-SXS için cd0=1.06 →
    # "AIRFRAME_WASH" önerisi buradan geliyordu).
    # Artık: gerçek uçuş yakıtı varsa ondan kalibre; yoksa faktör
    # ÜRETİLMEZ ve durum açıkça bildirilir.
    twins_results = calibrator.calibrate_fleet_digital_twins(results)

    twins_path = os.path.join(REPORTS_CASE_STUDIES, f"fleet_digital_twins_{date_str}.json")
    with open(twins_path, 'w', encoding='utf-8') as f:
        json.dump(twins_results, f, indent=2, default=str, ensure_ascii=False)

    print(f"\n  ✅ Dijital İkizler Veritabanı: {twins_path}")
    print(f"     Durum: {twins_results['status']} — {twins_results.get('message','')}")
    if twins_results.get('estimated_twins'):
        print(f"     ⚠ {twins_results['estimated_twins']} ikiz DEMO değerleriyle "
              f"(gerçek kalibrasyon DEĞİL)")
    if twins_results.get('insufficient_data_twins'):
        print(f"     ⚠ {twins_results['insufficient_data_twins']} tescil için yeterli "
              f"uçuş verisi yok — faktör üretilmedi")

    if twins_results["status"] in ("SUCCESS", "DEMO"):
        twins = twins_results["digital_twins"]
        print(f"     İşlenen Uçak Sayısı: {len(twins)} adet tescilli uçak")
        for reg, tw in list(twins.items())[:3]:
            cal = tw.get('calibration')
            if not cal:
                print(f"     ✈️ {reg} ({tw['aircraft_type']}) | veri yok — "
                      f"kalibrasyon üretilmedi")
                continue
            print(f"     ✈️ {reg} ({tw['aircraft_type']}) | "
                  f"CD0: {cal['cd0_factor']:.3f} | SFC: {cal['sfc_factor']:.3f} | "
                  f"Öneri: {tw['advisories'][0]['action']}")
    print(f"     Kalite: {quality_report['quality_grade']} — {quality_report['quality_desc']}")
    print(f"     Ort. tasarruf: {round(avg_fuel_opt)} kg / ${round(avg_saving):.0f} / uçuş")
    print(f"     Yıllık: ${sv['annualized_cost_saving_usd']:,}")

    # ═══════════════════════════════════════════════════════
    # ÖZET
    # ═══════════════════════════════════════════════════════

    print(f"\n{'═'*65}")
    print(f"  ✅ TÜM ÇIKTILAR ÜRETİLDİ")
    print(f"{'═'*65}")

    print(f"\n  📁 Üretilen dosyalar:")

    if report_result.get('html_path') and os.path.exists(report_result['html_path']):
        size_kb = os.path.getsize(report_result['html_path']) / 1024
        print(f"\n     📄 {os.path.basename(report_result['html_path'])} ({size_kb:.0f} KB)")
        print(f"        → Tarayıcıda aç → Ctrl+P → PDF")

    if os.path.isdir(REPORTS_CASE_STUDIES):
        print(f"\n     📁 {REPORTS_CASE_STUDIES}/")
        for fname in sorted(os.listdir(REPORTS_CASE_STUDIES)):
            fpath = os.path.join(REPORTS_CASE_STUDIES, fname)
            if os.path.isfile(fpath):
                size = os.path.getsize(fpath)
                icon = (
                    '📊' if fname.startswith('case_study') else
                    '🌍' if fname.startswith('corsia') else
                    '🔍' if fname.startswith('data_quality') else
                    '🧬' if fname.startswith('fleet_digital_twins') else
                    '📄'
                )
                print(f"        {icon} {fname} ({size:,} bytes)")

    rf_pct = round(results[0].get('realization_factor', 0.65) * 100) if results else 65

    print(f"""
  📊 ANALİZ ÖZETİ:
  ─────────────────────────────────────────────────────
  Uçuş sayısı        : {len(results)} ({quality_report['valid']} tam, {quality_report['partial']} partial)
  Veri kalitesi      : {quality_report['quality_grade']} — {quality_report['quality_desc']}
  Ort. tasarruf      : {round(avg_fuel_opt)} kg = ${round(avg_saving):.0f} / uçuş
  Yıllık projeksiyon : ${sv['annualized_cost_saving_usd']:,}
  Yıllık yakıt       : {sv['annualized_fuel_saving_tonnes']} ton
  Yıllık CO₂         : {sv['annualized_co2_saving_tonnes']} ton
  Gerçekleşme faktörü: %{rf_pct}
  ─────────────────────────────────────────────────────

  SONRAKİ ADIMLAR:
  ────────────────
  1. HTML raporu tarayıcıda aç → Ctrl+P → PDF
  2. data_quality_{date_str}.json → veri kalitesini incele
  3. Kalite D/C ise → 01_collect_data.py veya 08_automated_fleet_tracker.py ile taze veri topla
  4. Farklı havayolları için tekrarla

  ⚠ ÖNEMLİ UYARILAR:
  ────────────────────
  • Partial flight verisi → benchmark illustrative only
  • CORSIA değerleri → illustrative estimate (resmi değil)
    """)


# ═══════════════════════════════════════════════════════════
# ÇALIŞTIRMA
# ═══════════════════════════════════════════════════════════

def _resolve_data_source_subtitle(results: list) -> str:
    """
    Vaka çalışması alt başlığını, gerçek veri kaynağına göre belirle.

    Eski davranış: koşulsuz "Based on Real ADS-B Flight Data".
    Yeni davranış: kayıtların collection_method alanına bakılır;
    sentetik/simülasyon verisi varsa bunu AÇIKÇA belirtir.
    """
    methods = {str(r.get("collection_method", "") or "").lower() for r in results}
    methods.discard("")

    real_methods = {"arrivals", "departures", "active_flight", "opensky_adsb"}
    synthetic_markers = {"demo_simulation", "synthetic_fallback", "mock", "simulation"}

    has_synthetic = bool(methods & synthetic_markers) or any(
        "sim" in m or "mock" in m or "demo" in m for m in methods
    )
    has_real = bool(methods & real_methods)

    if has_synthetic and has_real:
        return "Mixed Data: Real ADS-B + Synthetic Simulation (see provenance)"
    if has_synthetic:
        return "Synthetic Simulation Data — Not Real Flight Records"
    if has_real:
        return "Based on Real ADS-B Flight Data (OpenSky Network)"
    return "Data Provenance Undetermined"


if __name__ == "__main__":
    main()
