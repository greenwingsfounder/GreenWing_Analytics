"""
GreenWing Analytics — GFS rüzgâr sağlayıcısı
═══════════════════════════════════════════════════════════════════════════

DENETİM #82 — "RÜZGÂR VARSAYIM" SORUNUNU ÇÖZEN MODÜL
──────────────────────────────────────────────────────

PROBLEM
───────
`wind_model.py` bugüne kadar yalnızca **klimatolojik profil** kullanıyordu:
irtifaya göre ortalama rüzgâr hızı (FL350 ≈ 98 kt) ve sabit batı yönü.
Bu, belirsizlik bütçesinin en büyük kalemiydi (±%22,2).

Gerçek sorun: rüzgâr **tarihe, konuma ve rotaya** bağlıdır. İstanbul'dan
Amsterdam'a uçarken karşı rüzgâr olabilir; aynı gün İstanbul'dan Ercan'a
uçarken de. Klimatoloji ikisini aynı sayar.

ÇÖZÜM — ÜÇ KADEMELİ SAĞLAYICI ZİNCİRİ
──────────────────────────────────────
  1. `GFSWindProvider`   — gerçek NOAA GFS ızgarası (varsa)
  2. `SeasonalProvider`  — mevsimsel profil (bugünkü davranış, yedek)
  3. `NoWindProvider`    — rüzgâr yok (referans senaryo)

Öncelik sırası: GFS > mevsimsel. GFS verisi yoksa sistem çalışmaya devam
eder ama `source` alanında hangisinin kullanıldığını **açıkça** söyler.
Böylece "gerçek rüzgâr mı, tahmin mi" sorusu her çıktıda cevaplanır.

GFS VERİSİ NASIL ALINIR
────────────────────────
  NOAA NOMADS (ücretsiz, kayıt yok):
    https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl

  Tek bir seviye+rüzgâr isteği için tipik URL:
    ?file=gfs.t00z.pgrb2.0p25.f000
    &lev_10_m_above_ground=on&lev_250_mb=on&lev_300_mb=on
    &var_UGRD=on&var_VGRD=on
    &subregion=&toplat=60&leftlon=-15&rightlon=50&bottomlat=30
    &dir=/gfs.20261122/00/atmos

  Çıktı GRIB2'dir. Okumak için `cfgrib` veya `pygrib` gerekir:
    pip install cfgrib eccodes
    ds = xr.open_dataset(path, engine='cfgrib')

  Bu modül GRIB2'yi kendisi çözmez; `xarray`/`cfgrib` opsiyonel
  bağımlılık olarak yüklenmişse okur. Yoksa sessizce mevsimsel
  sağlayıcıya düşer ve bunu `source` alanında bildirir.

KULLANIM
────────
    from src.models.wind_gfs import get_wind_provider, route_wind

    prov = get_wind_provider()               # GFS varsa GFS, yoksa mevsimsel
    r = route_wind(prov, altitude_ft=35000, track_deg=295, lat=41.0, lon=29.0)
    print(r.speed_kt, r.source)

    # Tüm rotayı örnekleyerek ortalama alın:
    r = route_wind_along_route(prov, [(41.0, 29.0), (48.0, 12.0), (52.3, 4.8)],
                               altitude_ft=35000)

BELİRSİZLİK ETKİSİ
───────────────────
  Mevsimsel profil : ±%22,2  (bugünkü durum)
  GFS (gerçek)     : ±%3-5   (analiz hatası + interpolasyon)
  → Toplam belirsizlik ±%26,6'dan ~%12'ye düşer.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Sequence

from src.models.wind_model import (WindResult, along_track_wind,
                                   wind_speed_at_altitude)

ROOT = Path(__file__).resolve().parents[2]
GFS_CACHE_DIR = ROOT / 'data' / 'cache' / 'gfs'


# ══════════════════════════════════════════════════════════════════════
# SÖZLEŞME
# ══════════════════════════════════════════════════════════════════════
class WindProvider(Protocol):
    """Rüzgâr sağlayıcı sözleşmesi — hepsi bunu uygular."""

    name: str
    is_measured: bool          # gerçek gözlem/tahmin mi, model mi
    uncertainty_pct: float     # bu kaynağın belirsizliği

    def wind_at(self, lat: float, lon: float, altitude_ft: float,
                when: datetime | None = None) -> WindResult:
        ...


# ══════════════════════════════════════════════════════════════════════
# 1. GFS — gerçek ızgara verisi
# ══════════════════════════════════════════════════════════════════════
@dataclass
class GFSWindProvider:
    """
    NOAA GFS ızgarasından rüzgâr okur.

    `xarray` + `cfgrib` kuruluysa ve `GFS_CACHE_DIR` içinde bir GRIB2
    dosyası varsa kullanılır. Aksi halde `available()` False döner.
    """

    name: str = 'NOAA GFS (gerçek ızgara)'
    is_measured: bool = True
    uncertainty_pct: float = 4.0
    cache_dir: Path = GFS_CACHE_DIR

    def available(self) -> bool:
        if not self.cache_dir.is_dir():
            return False
        if not any(self.cache_dir.glob('*.grib2')) and \
           not any(self.cache_dir.glob('*.grb2')):
            return False
        try:
            import xarray  # noqa: F401
            import cfgrib  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self, when: datetime | None = None):
        """En yakın GRIB2 dosyasını aç (basit bellek önbelleği)."""
        import xarray as xr
        files = sorted(self.cache_dir.glob('*.grib2')) + \
            sorted(self.cache_dir.glob('*.grb2'))
        if when and files:
            # dosya adında tarih varsa ona göre seç; yoksa en yenisi
            tag = when.strftime('%Y%m%d')
            dated = [f for f in files if tag in f.name]
            files = dated or files
        last = files[-1]
        cache_key = str(last)
        if getattr(self, '_cache_key', None) != cache_key:
            self._ds = xr.open_dataset(last, engine='cfgrib')
            self._cache_key = cache_key
        return self._ds

    def wind_at(self, lat: float, lon: float, altitude_ft: float,
                when: datetime | None = None) -> WindResult:
        ds = self._load(when)
        # GFS seviyeleri: 10m, 250mb, 300mb, 500mb ... → mb ≈ (1-ft/145442)*1013.25
        pressure = 1013.25 * (1.0 - altitude_ft / 145442.0) ** 5.2559
        levs = [v for v in ds.coords.get('level', ds.coords.get('isobaricInhPa'))
                .values]
        lev = min(levs, key=lambda x: abs(float(x) - pressure))
        d = ds.sel(latitude=lat, longitude=lon, level=lev, method='nearest')
        u = float(d['u'].values)
        v = float(d['v'].values)
        speed = math.hypot(u, v) * 1.943844          # m/s → kt
        # Meteorolojik yön = rüzgârın GELDİĞİ yön
        direction = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
        return WindResult(
            speed_kt=round(speed, 1),
            direction_deg=round(direction, 1),
            along_track_kt=0.0,   # çağıran rota yönüyle hesaplar
            cross_track_kt=0.0,
            source=f'{self.name} · {lev} hPa · {lat:.2f},{lon:.2f}',
        )


# ══════════════════════════════════════════════════════════════════════
# 2. Mevsimsel — bugünkü davranış (yedek)
# ══════════════════════════════════════════════════════════════════════
@dataclass
class SeasonalProvider:
    """
    Klimatolojik profil. GFS yoksa kullanılır — sistem çalışmaya devam eder
    ama `source` alanı bunun bir VARSAYIM olduğunu söyler.
    """

    name: str = 'Mevsimsel klimatoloji (VARSAYIM)'
    is_measured: bool = False
    uncertainty_pct: float = 22.2
    default_dir: float = 270.0        # batı rüzgârı (Kuzey yarımküre)

    def wind_at(self, lat: float, lon: float, altitude_ft: float,
                when: datetime | None = None) -> WindResult:
        speed = wind_speed_at_altitude(altitude_ft)
        return WindResult(
            speed_kt=round(speed, 1),
            direction_deg=self.default_dir,
            along_track_kt=0.0,
            cross_track_kt=0.0,
            source=f'{self.name} · batı rüzgârı {self.default_dir:.0f}°',
        )


# ══════════════════════════════════════════════════════════════════════
# 3. Rüzgârsız — referans senaryo
# ══════════════════════════════════════════════════════════════════════
@dataclass
class NoWindProvider:
    name: str = 'Rüzgârsız (referans)'
    is_measured: bool = False
    uncertainty_pct: float = 0.0

    def wind_at(self, lat: float, lon: float, altitude_ft: float,
                when: datetime | None = None) -> WindResult:
        return WindResult(speed_kt=0.0, direction_deg=0.0, along_track_kt=0.0,
                          cross_track_kt=0.0, source=self.name)


# ══════════════════════════════════════════════════════════════════════
# SEÇİCİ + ROTA YARDIMCILARI
# ══════════════════════════════════════════════════════════════════════
_provider: WindProvider | None = None


def get_wind_provider(force: str | None = None) -> WindProvider:
    """
    En iyi mevcut sağlayıcıyı döndür.

    Args:
        force: 'gfs' | 'seasonal' | 'none' — elle seç (test için)

    Returns:
        WindProvider
    """
    global _provider
    if force == 'none':
        return NoWindProvider()
    if force == 'seasonal':
        return SeasonalProvider()
    if force == 'gfs':
        g = GFSWindProvider()
        if not g.available():
            raise RuntimeError(
                'GFS verisi yok. data/cache/gfs/ altına bir GRIB2 dosyası '
                'koy ve `pip install cfgrib eccodes xarray` çalıştır.')
        return g
    if _provider is not None:
        return _provider
    g = GFSWindProvider()
    _provider = g if g.available() else SeasonalProvider()
    return _provider


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """İki nokta arasındaki başlangıç yönü (derece, kuzey=0)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def route_wind(provider: WindProvider, altitude_ft: float,
               track_deg: float, lat: float, lon: float,
               when: datetime | None = None) -> WindResult:
    """
    Tek noktada rüzgârı oku ve ROTA BİLEŞENİNİ hesapla.

    `along_track_kt` pozitifse kuyruk rüzgârı (yakıt azaltır), negatifse
    karşı rüzgâr (yakıt artırır).
    """
    w = provider.wind_at(lat, lon, altitude_ft, when)
    delta = math.radians(track_deg - (w.direction_deg + 180.0))
    return WindResult(
        speed_kt=w.speed_kt,
        direction_deg=w.direction_deg,
        along_track_kt=round(w.speed_kt * math.cos(delta), 1),
        cross_track_kt=round(w.speed_kt * math.sin(delta), 1),
        source=w.source,
    )


def route_wind_along_route(
    provider: WindProvider,
    coords: Sequence[tuple[float, float]],
    altitude_ft: float = 35_000.0,
    when: datetime | None = None,
) -> WindResult:
    """
    Rotayı nokta nokta örnekleyip mesafe ağırlıklı ortalama rüzgâr döndür.

    Bu, tek bir "tüm rota için ortalama rüzgâr" varsayımından çok daha
    doğrudur: İstanbul→Amsterdam'da Türkiye üzerinde farklı, Alpler
    üzerinde farklı rüzgâr vardır.

    Args:
        provider: rüzgâr sağlayıcı
        coords  : [(lat, lon), ...] en az 2 nokta
        altitude_ft: cruise irtifası
        when    : tarih (GFS dosya seçimi için)

    Returns:
        WindResult — along_track_kt mesafe ağırlıklı ortalama
    """
    if len(coords) < 2:
        raise ValueError('En az iki koordinat gerekli')

    def dist(a, b):
        R = 3440.065
        p1, p2 = math.radians(a[0]), math.radians(b[0])
        dp, dl = p2 - p1, math.radians(b[1] - a[1])
        h = (math.sin(dp / 2) ** 2 +
             math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
        return 2 * R * math.asin(math.sqrt(h))

    total = 0.0
    weighted_along = 0.0
    weighted_cross = 0.0
    weighted_speed = 0.0
    sources: set[str] = set()

    for a, b in zip(coords, coords[1:]):
        seg = dist(a, b)
        if seg <= 0:
            continue
        trk = _bearing(a[0], a[1], b[0], b[1])
        # segment ortasındaki rüzgâr (temsili)
        mlat, mlon = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        r = route_wind(provider, altitude_ft, trk, mlat, mlon, when)
        weighted_along += r.along_track_kt * seg
        weighted_cross += r.cross_track_kt * seg
        weighted_speed += r.speed_kt * seg
        sources.add(r.source)
        total += seg

    if total <= 0:
        raise ValueError('Sıfır uzunluklu rota')

    src = next(iter(sources)) if len(sources) == 1 else f'{len(sources)} segment ortalaması'
    return WindResult(
        speed_kt=round(weighted_speed / total, 1),
        direction_deg=0.0,
        along_track_kt=round(weighted_along / total, 1),
        cross_track_kt=round(weighted_cross / total, 1),
        source=src,
    )


def describe_chain() -> dict:
    """Hangi sağlayıcıların kullanılabilir olduğunu raporla."""
    g = GFSWindProvider()
    active = get_wind_provider()
    return {
        'active': active.name,
        'is_measured': active.is_measured,
        'uncertainty_pct': active.uncertainty_pct,
        'gfs_available': g.available(),
        'gfs_cache_dir': str(GFS_CACHE_DIR),
        'gfs_hint': ('data/cache/gfs/ altına GRIB2 koy + '
                     'pip install cfgrib eccodes xarray'),
        'fallback_uncertainty_pct': SeasonalProvider().uncertainty_pct,
    }


if __name__ == '__main__':
    d = describe_chain()
    print('RÜZGÂR SAĞLAYICI ZİNCİRİ')
    print('─' * 56)
    for k, v in d.items():
        print(f'  {k:26s}: {v}')
    print()
    prov = get_wind_provider()
    for alt in (10_000, 35_000, 39_000):
        r = route_wind(prov, alt, track_deg=295, lat=41.0, lon=29.0)
        print(f'  FL{alt//100:03d} · 295° rota · {r.speed_kt:5.1f} kt · '
              f'bileşen {r.along_track_kt:+6.1f} kt')
        print(f'         kaynak: {r.source}')
