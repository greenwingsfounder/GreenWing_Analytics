# src/data_collection/opensky_collector.py

"""
GreenWing Analytics — OpenSky Network Veri Toplama
══════════════════════════════════════════════════════════════════════════════

Bu dosya OpenSky Network API'dan gerçek uçuş verisi toplar.

VERİ KAYNAĞI ŞEFFAFLIĞI (PROVENANCE):
─────────────────────────────────────
    Bu modül İKİ tür veri üretir ve ikisi de kaynağını açıkça taşır:

    1. GERÇEK VERİ (collection_method = 'arrivals' / 'departures' / 'active_flight')
       OpenSky Network API'sinden canlı çekilen ADS-B uçuş yolları.

    2. SENTETİK YEDEK VERİ (collection_method = 'synthetic_fallback')
       API 403/429 verdiğinde devreye giren, 'data/archive/opensky_real/'
       klasöründeki dosyalar. ⚠️ ÖNEMLİ: scripts/06_seed_real_data.py bu
       dosyaları matematiksel olarak ÜRETİR (simülasyon). Bunlar GERÇEK radar
       kaydı DEĞİLDİR.

    SENTETİK YEDEK VERİ:
        • Artık "gerçek" olarak ETİKETLENMEZ (eski sürümde etiketleniyordu → düzeltildi).
        • Zaman damgaları "canlıymış gibi" ileri KAYDIRILMAZ (eski sürümde kaydırılıyordu → düzeltildi).
        • Her kayda 'synthetic_fallback' + 'data_provenance' damgası vurulur;
          rapor/benchmark katmanı bunu sentetik olarak tanır.

Kaynak:
    OpenSky Network API Documentation
    https://opensky-network.org/apidoc/rest.html
"""

from __future__ import annotations

import os
import time
import glob
import random
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from src.logging_config import get_logger

logger = get_logger(__name__)
from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════
# .env DOSYASINI YÜKLE
# ═══════════════════════════════════════════════════════════

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_ENV_PATH = os.path.join(_PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=_ENV_PATH, override=True)


# ═══════════════════════════════════════════════════════════
# SABİTLER
# ═══════════════════════════════════════════════════════════

_BASE_URL     = "https://opensky-network.org/api"
# # KAYNAK (denetim #86): ağ davranışı.
# # 30 s = ölü bağlantı eşiği (TCP yeniden iletim penceresi).
# #  OpenSky yanıtı tipik 1-3 s; daha uzun bekletmek kullanıcıyı yorar.
# # 5 s + 2 deneme = 3 istek; OpenSky anonim limit saatte 400 istek.
#
_TIMEOUT_S    = 30
_RETRY_WAIT_S = 5
_MAX_RETRIES  = 2

_STATE_COLUMNS = [
    'icao24', 'callsign', 'origin_country', 'time_position',
    'last_contact', 'longitude', 'latitude', 'baro_altitude',
    'on_ground', 'velocity', 'true_track', 'vertical_rate',
    'sensors', 'geo_altitude', 'squawk', 'spi',
    'position_source', 'category',
]

COLLECTION_METHOD_ARRIVALS   = 'arrivals'
COLLECTION_METHOD_DEPARTURES = 'departures'
COLLECTION_METHOD_ACTIVE     = 'active_flight'


# ═══════════════════════════════════════════════════════════
# OAUTH2 TOKEN YÖNETİCİSİ
# ═══════════════════════════════════════════════════════════

class OpenSkyTokenManager:
    """OpenSky OAuth2 token yönetimi için basit sınıf."""
    
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token = None
        self._token_expiry = 0
    
    def get_access_token(self) -> Optional[str]:
        """Geçerli access token'ı döndür, yoksa yenile."""
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token
        
        # Yeni token al
        url = "https://opensky-network.org/api/oauth/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        
        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                token_data = response.json()
                self._access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 3600)
                self._token_expiry = time.time() + expires_in - 60
                return self._access_token
            else:
                return None
        except Exception as e:
            return None


# ═══════════════════════════════════════════════════════════
# ANA SINIF (GÜNCELLENDİ: ARŞİV TABANLI GERÇEK VERİ MODU)
# ═══════════════════════════════════════════════════════════

class OpenSkyCollector:
    """
    OpenSky Network API veri toplayıcı ve Gerçek Uçuş Veri Bankası Entegrasyonu.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        # GÜVENLİK: Kimlik bilgileri tek noktadan okunur (config.secrets).
        # Kaynak kodda veya depoda asla sabit değer tutulmaz.
        from config.credentials import get_opensky_credentials

        _creds = get_opensky_credentials(
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
        )
        self.username = _creds.username
        self.password = _creds.password
        self.client_id = _creds.client_id
        self.client_secret = _creds.client_secret
        
        self.session = requests.Session()
        self._token_manager = None
        self._authenticated = False
        
        # Basic Auth her koşulda fallback için kurulur
        if self.username and self.password:
            self.session.auth = (self.username, self.password)
            self._authenticated = True
            
        # OAuth2 token yöneticisi
        if self.client_id and self.client_secret:
            self._token_manager = OpenSkyTokenManager(self.client_id, self.client_secret)
            self._authenticated = True
            print("  ✅ OpenSky OAuth2 authentication (Client ID/Secret) kuruldu")
        elif self.username and self.password:
            print("  ✅ OpenSky Basic authentication (username/password) aktif")
        else:
            self._authenticated = False
            print("  ⚠ OpenSky: Anonim erişim (düşük limit)")

    def _request_with_auth(self, url: str, params: Optional[dict] = None) -> Optional[requests.Response]:
        """OAuth2 token ile istek gönder."""
        if not self._token_manager:
            return None
        
        token = self._token_manager.get_access_token()
        if not token:
            print("  ⚠ OAuth2 Token alınamadı, basic auth/anonim fallback kullanılıyor")
            return None
        
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = self.session.get(url, headers=headers, params=params, timeout=_TIMEOUT_S)
            return response
        except Exception as exc:  # noqa: BLE001
            # Hata tipi KAYBOLMAMALI: ağ / kimlik / ayrıştırma hatası
            # aynı şekilde None dönerse tanılama imkânsızlaşır.
            logger.warning('OpenSky isteği başarısız: %s: %s',
                           type(exc).__name__, exc)
            self.last_error = f'{type(exc).__name__}: {exc}'
            return None

    def _request(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        retries: int = _MAX_RETRIES,
    ) -> Optional[dict]:
        """OpenSky API'ya istek gönder."""
        url = f"{_BASE_URL}/{endpoint}"
        
        if self.client_id and self.client_secret and endpoint in ["flights/arrival", "flights/departure", "tracks/all"]:
            auth_response = self._request_with_auth(url, params)
            if auth_response and auth_response.status_code == 200:
                return auth_response.json()

        for attempt in range(retries + 1):
            try:
                response = self.session.get(
                    url, params=params, timeout=_TIMEOUT_S
                )

                if response.status_code == 200:
                    return response.json()

                if response.status_code in [401, 403]:
                    return None

                if response.status_code == 404:
                    return None

                if response.status_code == 429:
                    wait = _RETRY_WAIT_S * (attempt + 1)
                    print(f"  ⚠ Rate limit (HTTP 429). {wait}s bekleniyor...")
                    time.sleep(wait)
                    continue

                if response.status_code >= 500:
                    wait = _RETRY_WAIT_S * (attempt + 1)
                    print(f"  ⚠ Sunucu hatası ({response.status_code}). {wait}s bekleniyor...")
                    time.sleep(wait)
                    continue

            except Exception as exc:  # noqa: BLE001
                if attempt < retries:
                    logger.warning(
                        'OpenSky denemesi %d/%d başarısız (%s: %s) — yeniden',
                        attempt + 1, retries + 1, type(exc).__name__, exc)
                    time.sleep(_RETRY_WAIT_S)
                else:
                    logger.error('OpenSky tüm denemeler tükendi: %s: %s',
                                 type(exc).__name__, exc)
                    self.last_error = f'{type(exc).__name__}: {exc}'
                    return None

        return None

    @staticmethod
    def _mark_synthetic(df: pd.DataFrame) -> pd.DataFrame:
        """
        Yedek arşivden gelen veriyi SENTETİK olarak damgalar.

        NEDEN: data/archive/opensky_real/ içindeki dosyalar
        scripts/06_seed_real_data.py tarafından ÜRETİLİR. Bunları
        "gerçek radar kaydı" gibi sunmak veri bütünlüğü ihlalidir.
        Bu damga, downstream katmanların (rapor, benchmark) sentetik
        veriyi tanımasını ve gerçekmiş gibi sunmamasını sağlar.
        """
        out = df.copy()
        out["collection_method"] = "synthetic_fallback"
        out["data_provenance"] = "synthetic_simulation"
        out["is_synthetic"] = True
        return out

    @staticmethod
    def _normalize_state_rows(states: list) -> list[list]:
        normalized = []
        for row in states:
            if row is None:
                continue
            row = list(row)
            if len(row) < len(_STATE_COLUMNS):
                row = row + [None] * (len(_STATE_COLUMNS) - len(row))
            elif len(row) > len(_STATE_COLUMNS):
                row = row[:len(_STATE_COLUMNS)]
            normalized.append(row)
        return normalized

    @staticmethod
    def _enrich_trajectory(
        df: pd.DataFrame,
        collection_method: str,
        origin_icao: str = '',
        destination_icao: str = '',
        callsign: str = '',
        icao24: str = '',
    ) -> pd.DataFrame:
        df = df.copy()
        if origin_icao and 'origin_icao' not in df.columns:
            df['origin_icao'] = origin_icao
        if destination_icao and 'destination_icao' not in df.columns:
            df['destination_icao'] = destination_icao
        if callsign and ('callsign' not in df.columns or df['callsign'].isna().all()):
            df['callsign'] = callsign
        if icao24 and 'icao24' not in df.columns:
            df['icao24'] = icao24
        df['collection_method'] = collection_method
        df['collected_at'] = datetime.now(timezone.utc).isoformat()
        return df

    def get_current_states(
        self,
        icao24_list: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        params = {}
        if icao24_list:
            params['icao24'] = ','.join(icao24_list)

        data = self._request("states/all", params)
        if not data or 'states' not in data or data['states'] is None:
            return pd.DataFrame()

        normalized = self._normalize_state_rows(data['states'])
        if not normalized:
            return pd.DataFrame(columns=_STATE_COLUMNS)

        df = pd.DataFrame(normalized, columns=_STATE_COLUMNS)
        if 'callsign' in df.columns:
            df['callsign'] = df['callsign'].fillna('').astype(str).str.strip()

        for col in [
            'baro_altitude', 'velocity', 'vertical_rate',
            'latitude', 'longitude', 'geo_altitude',
            'time_position', 'last_contact', 'true_track', 'category',
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        if 'on_ground' in df.columns:
            df['on_ground'] = df['on_ground'].fillna(False).astype(bool)

        if 'time' in data:
            df['api_timestamp'] = pd.to_datetime(data['time'], unit='s', errors='coerce')

        return df

    def get_airline_flights(self, airline_icao: str) -> pd.DataFrame:
        all_states = self.get_current_states()
        if all_states.empty:
            return pd.DataFrame()

        airline_icao = airline_icao.upper().strip()
        mask = all_states['callsign'].str.startswith(airline_icao, na=False)
        return all_states[mask].copy().reset_index(drop=True)

    def get_departures(
        self,
        airport_icao: str,
        begin_time: int,
        end_time: int,
    ) -> pd.DataFrame:
        params = {
            'airport': airport_icao.upper(),
            'begin': int(begin_time),
            'end': int(end_time),
        }
        data = self._request("flights/departure", params)
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        if not df.empty:
            for col in ['firstSeen', 'lastSeen']:
                if col in df.columns:
                    df[f'{col}_dt'] = pd.to_datetime(df[col], unit='s', errors='coerce')
            if 'callsign' in df.columns:
                df['callsign'] = df['callsign'].fillna('').astype(str).str.strip()
        return df

    def get_arrivals(
        self,
        airport_icao: str,
        begin_time: int,
        end_time: int,
    ) -> pd.DataFrame:
        params = {
            'airport': airport_icao.upper(),
            'begin': int(begin_time),
            'end': int(end_time),
        }
        data = self._request("flights/arrival", params)
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        if not df.empty:
            for col in ['firstSeen', 'lastSeen']:
                if col in df.columns:
                    df[f'{col}_dt'] = pd.to_datetime(df[col], unit='s', errors='coerce')
            if 'callsign' in df.columns:
                df['callsign'] = df['callsign'].fillna('').astype(str).str.strip()

            for col in ['estDepartureAirport', 'estArrivalAirport']:
                if col in df.columns:
                    df[col] = (
                        df[col].fillna('').astype(str)
                        .str.strip().str.upper()
                        .replace({'NONE': '', 'NAN': ''})
                    )
        return df

    def get_flight_track(
        self,
        icao24: str,
        timestamp: Optional[int] = None,
    ) -> pd.DataFrame:
        params = {'icao24': icao24.lower().strip()}
        if timestamp:
            params['time'] = int(timestamp)

        data = self._request("tracks/all", params)
        if not data or 'path' not in data or data['path'] is None:
            return pd.DataFrame()

        path_records = []
        for point in data['path']:
            try:
                path_records.append({
                    'time': pd.to_datetime(point[0], unit='s'),
                    'latitude': point[1],
                    'longitude': point[2],
                    'baro_altitude': point[3],
                    'true_track': point[4],
                    'on_ground': point[5],
                })
            except Exception:
                continue

        if not path_records:
            return pd.DataFrame()

        df = pd.DataFrame(path_records)
        df['callsign'] = str(data.get('callsign', '')).strip()
        df['icao24'] = str(data.get('icao24', '')).strip()

        for col in ['latitude', 'longitude', 'baro_altitude', 'true_track']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        if 'on_ground' in df.columns:
            df['on_ground'] = df['on_ground'].fillna(False).astype(bool)

        df = df.sort_values('time').reset_index(drop=True)
        return df


    # ═══════════════════════════════════════════════════════════
    # BÖLÜM 6: ARRIVALS TOPLU TOPLAMA [BİRİNCİL] (DATA BANK FALLBACK)
    # ═══════════════════════════════════════════════════════════

    def collect_arrival_trajectories(
        self,
        airport_icao: str,
        airline_filter: Optional[list[str]] = None,
        hours_back: int = 4,
        max_flights: int = 5,
        min_waypoints: int = 30,
        delay_between_calls_s: float = 3.0,
    ) -> list[pd.DataFrame]:
        """
        Havalimanına yeni inen uçuşların tam trajectory'lerini topla.
        """
        now = int(time.time())
        begin = now - (hours_back * 3600)

        print(
            f"  → {airport_icao} arrivals: son {hours_back} saat "
            f"({datetime.fromtimestamp(begin).strftime('%H:%M')} - şimdi)"
        )

        arrivals_df = self.get_arrivals(airport_icao, begin, now)

        # ⚡ SENTETİK YEDEK VERİ (API erişilemezse) — PROVENANCE ETİKETLİ
        if arrivals_df.empty:
            print("  ⚠ OpenSky API kısıtlı/boş. SENTETİK yedek arşiv devreye giriyor (gerçek veri DEĞİL).")
            
            archive_dir = os.path.join(_PROJECT_ROOT, "data", "archive", "opensky_real")
            if not os.path.exists(archive_dir):
                # Yedek olarak proje kökünde ara
                archive_dir = "data/archive/opensky_real"
                
            trajectories = []
            
            if os.path.exists(archive_dir):
                # Havalimanı filtresine uygun gerçek CSV dosyalarını bul
                all_files = glob.glob(os.path.join(archive_dir, f"ARR_*_*_{airport_icao.upper()}.csv"))
                if not all_files:
                    # Alternatif olarak tüm dosyaları bul
                    all_files = glob.glob(os.path.join(archive_dir, "ARR_*.csv"))
                
                if all_files:
                    # Havayolu filtresini uygula (varsa)
                    if airline_filter:
                        filters = [a.upper().strip() for a in airline_filter]
                        all_files = [f for f in all_files if any(os.path.basename(f).split('_')[1].startswith(p) for p in filters)]
                    
                    if not all_files:
                        # Filtre uymadıysa tekrar tümüne geri dön
                        all_files = glob.glob(os.path.join(archive_dir, "ARR_*.csv"))
                        
                    selected_files = random.sample(all_files, min(len(all_files), max_flights))
                    
                    for f_path in selected_files:
                        df = self._mark_synthetic(pd.read_csv(f_path))

                        # GÜVENLİK/DOĞRULUK: Zaman damgaları ARTIK kaydırılmaz.
                        # Eski "live time-shifting" sentetik veriyi canlıymış gibi
                        # gösteriyordu → kaldırıldı.
                        df['collected_at'] = datetime.now(timezone.utc).isoformat()

                        callsign = df['callsign'].iloc[0] if 'callsign' in df.columns else "UNK"
                        orig = df['origin_icao'].iloc[0] if 'origin_icao' in df.columns else "UNK"
                        dest = df['destination_icao'].iloc[0] if 'destination_icao' in df.columns else airport_icao.upper()

                        print(f"    🧪 SENTETİK yedek kayıt yüklendi: {callsign} ({orig} ✈ {dest}) [simülasyon]")
                        trajectories.append(df)
                        
                    return trajectories

        # API normal çalışıyorsa standard ADS-B akışı
        trajectories = []
        processed = 0

        for _, arrival in arrivals_df.iterrows():
            if processed >= max_flights:
                break

            icao24 = str(arrival.get('icao24', '')).strip().lower()
            callsign = str(arrival.get('callsign', '')).strip()

            if not icao24:
                continue

            origin_icao = str(arrival.get('estDepartureAirport', '')).strip().upper()
            destination_icao = airport_icao.upper()

            last_seen = arrival.get('lastSeen')
            track_timestamp = int(last_seen) if last_seen else None

            track = self.get_flight_track(icao24, track_timestamp)

            if track.empty:
                if delay_between_calls_s > 0:
                    time.sleep(delay_between_calls_s)
                continue

            n_pts = len(track)
            track = self._enrich_trajectory(
                track,
                collection_method=COLLECTION_METHOD_ARRIVALS,
                origin_icao=origin_icao,
                destination_icao=destination_icao,
                callsign=callsign,
                icao24=icao24,
            )

            trajectories.append(track)
            processed += 1

            if delay_between_calls_s > 0 and processed < max_flights:
                time.sleep(delay_between_calls_s)

        return trajectories


    # ──────────────────────────────────────────────────────
    # BÖLÜM 7: KALKIŞ TOPLU TOPLAMA [İKİNCİL] (DATA BANK FALLBACK)
    # ──────────────────────────────────────────────────────

    def collect_departure_trajectories(
        self,
        airport_icao: str,
        airline_icao: Optional[str] = None,
        hours_back: int = 3,
        max_flights: int = 5,
        delay_between_calls_s: float = 3.0,
    ) -> list[pd.DataFrame]:
        """Havalimanı kalkışlarından trajectory topla."""
        now = int(time.time())
        begin = now - (hours_back * 3600)

        departures = self.get_departures(airport_icao, begin, now)

        # ⚡ GERÇEK UÇUŞ VERİ HAVUZU ENTEGRASYONU (Departures Fallback)
        if departures.empty:
            print("  ⚠ OpenSky Departures API kısıtlı. SENTETİK yedek arşiv devrede (gerçek veri DEĞİL).")
            
            archive_dir = os.path.join(_PROJECT_ROOT, "data", "archive", "opensky_real")
            if not os.path.exists(archive_dir):
                archive_dir = "data/archive/opensky_real"
                
            trajectories = []
            
            if os.path.exists(archive_dir):
                # LTFM kalkışlı veya tüm dosyaları ara
                all_files = glob.glob(os.path.join(archive_dir, f"ARR_*_{airport_icao.upper()}_*.csv"))
                if not all_files:
                    all_files = glob.glob(os.path.join(archive_dir, "ARR_*.csv"))
                    
                if all_files:
                    selected_files = random.sample(all_files, min(len(all_files), max_flights))
                    for f_path in selected_files:
                        df = self._mark_synthetic(pd.read_csv(f_path))
                        df['collected_at'] = datetime.now(timezone.utc).isoformat()
                        df['collection_method'] = "synthetic_fallback"

                        callsign = df['callsign'].iloc[0] if 'callsign' in df.columns else "UNK"
                        orig = airport_icao.upper()
                        dest = df['destination_icao'].iloc[0] if 'destination_icao' in df.columns else "UNK"

                        print(f"    🧪 SENTETİK yedek kayıt yüklendi: {callsign} ({orig} ✈ {dest}) [simülasyon]")
                        trajectories.append(df)
                        
                    return trajectories

        if airline_icao:
            airline_icao = airline_icao.upper().strip()
            if 'callsign' in departures.columns:
                departures = departures[
                    departures['callsign'].str.startswith(airline_icao, na=False)
                ]

        if departures.empty:
            return []

        selected = departures.head(max_flights)
        trajectories = []

        for _, dep in selected.iterrows():
            icao24 = str(dep.get('icao24', '')).strip().lower()
            callsign = str(dep.get('callsign', '')).strip()

            if not icao24:
                continue

            dest_icao = str(dep.get('estArrivalAirport', '')).strip().upper()
            if dest_icao in {'', 'NONE', 'NAN'}:
                dest_icao = ''

            track = self.get_flight_track(icao24)

            if track.empty or len(track) < 10:
                if delay_between_calls_s > 0:
                    time.sleep(delay_between_calls_s)
                continue

            track = self._enrich_trajectory(
                track,
                collection_method=COLLECTION_METHOD_DEPARTURES,
                origin_icao=airport_icao.upper(),
                destination_icao=dest_icao,
                callsign=callsign,
                icao24=icao24,
            )

            trajectories.append(track)

            if delay_between_calls_s > 0:
                time.sleep(delay_between_calls_s)

        return trajectories


    # ──────────────────────────────────────────────────────
    # BÖLÜM 8: AKTİF UÇUŞ TOPLAMA [FALLBACK]
    # ──────────────────────────────────────────────────────

    def collect_airline_trajectories(
        self,
        airline_icao: str,
        max_flights: int = 5,
        min_altitude_m: float = 5000,
        delay_between_calls_s: float = 3.0,
    ) -> list[pd.DataFrame]:
        """
        Havadaki aktif uçuşların trajectory'lerini topla.
        """
        flights = self.get_airline_flights(airline_icao)

        # ⚡ GERÇEK UÇUŞ VERİ HAVUZU ENTEGRASYONU (Active/Partial Fallback)
        if flights.empty:
            print("  ⚠ OpenSky Active Flights API kısıtlı. SENTETİK yedek arşiv devrede (gerçek veri DEĞİL).")
            
            archive_dir = os.path.join(_PROJECT_ROOT, "data", "archive", "opensky_real")
            if not os.path.exists(archive_dir):
                archive_dir = "data/archive/opensky_real"
                
            trajectories = []
            
            if os.path.exists(archive_dir):
                # Belirtilen havayoluna ait gerçekçi dosyaları bul
                all_files = glob.glob(os.path.join(archive_dir, "ARR_*.csv"))
                if all_files:
                    # Filtreyi uygula (dosya adındaki havayolu)
                    all_files = [f for f in all_files if os.path.basename(f).split('_')[1].startswith(airline_icao.upper())]
                    if not all_files:
                        all_files = glob.glob(os.path.join(archive_dir, "ARR_*.csv"))
                        
                    selected_files = random.sample(all_files, min(len(all_files), max_flights))
                    for f_path in selected_files:
                        df = self._mark_synthetic(pd.read_csv(f_path))
                        df['collected_at'] = datetime.now(timezone.utc).isoformat()
                        df['collection_method'] = "synthetic_fallback"  # sentetik, partial değil
                        
                        # Kısmi veri gibi göstermek için uçuşun ilk %30'unu kırp! (ADS-B radar kaybı simülasyonu)
                        cut_index = int(len(df) * 0.3)
                        df = df.iloc[cut_index:].copy().reset_index(drop=True)
                        
                        callsign = df['callsign'].iloc[0] if 'callsign' in df.columns else "UNK"
                        orig = df['origin_icao'].iloc[0] if 'origin_icao' in df.columns else "UNK"
                        dest = df['destination_icao'].iloc[0] if 'destination_icao' in df.columns else "UNK"
                        
                        print(f"    🧪 {callsign:<12} [SENTETİK yedek] {len(df)} pts — benchmark dışı tutulacak")
                        trajectories.append(df)
                        
                    return trajectories

        airborne = flights[flights['on_ground'] == False].copy()

        if airborne.empty:
            return []

        if 'baro_altitude' in airborne.columns:
            airborne = airborne[
                airborne['baro_altitude'].fillna(0) > min_altitude_m
            ]

        if airborne.empty:
            return []

        airborne = airborne.sort_values('baro_altitude', ascending=False)
        selected = airborne.head(max_flights)

        trajectories = []

        for _, flight in selected.iterrows():
            icao24 = str(flight.get('icao24', '')).strip().lower()
            callsign = str(flight.get('callsign', '')).strip()

            if not icao24:
                continue

            track = self.get_flight_track(icao24)

            if track.empty or len(track) < 10:
                if delay_between_calls_s > 0:
                    time.sleep(delay_between_calls_s)
                continue

            track = self._enrich_trajectory(
                track,
                collection_method=COLLECTION_METHOD_ACTIVE,
                callsign=callsign,
                icao24=icao24,
            )

            trajectories.append(track)

            if delay_between_calls_s > 0:
                time.sleep(delay_between_calls_s)

        return trajectories


    # ──────────────────────────────────────────────────────
    # BÖLÜM 9: KAYDETME
    # ──────────────────────────────────────────────────────

    @staticmethod
    def save_trajectory(
        df: pd.DataFrame,
        save_dir: str,
        prefix: str = "",
    ) -> str:
        """Trajectory verisini CSV olarak kaydet."""
        os.makedirs(save_dir, exist_ok=True)

        callsign = ''
        if 'callsign' in df.columns and len(df) > 0:
            cs = df['callsign'].iloc[0]
            if isinstance(cs, str):
                callsign = cs.strip().replace(' ', '_').replace('/', '_')

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        parts = [p for p in [prefix, callsign, timestamp] if p]
        filename = '_'.join(parts) + '.csv'
        filepath = os.path.join(save_dir, filename)

        df.to_csv(filepath, index=False)
        return filepath


    # ──────────────────────────────────────────────────────
    # BÖLÜM 10: DURUM BİLGİSİ
    # ──────────────────────────────────────────────────────

    @property
    def is_authenticated(self) -> bool:
        """API kimlik doğrulaması yapılmış mı?"""
        return self._authenticated

    @property
    def daily_limit(self) -> int:
        """Günlük API çağrı limiti."""
        return 400 if self._authenticated else 100

    def status(self) -> dict:
        """Collector durum bilgisi."""
        return {
            'authenticated': self._authenticated,
            'username': self.username if self._authenticated else 'anonymous',
            'daily_limit': self.daily_limit,
            'base_url': _BASE_URL,
        }

    def __repr__(self) -> str:
        auth = f"authenticated={self._authenticated}"
        user = f"user={self.username}" if self._authenticated else "anonymous"
        return f"OpenSkyCollector({auth}, {user})"


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_opensky_collector() -> bool:
    """OpenSky Collector doğrulama testleri."""
    print("\n" + "=" * 65)
    print("  OPENSKY_COLLECTOR.PY — DOĞRULAMA TESTLERİ")
    print("=" * 65)

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

    # [1] Oluşturma
    print("\n  [1] Collector Oluşturma")

    collector = OpenSkyCollector()
    tests += 1
    if isinstance(collector, OpenSkyCollector):
        ok(f"Oluşturuldu: {repr(collector)}")
    else:
        fail("Collector", "oluşturulamadı")
        return False

    status = collector.status()
    tests += 1
    if 'authenticated' in status and 'daily_limit' in status:
        ok(f"Status: auth={status['authenticated']}, limit={status['daily_limit']}/gün")
    else:
        fail("Status", f"eksik alan: {status}")

    # [2] Metot varlık kontrolü
    print("\n  [2] Metot Varlık Kontrolü")

    required_methods = [
        'get_current_states', 'get_airline_flights',
        'get_departures', 'get_arrivals', 'get_flight_track',
        'collect_arrival_trajectories', 'collect_departure_trajectories',
        'collect_airline_trajectories', 'save_trajectory', 'status',
    ]

    for method in required_methods:
        tests += 1
        if hasattr(collector, method):
            ok(f"{method}() mevcut")
        else:
            fail(f"{method}", "metod yok")

    # [3] Kaydetme (offline)
    print("\n  [3] Kaydetme (offline)")

    import tempfile

    test_df = pd.DataFrame({
        'time': pd.date_range('2025-01-20 10:00', periods=5, freq='60s'),
        'latitude': [41.275, 41.280, 41.290, 41.300, 41.310],
        'longitude': [28.752, 28.760, 28.780, 28.800, 28.820],
        'baro_altitude': [100, 5000, 10000, 10500, 10600],
        'callsign': ['PGT1234'] * 5,
        'icao24': ['4b1814'] * 5,
        'collection_method': [COLLECTION_METHOD_ARRIVALS] * 5,
    })

    tests += 1
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = OpenSkyCollector.save_trajectory(test_df, tmpdir, prefix='ARR_PGT')
        if os.path.exists(filepath) and filepath.endswith('.csv'):
            ok(f"CSV kaydedildi: {os.path.basename(filepath)}")
        else:
            fail("CSV kayıt", f"dosya yok: {filepath}")

    # [4] _enrich_trajectory
    print("\n  [4] _enrich_trajectory")

    tests += 1
    enriched = OpenSkyCollector._enrich_trajectory(
        test_df.copy(),
        collection_method=COLLECTION_METHOD_ARRIVALS,
        origin_icao='LTFM',
        destination_icao='EGLL',
        callsign='PGT1234',
    )
    if enriched['collection_method'].iloc[0] == COLLECTION_METHOD_ARRIVALS:
        ok("_enrich_trajectory çalışıyor")
    else:
        fail("_enrich_trajectory", "metadata eksik")

    # [5] Collection method sabitleri
    print("\n  [5] Sabitler")

    tests += 1
    if COLLECTION_METHOD_ARRIVALS == 'arrivals':
        ok(f"ARRIVALS = '{COLLECTION_METHOD_ARRIVALS}'")
    else:
        fail("ARRIVALS", COLLECTION_METHOD_ARRIVALS)

    tests += 1
    if COLLECTION_METHOD_ACTIVE == 'active_flight':
        ok(f"ACTIVE = '{COLLECTION_METHOD_ACTIVE}'")
    else:
        fail("ACTIVE", COLLECTION_METHOD_ACTIVE)

    # [6] is_authenticated property
    print("\n  [6] Properties")

    tests += 1
    if isinstance(collector.is_authenticated, bool):
        ok(f"is_authenticated = {collector.is_authenticated}")
    else:
        fail("is_authenticated", "bool değil")

    tests += 1
    if isinstance(collector.daily_limit, int):
        ok(f"daily_limit = {collector.daily_limit}")
    else:
        fail("daily_limit", "int değil")

    # SONUÇ
    print(f"\n  {'─' * 55}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print(f"\n  ❌ BAŞARISIZ TESTLER:")
        for i, e in enumerate(errors, 1):
            print(f"     {i}. {e}")
        return False

    print(f"\n  ✅ TÜM TESTLER BAŞARILI\n")
    return True


if __name__ == "__main__":
    validate_opensky_collector()
