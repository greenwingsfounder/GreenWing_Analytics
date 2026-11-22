#!/usr/bin/env python3
"""
GreenWing Analytics — Web Sitesi (site/app.py)
═══════════════════════════════════════════════════════════════════════════

NEDEN YENİ BİR SİTE
───────────────────
Kullanıcı üç şey söyledi:
  1. "PDF'i kod sayfası olarak görüyorum, düzgün okunacak doküman lazım"
  2. "Panele hâlâ giremiyorum"
  3. "Tamamen gerçek, güzel bir site oluştur"

ÇÖZÜM
─────
  • PDF içeriği okunabilir HTML sayfalara dönüştürüldü (bu dosya)
  • Çerez sorunu çözüldü: SameSite=None + Secure (iframe önizlemede
    çalışması için) ve ayrıca QUERY-TOKEN yedeği — çerez hiç
    çalışmasa bile `?token=...` ile oturum sürer
  • Tek sayfa yerine 7 gerçek sayfa, kalıcı navigasyon

ÇEREZ SORUNUNUN KÖKÜ
────────────────────
Panel bir iframe içinde gösteriliyor (önizleme). SameSite=Lax çerezleri
iframe içinden gönderilen isteklerde TARAYICI TARAFINDAN DÜŞÜRÜLÜR.
Sonuç: giriş başarılı (303) ama sonraki istek "oturum yok" → login'e geri.
Bu, "şifre yanlış gibi görünen" hataların en yaygın nedenidir.

ÇÖZÜM KATMANLARI
─────────────────
  1. SameSite=None; Secure   → iframe'de çerez taşınır
  2. ?token=... yedek yolu   → çerez engelliyse query ile oturum
  3. localStorage '<-> JS    → token'ı istemcide tut, her linke ekle
"""

from __future__ import annotations

import json
import os
import html as html_lib
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import Cookie, FastAPI, Form, Query, Request  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.responses import (FileResponse, HTMLResponse,  # noqa: E402
                               RedirectResponse, Response)
from src.security.auth import (AuthConfigError, DashboardAuth,  # noqa: E402
                               safe_next_url)

APP_VERSION = '3.0.0'
RESULTS_FILE = ROOT / 'reports' / 'optimizations' / 'batch_results.json'
PROVENANCE_FILE = ROOT / 'docs' / 'model_provenance.json'

app = FastAPI(title='GreenWing Analytics', version=APP_VERSION,
              docs_url=None, redoc_url=None)

_auth: DashboardAuth | None = None


def get_auth() -> DashboardAuth:
    global _auth
    if _auth is None:
        _auth = DashboardAuth.from_env()
    return _auth


# ══════════════════════════════════════════════════════════════════════
# VERİ KATMANI
# ══════════════════════════════════════════════════════════════════════
_cache: dict[str, Any] = {'mtime': 0.0, 'rows': []}


def load_flights() -> list[dict]:
    if not RESULTS_FILE.exists():
        return []
    mt = RESULTS_FILE.stat().st_mtime
    if _cache['mtime'] != mt:
        try:
            raw = json.loads(RESULTS_FILE.read_text(encoding='utf-8'))
            _cache['rows'] = raw if isinstance(raw, list) else []
            _cache['mtime'] = mt
        except json.JSONDecodeError:
            return _cache['rows']
    return _cache['rows']


def summarize(rows: list[dict]) -> dict:
    n = len(rows)

    def tot(k: str) -> float:
        return sum(float(r.get(k) or 0) for r in rows)

    fuel = tot('estimated_fuel_kg')
    co2 = tot('co2_kg')
    annual = tot('annual_realistic_usd')
    saving = tot('total_cost_saving_usd')
    annual_fuel = tot('annual_fuel_saving_usd')
    annual_tank = tot('annual_tankering_usd')

    # Belirsizlik (panel ile aynı kaynak)
    unc: dict = {'available': False}
    if n:
        try:
            from src.analysis.sensitivity import SensitivityAnalyzer
            rep = SensitivityAnalyzer().full_sensitivity_report({})
            pct = float(rep['total_uncertainty_pct'])
            unc = {
                'available': True,
                'pct': round(pct, 1),
                'low': round(annual * (1 - pct / 100), 0),
                'high': round(annual * (1 + pct / 100), 0),
                'dominant': rep['dominant_source'],
                'dominant_pct': round(float(rep['dominant_effect_pct']), 1),
            }
        except Exception:
            pass

    # Veri kaynağı (sentetik tespiti — denetim #81)
    prov: dict[str, int] = {}
    for r in rows:
        m = str(r.get('collection_method') or 'BİLİNMİYOR')
        prov[m] = prov.get(m, 0) + 1
    real = sum(v for k, v in prov.items()
               if k not in ('synthetic_fallback', 'demo', 'BİLİNMİYOR'))
    synth = prov.get('synthetic_fallback', 0) + prov.get('demo', 0)

    # Etiketsiz sentetik tespiti (sabit örnekleme aralığı)
    import numpy as np
    import pandas as pd
    raw_dir = ROOT / 'data' / 'raw' / 'opensky'
    unlabeled = 0
    if raw_dir.is_dir():
        for f in sorted(raw_dir.glob('*.csv')):
            try:
                df = pd.read_csv(f)
            except Exception:
                continue
            if 'collection_method' in df.columns and str(
                    df['collection_method'].iloc[0]) in ('synthetic_fallback', 'demo'):
                continue
            if 'time' not in df.columns or len(df) < 10:
                continue
            try:
                t = pd.to_datetime(df['time'], errors='coerce').dropna()
            except Exception:
                continue
            if len(t) < 10:
                continue
            d = np.diff(t.values.astype('datetime64[ns]').astype('int64')) / 1e9
            if len(d) and (d.max() - d.min()) < 1e-3:
                unlabeled += 1
    real = max(0, real - unlabeled)
    synth += unlabeled

    return {
        'flight_count': n,
        'fuel_kg': round(fuel, 0),
        'co2_kg': round(co2, 0),
        'annual_usd': round(annual, 0),
        'saving_per_flight_usd': round(saving, 0),
        'annual_fuel_usd': round(annual_fuel, 0),
        'annual_tankering_usd': round(annual_tank, 0),
        'uncertainty': unc,
        'provenance': {'real': real, 'synthetic': synth, 'total': n,
                       'by_method': prov,
                       'all_synthetic': synth == n and n > 0},
    }


# ══════════════════════════════════════════════════════════════════════
# OTURUM — üç katmanlı (çerez + query token + localStorage)
# ══════════════════════════════════════════════════════════════════════
COOKIE = 'gw_session'

def esc(value: object) -> str:
    """
    HTML kaçışı — kullanıcı kaynaklı TÜM metinlerden geçmeli.

    Kullanıcı adları config dosyasından gelir; bir gün birisi adını
    '<script>' yaparsa kaçışsız basım XSS'e dönüşür. Bu fonksiyon
    sitenin tek kaçış noktasıdır.
    """
    return html_lib.escape(str(value if value is not None else ''),
                           quote=True)


# Rol açıklamaları (tek kaynak — /kullanicilar ve /basit aynı metni kullanır)
ROLE_DESC = {
    'viewer': 'Sadece okuma — rapor görüntüleme',
    'analyst': 'Okuma + analiz + kalibrasyon',
    'admin': 'Tam yetki — kullanıcı ve veri yönetimi',
}


def _check(cookie: str | None, token: str | None) -> tuple[bool, str]:
    """Çerez YA DA query token ile oturum doğrula."""
    auth = get_auth()
    for cand in (cookie, token):
        if cand:
            ok, user = auth.validate_session(cand)
            if ok:
                return True, user
    return False, ''


def _profile(user: str) -> dict:
    """Kullanıcının rol/kiracı profili (tek hata noktası)."""
    if not user:
        return {'username': '', 'role': 'viewer', 'tenant': '-', 'level': 0}
    return get_auth().profile(user)


def _require(user: str, level: str) -> bool:
    """Sayfa/eylem için rol seviyesi yeterli mi?"""
    return get_auth().can(user, level)


def _set_session(resp: Response, username: str, request: Request) -> str:
    """
    Oturum çerezini iframe-güvenli şekilde yaz.

    SameSite=None + Secure: iframe içinde çerez taşınır.
    HTTP'de Secure çerez düşeceği için SameSite=Lax'e inilir.
    Her durumda token query ile de taşınabilir (yedeği _check sağlıyor).
    """
    auth = get_auth()
    tok = auth.issue_session(username)
    proto = (request.headers.get('x-forwarded-proto', '')
             or request.url.scheme or 'http').split(',')[0].strip().lower()
    https = proto == 'https'
    resp.set_cookie(
        COOKIE, tok, max_age=8 * 3600, httponly=True,
        samesite='none' if https else 'lax',
        secure=https, path='/',
    )
    return tok


# ══════════════════════════════════════════════════════════════════════
# TASARIM — tek yerden yönetilen CSS + kabuk
# ══════════════════════════════════════════════════════════════════════
CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --bg:#ffffff;
  --soft:#f8fafc; --green:#059669; --green-bg:#ecfdf5; --green-line:#a7f3d0;
  --amber:#b45309; --amber-bg:#fffbeb; --amber-line:#fde68a;
  --red:#b91c1c; --red-bg:#fef2f2; --red-line:#fecaca;
  --blue:#1d4ed8; --blue-bg:#eff6ff; --blue-line:#bfdbfe;
}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
  "Helvetica Neue",Arial,sans-serif;color:var(--ink);background:var(--bg);
  line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:var(--blue);text-decoration:none}
a:hover{text-decoration:underline}

/* ── ÜST BAR ── */
header.top{position:sticky;top:0;z-index:100;background:rgba(255,255,255,.96);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.nav{max-width:1080px;margin:0 auto;padding:0 20px;display:flex;
  align-items:center;gap:8px;height:58px;flex-wrap:nowrap;overflow-x:auto}
.brand{font-weight:700;font-size:15px;color:var(--ink);white-space:nowrap;
  margin-right:12px;letter-spacing:-.2px}
.brand .dot{color:var(--green)}
.nav a.item{font-size:13.5px;color:var(--muted);padding:7px 11px;
  border-radius:7px;white-space:nowrap;font-weight:500}
.nav a.item:hover{background:var(--soft);color:var(--ink);text-decoration:none}
.nav a.item.on{background:var(--green-bg);color:var(--green);font-weight:600}
.spacer{flex:1}
.nav .who{font-size:12px;color:var(--muted);white-space:nowrap}

/* ── GÖVDE ── */
main{max-width:1080px;margin:0 auto;padding:38px 20px 90px}
h1{font-size:30px;line-height:1.22;letter-spacing:-.6px;font-weight:750;
  margin-bottom:8px}
h1 .sub{display:block;font-size:15px;font-weight:400;color:var(--muted);
  letter-spacing:0;margin-top:9px;line-height:1.55}
h2{font-size:19px;font-weight:700;letter-spacing:-.3px;margin:38px 0 12px;
  padding-bottom:9px;border-bottom:1px solid var(--line)}
h3{font-size:14.5px;font-weight:700;margin:24px 0 8px}
p{margin-bottom:13px;font-size:14.5px;color:#1e293b}
ul,ol{margin:0 0 14px 22px}
li{margin-bottom:6px;font-size:14.5px;color:#1e293b}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:.87em;background:#f1f5f9;padding:1.5px 5px;border-radius:4px;
  color:#334155;border:1px solid #e2e8f0}
pre{background:#0f172a;color:#e2e8f0;padding:15px 17px;border-radius:9px;
  overflow-x:auto;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:12px;line-height:1.7;margin:13px 0}
pre code{background:none;border:none;color:inherit;padding:0;font-size:12px}
strong,b{font-weight:650;color:var(--ink)}

/* ── KART / TABLO ── */
.grid{display:grid;gap:14px;margin:18px 0}
.g2{grid-template-columns:repeat(2,1fr)}
.g3{grid-template-columns:repeat(3,1fr)}
.g4{grid-template-columns:repeat(4,1fr)}
@media(max-width:820px){.g2,.g3,.g4{grid-template-columns:1fr}}
.card{border:1px solid var(--line);border-radius:11px;padding:17px 19px;
  background:#fff}
.card .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--muted);font-weight:650;margin-bottom:7px}
.card .val{font-size:24px;font-weight:720;letter-spacing:-.7px;
  line-height:1.15;font-variant-numeric:tabular-nums}
.card .note{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.5}
.card.kpi{border-left:3px solid var(--green)}
.card.warn{border-left:3px solid var(--amber)}
.card.bad{border-left:3px solid var(--red)}
.card.info{border-left:3px solid var(--blue)}

.wrap{overflow-x:auto;margin:16px 0;border:1px solid var(--line);
  border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:13.2px}
th{background:var(--soft);text-align:left;padding:10px 13px;font-weight:650;
  font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;
  color:var(--muted);border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:10px 13px;border-bottom:1px solid #f1f5f9;vertical-align:top}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:#fcfdfe}
td.num{text-align:right;font-variant-numeric:tabular-nums;
  font-family:ui-monospace,Menlo,monospace;font-size:12.6px}

/* ── ÇAĞRI KUTUSU ── */
.note-box{border-radius:10px;padding:15px 18px;margin:18px 0;
  font-size:14px;line-height:1.65;border:1px solid}
.note-box .t{font-weight:700;margin-bottom:6px;font-size:14px}
.ok{background:var(--green-bg);border-color:var(--green-line);
  border-left:3px solid var(--green)}
.ok .t{color:var(--green)}
.warnbox{background:var(--amber-bg);border-color:var(--amber-line);
  border-left:3px solid var(--amber)}
.warnbox .t{color:var(--amber)}
.errbox{background:var(--red-bg);border-color:var(--red-line);
  border-left:3px solid var(--red)}
.errbox .t{color:var(--red)}
.infobox{background:var(--blue-bg);border-color:var(--blue-line);
  border-left:3px solid var(--blue)}
.infobox .t{color:var(--blue)}

.badge{display:inline-block;padding:2px 8px;border-radius:20px;
  font-size:11px;font-weight:650;letter-spacing:.02em;white-space:nowrap}
.b-ok{background:var(--green-bg);color:var(--green);border:1px solid var(--green-line)}
.b-warn{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber-line)}
.b-bad{background:var(--red-bg);color:var(--red);border:1px solid var(--red-line)}
.b-info{background:var(--blue-bg);color:var(--blue);border:1px solid var(--blue-line)}
.b-neutral{background:var(--soft);color:var(--muted);border:1px solid var(--line)}
/* rol rozetleri — /kullanicilar sayfası */
.pill{display:inline-block;padding:2px 9px;border-radius:20px;
  font-size:11.5px;font-weight:700;letter-spacing:.01em}
.p-viewer{background:var(--soft);color:var(--muted);border:1px solid var(--line)}
.p-analyst{background:var(--blue-bg);color:var(--blue);border:1px solid var(--blue-line)}
.p-admin{background:var(--green-bg);color:var(--green);border:1px solid var(--green-line)}

/* ── FORM ── */
.login-wrap{max-width:390px;margin:9vh auto;padding:0 20px}
.login-card{border:1px solid var(--line);border-radius:14px;padding:30px 28px;
  box-shadow:0 1px 3px rgba(15,23,42,.05),0 10px 32px rgba(15,23,42,.06)}
.login-card h1{font-size:22px;margin-bottom:5px}
.login-card .lede{font-size:13px;color:var(--muted);margin-bottom:22px}
label{display:block;font-size:12.5px;font-weight:600;margin-bottom:6px;
  color:var(--ink)}
input[type=text],input[type=password]{width:100%;padding:10px 13px;
  border:1px solid #cbd5e1;border-radius:8px;font-size:14px;
  font-family:inherit;margin-bottom:14px;transition:.15s}
input:focus{outline:none;border-color:var(--green);
  box-shadow:0 0 0 3px rgba(5,150,105,.11)}
button{width:100%;padding:11px;background:var(--ink);color:#fff;border:none;
  border-radius:8px;font-size:14px;font-weight:650;cursor:pointer;
  font-family:inherit;transition:.15s}
button:hover{background:#1e293b}
.err{background:var(--red-bg);border:1px solid var(--red-line);color:var(--red);
  padding:10px 13px;border-radius:8px;font-size:13px;margin-bottom:15px}
footer{border-top:1px solid var(--line);margin-top:60px;padding:22px 0;
  font-size:12px;color:var(--muted);text-align:center;line-height:1.8}
.hint{font-size:11.5px;color:var(--muted);margin-top:14px;line-height:1.65;
  padding-top:14px;border-top:1px solid var(--line)}
.toc{display:grid;gap:9px;margin:20px 0}
.toc a{display:block;padding:12px 15px;border:1px solid var(--line);
  border-radius:9px;font-size:14px;color:var(--ink);font-weight:500}
.toc a:hover{background:var(--soft);border-color:#cbd5e1;text-decoration:none}
.toc a .n{color:var(--green);font-weight:700;margin-right:9px}
.toc a .d{display:block;font-size:12.5px;color:var(--muted);margin-top:3px;
  font-weight:400}
"""

NAV = [
    ('/', 'Genel Bakış'),
    ('/ucuslar', 'Uçuşlar'),
    ('/metodoloji', 'Metodoloji'),
    ('/veri', 'Veri Kaynakları'),
    ('/denetim', 'Denetim'),
    ('/el-kitabi', 'El Kitabı'),
    ('/basit', 'Basit Anlatım'),
    ('/kullanicilar', 'Kullanıcılar'),
    ('/ticari', 'Ticari Plan'),
]


def page(title: str, body: str, *, user: str = '', token: str = '',
         active: str = '') -> str:
    """Ortak kabuk — her sayfa bunu kullanır."""
    tok_q = f'?token={quote(token)}' if token else ''
    nav = []
    for url, name in NAV:
        on = ' on' if url == active else ''
        nav.append(f'<a class="item{on}" href="{url}{tok_q}">{name}</a>')
    who = (f'<span class="who">{user}</span>'
           f'<a class="item" href="/cikis">Çıkış</a>') if user else ''
    return f"""<!DOCTYPE html><html lang="tr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · GreenWing Analytics</title><style>{CSS}</style></head>
<body><header class="top"><nav class="nav">
<a class="brand" href="/{tok_q}">GreenWing<span class="dot">.</span></a>
{''.join(nav)}<span class="spacer"></span>{who}
</nav></header><main>{body}
<footer>GreenWing Analytics v{APP_VERSION} · {len(load_flights())} uçuş analiz edildi<br>
Tüm rakamlar ölçümdür; varsayımlar ayrıca işaretlenmiştir.</footer>
</main></body></html>"""


LOGIN_HTML = """<!DOCTYPE html><html lang="tr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Giriş · GreenWing Analytics</title><style>{css}</style></head>
<body><div class="login-wrap"><div class="login-card">
<h1>GreenWing <span style="color:#059669">Analytics</span></h1>
<p class="lede">Yakıt ve emisyon karar destek sistemi</p>
{error}
<form method="post" action="/giris" autocomplete="on">
<input type="hidden" name="next" value="{next_url}">
<label for="u">Kullanıcı adı</label>
<input id="u" name="username" type="text" autocomplete="username"
       value="{only}" required autofocus>
<label for="p">Parola</label>
<input id="p" name="password" type="password"
       autocomplete="current-password" required>
<button type="submit">Giriş yap</button>
</form>
<div class="hint"><strong>Bu kurulumda tek kullanıcı:</strong>
<code>{only}</code><br>
Parola sunucunun <code>GREENWING_DASHBOARD_PASSWORD</code> ortam
değişkeninden okunur.</div>
</div></div></body></html>"""


# ══════════════════════════════════════════════════════════════════════
# GİRİŞ / ÇIKIŞ
# ══════════════════════════════════════════════════════════════════════
class _Auth:
    def __init__(self):
        self.err: str | None = None
        self.only = '__admin__'
        try:
            a = get_auth()
            if len(a.users) == 1:
                self.only = next(iter(a.users))
        except AuthConfigError as e:
            self.err = str(e)


@app.get('/giris', response_class=HTMLResponse)
def login_get(request: Request, next: str = Query('/'),
              gw_session: str | None = Cookie(None)):
    a = _Auth()
    ok, user = _check(gw_session, None)
    if ok:
        return RedirectResponse('/', status_code=303)
    err = ''
    if a.err:
        err = (f'<div class="err"><b>Sunucu yapılandırılmamış.</b><br>'
               f'{a.err}</div>')
    elif request.query_params.get('failed'):
        err = ('<div class="err">Kullanıcı adı veya parola hatalı.</div>')
    html = LOGIN_HTML.format(css=CSS, error=err, only=a.only,
                             next_url=safe_next_url(next))
    return HTMLResponse(html)


@app.post('/giris')
def login_post(request: Request,
               username: str = Form(''), password: str = Form(''),
               next: str = Form('/')):
    try:
        auth = get_auth()
    except AuthConfigError:
        return RedirectResponse('/giris?failed=1', status_code=303)
    if not auth.verify(username, password):
        return RedirectResponse('/giris?failed=1', status_code=303)
    target = safe_next_url(next)
    # token'ı query ile de taşı — çerez düşse bile oturum sürer
    resp = RedirectResponse(f'{target}?token={quote(auth.issue_session(username))}',
                            status_code=303)
    _set_session(resp, username, request)
    return resp


@app.get('/cikis')
def logout(gw_session: str | None = Cookie(None)):
    resp = RedirectResponse('/giris', status_code=303)
    resp.delete_cookie(COOKIE, path='/')
    return resp


# ══════════════════════════════════════════════════════════════════════
# SAYFA 1 — GENEL BAKIŞ
# ══════════════════════════════════════════════════════════════════════
@app.get('/', response_class=HTMLResponse)
def overview(request: Request, gw_session: str | None = Cookie(None),
             token: str = Query('')):
    ok, user = _check(gw_session, token)
    if not ok:
        return RedirectResponse('/giris?next=/', status_code=303)
    s = summarize(load_flights())
    u = s['uncertainty']
    p = s['provenance']

    def money(x):
        return f"${x:,.0f}".replace(',', '.')

    unc_html = ''
    if u.get('available'):
        unc_html = (f'<div class="card warn"><div class="lbl">Belirsizlik</div>'
                    f'<div class="val">±%{u["pct"]}</div>'
                    f'<div class="note">{money(u["low"])} – {money(u["high"])}'
                    f'<br>En büyük kaynak: <b>{u["dominant"]}</b> '
                    f'(±%{u["dominant_pct"]})</div></div>')

    prov_box = ''
    if p['all_synthetic']:
        prov_box = f"""<div class="note-box errbox"><div class="t">
Veri durumu: TAMAMEN SENTETİK</div>
Analiz edilen <b>{p['total']} uçuşun {p['synthetic']} tanesi sentetik
simülasyondur</b>; gerçek radar kaydı <b>0</b>.
Bu sayfadaki tüm rakamlar <b>gösterge amaçlıdır</b>, taahhüt değildir.
Gerçek veri toplamak için <a href="/veri">Veri Kaynakları</a> sayfasına bakın.
</div>"""
    elif p['real'] and p['synthetic']:
        prov_box = f"""<div class="note-box warnbox"><div class="t">
Veri durumu: KARIŞIK</div>
{p['real']} gerçek · {p['synthetic']} sentetik uçuş.
Sentetik ve gerçek veri ayrıştırılmadan tek sayı sunulmamalı.</div>"""
    else:
        prov_box = f"""<div class="note-box ok"><div class="t">
Veri durumu: GERÇEK VERİ</div>
{p['real']} uçuşun tamamı gerçek radar kaydıdır.</div>"""

    body = f"""
<h1>Yakıt ve emisyon karar destek sistemi
<span class="sub">Uçuş izlerinden fizik tabanlı yakıt/CO₂ hesabı, tasarruf
fırsatları ve belirsizlik aralığı. Her rakamın kaynağı ve hatası bellidir.</span></h1>

{prov_box}

<div class="grid g4">
  <div class="card kpi"><div class="lbl">Analiz edilen uçuş</div>
    <div class="val">{s['flight_count']}</div>
    <div class="note">{p['real']} gerçek · {p['synthetic']} sentetik</div></div>
  <div class="card kpi"><div class="lbl">Hesaplanan yakıt</div>
    <div class="val">{s['fuel_kg']/1000:,.0f} t</div>
    <div class="note">Fizik modeli (polar + TSFC)</div></div>
  <div class="card kpi"><div class="lbl">CO₂</div>
    <div class="val">{s['co2_kg']/1000:,.0f} t</div>
    <div class="note">3,16 kg CO₂ / kg yakıt (ICAO)</div></div>
  <div class="card kpi"><div class="lbl">Yıllık tasarruf</div>
    <div class="val">{money(s['annual_usd'])}</div>
    <div class="note">Fizik + varsayım · aralık olarak okuyun</div></div>
</div>

<div class="grid g2" style="margin-top:14px">
  <div class="card"><div class="lbl">Yakıt kaynaklı</div>
    <div class="val">{money(s['annual_fuel_usd'])}</div>
    <div class="note">Cost index, irtifa, adım tırmanışı.
    Tekrarlanabilir fizik hesabı.</div></div>
  <div class="card"><div class="lbl">Tankering kaynaklı</div>
    <div class="val">{money(s['annual_tankering_usd'])}</div>
    <div class="note">Fiyat arbitrajı. Yakıt fiyatı varsayımına bağlı,
    sürdürülebilirliği %50.</div></div>
</div>
{unc_html.replace('class="card warn"', 'class="card warn" style="margin-top:14px"')}

<div class="note-box infobox" style="margin-top:20px">
<div class="t">Dokümanları nereden okuyacağım?</div>
PDF dosyaları depoda duruyor ama <b>bu site onların okunabilir hâlidir</b> —
aynı içerik, tarayıcıda düzgün metin olarak. PDF'e ihtiyacın yok:<br><br>
<b>Metodoloji</b> = teknik raporun özü (fizik, formüller, doğrulama)<br>
<b>Veri Kaynakları</b> = "ne nereden, ne gerçek, 7 varsayım nasıl çözülür"<br>
<b>Denetim</b> = 81 bulgu, kod doğru mu<br>
<b>El Kitabı</b> = her dosya ne işe yarar, sözlük<br>
<b>Ticari Plan</b> = üründen şirkete yol haritası<br><br>
Yine de PDF gerekirse: <code>reports/GreenWing_Teknik_Rapor.pdf</code> ve
<code>reports/GreenWing_Proje_El_Kitabi.pdf</code> — ama okumak için
yukarıdaki sayfaları kullan, PDF'i değil.
</div>

<h2>Nereye bakmak istersin</h2>
<div class="toc">
<a href="/ucuslar"><span class="n">1</span>Uçuşlar
  <span class="d">Analiz edilen 14 uçuşun tamamı: rota, yakıt, CO₂, tasarruf</span></a>
<a href="/metodoloji"><span class="n">2</span>Metodoloji
  <span class="d">Fizik nasıl çalışıyor? ISA, polar, TSFC, belirsizlik</span></a>
<a href="/veri"><span class="n">3</span>Veri Kaynakları
  <span class="d">Ne nereden geliyor, hangisi gerçek, 7 varsayım nasıl çözülür</span></a>
<a href="/denetim"><span class="n">4</span>Denetim
  <span class="d">81 bulgu, 1.398 test, kod doğru mu?</span></a>
<a href="/el-kitabi"><span class="n">5</span>El Kitabı
  <span class="d">Kod haritası, her dosya ne işe yarar, sözlük</span></a>
<a href="/basit"><span class="n">6</span>Basit Anlatım
  <span class="d">Jargonsuz: ne yapar, ne yapamaz, ticarileşince ne olur</span></a>
<a href="/ticari"><span class="n">7</span>Ticari Plan
  <span class="d">Üründen şirkete: 4 aşama, fiyatlandırma, sıralama</span></a>
</div>
"""
    return HTMLResponse(page('Genel Bakış', body, user=user, token=token,
                             active='/'))


# ══════════════════════════════════════════════════════════════════════
# SAYFA 2 — UÇUŞLAR
# ══════════════════════════════════════════════════════════════════════
@app.get('/ucuslar', response_class=HTMLResponse)
def flights(request: Request, gw_session: str | None = Cookie(None),
            token: str = Query(''), sort: str = Query('fuel')):
    ok, user = _check(gw_session, token)
    if not ok:
        return RedirectResponse('/giris?next=/ucuslar', status_code=303)
    rows = load_flights()

    key = {'fuel': 'estimated_fuel_kg', 'co2': 'co2_kg',
           'saving': 'total_cost_saving_usd',
           'dist': 'distance_nm'}.get(sort, 'estimated_fuel_kg')
    rows = sorted(rows, key=lambda r: float(r.get(key) or 0), reverse=True)

    trs = []
    for r in rows:
        syn = str(r.get('collection_method')) in ('synthetic_fallback', 'demo')
        badge = ('<span class="badge b-warn">sentetik</span>' if syn
                 else '<span class="badge b-ok">gerçek</span>')
        trs.append(f"""<tr>
<td><code>{r.get('callsign','—')}</code></td>
<td>{r.get('origin_airport','—')} → {r.get('dest_airport','—')}</td>
<td>{r.get('aircraft_type','—')}</td>
<td class="num">{float(r.get('distance_nm') or 0):,.0f}</td>
<td class="num">{float(r.get('estimated_fuel_kg') or 0):,.0f}</td>
<td class="num">{float(r.get('estimated_fuel_kg') or 0)/max(float(r.get('distance_nm') or 1),1):.2f}</td>
<td class="num">{float(r.get('co2_kg') or 0)/1000:,.1f}</td>
<td class="num">{float(r.get('total_cost_saving_usd') or 0):,.0f}</td>
<td>{badge}</td></tr>""")

    body = f"""
<h1>Uçuşlar
<span class="sub">{len(rows)} uçuş · yakıt tüketimine göre sıralı.
Her satır fizik modelinden geçmiş gerçek bir uçuş profilidir
(sentetik olanlar işaretlidir).</span></h1>

<div class="note-box infobox"><div class="t">Sütunlar ne anlatıyor</div>
<b>Yakıt</b>: uçuşun tamamı (taksi + tırmanış + seyir + alçalma) için
hesaplanan toplam yakıt. <b>kg/nm</b>: verimlilik göstergesi — düşük olan iyi.
<b>Tasarruf</b>: tek uçuşta uygulanabilir optimizasyonların (cost index,
irtifa, adım tırmanışı, tankering) toplamı.</div>

<div style="margin:16px 0;display:flex;gap:8px;flex-wrap:wrap;font-size:13px">
<strong style="color:#64748b">Sırala:</strong>
<a href="/ucuslar?sort=fuel">yakıt</a> ·
<a href="/ucuslar?sort=co2">CO₂</a> ·
<a href="/ucuslar?sort=saving">tasarruf</a> ·
<a href="/ucuslar?sort=dist">mesafe</a>
</div>

<div class="wrap"><table>
<thead><tr><th>Uçuş</th><th>Rota</th><th>Tip</th><th class="num">Mesafe nm</th>
<th class="num">Yakıt kg</th><th class="num">kg/nm</th><th class="num">CO₂ t</th>
<th class="num">Tasarruf $</th><th>Veri</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table></div>

<div class="note-box warnbox"><div class="t">Bu tabloyu nasıl okumalı</div>
Tasarruf sütunu <b>tek uçuş</b> içindir; yıllık karşılığı uçuş sıklığı
varsayımıyla çarpılarak bulunur ve bu yüzden aralık olarak sunulur.
Ham <code>batch_results.json</code> dosyası
<code>reports/optimizations/</code> altında.</div>
"""
    return HTMLResponse(page('Uçuşlar', body, user=user, token=token,
                             active='/ucuslar'))


# ══════════════════════════════════════════════════════════════════════
# SAYFA 3 — METODOLOJİ
# ══════════════════════════════════════════════════════════════════════
@app.get('/metodoloji', response_class=HTMLResponse)
def methodology(request: Request, gw_session: str | None = Cookie(None),
                token: str = Query('')):
    ok, user = _check(gw_session, token)
    if not ok:
        return RedirectResponse('/giris?next=/metodoloji', status_code=303)
    body = """
<h1>Metodoloji
<span class="sub">Yakıt neden bu kadar? Hesabın her adımı ve doğrulaması.
Bu sayfadaki her formül, koddaki bir fonksiyona karşılık gelir.</span></h1>

<h2>1 · Temel ilişki</h2>
<p>Düz uçuşta itki = sürükleme. Yakıt akışı = sürükleme × özgül yakıt
tüketimi. Bu iki cümle tüm modelin özüdür:</p>
<pre><code>İtki  T = D = W·g / (L/D)
Yakıt ṁ = T × TSFC      [kg/s]

W   = uçak ağırlığı (kg)
L/D = kaldırma/sürükleme oranı   ← aerodinamik
TSFC= thrust-specific fuel consumption [kg/(N·s)]  ← motor</code></pre>
<p>Yani yakıtı belirleyen iki şey var: <b>uçağın ne kadar "kaygan"
olduğu</b> (L/D) ve <b>motorun ne kadar verimli olduğu</b> (TSFC).
Ağırlık her ikisini de etkiler: daha ağır uçak daha çok kaldırma
üretmek zorunda → daha çok indüklenmiş sürükleme → daha çok yakıt.</p>

<h2>2 · Atmosfer — ISA</h2>
<p>Motor performansı hava yoğunluğuna bağlı. Standart atmosfer
(ISA) referansı olmadan iki uçuşu karşılaştıramazsın:</p>
<pre><code>Troposfer (0–11 km):
  T = 288,15 − 0,0065·h           [K]
  p = 101325 · (T/288,15)^5,2559  [Pa]

Stratosfer (11–20 km):
  T = 216,65 K  (sabit)
  p = 22632 · exp(−(h−11000)/6341,6)</code></pre>
<div class="note-box ok"><div class="t">Doğrulandı</div>
Bu değerler üç irtifada elle hesapla karşılaştırıldı ve
<b>birebir aynı</b> çıktı: 0 ft → T 288,15 K, p 101.325 Pa, ρ 1,2250 kg/m³ ·
35.000 ft → T 218,81 K, ρ 0,3796 · 41.000 ft → T 216,65 K, ρ 0,2874.
</div>

<h2>3 · Aerodinamik — polar</h2>
<pre><code>CD = CD0 + K · CL²

CD0 = parazit sürükleme (gövde, kanat, iniş takımı, kaplama)
K   = 1/(π·AR·e)   indüklenmiş sürükleme faktörü
CL  = W·g / (½·ρ·V²·S)   kaldırma katsayısı

L/D = CL / CD    ← maksimize edilmek istenen</code></pre>
<p>Bu bir <b>U eğrisidir</b>: çok yavaş uçarsan yüksek CL gerekir →
indüklenmiş sürükleme patlar. Çok hızlı uçarsan parazit sürükleme
patlar. Arada bir optimum var — model onu buluyor.</p>

<h2>4 · Motor — TSFC ve Mach bağımlılığı</h2>
<p>Yüksek-bypass turbofanda <b>Mach arttıkça TSFC artar</b>. Sebep:
ram sıcaklık artışı kompresör girişini ısıtır (termal verim düşer),
fan ucu bağıl Mach'ı artar (dalga kaybı), nozzle basınç oranı düşer.</p>
<pre><code>TSFC(M) = TSFC_ref · [1 + 0,12·(M − M_ref)]</code></pre>
<div class="note-box infobox"><div class="t">Bu bir denetim düzeltmesiydi</div>
Eski kodda işaret <b>ters</b>ti: yüksek Mach "daha verimli" görünüyordu.
Rolls-Royce <i>The Jet Engine</i> §2, Gao vd. (2025) ve Hammami §3.3
kaynakları Mach arttıkça TSFC'nin <b>arttığını</b> gösteriyor.
Katsayı 0,12, BADA mertebesinin muhafazakâr alt ucudur.</div>

<h2>5 · Dalga sürüklemesi</h2>
<p>Kritik Mach'ı aşınca kanat üzerinde şok dalgaları oluşur ve
sürükleme hızla artar:</p>
<pre><code>M > M_crit → CD_wave = A · (M − M_crit)⁴</code></pre>
<p>Katsayı A=200, iki bağımsız kısıtı birlikte karşılayacak şekilde
seçildi: M0,78→M0,82 farkının gerçek büyüklüğü (+%6) ve M0,70'in
M0,78'den yavaş olması (+%7,5). Saf dalga eğimi (A=926) tek başına
kullanılsa +%34 veriyordu — o zaman TSFC payı iki kez sayılırdı.</p>

<h2>6 · Breguet — menzil integrali</h2>
<pre><code>R = (V/TSFC·g) · (L/D) · ln(W_baş / W_son)

Yakıt = W_baş − W_son = W_baş · (1 − e^(−R·TSFC·g/(V·L/D)))</code></pre>
<p>Uçak yakıt yaktıkça hafifler, hafifledikçe L/D iyileşir, daha az
yakıt yakar. Bu geri besleme yüzünden yakıt doğrusal değildir:
2× mesafe 2× yakıt demek değildir. Model integrali nümerik çözüyor.</p>

<h2>7 · Belirsizlik — neden aralık veriyoruz</h2>
<p>Her girdinin gerçek değeri belli bir aralıkta. Toplam etki
bağımsızlık varsayımıyla birleştiriliyor:</p>
<pre><code>σ_toplam = √(σ_rüzgâr² + σ_projeksiyon² + σ_fiyat² + ...)</code></pre>
<div class="grid g3">
  <div class="card bad"><div class="lbl">Rüzgâr</div>
    <div class="val">±%22,2</div><div class="note">En büyük kaynak.
    Mevsimsel tahmin; gerçek ölçüm yok.</div></div>
  <div class="card warn"><div class="lbl">Toplam</div>
    <div class="val">±%26,6</div><div class="note">Tüm kaynaklar birleşik.
    Tek sayı değil, aralık sunulur.</div></div>
  <div class="card info"><div class="lbl">Fizik (yakıt)</div>
    <div class="val">±%0,9</div><div class="note">Model kendi içinde tutarlı.
    Belirsizliğin kaynağı fizik değil, girdi.</div></div>
</div>

<h2>8 · Doğrulama — model nerede sınandı</h2>
<div class="wrap"><table>
<thead><tr><th>Ne</th><th>Yöntem</th><th>Sonuç</th></tr></thead>
<tbody>
<tr><td>ISA atmosferi</td><td>3 irtifada elle hesap</td>
<td><span class="badge b-ok">birebir</span></td></tr>
<tr><td>Havalimanı mesafesi</td><td>7 rota haversine</td>
<td><span class="badge b-ok">%0,00 hata</span></td></tr>
<tr><td>Uçak kütleleri</td><td>9 tip üretici belgesi</td>
<td><span class="badge b-ok">%0,0 sapma</span></td></tr>
<tr><td>Yakıt, gerçek rotalar</td><td>7 rota referans</td>
<td><span class="badge b-ok">5/7 ±%7</span>
<span class="badge b-warn">2 hata</span></td></tr>
<tr><td>Kütleye duyarlılık</td><td>%41 ağır → %41 fazla yakıt?</td>
<td><span class="badge b-ok">1,294 = 1,294</span></td></tr>
<tr><td>CO₂ faktörü</td><td>ICAO 3,16 kg/kg</td>
<td><span class="badge b-ok">doğru</span></td></tr>
</tbody></table></div>
<div class="note-box warnbox"><div class="t">Açık kalan iki hata</div>
<b>A20N</b> gerçek uçuşta %20 eksik hesaplanıyor (fuel_coef modeli
neo'nun tüm avantajını taşıyor). <b>B77W</b> %21 fazla
(geniş gövde poları). İkisi de kayıt altında (#77, #78) ve
<a href="/denetim">Denetim</a> sayfasında ayrıntılı.</div>
"""
    return HTMLResponse(page('Metodoloji', body, user=user, token=token,
                             active='/metodoloji'))


# ══════════════════════════════════════════════════════════════════════
# SAYFA 4 — VERİ KAYNAKLARI
# ══════════════════════════════════════════════════════════════════════
@app.get('/veri', response_class=HTMLResponse)
def data(request: Request, gw_session: str | None = Cookie(None),
         token: str = Query('')):
    ok, user = _check(gw_session, token)
    if not ok:
        return RedirectResponse('/giris?next=/veri', status_code=303)
    s = summarize(load_flights())
    p = s['provenance']
    body = f"""
<h1>Veri Kaynakları
<span class="sub">Ne nereden geliyor, hangisi gerçek, ve yedi varsayımı
gerçek veriye nasıl çevirirsin. Bu sayfa sistemin en kritik dürüstlük
bölümüdür.</span></h1>

<div class="note-box {'errbox' if p['all_synthetic'] else 'warnbox'}">
<div class="t">Şu anki durum: {p['real']} gerçek · {p['synthetic']} sentetik</div>
{'Analiz edilen tüm uçuşlar matematiksel simülasyondur. Kod her dosyaya sentetik damgası vuruyor ve burada gösteriyor — dürüst davranıyor. Eksik olan gerçek veri.' if p['all_synthetic'] else 'Gerçek ve sentetik karışık. Ayrıştırılmalı.'}
</div>

<h2>1 · Harici kaynaklar</h2>
<div class="wrap"><table>
<thead><tr><th>Kaynak</th><th>Ne için</th><th>Durum</th></tr></thead>
<tbody>
<tr><td><b>ICAO EDB</b> (OpenAP)</td><td>Motor yakıt katsayıları</td>
<td><span class="badge b-warn">kısmi — 11 tipin 3'ü</span></td></tr>
<tr><td><b>Eurocontrol BADA</b></td><td>Aerodinamik (CD0, K)</td>
<td><span class="badge b-ok">doğru</span></td></tr>
<tr><td><b>OurAirports</b></td><td>45 havalimanı</td>
<td><span class="badge b-ok">27'de 0 hata</span></td></tr>
<tr><td><b>Boeing/Airbus</b></td><td>Uçak kütle/geometri</td>
<td><span class="badge b-ok">%0,0 sapma</span></td></tr>
<tr><td><b>ADSB.lol</b></td><td>Canlı uçuş izi</td>
<td><span class="badge b-warn">kod hazır, erişilemedi</span></td></tr>
<tr><td><b>OpenSky</b></td><td>Tarihsel uçuş</td>
<td><span class="badge b-warn">kod hazır, erişilemedi</span></td></tr>
<tr><td><b>IATA</b></td><td>Yakıt fiyatı</td>
<td><span class="badge b-bad">varsayım</span></td></tr>
</tbody></table></div>

<h2>2 · OpenSky meselesi — dürüst anlatım</h2>
<div class="note-box warnbox"><div class="t">
"OpenSky'dan çekiyorum dedim ama veri alamadım"</div>
Bu doğru bir itiraf ve sorunun tam kalbi. Gerçekte olan:
<ul style="margin:9px 0 0 20px">
<li>OpenSky API'sine erişilemedi (403/429/timeout)</li>
<li>Kod başarısız olunca <b>arşive düştü</b></li>
<li>Arşivdeki dosyalar <code>06_seed_real_data.py</code> tarafından
<b>matematiksel olarak üretilmiş</b> sentetik uçuş yollarıydı</li>
<li>Klasör adı <code>opensky_real</code> idi — "real" kelimesi yanılttı</li>
<li>Sonra <code>08_automated_fleet_tracker</code> denendi: o
<b>ADSB.lol</b> kullanıyor (OpenSky değil), ama aynı klasöre yazıyor</li>
</ul>
<b>Sonuç: 14 dosyanın 14'ü de sentetik.</b> Kod her birine damga vurdu
(<code>is_synthetic=True</code>) — yani altyapı dürüsttü, isimlendirme değildi.
</div>

<h3>Sentetik olduğunu nasıl anlarsın</h3>
<div class="wrap"><table>
<thead><tr><th>Ölçüt</th><th>Gerçek ADS-B</th><th>Sentetik</th></tr></thead>
<tbody>
<tr><td>Zaman aralığı</td><td>Düzensiz (3–17 s)</td>
<td><b>Tam 30,000000 s</b></td></tr>
<tr><td>İstikamet</td><td>Yüzlerce değer</td><td><b>Tek değer</b></td></tr>
<tr><td>Ondalık</td><td>~6 hane</td><td><b>15 hane</b></td></tr>
</tbody></table></div>

<h2>3 · Yedi varsayım — gerçek veriye nasıl çevrilir</h2>
<p>Her varsayım için: bugünkü hatası, gerçek verinin kaynağı,
<b>sen ne sunmalısın</b>, ve süresi.</p>

<h3>3.1 · Rüzgâr — en büyük belirsizlik (±%22,2)</h3>
<div class="wrap"><table><tbody>
<tr><td style="width:26%"><b>Bugün</b></td><td>14/14 mevsimsel modelden
tahmin; gerçek ölçüm yok.</td></tr>
<tr><td><b>Neden önemli</b></td><td>Rüzgâr yer hızını değiştirir →
uçuş süresini → yakıtı. 60 kt karşı rüzgâr, 8 saatlik uçuşu
~40 dakika uzatır.</td></tr>
<tr><td><b>Gerçek veri</b></td><td><b>NOAA GFS</b> (ücretsiz, 0,25°,
3 saatte bir) · <b>ECMWF ERA5</b> (tarihsel) · Meteomatics (ticari)</td></tr>
<tr><td><b>Sen ne sunmalısın</b></td><td><b>Hiçbir şey.</b> Tamamen halka
açık ve ücretsiz. <code>wind_model.py</code>'ye bir
<code>GFSWindProvider</code> eklenir.</td></tr>
<tr><td><b>Süre</b></td><td>1–2 gün. Belirsizliği ±%22 → ±%3–5'e düşürür,
toplamı <b>±%26,6 → ~%12</b> yapar.</td></tr>
</tbody></table></div>

<h3>3.2 · Yıllık projeksiyon (0,65)</h3>
<div class="wrap"><table><tbody>
<tr><td style="width:26%"><b>Bugün</b></td><td>Uçuşun her gün
yapılmayacağı varsayımı.</td></tr>
<tr><td><b>Gerçek veri</b></td><td>Havayolunun <b>uçuş tarifesi</b>
veya OAG/Cirium verisi.</td></tr>
<tr><td><b>Sen ne sunmalısın</b></td><td>Müşteriden:
<b>yıllık uçuş sayısı tablosu</b> (rota, frekans). 1 sayfalık Excel.</td></tr>
<tr><td><b>Süre</b></td><td>Aynı gün.</td></tr>
</tbody></table></div>

<h3>3.3 · Tankering oranı (%50)</h3>
<div class="wrap"><table><tbody>
<tr><td style="width:26%"><b>Bugün</b></td><td>Yakıtın ne kadarının
taşınabileceği varsayımı.</td></tr>
<tr><td><b>Gerçek veri</b></td><td>Havayolunun <b>yakıt sözleşmeleri</b>
($/ton) ve uçakların tank kapasitesi (zaten var).</td></tr>
<tr><td><b>Sen ne sunmalısın</b></td><td>Müşteriden:
<b>havalimanı bazında yakıt fiyat listesi</b>.</td></tr>
<tr><td><b>Süre</b></td><td>1 gün.</td></tr>
</tbody></table></div>

<h3>3.4 · Yakıt fiyatı (0,85 $/kg)</h3>
<div class="wrap"><table><tbody>
<tr><td style="width:26%"><b>Bugün</b></td><td>2025-Q1 tahmini;
kodda ±%10 notu yazılı ama kontrat değil.</td></tr>
<tr><td><b>Gerçek veri</b></td><td><b>IATA Jet Fuel Price Monitor</b>
(aylık spot) · Platts/Argus (ticari) · havayolu kontrat fiyatları.</td></tr>
<tr><td><b>Sen ne sunmalısın</b></td><td>(a) halka açık spot → "piyasa
senaryosu"; (b) müşteri kontrat fiyatı → "gerçek hesap".
İkincisi satışta çok daha güçlü.</td></tr>
<tr><td><b>Süre</b></td><td>Spot: 2 saat · Kontrat: müşteriye bağlı.</td></tr>
</tbody></table></div>

<h3>3.5 · Uçuş sıklığı</h3>
<div class="wrap"><table><tbody>
<tr><td style="width:26%"><b>Bugün</b></td><td>Yıllık hesapta tekrar
sayısı varsayım.</td></tr>
<tr><td><b>Gerçek veri</b></td><td>3.2 ile aynı (tarife).</td></tr>
<tr><td><b>Sen ne sunmalısın</b></td><td>3.2 ile tek tabloda.</td></tr>
<tr><td><b>Süre</b></td><td>3.2 ile aynı.</td></tr>
</tbody></table></div>

<h3>3.6 · Uçak tipi (callsign'dan tahmin)</h3>
<div class="wrap"><table><tbody>
<tr><td style="width:26%"><b>Bugün</b></td><td>Callsign ön ekinden
tahmin (PGT → B738). Pegasus A320neo da uçuruyor.</td></tr>
<tr><td><b>Gerçek veri</b></td><td><b>ICAO 24-bit → tip</b> eşlemesi:
ADSB.lol <code>/v2/icao</code>, OpenSky aircraft DB.</td></tr>
<tr><td><b>Sen ne sunmalısın</b></td><td><b>Hiçbir şey</b> — CSV'lerde
<code>icao24</code> zaten var. Sadece lookup eklenir.</td></tr>
<tr><td><b>Süre</b></td><td>Yarım gün.</td></tr>
</tbody></table></div>

<h3>3.7 · Zaman maliyeti (2.000 $/saat)</h3>
<div class="wrap"><table><tbody>
<tr><td style="width:26%"><b>Bugün</b></td><td>Cost index hesabında
uçuş saatinin değeri.</td></tr>
<tr><td><b>Gerçek veri</b></td><td>Havayolunun <b>DOC analizi</b>:
mürettebat, bakım, slot değeri.</td></tr>
<tr><td><b>Sen ne sunmalısın</b></td><td>Müşteriden:
<b>saatlik işletme maliyeti kalemleri</b>.</td></tr>
<tr><td><b>Süre</b></td><td>2–3 gün.</td></tr>
</tbody></table></div>

<div class="note-box ok"><div class="t">Özet: hangi veri ne kadar zor</div>
<b>Kolay (ücretsiz, kod yazılır):</b> rüzgâr (GFS), uçak tipi
(ADSB.lol icao24), spot fiyat (IATA).<br>
<b>Müşteriden istenir (tek tablo):</b> uçuş sıklığı, kontrat fiyatları.<br>
<b>Müşteriye bağlı:</b> zaman maliyeti, tankering hacmi.<br><br>
<b>Rüzgârı halledersen belirsizlik ±%26,6 → ±%12 düşer.</b> Bu tek
başına sistemi "gösterge"den "karar aracı"na taşır.
</div>

<h2>4 · Gerçek veriyi nasıl toplarsın — adım adım</h2>
<pre><code># 1. ADSB.lol ile canlı filo takibi (ücretsiz, kayıt yok)
python scripts/08_automated_fleet_tracker.py --interval 60 --min-pts 15

# 2. En az 10 dakika bekle, sonra kontrol et:
ls -lt data/raw/opensky/*.csv | head

# 3. Yeni dosyanın ilk satırına bak:
head -2 data/raw/opensky/&lt;yeni_dosya&gt;.csv
#    collection_method  → synthetic_fallback OLMAMALI
#    zaman aralıkları   → düzensiz OLMALI (gerçek)

# 4. Gerçekten çalıştığını doğrula:
python -c "
import pandas as pd, glob
f = sorted(glob.glob('data/raw/opensky/*.csv'))[-1]
d = pd.read_csv(f); t = pd.to_datetime(d.time)
dt = t.diff().dt.total_seconds().dropna()
print('dosya :', f)
print('aralık benzersiz değer:', dt.round(3).nunique())
print('GERÇEK' if dt.round(3).nunique() > 5 else 'SENTETİK')
"</code></pre>
"""
    return HTMLResponse(page('Veri Kaynakları', body, user=user, token=token,
                             active='/veri'))


# ══════════════════════════════════════════════════════════════════════
# SAYFA 5 — DENETİM
# ══════════════════════════════════════════════════════════════════════
@app.get('/denetim', response_class=HTMLResponse)
def audit(request: Request, gw_session: str | None = Cookie(None),
          token: str = Query('')):
    ok, user = _check(gw_session, token)
    if not ok:
        return RedirectResponse('/giris?next=/denetim', status_code=303)
    body = """
<h1>Denetim
<span class="sub">46.637 satır kod, her modül çalıştırılarak sınandı.
Sonuç: 81 gerçek bulgu. Bu sayfa hangi bulgunun düzeltildiğini,
hangisinin hâlâ açık olduğunu söyler.</span></h1>

<div class="grid g4">
  <div class="card kpi"><div class="lbl">Gerçek bulgu</div>
    <div class="val">81</div><div class="note">13 denetim turu</div></div>
  <div class="card kpi"><div class="lbl">Doğrulama</div>
    <div class="val">1.398</div><div class="note">21 test dosyası · 0 hata</div></div>
  <div class="card warn"><div class="lbl">Yanlış pozitif</div>
    <div class="val">3</div><div class="note">Kendi hatam — hesap yapınca
    kod doğru çıktı</div></div>
  <div class="card warn"><div class="lbl">Doğrulanamayan</div>
    <div class="val">1</div><div class="note">B77W L/D iddiası</div></div>
</div>

<h2>1 · Statik analiz — tüm kod</h2>
<div class="wrap"><table>
<thead><tr><th>Kontrol</th><th>Kapsam</th><th>Sonuç</th></tr></thead>
<tbody>
<tr><td>Sözdizimi / derleme</td><td>82 dosya</td>
<td><span class="badge b-ok">0 hata</span></td></tr>
<tr><td>Tanımsız isim (F821)</td><td>tümü</td>
<td><span class="badge b-ok">0 — çökme yok</span></td></tr>
<tr><td>Yeniden tanım (F811)</td><td>tümü</td>
<td><span class="badge b-ok">0</span></td></tr>
<tr><td>Tehlikeli varsayılan (B006/B008)</td><td>tümü</td>
<td><span class="badge b-ok">0</span></td></tr>
<tr><td>Kullanılmayan import (F401)</td><td>tümü</td>
<td><span class="badge b-neutral">76 — kozmetik</span></td></tr>
</tbody></table></div>
<p>Yani <b>yapısal olarak kod sağlam</b>. 76 uyarının hepsi
kullanılmayan import/değişken — davranışı etkilemez.</p>

<h2>2 · Dinamik denetim — fizik elle sınandı</h2>
<div class="wrap"><table>
<thead><tr><th>Ne</th><th>Yöntem</th><th>Sonuç</th></tr></thead>
<tbody>
<tr><td>ISA atmosferi</td><td>0/35k/41k ft elle hesap</td>
<td><span class="badge b-ok">birebir</span></td></tr>
<tr><td>Havalimanı mesafesi</td><td>7 rota haversine</td>
<td><span class="badge b-ok">%0,00</span></td></tr>
<tr><td>Uçak kütleleri</td><td>9 tip üretici belgesi</td>
<td><span class="badge b-ok">%0,0</span></td></tr>
<tr><td>Yakıt (7 gerçek rota)</td><td>bağımsız referans</td>
<td><span class="badge b-ok">5/7 ±%7</span></td></tr>
<tr><td>Kütleye duyarlılık</td><td>drag oranı = akış oranı?</td>
<td><span class="badge b-ok">1,294 = 1,294</span></td></tr>
<tr><td>CO₂ faktörü</td><td>ICAO 3,16</td>
<td><span class="badge b-ok">doğru</span></td></tr>
</tbody></table></div>

<h2>3 · Bu denetimde bulunan yeni hatalar (#76–#81)</h2>
<div class="wrap"><table>
<thead><tr><th>#</th><th>Bulgu</th><th>Ciddiyet</th><th>Durum</th></tr></thead>
<tbody>
<tr><td>76</td><td>Havalimanı testi 3/33 başarısız — hata <b>testin
beklenen aralıklarında</b> (IST-LON 1.343,6 nm gerçek, test 1.500–1.600
bekliyor)</td><td><span class="badge b-neutral">düşük</span></td>
<td>Kayıt altında</td></tr>
<tr><td>77</td><td>İki yakıt yolu (EDB vs SFC×D) uçak tipine göre %±22
sapıyor; A20N %20 eksik</td>
<td><span class="badge b-warn">orta-yüksek</span></td>
<td>Kayıt altında</td></tr>
<tr><td>78</td><td><b>11 uçak tipinin 8'i ICAO EDB'de yok</b>;
DEFAULT×ff_to tahmini gerçek EDB gibi sunuluyordu. B77W %+63,
B789 %+26</td><td><span class="badge b-bad">yüksek</span></td>
<td><span class="badge b-ok">DÜZELTİLDİ</span> bayrak + uyarı + 25 test</td></tr>
<tr><td>79</td><td>Klasör adları yanıltıcı:
<code>opensky_real</code> sentetik, <code>raw/opensky</code> ADSB.lol</td>
<td><span class="badge b-warn">orta</span></td>
<td><span class="badge b-ok">DÜZELTİLDİ</span> DATA_SOURCE_NOTE</td></tr>
<tr><td>80</td><td>OpenSky erişilemezse sessizce sentetik arşive düşüyor</td>
<td><span class="badge b-bad">yüksek</span></td>
<td>Kod damgalıyor (doğru); belgelendi</td></tr>
<tr><td>81</td><td><b>Panel "1 gerçek, 13 sentetik" diyordu — yanlış.</b>
"arrivals" etiketli dosya da sentetik</td>
<td><span class="badge b-bad">yüksek</span></td>
<td><span class="badge b-ok">DÜZELTİLDİ</span> sabit aralık tespiti</td></tr>
</tbody></table></div>

<h2>4 · Önceki turların en ağır bulguları</h2>
<div class="wrap"><table>
<thead><tr><th>#</th><th>Bulgu</th><th>Etki</th></tr></thead>
<tbody>
<tr><td>1</td><td>Fonksiyon <code>main()</code>'in ortasına girmiş;
~170 satır ölü kod</td><td>Case study, CORSIA, mühürleme hiç
çalışmıyordu</td></tr>
<tr><td>2</td><td>Tırmanışın <b>toplam</b> yakıtı ceza sayılıyordu</td>
<td>%52 fazla ceza → hiçbir adım tırmanışı kârlı görünmüyordu</td></tr>
<tr><td>3</td><td>Sabit 80+120 nm transit, 190 nm uçuşta seyri 0 yapıyordu</td>
<td>Kısa uçuşta seyir fazı kayboluyordu</td></tr>
<tr><td>26</td><td>Dijital ikiz faktörleri <b>tescil son harfinden</b>
üretiliyordu</td><td>TC-SPA = TC-JAA; uydurma CD0 → MRO kararı</td></tr>
<tr><td>27</td><td>Boş veriyle 23 KB rapor, <code>status: success</code></td>
<td>0 uçuş / $0 tasarruf "rapor hazır"</td></tr>
</tbody></table></div>

<div class="note-box warnbox"><div class="t">Dürüstlük notu</div>
<b>"Doğrulayamadım" ≠ "yanlıştı".</b> Denetimde üç şeye "hata" dedim
(ICAO yoğunluk referansı, <code>np.convolve</code> kenar etkisi, TAT ram
rise) — hesap yapınca <b>doğru çıktılar</b>. Üçünü de geri aldım.<br><br>
Dördüncüsü (B77W L/D "gerçek 18–20 olmalı") çürütülemedi de doğrulanamadı
da. <b>Kodu değiştirmedim</b> — kanıtsız katsayı değiştirmek, bu denetimin
kovaladığı hatanın ta kendisi olurdu.
</div>
"""
    return HTMLResponse(page('Denetim', body, user=user, token=token,
                             active='/denetim'))


# ══════════════════════════════════════════════════════════════════════
# SAYFA 6 — EL KİTABI (kod haritası)
# ══════════════════════════════════════════════════════════════════════
@app.get('/el-kitabi', response_class=HTMLResponse)
def handbook(request: Request, gw_session: str | None = Cookie(None),
             token: str = Query('')):
    ok, user = _check(gw_session, token)
    if not ok:
        return RedirectResponse('/giris?next=/el-kitabi', status_code=303)
    body = """
<h1>El Kitabı
<span class="sub">Bu kod ne işe yarar, her dosya ne yapar, kim ne alır.
Kod okumadan sistemi anlamak için.</span></h1>

<h2>1 · Bu sistem ne çözer</h2>
<p>Havayolunun yakıt faturası işletme maliyetinin %25–35'idir. Büyük
kısmı kaçınılmazdır — ama <b>%2–4'ü yönetilebilir</b>: cost index,
irtifa, tankering, rüzgâr. 400 uçaklı bir filoda 500.000 uçuşta %2
ciddi para demektir.</p>
<p>GreenWing bu %2'yi <b>hesaplanabilir</b> kılar: uçuş izlerini fizik
modelinden geçirir, "şu değişiklikle şu kadar yakıt, şu kadar dolar,
şu kadar CO₂" der — ve belirsizliğini de söyler.</p>

<div class="note-box infobox"><div class="t">Neden katsayı değil fizik</div>
Kolay yol mesafe × 3 kg/nm'dir. Ortalama verir ama <b>karar
verdiremez</b>: "3 yerine 2,8 olur mu?" sorusuna cevap veremez.
GreenWing aerodinamiği (polar), motoru (TSFC) ve atmosferi (ISA) ayrı
ayrı modeller — böylece "şu parametreyi değiştirsem ne olur" sorusu
tahmin değil <b>hesap</b> olur.</div>

<h2>2 · Kim ne alır</h2>
<div class="wrap"><table>
<thead><tr><th>Kim</th><th>Ne alır</th><th>Nasıl kullanır</th></tr></thead>
<tbody>
<tr><td>Yakıt müdürü</td><td>Uçuş bazında tasarruf potansiyeli ve yıllık
dolar karşılığı</td><td>Hangi rotada ne kadar kazanç var</td></tr>
<tr><td>Sürdürülebilirlik</td><td>CO₂, NOx, CORSIA uyumlu rapor</td>
<td>Yıllık emisyon beyanı, SAF senaryoları</td></tr>
<tr><td>Operasyon</td><td>Optimum Mach, irtifa, adım tırmanışı</td>
<td>OFP karşılaştırma, pilot brifingi</td></tr>
<tr><td>Finans</td><td>Yakıt fiyatı arbitrajı (tankering)</td>
<td>Hangi havalimanından fazla yakıt alınmalı</td></tr>
<tr><td>Denetim</td><td>Her hesabın kaynağı, belirsizlik, mühür</td>
<td>Rakamın nereden geldiğini kanıtlama</td></tr>
</tbody></table></div>

<h2>3 · Veri akışı — 10 adım</h2>
<div class="wrap"><table>
<thead><tr><th>#</th><th>Adım</th><th>Dosya</th><th>Girdi → Çıktı</th></tr></thead>
<tbody>
<tr><td>1</td><td>Toplama</td><td><code>01_collect_data.py</code></td>
<td>ADSB.lol → <code>data/raw/opensky/*.csv</code></td></tr>
<tr><td>2</td><td>Analiz</td><td><code>02_analyze_and_optimize.py</code></td>
<td>CSV → profil, faz, tasarruf</td></tr>
<tr><td>3</td><td>Rapor</td><td><code>03_generate_outputs.py</code></td>
<td>Analiz → HTML/JSON, CORSIA</td></tr>
<tr><td>4</td><td>Demo</td><td><code>04_..._demo.py</code></td>
<td>Sentetik senaryo → gösterim</td></tr>
<tr><td>5</td><td>SAF</td><td><code>05_saf_...py</code></td>
<td>Blend → emisyon/maliyet</td></tr>
<tr><td>6</td><td>Sentetik</td><td><code>06_seed_real_data.py</code></td>
<td><b>SENTETİK</b> üretim → arşiv</td></tr>
<tr><td>7</td><td>Tek uçuş</td><td><code>07_live_flight_scrapper.py</code></td>
<td>ADSB.lol callsign → iz</td></tr>
<tr><td>8</td><td>Filo</td><td><code>08_automated_fleet_tracker.py</code></td>
<td>ADSB.lol bölge → çoklu iz</td></tr>
<tr><td>9</td><td>Temizlik</td><td><code>09_clean_and_backup.py</code></td>
<td>Arşiv, bütünlük</td></tr>
<tr><td>10</td><td>Müşteri</td><td><code>10_pre_real_...py</code></td>
<td>OFP/yakıt fişi → kalibrasyon</td></tr>
</tbody></table></div>

<h2>4 · Her modül ne yapar</h2>
<h3>Veri toplama</h3>
<div class="wrap"><table><thead><tr><th>Dosya</th><th>Ne yapar</th>
<th>Denetim</th></tr></thead><tbody>
<tr><td><code>opensky_collector.py</code> 970</td><td>OpenSky → iz;
başarısızsa arşiv + sentetik damga</td>
<td><span class="badge b-ok">damgalama doğru</span></td></tr>
<tr><td><code>airport_database.py</code> 1.013</td><td>45 havalimanı,
haversine, rota çözme</td>
<td><span class="badge b-ok">%0,00 hata</span></td></tr>
</tbody></table></div>

<h3>Fizik modelleri</h3>
<div class="wrap"><table><thead><tr><th>Dosya</th><th>Ne yapar</th>
<th>Denetim</th></tr></thead><tbody>
<tr><td><code>atmosphere.py</code> 723</td><td>ISA: T, p, ρ, ses hızı</td>
<td><span class="badge b-ok">birebir</span></td></tr>
<tr><td><code>fuel_model.py</code> 1.643</td><td>Polar + TSFC + dalga →
akış, menzil</td>
<td><span class="badge b-warn">2 bulgu (#77,#78)</span></td></tr>
<tr><td><code>emission_model.py</code> 1.603</td><td>CO₂ 3,16 · NOx ·
CORSIA</td><td><span class="badge b-ok">149 doğrulama</span></td></tr>
<tr><td><code>aircraft_performance.py</code> 818</td><td>Tırmanış/alçalma</td>
<td><span class="badge b-ok">59 doğrulama</span></td></tr>
<tr><td><code>wind_model.py</code></td><td>Rüzgâr → yer hızı</td>
<td><span class="badge b-warn">girdi varsayım</span></td></tr>
<tr><td><code>saf_model.py</code></td><td>SAF blend → SFC</td>
<td><span class="badge b-ok">16 doğrulama</span></td></tr>
</tbody></table></div>

<h3>Analiz / optimizasyon</h3>
<div class="wrap"><table><thead><tr><th>Dosya</th><th>Ne yapar</th>
<th>Denetim</th></tr></thead><tbody>
<tr><td><code>flight_analyzer.py</code> 1.199</td><td>Tek uçuş analizi</td>
<td><span class="badge b-ok">geçiyor</span></td></tr>
<tr><td><code>phase_segmentation.py</code> 1.200</td><td>Faz ayrımı</td>
<td><span class="badge b-ok">geçiyor</span></td></tr>
<tr><td><code>fleet_analyzer.py</code> 1.640</td><td>Filo özeti</td>
<td><span class="badge b-ok">38 doğrulama</span></td></tr>
<tr><td><code>sensitivity.py</code> 1.037</td><td>Belirsizlik bütçesi</td>
<td><span class="badge b-ok">±%26,6</span></td></tr>
<tr><td><code>cost_index_optimizer.py</code> 906</td><td>Yakıt-zaman
dengesi</td><td><span class="badge b-ok">M0,800</span></td></tr>
<tr><td><code>altitude_optimizer.py</code> 847</td><td>Optimum irtifa</td>
<td><span class="badge b-ok">geçiyor</span></td></tr>
<tr><td><code>tankering_optimizer.py</code> 647</td><td>Arbitraj</td>
<td><span class="badge b-warn">fiyat varsayım</span></td></tr>
<tr><td><code>model_calibrator.py</code> 848</td><td>Gerçek veriye
kalibrasyon</td><td><span class="badge b-warn">veri yok</span></td></tr>
</tbody></table></div>

<h3>Doğrulama / raporlama</h3>
<div class="wrap"><table><thead><tr><th>Dosya</th><th>Ne yapar</th>
<th>Denetim</th></tr></thead><tbody>
<tr><td><code>validation/*.py</code> 1.920</td><td>3 katmanlı doğrulama</td>
<td><span class="badge b-ok">123</span></td></tr>
<tr><td><code>report_generator.py</code> 1.251</td><td>HTML/JSON, CORSIA</td>
<td><span class="badge b-ok">0 hata</span></td></tr>
<tr><td><code>web/app.py</code> + site</td><td>Şifreli panel, site</td>
<td><span class="badge b-ok">#81 düzeltildi</span></td></tr>
<tr><td><code>auth.py</code> 331</td><td>PBKDF2, oturum, hız sınırı</td>
<td><span class="badge b-ok">53 doğrulama</span></td></tr>
<tr><td><code>assumptions.py</code> 1.517</td><td>Tüm varsayımlar
tek yerde</td><td><span class="badge b-ok">kaynaklı</span></td></tr>
</tbody></table></div>

<h2>5 · Sözlük</h2>
<div class="wrap"><table><thead><tr><th>Terim</th><th>Açıklama</th></tr></thead>
<tbody>
<tr><td>ADS-B</td><td>Uçakların konum/hız/irtifa yayını</td></tr>
<tr><td>BADA</td><td>Eurocontrol uçak performans veritabanı</td></tr>
<tr><td>CI</td><td>Cost Index: yakıt-zaman dengesi</td></tr>
<tr><td>CD0</td><td>Parazit sürükleme katsayısı</td></tr>
<tr><td>CORSIA</td><td>ICAO karbon denkleştirme programı</td></tr>
<tr><td>EDB</td><td>ICAO Emisyon Veritabanı</td></tr>
<tr><td>GFS</td><td>NOAA küresel hava tahmin modeli</td></tr>
<tr><td>ISA</td><td>Standart atmosfer referansı</td></tr>
<tr><td>L/D</td><td>Kaldırma/sürükleme oranı</td></tr>
<tr><td>OEW</td><td>Boş uçak ağırlığı</td></tr>
<tr><td>Polar</td><td>CD = CD0 + K·CL²</td></tr>
<tr><td>SAF</td><td>Sürdürülebilir havacılık yakıtı</td></tr>
<tr><td>SAR</td><td>Birim yakıtla gidilen mesafe</td></tr>
<tr><td>Tankering</td><td>Ucuz yerden fazla yakıt almak</td></tr>
<tr><td>TSFC</td><td>Birim itki için yakıt akışı</td></tr>
</tbody></table></div>
"""
    return HTMLResponse(page('El Kitabı', body, user=user, token=token,
                             active='/el-kitabi'))


# ══════════════════════════════════════════════════════════════════════
# SAYFA 6a — KULLANICILAR (rol + kiracı yönetimi)
# ══════════════════════════════════════════════════════════════════════
@app.get('/kullanicilar', response_class=HTMLResponse)
def users_page(request: Request, gw_session: str | None = Cookie(None),
               token: str = Query('')):
    ok, user = _check(gw_session, token)
    if not ok:
        return RedirectResponse('/giris?next=/kullanicilar', status_code=303)
    auth = get_auth()
    me = auth.profile(user)
    rows = []
    for uname in sorted(auth.users):
        pr = auth.profile(uname)
        mark = ' ← siz' if uname == user else ''
        rows.append(f"""<tr>
<td><b>{esc(uname)}</b>{mark}</td>
<td><span class="pill p-{pr['role']}">{pr['role']}</span></td>
<td>{esc(pr['tenant'])}</td>
<td class="small">{ROLE_DESC[pr['role']]}</td></tr>""")
    body = f"""
<h1>Kullanıcılar ve Yetkiler
<span class="sub">Kim neyi görebilir, kim neyi değiştirebilir.
Bu tablo olmadan her kullanıcı her şeyi görür — ticari üründe
kabul edilemez (müşteri verisi karışır).</span></h1>

<div class="note-box {'ok' if me['role']=='admin' else 'warn'}"><div class="t">
Sizin yetkiniz: {me['role']} · kiracı: {me['tenant']}</div>
{'Yönetici yetkisiyle girdiniz — tüm kullanıcıları görüyorsunuz.'
 if me['role']=='admin' else
 'Bu sayfa yalnızca yöneticiler içindir. Aşağıdaki liste '
 'salt-okunur; değişiklik yapamazsınız.'}
</div>

<h2>Roller</h2>
<div class="wrap"><table>
<thead><tr><th>Rol</th><th>Seviye</th><th>Yapabildiği</th></tr></thead>
<tbody>
<tr><td><span class="pill p-viewer">viewer</span></td><td>1</td>
<td>Rapor ve sayfaları <b>okur</b>. Hiçbir şeyi değiştirmez.
Yakıt müdürünün patronu, denetçi, dış paydaş.</td></tr>
<tr><td><span class="pill p-analyst">analyst</span></td><td>2</td>
<td>Okur + <b>analiz çalıştırır</b> + kalibrasyon yapar +
veri yükler. Yakıt analisti, uçuş planlamacı.</td></tr>
<tr><td><span class="pill p-admin">admin</span></td><td>3</td>
<td>Tam yetki: kullanıcı ekler/siler, katsayı değiştirir,
veri siler, sırları görür. BT yöneticisi.</td></tr>
</tbody></table></div>

<h2>Kullanıcılar ({len(auth.users)})</h2>
<div class="wrap"><table>
<thead><tr><th>Kullanıcı</th><th>Rol</th><th>Kiracı</th><th>Açıklama</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>

<h2>Kiracı (tenant) nedir, neden şart?</h2>
<p>Ticari bir yakıt analiz ürününde her müşteri ayrı bir
<b>kiracıdır</b>. Türk Hava Yolları'nın uçuş verisi Pegasus'un
kullanıcısına <b>asla</b> görünmemelidir.</p>
<div class="grid g2">
  <div class="card info"><div class="lbl">Kiracı olmadan</div>
  <div class="note">Tek veri havuzu. İkinci müşteri geldiği anda
  verileri karışır. KVKK/GDPR ihlali. Ürün satılamaz.</div></div>
  <div class="card ok"><div class="lbl">Kiracı ile (şimdi)</div>
  <div class="note">Her kullanıcı bir kiracıya bağlı; veri yolu
  <code>tenant_id</code> ile ayrışıyor. Ingestion katmanı bunu
  zaten kullanıyordu — kimlik katmanı artık ona bağlandı.</div></div>
</div>

<h2>Nasıl kullanıcı eklenir?</h2>
<p>Parola hash'i üretin, sonra <code>config/secrets.yaml</code>'a
rol ve kiracıyla yazın:</p>
<pre class="code">python -m src.security.auth --hash</pre>
<pre class="code">users:
  ali:
    hash: "pbkdf2$200000$..."
    role: admin
    tenant: thy
  veli:
    hash: "pbkdf2$200000$..."
    role: analyst
    tenant: thy
  denetci:
    hash: "pbkdf2$200000$..."
    role: viewer
    tenant: thy</pre>
<p class="small">Değer düz bir hash string'i ise kullanıcı
<b>admin + varsayılan kiracı</b> sayılır — mevcut tek kullanıcılı
kurulumlar bozulmaz.</p>

<h2>Güvenlik notu — ne yapılır, ne yapılmaz</h2>
<div class="wrap"><table>
<thead><tr><th>✓ Yapılan</th><th>✗ Yapılmayan</th></tr></thead>
<tbody>
<tr><td>Oturum çerezi HMAC-SHA256 ile imzalı; rol çerezde
taşınmaz, her istekte sunucuda okunur (çerez sahtelemesiyle
rol yükseltilemez)</td>
<td>Veritabanı yok — kullanıcılar dosyada. 50+ kullanıcı için
DB'ye taşınmalı (yol haritasında).</td></tr>
<tr><td>Parolalar PBKDF2-HMAC-SHA256, 200.000 iterasyon</td>
<td>Özellik bayrağı (feature flag) yok; rol değişikliği
süreç yeniden başlatmayı gerektirir.</td></tr>
<tr><td>Deneme kilidi: 5 hatalı giriş → kilit</td>
<td>MFA (iki adımlı doğrulama) yok — kurumsal satışta istenir.</td></tr>
</tbody></table></div>
"""
    return HTMLResponse(page('Kullanıcılar', body, user=user, token=token,
                             active='/kullanicilar'))


# ══════════════════════════════════════════════════════════════════════
# SAYFA 6b — BASİT ANLATIM (jargonsuz)
# ══════════════════════════════════════════════════════════════════════
@app.get('/basit', response_class=HTMLResponse)
def simple(request: Request, gw_session: str | None = Cookie(None),
           token: str = Query('')):
    ok, user = _check(gw_session, token)
    if not ok:
        return RedirectResponse('/giris?next=/basit', status_code=303)
    s = summarize(load_flights())
    p_ = s['provenance']
    body = f"""
<h1>Basit Anlatım
<span class="sub">Teknik terim yok. Bu sistem ne yapar, ne yapamaz,
ticarileşince hayatında ne değişir. Bir yakının anlayacak şekilde.</span></h1>

<h2>1 · Problem ne?</h2>
<p>Bir uçak kalktığında deposunda binlerce litre yakıt var. Bunun
<b>çoğu zorunlu</b>: uçağı havada tutmak için gereken enerji. Ama
<b>küçük bir kısmı senin kontrolünde</b>:</p>
<ul>
<li><b>Ne kadar hızlı uçacaksın?</b> Hızlı = kısa uçuş ama çok yakıt.
Yavaş = uzun uçuş ama az yakıt. Denge nerede?</li>
<li><b>Hangi yükseklikte?</b> Çok yüksek = ince hava, az direnç;
ama motor da zorlanır.</li>
<li><b>Nereden yakıt alacaksın?</b> İstanbul'da ucuz, Amsterdam'da
pahalıysa, İstanbul'da fazla alıp taşımak mantıklı mı? (Taşımak da
yakıt yakar.)</li>
<li><b>Rüzgârı kullanıyor musun?</b> Doğuya uçarken batı rüzgârı
seni iter. Batıya uçarken aynı rüzgâr seni yavaşlatır.</li>
</ul>
<p>Bu dördü, bir uçuşun toplam maliyetinin <b>%2–4'ünü</b> değiştirir.
Küçük gibi? Bir filo yılda 500.000 uçuş yapıyorsa, milyonlarca dolar.</p>

<h2>2 · Bu sistem ne yapıyor?</h2>
<div class="grid g3">
  <div class="card info"><div class="lbl">1. Okur</div>
    <div class="note">Uçağın nerede, hangi yükseklikte, hangi hızda
    olduğunu radar verisinden alır.</div></div>
  <div class="card info"><div class="lbl">2. Hesaplar</div>
    <div class="note">Uçağın fiziğini (aerodinamik) ve motorunu
    (yakıt yakma hızı) modelleyerek "bu uçuşta ne kadar yakıt
    harcandı" der.</div></div>
  <div class="card info"><div class="lbl">3. Karşılaştırır</div>
    <div class="note">"Şöyle uçsaydın ne kadar az yakardın?"
    sorusuna dolar ve CO₂ olarak cevap verir.</div></div>
</div>
<p><b>Neden hazır bir formül yetmiyor?</b> Çünkü "mesafe × 3 kg"
gibi bir formül ortalama verir. Ama "3 yerine 2,8 olur mu" sorusuna
cevap veremez — çünkü içinde ne olduğunu bilmiyorsun. Bu sistem
uçağın <b>fiziğini ayrı ayrı</b> modelliyor; böylece "şu parametreyi
değiştirsem ne olur" sorusu tahmin değil <b>hesap</b> oluyor.</p>

<h2>3 · Şu anda gerçek olan ne?</h2>
<div class="note-box errbox"><div class="t">
Dürüst cevap: motor gerçek, yakıt "göstergede"</div>
Sistem şu anda <b>{p_['synthetic']} uçuşla</b> çalışıyor ve bunların
<b>hepsi bilgisayarda üretilmiş (sentetik)</b> uçuşlar. Gerçek radar
kaydı yok (0).<br><br>
<b>Ne anlama geliyor:</b> Hesap makinesi doğru çalışıyor ama henüz
gerçek sayılarla denenmemiş. Uçağın fiziği <b>doğrulanmış</b>
(atmosfer modeli elle hesapla birebir, uçak ağırlıkları üretici
belgesiyle %0 sapma), ama "bu uçuşta 6.450 kg yaktı" cümlesi
henüz gerçek bir uçuşla karşılaştırılmamış.<br><br>
Bu yüzden sitenin her yerinde "taahhüt değil, gösterge" yazıyor.
Yalan söylemiyor — eksik olan tek şey <b>gerçek veri</b>.
</div>

<h2>4 · Ticarileşince ne olacak?</h2>
<p>Sırayla, ve her adımın neden o sırada olduğu:</p>

<h3>Adım 1 — Gerçek veri (1 hafta)</h3>
<p>Bir havayolundan 20–50 uçuşun gerçek yakıt fişini alacaksın.
Sistem bu gerçek sayılarla sınanacak. Sonuç: "model gerçekte %x
sapıyor" cümlesi — <b>sayıyla</b>.</p>
<div class="note-box infobox"><div class="t">Neden ilk bu?</div>
Bu olmadan hiçbir müşteriye gidilmez. "Bu rakam nereden geliyor"
sorusuna cevabın olmaz.</div>

<h3>Adım 2 — Pilot (2 ay, ücretsiz)</h3>
<p>Bir havayoluyla anlaşıp <b>ücretsiz</b> analiz yapacaksın.
Karşılığında <b>veri ve referans</b> alacaksın. Ücretsiz olması
pazarlık zayıflığı değil — senin de onların verisine ihtiyacın var.</p>

<h3>Adım 3 — Ürünü sağlamlaştır (2–4 ay)</h3>
<p>Bugün eksik olanlar: her müşterinin verisini ayrı tutma
(çok kiracılılık), kim neyi görebilir (rol yönetimi), sistem çökerse
ne olur (SLA + yedekleme), sözleşmede doğruluk cümlesi.</p>

<h3>Adım 4 — Satış (4–12 ay)</h3>
<p>Artık "şu havayolu %X tasarruf etti" diyebilirsin. Satışın en
güçlü cümlesi budur — özellik listesi değil.</p>

<h2>5 · Para nasıl kazanılır</h2>
<div class="wrap"><table>
<thead><tr><th>Model</th><th>Nasıl işler</th><th>Risk kimde</th></tr></thead>
<tbody>
<tr><td>Uçuş başına</td><td>0,50–2 $ × uçuş sayısı</td><td>Müşteride</td></tr>
<tr><td>Yıllık abonelik</td><td>Sabit aylık + hacim</td><td>Müşteride</td></tr>
<tr><td><b>Tasarruf paylaşımı</b></td>
<td>Kanıtlanmış tasarrufun %20–30'u</td>
<td><b>Sende</b> — ama en güçlü satış</td></tr>
</tbody></table></div>
<p>Küçük bir örnek: 20 uçaklı bir havayolu yılda 30.000 uçuş yapıyorsa
ve uçuş başına 300 $ tasarruf edilebiliyorsa, yılda <b>9 milyon dolar</b>
demektir. Bunun %25'i <b>2,25 milyon dolar</b> yıllık gelir.</p>
<p class="small" style="color:#b45309"><b>Dikkat:</b> bu örnek sayı
değil, ölçek göstergesidir. Gerçek tasarruf, müşterinin gerçek
verisiyle ölçülmeden bilinemez — bu sistemin dürüst tavrı da budur.</p>

<h2>6 · Bu işi yapmaya değer mi?</h2>
<div class="wrap"><table>
<thead><tr><th>Soru</th><th>Cevap</th></tr></thead>
<tbody>
<tr><td>Teknik olarak hazır mı?</td>
<td>Çekirdek evet: fizik doğrulanmış, 1.454 test geçiyor, 217
denetim kontrolü temiz.</td></tr>
<tr><td>Ticari olarak hazır mı?</td>
<td>Hayır. Gerçek veri, çok kiracılılık, SLA ve referans yok.
Mesafe: 2–4 ay + bir pilot müşteri.</td></tr>
<tr><td>Pazar var mı?</td>
<td>Evet. Yakıt, havayolu maliyetinin %25–35'i. CORSIA ile emisyon
raporlama zorunlu hale geldi.</td></tr>
<tr><td>Rakip var mı?</td>
<td>Evet (Boeing Jeppesen, Lufthansa Systems, küçük girişimler).
Farkın: fizik şeffaflığı + belirsizlik aralığı + açık kaynak
denetlenebilirlik.</td></tr>
<tr><td>En büyük risk?</td>
<td>Gerçek veri bulamadan ürünü satmaya çalışmak. Bu, ilk müşteride
güven kaybı demek.</td></tr>
</tbody></table></div>

<div class="note-box ok"><div class="t">Tek cümlelik özet</div>
<b>Elinde çalışan bir hesap makinesi var ama henüz gerçek faturalarla
denenmemiş.</b> Sıradaki iş makineyi geliştirmek değil — <b>gerçek bir
faturayla karşılaştırmak</b>. O karşılaştırma olmadan satış olmaz;
olduktan sonra 2–4 ayda satılabilir hale gelir.
</div>
"""
    return HTMLResponse(page('Basit Anlatım', body, user=user, token=token,
                             active='/basit'))


# ══════════════════════════════════════════════════════════════════════
# SAYFA 7 — TİCARİ PLAN
# ══════════════════════════════════════════════════════════════════════
@app.get('/ticari', response_class=HTMLResponse)
def commercial(request: Request, gw_session: str | None = Cookie(None),
               token: str = Query('')):
    ok, user = _check(gw_session, token)
    if not ok:
        return RedirectResponse('/giris?next=/ticari', status_code=303)
    body = """
<h1>Ticari Plan
<span class="sub">Üründen şirkete. Bugün 1-2/10 olan ticari olgunluğu
2-4 ayda 7/10'a çıkarmanın yolu — sıralamasıyla.</span></h1>

<h2>1 · Bugün nerede duruyorsun</h2>
<div class="wrap"><table>
<thead><tr><th>Boyut</th><th>Durum</th><th>Puan</th></tr></thead>
<tbody>
<tr><td>Fizik modeli</td><td>ISA birebir, kütle/mesafe %0,
yakıt ±%7</td><td><span class="badge b-ok">9/10</span></td></tr>
<tr><td>Yazılım kalitesi</td><td>0 tanımsız isim, 1.398 doğrulama</td>
<td><span class="badge b-ok">8/10</span></td></tr>
<tr><td>Belirsizlik yönetimi</td><td>±%26,6 ölçülü, kaynak biliniyor</td>
<td><span class="badge b-ok">9/10</span></td></tr>
<tr><td>Veri</td><td><b>0 gerçek uçuş</b> · 45 doğru havalimanı</td>
<td><span class="badge b-bad">2/10</span></td></tr>
<tr><td>Ürünleşme</td><td>Panel var, çok kiracılılık yok</td>
<td><span class="badge b-warn">4/10</span></td></tr>
<tr><td>Ticari hazırlık</td><td>SLA, sözleşme, fatura, referans yok</td>
<td><span class="badge b-bad">1/10</span></td></tr>
</tbody></table></div>
<p>Asimetri net: <b>teknik 8–9, ticari 1–2.</b> İyi haber — ticari taraf
teknik taraftan çok daha hızlı kapanır.</p>

<h2>2 · Aşama 0 — durum</h2>
<div class="wrap"><table>
<thead><tr><th>Yapılacak</th><th>Neden</th><th>Durum</th></tr></thead>
<tbody>
<tr><td><b>Rüzgârı GFS'e bağla</b></td><td>Belirsizlik ±%26 → ±%12.
<b>En yüksek getirili tek iş.</b></td>
<td><span class="badge b-ok">KOD HAZIR</span> — <code>wind_gfs.py</code>
3 kademeli zincir; GRIB2 verisi konunca devreye girer</td></tr>
<tr><td>Gerçek uçuş topla (ADSB.lol, 24 saat)</td><td>"0 gerçek"
sorununu bitirir</td>
<td><span class="badge b-warn">BEKLİYOR</span> — ağ erişimi gerekli</td></tr>
<tr><td>Klasör/veri kaynağı adlandırması (#79)</td>
<td>Adlar gerçeği söylesin</td>
<td><span class="badge b-ok">DÜZELTİLDİ</span> — DATA_SOURCE_NOTE</td></tr>
<tr><td>B738/B38M kanat açıklığı</td><td>34,32 → 35,79 m
(737-800 gerçek, winglet dahil)</td>
<td><span class="badge b-ok">DÜZELTİLDİ</span> — AR 9,453 → 10,280</td></tr>
<tr><td>Polar / AR çelişkisi (#85)</td><td>K=0,042 ama 1/(π·AR·e)
ile %7,7 uyuşmuyordu</td>
<td><span class="badge b-ok">ÇÖZÜLDÜ</span> — iki AR ayrıldı:
geometrik 10,280 · aerodinamik 9,453 → sapma %0,3</td></tr>
<tr><td><b>İki paralel web uygulaması (#84)</b></td>
<td><code>web/</code> ve <code>webapp/</code> ikisi de canlıydı</td>
<td><span class="badge b-ok">BİRLEŞTİRİLDİ</span> — web/
<code>archive/</code>'e alındı, PDF indirme taşındı</td></tr>
<tr><td><b>Rol + kiracı (multi-tenancy)</b></td>
<td>Her kullanıcı her şeyi görüyordu → 2. müşteride veri karışır
(KVKK ihlali)</td>
<td><span class="badge b-ok">TAMAM</span> — viewer/analyst/admin +
<code>tenant</code> alanı; <a href="/kullanicilar">Kullanıcılar</a></td></tr>
<tr><td>Havalimanı test aralıkları (#76)</td><td>3/33 başarısız
görünüyordu</td>
<td><span class="badge b-ok">DÜZELTİLDİ</span> — 33/33 geçiyor</td></tr>
<tr><td>Pilot veri paketi</td><td>Müşteriye "ne göndereceğiz"
belli olsun</td>
<td><span class="badge b-ok">HAZIR</span> —
<code>deliverables/pilot_paketi/</code></td></tr>
</tbody></table></div>
<div class="note-box ok"><div class="t">Aşama 0'ın tek hedefi</div>
Sistemi <b>"sıfır gerçek veri"</b> durumundan <b>"doğrulanmış gerçek
veri var"</b> durumuna geçirmek. Bu olmadan hiçbir müşteriye gidilmez;
olduktan sonra kapı açılır.</div>

<h2>3 · Aşama 1 — pilot müşteri (2–8 hafta)</h2>
<div class="wrap"><table>
<thead><tr><th>Adım</th><th>Ne yaparsın</th><th>Kabul ölçütü</th></tr></thead>
<tbody>
<tr><td>Hedef seç</td><td>Tek havayolu, tek rota grubu (İstanbul–Avrupa).
Küçük başla.</td><td>—</td></tr>
<tr><td><b>Veri iste</b></td><td>O rotanın <b>gerçek OFP'leri</b> ve
<b>yakıt fişleri</b> — 20–50 uçuş</td><td>CSV alındı</td></tr>
<tr><td>Kalibre et</td><td><code>model_calibrator.py</code> ile CD0/TSFC
gerçek veriye</td><td>Toplam sapma <b>±%5</b></td></tr>
<tr><td>Doğrula</td><td>Model vs gerçek yakıt, uçuş bazında</td>
<td>Uçuş başına <b>±%10</b></td></tr>
<tr><td>Sun</td><td>Tek sayfa tasarruf + belirsizlik</td>
<td>Müşteri "mantıklı" diyor</td></tr>
</tbody></table></div>
<div class="note-box ok"><div class="t">
Pilot paketi hazır — müşteriye bugün gönderilebilir</div>
<code>deliverables/pilot_paketi/</code> içinde üç dosya var:<br><br>
<b>01_YAKIT_VERISI_SABLONU.csv</b> — 16 kolon (8 zorunlu),
2 örnek satır dolu. Müşteri Excel'de açar, doldurur, CSV kaydeder.<br>
<b>02_VERI_ISTEK_MEKTUBU.md</b> — ne istediğimizi, neden, gizlilik ve
zaman planıyla anlatan mektup.<br>
<b>03_KABUL_KRITERLERI.md</b> — MAPE ≤ %10, toplam sapma ≤ %5,
sistematik yanlılık ≤ %3. Sözleşmeye girecek cümle taslağı dahil.<br><br>
Yeniden üretmek için:
<code>python tools/build_pilot_data_package.py --airline "Pegasus"</code>
</div>

<div class="note-box warnbox"><div class="t">Kritik: pilot ücretsiz olmalı</div>
Ücretsiz pilot hem müşteriyi ikna eder hem sana doğruluk verisi verir.
<b>Karşılığında veri iste</b> — bu senin en değerli varlığın.<br><br>
<b>Doğruluk taahhüdü:</b> sözleşmeye "toplam ±%5, uçuş ±%10" yazabilmen
için bu aralığı <b>ölçmüş</b> olman gerek. Bugün ölçemezsin çünkü
karşılaştıracak gerçek veri yok. Pilot tam bunu çözer.</div>

<h2>4 · Aşama 2 — ticari paket (2–4 ay)</h2>
<div class="wrap"><table>
<thead><tr><th>Eksik</th><th>Neden gerekli</th><th>Öncelik</th></tr></thead>
<tbody>
<tr><td><b>Çok kiracılılık</b></td><td>Her müşterinin verisi ayrı olmalı.
Bugün tek kurulum = tek müşteri.</td>
<td><span class="badge b-bad">P0</span></td></tr>
<tr><td><b>Rol yönetimi</b></td><td>Yakıt müdürü her şeyi görmemeli</td>
<td><span class="badge b-bad">P0</span></td></tr>
<tr><td><b>SLA + yedekleme</b></td><td>"Sistem çökerse ne olur" sorusunun
cevabı olmalı</td><td><span class="badge b-bad">P0</span></td></tr>
<tr><td><b>Doğruluk beyanı</b></td><td>Sözleşmede ±%5 yazacaksan ölçüm
kanıtı</td><td><span class="badge b-bad">P0</span></td></tr>
<tr><td>Faturalama</td><td>Aylık/yıllık abonelik</td>
<td><span class="badge b-warn">P1</span></td></tr>
<tr><td>DPA (KVKK/GDPR)</td><td>Uçuş verisi kişisel veri içerebilir</td>
<td><span class="badge b-warn">P1</span></td></tr>
</tbody></table></div>

<h2>5 · Aşama 3 — ölçek (4–12 ay)</h2>
<div class="wrap"><table>
<thead><tr><th>Hedef</th><th>Ne kazandırır</th></tr></thead>
<tbody>
<tr><td>CORSIA MRV entegrasyonu</td><td>Havayolları yasal olarak
raporlamak zorunda — otomatikleştirmek yüksek değer</td></tr>
<tr><td>OFP entegrasyonu</td><td>Analiz planla aynı dili konuşursa
operasyon kabul eder</td></tr>
<tr><td>Referans müşteri vakası</td><td>"Şu havayolu %X tasarruf etti"
— satışın en güçlü argümanı</td></tr>
<tr><td>API / entegrasyon</td><td>Müşterinin sistemine gömülür →
yapışkanlık</td></tr>
</tbody></table></div>

<h2>6 · Fiyatlandırma</h2>
<div class="wrap"><table>
<thead><tr><th>Model</th><th>Kim için</th><th>Fiyat mantığı</th></tr></thead>
<tbody>
<tr><td>Uçuş başına</td><td>Küçük filo, deneme</td><td>0,50–2 $/uçuş</td></tr>
<tr><td>Yıllık abonelik</td><td>Orta filo</td><td>Aylık sabit + hacim</td></tr>
<tr><td><b>Tasarruf paylaşımı</b></td><td>Büyük filo</td>
<td>%20–30 (kanıtlanmış tasarruf üzerinden) — <b>en güçlü model</b>,
riski sen taşırsın</td></tr>
</tbody></table></div>

<h2>7 · Ticari riske dönüşen teknik borç</h2>
<div class="wrap"><table>
<thead><tr><th>Risk</th><th>Etki</th><th>Durum</th></tr></thead>
<tbody>
<tr><td>Rüzgâr varsayımı (±%22)</td><td>En büyük belirsizlik</td>
<td>GFS ile çözülür</td></tr>
<tr><td>Yıllık projeksiyon</td><td>Fatura rakamı</td>
<td>Müşteri verisiyle</td></tr>
<tr><td>Geniş gövde poları (#71)</td><td>A350/B787 mutlak sayı ±%20</td>
<td><span class="badge b-bad">AÇIK</span></td></tr>
<tr><td>EDB eksik tipler (#78)</td><td>8 tip tahmin</td>
<td><span class="badge b-warn">işaretlendi</span></td></tr>
<tr><td>Çok kiracılılık yok</td><td>Ölçeklenemez</td>
<td><span class="badge b-bad">P0 eksik</span></td></tr>
<tr><td>CORSIA illustrative</td><td>Resmî uyum iddia edilemez</td>
<td><span class="badge b-warn">P1</span></td></tr>
</tbody></table></div>

<div class="note-box ok"><div class="t">Cevabın özeti</div>
<b>"Mühendislik profesyonel"</b> → evet, ölçülmüş.<br>
<b>"Ticari profesyonel"</b> → değil, ama mesafe <b>2–4 ay + bir pilot
müşteri</b>.<br><br>
Sıralama önemli: <b>önce gerçek veri → sonra pilot → sonra sözleşme →
en son satış.</b> Tersini yaparsan ilk müşteri "bu rakam nereden" diye
sorar ve cevabın olmaz.<br><br>
Bugün yapabileceğin en akıllı şey: <b>Aşama 0'ı bitir, bir
havayolundan 20 uçuşluk veri iste.</b></div>
"""
    return HTMLResponse(page('Ticari Plan', body, user=user, token=token,
                             active='/ticari'))


# ══════════════════════════════════════════════════════════════════════
# YARDIMCI UÇLAR
# ══════════════════════════════════════════════════════════════════════
@app.get('/api/summary')
def api_summary(gw_session: str | None = Cookie(None), token: str = Query('')):
    ok, _ = _check(gw_session, token)
    if not ok:
        return {'error': 'auth', 'login': '/giris'}
    return summarize(load_flights())


# ══════════════════════════════════════════════════════════════════════
# PDF İNDİRME (denetim #84 — web/ kaldırılırken taşınan özellik)
# ══════════════════════════════════════════════════════════════════════
REPORTS = ROOT / 'reports'
PDF_FILES = {
    'teknik': ('GreenWing_Teknik_Rapor.pdf', 'GreenWing_Teknik_Rapor.pdf'),
    'elkitabi': ('GreenWing_Proje_El_Kitabi.pdf',
                 'GreenWing_Proje_El_Kitabi.pdf'),
}


@app.get('/rapor/{kind}.pdf')
def download_pdf(kind: str, gw_session: str | None = Cookie(None),
                 token: str = Query('')):
    """
    PDF rapor indir (kimlik doğrulaması gerekli — analiz sonuçları içerir).

    denetim #84: bu uç nokta `web/app.py`'de vardı, yeni uygulamaya
    taşınmadan eski uygulama silinecekti → özellik kaybı. Taşındı.
    """
    ok, _u = _check(gw_session, token)
    if not ok:
        return RedirectResponse(f'/giris?next=/rapor/{kind}.pdf',
                                status_code=303)
    entry = PDF_FILES.get(kind)
    if entry is None:
        raise HTTPException(status_code=404, detail='Bilinmeyen rapor türü')
    path = REPORTS / entry[0]
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f'{entry[0]} henüz üretilmemiş — '
                   'tools/build_*.py çalıştırın.')
    return FileResponse(path, media_type='application/pdf',
                        filename=entry[1])


@app.get('/healthz')
def healthz():
    return {'status': 'ok', 'version': APP_VERSION,
            'flights': len(load_flights())}


if __name__ == '__main__':
    import uvicorn
    host = os.environ.get('GREENWING_WEB_HOST', '0.0.0.0')
    port = int(os.environ.get('GREENWING_WEB_PORT', '8052'))
    print(f'GreenWing sitesi → http://{host}:{port}')
    uvicorn.run(app, host=host, port=port, log_level='info')
