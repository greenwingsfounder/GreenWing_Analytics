"""
GreenWing Analytics — Profesyonel Rapor Üretim Sistemi
══════════════════════════════════════════════════════
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import numpy as np

try:
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.subplots import make_subplots
    import base64
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

from config.settings import SYSTEM_NAME, SYSTEM_VERSION

# GÜVENLİK: Rapor HTML'i f-string ile üretiliyor. Dışarıdan gelen
# serbest metinler (havayolu adı, dönem) HTML'e kaçışsız girerse
# XSS'e (CWE-79) yol açar. Aşağıdaki yardımcı tüm serbest metinleri kaçışlar.
import html as _html_mod
import re as _re_mod


def escape_html(value) -> str:
    """Serbest metni HTML-güvenli hale getir (XSS savunması)."""
    return _html_mod.escape("" if value is None else str(value), quote=True)


_SAFE_FILENAME_RE = _re_mod.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str, fallback: str = "report") -> str:
    """
    Dosya adını güvenli hale getir (path traversal savunması, CWE-22).

    '/' , '..' ve benzeri karakterler temizlenir; boş/tehlikeli
    sonuç fallback'e düşer.
    """
    base = os.path.basename(str(name or ""))
    base = _SAFE_FILENAME_RE.sub("_", base).strip("._")
    if not base or base in {".", ".."}:
        return fallback
    return base[:150]


class ReportGenerator:

    def __init__(self):
        self.output_dir = os.path.join(
            os.path.dirname(__file__), '..', '..', 'reports'
        )
        os.makedirs(self.output_dir, exist_ok=True)

    def _fig_to_base64(self, fig, width=860, height=380) -> Optional[str]:
        if not PLOTLY_AVAILABLE:
            return None
        try:
            img_bytes = pio.to_image(fig, format='png', width=width, height=height)
            encoded   = base64.b64encode(img_bytes).decode('utf-8')
            return f"data:image/png;base64,{encoded}"
        except Exception:
            return None

    def _create_fuel_trend_chart(self, monthly_data: dict) -> Optional[str]:
        if not PLOTLY_AVAILABLE:
            return None
        months = list(monthly_data.keys())
        fuels  = [monthly_data[m].get('fuel_tonnes', 0) for m in months]
        co2s   = [monthly_data[m].get('co2_tonnes',  0) for m in months]

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Bar(x=months, y=fuels, name='Yakıt (ton)',
                   marker_color='#0984e3', opacity=0.75),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(x=months, y=co2s, name='CO₂ (ton)',
                       line=dict(color='#e94560', width=2.5),
                       mode='lines+markers'),
            secondary_y=True,
        )
        fig.update_layout(
            plot_bgcolor='white', paper_bgcolor='white',
            font=dict(family='Arial', size=11, color='#2d3436'),
            margin=dict(l=55, r=55, t=40, b=35),
            legend=dict(orientation='h', y=1.12, x=0),
        )
        fig.update_yaxes(
            title_text="Yakıt (ton)", secondary_y=False,
            gridcolor='#f0f0f0'
        )
        fig.update_yaxes(title_text="CO₂ (ton)", secondary_y=True)
        return self._fig_to_base64(fig)

    def _create_route_efficiency_chart(self, route_data: list, industry_avg: float = 6.6) -> Optional[str]:
        if not PLOTLY_AVAILABLE or not route_data:
            return None
        routes = [r.get('route', '') for r in route_data]
        fuels  = [r.get('fuel_per_nm', 0) for r in route_data]
        colors = [
            '#00b894' if x < industry_avg * 0.9 else '#fdcb6e' if x < industry_avg * 1.1 else '#d63031'
            for x in fuels
        ]
        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=routes, x=fuels, orientation='h',
            marker_color=colors,
            text=[f"{f:.2f}" for f in fuels],
            textposition='outside',
            textfont=dict(size=10),
        ))
        fig.add_vline(
            x=industry_avg, line_dash="dash", line_color="#e17055", line_width=1.5,
            annotation_text=f"Sektör Ort. ({industry_avg:.2f})",
            annotation_position="top left",
            annotation_font_size=10,
            annotation_font_color="#e17055"
        )
        fig.update_layout(
            plot_bgcolor='white', paper_bgcolor='white',
            font=dict(family='Arial', size=11, color='#2d3436'),
            margin=dict(l=120, r=65, t=15, b=35),
            xaxis_title="kg/Nm",
            xaxis=dict(gridcolor='#f0f0f0'),
        )
        return self._fig_to_base64(fig)

    @staticmethod
    def _score_color_label(score: float):
        if score >= 90:
            return '#00b894', 'Mükemmel'
        if score >= 80:
            return '#0984e3', 'İyi'
        if score >= 70:
            return '#fdcb6e', 'Orta'
        return '#d63031', 'İyileştirme Gerekli'

    def generate_fleet_report(
        self,
        fleet_summary: dict,
        airline_name: str = "Demo Airlines",
        reporting_period: str = "",
        output_filename: Optional[str] = None,
    ) -> dict:

        # ══════════════════════════════════════════════════════
        # DENETİM #56 — BOŞ VERİYLE "success" RAPORU
        # ══════════════════════════════════════════════════════
        # `generate_fleet_report({})` çağrısı 23 KB'lik bir HTML
        # üretiyor ve `status: "success"` dönüyordu: 0 uçuş,
        # 0 t yakıt, $0 tasarruf. Panelden "rapor hazır" diye
        # indirilebiliyordu.
        #
        # Sıfır uçuşlu bir analiz raporu, teslim edilebilir bir
        # çıktı değildir. Boş/eksik özette rapor üretilmemeli;
        # çağıran açık hata almalı.
        if not isinstance(fleet_summary, dict) or not fleet_summary:
            return {
                'status' : 'error',
                'message': ('Boş fleet_summary: analiz edilecek uçuş verisi '
                            'yok. Rapor üretilmedi. Önce scripts/02 ve '
                            'scripts/03 çalıştırılmalı.'),
                'html_path': None,
                'report_id': None,
            }

        _meta0 = fleet_summary.get('report_metadata', {}) or {}
        if int(_meta0.get('total_flights_analyzed', 0) or 0) <= 0:
            return {
                'status' : 'error',
                'message': ('total_flights_analyzed = 0: rapor üretilecek '
                            'uçuş yok. Sıfır uçuşlu rapor teslim edilebilir '
                            'bir çıktı değildir.'),
                'html_path': None,
                'report_id': None,
            }

        if output_filename is None:
            output_filename = (
                f"GreenWing_Fleet_Report_"
                f"{datetime.now().strftime('%Y%m%d')}"
            )
        if not reporting_period:
            reporting_period = (
                f"Analiz Raporu — {datetime.now().strftime('%B %Y')}"
            )

        # GÜVENLİK: serbest metinler HTML'e girmeden önce kaçışlanır (XSS),
        # dosya adı ise path traversal'a karşı temizlenir.
        airline_name = escape_html(airline_name)
        reporting_period = escape_html(reporting_period)
        output_filename = sanitize_filename(output_filename, "GreenWing_Fleet_Report")

        # ── Veri blokları ────────────────────────────────
        fs   = fleet_summary.get('fleet_summary', {})
        bm   = fleet_summary.get('benchmark', {})
        sv   = fleet_summary.get('savings_potential', {})
        ra   = fleet_summary.get('route_analysis', {})
        ap   = fleet_summary.get('altitude_performance', {})
        meta = fleet_summary.get('report_metadata', {})
        dq   = fleet_summary.get('data_quality', {})

        rankings  = ra.get('rankings', [])
        score     = float(fs.get('fleet_efficiency_score', 0))
        sc, sl    = self._score_color_label(score)
        n_flights = int(meta.get('total_flights_analyzed', 0))
        valid_n   = int(meta.get('valid_flights', n_flights))

        # ── Metrikler ────────────────────────────────────
        total_fuel_t = float(fs.get('total_fuel_tonnes', 0))
        total_co2_t  = float(fs.get('total_co2_tonnes', 0))
        avg_fuel_kg  = float(fs.get('avg_fuel_per_flight_kg', 0))
        avg_fuel_nm  = float(fs.get('avg_fuel_per_nm', 0))

        ann_cost = float(sv.get('annualized_cost_saving_usd', 0))

        # ── DENETİM #29: belirsizlik aralığı ────────────────
        # sensitivity.py ±%26,7 (rüzgâr baskın) hesaplıyor ama
        # rapor tek nokta değeri gösteriyordu. Müşteri bunu
        # taahhüt sanabilir; aralık HTML'e yazılıyor.
        _unc = sv.get('uncertainty') or {}
        if _unc.get('available'):
            unc_html = (
                f'<div style="font-size:11px;color:#636e72;margin-top:4px;">'
                f'Aralık: ${_unc["low_usd"]:,.0f} – ${_unc["high_usd"]:,.0f} '
                f'(&plusmn;%{_unc["total_uncertainty_pct"]}). '
                f'En büyük belirsizlik: {_unc["dominant_source"]}. '
                f'Bu bir taahhüt değil, aralıklı tahmindir.</div>'
            )
        else:
            unc_html = (
                '<div style="font-size:11px;color:#b2bec3;margin-top:4px;">'
                'Belirsizlik aralığı hesaplanamadı.</div>'
            )
        ann_fuel = float(sv.get('annualized_fuel_saving_tonnes', 0))
        ann_co2  = float(sv.get(
            'annualized_co2_saving_tonnes',
            round(ann_fuel * 3.16, 1)
        ))

        sar_loss = float(ap.get('avg_sar_loss_pct', 0))
        avg_dev  = float(ap.get('avg_deviation_from_optimum_ft', 0))
        step_n   = int(ap.get('flights_with_step_climb', 0))
        dev_pct  = int(ap.get('deviation_pct', 55))

        bm_fleet   = float(bm.get('fleet_fuel_per_nm', 0))
        bm_avg     = float(bm.get('industry_avg_fuel_per_nm', 8.2))
        bm_best    = float(bm.get('industry_best_fuel_per_nm', 6.8))
        bm_rating  = bm.get('rating', 'N/A')
        bm_gap     = float(bm.get('gap_to_best_pct', 0))
        bm_n       = int(bm.get('based_on_n_flights', 0))
        bm_warn    = bm.get('data_quality_warning')

        # CORSIA offset
        excess_co2_t   = total_co2_t * 0.05
        illustr_offset = round(excess_co2_t * 30)

        # Rapor kimliği
        report_id = f"GWA-RPT-{datetime.now().strftime('%Y%m%d')}"
        generated = datetime.now().strftime('%d/%m/%Y %H:%M')

        # ── Grafikler ────────────────────────────────────
        fuel_trend_html  = (
            '<p style="color:#aaa;font-size:12px;text-align:center;'
            'padding:30px 0;">Grafik üretilemedi — pip install kaleido</p>'
        )
        route_chart_html = ''

        if PLOTLY_AVAILABLE:
            # CRITICAL FIX: NO RANDOM in reports for real customer data.
            # Use deterministic synthetic trend ONLY when no real monthly data provided.
            # In real use: pass 'monthly_actual' in fleet_summary to override.
            current_date = datetime.now()
            months = []
            for i in range(5, -1, -1):
                m_diff = current_date.month - i
                year = current_date.year
                month = m_diff
                while month <= 0:
                    month += 12
                    year -= 1
                months.append(f"{year}-{month:02d}")

            # Use provided real monthly if present (from ingestion), else mark as illustrative
            monthly_actual = fleet_summary.get('monthly_actual')
            if monthly_actual and len(monthly_actual) >= 3:
                monthly = {m: {'fuel_tonnes': v.get('fuel_tonnes', 0), 'co2_tonnes': v.get('co2_tonnes', 0)} 
                           for m, v in list(monthly_actual.items())[:6]}
            else:
                # ILLUSTRATIVE ONLY — never use for customer pitch with real data
                avg_mf  = total_fuel_t / max(len(months), 1)
                monthly = {
                    m: {
                        'fuel_tonnes': round(avg_mf * (0.96 + (i*0.008)), 1),
                        'co2_tonnes': round(avg_mf * (0.96 + (i*0.008)) * 3.16, 1),
                    }
                    for i, m in enumerate(months)
                }
                # Add note that this is synthetic
                fuel_trend_html = fuel_trend_html or ''  # will be overwritten below with warning

            img = self._create_fuel_trend_chart(monthly)
            if img:
                fuel_trend_html = (
                    f'<img src="{img}" '
                    f'style="width:100%;max-width:820px;'
                    f'display:block;margin:0 auto;">'
                )
            if not monthly_actual:
                fuel_trend_html += '<p style="font-size:10px;color:#c0392b;text-align:center;margin-top:4px;">⚠️ TREND İLLÜSTRATİF / SENTETİK — Gerçek aylık verilerle değiştirin (PRE-REAL DEMO)</p>'

            if rankings:
                sorted_r = sorted(
                    rankings, key=lambda x: x.get('fuel_per_nm', 0)
                )
                img2 = self._create_route_efficiency_chart(sorted_r)
                if img2:
                    route_chart_html = (
                        f'<img src="{img2}" '
                        f'style="width:100%;max-width:820px;'
                        f'display:block;margin:0 auto;">'
                    )


        # ── KALİBRASYON BİLGİSİ (Pre-Real Data) ─────────────────────────
        cal = fleet_summary.get('calibration') or {}
        actual_vs = fleet_summary.get('actual_vs_model') or {}
        
        cal_html = ""
        if cal and cal.get('n_calibrated_flights', 0) > 0:
            cal_html = f"""
            <div style="background:#f0f9ff;border:2px solid #0984e3;border-radius:8px;padding:14px 18px;margin:18px 0 25px 0;">
                <div style="font-weight:700;color:#0984e3;margin-bottom:8px;font-size:14px;">
                    🔬 MODEL KALİBRASYONU (Gerçek Yakıt Verisiyle)
                </div>
                <div style="display:flex;gap:22px;flex-wrap:wrap;font-size:12.5px;line-height:1.4;">
                    <div><strong>CD0 faktörü:</strong> {cal.get('avg_cd0_factor', 1.0):.4f}</div>
                    <div><strong>SFC faktörü:</strong> {cal.get('avg_sfc_factor', 1.0):.4f}</div>
                    <div><strong>Doğruluk iyileşmesi:</strong> <span style="color:#00b894;font-weight:600;">+{cal.get('accuracy_improvement', 0):.1f}%</span></div>
                    <div><strong>Kalibre edilen uçuş:</strong> {cal.get('n_calibrated_flights', 0)}</div>
                </div>
                <div style="margin-top:6px;font-size:11.5px;color:#444;">
                    Bu rapor <strong>müşteri gerçek yakıt verisi</strong> ile kalibre edilmiş model kullanılarak üretilmiştir.
                    Model hatası %{fleet_summary.get('calibration', {}).get('accuracy_before', 10):.1f} → %{fleet_summary.get('calibration', {}).get('accuracy_after', 4):.1f}
                </div>
            </div>
            """
        
        # Also show actual vs model if present
        avm_html = ""
        if actual_vs and actual_vs.get('total_actual_fuel_kg'):
            avm_html = f"""
            <div style="font-size:12px;color:#555;margin:4px 0 18px 0;">
                <strong>Gerçek vs Model Yakıt:</strong> 
                Gerçek {actual_vs.get('total_actual_fuel_kg',0):,} kg — Model {actual_vs.get('total_model_fuel_kg',0):,} kg 
                (Fark: {actual_vs.get('diff_pct',0):.1f}%)
            </div>
            """

                # ── Veri kalitesi kutusu ─────────────────────────
        
        # === CALIBRATION BOX (auto-rendered for pre-real pipeline) ===
        cal_box = ""
        cal = fleet_summary.get('calibration') or {}
        avm = fleet_summary.get('actual_vs_model') or {}
        if cal and cal.get('n_calibrated_flights', 0) > 0:
            cal_box = f'''
            <div style="background:#f0f9ff;border:2px solid #0984e3;border-radius:8px;padding:13px 18px;margin:10px 0 22px 0;">
                <strong style="color:#0984e3;">🔬 Model Kalibrasyonu (Gerçek Yakıt ile)</strong><br>
                <span style="font-size:12.5px;">
                    CD0: {cal.get('avg_cd0_factor',1):.4f} &nbsp;|&nbsp; 
                    SFC: {cal.get('avg_sfc_factor',1):.4f} &nbsp;|&nbsp; 
                    Doğruluk: %{cal.get('accuracy_before_pct',10):.1f} → <strong style="color:#00b894;">%{cal.get('accuracy_after_pct',4):.1f}</strong> 
                    (+{cal.get('improvement_pct',0):.1f}%) &nbsp;|&nbsp; 
                    {cal.get('n_calibrated_flights')} uçuş
                </span>
                <div style="font-size:11px;margin-top:4px;color:#444;">
                    Müşteri gerçek yakıt verisiyle kalibre edilmiş model kullanılmıştır.
                </div>
            </div>
            '''

        partial_pct = float(dq.get('partial_pct', 0))
        partial_n   = int(dq.get('partial_flights', 0))
        # BÜTÜNLÜK: iki anahtar adı da desteklenir ('grade' eski sürüm).
        dq_grade    = dq.get('quality_grade') or dq.get('grade') or 'N/A'
        dq_recs     = dq.get('recommendations', [])

        if dq_grade in ('A', 'B'):
            dq_bg, dq_border = '#f0fff4', '#00b894'
            dq_color  = '#00b894'
            dq_icon   = '✅'
            dq_title  = f'Veri Kalitesi {dq_grade} — Gerçek Veri'
        elif dq_grade == 'SIM':
            # BÜTÜNLÜK: Simülasyon verisi ASLA "güvenilir" diye sunulmaz.
            dq_bg, dq_border = '#fff5f5', '#d63031'
            dq_color  = '#d63031'
            dq_icon   = '⚠'
            dq_title  = ('SİMÜLASYON VERİSİ — Gerçek uçuş verisi DEĞİL. '
                         'Yalnızca model gösterimi.')
        elif dq_grade == 'MIX':
            dq_bg, dq_border = '#fffbf0', '#e17055'
            dq_color  = '#b35c00'
            dq_icon   = '⚠'
            dq_title  = ('KARIŞIK VERİ — Gerçek + simüle uçuşlar '
                         'ayrıştırılmalı.')
        elif dq_grade == 'C':
            dq_bg, dq_border = '#fffbf0', '#fdcb6e'
            dq_color  = '#856404'
            dq_icon   = '⚠'
            dq_title  = 'Veri Kalitesi C — Kısmi Kullanım'
        else:
            dq_bg, dq_border = '#fff5f5', '#d63031'
            dq_color  = '#d63031'
            dq_icon   = '⚠'
            dq_title  = 'Veri Kalitesi D — Dikkatli Yorum'

        dq_rec_html = ''
        if dq_recs:
            items = ''.join(
                f'<li style="margin:3px 0;">{r}</li>'
                for r in dq_recs[:3]
            )
            dq_rec_html = (
                f'<ul style="margin:8px 0 0 18px;padding:0;'
                f'font-size:11.5px;">{items}</ul>'
            )

        cal_box_html = cal_box
        dq_box = f"""
        <div style="background:{dq_bg};border:1px solid {dq_border};
                    border-left:4px solid {dq_border};border-radius:6px;
                    padding:13px 16px;margin:0 0 20px 0;">
            <div style="font-weight:700;color:{dq_color};margin-bottom:6px;">
                {dq_icon} {dq_title}
            </div>
            <div style="font-size:11.5px;color:#555;">
                Toplam: <strong>{n_flights}</strong> uçuş &nbsp;|&nbsp;
                Tam: <strong>{valid_n}</strong> &nbsp;|&nbsp;
                Partial: <strong>{partial_n}</strong>
                (%{partial_pct:.0f})
            </div>
            {dq_rec_html}
        </div>"""

        # ── Benchmark uyarısı ────────────────────────────
        bm_warn_html = ''
        if bm_warn:
            bm_warn_html = f"""
            <div style="background:#fffbf0;border:1px solid #fdcb6e;
                        border-left:4px solid #fdcb6e;border-radius:6px;
                        padding:11px 15px;margin:12px 0;">
                <strong style="color:#856404;">⚠ Benchmark Notu</strong>
                <div style="font-size:11.5px;color:#555;margin-top:5px;">
                    {bm_warn}
                </div>
            </div>"""

        # ── Rota tablosu ─────────────────────────────────
        route_rows = ''
        for i, r in enumerate(rankings[:15]):
            bg      = '#fff8f8' if i < 3 else 'white'
            co2_ton = r.get('total_co2_kg', 0) / 1000
            route_rows += f"""
            <tr style="background:{bg};">
                <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
                           color:#888;font-size:12px;">{i+1}</td>
                <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
                           font-weight:600;">{r.get('route','–')}</td>
                <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
                           text-align:center;">{r.get('flights',0)}</td>
                <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
                           text-align:right;">
                    {r.get('avg_fuel_kg',0):,.0f}</td>
                <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
                           text-align:right;font-weight:600;color:#0984e3;">
                    {r.get('fuel_per_nm',0):.2f}</td>
                <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
                           text-align:right;color:#888;">
                    ±{r.get('fuel_consistency_std',0):.0f}</td>
                <td style="padding:9px 8px;border-bottom:1px solid #f0f0f0;
                           text-align:right;">{co2_ton:.1f}</td>
            </tr>"""

        # ── HTML ─────────────────────────────────────────
        html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>{SYSTEM_NAME} — {airline_name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{
    font-family:'Segoe UI',Arial,sans-serif;
    color:#2d3436;
    line-height:1.65;
    background:#fff;
    font-size:13px;
}}
.page{{max-width:860px;margin:0 auto;padding:28px 32px;}}

/* ── Header ── */
.header{{
    display:flex;
    justify-content:space-between;
    align-items:flex-start;
    border-bottom:3px solid #0984e3;
    padding-bottom:16px;
    margin-bottom:26px;
}}
.header-left h1{{
    color:#0984e3;font-size:22px;font-weight:700;line-height:1.3;
}}
.header-left .subtitle{{color:#636e72;font-size:12px;margin-top:3px;}}
.header-left .airline{{
    color:#0984e3;font-size:13px;font-weight:600;margin-top:4px;
}}
.header-right{{
    text-align:right;font-size:11px;color:#636e72;line-height:1.8;
}}
.header-right strong{{color:#2d3436;}}
.report-id{{color:#0984e3;font-weight:600;}}

/* ── Section ── */
.section{{margin-bottom:28px;}}
.section h2{{
    font-size:16px;font-weight:700;color:#2d3436;
    border-left:4px solid #0984e3;padding-left:11px;
    margin-bottom:14px;
}}

/* ── Highlight box ── */
.hbox{{
    background:#f0f8ff;border:1px solid #b3d4f5;
    border-radius:7px;padding:14px 16px;margin-bottom:14px;
}}
.hbox ul{{margin:8px 0 0 18px;padding:0;}}
.hbox ul li{{margin:4px 0;font-size:12.5px;}}

/* ── KPI Grid ── */
.kpi-grid{{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:11px;
    margin-bottom:10px;
}}
.kpi-card{{
    background:#f8f9fa;
    border:1px solid #e0e0e0;
    border-radius:8px;
    padding:14px 12px;
    text-align:center;
    display:flex;
    flex-direction:column;
    align-items:center;
    justify-content:center;
}}
.kpi-card .lbl{{
    font-size:10px;color:#888;
    text-transform:uppercase;letter-spacing:0.8px;
    margin-bottom:6px;
    min-height:14px;
}}
.kpi-card .val{{
    font-size:26px;font-weight:700;
    color:#0984e3;line-height:1.1;
}}
.kpi-card .sub{{font-size:10px;color:#aaa;margin-top:4px;}}
.kpi-note{{font-size:11px;color:#888;margin-top:5px;}}

/* ── Benchmark table ── */
.bm-table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px;}}
.bm-table td{{padding:7px 10px;border-bottom:1px solid #f0f0f0;}}
.bm-table td:last-child{{text-align:right;font-weight:600;}}

/* ── Route table ── */
table.route-table{{width:100%;border-collapse:collapse;font-size:12px;}}
table.route-table th{{
    background:#0984e3;color:white;
    padding:9px 8px;text-align:left;
    font-size:11px;font-weight:600;
}}

/* ── Savings box ── */
.sbox{{
    background:#f0fff4;border:1px solid #00b894;
    border-radius:7px;padding:15px 16px;margin-bottom:16px;
}}
.sbox h3{{
    color:#00b894;font-size:14px;font-weight:700;margin-bottom:12px;
}}
.sbox-grid{{
    display:grid;grid-template-columns:repeat(3,1fr);gap:10px;
}}
.sbox-item{{text-align:center;}}
.sbox-item .sv{{font-size:22px;font-weight:700;color:#00b894;}}
.sbox-item .sl{{font-size:10px;color:#666;margin-top:4px;}}

/* ── Recommendations ── */
.rec{{
    background:#f8f9fa;
    border-left:4px solid #00b894;
    padding:11px 14px;margin:8px 0;
    border-radius:0 7px 7px 0;
}}
.rec .pri{{
    display:inline-block;padding:2px 8px;
    border-radius:4px;font-size:10px;font-weight:700;margin-right:7px;
}}
.pri-h{{background:#ffe0e0;color:#c0392b;}}
.pri-m{{background:#fef3cd;color:#856404;}}
.pri-l{{background:#d4edda;color:#155724;}}
.rec strong{{font-size:13px;}}
.rec p{{font-size:11.5px;color:#555;margin-top:5px;line-height:1.5;}}

/* ── İrtifa ── */
.alt-grid{{
    display:grid;grid-template-columns:repeat(3,1fr);gap:10px;
}}
.alt-item{{
    background:#f8f9fa;border:1px solid #e0e0e0;
    border-radius:7px;padding:14px 12px;text-align:center;
}}
.alt-item .av{{font-size:20px;font-weight:700;color:#0984e3;}}
.alt-item .al{{font-size:10px;color:#888;margin-top:4px;}}

/* ── CORSIA ── */
.corsia-disc{{
    background:#fff5f5;border:1px solid #e74c3c;
    border-left:4px solid #e74c3c;border-radius:6px;
    padding:12px 15px;margin-bottom:12px;
}}
.corsia-warn{{
    background:#fffbf0;border:1px solid #f39c12;
    border-left:4px solid #f39c12;border-radius:6px;
    padding:12px 15px;
}}
.corsia-disc strong,.corsia-warn strong{{font-size:13px;}}
.corsia-disc p,.corsia-warn p{{
    font-size:11.5px;color:#555;margin-top:5px;line-height:1.5;
}}

/* ── Next steps ── */
.nst{{width:100%;border-collapse:collapse;font-size:12px;}}
.nst th{{
    background:#0984e3;color:white;padding:9px 10px;
    text-align:left;font-size:11px;font-weight:600;
}}
.nst td{{padding:9px 10px;border-bottom:1px solid #f0f0f0;}}

/* ── Footer ── */
.footer{{
    margin-top:32px;padding-top:14px;
    border-top:2px solid #e0e0e0;
    font-size:10px;color:#aaa;text-align:center;line-height:1.8;
}}

/* ── Page break ── */
.pb{{page-break-before:always;margin-top:28px;}}

@media print{{
    .page{{padding:15px 18px;max-width:100%;}}
    .pb{{page-break-before:always;}}
}}
</style>
</head>
<body>
<div class="page">

<!-- ════════════════════════════════════════════════════
     HEADER
═══════════════════════════════════════════════════════ -->
<div class="header">
    <div class="header-left">
        <h1>✈️ {SYSTEM_NAME}</h1>
        <div class="airline">{airline_name}</div>
        <div class="subtitle">
            Filo Yakıt Verimliliği ve Emisyon Analiz Raporu
        </div>
    </div>
    <div class="header-right">
        <div>Dönem: <strong>{reporting_period}</strong></div>
        <div>Oluşturulma: <strong>{generated}</strong></div>
        <div class="report-id">{report_id}</div>
    </div>
</div>
<!-- ════════════════════════════════════════════════════
     YÖNETİCİ ÖZETİ
═══════════════════════════════════════════════════════ -->
<div class="section">
    <h2>📋 Yönetici Özeti</h2>
    <p style="margin-bottom:12px;color:#555;font-size:12.5px;">
        Bu rapor, <strong>{airline_name}</strong> operasyonunun
        <strong>{reporting_period}</strong> dönemindeki yakıt
        verimliliği performansını, emisyon profilini ve optimizasyon
        fırsatlarını değerlendirmektedir.
    </p>
    <div class="hbox">
        <strong>Temel Bulgular:</strong>
        <ul>
            <li>Analiz edilen uçuş:
                <strong>{n_flights:,}</strong></li>
            <li>Filo verimlilik skoru:
                <strong style="color:{sc};">
                    {score:.1f}/100 ({sl})
                </strong>
            </li>
            <li>Toplam CO₂ emisyonu:
                <strong>{total_co2_t:,.0f} ton</strong></li>
            <li>Benchmark:
                <strong>{bm_rating}</strong></li>
            <li>Tespit edilen tasarruf potansiyeli:
                <strong style="color:#00b894;">
                    ${ann_cost:,.0f}/yıl
                </strong>
                {unc_html}
            </li>
        </ul>
    </div>
</div>

<!-- ════════════════════════════════════════════════════
     VERİ KALİTESİ
═══════════════════════════════════════════════════════ -->
<div class="section">
    <h2>🔍 Veri Kalitesi</h2>
    {dq_box}
</div>

<!-- ════════════════════════════════════════════════════
     KPI KARTLARI
═══════════════════════════════════════════════════════ -->
<div class="section">
    <h2>📊 Temel Performans Göstergeleri</h2>
    <div class="kpi-grid">

        <div class="kpi-card">
            <div class="lbl">Toplam Yakıt</div>
            <div class="val">{total_fuel_t:,.0f}</div>
            <div class="sub">ton</div>
        </div>

        <div class="kpi-card">
            <div class="lbl">Toplam CO₂</div>
            <div class="val" style="color:#e94560;">
                {total_co2_t:,.0f}
            </div>
            <div class="sub">ton</div>
        </div>

        <div class="kpi-card">
            <div class="lbl">Verimlilik</div>
            <div class="val" style="color:{sc};">{score:.1f}</div>
            <div class="sub">/100 — {sl}</div>
        </div>

        <div class="kpi-card">
            <div class="lbl">Ort. Yakıt / Uçuş</div>
            <div class="val">{avg_fuel_kg:,.0f}</div>
            <div class="sub">kg</div>
        </div>

        <div class="kpi-card">
            <div class="lbl">Ort. Yakıt / Nm</div>
            <div class="val">{avg_fuel_nm:.2f}</div>
            <div class="sub">kg/Nm</div>
        </div>

        <div class="kpi-card">
            <div class="lbl">Toplam Uçuş</div>
            <div class="val">{n_flights:,}</div>
            <div class="sub">analiz edilen</div>
        </div>

    </div>
    <p class="kpi-note">
        ※ Ortalama yakıt/Nm tüm uçuşları kapsar.
        Benchmark kıyaslaması tam uçuşlara dayandırılmıştır.
    </p>
</div>

<!-- ════════════════════════════════════════════════════
     TREND GRAFİĞİ
═══════════════════════════════════════════════════════ -->
<div class="section">
    <h2>📈 Yakıt Tüketimi ve CO₂ Emisyon Trendi</h2>
    {fuel_trend_html}
</div>

<!-- ════════════════════════════════════════════════════
     SAYFA KIRISI 1
═══════════════════════════════════════════════════════ -->
<div class="pb"></div>

<!-- ════════════════════════════════════════════════════
     ROTA ANALİZİ
═══════════════════════════════════════════════════════ -->
<div class="section">
    <h2>🛤 Rota Bazlı Verimlilik Analizi</h2>
    <p style="font-size:12px;color:#555;margin-bottom:10px;">
        <strong>kg/Nm</strong> metriği mesafe normalize yakıt tüketimini
        gösterir. Düşük = verimli &nbsp;|&nbsp;
        Kırmızı = sektör ortalaması üstü.
    </p>
    {route_chart_html}
    <table class="route-table" style="margin-top:12px;">
        <thead>
            <tr>
                <th style="width:36px;">#</th>
                <th>Rota</th>
                <th style="text-align:center;width:60px;">Uçuş</th>
                <th style="text-align:right;">Ort. Yakıt (kg)</th>
                <th style="text-align:right;width:72px;">kg/Nm</th>
                <th style="text-align:right;width:80px;">Tutarlılık</th>
                <th style="text-align:right;width:72px;">CO₂ (ton)</th>
            </tr>
        </thead>
        <tbody>{route_rows}</tbody>
    </table>
</div>

<!-- ════════════════════════════════════════════════════
     BENCHMARK
═══════════════════════════════════════════════════════ -->
<div class="section">
    <h2>📏 Sektör Benchmark Karşılaştırması</h2>
    {bm_warn_html}
    <div class="hbox">
        <table class="bm-table">
            <tr>
                <td>Benchmark bazlı filo ortalaması</td>
                <td style="color:#0984e3;">{bm_fleet:.2f} kg/Nm</td>
            </tr>
            <tr>
                <td>Sektör ortalaması</td>
                <td>{bm_avg:.2f} kg/Nm</td>
            </tr>
            <tr>
                <td>Sektör en iyi</td>
                <td>{bm_best:.2f} kg/Nm</td>
            </tr>
            <tr>
                <td>Değerlendirme</td>
                <td style="font-weight:700;">{bm_rating}</td>
            </tr>
            <tr>
                <td>En iyiye fark</td>
                <td>%{bm_gap:.1f}</td>
            </tr>
            <tr>
                <td>Kullanılan tam uçuş</td>
                <td>{bm_n}</td>
            </tr>
        </table>
    </div>
    <p style="font-size:11px;color:#888;margin-top:8px;">
        ※ Benchmark kıyaslaması yalnızca tam trajectory'ye sahip
        uçuşlara dayandırılmıştır.
    </p>
</div>

<!-- ════════════════════════════════════════════════════
     İRTİFA OPTİMİZASYON PERFORMANSI
═══════════════════════════════════════════════════════ -->
<div class="section">
    <h2>📐 İrtifa Optimizasyon Performansı</h2>
    <div class="alt-grid">
        <div class="alt-item">
            <div class="al">Ort. ATC FL Sapması</div>
            <div class="av">{avg_dev:,.0f} ft</div>
        </div>
        <div class="alt-item">
            <div class="al">Ort. SAR Kaybı</div>
            <div class="av">%{sar_loss:.2f}</div>
        </div>
        <div class="alt-item">
            <div class="al">Step Climb Uygulanan</div>
            <div class="av">{step_n} / {n_flights}</div>
        </div>
    </div>
    <p style="font-size:11.5px;color:#777;margin-top:10px;">
        ※ ATC kısıtı, traffic separation ve slot yönetimi nedeniyle
        uçuşların {dev_pct}%'inde optimum FL'den sapma modellendi.
        (Stokastik operasyonel model — Eurocontrol PRR 2023)
    </p>
</div>

<!-- ════════════════════════════════════════════════════
     SAYFA KIRISI 2
═══════════════════════════════════════════════════════ -->
<div class="pb"></div>

<!-- ════════════════════════════════════════════════════
     TASARRUF FIRSATLARI
═══════════════════════════════════════════════════════ -->
<div class="section">
    <h2>💡 Tasarruf Fırsatları ve Öneriler</h2>

    <div class="sbox">
        <h3>Toplam Yıllık Tasarruf Potansiyeli</h3>
        <div class="sbox-grid">
            <div class="sbox-item">
                <div class="sv">{ann_fuel:,.0f}</div>
                <div class="sl">ton yakıt / yıl</div>
            </div>
            <div class="sbox-item">
                <div class="sv">${ann_cost:,.0f}</div>
                <div class="sl">maliyet / yıl</div>
                <div class="sl" style="font-size:10px;color:#95a5a6;">
                    {_unc.get('low_usd', 0):,.0f} – {_unc.get('high_usd', 0):,.0f}
                </div>
            </div>
            <div class="sbox-item">
                <div class="sv">{ann_co2:,.0f}</div>
                <div class="sl">ton CO₂ / yıl</div>
            </div>
        </div>
    </div>

    <h3 style="font-size:13px;margin:14px 0 8px 0;">
        Önerilen Aksiyonlar
    </h3>

    <div class="rec">
        <span class="pri pri-h">YÜKSEK</span>
        <strong>Cruise İrtifa Optimizasyonu</strong>
        <p>Operasyonel veri, ATC kısıtları nedeniyle uçuşların {dev_pct}%'inde
        optimum FL'den ortalama {avg_dev:,.0f} ft sapma yaşandığını
        göstermektedir. Dispatcher briefing süreçleri ve ATC
        koordinasyonunun güçlendirilmesi, SAR kaybını
        (%{sar_loss:.1f}) giderme potansiyeli taşımaktadır.</p>
    </div>

    <div class="rec">
        <span class="pri pri-h">YÜKSEK</span>
        <strong>En Verimsiz Rotaların Öncelikli İncelenmesi</strong>
        <p>En yüksek kg/Nm oranına sahip ilk 3 rota detaylı analiz
        kapsamına alınmalıdır. Rota planlaması, yakıt yükleme politikası
        ve ATC koordinasyonu gözden geçirilmelidir.</p>
    </div>

    <div class="rec">
        <span class="pri pri-m">ORTA</span>
        <strong>Step Climb Uygulama Disiplini</strong>
        <p>Mevcut operasyonda {step_n}/{n_flights} uçuşta step climb
        uygulandı. 1.000+ Nm rotalarında 200–300 Nm aralıklarla
        2.000 ft step climb %1–2 yakıt tasarrufu sağlar.
        ATC koordinasyonu gerektirir.</p>
    </div>

    <div class="rec">
        <span class="pri pri-m">ORTA</span>
        <strong>Yakıt Tutarlılığı İyileştirmesi</strong>
        <p>Aynı rotadaki uçuşlar arasında anlamlı yakıt farkları
        gözlemlendi. En verimli uçuşların prosedürleri analiz edilerek
        operasyon geneline yaygınlaştırılması önerilmektedir.</p>
    </div>

    <div class="rec">
        <span class="pri pri-l">DÜŞÜK</span>
        <strong>CORSIA 2027 Hazırlık</strong>
        <p>Zorunlu faz başlamadan MRV altyapısının kurulması önerilir.
        {SYSTEM_NAME} aylık raporlama ve emisyon izleme sistemi bu
        ihtiyacı karşılamak için tasarlanmıştır.</p>
    </div>
</div>

<!-- ════════════════════════════════════════════════════
     CORSIA
═══════════════════════════════════════════════════════ -->
<div class="section">
    <h2>🌍 CORSIA Emisyon Durumu</h2>

    <div class="corsia-disc">
        <strong>⚠ CORSIA Disclaimer</strong>
        <p>Bu bölüm resmi yükümlülük hesabı değildir. Demonstrative /
        illustrative değerlendirme amaçlıdır. Resmi CORSIA raporlaması
        için operatör block fuel kayıtları, onaylı baseline verisi ve
        ISO 14065 akredite üçüncü taraf doğrulama gerekir.</p>
    </div>

    <div class="corsia-warn">
        <strong>⚠ CORSIA Zorunlu Faz: 2027</strong>
        <p>Tüm uluslararası operasyonlar 2027'den itibaren emisyon
        offset yükümlülüğüne tabidir. Yakıt verimliliği iyileştirmeleri
        hem operasyonel maliyeti hem de offset maruziyetini azaltır.</p>
        <p style="margin-top:8px;">
            Illustrative offset exposure
            (2019 baseline, %5 büyüme varsayımı):
            <strong style="color:#c0392b;">
                ~${illustr_offset:,}
            </strong>
            ($30/ton CO₂)
        </p>
    </div>
</div>

<!-- ════════════════════════════════════════════════════
     SONRAKI ADIMLAR
═══════════════════════════════════════════════════════ -->
<div class="section">
    <h2>📌 Önerilen Sonraki Adımlar</h2>
    <table class="nst">
        <thead>
            <tr>
                <th style="width:36px;">#</th>
                <th>Aksiyon</th>
                <th style="width:90px;">Öncelik</th>
                <th style="width:80px;">Süre</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>1</td>
                <td>En verimsiz 3 rota için detaylı uçuş bazlı analiz</td>
                <td><span style="color:#c0392b;">●</span> Yüksek</td>
                <td>2 hafta</td>
            </tr>
            <tr style="background:#f9f9f9;">
                <td>2</td>
                <td>QAR/FDR veri entegrasyonu ile model kalibrasyonu</td>
                <td><span style="color:#c0392b;">●</span> Yüksek</td>
                <td>4 hafta</td>
            </tr>
            <tr>
                <td>3</td>
                <td>Pilot yakıt verimliliği eğitim programı tasarımı</td>
                <td><span style="color:#f39c12;">●</span> Orta</td>
                <td>6 hafta</td>
            </tr>
            <tr style="background:#f9f9f9;">
                <td>4</td>
                <td>Aylık sürekli monitoring sistemi kurulumu</td>
                <td><span style="color:#f39c12;">●</span> Orta</td>
                <td>4 hafta</td>
            </tr>
            <tr>
                <td>5</td>
                <td>CORSIA MRV altyapısı ve raporlama otomasyonu</td>
                <td><span style="color:#27ae60;">●</span> Düşük</td>
                <td>8 hafta</td>
            </tr>
        </tbody>
    </table>
</div>

<!-- ════════════════════════════════════════════════════
     FOOTER
═══════════════════════════════════════════════════════ -->
<div class="footer">
    <p>
        <strong>{SYSTEM_NAME}</strong> v{SYSTEM_VERSION}
        &nbsp;|&nbsp;
        Aviation Fuel Efficiency &amp; Emission Intelligence
    </p>
    <p>
        Bu rapor {SYSTEM_NAME} tarafından üretilmiştir.
        Veriler belirtilen döneme ve belirtilen kaynağa aittir.
        Model çıktıları fizik tabanlıdır; operatör QAR/FDR verisiyle
        kalibre edildiğinde doğruluk artar (garanti edilen bir yüzde
        verilmez).
    </p>
    <p>
        greenwingsanalytics@gmail.com
        &nbsp;|&nbsp;
        CORSIA-aligned Methodology
        &nbsp;|&nbsp;
        Ref: {report_id}
    </p>
    <p style="margin-top:4px;">
        © {datetime.now().year} {SYSTEM_NAME}.
        Bu rapor gizlidir.
    </p>
</div>

</div><!-- /page -->
</body>
</html>"""

        # ── Kaydet ───────────────────────────────────────
        html_path = os.path.join(
            self.output_dir, f"{output_filename}.html"
        )
        os.makedirs(
            os.path.dirname(os.path.abspath(html_path)),
            exist_ok=True,
        )
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)

        return {
            'html_path': os.path.abspath(html_path),
            'status'   : 'success',
            'report_id': report_id,
            'generated': generated,
        }

    def __repr__(self) -> str:
        return f"ReportGenerator(output_dir={self.output_dir})"


# ═══════════════════════════════════════════════════════════
# DOĞRULAMA
# ═══════════════════════════════════════════════════════════

def validate_report_generator() -> bool:
    import tempfile
    print("\n" + "=" * 60)
    print("  REPORT_GENERATOR.PY — DOĞRULAMA")
    print("=" * 60)

    errors = []
    tests  = 0

    def ok(n):
        nonlocal tests
        tests += 1
        print(f"  ✅ {n}")

    def fail(n, d):
        nonlocal tests
        tests += 1
        errors.append(f"{n}: {d}")
        print(f"  ❌ {n}: {d}")

    gen = ReportGenerator()
    tests += 1
    if isinstance(gen, ReportGenerator):
        ok("ReportGenerator oluşturuldu")
    else:
        fail("oluşturma", "başarısız")
        return False

    demo = {
        'report_metadata': {
            'total_flights_analyzed': 233,
            'valid_flights': 233,
        },
        'fleet_summary': {
            'total_fuel_kg'         : 1970900,
            'total_fuel_tonnes'     : 1971.0,
            'total_co2_tonnes'      : 6228.0,
            'avg_fuel_per_flight_kg': 8459,
            'avg_fuel_per_nm'       : 7.62,
            'fleet_efficiency_score': 95.9,
        },
        'benchmark': {
            'fleet_fuel_per_nm'        : 7.62,
            'industry_avg_fuel_per_nm' : 8.2,
            'industry_best_fuel_per_nm': 6.8,
            'rating'                   : 'GOOD — Sektör ortalamasının üzerinde',
            'gap_to_best_pct'          : 12.1,
            'based_on_n_flights'       : 233,
            'data_quality_warning'     : None,
        },
        'savings_potential': {
            'total_fuel_saving_kg'          : 39682,
            'total_cost_saving_usd'         : 51047,
            'total_co2_saving_kg'           : 125395,
            'annualized_cost_saving_usd'    : 381567,
            'annualized_fuel_saving_tonnes' : 448.9,
            'annualized_co2_saving_tonnes'  : 1418.5,
        },
        'route_analysis': {
            'rankings': [
                {
                    'route': 'LTAI→EDDF', 'flights': 30,
                    'avg_fuel_kg': 9510, 'fuel_per_nm': 7.66,
                    'fuel_consistency_std': 175,
                    'total_co2_kg': 901500,
                },
            ],
        },
        'altitude_performance': {
            'avg_deviation_from_optimum_ft': 700,
            'avg_sar_loss_pct'             : 1.85,
            'flights_with_step_climb'      : 146,
        },
        'data_quality': {
            'quality_grade'  : 'A',
            'total_flights'  : 233,
            'valid_flights'  : 233,
            'partial_flights': 0,
            'partial_pct'    : 0.0,
            'recommendations': ['Veri kalitesi yüksek.'],
        },
    }

    with tempfile.TemporaryDirectory() as tmp:
        gen.output_dir = tmp
        res = gen.generate_fleet_report(
            demo,
            "SunExpress Airlines",
            "Test Period",
            "test",
        )
        tests += 1
        if res['status'] == 'success' and os.path.exists(res['html_path']):
            size = os.path.getsize(res['html_path']) // 1024
            ok(f"Rapor üretildi ({size} KB)")
        else:
            fail("Rapor", "üretilemedi")

        with open(res['html_path'], encoding='utf-8') as f:
            c = f.read()

        checks = [
            ("SunExpress", "SunExpress"),
            ("Tasarruf kutusu", "Toplam Yıllık Tasarruf"),
            ("CORSIA disclaimer", "CORSIA Disclaimer"),
            ("Sonraki adımlar", "Önerilen Sonraki Adımlar"),
            ("ATC notu", "ATC kısıtı"),
            ("KPI Toplam Yakıt", "Toplam Yakıt"),
            ("KPI Toplam CO2", "Toplam CO₂"),
            ("KPI Verimlilik", "Verimlilik"),
            ("700 ft sapma", "700"),
        ]
        for name, kw in checks:
            tests += 1
            if kw in c:
                ok(name)
            else:
                fail(name, f"'{kw}' bulunamadı")

    print(f"\n  Toplam: {tests} | Başarılı: {tests-len(errors)} | Hata: {len(errors)}")
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        return False
    print("  ✅ TÜM TESTLER BAŞARILI\n")
    return True


if __name__ == "__main__":
    validate_report_generator()



# src/reporting/templates