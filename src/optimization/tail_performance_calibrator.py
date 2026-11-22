# src/optimization/tail_performance_calibrator.py

"""
GreenWing Analytics — Kuyruk Bazlı Dijital İkiz ve Motor Aşınma Kalibrasyon Motoru
═════════════════════════════════════════════════════════════════════════════════

Bu modül, havayoluna ait her bir bağımsız uçağı (kuyruk tesciline göre, ör. TC-SPO)
uçuş bazlı radar ve yakıt verileri üzerinden izleyerek:
    1. Her uçağın kendine has pürüzsüzlük/sürtünme katsayısını (cd0_factor / gövde yaşlanması)
    2. Motorun verim/SFC aşınma katsayısını (sfc_factor / kompresör yıpranması)
gerçek zamanlı olarak kalibre eder ve her uçağın "Dijital İkizini" (Digital Twin) oluşturur.

MÜHENDİSLİK VE BAKIM ÖNERİLERİ (Condition-Based Maintenance):
─────────────────────────────────────────────────────────────
    Sistem sadece kalibrasyon yapmaz; havayolu bakım ekipleri (MRO) için aksiyon üretir:
        • Eğer cd0_factor > 1.05 ise → "Gövde ve Kanat Yıkama Önerisi" (Aerodynamic Wash)
        • Eğer sfc_factor > 1.03 ise → "Motor Kompresör Yıkama Önerisi" (Engine Wash)
    Bu sayede uçaklar havada ölü ağırlık taşımaktan kurtulur ve yakıt bütçesi optimize edilir.

KULLANIM:
─────────
    from src.optimization.tail_performance_calibrator import TailPerformanceCalibrator
    
    calibrator = TailPerformanceCalibrator()
    twins = calibrator.calibrate_fleet_digital_twins(batch_results_list)
    # twins artık her kuyruk tescilinin özelleşmiş fiziksel profillerini içerir.
"""

from __future__ import annotations

import numpy as np
from typing import List, Dict, Any


class TailPerformanceCalibrator:
    """
    Kuyruk tesciline özel aerodinamik ve motor verim kalibrasyon motoru.
    """

    def __init__(self) -> None:
        self.fleet_twins: Dict[str, Dict[str, Any]] = {}

    # ══════════════════════════════════════════════════════════
    # DENETİM #54 — "KALİBRASYON" ASLINDA HARF FONKSİYONUYDU
    # ══════════════════════════════════════════════════════════
    # Eski `_generate_mock_degradation(reg)` faktörleri TESCİL
    # NUMARASININ SON HARFİNDEN üretiyordu:
    #     cd0_f = 0.98 + (ord(reg[-1]) % 15) * 0.01
    #     sfc_f = 0.97 + (ord(reg[-1]) % 9)  * 0.009
    #
    # Sonuç: TC-SPA ile TC-JAA (farklı havayolu, farklı uçak)
    # BİREBİR AYNI faktörleri alıyordu; 1 uçuş ile 200 uçuş da
    # aynı sonucu veriyordu (veriden öğrenme YOK).
    #
    # Buna rağmen çıktı `"status": "SUCCESS"` dönüyor ve
    # "Gövde Yıkama ÖNERİLİR / YÜKSEK öncelik" gibi MRO
    # aksiyonları üretiyordu — uydurma sayıdan bakım kararı.
    #
    # DÜZELTME: Gerçek kalibrasyon için uçuş bazlı yakıt verisi
    # + Nelder-Mead gerekir (model_calibrator.py'de var). Bu modül
    # demo/PoC seviyesinde olduğu için artık UYDURMUYOR; açıkça
    # `estimated: True` bayrağı ve uyarı döndürüyor.

    # Deterministik demo profili — yalnız `demo_mode=True` ile
    # kullanılır ve ÇIKTIDA açıkça "estimated" işaretlenir.
    _DEMO_PROFILES = {
        'SPO': (1.062, 1.018),   # örnek: yıkanmamış gövde
        'SPA': (1.018, 1.004),
        'SPB': (1.034, 1.009),
        'JAA': (1.007, 0.997),
    }

    def _demo_degradation(self, tail_number: str) -> tuple[float, float]:
        """
        DEMO AMAÇLI sabit profil. GERÇEK KALİBRASYON DEĞİLDİR.

        Çağıran taraf bunu `demo_mode=True` ile açıkça istemeli;
        çıktıda `estimated: True` olarak işaretlenir.
        """
        suffix = tail_number[-3:].upper() if tail_number else ''
        return self._DEMO_PROFILES.get(suffix, (1.03, 1.01))

    def calibrate_fleet_digital_twins(
        self,
        batch_results: List[Dict[str, Any]],
        demo_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        Gelen toplu uçuş sonuçlarından, her kuyruk tescili için
        kalibrasyon faktörlerini ve bakım önerilerini çıkartır.

        Args:
            batch_results: Uçuş sonuçları listesi
            demo_mode    : True → doğrulanmamış DEMO profili kullanılır
                           ve çıktıda `estimated: True` işaretlenir.
                           False (varsayılan) → gerçek veriden kalibrasyon
                           denenir; yeterli veri yoksa faktör ÜRETİLMEZ.

        Not:
            Gerçek kalibrasyon, uçuş bazlı yakıt verisi gerektirir ve
            `model_calibrator.TailCalibrator`/`ModelCalibrator` ile
            yapılır (Nelder-Mead, min 3 uçuş). Bu sınıf onu
            TAMAMLAMAZ; ayrı bir modüldür.
        """
        if not batch_results:
            return {"status": "ERROR", "message": "Girdi verisi boş."}
            
        # Uçuşları kuyruk tescillerine göre grupla
        tail_groups = {}
        for r in batch_results:
            reg = r.get("registration") or r.get("tail_number")
            if not reg or reg == "UNK" or reg == "Bilinmeyen":
                # Callsign veya dosya adından tescili tahmin etmeye çalış
                filename = r.get("filename", "")
                if "TC-" in filename:
                    parts = filename.split("_")
                    for p in parts:
                        if p.startswith("TC-"):
                            reg = p.replace(".csv", "")
                            break
            if not reg:
                reg = "TC-SXS"  # Varsayılan SunExpress tescili
                
            reg = reg.upper().strip()
            if reg not in tail_groups:
                tail_groups[reg] = []
            tail_groups[reg].append(r)
            
        twins = {}
        
        for reg, flights in tail_groups.items():
            # DENETİM #54: burada eskiden `_generate_mock_degradation`
            # çağrılıyordu (tescil harfinden faktör üretiyordu).
            # Artık iki yol var:
            #   (a) demo_mode=True → sabit demo profili, `estimated: True`
            #   (b) demo_mode=False → gerçek veriden kalibrasyon; yeterli
            #       veri yoksa faktör ÜRETİLMEZ ve `estimated: False`
            #       yerine "insufficient_data" durumu döner.
            estimated = False
            calibrated  = False
            reason      = None

            if demo_mode:
                cd0_f, sfc_f = self._demo_degradation(reg)
                estimated = True
                reason = ("DEMO profili: gerçek kalibrasyon değil, "
                          "sabit demo değerleri kullanıldı.")
            else:
                # Uçuş bazlı yakıt verisi var mı? (estimated_fuel_kg /
                # actual_fuel_kg ve distance_nm gerekir)
                usable = [f for f in flights
                          if f.get("actual_fuel_kg") or f.get("estimated_fuel_kg")]
                if len(usable) < 3:
                    twins[reg] = {
                        "registration"         : reg,
                        "aircraft_type"        : flights[0].get("aircraft_type", "B738"),
                        "total_flights_tracked": len(flights),
                        "status"               : "INSUFFICIENT_DATA",
                        "message"              : (
                            f"Gerçek kalibrasyon için en az 3 uçuşta "
                            f"yakıt verisi gerekir; {len(usable)} bulundu. "
                            f"Faktör ÜRETİLMEDİ (uydurma değer yerine boş)."),
                        "calibration"          : None,
                        "estimated"            : False,
                        "advisories"           : [],
                    }
                    continue

                # DENETİM #55 — ALAN ADI UYUŞMAZLIĞI
                # ModelCalibrator şu adları bekler:
                #   distance_nm, actual_fuel_kg, cruise_altitude_ft,
                #   takeoff_weight_kg, cruise_mach
                # Tail kalibratörüne gelen kayıtlar ise sık sık
                # cruise_alt_ft / weight_kg / mach adlarını kullanır.
                # Aynen geçirilirse bu alanlar SESSİZCE varsayılana
                # düşer (35.000 ft, tahmini ağırlık) → yanlış
                # kalibrasyon, üstelik hata mesajı yok.
                def _norm(f: dict) -> dict:
                    return {
                        "distance_nm"      : f.get("distance_nm") or f.get("distance"),
                        "actual_fuel_kg"   : (f.get("actual_fuel_kg")
                                              or f.get("estimated_fuel_kg")),
                        "cruise_altitude_ft": (f.get("cruise_altitude_ft")
                                               or f.get("cruise_alt_ft")
                                               or f.get("altitude_ft")),
                        "takeoff_weight_kg": (f.get("takeoff_weight_kg")
                                              or f.get("weight_kg")),
                        "cruise_mach"      : f.get("cruise_mach") or f.get("mach"),
                    }
                norm_flights = [_norm(f) for f in usable]

                # Gerçek kalibrasyon model_calibrator'a delege edilir.
                from src.optimization.model_calibrator import ModelCalibrator
                try:
                    mc = ModelCalibrator(
                        flights[0].get("aircraft_type", "B738"))
                    cal = mc.calibrate(norm_flights)
                    if cal.get("status") != "SUCCESS":
                        raise ValueError(cal.get("message", "bilinmeyen"))
                    cd0_f = float(cal["calibration_factors"]["cd0_factor"])
                    sfc_f = float(cal["calibration_factors"]["sfc_factor"])
                    calibrated = True
                except Exception as exc:  # noqa: BLE001
                    twins[reg] = {
                        "registration"         : reg,
                        "aircraft_type"        : flights[0].get("aircraft_type", "B738"),
                        "total_flights_tracked": len(flights),
                        "status"               : "CALIBRATION_FAILED",
                        "message"              : f"Kalibrasyon başarısız: {exc}",
                        "calibration"          : None,
                        "estimated"            : False,
                        "advisories"           : [],
                    }
                    continue
            
            # Bakım Önerileri (Maintenance Advisories) Üretimi
            # DENETİM #54: demo/estimated ise öneriler TAHMİNİdir;
            # mesaja bu açıkça eklenir, aksi halde MRO kararı
            # uydurma sayıya dayanır.
            adv_suffix = (" [TAHMİNİ — demo değerlerinden türetildi; "
                          "gerçek bakım kararı için doğrulanmış "
                          "kalibrasyon gerekir]" if estimated else "")
            advisories = []
            if cd0_f > 1.05:
                advisories.append({
                    "type"     : "AIRFRAME_WASH",
                    "action"   : "Gövde ve Kanat Yüzeyi Aerodinamik Yıkama",
                    "priority" : "YÜKSEK" if cd0_f > 1.10 else "ORTA",
                    "rationale": (
                        f"Gövde sürtünme katsayısı limitlerin üzerinde (CD0 Factor: {cd0_f:.3f} = +%{(cd0_f-1)*100:.1f}). "
                        f"Uçak yüzeyindeki kir ve mikro-pürüzler yüksek sürüklemeye yol açıyor. "
                        f"Yıkama işlemi binde 5 ila binde 8 yakıt tasarrufu sağlayacaktır." + adv_suffix
                    )
                })
            if sfc_f > 1.03:
                advisories.append({
                    "type"     : "ENGINE_WASH",
                    "action"   : "Motor Kompresör ve Fan Kanadı Yıkama Programı (Engine Wash)",
                    "priority" : "YÜKSEK" if sfc_f > 1.04 else "ORTA",
                    "rationale": (
                        f"Motor özgül yakıt tüketim aşınması yüksek (SFC Factor: {sfc_f:.3f} = +%{(sfc_f-1)*100:.1f}). "
                        f"Kompresör kanatlarındaki toz ve kirlilik ısıl verimi düşürüyor. "
                        f"Yıkama işlemi uçuştaki kütlesel SFC debisini binde 8 ila %1.2 düşürme potansiyeli taşımaktadır." + adv_suffix
                    )
                })
                
            if not advisories:
                advisories.append({
                    "type"     : "MONITOR",
                    "action"   : "Rutin Performans Monitoring",
                    "priority" : "DÜŞÜK",
                    "rationale": f"Uçağın gövde ve motor performans parametreleri ideal sınırlar içinde (CD0: {cd0_f:.3f}, SFC: {sfc_f:.3f})." + adv_suffix
                })

            twins[reg] = {
                "registration"       : reg,
                "aircraft_type"      : flights[0].get("aircraft_type", "B738"),
                "total_flights_tracked": len(flights),
                "calibration"        : {
                    "cd0_factor"     : cd0_f,
                    "sfc_factor"     : sfc_f,
                },
                "estimated"          : estimated,
                "calibrated_from_data": calibrated,
                "data_quality_note"  : reason,
                "efficiency_rating"  : "EXCELLENT" if cd0_f < 1.01 and sfc_f < 1.01 else ("GOOD" if cd0_f < 1.04 and sfc_f < 1.03 else "DEGRADED"),
                "advisories"         : advisories
            }
            
        self.fleet_twins = twins
        n_estimated = sum(1 for t in twins.values() if t.get("estimated"))
        n_insuff    = sum(1 for t in twins.values()
                          if t.get("status") == "INSUFFICIENT_DATA")
        if n_estimated:
            status = "DEMO"
            msg = (f"{n_estimated} dijital ikiz DEMO değerleriyle "
                   f"üretildi — gerçek kalibrasyon değildir.")
        elif n_insuff:
            status = "PARTIAL"
            msg = (f"{n_insuff} tescil için yeterli veri yok; "
                   f"faktör üretilmedi.")
        else:
            status = "SUCCESS"
            msg = "Tüm dijital ikizler gerçek veriden kalibre edildi."

        return {
            "status"        : status,
            "message"       : msg,
            "demo_mode"     : bool(demo_mode),
            "total_twins"   : len(twins),
            "estimated_twins": n_estimated,
            "insufficient_data_twins": n_insuff,
            "digital_twins" : twins,
        }
