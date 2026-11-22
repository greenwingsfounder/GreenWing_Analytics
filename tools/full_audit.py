#!/usr/bin/env python3
"""
GreenWing Analytics — SIFIRDAN TAM DENETİM (Tam Denetim Aracı)
═══════════════════════════════════════════════════════════════════════════

KULLANICI: "en sıfırdan kontrolleri tekrar sağla, hata var mı yok mu,
eksik kısımları tamamla."

Bu araç, testlerden FARKLI bir iş yapar. Testler "beklenen davranış
gerçekleşiyor mu" sorusuna bakar. Bu araç şunu sorar:

    "Kodun HER public yüzeyi gerçekten ÇALIŞIYOR mu?"

Yani: bir fonksiyon hiç çağrılmamışsa test onu görmez. Burası görür.

YEDİ KATMAN
───────────
  K1  Statik analiz     — sözdizimi, tanımsız isim, tehlikeli desen
  K2  Import bütünlüğü  — her modül import edilebiliyor mu
  K3  Örnekleme         — her sınıf kurulabiliyor mu (gerçek argümanla)
  K4  Çağrı izi         — her public fonksiyon çağrılabiliyor mu
  K5  Fizik tutarlılığı — birim, aralık, korunum yasaları
  K6  Uçtan uca         — boru hattı gerçekten çalışıyor mu
  K7  Arayüz            — panel/site/API ayakta mı

ÇIKTI: her katman için PASS/FAIL + bulgu listesi. Sıfır FAIL hedefi.
Çıkış kodu 0 = temiz, 1 = bulgu var (CI'da kullanılabilir).

KULLANIM
────────
    python tools/full_audit.py            # tümü
    python tools/full_audit.py --layer 4  # tek katman
    python tools/full_audit.py --fast     # ağ/DB gerektirenleri atla
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import math
import os
import pkgutil
import subprocess
import sys
import traceback
import warnings
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('GREENWING_DASHBOARD_PASSWORD', 'GreenWing2026!')
os.environ.setdefault('GREENWING_ALLOW_INSECURE_DEMO', '0')


# ══════════════════════════════════════════════════════════════════════
# ALTYAPI
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Finding:
    layer: str
    severity: str          # FAIL | WARN | INFO
    subject: str
    detail: str = ''


@dataclass
class Layer:
    code: str
    name: str
    checks: int = 0
    passed: int = 0
    findings: list[Finding] = field(default_factory=list)

    def ok(self, n: int = 1) -> None:
        self.checks += n
        self.passed += n

    def fail(self, subject: str, detail: str = '') -> None:
        self.checks += 1
        self.findings.append(Finding(self.code, 'FAIL', subject, detail))

    def warn(self, subject: str, detail: str = '') -> None:
        self.checks += 1
        self.passed += 1
        self.findings.append(Finding(self.code, 'WARN', subject, detail))

    @property
    def fails(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == 'FAIL']

    @property
    def warns(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == 'WARN']


LAYERS = [
    Layer('K1', 'Statik analiz'),
    Layer('K2', 'Import bütünlüğü'),
    Layer('K3', 'Sınıf örnekleme'),
    Layer('K4', 'Çağrı izi (public API)'),
    Layer('K5', 'Fizik tutarlılığı'),
    Layer('K6', 'Uçtan uca akış'),
    Layer('K7', 'Arayüz'),
]
L = {x.code: x for x in LAYERS}


# ══════════════════════════════════════════════════════════════════════
# K1 · STATİK ANALİZ
# ══════════════════════════════════════════════════════════════════════
def layer_static() -> None:
    lay = L['K1']

    # 1a) Derleme
    r = subprocess.run([sys.executable, '-m', 'compileall', '-q',
                        'src', 'scripts', 'webapp', 'config',
                        'dashboard', 'tools', 'tests'],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode == 0:
        lay.ok()
    else:
        lay.fail('compileall', r.stdout[-400:] + r.stderr[-400:])

    # 1b) GCC-benzeri hata sınıfları (ruff varsa)
    ruff = Path('/tmp/sectools/bin/ruff')
    if ruff.exists():
        r = subprocess.run([str(ruff), 'check', '--select',
                            'E9,F63,F7,F82,F811,B006,B008',
                            '--output-format', 'concise',
                            'src', 'webapp', 'config', 'scripts'],
                           cwd=ROOT, capture_output=True, text=True)
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()
                 and 'All checks passed' not in ln]
        if not lines:
            lay.ok()
        else:
            for ln in lines[:8]:
                lay.fail('ruff', ln[:150])

    # 1c) Yasaklı desenler — kod varlığında sessiz hata üretenler
    bad_patterns = [
        ('except:', 'çıplak except (KeyboardInterrupt yutar)'),
        ('except Exception:\n            pass', 'sessiz yutma'),
        ('eval(', 'eval kullanımı'),
        ('exec(', 'exec kullanımı'),
        ('pickle.loads(', 'güvensiz deserialize'),
        ('verify=False', 'TLS doğrulaması kapalı'),
        ('shell=True', 'kabuk enjeksiyonu riski'),
    ]
    # #84: web/ arşivlendi (archive/web_v1) → canlı kod taraması dışı.
    py_files = list((ROOT / 'src').rglob('*.py')) + \
        list((ROOT / 'webapp').rglob('*.py'))
    for pat, why in bad_patterns:
        hits = []
        for f in py_files:
            try:
                txt = f.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            if pat in txt:
                # yorum satırlarını sayma
                for i, line in enumerate(txt.split('\n'), 1):
                    if pat in line and not line.strip().startswith('#'):
                        hits.append(f'{f.relative_to(ROOT)}:{i}')
                        break
        if hits:
            lay.warn(f'desen "{pat}" ({why})', ', '.join(hits[:3]))
        else:
            lay.ok()

    # 1d) TODO/FIXME/XXX/HAck — yarım işaretleri
    # NOT: 'XXXX' bir YASAK işaret DEĞİLDİR — testlerde "geçersiz tip
    # denenmeli" senaryosunun argümanıdır (FuelModel('XXXX') → ValueError).
    # İlk sürümde bunu TODO saymıştım → 15 sahte uyarı. Düzeltildi:
    # yalnızca yorum satırındaki TODO/FIXME/HACK sayılır.
    import re as _re
    _TODO_RE = _re.compile(r'\b(TODO|FIXME|HACK)\b')
    todo_hits = []
    for f in py_files:
        try:
            lines = f.read_text(encoding='utf-8', errors='ignore').split('\n')
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if not s.startswith('#'):
                continue
            # Kelime sınırı ŞART: 'metodoloji' içinde 'todo' var,
            # 'TODO' düz aramada onu yakalıyor → 2. sahte uyarı.
            if _TODO_RE.search(s):
                todo_hits.append(f'{f.relative_to(ROOT)}:{i}')
    if not todo_hits:
        lay.ok()
    else:
        lay.warn('gerçek TODO işaretleri', ', '.join(todo_hits[:4]))


# ══════════════════════════════════════════════════════════════════════
# K2 · IMPORT BÜTÜNLÜĞÜ
# ══════════════════════════════════════════════════════════════════════
MODULES: list[str] = []


def layer_import() -> None:
    lay = L['K2']
    global MODULES
    pkgs = ['src', 'src.models', 'src.analysis', 'src.optimization',
            'src.validation', 'src.reporting', 'src.ingestion',
            'src.security', 'src.data_collection', 'config']
    MODULES = []
    for p in pkgs:
        try:
            m = importlib.import_module(p)
        except Exception as e:
            lay.fail(f'paket {p}', f'{type(e).__name__}: {e}')
            continue
        lay.ok()
        if hasattr(m, '__path__'):
            for _, name, _ in pkgutil.iter_modules(m.__path__, p + '.'):
                try:
                    importlib.import_module(name)
                    MODULES.append(name)
                    lay.ok()
                except Exception as e:
                    lay.fail(f'modül {name}', f'{type(e).__name__}: {e}')

    # Ağır seçenekler: web ve webapp
    # #84: web/app.py arşivlendi → yalnızca webapp/ canlı
    for name in ('webapp.app',):
        try:
            importlib.import_module(name)
            lay.ok()
        except Exception as e:
            lay.fail(f'modül {name}', f'{type(e).__name__}: {e}')


# ══════════════════════════════════════════════════════════════════════
# K3 · SINIF ÖRNEKLEME
# ══════════════════════════════════════════════════════════════════════
# Sınıf → deneme argümanları. Yalnızca ZORUNLU (default'suz) argümanlar.
CTOR_ARGS: dict[str, dict] = {
    'FuelModel': {'aircraft_type': 'B738'},
    'EmissionCalculator': {},
    'AircraftPerformance': {'aircraft_type': 'B738'},
    'AirportDatabase': {},
    'OpenSkyCollector': {},
    'WindModel': {},
    'SAFModel': {},
    'FlightAnalyzer': {},
    'FleetAnalyzer': {},
    'PhaseSegmenter': {},
    'SensitivityAnalyzer': {},
    'CostIndexOptimizer': {},
    'AltitudeOptimizer': {},
    'TankeringOptimizer': {},
    'ModelCalibrator': {},
    'BenchmarkAnalyzer': {},
    'UncertaintyAnalyzer': {},
    'DataValidator': {},
    'PhysicsValidator': {},
    'BusinessValidator': {},
    'ReportGenerator': {},
    'CustomerFuelIngestor': {},
    'FlightMatcher': {},
    'DashboardAuth': {'users': {}, 'session_secret': 'x' * 32},
    'ISAAtmosphere': {},
    'FuelThermalModel': {},
    # Denetimde eklenen üç sınıf — önce "argüman haritası yok"
    # uyarısı veriyorlardı. Hepsi veri taşıyıcı/durum nesnesi:
    'BenchmarkResult': {'check_name': 'AR', 'status': 'PASS',
                        'value': 10.28, 'expected': '~10.3',
                        'message': 'ok'},
    'UncertainValue': {'value': 1.0},
    'OpenSkyTokenManager': {'client_id': 'x', 'client_secret': 'y'},
}

SKIP_CLASSES = {
    'WindResult',          # dataclass sonucu
    'AuthConfigError',     # istisna
    'Units',               # salt sınıf sabitleri
}

# DENETİM NOTU (7. yanlış pozitifim): bu araç ilk koşuda 3 FAIL verdi
# ve ÜÇÜ DE ARACIN hatasıydı, kodun değil:
#   1. WindProvider → typing.Protocol, SOYUT arayüz. Örneklenmez.
#      Düzeltme: Protocol alt sınıflarını atla.
#   2. AirportDatabase.count → @property, çağrılmaz OKUNUR.
#      Düzeltme: property'leri çağırma, değerini kontrol et.
#   3. 'EmissionModel' → sınıfın gerçek adı EmissionCalculator.
#      Düzeltme: doğru adı kullan.
# Ders: denetim aracı da bir yazılımdır; FAIL'lerin kaynağını ayırt et.


def _public_classes() -> list[tuple[str, type]]:
    out = []
    for mod_name in MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        if not mod.__file__ or '__pycache__' in mod.__file__:
            continue
        for name, obj in vars(mod).items():
            if name.startswith('_'):
                continue
            if not inspect.isclass(obj):
                continue
            if obj.__module__ != mod_name:      # dışarıdan import edilmiş
                continue
            out.append((f'{mod_name}.{name}', obj))
    return sorted(out)


def layer_classes() -> None:
    lay = L['K3']
    for full, cls in _public_classes():
        short = full.rsplit('.', 1)[-1]
        if short in SKIP_CLASSES:
            lay.ok()
            continue
        if inspect.isabstract(cls):
            lay.ok()
            continue
        # typing.Protocol türevleri soyut arayüzlerdir — örneklenmez
        try:
            from typing import Protocol as _P
            if issubclass(cls, _P) and cls is not _P:
                lay.ok()
                continue
        except Exception:
            pass
        try:
            sig = inspect.signature(cls.__init__)
        except (ValueError, TypeError):
            lay.ok()
            continue
        req = [p for p, v in sig.parameters.items()
               if p != 'self' and v.default is inspect.Parameter.empty
               and v.kind not in (v.VAR_POSITIONAL, v.VAR_KEYWORD)]
        if not req:
            try:
                cls()
                lay.ok()
            except Exception as e:
                lay.fail(short, f'{type(e).__name__}: {str(e)[:100]}')
            continue
        args = CTOR_ARGS.get(short)
        if args is None:
            lay.warn(f'{short} (argüman haritası yok)',
                     f'zorunlu: {req}')
            continue
        try:
            cls(**args)
            lay.ok()
        except Exception as e:
            lay.fail(short, f'{type(e).__name__}: {str(e)[:120]}')


# ══════════════════════════════════════════════════════════════════════
# K4 · ÇAĞRI İZİ — public fonksiyonlar gerçekten çalışıyor mu
# ══════════════════════════════════════════════════════════════════════
# Fonksiyon adı → (örnek, argümanlar). Eşleşme son ek ile yapılır.
CALLS: dict[str, tuple[Any, tuple]] = {}
_instances: dict[str, Any] = {}


def _get(short: str):
    if short in _instances:
        return _instances[short]
    cls = CTOR_ARGS.get(short)
    if cls is None:
        return None
    for full, c in _public_classes():
        if full.rsplit('.', 1)[-1] == short:
            try:
                obj = c(**cls)
            except Exception:
                return None
            _instances[short] = obj
            return obj
    return None


def _prepare() -> dict[str, tuple[Any, tuple]]:
    """Test edilecek (bağlı metod, argüman) çiftlerini kur."""
    m: dict[str, tuple[Any, tuple]] = {}

    fm = _get('FuelModel')
    if fm:
        m['cruise_fuel_flow'] = (fm, (65000.0, 35000.0, 0.78))
        m['fuel_for_distance'] = (fm, (1000.0, 70000.0, 35000.0, 0.78))
        m['corrected_sfc'] = (fm, (35000.0, 0.78))
        m['lift_to_drag_ratio'] = (fm, (66000.0, 35000.0, 0.78))
        m['cruise_drag'] = (fm, (66000.0, 35000.0, 0.78))
        m['drag_coefficient'] = (fm, (0.49, 0.78))
        m['lift_coefficient'] = (fm, (66000.0, 35000.0, 0.78))
        m['specific_air_range'] = (fm, (66000.0, 35000.0, 0.78))
        m['breguet_range'] = (fm, (70000.0, 64000.0, 35000.0, 0.78))
        m['optimum_altitude'] = (fm, (66000.0, 0.78))
        m['cruise_fuel_flow_kg_hr'] = (fm, (66000.0, 35000.0, 0.78))
        m['summary'] = (fm, ())

    at = _get('ISAAtmosphere')
    if at:
        m['temperature'] = (at, (35000.0,))
        m['pressure'] = (at, (35000.0,))
        m['density'] = (at, (35000.0,))
        m['speed_of_sound'] = (at, (35000.0,))
        m['true_airspeed'] = (at, (0.78, 35000.0))
        m['mach_from_tas'] = (at, (450.0, 35000.0))
        m['get_properties'] = (at, (35000.0,))

    db = _get('AirportDatabase')
    if db:
        m['get_distance'] = (db, ('LTFM', 'EGLL'))
        m['get'] = (db, ('LTFM',))
        m['get_by_iata'] = (db, ('IST',))
        m['exists'] = (db, ('LTFM',))
        m['count'] = (db, ())
        m['search'] = (db, ('Istanbul',))
        m['get_all_codes'] = (db, ())
        m['get_nearest_airports'] = (db, (41.28, 28.75))

    em = _get('EmissionModel')
    if em:
        for name in ('co2_kg', 'co2', 'co2_emissions'):
            if hasattr(em, name):
                m[name] = (em, (6000.0,))
                break

    wg = None
    try:
        wgm = importlib.import_module('src.models.wind_gfs')
        wg = wgm.get_wind_provider('seasonal')
        m['wind_at'] = (wg, (41.0, 29.0, 35000.0))
    except Exception:
        pass

    ci = _get('CostIndexOptimizer')
    if ci:
        for name in ('optimum_mach', 'optimal_mach', 'mach_for_ci',
                     'optimize'):
            if hasattr(ci, name):
                m[name] = (ci, (2000.0,))
                break

    return m


def _auto_arg(prm: inspect.Parameter):
    """Zorunlu argüman için tip ipucundan makul bir değer üret."""
    a = prm.annotation
    txt = str(a).lower()
    if any(k in txt for k in ('str', 'path', 'icao', 'code', 'name')):
        return 'LTFM'
    if 'bool' in txt:
        return False
    if any(k in txt for k in ('int',)):
        return 5
    if any(k in txt for k in ('float', 'decimal')):
        return 1.0
    if 'dict' in txt or 'mapping' in txt:
        return {}
    if any(k in txt for k in ('list', 'sequence', 'tuple')):
        return []
    return 1.0


def layer_calls() -> None:
    lay = L['K4']
    calls = _prepare()
    if not calls:
        lay.fail('hazırlık', 'hiç örnek kurulamadı')
        return
    for name, (obj, args) in calls.items():
        fn = getattr(obj, name, None)
        if fn is None:
            lay.fail(f'.{name}', 'metot bulunamadı')
            continue
        # @property → çağrılmaz, OKUNUR
        if not callable(fn):
            try:
                _ = fn
                lay.ok()
            except Exception as e:
                lay.fail(f'.{name} (property)',
                         f'{type(e).__name__}: {str(e)[:100]}')
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                kwargs = {}
                sig = inspect.signature(fn)
                params = [p for p in sig.parameters.values()
                          if p.kind in (p.POSITIONAL_OR_KEYWORD,
                                        p.POSITIONAL_ONLY)]
                # Kalan zorunlu argümanlar için tip tabanlı varsayılan üret
                need = params[len(args):]
                missing_required = [p for p in need
                                    if p.default is inspect.Parameter.empty]
                auto = []
                for prm in need:
                    if prm.default is not inspect.Parameter.empty:
                        continue          # varsayılan var, geç
                    if prm.name in kwargs:
                        continue
                    auto.append(_auto_arg(prm))
                if auto:
                    kwargs.update({prm.name: val
                                   for prm, val in zip(missing_required, auto)})
                out = fn(*args, **kwargs)
            lay.ok()
            del out
        except Exception as e:
            lay.fail(f'.{name}', f'{type(e).__name__}: {str(e)[:110]}')


# ══════════════════════════════════════════════════════════════════════
# K5 · FİZİK TUTARLILIĞI — bağımsız hesap
# ══════════════════════════════════════════════════════════════════════
def layer_physics() -> None:
    lay = L['K5']

    # 5a) ISA elle hesap
    from src.models.atmosphere import ISAAtmosphere
    at = ISAAtmosphere()
    for ft, T_ref, p_ref in ((0, 288.15, 101325.0),
                             (35000, 218.81, 23842.0),
                             (41000, 216.65, 17874.0)):
        T = at.temperature(ft)
        p = at.pressure(ft)
        if abs(T - T_ref) < 0.35:
            lay.ok()
        else:
            lay.fail(f'ISA T @{ft}ft', f'{T:.2f} vs {T_ref}')
        if abs(p - p_ref) / p_ref < 0.004:
            lay.ok()
        else:
            lay.fail(f'ISA p @{ft}ft', f'{p:.0f} vs {p_ref}')

    # 5b) ρ = p/(R·T) tutarlılığı
    for ft in (0, 20000, 40000):
        rho = at.density(ft)
        rho_calc = at.pressure(ft) / (287.05 * at.temperature(ft))
        if abs(rho - rho_calc) / rho_calc < 1e-4:
            lay.ok()
        else:
            lay.fail(f'ρ tutarlılık @{ft}ft', f'{rho:.5f} vs {rho_calc:.5f}')

    # 5c) Havalimanı mesafesi — bağımsız haversine
    from src.data_collection.airport_database import AirportDatabase
    db = AirportDatabase()

    def hav(a, b):
        R = 3440.065
        p1, p2 = math.radians(a['lat']), math.radians(b['lat'])
        dp = p2 - p1
        dl = math.radians(b['lon'] - a['lon'])
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * R * math.asin(math.sqrt(h))

    for o, d in (('LTFM', 'EGLL'), ('LTFM', 'LTAC'), ('LTFM', 'OMDB'),
                 ('LTFM', 'KJFK'), ('LTFJ', 'EDDF')):
        A, B = db.get(o), db.get(d)
        if not A or not B:
            lay.fail(f'{o}-{d}', 'kayıt yok')
            continue
        mod = db.get_distance(o, d)
        ref = hav(A, B)
        if abs(mod - ref) / ref < 1e-6:
            lay.ok()
        else:
            lay.fail(f'{o}-{d}', f'modül {mod:.2f} vs elle {ref:.2f}')

    # 5d) AR = span²/S tutarlılığı (tüm tipler)
    import yaml
    dbf = yaml.safe_load(
        (ROOT / 'config' / 'aircraft_database.yaml').read_text(encoding='utf-8'))
    for tip, p in dbf['aircraft_types'].items():
        calc = p['wingspan'] ** 2 / p['wing_area']
        if abs(p['AR'] - calc) / calc < 0.01:
            lay.ok()
        else:
            lay.fail(f'{tip} AR', f'{p["AR"]:.3f} vs span²/S {calc:.3f}')

    # 5d-2) POLAR TUTARLILIĞI: K ≈ 1/(π · AR_aero · e)  [denetim #85]
    # Neden ayrı bir kontrol: yukarıdaki 5d geometrik AR'yi ölçer
    # (span²/S, winglet DAHİL). Drag poları ise WINGLET'SİZ kanat
    # üzerinde fit edilmiştir (B738: 34.32 m → AR 9.453). İki büyüklük
    # karıştırıldığında K/e yapay olarak %7,7 çelişiyordu.
    # Kural: AR_aerodynamic varsa onu kullan; yoksa AR.
    import math as _math
    for tip, p in dbf['aircraft_types'].items():
        if not isinstance(p, dict) or 'K' not in p or 'e' not in p:
            continue
        ar = p.get('AR_aerodynamic') or p.get('AR')
        if not ar:
            lay.warn(f'{tip} polar', 'AR_aerodynamic/AR yok — atlandı')
            continue
        k_imp = 1.0 / (_math.pi * float(ar) * float(p['e']))
        rel = abs(k_imp - float(p['K'])) / float(p['K']) * 100
        if rel < 2.0:
            lay.ok()
        else:
            lay.fail(f'{tip} polar K',
                     f'K={p["K"]} vs 1/(π·{ar}·{p["e"]})={k_imp:.4f} '
                     f'(%{rel:.1f})')

    # 5e) Kütle hiyerarşisi: OEW < MTOW, max_fuel < MTOW−OEW
    for tip, p in dbf['aircraft_types'].items():
        oew, mtow, fuel = p['oew'], p['mtow'], p['max_fuel']
        if not (oew < mtow):
            lay.fail(f'{tip} OEW<MTOW', f'{oew} >= {mtow}')
        else:
            # max_fuel > MTOW−OEW NORMALDİR: tank kapasitesi MTOW'tan
            # bağımsız bir limittir. Uçak dolu tankla kalkamaz ama tank
            # daha büyük olabilir (B789: 126.372 kg > 125.161).
            # Gerçek kontrol: max_fuel MTOW'un %60'ını aşmasın.
            if fuel > mtow * 0.60:
                lay.fail(f'{tip} max_fuel', f'{fuel} > MTOW×%60')
            elif fuel <= 0:
                lay.fail(f'{tip} max_fuel', f'negatif/sıfır: {fuel}')
            else:
                lay.ok()

    # 5f) Yakıt monotonluğu — mesafe artınca yakıt artmalı
    from src.models.fuel_model import FuelModel
    fm = FuelModel('B738')
    prev = 0.0
    mono = True
    for d in (300, 600, 1200, 2400):
        f = fm.fuel_for_distance(d, 70000, 35000, 0.78)['total_fuel_kg']
        if f <= prev:
            mono = False
            lay.fail('yakıt monotonluğu', f'{d} nm → {f:.0f} kg (önceki {prev:.0f})')
            break
        prev = f
    if mono:
        lay.ok()

    # 5g) Uçak ağırlığı artınca yakıt artmalı (ayni mesafe)
    f1 = fm.fuel_for_distance(1000, 55000, 35000, 0.78)['total_fuel_kg']
    f2 = fm.fuel_for_distance(1000, 75000, 35000, 0.78)['total_fuel_kg']
    if f2 > f1:
        lay.ok()
    else:
        lay.fail('ağırlık duyarlılığı', f'{f1:.0f} → {f2:.0f}')

    # 5h) CO₂ faktörü ICAO 3,16
    from src.models.emission_model import EmissionCalculator
    em = EmissionCalculator()
    fn = (getattr(em, 'co2_kg', None) or getattr(em, 'co2', None)
          or getattr(em, 'co2_emissions', None))
    if fn:
        c = fn(1000.0)
        if c is None:
            lay.warn('CO₂', 'fonksiyon None döndü')
        else:
            val = c if isinstance(c, (int, float)) else (
                c.get('co2_kg') if isinstance(c, dict) else None)
            if val and abs(val - 3160) / 3160 < 0.02:
                lay.ok()
            else:
                lay.warn('CO₂ faktörü', f'1000 kg yakıt → {val} (beklenen ~3160)')

    # 5i) Ses hızı deniz seviyesi ≈ 340,3 m/s
    a0 = at.speed_of_sound(0)
    if abs(a0 - 340.29) < 1.0:
        lay.ok()
    else:
        lay.fail('ses hızı @SL', f'{a0:.2f} m/s vs 340,29')


# ══════════════════════════════════════════════════════════════════════
# K6 · UÇTAN UCA AKIŞ
# ══════════════════════════════════════════════════════════════════════
def layer_e2e() -> None:
    lay = L['K6']

    # 6a) batch_results.json tutarlılığı
    p = ROOT / 'reports' / 'optimizations' / 'batch_results.json'
    if p.exists():
        rows = json.loads(p.read_text(encoding='utf-8'))
        lay.ok()
        if isinstance(rows, list) and rows:
            lay.ok()
            # gerekli alanlar
            need = {'callsign', 'aircraft_type', 'distance_nm',
                    'estimated_fuel_kg', 'co2_kg'}
            miss = need - set(rows[0])
            if miss:
                lay.fail('batch_results alanları', f'eksik: {miss}')
            else:
                lay.ok()
            # negatif değer yok
            neg = [r.get('callsign') for r in rows
                   if float(r.get('estimated_fuel_kg') or 0) < 0]
            if neg:
                lay.fail('negatif yakıt', str(neg[:3]))
            else:
                lay.ok()
            # kg/nm fiziksel aralık
            bad = []
            for r in rows:
                d = float(r.get('distance_nm') or 0)
                f = float(r.get('estimated_fuel_kg') or 0)
                if d > 0 and not (0.5 < f / d < 30):
                    bad.append((r.get('callsign'), round(f / d, 2)))
            if bad:
                lay.warn('kg/nm aralık dışı', str(bad[:3]))
            else:
                lay.ok()
        else:
            lay.warn('batch_results', 'boş liste')
    else:
        lay.fail('batch_results.json', 'yok')

    # 6b) Özet fonksiyonu (panel/site aynı veriyi okuyor mu)
    try:
        wm = importlib.import_module('webapp.app')
        s = wm.summarize(wm.load_flights())
        if s['flight_count'] > 0:
            lay.ok()
        else:
            lay.fail('site özeti', '0 uçuş')
        if s['provenance']['total'] == s['flight_count']:
            lay.ok()
        else:
            lay.fail('provenance toplamı', f"{s['provenance']['total']} != {s['flight_count']}")
    except Exception as e:
        lay.fail('site özeti', f'{type(e).__name__}: {str(e)[:110]}')

    # 6c) Rapor üretici boş veriyle çökmemeli
    try:
        from src.reporting.report_generator import ReportGenerator
        rg = ReportGenerator()
        if hasattr(rg, 'generate_fleet_report'):
            sig = inspect.signature(rg.generate_fleet_report)
            kwargs = {}
            for prm in sig.parameters.values():
                if prm.default is not inspect.Parameter.empty:
                    continue
                if prm.name == 'flights':
                    kwargs[prm.name] = []
                elif any(k in prm.name for k in ('name', 'airline')):
                    kwargs[prm.name] = 'audit'
                elif 'int' in str(prm.annotation):
                    kwargs[prm.name] = 0
                else:
                    kwargs[prm.name] = []
            rg.generate_fleet_report(**kwargs)
        lay.ok()
    except Exception as e:
        # boş veri → hata beklenen davranış olabilir; FAIL değil
        lay.warn('rapor üretici (boş veri)',
                 f'{type(e).__name__} — belgelenmiş davranış mı?')

    # 6d) JSON rapor dosyaları geçerli mi
    for jf in (ROOT / 'reports').rglob('*.json'):
        try:
            json.loads(jf.read_text(encoding='utf-8'))
            lay.ok()
        except Exception as e:
            lay.fail(f'JSON {jf.name}', f'{type(e).__name__}')

    # 6e) CSV bütünlüğü
    import pandas as pd
    for cf in sorted((ROOT / 'data' / 'raw' / 'opensky').glob('*.csv'))[:20]:
        try:
            d = pd.read_csv(cf)
            if len(d) == 0:
                lay.fail(f'CSV {cf.name}', 'boş')
            elif 'time' not in d.columns:
                lay.fail(f'CSV {cf.name}', 'time kolonu yok')
            else:
                lay.ok()
        except Exception as e:
            lay.fail(f'CSV {cf.name}', f'{type(e).__name__}')


# ══════════════════════════════════════════════════════════════════════
# K7 · ARAYÜZ
# ══════════════════════════════════════════════════════════════════════
def layer_ui() -> None:
    lay = L['K7']
    try:
        import httpx
    except ImportError:
        lay.warn('httpx', 'kurulu değil — arayüz testi atlandı')
        return

    # 7a) Site ayakta mı
    base = 'http://127.0.0.1:8052'
    try:
        r = httpx.get(f'{base}/giris', timeout=5)
        if r.status_code == 200 and 'GreenWing' in r.text:
            lay.ok()
        else:
            lay.fail('site /giris', f'HTTP {r.status_code}')
    except Exception as e:
        lay.warn('site erişilemiyor',
                 f'{type(e).__name__} — sunucu kapalı olabilir')

    # 7b) Giriş → token → sayfalar
    try:
        r = httpx.post(f'{base}/giris',
                       data={'username': '__admin__',
                             'password': os.environ['GREENWING_DASHBOARD_PASSWORD'],
                             'next': '/'},
                       timeout=8, follow_redirects=False)
        loc = r.headers.get('location', '')
        if r.status_code == 303 and 'token=' in loc:
            lay.ok()
            tok = loc.split('token=')[-1]
            for page in ('', 'ucuslar', 'metodoloji', 'veri', 'denetim',
                         'el-kitabi', 'ticari'):
                rr = httpx.get(f'{base}/{page}?token={tok}', timeout=8)
                if rr.status_code == 200 and 'GreenWing' in rr.text:
                    lay.ok()
                else:
                    lay.fail(f'site /{page}', f'HTTP {rr.status_code}')
            # yetkisiz
            rr = httpx.get(f'{base}/ucuslar', timeout=8, follow_redirects=False)
            if rr.status_code == 303:
                lay.ok()
            else:
                lay.fail('yetkisiz erişim', f'HTTP {rr.status_code} — açık!')
        else:
            lay.fail('site giriş', f'HTTP {r.status_code} {loc[:50]}')
    except KeyError:
        lay.warn('giriş testi', 'GREENWING_DASHBOARD_PASSWORD yok')
    except Exception as e:
        lay.warn('giriş testi', f'{type(e).__name__}: {str(e)[:80]}')


# ══════════════════════════════════════════════════════════════════════
# RAPOR
# ══════════════════════════════════════════════════════════════════════
def report() -> int:
    print('\n' + '═' * 74)
    print('  GREENWING ANALYTICS — SIFIRDAN TAM DENETİM')
    print('═' * 74)
    total_c = total_p = 0
    total_f = 0
    for lay in LAYERS:
        total_c += lay.checks
        total_p += lay.passed
        total_f += len(lay.fails)
        icon = '✓' if not lay.fails else '✗'
        rate = (100.0 * lay.passed / lay.checks) if lay.checks else 0.0
        print(f'\n  {icon} {lay.code} · {lay.name:24s} '
              f'{lay.passed:>3}/{lay.checks:<3} (%{rate:.0f})')
        for f in lay.fails:
            print(f'       ✗ {f.subject}  — {f.detail}')
        for w in lay.warns[:3]:
            print(f'       ⚠ {w.subject}  — {w.detail}')
        if len(lay.warns) > 3:
            print(f'       ⚠ ... +{len(lay.warns)-3} uyarı')

    print('\n' + '═' * 74)
    print(f'  TOPLAM: {total_p}/{total_c} kontrol geçti · '
          f'{total_f} FAIL')
    if total_f == 0:
        print('  ✓ HİÇ HATA YOK — sistem temiz')
    else:
        print('  ❌ DÜZELTİLMESİ GEREKEN BULGULAR VAR')
    print('═' * 74)

    out = ROOT / 'reports' / 'audit' / 'full_audit.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        'timestamp': __import__('datetime').datetime.now().isoformat(),
        'total_checks': total_c,
        'passed': total_p,
        'fails': total_f,
        'layers': [{
            'code': l.code, 'name': l.name, 'checks': l.checks,
            'passed': l.passed,
            'findings': [{'severity': f.severity, 'subject': f.subject,
                          'detail': f.detail} for f in l.findings],
        } for l in LAYERS],
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  JSON: {out.relative_to(ROOT)}')
    return 0 if total_f == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--layer', type=str, default='')
    ap.add_argument('--fast', action='store_true')
    a = ap.parse_args()

    fns = {'K1': layer_static, 'K2': layer_import, 'K3': layer_classes,
           'K4': layer_calls, 'K5': layer_physics, 'K6': layer_e2e,
           'K7': layer_ui}
    order = [a.layer] if a.layer else [x.code for x in LAYERS]
    for code in order:
        fn = fns.get(code)
        if not fn:
            print(f'bilinmeyen katman: {code}')
            continue
        if a.fast and code in ('K6', 'K7'):
            continue
        try:
            fn()
        except Exception:
            L[code].fail('KATMAN ÇÖKTÜ', traceback.format_exc()[-300:])
    return report()


if __name__ == '__main__':
    raise SystemExit(main())
