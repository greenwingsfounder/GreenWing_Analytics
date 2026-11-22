# scripts/06_seed_real_data.py

"""
GreenWing Analytics — Sentetik Uçuş Yolu Üreteci (Synthetic Data Seeder)
═══════════════════════════════════════════════════════════════════════════

⚠️  ÖNEMLİ / DÜRÜSTLÜK NOTU:
    Bu script GERÇEK radar/ADS-B verisi toplamaz. Matematiksel olarak
    SENTETİK (simüle) uçuş yolları ÜRETİR ve bunları test/demo amacıyla
    'data/archive/opensky_real/' klasörüne yazar.

    Eski sürüm bu verileri "Gerçek Uçuş Veri Havuzu" ve "%100 gerçek"
    olarak tanımlıyordu. Bu yanıltıcıydı ve düzeltildi.

    Gerçek veri için: OpenSkyCollector (OpenSky API) veya
    scripts/07_live_flight_scrapper.py (ADSB.lol canlı radar) kullanın.

NE ÜRETİR?
──────────
    Gerçekçilik katmak için 4 havacılık anomalisini simüle eder:
        1. Holding Pattern (Bekleme Turu)
        2. Rüzgar/Türbülans gürültüsü (rastgele GPS sapması)
        3. ATC hız ve irtifa kısıtları (kademeli alçalma/tırmanma)
        4. Yaklaşma sırasında hız değişimleri

    Çıktı: 15 adet SENTETİK rota kaydı (test/demo amaçlı).
"""

import os
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

def generate_holding_pattern(center_lat, center_lon, radius=0.08, num_points=12):
    """Havalimanı üzerinde uçuşun daire (holding) çizmesini simüle eder."""
    angles = np.linspace(0, 2 * np.pi, num_points)
    lat_pts = center_lat + radius * np.sin(angles)
    lon_pts = center_lon + radius * np.cos(angles) * 1.3  # Boylam düzeltmesi
    return list(lat_pts), list(lon_pts)

def seed_real_flights():
    archive_dir = "data/archive/opensky_real"
    os.makedirs(archive_dir, exist_ok=True)
    
    # Gerçek Rota Eşlemeleri
    flights = [
        {"origin": "LTAI", "dest": "EDDF", "callsign": "SXS1409", "icao24": "4b1814", "ac": "B738", "holding": True, "step": True},
        {"origin": "LTBJ", "dest": "EDDF", "callsign": "SXS6381", "icao24": "4b1815", "ac": "B738", "holding": False, "step": True},
        {"origin": "LTFM", "dest": "EDDF", "callsign": "THY501",  "icao24": "4b1816", "ac": "A321", "holding": True, "step": False},
        {"origin": "LTAI", "dest": "EDDM", "callsign": "SXS5720", "icao24": "4b1817", "ac": "B738", "holding": False, "step": False},
        {"origin": "LTFM", "dest": "EDDM", "callsign": "THY764",  "icao24": "4b1818", "ac": "A320", "holding": True, "step": False},
        {"origin": "LTFM", "dest": "EHAM", "callsign": "THY1951", "icao24": "4b1819", "ac": "B738", "holding": False, "step": True},
        {"origin": "LTFJ", "dest": "EHAM", "callsign": "PGT120",  "icao24": "4b1820", "ac": "A20N", "holding": True, "step": True},
        {"origin": "LTFM", "dest": "LEMD", "callsign": "THY1011", "icao24": "4b1821", "ac": "B738", "holding": False, "step": True},
        {"origin": "LTFM", "dest": "LIRF", "callsign": "THY1865", "icao24": "4b1822", "ac": "A321", "holding": False, "step": False},
        {"origin": "LTFJ", "dest": "LIRF", "callsign": "PGT802",  "icao24": "4b1823", "ac": "A20N", "holding": False, "step": False},
        {"origin": "LTFM", "dest": "EDDF", "callsign": "THY1587", "icao24": "4b1830", "ac": "B738", "holding": True, "step": False},
        {"origin": "LTFM", "dest": "EDDM", "callsign": "THY1629", "icao24": "4b1831", "ac": "B738", "holding": False, "step": False},
        {"origin": "LTFM", "dest": "KJFK", "callsign": "THY001",  "icao24": "4b1832", "ac": "A350", "holding": False, "step": True},
        {"origin": "LTFJ", "dest": "EDDF", "callsign": "PGT501",  "icao24": "4b1833", "ac": "A20N", "holding": True, "step": True},
        {"origin": "LTFJ", "dest": "LCLK", "callsign": "PGT120",  "icao24": "4b1834", "ac": "A20N", "holding": False, "step": False}
    ]

    airport_coords = {
        "LTFM": (41.275, 28.752), "LTFJ": (40.898, 29.309), "LTAI": (36.900, 30.800), "LTBJ": (38.289, 27.155),
        "EDDF": (50.033, 8.570),  "EDDM": (48.353, 11.786), "EHAM": (52.308, 4.764),  "LEMD": (40.471, -3.560),
        "LIRF": (41.800, 12.238), "KJFK": (40.640, -73.778), "KLAX": (33.942, -118.408), "WSSS": (1.364, 103.991),
        "LCLK": (34.878, 33.625)
    }

    print(f"✈ Uçuş Veri Havuzu Seeding İşlemi Başlatıldı...")
    
    for f in flights:
        orig = f["origin"]
        dest = f["dest"]
        call = f["callsign"]
        icao = f["icao24"]
        holding = f["holding"]
        step = f["step"]
        
        orig_lat, orig_lon = airport_coords.get(orig, (41.0, 29.0))
        dest_lat, dest_lon = airport_coords.get(dest, (50.0, 8.5))
        
        # Mesafe hesabı
        lat_diff = dest_lat - orig_lat
        lon_diff = dest_lon - orig_lon
        dist_nm = np.sqrt(lat_diff**2 + (lon_diff * np.cos(np.radians(orig_lat)))**2) * 60.0
        
        # Adım sayısı ve süre (1Hz yerine 30s'de bir veri noktası, gerçekçi sıklaştırılmış ADS-B)
        duration_hrs = dist_nm / 410.0 + (0.3 if holding else 0)
        num_points = int(duration_hrs * 120)  # Her 30 saniyede bir nokta
        
        start_time = datetime.now(timezone.utc) - timedelta(hours=duration_hrs)
        
        records = []
        climb_pts = int(num_points * 0.15)
        descent_pts = int(num_points * 0.20)
        holding_pts = 12 if holding else 0
        cruise_pts = num_points - climb_pts - descent_pts - holding_pts
        
        target_alt_ft = 35000.0 if f["ac"] != "A350" else 37000.0
        
        # 1. Tırmanış
        for i in range(climb_pts):
            frac = i / climb_pts
            lat = orig_lat + frac * (lat_diff * 0.15) + np.random.randn() * 0.005
            lon = orig_lon + frac * (lon_diff * 0.15) + np.random.randn() * 0.005
            alt = target_alt_ft * np.sin(frac * np.pi / 2)
            vel = 150.0 + frac * 280.0 + np.random.randn() * 5
            on_ground = True if i == 0 else False
            records.append((start_time + timedelta(seconds=i*30), lat, lon, alt, vel, on_ground))
            
        # 2. Cruise (Step Climb dahil)
        curr_time = start_time + timedelta(seconds=climb_pts*30)
        for i in range(cruise_pts):
            frac = i / cruise_pts
            # Rota koordinatları
            lat = (orig_lat + lat_diff * 0.15) + frac * (lat_diff * 0.65) + np.random.randn() * 0.003
            lon = (orig_lon + lon_diff * 0.15) + frac * (lon_diff * 0.65) + np.random.randn() * 0.003
            
            # Step climb simülasyonu (Yarı yolda FL340'dan FL380'e çıkış)
            alt = target_alt_ft
            if step and frac > 0.5:
                alt = target_alt_ft + 2000.0  # FL370/FL390 step
                
            vel = 420.0 + np.random.randn() * 8  # Seyir hızı
            records.append((curr_time + timedelta(seconds=i*30), lat, lon, alt, vel, False))
            
        # 3. Holding Pattern (Eğer iniş yoğunluğu varsa varış havalimanı yakınında beklet)
        curr_time = curr_time + timedelta(seconds=cruise_pts*30)
        if holding:
            # Varışa 20 Nm kala holding çizdir
            hold_lat_c = dest_lat - lat_diff * 0.08
            hold_lon_c = dest_lon - lon_diff * 0.08
            hold_lats, hold_lons = generate_holding_pattern(hold_lat_c, hold_lon_c)
            for i in range(holding_pts):
                lat = hold_lats[i] + np.random.randn() * 0.002
                lon = hold_lons[i] + np.random.randn() * 0.002
                alt = 10000.0 + np.random.randn() * 100  # Holding irtifası (10k ft)
                vel = 220.0 + np.random.randn() * 5     # Holding hızı (yavaş)
                records.append((curr_time + timedelta(seconds=i*30), lat, lon, alt, vel, False))
                
        # 4. İniş
        curr_time = curr_time + timedelta(seconds=holding_pts*30)
        for i in range(descent_pts):
            frac = i / descent_pts
            # Varış havalimanına kalan mesafe
            lat = (dest_lat - lat_diff * 0.08 if holding else orig_lat + lat_diff * 0.80) + frac * (lat_diff * 0.08 if holding else lat_diff * 0.20) + np.random.randn() * 0.005
            lon = (dest_lon - lon_diff * 0.08 if holding else orig_lon + lon_diff * 0.80) + frac * (lon_diff * 0.08 if holding else lon_diff * 0.20) + np.random.randn() * 0.005
            
            alt_start = 10000.0 if holding else target_alt_ft
            alt = alt_start * (1.0 - frac)
            vel = (220.0 if holding else 420.0) - frac * 120.0 + np.random.randn() * 4
            on_ground = True if i == (descent_pts - 1) else False
            records.append((curr_time + timedelta(seconds=i*30), lat, lon, alt, vel, on_ground))
            
        # DataFrame oluştur
        df = pd.DataFrame(records, columns=['time', 'latitude', 'longitude', 'baro_altitude', 'velocity', 'on_ground'])
        df['callsign'] = call
        df['icao24'] = icao
        df['true_track'] = np.degrees(np.arctan2(lon_diff, lat_diff)) % 360.0
        
        # Metadata ekle
        df['origin_icao'] = orig
        df['destination_icao'] = dest
        df['collection_method'] = "arrivals" if not f.get("departure", False) else "departures"
        df['collected_at'] = datetime.now(timezone.utc).isoformat()
        
        # Kaydet
        prefix = f"ARR_{call[:3]}"
        filename = f"{prefix}_{call}_{orig}_{dest}.csv"
        filepath = os.path.join(archive_dir, filename)
        df.to_csv(filepath, index=False)
        print(f"  ✅ Havuza Eklendi: {filename:<35} | {dist_nm:>4.0f} Nm | Holding: {str(holding):<5} | Step: {str(step):<5}")
        
    print(f"🎉 Toplam {len(flights)} adet gerçekçi uçuş verisi başarıyla arşivlendi.")

if __name__ == "__main__":
    seed_real_flights()
