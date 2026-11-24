# src/logging_config.py

"""
GreenWing Analytics — Hesaplama İzleme ve Kayıt Sistemi
════════════════════════════════════════════════════════

Bu dosya sistemin "kara kutusu"dur.

NEDEN GEREKLİ:
──────────────
Müşteri sorar: "Bu sonucu nasıl hesapladın?"
Havayolu sorar: "Hangi varsayımla $442 çıktı?"
Regülatör sorar: "CORSIA raporunun dayanağı nedir?"

Yanıt verebilmek için her hesap adımı kayıt altında olmalı.

BU DOSYA:
─────────
• Her analiz için benzersiz ID üretir
• Girdileri kaydeder (kaynak bilgisiyle birlikte)
• Varsayımları kaydeder (hata payıyla birlikte)
• Hesaplama adımlarını kaydeder (formül + değerler)
• Validasyon sonuçlarını kaydeder
• Belirsizlik değerlerini kaydeder
• Optimizasyon kararlarını kaydeder
• Uyarıları kaydeder
• Tam izi JSON olarak verebilir

KULLANIM:
─────────
    from src.logging_config import AnalysisTracer

    tracer = AnalysisTracer("PGT1234_LTFM_EGLL_20250120")

    tracer.log_input("weight_kg",     72000, "kg", "assumption:80%_load")
    tracer.log_input("altitude_ft",   35000, "ft", "opensky_adsb")
    tracer.log_assumption("payload",  15000, "kg", "150 pax × 100 kg", uncertainty_pct=15)
    tracer.log_step("cruise_fuel_flow",
                    formula="FF = SFC × Drag",
                    inputs={"SFC": 0.0000184, "Drag_N": 35420},
                    outputs={"fuel_flow_kg_hr": 2347})
    tracer.log_optimization("altitude", "FL380", reason="Max SAR, buffet marjı yeterli")
    tracer.log_warning("Buffet marjı düşük: %12.3")

    trace = tracer.get_trace()
    tracer.save_trace("reports/traces/PGT1234.json")
    tracer.print_summary()

TASARIM KARARLARI:
──────────────────
1. Her analiz kendi Tracer instance'ına sahip (thread-safe)
2. Kayıtlar sıralı ve zaman damgalı
3. JSON formatı (her araç açabilir)
4. Özet görünümü + detaylı iz ayrı
5. Performans: loglama asla hesabı yavaşlatmaz
   (sync, in-memory, lazy serialization)
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════
# VERSİYON
# ═══════════════════════════════════════════════════════════

_SYSTEM_VERSION = "1.0.0"


# ═══════════════════════════════════════════════════════════
# MERKEZİ LOGGER (modül bazlı loglama)
# ═══════════════════════════════════════════════════════════

import logging

def setup_logging(level: str = "INFO") -> None:
    """
    Kök log yapılandırmasını kur.

    DENETİM #92: `scripts/10_pre_real_ingestion_demo.py` bu fonksiyonu
    import ediyordu ama fonksiyon HİÇ YOKTU → script ImportError ile
    çöküyordu. Yani müşteri verisini alacak olan tek script çalışmıyordu
    ve bu, hiçbir test kapsamadığı için fark edilmemişti.

    Kullanım:
        from src.logging_config import setup_logging, get_logger
        setup_logging("INFO")
        logger = get_logger(__name__)
    """
    import sys as _sys
    lvl = getattr(logging, str(level).upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers:            # ikinci çağrıda çift handler olmasın
        root.setLevel(lvl)
        return
    h = logging.StreamHandler(_sys.stdout)
    h.setLevel(lvl)
    h.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(h)
    root.setLevel(lvl)


def get_logger(name: str) -> logging.Logger:
    """
    Merkezi logger factory.
    
    Tüm modüller bu fonksiyonu kullanarak logger alır.
    Aynı isimli logger birden fazla çağrılarda handler tekrarlanmaz.
    
    Format: [timestamp] [level] [module] message
    
    Args:
        name: Logger adı — genellikle modül adı
              ("ingestion.pipeline", "optimization.calibrator", vb.)
    
    Returns:
        logging.Logger: Yapılandırılmış logger instance
    
    Kullanım:
        from src.logging_config import get_logger
        logger = get_logger("ingestion.pipeline")
        logger.info("Pipeline başladı")
        logger.warning("Gate başarısız")
    """
    logger = logging.getLogger(name)
    
    # Handler tekrarlanmasın (aynı isimli logger'a birden fazla handler eklenmez)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    return logger


# ═══════════════════════════════════════════════════════════
# YARDIMCI: JSON SERİLEŞTİRME
# ═══════════════════════════════════════════════════════════

def _safe_serialize(obj: Any) -> Any:
    """
    JSON serileştirilemez tipleri güvenle dönüştür.

    numpy, pandas, datetime gibi tipler standart
    json.dumps ile serileştirilemez.
    Bu fonksiyon onları Python primitiflere çevirir.
    """
    # numpy scalar
    try:
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
    except ImportError:
        pass

    # pandas
    try:
        import pandas as pd
        if isinstance(obj, pd.Series):
            return obj.tolist()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict('records')
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except ImportError:
        pass

    # datetime
    if isinstance(obj, datetime):
        return obj.isoformat()

    # set
    if isinstance(obj, set):
        return list(obj)

    # Fallback: string
    return str(obj)


def _json_dumps(obj: Any, indent: int = 2) -> str:
    """JSON dumps with safe serialization."""
    return json.dumps(obj, default=_safe_serialize, indent=indent, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# ANA SINIF
# ═══════════════════════════════════════════════════════════

class AnalysisTracer:
    """
    GreenWing Analytics Hesaplama İz Kaydedici.

    Her analiz için tek bir instance oluştur.
    Tüm hesap adımlarını kaydet.
    Sonunda izi al veya dosyaya kaydet.

    Kullanım:
        tracer = AnalysisTracer("PGT1234_LTFM_EGLL_20250120")
        # ... hesaplamalar ...
        tracer.save_trace("reports/traces/PGT1234.json")
    """

    def __init__(
        self,
        analysis_id: Optional[str] = None,
        description: str = "",
    ) -> None:
        """
        Args:
            analysis_id : Benzersiz analiz kimliği. None → otomatik UUID.
            description : Kısa açıklama (uçuş no, rota, tarih vb.)
        """
        self._id          = analysis_id or str(uuid.uuid4())[:12]
        self._description = description
        self._started_at  = datetime.now(timezone.utc).isoformat()
        self._version     = _SYSTEM_VERSION

        # Kayıt listeleri — sıralı
        self._inputs        : list[dict] = []
        self._assumptions   : list[dict] = []
        self._steps         : list[dict] = []
        self._validations   : list[dict] = []
        self._uncertainties : list[dict] = []
        self._optimizations : list[dict] = []
        self._warnings      : list[dict] = []

        # Özet istatistikler
        self._warning_count   = 0
        self._step_count      = 0
        self._error_count     = 0

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: GİRDİ KAYDI
    # ──────────────────────────────────────────────────────

    def log_input(
        self,
        name: str,
        value: Any,
        unit: str = "",
        source: str = "unknown",
        note: str = "",
    ) -> None:
        """
        Analiz girdisini kaydet.

        Args:
            name  : Parametre adı ('weight_kg', 'altitude_ft', ...)
            value : Değer
            unit  : Birim ('kg', 'ft', 'm/s', ...)
            source: Veri kaynağı
                    'opensky_adsb'     → ADS-B verisi
                    'assumption'       → config/assumptions.py
                    'customer_data'    → Müşteri sağladı
                    'calibration'      → Model kalibrasyon sonucu
                    'calculated'       → Başka değerden hesaplandı
                    'user_input'       → Manuel girildi
            note  : Ek açıklama

        Örnekler:
            tracer.log_input("weight_kg",   72000, "kg", "assumption:80%_load")
            tracer.log_input("altitude_ft", 35000, "ft", "opensky_adsb")
            tracer.log_input("fuel_price",  0.78,  "USD/kg", "assumption")
            tracer.log_input("oew_kg",      42800, "kg", "customer_data",
                             "Müşteri weight & balance dokümanından")
        """
        self._inputs.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'name'     : name,
            'value'    : _safe_serialize(value),
            'unit'     : unit,
            'source'   : source,
            'note'     : note,
        })

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: VARSAYIM KAYDI
    # ──────────────────────────────────────────────────────

    def log_assumption(
        self,
        name: str,
        value: Any,
        unit: str = "",
        rationale: str = "",
        uncertainty_pct: float = 0.0,
        can_override: bool = True,
    ) -> None:
        """
        Kullanılan varsayımı kaydet.

        Varsayım = gerçek verisi olmadığı için tahmin edilen değer.
        Her varsayım hata payıyla birlikte kaydedilmeli.

        Args:
            name           : Varsayım adı
            value          : Kullanılan değer
            unit           : Birim
            rationale      : Neden bu değer? Açıklama.
            uncertainty_pct: Tahmini hata payı (%)
            can_override   : Müşteri gerçek değer verebilir mi?

        Örnekler:
            tracer.log_assumption(
                "payload_kg", 15000, "kg",
                "150 pax × 100 kg, %80 doluluk varsayımı",
                uncertainty_pct=15.0
            )
            tracer.log_assumption(
                "fuel_price_ltfm", 0.78, "USD/kg",
                "2025-Q1 piyasa tahmini. Müşteri kontrat fiyatı farklı olabilir.",
                uncertainty_pct=10.0
            )
            tracer.log_assumption(
                "realization_factor", 0.65, "",
                "%65 gerçekleşme. ATC/hava durumu/slot kısıtları nedeniyle.",
                uncertainty_pct=15.0
            )
        """
        self._assumptions.append({
            'timestamp'      : datetime.now(timezone.utc).isoformat(),
            'name'           : name,
            'value'          : _safe_serialize(value),
            'unit'           : unit,
            'rationale'      : rationale,
            'uncertainty_pct': uncertainty_pct,
            'can_override'   : can_override,
        })

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: HESAPLAMA ADIMI KAYDI
    # ──────────────────────────────────────────────────────

    def log_step(
        self,
        step_name: str,
        formula: str,
        inputs: dict,
        outputs: dict,
        module: str = "",
        note: str = "",
    ) -> None:
        """
        Hesaplama adımını kaydet.

        "Bu sonucu nasıl hesapladın?" sorusunun cevabı buradadır.
        Her önemli hesap adımı kaydedilmeli.

        Args:
            step_name: Adım adı ('cruise_fuel_flow', 'sar_calculation', ...)
            formula  : Kullanılan formül (metin olarak)
            inputs   : Giriş değerleri {isim: değer}
            outputs  : Çıkış değerleri {isim: değer}
            module   : Kaynak modül adı ('fuel_model', 'atmosphere', ...)
            note     : Ek açıklama

        Örnekler:
            tracer.log_step(
                step_name="cruise_fuel_flow",
                formula="FF = SFC × Drag",
                inputs={"SFC_kg_Ns": 0.0000184, "Drag_N": 35420},
                outputs={"fuel_flow_kg_s": 0.652, "fuel_flow_kg_hr": 2347},
                module="fuel_model"
            )
            tracer.log_step(
                step_name="specific_air_range",
                formula="SAR = TAS / Fuel_Flow",
                inputs={"TAS_ms": 229.6, "fuel_flow_kg_s": 0.652},
                outputs={"SAR_nm_per_kg": 0.0967},
                module="fuel_model"
            )
            tracer.log_step(
                step_name="annual_projection",
                formula="annual = per_flight × daily_flights × op_days × RF",
                inputs={
                    "per_flight_usd": 442,
                    "daily_flights": 2,
                    "operational_days": 345,
                    "realization_factor": 0.65,
                },
                outputs={
                    "raw_annual_usd": 305160,
                    "realistic_annual_usd": 198354,
                },
                module="assumptions"
            )
        """
        self._step_count += 1
        self._steps.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'step_no'  : self._step_count,
            'step_name': step_name,
            'formula'  : formula,
            'inputs'   : {k: _safe_serialize(v) for k, v in inputs.items()},
            'outputs'  : {k: _safe_serialize(v) for k, v in outputs.items()},
            'module'   : module,
            'note'     : note,
        })

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: VALİDASYON KAYDI
    # ──────────────────────────────────────────────────────

    def log_validation(
        self,
        validator: str,
        check_name: str,
        result: str,
        value: Any = None,
        expected_range: str = "",
        detail: str = "",
    ) -> None:
        """
        Doğrulama kontrolünü kaydet.

        Args:
            validator    : Validatör adı ('DataValidator', 'PhysicsValidator', ...)
            check_name   : Kontrol adı ('CL_range', 'SAR_range', 'MTOW_check', ...)
            result       : 'PASS', 'WARNING' veya 'FAIL'
            value        : Kontrol edilen değer
            expected_range: Beklenen aralık ('0.08-0.12 Nm/kg' gibi)
            detail       : Açıklama

        Örnekler:
            tracer.log_validation(
                "PhysicsValidator", "CL_range", "PASS",
                value=0.498, expected_range="[0.01, 1.5]",
                detail="CL=0.498, normal cruise aralığında"
            )
            tracer.log_validation(
                "BusinessValidator", "SAR_range", "WARNING",
                value=0.155, expected_range="[0.03, 0.20]",
                detail="SAR yüksek, hafif uçak veya düşük irtifa olabilir"
            )
            tracer.log_validation(
                "BusinessValidator", "MTOW_check", "FAIL",
                value=80500, expected_range="≤ 79016 kg",
                detail="Tankering ile MTOW aşılıyor! 2000 kg azalt."
            )
        """
        if result == 'FAIL':
            self._error_count += 1
        elif result == 'WARNING':
            self._warning_count += 1

        self._validations.append({
            'timestamp'     : datetime.now(timezone.utc).isoformat(),
            'validator'     : validator,
            'check_name'    : check_name,
            'result'        : result,
            'value'         : _safe_serialize(value),
            'expected_range': expected_range,
            'detail'        : detail,
        })

    # ──────────────────────────────────────────────────────
    # BÖLÜM 5: BELİRSİZLİK KAYDI
    # ──────────────────────────────────────────────────────

    def log_uncertainty(
        self,
        parameter: str,
        value: float,
        uncertainty_pct: float,
        source: str,
        propagated_from: Optional[list[str]] = None,
    ) -> None:
        """
        Belirsizlik değerini kaydet.

        "Bu sonuç ±kaç?" sorusunun cevabı buradadır.

        Args:
            parameter      : Parametre adı
            value          : Merkez değer
            uncertainty_pct: Belirsizlik yüzdesi
            source         : Belirsizlik kaynağı açıklaması
            propagated_from: Hangi parametrelerden yayıldı?

        Örnekler:
            tracer.log_uncertainty(
                "estimated_fuel_kg", 12450, 8.0,
                "Ağırlık varsayımından ±5% + SFC varsayımından ±3%",
                propagated_from=["weight_kg", "sfc_factor"]
            )
            tracer.log_uncertainty(
                "annual_saving_usd", 198354, 22.0,
                "Yakıt tahmini ±8% + gerçekleşme faktörü ±15%",
                propagated_from=["estimated_fuel_kg", "realization_factor"]
            )
        """
        self._uncertainties.append({
            'timestamp'      : datetime.now(timezone.utc).isoformat(),
            'parameter'      : parameter,
            'value'          : _safe_serialize(value),
            'uncertainty_pct': uncertainty_pct,
            'lower_bound'    : _safe_serialize(value * (1 - uncertainty_pct / 100)),
            'upper_bound'    : _safe_serialize(value * (1 + uncertainty_pct / 100)),
            'source'         : source,
            'propagated_from': propagated_from or [],
        })

    # ──────────────────────────────────────────────────────
    # BÖLÜM 6: OPTİMİZASYON KAYDI
    # ──────────────────────────────────────────────────────

    def log_optimization(
        self,
        opt_type: str,
        selected: str,
        reason: str,
        alternatives: Optional[dict] = None,
        constraints_applied: Optional[list[str]] = None,
        saving_kg: float = 0.0,
        saving_usd: float = 0.0,
    ) -> None:
        """
        Optimizasyon kararını kaydet.

        "Neden FL380 önerildi?" gibi sorulara cevap.

        Args:
            opt_type           : Optimizasyon tipi
                                 'altitude', 'step_climb', 'cost_index',
                                 'tankering', 'route', 'holding'
            selected           : Seçilen değer ('FL380', 'CI=35', ...)
            reason             : Seçim gerekçesi
            alternatives       : Değerlendirilen alternatifler {seçenek: SAR/değer}
            constraints_applied: Uygulanan kısıtlar listesi
            saving_kg          : Bu kararla elde edilen yakıt tasarrufu (kg)
            saving_usd         : Bu kararla elde edilen maliyet tasarrufu (USD)

        Örnekler:
            tracer.log_optimization(
                opt_type="altitude",
                selected="FL380",
                reason="Max Ground SAR. Rüzgar etkisi dahil FL380 en iyi.",
                alternatives={
                    "FL360": 0.0951, "FL370": 0.0968,
                    "FL380": 0.0972, "FL390": 0.0964
                },
                constraints_applied=[
                    "RVSM westbound: çift FL",
                    "Buffet marjı > %10: FL380 sınırda (%12.3)",
                    "Max altitude B738: FL410"
                ],
                saving_kg=180, saving_usd=153
            )
            tracer.log_optimization(
                opt_type="step_climb",
                selected="FL350 → FL370 @ 400 Nm, FL370 → FL390 @ 900 Nm",
                reason="Ağırlık azaldıkça optimum irtifa yükseliyor.",
                saving_kg=145, saving_usd=123
            )
            tracer.log_optimization(
                opt_type="tankering",
                selected="2000 kg ekstra",
                reason="IST $0.78/kg, LON $1.05/kg. Fark $0.27/kg. CF=%12.",
                saving_kg=0, saving_usd=168
            )
        """
        self._optimizations.append({
            'timestamp'          : datetime.now(timezone.utc).isoformat(),
            'opt_type'           : opt_type,
            'selected'           : selected,
            'reason'             : reason,
            'alternatives'       : {
                k: _safe_serialize(v)
                for k, v in (alternatives or {}).items()
            },
            'constraints_applied': constraints_applied or [],
            'saving_kg'          : saving_kg,
            'saving_usd'         : saving_usd,
        })

    # ──────────────────────────────────────────────────────
    # BÖLÜM 7: UYARI KAYDI
    # ──────────────────────────────────────────────────────

    def log_warning(
        self,
        message: str,
        severity: str = "WARNING",
        module: str = "",
        action_required: bool = False,
    ) -> None:
        """
        Uyarı kaydı.

        Args:
            message        : Uyarı mesajı
            severity       : 'INFO', 'WARNING', 'CRITICAL'
            module         : Kaynak modül
            action_required: Müşterinin aksiyon alması gerekiyor mu?

        Örnekler:
            tracer.log_warning("Buffet marjı düşük: %12.3. Turbülansta dikkat.")
            tracer.log_warning(
                "realization_factor override yok, varsayılan 0.65 kullanılıyor.",
                severity="INFO"
            )
            tracer.log_warning(
                "MTOW sınırına yakın: 78,950 / 79,016 kg.",
                severity="CRITICAL",
                action_required=True
            )
        """
        self._warning_count += 1
        self._warnings.append({
            'timestamp'      : datetime.now(timezone.utc).isoformat(),
            'message'        : message,
            'severity'       : severity,
            'module'         : module,
            'action_required': action_required,
        })

    # ──────────────────────────────────────────────────────
    # BÖLÜM 8: İZ ÇIKTI METODLARI
    # ──────────────────────────────────────────────────────

    def get_trace(self) -> dict:
        """
        Tam analiz izini dict olarak döndür.

        Returns:
            dict: Tüm kayıtlar, özet bilgiler

        Kullanım:
            trace = tracer.get_trace()
            # JSON'a çevir
            import json
            print(json.dumps(trace, indent=2))
        """
        return {
            'meta': {
                'analysis_id'  : self._id,
                'description'  : self._description,
                'system_version': self._version,
                'started_at'   : self._started_at,
                'completed_at' : datetime.now(timezone.utc).isoformat(),
            },
            'summary': {
                'total_inputs'        : len(self._inputs),
                'total_assumptions'   : len(self._assumptions),
                'total_steps'         : self._step_count,
                'total_validations'   : len(self._validations),
                'total_uncertainties' : len(self._uncertainties),
                'total_optimizations' : len(self._optimizations),
                'total_warnings'      : self._warning_count,
                'total_errors'        : self._error_count,
                'has_fails'           : self._error_count > 0,
            },
            'inputs'        : self._inputs,
            'assumptions'   : self._assumptions,
            'steps'         : self._steps,
            'validations'   : self._validations,
            'uncertainties' : self._uncertainties,
            'optimizations' : self._optimizations,
            'warnings'      : self._warnings,
        }

    def save_trace(self, filepath: str) -> str:
        """
        İzi JSON dosyasına kaydet.

        Args:
            filepath: Dosya yolu (klasör yoksa oluşturulur)

        Returns:
            str: Kaydedilen dosyanın tam yolu

        Kullanım:
            path = tracer.save_trace("reports/traces/PGT1234.json")
            print(f"Kaydedildi: {path}")
        """
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

        trace = self.get_trace()
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(_json_dumps(trace))

        return os.path.abspath(filepath)

    def get_trace_json(self) -> str:
        """
        İzi JSON string olarak döndür.

        Returns:
            str: JSON formatında iz
        """
        return _json_dumps(self.get_trace())

    def print_summary(self) -> None:
        """
        İzin kısa özetini ekrana yaz.
        Hızlı kontrol için kullanılır.
        """
        trace = self.get_trace()
        meta  = trace['meta']
        summ  = trace['summary']

        print(f"\n{'─' * 60}")
        print(f"  ANALİZ İZİ ÖZETİ")
        print(f"{'─' * 60}")
        print(f"  ID         : {meta['analysis_id']}")
        if meta['description']:
            print(f"  Açıklama   : {meta['description']}")
        print(f"  Başlangıç  : {meta['started_at'][:19]}")
        print(f"  Sistem     : v{meta['system_version']}")
        print(f"{'─' * 60}")
        print(f"  Girdi      : {summ['total_inputs']}")
        print(f"  Varsayım   : {summ['total_assumptions']}")
        print(f"  Hesap adımı: {summ['total_steps']}")
        print(f"  Validasyon : {summ['total_validations']}")
        print(f"  Belirsizlik: {summ['total_uncertainties']}")
        print(f"  Optimizasyon:{summ['total_optimizations']}")
        print(f"  Uyarı      : {summ['total_warnings']}")

        if summ['total_errors'] > 0:
            print(f"\n  ❌ {summ['total_errors']} HATA VAR!")
        elif summ['total_warnings'] > 0:
            print(f"\n  ⚠  {summ['total_warnings']} uyarı")
        else:
            print(f"\n  ✅ Sorun yok")

        # Varsayımları göster
        if self._assumptions:
            print(f"\n  VARSAYIMLAR:")
            for a in self._assumptions:
                unc = f"±{a['uncertainty_pct']}%" if a['uncertainty_pct'] else ""
                print(f"    {a['name']}: {a['value']} {a['unit']} {unc}")

        # Uyarıları göster
        if self._warnings:
            print(f"\n  UYARILAR:")
            for w in self._warnings:
                icon = "❌" if w['severity'] == 'CRITICAL' else "⚠"
                print(f"    {icon} {w['message']}")

        # Optimizasyon kararlarını göster
        if self._optimizations:
            print(f"\n  OPTİMİZASYON KARARLARI:")
            for o in self._optimizations:
                saving_info = ""
                if o['saving_kg'] or o['saving_usd']:
                    saving_info = (
                        f" → {o['saving_kg']:.0f} kg, "
                        f"${o['saving_usd']:.0f}"
                    )
                print(f"    [{o['opt_type']}] {o['selected']}{saving_info}")

        print(f"{'─' * 60}\n")

    def get_assumptions_report(self) -> str:
        """
        Tüm varsayımların okunabilir raporu.

        Returns:
            str: Metin raporu

        Kullanım:
            print(tracer.get_assumptions_report())
        """
        if not self._assumptions:
            return "Hiç varsayım kaydedilmedi."

        lines = [
            "KULLANILAN VARSAYIMLAR:",
            "=" * 50,
        ]

        total_max_uncertainty = 0.0
        for a in self._assumptions:
            unc = a['uncertainty_pct']
            if unc > total_max_uncertainty:
                total_max_uncertainty = unc
            lines.append(
                f"\n• {a['name']}: {a['value']} {a['unit']}"
            )
            if unc > 0:
                lines.append(f"  Hata payı : ±{unc}%")
            if a['rationale']:
                lines.append(f"  Gerekçe   : {a['rationale']}")
            if a['can_override']:
                lines.append(f"  Not       : Müşteri verisiyle güncellenebilir")

        lines.append(f"\n{'─' * 50}")
        lines.append(
            f"Maksimum belirsizlik: ±{total_max_uncertainty:.1f}% "
            f"(gerçek veri ile büyük ölçüde azaltılabilir)"
        )

        return "\n".join(lines)

    def get_validation_report(self) -> str:
        """
        Tüm validasyon sonuçlarının raporu.

        Returns:
            str: Metin raporu
        """
        if not self._validations:
            return "Hiç validasyon kaydedilmedi."

        pass_count = sum(1 for v in self._validations if v['result'] == 'PASS')
        warn_count = sum(1 for v in self._validations if v['result'] == 'WARNING')
        fail_count = sum(1 for v in self._validations if v['result'] == 'FAIL')

        lines = [
            "VALİDASYON SONUÇLARI:",
            "=" * 50,
            f"PASS: {pass_count}  WARNING: {warn_count}  FAIL: {fail_count}",
            "─" * 50,
        ]

        for v in self._validations:
            icon = {'PASS': '✅', 'WARNING': '⚠', 'FAIL': '❌'}.get(v['result'], '?')
            lines.append(
                f"{icon} [{v['validator']}] {v['check_name']}: {v['result']}"
            )
            if v['value'] is not None:
                lines.append(f"   Değer: {v['value']} {v['expected_range']}")
            if v['detail']:
                lines.append(f"   Detay: {v['detail']}")

        return "\n".join(lines)

    def get_uncertainty_summary(self) -> dict:
        """
        Belirsizlik özeti.

        Returns:
            dict:
                max_uncertainty_pct: En yüksek belirsizlik
                dominant_source    : En büyük belirsizlik kaynağı
                uncertainties      : Tüm liste
        """
        if not self._uncertainties:
            return {
                'max_uncertainty_pct': 0.0,
                'dominant_source'    : 'Belirsizlik kaydı yok',
                'uncertainties'      : [],
            }

        sorted_unc = sorted(
            self._uncertainties,
            key=lambda x: x['uncertainty_pct'],
            reverse=True,
        )

        return {
            'max_uncertainty_pct': sorted_unc[0]['uncertainty_pct'],
            'dominant_source'    : sorted_unc[0]['source'],
            'dominant_parameter' : sorted_unc[0]['parameter'],
            'uncertainties'      : sorted_unc,
        }

    # ──────────────────────────────────────────────────────
    # BÖLÜM 9: YARDIMCI ÖZELLİKLER
    # ──────────────────────────────────────────────────────

    @property
    def analysis_id(self) -> str:
        """Analiz kimliği."""
        return self._id

    @property
    def has_errors(self) -> bool:
        """FAIL sonuçlu validasyon var mı?"""
        return self._error_count > 0

    @property
    def has_warnings(self) -> bool:
        """WARNING var mı?"""
        return self._warning_count > 0

    @property
    def step_count(self) -> int:
        """Toplam hesaplama adımı sayısı."""
        return self._step_count

    def __repr__(self) -> str:
        return (
            f"AnalysisTracer("
            f"id={self._id!r}, "
            f"steps={self._step_count}, "
            f"warnings={self._warning_count}, "
            f"errors={self._error_count})"
        )


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════

def validate_logging_config() -> bool:
    """
    AnalysisTracer'ın doğru çalıştığını kontrol et.

    Çalıştırma:
        python -m src.logging_config
    """
    import tempfile

    print("\n" + "=" * 60)
    print("  LOGGING_CONFIG.PY — DOĞRULAMA TESTLERİ")
    print("=" * 60)

    errors: list[str] = []
    tests  = 0

    # ─── [1] Temel oluşturma ──────────────────────────────
    print("\n  [1] Temel Oluşturma")

    tests += 1
    tracer = AnalysisTracer("TEST_001", "Doğrulama testi")
    if tracer.analysis_id == "TEST_001":
        print("  ✅ Tracer oluşturuldu")
    else:
        errors.append("Tracer ID yanlış")
        print("  ❌ Tracer ID yanlış")

    tests += 1
    tracer_auto = AnalysisTracer()
    if len(tracer_auto.analysis_id) > 0:
        print(f"  ✅ Otomatik ID: {tracer_auto.analysis_id}")
    else:
        errors.append("Otomatik ID boş")
        print("  ❌ Otomatik ID boş")

    # ─── [2] log_input ────────────────────────────────────
    print("\n  [2] Girdi Kaydı")

    tracer.log_input("weight_kg",   72000,  "kg",     "assumption:80%_load")
    tracer.log_input("altitude_ft", 35000,  "ft",     "opensky_adsb")
    tracer.log_input("mach",        0.785,  "",       "aircraft_database")
    tracer.log_input("fuel_price",  0.78,   "USD/kg", "assumption",
                     "2025-Q1 tahmini")

    tests += 1
    if len(tracer._inputs) == 4:
        print(f"  ✅ 4 girdi kaydedildi")
    else:
        errors.append(f"Girdi sayısı yanlış: {len(tracer._inputs)}")
        print(f"  ❌ Girdi sayısı: {len(tracer._inputs)}")

    tests += 1
    inp = tracer._inputs[0]
    if inp['name'] == 'weight_kg' and inp['value'] == 72000 and inp['source'] == 'assumption:80%_load':
        print("  ✅ Girdi içeriği doğru")
    else:
        errors.append(f"Girdi içeriği yanlış: {inp}")
        print("  ❌ Girdi içeriği yanlış")

    # ─── [3] log_assumption ───────────────────────────────
    print("\n  [3] Varsayım Kaydı")

    tracer.log_assumption(
        "payload_kg", 15000, "kg",
        "150 pax × 100 kg, %80 doluluk",
        uncertainty_pct=15.0
    )
    tracer.log_assumption(
        "realization_factor", 0.65, "",
        "%65 gerçekleşme varsayımı",
        uncertainty_pct=15.0
    )

    tests += 1
    if len(tracer._assumptions) == 2:
        print("  ✅ 2 varsayım kaydedildi")
    else:
        errors.append(f"Varsayım sayısı: {len(tracer._assumptions)}")
        print(f"  ❌ Varsayım sayısı: {len(tracer._assumptions)}")

    tests += 1
    asm = tracer._assumptions[0]
    if asm['uncertainty_pct'] == 15.0 and asm['can_override']:
        print("  ✅ Varsayım içeriği doğru")
    else:
        errors.append("Varsayım içeriği yanlış")
        print("  ❌ Varsayım içeriği yanlış")

    # ─── [4] log_step ─────────────────────────────────────
    print("\n  [4] Hesaplama Adımı Kaydı")

    tracer.log_step(
        "cruise_fuel_flow",
        formula="FF = SFC × Drag",
        inputs={"SFC_kg_Ns": 0.0000184, "Drag_N": 35420},
        outputs={"fuel_flow_kg_s": 0.652, "fuel_flow_kg_hr": 2347},
        module="fuel_model"
    )
    tracer.log_step(
        "specific_air_range",
        formula="SAR = TAS / FF",
        inputs={"TAS_ms": 229.6, "FF_kg_s": 0.652},
        outputs={"SAR_nm_per_kg": 0.0967},
        module="fuel_model"
    )
    tracer.log_step(
        "annual_projection",
        formula="annual = per_flight × daily × op_days × RF",
        inputs={
            "per_flight_usd": 442,
            "daily_flights": 2,
            "op_days": 345,
            "RF": 0.65
        },
        outputs={
            "raw_annual": 305160,
            "realistic_annual": 198354
        },
        module="assumptions"
    )

    tests += 1
    if tracer.step_count == 3:
        print(f"  ✅ 3 hesaplama adımı kaydedildi")
    else:
        errors.append(f"Adım sayısı yanlış: {tracer.step_count}")
        print(f"  ❌ Adım sayısı: {tracer.step_count}")

    tests += 1
    step = tracer._steps[0]
    if step['step_no'] == 1 and 'formula' in step and 'inputs' in step:
        print("  ✅ Adım içeriği doğru")
    else:
        errors.append(f"Adım içeriği yanlış: {step}")
        print("  ❌ Adım içeriği yanlış")

    # ─── [5] log_validation ───────────────────────────────
    print("\n  [5] Validasyon Kaydı")

    tracer.log_validation(
        "PhysicsValidator", "CL_range", "PASS",
        value=0.498, expected_range="[0.01, 1.5]",
        detail="Normal cruise CL"
    )
    tracer.log_validation(
        "BusinessValidator", "buffet_margin", "WARNING",
        value=12.3, expected_range=">15%",
        detail="Düşük buffet marjı"
    )
    tracer.log_validation(
        "BusinessValidator", "MTOW_check", "FAIL",
        value=80500, expected_range="≤79016",
        detail="MTOW aşıldı!"
    )

    tests += 1
    if len(tracer._validations) == 3:
        print("  ✅ 3 validasyon kaydedildi")
    else:
        errors.append(f"Validasyon sayısı: {len(tracer._validations)}")
        print(f"  ❌ Validasyon sayısı: {len(tracer._validations)}")

    tests += 1
    if tracer.has_errors and tracer.has_warnings:
        print("  ✅ has_errors ve has_warnings doğru")
    else:
        errors.append("has_errors veya has_warnings yanlış")
        print("  ❌ has_errors/has_warnings yanlış")

    tests += 1
    if tracer._error_count == 1 and tracer._warning_count >= 1:
        print(f"  ✅ Sayaçlar doğru: errors={tracer._error_count}, warnings={tracer._warning_count}")
    else:
        errors.append(f"Sayaçlar yanlış: e={tracer._error_count}, w={tracer._warning_count}")
        print("  ❌ Sayaçlar yanlış")

    # ─── [6] log_uncertainty ──────────────────────────────
    print("\n  [6] Belirsizlik Kaydı")

    tracer.log_uncertainty(
        "estimated_fuel_kg", 12450, 8.0,
        "Ağırlık varsayımı ±5% + SFC varsayımı ±3%",
        propagated_from=["weight_kg", "sfc_factor"]
    )
    tracer.log_uncertainty(
        "annual_saving_usd", 198354, 22.0,
        "Yakıt tahmini ±8% + RF ±15%",
        propagated_from=["estimated_fuel_kg", "realization_factor"]
    )

    tests += 1
    if len(tracer._uncertainties) == 2:
        print("  ✅ 2 belirsizlik kaydedildi")
    else:
        errors.append(f"Belirsizlik sayısı: {len(tracer._uncertainties)}")
        print(f"  ❌ Belirsizlik sayısı: {len(tracer._uncertainties)}")

    tests += 1
    unc = tracer._uncertainties[0]
    if unc['lower_bound'] < unc['value'] < unc['upper_bound']:
        print(f"  ✅ Belirsizlik aralığı: {unc['lower_bound']:.0f} – {unc['upper_bound']:.0f}")
    else:
        errors.append("Belirsizlik aralığı yanlış")
        print("  ❌ Belirsizlik aralığı yanlış")

    unc_summary = tracer.get_uncertainty_summary()
    tests += 1
    if unc_summary['max_uncertainty_pct'] == 22.0:
        print(f"  ✅ Dominant belirsizlik: %{unc_summary['max_uncertainty_pct']}")
    else:
        errors.append(f"Dominant belirsizlik yanlış: {unc_summary['max_uncertainty_pct']}")
        print("  ❌ Dominant belirsizlik yanlış")

    # ─── [7] log_optimization ─────────────────────────────
    print("\n  [7] Optimizasyon Kaydı")

    tracer.log_optimization(
        opt_type="altitude",
        selected="FL380",
        reason="Max Ground SAR. Rüzgar dahil FL380 en iyi.",
        alternatives={
            "FL360": 0.0951, "FL370": 0.0968,
            "FL380": 0.0972, "FL390": 0.0964
        },
        constraints_applied=[
            "Westbound: çift FL",
            "Buffet marjı: %12.3 (sınırda)",
        ],
        saving_kg=180, saving_usd=153
    )
    tracer.log_optimization(
        opt_type="tankering",
        selected="2000 kg ekstra",
        reason="$0.27/kg fark. CF=%12. Net +$168/uçuş.",
        saving_kg=0, saving_usd=168
    )

    tests += 1
    if len(tracer._optimizations) == 2:
        print("  ✅ 2 optimizasyon kararı kaydedildi")
    else:
        errors.append(f"Optimizasyon sayısı: {len(tracer._optimizations)}")
        print(f"  ❌ Optimizasyon sayısı: {len(tracer._optimizations)}")

    # ─── [8] log_warning ──────────────────────────────────
    print("\n  [8] Uyarı Kaydı")

    tracer.log_warning("Buffet marjı düşük: %12.3.")
    tracer.log_warning("realization_factor varsayılan 0.65.", severity="INFO")
    tracer.log_warning(
        "MTOW sınırına çok yakın!",
        severity="CRITICAL",
        action_required=True
    )

    tests += 1
    if len(tracer._warnings) == 3:
        print("  ✅ 3 uyarı kaydedildi")
    else:
        errors.append(f"Uyarı sayısı: {len(tracer._warnings)}")
        print(f"  ❌ Uyarı sayısı: {len(tracer._warnings)}")

    # ─── [9] get_trace ────────────────────────────────────
    print("\n  [9] İz Çıktısı")

    trace = tracer.get_trace()
    tests += 1
    required_keys = ['meta', 'summary', 'inputs', 'assumptions', 'steps',
                     'validations', 'uncertainties', 'optimizations', 'warnings']
    missing = [k for k in required_keys if k not in trace]
    if not missing:
        print(f"  ✅ Tam iz: {len(required_keys)} bölüm")
    else:
        errors.append(f"Eksik bölümler: {missing}")
        print(f"  ❌ Eksik: {missing}")

    tests += 1
    summ = trace['summary']
    if (summ['total_inputs'] == 4 and
            summ['total_steps'] == 3 and
            summ['has_fails']):
        print(f"  ✅ Özet doğru")
    else:
        errors.append(f"Özet yanlış: {summ}")
        print(f"  ❌ Özet yanlış: {summ}")

    # ─── [10] JSON serileştirme ───────────────────────────
    print("\n  [10] JSON Serileştirme")

    tests += 1
    try:
        json_str = tracer.get_trace_json()
        parsed   = json.loads(json_str)
        if parsed['meta']['analysis_id'] == "TEST_001":
            print(f"  ✅ JSON serileştirme: {len(json_str):,} karakter")
        else:
            errors.append("JSON içeriği yanlış")
            print("  ❌ JSON içeriği yanlış")
    except Exception as e:
        errors.append(f"JSON hatası: {e}")
        print(f"  ❌ JSON hatası: {e}")

    # numpy değerleri
    import numpy as np
    tracer2 = AnalysisTracer("TEST_NP")
    tracer2.log_input("numpy_int",   np.int64(35000),   "ft", "test")
    tracer2.log_input("numpy_float", np.float64(0.785), "",   "test")
    tracer2.log_input("numpy_array", np.array([1.0, 2.0, 3.0]), "", "test")

    tests += 1
    try:
        js = tracer2.get_trace_json()
        json.loads(js)
        print("  ✅ numpy tipleri JSON'a serileşti")
    except Exception as e:
        errors.append(f"numpy JSON hatası: {e}")
        print(f"  ❌ numpy JSON hatası: {e}")

    # ─── [11] Dosyaya kaydet ──────────────────────────────
    print("\n  [11] Dosyaya Kaydetme")

    tests += 1
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "sub", "trace_test.json")
        saved_path = tracer.save_trace(filepath)

        if os.path.exists(saved_path):
            with open(saved_path, encoding='utf-8') as f:
                loaded = json.load(f)
            if loaded['meta']['analysis_id'] == "TEST_001":
                size_kb = os.path.getsize(saved_path) / 1024
                print(f"  ✅ Dosyaya kaydedildi: {size_kb:.1f} KB")
            else:
                errors.append("Dosya içeriği yanlış")
                print("  ❌ Dosya içeriği yanlış")
        else:
            errors.append(f"Dosya oluşturulmadı: {saved_path}")
            print("  ❌ Dosya oluşturulmadı")

    # ─── [12] print_summary ───────────────────────────────
    print("\n  [12] Özet Yazdırma")

    tests += 1
    try:
        tracer.print_summary()
        print("  ✅ print_summary çalıştı")
    except Exception as e:
        errors.append(f"print_summary hatası: {e}")
        print(f"  ❌ print_summary hatası: {e}")

    # ─── [13] Rapor metodları ─────────────────────────────
    print("\n  [13] Rapor Metodları")

    tests += 1
    asm_report = tracer.get_assumptions_report()
    if "KULLLANILAN VARSAYIMLAR" in asm_report or "VARSAYIMLAR" in asm_report:
        print("  ✅ get_assumptions_report çalıştı")
    elif len(asm_report) > 50:
        print("  ✅ get_assumptions_report üretildi")
    else:
        errors.append("get_assumptions_report boş")
        print("  ❌ get_assumptions_report boş")

    tests += 1
    val_report = tracer.get_validation_report()
    if "PASS" in val_report and "FAIL" in val_report:
        print("  ✅ get_validation_report çalıştı")
    else:
        errors.append("get_validation_report içeriği yanlış")
        print("  ❌ get_validation_report yanlış")

    # ─── [14] repr ────────────────────────────────────────
    print("\n  [14] Temsil (__repr__)")

    tests += 1
    r = repr(tracer)
    if "AnalysisTracer" in r and "TEST_001" in r:
        print(f"  ✅ repr: {r}")
    else:
        errors.append(f"repr yanlış: {r}")
        print(f"  ❌ repr: {r}")

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
    validate_logging_config()
