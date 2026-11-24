# tests/test_tail_calibrator.py

"""
GreenWing Analytics — Kurumsal Entegrasyon Katmanı Testleri
═══════════════════════════════════════════════════════════

Bu test süiti:
    1.  CORSIA Raporlama Blockchain Sealer (Mühürleme) SHA-256 bütünlüğünü,
    2.  Sealed rapor tahrif (tampering) kontrol doğrulamalarını,
    3.  Kuyruk Bazlı Dijital İkiz (TailPerformanceCalibrator) katsayı hesaplamalarını,
    4.  Motor/gövde aşınma limitlerine göre Bakım Önerileri (Advisories) üretimini
test eder.

Çalıştırma:
    python tests/test_tail_calibrator.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.blockchain_sealer import BlockchainSealer
from src.optimization.tail_performance_calibrator import TailPerformanceCalibrator


def run_tests():
    print("\n" + "=" * 60)
    print("  TEST: tail_calibrator.py — ENTERPRISE ENTEGRASYON TEST SÜİTİ")
    print("=" * 60)

    errors = []
    tests  = 0

    def check(name, actual, expected, tol=0.01):
        nonlocal tests
        tests += 1
        diff = abs(float(actual) - float(expected))
        if diff <= tol:
            print(f"  ✅ {name} = {actual:.4f}")
        else:
            errors.append(f"{name}: {actual:.4f} ≠ {expected:.4f} (Δ={diff:.4f})")
            print(f"  ❌ {name}: {actual:.4f} (beklenen {expected:.4f})")

    def check_true(name, condition):
        nonlocal tests
        tests += 1
        if condition:
            print(f"  ✅ {name}")
        else:
            errors.append(name)
            print(f"  ❌ {name}")

    # 1. BLOCKCHAIN SEALER TESTLERİ
    print("\n  [1] Blockchain Sealer & Kriptografik Mühürleme Testleri")
    
    sealer = BlockchainSealer()
    mock_report = {
        "airline": "SunExpress",
        "co2_tonnes": 5346.2,
        "offset_required": 267.3
    }
    
    # Raporu mühürle
    sealed = sealer.seal_document(mock_report, block_number=500)
    
    check_true("Rapor mühürleme başarılı", "blockchain_audit_trail" in sealed)
    if "blockchain_audit_trail" in sealed:
        trail = sealed["blockchain_audit_trail"]
        check_true("Block hash üretildi", len(trail["block_hash"]) == 64)
        # BÜTÜNLÜK: Sahte "VERIFIED_ON_LEDGER" ve uydurma tx_id/block_number
        # KALDIRILDI. Doğru davranış: yerel SHA-256 mührü, zincir iddiası YOK.
        check_true("Mühür tipi dürüst etiketli (LOCAL_SHA256)",
                   trail.get("seal_type") == "LOCAL_SHA256")
        check_true("Zincir iddiası YOK (verification_status)",
                   trail.get("verification_status") == "LOCAL_SHA256_SEALED")
        check_true("ledger_network None (zincire yazılmadı)",
                   trail.get("ledger_network") is None)
        check_true("transaction_id None (zincir işlemi yok)",
                   trail.get("transaction_id") is None)
        check_true("verification_url None (doğrulama servisi yok)",
                   trail.get("verification_url") is None)
        
        # Bütünlük kontrolü (Doğrulama)
        check_true("Kriptografik mühür doğrulaması geçti", sealer.verify_seal(sealed))
        
        # ⚠️ TAHRİFAT (TAMPERING) TESTİ: Rapordaki ofset değerini sahtekarlıkla değiştirelim!
        tampered = sealed.copy()
        tampered["offset_required"] = 0.0  # Ofseti sıfırladık! (Sahtekarlık!)
        check_true("Sahtekarlık/Tahrifat başarıyla tespit edildi (verify_seal=False)", not sealer.verify_seal(tampered))

    # 2. TAIL PERFORMANCE CALIBRATOR TESTLERİ
    print("\n  [2] Kuyruk Bazlı Dijital İkiz Kalibrasyon Testleri")
    
    calibrator = TailPerformanceCalibrator()
    mock_batch = [
        {"filename": "ARR_AUTO_SXS1409_LTAI_EDDF.csv", "aircraft_type": "B738", "registration": "TC-SPO"},
        {"filename": "ARR_AUTO_SXS1409_LTAI_EDDF.csv", "aircraft_type": "B738", "registration": "TC-SPO"},
        {"filename": "ARR_AUTO_SXS6381_LTBJ_EDDF.csv", "aircraft_type": "B738", "registration": "TC-SMZ"},
    ]
    
    # ═══════════════════════════════════════════════════════
    # DENETİM #54 — ESKİ TEST UYDURMA DAVRANIŞI DOĞRULUYORDU
    # ═══════════════════════════════════════════════════════
    # Bu test eskiden `calibrate_fleet_digital_twins(mock_batch)`
    # çağrısının "SUCCESS" dönmesini ve tescil harfinden türetilmiş
    # cd0/sfc faktörlerini "makul" sayıyordu. Oysa faktörler
    # uçuşla hiçbir ilgisi olmayan son-harf fonksiyonuydu.
    # Test, sahte davranışı YEŞİL tutuyordu.
    #
    # Yeni sözleşme:
    #   • demo_mode=False (varsayılan) + yeterli veri yok
    #     → status PARTIAL, calibration None (faktör UYDURULMAZ)
    #   • demo_mode=True → status DEMO, estimated=True
    #     ve bakım önerileri "TAHMİNİ" ibaresi taşır
    #   • gerçek uçuş verisi → status SUCCESS, calibrated_from_data

    # ── (a) Varsayılan: veri yok → faktör üretilmemeli ──
    results = calibrator.calibrate_fleet_digital_twins(mock_batch)
    check_true(
        f"Varsayılan mod DEMO/SUCCESS değil ({results['status']})",
        results["status"] in ("PARTIAL", "ERROR")
    )
    check("Toplam dijital ikiz sayısı doğru", results["total_twins"], 2, 0.01)

    twins = results["digital_twins"]
    spo = twins.get("TC-SPO", {})
    check_true("TC-SPO calibration = None (uydurma yok)",
               spo.get("calibration") is None)
    check_true("TC-SPO durumu INSUFFICIENT_DATA",
               spo.get("status") == "INSUFFICIENT_DATA")
    check_true("TC-SPO estimated = False", spo.get("estimated") is False)
    check("TC-SPO takip edilen uçuş sayısı",
          spo.get("total_flights_tracked", 0), 2, 0.01)

    # ── (b) demo_mode=True → açıkça DEMO ve TAHMİNİ ──
    demo = calibrator.calibrate_fleet_digital_twins(mock_batch, demo_mode=True)
    check_true(f"demo_mode=True → status DEMO ({demo['status']})",
               demo["status"] == "DEMO")
    check_true("demo_mode=True → estimated_twins > 0",
               demo["estimated_twins"] > 0)
    demo_spo = demo["digital_twins"]["TC-SPO"]
    check_true("demo TC-SPO estimated = True", demo_spo["estimated"] is True)
    check_true("demo TC-SPO calibration dolu",
               demo_spo.get("calibration") is not None)
    check_true(
        "demo bakım önerisi 'TAHMİNİ' ibaresi taşıyor",
        any("TAHMİNİ" in a["rationale"] for a in demo_spo["advisories"])
    )

    # ── (c) Aynı harf → aynı faktör DEĞİL (eski hata) ──
    # Eski kod TC-SPA ile TC-JAA'ya birebir aynı değerleri verirdi.
    # Artık demo profili de tescil son 3 harfe göre ayrışır;
    # en azından farklı tescil → farklı kayıt anahtarı.
    _two = calibrator.calibrate_fleet_digital_twins(
        [{"registration": "TC-SPA", "aircraft_type": "B738"},
         {"registration": "TC-JAA", "aircraft_type": "B738"}],
        demo_mode=True)
    check_true("TC-SPA ve TC-JAA ayrı ikizler",
               set(_two["digital_twins"]) == {"TC-SPA", "TC-JAA"})
    # Eski hata: ikisi de 'A' ile bittiği için AYNI faktörleri alırdı.
    # Yeni demo profili son 3 harfe bakar → SPA != JAA.
    _c_spa = _two["digital_twins"]["TC-SPA"]["calibration"]
    _c_jaa = _two["digital_twins"]["TC-JAA"]["calibration"]
    check_true(
        f"TC-SPA ({_c_spa['cd0_factor']}) ≠ TC-JAA ({_c_jaa['cd0_factor']})",
        _c_spa["cd0_factor"] != _c_jaa["cd0_factor"]
    )

    # ── (d) Gerçek uçuş verisi → veriden kalibrasyon ──
    real_batch = [
        {"registration": "TC-REAL", "aircraft_type": "B738",
         "distance_nm": 600,  "weight_kg": 65000, "cruise_alt_ft": 33000,
         "mach": 0.78, "actual_fuel_kg": 4300},
        {"registration": "TC-REAL", "aircraft_type": "B738",
         "distance_nm": 900,  "weight_kg": 64000, "cruise_alt_ft": 35000,
         "mach": 0.78, "actual_fuel_kg": 6300},
        {"registration": "TC-REAL", "aircraft_type": "B738",
         "distance_nm": 1200, "weight_kg": 62000, "cruise_alt_ft": 37000,
         "mach": 0.78, "actual_fuel_kg": 8300},
        {"registration": "TC-REAL", "aircraft_type": "B738",
         "distance_nm": 1500, "weight_kg": 60000, "cruise_alt_ft": 39000,
         "mach": 0.78, "actual_fuel_kg": 10300},
    ]
    real = calibrator.calibrate_fleet_digital_twins(real_batch)
    real_twin = real["digital_twins"]["TC-REAL"]
    check_true(f"Gerçek veri → kalibrasyon yapıldı ({real['status']})",
               real_twin.get("calibrated_from_data") is True)
    if real_twin.get("calibration"):
        cd0_f = real_twin["calibration"]["cd0_factor"]
        sfc_f = real_twin["calibration"]["sfc_factor"]
        check_true(f"TC-REAL CD0 makul ({cd0_f:.4f})", 0.85 <= cd0_f <= 1.25)
        check_true(f"TC-REAL SFC makul ({sfc_f:.4f})", 0.90 <= sfc_f <= 1.15)
        print(f"     TC-REAL CD0 Factor: {cd0_f:.4f}")
        print(f"     TC-REAL SFC Factor: {sfc_f:.4f}")

    # ── (e) [59] TESCİL YOKSA ERROR — tek uçağa atfetme ──
    # DENETİM #59: batch_results içinde registration hiç yoksa
    # tüm uçuşlar tek varsayılan tescile düşüyordu. 14 farklı
    # uçak tek "dijital ikiz" gibi kalibre edilip cd0 sınıra
    # dayanıyordu (1.248). Bu sessizce yapılmamalı.
    _no_reg = [
        {"callsign": "X1", "aircraft_type": "B738",
         "distance_nm": 600, "estimated_fuel_kg": 4300},
        {"callsign": "X2", "aircraft_type": "B738",
         "distance_nm": 900, "estimated_fuel_kg": 6300},
        {"callsign": "X3", "aircraft_type": "A320",
         "distance_nm": 1200, "estimated_fuel_kg": 8300},
    ]
    _nr = calibrator.calibrate_fleet_digital_twins(_no_reg)
    check_true(f"Tescilsiz batch → ERROR ({_nr['status']})",
               _nr["status"] == "ERROR")
    check_true("Tescilsiz batch → mesaj tescil istiyor",
               "registration" in _nr["message"])
    check_true("Tescilsiz batch → ikiz üretilmedi",
               _nr["total_twins"] == 0)

    # demo_mode ile tescilsiz çalışabilmeli (açık istek)
    _nr_demo = calibrator.calibrate_fleet_digital_twins(_no_reg, demo_mode=True)
    check_true(f"Tescilsiz + demo_mode → çalışır ({_nr_demo['status']})",
               _nr_demo["status"] in ("DEMO", "PARTIAL"))

    # ── (f) [58] Özet durum TÜM kayıtları kapsamalı ──────
    # DENETİM #58: CALIBRATION_FAILED hiçbir sayaca girmiyordu
    # → 1 başarısız ikizle "SUCCESS" dönüyordu.
    _fail = [
        {"registration": "TC-FAIL", "aircraft_type": "B738",
         "distance_nm": 600, "actual_fuel_kg": 4300},
        {"registration": "TC-FAIL", "aircraft_type": "B738",
         "distance_nm": 900, "actual_fuel_kg": 6300},
        {"registration": "TC-FAIL", "aircraft_type": "B738",
         "distance_nm": 1200, "actual_fuel_kg": "BOZUK"},
        {"registration": "TC-FAIL", "aircraft_type": "B738",
         "distance_nm": 1500, "actual_fuel_kg": 10300},
    ]
    try:
        _fr = calibrator.calibrate_fleet_digital_twins(_fail)
        _ok = _fr["status"] != "SUCCESS" or \
              _fr.get("calibrated_twins") == _fr["total_twins"]
        check_true(f"Bozuk veri → SUCCESS değil ({_fr['status']})", _ok)
    except Exception:
        check_true("Bozuk veri → çökmedi", False)

    # ═══════════════════════════════════════════════════════
    # SONUÇ
    # ═══════════════════════════════════════════════════════
    print(f"\n  {'─' * 50}")
    print(f"  Toplam test : {tests}")
    print(f"  Başarılı    : {tests - len(errors)}")
    print(f"  Başarısız   : {len(errors)}")

    if errors:
        print(f"\n  ❌ BAŞARISIZ ENTEGRASYON TESTLERİ:")
        for i, e in enumerate(errors, 1):
            print(f"     {i}. {e}")
        return False
    print("  ✅ TÜM ENTEGRASYON KATMANI TESTLERİ BAŞARILI\n")
    return True


if __name__ == "__main__":
    run_tests()
