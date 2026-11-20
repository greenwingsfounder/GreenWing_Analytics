# src/utils.py

"""
GreenWing Analytics — Ortak Yardımcı Fonksiyonlar
══════════════════════════════════════════════════

Birden fazla modül tarafından kullanılan paylaşımlı fonksiyonlar.

Bu dosya:
    • Heading hesabı (coğrafi, great circle)
    • Haversine mesafe hesabı
    • Günlük frekans tahmini
    • Mevsimsel rüzgar tahmini
    • Format yardımcıları (para, ağırlık)
    • Uçak tipi doğrulama

NEDEN AYRI DOSYA:
─────────────────
    Aynı fonksiyonu 5 farklı dosyada yazmak:
        • Kod tekrarı (DRY ihlali)
        • Bir yerde düzeltirsen diğerlerini unutursun
        • Tutarsızlık riski

    Tek yerde toplamak:
        • Tek noktada değişiklik
        • Tutarlılık garantisi
        • Test kolaylığı

KULLANIM:
─────────
    from src.utils import (
        calculate_initial_heading,
        haversine_distance,
        estimate_daily_frequency,
        get_seasonal_wind_estimate,
        format_currency,
        format_weight,
    )

    heading = calculate_initial_heading(41.275, 28.752, 51.470, -0.454)
    distance = haversine_distance(41.275, 28.752, 51.470, -0.454)
    wind = get_seasonal_wind_estimate(310, month=1)

Kaynak:
───────
    Aviation Formulary by Ed Williams (heading hesabı)
    ICAO Doc 7488 (atmosfer referansları)
    Eurocontrol istatistikleri (rüzgar tahminleri)
"""

from __future__ import annotations

import numpy as np
from datetime import datetime
from typing import Optional


# ═══════════════════════════════════════════════════════════
# BÖLÜM 1: COĞRAFİ HESAPLAMALAR
# ═══════════════════════════════════════════════════════════

def calculate_initial_heading(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """
    İki nokta arası initial great circle heading.

    Coğrafi heading: Kuzey=0°, Doğu=90°, Güney=180°, Batı=270°

    Bu FONKSİYON ÇOK ÖNEMLİDİR çünkü:
        Yön kuralı (RVSM) heading'e bağlı.
        Yanlış heading = yanlış FL seçenekleri = yanlış optimizasyon.

    Eski yanlış yöntem (kullanma):
        heading = atan2(dlon, dlat)  → MATEMATİKSEL açı, coğrafi DEĞİL

    Doğru yöntem (bu fonksiyon):
        Great circle initial bearing formülü.
        Dünya'nın küresel şeklini hesaba katar.

    Args:
        lat1, lon1: Kalkış koordinatları (derece)
        lat2, lon2: Varış koordinatları (derece)

    Returns:
        float: Heading (0-360 derece)
               0° = Kuzey, 90° = Doğu, 180° = Güney, 270° = Batı

    Örnekler:
        IST → LON: ~310° (kuzeybatı, westbound)
        IST → DXB: ~145° (güneydoğu, eastbound)
        IST → ANK: ~100° (doğu, eastbound)
        IST → FRA: ~315° (kuzeybatı, westbound)

    Doğrulama:
        gcmap.com'da rota çizerek heading kontrolü yapılabilir.

    Kaynak:
        Aviation Formulary by Ed Williams
        https://edwilliams.org/avform147.htm

    Nerede kullanılır:
        altitude_optimizer → yön kuralı (eastbound/westbound FL seçimi)
        scripts/02_analyze → heading otomatik hesaplama
    """
    lat1_r = np.radians(lat1)
    lon1_r = np.radians(lon1)
    lat2_r = np.radians(lat2)
    lon2_r = np.radians(lon2)

    dlon = lon2_r - lon1_r

    x = np.sin(dlon) * np.cos(lat2_r)
    y = (
        np.cos(lat1_r) * np.sin(lat2_r)
        - np.sin(lat1_r) * np.cos(lat2_r) * np.cos(dlon)
    )

    heading = np.degrees(np.arctan2(x, y))
    heading = heading % 360

    return float(heading)


def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """
    İki nokta arası great circle mesafesi (Nm).

    Haversine formülü Dünya'nın küresel şeklini hesaba katar.
    Düz yüzey yaklaşımından çok daha doğru (özellikle uzun mesafelerde).

    Args:
        lat1, lon1: Birinci nokta (derece)
        lat2, lon2: İkinci nokta (derece)

    Returns:
        float: Mesafe (deniz mili / Nm)

    Örnekler:
        IST → LON: ~1560 Nm
        IST → ANK: ~190 Nm
        IST → DXB: ~1550 Nm
        IST → FRA: ~1000 Nm

    Doğruluk:
        Küresel model: ±0.3% hata (elipsoid vs sphere)
        Havacılık için yeterli doğruluk.

    Nerede kullanılır:
        airport_database → havalimanları arası mesafe
        flight_analyzer → great circle vs gerçek rota karşılaştırması
        scripts → rota mesafesi hesabı
    """
    R_earth_nm = 3440.065  # Dünya yarıçapı (deniz mili)

    lat1_r = np.radians(lat1)
    lon1_r = np.radians(lon1)
    lat2_r = np.radians(lat2)
    lon2_r = np.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    )

    # NaN güvenliği
    a = np.clip(a, 0, 1)

    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

    return float(R_earth_nm * c)


# ═══════════════════════════════════════════════════════════
# BÖLÜM 2: OPERASYONEL TAHMİNLER
# ═══════════════════════════════════════════════════════════

def estimate_daily_frequency(distance_nm: float) -> int:
    """
    Rota mesafesine göre tahmini günlük sefer sayısı.

    Kısa rota → yüksek frekans (İstanbul-Ankara günde 6+)
    Uzun rota → düşük frekans (İstanbul-NewYork günde 1)

    Args:
        distance_nm: Rota uzunluğu (Nm)

    Returns:
        int: Tahmini günlük sefer sayısı

    Örnekler:
        estimate_daily_frequency(190)  → 6  (IST-ANK)
        estimate_daily_frequency(300)  → 4  (IST-AYT)
        estimate_daily_frequency(1560) → 2  (IST-LON)
        estimate_daily_frequency(5000) → 1  (IST-JFK)

    Not:
        ±30% hata payı. Gerçek schedule müşteriden alınmalı.
        Yıllık projeksiyon için bu değer yerine müşteri
        verisi kullanılmalıdır.

    Kaynak:
        OAG schedule veritabanı genel eğilimi

    Nerede kullanılır:
        assumptions.py → annual_projection() içinde
        scripts/02_analyze → yıllık tasarruf hesabı
    """
    if distance_nm < 300:
        return 6     # Ultra kısa iç hat
    elif distance_nm < 800:
        return 4     # Kısa mesafe
    elif distance_nm < 1500:
        return 2     # Orta mesafe (Avrupa)
    elif distance_nm < 4000:
        return 1     # Uzun mesafe
    else:
        return 1     # Ultra uzun mesafe


def get_seasonal_wind_estimate(
    heading_deg: float,
    month: Optional[int] = None,
) -> dict[int, float]:
    """
    Mevsimsel ortalama rüzgar tahmini.

    Jet stream genellikle batıdan doğuya eser.
    Westbound uçuşlar headwind alır → yavaşlar → daha çok yakıt.
    Eastbound uçuşlar tailwind alır → hızlanır → daha az yakıt.

    Kış: Jet stream güçlü (70-120 kt)
    Yaz: Jet stream zayıf (30-60 kt)

    Bu ORTALAMA tahmindir. Gerçek rüzgar günlük değişir.
    Raporlarda "ortalama rüzgar tahmini kullanıldı" notu ekle.

    Args:
        heading_deg: Uçuş heading'i (derece, 0-360)
        month      : Ay (1-12). None → mevcut ay.

    Returns:
        dict: {altitude_ft: wind_component_kts}
              Pozitif = headwind (karşı rüzgar, kötü)
              Negatif = tailwind (kuyruk rüzgarı, iyi)

    Örnekler:
        # IST→LON (westbound, ~310°, Ocak)
        wind = get_seasonal_wind_estimate(310, month=1)
        # → {30000: 21, 32000: 35, 34000: 49, 36000: 63, 38000: 70, 40000: 56}
        # Headwind: jet stream karşı

        # LON→IST (eastbound, ~130°, Ocak)
        wind = get_seasonal_wind_estimate(130, month=1)
        # → {30000: -21, ..., 38000: -70, ...}
        # Tailwind: jet stream arka

    Kaynak:
        Eurocontrol istatistikleri
        NOAA GFS klimatoloji verileri

    Nerede kullanılır:
        altitude_optimizer → rüzgarlı irtifa optimizasyonu
        scripts/02_analyze → wind_profile parametresi
    """
    if month is None:
        month = datetime.now().month

    # Mevsimsel jet stream gücü (FL300-FL400 arası ortalama)
    winter_months = [11, 12, 1, 2, 3]
    summer_months = [6, 7, 8]

    if month in winter_months:
        jet_strength = 70   # kt, kış ortalaması
    elif month in summer_months:
        jet_strength = 35   # kt, yaz ortalaması
    else:
        jet_strength = 50   # kt, ilkbahar/sonbahar

    # Heading'e göre rüzgar yönü
    # Westbound (225-315°): Headwind (jet stream karşı)
    # Eastbound (45-135°): Tailwind (jet stream arka)
    # Kuzey/Güney: Minimal crosswind bileşeni

    if 225 <= heading_deg <= 315:
        # Westbound — headwind (pozitif)
        sign = 1
        factors = [0.3, 0.5, 0.7, 0.9, 1.0, 0.8]

    elif 45 <= heading_deg <= 135:
        # Eastbound — tailwind (negatif)
        sign = -1
        factors = [0.3, 0.5, 0.7, 0.9, 1.0, 0.8]

    else:
        # Kuzey/Güney — minimal crosswind bileşeni
        sign = 1
        factors = [0.1, 0.1, 0.15, 0.15, 0.1, 0.1]

    altitudes = [30000, 32000, 34000, 36000, 38000, 40000]

    wind = {}
    for alt, factor in zip(altitudes, factors):
        wind[alt] = int(jet_strength * factor * sign)

    return wind


# ═══════════════════════════════════════════════════════════
# BÖLÜM 3: FORMAT YARDIMCILARI
# ═══════════════════════════════════════════════════════════

def format_currency(amount: float) -> str:
    """
    Para birimini okunabilir formata çevir.

    Args:
        amount: USD miktarı

    Returns:
        str: Formatlanmış metin

    Örnekler:
        format_currency(442)       → "$442"
        format_currency(1234)      → "$1,234"
        format_currency(198354)    → "$198,354"
        format_currency(1500000)   → "$1.5M"
        format_currency(25000000)  → "$25.0M"

    Nerede kullanılır:
        report_generator → raporlarda para değerleri
        scripts → ekran çıktısında
    """
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    elif abs(amount) >= 1_000:
        return f"${amount:,.0f}"
    elif abs(amount) >= 1:
        return f"${amount:.0f}"
    else:
        return f"${amount:.2f}"


def format_weight(kg: float) -> str:
    """
    Ağırlığı okunabilir formata çevir.

    Args:
        kg: Kilogram

    Returns:
        str: Formatlanmış metin

    Örnekler:
        format_weight(325)     → "325 kg"
        format_weight(1250)    → "1.3 ton"
        format_weight(12500)   → "12.5 ton"
        format_weight(142000)  → "142.0 ton"

    Nerede kullanılır:
        report_generator → raporlarda ağırlık değerleri
        scripts → ekran çıktısında
    """
    if abs(kg) >= 1000:
        return f"{kg / 1000:.1f} ton"
    else:
        return f"{kg:.0f} kg"


def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Yüzde değerini formata çevir.

    Args:
        value   : Yüzde değeri (örn: 2.85)
        decimals: Ondalık basamak

    Returns:
        str: Formatlanmış metin

    Örnekler:
        format_percentage(2.85) → "%2.9"
        format_percentage(0.5)  → "%0.5"
        format_percentage(15.0) → "%15.0"
    """
    return f"%{value:.{decimals}f}"


def format_flight_level(altitude_ft: float) -> str:
    """
    İrtifayı Flight Level formatına çevir.

    Args:
        altitude_ft: İrtifa (feet)

    Returns:
        str: "FL350" gibi metin

    Örnekler:
        format_flight_level(35000) → "FL350"
        format_flight_level(37000) → "FL370"
        format_flight_level(41000) → "FL410"
    """
    fl = int(round(altitude_ft / 100))
    return f"FL{fl}"


# ═══════════════════════════════════════════════════════════
# BÖLÜM 4: UÇAK TİPİ DOĞRULAMA
# ═══════════════════════════════════════════════════════════

def validate_aircraft_type(ac_type: str) -> bool:
    """
    Uçak tipinin aircraft_database.yaml'da olup olmadığını kontrol et.

    Args:
        ac_type: ICAO uçak tipi kodu ('B738', 'A320', ...)

    Returns:
        bool: True → destekleniyor

    Raises:
        ValueError: Desteklenmeyen uçak tipi

    Örnekler:
        validate_aircraft_type('B738') → True
        validate_aircraft_type('XXXX') → ValueError

    Nerede kullanılır:
        scripts → kullanıcı girdisi kontrol
        flight_analyzer → analiz öncesi kontrol
    """
    import yaml
    import os

    config_path = os.path.join(
        os.path.dirname(__file__), '..', 'config', 'aircraft_database.yaml'
    )

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"aircraft_database.yaml bulunamadı: {config_path}"
        )

    with open(config_path, 'r', encoding='utf-8') as f:
        db = yaml.safe_load(f)

    supported = sorted(db.get('aircraft_types', {}).keys())

    if ac_type in supported:
        return True

    raise ValueError(
        f"Desteklenmeyen uçak tipi: '{ac_type}'. "
        f"Desteklenen: {supported}"
    )


def get_supported_aircraft_types() -> list[str]:
    """
    Desteklenen uçak tiplerinin listesini döndür.

    Returns:
        list[str]: ICAO uçak tipi kodları

    Örnekler:
        types = get_supported_aircraft_types()
        # ['A20N', 'A320', 'A321', 'A21N', 'A350', 'A380',
        #  'B38M', 'B738', 'B77W', 'B788', 'B789']
    """
    import yaml
    import os

    config_path = os.path.join(
        os.path.dirname(__file__), '..', 'config', 'aircraft_database.yaml'
    )

    if not os.path.exists(config_path):
        return []

    with open(config_path, 'r', encoding='utf-8') as f:
        db = yaml.safe_load(f)

    return sorted(db.get('aircraft_types', {}).keys())


# ═══════════════════════════════════════════════════════════
# BÖLÜM 5: ZAMAN YARDIMCILARI
# ═══════════════════════════════════════════════════════════

def hours_to_hhmm(hours: float) -> str:
    """
    Ondalık saati HH:MM formatına çevir.

    Args:
        hours: Saat (ondalık)

    Returns:
        str: "HH:MM" formatı

    Örnekler:
        hours_to_hhmm(3.5)  → "3:30"
        hours_to_hhmm(1.75) → "1:45"
        hours_to_hhmm(0.25) → "0:15"
    """
    h = int(hours)
    m = int((hours - h) * 60)
    return f"{h}:{m:02d}"


def minutes_to_hhmm(minutes: float) -> str:
    """
    Dakikayı HH:MM formatına çevir.

    Args:
        minutes: Dakika

    Returns:
        str: "HH:MM" formatı

    Örnekler:
        minutes_to_hhmm(210)  → "3:30"
        minutes_to_hhmm(45)   → "0:45"
        minutes_to_hhmm(1440) → "24:00"
    """
    h = int(minutes // 60)
    m = int(minutes % 60)
    return f"{h}:{m:02d}"


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_utils() -> bool:
    """
    Utils fonksiyonları doğrulama testleri.

    Çalıştırma:
        python -m src.utils
    """
    print("\n" + "=" * 60)
    print("  UTILS.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests = 0

    def check(name: str, actual, expected, tol: float = 0.01) -> None:
        nonlocal tests
        tests += 1
        if isinstance(expected, str):
            if actual == expected:
                print(f"  ✅ {name} = {actual}")
            else:
                errors.append(f"{name}: '{actual}' ≠ '{expected}'")
                print(f"  ❌ {name}: '{actual}' ≠ '{expected}'")
        else:
            if abs(float(actual) - float(expected)) <= tol:
                print(f"  ✅ {name} = {actual}")
            else:
                errors.append(f"{name}: {actual} ≠ {expected}")
                print(f"  ❌ {name}: {actual} ≠ {expected}")

    def check_range(name: str, actual: float, lo: float, hi: float) -> None:
        nonlocal tests
        tests += 1
        if lo <= actual <= hi:
            print(f"  ✅ {name} = {actual:.1f} [{lo}, {hi}]")
        else:
            errors.append(f"{name}: {actual} dışı [{lo}, {hi}]")
            print(f"  ❌ {name} = {actual} [{lo}, {hi}]")

    # ─── [1] Heading hesabı ───────────────────────────────
    print("\n  [1] Heading Hesabı")

    # IST → LON: ~310° (kuzeybatı)
    h_ist_lon = calculate_initial_heading(41.275, 28.752, 51.470, -0.454)
    check_range("IST→LON heading", h_ist_lon, 300, 320)

    # IST → DXB: ~145° (güneydoğu)
    h_ist_dxb = calculate_initial_heading(41.275, 28.752, 25.253, 55.364)
    check_range("IST→DXB heading", h_ist_dxb, 130, 160)

    # IST → ANK: ~95° (doğu)
    h_ist_ank = calculate_initial_heading(41.275, 28.752, 40.128, 32.995)
    check_range("IST→ANK heading", h_ist_ank, 80, 120)

    # IST → FRA: ~310° (kuzeybatı)
    h_ist_fra = calculate_initial_heading(41.275, 28.752, 50.033, 8.571)
    check_range("IST→FRA heading", h_ist_fra, 305, 325)

    # Heading aralık kontrolü (her zaman 0-360)
    tests += 1
    all_headings = [h_ist_lon, h_ist_dxb, h_ist_ank, h_ist_fra]
    if all(0 <= h < 360 for h in all_headings):
        print("  ✅ Tüm heading'ler 0-360 aralığında")
    else:
        errors.append("Heading aralık hatası")
        print("  ❌ Heading aralık hatası")

    # Yön kuralı kontrolü
    # IST→LON ~310° → westbound → çift FL
    tests += 1
    if 180 <= h_ist_lon < 360:
        print(f"  ✅ IST→LON ({h_ist_lon:.0f}°) = Westbound (çift FL)")
    else:
        errors.append("IST→LON westbound olmalı")

    # IST→DXB ~145° → eastbound → tek FL
    tests += 1
    if 0 <= h_ist_dxb < 180:
        print(f"  ✅ IST→DXB ({h_ist_dxb:.0f}°) = Eastbound (tek FL)")
    else:
        errors.append("IST→DXB eastbound olmalı")

    # ─── [2] Haversine mesafe ─────────────────────────────
    print("\n  [2] Haversine Mesafe")

    d_ist_lon = haversine_distance(41.275, 28.752, 51.470, -0.454)
    check_range("IST→LON mesafe", d_ist_lon, 1500, 1600)

    d_ist_ank = haversine_distance(41.275, 28.752, 40.128, 32.995)
    check_range("IST→ANK mesafe", d_ist_ank, 180, 200)

    d_ist_dxb = haversine_distance(41.275, 28.752, 25.253, 55.364)
    check_range("IST→DXB mesafe", d_ist_dxb, 1500, 1600)

    d_ist_fra = haversine_distance(41.275, 28.752, 50.033, 8.571)
    check_range("IST→FRA mesafe", d_ist_fra, 950, 1050)

    # Sıfır mesafe (aynı nokta)
    d_zero = haversine_distance(41.275, 28.752, 41.275, 28.752)
    check("aynı nokta mesafe", d_zero, 0.0, 0.1)

    # Mesafe her zaman pozitif
    tests += 1
    if d_ist_lon > 0 and d_ist_ank > 0 and d_ist_dxb > 0:
        print("  ✅ Tüm mesafeler pozitif")
    else:
        errors.append("Negatif mesafe")

    # Uzun > Kısa
    tests += 1
    if d_ist_lon > d_ist_ank:
        print(f"  ✅ IST→LON ({d_ist_lon:.0f}) > IST→ANK ({d_ist_ank:.0f})")
    else:
        errors.append("Mesafe sıralaması yanlış")

    # ─── [3] Günlük frekans ───────────────────────────────
    print("\n  [3] Günlük Frekans Tahmini")

    check("freq 190 Nm",  estimate_daily_frequency(190),  6, 0.1)
    check("freq 500 Nm",  estimate_daily_frequency(500),  4, 0.1)
    check("freq 1560 Nm", estimate_daily_frequency(1560), 2, 0.1)
    check("freq 5000 Nm", estimate_daily_frequency(5000), 1, 0.1)

    # Kısa rota > uzun rota frekansı
    tests += 1
    if estimate_daily_frequency(190) > estimate_daily_frequency(5000):
        print("  ✅ Kısa rota frekansı > Uzun rota")
    else:
        errors.append("Frekans sıralaması yanlış")

    # ─── [4] Mevsimsel rüzgar ─────────────────────────────
    print("\n  [4] Mevsimsel Rüzgar Tahmini")

    # Westbound kış — headwind (pozitif)
    wind_west_winter = get_seasonal_wind_estimate(310, month=1)
    tests += 1
    if wind_west_winter.get(38000, 0) > 0:
        print(f"  ✅ Westbound kış FL380: +{wind_west_winter[38000]} kt headwind")
    else:
        errors.append("Westbound kış headwind olmalı")

    # Eastbound kış — tailwind (negatif)
    wind_east_winter = get_seasonal_wind_estimate(130, month=1)
    tests += 1
    if wind_east_winter.get(38000, 0) < 0:
        print(f"  ✅ Eastbound kış FL380: {wind_east_winter[38000]} kt tailwind")
    else:
        errors.append("Eastbound kış tailwind olmalı")

    # Kış > yaz rüzgar
    wind_west_summer = get_seasonal_wind_estimate(310, month=7)
    tests += 1
    if abs(wind_west_winter.get(38000, 0)) > abs(wind_west_summer.get(38000, 0)):
        print(f"  ✅ Kış({wind_west_winter[38000]}) > Yaz({wind_west_summer[38000]}) rüzgar")
    else:
        errors.append("Kış rüzgarı yazdan güçlü olmalı")

    # 6 irtifa seviyesi olmalı
    tests += 1
    if len(wind_west_winter) == 6:
        print(f"  ✅ 6 irtifa seviyesi: {sorted(wind_west_winter.keys())}")
    else:
        errors.append(f"6 irtifa beklendi: {len(wind_west_winter)}")

    # None month → mevcut ay kullanılır
    wind_auto = get_seasonal_wind_estimate(310)
    tests += 1
    if len(wind_auto) == 6:
        print(f"  ✅ Otomatik ay (month=None) çalışıyor")
    else:
        errors.append("Otomatik ay çalışmıyor")

    # ─── [5] Format yardımcıları ──────────────────────────
    print("\n  [5] Format Yardımcıları")

    # Para
    check("format_currency(442)",     format_currency(442),     "$442")
    check("format_currency(1234)",    format_currency(1234),    "$1,234")
    check("format_currency(198354)",  format_currency(198354),  "$198,354")
    check("format_currency(1500000)", format_currency(1500000), "$1.5M")

    # Ağırlık
    check("format_weight(325)",    format_weight(325),    "325 kg")
    check("format_weight(1250)",   format_weight(1250),   "1.3 ton")
    check("format_weight(12500)",  format_weight(12500),  "12.5 ton")

    # Yüzde
    check("format_percentage(2.85)", format_percentage(2.85), "%2.9")
    check("format_percentage(15.0)", format_percentage(15.0), "%15.0")

    # Flight Level
    check("format_fl(35000)", format_flight_level(35000), "FL350")
    check("format_fl(37000)", format_flight_level(37000), "FL370")
    check("format_fl(41000)", format_flight_level(41000), "FL410")

    # Zaman
    check("hours_to_hhmm(3.5)",    hours_to_hhmm(3.5),    "3:30")
    check("hours_to_hhmm(1.75)",   hours_to_hhmm(1.75),   "1:45")
    check("minutes_to_hhmm(210)",  minutes_to_hhmm(210),  "3:30")
    check("minutes_to_hhmm(45)",   minutes_to_hhmm(45),   "0:45")

    # ─── [6] Uçak tipi doğrulama ─────────────────────────
    print("\n  [6] Uçak Tipi Doğrulama")

    tests += 1
    try:
        if validate_aircraft_type('B738'):
            print("  ✅ validate_aircraft_type('B738') = True")
    except Exception as e:
        errors.append(f"B738 doğrulama: {e}")
        print(f"  ❌ B738: {e}")

    tests += 1
    try:
        validate_aircraft_type('XXXX')
        errors.append("XXXX ValueError vermedi")
        print("  ❌ XXXX hata vermedi")
    except ValueError:
        print("  ✅ validate_aircraft_type('XXXX') → ValueError")
    except (KeyboardInterrupt, SystemExit):
        raise

    tests += 1
    supported = get_supported_aircraft_types()
    if len(supported) >= 8:
        print(f"  ✅ {len(supported)} uçak tipi: {supported}")
    else:
        errors.append(f"Az uçak tipi: {len(supported)}")
        print(f"  ❌ Az: {supported}")

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


# ═══════════════════════════════════════════════════════════
# ÇALIŞTIRMA
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    validate_utils()

