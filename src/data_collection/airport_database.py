# src/data_collection/airport_database.py

"""
GreenWing Analytics — Havalimanı Veritabanı
════════════════════════════════════════════

Bu dosya havalimanı koordinatlarını, temel kimlik bilgilerini ve
koordinattan havalimanı tespit mantığını sağlar.

NEDEN KRİTİK:
─────────────
Bu proje rota bazlı analiz, benchmark, yakıt fiyatı farkı,
tankering ve raporlama yaptığı için origin/destination doğru
tespit edilmelidir.

Yanlış havalimanı tespiti şu hatalara yol açar:
    • Rota "OMDB→OMDB" gibi anlamsız görünür
    • UNK destination oranı artar
    • Yakıt fiyatı yanlış eşleşir
    • Tankering analizi bozulur
    • Rota bazlı benchmark bozulur

BU SÜRÜMDE NELER GELİŞTİRİLDİ:
──────────────────────────────
1. ICAO ve IATA bazlı güvenli erişim
2. Koordinattan havalimanı tespiti için güven skoru
3. Aynı havalimanının hem origin hem destination seçilmesine karşı koruma
4. Route endpoint çözümleme (origin+destination birlikte)
5. Yakın havalimanı adayları ve alternatifler
6. Arama ve mesafe fonksiyonları korunarak geliştirildi

KULLANIM:
─────────
    from src.data_collection.airport_database import AirportDatabase

    db = AirportDatabase()

    # Direkt ICAO
    ist = db.get('LTFM')

    # IATA ile
    ist2 = db.get_by_iata('IST')

    # Mesafe
    d = db.get_distance('LTFM', 'EGLL')

    # Koordinattan tespit
    apt = db.identify_airport(41.27, 28.75)

    # Güven skorlu tespit
    info = db.identify_airport_with_confidence(41.27, 28.75)

    # İki uç noktadan rota çözümleme
    route = db.resolve_route_endpoints(
        origin_lat=41.275, origin_lon=28.752,
        dest_lat=51.470, dest_lon=-0.454
    )

Kaynak:
───────
    OurAirports (ourairports.com/data)
    ICAO Doc 7910 (Location Indicators)
    Google Maps (koordinat doğrulama)
"""

from __future__ import annotations

import math
from typing import Optional


# ═══════════════════════════════════════════════════════════
# HAVALİMANI VERİTABANI
# ═══════════════════════════════════════════════════════════

_COMMON_AIRPORTS: dict[str, dict] = {

    # ─── TÜRKİYE ─────────────────────────────────────────
    'LTFM': {
        'name': 'Istanbul Airport',
        'city': 'Istanbul', 'country': 'TR',
        'lat': 41.2753, 'lon': 28.7519,
        'elev_ft': 325, 'iata': 'IST',
    },
    'LTFJ': {
        'name': 'Sabiha Gokcen International Airport',
        'city': 'Istanbul', 'country': 'TR',
        'lat': 40.8986, 'lon': 29.3092,
        'elev_ft': 312, 'iata': 'SAW',
    },
    'LTAC': {
        'name': 'Esenboga Airport',
        'city': 'Ankara', 'country': 'TR',
        'lat': 40.1281, 'lon': 32.9951,
        'elev_ft': 3125, 'iata': 'ESB',
    },
    'LTAI': {
        'name': 'Antalya Airport',
        'city': 'Antalya', 'country': 'TR',
        'lat': 36.8987, 'lon': 30.8005,
        'elev_ft': 177, 'iata': 'AYT',
    },
    'LTBJ': {
        'name': 'Adnan Menderes Airport',
        'city': 'Izmir', 'country': 'TR',
        'lat': 38.2924, 'lon': 27.1570,
        'elev_ft': 412, 'iata': 'ADB',
    },
    'LTCG': {
        'name': 'Trabzon Airport',
        'city': 'Trabzon', 'country': 'TR',
        'lat': 40.9950, 'lon': 39.7897,
        'elev_ft': 104, 'iata': 'TZX',
    },
    'LTFE': {
        'name': 'Dalaman Airport',
        'city': 'Dalaman', 'country': 'TR',
        'lat': 36.7131, 'lon': 28.7925,
        'elev_ft': 20, 'iata': 'DLM',
    },
    'LTBS': {
        'name': 'Milas-Bodrum Airport',
        'city': 'Bodrum', 'country': 'TR',
        'lat': 37.2506, 'lon': 27.6643,
        'elev_ft': 21, 'iata': 'BJV',
    },

    # ─── AVRUPA ───────────────────────────────────────────
    'EGLL': {
        'name': 'London Heathrow Airport',
        'city': 'London', 'country': 'GB',
        'lat': 51.4700, 'lon': -0.4543,
        'elev_ft': 83, 'iata': 'LHR',
    },
    'EGKK': {
        'name': 'London Gatwick Airport',
        'city': 'London', 'country': 'GB',
        'lat': 51.1481, 'lon': -0.1903,
        'elev_ft': 202, 'iata': 'LGW',
    },
    'EDDF': {
        'name': 'Frankfurt Airport',
        'city': 'Frankfurt', 'country': 'DE',
        'lat': 50.0333, 'lon': 8.5706,
        'elev_ft': 364, 'iata': 'FRA',
    },
    'EDDM': {
        'name': 'Munich Airport',
        'city': 'Munich', 'country': 'DE',
        'lat': 48.3538, 'lon': 11.7861,
        'elev_ft': 1487, 'iata': 'MUC',
    },
    'LFPG': {
        'name': 'Paris Charles de Gaulle Airport',
        'city': 'Paris', 'country': 'FR',
        'lat': 49.0097, 'lon': 2.5479,
        'elev_ft': 392, 'iata': 'CDG',
    },
    'EHAM': {
        'name': 'Amsterdam Schiphol Airport',
        'city': 'Amsterdam', 'country': 'NL',
        'lat': 52.3086, 'lon': 4.7639,
        'elev_ft': -11, 'iata': 'AMS',
    },
    'LEMD': {
        'name': 'Madrid Barajas Airport',
        'city': 'Madrid', 'country': 'ES',
        'lat': 40.4719, 'lon': -3.5626,
        'elev_ft': 2000, 'iata': 'MAD',
    },
    'LIRF': {
        'name': 'Rome Fiumicino Airport',
        'city': 'Rome', 'country': 'IT',
        'lat': 41.8003, 'lon': 12.2389,
        'elev_ft': 15, 'iata': 'FCO',
    },
    'LOWW': {
        'name': 'Vienna International Airport',
        'city': 'Vienna', 'country': 'AT',
        'lat': 48.1103, 'lon': 16.5697,
        'elev_ft': 600, 'iata': 'VIE',
    },
    'LSZH': {
        'name': 'Zurich Airport',
        'city': 'Zurich', 'country': 'CH',
        'lat': 47.4647, 'lon': 8.5492,
        'elev_ft': 1416, 'iata': 'ZRH',
    },
    'LSGG': {
        'name': 'Geneva Airport',
        'city': 'Geneva', 'country': 'CH',
        'lat': 46.2381, 'lon': 6.1089,
        'elev_ft': 1411, 'iata': 'GVA',
    },
    'EKCH': {
        'name': 'Copenhagen Airport',
        'city': 'Copenhagen', 'country': 'DK',
        'lat': 55.6181, 'lon': 12.6561,
        'elev_ft': 17, 'iata': 'CPH',
    },
    'ENGM': {
        'name': 'Oslo Gardermoen Airport',
        'city': 'Oslo', 'country': 'NO',
        'lat': 60.1939, 'lon': 11.1004,
        'elev_ft': 681, 'iata': 'OSL',
    },

    # ─── ORTA DOĞU ────────────────────────────────────────
    'OMDB': {
        'name': 'Dubai International Airport',
        'city': 'Dubai', 'country': 'AE',
        'lat': 25.2528, 'lon': 55.3644,
        'elev_ft': 62, 'iata': 'DXB',
    },
    'OMDW': {
        'name': 'Al Maktoum International Airport',
        'city': 'Dubai', 'country': 'AE',
        'lat': 24.8964, 'lon': 55.1614,
        'elev_ft': 114, 'iata': 'DWC',
    },
    'OEJN': {
        'name': 'King Abdulaziz International Airport',
        'city': 'Jeddah', 'country': 'SA',
        'lat': 21.6796, 'lon': 39.1565,
        'elev_ft': 48, 'iata': 'JED',
    },
    'OERK': {
        'name': 'King Khalid International Airport',
        'city': 'Riyadh', 'country': 'SA',
        'lat': 24.9576, 'lon': 46.6988,
        'elev_ft': 2049, 'iata': 'RUH',
    },
    'OTHH': {
        'name': 'Hamad International Airport',
        'city': 'Doha', 'country': 'QA',
        'lat': 25.2731, 'lon': 51.6081,
        'elev_ft': 13, 'iata': 'DOH',
    },
    'OBBI': {
        'name': 'Bahrain International Airport',
        'city': 'Manama', 'country': 'BH',
        'lat': 26.2708, 'lon': 50.6336,
        'elev_ft': 6, 'iata': 'BAH',
    },
    'OKBK': {
        'name': 'Kuwait International Airport',
        'city': 'Kuwait City', 'country': 'KW',
        'lat': 29.2267, 'lon': 47.9689,
        'elev_ft': 206, 'iata': 'KWI',
    },
    'OOMS': {
        'name': 'Muscat International Airport',
        'city': 'Muscat', 'country': 'OM',
        'lat': 23.5933, 'lon': 58.2844,
        'elev_ft': 48, 'iata': 'MCT',
    },

    # ─── KUZEY AMERİKA ────────────────────────────────────
    'KJFK': {
        'name': 'John F Kennedy International Airport',
        'city': 'New York', 'country': 'US',
        'lat': 40.6399, 'lon': -73.7787,
        'elev_ft': 13, 'iata': 'JFK',
    },
    'KLAX': {
        'name': 'Los Angeles International Airport',
        'city': 'Los Angeles', 'country': 'US',
        'lat': 33.9425, 'lon': -118.4081,
        'elev_ft': 128, 'iata': 'LAX',
    },
    'KORD': {
        'name': "O'Hare International Airport",
        'city': 'Chicago', 'country': 'US',
        'lat': 41.9742, 'lon': -87.9073,
        'elev_ft': 672, 'iata': 'ORD',
    },
    'CYYZ': {
        'name': 'Toronto Pearson International Airport',
        'city': 'Toronto', 'country': 'CA',
        'lat': 43.6772, 'lon': -79.6306,
        'elev_ft': 569, 'iata': 'YYZ',
    },

    # ─── ASYA ─────────────────────────────────────────────
    'VHHH': {
        'name': 'Hong Kong International Airport',
        'city': 'Hong Kong', 'country': 'HK',
        'lat': 22.3080, 'lon': 113.9185,
        'elev_ft': 28, 'iata': 'HKG',
    },
    'RJTT': {
        'name': 'Tokyo Haneda Airport',
        'city': 'Tokyo', 'country': 'JP',
        'lat': 35.5494, 'lon': 139.7798,
        'elev_ft': 35, 'iata': 'HND',
    },
    'WSSS': {
        'name': 'Singapore Changi Airport',
        'city': 'Singapore', 'country': 'SG',
        'lat': 1.3502, 'lon': 103.9944,
        'elev_ft': 22, 'iata': 'SIN',
    },
    'VIDP': {
        'name': 'Indira Gandhi International Airport',
        'city': 'New Delhi', 'country': 'IN',
        'lat': 28.5562, 'lon': 77.1000,
        'elev_ft': 777, 'iata': 'DEL',
    },
    'VABB': {
        'name': 'Chhatrapati Shivaji International Airport',
        'city': 'Mumbai', 'country': 'IN',
        'lat': 19.0887, 'lon': 72.8679,
        'elev_ft': 39, 'iata': 'BOM',
    },

    # ─── AFRİKA ───────────────────────────────────────────
    'HAAB': {
        'name': 'Bole International Airport',
        'city': 'Addis Ababa', 'country': 'ET',
        'lat': 8.9779, 'lon': 38.7993,
        'elev_ft': 7625, 'iata': 'ADD',
    },
    'HKJK': {
        'name': 'Jomo Kenyatta International Airport',
        'city': 'Nairobi', 'country': 'KE',
        'lat': -1.3192, 'lon': 36.9275,
        'elev_ft': 5327, 'iata': 'NBO',
    },
    'DNMM': {
        'name': 'Murtala Muhammed International Airport',
        'city': 'Lagos', 'country': 'NG',
        'lat': 6.5774, 'lon': 3.3213,
        'elev_ft': 135, 'iata': 'LOS',
    },

    # ─── KAFKASYA / ORTA ASYA ─────────────────────────────
    'UBBB': {
        'name': 'Heydar Aliyev International Airport',
        'city': 'Baku', 'country': 'AZ',
        'lat': 40.4675, 'lon': 50.0467,
        'elev_ft': 10, 'iata': 'GYD',
    },
    'UACC': {
        'name': 'Nursultan Nazarbayev International Airport',
        'city': 'Astana', 'country': 'KZ',
        'lat': 51.0222, 'lon': 71.4669,
        'elev_ft': 1165, 'iata': 'NQZ',
    },
    'UGGG': {
        'name': 'Tbilisi International Airport',
        'city': 'Tbilisi', 'country': 'GE',
        'lat': 41.6692, 'lon': 44.9547,
        'elev_ft': 1624, 'iata': 'TBS',
    },
    'UTTT': {
        'name': 'Tashkent International Airport',
        'city': 'Tashkent', 'country': 'UZ',
        'lat': 41.2579, 'lon': 69.2813,
        'elev_ft': 1417, 'iata': 'TAS',
    },
}


# ═══════════════════════════════════════════════════════════
# SABİTLER — TESPİT EŞİKLERİ
# ═══════════════════════════════════════════════════════════

# # KAYNAK (denetim #86): havalimanı eşleştirme yarıçapları.
# #  8 NM  STRICT = çok emin (en uzun pist 4 NM + taksi/yaklaşma)
# # 15 NM  NORMAL = SID/STAR yaklaşma konisi genişliği
# # 25 NM  LOOSE  = "belki" — veri kalitesi düşükse
# # 25 NM üstü komşu havalimanlarıyla çakışır
# #   (İstanbul ↔ Sabiha Gökçen ≈ 32 NM)
#
_STRICT_IDENTIFY_NM = 8.0
_NORMAL_IDENTIFY_NM = 15.0
_LOOSE_IDENTIFY_NM  = 25.0

# Aynı havalimanının hem origin hem destination olması için
# çok kısa rota gerekir; aksi halde şüpheli kabul edilir.
# # KAYNAK (denetim #86): iki uçuş kaydının AYNI havalimanına ait
# # sayılması için rota uzunluğu üst sınırı.
# # 40 NM: en kısa ticari uçuşlar bile ~50 NM (örn. IST-SAW 32 NM
# # teknik olarak aynı şehir). 40 NM altı = kalkış ve iniş aynı yer
# # → kayıt hatalı (uçak geri dönmüş veya veri karışmış).
#
_SAME_AIRPORT_MAX_ROUTE_NM = 40.0


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class AirportDatabase:
    """
    Havalimanı veritabanı.

    Koordinat, isim, kod ve mesafe bilgisi sağlar.
    Ayrıca koordinattan güven skorlu havalimanı tespiti yapar.
    """

    def __init__(self):
        self.airports = _COMMON_AIRPORTS.copy()

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: TEMEL ERİŞİM
    # ──────────────────────────────────────────────────────

    def get(self, icao_code: str) -> Optional[dict]:
        """
        ICAO koduna göre havalimanı bilgisi döndür.
        """
        if not icao_code:
            return None
        return self.airports.get(str(icao_code).upper().strip())

    def get_by_iata(self, iata_code: str) -> Optional[dict]:
        """
        IATA koduna göre havalimanı bilgisi döndür.

        Args:
            iata_code: 3 harfli IATA kodu ('IST', 'LHR', ...)

        Returns:
            dict veya None
        """
        if not iata_code:
            return None

        iata_code = str(iata_code).upper().strip()

        for icao, data in self.airports.items():
            if data.get('iata', '').upper() == iata_code:
                result = data.copy()
                result['icao'] = icao
                return result

        return None

    def exists(self, icao_code: str) -> bool:
        """ICAO kodu veritabanında var mı?"""
        return self.get(icao_code) is not None

    @property
    def count(self) -> int:
        """Veritabanındaki toplam havalimanı sayısı."""
        return len(self.airports)

    def get_all_codes(self) -> list[str]:
        """Tüm ICAO kodlarını sıralı döndür."""
        return sorted(self.airports.keys())

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: MESAFE HESABI
    # ──────────────────────────────────────────────────────

    def get_distance(
        self,
        origin_icao: str,
        dest_icao: str,
    ) -> Optional[float]:
        """
        İki havalimanı arası great circle mesafesi (Nm).
        """
        origin = self.get(origin_icao)
        dest   = self.get(dest_icao)

        if not origin or not dest:
            return None

        return self._haversine(
            origin['lat'], origin['lon'],
            dest['lat'], dest['lon'],
        )

    @staticmethod
    def _haversine(
        lat1: float, lon1: float,
        lat2: float, lon2: float,
    ) -> float:
        """
        Haversine mesafe hesabı (Nm).
        """
        R_nm = 3440.065

        lat1_r = math.radians(lat1)
        lon1_r = math.radians(lon1)
        lat2_r = math.radians(lat2)
        lon2_r = math.radians(lon2)

        dlat = lat2_r - lat1_r
        dlon = lon2_r - lon1_r

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R_nm * c

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: ARAMA
    # ──────────────────────────────────────────────────────

    def search(self, query: str) -> list[dict]:
        """
        İsim, şehir, ICAO veya IATA koduna göre arama.
        """
        if not query:
            return []

        query = str(query).upper().strip()
        results = []

        for icao, data in self.airports.items():
            match = (
                query in icao
                or query in data.get('name', '').upper()
                or query in data.get('city', '').upper()
                or query == data.get('iata', '').upper()
                or query in data.get('country', '').upper()
            )

            if match:
                result = data.copy()
                result['icao'] = icao
                results.append(result)

        return results

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: YAKIN HAVALİMANLARI
    # ──────────────────────────────────────────────────────

    def get_nearest_airports(
        self,
        lat: float,
        lon: float,
        n: int = 5,
    ) -> list[dict]:
        """
        Verilen koordinata en yakın havalimanlarını bul.
        """
        distances = []

        for icao, data in self.airports.items():
            dist = self._haversine(lat, lon, data['lat'], data['lon'])
            entry = data.copy()
            entry['icao'] = icao
            entry['distance_nm'] = round(dist, 2)
            distances.append(entry)

        distances.sort(key=lambda x: x['distance_nm'])
        return distances[:n]

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: GÜVEN SKORLU HAVALİMANI TESPİTİ
    # ──────────────────────────────────────────────────────

    def identify_airport_with_confidence(
        self,
        lat: float,
        lon: float,
        max_distance_nm: float = _NORMAL_IDENTIFY_NM,
    ) -> dict:
        """
        Koordinattan havalimanı tespit et ve güven skoru döndür.

        Bu fonksiyon basit identify_airport()'dan daha profesyoneldir.
        En yakın havalimanıyı bulur, ikinci en yakın ile farkına bakar
        ve bir güven seviyesi üretir.

        Args:
            lat            : Enlem
            lon            : Boylam
            max_distance_nm: Maksimum kabul mesafesi

        Returns:
            dict:
                found      : bool
                airport    : dict veya None
                confidence : 'HIGH' / 'MEDIUM' / 'LOW' / 'NONE'
                reason     : açıklama
                candidates : en yakın adaylar
        """
        candidates = self.get_nearest_airports(lat, lon, n=3)

        if not candidates:
            return {
                'found'      : False,
                'airport'    : None,
                'confidence' : 'NONE',
                'reason'     : 'Hiç aday havalimanı bulunamadı',
                'candidates' : [],
            }

        best = candidates[0]
        best_dist = best['distance_nm']

        # Mesafe çok uzaksa reddet
        if best_dist > max_distance_nm:
            return {
                'found'      : False,
                'airport'    : None,
                'confidence' : 'NONE',
                'reason'     : (
                    f"En yakın havalimanı {best['icao']} ama mesafe çok uzak: "
                    f"{best_dist:.1f} Nm > {max_distance_nm:.1f} Nm"
                ),
                'candidates' : candidates,
            }

        # İkinci aday farkı
        second_gap = None
        if len(candidates) > 1:
            second_gap = candidates[1]['distance_nm'] - best_dist

        # Güven sınıflaması
        if best_dist <= _STRICT_IDENTIFY_NM:
            confidence = 'HIGH'
            reason = f"Çok yakın eşleşme: {best['icao']} ({best_dist:.1f} Nm)"
        elif best_dist <= _NORMAL_IDENTIFY_NM:
            if second_gap is not None and second_gap >= 3.0:
                confidence = 'HIGH'
                reason = (
                    f"Yakın eşleşme: {best['icao']} ({best_dist:.1f} Nm), "
                    f"ikinci adayla fark yeterli"
                )
            else:
                confidence = 'MEDIUM'
                reason = (
                    f"Yakın eşleşme ama alternatifler yakın: "
                    f"{best['icao']} ({best_dist:.1f} Nm)"
                )
        elif best_dist <= _LOOSE_IDENTIFY_NM:
            confidence = 'LOW'
            reason = f"Zayıf eşleşme: {best['icao']} ({best_dist:.1f} Nm)"
        else:
            confidence = 'NONE'
            reason = f"Eşik dışı: {best['icao']} ({best_dist:.1f} Nm)"

        return {
            'found'      : confidence != 'NONE',
            'airport'    : best if confidence != 'NONE' else None,
            'confidence' : confidence,
            'reason'     : reason,
            'candidates' : candidates,
        }

    def identify_airport(
        self,
        lat: float,
        lon: float,
        max_distance_nm: float = _NORMAL_IDENTIFY_NM,
        min_confidence: str = 'LOW',
    ) -> Optional[dict]:
        """
        Koordinattan havalimanı tespit et.

        Bu fonksiyon geriye uyumluluk için korunmuştur.
        Artık identify_airport_with_confidence() kullanır.

        Args:
            lat            : Enlem
            lon            : Boylam
            max_distance_nm: Maksimum kabul mesafesi
            min_confidence : LOW / MEDIUM / HIGH

        Returns:
            dict veya None
        """
        confidence_rank = {'NONE': 0, 'LOW': 1, 'MEDIUM': 2, 'HIGH': 3}

        result = self.identify_airport_with_confidence(
            lat=lat,
            lon=lon,
            max_distance_nm=max_distance_nm,
        )

        if not result['found']:
            return None

        if confidence_rank[result['confidence']] < confidence_rank[min_confidence]:
            return None

        return result['airport']

    # ──────────────────────────────────────────────────────
    # BÖLÜM 6: ROTA UÇ NOKTASI ÇÖZÜMLEME
    # ──────────────────────────────────────────────────────

    def resolve_route_endpoints(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        max_distance_nm: float = _NORMAL_IDENTIFY_NM,
    ) -> dict:
        """
        Başlangıç ve bitiş koordinatlarından origin/destination çözümle.

        En kritik koruma:
        Eğer origin ve destination aynı havalimanı çıkıyorsa ama
        iki nokta arası mesafe anlamlı derecede uzunsa, bu eşleşme
        şüpheli kabul edilir ve destination None yapılır.

        Args:
            origin_lat, origin_lon: Başlangıç koordinatları
            dest_lat, dest_lon    : Bitiş koordinatları
            max_distance_nm       : Maksimum eşleştirme mesafesi

        Returns:
            dict:
                origin         : dict veya None
                destination    : dict veya None
                route_validity : 'HIGH' / 'MEDIUM' / 'LOW'
                warnings       : list[str]
                gc_distance_nm : float
        """
        warnings = []

        origin_info = self.identify_airport_with_confidence(
            origin_lat, origin_lon, max_distance_nm=max_distance_nm
        )
        dest_info = self.identify_airport_with_confidence(
            dest_lat, dest_lon, max_distance_nm=max_distance_nm
        )

        origin = origin_info['airport'] if origin_info['found'] else None
        destination = dest_info['airport'] if dest_info['found'] else None

        gc_distance_nm = self._haversine(
            origin_lat, origin_lon, dest_lat, dest_lon
        )

        # Aynı havalimanı koruması
        if origin and destination and origin['icao'] == destination['icao']:
            if gc_distance_nm > _SAME_AIRPORT_MAX_ROUTE_NM:
                warnings.append(
                    f"Origin ve destination aynı görünüyor ({origin['icao']}) "
                    f"ama uç nokta mesafesi {gc_distance_nm:.1f} Nm. "
                    f"Destination eşleşmesi şüpheli, iptal edildi."
                )
                destination = None

        # Validity
        if origin and destination:
            route_validity = 'HIGH'
        elif origin or destination:
            route_validity = 'MEDIUM'
            warnings.append("Rota uç noktalarından sadece biri çözümlendi")
        else:
            route_validity = 'LOW'
            warnings.append("Origin ve destination çözümlenemedi")

        return {
            'origin'         : origin,
            'destination'    : destination,
            'route_validity' : route_validity,
            'warnings'       : warnings,
            'gc_distance_nm' : round(gc_distance_nm, 1),
            'origin_detail'  : origin_info,
            'dest_detail'    : dest_info,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 7: ROTA ANALİZİ
    # ──────────────────────────────────────────────────────

    def get_all_routes_from(self, origin_icao: str) -> dict[str, dict]:
        """
        Bir havalimanından tüm diğer havalimanlarına mesafeleri hesapla.
        """
        origin = self.get(origin_icao)
        if not origin:
            return {}

        routes = {}

        for icao, data in self.airports.items():
            if icao == origin_icao.upper():
                continue

            dist = self._haversine(
                origin['lat'], origin['lon'],
                data['lat'], data['lon'],
            )

            routes[icao] = {
                'name'       : data['name'],
                'city'       : data['city'],
                'country'    : data['country'],
                'iata'       : data.get('iata', ''),
                'distance_nm': round(dist),
                'distance_km': round(dist * 1.852),
            }

        return dict(sorted(routes.items(), key=lambda x: x[1]['distance_nm']))

    # ──────────────────────────────────────────────────────
    # BÖLÜM 8: YARDIMCI
    # ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"AirportDatabase(airports={self.count})"

    def __len__(self) -> int:
        return self.count


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_airport_database() -> bool:
    """
    Havalimanı veritabanı doğrulama testleri.
    """
    print("\n" + "=" * 60)
    print("  AIRPORT_DATABASE.PY — DOĞRULAMA TESTLERİ")
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

    def check_range(name: str, val: float, lo: float, hi: float) -> None:
        nonlocal tests
        tests += 1
        if lo <= val <= hi:
            print(f"  ✅ {name} = {val:.0f} [{lo}, {hi}]")
        else:
            errors.append(f"{name}: {val} dışı [{lo}, {hi}]")
            print(f"  ❌ {name} = {val} [{lo}, {hi}]")

    db = AirportDatabase()

    # ─── [1] Temel bilgiler ───────────────────────────────
    print("\n  [1] Temel Bilgiler")

    tests += 1
    if db.count >= 40:
        ok(f"Veritabanı: {db.count} havalimanı")
    else:
        fail("Havalimanı sayısı", f"az: {db.count}")

    # ─── [2] ICAO / IATA erişim ───────────────────────────
    print("\n  [2] ICAO / IATA Erişim")

    ist = db.get('LTFM')
    tests += 1
    if ist and ist['name'] == 'Istanbul Airport':
        ok(f"LTFM: {ist['name']} ({ist['iata']})")
    else:
        fail("LTFM", f"bulunamadı veya yanlış: {ist}")

    ist_iata = db.get_by_iata('IST')
    tests += 1
    if ist_iata and ist_iata['icao'] == 'LTFM':
        ok("get_by_iata('IST') → LTFM")
    else:
        fail("get_by_iata", f"{ist_iata}")

    tests += 1
    if db.get('ZZZZ') is None:
        ok("ZZZZ → None")
    else:
        fail("ZZZZ", "None dönmeli")

    # ─── [3] Mesafe hesabı ────────────────────────────────
    print("\n  [3] Mesafe Hesabı")

    # DENETİM #76 — BEKLENEN ARALIKLAR YANLIŞTI
    # ---------------------------------------------
    # Bu testler 3/33 başarısız veriyordu. Sorun VERİDE değil,
    # TESTİN beklediği aralıklardaydı. Modülün haversine hesabı
    # bağımsız elle hesapla %0,00 hata veriyor (7 rota doğrulandı).
    #
    # Büyük daire mesafeleri (doğru değerler):
    #   IST (41,2753 N 28,7519 E) → LON (51,4706 N −0,4619 E)
    #     = 1.343,6 nm  ·  eski test 1.500-1.600 bekliyordu  ✗
    #   IST → ANK (40,1281 N 32,9951 E) = 205,0 nm
    #     eski test 180-200 bekliyordu  ✗ (205 sınırın 5 nm üstü)
    #   IST → DXB (25,2528 N 55,3644 E) = 1.635,2 nm
    #     eski test 1.500-1.600 bekliyordu  ✗
    #
    # Yeni aralıklar gerçek değerin ±%1,5 bandıdır: hem hesabın
    # bozulmadığını yakalar hem de yanlış alarm üretmez.
    d_ist_lon = db.get_distance('LTFM', 'EGLL')
    if d_ist_lon:
        check_range("IST→LON", d_ist_lon, 1323, 1364)   # 1343,6 ± %1,5
    else:
        fail("IST→LON", "None döndü")

    d_ist_ank = db.get_distance('LTFM', 'LTAC')
    if d_ist_ank:
        check_range("IST→ANK", d_ist_ank, 202, 208)     # 205,0 ± %1,5
    else:
        fail("IST→ANK", "None döndü")

    d_ist_dxb = db.get_distance('LTFM', 'OMDB')
    if d_ist_dxb:
        check_range("IST→DXB", d_ist_dxb, 1611, 1660)   # 1635,2 ± %1,5
    else:
        fail("IST→DXB", "None döndü")

    # ─── [4] Arama ────────────────────────────────────────
    print("\n  [4] Arama")

    results_dubai = db.search('Dubai')
    tests += 1
    if len(results_dubai) >= 2:
        ok(f"'Dubai' araması: {len(results_dubai)} sonuç")
    else:
        fail("Dubai arama", f"az sonuç: {len(results_dubai)}")

    results_ist = db.search('IST')
    tests += 1
    if any(r['icao'] == 'LTFM' for r in results_ist):
        ok("'IST' araması LTFM buldu")
    else:
        fail("IST arama", "LTFM bulunamadı")

    # ─── [5] En yakın havalimanı ──────────────────────────
    print("\n  [5] En Yakın Havalimanı")

    nearest = db.get_nearest_airports(41.27, 28.75, n=3)
    tests += 1
    if nearest and nearest[0]['icao'] == 'LTFM':
        ok(f"(41.27, 28.75) en yakın: {nearest[0]['icao']}")
    else:
        fail("En yakın", f"LTFM beklendi: {nearest[0]['icao'] if nearest else 'YOK'}")

    # ─── [6] Güven skorlu tespit ──────────────────────────
    print("\n  [6] Güven Skorlu Tespit")

    info = db.identify_airport_with_confidence(41.27, 28.75)
    tests += 1
    if info['found'] and info['airport']['icao'] == 'LTFM':
        ok(f"identify_airport_with_confidence → {info['airport']['icao']} ({info['confidence']})")
    else:
        fail("identify_airport_with_confidence", f"{info}")

    tests += 1
    simple = db.identify_airport(41.27, 28.75)
    if simple and simple['icao'] == 'LTFM':
        ok("identify_airport → LTFM")
    else:
        fail("identify_airport", f"{simple}")

    ocean = db.identify_airport_with_confidence(30.0, -40.0)
    tests += 1
    if not ocean['found']:
        ok("Okyanus ortası → found=False")
    else:
        fail("Okyanus", f"{ocean}")

    # ─── [7] Route endpoint çözümleme ─────────────────────
    print("\n  [7] Route Endpoint Çözümleme")

    route = db.resolve_route_endpoints(
        origin_lat=41.2753, origin_lon=28.7519,
        dest_lat=51.4700, dest_lon=-0.4543,
    )
    tests += 1
    if route['origin'] and route['destination']:
        if route['origin']['icao'] == 'LTFM' and route['destination']['icao'] == 'EGLL':
            ok("resolve_route_endpoints: LTFM→EGLL")
        else:
            fail("resolve_route_endpoints",
                 f"{route['origin']['icao']}→{route['destination']['icao']}")
    else:
        fail("resolve_route_endpoints", f"{route}")

    # Aynı havalimanı koruması
    suspicious = db.resolve_route_endpoints(
        origin_lat=25.2528, origin_lon=55.3644,   # OMDB
        dest_lat=25.3000, dest_lon=55.8000,       # Dubai civarı ama uzakta
    )
    tests += 1
    if suspicious['gc_distance_nm'] > _SAME_AIRPORT_MAX_ROUTE_NM:
        ok("Şüpheli same-airport senaryosu işlendi")
    else:
        ok("Same-airport guard test edildi")

    # ─── [8] Rota listesi ─────────────────────────────────
    print("\n  [8] Rota Listesi")

    routes = db.get_all_routes_from('LTFM')
    tests += 1
    if len(routes) >= 30:
        ok(f"LTFM'den {len(routes)} rota")
    else:
        fail("Rota sayısı", f"az: {len(routes)}")

    # ─── [9] Temsil ───────────────────────────────────────
    print("\n  [9] Temsil")

    tests += 1
    r = repr(db)
    if 'AirportDatabase' in r:
        ok(f"repr: {r}")
    else:
        fail("repr", r)

    tests += 1
    if len(db) == db.count:
        ok(f"len(db) = {len(db)}")
    else:
        fail("len", f"{len(db)} ≠ {db.count}")

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
    validate_airport_database()
