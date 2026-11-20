# scripts/05_saf_scenario_analysis.py

"""
GreenWing Analytics — SAF Karışım ve Senaryo Analiz Simülasyonu
═════════════════════════════════════════════════════════════════

Bu script, SAF entegrasyonunun uçuş performansı, emisyonlar ve operasyonel maliyetler 
üzerindeki etkilerini farklı senaryolar altında simüle eder.

PROFESÖR TOPLANTISI İÇİN:
─────────────────────────
Bu analiz, seçilen bir rotada (örneğin SunExpress LTAI-EDDF veya Türk Hava Yolları LTFM-KJFK)
farklı SAF blend oranlarının (%10, %20, %30, %50) ve farklı SAF yollarının (HEFA, PTL):
    1. Kütlesel yakıt tüketimine olan fiziksel etkisini (LHV iyileşmesi)
    2. Kuyruk borusu (Tailpipe) vs Yaşam Döngüsü (LCA) CO2 salınımlarını
    3. Yakıt alım maliyeti (Green Premium) ve CORSIA Karbon Ofset kaçınım kazancını
karşılaştırmalı bir rapor halinde sunar.

Kullanım:
    python scripts/05_saf_scenario_analysis.py --airline SXS --route LTAI-EDDF
"""

from __future__ import annotations

import os
import sys
import argparse
import yaml
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.models.fuel_model import FuelModel
from src.models.saf_model import SAFModel


def run_saf_analysis(airline_key: str, route_str: str):
    # 1. Senaryo veritabanını yükle
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "demo_scenarios.yaml"
    )
    if not os.path.exists(config_path):
        print(f"❌ HATA: Senaryo dosyası bulunamadı: {config_path}")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        scenarios_db = yaml.safe_load(f)

    if airline_key not in scenarios_db.get("scenarios", {}):
        print(f"❌ HATA: '{airline_key}' anahtarı senaryolarda bulunamadı.")
        return

    scenario = scenarios_db["scenarios"][airline_key]
    airline_name = scenario["airline_name"]
    aircraft_type = scenario["aircraft_type"]

    # Rota eşlemesi
    route_parts = route_str.split("-")
    if len(route_parts) != 2:
        print(f"❌ HATA: Rota formatı 'ORJ-VAR' olmalıdır (ör. LTAI-EDDF)")
        return
    origin, destination = route_parts[0].upper(), route_parts[1].upper()

    route_data = None
    for r in scenario["routes"]:
        if r["origin"] == origin and r["destination"] == destination:
            route_data = r
            break

    if not route_data:
        available_routes = [f"{r['origin']}-{r['destination']}" for r in scenario['routes']]
        print(f"❌ HATA: {airline_name} için '{route_str}' rotası tanımlı değil.")
        print(f"Mevcut rotalar: {available_routes}")
        return

    distance_nm = route_data["distance_nm"]
    mach = 0.785 if aircraft_type == "B738" else (0.78 if aircraft_type == "A20N" else 0.85)
    altitude_ft = 37000 if aircraft_type == "A350" else 35000
    
    # Kaba kalkış ağırlığı belirleme (OEW + Payload + Trip Fuel tahmini)
    fm_temp = FuelModel(aircraft_type)
    oew = fm_temp.params.get("oew", 41000)
    mtow = fm_temp.params.get("mtow", 79000)
    # Payload ve yedek yakıt tahmini
    weight_without_fuel = oew + 15000  # OEW + 15t payload
    takeoff_weight_kg = min(mtow - 2000, weight_without_fuel + distance_nm * 6.5 + 4000)

    print("\n" + "=" * 80)
    print(f"  GREENWING ANALYTICS — SAF KARAR DESTEK VE ENTEGRASYON ANALİZİ")
    print(f"  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)
    print(f"  Havayolu         : {airline_name} ({airline_key})")
    print(f"  Uçak Tipi        : {aircraft_type} (Motor: {fm_temp.params.get('engine_type', '?')})")
    print(f"  Rota             : {origin} ✈ {destination} ({distance_nm} Nm)")
    print(f"  Kalkış Ağırlığı  : {takeoff_weight_kg:,.0f} kg")
    print(f"  Seyir İrtifası   : FL{altitude_ft // 100} (M {mach:.3f})")
    print("=" * 80)

    # Senaryolar: [Blend Ratio, SAF Type, Carbon Price, Jet A-1 Price]
    scenarios = [
        (0.0, "HEFA", "Jet A-1 Baseline (Referans)"),
        (0.10, "HEFA", "%10 HEFA Karışımı (ReFuelEU 2030 Hedefi)"),
        (0.20, "HEFA", "%20 HEFA Karışımı"),
        (0.30, "HEFA", "%30 HEFA Karışımı"),
        (0.50, "HEFA", "%50 HEFA Karışımı (Maksimum ASTM Sınırı)"),
        (0.50, "PTL", "%50 PtL (e-Fuel) Karışımı (Gelecek Vizyonu)"),
    ]

    carbon_price = 30.0  # $/tonne (CORSIA / EU-ETS Ofset fiyatı tahmini)
    jet_price = 0.80     # $/kg (Standart Jet A-1 fiyatı)

    results = []

    print(f"\n  UÇUŞ SİMÜLASYONU VE TERMODİNAMİK HESAPLAMALAR BAŞLATILIYOR...")
    print(f"  [Fizik Motoru: ISA + Drag Polar + LHV-Adjusted SFC]")
    print(f"  " + "─" * 76)

    # 1. Referans Uçuş Simülasyonu (0% SAF)
    fm_ref = FuelModel(aircraft_type, saf_blend_ratio=0.0)
    ref_burn_results = fm_ref.estimate_total_flight_fuel(distance_nm, takeoff_weight_kg, altitude_ft, mach)
    ref_fuel_burn_kg = ref_burn_results["total_fuel_kg"]

    for ratio, saf_type, desc in scenarios:
        # SAF modelini oluştur
        saf_model = SAFModel(blend_ratio=ratio, saf_type=saf_type, jet_a1_price_usd_kg=jet_price)
        
        # SAF etkili fiziksel yakıt modelini oluştur
        fm_saf = FuelModel(
            aircraft_type, 
            saf_blend_ratio=ratio, 
            saf_type=saf_type
        )
        
        # Simülasyonu çalıştır
        sim_results = fm_saf.estimate_total_flight_fuel(distance_nm, takeoff_weight_kg, altitude_ft, mach)
        actual_burn_kg = sim_results["total_fuel_kg"]
        
        # Ekonomik analizi yap
        econ = saf_model.analyze_economic_tradeoff(
            flight_fuel_consumption_kg=ref_fuel_burn_kg,
            carbon_credit_price_usd_tonne=carbon_price
        )
        
        # Kuyruk borusu emisyonu (Gerçek yanma CO2)
        tailpipe_co2_tonnes = actual_burn_kg * saf_model.get_tailpipe_co2_factor() / 1000.0
        
        # Yaşam döngüsü CO2 emisyonu (Well-to-Wake)
        # 1 MJ yakıt yandığında oluşan CO2e = LCA_intensity (g/MJ)
        # Toplam MJ = actual_burn * LHV_blend
        total_energy_mj = actual_burn_kg * saf_model.get_blend_lhv()
        lifecycle_co2_tonnes = (total_energy_mj * saf_model.get_lifecycle_co2_factor_g_mj()) / 1_000_000.0

        results.append({
            'desc': desc,
            'ratio': ratio,
            'saf_type': saf_type,
            'fuel_burn_kg': actual_burn_kg,
            'mass_saving_kg': ref_fuel_burn_kg - actual_burn_kg,
            'density': saf_model.get_blend_density(),
            'aromatics': saf_model.get_blend_aromatics(),
            'tailpipe_co2': tailpipe_co2_tonnes,
            'lifecycle_co2': lifecycle_co2_tonnes,
            'co2_saved_lca_tonnes': econ['co2_saved_lifecycle_tonnes'],
            'fuel_cost_usd': econ['saf_fuel_cost_usd'],
            'green_premium_usd': econ['green_premium_usd'],
            'offset_saving_usd': econ['offset_saving_usd'],
            'net_impact_usd': econ['net_financial_impact_usd']
        })
        
        print(f"  ✅ Simüle Edildi: {desc:<48} | Kütlesel Tüketim: {actual_burn_kg:,.0f} kg")

    print("  " + "─" * 76)

    # 2. Karşılaştırmalı Rapor Ekranı
    print("\n" + "=" * 115)
    print(f"  SAF SİMÜLASYONU KARIŞIM KARŞILAŞTIRMA TABLOSU (Karbon Ofset Fiyatı: ${carbon_price:.0f}/ton, Jet A-1: ${jet_price:.2f}/kg)")
    print("=" * 115)
    print(f"  Senaryo / Yakıt Tipi           Oran   Yoğunluk   Aromatik   Yakıt Tük.  Kütlesel  Egzoz CO2  LCA CO2   Yakıt Mal.  Green Prem. Ofset Tas.  Net Etki")
    print(f"                                 (%)     (kg/m³)     (%)        (kg)      Tasarruf    (ton)     (ton)       ($)         ($)         ($)       ($)")
    print("─" * 115)
    
    for r in results:
        ratio_str = f"{r['ratio']*100:.0f}%"
        aromatic_warning = "⚠" if r['aromatics'] < 8.0 and r['ratio'] > 0 else " "
        print(f"  {r['desc'][:28]:<28} {ratio_str:>5} {r['density']:>8.1f} {r['aromatics']:>8.1f}%{aromatic_warning} {r['fuel_burn_kg']:>10,.0f} {r['mass_saving_kg']:>9,.0f} {r['tailpipe_co2']:>10.2f} {r['lifecycle_co2']:>9.2f} {r['fuel_cost_usd']:>11,.0f} {r['green_premium_usd']:>11,.0f} {r['offset_saving_usd']:>10,.0f} {r['net_impact_usd']:>9,.0f}")
    
    print("=" * 115)
    print("  Notlar:")
    print("  1. LHV (Net Isıl Değer) artışından ötürü, SAF oranı arttıkça kütlesel yakıt tüketimi düşer (Kütlesel Tasarruf sütunu).")
    print("  2. [⚠] Simgesi, aromatik oranının ASTM D7566 standardında sızdırmazlık için belirlenmiş olan %8 limitinin altına indiğini gösterir.")
    print("     Pure SAF sıfır aromatik içerdiğinden, uçağa yüklenmeden önce aromatikli fosil yakıtla blend edilmek ZORUNDADIR.")
    print("  3. Egzoz CO2 emisyonu doğrudan yanma sonucu açığa çıkan gazdır. LCA (Life Cycle) CO2 ise yakıtın hammaddeden üretime")
    print("     ve yanmaya kadar olan tüm Well-to-Wake emisyonlarını yansıtır. CORSIA ve EU-ETS ofsetleri LCA emisyon tasarrufuna göre hesaplanır.")
    print("=" * 115 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GreenWing Analytics - SAF Scenario Analysis")
    parser.add_argument("--airline", type=str, default="SXS", choices=["SXS", "PGT", "THY"], help="Simüle edilecek havayolu")
    parser.add_argument("--route", type=str, default="LTAI-EDDF", help="Simüle edilecek rota (ör. LTAI-EDDF)")
    args = parser.parse_args()

    run_saf_analysis(args.airline, args.route)
