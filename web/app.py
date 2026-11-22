"""
GreenWing Analytics — Yeni Web Paneli (FastAPI)
══════════════════════════════════════════════════

NEDEN YENİ BİR PANEL
--------------------
Eski panel (dashboard/app.py, Dash) şu sorunları taşıyordu:
  • Kimlik doğrulaması YOK — müşteri verisi herkese açık
  • Simüle veri üretiyor (generate_demo_data)
  • Tek dosya, 38 KB, test edilemez
  • Sunucu tarafı oturum yok

Bu panel:
  • Oturum tabanlı kimlik doğrulama (src/security/auth.py)
  • GERÇEK analiz çıktısını okur (reports/optimizations/batch_results.json)
  • Kanıtlanabilir sayılar: her KPI'nın altında kaynak etiketi
  • Mobil uyumlu, erişilebilir (WCAG AA kontrast), klavye gezinmesi
  • JSON API'si ayrı — panel bir istemci, veri katmanı değil

API
---
    GET  /                → panel (giriş gerekli)
    GET  /login           → giriş formu
    POST /login           → kimlik doğrulama
    GET  /logout          → oturum kapat
    GET  /api/summary     → toplam KPI'lar (JSON)
    GET  /api/flights     → uçuş listesi (JSON, sayfalı)
    GET  /api/provenance  → model kaynak matrisi (JSON)
    GET  /healthz         → sağlık kontrolü
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import Cookie, FastAPI, Form, HTTPException, Query, Request, Response  # noqa: E402
from fastapi.responses import (  # noqa: E402
    FileResponse, HTMLResponse, JSONResponse, RedirectResponse,
)
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from src.security.auth import (AuthConfigError, DashboardAuth,  # noqa: E402
                               safe_next_url)

APP_VERSION = '2.0.0'
RESULTS_FILE = ROOT / 'reports' / 'optimizations' / 'batch_results.json'
# Teknik rapor PDF — panelden indirilebilir
REPORT_PDF   = ROOT / 'reports' / 'GreenWing_Teknik_Rapor.pdf'
PROVENANCE_FILE = ROOT / 'docs' / 'model_provenance.json'

app = FastAPI(title='GreenWing Analytics', version=APP_VERSION,
              docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(ROOT / 'web' / 'templates'))

# Statik dosyalar (CSS panelin içinde inline; klasör gelecekteki varlıklar için)
_static = ROOT / 'web' / 'static'
if _static.exists():
    app.mount('/static', StaticFiles(directory=str(_static)), name='static')

_auth: DashboardAuth | None = None


def get_auth() -> DashboardAuth:
    """Kimlik doğrulamayı tembel yükle (import anında hata vermesin)."""
    global _auth
    if _auth is None:
        _auth = DashboardAuth.from_env()
    return _auth


# ── Veri katmanı ──────────────────────────────────────────
_flight_cache: dict[str, Any] = {'mtime': 0.0, 'rows': []}


def load_flights() -> list[dict]:
    """batch_results.json'u oku (mtime değişince yenile)."""
    if not RESULTS_FILE.exists():
        return []
    mtime = RESULTS_FILE.stat().st_mtime
    if _flight_cache['mtime'] != mtime:
        try:
            rows = json.loads(RESULTS_FILE.read_text(encoding='utf-8'))
            _flight_cache['rows'] = rows if isinstance(rows, list) else []
            _flight_cache['mtime'] = mtime
        except json.JSONDecodeError:
            return []
    return _flight_cache['rows']


def summarize(rows: list[dict]) -> dict:
    """Uçuş listesinden KPI özeti — her alan kaynak etiketli."""
    n = len(rows)

    def total(key: str) -> float:
        return sum(float(r.get(key) or 0) for r in rows)

    fuel = total('estimated_fuel_kg')
    dist = total('distance_nm')
    optimal = total('fuel_optimization_kg')
    co2 = total('co2_kg')
    saving = total('total_cost_saving_usd')
    annual = total('annual_realistic_usd')
    # Yıllık ayrıştırma: fiziksel yakıt (tekrarlanabilir) vs tankering
    # (fiyat arbitrajı, %50 sürdürülebilirlik). Bu ayrım olmadan
    # "yıllık tasarruf" rakamı yanıltıcıdır.
    annual_fuel = total('annual_fuel_saving_usd')
    annual_tank = total('annual_tankering_usd')
    co2_pax = [float(r['co2_per_pax_km_g']) for r in rows
               if r.get('co2_per_pax_km_g')]

    # Rota güvenilirliği (route_validity: HIGH/MEDIUM/LOW)
    bench: dict[str, int] = {}
    for r in rows:
        st = str(r.get('route_validity') or 'UNKNOWN').upper()
        bench[st] = bench.get(st, 0) + 1

    # Tasarruf kaynağı ayrıştırması (yakıt vs tankering — KARIŞTIRILMAMALI)
    breakdown = {'altitude_kg': 0.0, 'step_climb_kg': 0.0,
                 'tankering_usd': 0.0, 'fuel_kg_total': 0.0}
    for r in rows:
        sb = r.get('saving_breakdown') or {}
        for k in breakdown:
            breakdown[k] += float(sb.get(k) or 0)

    # ── VERİ KAYNAĞI ŞEFFAFLIĞI ─────────────────────────────
    # Sentetik ve gerçek uçuşları KARIŞTIRIP tek sayı vermek yanıltıcıdır.
    # Panel her zaman hangi verinin gerçek olduğunu göstermelidir.
    provenance: dict[str, int] = {}
    for r in rows:
        m = str(r.get('collection_method') or 'BİLİNMİYOR')
        provenance[m] = provenance.get(m, 0) + 1
    real_count = sum(v for k, v in provenance.items()
                     if k not in ('synthetic_fallback', 'demo', 'BİLİNMİYOR'))
    synthetic_count = provenance.get('synthetic_fallback', 0) + provenance.get('demo', 0)
    unknown_count = provenance.get('BİLİNMİYOR', 0)

    # ── DENETİM #29: BELİRSİZLİK ARALIĞI ────────────────────
    # sensitivity.py ±%26,7 (rüzgâr baskın) hesaplıyor ama panel
    # tek nokta değeri gösteriyordu. Müşteri "$1.4M" rakamını
    # taahhüt sanabilir. Aralık da dönüyor.
    _unc_block: dict = {'available': False,
                        'message': 'uçuş yok — hesaplanamadı'}
    if n > 0:
        try:
            from src.analysis.sensitivity import SensitivityAnalyzer
            _rep = SensitivityAnalyzer().full_sensitivity_report({})
            _pct = float(_rep['total_uncertainty_pct'])
            _unc_block = {
                'available'            : True,
                'total_uncertainty_pct': round(_pct, 1),
                'low_usd'              : round(annual * (1 - _pct / 100.0), 0),
                'high_usd'             : round(annual * (1 + _pct / 100.0), 0),
                'dominant_source'      : _rep['dominant_source'],
                'dominant_effect_pct'  : round(
                    float(_rep['dominant_effect_pct']), 1),
                'note'                 : (
                    f'±%{_pct:.1f} — en büyük belirsizlik: '
                    f'{_rep["dominant_source"]}. Taahhüt değil, aralık.'
                ),
            }
        except Exception as _exc:  # noqa: BLE001
            _unc_block = {'available': False,
                          'message': f'hesaplanamadı: {_exc}'}

    return {
        'flight_count': n,
        'annual_uncertainty': _unc_block,
        'saving_breakdown': {k: round(v, 2) for k, v in breakdown.items()},
        'data_provenance': {
            'real': real_count,
            'synthetic': synthetic_count,
            'unknown': unknown_count,
            'by_method': provenance,
            'is_mixed': real_count > 0 and synthetic_count > 0,
            'is_all_synthetic': synthetic_count == n and n > 0,
            'is_all_real': real_count == n and n > 0,
            'verdict': ('TAMAMEN GERÇEK VERİ' if real_count == n and n > 0
                        else 'TAMAMEN SENTETİK — gösterge amaçlı, taahhüt değil'
                        if synthetic_count == n and n > 0
                        else 'KARIŞIK VERİ — sentetik ve gerçek ayrıştırılmalı'),
        },
        'valid_routes': sum(1 for r in rows
                            if str(r.get('route_validity')).upper() == 'HIGH'),
        'data_quality_note': (rows[0].get('benchmark_status')
                              if rows else None),
        'total_fuel_kg': round(fuel, 1),
        'total_distance_nm': round(dist, 1),
        'fuel_per_nm': round(fuel / dist, 3) if dist else 0.0,
        'optimizable_fuel_kg': round(optimal, 1),
        'optimizable_pct': round(optimal / fuel * 100, 2) if fuel else 0.0,
        'cost_saving_usd': round(saving, 2),
        'annual_realistic_usd': round(annual, 0),
        'annual_fuel_saving_usd': round(annual_fuel, 0),
        'annual_tankering_usd': round(annual_tank, 0),
        'annual_tankering_pct': (round(annual_tank / (annual_fuel + annual_tank) * 100, 1)
                                 if (annual_fuel + annual_tank) else 0.0),
        'co2_kg': round(co2, 1),
        'co2_per_pax_km_g_mean': round(sum(co2_pax) / len(co2_pax), 2) if co2_pax else 0.0,
        'benchmark': bench,
        'aircraft_types': sorted({str(r.get('aircraft_type')) for r in rows
                                  if r.get('aircraft_type')}),
        'data_source': str(RESULTS_FILE.relative_to(ROOT)),
        'flight_date_range': _date_range(rows),
    }


def _date_range(rows: list[dict]) -> dict:
    dates = sorted(str(r.get('flight_date')) for r in rows if r.get('flight_date'))
    if not dates:
        return {'min': None, 'max': None}
    return {'min': dates[0], 'max': dates[-1]}


# ── Yardımcı: oturum ──────────────────────────────────────
def current_user(gw_session: str | None) -> tuple[bool, str | None]:
    try:
        return get_auth().validate_session(gw_session)
    except AuthConfigError:
        return False, None


def auth_failure_response() -> Response:
    return JSONResponse({'error': 'kimlik doğrulama gerekli',
                         'login': '/login'}, status_code=401)


# ── Sayfalar ──────────────────────────────────────────────
@app.get('/rapor.pdf')
def download_report(gw_session: str | None = Cookie(None)):
    """
    Teknik doğrulama raporunu PDF olarak indir.

    Rapor, batch_results.json'dan üretilir; kimlik doğrulaması
    gerektirir çünkü analiz sonuçlarını içerir.
    """
    ok, _user = current_user(gw_session)
    if not ok:
        return RedirectResponse('/login?next=/rapor.pdf', status_code=303)
    if not REPORT_PDF.exists():
        raise HTTPException(
            status_code=404,
            detail='Rapor henüz üretilmemiş. '
                   'tools/build_technical_report.py çalıştırın.',
        )
    return FileResponse(
        REPORT_PDF,
        media_type='application/pdf',
        filename='GreenWing_Teknik_Rapor.pdf',
    )


@app.get('/healthz')
def healthz() -> dict:
    return {'status': 'ok', 'version': APP_VERSION,
            'has_data': RESULTS_FILE.exists()}


LOGIN_HTML = '''<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Giriş — GreenWing Analytics</title>
<style>
:root{--bg:#0b1220;--card:#151f33;--line:#243149;--txt:#e8eefc;--mut:#93a4c4;
--accent:#39d98a;--danger:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;
font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
background:radial-gradient(1200px 600px at 20% -10%,#123,var(--bg));color:var(--txt)}
.card{width:min(380px,92vw);background:var(--card);border:1px solid var(--line);
border-radius:16px;padding:28px;box-shadow:0 20px 60px #0008}
h1{font-size:19px;margin:0 0 4px}
p.sub{color:var(--mut);font-size:13px;margin:0 0 22px}
label{display:block;font-size:12px;color:var(--mut);margin:14px 0 6px;
text-transform:uppercase;letter-spacing:.06em}
input{width:100%;padding:11px 13px;border-radius:9px;border:1px solid var(--line);
background:#0e1726;color:var(--txt);font-size:15px}
input:focus{outline:2px solid var(--accent);outline-offset:1px;border-color:transparent}
button{width:100%;margin-top:20px;padding:12px;border:0;border-radius:9px;
background:var(--accent);color:#04250f;font-weight:700;font-size:15px;cursor:pointer}
button:hover{filter:brightness(1.08)}
.err{margin-top:16px;padding:11px 13px;border-radius:9px;background:#3a1520;
border:1px solid #6b2333;color:#ffb4b4;font-size:13px}
.note{margin-top:22px;font-size:11.5px;color:var(--mut);line-height:1.55;
border-top:1px solid var(--line);padding-top:14px}
code{background:#0e1726;padding:1px 5px;border-radius:4px;font-size:11px}
</style></head><body>
<form class="card" method="post" action="/login" autocomplete="on">
  <h1>GreenWing Analytics</h1>
  <p class="sub">Uçuş yakıt analizi paneli — oturum açın</p>
  <input type="hidden" name="next" value="__NEXT__">
  <label for="u">Kullanıcı adı</label>
  <input id="u" name="username" required autofocus autocomplete="username">
  <label for="p">Parola</label>
  <input id="p" name="password" type="password" required
         autocomplete="current-password">
  <button type="submit">Giriş</button>
  __ERROR__
  <div class="note">
    Bu panel müşteri uçuş verisi içerir. Erişim yetkilendirilmiş
    kullanıcılarla sınırlıdır. Parolalar PBKDF2-HMAC-SHA256 ile
    saklanır; oturumlar imzalı çerezlerdir (8 saat).
    <br><br>Kurulum: <code>GREENWING_DASHBOARD_PASSWORD</code>
    ortam değişkeni veya <code>config/secrets.yaml</code>.
  </div>
</form></body></html>'''


def render_login(next_url: str = '/', error: str = '', hint: str = '') -> str:
    """
    Giriş sayfasını doldur.

    ``next_url`` ve ``error`` HTML-kaçışlıdır (reflected XSS koruması);
    bir kullanıcı ``/login?next="><script>`` deneyemez.
    """
    from html import escape
    return (LOGIN_HTML
            .replace('__NEXT__', escape(next_url, quote=True))
            .replace('__ERROR__', (error or '') + (hint or '')))


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request, next_url: str = '/'):
    """
    Giriş formunu göster.

    NOT: parametre adı ``next`` DEĞİL — ``next`` Python yerleşik
    fonksiyonudur; parametre adı olarak kullanılırsa fonksiyon
    gövdesinde ``next(iter(...))`` çağrısı ``'str' object is not
    callable`` hatası verir. Bu gerçek bir hata olarak yakalandı.
    """
    hint = ''
    try:
        users = get_auth().users
        if len(users) == 1:
            only = next(iter(users))
            hint = (f'<div class="note" style="border-top:0;margin-top:10px;'
                    f'padding-top:0;color:#93a4c4">Bu kurulumda tek kullanıcı: '
                    f'<code>{only}</code></div>')
    except AuthConfigError as exc:
        # Yapılandırma yoksa login sayfası bunu AÇIKÇA söylemeli —
        # kullanıcı "parolamı bilmiyorum" değil, "sunucu ayarlı değil"
        # durumunu görmeli.
        hint = (f'<div class="err">Kimlik doğrulama yapılandırılmamış. '
                f'Sunucu tarafında GREENWING_DASHBOARD_PASSWORD veya '
                f'config/secrets.yaml tanımlayın.</div>')
    except Exception as exc:  # noqa: BLE001
        import traceback as _tb
        print('LOGIN HINT HATASI:\n' + _tb.format_exc())
        hint = (f'<div class="err">Giriş sistemi hatası: '
                f'{type(exc).__name__}: {exc}</div>')
    return render_login(safe_next_url(next_url), hint=hint)


@app.post('/login')
def login_submit(request: Request,
                 username: str = Form(''),
                 password: str = Form(''),
                 next_url: str = Form('/', alias='next')):
    client_ip = (request.client.host if request.client else '') or ''
    try:
        auth = get_auth()
    except AuthConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if auth.is_locked(username, client_ip):
        wait = auth.remaining_lockout(username, client_ip)
        err = (f'<div class="err">Çok fazla hatalı deneme. '
               f'{wait} saniye sonra tekrar deneyin.</div>')
        return HTMLResponse(render_login(safe_next_url(next_url), err),
                            status_code=429)

    if not auth.verify(username, password, client_ip):
        err = '<div class="err">Kullanıcı adı veya parola hatalı.</div>'
        return HTMLResponse(render_login(safe_next_url(next_url), err),
                            status_code=401)

    resp = RedirectResponse(safe_next_url(next_url), status_code=303)

    # ── Secure bayrağı: PROTOKOLE GÖRE ─────────────────────
    # `Secure` çerezler yalnızca HTTPS üzerinden gönderilir. Preview /
    # geliştirme ortamı HTTP üzerinden geliyorsa `Secure=True` çerez
    # HİÇ SET EDİLMEZ → tarayıcı oturumu hiç edinmez → sonsuz login
    # döngüsü (panelin "görünmemesi"nin en yaygın nedeni).
    # Çözüm: isteğin gerçek şemasına bak. Arkada proxy varsa
    # X-Forwarded-Proto'yu güven (uvicorn --proxy-headers ile).
    _proto = (request.headers.get('x-forwarded-proto', '')
              or request.url.scheme or '').split(',')[0].strip().lower()
    _is_https = _proto == 'https'
    # HTTPS değilse Secure'ı KAPAT (aksi halde çerez kaybolur), ama
    # üretimde HTTPS zorunlu olduğunu logla.
    _secure = auth.secure_cookie and _is_https
    if auth.secure_cookie and not _is_https:
        print(f'ℹ  Oturum çerezi Secure olmadan gönderiliyor '
              f'(şema: {_proto or "http"}). Üretimde HTTPS kullanın.')

    resp.set_cookie(
        auth.cookie_name, auth.issue_session(username),
        max_age=8 * 3600, httponly=True, samesite='lax',
        secure=_secure, path='/',
    )
    return resp


@app.get('/logout')
def logout():
    try:
        name = get_auth().cookie_name
    except AuthConfigError:
        name = 'gw_session'
    resp = RedirectResponse('/login', status_code=303)
    resp.delete_cookie(name, path='/')
    return resp


@app.get('/', response_class=HTMLResponse)
def panel(request: Request, gw_session: str | None = Cookie(None)):
    ok, user = current_user(gw_session)
    if not ok:
        return RedirectResponse('/login?next=/', status_code=303)
    return templates.TemplateResponse(
        request, 'panel.html',
        {'user': user, 'version': APP_VERSION})


# ── JSON API ──────────────────────────────────────────────
@app.get('/api/summary')
def api_summary(gw_session: str | None = Cookie(None)):
    ok, _ = current_user(gw_session)
    if not ok:
        return auth_failure_response()
    return summarize(load_flights())


@app.get('/api/flights')
def api_flights(gw_session: str | None = Cookie(None),
                limit: int = Query(50, ge=1, le=500),
                offset: int = Query(0, ge=0),
                aircraft: str | None = None,
                sort: str = Query('fuel_per_nm', pattern='^[a-z_]+$')):
    ok, _ = current_user(gw_session)
    if not ok:
        return auth_failure_response()
    rows = load_flights()
    if aircraft:
        rows = [r for r in rows if str(r.get('aircraft_type')) == aircraft]
    rows = sorted(rows, key=lambda r: float(r.get(sort) or 0), reverse=True)
    return {'total': len(rows), 'limit': limit, 'offset': offset,
            'rows': rows[offset:offset + limit]}


@app.get('/api/provenance')
def api_provenance(gw_session: str | None = Cookie(None)):
    ok, _ = current_user(gw_session)
    if not ok:
        return auth_failure_response()
    if not PROVENANCE_FILE.exists():
        return {'available': False,
                'hint': 'tools/build_provenance.py çalıştırılmalı'}
    return json.loads(PROVENANCE_FILE.read_text(encoding='utf-8'))


if __name__ == '__main__':
    import uvicorn
    host = os.environ.get('GREENWING_WEB_HOST', '0.0.0.0')
    port = int(os.environ.get('GREENWING_WEB_PORT', '8051'))
    print(f'GreenWing paneli → http://{host}:{port}')
    uvicorn.run(app, host=host, port=port, log_level='info')
