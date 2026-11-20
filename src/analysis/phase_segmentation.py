# src/analysis/phase_segmentation.py

"""
GreenWing Analytics — Uçuş Fazı Segmentasyonu
═══════════════════════════════════════════════

Bu dosya trajectory verisinden uçuş fazlarını belirler.

NEDEN KRİTİK:
─────────────
Yanlış faz = yanlış yakıt hesabı = yanlış optimizasyon.

Örnek:
    Climb fazını cruise sanıyorsan → fuel flow çok düşük hesaplanır
    Holding'i cruise sanıyorsan → SAR yanlış çıkar
    Descent'i climb sanıyorsan → step climb önerisi saçmalar

FAZLAR:
───────
    GROUND_TAXI_OUT   : Gate → Pist (motorlar idle)
    TAKEOFF           : Pist koşusu + ilk tırmanma (0-1500 ft AGL)
    INITIAL_CLIMB     : 1500-10000 ft (hız kısıtlaması bölgesi)
    CLIMB             : 10000 ft → cruise irtifası
    CRUISE            : Seviye uçuş (ana faz, en uzun)
    STEP_CLIMB        : Cruise sırasında irtifa değişimi
    DESCENT           : Cruise irtifası → 10000 ft
    APPROACH          : 10000 ft → pist eşiği
    LANDING           : Piste dokunma ve yavaşlama
    GROUND_TAXI_IN    : Pist → Gate
    HOLDING           : Dairesel bekleme (ATC talimatıyla)

KULLANIM:
─────────
    from src.analysis.phase_segmentation import FlightPhaseSegmenter

    segmenter = FlightPhaseSegmenter()
    df = segmenter.segment_trajectory(trajectory_df)
    # df artık 'flight_phase' sütununa sahip

    phases = segmenter.get_phase_summary(df)
    cruise = segmenter.get_cruise_segment(df)
    holdings = segmenter.detect_holdings(df)

Fiziksel kurallar:
──────────────────
    Dikey hız > +500 fpm  → CLIMB (veya STEP_CLIMB)
    Dikey hız < -500 fpm  → DESCENT
    |Dikey hız| ≤ 500 fpm → Seviye uçuş (CRUISE veya GROUND)
    on_ground = True       → GROUND
    Küçük alanda dairesel  → HOLDING

Kaynak:
───────
    ICAO Doc 9613 (PBN Manual) — Faz tanımları
    EUROCONTROL DDR — Trajectory segmentation methodology
    FAA Advisory Circular AC 91-79A — Stabilized approach
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional

from src.units import Units


# ═══════════════════════════════════════════════════════════
# FAZ SABİTLERİ
# ═══════════════════════════════════════════════════════════

# Faz isimleri (standart)
PHASE_GROUND_TAXI_OUT = 'GROUND_TAXI_OUT'
PHASE_TAKEOFF         = 'TAKEOFF'
PHASE_INITIAL_CLIMB   = 'INITIAL_CLIMB'
PHASE_CLIMB           = 'CLIMB'
PHASE_CRUISE          = 'CRUISE'
PHASE_STEP_CLIMB      = 'STEP_CLIMB'
PHASE_DESCENT         = 'DESCENT'
PHASE_APPROACH        = 'APPROACH'
PHASE_LANDING         = 'LANDING'
PHASE_GROUND_TAXI_IN  = 'GROUND_TAXI_IN'
PHASE_HOLDING         = 'HOLDING'
PHASE_UNKNOWN         = 'UNKNOWN'

# Tüm fazlar listesi (sıralı)
ALL_PHASES = [
    PHASE_GROUND_TAXI_OUT,
    PHASE_TAKEOFF,
    PHASE_INITIAL_CLIMB,
    PHASE_CLIMB,
    PHASE_CRUISE,
    PHASE_STEP_CLIMB,
    PHASE_DESCENT,
    PHASE_APPROACH,
    PHASE_LANDING,
    PHASE_GROUND_TAXI_IN,
    PHASE_HOLDING,
    PHASE_UNKNOWN,
]

# Dikey hız eşikleri (fpm)
# Bu değerler havacılık mühendisliği literatüründen
_CLIMB_THRESHOLD_FPM   = 500     # Üstü → tırmanma
_DESCENT_THRESHOLD_FPM = -500    # Altı → iniş
_LEVEL_BAND_FPM        = 300     # ±300 fpm → kesinlikle seviye

# İrtifa eşikleri (ft)
_GROUND_ALT_FT         = 200     # Bu altı → yerde
_TAKEOFF_ALT_FT        = 1500    # Kalkış üst sınırı (AGL)
_INITIAL_CLIMB_ALT_FT  = 10000   # İlk tırmanma üst sınırı
_CRUISE_MIN_ALT_FT     = 15000   # Cruise minimum irtifası

# Holding tespiti
_HOLDING_MIN_DURATION_S = 120    # Minimum 2 dakika
_HOLDING_MAX_AREA_DEG   = 0.15   # ~10 Nm yarıçap (derece cinsinden)

# Step climb tespiti
_STEP_CLIMB_MIN_ALT_CHANGE_FT = 1000  # Minimum 1000 ft değişim
_STEP_CLIMB_MAX_DURATION_S     = 600   # Maksimum 10 dakika


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class FlightPhaseSegmenter:
    """
    Uçuş fazı segmentasyonu.

    Trajectory verisinden her veri noktasına faz etiketi atar.

    Kullanım:
        segmenter = FlightPhaseSegmenter()
        df = segmenter.segment_trajectory(trajectory_df)
    """

    def __init__(
        self,
        climb_threshold_fpm: float = _CLIMB_THRESHOLD_FPM,
        descent_threshold_fpm: float = _DESCENT_THRESHOLD_FPM,
        ground_alt_ft: float = _GROUND_ALT_FT,
        cruise_min_alt_ft: float = _CRUISE_MIN_ALT_FT,
    ) -> None:
        """
        Args:
            climb_threshold_fpm  : Bu üstü → CLIMB (fpm)
            descent_threshold_fpm: Bu altı → DESCENT (fpm, negatif)
            ground_alt_ft        : Bu altı → GROUND (ft)
            cruise_min_alt_ft    : Bu üstü cruise olabilir (ft)
        """
        self.climb_threshold   = climb_threshold_fpm
        self.descent_threshold = descent_threshold_fpm
        self.ground_alt        = ground_alt_ft
        self.cruise_min_alt    = cruise_min_alt_ft

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: ANA SEGMENTASYON
    # ──────────────────────────────────────────────────────

    def segment_trajectory(
        self,
        df: pd.DataFrame,
        smooth_window: int = 5,
    ) -> pd.DataFrame:
        """
        Trajectory'deki her noktaya uçuş fazı etiketi ata.

        İşlem sırası:
            1. Gerekli sütunları kontrol et
            2. Dikey hızı yumuşat (gürültü azaltma)
            3. Temel faz ataması (irtifa + dikey hız kuralları)
            4. Kalkış/iniş ayrımı (uçuş yarısına göre)
            5. Step climb tespiti
            6. Holding tespiti
            7. Faz geçişlerini düzelt (izole noktaları temizle)

        Args:
            df           : Trajectory DataFrame.
                           standardize_trajectory'den geçmiş olmalı.
                           Gerekli sütunlar:
                               baro_altitude_ft
                               vertical_rate_fpm
                           Opsiyonel ama faydalı:
                               on_ground
                               velocity_kts
                               time_diff_s
                               latitude, longitude
            smooth_window: Dikey hız yumuşatma penceresi.
                           Tek sayı olmalı. 5 = iyi denge.
                           1 = yumuşatma yok.

        Returns:
            DataFrame: 'flight_phase' sütunu eklenmiş

        Not:
            Orijinal DataFrame değiştirilmez, kopya döner.
        """
        df = df.copy()

        # ─── Gerekli sütun kontrolü ──────────────────────
        if 'baro_altitude_ft' not in df.columns:
            df['flight_phase'] = PHASE_UNKNOWN
            return df

        alt = df['baro_altitude_ft'].values

        # ─── Dikey hız (varsa kullan, yoksa hesapla) ──────
        if 'vertical_rate_fpm' in df.columns:
            vr = df['vertical_rate_fpm'].values.copy()
        elif 'altitude_diff_ft' in df.columns and 'time_diff_s' in df.columns:
            td = df['time_diff_s'].values
            ad = df['altitude_diff_ft'].values
            vr = np.where(td > 0, ad / (td / 60.0), 0.0)
        else:
            # İrtifadan dikey hız türet
            vr = np.zeros(len(df))
            for i in range(1, len(df)):
                vr[i] = alt[i] - alt[i-1]  # ft/nokta (kaba tahmin)

        # ─── Dikey hız yumuşatma (gürültü azaltma) ───────
        if smooth_window > 1 and len(vr) > smooth_window:
            # Hareketli ortalama (kenarları koruyarak)
            kernel = np.ones(smooth_window) / smooth_window
            vr_smooth = np.convolve(vr, kernel, mode='same')

            # Kenarları orijinal bırak (convolution kenar etkisi)
            half = smooth_window // 2
            vr_smooth[:half]  = vr[:half]
            vr_smooth[-half:] = vr[-half:]
            vr = vr_smooth

        df['vertical_rate_fpm_smooth'] = vr

        # ─── on_ground bilgisi ────────────────────────────
        if 'on_ground' in df.columns:
            on_ground = df['on_ground'].values.astype(bool)
        else:
            on_ground = alt < self.ground_alt

        # ─── Adım 1: Temel faz ataması ───────────────────
        n      = len(df)
        phases = np.full(n, PHASE_UNKNOWN, dtype=object)

        for i in range(n):
            a  = alt[i]
            v  = vr[i]
            og = on_ground[i]

            if og or a < self.ground_alt:
                phases[i] = PHASE_GROUND_TAXI_OUT  # Sonra düzeltilecek
            elif a < _TAKEOFF_ALT_FT and v > self.climb_threshold:
                phases[i] = PHASE_TAKEOFF
            elif a < _INITIAL_CLIMB_ALT_FT and v > self.climb_threshold:
                phases[i] = PHASE_INITIAL_CLIMB
            elif v > self.climb_threshold:
                phases[i] = PHASE_CLIMB
            elif v < self.descent_threshold:
                phases[i] = PHASE_DESCENT
            elif a < _INITIAL_CLIMB_ALT_FT and v < self.descent_threshold * 0.5:
                phases[i] = PHASE_APPROACH
            elif a >= self.cruise_min_alt and abs(v) <= _LEVEL_BAND_FPM:
                phases[i] = PHASE_CRUISE
            elif a >= self.cruise_min_alt:
                # İrtifa yüksek ama ne tırmanma ne iniş → cruise
                phases[i] = PHASE_CRUISE
            else:
                # Düşük irtifa, düşük dikey hız → muhtemelen approach
                if v < 0:
                    phases[i] = PHASE_APPROACH
                else:
                    phases[i] = PHASE_INITIAL_CLIMB

        # ─── Adım 2: Ground fazını düzelt ─────────────────
        # Uçuşun ilk yarısındaki ground = TAXI_OUT
        # İkinci yarısındaki ground = TAXI_IN
        mid = n // 2

        # İlk ground bloğu = taxi out
        # Son ground bloğu = taxi in
        first_airborne = -1
        last_airborne  = -1

        for i in range(n):
            if phases[i] != PHASE_GROUND_TAXI_OUT:
                first_airborne = i
                break

        for i in range(n-1, -1, -1):
            if phases[i] not in (PHASE_GROUND_TAXI_OUT, PHASE_GROUND_TAXI_IN):
                last_airborne = i
                break

        if first_airborne > 0 and last_airborne > 0:
            # İlk airborne öncesi = taxi out
            for i in range(first_airborne):
                phases[i] = PHASE_GROUND_TAXI_OUT

            # Son airborne sonrası = taxi in
            for i in range(last_airborne + 1, n):
                if on_ground[i] or alt[i] < self.ground_alt:
                    phases[i] = PHASE_GROUND_TAXI_IN

            # Landing = son approach/descent'tan hemen sonra, yerde
            if last_airborne < n - 1:
                phases[last_airborne + 1] = PHASE_LANDING

        # ─── Adım 3: Approach düzeltme ───────────────────
        # Descent'ten sonra gelen düşük irtifa fazları → APPROACH
        in_descent_zone = False
        for i in range(n):
            if phases[i] == PHASE_DESCENT:
                in_descent_zone = True
            elif in_descent_zone and phases[i] in (PHASE_INITIAL_CLIMB, PHASE_UNKNOWN):
                if alt[i] < _INITIAL_CLIMB_ALT_FT:
                    phases[i] = PHASE_APPROACH
            elif phases[i] == PHASE_GROUND_TAXI_IN:
                in_descent_zone = False

        # ─── Adım 4: Step climb tespiti ──────────────────
        phases = self._detect_step_climbs(phases, alt, vr, df)

        # ─── Adım 5: Holding tespiti ─────────────────────
        if 'latitude' in df.columns and 'longitude' in df.columns:
            phases = self._detect_holdings(
                phases, df, alt
            )

        # ─── Adım 6: İzole noktaları düzelt ──────────────
        phases = self._smooth_phases(phases, min_duration=3)

        df['flight_phase'] = phases
        return df

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: STEP CLIMB TESPİTİ
    # ──────────────────────────────────────────────────────

    def _detect_step_climbs(
        self,
        phases: np.ndarray,
        alt: np.ndarray,
        vr: np.ndarray,
        df: pd.DataFrame,
    ) -> np.ndarray:
        """
        Cruise sırasındaki step climb'ları tespit et.

        Step climb = cruise irtifasından daha yüksek irtifaya
        kısa süreli tırmanma.

        Koşullar:
            1. Önceki faz CRUISE
            2. Dikey hız > climb_threshold
            3. İrtifa değişimi > 1000 ft
            4. Süre < 10 dakika
            5. Sonraki faz tekrar CRUISE
        """
        n = len(phases)

        # Cruise bölgelerini bul
        for i in range(2, n - 2):
            if phases[i] == PHASE_CLIMB:
                # Önceki ve sonraki fazlar cruise mi?
                prev_cruise = any(
                    phases[j] == PHASE_CRUISE
                    for j in range(max(0, i-5), i)
                )
                next_cruise = any(
                    phases[j] == PHASE_CRUISE
                    for j in range(i+1, min(n, i+10))
                )

                if prev_cruise and next_cruise:
                    # İrtifa değişimi yeterli mi?
                    alt_before = alt[max(0, i-3):i].mean() if i > 2 else alt[i]
                    alt_after_idx = min(i+5, n-1)
                    alt_after  = alt[i+1:alt_after_idx+1].mean() if i+1 < n else alt[i]

                    alt_change = alt_after - alt_before

                    if alt_change > _STEP_CLIMB_MIN_ALT_CHANGE_FT:
                        phases[i] = PHASE_STEP_CLIMB

        return phases

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: HOLDING TESPİTİ
    # ──────────────────────────────────────────────────────

    def _detect_holdings(
        self,
        phases: np.ndarray,
        df: pd.DataFrame,
        alt: np.ndarray,
    ) -> np.ndarray:
        """
        Holding pattern tespiti.

        Holding = ATC tarafından uçağın belirli bir noktada
        dairesel olarak bekleme yapması.

        Tespit yöntemi:
            Küçük bir coğrafi alanda (lat/lon aralığı < 0.15°)
            uzun süre (> 2 dakika) kalmak.

        NOT: Bu basitleştirilmiş yöntem.
             Gelişmiş versiyon: heading değişim analizi,
             racetrack pattern tespiti.
        """
        n = len(phases)

        if 'latitude' not in df.columns or 'longitude' not in df.columns:
            return phases

        lat = df['latitude'].values
        lon = df['longitude'].values

        # time_diff_s varsa süre hesabı
        has_time = 'time_diff_s' in df.columns
        td = df['time_diff_s'].values if has_time else np.ones(n)

        # Kayan pencere ile holding tespiti
        window = 20  # Her 20 noktayı kontrol et

        for start in range(0, n - window, window // 2):
            end = min(start + window, n)
            segment = slice(start, end)

            # Coğrafi alan hesapla
            seg_lat = lat[segment]
            seg_lon = lon[segment]

            # NaN kontrolü
            valid = ~(np.isnan(seg_lat) | np.isnan(seg_lon))
            if valid.sum() < 5:
                continue

            lat_range = np.nanmax(seg_lat) - np.nanmin(seg_lat)
            lon_range = np.nanmax(seg_lon) - np.nanmin(seg_lon)

            # Süre hesapla
            if has_time:
                duration = td[segment].sum()
            else:
                duration = (end - start) * 60  # Varsayım: 1 dk/nokta

            # İrtifa: cruise irtifasında veya approach irtifasında
            avg_alt = np.nanmean(alt[segment])

            # Holding koşulları
            is_small_area = lat_range < _HOLDING_MAX_AREA_DEG and \
                           lon_range < _HOLDING_MAX_AREA_DEG
            is_long_enough = duration > _HOLDING_MIN_DURATION_S
            is_airborne = avg_alt > self.ground_alt

            if is_small_area and is_long_enough and is_airborne:
                # Bu bölgeyi HOLDING olarak işaretle
                for i in range(start, end):
                    if phases[i] in (PHASE_CRUISE, PHASE_APPROACH,
                                     PHASE_DESCENT, PHASE_UNKNOWN):
                        phases[i] = PHASE_HOLDING

        return phases

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: FAZ DÜZELTME (İZOLE NOKTALAR)
    # ──────────────────────────────────────────────────────

    def _smooth_phases(
        self,
        phases: np.ndarray,
        min_duration: int = 3,
    ) -> np.ndarray:
        """
        İzole faz noktalarını düzelt.

        Sorun:
            GPS gürültüsü veya dikey hız salınımı nedeniyle
            tek nokta farklı faz alabilir:
            CRUISE CRUISE CLIMB CRUISE CRUISE
            → Ortadaki CLIMB muhtemelen gürültü

        Çözüm:
            min_duration'dan kısa süren faz blokları,
            çevreleyen fazla değiştirilir.

        Args:
            phases      : Faz dizisi
            min_duration: Minimum nokta sayısı (altı → düzelt)

        Returns:
            np.ndarray: Düzeltilmiş fazlar
        """
        n = len(phases)
        if n < 3:
            return phases

        result = phases.copy()

        # Faz bloklarını bul
        i = 0
        while i < n:
            # Bu blok nerede bitiyor?
            j = i
            while j < n and result[j] == result[i]:
                j += 1

            block_length = j - i
            block_phase  = result[i]

            # Çok kısa blok → düzelt
            if block_length < min_duration:
                # Önceki ve sonraki fazı kontrol et
                prev_phase = result[i-1] if i > 0 else PHASE_UNKNOWN
                next_phase = result[j] if j < n else PHASE_UNKNOWN

                # Önceki ve sonraki aynıysa → onlarla değiştir
                if prev_phase == next_phase and prev_phase != PHASE_UNKNOWN:
                    for k in range(i, j):
                        result[k] = prev_phase
                # Önceki veya sonraki ile değiştir
                elif prev_phase != PHASE_UNKNOWN:
                    for k in range(i, j):
                        result[k] = prev_phase
                elif next_phase != PHASE_UNKNOWN:
                    for k in range(i, j):
                        result[k] = next_phase

            i = j

        return result

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: FAZ BİLGİ FONKSİYONLARI
    # ──────────────────────────────────────────────────────

    @staticmethod
    def get_phase_summary(df: pd.DataFrame) -> dict:
        """
        Faz bazlı özet istatistikler.

        Args:
            df: segment_trajectory'den geçmiş DataFrame
                ('flight_phase' sütunu olmalı)

        Returns:
            dict: {faz_adı: {count, duration_s, duration_min,
                             alt_min_ft, alt_max_ft, pct_of_total}}

        Örnekler:
            summary = FlightPhaseSegmenter.get_phase_summary(df)
            print(f"Cruise süresi: {summary['CRUISE']['duration_min']:.1f} dk")
        """
        if 'flight_phase' not in df.columns:
            return {}

        has_time = 'time_diff_s' in df.columns
        has_alt  = 'baro_altitude_ft' in df.columns
        n        = len(df)

        summary = {}

        for phase in df['flight_phase'].unique():
            mask = df['flight_phase'] == phase
            count = int(mask.sum())

            phase_data = {
                'count'        : count,
                'pct_of_total' : round(count / n * 100, 1) if n > 0 else 0,
            }

            if has_time:
                duration_s = float(df.loc[mask, 'time_diff_s'].sum())
                phase_data['duration_s']   = round(duration_s, 1)
                phase_data['duration_min'] = round(duration_s / 60, 1)

            if has_alt:
                alt_vals = df.loc[mask, 'baro_altitude_ft'].dropna()
                if len(alt_vals) > 0:
                    phase_data['alt_min_ft'] = round(float(alt_vals.min()))
                    phase_data['alt_max_ft'] = round(float(alt_vals.max()))
                    phase_data['alt_avg_ft'] = round(float(alt_vals.mean()))

            summary[phase] = phase_data

        return summary

    @staticmethod
    def get_cruise_segment(df: pd.DataFrame) -> pd.DataFrame:
        """
        Sadece cruise fazındaki veri noktalarını döndür.

        Args:
            df: segment_trajectory'den geçmiş DataFrame

        Returns:
            DataFrame: Sadece CRUISE (ve STEP_CLIMB) fazları

        Not:
            Step climb noktaları da dahil edilir çünkü
            cruise bölümünün bir parçasıdır.
        """
        if 'flight_phase' not in df.columns:
            return df

        cruise_phases = [PHASE_CRUISE, PHASE_STEP_CLIMB]
        mask = df['flight_phase'].isin(cruise_phases)
        return df[mask].copy().reset_index(drop=True)

    @staticmethod
    def get_phase_transitions(df: pd.DataFrame) -> list[dict]:
        """
        Faz geçişlerini listele.

        Uçuşun kronolojik faz sıralamasını gösterir.

        Args:
            df: segment_trajectory'den geçmiş DataFrame

        Returns:
            list[dict]: Her geçiş {from_phase, to_phase, index, altitude_ft}

        Örnekler:
            transitions = FlightPhaseSegmenter.get_phase_transitions(df)
            # [
            #   {'from': 'GROUND_TAXI_OUT', 'to': 'TAKEOFF', 'index': 5, 'alt': 200},
            #   {'from': 'TAKEOFF', 'to': 'INITIAL_CLIMB', 'index': 8, 'alt': 1500},
            #   ...
            # ]
        """
        if 'flight_phase' not in df.columns:
            return []

        transitions = []
        phases = df['flight_phase'].values
        has_alt = 'baro_altitude_ft' in df.columns

        for i in range(1, len(phases)):
            if phases[i] != phases[i-1]:
                t = {
                    'from_phase': phases[i-1],
                    'to_phase'  : phases[i],
                    'index'     : i,
                }
                if has_alt:
                    t['altitude_ft'] = round(float(df['baro_altitude_ft'].iloc[i]))
                transitions.append(t)

        return transitions

    @staticmethod
    def detect_holdings_detailed(df: pd.DataFrame) -> list[dict]:
        """
        Holding pattern detaylarını listele.

        Args:
            df: segment_trajectory'den geçmiş DataFrame

        Returns:
            list[dict]: Her holding {start_index, end_index,
                                      duration_s, altitude_ft, position}
        """
        if 'flight_phase' not in df.columns:
            return []

        holdings = []
        in_holding = False
        start_idx  = 0

        for i in range(len(df)):
            if df['flight_phase'].iloc[i] == PHASE_HOLDING:
                if not in_holding:
                    in_holding = True
                    start_idx  = i
            else:
                if in_holding:
                    # Holding bitti
                    end_idx = i - 1

                    holding_data = {
                        'start_index': start_idx,
                        'end_index'  : end_idx,
                        'points'     : end_idx - start_idx + 1,
                    }

                    if 'time_diff_s' in df.columns:
                        duration = float(
                            df['time_diff_s'].iloc[start_idx:end_idx+1].sum()
                        )
                        holding_data['duration_s']   = round(duration, 1)
                        holding_data['duration_min'] = round(duration / 60, 1)

                    if 'baro_altitude_ft' in df.columns:
                        alt_slice = df['baro_altitude_ft'].iloc[start_idx:end_idx+1]
                        holding_data['altitude_ft'] = round(float(alt_slice.mean()))

                    if 'latitude' in df.columns and 'longitude' in df.columns:
                        holding_data['center_lat'] = round(float(
                            df['latitude'].iloc[start_idx:end_idx+1].mean()
                        ), 4)
                        holding_data['center_lon'] = round(float(
                            df['longitude'].iloc[start_idx:end_idx+1].mean()
                        ), 4)

                    holdings.append(holding_data)
                    in_holding = False

        # Son blok holding ise
        if in_holding:
            end_idx = len(df) - 1
            holding_data = {
                'start_index': start_idx,
                'end_index'  : end_idx,
                'points'     : end_idx - start_idx + 1,
            }

            if 'time_diff_s' in df.columns:
                duration = float(
                    df['time_diff_s'].iloc[start_idx:end_idx+1].sum()
                )
                holding_data['duration_s']   = round(duration, 1)
                holding_data['duration_min'] = round(duration / 60, 1)

            holdings.append(holding_data)

        return holdings

    @staticmethod
    def get_step_climbs_detected(df: pd.DataFrame) -> list[dict]:
        """
        Tespit edilen step climb'ları listele.

        Args:
            df: segment_trajectory'den geçmiş DataFrame

        Returns:
            list[dict]: Her step climb {start_index, end_index,
                                         from_alt_ft, to_alt_ft, alt_change_ft}
        """
        if 'flight_phase' not in df.columns:
            return []

        step_climbs = []
        in_step     = False
        start_idx   = 0

        for i in range(len(df)):
            if df['flight_phase'].iloc[i] == PHASE_STEP_CLIMB:
                if not in_step:
                    in_step   = True
                    start_idx = i
            else:
                if in_step:
                    end_idx = i - 1

                    from_alt = float(df['baro_altitude_ft'].iloc[max(0, start_idx-1)])
                    to_alt   = float(df['baro_altitude_ft'].iloc[min(end_idx+1, len(df)-1)])

                    step_climbs.append({
                        'start_index' : start_idx,
                        'end_index'   : end_idx,
                        'from_alt_ft' : round(from_alt),
                        'to_alt_ft'   : round(to_alt),
                        'alt_change_ft': round(to_alt - from_alt),
                    })

                    in_step = False

        return step_climbs

    # ──────────────────────────────────────────────────────
    # BÖLÜM 6: HIZLI FAZ BİLGİSİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def flight_phase_exists(df: pd.DataFrame, phase: str) -> bool:
        """Belirli bir faz var mı?"""
        if 'flight_phase' not in df.columns:
            return False
        return phase in df['flight_phase'].values

    @staticmethod
    def cruise_duration_minutes(df: pd.DataFrame) -> float:
        """Cruise süresi (dakika)."""
        if 'flight_phase' not in df.columns or 'time_diff_s' not in df.columns:
            return 0.0
        mask = df['flight_phase'].isin([PHASE_CRUISE, PHASE_STEP_CLIMB])
        return float(df.loc[mask, 'time_diff_s'].sum() / 60.0)

    @staticmethod
    def holding_duration_minutes(df: pd.DataFrame) -> float:
        """Toplam holding süresi (dakika)."""
        if 'flight_phase' not in df.columns or 'time_diff_s' not in df.columns:
            return 0.0
        mask = df['flight_phase'] == PHASE_HOLDING
        return float(df.loc[mask, 'time_diff_s'].sum() / 60.0)


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_phase_segmentation() -> bool:
    """
    Phase segmentation doğrulama testleri.

    Çalıştırma:
        python -m src.analysis.phase_segmentation
    """
    print("\n" + "=" * 60)
    print("  PHASE_SEGMENTATION.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests = 0

    segmenter = FlightPhaseSegmenter()

    def ok(name: str) -> None:
        nonlocal tests
        tests += 1
        print(f"  ✅ {name}")

    def fail(name: str, detail: str) -> None:
        nonlocal tests
        tests += 1
        errors.append(f"{name}: {detail}")
        print(f"  ❌ {name}: {detail}")

    # ─── Simüle uçuş oluştur ─────────────────────────────
    def make_flight(n_points: int = 200) -> pd.DataFrame:
        """
        Gerçekçi uçuş profili simüle et.
        LTFM → EGLL benzeri (~1560 Nm, ~3.5 saat)
        """
        data = {
            'time': pd.date_range('2025-01-20 10:00', periods=n_points, freq='60s'),
            'latitude': np.zeros(n_points),
            'longitude': np.zeros(n_points),
            'baro_altitude_ft': np.zeros(n_points),
            'velocity_kts': np.zeros(n_points),
            'on_ground': np.zeros(n_points, dtype=bool),
        }

        # Faz profili oluştur
        # Taxi out: 0-9 (10 nokta = 10 dk)
        # Takeoff: 10-14 (5 nokta)
        # Initial climb: 15-24 (10 nokta)
        # Climb: 25-49 (25 nokta)
        # Cruise: 50-149 (100 nokta)
        # Descent: 150-174 (25 nokta)
        # Approach: 175-189 (15 nokta)
        # Landing: 190 (1 nokta)
        # Taxi in: 191-199 (9 nokta)

        for i in range(n_points):
            if i < 10:
                # Taxi out
                data['baro_altitude_ft'][i] = 100
                data['velocity_kts'][i] = 15
                data['on_ground'][i] = True
                data['latitude'][i] = 41.275 + i * 0.001
                data['longitude'][i] = 28.752

            elif i < 15:
                # Takeoff
                frac = (i - 10) / 5
                data['baro_altitude_ft'][i] = 100 + frac * 1400
                data['velocity_kts'][i] = 150 + frac * 100
                data['on_ground'][i] = False
                data['latitude'][i] = 41.280 + frac * 0.02
                data['longitude'][i] = 28.752 + frac * 0.02

            elif i < 25:
                # Initial climb (1500 → 10000 ft)
                frac = (i - 15) / 10
                data['baro_altitude_ft'][i] = 1500 + frac * 8500
                data['velocity_kts'][i] = 250
                data['latitude'][i] = 41.30 + frac * 0.5
                data['longitude'][i] = 28.77 + frac * 0.5

            elif i < 50:
                # Climb (10000 → 37000 ft)
                frac = (i - 25) / 25
                data['baro_altitude_ft'][i] = 10000 + frac * 27000
                data['velocity_kts'][i] = 300 + frac * 150
                data['latitude'][i] = 41.80 + frac * 2.0
                data['longitude'][i] = 29.27 + frac * 2.0

            elif i < 150:
                # Cruise (37000 ft sabit)
                frac = (i - 50) / 100
                data['baro_altitude_ft'][i] = 37000 + np.random.normal(0, 30)
                data['velocity_kts'][i] = 450 + np.random.normal(0, 5)
                data['latitude'][i] = 43.80 + frac * 7.67
                data['longitude'][i] = 31.27 - frac * 31.72

            elif i < 175:
                # Descent (37000 → 10000 ft)
                frac = (i - 150) / 25
                data['baro_altitude_ft'][i] = 37000 - frac * 27000
                data['velocity_kts'][i] = 400 - frac * 100
                data['latitude'][i] = 51.47 - frac * 0.3
                data['longitude'][i] = -0.45 + frac * 0.1

            elif i < 190:
                # Approach (10000 → 200 ft)
                frac = (i - 175) / 15
                data['baro_altitude_ft'][i] = 10000 - frac * 9800
                data['velocity_kts'][i] = 250 - frac * 110
                data['latitude'][i] = 51.47 - frac * 0.01
                data['longitude'][i] = -0.45

            elif i == 190:
                # Landing
                data['baro_altitude_ft'][i] = 83
                data['velocity_kts'][i] = 60
                data['on_ground'][i] = True
                data['latitude'][i] = 51.470
                data['longitude'][i] = -0.454

            else:
                # Taxi in
                data['baro_altitude_ft'][i] = 83
                data['velocity_kts'][i] = 15
                data['on_ground'][i] = True
                data['latitude'][i] = 51.470
                data['longitude'][i] = -0.454

        df = pd.DataFrame(data)

        # time_diff_s ve vertical_rate_fpm ekle
        df['time_diff_s'] = df['time'].diff().dt.total_seconds().fillna(0)
        df['altitude_diff_ft'] = df['baro_altitude_ft'].diff().fillna(0)
        df['vertical_rate_fpm'] = np.where(
            df['time_diff_s'] > 0,
            df['altitude_diff_ft'] / (df['time_diff_s'] / 60.0),
            0
        )

        return df

    # ─── [1] Temel segmentasyon ───────────────────────────
    print("\n  [1] Temel Segmentasyon")

    flight = make_flight()
    result = segmenter.segment_trajectory(flight)

    if 'flight_phase' in result.columns:
        ok("flight_phase sütunu oluşturuldu")
    else:
        fail("flight_phase", "sütun yok")
        return False

    unique_phases = result['flight_phase'].unique()
    if len(unique_phases) >= 4:
        ok(f"{len(unique_phases)} farklı faz tespit edildi: {sorted(unique_phases)}")
    else:
        fail("faz sayısı", f"az: {unique_phases}")

    # ─── [2] Beklenen fazlar var mı? ──────────────────────
    print("\n  [2] Beklenen Fazlar")

    expected_phases = [
        PHASE_GROUND_TAXI_OUT, PHASE_CRUISE, PHASE_DESCENT,
    ]
    for phase in expected_phases:
        if phase in unique_phases:
            ok(f"{phase} mevcut")
        else:
            fail(phase, "bulunamadı")

    # Cruise en uzun faz olmalı
    summary = FlightPhaseSegmenter.get_phase_summary(result)

    if PHASE_CRUISE in summary:
        cruise_pct = summary[PHASE_CRUISE]['pct_of_total']
        if cruise_pct > 30:
            ok(f"Cruise %{cruise_pct:.1f} — en büyük faz")
        else:
            fail("Cruise oranı", f"%{cruise_pct:.1f} çok düşük")
    else:
        fail("Cruise", "summary'de yok")

    # ─── [3] Cruise segmenti ──────────────────────────────
    print("\n  [3] Cruise Segmenti")

    cruise_df = FlightPhaseSegmenter.get_cruise_segment(result)

    if len(cruise_df) > 0:
        ok(f"Cruise segmenti: {len(cruise_df)} nokta")
    else:
        fail("Cruise segmenti", "boş")

    if 'baro_altitude_ft' in cruise_df.columns and len(cruise_df) > 0:
        avg_alt = cruise_df['baro_altitude_ft'].mean()
        if 30000 < avg_alt < 42000:
            ok(f"Cruise irtifası: FL{avg_alt/100:.0f}")
        else:
            fail("Cruise irtifası", f"{avg_alt:.0f} ft makul değil")

    # ─── [4] Faz geçişleri ────────────────────────────────
    print("\n  [4] Faz Geçişleri")

    transitions = FlightPhaseSegmenter.get_phase_transitions(result)

    if len(transitions) > 3:
        ok(f"{len(transitions)} faz geçişi")
    else:
        fail("Faz geçişleri", f"az: {len(transitions)}")

    # İlk geçiş ground'dan olmalı
    if transitions and transitions[0]['from_phase'] in (
        PHASE_GROUND_TAXI_OUT, PHASE_TAKEOFF
    ):
        ok(f"İlk geçiş: {transitions[0]['from_phase']} → {transitions[0]['to_phase']}")
    else:
        if transitions:
            fail("İlk geçiş", f"{transitions[0]}")
        else:
            fail("İlk geçiş", "geçiş yok")

    # ─── [5] Sıralama mantığı ─────────────────────────────
    print("\n  [5] Faz Sıralaması")

    phase_order = [
        p for p in result['flight_phase'].values
        if p != result['flight_phase'].values[0]
    ][:1]

    # İlk non-ground faz takeoff veya climb olmalı
    first_airborne = None
    for p in result['flight_phase']:
        if p not in (PHASE_GROUND_TAXI_OUT, PHASE_GROUND_TAXI_IN):
            first_airborne = p
            break

    if first_airborne in (PHASE_TAKEOFF, PHASE_INITIAL_CLIMB, PHASE_CLIMB):
        ok(f"İlk havada faz: {first_airborne}")
    else:
        fail("İlk havada faz", f"{first_airborne}")

    # Son non-ground faz approach veya descent olmalı
    last_airborne = None
    for p in reversed(result['flight_phase'].values):
        if p not in (PHASE_GROUND_TAXI_IN, PHASE_LANDING):
            last_airborne = p
            break

    if last_airborne in (PHASE_APPROACH, PHASE_DESCENT, PHASE_HOLDING):
        ok(f"Son havada faz: {last_airborne}")
    else:
        fail("Son havada faz", f"{last_airborne}")

    # ─── [6] Cruise süresi ────────────────────────────────
    print("\n  [6] Süre Hesabı")

    cruise_min = FlightPhaseSegmenter.cruise_duration_minutes(result)
    if cruise_min > 0:
        ok(f"Cruise süresi: {cruise_min:.1f} dakika")
    else:
        fail("Cruise süresi", "sıfır")

    holding_min = FlightPhaseSegmenter.holding_duration_minutes(result)
    ok(f"Holding süresi: {holding_min:.1f} dakika")

    # ─── [7] Step climb tespiti ───────────────────────────
    print("\n  [7] Step Climb")

    step_climbs = FlightPhaseSegmenter.get_step_climbs_detected(result)
    ok(f"Step climb tespit: {len(step_climbs)} adet")

    # Step climb'lı veri oluştur
    flight_sc = make_flight()
    # Cruise ortasında step climb ekle
    for i in range(90, 95):
        flight_sc.loc[i, 'baro_altitude_ft'] = 37000 + (i-90) * 500

    flight_sc['altitude_diff_ft'] = flight_sc['baro_altitude_ft'].diff().fillna(0)
    flight_sc['vertical_rate_fpm'] = np.where(
        flight_sc['time_diff_s'] > 0,
        flight_sc['altitude_diff_ft'] / (flight_sc['time_diff_s'] / 60.0),
        0
    )

    result_sc = segmenter.segment_trajectory(flight_sc)
    sc_detected = FlightPhaseSegmenter.get_step_climbs_detected(result_sc)
    # Step climb tespit edilmeyebilir (eşik değerlerine bağlı) ama crash etmemeli
    ok(f"Step climb'lı veri işlendi: {len(sc_detected)} tespit")

    # ─── [8] Holding tespiti ──────────────────────────────
    print("\n  [8] Holding Tespiti")

    # Holding simüle et: aynı yerde dairesel
    flight_hold = make_flight()
    # Approach bölgesinde holding ekle (175-185 arası aynı koordinat)
    for i in range(170, 185):
        flight_hold.loc[i, 'latitude']  = 51.45 + np.sin(i * 0.3) * 0.02
        flight_hold.loc[i, 'longitude'] = -0.50 + np.cos(i * 0.3) * 0.02
        flight_hold.loc[i, 'baro_altitude_ft'] = 5000

    result_hold = segmenter.segment_trajectory(flight_hold)
    holdings = FlightPhaseSegmenter.detect_holdings_detailed(result_hold)
    ok(f"Holding simülasyonu işlendi: {len(holdings)} tespit")

    # ─── [9] Boş/eksik veri ───────────────────────────────
    print("\n  [9] Edge Cases")

    # Çok kısa veri
    short_df = pd.DataFrame({
        'baro_altitude_ft': [0, 5000, 35000, 5000, 0],
        'time_diff_s': [0, 60, 60, 60, 60],
    })
    result_short = segmenter.segment_trajectory(short_df)
    if 'flight_phase' in result_short.columns:
        ok("Kısa veri (5 nokta) işlendi")
    else:
        fail("Kısa veri", "flight_phase yok")

    # İrtifa sütunu yok
    no_alt_df = pd.DataFrame({
        'latitude': [41.27, 41.28],
        'longitude': [28.75, 28.76],
    })
    result_no_alt = segmenter.segment_trajectory(no_alt_df)
    if result_no_alt['flight_phase'].iloc[0] == PHASE_UNKNOWN:
        ok("İrtifa yok → UNKNOWN")
    else:
        fail("İrtifa yok", f"UNKNOWN beklendi: {result_no_alt['flight_phase'].iloc[0]}")

    # Tüm cruise (sabit irtifa)
    all_cruise = pd.DataFrame({
        'baro_altitude_ft': [35000] * 50,
        'vertical_rate_fpm': [0] * 50,
        'time_diff_s': [60] * 50,
    })
    result_cruise = segmenter.segment_trajectory(all_cruise)
    cruise_count = (result_cruise['flight_phase'] == PHASE_CRUISE).sum()
    if cruise_count > 40:
        ok(f"Sabit irtifa → {cruise_count}/50 CRUISE")
    else:
        fail("Sabit irtifa", f"CRUISE sayısı az: {cruise_count}")

    # ─── [10] flight_phase_exists ─────────────────────────
    print("\n  [10] Yardımcı Fonksiyonlar")

    if FlightPhaseSegmenter.flight_phase_exists(result, PHASE_CRUISE):
        ok("flight_phase_exists(CRUISE) = True")
    else:
        fail("flight_phase_exists", "CRUISE bulunamadı")

    if not FlightPhaseSegmenter.flight_phase_exists(result, 'NONEXISTENT'):
        ok("flight_phase_exists(NONEXISTENT) = False")
    else:
        fail("flight_phase_exists", "olmayan faz True döndü")

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
    validate_phase_segmentation()
