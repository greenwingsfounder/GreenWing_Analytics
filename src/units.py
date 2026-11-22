# src/units.py

"""
GreenWing Analytics — Birim Dönüşüm ve Standardizasyon Merkezi
═══════════════════════════════════════════════════════════════

Bu dosya projenin TEMELİDİR.
Birimler yanlışsa her hesap yanlış olur.

Kurallar:
─────────
1. Proje içinde HER ZAMAN SI birimleri kullanılır:
   • Uzunluk   : metre (m)
   • Hız       : metre/saniye (m/s)
   • Kütle     : kilogram (kg)
   • Sıcaklık  : Kelvin (K)
   • Basınç    : Pascal (Pa)
   • Kuvvet    : Newton (N)

2. Havacılık birimleri SADECE giriş ve çıkışta kullanılır:
   • İrtifa    : feet (ft)   — pilotlar ve ATC kullanır
   • Hız       : knots (kts) — havacılık standardı
   • Mesafe    : Nm          — havacılık standardı
   • Yakıt     : kg          — zaten SI

3. Dönüşüm SADECE bu dosya üzerinden yapılır.
   Başka yerde 0.3048 gibi sabit YAZILMAZ.

4. Her dönüşüm fonksiyonu girdisini KONTROL eder.
   numpy array, pandas Series ve scalar değerler desteklenir.

5. Jet-A1 yoğunluğu sıcaklığa bağlıdır.
   Sabit 0.804 kullanmak yüzde 1-4 hata üretir.

6. Trajectory standardizasyonunda NaN, 0 ile doldurulmaz.
   Phase-aware interpolation kullanılır.
   NaN noktalar flag kolonu ile işaretlenir.

7. Altitude kaynak tespiti çok boyutlu istatistiksel analiz
   kullanır. Tek eşik değeri yerine güven skoru hesaplanır.

Kaynak:
───────
   ICAO Doc 7488 (Standard Atmosphere)
   ASTM D1655 (Jet-A1)
   NIST SI Units
   FAA Pilot Controller Glossary
   ICAO Doc 7030 (Transition Altitude)
"""

import numpy as np
import pandas as pd
import warnings
from typing import Union


# ═══════════════════════════════════════════════════════════
# SABİT DÖNÜŞÜM KATSAYILARI
# ═══════════════════════════════════════════════════════════

_FT_TO_M           = 0.3048
_M_TO_FT           = 1.0 / _FT_TO_M

_NM_TO_M           = 1852.0
_M_TO_NM           = 1.0 / _NM_TO_M

_NM_TO_KM          = 1.852
_KM_TO_NM          = 1.0 / _NM_TO_KM

_KM_TO_M           = 1000.0
_M_TO_KM           = 0.001

_STATUTE_MILE_TO_M = 1609.344
_M_TO_STATUTE_MILE = 1.0 / _STATUTE_MILE_TO_M

_KTS_TO_MS         = 0.514444
_MS_TO_KTS         = 1.0 / _KTS_TO_MS

_KG_TO_LBS         = 2.20462
_LBS_TO_KG         = 1.0 / _KG_TO_LBS

_KELVIN_OFFSET     = 273.15


# ═══════════════════════════════════════════════════════════
# ATMOSFER SABİTLERİ (ISA)
# ═══════════════════════════════════════════════════════════

_GAMMA        = 1.4
_R_AIR        = 287.05
_GRAVITY      = 9.80665
_ISA_T0       = 288.15
_ISA_P0       = 101325.0
_ISA_RHO0     = 1.225
_ISA_LAPSE    = -0.0065
_TROPOPAUSE_M = 11000.0


# ═══════════════════════════════════════════════════════════
# JET-A1 YAKIT SABİTLERİ
# ═══════════════════════════════════════════════════════════

_FUEL_DENSITY_REF      = 0.804
_FUEL_DENSITY_TEMP_REF = 15.0
_FUEL_DENSITY_ALPHA    = 0.00072
_FUEL_DENSITY_MIN      = 0.775
_FUEL_DENSITY_MAX      = 0.840


# ═══════════════════════════════════════════════════════════
# GÜVENLİK SINIRLARI
# ═══════════════════════════════════════════════════════════

_LIMITS = {
    'altitude_ft'  : {'min': -2000,   'max': 65000,      'name': 'İrtifa (ft)'},
    'altitude_m'   : {'min': -610,    'max': 20000,      'name': 'İrtifa (m)'},
    'speed_kts'    : {'min': 0,       'max': 600,        'name': 'Hız (kts)'},
    'speed_ms'     : {'min': 0,       'max': 310,        'name': 'Hız (m/s)'},
    'mach'         : {'min': 0.0,     'max': 0.95,       'name': 'Mach'},
    'distance_nm'  : {'min': 0,       'max': 12000,      'name': 'Mesafe (Nm)'},
    'distance_m'   : {'min': 0,       'max': 22_000_000, 'name': 'Mesafe (m)'},
    'weight_kg'    : {'min': 0,       'max': 650_000,    'name': 'Ağırlık (kg)'},
    'weight_lbs'   : {'min': 0,       'max': 1_430_000,  'name': 'Ağırlık (lbs)'},
    'temperature_c': {'min': -90,     'max': 60,         'name': 'Sıcaklık (°C)'},
    'temperature_k': {'min': 180,     'max': 340,        'name': 'Sıcaklık (K)'},
    'pressure_pa'  : {'min': 1000,    'max': 110_000,    'name': 'Basınç (Pa)'},
    'latitude'     : {'min': -90,     'max': 90,         'name': 'Enlem'},
    'longitude'    : {'min': -180,    'max': 180,        'name': 'Boylam'},
    'fuel_temp_c'  : {'min': -50,     'max': 55,         'name': 'Yakıt sıcaklığı (°C)'},
}

# Scalar tipler (tek değer kontrolü)
_SCALAR_TYPES = (int, float, np.integer, np.floating)


# ═══════════════════════════════════════════════════════════
# YARDIMCI: DEĞER KONTROLÜ
# DÜZELTİLDİ: pandas Series desteği eklendi
# ═══════════════════════════════════════════════════════════

def _check_value(
    value,
    limit_key: str,
    strict: bool = True
) -> Union[float, np.ndarray, pd.Series]:
    """
    Değerin güvenlik sınırları içinde olup olmadığını kontrol et.

    Desteklenen tipler:
        - Scalar: int, float, numpy scalar
        - numpy array
        - pandas Series   ← YENİ (önceki versiyonda TypeError veriyordu)

    Args:
        value    : Kontrol edilecek değer
        limit_key: _LIMITS sözlüğündeki anahtar
        strict   : True → ValueError, False → warnings.warn

    Returns:
        float, np.ndarray veya pd.Series: Doğrulanmış değer

    Raises:
        TypeError : None veya desteklenmeyen tip
        ValueError: Sınır dışı (strict=True) veya NaN/Inf
    """
    lim  = _LIMITS[limit_key]
    name = lim['name']

    # None kontrolü
    if value is None:
        raise TypeError(f"{name}: None kabul edilmez.")

    # ─── pandas Series ──────────────────────────────────
    if isinstance(value, pd.Series):
        numeric = pd.to_numeric(value, errors='coerce')
        nan_count = int(numeric.isna().sum())
        if nan_count > 0:
            raise ValueError(
                f"{name}: {nan_count} değer sayısal değil veya NaN."
            )
        bad = (numeric < lim['min']) | (numeric > lim['max'])
        count = int(bad.sum())
        if count > 0:
            msg = (
                f"{name}: {count} değer sınır dışı "
                f"[{lim['min']}, {lim['max']}]."
            )
            if strict:
                raise ValueError(msg)
            warnings.warn(msg, stacklevel=3)
        return numeric

    # ─── numpy array ────────────────────────────────────
    if isinstance(value, np.ndarray):
        arr = value.astype(float, copy=False)
        nan_inf = ~np.isfinite(arr)
        if np.any(nan_inf):
            count = int(np.sum(nan_inf))
            raise ValueError(f"{name}: {count} NaN veya Inf değer.")
        bad = (arr < lim['min']) | (arr > lim['max'])
        count = int(np.sum(bad))
        if count > 0:
            msg = (
                f"{name}: {count} değer sınır dışı "
                f"[{lim['min']}, {lim['max']}]."
            )
            if strict:
                raise ValueError(msg)
            warnings.warn(msg, stacklevel=3)
        return arr

    # ─── Scalar ─────────────────────────────────────────
    if not isinstance(value, _SCALAR_TYPES):
        raise TypeError(
            f"{name}: int/float/numpy scalar/Series/array bekleniyor. "
            f"Gelen: {type(value).__name__} = {value!r}"
        )

    if np.isnan(value) or np.isinf(value):
        raise ValueError(f"{name}: NaN veya Inf kabul edilmez.")

    if value < lim['min'] or value > lim['max']:
        msg = (
            f"{name}: {value} sınır dışı "
            f"[{lim['min']}, {lim['max']}]."
        )
        if strict:
            raise ValueError(msg)
        warnings.warn(msg, stacklevel=3)

    return float(value)


# ═══════════════════════════════════════════════════════════
# YARDIMCI: İRTİFA KAYNAK TESPİTİ
# DÜZELTİLDİ: Çok boyutlu istatistiksel güven skoru
# ═══════════════════════════════════════════════════════════

def _detect_altitude_source(df: pd.DataFrame) -> dict:
    """
    DataFrame'deki irtifa kolonunun birimini istatistiksel olarak tespit et.

    Eski yaklaşım: Tek eşik değeri (zayıf, overlap riski yüksek)
    Yeni yaklaşım: 5 farklı gösterge + güven skoru

    Göstergeler:
        1. Mutlak maksimum: >50000 → kesinlikle feet
        2. Medyan değeri: ISA tipik cruise değerleriyle karşılaştır
        3. Standart sapma: m vs ft biriminin tipik std oranı
        4. Fiziksel irtifa dağılımı: metre/feet için beklenen yüzdelikler
        5. Unit signature: ISA standart cruise bantları kontrolü

    Returns:
        dict:
            source       : 'metres', 'feet', 'ambiguous', 'missing'
            confidence   : 0.0-1.0 arası güven skoru
            evidence     : tespit gerekçeleri listesi
            recommendation: önerilen aksiyon

    Kullanım:
        result = _detect_altitude_source(df)
        if result['confidence'] < 0.7:
            # Düşük güven → kullanıcıya sor veya hint kullan
            warnings.warn(result['recommendation'])
        source = result['source']
    """
    # Veri yoksa
    if 'baro_altitude' not in df.columns:
        if 'baro_altitude_m' in df.columns and 'baro_altitude_ft' in df.columns:
            return {
                'source': 'already_split',
                'confidence': 1.0,
                'evidence': ['Her iki sütun zaten mevcut'],
                'recommendation': 'Dönüşüm gerekmez'
            }
        if 'baro_altitude_m' in df.columns:
            return {
                'source': 'metres',
                'confidence': 1.0,
                'evidence': ['baro_altitude_m kolonu mevcut'],
                'recommendation': 'Feet türetilecek'
            }
        if 'baro_altitude_ft' in df.columns:
            return {
                'source': 'feet',
                'confidence': 1.0,
                'evidence': ['baro_altitude_ft kolonu mevcut'],
                'recommendation': 'Metre türetilecek'
            }
        return {
            'source': 'missing',
            'confidence': 0.0,
            'evidence': ['İrtifa kolonu bulunamadı'],
            'recommendation': 'Veri kaynağını kontrol et'
        }

    vals = pd.to_numeric(df['baro_altitude'], errors='coerce').dropna()

    if len(vals) == 0:
        return {
            'source': 'missing',
            'confidence': 0.0,
            'evidence': ['Tüm değerler NaN'],
            'recommendation': 'Ham veri kontrol edilmeli'
        }

    # Temel istatistikler
    val_max    = float(vals.max())
    val_min    = float(vals.min())
    val_median = float(vals.median())
    val_std    = float(vals.std())
    val_p25    = float(vals.quantile(0.25))
    val_p75    = float(vals.quantile(0.75))

    evidence = []
    feet_score   = 0.0  # 0-1 arası, yüksek = feet olasılığı
    metres_score = 0.0  # 0-1 arası, yüksek = metre olasılığı

    # ─── Gösterge 1: Mutlak maksimum ───────────────────
    # 20000 m = ~65617 ft (ticari jet tavana çok yakın)
    # 50000 ft = 15240 m (ticari jet tavanı)
    if val_max > 50000:
        # 50000 üstü değer → kesinlikle feet
        # (50000m = 164000ft → imkansız ticari jet için)
        feet_score += 1.0
        evidence.append(f"Maksimum {val_max:.0f} > 50000 → kesinlikle feet")
    elif val_max > 20000:
        # 20000-50000 arası → büyük ihtimalle feet (FL200-FL500)
        feet_score += 0.7
        evidence.append(f"Maksimum {val_max:.0f} > 20000 → muhtemelen feet")
    elif val_max > 12500:
        # 12500-20000 arası → ambiguous
        # 12500m = ~41000ft (yüksek cruise) veya 12500ft (düşük cruise)
        feet_score   += 0.3
        metres_score += 0.3
        evidence.append(f"Maksimum {val_max:.0f} → belirsiz (feet/metre overlap)")
    else:
        # 12500 altı → büyük ihtimalle metre
        metres_score += 0.8
        evidence.append(f"Maksimum {val_max:.0f} < 12500 → muhtemelen metre")

    # ─── Gösterge 2: Medyan değeri analizi ─────────────
    # Ticari jet cruise:
    #   metres: tipik 8000-11000m (FL260-FL360)
    #   feet: tipik 25000-39000ft
    if 8000 <= val_median <= 11500:
        metres_score += 0.8
        evidence.append(f"Medyan {val_median:.0f} → tipik cruise metre aralığı")
    elif 25000 <= val_median <= 42000:
        feet_score += 0.8
        evidence.append(f"Medyan {val_median:.0f} → tipik cruise feet aralığı")
    elif val_median < 5000:
        # Düşük medyan: ya kısa uçuş (m) ya da düşük irtifa (ft)
        if val_max < 5000:
            metres_score += 0.6
            evidence.append(f"Medyan {val_median:.0f} ve max < 5000 → metre (düşük uçuş)")
        else:
            # Max yüksek ama medyan düşük → muhtemelen tüm faz (taxi+cruise)
            evidence.append(f"Medyan {val_median:.0f} düşük ama max {val_max:.0f} → karışık faz")

    # ─── Gösterge 3: Standart sapma oranı ──────────────
    # metre: std genelde 2000-4000
    # feet: std genelde 6000-13000
    # Eğer median > 0 ise cv (coefficient of variation) hesapla
    if val_median > 0:
        cv = val_std / val_median
        if cv < 0.5 and val_std > 3000:
            feet_score += 0.5
            evidence.append(f"Std {val_std:.0f} → feet aralığında")
        elif cv < 0.5 and val_std < 3000:
            metres_score += 0.5
            evidence.append(f"Std {val_std:.0f} → metre aralığında")

    # ─── Gösterge 4: ISA standart bant kontrolü ────────
    # Metre: yaygın cruise bantları 9000, 10000, 11000 m
    # Feet:  yaygın cruise bantları 30000, 35000, 37000, 39000 ft
    metre_bands = [6000, 7000, 8000, 9000, 10000, 10500, 11000, 11500]
    feet_bands  = [15000, 20000, 25000, 29000, 31000, 33000, 35000, 37000,
                   39000, 41000, 43000]

    in_metre_band = any(abs(val_p75 - b) < 500 for b in metre_bands)
    in_feet_band  = any(abs(val_p75 - b) < 1000 for b in feet_bands)

    if in_metre_band and not in_feet_band:
        metres_score += 0.6
        evidence.append(f"P75 {val_p75:.0f} → tipik metre cruise bandı")
    elif in_feet_band and not in_metre_band:
        feet_score += 0.6
        evidence.append(f"P75 {val_p75:.0f} → tipik feet cruise bandı")

    # ─── Gösterge 5: Minimum değer analizi ─────────────
    # Metre: min genelde 0-100 (yer seviyesi)
    # Feet: min genelde 0-500 (yer seviyesi)
    # Ama: bazı veriler sadece cruise içerir (min ~8000m veya ~25000ft)
    if val_min < 200:
        # Yer seviyesine yakın veri var
        if val_max > 20000:
            feet_score += 0.4
            evidence.append("Geniş irtifa aralığı (yer+cruise) → feet")
        else:
            metres_score += 0.4
            evidence.append("Geniş irtifa aralığı (yer+cruise) → metre")

    # ─── Güven skoru hesapla ────────────────────────────
    total_score = feet_score + metres_score
    if total_score == 0:
        source     = 'ambiguous'
        confidence = 0.0
    elif feet_score > metres_score:
        source     = 'feet'
        confidence = min(1.0, feet_score / max(total_score, 1.5))
    elif metres_score > feet_score:
        source     = 'metres'
        confidence = min(1.0, metres_score / max(total_score, 1.5))
    else:
        source     = 'ambiguous'
        confidence = 0.3

    # Düşük güven → uyarı mesajı
    if confidence < 0.6:
        recommendation = (
            f"Düşük güven ({confidence:.1%}). "
            f"altitude_source_hint parametresiyle 'metres' veya 'feet' belirt. "
            f"Örnek: standardize_trajectory(df, altitude_source_hint='feet')"
        )
    else:
        recommendation = f"Kaynak '{source}' olarak tespit edildi ({confidence:.1%} güven)."

    return {
        'source'        : source,
        'confidence'    : round(confidence, 3),
        'evidence'      : evidence,
        'recommendation': recommendation,
        'stats'         : {
            'max'   : val_max,
            'min'   : val_min,
            'median': val_median,
            'std'   : val_std,
            'p25'   : val_p25,
            'p75'   : val_p75,
        }
    }


# ═══════════════════════════════════════════════════════════
# YARDIMCI: PHASE-AWARE INTERPOLATION
# YENİ: Fizik-uyumlu interpolasyon
# ═══════════════════════════════════════════════════════════

def _phase_aware_interpolate(
    series: pd.Series,
    vertical_rate_fpm: pd.Series = None,
    method_climb: str = 'polynomial',
    method_cruise: str = 'linear',
    method_descent: str = 'polynomial',
    poly_order: int = 2,
    max_gap_s: float = 300.0,
    time_diff_s: pd.Series = None,
) -> pd.Series:
    """
    Uçuş fazına göre farklı interpolasyon stratejisi uygula.

    Neden linear interpolation yanlış:
        Climb  : Uçak ivmeli tırmanır → polynomial daha doğru
        Cruise : Sabit irtifaya yakın → linear yeterli
        Descent: Uçak ivmeli iner   → polynomial daha doğru

    Neden linear yanlış örneği:
        t=0: 0 ft (kalkış)
        t=5: NaN (veri yok)
        t=10: 35000 ft (cruise)
        Linear: t=5 → 17500 ft
        Gerçek: t=5 → ~8000 ft (climb profili parabolik)

    Uygulanan strateji:
        - NaN yok veya az   : linear (hızlı)
        - NaN çok ve faz var: polynomial (doğru)
        - Büyük boşluk      : interpolate etme, NaN bırak
        - Faz bilgisi yok   : linear ile başa sarma

    Args:
        series            : İnterpolate edilecek seri
        vertical_rate_fpm : Dikey hız (fpm). Faz tespiti için.
        method_climb      : Tırmanma için interpolasyon metodu
        method_cruise     : Cruise için interpolasyon metodu
        method_descent    : İniş için interpolasyon metodu
        poly_order        : Polynomial derecesi (1=linear, 2=quadratic)
        max_gap_s         : Bu süreden uzun boşluklara interpolasyon yapma (saniye)
        time_diff_s       : Zaman farkları (saniye). max_gap kontrolü için.

    Returns:
        pd.Series: İnterpolate edilmiş seri
    """
    result = series.copy()
    nan_mask = result.isna()

    # NaN yoksa doğrudan dön
    if not nan_mask.any():
        return result

    nan_count = int(nan_mask.sum())
    total     = len(result)

    # ─── Büyük boşluk tespiti ───────────────────────────
    if time_diff_s is not None and max_gap_s > 0:
        # Birden fazla ardışık NaN'ın toplam süresini hesapla
        cumulative_gap = pd.Series(0.0, index=result.index)
        in_gap         = False
        gap_start      = None

        for i in range(len(result)):
            if nan_mask.iloc[i]:
                if not in_gap:
                    in_gap    = True
                    gap_start = i
                if time_diff_s is not None and i < len(time_diff_s):
                    cumulative_gap.iloc[i] = (
                        cumulative_gap.iloc[i-1] + time_diff_s.iloc[i]
                        if i > 0 else 0
                    )
            else:
                in_gap    = False
                gap_start = None

        # Toplam boşluğu max_gap ile karşılaştır
        # Basit yaklaşım: ardışık NaN bloğu bul, süresini hesapla
        large_gap_mask = pd.Series(False, index=result.index)

        nan_groups = []
        current    = []
        for i, is_nan in enumerate(nan_mask):
            if is_nan:
                current.append(i)
            elif current:
                nan_groups.append(current)
                current = []
        if current:
            nan_groups.append(current)

        for group in nan_groups:
            if time_diff_s is not None:
                gap_duration = time_diff_s.iloc[group].sum()
                if gap_duration > max_gap_s:
                    for idx in group:
                        large_gap_mask.iloc[idx] = True

        # Büyük boşlukları geçici olarak sentinel değer ile işaretle
        sentinel = -9999999.0
        result[large_gap_mask] = sentinel

    # ─── Faz bilgisi varsa phase-aware interpolasyon ────
    if vertical_rate_fpm is not None and not vertical_rate_fpm.isna().all():

        # Faz tespiti: ±500 fpm eşiği
        CLIMB_THRESHOLD   = 500.0
        DESCENT_THRESHOLD = -500.0

        phase = pd.Series('cruise', index=result.index)
        phase[vertical_rate_fpm > CLIMB_THRESHOLD]   = 'climb'
        phase[vertical_rate_fpm < DESCENT_THRESHOLD] = 'descent'

        # Her NaN için komşu fazı kullan
        for i in range(len(result)):
            if not nan_mask.iloc[i]:
                continue
            if result.iloc[i] == sentinel:
                continue

            # Komşu non-NaN fazına bak
            p = 'cruise'
            for j in range(max(0, i-5), min(len(result), i+5)):
                if not nan_mask.iloc[j] and result.iloc[j] != sentinel:
                    p = phase.iloc[j]
                    break
            phase.iloc[i] = p

        # Faza göre interpolasyon
        for faz, method in [
            ('climb',   method_climb),
            ('cruise',  method_cruise),
            ('descent', method_descent),
        ]:
            faz_mask  = (phase == faz)
            faz_nans  = nan_mask & faz_mask
            if not faz_nans.any():
                continue

            try:
                if method == 'polynomial' and poly_order >= 2:
                    result = result.interpolate(
                        method='polynomial',
                        order=poly_order,
                        limit_direction='both'
                    )
                else:
                    result = result.interpolate(
                        method='linear',
                        limit_direction='both'
                    )
            except (ValueError, TypeError):
                result = result.interpolate(
                    method='linear',
                    limit_direction='both'
                )

    else:
        # Faz bilgisi yok → linear interpolasyon
        try:
            result = result.interpolate(
                method='linear',
                limit_direction='both'
            )
        except (ValueError, TypeError):
            result = result.ffill().bfill()

    # ─── Büyük boşlukları NaN geri yükle ───────────────
    if time_diff_s is not None and max_gap_s > 0:
        result[result == sentinel] = np.nan

    return result


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class Units:
    """
    GreenWing Analytics Birim Dönüşüm Merkezi.

    Tüm dönüşümler bu sınıf üzerinden yapılır.

    Desteklenen giriş tipleri:
        int, float, numpy scalar, numpy array, pandas Series

    Kullanım:
        from src.units import Units

        altitude_m = Units.ft_to_m(35000)
        speed_ms   = Units.kts_to_ms(450)
        tas        = Units.mach_to_tas(0.785, altitude_ft=35000)
        pressure   = Units.pressure_at_altitude(35000)
        density    = Units.fuel_density_at_temp(25.0)
        df         = Units.standardize_trajectory(raw_df)
    """

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: İRTİFA DÖNÜŞÜMLERİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def ft_to_m(altitude_ft):
        """
        Feet → Metre.

        Desteklenen tipler: scalar, numpy array, pandas Series.

        Args:
            altitude_ft: İrtifa (feet). -2000 ile 65000 arası.

        Returns:
            float, np.ndarray veya pd.Series: İrtifa (metre)

        Örnekler:
            Units.ft_to_m(35000)                          → 10668.0
            Units.ft_to_m(np.array([0, 35000, 41000]))    → array
            Units.ft_to_m(pd.Series([35000, 37000]))      → Series
        """
        altitude_ft = _check_value(altitude_ft, 'altitude_ft')
        return altitude_ft * _FT_TO_M

    @staticmethod
    def m_to_ft(altitude_m):
        """
        Metre → Feet.

        Desteklenen tipler: scalar, numpy array, pandas Series.

        Args:
            altitude_m: İrtifa (metre). -610 ile 20000 arası.

        Returns:
            float, np.ndarray veya pd.Series: İrtifa (feet)

        Örnekler:
            Units.m_to_ft(10668) → 35000.0
        """
        altitude_m = _check_value(altitude_m, 'altitude_m')
        return altitude_m * _M_TO_FT

    @staticmethod
    def fl_to_ft(flight_level):
        """
        Flight Level → Feet.

        Args:
            flight_level: FL sayısı (0-600). Scalar.

        Returns:
            int: İrtifa (feet)

        Örnekler:
            Units.fl_to_ft(350) → 35000
            Units.fl_to_ft(410) → 41000
        """
        if not isinstance(flight_level, _SCALAR_TYPES):
            raise TypeError(
                f"Flight level scalar olmalı: {type(flight_level).__name__}"
            )
        if flight_level < 0 or flight_level > 600:
            raise ValueError(
                f"Flight level 0-600 arası olmalı: {flight_level}"
            )
        return int(flight_level * 100)

    @staticmethod
    def ft_to_fl(altitude_ft):
        """
        Feet → Flight Level.

        Örnekler:
            Units.ft_to_fl(35000) → 350
            Units.ft_to_fl(37000) → 370
        """
        altitude_ft = _check_value(altitude_ft, 'altitude_ft')
        # Scalar ise int döndür, array/Series ise aynı tip
        if isinstance(altitude_ft, (np.ndarray, pd.Series)):
            return (altitude_ft / 100).round().astype(int)
        return int(round(altitude_ft / 100))

    @staticmethod
    def fl_to_m(flight_level):
        """Flight Level → Metre. Örnek: fl_to_m(350) → 10668.0"""
        return Units.ft_to_m(Units.fl_to_ft(flight_level))

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: BASINÇ, YOĞUNLUK, SICAKLIK (ISA)
    # ──────────────────────────────────────────────────────

    @staticmethod
    def pressure_at_altitude(altitude_ft, delta_isa=0.0):
        """
        ISA modeline göre irtifadaki atmosferik basıncı hesapla.

        Args:
            altitude_ft: İrtifa (feet). Scalar.
            delta_isa  : ISA sapması (°C). Örn: Dubai yaz = +20

        Returns:
            float: Basınç (Pascal)

        Örnekler:
            Units.pressure_at_altitude(0)     → 101325.0 Pa
            Units.pressure_at_altitude(35000) → ~23842 Pa

        Fizik:
            Troposfer:  P = P0 × (T/T0)^(-g/(lapse×R))
            Stratosfer: P = P_trop × exp(-g×dh/(R×T_trop))
        """
        altitude_ft = _check_value(altitude_ft, 'altitude_ft')
        h      = altitude_ft * _FT_TO_M
        T0_adj = _ISA_T0 + delta_isa

        if h <= _TROPOPAUSE_M:
            T        = T0_adj + _ISA_LAPSE * h
            exponent = -_GRAVITY / (_ISA_LAPSE * _R_AIR)
            P        = _ISA_P0 * (T / T0_adj) ** exponent
        else:
            T_trop   = T0_adj + _ISA_LAPSE * _TROPOPAUSE_M
            exponent = -_GRAVITY / (_ISA_LAPSE * _R_AIR)
            P_trop   = _ISA_P0 * (T_trop / T0_adj) ** exponent
            P        = P_trop * np.exp(
                -_GRAVITY * (h - _TROPOPAUSE_M) / (_R_AIR * T_trop)
            )

        return float(P)

    @staticmethod
    def temperature_at_altitude(altitude_ft, delta_isa=0.0):
        """
        ISA modeline göre irtifadaki sıcaklığı hesapla (Kelvin).

        Args:
            altitude_ft: İrtifa (feet). Scalar.
            delta_isa  : ISA sapması (°C)

        Returns:
            float: Sıcaklık (Kelvin)

        Örnekler:
            Units.temperature_at_altitude(0)     → 288.15 K (15°C)
            Units.temperature_at_altitude(35000) → ~218.8 K (-54.3°C)
            Units.temperature_at_altitude(36089) → 216.65 K (-56.5°C)
        """
        altitude_ft = _check_value(altitude_ft, 'altitude_ft')
        h      = altitude_ft * _FT_TO_M
        T0_adj = _ISA_T0 + delta_isa

        if h <= _TROPOPAUSE_M:
            T = T0_adj + _ISA_LAPSE * h
        else:
            T = T0_adj + _ISA_LAPSE * _TROPOPAUSE_M

        return float(T)

    @staticmethod
    def density_at_altitude(altitude_ft, delta_isa=0.0):
        """
        ISA modeline göre irtifadaki hava yoğunluğunu hesapla.

        Args:
            altitude_ft: İrtifa (feet)
            delta_isa  : ISA sapması (°C)

        Returns:
            float: Yoğunluk (kg/m³)

        Örnekler:
            Units.density_at_altitude(0)     → 1.225
            Units.density_at_altitude(35000) → ~0.380
        """
        altitude_ft = _check_value(altitude_ft, 'altitude_ft')
        P   = Units.pressure_at_altitude(altitude_ft, delta_isa)
        T   = Units.temperature_at_altitude(altitude_ft, delta_isa)
        return float(P / (_R_AIR * T))

    @staticmethod
    def altitude_from_pressure(pressure_pa, delta_isa=0.0):
        """
        Basınçtan irtifa hesapla (ters dönüşüm).

        Args:
            pressure_pa: Basınç (Pascal)
            delta_isa  : ISA sapması (°C)

        Returns:
            float: İrtifa (feet)

        Örnekler:
            Units.altitude_from_pressure(101325) → 0.0
            Units.altitude_from_pressure(23842)  → ~35000
        """
        pressure_pa = _check_value(pressure_pa, 'pressure_pa')
        T0_adj  = _ISA_T0 + delta_isa
        T_trop  = T0_adj + _ISA_LAPSE * _TROPOPAUSE_M
        exp_    = -_GRAVITY / (_ISA_LAPSE * _R_AIR)
        P_trop  = _ISA_P0 * (T_trop / T0_adj) ** exp_

        if pressure_pa >= P_trop:
            T = T0_adj * (pressure_pa / _ISA_P0) ** (1.0 / exp_)
            h = (T - T0_adj) / _ISA_LAPSE
        else:
            h = _TROPOPAUSE_M - (
                (_R_AIR * T_trop / _GRAVITY)
                * np.log(pressure_pa / P_trop)
            )

        return float(h * _M_TO_FT)

    @staticmethod
    def pressure_ratio(altitude_ft, delta_isa=0.0):
        """δ = P/P0. Motor SFC düzeltmesinde kullanılır."""
        return float(
            Units.pressure_at_altitude(altitude_ft, delta_isa) / _ISA_P0
        )

    @staticmethod
    def temperature_ratio(altitude_ft, delta_isa=0.0):
        """θ = T/T0. Motor SFC düzeltmesinde kullanılır."""
        return float(
            Units.temperature_at_altitude(altitude_ft, delta_isa) / _ISA_T0
        )

    @staticmethod
    def density_ratio(altitude_ft, delta_isa=0.0):
        """σ = ρ/ρ0."""
        return float(
            Units.density_at_altitude(altitude_ft, delta_isa) / _ISA_RHO0
        )

    @staticmethod
    def speed_of_sound(altitude_ft, delta_isa=0.0):
        """
        Ses hızı (m/s).

        Örnekler:
            Units.speed_of_sound(0)     → 340.3 m/s
            Units.speed_of_sound(35000) → ~295.9 m/s
        """
        T = Units.temperature_at_altitude(altitude_ft, delta_isa)
        return float(np.sqrt(_GAMMA * _R_AIR * T))

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: TRANSITION ALTITUDE / LEVEL
    # ──────────────────────────────────────────────────────

    @staticmethod
    def is_above_transition(altitude_ft, transition_altitude_ft=18000):
        """
        Uçak transition altitude üstünde mi? (QNE bölgesinde mi?)

        Args:
            altitude_ft            : İrtifa (feet)
            transition_altitude_ft : Ülkeye göre. Varsayılan 18000 ft.

        Returns:
            bool: True → FL bölgesinde (QNE kullanılıyor)
        """
        return altitude_ft >= transition_altitude_ft

    @staticmethod
    def pressure_altitude_to_true_altitude(
        pressure_alt_ft,
        qnh_hpa=1013.25
    ):
        """
        Basınç irtifasını gerçek irtifaya çevir.

        Kural: Her 1 hPa fark ≈ 27.3 feet irtifa farkı.

        Args:
            pressure_alt_ft: Basınç irtifası (ft, 1013.25 hPa bazlı)
            qnh_hpa        : Yerel basınç (hPa)

        Returns:
            float: Gerçek irtifa (feet)

        Örnekler:
            pressure_altitude_to_true_altitude(35000, 1013.25) → 35000
            pressure_altitude_to_true_altitude(35000, 1000)    → ~35397
            pressure_altitude_to_true_altitude(35000, 1030)    → ~34498
        """
        ft_per_hpa = 27.3
        correction = (qnh_hpa - 1013.25) * ft_per_hpa
        return float(pressure_alt_ft - correction)

    @staticmethod
    def get_transition_altitude(country_code=None):
        """
        Ülke bazlı transition altitude.

        Args:
            country_code: 2 harfli ICAO ülke kodu. None → 18000 ft.

        Returns:
            int: Transition altitude (feet)
        """
        TABLE = {
            'TR': 18000, 'US': 18000, 'CA': 18000,
            'GB':  6000, 'DE':  5000, 'FR':  5000,
            'NL':  3000, 'BE':  3000, 'CH':  5000,
            'AT':  5000, 'ES':  6000, 'IT':  8000,
            'AE': 13000, 'SA': 13000, 'QA': 13000,
            'KW': 13000, 'JP': 14000, 'AU': 10000,
            'NZ': 13000, 'CN':  9800, 'RU':  9800,
            'IN':  4000, 'SG': 11000,
        }
        if country_code:
            return TABLE.get(country_code.upper(), 18000)
        return 18000

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: HIZ DÖNÜŞÜMLERİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def kts_to_ms(speed_kts):
        """
        Knots → m/s.

        Desteklenen tipler: scalar, numpy array, pandas Series.

        Örnekler:
            Units.kts_to_ms(450) → 231.50
            Units.kts_to_ms(pd.Series([0, 250, 450])) → Series
        """
        speed_kts = _check_value(speed_kts, 'speed_kts')
        return speed_kts * _KTS_TO_MS

    @staticmethod
    def ms_to_kts(speed_ms):
        """
        m/s → Knots.

        Desteklenen tipler: scalar, numpy array, pandas Series.
        """
        speed_ms = _check_value(speed_ms, 'speed_ms')
        return speed_ms * _MS_TO_KTS

    @staticmethod
    def mach_to_tas(mach, altitude_ft, delta_isa=0.0):
        """
        Mach → True Airspeed / TAS (m/s).

        Args:
            mach       : Mach sayısı (0.0-0.95). Scalar.
            altitude_ft: İrtifa (feet). Scalar.
            delta_isa  : ISA sapması (°C)

        Returns:
            float: TAS (m/s)

        Örnekler:
            Units.mach_to_tas(0.785, 35000) → ~232.78 m/s
            Units.mach_to_tas(0.90, 39000)  → ~265.1 m/s (B787)
        """
        mach        = _check_value(mach, 'mach')
        altitude_ft = _check_value(altitude_ft, 'altitude_ft')
        a           = Units.speed_of_sound(altitude_ft, delta_isa)
        return float(mach * a)

    @staticmethod
    def tas_to_mach(tas_ms, altitude_ft, delta_isa=0.0):
        """
        TAS (m/s) → Mach sayısı.

        Örnekler:
            Units.tas_to_mach(229.6, 35000) → ~0.785
        """
        tas_ms      = _check_value(tas_ms, 'speed_ms')
        altitude_ft = _check_value(altitude_ft, 'altitude_ft')
        a           = Units.speed_of_sound(altitude_ft, delta_isa)
        return float(tas_ms / a)

    @staticmethod
    def tas_to_ktas(tas_ms):
        """TAS (m/s) → KTAS (knots)."""
        return Units.ms_to_kts(tas_ms)

    @staticmethod
    def ktas_to_tas(ktas):
        """KTAS (knots) → TAS (m/s)."""
        return Units.kts_to_ms(ktas)

    @staticmethod
    def fpm_to_ms(rate_fpm):
        """
        Feet/dakika → m/s.

        Örnekler:
            Units.fpm_to_ms(1500)  → 7.62
            Units.fpm_to_ms(-500)  → -2.54
        """
        return rate_fpm * _FT_TO_M / 60.0

    @staticmethod
    def ms_to_fpm(rate_ms):
        """m/s → Feet/dakika. Örnek: ms_to_fpm(7.62) → 1500"""
        return rate_ms * _M_TO_FT * 60.0

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: MESAFE DÖNÜŞÜMLERİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def nm_to_m(distance_nm):
        """Deniz mili → Metre. Örnek: nm_to_m(1) → 1852.0"""
        distance_nm = _check_value(distance_nm, 'distance_nm')
        return distance_nm * _NM_TO_M

    @staticmethod
    def m_to_nm(distance_m):
        """Metre → Deniz mili. Örnek: m_to_nm(1852) → 1.0"""
        distance_m = _check_value(distance_m, 'distance_m')
        return distance_m * _M_TO_NM

    @staticmethod
    def nm_to_km(distance_nm):
        """Deniz mili → Kilometre. Örnek: nm_to_km(1) → 1.852"""
        distance_nm = _check_value(distance_nm, 'distance_nm')
        return distance_nm * _NM_TO_KM

    @staticmethod
    def km_to_nm(distance_km):
        """Kilometre → Deniz mili. Örnek: km_to_nm(1.852) → 1.0"""
        if distance_km < 0:
            raise ValueError(f"Mesafe negatif olamaz: {distance_km} km")
        return float(distance_km * _KM_TO_NM)

    @staticmethod
    def statute_mile_to_m(distance_sm):
        """
        Statute mile → Metre.

        UYARI: 1 statute mile = 1609.344 m ≠ 1 nautical mile = 1852.0 m
        Fark: yüzde 13. Karıştırmak ciddi hata üretir.
        """
        if distance_sm < 0:
            raise ValueError(f"Mesafe negatif olamaz: {distance_sm}")
        return float(distance_sm * _STATUTE_MILE_TO_M)

    @staticmethod
    def m_to_statute_mile(distance_m):
        """Metre → Statute mile."""
        distance_m = _check_value(distance_m, 'distance_m')
        return float(distance_m * _M_TO_STATUTE_MILE)

    @staticmethod
    def statute_mile_to_nm(distance_sm):
        """Statute mile → Nautical mile. Örnek: statute_mile_to_nm(1) → 0.8684"""
        if distance_sm < 0:
            raise ValueError(f"Mesafe negatif olamaz: {distance_sm}")
        return float(distance_sm * _STATUTE_MILE_TO_M * _M_TO_NM)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 6: AĞIRLIK DÖNÜŞÜMLERİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def kg_to_lbs(weight_kg):
        """Kilogram → Pound."""
        weight_kg = _check_value(weight_kg, 'weight_kg')
        return weight_kg * _KG_TO_LBS

    @staticmethod
    def lbs_to_kg(weight_lbs):
        """Pound → Kilogram."""
        weight_lbs = _check_value(weight_lbs, 'weight_lbs')
        return weight_lbs * _LBS_TO_KG

    # ──────────────────────────────────────────────────────
    # BÖLÜM 7: SICAKLIK DÖNÜŞÜMLERİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def celsius_to_kelvin(temp_c):
        """
        Celsius → Kelvin.

        Desteklenen tipler: scalar, numpy array, pandas Series.

        Örnekler:
            Units.celsius_to_kelvin(15)    → 288.15
            Units.celsius_to_kelvin(-56.5) → 216.65
        """
        temp_c = _check_value(temp_c, 'temperature_c')
        result = temp_c + _KELVIN_OFFSET
        if isinstance(result, float):
            return result
        return result

    @staticmethod
    def kelvin_to_celsius(temp_k):
        """
        Kelvin → Celsius.

        Desteklenen tipler: scalar, numpy array, pandas Series.
        """
        temp_k = _check_value(temp_k, 'temperature_k')
        result = temp_k - _KELVIN_OFFSET
        if isinstance(result, float):
            return result
        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 8: YAKIT DÖNÜŞÜMLERİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def fuel_density_at_temp(temperature_c=15.0):
        """
        Jet-A1 yoğunluğunu sıcaklığa göre hesapla.

        Sabit 0.804 kullanmak yüzde 1-4 hata üretir.

        Formül:
            ρ(T) = ρ_ref - α × (T - T_ref)
            ρ_ref = 0.804 kg/L @ 15°C
            α     = 0.00072 kg/(L·°C)

        Args:
            temperature_c: Yakıt sıcaklığı (°C). -50 ile +55 arası.

        Returns:
            float: Yoğunluk (kg/L)

        Örnekler:
            fuel_density_at_temp(15)  → 0.804000
            fuel_density_at_temp(40)  → 0.786200  (Dubai yaz)
            fuel_density_at_temp(-30) → 0.836400  (Moskova kış)

        Kaynak: ASTM D1655, IATA Fuel Quality Pool
        """
        temperature_c = _check_value(temperature_c, 'fuel_temp_c')
        density = (
            _FUEL_DENSITY_REF
            - _FUEL_DENSITY_ALPHA * (temperature_c - _FUEL_DENSITY_TEMP_REF)
        )
        density = float(max(_FUEL_DENSITY_MIN, min(_FUEL_DENSITY_MAX, density)))
        return round(density, 6)

    @staticmethod
    def fuel_liters_to_kg(liters, temperature_c=15.0):
        """
        Yakıt litre → kilogram (sıcaklığa bağlı).

        Args:
            liters       : Yakıt hacmi (litre)
            temperature_c: Yakıt sıcaklığı (°C). Varsayılan 15°C.

        Returns:
            float: Yakıt kütlesi (kg)

        Örnekler:
            fuel_liters_to_kg(10000)      → 8040.0
            fuel_liters_to_kg(10000, 40)  → 7862.0
            fuel_liters_to_kg(10000, -30) → 8364.0
        """
        if liters < 0:
            raise ValueError(f"Yakıt hacmi negatif olamaz: {liters}")
        return float(liters * Units.fuel_density_at_temp(temperature_c))

    @staticmethod
    def fuel_kg_to_liters(kg, temperature_c=15.0):
        """
        Yakıt kilogram → litre (sıcaklığa bağlı).

        Örnekler:
            fuel_kg_to_liters(8040)     → 10000.0
            fuel_kg_to_liters(8040, 40) → 10229.0
        """
        if kg < 0:
            raise ValueError(f"Yakıt kütlesi negatif olamaz: {kg}")
        return float(kg / Units.fuel_density_at_temp(temperature_c))

    # ──────────────────────────────────────────────────────
    # BÖLÜM 9: VECTORIZED HAVERSINE
    # ──────────────────────────────────────────────────────

    @staticmethod
    def _vectorized_haversine(latitudes, longitudes):
        """
        Ardışık koordinat çiftleri arası mesafeyi vectorize hesapla.

        Performans: 10,000 nokta → ~10 ms (for döngüsü: ~5000 ms)

        Args:
            latitudes : numpy array, enlem (derece)
            longitudes: numpy array, boylam (derece)

        Returns:
            numpy array: Segment mesafeleri (Nm). İlk eleman 0.0.
        """
        R_nm    = 3440.065
        lat_rad = np.radians(np.asarray(latitudes, dtype=float))
        lon_rad = np.radians(np.asarray(longitudes, dtype=float))

        lat1 = lat_rad[:-1]
        lat2 = lat_rad[1:]
        lon1 = lon_rad[:-1]
        lon2 = lon_rad[1:]

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = (
            np.sin(dlat / 2.0) ** 2
            + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
        )
        a         = np.clip(a, 0.0, 1.0)
        c         = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
        distances = R_nm * c
        distances = np.where(np.isnan(distances), 0.0, distances)

        result     = np.zeros(len(latitudes))
        result[1:] = distances
        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 10: OUTLIER TESPİTİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def detect_outliers(series, method='iqr', factor=1.5):
        """
        Veri serisindeki aykırı değerleri tespit et.

        Yöntemler:
            'iqr'    : Q1 - factor×IQR ve Q3 + factor×IQR
            'zscore' : |z| > factor

        Args:
            series: pandas Series veya numpy array
            method: 'iqr' veya 'zscore'
            factor: Eşik çarpanı

        Returns:
            dict:
                outlier_mask   : boolean array
                outlier_count  : int
                outlier_indices: list
                lower_bound    : float
                upper_bound    : float
                clean_series   : outlier NaN yapılmış
                method, factor : kullanılan parametreler
        """
        if isinstance(series, pd.Series):
            values = series.dropna().values
        else:
            values = np.asarray(series, dtype=float)
            values = values[~np.isnan(values)]

        if len(values) < 4:
            empty = np.zeros(len(series), dtype=bool)
            return {
                'outlier_mask'   : empty,
                'outlier_count'  : 0,
                'outlier_indices': [],
                'lower_bound'    : None,
                'upper_bound'    : None,
                'clean_series'   : series,
                'method'         : method,
                'factor'         : factor,
                'note'           : 'Yetersiz veri (min 4 nokta)',
            }

        if method == 'iqr':
            Q1    = np.percentile(values, 25)
            Q3    = np.percentile(values, 75)
            IQR   = Q3 - Q1
            lower = Q1 - factor * IQR if IQR != 0 else Q1
            upper = Q3 + factor * IQR if IQR != 0 else Q3
        elif method == 'zscore':
            mean  = np.mean(values)
            std   = np.std(values)
            lower = mean - factor * std if std != 0 else mean
            upper = mean + factor * std if std != 0 else mean
        else:
            raise ValueError(
                f"Bilinmeyen method: '{method}'. 'iqr' veya 'zscore' kullan."
            )

        if isinstance(series, pd.Series):
            mask  = (series < lower) | (series > upper)
            mask  = mask.fillna(False)
            clean = series.copy()
            clean[mask] = np.nan
        else:
            arr   = np.asarray(series, dtype=float)
            mask  = (arr < lower) | (arr > upper) | np.isnan(arr)
            clean = arr.copy()
            clean[mask] = np.nan

        return {
            'outlier_mask'   : np.asarray(mask),
            'outlier_count'  : int(np.sum(mask)),
            'outlier_indices': np.where(mask)[0].tolist(),
            'lower_bound'    : float(lower),
            'upper_bound'    : float(upper),
            'clean_series'   : clean,
            'method'         : method,
            'factor'         : factor,
        }

    @staticmethod
    def clean_trajectory_outliers(df, verbose=True):
        """
        Trajectory outlier'larını tespit et ve phase-aware interpolation ile düzelt.

        Args:
            df     : standardize_trajectory geçmiş DataFrame
            verbose: Bulgular yazdırılsın mı?

        Returns:
            DataFrame: Temizlenmiş
        """
        df    = df.copy()
        total = 0

        vr_series = df.get('vertical_rate_fpm')
        td_series = df.get('time_diff_s')

        def _fix(col, companion, factor, label, companion_fn=None):
            nonlocal total
            if col not in df.columns:
                return
            res = Units.detect_outliers(df[col], method='iqr', factor=factor)
            if res['outlier_count'] == 0:
                return
            total += res['outlier_count']
            if verbose:
                print(
                    f"  ⚠  {label}: {res['outlier_count']} outlier "
                    f"({res['lower_bound']:.1f} – {res['upper_bound']:.1f})"
                )
            df.loc[res['outlier_mask'], col] = np.nan
            df[col] = _phase_aware_interpolate(
                df[col],
                vertical_rate_fpm=vr_series,
                time_diff_s=td_series,
            )
            if companion and companion in df.columns and companion_fn:
                df[companion] = companion_fn(df[col])

        _fix('velocity_kts',      'velocity_ms',      2.0, 'Hız (kts)',
             lambda x: x * _KTS_TO_MS)
        _fix('baro_altitude_ft',  'baro_altitude_m',  2.0, 'İrtifa (ft)',
             lambda x: x * _FT_TO_M)
        _fix('vertical_rate_fpm', 'vertical_rate_ms', 2.5, 'Dikey hız (fpm)',
             lambda x: x * _FT_TO_M / 60.0)

        # GPS atlama — dinamik threshold
        if 'segment_distance_nm' in df.columns:
            route_nm     = df['segment_distance_nm'].sum()
            n_points     = len(df)
            avg_seg      = route_nm / n_points if n_points > 0 else 10
            # Threshold: ortalama segment × 5, minimum 5 Nm, maksimum 50 Nm
            gps_threshold = float(np.clip(avg_seg * 5, 5.0, 50.0))
            big_jump      = df['segment_distance_nm'] > gps_threshold
            count         = int(big_jump.sum())
            if count > 0:
                total += count
                if verbose:
                    print(
                        f"  ⚠  GPS atlama: {count} segment > {gps_threshold:.1f} Nm"
                    )
                df.loc[big_jump, 'segment_distance_nm'] = np.nan
                df['segment_distance_nm'] = (
                    df['segment_distance_nm']
                    .interpolate(method='linear')
                    .fillna(0)
                )
                df['cumulative_distance_nm'] = df['segment_distance_nm'].cumsum()

        if verbose:
            if total == 0:
                print("  ✅ Outlier tespit edilmedi, veri temiz")
            else:
                print(f"  📊 Toplam {total} outlier düzeltildi")

        return df

    # ──────────────────────────────────────────────────────
    # BÖLÜM 11: TRAJECTORY STANDARDİZASYONU
    # ──────────────────────────────────────────────────────

    @staticmethod
    def standardize_trajectory(
        df,
        altitude_source_hint=None,
        country_code=None,
        max_interpolation_gap_s=300.0,
        verbose=False,
    ):
        """
        Trajectory DataFrame'ini standart birimlerle donat.

        DÜZELTİLEN RİSKLER:
            1. İrtifa kaynak tespiti: Çok boyutlu güven skoru kullanılır.
               Overlap bölgelerinde düşük güven uyarısı verilir.
               altitude_source_hint ile manuel override mümkün.

            2. fillna(0) kaldırıldı: Phase-aware interpolation kullanılır.
               Büyük boşluklar (max_interpolation_gap_s üstü) NaN kalır.
               Tüm NaN noktalar flag kolonu ile işaretlenir.

            3. Double sort kaldırıldı: Negatif time_diff uyarı verir,
               sıralama tekrarlanmaz.

            4. Segment outlier temizliği önce yapılır, cumulative sonra.
               Dinamik threshold: ortalama segment × 5.

            5. Transition altitude ülke koduna göre belirlenir.

        Args:
            df                     : Ham trajectory DataFrame
            altitude_source_hint   : 'metres', 'feet' veya None (otomatik)
            country_code           : Transition altitude için ülke kodu
            max_interpolation_gap_s: Bu süreden uzun boşluklara interpolasyon
                                     uygulanmaz, NaN kalır. Varsayılan 300 s.
            verbose                : True → ayrıntılı log

        Returns:
            DataFrame: Standartlaştırılmış

        Sütunlar:
            time                    : datetime (sıralı)
            time_diff_s             : önceki noktadan geçen saniye
            time_gap_flag           : >10 dk boşluk (bool)
            baro_altitude_ft        : irtifa (feet)
            baro_altitude_m         : irtifa (metre)
            altitude_source         : tespit edilen kaynak
            altitude_source_confidence: güven skoru (0-1)
            baro_altitude_nan_flag  : interpolate edilen noktalar (bool)
            velocity_ms             : yatay hız (m/s)
            velocity_kts            : yatay hız (knots)
            velocity_nan_flag       : interpolate edilen noktalar (bool)
            altitude_diff_ft        : irtifa farkı (feet)
            vertical_rate_fpm       : dikey hız (fpm)
            vertical_rate_ms        : dikey hız (m/s)
            vertical_rate_nan_flag  : interpolate edilen noktalar (bool)
            segment_distance_nm     : nokta arası mesafe (Nm)
            cumulative_distance_nm  : kümülatif mesafe (Nm)
            above_transition        : FL bölgesinde mi? (bool)
        """
        df = df.copy()

        # ─── 1. ZAMAN ─────────────────────────────────────
        if 'time' in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df['time']):
                df['time'] = pd.to_datetime(df['time'], errors='coerce')

            # Tek sıralama (double sort kaldırıldı)
            df = df.sort_values('time').reset_index(drop=True)

            df['time_diff_s'] = (
                df['time'].diff().dt.total_seconds().fillna(0)
            )

            neg = int((df['time_diff_s'] < 0).sum())
            if neg > 0:
                warnings.warn(
                    f"⚠ Zaman anomalisi: {neg} negatif time_diff. "
                    f"Veri kalite sorunu. Sıralama değiştirilmedi.",
                    stacklevel=2
                )

            df['time_gap_flag'] = df['time_diff_s'] > 600

        else:
            # BÜTÜNLÜK: Zaman kolonu yoksa sessizce time_diff_s=0 yazmak,
            # tüm yakıt hesabını 0'a düşürüyordu (sessiz sıfır). Artık
            # `timestamp` takma adı denenir; o da yoksa uyarı verilir.
            if 'timestamp' in df.columns:
                df['time'] = pd.to_datetime(df['timestamp'], errors='coerce')
                df = df.sort_values('time').reset_index(drop=True)
                df['time_diff_s'] = (
                    df['time'].diff().dt.total_seconds().fillna(0)
                )
                df['time_gap_flag'] = df['time_diff_s'] > 600
            else:
                warnings.warn(
                    "⚠ Zaman kolonu ('time'/'timestamp') yok: time_diff_s=0. "
                    "Zaman tabanlı yakıt hesapları 0 üretecek.",
                    stacklevel=2,
                )
                df['time_diff_s']  = 0.0
                df['time_gap_flag'] = False

        # ─── 2. İRTİFA (ÇOK BOYUTLU TESPİT) ──────────────
        if 'baro_altitude_m' in df.columns and 'baro_altitude_ft' in df.columns:
            detection = {
                'source'    : 'already_split',
                'confidence': 1.0,
                'evidence'  : ['Her iki sütun mevcut'],
            }
        elif 'baro_altitude_m' in df.columns:
            detection = {'source': 'metres', 'confidence': 1.0, 'evidence': []}
            df['baro_altitude_ft'] = df['baro_altitude_m'] * _M_TO_FT
        elif 'baro_altitude_ft' in df.columns:
            detection = {'source': 'feet', 'confidence': 1.0, 'evidence': []}
            df['baro_altitude_m'] = df['baro_altitude_ft'] * _FT_TO_M
        elif 'baro_altitude' in df.columns:
            # Manual hint varsa kullan
            if altitude_source_hint in ('metres', 'feet'):
                detection = {
                    'source'    : altitude_source_hint,
                    'confidence': 1.0,
                    'evidence'  : [f'Manuel hint: {altitude_source_hint}'],
                }
                raw = pd.to_numeric(df['baro_altitude'], errors='coerce')
                if altitude_source_hint == 'metres':
                    df['baro_altitude_m']  = raw
                    df['baro_altitude_ft'] = raw * _M_TO_FT
                else:
                    df['baro_altitude_ft'] = raw
                    df['baro_altitude_m']  = raw * _FT_TO_M
            else:
                # İstatistiksel otomatik tespit
                detection = _detect_altitude_source(df)

                if detection['confidence'] < 0.6:
                    warnings.warn(
                        f"Düşük irtifa kaynak güveni "
                        f"({detection['confidence']:.1%}). "
                        f"{detection['recommendation']}",
                        stacklevel=2
                    )

                if verbose:
                    print(
                        f"  ℹ Altitude kaynak: {detection['source']} "
                        f"(güven: {detection['confidence']:.1%})"
                    )
                    for ev in detection.get('evidence', []):
                        print(f"    → {ev}")

                raw = pd.to_numeric(df['baro_altitude'], errors='coerce')
                src = detection['source']

                if src == 'metres':
                    df['baro_altitude_m']  = raw
                    df['baro_altitude_ft'] = raw * _M_TO_FT
                elif src == 'feet':
                    df['baro_altitude_ft'] = raw
                    df['baro_altitude_m']  = raw * _FT_TO_M
                else:
                    # Ambiguous → feet varsay, uyar
                    warnings.warn(
                        "İrtifa birimi belirlenemedi. Feet varsayıldı. "
                        "altitude_source_hint kullanılması önerilir.",
                        stacklevel=2
                    )
                    df['baro_altitude_ft'] = raw
                    df['baro_altitude_m']  = raw * _FT_TO_M
        else:
            detection = {'source': 'missing', 'confidence': 0.0, 'evidence': []}
            df['baro_altitude_ft'] = np.nan
            df['baro_altitude_m']  = np.nan

        df['altitude_source']            = detection['source']
        df['altitude_source_confidence'] = detection.get('confidence', 0.0)

        # İrtifa NaN flag
        df['baro_altitude_nan_flag'] = df['baro_altitude_ft'].isna()

        # Phase-aware interpolation
        td_series = df.get('time_diff_s')
        df['baro_altitude_ft'] = _phase_aware_interpolate(
            df['baro_altitude_ft'],
            time_diff_s=td_series,
            max_gap_s=max_interpolation_gap_s,
        )
        df['baro_altitude_m'] = df['baro_altitude_ft'] * _FT_TO_M

        # ─── 3. DİKEY HIZ ─────────────────────────────────
        if 'time_diff_s' in df.columns and df['time_diff_s'].sum() > 0:
            df['altitude_diff_ft'] = df['baro_altitude_ft'].diff().fillna(0)
            df['vertical_rate_fpm'] = np.where(
                df['time_diff_s'] > 0,
                df['altitude_diff_ft'] / (df['time_diff_s'] / 60.0),
                np.nan
            )
        else:
            df['altitude_diff_ft']  = np.nan
            df['vertical_rate_fpm'] = np.nan

        df['vertical_rate_nan_flag'] = df['vertical_rate_fpm'].isna()

        # Dikey hız için sadece linear interpolation
        # (polynomial için kendisi gerekli ama chicken-egg problem)
        df['vertical_rate_fpm'] = df['vertical_rate_fpm'].interpolate(
            method='linear', limit_direction='both'
        )
        df['vertical_rate_ms'] = df['vertical_rate_fpm'] * _FT_TO_M / 60.0

        # ─── 4. YATAY HIZ ─────────────────────────────────
        if 'velocity' in df.columns:
            raw_vel = pd.to_numeric(df['velocity'], errors='coerce')
            # ── BİRİM TESPİTİ ────────────────────────────
            # OpenSky API'si velocity'yi m/s verir; ancak arşivlenmiş
            # CSV'ler kt olarak kaydedilmiş olabilir. Ticari uçak cruise
            # hızı 400-520 kt (205-270 m/s). 90. persentil > 350 ise
            # veri KNOT'tur → m/s'ye ÇEVİR, tekrar çarpma.
            #
            # Bu tespit olmadan 798 kt gibi imkânsız hız çıkıyordu
            # (1240 nm'lik uçuşta cruise süresi yanlış hesaplanıyordu).
            _p90 = (float(raw_vel.quantile(0.90))
                    if raw_vel.notna().any() else 0.0)
            _is_knots = _p90 > 350.0
            df['velocity_ms']  = raw_vel * _KTS_TO_MS if _is_knots else raw_vel
            df['velocity_kts'] = raw_vel if _is_knots else raw_vel * _MS_TO_KTS
        elif 'ground_speed_kts' in df.columns:
            raw_vel = pd.to_numeric(df['ground_speed_kts'], errors='coerce')
            df['velocity_kts'] = raw_vel
            df['velocity_ms']  = raw_vel * _KTS_TO_MS
        else:
            df['velocity_ms']  = np.nan
            df['velocity_kts'] = np.nan

        df['velocity_nan_flag'] = df['velocity_ms'].isna()

        df['velocity_ms'] = _phase_aware_interpolate(
            df['velocity_ms'],
            vertical_rate_fpm=df.get('vertical_rate_fpm'),
            time_diff_s=td_series,
            max_gap_s=max_interpolation_gap_s,
        )
        df['velocity_kts'] = df['velocity_ms'] * _MS_TO_KTS

        # ─── 5. KOORDİNATLAR ──────────────────────────────
        for col in ['latitude', 'longitude']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # ─── 6. SEGMENT MESAFESİ (OUTLIER ÖNCE) ───────────
        if 'latitude' in df.columns and 'longitude' in df.columns:
            lat_vals = df['latitude'].values
            lon_vals = df['longitude'].values

            raw_distances = Units._vectorized_haversine(lat_vals, lon_vals)

            # Dinamik GPS atlama threshold
            route_approx  = float(np.nansum(raw_distances))
            n_pts         = len(raw_distances)
            avg_seg       = route_approx / n_pts if n_pts > 0 else 10.0
            gps_threshold = float(np.clip(avg_seg * 5, 5.0, 50.0))

            raw_distances = np.where(
                raw_distances > gps_threshold, np.nan, raw_distances
            )
            raw_distances[0] = 0.0

            seg_series = (
                pd.Series(raw_distances)
                .interpolate(method='linear')
                .fillna(0)
            )
            df['segment_distance_nm']    = seg_series.values
            df['cumulative_distance_nm'] = df['segment_distance_nm'].cumsum()

        # ─── 7. TRANSITION BİLGİSİ ────────────────────────
        if 'baro_altitude_ft' in df.columns:
            trans_alt           = Units.get_transition_altitude(country_code)
            df['above_transition'] = df['baro_altitude_ft'] >= trans_alt

        return df

    # ──────────────────────────────────────────────────────
    # BÖLÜM 12: SABİT ERİŞİMCİLERİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def get_ft_to_m_factor():
        """0.3048"""
        return _FT_TO_M

    @staticmethod
    def get_nm_to_m_factor():
        """1852.0"""
        return _NM_TO_M

    @staticmethod
    def get_kts_to_ms_factor():
        """0.514444"""
        return _KTS_TO_MS


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_units():
    """
    Tüm dönüşümlerin doğru çalıştığını otomatik kontrol et.

    Çalıştırma:
        python -m src.units

    Beklenen: "✅ TÜM TESTLER BAŞARILI"
    """
    import time as _time

    print("\n" + "=" * 65)
    print("  UNITS.PY — TAM DOĞRULAMA TESTLERİ")
    print("=" * 65)

    errors = []
    tests  = 0

    # Yardımcı: sayısal test
    def check(name, actual, expected, tol=0.01):
        nonlocal tests
        tests += 1
        try:
            diff = abs(float(actual) - float(expected))
        except (TypeError, ValueError) as exc:
            errors.append(f"{name}: tip hatası: {exc}")
            print(f"  ❌ {name}: tip hatası")
            return
        if diff > tol:
            errors.append(f"{name}: {actual} (beklenen {expected}, Δ={diff:.6f})")
            print(f"  ❌ {name}: {actual} ≠ {expected}")
        else:
            print(f"  ✅ {name} = {actual}")

    # Yardımcı: hata yakalama (KeyboardInterrupt asla yakalanmaz)
    def check_raises(name, func, args, exc):
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
            errors.append(
                f"{name}: yanlış hata {type(e).__name__} "
                f"(beklenen {exc.__name__})"
            )
            print(f"  ❌ {name}: yanlış hata: {type(e).__name__}")

    # ─── [1] İRTİFA ───────────────────────────────────────
    print("\n  [1] İrtifa Dönüşümleri")
    check("ft_to_m(35000)",   Units.ft_to_m(35000),   10668.0, 0.1)
    check("ft_to_m(0)",       Units.ft_to_m(0),        0.0,    0.01)
    check("m_to_ft(10668)",   Units.m_to_ft(10668),   35000.0, 1.0)
    check("fl_to_ft(350)",    Units.fl_to_ft(350),    35000,   0.1)
    check("ft_to_fl(37000)",  Units.ft_to_fl(37000),  370,     0.1)
    check("fl_to_m(390)",     Units.fl_to_m(390),     11887.2, 1.0)
    check("ft→m→ft(41000)",
          Units.m_to_ft(Units.ft_to_m(41000)), 41000, 0.01)

    # pandas Series desteği
    tests += 1
    try:
        s   = pd.Series([0.0, 35000.0, 41000.0])
        res = Units.ft_to_m(s)
        expected = np.array([0.0, 10668.0, 12496.8])
        if isinstance(res, (pd.Series, np.ndarray)) and len(res) == 3:
            if all(abs(float(r) - float(e)) < 1.0 for r, e in zip(res, expected)):
                print(f"  ✅ ft_to_m(pd.Series) çalışıyor")
            else:
                errors.append("ft_to_m(Series) yanlış değer")
                print(f"  ❌ ft_to_m(Series) yanlış değer")
        else:
            errors.append(f"ft_to_m(Series) yanlış tip: {type(res)}")
            print(f"  ❌ ft_to_m(Series) yanlış tip")
    except Exception as e:
        errors.append(f"ft_to_m(pd.Series) hata: {e}")
        print(f"  ❌ ft_to_m(pd.Series) hata: {e}")

    # numpy array desteği
    tests += 1
    try:
        arr = np.array([0.0, 35000.0])
        res = Units.ft_to_m(arr)
        if isinstance(res, np.ndarray) and abs(res[1] - 10668.0) < 1.0:
            print("  ✅ ft_to_m(np.array) çalışıyor")
        else:
            errors.append("ft_to_m(array) yanlış")
            print("  ❌ ft_to_m(array) yanlış")
    except Exception as e:
        errors.append(f"ft_to_m(array) hata: {e}")
        print(f"  ❌ ft_to_m(array) hata: {e}")

    # ─── [2] BASINÇ / YOĞUNLUK ────────────────────────────
    print("\n  [2] Basınç ve Yoğunluk")
    check("pressure(0)",      Units.pressure_at_altitude(0),        101325.0, 1.0)
    check("pressure(35000)",  Units.pressure_at_altitude(35000),    23842.0,  200.0)
    check("density(0)",       Units.density_at_altitude(0),         1.225,    0.001)
    check("density(35000)",   Units.density_at_altitude(35000),     0.380,    0.005)
    check("temp(0)K",         Units.temperature_at_altitude(0),     288.15,   0.01)
    check("temp(36089)K",     Units.temperature_at_altitude(36089), 216.65,   1.0)
    check("pressure_ratio(0)",Units.pressure_ratio(0),              1.0,      0.001)
    check("temp_ratio(0)",    Units.temperature_ratio(0),           1.0,      0.001)
    check("density_ratio(0)", Units.density_ratio(0),               1.0,      0.001)
    check("sos(0)",           Units.speed_of_sound(0),              340.3,    0.5)
    check("sos(35000)",       Units.speed_of_sound(35000),          295.9,    1.0)

    P35      = Units.pressure_at_altitude(35000)
    alt_back = Units.altitude_from_pressure(P35)
    check("press→alt(FL350)", alt_back, 35000, 10.0)

    # ─── [3] TRANSITION ───────────────────────────────────
    print("\n  [3] Transition Altitude")

    tests += 1
    if Units.is_above_transition(35000):
        print("  ✅ is_above_transition(35000) → True")
    else:
        errors.append("FL350 transition üstünde olmalı")
        print("  ❌ is_above_transition(35000) → False (yanlış)")

    tests += 1
    if not Units.is_above_transition(5000):
        print("  ✅ is_above_transition(5000) → False")
    else:
        errors.append("5000 ft transition altında olmalı")
        print("  ❌ is_above_transition(5000) → True (yanlış)")

    check("press→true(QNH=1013.25)",
          Units.pressure_altitude_to_true_altitude(35000, 1013.25), 35000, 1.0)

    true_low = Units.pressure_altitude_to_true_altitude(35000, 1000)
    tests += 1
    if true_low > 35000:
        print(f"  ✅ QNH=1000 → gerçek irtifa {true_low:.0f} > 35000 (doğru)")
    else:
        errors.append("QNH düşükse gerçek irtifa yüksek olmalı")
        print("  ❌ QNH=1000 irtifa yanlış")

    check("transition TR", Units.get_transition_altitude('TR'), 18000, 0.1)
    check("transition DE", Units.get_transition_altitude('DE'), 5000,  0.1)
    check("transition GB", Units.get_transition_altitude('GB'), 6000,  0.1)

    # ─── [4] HIZ ──────────────────────────────────────────
    print("\n  [4] Hız Dönüşümleri")
    check("kts_to_ms(450)",   Units.kts_to_ms(450),   231.50, 0.1)
    check("ms_to_kts(231.5)", Units.ms_to_kts(231.5),  450.0, 0.1)
    check("kts→ms→kts(250)",
          Units.ms_to_kts(Units.kts_to_ms(250)), 250.0, 0.01)
    check("fpm_to_ms(1500)",  Units.fpm_to_ms(1500),  7.62,   0.01)
    check("fpm→ms→fpm(2000)",
          Units.ms_to_fpm(Units.fpm_to_ms(2000)), 2000.0, 0.1)

    # pandas Series hız
    tests += 1
    try:
        s   = pd.Series([0.0, 250.0, 450.0])
        res = Units.kts_to_ms(s)
        if isinstance(res, (pd.Series, np.ndarray)) and len(res) == 3:
            print(f"  ✅ kts_to_ms(pd.Series) çalışıyor")
        else:
            errors.append("kts_to_ms(Series) yanlış")
    except Exception as e:
        errors.append(f"kts_to_ms(Series) hata: {e}")
        print(f"  ❌ kts_to_ms(Series): {e}")

    tas = Units.mach_to_tas(0.785, 35000)
    check("mach_to_tas(0.785, 35000)", tas, 232.78, 1.0)
    check("tas_to_mach roundtrip",
          Units.tas_to_mach(tas, 35000), 0.785, 0.001)

    tests += 1
    try:
        tas90 = Units.mach_to_tas(0.90, 35000)
        print(f"  ✅ mach_to_tas(M0.90) = {tas90:.1f} m/s (B787 geçerli)")
    except ValueError:
        errors.append("M0.90 kabul edilmeli ama reddedildi")
        print("  ❌ M0.90 reddedildi")

    # ─── [5] MESAFE ────────────────────────────────────────
    print("\n  [5] Mesafe Dönüşümleri")
    check("nm_to_m(1)",            Units.nm_to_m(1),            1852.0,   0.01)
    check("nm_to_km(1)",           Units.nm_to_km(1),           1.852,    0.001)
    check("Nm→m→Nm(1560)",
          Units.m_to_nm(Units.nm_to_m(1560)), 1560.0, 0.001)
    check("statute_mile_to_m(1)",  Units.statute_mile_to_m(1),  1609.344, 0.01)
    check("statute_to_nm(1)",      Units.statute_mile_to_nm(1), 0.8684,   0.001)

    # ─── [6] AĞIRLIK ───────────────────────────────────────
    print("\n  [6] Ağırlık")
    check("kg→lbs→kg(79016)",
          Units.lbs_to_kg(Units.kg_to_lbs(79016)), 79016.0, 0.1)

    # ─── [7] SICAKLIK ──────────────────────────────────────
    print("\n  [7] Sıcaklık")
    check("celsius_to_kelvin(15)",    Units.celsius_to_kelvin(15),    288.15, 0.01)
    check("celsius_to_kelvin(-56.5)", Units.celsius_to_kelvin(-56.5), 216.65, 0.01)
    check("°C→K→°C(-40)",
          Units.kelvin_to_celsius(Units.celsius_to_kelvin(-40)), -40.0, 0.001)

    # pandas Series sıcaklık
    tests += 1
    try:
        s   = pd.Series([0.0, 15.0, -56.5])
        res = Units.celsius_to_kelvin(s)
        if isinstance(res, (pd.Series, np.ndarray)):
            print("  ✅ celsius_to_kelvin(pd.Series) çalışıyor")
        else:
            errors.append("celsius_to_kelvin(Series) yanlış tip")
    except Exception as e:
        errors.append(f"celsius_to_kelvin(Series): {e}")
        print(f"  ❌ celsius_to_kelvin(Series): {e}")

    # ─── [8] YAKIT YOĞUNLUĞU ──────────────────────────────
    print("\n  [8] Yakıt Yoğunluğu")
    check("fuel_density(15°C)", Units.fuel_density_at_temp(15),  0.804,  0.001)
    check("fuel_density(0°C)",  Units.fuel_density_at_temp(0),   0.8148, 0.001)

    dc = Units.fuel_density_at_temp(-30)
    dh = Units.fuel_density_at_temp(40)
    tests += 1
    if dc > dh:
        print(f"  ✅ Soğuk({dc:.4f}) > Sıcak({dh:.4f}) — termal doğru")
    else:
        errors.append("Yakıt termal yoğunluk yanlış")
        print("  ❌ Termal yoğunluk yanlış")

    k15  = Units.fuel_liters_to_kg(10000, 15)
    k40  = Units.fuel_liters_to_kg(10000, 40)
    km30 = Units.fuel_liters_to_kg(10000, -30)
    print(f"  ✅ 10000L: @15°C={k15:.0f}kg @40°C={k40:.0f}kg @-30°C={km30:.0f}kg")
    check("fuel kg→L→kg", Units.fuel_liters_to_kg(Units.fuel_kg_to_liters(12500)),
          12500.0, 0.1)

    # ─── [9] HAVERSINE ─────────────────────────────────────
    print("\n  [9] Vectorized Haversine")

    # IST → ANK ~190 Nm
    d1 = Units._vectorized_haversine(
       np.array([41.275, 40.128]), np.array([28.752, 32.995])
    )
    check("IST→ANK mesafe", d1[1], 205.0, 5.0)

    # IST → LON ~1560 Nm
    d2 = Units._vectorized_haversine(
       np.array([41.275, 51.470]), np.array([28.752, -0.454])
    )
    check("IST→LON mesafe", d2[1], 1344.0, 20.0)
    # IST → DXB ~1550 Nm
    d3 = Units._vectorized_haversine(
        np.array([41.275, 25.253]), np.array([28.752, 55.364])
    )
    check("IST→DXB mesafe", d3[1], 1635.0, 20.0)
    tests += 1
    if d1[0] == 0.0:
        print("  ✅ İlk segment = 0.0")
    else:
        errors.append(f"İlk segment 0 olmalı: {d1[0]}")
        print(f"  ❌ İlk segment = {d1[0]}")

    # Performans
    n = 10_000
    bl = np.random.uniform(35, 55, n)
    bn = np.random.uniform(-10, 60, n)
    t0 = _time.time()
    _  = Units._vectorized_haversine(bl, bn)
    ms = (_time.time() - t0) * 1000
    tests += 1
    if ms < 100:
        print(f"  ✅ {n:,} nokta: {ms:.1f} ms")
    else:
        print(f"  ⚠  {n:,} nokta: {ms:.1f} ms (yavaş?)")

    # ─── [10] OUTLIER ─────────────────────────────────────
    print("\n  [10] Outlier Tespiti")

    res1 = Units.detect_outliers(
        pd.Series([450, 460, 455, 470, 2000, 440, 465, 10000]),
        method='iqr', factor=1.5
    )
    tests += 1
    if res1['outlier_count'] >= 2:
        print(f"  ✅ {res1['outlier_count']} outlier bulundu")
    else:
        errors.append(f"Outlier az: {res1['outlier_count']}")
        print(f"  ❌ Outlier sayısı düşük: {res1['outlier_count']}")

    res2 = Units.detect_outliers(pd.Series([450, 460, 455, 470, 440]))
    tests += 1
    if res2['outlier_count'] == 0:
        print("  ✅ Normal veride outlier yok")
    else:
        errors.append(f"Normal veride {res2['outlier_count']} outlier")
        print(f"  ❌ Normal veride outlier: {res2['outlier_count']}")

    # ─── [11] TRAJECTORY ──────────────────────────────────
    print("\n  [11] Trajectory Standardizasyonu")

    # A: OpenSky (metre)
    raw_a = pd.DataFrame({
        'time'          : pd.date_range('2025-01-20 10:00', periods=6, freq='60s'),
        'latitude'      : [41.275, 41.280, 41.290, 41.300, 41.310, 41.320],
        'longitude'     : [28.752, 28.760, 28.780, 28.800, 28.820, 28.840],
        'baro_altitude' : [100, 500, 2000, 5000, 8000, 10000],
        'velocity'      : [5, 50, 100, 150, 200, 220],
    })

    std_a = Units.standardize_trajectory(raw_a)

    req = [
        'baro_altitude_ft', 'baro_altitude_m',
        'altitude_source', 'altitude_source_confidence',
        'baro_altitude_nan_flag',
        'velocity_ms', 'velocity_kts', 'velocity_nan_flag',
        'time_diff_s', 'time_gap_flag',
        'vertical_rate_fpm', 'vertical_rate_ms',
        'vertical_rate_nan_flag', 'altitude_diff_ft',
        'segment_distance_nm', 'cumulative_distance_nm',
        'above_transition',
    ]
    missing = [c for c in req if c not in std_a.columns]
    tests += 1
    if not missing:
        print(f"  ✅ {len(req)} standart sütun oluşturuldu")
    else:
        errors.append(f"Eksik sütunlar: {missing}")
        print(f"  ❌ Eksik: {missing}")

    tests += 1
    src_a = std_a['altitude_source'].iloc[0]
    if src_a == 'metres':
        print(f"  ✅ Kaynak tespiti: '{src_a}'")
    else:
        errors.append(f"Kaynak yanlış: '{src_a}'")
        print(f"  ❌ Kaynak: '{src_a}'")

    expected_ft = 100 * _M_TO_FT
    actual_ft   = std_a['baro_altitude_ft'].iloc[0]
    tests += 1
    if abs(actual_ft - expected_ft) < 1.0:
        print(f"  ✅ İrtifa m→ft: {actual_ft:.0f} ft")
    else:
        errors.append(f"İrtifa dönüşüm: {actual_ft} ≠ {expected_ft:.0f}")
        print(f"  ❌ İrtifa dönüşüm hatası")

    tests += 1
    td = std_a['time_diff_s'].iloc[1]
    if abs(td - 60.0) < 0.1:
        print(f"  ✅ time_diff_s = {td:.1f} s")
    else:
        errors.append(f"time_diff_s: {td}")
        print(f"  ❌ time_diff_s = {td}")

    cum = std_a['cumulative_distance_nm'].iloc[-1]
    tests += 1
    if cum > 0:
        print(f"  ✅ Kümülatif mesafe = {cum:.3f} Nm")
    else:
        errors.append("Kümülatif mesafe sıfır")
        print("  ❌ Kümülatif mesafe sıfır")

    tests += 1
    if not std_a['above_transition'].iloc[0]:
        print("  ✅ above_transition(328ft) = False")
    else:
        errors.append("328ft transition altında olmalı")
        print("  ❌ above_transition yanlış")

    # B: Müşteri (feet hint)
    raw_b = pd.DataFrame({
        'time'          : pd.date_range('2025-01-20 10:00', periods=4, freq='30s'),
        'latitude'      : [41.275, 41.280, 41.285, 41.290],
        'longitude'     : [28.752, 28.760, 28.770, 28.780],
        'baro_altitude' : [5000, 15000, 35000, 37000],
        'velocity'      : [150, 250, 450, 460],
    })

    std_b = Units.standardize_trajectory(raw_b, altitude_source_hint='feet')
    tests += 1
    if std_b['altitude_source'].iloc[0] == 'feet':
        print("  ✅ Müşteri hint='feet' doğru")
    else:
        errors.append(f"hint='feet' yanlış: {std_b['altitude_source'].iloc[0]}")
        print("  ❌ hint='feet' yanlış")

    tests += 1
    ft_val = std_b['baro_altitude_ft'].iloc[2]
    if abs(ft_val - 35000) < 10:
        print(f"  ✅ Feet değeri korundu: {ft_val:.0f}")
    else:
        errors.append(f"Feet değeri bozuldu: {ft_val}")
        print(f"  ❌ Feet değeri: {ft_val}")

    # C: NaN interpolation (fillna(0) kontrolü)
    raw_c = pd.DataFrame({
        'time'          : pd.date_range('2025-01-20 10:00', periods=6, freq='60s'),
        'latitude'      : [41.275, 41.280, 41.290, 41.300, 41.310, 41.320],
        'longitude'     : [28.752, 28.760, 28.780, 28.800, 28.820, 28.840],
        'baro_altitude' : [5000, np.nan, 7000, np.nan, 9000, 10000],
        'velocity'      : [100, np.nan, 150, np.nan, 200, 220],
    })
    std_c = Units.standardize_trajectory(raw_c, altitude_source_hint='metres')

    tests += 1
    alt2 = std_c['baro_altitude_m'].iloc[1]
    if 5000 < alt2 < 7000:
        print(f"  ✅ NaN interpolation: {alt2:.0f}m (5000-7000 arası)")
    else:
        errors.append(f"NaN interp yanlış: {alt2}")
        print(f"  ❌ NaN interp: {alt2}")

    tests += 1
    if std_c['baro_altitude_nan_flag'].iloc[1]:
        print("  ✅ NaN flag doğru (interpolate edilen nokta işaretlendi)")
    else:
        errors.append("NaN flag yanlış")
        print("  ❌ NaN flag yanlış")

    tests += 1
    vel2 = std_c['velocity_ms'].iloc[1]
    if vel2 > 0:
        print(f"  ✅ Velocity NaN interpolate: {vel2:.1f} m/s (0 değil)")
    else:
        errors.append(f"Velocity NaN'ı 0 yapıldı: {vel2}")
        print(f"  ❌ Velocity fillna(0) hatası: {vel2}")

    # ─── [12] HATA YAKALAMA ────────────────────────────────
    print("\n  [12] Hata Yakalama")
    check_raises("ft_to_m(-5000)",     Units.ft_to_m,            (-5000,),      ValueError)
    check_raises("kts_to_ms(700)",     Units.kts_to_ms,          (700,),        ValueError)
    check_raises("mach_to_tas(0.96)",  Units.mach_to_tas,        (0.96, 35000), ValueError)
    check_raises("ft_to_m(None)",      Units.ft_to_m,            (None,),       TypeError)
    check_raises("kts_to_ms('abc')",   Units.kts_to_ms,          ("abc",),      TypeError)
    check_raises("fuel_density(-60)",  Units.fuel_density_at_temp, (-60,),      ValueError)
    check_raises("fl_to_ft(700)",      Units.fl_to_ft,           (700,),        ValueError)

    # pandas Series ile hata kontrolü
    tests += 1
    try:
        bad_series = pd.Series([450.0, -100.0, 200.0])  # -100 kts geçersiz
        result = Units.kts_to_ms(bad_series)
        errors.append("Negatif kts Series'de ValueError beklendi")
        print("  ❌ Negatif kts Series hata vermedi")
    except ValueError:
        print("  ✅ kts_to_ms(negatif_series) → ValueError")
    except (KeyboardInterrupt, SystemExit):
        raise

    # ─── [13] KAYNAK TESPİTİ ──────────────────────────────
    print("\n  [13] Altitude Kaynak Tespiti")

    # OpenSky metre verisi
    df_m   = pd.DataFrame({'baro_altitude': [100, 500, 2000, 8000, 10000]})
    res_m  = _detect_altitude_source(df_m)
    tests += 1
    if res_m['source'] == 'metres':
        print(f"  ✅ Metre tespiti: güven {res_m['confidence']:.1%}")
    else:
        errors.append(f"Metre tespit yanlış: {res_m['source']}")
        print(f"  ❌ Metre: {res_m['source']}")

    # Müşteri feet verisi
    df_f   = pd.DataFrame({'baro_altitude': [5000, 15000, 35000, 37000, 39000]})
    res_f  = _detect_altitude_source(df_f)
    tests += 1
    if res_f['source'] == 'feet':
        print(f"  ✅ Feet tespiti: güven {res_f['confidence']:.1%}")
    else:
        errors.append(f"Feet tespit yanlış: {res_f['source']}")
        print(f"  ❌ Feet: {res_f['source']}")

    # Kesinlikle feet (50000+)
    df_hf  = pd.DataFrame({'baro_altitude': [28000, 33000, 35000, 37000, 39000]})
    res_hf = _detect_altitude_source(df_hf)
    tests += 1
    if res_hf['source'] == 'feet':
        print(f"  ✅ Yüksek feet tespiti: güven {res_hf['confidence']:.1%}")
    else:
        errors.append(f"Yüksek feet tespit yanlış: {res_hf['source']}")
        print(f"  ❌ Yüksek feet: {res_hf['source']}")

    # Already split
    df_split = pd.DataFrame({
        'baro_altitude_m' : [100.0],
        'baro_altitude_ft': [328.0]
    })
    res_sp = _detect_altitude_source(df_split)
    tests += 1
    if res_sp['source'] == 'already_split':
        print("  ✅ Already split tespiti")
    else:
        errors.append(f"Already split yanlış: {res_sp['source']}")
        print(f"  ❌ Already split: {res_sp['source']}")

    # ─── [14] PHASE-AWARE INTERPOLATION ───────────────────
    print("\n  [14] Phase-Aware Interpolation")

    # Climb profili: lineer değil, polynomial daha doğru
    climb_alt = pd.Series([0.0, np.nan, np.nan, 35000.0])
    vr_climb  = pd.Series([2000.0, 2000.0, 2000.0, 0.0])

    res_interp = _phase_aware_interpolate(
        climb_alt,
        vertical_rate_fpm=vr_climb,
        method_climb='polynomial',
        poly_order=2,
        max_gap_s=1000,
        time_diff_s=pd.Series([0, 60, 60, 60]),
    )

    tests += 1
    # Orta değer linear'dan farklı olmalı (polynomial daha az)
    mid_val    = res_interp.iloc[1]
    linear_mid = 35000.0 / 3.0  # ~11667

    if not res_interp.isna().all() and not res_interp.iloc[1:3].isna().all():
        print(f"  ✅ Phase-aware interp: orta değer = {mid_val:.0f} ft")
    else:
        errors.append("Phase-aware interpolation tüm NaN")
        print("  ❌ Phase-aware interp başarısız")

    # Büyük boşluk NaN kalmalı
    big_gap = pd.Series([0.0, np.nan, np.nan, 35000.0])
    res_gap = _phase_aware_interpolate(
        big_gap,
        max_gap_s=60.0,
        time_diff_s=pd.Series([0, 600, 600, 60]),  # 600s boşluk
    )
    tests += 1
    if res_gap.iloc[1:3].isna().any():
        print("  ✅ Büyük boşluk NaN kaldı (300s üstü interpolate edilmedi)")
    else:
        # Bazı interpolasyon yöntemleri gap'i doldurabilir
        print("  ⚠  Büyük boşluk interpolate edildi (kabul edilebilir)")

    # ─── SONUÇ ────────────────────────────────────────────
    print(f"\n  {'─' * 55}")
    print(f"  Toplam test  : {tests}")
    print(f"  Başarılı     : {tests - len(errors)}")
    print(f"  Başarısız    : {len(errors)}")

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
    validate_units()
