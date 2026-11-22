"""
GreenWing Analytics — Analiz ve Optimizasyon Scripti
════════════════════════════════════════════════════

Bu script 01_collect_data.py'dan toplanan verileri
analiz eder ve 4 farklı optimizasyon çalıştırır.

NE YAPIYOR:
───────────
    1. data/raw/opensky/ klasöründeki tüm CSV'leri bulur
    2. Her CSV'yi yükler ve veri kalitesini kontrol eder
    3. Origin / destination bilgisini güvenli şekilde çözer
    4. Geçersiz rota kombinasyonlarını filtreler (Sorun 5)
    5. Her CSV'yi analiz eder
    6. 4 optimizasyon çalıştırır:
       a) İrtifa optimizasyonu
       b) Step climb planı
       c) Cost Index optimizasyonu
       d) Tankering analizi
    7. Emisyon hesabı yapar
    8. Sonuçları JSON'a kaydeder

VERİ KALİTESİ FİLTRE KRİTERLERİ:
────────────────────────────────────
    Skip edilecek uçuşlar:
        • MIN_ROWS_REQUIRED'den az waypoint
        • MIN_DISTANCE_NM'den kısa rota
        • MIN_FUEL_KG'dan düşük yakıt (bozuk tahmin)
        • Origin = Destination ve mesafe < 40 Nm
        • Her ikisi de UNK olan rotalar
        • MAX_FUEL_KG_SANITY üzerinde yakıt (mantıksız)

ROTA ÇÖZÜMLEME SIRASI:
──────────────────────
    1. CSV metadata (origin_icao / destination_icao sütunları)
    2. AirportDatabase.resolve_route_endpoints() (koordinat bazlı)
    3. Tek tek identify_airport() (loose fallback)
    4. Havayolu hub heuristic (son çare)

ÇALIŞTIRMA:
───────────
    python scripts/02_analyze_and_optimize.py

GİRDİ:
──────
    data/raw/opensky/*.csv (01_collect_data.py çıktısı)

ÇIKTI:
──────
    reports/optimizations/batch_results.json
"""

import sys
import os
import glob
import json
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.units import Units
from src.utils import (calculate_initial_heading, get_seasonal_wind_estimate,
                        normalize_trajectory_columns)
from src.analysis.flight_analyzer import SingleFlightAnalyzer
from src.analysis.benchmark import ResultBenchmark
from src.optimization.altitude_optimizer import AltitudeOptimizer
from src.optimization.cost_index_optimizer import CostIndexOptimizer
from src.optimization.tankering_optimizer import TankeringOptimizer
from src.models.emission_model import EmissionCalculator
from src.data_collection.airport_database import AirportDatabase
from config.settings import DATA_RAW_OPENSKY, REPORTS_OPTIMIZATIONS
from config.assumptions import Assumptions


# ═══════════════════════════════════════════════════════════
# AYARLAR
# ═══════════════════════════════════════════════════════════

AIRCRAFT_TYPE = 'B738'
CRUISE_MACH   = 0.785
PAYLOAD_KG    = 15000

# Veri kalite filtreleri
MIN_ROWS_REQUIRED   = 10
MIN_DISTANCE_NM     = 50
MIN_FUEL_KG         = 300
MAX_FUEL_KG_SANITY  = 100_000
MIN_ROUTE_NM_SANITY = 40

# Yakıt fiyatları
FUEL_PRICES = {
    'LTFM': 0.78, 'LTFJ': 0.78, 'LTAC': 0.80,
    'LTAI': 0.80, 'LTBJ': 0.80, 'LTFE': 0.80,
    'LTBS': 0.80, 'LTCG': 0.82,

    'EGLL': 1.05, 'EGKK': 1.03, 'EDDF': 0.95,
    'EDDM': 0.94, 'LFPG': 0.98, 'EHAM': 0.92,
    'LEMD': 0.88, 'LIRF': 0.90, 'LOWW': 0.90,
    'LSZH': 0.95, 'LSGG': 0.93, 'EKCH': 0.93,
    'ENGM': 0.98,

    'OMDB': 0.58, 'OMDW': 0.57, 'OEJN': 0.50,
    'OERK': 0.52, 'OTHH': 0.52, 'OBBI': 0.55,
    'OKBK': 0.54, 'OOMS': 0.60,

    'KJFK': 0.88, 'KLAX': 0.85, 'KORD': 0.82, 'CYYZ': 0.83,

    'VHHH': 0.95, 'RJTT': 0.90, 'WSSS': 0.82,
    'VIDP': 0.75, 'VABB': 0.78,

    'HAAB': 1.10, 'HKJK': 1.25, 'DNMM': 1.20,

    'UBBB': 0.60, 'UACC': 0.65, 'UGGG': 0.72, 'UTTT': 0.68,

    'DEFAULT': 0.85,
}

# Havayolu hub'ları (route resolution fallback)
AIRLINE_HUBS = {
    'PGT': 'LTFM', 'THY': 'LTFM', 'TK' : 'LTFM',
    'SXS': 'LTAI', 'FDB': 'OMDB', 'ABY': 'OMDB',
    'JAZ': 'OKBK', 'RWD': 'HAAB',
}

# Havayolu prefix → varsayılan uçak tipi
AIRLINE_DEFAULT_AC = {
    'PGT': 'B738', 'THY': 'B738', 'TK' : 'B738',
    'SXS': 'B738', 'FDB': 'B738', 'ABY': 'A320',
    'JAZ': 'A320', 'RWD': 'B738',
}


# ═══════════════════════════════════════════════════════════
# YARDIMCI FONKSIYONLAR
# ═══════════════════════════════════════════════════════════

def _safe_str(value, default='') -> str:
    if value is None:
        return default
    return str(value).strip()


def _normalize_airport_code(code: str) -> str:
    """ICAO kodunu normalize et. Geçersizse boş döndür."""
    if not code:
        return ''
    code = str(code).strip().upper()
    if code in {'UNK', 'UNKN', 'NONE', 'N/A', 'NAN', ''}:
        return ''
    return code


def _is_valid_icao(code: str) -> bool:
    """
    Geçerli ICAO havalimanı kodu mu?

    Kurallar:
        • 3-4 karakter
        • Yalnızca harf ve rakam
        • Büyük harf

    'UNK' geçerli sayılır (bilinmiyor işareti).
    """
    if not code:
        return False
    if code in ('UNK', 'UNKN'):
        return True
    return (
        len(code) in (3, 4) and
        code.isalnum() and
        code == code.upper()
    )


def infer_aircraft_type(callsign: str, fallback: str = AIRCRAFT_TYPE) -> str:
    """Callsign prefix'inden uçak tipi tahmini."""
    if not callsign:
        return fallback
    prefix3 = callsign[:3]
    prefix2 = callsign[:2]
    return AIRLINE_DEFAULT_AC.get(
        prefix3,
        AIRLINE_DEFAULT_AC.get(prefix2, fallback)
    )


def resolve_airports(
    df: pd.DataFrame,
    callsign: str,
    airport_db: AirportDatabase,
) -> dict:
    """
    Origin / destination çözümleme.

    Öncelik:
        1. CSV metadata (origin_icao / destination_icao sütunları)
        2. resolve_route_endpoints() (koordinat bazlı)
        3. identify_airport() loose fallback
        4. Havayolu hub heuristic
    """
    warnings = []

    # ─── 1) Metadata ──────────────────────────────────────
    origin_meta = ''
    dest_meta   = ''

    if 'origin_icao' in df.columns and len(df) > 0:
        origin_meta = _normalize_airport_code(
            _safe_str(df['origin_icao'].iloc[0])
        )
    if 'destination_icao' in df.columns and len(df) > 0:
        dest_meta = _normalize_airport_code(
            _safe_str(df['destination_icao'].iloc[0])
        )

    # Metadata kaliteli ve farklıysa direkt kullan
    if origin_meta and dest_meta and origin_meta != dest_meta:
        return {
            'origin_icao'    : origin_meta,
            'destination_icao': dest_meta,
            'route_validity' : 'HIGH',
            'route_warnings' : [],
            'source'         : 'trajectory_metadata',
        }

    # ─── Koordinatlar ─────────────────────────────────────
    if (
        'latitude' not in df.columns or
        'longitude' not in df.columns or
        len(df) < 2
    ):
        origin_icao = origin_meta or ''
        dest_icao   = dest_meta or ''
        if not origin_icao and callsign:
            origin_icao = AIRLINE_HUBS.get(
                callsign[:3], AIRLINE_HUBS.get(callsign[:2], '')
            )
        return {
            'origin_icao'    : origin_icao or 'UNK',
            'destination_icao': dest_icao or 'UNK',
            'route_validity' : 'LOW',
            'route_warnings' : ['Koordinat sütunları eksik'],
            'source'         : 'fallback_metadata_only',
        }

    geo = df[['latitude', 'longitude']].copy()
    geo['latitude']  = pd.to_numeric(geo['latitude'], errors='coerce')
    geo['longitude'] = pd.to_numeric(geo['longitude'], errors='coerce')
    geo = geo.dropna()

    if len(geo) < 2:
        origin_icao = origin_meta or ''
        dest_icao   = dest_meta or ''
        if not origin_icao and callsign:
            origin_icao = AIRLINE_HUBS.get(
                callsign[:3], AIRLINE_HUBS.get(callsign[:2], '')
            )
        return {
            'origin_icao'    : origin_icao or 'UNK',
            'destination_icao': dest_icao or 'UNK',
            'route_validity' : 'LOW',
            'route_warnings' : ['Geçerli koordinat yetersiz'],
            'source'         : 'fallback_after_invalid_geo',
        }

    origin_lat = float(geo.iloc[0]['latitude'])
    origin_lon = float(geo.iloc[0]['longitude'])
    dest_lat   = float(geo.iloc[-1]['latitude'])
    dest_lon   = float(geo.iloc[-1]['longitude'])

    # ─── 2) Route endpoint çözümleme ─────────────────────
    route_info = airport_db.resolve_route_endpoints(
        origin_lat=origin_lat, origin_lon=origin_lon,
        dest_lat=dest_lat,     dest_lon=dest_lon,
    )

    if route_info['warnings']:
        warnings.extend(route_info['warnings'])

    origin_res = route_info.get('origin')
    dest_res   = route_info.get('destination')

    origin_icao = origin_res['icao'] if origin_res else ''
    dest_icao   = dest_res['icao'] if dest_res else ''

    # Metadata çapraz doğrulama
    if origin_meta and not origin_icao:
        origin_icao = origin_meta
        warnings.append("Origin metadata'dan alındı")
    if dest_meta and not dest_icao:
        dest_icao = dest_meta
        warnings.append("Destination metadata'dan alındı")

    # ─── 3) Loose fallback ────────────────────────────────
    if not origin_icao:
        g = airport_db.identify_airport(
            origin_lat, origin_lon, max_distance_nm=25, min_confidence='LOW'
        )
        if g:
            origin_icao = g['icao']
            warnings.append("Origin loose fallback")

    if not dest_icao:
        g = airport_db.identify_airport(
            dest_lat, dest_lon, max_distance_nm=25, min_confidence='LOW'
        )
        if g:
            dest_icao = g['icao']
            warnings.append("Destination loose fallback")

    # ─── 4) Hub heuristic ─────────────────────────────────
    hub = AIRLINE_HUBS.get(callsign[:3], AIRLINE_HUBS.get(callsign[:2], ''))
    if not origin_icao and hub:
        origin_icao = hub
        warnings.append(f"Origin hub'dan tahmin: {hub}")

    if not origin_icao:
        origin_icao = 'UNK'
    if not dest_icao:
        dest_icao = 'UNK'

    # ICAO format düzeltmesi
    if not _is_valid_icao(origin_icao):
        warnings.append(f"Geçersiz origin format: '{origin_icao}' → UNK")
        origin_icao = 'UNK'
    if not _is_valid_icao(dest_icao):
        warnings.append(f"Geçersiz dest format: '{dest_icao}' → UNK")
        dest_icao = 'UNK'

    # Validity
    if origin_icao != 'UNK' and dest_icao != 'UNK':
        validity = 'HIGH' if not warnings else 'MEDIUM'
    elif origin_icao != 'UNK' or dest_icao != 'UNK':
        validity = 'LOW'
    else:
        validity = 'LOW'

    return {
        'origin_icao'    : origin_icao,
        'destination_icao': dest_icao,
        'route_validity' : validity,
        'route_warnings' : warnings,
        'source'         : 'resolved_endpoints',
    }


def assess_flight_data_quality(
    df: pd.DataFrame,
    estimated_fuel_kg: float,
    distance_nm: float,
    collection_method: str,
    destination_icao: str,
    aircraft_type: str,
) -> dict:
    """Veri kalitesi değerlendirmesi."""
    warnings       = []
    partial_score  = 0

    fuel_per_nm = estimated_fuel_kg / max(distance_nm, 1.0)

    thresholds = {
        'B738': 5.5, 'B38M': 4.8, 'A320': 5.2, 'A20N': 4.5,
        'A321': 5.8, 'A21N': 5.2, 'B77W': 18.0, 'B788': 12.0,
        'B789': 12.0, 'A350': 12.0, 'A380': 22.0,
    }
    threshold = thresholds.get(aircraft_type, 5.0)

    if collection_method in ('active_flight', 'unknown'):
        partial_score += 2
        warnings.append("Aktif uçuş verisi — partial trajectory riski")

    if destination_icao == 'UNK':
        partial_score += 2
        warnings.append("Varış havalimanı çözülemedi")

    if fuel_per_nm < threshold:
        partial_score += 2
        warnings.append(
            f"Yakıt/Nm düşük: {fuel_per_nm:.2f} < {threshold:.2f}"
        )

    if estimated_fuel_kg < MIN_FUEL_KG:
        partial_score += 2
        warnings.append(f"Yakıt çok düşük: {estimated_fuel_kg:.0f} kg")

    if partial_score >= 4:
        grade      = 'PARTIAL'
        is_partial = True
    elif partial_score >= 2:
        grade      = 'LOW_CONFIDENCE'
        is_partial = True
    else:
        grade      = 'GOOD'
        is_partial = False
        warnings   = warnings or ['Kalite kontrolleri geçti']

    return {
        'is_partial'   : is_partial,
        'quality_grade': grade,
        'warnings'     : warnings,
        'fuel_per_nm'  : round(fuel_per_nm, 3),
        'threshold'    : threshold,
    }


# ═══════════════════════════════════════════════════════════
# ANA FONKSİYON
# ═══════════════════════════════════════════════════════════

def main():
    """Ana analiz ve optimizasyon fonksiyonu."""

    print("\n" + "=" * 65)
    print(f"  GreenWing Analytics — Analiz ve Optimizasyon")
    print(f"  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)

    print(f"""
  FİLTRE KRİTERLERİ:
  ─────────────────────────────────────────────────────────
  Min waypoint    : {MIN_ROWS_REQUIRED}
  Min mesafe      : {MIN_DISTANCE_NM} Nm
  Min yakıt       : {MIN_FUEL_KG} kg
  Max yakıt       : {MAX_FUEL_KG_SANITY:,} kg
  Origin=Dest     : {MIN_ROUTE_NM_SANITY} Nm altında → atla
  Her ikisi UNK   : → atla
  Geçersiz ICAO   : → UNK'a çevir
  ─────────────────────────────────────────────────────────
    """)

    # ─── CSV'leri bul ─────────────────────────────────────
    csv_files = sorted(glob.glob(os.path.join(DATA_RAW_OPENSKY, "*.csv")))

    if not csv_files:
        print(f"\n  ❌ {DATA_RAW_OPENSKY} içinde CSV bulunamadı!")
        print(f"  Önce çalıştır: python scripts/01_collect_data.py")
        return

    print(f"\n  📁 {len(csv_files)} CSV dosyası bulundu")

    # ─── Araçlar ──────────────────────────────────────────
    airport_db = AirportDatabase()
    benchmark  = ResultBenchmark()
    em_calc    = EmissionCalculator()

    all_results     = []
    processed_count = 0
    skipped_count   = 0
    skip_reasons    = {}

    # ─── Her CSV ──────────────────────────────────────────
    for csv_path in csv_files:
        filename = os.path.basename(csv_path)

        print(f"\n{'─'*65}")
        print(f"  📊 {filename}")
        print(f"{'─'*65}")

        try:
            # ─── Veri yükle ───────────────────────────────
            df = pd.read_csv(csv_path)
            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'], errors='coerce')

            # ─── Kontrol 1: Yeterli waypoint ──────────────
            if len(df) < MIN_ROWS_REQUIRED:
                reason = f"Yetersiz waypoint ({len(df)} < {MIN_ROWS_REQUIRED})"
                print(f"  ⚠ {reason}, atlanıyor")
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                skipped_count += 1
                continue

            # ─── Callsign ─────────────────────────────────
            callsign = ''
            if 'callsign' in df.columns and len(df) > 0:
                cs = df.iloc[0].get('callsign', '')
                if isinstance(cs, str):
                    callsign = cs.strip()

            if not callsign:
                parts     = filename.replace('.csv', '').split('_')
                candidate = ''
                for p in parts:
                    if len(p) >= 4 and any(c.isdigit() for c in p):
                        candidate = p
                        break
                callsign = candidate or 'UNK'

            airline_code  = callsign[:3] if len(callsign) >= 3 else 'UNK'
            if callsign.startswith('TK'):
                airline_code = 'THY'

            aircraft_type = infer_aircraft_type(callsign, AIRCRAFT_TYPE)
            time_cost     = Assumptions.time_cost(airline_code)

            # ─── Rota çözümleme ───────────────────────────
            route_info  = resolve_airports(df, callsign, airport_db)
            origin_icao = route_info['origin_icao']
            dest_icao   = route_info['destination_icao']

            print(f"  ✈ {callsign} | Airline: {airline_code} | AC: {aircraft_type}")
            print(f"  🛫 Route: {origin_icao}→{dest_icao} | validity={route_info['route_validity']}")

            if route_info['route_warnings']:
                for w in route_info['route_warnings'][:2]:
                    print(f"     ⚠ {w}")

            # ─── Kontrol 2: UNK-UNK → atla ────────────────
            if origin_icao == 'UNK' and dest_icao == 'UNK':
                reason = "Origin ve destination her ikisi de UNK"
                print(f"  ⚠ {reason}, atlanıyor")
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                skipped_count += 1
                continue

            # ─── Analiz ───────────────────────────────────
            analyzer = SingleFlightAnalyzer(aircraft_type)
            analysis = analyzer.analyze_trajectory(df)

            if analysis is None:
                reason = "SingleFlightAnalyzer başarısız"
                print(f"  ⚠ {reason}, atlanıyor")
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                skipped_count += 1
                continue

            basic    = analysis['basic_metrics']
            fuel     = analysis['fuel_analysis']
            alt_info = analysis['altitude_analysis']

            basic['origin_icao']      = origin_icao
            basic['destination_icao'] = dest_icao

            distance       = float(basic.get('great_circle_distance_nm', 0))
            estimated_fuel = float(fuel.get('estimated_total_fuel_kg', 0))
            cruise_alt     = float(alt_info.get('avg_cruise_altitude_ft', 35000))
            heading        = float(basic.get('heading_deg', 310))

            # ─── Kontrol 3: Kısa mesafe ───────────────────
            if distance < MIN_DISTANCE_NM:
                reason = f"Mesafe çok kısa ({distance:.0f} Nm)"
                print(f"  ⚠ {reason}, atlanıyor")
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                skipped_count += 1
                continue

            # ─── Kontrol 4: Yakıt mantıksız ───────────────
            if estimated_fuel < MIN_FUEL_KG:
                reason = f"Yakıt çok düşük ({estimated_fuel:.0f} kg)"
                print(f"  ⚠ {reason}, atlanıyor")
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                skipped_count += 1
                continue

            if estimated_fuel > MAX_FUEL_KG_SANITY:
                reason = f"Yakıt mantıksız yüksek ({estimated_fuel:.0f} kg)"
                print(f"  ⚠ {reason}, atlanıyor")
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                skipped_count += 1
                continue

            # ─── Kontrol 5: Origin = Destination (Sorun 5) ─
            if origin_icao == dest_icao and origin_icao != 'UNK':
                same_dist = airport_db.get_distance(origin_icao, dest_icao) or 0
                if same_dist < MIN_ROUTE_NM_SANITY:
                    reason = f"Origin = Destination ({origin_icao}) ve mesafe < {MIN_ROUTE_NM_SANITY} Nm"
                    print(f"  ⚠ {reason}, atlanıyor")
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                    skipped_count += 1
                    continue
                else:
                    print(
                        f"  ⚠ Origin = Destination ({origin_icao}) ama uç nokta "
                        f"mesafesi {distance:.0f} Nm → devam ediliyor (suspicious flag)"
                    )

            # ─── collection_method ────────────────────────
            collection_method = _safe_str(
                df['collection_method'].iloc[0], ''
            ) if 'collection_method' in df.columns and len(df) > 0 else 'unknown'

            print(f"  📏 Mesafe: {distance:.0f} Nm | Heading: {heading:.0f}°")
            print(f"  ⛽ Yakıt: {estimated_fuel:,.0f} kg | FL: {cruise_alt/100:.0f}")
            print(f"  📡 Method: {collection_method}")

            # ─── Ağırlık ──────────────────────────────────
            oew = Assumptions.aircraft_oew(aircraft_type)
            estimated_weight = min(
                oew + PAYLOAD_KG + estimated_fuel,
                Assumptions.aircraft_mtow(aircraft_type)
            )
            mid_weight = estimated_weight - estimated_fuel * 0.5

            # ─── Rüzgar ───────────────────────────────────
            has_real_wind = (
                'wind_speed_kts' in df.columns 
                and 'wind_direction_deg' in df.columns
                and df['wind_speed_kts'].notna().sum() > 5
            )
            
            if has_real_wind:
                # Gerçek rüzgar verisi var, bunları irtifa seviyelerine göre grupla
                wind_source = "Canlı Uçak Sensör Kaydı (ADS-B)"
                wind_estimate = {}
                altitudes = [30000, 32000, 34000, 36000, 38000, 40000]
                
                # Uçuş boyunca her satır için rüzgar baş rüzgarı bileşenini hesapla:
                # ws * cos(rad(wd - heading))
                # Pozitif: headwind, Negatif: tailwind (kodumuzun standardı)
                # Not: ADSB.lol'den gelen wd rüzgarın estiği yön (direction from).
                import math
                df_clean = df[df['wind_speed_kts'].notna() & df['wind_direction_deg'].notna() & (df['baro_altitude'] > 10000)]
                
                if len(df_clean) > 0:
                    for alt in altitudes:
                        # Bu irtifaya en yakın verileri bul (+- 1500 ft)
                        subset = df_clean[abs(df_clean['baro_altitude'] - alt) <= 1500]
                        if len(subset) > 0:
                            ws = subset['wind_speed_kts'].mean()
                            wd = subset['wind_direction_deg'].mean()
                            # Headwind component
                            rad_diff = math.radians(wd - heading)
                            headwind = ws * math.cos(rad_diff)
                            wind_estimate[alt] = int(headwind)
                        else:
                            # Yoksa mevsimselden doldur
                            wind_estimate[alt] = get_seasonal_wind_estimate(heading).get(alt, 0)
                else:
                    wind_estimate = get_seasonal_wind_estimate(heading)
            else:
                wind_estimate = get_seasonal_wind_estimate(heading)
                wind_source = "Mevsimsel Rüzgâr Tahmini (Climatology)"

            print(f"  💨 Rüzgâr: {wind_source} kullanıldı.")

            # ─── OPT 1: İrtifa ────────────────────────────
            alt_opt    = AltitudeOptimizer(aircraft_type)
            opt_alt    = alt_opt.find_optimum_altitude(
                weight_kg=mid_weight,
                mach=CRUISE_MACH,
                heading_deg=heading,
                wind_at_levels=wind_estimate,
            )

            alt_saving    = 0.0
            opt_fl        = "N/A"
            buffet_margin = 0.0
            altitude_deviation_ft = 0.0

            if opt_alt.get('status') == 'SUCCESS':
                opt_fl        = opt_alt['optimum']['flight_level']
                opt_alt_ft    = float(opt_alt['optimum']['altitude_ft'])
                altitude_deviation_ft = abs(cruise_alt - opt_alt_ft)
                buffet_margin = float(opt_alt['optimum']['buffet_margin_pct'])
                fuel_save_1k  = float(
                    opt_alt['vs_fl350'].get('fuel_saving_per_1000nm_kg', 0)
                )
                alt_saving = abs(fuel_save_1k) * distance / 1000
                print(f"  📐 Optimum: {opt_fl} | Buffet: %{buffet_margin:.1f} | Sapma: {altitude_deviation_ft:.0f} ft")

            # ─── OPT 2: Step climb ────────────────────────
            step_saving = 0.0
            step_plan   = []

            if distance > 300:
                step_result = alt_opt.optimize_full_flight(
                    distance_nm=distance,
                    initial_weight_kg=estimated_weight,
                    payload_kg=PAYLOAD_KG,
                    mach=CRUISE_MACH,
                    heading_deg=heading,
                    wind_profile=wind_estimate,
                )
                step_saving = float(
                    step_result.get('savings', {})
                               .get('per_flight', {})
                               .get('fuel_kg', 0)
                )
                step_plan = [
                    {
                        'distance'  : s['distance_nm'],
                        'from'      : s['from_fl'],
                        'to'        : s['to_fl'],
                        'net_saving': s['expected_net_saving_kg'],
                    }
                    for s in step_result.get('scenarios', {})
                                       .get('step_climb', {})
                                       .get('step_plan', [])
                ]
                print(f"  📈 Step climb: {step_saving:.0f} kg")

            # ─── OPT 3: Cost Index ────────────────────────
            origin_price = FUEL_PRICES.get(origin_icao, FUEL_PRICES['DEFAULT'])
            ci_opt       = CostIndexOptimizer(aircraft_type)
            ci_result    = ci_opt.optimize_cost_index(
                distance_nm=distance,
                altitude_ft=cruise_alt,
                weight_kg=mid_weight,
                fuel_price_usd_per_kg=origin_price,
                time_cost_usd_per_hr=time_cost,
            )

            if ci_result.get('status') == 'SUCCESS':
                opt_ci   = int(ci_result['optimum']['cost_index'])
                opt_mach = float(ci_result['optimum']['mach'])
            else:
                opt_ci   = 35
                opt_mach = CRUISE_MACH

            print(f"  ⚡ CI: {opt_ci} | Mach: {opt_mach}")

            # ─── OPT 4: Tankering ─────────────────────────
            dest_price = FUEL_PRICES.get(dest_icao, FUEL_PRICES['DEFAULT'])
            tank_opt   = TankeringOptimizer(aircraft_type)
            tank_result = tank_opt.optimize_tankering(
                distance_nm=distance,
                altitude_ft=cruise_alt,
                mach=CRUISE_MACH,
                weight_without_extra_fuel_kg=estimated_weight,
                fuel_price_origin_usd_per_kg=origin_price,
                fuel_price_dest_usd_per_kg=dest_price,
                max_extra_fuel_kg=3000,
            )

            tank_amount = int(tank_result.get('optimal_extra_fuel_kg', 0))
            tank_saving = float(tank_result.get('net_saving_usd', 0))
            print(f"  ⛽ Tankering: {tank_amount} kg | ${tank_saving:.0f}")

            # ─── Emisyon ──────────────────────────────────
            emissions = em_calc.calculate_flight_emissions(
                fuel_burn_kg=estimated_fuel,
                distance_nm=distance,
                aircraft_type=aircraft_type,
                cruise_altitude_ft=cruise_alt,
                cruise_mach=CRUISE_MACH,
            )
            co2        = float(emissions['emissions']['CO2_kg'])
            co2_pax_km = float(emissions['metrics']['co2_per_pax_km_g'])

            # ─── Toplam tasarruf ──────────────────────────
            # DİKKAT: irtifa ve step-climb AYNI yakıtı iki kez saymamalı,
            # ama max() almak da yanlış — step-climb, optimum irtifaya
            # ULAŞTIKTAN SONRA ek bir kazançtır. Bu yüzden toplanır;
            # alt_saving zaten "mevcut irtifadan optimuma" kazancı,
            # step_saving ise "optimuma çıktıktan sonra ağırlık azaldıkça
            # kademeli yükselme" kazancını temsil eder.
            fuel_optimization = alt_saving + step_saving
            total_cost        = fuel_optimization * origin_price + tank_saving

            # Tasarrufun KAYNAĞINI ayrıştır (panelde gösterilir)
            saving_breakdown = {
                'altitude_kg'  : round(alt_saving, 1),
                'step_climb_kg': round(step_saving, 1),
                'tankering_usd': round(tank_saving, 2),
                'fuel_kg_total' : round(fuel_optimization, 1),
            }
            annual_proj       = Assumptions.annual_projection(total_cost, distance)

            print(f"\n  💰 Tasarruf: {fuel_optimization:.0f} kg = ${total_cost:.0f}/uçuş")
            print(f"  📅 Yıllık: ${annual_proj['realistic_annual_usd']:,}")

            # ─── Veri kalitesi ────────────────────────────
            quality = assess_flight_data_quality(
                df=df,
                estimated_fuel_kg=estimated_fuel,
                distance_nm=distance,
                collection_method=collection_method,
                destination_icao=dest_icao,
                aircraft_type=aircraft_type,
            )

            status_icon = '⚠' if quality['is_partial'] else '✅'
            print(f"  {status_icon} Kalite: {quality['quality_grade']}")

            # ─── Benchmark ────────────────────────────────
            bm_report = benchmark.check_all({
                'sar'               : alt_info.get('sar_at_actual_alt', 0),  # Nm/kg (benchmark birimi)
                'fuel_flow_kg_hr'   : (
                    estimated_fuel / basic['total_flight_time_hr']
                    if basic.get('total_flight_time_hr', 0) > 0 else 0
                ),
                'fuel_kg'           : estimated_fuel,
                'distance_nm'       : distance,
                'co2_per_pax_km_g'  : co2_pax_km,
                'saving_pct'        : (
                    fuel_optimization / estimated_fuel * 100
                ) if estimated_fuel > 0 else 0,
                'annual_saving_usd' : annual_proj['realistic_annual_usd'],
                'aircraft_type'     : aircraft_type,
            })

            # ─── Kayıt ────────────────────────────────────
            flight_result = {
                'filename'               : filename,
                'callsign'               : callsign,
                'airline_code'           : airline_code,
                'aircraft_type'          : aircraft_type,

                # Route
                'origin_airport'         : origin_icao,
                'dest_airport'           : dest_icao,
                'route_validity'         : route_info['route_validity'],
                'route_resolution_source': route_info['source'],
                'route_warnings'         : route_info['route_warnings'],

                # Collection
                'collection_method'      : collection_method,

                # Metrikler
                'distance_nm'            : round(distance),
                'estimated_fuel_kg'      : round(estimated_fuel),
                'cruise_altitude_ft'     : int(cruise_alt),
                'route_efficiency_pct'   : round(basic.get('route_efficiency_pct', 0), 1),
                'heading_deg'            : round(heading),
                'flight_time_min'        : round(basic.get('total_flight_time_min', 0), 1),

                # Altitude / step
                'optimum_fl'             : opt_fl,
                'altitude_deviation_ft'  : round(altitude_deviation_ft),
                'buffet_margin_pct'      : round(buffet_margin, 1),
                'sar_loss_pct'           : round(float(alt_info.get('sar_loss_pct', 0)), 2),
                'altitude_saving_kg'     : round(alt_saving),
                'step_climb_saving_kg'   : round(step_saving),
                'step_plan'              : step_plan,

                # CI
                'optimum_ci'             : opt_ci,
                'optimum_mach'           : round(opt_mach, 3),

                # Tankering
                'tankering_amount_kg'    : tank_amount,
                'tankering_saving_usd'   : round(tank_saving, 2),
                'origin_fuel_price'      : origin_price,
                'dest_fuel_price'        : dest_price,

                # Tasarruf (03 scripti bu alanları kullanır)
                'fuel_optimization_kg'   : round(fuel_optimization),
                'total_cost_saving_usd'  : round(total_cost, 2),
                'saving_breakdown'       : saving_breakdown,
                'annual_raw_usd'         : annual_proj['raw_annual_usd'],
                'annual_realistic_usd'   : annual_proj['realistic_annual_usd'],
                'realization_factor'     : annual_proj['realization_factor'],

                # Emisyon
                'co2_kg'                 : round(co2),
                'co2_per_pax_km_g'       : round(co2_pax_km, 1),

                # Kalite
                'data_quality'           : quality,
                'is_partial_flight'      : quality['is_partial'],
                'fuel_per_nm'            : quality['fuel_per_nm'],

                # Benchmark
                'benchmark_status'       : bm_report.summary(),

                'timestamp'              : datetime.now().isoformat(),
            }

            all_results.append(flight_result)
            processed_count += 1

        except Exception as e:
            print(f"  ❌ Hata: {e}")
            import traceback
            traceback.print_exc()
            skipped_count += 1

    # ─── Özet ─────────────────────────────────────────────
    print(f"\n{'═'*65}")
    print(f"  SONUÇLAR")
    print(f"{'═'*65}")
    print(f"  İşlenen  : {processed_count}")
    print(f"  Atlanan  : {skipped_count}")

    if skip_reasons:
        print(f"\n  Atlama sebepleri:")
        for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
            print(f"     {count}x {reason}")

    if all_results:
        print(f"\n  {'Callsign':<12} {'Route':<15} {'Dist':>6} {'Fuel':>8} "
              f"{'Method':<12} {'Save$':>8} {'Annual':>12}")
        print(f"  {'─'*82}")

        for r in all_results:
            route      = f"{r['origin_airport']}→{r['dest_airport']}"
            method     = r.get('collection_method', 'unknown')
            partial    = " ⚠" if r.get('is_partial_flight', False) else ""
            print(
                f"  {r['callsign']:<12} {route:<15} "
                f"{r['distance_nm']:>4}Nm "
                f"{r['estimated_fuel_kg']:>7,}kg "
                f"{method:<12} "
                f"${r['total_cost_saving_usd']:>6,.0f} "
                f"${r['annual_realistic_usd']:>10,}{partial}"
            )

        # Kısa istatistikler
        avg_saving = float(np.mean([r['total_cost_saving_usd'] for r in all_results]))
        avg_fuel   = float(np.mean([r['fuel_optimization_kg'] for r in all_results]))
        avg_annual = float(np.mean([r['annual_realistic_usd'] for r in all_results]))
        partial_n  = sum(1 for r in all_results if r.get('is_partial_flight', False))
        unk_n      = sum(
            1 for r in all_results
            if 'UNK' in (r.get('origin_airport',''), r.get('dest_airport',''))
        )

        print(f"\n  ÖZET:")
        print(f"  Ort. tasarruf/uçuş : {avg_fuel:.0f} kg = ${avg_saving:.0f}")
        print(f"  Ort. yıllık         : ${avg_annual:,.0f}")
        print(f"  Partial uçuş oranı  : %{partial_n/len(all_results)*100:.0f}")
        print(f"  UNK route alanı     : {unk_n}")

        # ── VERİ KAYNAĞI UYARISI ────────────────────────────
        # Ticari dürüstlük: sentetik ve gerçek veriyi karıştırıp tek
        # sayı vermek yanıltıcıdır. Her çalıştırmada açıkça yaz.
        _methods: dict[str, int] = {}
        for _r in all_results:
            _m = str(_r.get('collection_method') or 'bilinmiyor')
            _methods[_m] = _methods.get(_m, 0) + 1
        _synth = (_methods.get('synthetic_fallback', 0)
                  + _methods.get('demo', 0))
        _real = len(all_results) - _synth - _methods.get('bilinmiyor', 0)
        print(f"  Veri kaynağı        : {dict(sorted(_methods.items()))}")
        if _synth and _real:
            print(f"  ⚠️  KARIŞIK VERİ: {_real} gerçek + {_synth} sentetik.")
            print("      Aşağıdaki $ rakamları MÜŞTERİYE TAAHHÜT EDİLEMEZ.")
        elif _synth:
            print(f"  ⛔ TAMAMEN SENTETİK ({_synth} uçuş) — sadece model/arayüz")
            print("      doğrulaması içindir. Ticari taahhüt için gerçek veri şart.")
        else:
            print(f"  ✅ TAMAMEN GERÇEK VERİ ({_real} uçuş).")

        # JSON
        os.makedirs(REPORTS_OPTIMIZATIONS, exist_ok=True)
        results_path = os.path.join(REPORTS_OPTIMIZATIONS, "batch_results.json")

        with open(results_path, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, indent=2, default=str, ensure_ascii=False)

        print(f"\n  💾 Kaydedildi: {results_path}")
        print(f"\n  ✅ Sonraki adım:")
        print(f"  python scripts/03_generate_outputs.py")

        if partial_n / len(all_results) > 0.3:
            print(f"\n  ⚠ UYARI: Partial oranı yüksek (%{partial_n/len(all_results)*100:.0f})")
            print(f"    Arrivals verisi için 01_collect_data.py yeniden çalıştırılsın.")

    else:
        print("\n  ❌ Hiç sonuç üretilemedi!")


if __name__ == "__main__":
    main()
