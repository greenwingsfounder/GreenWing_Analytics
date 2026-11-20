"""
GreenWing Analytics — Sürdürülebilir Havacılık Yakıtı (SAF) Hesaplama Modeli
════════════════════════════════════════════════════════════════════════════

Bu modül, farklı SAF karışım oranlarının (blend ratios):
    1. Kimyasal / Fiziksel özelliklerini (Yoğunluk, Isıl Değer - LHV)
    2. Motorun kütlesel Özgül Yakıt Tüketimine (SFC) termodinamik etkilerini
    3. CORSIA ve ReFuelEU uyumlu Yaşam Döngüsü (Well-to-Wake) CO2 emisyon azaltımlarını
    4. SAF Green Premium maliyeti ile CORSIA Karbon Ofset tasarrufu arasındaki ekonomik trade-off'u
hesaplar.

FİZİK VE TERMODİNAMİK TEMEL:
─────────────────────────────
    • Karışım Isıl Değeri:
      LHV_blend = (1 - b) * LHV_JetA1 + b * LHV_SAF
      
    • Kütlesel SFC Düzeltmesi (LHV Etkisi):
      SFC_blend = SFC_JetA1 * (LHV_JetA1 / LHV_blend)
      (LHV arttıkça, aynı itme kuvveti için gereken yakıt kütlesi azalır)
      
    • Karışım Yoğunluğu:
      rho_blend = (1 - b) * rho_JetA1 + b * rho_SAF

KULLANIM:
─────────
    from src.models.saf_model import SAFModel
    
    saf_model = SAFModel(blend_ratio=0.30, saf_type="HEFA")
    sfc_factor = saf_model.sfc_correction_factor()  # ör. 0.993 (yakıt kütlesinde %0.7 verim artışı)
    co2_reduction = saf_model.get_lifecycle_co2_reduction_pct()  # ör. %24.6
"""

from __future__ import annotations

import os
import yaml
from typing import Dict, Any, Optional
from src.logging_config import get_logger

logger = get_logger("models.saf")  # Central logging (SAF + CORSIA preparation)


class SAFModel:
    """
    Sürdürülebilir Havacılık Yakıtı (SAF) Fizikokimyasal ve Ekonomik Değerlendirme Modeli.
    """

    def __init__(
        self,
        blend_ratio: float = 0.0,
        saf_type: str = "HEFA",
        jet_a1_price_usd_kg: float = 0.80,
    ) -> None:
        """
        Args:
            blend_ratio        : Karışım oranı (0.0 - 0.50). ASTM D7566 sınırı %50'dir.
            saf_type           : SAF üretim yolu ('HEFA', 'FT', 'ATJ', 'PTL')
            jet_a1_price_usd_kg: Geleneksel Jet A-1 fiyatı ($/kg). Varsayılan: $0.80 (~$2.60/gal).
        """
        self.blend_ratio = float(min(0.50, max(0.0, blend_ratio)))  # ASTM D7566 sınırı
        self.saf_type = saf_type.upper()
        self.jet_a1_price = jet_a1_price_usd_kg

        # Veritabanını yükle
        self.saf_db = self._load_saf_database()

        # Aktif SAF ve Referans Jet A-1 verilerini al
        if self.saf_type not in self.saf_db:
            available = [k for k in self.saf_db.keys() if k != "Jet_A1"]
            raise ValueError(
                f"Bilinmeyen SAF tipi: '{self.saf_type}'. "
                f"Desteklenen: {available}"
            )

        self.saf_props = self.saf_db[self.saf_type]
        self.jet_props = self.saf_db["Jet_A1"]
        logger.info(f"SAFModel initialized: type={self.saf_type}, blend={self.blend_ratio*100:.1f}% (CORSIA/SAF pillar ready)")

    def _load_saf_database(self) -> Dict[str, Dict[str, Any]]:
        """saf_database.yaml dosyasını yükler."""
        db_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "saf_database.yaml"
        )
        if not os.path.exists(db_path):
            # Fallback (YAML dosyası bulunamazsa kod içi yedek veriler)
            return {
                "Jet_A1": {
                    "name": "Conventional Jet A-1", "lhv": 43.15, "density": 800.0,
                    "lifecycle_co2_g_mj": 89.0, "aromatics_pct": 18.0, "price_premium_factor": 1.0,
                    "tailpipe_co2_factor": 3.160, "tailpipe_h2o_factor": 1.230, "max_blend_limit": 100.0
                },
                "HEFA": {
                    "name": "Hydroprocessed Esters and Fatty Acids", "lhv": 44.10, "density": 755.0,
                    "lifecycle_co2_g_mj": 16.0, "aromatics_pct": 0.0, "price_premium_factor": 2.8,
                    "tailpipe_co2_factor": 3.100, "tailpipe_h2o_factor": 1.370, "max_blend_limit": 50.0
                },
                "FT": {
                    "name": "Fischer-Tropsch Synthetic Paraffinic Kerosene", "lhv": 44.00, "density": 760.0,
                    "lifecycle_co2_g_mj": 13.0, "aromatics_pct": 0.0, "price_premium_factor": 4.0,
                    "tailpipe_co2_factor": 3.110, "tailpipe_h2o_factor": 1.360, "max_blend_limit": 50.0
                },
                "ATJ": {
                    "name": "Alcohol-to-Jet Synthetic Paraffinic Kerosene", "lhv": 43.80, "density": 765.0,
                    "lifecycle_co2_g_mj": 26.0, "aromatics_pct": 0.0, "price_premium_factor": 3.5,
                    "tailpipe_co2_factor": 3.120, "tailpipe_h2o_factor": 1.340, "max_blend_limit": 50.0
                },
                "PTL": {
                    "name": "Synthetic e-Kerosene (Power-to-Liquid)", "lhv": 44.20, "density": 762.0,
                    "lifecycle_co2_g_mj": 4.5, "aromatics_pct": 0.0, "price_premium_factor": 5.5,
                    "tailpipe_co2_factor": 3.090, "tailpipe_h2o_factor": 1.380, "max_blend_limit": 50.0
                }
            }

        with open(db_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data["saf_pathways"]

    # ──────────────────────────────────────────────────────
    # BÖLÜM 1: KARIŞIM FİZİKSEL ÖZELLİKLERİ
    # ──────────────────────────────────────────────────────

    def get_blend_lhv(self) -> float:
        """Karışım yakıtın Net Isıl Değerini (LHV) hesaplar (MJ/kg)."""
        b = self.blend_ratio
        lhv = (1.0 - b) * self.jet_props["lhv"] + b * self.saf_props["lhv"]
        return float(lhv)

    def get_blend_density(self) -> float:
        """Karışım yakıtın 15°C'deki yoğunluğunu hesaplar (kg/m³)."""
        b = self.blend_ratio
        density = (1.0 - b) * self.jet_props["density"] + b * self.saf_props["density"]
        return float(density)

    def get_blend_aromatics(self) -> float:
        """Karışımın aromatik oranını (%) hesaplar. Sızdırmazlık contaları için min %8 olmalıdır."""
        b = self.blend_ratio
        aromatics = (1.0 - b) * self.jet_props["aromatics_pct"] + b * self.saf_props["aromatics_pct"]
        return float(aromatics)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 2: TERMODİNAMİK ETKİ / SFC DÜZELTMESİ
    # ──────────────────────────────────────────────────────

    def sfc_correction_factor(self) -> float:
        """
        Isıl değer artışı nedeniyle kütlesel SFC düzeltme çarpanı.
        
        Aynı itme kuvvetini üretmek için yakıt kütlesindeki azalmayı simüle eder.
        Daha yüksek LHV → Daha az kütlesel debi (FF) → < 1.0 SFC faktörü.
        """
        return float(self.jet_props["lhv"] / self.get_blend_lhv())

    # ──────────────────────────────────────────────────────
    # BÖLÜM 3: EMİSYON VE SÜRDÜRÜLEBİLİRLİK METRİKLERİ
    # ──────────────────────────────────────────────────────

    def get_tailpipe_co2_factor(self) -> float:
        """Karışım yakıtın doğrudan yanma (egzoz) CO2 emisyon katsayısı (kg CO2 / kg fuel)."""
        b = self.blend_ratio
        co2_factor = (1.0 - b) * self.jet_props["tailpipe_co2_factor"] + b * self.saf_props["tailpipe_co2_factor"]
        return float(co2_factor)

    def get_tailpipe_h2o_factor(self) -> float:
        """Karışım yakıtın doğrudan yanma (egzoz) su buharı katsayısı (kg H2O / kg fuel)."""
        b = self.blend_ratio
        h2o_factor = (1.0 - b) * self.jet_props["tailpipe_h2o_factor"] + b * self.saf_props["tailpipe_h2o_factor"]
        return float(h2o_factor)

    def get_lifecycle_co2_factor_g_mj(self) -> float:
        """Karışım yakıtın yaşam döngüsü (LCA) karbon yoğunluğu (g CO2e / MJ)."""
        b = self.blend_ratio
        lca = (1.0 - b) * self.jet_props["lifecycle_co2_g_mj"] + b * self.saf_props["lifecycle_co2_g_mj"]
        return float(lca)

    def get_lifecycle_co2_reduction_pct(self) -> float:
        """
        Referans Jet A-1'e göre yaşam döngüsü CO2e emisyonlarındaki net azalma yüzdesi (%).
        CORSIA karbon ofset ve ReFuelEU uyumluluğu için temel metriktir.
        """
        ref_lca = self.jet_props["lifecycle_co2_g_mj"]
        blend_lca = self.get_lifecycle_co2_factor_g_mj()
        reduction = (ref_lca - blend_lca) / ref_lca * 100.0
        return float(reduction)

    # ──────────────────────────────────────────────────────
    # BÖLÜM 4: EKONOMİK ANALİZ (GREEN PREMIUM VS OFFSET AVOIDANCE)
    # ──────────────────────────────────────────────────────

    def get_blend_price_usd_kg(self) -> float:
        """Karışım yakıtın birim kütle fiyatı ($/kg)."""
        b = self.blend_ratio
        saf_price = self.jet_a1_price * self.saf_props["price_premium_factor"]
        blend_price = (1.0 - b) * self.jet_a1_price + b * saf_price
        return float(blend_price)

    def analyze_economic_tradeoff(
        self,
        flight_fuel_consumption_kg: float,
        carbon_credit_price_usd_tonne: float = 30.0,
    ) -> dict:
        """
        Verilen yakıt tüketimi için SAF kullanımının ekonomik analizini çıkartır.
        
        SAF Green Premium maliyetini ve CORSIA karbon ofseti engelleme tasarrufunu
        karşılaştırarak net finansal etkiyi hesaplar.
        """
        # Standart Jet A-1 maliyeti
        base_cost = flight_fuel_consumption_kg * self.jet_a1_price

        # Isıl değer düzeltmesiyle SAF karışımı kütlesel tüketimi (Daha hafif)
        saf_fuel_consumption_kg = flight_fuel_consumption_kg * self.sfc_correction_factor()
        saf_cost = saf_fuel_consumption_kg * self.get_blend_price_usd_kg()

        # Yakıt maliyet farkı (Green Premium)
        green_premium_usd = saf_cost - base_cost

        # Yaşam döngüsü CO2 azaltımı (tonnes)
        # 1 kg Jet A-1 yandığında 3.16 kg CO2 üretir. Ofset azaltımı yaşam döngüsündeki CO2 tasarrufu kadardır.
        co2_saved_tonnes = (
            (flight_fuel_consumption_kg * 3.16 / 1000.0)
            * (self.get_lifecycle_co2_reduction_pct() / 100.0)
        )

        # CORSIA ofset maliyet tasarrufu
        offset_saving_usd = co2_saved_tonnes * carbon_credit_price_usd_tonne
        
        # Net operasyonel etki
        net_financial_impact_usd = offset_saving_usd - green_premium_usd

        return {
            'saf_type'                      : self.saf_type,
            'blend_ratio_pct'               : self.blend_ratio * 100.0,
            'base_fuel_burn_kg'             : round(flight_fuel_consumption_kg),
            'saf_fuel_burn_kg'              : round(saf_fuel_consumption_kg),
            'mass_saving_kg'                : round(flight_fuel_consumption_kg - saf_fuel_consumption_kg),
            'base_fuel_cost_usd'            : round(base_cost, 2),
            'saf_fuel_cost_usd'             : round(saf_cost, 2),
            'green_premium_usd'             : round(green_premium_usd, 2),
            'co2_saved_lifecycle_tonnes'    : round(co2_saved_tonnes, 3),
            'offset_saving_usd'             : round(offset_saving_usd, 2),
            'net_financial_impact_usd'      : round(net_financial_impact_usd, 2),
            'is_commercially_viable'        : net_financial_impact_usd > 0
        }

    def __repr__(self) -> str:
        return (
            f"SAFModel(type='{self.saf_type}', blend_ratio={self.blend_ratio:.2f}, "
            f"LHV={self.get_blend_lhv():.2f} MJ/kg, density={self.get_blend_density():.1f} kg/m³)"
        )
    