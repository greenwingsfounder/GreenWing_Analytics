"""
GreenWing Analytics — Veri Kalitesi Doğrulayıcı
═════════════════════════════════════════════════

KATMAN 1 / 3: Veri Kalitesi

Bu dosya HAM VERİNİN kalitesini kontrol eder.
Fiziksel mantık değil, veri bütünlüğü.

Kontroller:
    1.  None / boş DataFrame
    2.  Minimum veri noktası
    3.  Zorunlu sütunlar
    4.  Koordinat geçerliliği
    5.  İrtifa geçerliliği
    6.  Hız geçerliliği
    7.  NaN yoğunluğu
    8.  Zaman sırası ve boşluklar
    9.  Duplicate satırlar
    10. Aşırı outlier
    11. altitude_source_confidence (FEET fallback güveni)
    12. segment_distance_nm NaN (cumulative bozulma)

KULLANIM:
─────────
    from src.validation.data_validator import DataValidator

    result = DataValidator.validate_trajectory(df)
    if not result.is_valid:
        print(result.errors)

    result = DataValidator.validate_scalar("weight_kg", 72000)
    result = DataValidator.validate_flight_inputs(
        distance_nm=1560, weight_kg=72000, mach=0.785
    )
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════
# SONUÇ NESNESİ
# ═══════════════════════════════════════════════════════════

@dataclass
class ValidationResult:
    """
    Doğrulama sonucu.

    Attributes:
        is_valid     : Doğrulama geçti mi?
        errors       : FAIL listesi (kritik sorunlar)
        warnings     : WARNING listesi (dikkat edilmeli ama geçer)
        info         : INFO listesi (bilgi amaçlı)
        cleaned_data : Temizlenmiş veri (varsa)
        stats        : İstatistikler (veri özeti)
    """
    is_valid     : bool          = True
    errors       : list[str]     = field(default_factory=list)
    warnings     : list[str]     = field(default_factory=list)
    info         : list[str]     = field(default_factory=list)
    cleaned_data : Optional[Any] = None
    stats        : dict          = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def add_info(self, msg: str) -> None:
        self.info.append(msg)

    def merge(self, other: ValidationResult) -> None:
        """Başka bir sonucu bu sonuca ekle."""
        if not other.is_valid:
            self.is_valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.info.extend(other.info)
        self.stats.update(other.stats)

    def summary(self) -> str:
        status = "✅ PASS" if self.is_valid else "❌ FAIL"
        return (
            f"{status} | "
            f"errors={len(self.errors)} "
            f"warnings={len(self.warnings)} "
            f"info={len(self.info)}"
        )

    def __repr__(self) -> str:
        return f"ValidationResult({self.summary()})"


# ═══════════════════════════════════════════════════════════
# SINIR DEĞERLERİ
# ═══════════════════════════════════════════════════════════

_DATA_LIMITS = {
    "latitude"          : (-90.0,    90.0),
    "longitude"         : (-180.0,  180.0),
    "baro_altitude_ft"  : (-2000.0, 65000.0),
    "baro_altitude_m"   : (-610.0,  20000.0),
    "velocity_ms"       : (0.0,      310.0),
    "velocity_kts"      : (0.0,      600.0),
    "vertical_rate_fpm" : (-8000.0,  8000.0),
    "weight_kg"         : (5000.0,  650000.0),
    "fuel_kg"           : (0.0,     320000.0),
    "distance_nm"       : (0.0,     12000.0),
    "mach"              : (0.0,        0.95),
    "temperature_c"     : (-90.0,      60.0),
    "pressure_pa"       : (1000.0, 110000.0),
}

# # KAYNAK (denetim #86): uçuş izi kabul kuralları.
# #  5 nokta : bundan az noktayla tırmanış/seyir/alçalma ayrılamaz.
# #  600 s   : iki kayıt arası 10 dakikadan fazla boşluk → iz kopuk,
# #            faz segmentasyonu güvenilmez (ADSB ~1-60 s aralık verir).
#
MIN_TRAJECTORY_POINTS = 5
MAX_TIME_GAP_SECONDS  = 600


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class DataValidator:
    """
    Veri kalitesi doğrulama sınıfı.
    Tüm metodlar statik.
    """

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: SCALAR DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_scalar(
        name: str,
        value: Any,
        strict: bool = True,
    ) -> ValidationResult:
        """
        Tek bir skalar değeri doğrula.

        Args:
            name  : Parametre adı (_DATA_LIMITS anahtarı)
            value : Kontrol edilecek değer
            strict: True → sınır dışı = error, False → warning

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        if value is None:
            result.add_error(f"'{name}': None kabul edilmez.")
            return result

        if not isinstance(value, (int, float, np.integer, np.floating)):
            result.add_error(
                f"'{name}': Sayısal değer bekleniyor, "
                f"gelen: {type(value).__name__} = {value!r}"
            )
            return result

        if np.isnan(value) or np.isinf(value):
            result.add_error(f"'{name}': NaN veya Inf kabul edilmez.")
            return result

        if name in _DATA_LIMITS:
            lo, hi = _DATA_LIMITS[name]
            if value < lo or value > hi:
                msg = (
                    f"'{name}': {value} sınır dışı "
                    f"[{lo}, {hi}]."
                )
                if strict:
                    result.add_error(msg)
                else:
                    result.add_warning(msg)

        result.stats[name] = float(value)
        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: TRAJECTORY DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_trajectory(
        df: pd.DataFrame,
        min_points: int = MIN_TRAJECTORY_POINTS,
        max_gap_s: float = MAX_TIME_GAP_SECONDS,
        clean: bool = True,
    ) -> ValidationResult:
        """
        Trajectory DataFrame'ini doğrula.

        12 kontrol noktası:
            1.  None / boş DataFrame
            2.  Minimum veri noktası sayısı
            3.  Zorunlu sütunlar
            4.  Koordinat geçerliliği
            5.  İrtifa geçerliliği
            6.  Hız geçerliliği
            7.  NaN yoğunluğu
            8.  Zaman sırası ve boşluklar
            9.  Duplicate satırlar
            10. Aşırı outlier
            11. altitude_source_confidence (FEET fallback)
            12. segment_distance_nm NaN (cumulative bozulma)

        Args:
            df        : Trajectory DataFrame
            min_points: Minimum waypoint sayısı
            max_gap_s : Maksimum kabul edilebilir zaman boşluğu (saniye)
            clean     : True → temizlenmiş versiyonu result.cleaned_data'ya koy

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        # ─── Kontrol 1: None / Boş ────────────────────────
        if df is None:
            result.add_error("Trajectory DataFrame None.")
            return result

        if not isinstance(df, pd.DataFrame):
            result.add_error(
                f"pd.DataFrame bekleniyor, gelen: {type(df).__name__}"
            )
            return result

        if df.empty:
            result.add_error("Trajectory DataFrame boş (sıfır satır).")
            return result

        n = len(df)
        result.stats["total_rows"] = n

        # ─── Kontrol 2: Minimum nokta ─────────────────────
        if n < min_points:
            result.add_error(
                f"Yetersiz veri: {n} satır var, minimum {min_points} gerekli."
            )
            return result

        result.add_info(f"{n} satır yüklendi.")

        # ─── Kontrol 3: Zorunlu sütunlar ──────────────────
        has_time = 'time' in df.columns
        has_lat  = 'latitude' in df.columns
        has_lon  = 'longitude' in df.columns
        has_alt  = any(c in df.columns for c in
                       ['baro_altitude', 'baro_altitude_m', 'baro_altitude_ft'])

        if not has_lat:
            result.add_error("'latitude' sütunu eksik.")
        if not has_lon:
            result.add_error("'longitude' sütunu eksik.")
        if not has_alt:
            result.add_warning(
                "İrtifa sütunu bulunamadı "
                "('baro_altitude', 'baro_altitude_m', 'baro_altitude_ft'). "
                "Performans hesapları yapılamayabilir."
            )
        if not has_time:
            result.add_warning(
                "'time' sütunu eksik. "
                "Zaman bazlı analizler yapılamaz."
            )

        if not has_lat or not has_lon:
            return result

        # ─── Kontrol 4: Koordinat geçerliliği ─────────────
        lat_col = pd.to_numeric(df['latitude'], errors='coerce')
        lon_col = pd.to_numeric(df['longitude'], errors='coerce')

        lat_nan = int(lat_col.isna().sum())
        lon_nan = int(lon_col.isna().sum())

        if lat_nan > 0:
            result.add_warning(f"{lat_nan} satırda latitude NaN.")
        if lon_nan > 0:
            result.add_warning(f"{lon_nan} satırda longitude NaN.")

        lat_invalid = int(((lat_col < -90) | (lat_col > 90)).sum())
        lon_invalid = int(((lon_col < -180) | (lon_col > 180)).sum())

        if lat_invalid > 0:
            result.add_error(
                f"{lat_invalid} satırda latitude sınır dışı [-90, 90]."
            )
        if lon_invalid > 0:
            result.add_error(
                f"{lon_invalid} satırda longitude sınır dışı [-180, 180]."
            )

        result.stats["lat_nan_count"] = lat_nan
        result.stats["lon_nan_count"] = lon_nan

        # ─── Kontrol 5: İrtifa geçerliliği ────────────────
        alt_col_name = None
        alt_unit     = None

        if 'baro_altitude_ft' in df.columns:
            alt_col_name = 'baro_altitude_ft'
            alt_unit     = 'ft'
            lo, hi       = _DATA_LIMITS["baro_altitude_ft"]
        elif 'baro_altitude_m' in df.columns:
            alt_col_name = 'baro_altitude_m'
            alt_unit     = 'm'
            lo, hi       = _DATA_LIMITS["baro_altitude_m"]
        elif 'baro_altitude' in df.columns:
            alt_col_name = 'baro_altitude'
            alt_unit     = '?'
            lo, hi       = -2000, 65000

        if alt_col_name:
            alt_col     = pd.to_numeric(df[alt_col_name], errors='coerce')
            alt_nan     = int(alt_col.isna().sum())
            alt_nan_pct = alt_nan / n * 100

            if alt_nan_pct > 80:
                result.add_error(
                    f"İrtifa sütununda %{alt_nan_pct:.1f} NaN. "
                    f"Veri çok bozuk."
                )
            elif alt_nan_pct > 20:
                result.add_warning(
                    f"İrtifa sütununda %{alt_nan_pct:.1f} NaN. "
                    f"Interpolation gerekecek."
                )

            alt_invalid = int(((alt_col < lo) | (alt_col > hi)).sum())
            if alt_invalid > 0:
                result.add_error(
                    f"{alt_invalid} satırda irtifa sınır dışı "
                    f"[{lo}, {hi}] {alt_unit}."
                )

            if not alt_col.isna().all():
                result.stats["altitude_min"]     = float(alt_col.min())
                result.stats["altitude_max"]     = float(alt_col.max())
                result.stats["altitude_median"]  = float(alt_col.median())
                result.stats["altitude_nan_pct"] = round(alt_nan_pct, 1)

        # ─── Kontrol 6: Hız geçerliliği ───────────────────
        vel_col_name = None
        if 'velocity_kts' in df.columns:
            vel_col_name = 'velocity_kts'
            lo_v, hi_v   = _DATA_LIMITS["velocity_kts"]
        elif 'velocity_ms' in df.columns:
            vel_col_name = 'velocity_ms'
            lo_v, hi_v   = _DATA_LIMITS["velocity_ms"]
        elif 'velocity' in df.columns:
            vel_col_name = 'velocity'
            lo_v, hi_v   = _DATA_LIMITS["velocity_ms"]

        if vel_col_name:
            vel_col     = pd.to_numeric(df[vel_col_name], errors='coerce')
            vel_nan     = int(vel_col.isna().sum())
            vel_nan_pct = vel_nan / n * 100

            if vel_nan_pct > 80:
                result.add_warning(
                    f"Hız sütununda %{vel_nan_pct:.1f} NaN. "
                    f"Yakıt hesaplamalarında yalnızca irtifa kullanılacak."
                )

            vel_invalid = int(((vel_col < lo_v) | (vel_col > hi_v)).sum())
            if vel_invalid > 0:
                result.add_error(
                    f"{vel_invalid} satırda hız sınır dışı "
                    f"[{lo_v}, {hi_v}]."
                )

            result.stats["velocity_nan_pct"] = round(vel_nan_pct, 1)

        # ─── Kontrol 7: Genel NaN yoğunluğu ───────────────
        total_cells     = df.shape[0] * df.shape[1]
        total_nan       = int(df.isna().sum().sum())
        nan_pct_overall = total_nan / total_cells * 100 if total_cells > 0 else 0

        result.stats["overall_nan_pct"] = round(nan_pct_overall, 1)

        if nan_pct_overall > 50:
            result.add_error(
                f"Genel NaN oranı çok yüksek: %{nan_pct_overall:.1f}. "
                f"Veri kullanılamaz düzeyde bozuk."
            )
        elif nan_pct_overall > 20:
            result.add_warning(
                f"Genel NaN oranı: %{nan_pct_overall:.1f}. "
                f"Interpolation gerekecek."
            )

        # ─── Kontrol 8: Zaman sırası ve boşluklar ─────────
        if has_time:
            time_col = pd.to_datetime(df['time'], errors='coerce')
            time_nan = int(time_col.isna().sum())

            if time_nan > 0:
                result.add_warning(f"{time_nan} satırda geçersiz zaman.")

            if time_nan < n:
                valid_time = time_col.dropna().sort_values()
                time_diffs = valid_time.diff().dt.total_seconds().dropna()

                neg_diffs = int((time_diffs < 0).sum())
                if neg_diffs > 0:
                    result.add_warning(
                        f"{neg_diffs} negatif zaman farkı. "
                        f"Veri yeniden sıralanacak."
                    )

                big_gaps = int((time_diffs > max_gap_s).sum())
                if big_gaps > 0:
                    result.add_warning(
                        f"{big_gaps} büyük zaman boşluğu (>{max_gap_s}s). "
                        f"GPS kopması veya farklı uçuş segmentleri olabilir."
                    )

                result.stats["time_gap_count"]    = big_gaps
                result.stats["min_time_diff_s"]   = float(time_diffs.min()) if len(time_diffs) > 0 else 0
                result.stats["max_time_diff_s"]   = float(time_diffs.max()) if len(time_diffs) > 0 else 0
                result.stats["flight_duration_s"] = float(
                    (valid_time.max() - valid_time.min()).total_seconds()
                )

        # ─── Kontrol 9: Duplicate satırlar ────────────────
        if has_time:
            dup_count = int(df.duplicated(subset=['time'], keep='first').sum())
        else:
            dup_count = int(df.duplicated().sum())

        if dup_count > 0:
            result.add_warning(
                f"{dup_count} duplicate satır tespit edildi. "
                f"Temizleme sırasında kaldırılacak."
            )
            result.stats["duplicate_count"] = dup_count

        # ─── Kontrol 10: Aşırı outlier ────────────────────
        if alt_col_name and not df[alt_col_name].isna().all():
            alt_series = pd.to_numeric(df[alt_col_name], errors='coerce').dropna()
            if len(alt_series) > 4:
                Q1  = alt_series.quantile(0.25)
                Q3  = alt_series.quantile(0.75)
                IQR = Q3 - Q1
                if IQR > 0:
                    outlier_mask  = (
                        (alt_series < Q1 - 3 * IQR) |
                        (alt_series > Q3 + 3 * IQR)
                    )
                    outlier_count = int(outlier_mask.sum())
                    if outlier_count > 0:
                        result.add_warning(
                            f"İrtifada {outlier_count} aşırı outlier "
                            f"(IQR×3 yöntemi). "
                            f"GPS hatası olabilir."
                        )
                    result.stats["altitude_outlier_count"] = outlier_count

        # ─── Kontrol 11: altitude_source_confidence ────────
        if 'altitude_source_confidence' in df.columns:
            conf_vals = pd.to_numeric(
                df['altitude_source_confidence'], errors='coerce'
            ).dropna()

            if len(conf_vals) > 0:
                confidence = float(conf_vals.iloc[0])

                if confidence < 0.4:
                    result.add_error(
                        f"İrtifa birimi tespit güveni çok düşük: "
                        f"{confidence:.1%}. "
                        f"Veri güvenilmez. "
                        f"standardize_trajectory() çağrısında "
                        f"altitude_source_hint='metres' veya 'feet' "
                        f"parametresi kullanılmalı."
                    )
                elif confidence < 0.6:
                    result.add_warning(
                        f"İrtifa birimi tespit güveni düşük: "
                        f"{confidence:.1%}. "
                        f"Metre/feet karışma riski var. "
                        f"altitude_source_hint parametresiyle "
                        f"manuel belirtilmesi önerilir."
                    )
                else:
                    result.add_info(
                        f"İrtifa birimi güveni: {confidence:.1%}."
                    )

                result.stats["altitude_source_confidence"] = round(confidence, 3)

        elif 'altitude_source' in df.columns:
            source = str(df['altitude_source'].iloc[0])
            if source == 'ambiguous':
                result.add_warning(
                    f"İrtifa birimi belirsiz (ambiguous). "
                    f"Metre/feet karışma riski. "
                    f"altitude_source_hint kullanılması önerilir."
                )
            elif source == 'missing':
                result.add_error(
                    f"İrtifa verisi tamamen eksik. "
                    f"Performans hesapları yapılamaz."
                )

        # ─── Kontrol 12: segment_distance_nm NaN ──────────
        if 'segment_distance_nm' in df.columns:
            seg           = pd.to_numeric(df['segment_distance_nm'], errors='coerce')
            seg_nan_count = int(seg.isna().sum())
            seg_nan_pct   = seg_nan_count / n * 100

            if seg_nan_pct > 50:
                result.add_error(
                    f"segment_distance_nm'de %{seg_nan_pct:.1f} NaN. "
                    f"Rota mesafesi hesaplanamıyor. "
                    f"Koordinat verisi bozuk veya çok eksik."
                )
            elif seg_nan_pct > 10:
                result.add_warning(
                    f"segment_distance_nm'de %{seg_nan_pct:.1f} NaN. "
                    f"Bazı segmentlerin mesafesi bilinmiyor. "
                    f"GPS kopması veya koordinat hatası olabilir."
                )

            if not seg.isna().all():
                neg_segs   = int((seg < 0).sum())
                giant_segs = int((seg > 100).sum())

                if neg_segs > 0:
                    result.add_error(
                        f"{neg_segs} negatif segment_distance_nm. "
                        f"Haversine hesabında hata veya koordinat sorunu."
                    )

                if giant_segs > 0:
                    result.add_warning(
                        f"{giant_segs} segment > 100 Nm. "
                        f"GPS atlama veya veri boşluğu olabilir. "
                        f"clean_trajectory_outliers() uygulandı mı?"
                    )

            result.stats["segment_nan_pct"]   = round(seg_nan_pct, 1)
            result.stats["segment_nan_count"] = seg_nan_count

        if 'cumulative_distance_nm' in df.columns:
            cum           = pd.to_numeric(df['cumulative_distance_nm'], errors='coerce')
            cum_nan_count = int(cum.isna().sum())
            cum_final     = float(cum.dropna().iloc[-1]) if not cum.isna().all() else 0

            if cum_nan_count > 0:
                result.add_warning(
                    f"cumulative_distance_nm'de {cum_nan_count} NaN. "
                    f"Toplam mesafe hesabı eksik. "
                    f"segment_distance_nm'deki NaN'lardan yayılmış."
                )

            if cum_final < 1 and n > 5:
                result.add_error(
                    f"Kümülatif mesafe çok düşük: {cum_final:.2f} Nm. "
                    f"Koordinat verisi sabit veya bozuk olabilir."
                )

            result.stats["cumulative_distance_nm_final"] = round(cum_final, 2)

        # ─── Temizleme ─────────────────────────────────────
        if clean:
            cleaned = df.copy()

            if has_time:
                cleaned['time'] = pd.to_datetime(cleaned['time'], errors='coerce')
                cleaned = cleaned.sort_values('time').reset_index(drop=True)
                cleaned = cleaned.drop_duplicates(subset=['time'], keep='first')
                cleaned = cleaned.reset_index(drop=True)

            result.cleaned_data = cleaned

        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: UÇUŞ GİRDİLERİ DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_flight_inputs(
        distance_nm: Any,
        weight_kg: Any,
        mach: Any,
        altitude_ft: Optional[Any] = None,
        payload_kg: Optional[Any] = None,
        fuel_kg: Optional[Any] = None,
    ) -> ValidationResult:
        """
        Uçuş hesabı girdilerini doğrula.

        Args:
            distance_nm: Rota mesafesi (Nm)
            weight_kg  : Uçak ağırlığı (kg)
            mach       : Cruise Mach sayısı
            altitude_ft: Cruise irtifası (ft) — opsiyonel
            payload_kg : Payload (kg) — opsiyonel
            fuel_kg    : Yakıt miktarı (kg) — opsiyonel

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        r = DataValidator.validate_scalar("distance_nm", distance_nm)
        result.merge(r)
        if not r.is_valid:
            return result

        if float(distance_nm) < 1:
            result.add_error(
                f"distance_nm çok küçük: {distance_nm} Nm. Minimum 1 Nm."
            )

        r = DataValidator.validate_scalar("weight_kg", weight_kg)
        result.merge(r)
        if not r.is_valid:
            return result

        r = DataValidator.validate_scalar("mach", mach)
        result.merge(r)

        if altitude_ft is not None:
            r = DataValidator.validate_scalar("altitude_ft", altitude_ft)
            result.merge(r)

            if r.is_valid and float(altitude_ft) < 1000:
                result.add_warning(
                    f"altitude_ft çok düşük: {altitude_ft} ft. "
                    f"Cruise irtifası genellikle 15,000 ft üstünde."
                )

        if payload_kg is not None:
            r = DataValidator.validate_scalar("weight_kg", payload_kg)
            result.merge(r)

            if r.is_valid and float(payload_kg) > float(weight_kg):
                result.add_error(
                    f"payload_kg ({payload_kg}) > weight_kg ({weight_kg}). "
                    f"Payload, toplam ağırlıktan büyük olamaz."
                )

        if fuel_kg is not None:
            r = DataValidator.validate_scalar("fuel_kg", fuel_kg)
            result.merge(r)

            if r.is_valid and float(fuel_kg) > float(weight_kg) * 0.5:
                result.add_warning(
                    f"fuel_kg ({fuel_kg:.0f}) toplam ağırlığın "
                    f"%{float(fuel_kg)/float(weight_kg)*100:.0f}'inden fazla. "
                    f"Makul mu kontrol edin."
                )

        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: MÜŞTERİ VERİSİ DOĞRULAMA
    # ──────────────────────────────────────────────────────

    @staticmethod
    def validate_customer_dataframe(
        df: pd.DataFrame,
        required_columns: Optional[list[str]] = None,
    ) -> ValidationResult:
        """
        Müşteriden gelen Excel/CSV verisini doğrula.

        Args:
            df              : Müşteri DataFrame'i
            required_columns: Zorunlu sütun listesi. None → varsayılan.

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        if required_columns is None:
            required_columns = ['origin', 'destination', 'fuel_kg']

        if df is None or not isinstance(df, pd.DataFrame):
            result.add_error("Geçerli bir DataFrame değil.")
            return result

        if df.empty:
            result.add_error("DataFrame boş.")
            return result

        n = len(df)
        result.stats["total_rows"] = n
        result.add_info(f"{n} uçuş kaydı bulundu.")

        missing_cols = [c for c in required_columns if c not in df.columns]
        if missing_cols:
            result.add_error(
                f"Zorunlu sütunlar eksik: {missing_cols}. "
                f"Mevcut sütunlar: {list(df.columns)}"
            )
            return result

        if 'fuel_kg' in df.columns:
            fuel      = pd.to_numeric(df['fuel_kg'], errors='coerce')
            fuel_nan  = int(fuel.isna().sum())
            fuel_neg  = int((fuel < 0).sum())
            fuel_zero = int((fuel == 0).sum())

            if fuel_nan > 0:
                result.add_error(
                    f"fuel_kg sütununda {fuel_nan} geçersiz değer."
                )
            if fuel_neg > 0:
                result.add_error(
                    f"fuel_kg sütununda {fuel_neg} negatif değer. "
                    f"Yakıt negatif olamaz."
                )
            if fuel_zero > 0:
                result.add_warning(
                    f"{fuel_zero} satırda fuel_kg = 0. "
                    f"Sıfır yakıtlı uçuş mümkün mü?"
                )

            if not fuel.isna().all():
                result.stats["fuel_min"]  = float(fuel.min())
                result.stats["fuel_max"]  = float(fuel.max())
                result.stats["fuel_mean"] = float(fuel.mean())

        # ══════════════════════════════════════════════════════
        # DENETİM #47 — YALNIZ fuel_kg KONTROL EDİLİYORDU
        # ══════════════════════════════════════════════════════
        # Eski kod yalnız `fuel_kg` için sayısal/negatif kontrolü
        # yapıyordu. Müşteri verisinde `distance_nm = -100` veya
        # `weight_kg = 300.000` (300 ton — hiçbir uçak değil)
        # HİÇ yakalanmıyordu. Aşağıdaki fiziksel aralıklar
        # sektör dışı değerleri işaretler (hata değil UYARI:
        # müşteri verisi reddedilmeden önce gözden geçirilmeli).
        #
        # fuel_kg hata (hesap bozulur); diğerleri uyarı (rapor
        # kalitesi düşer ama motor çökmez).
        _RANGES = {
            'distance_nm'  : (1,      12_000, 'Mesafe'),
            'weight_kg'    : (20_000, 600_000, 'Ağırlık'),
            'cruise_alt_ft': (5_000,  45_000, 'Seyir irtifası'),
            'mach'         : (0.50,   0.92,   'Mach'),
        }
        for _col, (_lo, _hi, _label) in _RANGES.items():
            if _col not in df.columns:
                continue
            _vals = pd.to_numeric(df[_col], errors='coerce')
            _valid = _vals.dropna()
            if len(_valid) == 0:
                continue

            _nan = int(_vals.isna().sum())
            _neg = int((_valid < 0).sum())
            _below = int(((_valid > 0) & (_valid < _lo)).sum())
            _above = int((_valid > _hi).sum())

            if _nan > 0:
                result.add_warning(
                    f"{_col} sütununda {_nan} sayısal olmayan değer."
                )
            if _neg > 0:
                result.add_error(
                    f"{_col} sütununda {_neg} NEGATİF değer. "
                    f"{_label} negatif olamaz — hesap bozulur."
                )
            elif _below > 0 or _above > 0:
                result.add_warning(
                    f"{_col} sütununda {_below + _above} değer fiziksel "
                    f"aralık dışı [{_lo:,}–{_hi:,}] ({_label})."
                )

            result.stats[f"{_col}_min"] = float(_valid.min())
            result.stats[f"{_col}_max"] = float(_valid.max())

        for col in ['origin', 'destination']:
            if col in df.columns:
                invalid_icao = df[col].apply(
                    lambda x: not (isinstance(x, str) and 3 <= len(str(x)) <= 4)
                ).sum()
                if invalid_icao > 0:
                    result.add_warning(
                        f"{col} sütununda {invalid_icao} geçersiz ICAO kodu. "
                        f"ICAO kodları 3-4 karakter olmalı."
                    )

        if 'date' in df.columns:
            dates    = pd.to_datetime(df['date'], errors='coerce')
            date_nan = int(dates.isna().sum())
            if date_nan > 0:
                result.add_warning(
                    f"date sütununda {date_nan} geçersiz tarih."
                )

        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: HIZLI ÖZET
    # ──────────────────────────────────────────────────────

    @staticmethod
    def quick_check(df: pd.DataFrame) -> dict:
        """
        DataFrame hakkında hızlı özet istatistikler.
        Validasyon yapmaz, sadece bilgi verir.

        Args:
            df: Herhangi bir DataFrame

        Returns:
            dict: Temel istatistikler
        """
        if df is None or df.empty:
            return {"rows": 0, "cols": 0, "nan_pct": 100}

        total_cells = df.shape[0] * df.shape[1]
        total_nan   = int(df.isna().sum().sum())

        summary = {
            "rows"   : len(df),
            "cols"   : len(df.columns),
            "columns": list(df.columns),
            "nan_pct": round(total_nan / total_cells * 100, 1) if total_cells > 0 else 0,
            "dtypes" : df.dtypes.astype(str).to_dict(),
        }

        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            summary["numeric_summary"] = {}
            for col in numeric_cols:
                col_data = df[col].dropna()
                if len(col_data) > 0:
                    summary["numeric_summary"][col] = {
                        "min"  : round(float(col_data.min()), 4),
                        "max"  : round(float(col_data.max()), 4),
                        "mean" : round(float(col_data.mean()), 4),
                        "nan_n": int(df[col].isna().sum()),
                    }

        return summary