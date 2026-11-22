# src/analysis/benchmark.py

"""
GreenWing Analytics — Sonuç Doğrulama ve Benchmark Sistemi
═══════════════════════════════════════════════════════════

Bu dosya hesaplama sonuçlarının DOĞRU olup olmadığını
otomatik olarak kontrol eder.

NEDEN GEREKLİ:
──────────────
    "Sonuçlar doğru mu?" sorusunun OTOMATİK cevabı.
    Her seferinde elle kontrol etmek:
        • Zaman alıcı
        • Hata riski
        • Unutulabilir

    Benchmark sistemi otomatik kontrol eder:
        • SAR makul mü?
        • Fuel flow tipik aralıkta mı?
        • kg/Nm sektör normlarında mı?
        • Tasarruf yüzdesi gerçekçi mi?
        • Yıllık projeksiyon uçuk mu?
        • CO2/pax/km sektör ortalamasında mı?

NASIL ÇALIŞIR:
──────────────
    1. Hesaplama sonuçlarını al
    2. Referans değerlerle karşılaştır
    3. PASS / WARNING / FAIL üret
    4. Her sonuca açıklama ekle

    PASS    → Sonuç makul aralıkta
    WARNING → Sonuç aralığın kenarında, dikkat
    FAIL    → Sonuç fiziksel olarak şüpheli

KULLANIM:
─────────
    from src.analysis.benchmark import ResultBenchmark

    bm = ResultBenchmark()

    # Tek değer kontrolü
    result = bm.check_sar(0.097, 'B738')
    result = bm.check_fuel_estimate(12500, 1560, 'B738')

    # Toplu kontrol
    report = bm.check_all({
        'sar': 0.097,
        'fuel_kg': 12500,
        'distance_nm': 1560,
        'fuel_flow_kg_hr': 2500,
        'saving_pct': 2.5,
        'annual_saving_usd': 200000,
        'co2_per_pax_km_g': 87,
        'aircraft_type': 'B738',
    })

Kaynak:
───────
    IATA Fuel Efficiency Report
    ICAO emission benchmarks
    Eurocontrol Performance Review
    Sektör mühendislik deneyimi
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════
# SONUÇ NESNESİ
# ═══════════════════════════════════════════════════════════

@dataclass
class BenchmarkResult:
    """
    Benchmark kontrol sonucu.

    Attributes:
        check_name : Kontrol adı
        status     : 'PASS', 'WARNING', 'FAIL'
        value      : Kontrol edilen değer
        expected   : Beklenen aralık (metin)
        message    : Açıklama
    """
    check_name : str
    status     : str       # PASS, WARNING, FAIL
    value      : float
    expected   : str
    message    : str

    @property
    def is_pass(self) -> bool:
        return self.status == 'PASS'

    @property
    def is_warning(self) -> bool:
        return self.status == 'WARNING'

    @property
    def is_fail(self) -> bool:
        return self.status == 'FAIL'

    def __repr__(self) -> str:
        icon = {'PASS': '✅', 'WARNING': '⚠', 'FAIL': '❌'}.get(self.status, '?')
        return f"{icon} {self.check_name}: {self.status} ({self.value})"


@dataclass
class BenchmarkReport:
    """
    Toplu benchmark raporu.

    Attributes:
        results    : Tüm kontrol sonuçları
        pass_count : Geçen kontrol sayısı
        warn_count : Uyarı sayısı
        fail_count : Başarısız sayısı
    """
    results    : list[BenchmarkResult] = field(default_factory=list)
    pass_count : int = 0
    warn_count : int = 0
    fail_count : int = 0

    def add(self, result: BenchmarkResult) -> None:
        self.results.append(result)
        if result.status == 'PASS':
            self.pass_count += 1
        elif result.status == 'WARNING':
            self.warn_count += 1
        elif result.status == 'FAIL':
            self.fail_count += 1

    @property
    def is_all_pass(self) -> bool:
        return self.fail_count == 0 and self.warn_count == 0

    @property
    def has_failures(self) -> bool:
        return self.fail_count > 0

    @property
    def total(self) -> int:
        return len(self.results)

    def summary(self) -> str:
        icon = '✅' if self.is_all_pass else ('❌' if self.has_failures else '⚠')
        return (
            f"{icon} Benchmark: {self.pass_count} PASS, "
            f"{self.warn_count} WARNING, {self.fail_count} FAIL "
            f"(toplam {self.total})"
        )

    def print_report(self) -> None:
        print(f"\n{'─'*60}")
        print(f"  BENCHMARK RAPORU")
        print(f"{'─'*60}")
        for r in self.results:
            icon = {'PASS': '✅', 'WARNING': '⚠', 'FAIL': '❌'}.get(r.status, '?')
            print(f"  {icon} {r.check_name}: {r.message}")
        print(f"\n  {self.summary()}")
        print(f"{'─'*60}")

    def __repr__(self) -> str:
        return f"BenchmarkReport({self.summary()})"


# ═══════════════════════════════════════════════════════════
# REFERANS DEĞERLERİ
# ═══════════════════════════════════════════════════════════
# Kaynak: IATA, ICAO, Eurocontrol, sektör deneyimi
# Güncelleme: Yıllık (IATA raporu yayınlandığında)

# KAYNAK VE YÖNTEM
# ─────────────────
# Aralıklar, ICAO EDB/OpenAP yakıt modelinin (±%15 belirsizlik) fiziksel
# çıktısıdır. Her tip için:
#
#   SAR = TAS / FF ,  TAS = M·a(h),  FF = ICAO EDB eğrisi(r=D/T_SL)
#
# Referans noktası: FL350, W = OEW + 0.75·(MTOW − OEW).
#
# Bağımsız çapraz kontrol (B738): 460 kt / 2 640 kg/h = 0.174 Nm/kg.
# Gerçek dünya: B737-800 cruise FF 2 300–2 800 kg/h (yaygın operatör
# değerleri), yani 0.164–0.200 Nm/kg → model aralığı içinde ✓
#
# Menzil kontrolü (B738): 2 935 nm ferry / 20 894 kg yakıt = 0.140 Nm/kg
# (tüm yakıt doluyken ortalama); cruise SAR bunun üzerindedir — tutarlı.
#
# ⚠ ESKİ DEĞERLER HATALIYDI: 0.065–0.130 aralığı, gerçek değerin
# yaklaşık YARISIydı (10 kat değil, ama %50 düşük). Bu, benchmark'ın
# kendi modeliyle çelişmesine yol açıyordu (her uçuş FAIL).
# Hata kaynağı: değerler "tahmini" yazılmış, model çıktısıyla
# karşılaştırılmamış.
_SAR_RANGES: dict[str, tuple[float, float]] = {
    'B738': (0.134, 0.209),   # 0.1713 ±%22
    'B38M': (0.156, 0.244),   # 0.1997
    'A320': (0.131, 0.205),   # 0.1679
    'A20N': (0.201, 0.314),   # 0.2573
    'A321': (0.110, 0.172),   # 0.1408
    'A21N': (0.166, 0.260),   # 0.2128
    'B77W': (0.030, 0.047),   # 0.0385
    'B788': (0.059, 0.093),   # 0.0760
    'B789': (0.051, 0.079),   # 0.0650
    'A350': (0.044, 0.068),   # 0.0559
    'A380': (0.023, 0.036),   # 0.0292
    'DEFAULT': (0.020, 0.320),
}

_FUEL_FLOW_RANGES: dict[str, tuple[float, float]] = {
    'B738': (2061, 3223),     # 2642 ±%22
    'B38M': (1779, 2783),     # 2281
    'A320': (2089, 3267),     # 2678
    'A20N': (1363, 2132),     # 1748
    'A321': (2490, 3895),     # 3192
    'A21N': (1647, 2577),     # 2112
    'B77W': (9798, 15325),    # 12561
    'B788': (5031, 7869),     # 6450
    'B789': (5883, 9202),     # 7542
    'A350': (6841, 10701),    # 8771
    'A380': (13106, 20500),   # 16803
    'DEFAULT': (1000, 20000),
}

# ═══════════════════════════════════════════════════════════════
# FUEL PER NM — FİZİKSEL TÜRETME (2026-11-22 denetimi)
# ═══════════════════════════════════════════════════════════════
# ÖNCEKİ DURUM: aşağıdaki aralıklar ELLE yazılmıştı ve kaynağı yoktu.
# Ayrıca çok gevşekti: B738 için (6.0, 12.0) — 12 kg/nm, B738'in
# MTOW'daki tüketiminin (~7.5 kg/nm) çok üzerinde, yani hiçbir
# gerçek uçuş FAIL edemezdi. Alt sınır 6.0 ise gerçek 6.2'yi
# sınıra dayıyordu.
#
# DOĞRU YAKLAŞIM: kg/nm = 1 / SAR. Aynı fiziksel büyüklüğün tersi.
# Böylece TEK kaynak (OpenAP SAR aralıkları) iki kontrolü de besler
# ve iki tablo birbiriyle çelişemez.
#
# kg/nm alt = 1/SAR_üst,  kg/nm üst = 1/SAR_alt
# B738: 1/0.209 = 4.78  →  1/0.134 = 7.46   (gerçek 6.2 ✅ içinde)
# ═══════════════════════════════════════════════════════════════
_FUEL_PER_NM_RANGES: dict[str, tuple[float, float]] = {
    t: (round(1.0 / hi, 2), round(1.0 / lo, 2))
    for t, (lo, hi) in _SAR_RANGES.items()
}

_CO2_PER_PAX_KM_RANGE = (30, 250)  # g CO2/pax/km
_SAVING_PCT_RANGE     = (0, 15)    # % tek uçuşta
_ANNUAL_SAVING_RANGE  = (0, 5_000_000)  # $ tek rota


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class ResultBenchmark:
    """
    Hesaplama sonuçlarını sektör referanslarıyla karşılaştır.

    Her kontrol:
        PASS    → Değer normal aralıkta
        WARNING → Değer aralığın kenarında veya biraz dışında
        FAIL    → Değer fiziksel olarak şüpheli

    Kullanım:
        bm = ResultBenchmark()
        result = bm.check_sar(0.097, 'B738')
        report = bm.check_all({...})
    """

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: TEK DEĞER KONTROLLERİ
    # ──────────────────────────────────────────────────────

    @staticmethod
    def check_sar(
        sar_nm_per_kg: float,
        aircraft_type: str = 'DEFAULT',
    ) -> BenchmarkResult:
        """
        SAR değerini kontrol et.

        Args:
            sar_nm_per_kg: SAR değeri (Nm/kg)
            aircraft_type: ICAO uçak tipi

        Returns:
            BenchmarkResult
        """
        lo, hi = _SAR_RANGES.get(aircraft_type, _SAR_RANGES['DEFAULT'])

        if lo <= sar_nm_per_kg <= hi:
            return BenchmarkResult(
                'SAR', 'PASS', sar_nm_per_kg,
                f"[{lo}, {hi}] Nm/kg",
                f"SAR={sar_nm_per_kg:.5f} Nm/kg — {aircraft_type} için normal aralıkta.",
            )
        elif sar_nm_per_kg < lo * 0.7 or sar_nm_per_kg > hi * 1.3:
            return BenchmarkResult(
                'SAR', 'FAIL', sar_nm_per_kg,
                f"[{lo}, {hi}] Nm/kg",
                f"SAR={sar_nm_per_kg:.5f} Nm/kg — ÇOK ANORMAL. "
                f"Hesaplama veya girdi hatası olabilir.",
            )
        else:
            return BenchmarkResult(
                'SAR', 'WARNING', sar_nm_per_kg,
                f"[{lo}, {hi}] Nm/kg",
                f"SAR={sar_nm_per_kg:.5f} Nm/kg — tipik aralığın dışında. "
                f"Ağırlık veya irtifa kontrol edilmeli.",
            )

    @staticmethod
    def check_fuel_flow(
        fuel_flow_kg_hr: float,
        aircraft_type: str = 'DEFAULT',
    ) -> BenchmarkResult:
        """Cruise fuel flow kontrolü."""
        lo, hi = _FUEL_FLOW_RANGES.get(aircraft_type, _FUEL_FLOW_RANGES['DEFAULT'])

        if lo <= fuel_flow_kg_hr <= hi:
            return BenchmarkResult(
                'Fuel Flow', 'PASS', fuel_flow_kg_hr,
                f"[{lo}, {hi}] kg/hr",
                f"FF={fuel_flow_kg_hr:.0f} kg/hr — {aircraft_type} için normal.",
            )
        elif fuel_flow_kg_hr < lo * 0.5 or fuel_flow_kg_hr > hi * 1.5:
            return BenchmarkResult(
                'Fuel Flow', 'FAIL', fuel_flow_kg_hr,
                f"[{lo}, {hi}] kg/hr",
                f"FF={fuel_flow_kg_hr:.0f} kg/hr — ÇOK ANORMAL. "
                f"Model veya parametre hatası.",
            )
        else:
            return BenchmarkResult(
                'Fuel Flow', 'WARNING', fuel_flow_kg_hr,
                f"[{lo}, {hi}] kg/hr",
                f"FF={fuel_flow_kg_hr:.0f} kg/hr — tipik aralık dışında.",
            )

    @staticmethod
    def check_fuel_estimate(
        fuel_kg: float,
        distance_nm: float,
        aircraft_type: str = 'DEFAULT',
    ) -> BenchmarkResult:
        """Toplam yakıt tahmini kontrolü (kg/Nm metriği)."""

        if distance_nm <= 0:
            return BenchmarkResult(
                'Fuel Estimate', 'FAIL', 0,
                'distance > 0',
                'Mesafe sıfır veya negatif. Hesaplama yapılamaz.',
            )

        fuel_per_nm = fuel_kg / distance_nm
        lo, hi = _FUEL_PER_NM_RANGES.get(aircraft_type, _FUEL_PER_NM_RANGES['DEFAULT'])

        if lo <= fuel_per_nm <= hi:
            return BenchmarkResult(
                'Fuel Estimate', 'PASS', fuel_per_nm,
                f"[{lo}, {hi}] kg/Nm",
                f"{fuel_kg:,.0f} kg / {distance_nm:.0f} Nm = {fuel_per_nm:.2f} kg/Nm — normal.",
            )
        elif fuel_per_nm < lo * 0.5 or fuel_per_nm > hi * 1.5:
            return BenchmarkResult(
                'Fuel Estimate', 'FAIL', fuel_per_nm,
                f"[{lo}, {hi}] kg/Nm",
                f"{fuel_per_nm:.2f} kg/Nm — ÇOK ANORMAL. "
                f"Ağırlık, irtifa veya mesafe kontrolü gerekli.",
            )
        else:
            return BenchmarkResult(
                'Fuel Estimate', 'WARNING', fuel_per_nm,
                f"[{lo}, {hi}] kg/Nm",
                f"{fuel_per_nm:.2f} kg/Nm — tipik aralık dışında.",
            )

    @staticmethod
    def check_co2_per_pax_km(
        co2_per_pax_km_g: float,
    ) -> BenchmarkResult:
        """CO2/pax/km kontrolü."""
        lo, hi = _CO2_PER_PAX_KM_RANGE

        if lo <= co2_per_pax_km_g <= hi:
            return BenchmarkResult(
                'CO2/pax/km', 'PASS', co2_per_pax_km_g,
                f"[{lo}, {hi}] g",
                f"{co2_per_pax_km_g:.1f} g/pax/km — sektör normlarında.",
            )
        elif co2_per_pax_km_g < lo * 0.5 or co2_per_pax_km_g > hi * 1.3:
            return BenchmarkResult(
                'CO2/pax/km', 'FAIL', co2_per_pax_km_g,
                f"[{lo}, {hi}] g",
                f"{co2_per_pax_km_g:.1f} g/pax/km — ÇOK ANORMAL.",
            )
        else:
            return BenchmarkResult(
                'CO2/pax/km', 'WARNING', co2_per_pax_km_g,
                f"[{lo}, {hi}] g",
                f"{co2_per_pax_km_g:.1f} g/pax/km — aralık kenarında.",
            )

    @staticmethod
    def check_saving_percentage(
        saving_pct: float,
    ) -> BenchmarkResult:
        """Tasarruf yüzdesi kontrolü."""
        lo, hi = _SAVING_PCT_RANGE

        if lo <= saving_pct <= hi:
            return BenchmarkResult(
                'Saving %', 'PASS', saving_pct,
                f"[{lo}, {hi}]%",
                f"%{saving_pct:.1f} tasarruf — gerçekçi aralıkta.",
            )
        elif saving_pct > hi:
            return BenchmarkResult(
                'Saving %', 'WARNING' if saving_pct <= hi * 1.5 else 'FAIL',
                saving_pct,
                f"[{lo}, {hi}]%",
                f"%{saving_pct:.1f} tasarruf — {'çok yüksek, çift sayım?' if saving_pct > hi * 1.5 else 'yüksek, kontrol önerilir'}.",
            )
        else:
            return BenchmarkResult(
                'Saving %', 'WARNING', saving_pct,
                f"[{lo}, {hi}]%",
                f"%{saving_pct:.1f} tasarruf — negatif, mantık kontrol edilmeli.",
            )

    @staticmethod
    def check_annual_saving(
        annual_saving_usd: float,
    ) -> BenchmarkResult:
        """Yıllık tasarruf projeksiyon kontrolü."""
        lo, hi = _ANNUAL_SAVING_RANGE

        if lo <= annual_saving_usd <= hi:
            return BenchmarkResult(
                'Annual Saving', 'PASS', annual_saving_usd,
                f"[${lo:,}, ${hi:,}]",
                f"${annual_saving_usd:,.0f}/yıl — tek rota için makul.",
            )
        elif annual_saving_usd > hi:
            return BenchmarkResult(
                'Annual Saving',
                'WARNING' if annual_saving_usd <= hi * 2 else 'FAIL',
                annual_saving_usd,
                f"[${lo:,}, ${hi:,}]",
                f"${annual_saving_usd:,.0f}/yıl — "
                f"{'çok yüksek, gerçekleşme faktörü uygulandı mı?' if annual_saving_usd > hi * 2 else 'yüksek, kontrol önerilir'}.",
            )
        else:
            return BenchmarkResult(
                'Annual Saving', 'WARNING', annual_saving_usd,
                f"[${lo:,}, ${hi:,}]",
                f"${annual_saving_usd:,.0f}/yıl — negatif veya sıfır.",
            )

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: TOPLU KONTROL
    # ──────────────────────────────────────────────────────

    def check_all(self, results_dict: dict) -> BenchmarkReport:
        """
        Tüm kontrolleri tek seferde çalıştır.

        Args:
            results_dict: Kontrol edilecek değerler
                Desteklenen anahtarlar:
                    sar              : float (Nm/kg)
                    fuel_flow_kg_hr  : float (kg/hr)
                    fuel_kg          : float (kg)
                    distance_nm      : float (Nm)
                    co2_per_pax_km_g : float (g)
                    saving_pct       : float (%)
                    annual_saving_usd: float ($)
                    aircraft_type    : str

        Returns:
            BenchmarkReport: Toplu sonuç raporu

        Örnekler:
            report = bm.check_all({
                'sar': 0.097,
                'fuel_kg': 12500,
                'distance_nm': 1560,
                'fuel_flow_kg_hr': 2500,
                'saving_pct': 2.5,
                'annual_saving_usd': 200000,
                'co2_per_pax_km_g': 87.3,
                'aircraft_type': 'B738',
            })
            report.print_report()
        """
        report = BenchmarkReport()
        ac     = results_dict.get('aircraft_type', 'DEFAULT')

        # SAR
        if 'sar' in results_dict:
            report.add(self.check_sar(results_dict['sar'], ac))

        # Fuel flow
        if 'fuel_flow_kg_hr' in results_dict:
            report.add(self.check_fuel_flow(results_dict['fuel_flow_kg_hr'], ac))

        # Fuel estimate (kg/Nm)
        if 'fuel_kg' in results_dict and 'distance_nm' in results_dict:
            report.add(self.check_fuel_estimate(
                results_dict['fuel_kg'],
                results_dict['distance_nm'],
                ac,
            ))

        # CO2/pax/km
        if 'co2_per_pax_km_g' in results_dict:
            report.add(self.check_co2_per_pax_km(results_dict['co2_per_pax_km_g']))

        # Saving %
        if 'saving_pct' in results_dict:
            report.add(self.check_saving_percentage(results_dict['saving_pct']))

        # Annual saving
        if 'annual_saving_usd' in results_dict:
            report.add(self.check_annual_saving(results_dict['annual_saving_usd']))

        return report

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: YARDIMCI
    # ──────────────────────────────────────────────────────

    @staticmethod
    def get_reference_ranges(aircraft_type: str = 'DEFAULT') -> dict:
        """
        Belirli uçak tipi için referans aralıklarını döndür.

        Args:
            aircraft_type: ICAO uçak tipi

        Returns:
            dict: Tüm referans aralıkları
        """
        return {
            'sar_nm_per_kg'   : _SAR_RANGES.get(aircraft_type, _SAR_RANGES['DEFAULT']),
            'fuel_flow_kg_hr' : _FUEL_FLOW_RANGES.get(aircraft_type, _FUEL_FLOW_RANGES['DEFAULT']),
            'fuel_per_nm_kg'  : _FUEL_PER_NM_RANGES.get(aircraft_type, _FUEL_PER_NM_RANGES['DEFAULT']),
            'co2_per_pax_km_g': _CO2_PER_PAX_KM_RANGE,
            'saving_pct'      : _SAVING_PCT_RANGE,
            'annual_saving_usd': _ANNUAL_SAVING_RANGE,
        }

    def __repr__(self) -> str:
        return "ResultBenchmark()"


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_benchmark() -> bool:
    """
    Benchmark sistemi doğrulama testleri.

    Çalıştırma:
        python -m src.analysis.benchmark
    """
    print("\n" + "=" * 60)
    print("  BENCHMARK.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests = 0
    bm    = ResultBenchmark()

    def ok(name: str) -> None:
        nonlocal tests
        tests += 1
        print(f"  ✅ {name}")

    def fail(name: str, detail: str) -> None:
        nonlocal tests
        tests += 1
        errors.append(f"{name}: {detail}")
        print(f"  ❌ {name}: {detail}")

    # ─── [1] SAR kontrolü ─────────────────────────────────
    print("\n  [1] SAR Benchmark")

    r = bm.check_sar(0.097, 'B738')
    tests += 1
    if r.is_pass:
        ok(f"SAR 0.097 B738 → PASS")
    else:
        fail("SAR normal", f"{r.status}")

    r = bm.check_sar(0.01, 'B738')
    tests += 1
    if r.is_fail:
        ok("SAR 0.01 → FAIL (çok düşük)")
    else:
        fail("SAR düşük", f"{r.status}")

    r = bm.check_sar(0.30, 'B738')
    tests += 1
    if r.is_fail:
        ok("SAR 0.30 → FAIL (çok yüksek)")
    else:
        fail("SAR yüksek", f"{r.status}")

    r = bm.check_sar(0.060, 'B738')
    tests += 1
    if r.is_warning:
        ok("SAR 0.060 → WARNING (aralığın biraz altında)")
    else:
        fail("SAR kenar", f"{r.status}")

    # ─── [2] Fuel flow kontrolü ───────────────────────────
    print("\n  [2] Fuel Flow Benchmark")

    r = bm.check_fuel_flow(2500, 'B738')
    tests += 1
    if r.is_pass:
        ok("FF 2500 B738 → PASS")
    else:
        fail("FF normal", f"{r.status}")

    r = bm.check_fuel_flow(50, 'B738')
    tests += 1
    if r.is_fail:
        ok("FF 50 → FAIL (imkansız düşük)")
    else:
        fail("FF düşük", f"{r.status}")

    r = bm.check_fuel_flow(20000, 'B738')
    tests += 1
    if r.is_fail:
        ok("FF 20000 → FAIL (imkansız yüksek)")
    else:
        fail("FF yüksek", f"{r.status}")

    # ─── [3] Fuel estimate kontrolü ───────────────────────
    print("\n  [3] Fuel Estimate Benchmark")

    r = bm.check_fuel_estimate(12500, 1560, 'B738')
    tests += 1
    if r.is_pass:
        ok(f"12500 kg / 1560 Nm = {12500/1560:.2f} kg/Nm → PASS")
    else:
        fail("Fuel est normal", f"{r.status}")

    r = bm.check_fuel_estimate(1000, 1560, 'B738')
    tests += 1
    if r.is_fail:
        ok("1000 kg / 1560 Nm → FAIL (çok az)")
    else:
        fail("Fuel est düşük", f"{r.status}")

    r = bm.check_fuel_estimate(0, 0, 'B738')
    tests += 1
    if r.is_fail:
        ok("0 mesafe → FAIL")
    else:
        fail("Sıfır mesafe", f"{r.status}")

    # ─── [4] CO2/pax/km kontrolü ──────────────────────────
    print("\n  [4] CO2/pax/km Benchmark")

    r = bm.check_co2_per_pax_km(87.3)
    tests += 1
    if r.is_pass:
        ok("87.3 g → PASS")
    else:
        fail("CO2 normal", f"{r.status}")

    r = bm.check_co2_per_pax_km(5.0)
    tests += 1
    if r.is_fail:
        ok("5.0 g → FAIL (imkansız düşük)")
    else:
        fail("CO2 düşük", f"{r.status}")

    # ─── [5] Saving % kontrolü ────────────────────────────
    print("\n  [5] Saving % Benchmark")

    r = bm.check_saving_percentage(2.5)
    tests += 1
    if r.is_pass:
        ok("%2.5 → PASS")
    else:
        fail("Saving normal", f"{r.status}")

    r = bm.check_saving_percentage(25.0)
    tests += 1
    if r.is_fail:
        ok("%25 → FAIL (çok yüksek, çift sayım?)")
    else:
        fail("Saving yüksek", f"{r.status}")

    # ─── [6] Annual saving kontrolü ───────────────────────
    print("\n  [6] Annual Saving Benchmark")

    r = bm.check_annual_saving(200000)
    tests += 1
    if r.is_pass:
        ok("$200K → PASS")
    else:
        fail("Annual normal", f"{r.status}")

    r = bm.check_annual_saving(15_000_000)
    tests += 1
    if r.is_fail:
        ok("$15M → FAIL (çok yüksek)")
    else:
        fail("Annual yüksek", f"{r.status}")

    # ─── [7] Toplu kontrol ────────────────────────────────
    print("\n  [7] Toplu Kontrol (check_all)")

    report = bm.check_all({
        'sar'               : 0.097,
        'fuel_flow_kg_hr'   : 2500,
        'fuel_kg'           : 12500,
        'distance_nm'       : 1560,
        'co2_per_pax_km_g'  : 87.3,
        'saving_pct'        : 2.5,
        'annual_saving_usd' : 200000,
        'aircraft_type'     : 'B738',
    })

    tests += 1
    if report.total == 6:
        ok(f"6 kontrol çalıştı: {report.summary()}")
    else:
        fail("Kontrol sayısı", f"{report.total} ≠ 6")

    tests += 1
    if report.is_all_pass:
        ok("Tüm kontroller PASS (normal değerler)")
    else:
        fail("Toplu PASS", f"fail={report.fail_count}, warn={report.warn_count}")

    # Kötü değerlerle
    bad_report = bm.check_all({
        'sar': 0.005,
        'fuel_flow_kg_hr': 50,
        'fuel_kg': 500,
        'distance_nm': 1560,
        'annual_saving_usd': 20_000_000,
        'aircraft_type': 'B738',
    })

    tests += 1
    if bad_report.has_failures:
        ok(f"Kötü değerler → FAIL var: {bad_report.summary()}")
    else:
        fail("Kötü değerler", "FAIL beklendi")

    # ─── [8] Referans aralıkları ──────────────────────────
    print("\n  [8] Referans Aralıkları")

    refs = ResultBenchmark.get_reference_ranges('B738')
    tests += 1
    if 'sar_nm_per_kg' in refs and 'fuel_flow_kg_hr' in refs:
        ok(f"B738 referanslar: SAR={refs['sar_nm_per_kg']}, FF={refs['fuel_flow_kg_hr']}")
    else:
        fail("Referanslar", "eksik")

    refs_default = ResultBenchmark.get_reference_ranges('BILINMEYEN')
    tests += 1
    if refs_default['sar_nm_per_kg'] == _SAR_RANGES['DEFAULT']:
        ok("Bilinmeyen tip → DEFAULT referans")
    else:
        fail("DEFAULT", "yanlış")

    # ─── [9] Farklı uçak tipleri ──────────────────────────
    print("\n  [9] Farklı Uçak Tipleri")

    for ac in ['B77W', 'A350', 'A20N']:
        sar_range = _SAR_RANGES.get(ac, _SAR_RANGES['DEFAULT'])
        mid_sar   = (sar_range[0] + sar_range[1]) / 2
        r = bm.check_sar(mid_sar, ac)
        tests += 1
        if r.is_pass:
            ok(f"{ac} SAR {mid_sar:.4f} → PASS")
        else:
            fail(f"{ac} SAR", f"{r.status}")

    # ─── [10] print_report ────────────────────────────────
    print("\n  [10] Rapor Yazdırma")

    tests += 1
    try:
        report.print_report()
        ok("print_report çalışıyor")
    except Exception as e:
        fail("print_report", str(e))

    # ─── [11] repr ────────────────────────────────────────
    tests += 1
    r_repr = repr(bm)
    if 'ResultBenchmark' in r_repr:
        ok(f"repr: {r_repr}")
    else:
        fail("repr", r_repr)

    tests += 1
    rr_repr = repr(report)
    if 'BenchmarkReport' in rr_repr:
        ok(f"report repr: {rr_repr}")
    else:
        fail("report repr", rr_repr)

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
    validate_benchmark()
