#!/usr/bin/env python3
"""
GreenWing Analytics — Yakıt modeli "tahmin" bayrağı testleri (DENETİM #78)
═══════════════════════════════════════════════════════════════════════════

NEDEN BU TEST VAR
─────────────────
OpenAP'ın `fuel_models.csv` dosyasında yalnızca 15 uçak tipinin GERÇEK
ICAO EDB katsayısı vardır. GreenWing'in desteklediği 11 tipin 8'i
(B38M, A20N, A21N, B77W, B788, B789, A350, A380) bu listede YOKTUR;
onlar için `default × ff_to` türetmesi kullanılır ve c2/c3 katsayıları
`default` satırından AYNEN alınır.

Sorun: bu "tahmin" olduğu hiçbir yerde yazmıyordu; çıktı gerçek EDB
eğrisi gibi sunuluyordu. Denetimde ölçülen sapma:
    A20N −%17 · B789 +%26 · B77W +%63

Bu test, tahmin olan tiplerin BAYRAKLA işaretlendiğini kilitler.
Bayrak kaldırılırsa test kırılır — böylece "sessiz tahmin" geri gelemez.

Doğrulama: 12
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.fuel_model import FuelModel, _PILLAR_C2, _PILLAR_C3  # noqa: E402

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        _failed += 1
        print(f"  ✗ {name}  {detail}")


# OpenAP fuel_models.csv'de GERÇEKTEN bulunan tipler
GERCEK_EDB = {"B738", "A320", "A321"}
# Listede olmayan → default × ff_to türetmesi
TAHMIN = {"B38M", "A20N", "A21N", "B77W", "B788", "B789", "A350", "A380"}


def main() -> int:
    print("=" * 70)
    print("  DENETİM #78 — Yakıt modeli tahmin bayrağı")
    print("=" * 70)

    print("\n1. Gerçek EDB katsayısı olan tipler → tahmin DEĞİL")
    for t in sorted(GERCEK_EDB):
        m = FuelModel(t)
        check(f"{t}: fuel_model_is_estimate == False",
              m.fuel_model_is_estimate is False,
              f"gelen {m.fuel_model_is_estimate}")

    print("\n2. default × ff_to türetmesi olan tipler → tahmin EVET")
    for t in sorted(TAHMIN):
        m = FuelModel(t)
        check(f"{t}: fuel_model_is_estimate == True",
              m.fuel_model_is_estimate is True,
              f"gelen {m.fuel_model_is_estimate}")

    print("\n3. Tespit ölçütü doğru mu? (c2/c3 == default)")
    for t in sorted(GERCEK_EDB | TAHMIN):
        m = FuelModel(t)
        fc = m.params["fuel_coef"]
        same = abs(fc[1] - _PILLAR_C2) < 1e-6 and abs(fc[2] - _PILLAR_C3) < 1e-6
        check(f"{t}: bayrak == (c2,c3 default'a eşit)",
              bool(m.fuel_model_is_estimate) == same)

    print("\n4. Gerçek EDB tiplerinin c2/c3'ü default'tan FARKLI olmalı")
    for t in sorted(GERCEK_EDB):
        fc = FuelModel(t).params["fuel_coef"]
        check(f"{t}: c2 farklı", abs(fc[1] - _PILLAR_C2) > 1e-6)

    print("\n" + "=" * 70)
    total = _passed + _failed
    print(f"  Toplam : {total}")
    print(f"  Başarılı : {_passed}")
    print(f"  Başarısız : {_failed}")
    if _failed:
        print("  ❌ BAŞARISIZ")
        return 1
    print("  ✓ TÜM TAHMİN BAYRAĞI TESTLERİ BAŞARILI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
