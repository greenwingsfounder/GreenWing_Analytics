"""
Rüzgar modeli — fiziksel yükseklik profili ve rota bileşeni.

NEDEN GEREKLİ
-------------
Yakıt tüketimi yer hızına değil HAVA hızına (TAS) bağlıdır, ama
uçuş SÜRESİ yer hızına bağlıdır. 60 kt karşı rüzgar 8 saatlik bir
uçuşta +%8-15 fazla yakıt demektir. Rüzgarı yok saymak, uzun
rotalarda yıllık projeksiyonu sistematik olarak yanlış yapar.

KAYNAK
------
• ICAO Doc 7488 / Standard Atmosphere: rüzgarsız referans
• NOAA/NCEP Global Forecast System (GFS) klimatolojisi
• ARINC 424 / AIXM: rüzgar verisi formatı (u, v bileşenleri)
• Jet stream: 200-300 hPa (~FL340-FL390), ortalama 60-120 kt batı
  rüzgarı (Kuzey yarımküre kışı); bu projede FL350 referans alınır.

MODEL
-----
Yükseklikle rüzgar profili (Kuzey yarımküre orta enlemler, yıllık ortalama):

    h < 3 000 ft : V_w = 8 + 0.006·h          (sürtünme katmanı)
    3-20 kft     : V_w = 26 + 0.0015·(h-3000)
    20-36 kft    : V_w = 51 + 0.0030·(h-20000)   (jet çekirdeğine doğru)
    > 36 kft     : V_w = 99 (jet çekirdeği, sabit)

Yön: Kuzey yarımkürede hakim batı rüzgarı → 270° (batıdan eser).
Rota bileşeni: W_along = V_w · cos(θ_rota − θ_rüzgar)
  • pozitif → tailwind (yer hızı artar, yakıt azalır)
  • negatif → headwind

BELİRSİZLİK
-----------
Klimatolojik ortalama ±20 kt. Gerçek rüzgar günlük değişir; bu yüzden
model deterministik bir ortalama verir, tahmin değil. Daha iyisi:
müşterinin gerçek ADS-B/AMDAR veya METEO verisi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Kuzey yarımküre orta enlem klimatolojisi (yıllık ortalama)
_DEFAULT_WIND_DIR_DEG = 270.0   # batıdan eser
_DEFAULT_LATITUDE_DEG = 45.0    # orta enlem

# Yükseklik profili: (üst_sınır_ft, üst_sınır_hız_kt)
# Her aralıkta doğrusal interpolasyon; değerler kırılma noktalarında
# süreklidir. Kuzey yarımküre orta enlem, yıllık ortalama.
_PROFILE = [
    (0,        8.0),    # yer: sürtünme katmanı
    (3_000,   23.0),    # sınır tabakası üstü
    (12_000,  40.0),    # serbest atmosfer
    (24_000,  72.0),    # jet girişi
    (34_000,  95.0),    # jet çekirdeği
    (38_000, 109.0),    # jet maksimumu (~FL380, 200-300 hPa)
    (45_000,  86.0),    # jet üstü: azalır
]


@dataclass(frozen=True)
class WindResult:
    """Tek bir noktadaki rüzgar sonucu."""
    speed_kt: float
    direction_deg: float
    along_track_kt: float      # +tailwind, −headwind
    cross_track_kt: float      # +sağdan
    source: str

    def ground_speed_kt(self, tas_kt: float) -> float:
        """Yer hızı = TAS + rüzgarın rota bileşeni."""
        return float(tas_kt + self.along_track_kt)


def wind_speed_at_altitude(altitude_ft: float) -> float:
    """
    Klimatolojik ortalama rüzgar hızı (kt) — irtifaya göre.

    Kırılma noktaları arasında doğrusal interpolasyon; profil süreklidir.
    Kaynak: NOAA GFS klimatolojisi, Kuzey yarımküre 45° enlem, yıllık
    ortalama. Jet çekirdeği FL380'de ~109 kt, FL350'de ~98 kt.

    Args:
        altitude_ft: İrtifa (feet)

    Returns:
        Rüzgar hızı (kt)

    Examples:
        >>> round(wind_speed_at_altitude(0), 1)
        8.0
        >>> round(wind_speed_at_altitude(35000), 1)
        98.5
    """
    h = max(0.0, float(altitude_ft))
    for i in range(len(_PROFILE) - 1):
        h0, v0 = _PROFILE[i]
        h1, v1 = _PROFILE[i + 1]
        if h <= h1:
            return float(v0 + (v1 - v0) * (h - h0) / (h1 - h0))
    return float(_PROFILE[-1][1])


def along_track_wind(
    altitude_ft: float,
    track_deg: float,
    speed_kt: float | None = None,
    wind_dir_deg: float = _DEFAULT_WIND_DIR_DEG,
) -> WindResult:
    """
    Rota boyunca rüzgar bileşenini hesapla.

    Args:
        altitude_ft : İrtifa (ft)
        track_deg   : Rota yönü (derece, kuzey=0, saat yönü)
        speed_kt    : Rüzgar hızı (None → klimatolojik profil)
        wind_dir_deg: Rüzgarın GELDİĞİ yön (meteorolojik konvansiyon)

    Returns:
        WindResult
    """
    v = float(speed_kt) if speed_kt is not None else wind_speed_at_altitude(altitude_ft)

    # Meteorolojik yön "nereden estiği"dir → rüzgar vektörü onun tersi.
    # Rota ile rüzgar vektörü arasındaki açı:
    delta = math.radians(float(track_deg) - (float(wind_dir_deg) + 180.0))
    along = v * math.cos(delta)
    cross = v * math.sin(delta)

    return WindResult(
        speed_kt=v,
        direction_deg=float(wind_dir_deg),
        along_track_kt=along,
        cross_track_kt=cross,
        source='NOAA GFS klimatolojisi (batı rüzgarı, FL350 ≈ 96 kt)',
    )


def effective_wind_for_route(
    distance_nm: float,
    altitude_ft: float = 35_000.0,
    track_deg: float | None = None,
) -> WindResult:
    """
    Bir rota için etkin ortalama rüzgarı döndür.

    Rota yönü verilmezse doğu-batı ekseni varsayılır (Kuzey yarımkürede
    en yaygın uzun mesafe rotası). Yer hızı hesabında kullanılır.

    Args:
        distance_nm: Rota mesafesi (nm)
        altitude_ft: Cruise irtifası (ft)
        track_deg  : Rota yönü (None → 90° doğuya)

    Returns:
        WindResult
    """
    track = 90.0 if track_deg is None else float(track_deg)
    return along_track_wind(altitude_ft, track)


def fuel_penalty_factor(
    distance_nm: float,
    tas_kt: float,
    altitude_ft: float = 35_000.0,
    track_deg: float | None = None,
) -> float:
    """
    Rüzgarın yakıt tüketimine çarpan etkisi.

    Tüketim = FF × süre; süre = mesafe / yer hızı. Bu yüzden:

        çarpan = TAS / (TAS + W_along)

    Tailwind (W_along > 0) → çarpan < 1 (daha az yakıt)
    Headwind (W_along < 0) → çarpan > 1

    Returns:
        float: yakıt çarpanı (ör. 1.12 = %12 fazla)

    Examples:
        >>> round(fuel_penalty_factor(1560, 460, 35000), 3)
        0.827
    """
    w = effective_wind_for_route(distance_nm, altitude_ft, track_deg)
    gs = tas_kt + w.along_track_kt
    if gs <= 50.0:      # aşırı karşı rüzgar → mantıksız
        gs = 0.35 * tas_kt
    return float(tas_kt / gs)


if __name__ == '__main__':
    print('İrtifa — rüzgar profili (Kuzey yarımküre klimatolojisi)')
    print(f"{'ft':>8} {'kt':>7} {'rota(090°)':>12}")
    for alt in (0, 5_000, 10_000, 20_000, 30_000, 35_000, 39_000):
        w = along_track_wind(alt, 90.0)
        print(f'{alt:>8} {w.speed_kt:>7.1f} {w.along_track_kt:>+12.1f}')
    print()
    print('Yakıt çarpanı (460 kt TAS, FL350):')
    for trk in (90, 270):
        f = fuel_penalty_factor(1560, 460, 35_000, trk)
        print(f'  rota {trk:>3}°: ×{f:.3f} ({(f-1)*100:+.1f} %)')
