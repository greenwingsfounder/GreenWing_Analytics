"""
GreenWing Analytics — Merkezi Ayarlar ve Sabitler
══════════════════════════════════════════════════

Bu dosya projenin TÜM sabitlerini tek yerde toplar.

NEDEN TEK YER:
──────────────
Aynı sabiti 10 farklı dosyada yazmak:
    • Bir yerde 9.81, diğerinde 9.80665 yazarsın → tutarsızlık
    • Değiştirmek istersen 10 dosya düzenlersin
    • Kaynak belli olmaz

Tek yerde toplamak:
    • Tutarlılık garantisi
    • Tek noktada değişiklik
    • Kaynak belgelenmiş
    • "Bu sabit nereden geliyor?" sorusunun cevabı burada

KATEGORİLER:
────────────
1. Fiziksel sabitler    → ASLA değişmez (fizik yasası)
2. ISA sabitleri        → ASLA değişmez (ICAO standardı)
3. Birim dönüşümler     → ASLA değişmez (tanım gereği)
4. Emisyon sabitleri    → ASLA değişmez (kimya)
5. Yakıt özellikleri    → Pratikte sabit
6. CORSIA ayarları      → Düzenleme değişirse güncellenir
7. Dashboard ayarları   → Deployment'a göre değişir
8. Dosya yolları        → Proje yapısına göre

KULLANIM:
─────────
    from config.settings import GRAVITY, EI_CO2, ISA_T0
    from config.settings import CARBON_CREDIT_PRICE_USD

GÜNCELLEME KURALLARI:
─────────────────────
    Kategori 1-4: Değiştirme. Fizik/kimya değişmiyor.
    Kategori 5:   Çok nadiren. Yeni yakıt tipi eklenirse.
    Kategori 6:   ICAO kararlarına göre (yıllık kontrol).
    Kategori 7-8: İhtiyaca göre.

KAYNAK:
───────
    ICAO Doc 7488 (Standard Atmosphere)
    NIST SI Reference
    ICAO CORSIA SARP Annex 16 Vol IV
    ASTM D1655 (Jet-A1 Specification)
    IPCC Emission Factors
"""

import os
from dotenv import load_dotenv

# Proje kök dizini (bu dosyanın bulunduğu src/config/ dizininden iki üst)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# .env dosyasının tam yolu
_ENV_PATH = os.path.join(_PROJECT_ROOT, '.env')

# .env dosyasını KESİN olarak bu yoldan yükle
# override=True → varsa boş env değişkenlerini de ezer
load_dotenv(dotenv_path=_ENV_PATH, override=True)

# Kullanım örneği:
# OPENSKY_USERNAME = os.getenv('OPENSKY_USERNAME')
# OPENSKY_PASSWORD = os.getenv('OPENSKY_PASSWORD')

# ═══════════════════════════════════════════════════════════
# 1. FİZİKSEL SABİTLER
# ═══════════════════════════════════════════════════════════
# Kaynak: NIST, ICAO
# DEĞİŞİR Mİ: ASLA. Fizik yasaları.

GRAVITY = 9.80665
"""
Yerçekimi ivmesi (m/s²).
Kaldırma kuvveti hesabında: L = W × g
Her ağırlık → kuvvet dönüşümünde kullanılır.
Kaynak: 3. CGPM (1901), standart yerçekimi.
"""

R_AIR = 287.05
"""
Kuru hava spesifik gaz sabiti (J/(kg·K)).
İdeal gaz denklemi: P = ρ × R × T
Atmosfer hesaplarının temeli.
Kaynak: NIST, kuru hava moleküler ağırlığından türetilmiş.
"""

GAMMA = 1.4
"""
Havanın spesifik ısı oranı (cp/cv).
Ses hızı: a = √(γ × R × T)
Kompresibilite hesaplarında.
Kaynak: Kuru hava termodinamiği.
Not: Nem ile çok az değişir (ihmal edilebilir).
"""

R_EARTH = 6371000
"""
Dünya ortalama yarıçapı (metre).
Haversine mesafe hesabında kullanılır.
Kaynak: WGS-84 elipsoidi ortalama değeri.
Not: Ekvator vs kutup farkı ~21 km. Pratikte ortalama yeterli.
"""


# ═══════════════════════════════════════════════════════════
# 2. ISA (International Standard Atmosphere) SABİTLERİ
# ═══════════════════════════════════════════════════════════
# Kaynak: ICAO Doc 7488 (Manual of the ICAO Standard Atmosphere)
# DEĞİŞİR Mİ: ASLA. Uluslararası standart.

ISA_T0 = 288.15
"""
ISA deniz seviyesi sıcaklığı (Kelvin).
= 15°C
Tüm ISA hesaplarının başlangıç referansı.
"""

ISA_P0 = 101325.0
"""
ISA deniz seviyesi basıncı (Pascal).
= 1013.25 hPa = 29.92 inHg
Altimetre kalibrasyonu ve basınç oranı (δ) hesabı referansı.
"""

ISA_RHO0 = 1.225
"""
ISA deniz seviyesi hava yoğunluğu (kg/m³).
P = ρ × R × T ilişkisinden: 101325 / (287.05 × 288.15) = 1.225
Dinamik basınç ve yoğunluk oranı (σ) hesabı referansı.
"""

ISA_LAPSE_RATE = -0.0065
"""
Troposfer sıcaklık düşüş oranı (K/m).
Her 1000 metre yükselişte sıcaklık 6.5°C azalır.
0 ile 11000 m arası geçerli.
Not: Negatif değer (sıcaklık azalıyor).
"""

TROPOPAUSE_ALT = 11000
"""
Tropopoz irtifası (metre).
= ~36089 feet
Bu irtifanın üstünde sıcaklık sabit kalır (216.65 K).
Stratosfer başlangıcı.
"""


# ═══════════════════════════════════════════════════════════
# 3. BİRİM DÖNÜŞÜM SABİTLERİ
# ═══════════════════════════════════════════════════════════
# DEĞİŞİR Mİ: ASLA. Tanım gereği sabit.
# NOT: units.py bu sabitleri kendi içinde de tutar.
#      Burada da referans olarak bulunur.
#      KULLANIM: Tercihen units.py üzerinden dönüşüm yap.

KNOT_TO_MS = 0.514444
"""
1 knot = 0.514444 m/s
Havacılık hız birimi dönüşümü.
"""

FT_TO_M = 0.3048
"""
1 foot = 0.3048 metre
Havacılık irtifa birimi dönüşümü.
Tanım gereği TAM OLARAK bu değer.
"""

NM_TO_M = 1852.0
"""
1 deniz mili (nautical mile) = 1852.0 metre
Havacılık mesafe birimi dönüşümü.
Tanım gereği TAM OLARAK bu değer.
Not: Statute mile = 1609.344 m → FARKLI! Karıştırma.
"""

KG_TO_LBS = 2.20462
"""
1 kilogram = 2.20462 pound
Ağırlık dönüşümü. ABD ve İngiltere hâlâ pound kullanır.
"""


# ═══════════════════════════════════════════════════════════
# 4. EMİSYON SABİTLERİ
# ═══════════════════════════════════════════════════════════
# Kaynak: ICAO CORSIA, DEFRA, IPCC AR6
# DEĞİŞİR Mİ: ASLA. Kimyasal sabitler.

EI_CO2 = 3.16
"""
CO2 emission index (kg CO2 / kg Jet-A1 yakıt).
Jet-A1 kimyasal formülü C12H23 (yaklaşık).
Yanma: CnHm + O2 → CO2 + H2O
1 kg yakıt → 3.16 kg CO2

Bu CORSIA'nın resmi değeri. Tüm havacılık emisyon
raporlamasında bu katsayı kullanılır.
Kaynak: ICAO CORSIA SARP, IPCC Guidelines Vol 2 Ch 3.
"""

EI_H2O = 1.24
"""
H2O emission index (kg H2O / kg yakıt).
Su buharı emisyonu. Contrail oluşumunda önemli.
Non-CO2 iklim etkisi hesaplamalarında kullanılır.
"""

EI_SO2 = 0.001
"""
SO2 emission index (kg SO2 / kg yakıt).
Jet-A1'deki küçük sülfür içeriğinden (~0.05% S).
Kaynak: ICAO Doc 9889.
"""


# ═══════════════════════════════════════════════════════════
# 5. JET YAKIT ÖZELLİKLERİ
# ═══════════════════════════════════════════════════════════
# Kaynak: ASTM D1655, IATA Fuel Quality Pool
# DEĞİŞİR Mİ: Pratikte sabit. Yeni yakıt formülasyonu ile teorik olarak.

JET_A1_DENSITY = 0.804
"""
Jet-A1 referans yoğunluğu (kg/L) @ 15°C.
NOT: Bu sabit değerdir. Sıcaklığa bağlı yoğunluk için
     Units.fuel_density_at_temp(temperature_c) kullan.
"""

JET_A1_ENERGY = 43.15
"""
Jet-A1 alt ısıl değeri / Lower Heating Value (MJ/kg).
Motor termal verim hesaplarında kullanılır.
Kaynak: ASTM D1655 typical value.
"""


# ═══════════════════════════════════════════════════════════
# 6. CORSIA AYARLARI
# ═══════════════════════════════════════════════════════════
# Kaynak: ICAO CORSIA Implementation Elements
# DEĞİŞİR Mİ: ICAO kararlarıyla EVET (yıllık kontrol).

CORSIA_BASELINE_YEAR = 2019
"""
CORSIA baseline yılı.
2019 seçildi çünkü 2020 COVID nedeniyle anormal.
ICAO kararı ile sabit. Değiştirmek ICAO kararı gerektirir.

Not: Bazı operatörler için 2020 seçeneği de var.
     CORSIA SARP'a göre operatör belirler.
"""

CORSIA_GROWTH_FACTOR = 0.03
"""
Havacılık sektörü yıllık büyüme oranı tahmini.
ICAO CAEP projeksiyonları bazlı.
CORSIA offset hesabında kullanılır.
Not: Gerçek büyüme yıldan yıla değişir.
"""

CARBON_CREDIT_PRICE_USD = 30
"""
Karbon kredi fiyatı (USD / ton CO2).
CORSIA eligible emission units (CEU) piyasa fiyatı.

GÜNCEL FİYAT ARALIĞI (2025-Q1):
    CORSIA CEU    : $20-35 / ton
    EU ETS (EUA)  : €60-100 / ton (~$65-110)
    Voluntary     : $5-50 / ton

Bu değer projeksiyonlarda kullanılır.
Gerçek maliyet müşterinin satın alma fiyatına bağlı.

GÜNCELLEME: Her çeyrek kontrol et.
    2025: ~$30
    2027: ~$40-60 beklentisi
    2030: ~$50-80 beklentisi

NOT: Bu değer assumptions.py'dan override edilebilir.
     Ama buradaki değer tüm sistemin default'u.
"""


# ═══════════════════════════════════════════════════════════
# 7. DASHBOARD AYARLARI
# ═══════════════════════════════════════════════════════════
# DEĞİŞİR Mİ: Deployment/geliştirme ortamına göre EVET.

DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
"""
Dashboard sunucu adresi.
"0.0.0.0" = tüm ağ arayüzlerinden erişilebilir.
"127.0.0.1" = sadece yerel erişim.
.env dosyasından override edilebilir.
"""

DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8050"))
"""
Dashboard port numarası.
Varsayılan: 8050 (Dash default).
Başka uygulama bu portu kullanıyorsa değiştir.
"""

DASHBOARD_DEBUG = os.getenv("DASHBOARD_DEBUG", "False").lower() in ("true", "1", "yes")
"""
Dashboard debug modu.

GÜVENLİK NOTU (CWE-94 / CWE-489):
    Dash/Flask debug=True, hata sayfasında ETKİLEŞİMLİ HATA AYIKLAYICI
    (Werkzeug debugger) açar. Bu, uzaktan keyfi KOD ÇALIŞTIRMA (RCE)
    riski taşır. Bu nedenle varsayılan artık False'tur.

    True  = Geliştirme (hot reload, detaylı hatalar — ASLA internete açma)
    False = Production (güvenli varsayılan)

    Yerelde geliştirirken: DASHBOARD_DEBUG=true (.env içinde)
"""


# ═══════════════════════════════════════════════════════════
# 8. DOSYA YOLLARI
# ═══════════════════════════════════════════════════════════
# Proje kök dizinine göre relatif yollar.

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_RAW = os.path.join(_PROJECT_ROOT, 'data', 'raw')
"""Ham veri klasörü (OpenSky CSV'ler)."""

DATA_RAW_OPENSKY = os.path.join(DATA_RAW, 'opensky')

# ══════════════════════════════════════════════════════════════
# DENETİM #79 — VERİ KAYNAĞI ADI YANILTICI
# ══════════════════════════════════════════════════════════════
# Klasör adı `opensky` AMA bu klasöre yazan üç kaynağın hiçbiri
# OpenSky değil:
#   • scripts/06_seed_real_data.py   → tamamen SENTETİK simülasyon
#   • scripts/07_live_flight_scrapper.py → ADSB.lol (api.adsb.lol)
#   • scripts/08_automated_fleet_tracker.py → ADSB.lol
#
# Yani "opensky" klasöründeki veri ya sentetik ya da ADSB.lol
# kaynaklıdır. Bu ayrım raporlarda/yüzeyde doğru gösterilmelidir.
#
# Gerçek OpenSky verisi için src/data_collection/opensky_collector.py
# kullanılır (kimlik bilgisi gerekir, bu ortamdan erişilemedi).
#
# Klasör adı geriye dönük uyumluluk için DEĞİŞTİRİLMEDİ — boru hattı
# (01→02→03) bu yola bağlı. Doğru bilgi DATA_SOURCE_NOTE ile taşınır.
DATA_SOURCE_NOTE = (
    'data/raw/opensky/ içeriği OpenSky ağından GELMEZ: '
    '06 sentetik simülasyon, 07 ve 08 ADSB.lol topluluk radarıdır.'
)
"""OpenSky ADS-B veri klasörü."""

DATA_PROCESSED = os.path.join(_PROJECT_ROOT, 'data', 'processed')
"""İşlenmiş veri klasörü."""

REPORTS_DIR = os.path.join(_PROJECT_ROOT, 'reports')
"""Üretilen raporlar ana klasörü."""

REPORTS_OPTIMIZATIONS = os.path.join(REPORTS_DIR, 'optimizations')
"""Optimizasyon sonuçları (JSON)."""

REPORTS_CASE_STUDIES = os.path.join(REPORTS_DIR, 'case_studies')
"""Case study çıktıları."""

DOCS_DIR = os.path.join(_PROJECT_ROOT, 'docs')
"""Belgeler ve grafikler klasörü."""


# ═══════════════════════════════════════════════════════════
# 9. OpenSky API AYARLARI
# ═══════════════════════════════════════════════════════════
# .env dosyasından okunur. Kod içinde şifre YAZILMAZ.

OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")
"""
OpenSky Network API kullanıcı adı.
Ücretsiz hesap: opensky-network.org
.env dosyasına yaz: OPENSKY_USERNAME=kullanici_adin
API limitleri:
    Anonim  : 100 call/gün
    Kayıtlı : 400 call/gün
"""

OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")
"""
OpenSky Network API şifresi.
.env dosyasına yaz: OPENSKY_PASSWORD=sifren
KOD İÇİNDE ŞİFRE YAZMA!
"""


# ═══════════════════════════════════════════════════════════
# 10. SİSTEM VERSİYONU
# ═══════════════════════════════════════════════════════════

SYSTEM_VERSION = "1.0.0"
"""
GreenWing Analytics sistem versiyonu.
Semantic versioning: MAJOR.MINOR.PATCH
    MAJOR : Büyük değişiklik (API kırılması)
    MINOR : Yeni özellik (geriye uyumlu)
    PATCH : Hata düzeltme
"""

SYSTEM_NAME = "GreenWing Analytics"
"""Sistem adı. Raporlarda ve dashboard'da kullanılır."""


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA
# ═══════════════════════════════════════════════════════════

def validate_settings() -> bool:
    """
    Settings değerlerinin tutarlılığını kontrol et.

    Çalıştırma:
        python -m config.settings
    """
    print("\n" + "=" * 60)
    print("  SETTINGS.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests = 0

    def check(name: str, value, expected, tol: float = 0.001) -> None:
        nonlocal tests
        tests += 1
        if isinstance(expected, (int, float)):
            if abs(float(value) - float(expected)) > tol:
                errors.append(f"{name}: {value} ≠ {expected}")
                print(f"  ❌ {name}: {value}")
            else:
                print(f"  ✅ {name} = {value}")
        else:
            if value == expected:
                print(f"  ✅ {name} = {value}")
            else:
                errors.append(f"{name}: {value} ≠ {expected}")
                print(f"  ❌ {name}: {value}")

    # Fiziksel sabitler
    print("\n  [1] Fiziksel Sabitler")
    check("GRAVITY",    GRAVITY,    9.80665)
    check("R_AIR",      R_AIR,      287.05)
    check("GAMMA",      GAMMA,      1.4)
    check("R_EARTH",    R_EARTH,    6371000)

    # ISA
    print("\n  [2] ISA Sabitleri")
    check("ISA_T0",         ISA_T0,         288.15)
    check("ISA_P0",         ISA_P0,         101325.0)
    check("ISA_RHO0",       ISA_RHO0,       1.225)
    check("ISA_LAPSE_RATE", ISA_LAPSE_RATE, -0.0065)
    check("TROPOPAUSE_ALT", TROPOPAUSE_ALT, 11000)

    # İdeal gaz tutarlılığı: P0 = ρ0 × R × T0
    tests += 1
    expected_P0 = ISA_RHO0 * R_AIR * ISA_T0
    if abs(expected_P0 - ISA_P0) / ISA_P0 < 0.001:
        print(f"  ✅ İdeal gaz tutarlı: ρ0×R×T0 = {expected_P0:.0f} ≈ P0 = {ISA_P0:.0f}")
    else:
        errors.append(f"İdeal gaz tutarsız: {expected_P0} ≠ {ISA_P0}")
        print(f"  ❌ İdeal gaz tutarsız")

    # Birim dönüşüm
    print("\n  [3] Birim Dönüşüm")
    check("KNOT_TO_MS", KNOT_TO_MS, 0.514444)
    check("FT_TO_M",    FT_TO_M,    0.3048)
    check("NM_TO_M",    NM_TO_M,    1852.0)
    check("KG_TO_LBS",  KG_TO_LBS,  2.20462)

    # Emisyon
    print("\n  [4] Emisyon Sabitleri")
    check("EI_CO2", EI_CO2, 3.16)
    check("EI_H2O", EI_H2O, 1.24)
    check("EI_SO2", EI_SO2, 0.001)

    # Yakıt
    print("\n  [5] Yakıt Özellikleri")
    check("JET_A1_DENSITY", JET_A1_DENSITY, 0.804)
    check("JET_A1_ENERGY",  JET_A1_ENERGY,  43.15, 0.1)

    # CORSIA
    print("\n  [6] CORSIA Ayarları")
    check("CORSIA_BASELINE_YEAR", CORSIA_BASELINE_YEAR, 2019)

    tests += 1
    if CARBON_CREDIT_PRICE_USD > 0:
        print(f"  ✅ CARBON_CREDIT_PRICE = ${CARBON_CREDIT_PRICE_USD}/ton")
    else:
        errors.append("Karbon fiyatı sıfır veya negatif")
        print("  ❌ Karbon fiyatı sıfır")

    # Dashboard
    print("\n  [7] Dashboard Ayarları")

    tests += 1
    if isinstance(DASHBOARD_PORT, int) and 1024 <= DASHBOARD_PORT <= 65535:
        print(f"  ✅ DASHBOARD_PORT = {DASHBOARD_PORT}")
    else:
        errors.append(f"Port geçersiz: {DASHBOARD_PORT}")
        print(f"  ❌ Port: {DASHBOARD_PORT}")

    tests += 1
    if isinstance(DASHBOARD_DEBUG, bool):
        print(f"  ✅ DASHBOARD_DEBUG = {DASHBOARD_DEBUG}")
    else:
        errors.append(f"Debug boolean değil: {DASHBOARD_DEBUG}")

    # Dosya yolları
    print("\n  [8] Dosya Yolları")

    tests += 1
    if os.path.isdir(_PROJECT_ROOT):
        print(f"  ✅ PROJECT_ROOT mevcut: {_PROJECT_ROOT}")
    else:
        errors.append(f"PROJECT_ROOT yok: {_PROJECT_ROOT}")
        print(f"  ❌ PROJECT_ROOT yok")

    for name, path in [
        ("DATA_RAW",             DATA_RAW),
        ("DATA_RAW_OPENSKY",     DATA_RAW_OPENSKY),
        ("DATA_PROCESSED",       DATA_PROCESSED),
        ("REPORTS_DIR",          REPORTS_DIR),
        ("REPORTS_OPTIMIZATIONS",REPORTS_OPTIMIZATIONS),
        ("REPORTS_CASE_STUDIES", REPORTS_CASE_STUDIES),
    ]:
        tests += 1
        if path and len(path) > 5:
            print(f"  ✅ {name} = ...{path[-30:]}")
        else:
            errors.append(f"{name} boş veya çok kısa")
            print(f"  ❌ {name} = {path}")

    # Versiyon
    print("\n  [9] Sistem Bilgisi")
    check("SYSTEM_VERSION", SYSTEM_VERSION, "1.0.0")
    check("SYSTEM_NAME",    SYSTEM_NAME,    "GreenWing Analytics")

    # API (varlık kontrolü, değer kontrolü değil)
    print("\n  [10] API Ayarları")
    tests += 1
    if isinstance(OPENSKY_USERNAME, str):
        status = "ayarlanmış" if OPENSKY_USERNAME else "boş (anonim)"
        print(f"  ✅ OPENSKY_USERNAME: {status}")
    else:
        errors.append("OPENSKY_USERNAME string değil")
        print("  ❌ OPENSKY_USERNAME tip hatası")

    # Sonuç
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
    validate_settings()