#!/usr/bin/env python3
"""
Proje Yapı Ağacı Üreteci
════════════════════
Deponun GERÇEK ağacını, her dosyanın ne işe yaradığıyla birlikte
üretir. Elle yazılmaz — bu yüzden asla gerçekle uyuşmazlık olmaz.

Kullanım:
    python tools/build_tree.py              # stdout
    python tools/build_tree.py --md         # docs/YAPI_AGACI.md
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ── Açıklamalar: dosya → ne işe yarar (kısa, dürüst) ──────────
DESC: dict[str, str] = {
    # üst düzey
    'README.md': 'Giriş: ne bu, nasıl çalıştırılır',
    'requirements.txt': 'Python bağımlılıkları',
    'setup.py': 'Paket kurulumu (pip install -e .)',
    '.env.example': 'Ortam değişkenleri örneği (sırlar burada DEĞİL)',
    '.gitignore': 'Sürüm kontrolü dışında tutulacaklar',
    'python': 'DİKKAT: 0 byte kaza dosyası (silinmeli)',

    # src kökü
    'src/units.py': '★ Birim dönüşümü + fizik sabitleri — TEK KAYNAK',
    'src/utils.py': 'Ortak yardımcılar (haversine, biçimlendirme)',
    'src/logging_config.py': 'Hesaplama izleme / log sistemi',

    # models
    'src/models/atmosphere.py': 'ISA standart atmosfer: T/P/ρ/ses hızı',
    'src/models/aircraft_performance.py': 'Kaldırma, sürükleme, L/D, buffet',
    'src/models/fuel_model.py': '★ Yakıt akışı — EDB veya tahmin yolu',
    'src/models/emission_model.py': 'CO₂/H₂O/SO₂/NOₓ + CORSIA raporu',
    'src/models/wind_model.py': 'Rüzgâr profili (ölçüm DEĞİL, varsayım)',
    'src/models/wind_gfs.py': 'GFS rüzgârı (3 kademeli zincir)',
    'src/models/saf_model.py': 'SAF karışımı ve CO₂ azaltımı',
    'src/models/fuel_thermal_model.py': 'Yakıt sıcaklığı / donma noktası',
    'src/models/blockchain_sealer.py': 'Sonuç değiştirilemezlik mührü (SHA-256)',

    # data_collection
    'src/data_collection/airport_database.py': '60+ havalimanı + eşleştirme',
    'src/data_collection/opensky_collector.py': 'OpenSky OAuth2 + tarihsel veri',

    # ingestion
    'src/ingestion/customer_fuel_ingestor.py': 'Müşteri yakıt CSV → normalize',
    'src/ingestion/flight_matcher.py': 'Yakıt kaydı ↔ radar izi eşleştirme',
    'src/ingestion/calibration_pipeline.py': 'Uçtan uca kalibrasyon akışı',

    # analysis
    'src/analysis/phase_segmentation.py': 'Uçuşu fazlara ayır',
    'src/analysis/flight_analyzer.py': 'Tek uçuş analizi',
    'src/analysis/fleet_analyzer.py': 'Filo geneli: yakıt, tasarruf, CO₂',
    'src/analysis/sensitivity.py': 'Hassasiyet: hangi parametre ne kadar etkiler',
    'src/analysis/uncertainty.py': '★ Belirsizlik bütçesi / güven aralığı',
    'src/analysis/benchmark.py': 'Bağımsız kaynakla karşılaştırma',
    'src/analysis/fuel_thermal_model.py': 'Termal model yardımcısı',

    # optimization
    'src/optimization/altitude_optimizer.py': 'Optimum irtifa + step climb',
    'src/optimization/cost_index_optimizer.py': 'CI → hız optimizasyonu',
    'src/optimization/tankering_optimizer.py': 'Yakıt tankering kararı',
    'src/optimization/model_calibrator.py': 'Modeli müşteri verisine göre ayarla',
    'src/optimization/tail_performance_calibrator.py': 'Kuyruk bazlı dijital ikiz',

    # validation
    'src/validation/data_validator.py': 'Girdi verisi sağlıklı mı',
    'src/validation/business_validator.py': 'İş mantığı tutarlı mı',
    'src/validation/physics_validator.py': '★ Fizik yasalarına uyuyor mu',

    # reporting / security
    'src/reporting/report_generator.py': 'HTML/JSON rapor + CORSIA belgesi',
    'src/security/auth.py': '★ Oturum + rol + kiracı',

    # config
    "config/settings.py": "Sistem ayarları (units.py'den okur)",
    'config/assumptions.py': 'İş varsayımları (fiyat, gerçekleşme)',
    'config/credentials.py': 'Sır okuma (env önceliği, depoda sır YOK)',
    'config/aircraft_database.yaml': '★ 14 uçak tipi: ağırlık, kanat, polar',
    'config/aircraft_polar_sources.yaml': 'Polar değerlerin kaynak izi',
    'config/phase_thrust_table.yaml': 'Faz bazlı itki tablosu',
    'config/saf_database.yaml': 'SAF türleri ve özellikleri',
    'config/ingestion_config.py': 'Müşteri verisi kabul kuralları',
    'config/demo_scenarios.yaml': 'Demo senaryoları (ticari kullanılmaz)',

    # webapp
    'webapp/app.py': '★ 10 sayfalı site + API + PDF indirme',

    # tools
    'tools/full_audit.py': '★ 7 katmanlı tam denetim (228 kontrol)',
    'tools/build_tree.py': 'Bu ağacı üreten script',
    'tools/build_handbook.py': 'PDF: proje el kitabı',
    'tools/build_technical_report.py': 'PDF: teknik rapor',
    'tools/build_pilot_data_package.py': 'Pilot veri paketi üretir',
    'tools/build_provenance.py': 'Model kaynak envanteri',
    'tools/calibrate_aircraft_database.py': 'Polar katsayı kalibrasyonu',
    'tools/calibrate_phase_thrust.py': 'Faz itkisi kalibrasyonu',
    'tools/openap_reference.py': 'OpenAP referans karşılaştırması',
    'tools/sync_openap_params.py': 'OpenAP → YAML senkron',
    'tools/sync_fuel_coef.py': 'Yakıt katsayısı senkron',

    # scripts
    'scripts/01_collect_data.py': '① Veri topla (OpenSky/ADSB.lol)',
    'scripts/02_analyze_and_optimize.py': '② ★ Ana boru hattı: analiz + optimizasyon',
    'scripts/03_generate_outputs.py': '③ Rapor üret (HTML/JSON)',
    'scripts/04_generate_professional_demo.py': '④ Demo verisi üret (sentetik)',
    'scripts/05_saf_scenario_analysis.py': '⑤ SAF senaryo analizi',
    'scripts/06_seed_real_data.py': '⑥ Sentetik uçuş yolu üret (demo)',
    'scripts/07_live_flight_scrapper.py': '⑦ Canlı radar (ADSB.lol)',
    'scripts/08_automated_fleet_tracker.py': '⑧ Otomatik filo takibi',
    'scripts/09_clean_and_backup.py': '⑨ Temizlik + yedekleme',
    'scripts/10_pre_real_ingestion_demo.py': '⑩ Müşteri verisi kabul demo',

    # tests
    'tests/test_webapp.py': 'Site: 10 sayfa, API, PDF, rol',
    'tests/test_auth.py': 'Kimlik: parola, oturum, rol, kiracı',
    'tests/test_units.py': 'Birim dönüşümleri',
    'tests/test_atmosphere.py': 'ISA atmosfer (ICAO elle hesap)',
    'tests/test_fuel_model.py': 'Yakıt modeli fizik',
    'tests/test_aircraft_data_provenance.py': '★ Uçak verisi kaynak doğrulaması',
    'tests/test_security.py': 'Güvenlik: sırlar, XSS, enjeksiyon',
    'tests/test_emission.py': 'Emisyon + CORSIA',
    'tests/test_uncertainty.py': 'Belirsizlik',
    'tests/test_wind_provider.py': 'Rüzgâr zinciri',
    'tests/test_performance.py': 'Aerodinamik performans',
    'tests/test_optimization.py': 'Optimizasyon',
    'tests/test_fleet_analyzer.py': 'Filo analizi',
    'tests/test_sensitivity.py': 'Hassasiyet',
    'tests/test_validation.py': 'Doğrulayıcılar',
    'tests/test_utils.py': 'Yardımcılar',
    'tests/test_logging.py': 'Log sistemi',
    'tests/test_mach_physics.py': 'Mach fiziği',
    'tests/test_saf_model.py': 'SAF modeli',
    'tests/test_thermal_model.py': 'Termal model',
    'tests/test_tail_calibrator.py': 'Kuyruk kalibrasyonu',
    'tests/test_pdf_glyphs.py': 'PDF Türkçe karakter',
    'tests/test_fuel_model_estimate_flag.py': 'Tahmin bayrağı',

    # deliverables
    'deliverables/pilot_paketi/OKU.md': '★ Pilot paketi: nasıl kullanılır',
    'deliverables/pilot_paketi/01_YAKIT_VERISI_SABLONU.csv': '★ Müşteriden istenecek CSV',
    'deliverables/pilot_paketi/02_VERI_ISTEK_MEKTUBU.md': '★ Havayoluna gönderilecek mektup',
    'deliverables/pilot_paketi/03_KABUL_KRITERLERI.md': '★ Başarı ölçütleri (MAPE ≤ %10)',

    # docs
    'docs/KOD_ATLASI.md': '★ Her modül + her sayının kaynağı',
    'docs/YAPI_AGACI.md': '★ Bu ağaç (bu dosya)',
    'docs/MODEL_PROVENANCE.md': 'Model kaynak envanteri',
    'docs/model_provenance.json': 'Aynı, makine okunur',
    'docs/FULL_TECHNICAL_AUDIT.md': 'Tam teknik denetim bulguları',
    'docs/SECURITY_AUDIT.md': 'Güvenlik denetimi',
    'docs/COMMERCIAL_READINESS.md': 'Ticarileşme hazırlık değerlendirmesi',

    # data
    'data/archive/synthetic_demo/OKU.md': '⚠️ Bu veri GERÇEK DEĞİL — kanıtıyla',
}

SKIP_DIRS = {'.git', '__pycache__', '.pytest_cache', '.ruff_cache',
             'archive', 'node_modules', '.mypy_cache'}
SKIP_EXT = {'.pyc', '.pyo'}


def module_purpose(p: Path) -> str:
    """Docstring'in ilk anlamlı satırı."""
    try:
        tree = ast.parse(p.read_text(encoding='utf-8', errors='ignore'))
        doc = ast.get_docstring(tree)
        if not doc:
            return ''
        for ln in doc.split('\n'):
            ln = ln.strip()
            if ln and not ln.startswith('═') and not ln.startswith('─'):
                return ln.replace('GreenWing Analytics — ', '')[:80]
    except Exception:
        return ''
    return ''


def human(n: int) -> str:
    return f'{n:,}'.replace(',', '.')


def build() -> list[str]:
    out: list[str] = []
    stats = {'py': 0, 'lines': 0, 'files': 0}
    all_py = [p for p in ROOT.rglob('*.py')
              if not any(s in p.parts for s in SKIP_DIRS)]
    for p in all_py:
        try:
            stats['lines'] += len(p.read_text(encoding='utf-8',
                                              errors='ignore').split('\n'))
            stats['py'] += 1
        except Exception:
            pass

    def walk(d: Path, prefix: str = '', depth: int = 0) -> None:
        if depth > 6:
            return
        try:
            items = sorted(d.iterdir(),
                           key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return
        items = [i for i in items
                 if i.name not in SKIP_DIRS
                 and i.suffix not in SKIP_EXT
                 and not i.name.startswith('.pytest')
                 and i.name != '.git']
        for i, item in enumerate(items):
            last = i == len(items) - 1
            branch = '└── ' if last else '├── '
            rel = item.relative_to(ROOT).as_posix()
            if item.is_dir():
                n = len([x for x in item.rglob('*') if x.is_file()])
                out.append(f'{prefix}{branch}{item.name}/'
                           + (f'   ({n} dosya)' if depth < 2 else ''))
                walk(item, prefix + ('    ' if last else '│   '), depth + 1)
            else:
                stats['files'] += 1
                desc = DESC.get(rel) or module_purpose(item)
                if item.suffix not in ('.py', '.md', '.yaml', '.yml',
                                       '.csv', '.json', '.txt', '.sh',
                                       '.html', '.pdf'):
                    continue
                size = ''
                if item.suffix in ('.pdf', '.json'):
                    kb = item.stat().st_size / 1024
                    size = f' [{kb:.0f} KB]'
                line = f'{prefix}{branch}{item.name}{size}'
                if desc:
                    line += f'  — {desc}'
                out.append(line)

    walk(ROOT)
    return out, stats


if __name__ == '__main__':
    lines, st = build()
    header = [
        '# GreenWing Analytics — Proje Yapı Ağacı',
        '',
        f'> Otomatik üretildi: `python tools/build_tree.py`  ',
        f'> **{st["files"]} dosya** · **{st["py"]} Python modülü** · '
        f'**{human(st["lines"])} satır kod**',
        '',
        '**İşaretler:** ★ = kritik dosya · ⚠️ = dikkat · '
        '(0 byte) = silinecek',
        '',
        '```',
    ]
    footer = ['```', '']
    body = header + lines + footer

    if '--md' in sys.argv:
        outp = ROOT / 'docs' / 'YAPI_AGACI.md'
        outp.write_text('\n'.join(body), encoding='utf-8')
        print(f'✓ {outp} ({len(body)} satır)')
    else:
        print('\n'.join(body))
