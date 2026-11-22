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
    
    results = calibrator.calibrate_fleet_digital_twins(mock_batch)
    
    check_true("Kalibratör çıktısı başarılı", results["status"] == "SUCCESS")
    check("Toplam dijital ikiz sayısı doğru", results["total_twins"], 2, 0.01)
    
    twins = results["digital_twins"]
    check_true("TC-SPO tescili bulundu", "TC-SPO" in twins)
    check_true("TC-SMZ tescili bulundu", "TC-SMZ" in twins)
    
    if "TC-SPO" in twins:
        spo = twins["TC-SPO"]
        check("TC-SPO takip edilen uçuş sayısı", spo["total_flights_tracked"], 2, 0.01)
        
        # Katsayıların doğruluğu
        cd0_f = spo["calibration"]["cd0_factor"]
        sfc_f = spo["calibration"]["sfc_factor"]
        check_true(f"TC-SPO CD0 Factor makul ({cd0_f})", 0.95 <= cd0_f <= 1.25)
        check_true(f"TC-SPO SFC Factor makul ({sfc_f})", 0.90 <= sfc_f <= 1.15)
        
        # Bakım önerileri üretildi mi?
        advisories = spo["advisories"]
        check_true("Bakım önerileri listesi dolu", len(advisories) > 0)
        check_true("Bakım önerisinde aksiyon var", "action" in advisories[0] and "priority" in advisories[0])
        print(f"     TC-SPO Gövde Aşınma Katsayısı: {cd0_f:.3f}")
        print(f"     TC-SPO Motor Aşınma Katsayısı: {sfc_f:.3f}")
        print(f"     Önerilen Aksiyon             : {advisories[0]['action']} (Öncelik: {advisories[0]['priority']})")

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
