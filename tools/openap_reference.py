"""
OpenAP tabanlı GERÇEK referans üreteci
======================================

NE YAPAR
--------
Her uçak tipi için, TU Delft'in açık kaynak OpenAP modelini (gerçek ADS-B
uçuş verisinden türetilmiş drag polar + ICAO Emisyon Veritabanı tabanlı
motor yakıt modeli) kullanarak cruise yakıt akışını ve kg/nm'yi hesaplar.

NEDEN
-----
Projenin kendi yakıt modelini doğrulamak için BAĞIMSIZ bir referans
gerekiyordu. Bu araç o referansı üretir: aynı fizik (aynı drag polar
yapısı, aynı thrust dengesi) ama BAĞIMSIZ kaynaktan gelen katsayılarla.

KAYNAKLAR (hepsi açık, lisans kısıtı yok)
-----------------------------------------
  • OpenAP  : https://github.com/junzis/openap  (TU Delft, Sun & Hoekstra)
              - data/aircraft/<type>.yml   : kütle, geometri, drag
              - data/fuel/fuel_models.csv  : c1,c2,c3 (ICAO EDB tabanlı)
              - data/engine/engines.csv    : max_thrust (N), ff_to
              - Drag polar YAPISI: CD = CD0 + k·CL²  (BADA 3 ile aynı)
              - Yakıt modeli    : FF[kg/s]/motor =
                                  c1 − exp(−c2·(r·e^(c3·r) − ln(c1)/c2))
                                  burada r = T_motor / T_max_motor
  • ICAO Doc 9889 / EDB : yakıt modelinin kaynağı (OpenAP bunu kullanır)

SINIRLAR (dürüstçe)
-------------------
  • OpenAP bazı tipler için drag polar'ı kardeş tipten devralır
    (örn. a21n drag → a20n). Bu, araçta `drag_from` alanına yazılır.
  • OpenAP bazı tipler için ICAO yakıt katsayısı içermez; bu durumda
    BADA/OpenAP'ın kendi kuralı uygulanır: "default" katsayılar ×
    (motor ff_to oranı). Bu da `fuel_via` alanına yazılır.
  • Boeing/Airbus ACAP'teki kanat açıklığı (winglet dahil) OpenAP'ta
    birkaç tip için farklıdır; kg/nm hesabı bu açıklığa bağlı DEĞİLDİR
    (yalnızca S kullanılır), dolayısıyla sonuç etkilenmez.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'openap'
OUT = ROOT / 'data' / 'openap_reference.json'

# Projede kullanılan ICAO tipi → OpenAP tip kodu
TYPE_MAP = {
    'B738': 'B738', 'B38M': 'B38M', 'A320': 'A320', 'A20N': 'A20N',
    'A321': 'A321', 'A21N': 'A21N', 'B77W': 'B77W', 'B788': 'B788',
    'B789': 'B789', 'A350': 'A359', 'A380': 'A388',
}

# OpenAP uçak dosyalarında 'fuel' bloğu yoksa kullanılacak motor adı.
# Seçim, projedeki engine_type ile BİREBİR aynı motor ailesindendir.
# ÖNEMLİ: OpenAP'ın kendi 'engine.default' değeri bazı tiplerde gerçek
# operatör konfigürasyonundan farklıdır (örn. B788 için Trent 1000 yazar;
# gerçek B788'lerin çoğu GEnx-1B kullanır). Bu yüzden motor seçimi
# OpenAP'a BIRAKILMAZ — projedeki engine_type ile eşleştirilir.
ENGINE_MAP = {
    'B738': 'CFM56-7B26E',
    'B38M': 'LEAP-1B27',       # proje: LEAP-1B
    'A320': 'CFM56-5B4/P',
    'A20N': 'LEAP-1A26/26E1',  # proje: LEAP-1A (OpenAP kaydı)
    'A321': 'V2533-A5',
    'A21N': 'LEAP-1A35A/33/33B2/32/30',  # proje: LEAP-1A
    'B77W': 'GE90-115B',
    'B788': 'GENX-1B70',       # proje: GEnx-1B70 (gerçek B788 motoru)
    'B789': 'GENX-1B70',       # proje: GEnx-1B76 → en yakın DB kaydı
    'A350': 'TRENT XWB-84',    # proje: Trent XWB
    'A380': 'TRENT 970-84',    # proje: Trent 970 (A380-841)
}


def load_data():
    ac, fuel, eng = {}, {}, {}
    for f in (DATA / 'aircraft').glob('*.yml'):
        ac[f.stem.upper()] = yaml.safe_load(f.read_text(encoding='utf-8'))
    for r in csv.DictReader(open(DATA / 'fuel' / 'fuel_models.csv', encoding='utf-8')):
        fuel[r['typecode'].upper()] = (
            float(r['c1']), float(r['c2']), float(r['c3']), r['engine_type'])
    for r in csv.DictReader(open(DATA / 'engine' / 'engines.csv', encoding='utf-8')):
        eng[r['name'].upper()] = r
    # ENGINE_MAP anahtarları da büyük harfe normalize edilir
    for k in list(ENGINE_MAP):
        if ENGINE_MAP[k].upper() not in eng:
            ENGINE_MAP[k] = ENGINE_MAP[k]
    return ac, fuel, eng


def isa(alt_m: float) -> float:
    """ISA yoğunluk (kg/m³). Troposfer formülü (ICAO Doc 7488)."""
    T0, L, R, g = 288.15, 0.0065, 287.05287, 9.80665
    p0 = 101325.0
    T = T0 - L * alt_m
    p = p0 * (T / T0) ** (g / (R * L))
    return p / (R * T)


def tas(mach: float, alt_m: float) -> float:
    """TAS (m/s)."""
    T0, L, R, g = 288.15, 0.0065, 287.05287, 9.80665
    T = T0 - L * alt_m
    a = math.sqrt(1.4 * R * T)
    return mach * a


def model(ac: str):
    """Tek tip için referans yakıt akışı (kg/h) ve kg/nm."""
    aircraft, fuel, eng = load_data()
    tc = TYPE_MAP[ac]
    a = aircraft[tc]
    dr = a['drag']
    S = float(a['wing']['area'])
    oew, mtow = float(a['oew']), float(a['mtow'])
    mach = float(a['cruise']['mach'])
    n_eng = int(a['engine']['number'])

    # Referans ağırlık: OEW + %75 (MTOW−OEW) — açıkça belgelenmiş varsayım
    W = oew + 0.75 * (mtow - oew)

    alt_m = 35000 * 0.3048      # FL350
    rho = isa(alt_m)
    V = tas(mach, alt_m)
    q = 0.5 * rho * V * V
    CL = W * 9.80665 / (q * S)
    CD = dr['cd0'] + dr['k'] * CL * CL
    D = q * S * CD

    # Motor adı: önce uçak dosyasındaki 'engine.default', sonra ENGINE_MAP
    eng_name = ENGINE_MAP.get(tc, '').upper()
    if eng_name not in eng:
        eng_name = ((a.get('engine') or {}).get('default') or '').upper()
    e = eng.get(eng_name)
    if e is None:
        return None

    Tmax = float(e['max_thrust'])       # N
    T_eng = D / n_eng
    ratio = T_eng / Tmax

    if tc in fuel:
        c1, c2, c3, src_eng = fuel[tc]
        scale, fuel_via = 1.0, f'doğrudan ({src_eng})'
    else:
        c1, c2, c3, _ = fuel['DEFAULT']
        scale = float(e['ff_to'])
        fuel_via = f'default × ff_to({eng_name})'

    ff_eng = scale * (c1 - math.exp(
        -c2 * (ratio * math.exp(c3 * ratio) - math.log(c1) / c2)))
    ff = ff_eng * n_eng * 3600.0
    kpnm = ff / (V * 1.94384)

    return dict(
        ac=ac, openap_type=tc, S=S, cd0=dr['cd0'], k=dr['k'],
        e_polar=dr.get('e'), mach=mach, W=W, CL=CL, CD=CD,
        L_D=CL / CD, T_eng_N=T_eng, Tmax_N=Tmax, ratio=ratio,
        ff_kg_hr=ff, kg_per_nm=kpnm, fuel_via=fuel_via,
    )


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    print(f"{'AC':>5} {'cd0':>6} {'k':>5} {'L/D':>5} {'r':>5} "
          f"{'FF kg/h':>8} {'kg/nm':>7}  fuel_via")
    for ac in TYPE_MAP:
        r = model(ac)
        if r is None:
            print(f"{ac:>5}  — motor verisi eksik")
            continue
        rows.append(r)
        print(f"{r['ac']:>5} {r['cd0']:>6.3f} {r['k']:>5.3f} {r['L_D']:>5.1f} "
              f"{r['ratio']:>5.3f} {r['ff_kg_hr']:>8.0f} {r['kg_per_nm']:>7.2f}  {r['fuel_via']}")
    OUT.write_text(json.dumps({'source': 'OpenAP v3 (TU Delft) — drag polar + ICAO EDB fuel model',
                               'alt_ft': 35000, 'ref_weight': 'OEW + 0.75*(MTOW-OEW)',
                               'rows': rows}, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n→ {OUT}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
