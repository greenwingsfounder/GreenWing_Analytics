# scripts/01_collect_data.py

"""
GreenWing Analytics — Veri Toplama Scripti
══════════════════════════════════════════

Bu script OpenSky Network'ten gerçek uçuş verisi toplar.

TEMEL TASARIM KARARI — ARRIVALS (TAMAMLANMIŞ UÇUŞLAR):
────────────────────────────────────────────────────────
Eski yaklaşım: Havadaki aktif uçuşları yakala (YANLIŞ)
    • Trajectory eksik (kalkış/iniş yakalanmıyor)
    • Yakıt düşük hesaplanıyor (partial segment)
    • Varış havalimanı tespit edilemiyor (UNK)
    • Benchmark yanıltıcı çıkıyor

Yeni yaklaşım: Yeni inen (arrivals) uçuşları topla (DOĞRU)
    • Tam gate-to-gate trajectory
    • Gerçekçi yakıt hesabı
    • Varış havalimanı kesin belli
    • Kalkış flights endpoint'ten geliyor

YÖNTEMLER (öncelik sırasıyla):
───────────────────────────────
    1. ARRIVALS (birincil):
       → Son X saatte belirtilen havalimanlarına inen uçuşlar
       → Tam trajectory, UNK yok, yakıt güvenilir

    2. DEPARTURES (ikincil):
       → Belirli havalimanlarından kalkıp trajectory'si
         tamamlanmış uçuşlar

    3. AKTİF UÇUŞLAR (fallback):
       → Sadece yukarıdakiler yetersizse devreye girer
       → Partial olarak işaretlenir, benchmark dışı tutulur

ÇALIŞTIRMA:
───────────
    cd greenWing-analytics
    greenWing_env\\Scripts\\activate
    python scripts/01_collect_data.py

EN İYİ ZAMAN:
─────────────
    10:00-23:00 TR saati
    LTFM arrivals yoğun: 07:00-11:00 ve 16:00-21:00
    EGLL arrivals yoğun: 09:00-14:00 ve 18:00-23:00

ÇIKTI:
──────
    data/raw/opensky/ klasörüne CSV dosyaları:

    ARR_TK1985_EGLL_LTFM_20250520_1430.csv  ← arrivals (tercih)
    DEP_PGT1234_LTFM_20250520_0930.csv      ← departure
    ACT_FDB2MF_20250520_1105.csv            ← aktif (fallback)

    Her dosya şu metadata sütunlarını içerir:
        time, callsign, latitude, longitude,
        baro_altitude, velocity, on_ground,
        origin_icao, destination_icao,
        collection_method, collected_at

SONRAKI ADIM:
─────────────
    python scripts/02_analyze_and_optimize.py
"""

import sys
import os
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data_collection.opensky_collector import OpenSkyCollector
from config.settings import DATA_RAW_OPENSKY


# ═══════════════════════════════════════════════════════════
# AYARLAR
# ═══════════════════════════════════════════════════════════

# ─── Hedef havalimanları (arrivals — birincil) ────────────
# Bu havalimanlarına son X saatte inen uçuşları topla.
# Varış havalimanı kesin belli → UNK sorunu yok.
# SADECE ÇALIŞAN HAVALİMANLARI
ARRIVAL_AIRPORTS = [
    {"icao": "EDDF", "name": "Frankfurt",          "priority": 1},
    {"icao": "EDDM", "name": "Munich",             "priority": 1},
    {"icao": "EHAM", "name": "Amsterdam Schiphol", "priority": 1},
    {"icao": "LEMD", "name": "Madrid Barajas",     "priority": 2},
    {"icao": "LIRF", "name": "Rome Fiumicino",     "priority": 2},
]

# Filtre yok — her havayolu gelsin
TARGET_AIRLINES = []

# Parametreler
ARRIVALS_HOURS_BACK     = 6   # 6 saat geriye bak
MAX_FLIGHTS_PER_AIRPORT = 5   # Her havalimanından 5 uçuş
TARGET_TOTAL_FLIGHTS    = 15  # Toplam 15 hedef

# Fallback'i kapat — partial istemiyoruz
USE_ACTIVE_FALLBACK     = False
USE_DEPARTURE_METHOD    = False
# ─── Toplama parametreleri ────────────────────────────────
ARRIVALS_HOURS_BACK       = 4    # Son kaç saat arrivals bakılacak
MAX_FLIGHTS_PER_AIRPORT   = 5    # Her havalimanından max uçuş
TARGET_TOTAL_FLIGHTS      = 15   # Toplam hedef uçuş sayısı
API_DELAY_S               = 3    # API çağrıları arası bekleme (rate limit)

# ─── Trajectory kalite eşikleri ──────────────────────────
MIN_WAYPOINTS             = 30   # Min waypoint (az = eksik trajectory)
MIN_FLIGHT_DURATION_MIN   = 20   # Min uçuş süresi (dakika)

# ─── Fallback: kalkış bazlı (arrivals yetersizse) ─────────
USE_DEPARTURE_METHOD      = True
DEPARTURE_AIRPORTS        = ["LTFM"]
DEPARTURE_HOURS_BACK      = 3
MAX_DEP_PER_AIRPORT       = 3

# ─── Fallback: aktif uçuşlar (hepsi yetersizse) ───────────
USE_ACTIVE_FALLBACK       = True
ACTIVE_FALLBACK_AIRLINES  = ["PGT", "THY", "SXS"]
MAX_ACTIVE_PER_AIRLINE    = 1
MIN_ALTITUDE_M_ACTIVE     = 8000  # Yüksek irtifa = cruise = daha iyi trajectory


# ═══════════════════════════════════════════════════════════
# YARDIMCI: TRAJECTORY KALİTE KONTROLÜ
# ═══════════════════════════════════════════════════════════

def check_trajectory_quality(traj, callsign: str = '') -> dict:
    """
    Trajectory'nin kalitesini değerlendir.

    Kontroller:
        1. Minimum waypoint sayısı
        2. Minimum uçuş süresi
        3. Cruise irtifasına ulaşmış mı?
        4. Yer seviyesi veri var mı?

    Returns:
        dict:
            is_quality     : Kullanılabilir mi?
            confidence     : 'HIGH' / 'MEDIUM' / 'LOW'
            recommendation : 'USE' / 'USE_WITH_WARNING' / 'SKIP'
            issues         : Sorun listesi
            metrics        : waypoints, duration_min, max_alt_ft
    """
    import numpy as np
    import pandas as pd

    issues     = []
    quality_ok = True
    confidence = 'HIGH'

    n_points = len(traj)

    # ─── Waypoint sayısı ──────────────────────────────────
    if n_points < MIN_WAYPOINTS:
        issues.append(f"Az waypoint: {n_points} < {MIN_WAYPOINTS}")
        confidence = 'LOW'
        if n_points < 10:
            quality_ok = False

    # ─── Uçuş süresi ──────────────────────────────────────
    duration_min = 0
    if 'time' in traj.columns:
        try:
            times = pd.to_datetime(traj['time'], errors='coerce').dropna()
            if len(times) >= 2:
                duration_min = (
                    times.max() - times.min()
                ).total_seconds() / 60
                if duration_min < MIN_FLIGHT_DURATION_MIN:
                    issues.append(
                        f"Kısa süre: {duration_min:.0f} dk < "
                        f"{MIN_FLIGHT_DURATION_MIN} dk"
                    )
                    confidence = 'MEDIUM' if confidence == 'HIGH' else confidence
        except Exception:
            issues.append("Zaman parse hatası")

    # ─── İrtifa profili ───────────────────────────────────
    max_alt_ft = 0
    has_cruise = False
    has_ground = False

    alt_col = None
    for col in ['baro_altitude', 'baro_altitude_m', 'baro_altitude_ft']:
        if col in traj.columns:
            alt_col = col
            break

    if alt_col:
        import pandas as pd
        alt_vals = pd.to_numeric(traj[alt_col], errors='coerce').dropna()
        if len(alt_vals) > 0:
            max_alt_raw = float(alt_vals.max())
            min_alt_raw = float(alt_vals.min())

            # Metre/feet tespiti
            if max_alt_raw > 20000:
                max_alt_ft = max_alt_raw
                min_alt_ft = min_alt_raw
            else:
                max_alt_ft = max_alt_raw * 3.28084
                min_alt_ft = min_alt_raw * 3.28084

            has_cruise = max_alt_ft > 15000
            has_ground = min_alt_ft < 2000

            if not has_cruise:
                issues.append(
                    f"Cruise irtifasına ulaşmamış: max {max_alt_ft:.0f} ft"
                )
                confidence = 'LOW'
                quality_ok = False

            if not has_ground:
                issues.append(
                    "Yer seviyesi veri yok — muhtemelen sadece cruise"
                )
                confidence = 'MEDIUM' if confidence == 'HIGH' else confidence
    else:
        issues.append("İrtifa sütunu bulunamadı")
        confidence = 'LOW'

    # ─── on_ground ────────────────────────────────────────
    if 'on_ground' in traj.columns:
        if traj['on_ground'].astype(bool).any():
            has_ground = True

    # ─── Öneri ────────────────────────────────────────────
    if not quality_ok:
        recommendation = 'SKIP'
    elif confidence == 'LOW' or issues:
        recommendation = 'USE_WITH_WARNING'
    else:
        recommendation = 'USE'

    return {
        'is_quality'    : quality_ok,
        'confidence'    : confidence,
        'recommendation': recommendation,
        'issues'        : issues,
        'metrics': {
            'waypoints'   : n_points,
            'duration_min': round(duration_min, 1),
            'max_alt_ft'  : round(max_alt_ft),
            'has_ground'  : has_ground,
            'has_cruise'  : has_cruise,
        },
    }


# ═══════════════════════════════════════════════════════════
# ANA FONKSİYON
# ═══════════════════════════════════════════════════════════

def main():
    """Ana veri toplama fonksiyonu."""

    print("\n" + "=" * 65)
    print(f"  GreenWing Analytics — Veri Toplama (Arrivals Yöntemi)")
    print(f"  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)

    print(f"""
  TOPLAMA STRATEJİSİ:
  ─────────────────────────────────────────────────────────
  Birincil  : Arrivals (son {ARRIVALS_HOURS_BACK} saat) → Tam trajectory ✅
  İkincil   : Departures (son {DEPARTURE_HOURS_BACK} saat) → Yaklaşık tam
  Fallback  : Aktif uçuşlar → Partial ⚠ (sadece yetmezse)
  ─────────────────────────────────────────────────────────
  Hedef     : {TARGET_TOTAL_FLIGHTS} uçuş
  Havalimanı: {', '.join(a['icao'] for a in ARRIVAL_AIRPORTS)}
  Havayolları: {', '.join(TARGET_AIRLINES)}
    """)

    # ─── Kayıt klasörü ────────────────────────────────────
    os.makedirs(DATA_RAW_OPENSKY, exist_ok=True)

    # ─── Collector ────────────────────────────────────────
    collector = OpenSkyCollector()
    status    = collector.status()

    print(f"  API: {'✅ Kimlik doğrulamalı' if status['authenticated'] else '⚠ Anonim'}")
    print(f"  Günlük limit: {status['daily_limit']} çağrı")

    if not status['authenticated']:
        print(f"""
  💡 Öneri: .env dosyasına OpenSky hesabı ekle:
     OPENSKY_USERNAME=kullanici_adin
     OPENSKY_PASSWORD=sifren
     (opensky-network.org — ücretsiz kayıt)
    """)

    total_saved     = 0
    saved_files     = []
    saved_callsigns = set()

    stats = {
        'arrivals_found'  : 0,
        'arrivals_saved'  : 0,
        'departures_found': 0,
        'departures_saved': 0,
        'active_found'    : 0,
        'active_saved'    : 0,
        'quality_skip'    : 0,
        'duplicate_skip'  : 0,
    }

    # ═══════════════════════════════════════════════════════
    # YÖNTEM 1: ARRIVALS (BİRİNCİL)
    # ═══════════════════════════════════════════════════════

    print(f"\n{'═'*65}")
    print(f"  📥 YÖNTEM 1: ARRIVALS (Son {ARRIVALS_HOURS_BACK} Saat)")
    print(f"{'═'*65}")
    print(f"  Bu yöntem tam gate-to-gate trajectory üretir.")
    print(f"  Varış havalimanı kesin, yakıt hesabı güvenilir.\n")

    for airport_info in sorted(ARRIVAL_AIRPORTS, key=lambda x: x['priority']):
        if total_saved >= TARGET_TOTAL_FLIGHTS:
            print(f"  ✅ Hedef {TARGET_TOTAL_FLIGHTS} uçuşa ulaşıldı, durduruluyor.")
            break

        airport_icao = airport_info['icao']
        airport_name = airport_info['name']

        print(f"  {'─'*60}")
        print(f"  📡 {airport_name} ({airport_icao}) taranıyor...")
        print(f"  {'─'*60}")

        try:
            trajectories = collector.collect_arrival_trajectories(
                airport_icao          = airport_icao,
                airline_filter        = TARGET_AIRLINES if TARGET_AIRLINES else None,
                hours_back            = ARRIVALS_HOURS_BACK,
                max_flights           = MAX_FLIGHTS_PER_AIRPORT,
                min_waypoints         = MIN_WAYPOINTS,
                delay_between_calls_s = API_DELAY_S,
            )

            if not trajectories:
                print(f"  ⚠ {airport_name}: Uygun arrival bulunamadı")
                time.sleep(1)
                continue

            stats['arrivals_found'] += len(trajectories)

            for traj in trajectories:
                # Callsign al
                callsign = ''
                if 'callsign' in traj.columns and len(traj) > 0:
                    cs = traj['callsign'].iloc[0]
                    if isinstance(cs, str):
                        callsign = cs.strip()

                # Duplicate kontrolü
                if callsign and callsign in saved_callsigns:
                    print(f"    ℹ {callsign}: zaten kaydedilmiş, atlanıyor")
                    stats['duplicate_skip'] += 1
                    continue

                # Kalite kontrolü
                quality = check_trajectory_quality(traj, callsign)

                if quality['recommendation'] == 'SKIP':
                    print(
                        f"    ❌ {callsign or '?'}: Kalite yetersiz → "
                        f"{', '.join(quality['issues'][:2])}"
                    )
                    stats['quality_skip'] += 1
                    continue

                # Kaydet
                dest_icao = ''
                if 'destination_icao' in traj.columns:
                    dest_icao = str(traj['destination_icao'].iloc[0]).strip()

                origin_icao = ''
                if 'origin_icao' in traj.columns:
                    origin_icao = str(traj['origin_icao'].iloc[0]).strip()

                prefix   = f"ARR_{callsign[:3] if len(callsign) >= 3 else 'UNK'}"
                filepath = OpenSkyCollector.save_trajectory(
                    traj, DATA_RAW_OPENSKY, prefix=prefix
                )
                filename = os.path.basename(filepath)
                saved_files.append(filename)
                saved_callsigns.add(callsign)
                total_saved += 1
                stats['arrivals_saved'] += 1

                quality_tag = (
                    ' [⚠ partial]'
                    if quality['recommendation'] == 'USE_WITH_WARNING'
                    else ' [✅ tam]'
                )

                print(
                    f"    ✅ {callsign or '?':<12} "
                    f"{origin_icao or '?'}→{dest_icao or airport_icao} "
                    f"[{quality['metrics']['waypoints']} pts, "
                    f"{quality['metrics']['duration_min']:.0f}dk, "
                    f"FL{quality['metrics']['max_alt_ft']//100:.0f}]"
                    f"{quality_tag}"
                )

                if total_saved >= TARGET_TOTAL_FLIGHTS:
                    break

        except AttributeError:
            print(f"  ⚠ collect_arrival_trajectories() bulunamadı")
            print(f"    → opensky_collector.py güncellendi mi? Kontrol et.")
            break

        except Exception as e:
            print(f"  ❌ {airport_name} hatası: {e}")

        time.sleep(API_DELAY_S)

    print(f"\n  Arrivals sonucu: {stats['arrivals_saved']} uçuş kaydedildi")

    # ═══════════════════════════════════════════════════════
    # YÖNTEM 2: DEPARTURES (İKİNCİL)
    # ═══════════════════════════════════════════════════════

    if USE_DEPARTURE_METHOD and total_saved < TARGET_TOTAL_FLIGHTS:
        print(f"\n{'═'*65}")
        print(f"  📤 YÖNTEM 2: DEPARTURES (Son {DEPARTURE_HOURS_BACK} Saat)")
        print(f"{'═'*65}")
        print(f"  Kalkış uçuşları — tamamlanmış trajectory tercih edilir.\n")

        for airport_icao in DEPARTURE_AIRPORTS:
            if total_saved >= TARGET_TOTAL_FLIGHTS:
                break

            print(f"  {'─'*60}")
            print(f"  📡 {airport_icao} kalkışları taranıyor...")
            print(f"  {'─'*60}")

            try:
                trajectories = collector.collect_departure_trajectories(
                    airport_icao          = airport_icao,
                    airline_icao          = None,
                    hours_back            = DEPARTURE_HOURS_BACK,
                    max_flights           = MAX_DEP_PER_AIRPORT,
                    delay_between_calls_s = API_DELAY_S,
                )

                if not trajectories:
                    print(f"  ⚠ {airport_icao}: Kalkış verisi bulunamadı")
                    continue

                stats['departures_found'] += len(trajectories)

                for traj in trajectories:
                    callsign = ''
                    if 'callsign' in traj.columns and len(traj) > 0:
                        cs = traj['callsign'].iloc[0]
                        if isinstance(cs, str):
                            callsign = cs.strip()

                    if callsign and callsign in saved_callsigns:
                        stats['duplicate_skip'] += 1
                        continue

                    # Havayolu filtresi
                    if TARGET_AIRLINES:
                        prefix3 = callsign[:3] if len(callsign) >= 3 else ''
                        prefix2 = callsign[:2] if len(callsign) >= 2 else ''
                        if (
                            prefix3 not in TARGET_AIRLINES and
                            prefix2 not in TARGET_AIRLINES
                        ):
                            continue

                    # Kalite kontrolü
                    quality = check_trajectory_quality(traj, callsign)

                    if quality['recommendation'] == 'SKIP':
                        print(
                            f"    ❌ {callsign or '?'}: "
                            f"{', '.join(quality['issues'][:1])}"
                        )
                        stats['quality_skip'] += 1
                        continue

                    prefix   = f"DEP_{callsign[:3] if len(callsign) >= 3 else 'UNK'}"
                    filepath = OpenSkyCollector.save_trajectory(
                        traj, DATA_RAW_OPENSKY, prefix=prefix
                    )
                    filename = os.path.basename(filepath)
                    saved_files.append(filename)
                    saved_callsigns.add(callsign)
                    total_saved += 1
                    stats['departures_saved'] += 1

                    partial_note = (
                        ' [⚠ varış belirsiz]'
                        if quality['recommendation'] == 'USE_WITH_WARNING'
                        else ''
                    )

                    print(
                        f"    ✅ {callsign or '?':<12} "
                        f"{airport_icao}→? "
                        f"[{quality['metrics']['waypoints']} pts, "
                        f"{quality['metrics']['duration_min']:.0f}dk]"
                        f"{partial_note}"
                    )

                    if total_saved >= TARGET_TOTAL_FLIGHTS:
                        break

            except Exception as e:
                print(f"  ❌ {airport_icao} departure hatası: {e}")

            time.sleep(API_DELAY_S)

        print(f"\n  Departures sonucu: {stats['departures_saved']} uçuş kaydedildi")

    # ═══════════════════════════════════════════════════════
    # YÖNTEM 3: AKTİF UÇUŞLAR (FALLBACK)
    # ═══════════════════════════════════════════════════════

    if USE_ACTIVE_FALLBACK and total_saved < TARGET_TOTAL_FLIGHTS:
        remaining = TARGET_TOTAL_FLIGHTS - total_saved

        print(f"\n{'═'*65}")
        print(f"  📡 YÖNTEM 3: AKTİF UÇUŞLAR (Fallback — {remaining} gerekli)")
        print(f"{'═'*65}")
        print(f"  ⚠ Bu uçuşlar PARTIAL olarak işaretlenir.")
        print(f"    Benchmark ve yakıt hesaplarında daha az ağırlık taşır.\n")

        for airline in ACTIVE_FALLBACK_AIRLINES:
            if total_saved >= TARGET_TOTAL_FLIGHTS:
                break

            print(f"  {'─'*60}")
            print(f"  📡 {airline} aktif uçuşları (fallback)...")
            print(f"  {'─'*60}")

            try:
                trajectories = collector.collect_airline_trajectories(
                    airline_icao          = airline,
                    max_flights           = MAX_ACTIVE_PER_AIRLINE,
                    min_altitude_m        = MIN_ALTITUDE_M_ACTIVE,
                    delay_between_calls_s = API_DELAY_S,
                )

                if not trajectories:
                    print(f"  ⚠ {airline}: Aktif uçuş bulunamadı")
                    continue

                stats['active_found'] += len(trajectories)

                for traj in trajectories:
                    callsign = ''
                    if 'callsign' in traj.columns and len(traj) > 0:
                        cs = traj['callsign'].iloc[0]
                        if isinstance(cs, str):
                            callsign = cs.strip()

                    if callsign and callsign in saved_callsigns:
                        stats['duplicate_skip'] += 1
                        continue

                    prefix   = f"ACT_{airline}"
                    filepath = OpenSkyCollector.save_trajectory(
                        traj, DATA_RAW_OPENSKY, prefix=prefix
                    )
                    filename = os.path.basename(filepath)
                    saved_files.append(filename)
                    saved_callsigns.add(callsign)
                    total_saved += 1
                    stats['active_saved'] += 1

                    print(
                        f"    ⚠ {callsign or '?':<12} [ACT - partial] "
                        f"{len(traj)} pts — benchmark dışı tutulacak"
                    )

                    if total_saved >= TARGET_TOTAL_FLIGHTS:
                        break

            except Exception as e:
                print(f"  ❌ {airline} aktif uçuş hatası: {e}")

            time.sleep(1)

        print(f"\n  Aktif uçuş sonucu: {stats['active_saved']} uçuş (partial)")

    # ═══════════════════════════════════════════════════════
    # ÖZET
    # ═══════════════════════════════════════════════════════

    print(f"\n{'═'*65}")
    print(f"  📊 TOPLAMA SONUÇLARI")
    print(f"{'═'*65}")

    print(f"""
  Yöntem            Bulunan   Kaydedilen   Kalite
  ──────────────────────────────────────────────────
  Arrivals          {stats['arrivals_found']:>7}   {stats['arrivals_saved']:>10}   Tam ✅
  Departures        {stats['departures_found']:>7}   {stats['departures_saved']:>10}   Yaklaşık ✅
  Aktif (fallback)  {stats['active_found']:>7}   {stats['active_saved']:>10}   Partial ⚠
  ──────────────────────────────────────────────────
  TOPLAM            {stats['arrivals_found']+stats['departures_found']+stats['active_found']:>7}   {total_saved:>10}
  ──────────────────────────────────────────────────
  Kalite filtre     {stats['quality_skip']:>7} atlandı
  Duplicate         {stats['duplicate_skip']:>7} atlandı
    """)

    if saved_files:
        print(f"  📁 Kaydedilen dosyalar ({DATA_RAW_OPENSKY}):")
        for fname in saved_files:
            prefix_tag = (
                '✅ Tam    ' if fname.startswith('ARR_') else
                '✅ Kalkış ' if fname.startswith('DEP_') else
                '⚠  Partial'
            )
            print(f"     {prefix_tag} | {fname}")

        # Kalite notu
        arrivals_pct = (
            stats['arrivals_saved'] / total_saved * 100
            if total_saved > 0 else 0
        )
        if arrivals_pct > 70:
            grade = 'A — Mükemmel'
        elif arrivals_pct > 40:
            grade = 'B — İyi'
        elif arrivals_pct > 20:
            grade = 'C — Orta'
        else:
            grade = 'D — Arrivals endpoint güncellemesi gerekiyor'

        print(f"\n  Veri kalitesi: {grade}")
        print(f"  Tam trajectory oranı: %{arrivals_pct:.0f}")
        print(f"\n  ✅ Sonraki adım:")
        print(f"  python scripts/02_analyze_and_optimize.py")

    else:
        print(f"""
  ❌ Hiç veri toplanamadı.

  OLASI SEBEPLER:
  ───────────────
  1. İnternet bağlantısı yok
  2. OpenSky API geçici yanıt vermiyor
  3. API günlük limit aşıldı (anonim: 100/gün)
  4. Seçilen havalimanlarında o saatte uçuş yok

  ÇÖZÜMLER:
  ─────────
  A. .env dosyasına OpenSky hesabı ekle (daha yüksek limit)
  B. 10:00-23:00 TR saatinde tekrar dene
  C. Birkaç dakika bekleyip tekrar dene
  D. ARRIVAL_AIRPORTS listesine daha büyük havalimanı ekle
        """)


# ═══════════════════════════════════════════════════════════
# ÇALIŞTIRMA
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
