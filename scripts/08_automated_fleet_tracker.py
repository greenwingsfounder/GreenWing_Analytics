# scripts/08_automated_fleet_tracker.py

"""
GreenWing Analytics — Otomatik Canlı Filo Takip ve Kayıt Motoru (Automated ADS-B Logger)
═══════════════════════════════════════════════════════════════════════════════════════

Bu script, herhangi bir kullanıcı hesabı veya API anahtarına ihtiyaç duymadan,
ADSB.lol ücretsiz topluluk radar ağı üzerinden Pegasus (PGT), Türk Hava Yolları (THY)
ve SunExpress (SXS) havayollarına ait havadaki TÜM aktif uçuşları arka planda 
tamamen otomatik ve paralel olarak takip eder (multi-flight tracking).

MÜKEMMEL VE SÜRDÜRÜLEBİLİR ÇÖZÜM (BÖLGESEL CANLI ADS-B KEŞİF MOTORU):
────────────────────────────────────────────────────────────────────
    Daha önce tek bir uçuş numarasını beklemek veya OpenSky kısıtlamalarına takılmak
    yerine, bu script Türkiye, Almanya, İngiltere/Hollanda, İtalya ve İspanya'yı
    kapsayan 5 dev bölgesel radar dairesini (point-radius scan) her 60 saniyede bir tarar [3].
    
    Bu sayede, havada o an aktif olarak uçan ve Flightradar24'te canlı görünen
    yüzlerce Pegasus, THY ve SunExpress uçağını saniyeler içinde OTOMATİK KEŞFEDER.
    
    Takip ve Kayıt Süreci:
    1. Her 60 saniyede bir 5 ana bölge taranır ve havayolu uçuşları süzülür.
    2. Yeni keşfedilen uçuşlar RAM üzerinde paralel takibe alınır.
    3. Uçaklar tırmanır, cruise yapar, rüzgarla savaşır ve bekleme turu atar.
    4. İniş yapan veya radardan çıkan uçağın tüm rota geçmişi (trajectory) anında
       'data/raw/opensky/' klasörüne tamamlanmış yasal bir CSV dosyası olarak kaydedilir.

KULLANIM:
─────────
    # Arka planda çalıştırıp her gün onlarca gerçek uçuş yolunu otomatik toplamak için:
    python scripts/08_automated_fleet_tracker.py --interval 60 --min-pts 15
"""

import os
import sys
import time
import argparse
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Hafızadaki uçuş veri tabanı
# { CALLSIGN: { "points": [...], "last_seen": timestamp, "type": B738, "reg": TC-XXX } }
ACTIVE_TRACKER: dict[str, dict] = {}

def fetch_live_fleet(airlines: list[str]) -> list[dict]:
    """
    ADSB.lol'den 5 ana bölge noktasını tarayarak havayollarına ait aktif tüm uçakları çeker.
    Bu yöntem kısıtlamasız, şifresiz ve %100 canlı gerçek verilere ulaşır.
    """
    points = [
        ('Turkey', 40.0, 32.0, 600),
        ('Germany', 50.0, 10.0, 600),
        ('UK_NL', 51.5, 2.0, 600),
        ('Spain', 40.0, -3.5, 600),
        ('Italy', 41.8, 12.5, 600),
        ('US_East', 40.7, -74.0, 600),   # ✅ New York, Boston, Washington (Kalkış/İniş Kapsaması)
        ('US_West', 34.0, -118.2, 600),  # ✅ Los Angeles, San Francisco
        ('Canada_East', 45.5, -73.5, 600) # ✅ Toronto, Montreal
    ]
    
    unique_aircraft = {}
    
    # AJet ('TKJ'), Pegasus ('PC'), THY ('TK') gibi alt/ortak markaları da kapsayalım
    target_prefixes = []
    for a in airlines:
        target_prefixes.append(a.upper().strip())
        if a.upper().strip() == "THY":
            target_prefixes.extend(["TK", "TKJ", "AJet"])
        elif a.upper().strip() == "PGT":
            target_prefixes.extend(["PC", "PGT"])
        elif a.upper().strip() == "SXS":
            target_prefixes.extend(["XQ", "SXS"])
            
    prefixes = tuple(target_prefixes)
    
    for name, lat, lon, r in points:
        url = f"https://api.adsb.lol/v2/point/{lat}/{lon}/{r}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                ac_list = data.get("ac", [])
                for ac in ac_list:
                    callsign = ac.get("flight", "").strip().upper()
                    if callsign.startswith(prefixes):
                        hex_code = ac.get("hex")
                        if hex_code and hex_code not in unique_aircraft:
                            unique_aircraft[hex_code] = ac
        except Exception:
            pass
            
    return list(unique_aircraft.values())

def track_fleet(airlines: list[str], min_pts: int, timeout_mins: int, interval_s: int):
    save_dir = "data/raw/opensky"
    os.makedirs(save_dir, exist_ok=True)
    
    print("\n" + "=" * 80)
    print(f"  GREENWING ANALYTICS — CANLI OTO-FİLO TAKİP VE KAYIT SİSTEMİ")
    print(f"  Takip Edilen Filolar: {', '.join(airlines)}")
    print(f"  Bölgesel Keşif Alanı : Türkiye, Almanya, İngiltere/Hollanda, İtalya, İspanya 🌍")
    print(f"  Min Kayıt Waypoint  : {min_pts} nokta")
    print(f"  Zaman Aşımı Sınırı  : {timeout_mins} dakika (Sinyal kaybı/İniş tespiti)")
    print(f"  Hedef Klasör        : {save_dir}")
    print("=" * 80)
    print("  Arka plan filo takibi başlatıldı. Durdurmak için [Ctrl + C] tuşlarına basın...")
    print("  " + "─" * 76)

    try:
        while True:
            now = datetime.now(timezone.utc)
            now_ts = time.time()
            
            # 1. Havadaki uçakları otomatik tara (Point-Radius Keşif)
            current_active_callsigns = set()
            aircrafts = fetch_live_fleet(airlines)
            
            for ac in aircrafts:
                callsign = ac.get("flight", "").strip().upper()
                if not callsign or len(callsign) < 3:
                    continue
                    
                current_active_callsigns.add(callsign)
                lat = ac.get("lat")
                lon = ac.get("lon")
                alt = ac.get("alt_baro")
                vel = ac.get("gs")
                track_deg = ac.get("track")
                icao24 = ac.get("hex", "UNK")
                ac_type = ac.get("t", "UNK")
                registration = ac.get("r", "UNK")
                
                if lat is None or lon is None:
                    continue
                    
                if str(alt).lower() == "ground":
                    alt = 0.0

                point = {
                    'time': now.strftime('%Y-%m-%d %H:%M:%S'),
                    'latitude': float(lat),
                    'longitude': float(lon),
                    'baro_altitude': float(alt) if alt else 0.0,
                    'velocity': float(vel) if vel else 0.0,
                    'true_track': float(track_deg) if track_deg else 0.0,
                    'on_ground': alt == 0 or alt is None,
                    'callsign': callsign,
                    'icao24': icao24,
                    'origin_icao': "UNK",
                    'destination_icao': "UNK",
                    'collection_method': 'arrivals',
                    'collected_at': now.isoformat(),
                    'wind_speed_kts': float(ac.get("ws")) if ac.get("ws") is not None else None,
                    'wind_direction_deg': float(ac.get("wd")) if ac.get("wd") is not None else None,
                    'temperature_c': float(ac.get("oat")) if ac.get("oat") is not None else None
                }
                
                # Eğer uçuş hafızada yoksa yeni kayıt oluştur
                if callsign not in ACTIVE_TRACKER:
                    ACTIVE_TRACKER[callsign] = {
                        "points": [point],
                        "last_seen": now_ts,
                        "type": ac_type,
                        "reg": registration,
                        "started_at": now.strftime('%H:%M')
                    }
                    print(f"  ✈️  [Keşif {now.strftime('%H:%M')}] Yeni Uçuş Yakalandı: {callsign:<10} | Tip: {ac_type:<4} | Tescil: {registration}")
                else:
                    # Varsa, yeni koordinat noktasını ekle (Aynı saniye verisini dublike etme)
                    last_pt = ACTIVE_TRACKER[callsign]["points"][-1]
                    if last_pt["latitude"] != lat or last_pt["longitude"] != lon:
                        ACTIVE_TRACKER[callsign]["points"].append(point)
                    ACTIVE_TRACKER[callsign]["last_seen"] = now_ts

            # 2. İniş yapmış veya radardan çıkmış (tamamlanmış) uçuşları denetle
            completed_flights = []
            for callsign, data in list(ACTIVE_TRACKER.items()):
                # Eğer uçağı son taramada görmediysek ve üzerinden 'timeout_mins' geçmişse, uçak İNMİŞ veya radardan çıkmıştır!
                time_since_last_seen_mins = (now_ts - data["last_seen"]) / 60.0
                
                if time_since_last_seen_mins >= timeout_mins:
                    completed_flights.append(callsign)
                    
                    # Eğer toplanan veri miktarı emniyet sınırından (min_pts) büyükse disk dosyası olarak kaydet!
                    n_points = len(data["points"])
                    if n_points >= min_pts:
                        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"ARR_AUTO_{callsign}_{timestamp_str}.csv"
                        filepath = os.path.join(save_dir, filename)
                        
                        df = pd.DataFrame(data["points"])
                        df.to_csv(filepath, index=False)
                        
                        print(f"  💾  [Kayıt {now.strftime('%H:%M')}] Gerçek Rota Tamamlandı ve Kaydedildi: {callsign:<10} | {n_points:>3} pts | Tip: {data['type']} | Dosya: {filename}")
                    else:
                        pass # Çok kısa süreli takip, atla

            # Kaydedilen tamamlanmış uçuşları hafıza takibinden çıkar
            for callsign in completed_flights:
                ACTIVE_TRACKER.pop(callsign, None)

            # 3. Durum Raporu Bas
            print(f"  📊  [Oto-Takip Durumu {now.strftime('%H:%M:%S')}] Havadaki Aktif Takip: {len(ACTIVE_TRACKER)} uçuş.")
            time.sleep(interval_s)

    except KeyboardInterrupt:
        print("\n" + "─" * 80)
        print(f"  🛑 Oto-filo takip motoru kullanıcı tarafından durduruldu.")
        saved_count = 0
        for callsign, data in ACTIVE_TRACKER.items():
            if len(data["points"]) >= min_pts:
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"ARR_AUTO_RECOVER_{callsign}_{timestamp_str}.csv"
                filepath = os.path.join(save_dir, filename)
                df = pd.DataFrame(data["points"])
                df.to_csv(filepath, index=False)
                saved_count += 1
        print(f"  Hafızadaki {saved_count} adet uçuş kurtarılarak diske kaydedildi.")
        print("  " + "─" * 76 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated ADS-B Fleet Tracker")
    parser.add_argument("--airlines", type=str, default="SXS,PGT,THY", help="Takip edilecek havayolları (virgülle ayırın)")
    parser.add_argument("--min-pts", type=int, default=15, help="Kaydedilecek minimum waypoint noktası")
    parser.add_argument("--timeout", type=int, default=5, help="İniş tespiti için sinyal kesilme süresi (dakika)")
    parser.add_argument("--interval", type=int, default=60, help="Tarama sıklığı (saniye)")
    args = parser.parse_args()

    airline_list = [a.strip().upper() for a in args.airlines.split(",")]
    track_fleet(airline_list, args.min_pts, args.timeout, args.interval)
