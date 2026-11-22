"""
GreenWing Analytics — Varsayımlar Merkezi
═════════════════════════════════════════

Bu dosya sistemin tüm varsayımlarını tek yerde toplar.

NEDEN GEREKLİ:
──────────────
OpenSky ADS-B verisi şunları VERMEZ:
    • Yakıt miktarı
    • Gerçek uçak ağırlığı
    • Payload (yolcu + bagaj + kargo)
    • Motor yaşı / degradasyon
    • Gerçek yakıt fiyatı
    • Pilot deneyim seviyesi

Bu bilgiler olmadan hesap yapılamaz.
O yüzden VARSAYIYORUZ.

Ama bu varsayımlar:
    1. Belgelenmeli   → "hangi varsayımla hesaplandı?"
    2. Değiştirilebilir olmalı → müşteri gerçek değer verince güncellenir
    3. Doğruluk notu içermeli → "bu ±X% hata payı taşır"
    4. Tek yerde olmalı → dağınık olunca tutarsızlık olur

KULLANIM:
─────────
    from config.assumptions import Assumptions

    oew   = Assumptions.aircraft_oew('B738')
    pax   = Assumptions.typical_payload('B738', 0.80)
    price = Assumptions.fuel_price('LTFM')
    tc    = Assumptions.time_cost('PGT')
    freq  = Assumptions.daily_frequency(1560)
    rf    = Assumptions.realization_factor()
    note  = Assumptions.accuracy_note('payload')

MÜŞTERİ VERİSİ GELİNCE:
─────────────────────────
    Assumptions.override('oew', 'B738', 42800, 'customer_weight_manual')
    Assumptions.override('realization_factor', 'DEFAULT', 0.75, 'ops_review')
    Assumptions.get_active_overrides()
"""

from __future__ import annotations

import threading
import warnings
from datetime import datetime
from typing import Optional


# ═══════════════════════════════════════════════════════════
# UÇAK PARAMETRELERİ
# ═══════════════════════════════════════════════════════════

# ── TEK DOĞRULUK KAYNAĞI ─────────────────────────────────
# Aşağıdaki OEW / MTOW / MAX_FUEL / SEATS değerleri DOĞRUDAN
# config/aircraft_database.yaml'dan okunur. Önceden burada ikinci bir
# kopya vardı ve zamanla veritabanından SAPTI (B38M OEW 44 280 vs
# 45 070; A380 max_fuel 320 000 vs 253 983 kg → %26 hata).
# İki kaynak tutmanın doğurduğu bu tür sessiz sapmalar, "hangi sayı
# doğru?" sorusunu cevapsız bırakır. Artık tek kaynak var.
#
# Kaynak: Boeing/Airbus Aircraft Characteristics Manual + EASA/FAA TCDS,
#         OpenAP v3 (tools/sync_openap_params.py ile senkronize edilir).

def _load_aircraft_facts() -> dict:
    """config/aircraft_database.yaml'ı oku (tek doğruluk kaynağı)."""
    from pathlib import Path as _Path
    import yaml as _yaml
    _p = _Path(__file__).resolve().with_name('aircraft_database.yaml')
    if not _p.exists():          # savunmacı: paketlenmiş kurulumlar
        return {}
    with _p.open(encoding='utf-8') as _f:
        _db = _yaml.safe_load(_f) or {}
    return _db.get('aircraft_types', _db)


_AIRCRAFT_FACTS: dict = _load_aircraft_facts()

# Geri uyumluluk: eski kod _OEW[...] gibi sözlük erişimi kullanıyor.
_OEW: dict[str, int] = {
    ac: int(v['oew']) for ac, v in _AIRCRAFT_FACTS.items() if 'oew' in v}
_MTOW: dict[str, int] = {
    ac: int(v['mtow']) for ac, v in _AIRCRAFT_FACTS.items() if 'mtow' in v}
_MAX_FUEL: dict[str, int] = {
    ac: int(v['max_fuel']) for ac, v in _AIRCRAFT_FACTS.items()
    if 'max_fuel' in v}
_TYPICAL_SEATS: dict[str, int] = {
    ac: int(v['passengers_typical']) for ac, v in _AIRCRAFT_FACTS.items()
    if 'passengers_typical' in v}

# Veritabanı okunamazsa (dosya yok) eski sabitlere düş — ama UYARI bas.
if not _OEW:
    import warnings as _w
    _w.warn('config/aircraft_database.yaml okunamadı; gömülü yedek '
            'değerler kullanılıyor. Bu durumda değerler senkronize '
            'OLMAYABİLİR.', RuntimeWarning)
    _OEW = {'B738': 41413, 'B38M': 45070, 'A320': 42600, 'A20N': 44300,
            'A321': 48500, 'A21N': 50900, 'B77W': 167829, 'B788': 119950,
            'B789': 128850, 'A350': 142400, 'A380': 277145}
    _MTOW = {'B738': 79016, 'B38M': 82191, 'A320': 78000, 'A20N': 79000,
             'A321': 93500, 'A21N': 97000, 'B77W': 351534, 'B788': 227930,
             'B789': 254011, 'A350': 280000, 'A380': 575000}
    _MAX_FUEL = {'B738': 20894, 'B38M': 20894, 'A320': 18900,
                 'A20N': 19100, 'A321': 23860, 'A21N': 26730,
                 'B77W': 145538, 'B788': 101323, 'B789': 126920,
                 'A350': 158791, 'A380': 253983}
    _TYPICAL_SEATS = {'B738': 162, 'B38M': 178, 'A320': 165, 'A20N': 150,
                      'A321': 185, 'A21N': 180, 'B77W': 365, 'B788': 242,
                      'B789': 296, 'A350': 315, 'A380': 555}

# ═══════════════════════════════════════════════════════════

# Kişi başı ağırlık (yolcu + bagaj + kişisel eşya) — kg
#
# Kaynak: EASA CS-25 / EU-OPS 1.620 standart yolcu ağırlıkları.
# EASA 2022 güncellemesi (COVID sonrası bagaj artışı):
#   • erkek 88.4 kg, kadın 70.2 kg, çocuk 35 kg → karışım ≈ 84 kg
#   • el bagajı +6 kg, kayıtlı bagaj ortalama +16 kg
#   • kısa/orta/uzun mesafe farkı: bagaj ağırlığı artar
# Aşağıdaki 95/100/105 kg değerleri bu bileşenleri İÇERİR ve
# muhafazakârdır (EASA saf yetişkin ortalamasından yüksek).
_PAX_WEIGHT_KG: dict[str, int] = {
    'short_haul' : 95,
    'medium_haul': 100,
    'long_haul'  : 105,
}


# ═══════════════════════════════════════════════════════════
# YAKIT FİYATI VERİSİ
# ═══════════════════════════════════════════════════════════

# Havalimanı bazlı yakıt fiyatları — USD/kg
#
# ⚠ BU BİR TAHMİNDİR — canlı piyasa verisi DEĞİLDİR.
# Kaynak: IATA Jet Fuel Price Monitor genel eğilimi (2025-Q1 bandı),
#         bölgesel vergi/lojistik farkları için sektör deneyimi.
# Doğruluk: ±%10 günlük piyasa; müşteri kontrat fiyatı ±%30 farklı olabilir.
#
# TÜM $ KPI'LARI BU DEĞERE DOĞRUSAL BAĞLIDIR. Ticari kullanımda
# müşterinin gerçek kontrat fiyatı girilmelidir (Assumptions.override
# veya entegrasyonla). Bu tablo yalnızca varsayılan/örnek değerdir.
#
# Tarih: 2025-Q1 tahmini. Aylık kontrol önerilir.
_FUEL_PRICES_USD_PER_KG: dict[str, float] = {
    # Türkiye
    'LTFM': 0.78, 'LTFJ': 0.78, 'LTAC': 0.80,
    'LTAI': 0.80, 'LTBJ': 0.80,
    # Avrupa
    'EGLL': 1.05, 'EGKK': 1.03, 'EDDF': 0.95,
    'LFPG': 0.98, 'EHAM': 0.92, 'LEMD': 0.88,
    'LIRF': 0.90, 'LOWW': 0.90, 'LSZH': 0.95,
    'LSGG': 0.93, 'EDDM': 0.94,
    # Orta Doğu
    'OMDB': 0.58, 'OMDW': 0.57, 'OEJN': 0.50,
    'OERK': 0.52, 'OTHH': 0.52, 'OAKB': 0.65,
    # Kuzey Amerika
    'KJFK': 0.88, 'KLAX': 0.85,
    'KORD': 0.82, 'CYYZ': 0.83,
    # Asya
    'VHHH': 0.95, 'RJTT': 0.90,
    'WSSS': 0.82, 'VIDP': 0.75,
    # Afrika
    'HAAB': 1.10, 'HKJK': 1.25, 'DNMM': 1.20,
    # Varsayılan
    'DEFAULT': 0.85,
}

# Ülke prefix → genel fiyat (bilinmeyen havalimanı fallback)
_COUNTRY_FUEL_DEFAULTS: dict[str, float] = {
    'LT': 0.79,  # Türkiye
    'EG': 1.04,  # İngiltere
    'ED': 0.94,  # Almanya
    'LF': 0.97,  # Fransa
    'OM': 0.58,  # BAE
    'OE': 0.52,  # Suudi Arabistan
    'OT': 0.53,  # Katar
    'K' : 0.86,  # ABD
    'CY': 0.83,  # Kanada
    'VH': 0.95,  # Hong Kong
    'RJ': 0.90,  # Japonya
}


# ═══════════════════════════════════════════════════════════
# ZAMAN MALİYETİ
# ═══════════════════════════════════════════════════════════

# Havayolu tipi bazlı zaman maliyeti — USD/saat
# Bileşenler: mürettebat + bakım + leasing + fırsat maliyeti
#
# ⚠ TAHMİN. Kaynak: ATAG (Aviation Benefits Report) ve IATA Aircraft
# Economics dokümanlarındaki tipik DOC (Direct Operating Cost) aralıkları.
# Havayoluna göre ±%20 değişir (mürettebat anlaşmaları, leasing oranları).
# Cost Index optimizasyonunun hassasiyetini belirler: CI bu değere
# doğrusal bağlıdır, dolayısıyla sonuç ±%20 taşır.
_TIME_COST_USD_PER_HR: dict[str, int] = {
    'ultra_lcc' : 800,
    'lcc'       : 1200,
    'hybrid_lcc': 1500,
    'regional'  : 1800,
    'network'   : 2200,
    'premium'   : 3000,
    'cargo'     : 1500,
    'DEFAULT'   : 1800,
}

# Havayolu kodu → tip eşleştirmesi
_AIRLINE_TIME_COST_MAP: dict[str, str] = {
    'PGT': 'lcc',     'THY': 'network',  'TK' : 'network',
    'SXS': 'lcc',     'CAI': 'lcc',      'FHY': 'lcc',
    'FDB': 'lcc',     'ABY': 'lcc',      'JAZ': 'lcc',
    'KNE': 'lcc',     'UAE': 'premium',  'QTR': 'premium',
    'ETD': 'premium', 'EZY': 'ultra_lcc','RYR': 'ultra_lcc',
    'WZZ': 'ultra_lcc','DLH': 'network', 'AFR': 'network',
    'BAW': 'network',  'ETH': 'network', 'RWD': 'regional',
}

# Tipik load factor
#
# Kaynak: IATA World Air Transport Statistics (WATS) — sektör ortalaması
# 2024: %83.5 (network), LCC'lerde %87-90. Aşağıdaki değerler bu
# aralığa oturur. ±%5 mevsimsel/yıllık dalgalanma.
_TYPICAL_LOAD_FACTOR: dict[str, float] = {
    'lcc'    : 0.87,
    'network': 0.83,
    'charter': 0.92,
    'regional': 0.80,
    'cargo': 0.95,
    'DEFAULT': 0.82,
}


# ═══════════════════════════════════════════════════════════
# OPERASYONEL VARSAYIMLAR
# ═══════════════════════════════════════════════════════════

# Yıllık operasyonel gün sayısı
#
# KAYNAK: IATA / Airbus Global Market Forecast ve tipik havayolu
# kullanım oranı: uçak yılda ~330-350 gün operasyonel, kalan gün
# planlı bakım (A-check ~her 500 FH, C-check yıllık). 345 gün = %94.5
# dispatch availability. Bu, endüstri standardına uygundur.
OPERATIONAL_DAYS_PER_YEAR: int = 345

# Yıllık AZAMİ blok-saat (uçak başına) — FİZİKSEL ÜST SINIR
#
# KAYNAK: Boeing/Airbus operatör kılavuzları tipik yüksek kullanım:
#   • Kısa mesafe (A320/B737) : 3 000–3 800 blok-saat/yıl
#   • Uzun mesafe (B77W/A350) : 4 500–5 200 blok-saat/yıl
#   • Bölgesel                 : 2 500–3 000 blok-saat/yıl
# 2019 öncesi en yoğun filolar 5 200 saat/yıl'a ulaştı (ör. Southwest
# 737NG ~3 400 h, Emirates 777 ~4 800 h). 4 500 saat muhafazakâr üst
# sınırdır; bunun üzerindeki projeksiyonlar fiziksel değildir.
MAX_ANNUAL_BLOCK_HOURS: float = 4500.0

# Günlük sefer frekansı — rota uzunluğuna göre
#
# ⚠ KAYNAKSIZ TAHMİN. OAG schedule veritabanı genel eğiliminden
# türetilmiştir, tek tek rotalar için doğrulanmamıştır (±%30).
# Bu yüzden annual_projection() frekansı ayrıca FİZİKSEL olarak
# sınırlar (bkz. MAX_ANNUAL_BLOCK_HOURS) ve plate hour'ı raporlar.
_DAILY_FREQUENCY_BY_DISTANCE: list[dict] = [
    {'max_nm':  300, 'label': 'ultra_short', 'freq': 6},
    {'max_nm':  800, 'label': 'short',       'freq': 4},
    {'max_nm': 1500, 'label': 'medium',      'freq': 2},
    {'max_nm': 4000, 'label': 'long',        'freq': 1},
    {'max_nm': 99999,'label': 'ultra_long',  'freq': 1},
]

# Varsayılan gerçekleşme faktörü
# Teorik tasarruf × bu faktör = operasyonel gerçekleşme tahmini
# Neden 1.0 değil: ATC kısıtları, hava durumu, slot, operasyonel sınırlar
# Override edilebilir. Değer aralığı: 0.0 < x ≤ 1.0
REALIZATION_FACTOR: float = 0.65

# Tankering tekrarlanabilirlik faktörü
#
# Tankering = yakıtı ucuz havalimanından alıp pahalıya göre taşımak.
# Bu bir YAKIT MİKTARI tasarrufu DEĞİL, FİYAT arbitrajıdır. Yıllık
# projeksiyonda tam tekrarlanması gerçekçi değildir:
#   • Fiyat farkı kalıcı değil (haftalar içinde kapanır)
#   • Tank kapasitesi uçuşa, yüke, hava durumuna göre değişir
#   • Operatörler yakıt güvenliği için marj bırakır
# %50 muhafazakâr kabul; müşteri verisiyle kalibre edilmeli.
TANKERING_PERSISTENCE: float = 0.50

# Motor degradasyon varsayılanı (kalibrasyon öncesi)
_DEFAULT_ENGINE_DEGRADATION: dict[str, float] = {
    'cd0_factor': 1.00,
    'sfc_factor': 1.00,
}


# ═══════════════════════════════════════════════════════════
# DOĞRULUK NOTLARI
# ═══════════════════════════════════════════════════════════

_ACCURACY_NOTES: dict[str, dict] = {
    'oew': {
        'uncertainty_pct': 3.0,
        'note': (
            'OEW standart konfigürasyon bazlıdır. '
            'Müşterinin gerçek konfigürasyonu (koltuk, galley, IFE) '
            'farklı olabilir. ±3% hata payı. '
            'Weight & balance dokümanı ile sıfıra düşer.'
        ),
        'source': 'Boeing/Airbus Aircraft Characteristics Manual',
    },
    'payload': {
        'uncertainty_pct': 15.0,
        'note': (
            'Tipik load factor ve kişi başı ağırlık kullanılmıştır. '
            'Gerçek doluluk ve bagaj ağırlığı günlük değişir. ±15% hata payı. '
            'Loadsheet verisi ile ±3%\'e düşer.'
        ),
        'source': 'EASA kişi başı standart ağırlık, IATA load factor istatistikleri',
    },
    'fuel_price': {
        'uncertainty_pct': 10.0,
        'note': (
            '2025-Q1 genel eğilimine dayanır. '
            'Günlük ve mevsimsel dalgalanma ±10% olabilir. '
            'Müşteri kontrat fiyatı çok farklı olabilir. '
            'Tankering kararı için gerçek değer şarttır.'
        ),
        'source': 'IATA Fuel Monitor, genel piyasa tahminleri',
    },
    'time_cost': {
        'uncertainty_pct': 20.0,
        'note': (
            'Havayolu tipiyle tahmin edilmiştir. '
            'Gerçek mürettebat, leasing, bakım anlaşmaları farklı olabilir. ±20%. '
            'Cost Index optimizasyonu için müşteri değeri önerilir.'
        ),
        'source': 'ATAG, IATA Aircraft Economics',
    },
    'daily_frequency': {
        'uncertainty_pct': 30.0,
        'note': (
            'Mesafeden tahmin edilmiştir. '
            'Gerçek schedule\'a göre büyük fark olabilir. ±30%. '
            'Yıllık projeksiyon için müşteri schedule verisi gereklidir.'
        ),
        'source': 'OAG schedule veritabanı genel eğilimi',
    },
    'realization_factor': {
        'uncertainty_pct': 15.0,
        'note': (
            'Tasarruf gerçekleşme oranı varsayılandır. '
            'ATC kısıtları, hava durumu ve operasyonel sınırlar nedeniyle '
            'teorik tasarrufun tamamı elde edilemez. '
            'İlk 3 ay pilot uygulama sonrası kalibrasyon önerilir. '
            'Override ile havayoluna/rotaya özel değer atanabilir.'
        ),
        'source': 'Endüstri deneyimi ve akademik literatür',
    },
    'engine_degradation': {
        'uncertainty_pct': 5.0,
        'note': (
            'Varsayılan değerler kullanılmaktadır (cd0_factor=1.0, sfc_factor=1.0). '
            'Gerçek veriyle kalibrasyon yapılmamıştır. '
            'QAR/FDR verisiyle kalibrasyon sonrası ±1-2%\'ye düşer.'
        ),
        'source': 'Varsayılan (kalibrasyon bekliyor)',
    },
}


# ═══════════════════════════════════════════════════════════
# OVERRIDE DEPOSU (thread-safe, per-request isolation)
# ═══════════════════════════════════════════════════════════
# 
# ✅ v2.2: Thread-safe override deposu
# Her thread/request kendi override deposuna sahip.
# Multi-tenant SaaS ortamında Tenant A'nın override'ları
# Tenant B'yi ETKİLEMEZ.
#
# Nasıl çalışır:
#   - threading.local() ile her thread'e özel dict
#   - CLI (tek thread): Eskisiyle aynı davranış
#   - FastAPI/Dash (çok thread): Her request izole
#   - clear_overrides(): Sadece çağıran thread'i temizler
#
# {(category, key): (value, source, timestamp)}

_THREAD_LOCAL = threading.local()

# Geriye uyumluluk: eski _OVERRIDES referansları artık thread-local store'a yönlendir
_OVERRIDES: dict[tuple, tuple] = {}  # DEPRECATED — _get_overrides_store() kullan


def _get_overrides_store() -> dict[tuple, tuple]:
    """
    Thread-safe override deposu döndür.
    
    Her thread kendi bağımsız override deposuna sahiptir.
    İlk çağrıda otomatik olarak boş dict oluşturulur.
    
    Returns:
        dict: {(category, key): (value, source, timestamp)}
    """
    if not hasattr(_THREAD_LOCAL, 'overrides'):
        _THREAD_LOCAL.overrides = {}
    return _THREAD_LOCAL.overrides


# ═══════════════════════════════════════════════════════════
# YARDIMCI FONKSIYONLAR (modül seviyesi)
# ═══════════════════════════════════════════════════════════

def _get_override(category: str, key: str):
    """Override varsa değeri döndür, yoksa None. Thread-safe."""
    store = _get_overrides_store()
    entry = store.get((category, key))
    if entry is not None:
        return entry[0]
    return None


def _set_override(category: str, key: str, value, source: str) -> None:
    """Override kaydet. Thread-safe."""
    store = _get_overrides_store()
    store[(category, key)] = (value, source, datetime.now().isoformat())


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class Assumptions:
    """
    GreenWing Analytics Varsayımlar Merkezi.

    Tüm varsayım değerlerine buradan erişilir.
    Müşteri gerçek değer verdiğinde override edilebilir.
    Her değer hata payıyla birlikte belgelenmiştir.

    Kullanım:
        from config.assumptions import Assumptions

        oew   = Assumptions.aircraft_oew('B738')
        price = Assumptions.fuel_price('LTFM')
        tc    = Assumptions.time_cost('PGT')
        freq  = Assumptions.daily_frequency(1560)
        rf    = Assumptions.realization_factor()
        note  = Assumptions.accuracy_note('payload')
    """

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: UÇAK PARAMETRELERİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def aircraft_oew(ac_type: str) -> float:
        """
        Operating Empty Weight (OEW) — kg.

        Args:
            ac_type: ICAO uçak tipi kodu ('B738', 'A320', ...)

        Returns:
            float: OEW (kg)

        Raises:
            KeyError: Bilinmeyen uçak tipi

        Örnekler:
            Assumptions.aircraft_oew('B738') → 41413.0
            Assumptions.aircraft_oew('A320') → 42600.0

        Not:
            Standart konfigürasyon değeridir. ±3% hata payı.
            Müşteri verisiyle override edilmeli.
        """
        val = _get_override('oew', ac_type)
        if val is not None:
            return float(val)

        if ac_type not in _OEW:
            raise KeyError(
                f"Bilinmeyen uçak tipi: '{ac_type}'. "
                f"Desteklenen: {sorted(_OEW.keys())}. "
                f"Yeni tip için assumptions.py ve aircraft_database.yaml güncellenmeli."
            )
        return float(_OEW[ac_type])

    @staticmethod
    def aircraft_mtow(ac_type: str) -> float:
        """
        Maximum Takeoff Weight (MTOW) — kg.

        Args:
            ac_type: ICAO uçak tipi kodu

        Returns:
            float: MTOW (kg)

        Not:
            Sertifikasyon limiti. Değişmez.
            Performans bazlı kısıtlama MTOW'u düşürebilir.
        """
        val = _get_override('mtow', ac_type)
        if val is not None:
            return float(val)

        if ac_type not in _MTOW:
            raise KeyError(f"Bilinmeyen uçak tipi: '{ac_type}'")
        return float(_MTOW[ac_type])

    @staticmethod
    def aircraft_max_fuel(ac_type: str) -> float:
        """
        Maksimum yakıt kapasitesi — kg.

        Args:
            ac_type: ICAO uçak tipi kodu

        Returns:
            float: Maksimum yakıt (kg)
        """
        val = _get_override('max_fuel', ac_type)
        if val is not None:
            return float(val)

        if ac_type not in _MAX_FUEL:
            raise KeyError(f"Bilinmeyen uçak tipi: '{ac_type}'")
        return float(_MAX_FUEL[ac_type])

    @staticmethod
    def typical_payload(
        ac_type: str,
        load_factor: Optional[float] = None,
        route_nm: Optional[float] = None,
    ) -> float:
        """
        Tipik payload (yolcu + bagaj) — kg.

        Args:
            ac_type    : ICAO uçak tipi kodu
            load_factor: Doluluk oranı (0.0-1.0). None → varsayılan.
            route_nm   : Rota mesafesi (Nm). Kişi başı ağırlığı etkiler.

        Returns:
            float: Payload (kg)

        Örnekler:
            Assumptions.typical_payload('B738')              → ~11340 kg
            Assumptions.typical_payload('B738', 0.95)        → ~13148 kg
            Assumptions.typical_payload('B738', route_nm=500) → biraz daha az

        Not: ±15% hata payı. Loadsheet verisi ile override edilmeli.
        """
        val = _get_override('payload', ac_type)
        if val is not None:
            return float(val)

        seats = _TYPICAL_SEATS.get(ac_type, 150)

        if load_factor is None:
            load_factor = _TYPICAL_LOAD_FACTOR['DEFAULT']
        load_factor = float(max(0.0, min(1.0, load_factor)))

        if route_nm is None or route_nm < 1500:
            pax_weight = _PAX_WEIGHT_KG['short_haul']
        elif route_nm < 4000:
            pax_weight = _PAX_WEIGHT_KG['medium_haul']
        else:
            pax_weight = _PAX_WEIGHT_KG['long_haul']

        return float(seats * load_factor * pax_weight)

    @staticmethod
    def engine_degradation(ac_type: str) -> dict:
        """
        Motor ve aerodinamik degradasyon faktörleri.

        Args:
            ac_type: ICAO uçak tipi kodu

        Returns:
            dict:
                cd0_factor: Drag artışı (1.0 = yeni uçak)
                sfc_factor: SFC artışı  (1.0 = yeni motor)

        Not:
            Kalibrasyon yapılmamışsa her ikisi de 1.0.
            ModelCalibrator çalıştırıldıktan sonra override edilir.
        """
        val = _get_override('degradation', ac_type)
        if val is not None:
            return val

        return _DEFAULT_ENGINE_DEGRADATION.copy()

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: YAKIT FİYATLARI
    # ──────────────────────────────────────────────────────

    @staticmethod
    def fuel_price(airport_icao: str) -> float:
        """
        Havalimanı bazlı yakıt fiyatı — USD/kg.

        Args:
            airport_icao: ICAO havalimanı kodu ('LTFM', 'EGLL', ...)

        Returns:
            float: Yakıt fiyatı (USD/kg)

        Not:
            2025-Q1 genel tahmini. ±10% hata payı.
            Bilinmeyen havalimanı için ülke prefixine bakılır,
            o da yoksa DEFAULT kullanılır ve uyarı verilir.
            Tankering kararları için müşteri kontrat fiyatı şarttır.
        """
        val = _get_override('fuel_price', airport_icao)
        if val is not None:
            return float(val)

        if airport_icao in _FUEL_PRICES_USD_PER_KG:
            return float(_FUEL_PRICES_USD_PER_KG[airport_icao])

        # Ülke prefix fallback
        prefix = airport_icao[:2] if len(airport_icao) >= 2 else ''
        if prefix in _COUNTRY_FUEL_DEFAULTS:
            price = _COUNTRY_FUEL_DEFAULTS[prefix]
            warnings.warn(
                f"'{airport_icao}' için fiyat bilinmiyor. "
                f"Ülke genel fiyatı kullanıldı: ${price:.3f}/kg. "
                f"assumptions.py'a eklenmesi önerilir.",
                stacklevel=2,
            )
            return float(price)

        # DEFAULT
        price = _FUEL_PRICES_USD_PER_KG['DEFAULT']
        warnings.warn(
            f"'{airport_icao}' için yakıt fiyatı bilinmiyor. "
            f"DEFAULT: ${price:.3f}/kg.",
            stacklevel=2,
        )
        return float(price)

    @staticmethod
    def fuel_price_differential(
        origin_icao: str,
        dest_icao: str,
    ) -> dict:
        """
        İki havalimanı arası yakıt fiyat farkını analiz et.

        Args:
            origin_icao: Kalkış havalimanı ICAO kodu
            dest_icao  : Varış havalimanı ICAO kodu

        Returns:
            dict:
                origin_price    : float
                dest_price      : float
                price_diff      : float (pozitif = varış pahalı)
                tankering_viable: bool
                tankering_note  : str
        """
        MIN_DIFF = 0.05  # USD/kg — tankering için minimum anlamlı fark

        origin_price = Assumptions.fuel_price(origin_icao)
        dest_price   = Assumptions.fuel_price(dest_icao)
        diff         = dest_price - origin_price

        return {
            'origin_price'    : origin_price,
            'dest_price'      : dest_price,
            'price_diff'      : round(diff, 4),
            'tankering_viable': diff > MIN_DIFF,
            'tankering_note'  : (
                f"${diff:.3f}/kg fark → "
                f"Tankering {'mantıklı' if diff > MIN_DIFF else 'mantıksız'}."
            ),
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: ZAMAN MALİYETİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def time_cost(airline_code: str) -> float:
        """
        Havayolu bazlı zaman maliyeti — USD/saat.

        Args:
            airline_code: ICAO havayolu kodu ('PGT', 'THY', ...)
                          veya tip kodu ('lcc', 'network', 'premium', ...)

        Returns:
            float: Zaman maliyeti (USD/saat)

        Örnekler:
            Assumptions.time_cost('PGT')     → 1200.0
            Assumptions.time_cost('THY')     → 2200.0
            Assumptions.time_cost('lcc')     → 1200.0
            Assumptions.time_cost('UNKNOWN') → 1800.0

        Not: ±20% hata payı.
        """
        val = _get_override('time_cost', airline_code)
        if val is not None:
            return float(val)

        # Doğrudan tip kodu
        if airline_code in _TIME_COST_USD_PER_HR:
            return float(_TIME_COST_USD_PER_HR[airline_code])

        # Havayolu kodu → tip → maliyet
        airline_type = _AIRLINE_TIME_COST_MAP.get(airline_code, 'DEFAULT')
        return float(_TIME_COST_USD_PER_HR.get(airline_type, _TIME_COST_USD_PER_HR['DEFAULT']))

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: GERÇEKLEŞME FAKTÖRÜ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def realization_factor() -> float:
        """
        Tasarruf gerçekleşme faktörü.

        Teorik tasarruf × bu faktör = operasyonel gerçekleşme tahmini.

        Neden 1.0 değil:
            ATC kısıtlamaları, hava durumu, slot yönetimi,
            operasyonel disiplin farklılıkları teorik tasarrufun
            tamamının elde edilmesini engeller.

        Varsayılan: 0.65 (%65 gerçekleşme)

        Tipik aralıklar:
            0.40-0.55 → Yoğun Avrupa hava sahası, kısa iç hat
            0.55-0.70 → Tipik karışık operasyon
            0.70-0.85 → Sakin hava sahası, disiplinli operatör
            0.85-0.95 → Çok iyi koşullar (nadiren)

        Override ile havayoluna özel değer atanabilir:
            Assumptions.override(
                'realization_factor', 'DEFAULT', 0.75, 'ops_review'
            )

        Returns:
            float: 0.0 < value ≤ 1.0

        Raises:
            ValueError: Override değeri geçersiz aralıkta
        """
        val = _get_override('realization_factor', 'DEFAULT')
        if val is not None:
            val = float(val)
            if not (0.0 < val <= 1.0):
                raise ValueError(
                    f"realization_factor 0 ile 1 arasında olmalı, "
                    f"gelen: {val}. "
                    f"Örnek: Assumptions.override('realization_factor', 'DEFAULT', 0.75, 'kaynak')"
                )
            return val

        return float(REALIZATION_FACTOR)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: OPERASYONEL VARSAYIMLAR
    # ──────────────────────────────────────────────────────

    @staticmethod
    def daily_frequency(route_nm: float) -> int:
        """
        Rota mesafesine göre tahmini günlük sefer sayısı.

        Args:
            route_nm: Rota uzunluğu (Nm)

        Returns:
            int: Tahmini günlük sefer sayısı

        Örnekler:
            Assumptions.daily_frequency(190)  → 6
            Assumptions.daily_frequency(1200) → 2
            Assumptions.daily_frequency(5000) → 1

        Not: ±30% hata payı. Gerçek schedule önerilir.
        """
        val = _get_override('daily_freq', str(int(route_nm)))
        if val is not None:
            return int(val)

        for band in _DAILY_FREQUENCY_BY_DISTANCE:
            if route_nm <= band['max_nm']:
                return band['freq']

        return 1

    @staticmethod
    def _block_hours(route_nm: float) -> float:
        """
        Rota için blok-saat tahmini (kapı-kapı).

        Yöntem: cruise süresi (TAS 460 kt varsayımı) + sabit taksi/
        tırmanma/alçalma payı. Kısa rotada sabit pay baskındır.

        KAYNAK: EUROCONTROL/ICAO tipik blok-süre bileşenleri;
        taksi-out 12 dk + kalkış/tırmanma 8 dk + alçalma/yaklaşma 15 dk
        + taksi-in 6 dk ≈ 41 dk sabit pay (kısa mesafe).
        """
        cruise_hr = float(route_nm) / 460.0
        return cruise_hr + 0.68

    @staticmethod
    def annual_projection(
        per_flight_saving_usd: float,
        route_nm: float,
        daily_flights: Optional[int] = None,
        realization_factor: Optional[float] = None,
        tankering_usd_per_flight: float = 0.0,
    ) -> dict:
        """
        Yıllık tasarruf projeksiyonu hesapla.

        Args:
            per_flight_saving_usd: Uçuş başına tasarruf (USD)
            route_nm             : Rota uzunluğu (Nm)
            daily_flights        : Günlük sefer sayısı. None → otomatik tahmin.
            realization_factor   : Gerçekleşme oranı (0.0-1.0).
                                   None → override veya varsayılan kullanılır.
                                   Doğrudan değer vermek override'ı geçersiz kılar.
            tankering_usd_per_flight : Uçuş başına TANKERING (yakıt fiyat
                                   arbitrajı) tasarrufu. Bu ayrı işlenir:
                                   tankering bir YAKIT MİKTARI tasarrufu
                                   değil, FİYAT arbitrajıdır ve her uçuşta
                                   tekrarlanması garanti değildir (dest
                                   fiyatı değişir, tank kapasitesi sınırlı).
                                   Yıllık projeksiyonda %50 tekrarlanabilirlik
                                   varsayılır ve AYRI raporlanır.

        DÖNÜŞ AYRINTISI:
            fuel_saving_usd  : yalnızca fiziksel yakıt tasarrufundan gelen
            tankering_usd    : ayrı, tekrarlanabilirlik düzeltmeli
            Bu ayrım olmadan, tek uçuşta görülen $249'luk "tasarrufun"
            %99'u tankering olabilir ve yıllık $112k gibi fiziksel olarak
            yanıltıcı bir sayı çıkar.

        Returns:
            dict:
                daily_flights        : kullanılan günlük sefer sayısı
                operational_days     : kullanılan operasyonel gün sayısı
                raw_annual_usd       : teorik yıllık tasarruf
                realistic_annual_usd : gerçekçilik düzeltmeli tasarruf
                realization_factor   : kullanılan gerçekleşme faktörü
                assumptions_used     : hangi varsayımların kullanıldığı

        Örnekler:
            # Tüm varsayılan
            proj = Assumptions.annual_projection(442, 1560)

            # Özel günlük sefer + özel RF
            proj = Assumptions.annual_projection(442, 1560,
                        daily_flights=3, realization_factor=0.70)

            # Override ile
            Assumptions.override('realization_factor', 'DEFAULT', 0.75, 'ops_review')
            proj = Assumptions.annual_projection(442, 1560)
            # → 0.75 kullanır

        Raises:
            ValueError: realization_factor geçersiz aralıkta
        """
        # Günlük sefer
        if daily_flights is None:
            daily_flights      = Assumptions.daily_frequency(route_nm)
            daily_flights_src  = 'tahmini'
        else:
            daily_flights_src  = 'kullanıcı tarafından verildi'

        # Gerçekleşme faktörü
        if realization_factor is None:
            rf     = Assumptions.realization_factor()
            rf_src = (
                'override (müşteri değeri)'
                if Assumptions.is_overridden('realization_factor', 'DEFAULT')
                else 'varsayılan (%65)'
            )
        else:
            rf = float(realization_factor)
            if not (0.0 < rf <= 1.0):
                raise ValueError(
                    f"realization_factor 0 ile 1 arasında olmalı, gelen: {rf}"
                )
            rf_src = 'doğrudan parametre'

        # ── FİZİKSEL ÜST SINIR ────────────────────────────────────
        # Frekans bir TAHMİNDİR (kaynaksız, ±%30). Bu yüzden yıllık
        # blok-saat, uçağın yıllık kapasitesini (MAX_ANNUAL_BLOCK_HOURS)
        # aşamaz. Aşarsa frekans kırpılır ve durum raporlanır.
        block_hr_per_flight = Assumptions._block_hours(route_nm)
        uncapped_freq       = daily_flights
        max_freq_by_capacity = (MAX_ANNUAL_BLOCK_HOURS
                                / (block_hr_per_flight * OPERATIONAL_DAYS_PER_YEAR))
        capped = False
        if daily_flights > max_freq_by_capacity:
            daily_flights = max_freq_by_capacity
            capped = True

        annual_block_hr = (daily_flights * OPERATIONAL_DAYS_PER_YEAR
                           * block_hr_per_flight)
        flight_hr_year  = annual_block_hr

        # ── FİZİKSEL vs FİYAT ARBITRAJI AYRIMI ──────────────
        # per_flight_saving_usd iki bileşen içerebilir:
        #   (a) fiziksel yakıt tasarrufu (irtifa, step climb, CI) — her
        #       uçuşta tekrarlanır
        #   (b) tankering — yakıtı ucuz yerden alıp pahalı yerden almama;
        #       bu bir FİYAT arbitrajıdır, yakıt miktarı azalmaz ve
        #       sürdürülebilirliği belirsizdir (dest fiyatı değişir,
        #       tank kapasitesi uçuşa göre değişir)
        #
        # Tankering tekrarlanabilirlik faktörü: %50 (muhafazakâr).
        # Gerekçe: fiyat farkı kalıcı değildir; tam kapasite her uçuşta
        # kullanılamaz; operatörler yakıt güvenliği için pay bırakır.
        _tank_per_flight = max(0.0, float(tankering_usd_per_flight or 0.0))
        _fuel_per_flight = max(0.0, float(per_flight_saving_usd) - _tank_per_flight)

        annual_flights = daily_flights * OPERATIONAL_DAYS_PER_YEAR
        fuel_saving_usd   = _fuel_per_flight * annual_flights * rf
        tankering_usd     = _tank_per_flight * annual_flights * rf * TANKERING_PERSISTENCE
        raw               = per_flight_saving_usd * annual_flights
        realistic         = fuel_saving_usd + tankering_usd

        return {
            'daily_flights'          : round(daily_flights, 2),
            'operational_days'       : OPERATIONAL_DAYS_PER_YEAR,
            'raw_annual_usd'         : round(raw),
            'realistic_annual_usd'   : round(realistic),
            'fuel_saving_usd'        : round(fuel_saving_usd),
            'tankering_usd'          : round(tankering_usd),
            'tankering_persistence'  : TANKERING_PERSISTENCE,
            'realization_factor'     : rf,
            'annual_block_hours'     : round(annual_block_hr),
            'block_hours_per_year'   : round(flight_hr_year),
            'capacity_capped'        : capped,
            'assumptions_used'       : {
                'daily_flights_source'    : (f'{daily_flights:.2f} sefer/gün '
                                             f'({daily_flights_src}'
                                             + (f'; kapasite tavanı {max_freq_by_capacity:.2f}'
                                                if capped else '') + ')'),
                'realization_factor_source': f'%{rf*100:.0f} ({rf_src})',
                'operational_days'        : f'{OPERATIONAL_DAYS_PER_YEAR} gün/yıl',
                'annual_block_hours'      : (f'{annual_block_hr:,.0f} blok-saat/yıl '
                                             f'(tavan {MAX_ANNUAL_BLOCK_HOURS:,.0f})'),
            },
        }

    @staticmethod
    def load_factor(airline_code: Optional[str] = None) -> float:
        """
        Tipik doluluk oranı.

        Args:
            airline_code: Havayolu kodu. None → DEFAULT.

        Returns:
            float: Load factor (0.0-1.0)
        """
        key = airline_code or 'DEFAULT'
        val = _get_override('load_factor', key)
        if val is not None:
            return float(val)

        if airline_code and airline_code in _AIRLINE_TIME_COST_MAP:
            airline_type = _AIRLINE_TIME_COST_MAP[airline_code]
            return float(_TYPICAL_LOAD_FACTOR.get(airline_type, _TYPICAL_LOAD_FACTOR['DEFAULT']))

        return float(_TYPICAL_LOAD_FACTOR['DEFAULT'])

    # ──────────────────────────────────────────────────────
    # BÖLÜM 6: DOĞRULUK NOTLARI
    # ──────────────────────────────────────────────────────

    @staticmethod
    def accuracy_note(category: str) -> dict:
        """
        Belirli bir kategori için hata payı ve açıklama.

        Args:
            category: 'oew', 'payload', 'fuel_price', 'time_cost',
                       'daily_frequency', 'realization_factor', 'engine_degradation'

        Returns:
            dict:
                uncertainty_pct: tahmini hata payı (%)
                note           : açıklama
                source         : veri kaynağı

        Örnekler:
            note = Assumptions.accuracy_note('payload')
            print(f"±{note['uncertainty_pct']}%")
        """
        if category not in _ACCURACY_NOTES:
            return {
                'uncertainty_pct': 999,
                'note'           : f"'{category}' için doğruluk notu tanımlanmamış.",
                'source'         : 'Bilinmiyor',
            }
        return _ACCURACY_NOTES[category].copy()

    @staticmethod
    def full_uncertainty_report() -> dict:
        """
        Tüm kategoriler için doğruluk raporu.

        Returns:
            dict: {kategori: doğruluk_notu}
        """
        return {cat: info.copy() for cat, info in _ACCURACY_NOTES.items()}

    # ──────────────────────────────────────────────────────
    # BÖLÜM 7: OVERRIDE SİSTEMİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def override(
        category: str,
        key: str,
        value,
        source: str = 'manual',
    ) -> None:
        """
        Varsayım değerini gerçek veriyle geçersiz kıl.

        Args:
            category: Kategori adı
            key     : Alt anahtar (uçak tipi, havalimanı kodu, ...)
            value   : Yeni değer
            source  : Veri kaynağı (raporlama şeffaflığı için)

        Örnekler:
            # Müşterinin gerçek OEW
            Assumptions.override('oew', 'B738', 42800, 'customer_weight_manual')

            # Müşterinin LTFM kontrat fiyatı
            Assumptions.override('fuel_price', 'LTFM', 0.72, 'customer_contract_2025')

            # Gerçekleşme faktörü (ops review sonrası)
            Assumptions.override('realization_factor', 'DEFAULT', 0.72, 'ops_review_jan2025')

            # Günlük gerçek sefer sayısı
            Assumptions.override('daily_freq', '1560', 3, 'customer_schedule_OAG')

        Not:
            Session bazlı. Program yeniden başlatılınca sıfırlanır.
            Kalıcı değişiklik için dosyayı düzenleyin.
        """
        if category in ('oew', 'mtow', 'max_fuel', 'realization_factor'):
            if not isinstance(value, (int, float)):
                raise TypeError(f"'{category}' için sayı gerekli, {type(value).__name__} geldi")
        if category == 'realization_factor':
            if not (0 < value <= 1):
                raise ValueError(f"realization_factor 0-1 arasında olmalı, {value} geldi")
        if category == 'daily_freq':
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise TypeError(f"daily_freq için sayı gerekli, {value} geldi")
        _set_override(category, key, value, source)

    @staticmethod
    def get_active_overrides() -> dict:
        """
        Aktif override'ları listele. Thread-safe.

        Returns:
            dict: {(category, key): {value, source, timestamp}}

        Kullanım:
            overrides = Assumptions.get_active_overrides()
            for key, info in overrides.items():
                print(f"{key}: {info['value']} [{info['source']}]")
        """
        store = _get_overrides_store()
        return {
            k: {'value': v[0], 'source': v[1], 'timestamp': v[2]}
            for k, v in store.items()
        }

    @staticmethod
    def clear_overrides() -> None:
        """Tüm override'ları temizle (orijinal varsayımlara dön). Thread-safe — sadece çağıran thread'i temizler."""
        store = _get_overrides_store()
        store.clear()

    @staticmethod
    def is_overridden(category: str, key: str) -> bool:
        """
        Belirli bir değer override edilmiş mi? Thread-safe.

        Returns:
            bool: True → müşteri/gerçek verisi kullanılıyor
        """
        store = _get_overrides_store()
        return (category, key) in store

    # ──────────────────────────────────────────────────────
    # BÖLÜM 8: DOĞRULAMA VE DURUM
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_aircraft_type(ac_type: str) -> bool:
        """
        Uçak tipinin desteklenip desteklenmediğini kontrol et.

        Returns:
            bool: True → destekleniyor

        Raises:
            ValueError: Desteklenmeyen uçak tipi
        """
        if ac_type in _OEW:
            return True
        raise ValueError(
            f"Desteklenmeyen uçak tipi: '{ac_type}'. "
            f"Desteklenen: {sorted(_OEW.keys())}. "
            f"Yeni tip: assumptions.py ve aircraft_database.yaml güncellenmeli."
        )

    @staticmethod
    def status_report() -> str:
        """
        Aktif varsayımların ve override'ların özet raporu.

        Returns:
            str: Okunabilir durum raporu
        """
        lines = [
            "═══════════════════════════════════════",
            "  VARSAYIM DURUMU RAPORU",
            f"  Gerçekleşme faktörü: %{Assumptions.realization_factor()*100:.0f}",
            "═══════════════════════════════════════",
        ]

        overrides = Assumptions.get_active_overrides()
        if overrides:
            lines.append(f"\n  ✅ GERÇEK VERİ ({len(overrides)} değer):")
            for (cat, key), info in overrides.items():
                lines.append(
                    f"     {cat}/{key}: {info['value']} "
                    f"[{info['source']}] @ {info['timestamp'][:10]}"
                )
        else:
            lines.append("\n  ⚠  Tüm değerler varsayılan (müşteri verisi yok)")

        lines.append("\n  DOĞRULUK NOTU:")
        store = _get_overrides_store()
        for cat, info in _ACCURACY_NOTES.items():
            is_overridden = any(c == cat for c, _ in store)
            status = "✅ Gerçek" if is_overridden else f"⚠  ±{info['uncertainty_pct']}% tahmin"
            lines.append(f"     {cat:<25} {status}")

        lines.append("\n═══════════════════════════════════════")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_assumptions() -> bool:
    """
    Varsayım değerlerinin tutarlılığını kontrol et.

    Çalıştırma:
        python -m config.assumptions
    """
    print("\n" + "=" * 60)
    print("  ASSUMPTIONS.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests  = 0

    def check(name: str, actual, expected, tol: float = 0.01) -> None:
        nonlocal tests
        tests += 1
        try:
            diff = abs(float(actual) - float(expected))
        except (TypeError, ValueError) as exc:
            errors.append(f"{name}: tip hatası: {exc}")
            print(f"  ❌ {name}")
            return
        if diff > tol:
            errors.append(f"{name}: {actual} ≠ {expected} (Δ={diff:.4f})")
            print(f"  ❌ {name}: {actual} ≠ {expected}")
        else:
            print(f"  ✅ {name} = {actual}")

    def check_raises(name: str, func, args: tuple, exc) -> None:
        nonlocal tests
        tests += 1
        if exc in (KeyboardInterrupt, SystemExit):
            errors.append(f"{name}: test mantık hatası")
            return
        try:
            func(*args)
            errors.append(f"{name}: {exc.__name__} beklendi ama verilmedi")
            print(f"  ❌ {name}: hata verilmedi")
        except exc:
            print(f"  ✅ {name} → {exc.__name__}")
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            errors.append(f"{name}: yanlış hata {type(e).__name__}")
            print(f"  ❌ {name}: yanlış hata: {type(e).__name__}: {e}")

    # ─── [1] Uçak parametreleri ───────────────────────────
    print("\n  [1] Uçak Parametreleri")
    check("OEW B738",     Assumptions.aircraft_oew('B738'),      41413, 1.0)
    check("OEW A320",     Assumptions.aircraft_oew('A320'),      42600, 1.0)
    check("MTOW B738",    Assumptions.aircraft_mtow('B738'),     79016, 1.0)
    check("MaxFuel B738", Assumptions.aircraft_max_fuel('B738'), 20894, 1.0)
    check_raises("OEW XXXX",   Assumptions.aircraft_oew,          ('XXXX',), KeyError)
    check_raises("MTOW XXXX",  Assumptions.aircraft_mtow,         ('XXXX',), KeyError)
    check_raises("Fuel XXXX",  Assumptions.aircraft_max_fuel,     ('XXXX',), KeyError)
    check_raises("Valid XXXX", Assumptions.validate_aircraft_type,('XXXX',), ValueError)

    tests += 1
    if Assumptions.validate_aircraft_type('B738'):
        print("  ✅ validate_aircraft_type B738")
    else:
        errors.append("validate_aircraft_type B738 başarısız")

    p_default = Assumptions.typical_payload('B738')
    p_full    = Assumptions.typical_payload('B738', load_factor=0.95)
    p_short   = Assumptions.typical_payload('B738', route_nm=300)
    p_long    = Assumptions.typical_payload('B738', route_nm=5000)
    tests += 1
    if p_default > 0 and p_full > p_default and p_long > p_short:
        print(f"  ✅ Payload mantıklı: default={p_default:.0f}, "
              f"dolu={p_full:.0f}, kısa={p_short:.0f}, uzun={p_long:.0f}")
    else:
        errors.append("Payload mantıksız")
        print("  ❌ Payload mantıksız")

    # ─── [2] Yakıt fiyatları ──────────────────────────────
    print("\n  [2] Yakıt Fiyatları")
    check("Fuel LTFM", Assumptions.fuel_price('LTFM'), 0.78, 0.01)
    check("Fuel EGLL", Assumptions.fuel_price('EGLL'), 1.05, 0.01)
    check("Fuel OMDB", Assumptions.fuel_price('OMDB'), 0.58, 0.01)

    tests += 1
    if Assumptions.fuel_price('EGLL') > Assumptions.fuel_price('LTFM'):
        print("  ✅ Londra > İstanbul yakıt fiyatı")
    else:
        errors.append("Londra < İstanbul (fiziksel olarak beklenmiyor)")
        print("  ❌ Londra < İstanbul")

    # Bilinmeyen → uyarı + DEFAULT veya ülke fiyatı
    tests += 1
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        price_unk = Assumptions.fuel_price('ZZZZ')
        if caught and price_unk > 0:
            print(f"  ✅ Bilinmeyen ZZZZ → ${price_unk:.3f} + uyarı")
        else:
            errors.append(f"Bilinmeyen havalimanı yanlış: {price_unk}")

    diff_ist_lon = Assumptions.fuel_price_differential('LTFM', 'EGLL')
    tests += 1
    if diff_ist_lon['tankering_viable'] and diff_ist_lon['price_diff'] > 0:
        print(f"  ✅ IST→LON tankering viable (${diff_ist_lon['price_diff']:.3f}/kg)")
    else:
        errors.append("IST→LON tankering viable olmalı")
        print("  ❌ IST→LON tankering viable değil")

    diff_ist_dxb = Assumptions.fuel_price_differential('LTFM', 'OMDB')
    tests += 1
    if not diff_ist_dxb['tankering_viable']:
        print("  ✅ IST→DXB tankering not viable (Dubai ucuz)")
    else:
        errors.append("IST→DXB tankering viable olmamalı")
        print("  ❌ IST→DXB tankering viable (yanlış, Dubai ucuz)")

    # ─── [3] Zaman maliyeti ───────────────────────────────
    print("\n  [3] Zaman Maliyeti")
    check("Time PGT",     Assumptions.time_cost('PGT'),     1200, 1.0)
    check("Time THY",     Assumptions.time_cost('THY'),     2200, 1.0)
    check("Time lcc",     Assumptions.time_cost('lcc'),     1200, 1.0)
    check("Time premium", Assumptions.time_cost('premium'), 3000, 1.0)

    tests += 1
    if Assumptions.time_cost('THY') > Assumptions.time_cost('PGT'):
        print("  ✅ Network > LCC zaman maliyeti")
    else:
        errors.append("Network ≥ LCC olmalı")
        print("  ❌ Network ≤ LCC")

    # ─── [4] Gerçekleşme faktörü ──────────────────────────
    print("\n  [4] Gerçekleşme Faktörü (realization_factor)")

    # Varsayılan
    tests += 1
    rf_default = Assumptions.realization_factor()
    if abs(rf_default - 0.65) < 0.001:
        print(f"  ✅ Varsayılan RF = {rf_default}")
    else:
        errors.append(f"Varsayılan RF yanlış: {rf_default}")
        print(f"  ❌ Varsayılan RF = {rf_default}")

    # Override
    Assumptions.override('realization_factor', 'DEFAULT', 0.75, 'test_override')
    tests += 1
    rf_overridden = Assumptions.realization_factor()
    if abs(rf_overridden - 0.75) < 0.001:
        print(f"  ✅ Override RF = {rf_overridden}")
    else:
        errors.append(f"Override RF yanlış: {rf_overridden}")
        print(f"  ❌ Override RF = {rf_overridden}")

    # Temizle ve varsayılana dön
    Assumptions.clear_overrides()
    tests += 1
    rf_restored = Assumptions.realization_factor()
    if abs(rf_restored - 0.65) < 0.001:
        print(f"  ✅ Clear sonrası RF geri geldi: {rf_restored}")
    else:
        errors.append(f"Clear sonrası RF yanlış: {rf_restored}")
        print(f"  ❌ Clear sonrası RF = {rf_restored}")

    # Geçersiz override → ValueError
    Assumptions.override('realization_factor', 'DEFAULT', 1.5, 'bad_test')
    tests += 1
    try:
        _ = Assumptions.realization_factor()
        errors.append("RF=1.5 ValueError vermeli")
        print("  ❌ RF=1.5 hata vermedi")
    except ValueError:
        print("  ✅ RF=1.5 → ValueError yakalandı")
    except (KeyboardInterrupt, SystemExit):
        raise
    finally:
        Assumptions.clear_overrides()

    # Sıfır override
    Assumptions.override('realization_factor', 'DEFAULT', 0.0, 'bad_test')
    tests += 1
    try:
        _ = Assumptions.realization_factor()
        errors.append("RF=0.0 ValueError vermeli")
        print("  ❌ RF=0.0 hata vermedi")
    except ValueError:
        print("  ✅ RF=0.0 → ValueError yakalandı")
    except (KeyboardInterrupt, SystemExit):
        raise
    finally:
        Assumptions.clear_overrides()

    # annual_projection ile entegrasyon
    proj_default = Assumptions.annual_projection(442.0, 1560)
    tests += 1
    if abs(proj_default['realization_factor'] - 0.65) < 0.001:
        print(f"  ✅ annual_projection varsayılan RF=0.65 kullanıyor")
    else:
        errors.append(f"annual_projection RF yanlış: {proj_default['realization_factor']}")
        print(f"  ❌ annual_projection RF = {proj_default['realization_factor']}")

    proj_override = Assumptions.annual_projection(442.0, 1560, realization_factor=0.70)
    tests += 1
    if abs(proj_override['realization_factor'] - 0.70) < 0.001:
        print(f"  ✅ annual_projection doğrudan RF=0.70 kullanıyor")
    else:
        errors.append(f"annual_projection direkt RF yanlış: {proj_override['realization_factor']}")
        print(f"  ❌ annual_projection direkt RF = {proj_override['realization_factor']}")

    # annual_projection override ile
    Assumptions.override('realization_factor', 'DEFAULT', 0.75, 'test')
    proj_from_override = Assumptions.annual_projection(442.0, 1560)
    tests += 1
    if abs(proj_from_override['realization_factor'] - 0.75) < 0.001:
        print(f"  ✅ annual_projection override RF=0.75 kullanıyor")
    else:
        errors.append(f"annual_projection override RF yanlış: {proj_from_override['realization_factor']}")
        print(f"  ❌ annual_projection override RF = {proj_from_override['realization_factor']}")
    Assumptions.clear_overrides()

    # Gerçekçi < teorik kontrolü
    tests += 1
    if proj_default['realistic_annual_usd'] < proj_default['raw_annual_usd']:
        print(f"  ✅ Gerçekçi ({proj_default['realistic_annual_usd']:,}) "
              f"< Teorik ({proj_default['raw_annual_usd']:,})")
    else:
        errors.append("Gerçekçi ≥ Teorik (yanlış)")
        print("  ❌ Gerçekçi ≥ Teorik")

    # annual_projection geçersiz RF → ValueError
    tests += 1
    try:
        Assumptions.annual_projection(442.0, 1560, realization_factor=1.5)
        errors.append("RF=1.5 ValueError vermeli")
        print("  ❌ RF=1.5 hata vermedi")
    except ValueError:
        print("  ✅ annual_projection RF=1.5 → ValueError")
    except (KeyboardInterrupt, SystemExit):
        raise

    # ─── [5] Operasyonel varsayımlar ─────────────────────
    print("\n  [5] Operasyonel Varsayımlar")
    check("Freq 190 Nm",  Assumptions.daily_frequency(190),  6, 0.1)
    check("Freq 1560 Nm", Assumptions.daily_frequency(1560), 2, 0.1)
    check("Freq 5000 Nm", Assumptions.daily_frequency(5000), 1, 0.1)

    check("LF default",   Assumptions.load_factor(),       0.82, 0.01)
    check("LF PGT",       Assumptions.load_factor('PGT'),  0.87, 0.01)

    # ─── [6] Override sistemi ─────────────────────────────
    print("\n  [6] Override Sistemi")

    original_oew = Assumptions.aircraft_oew('B738')
    Assumptions.override('oew', 'B738', 42800, 'test')

    tests += 1
    if abs(Assumptions.aircraft_oew('B738') - 42800) < 1:
        print("  ✅ Override çalışıyor")
    else:
        errors.append("Override çalışmıyor")
        print("  ❌ Override çalışmıyor")

    tests += 1
    if Assumptions.is_overridden('oew', 'B738'):
        print("  ✅ is_overridden() doğru")
    else:
        errors.append("is_overridden yanlış")
        print("  ❌ is_overridden yanlış")

    tests += 1
    active = Assumptions.get_active_overrides()
    if ('oew', 'B738') in active:
        print(f"  ✅ get_active_overrides: {len(active)} override")
    else:
        errors.append("get_active_overrides eksik")
        print("  ❌ get_active_overrides eksik")

    Assumptions.clear_overrides()
    tests += 1
    if abs(Assumptions.aircraft_oew('B738') - original_oew) < 1:
        print(f"  ✅ clear_overrides sonrası orijinal değer: {original_oew}")
    else:
        errors.append("clear_overrides çalışmıyor")
        print("  ❌ clear_overrides çalışmıyor")

    tests += 1
    if not Assumptions.is_overridden('oew', 'B738'):
        print("  ✅ clear sonrası is_overridden False")
    else:
        errors.append("clear_overrides sonrası is_overridden hâlâ True")
        print("  ❌ clear sonrası is_overridden hâlâ True")

    # ─── [7] Doğruluk notları ─────────────────────────────
    print("\n  [7] Doğruluk Notları")
    for cat in _ACCURACY_NOTES:
        note = Assumptions.accuracy_note(cat)
        tests += 1
        if note['uncertainty_pct'] > 0 and note['note']:
            print(f"  ✅ {cat}: ±{note['uncertainty_pct']}%")
        else:
            errors.append(f"Doğruluk notu eksik: {cat}")
            print(f"  ❌ {cat}: eksik")

    tests += 1
    note_unk = Assumptions.accuracy_note('bilinmeyen')
    if note_unk['uncertainty_pct'] == 999:
        print("  ✅ Bilinmeyen kategori güvenli döndü")
    else:
        errors.append("Bilinmeyen kategori yanlış")
        print("  ❌ Bilinmeyen kategori yanlış")

    # ─── [8] Durum raporu ─────────────────────────────────
    print("\n  [8] Durum Raporu")
    tests += 1
    try:
        report = Assumptions.status_report()
        if len(report) > 100:
            print("  ✅ Durum raporu üretildi")
        else:
            errors.append("Durum raporu çok kısa")
            print("  ❌ Durum raporu çok kısa")
    except Exception as e:
        errors.append(f"Durum raporu hatası: {e}")
        print(f"  ❌ Durum raporu: {e}")

    # ─── SONUÇ ────────────────────────────────────────────
    print(f"\n  {'─' * 50}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print(f"\n  ❌ BAŞARISIZ TESTLER:")
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
    ok = validate_assumptions()
    print(Assumptions.status_report())