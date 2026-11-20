# dashboard/app.py

"""
GreenWing Analytics — İnteraktif Dashboard
════════════════════════════════════════════

Bu dosya tüm analiz ve optimizasyon sonuçlarını
interaktif web uygulaması olarak görselleştirir.

MODÜLLER:
─────────
    1. KPI Kartları (6 adet)
       → Toplam yakıt, CO₂, verimlilik, tasarruf
    2. Aylık Yakıt + CO₂ Trend
       → Bar chart (yakıt) + line (CO₂)
    3. Uçak Tipi Dağılımı
       → Donut chart
    4. Rota Verimlilik Sıralaması
       → Horizontal bar + sektör ortalaması referans
    5. Rota Haritası
       → Dünya haritası üzerinde rotalar
    6. Tasarruf Fırsatları
       → Horizontal bar chart
    7. Tutarlılık Analizi
       → Box plot (aynı rotadaki yakıt farkları)
    8. CORSIA Raporu
       → Aylık CO₂ vs baseline + offset pie chart

FİLTRELER:
──────────
    • Tarih aralığı (DatePickerRange)
    • Uçak tipi (Dropdown)
    • Rota (Dropdown)
    Filtre değişince TÜM grafikler anında güncellenir.

ÇALIŞTIRMA:
───────────
    python dashboard/app.py
    → Tarayıcıda http://localhost:8050 aç

VERİ KAYNAĞI:
─────────────
    Şu an: generate_demo_data() ile simüle veri üretir.
    Müşteri gelince: Gerçek JSON/CSV ile değiştirilecek.

KULLANIM:
─────────
    # Terminal
    cd greenWing-analytics
    greenWing_env\\Scripts\\activate
    python dashboard/app.py

    # Tarayıcıda
    http://localhost:8050
"""

import sys
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Proje kök dizinini path'e ekle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import dash
from dash import dcc, html, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

from config.settings import (
    SYSTEM_NAME, SYSTEM_VERSION,
    DASHBOARD_HOST, DASHBOARD_PORT, DASHBOARD_DEBUG,
    REPORTS_OPTIMIZATIONS,
)


# ═══════════════════════════════════════════════════════════
# VERİ KAYNAĞI
# ═══════════════════════════════════════════════════════════

def load_data() -> pd.DataFrame:
    """
    Dashboard verisini yükle.

    Öncelik sırası:
        1. reports/optimizations/batch_results.json (gerçek veri)
        2. Demo veri (simüle)

    Returns:
        pd.DataFrame: Dashboard için hazır veri
    """
    json_path = os.path.join(REPORTS_OPTIMIZATIONS, "batch_results.json")

    if os.path.exists(json_path):
        try:
            with open(json_path, encoding='utf-8') as f:
                results = json.load(f)
            if results:
                df = pd.DataFrame(results)
                if 'timestamp' in df.columns:
                    df['date'] = pd.to_datetime(
                        df['timestamp'], errors='coerce'
                    ).dt.strftime('%Y-%m-%d')
                else:
                    df['date'] = datetime.now().strftime('%Y-%m-%d')

                if 'month' not in df.columns:
                    df['month'] = pd.to_datetime(
                        df['date'], errors='coerce'
                    ).dt.strftime('%Y-%m')

                if 'aircraft_type' not in df.columns:
                    df['aircraft_type'] = 'B738'

                # fuel_per_nm hesapla (yoksa)
                if 'fuel_per_nm' not in df.columns and 'estimated_fuel_kg' in df.columns:
                    df['fuel_per_nm'] = df['estimated_fuel_kg'] / df['distance_nm'].clip(lower=1)

                # co2_kg hesapla (yoksa)
                if 'co2_kg' not in df.columns and 'estimated_fuel_kg' in df.columns:
                    df['co2_kg'] = df['estimated_fuel_kg'] * 3.16

                # origin-destination rota
                if 'origin' not in df.columns:
                    df['origin'] = 'LTFM'
                if 'destination' not in df.columns:
                    df['destination'] = df.get('dest_airport', 'EGLL')

                # potential_saving_kg (yoksa)
                if 'potential_saving_kg' not in df.columns:
                    df['potential_saving_kg'] = df.get('fuel_optimization_kg', 0)

                return df
        except Exception as e:
            print(f"  ⚠ JSON yükleme hatası: {e}. Demo veri kullanılıyor.")

    return generate_demo_data()


def generate_demo_data() -> pd.DataFrame:
    """
    Demo amaçlı 6 aylık simüle havayolu verisi üret.

    12 farklı rota, 3 uçak tipi, mevsimsel etki dahil.
    Gerçek müşteri gelince bu fonksiyon devre dışı kalır.
    """
    np.random.seed(42)

    routes = [
        {'origin': 'LTFM', 'dest': 'EGLL', 'dist': 1560, 'ac': 'B738',
         'base_fuel': 12500, 'freq': 2},
        {'origin': 'EGLL', 'dest': 'LTFM', 'dist': 1560, 'ac': 'B738',
         'base_fuel': 11800, 'freq': 2},
        {'origin': 'LTFM', 'dest': 'EDDF', 'dist': 1000, 'ac': 'B738',
         'base_fuel': 8500, 'freq': 3},
        {'origin': 'EDDF', 'dest': 'LTFM', 'dist': 1000, 'ac': 'B738',
         'base_fuel': 8200, 'freq': 3},
        {'origin': 'LTFM', 'dest': 'LFPG', 'dist': 1220, 'ac': 'A320',
         'base_fuel': 10200, 'freq': 2},
        {'origin': 'LFPG', 'dest': 'LTFM', 'dist': 1220, 'ac': 'A320',
         'base_fuel': 9800, 'freq': 2},
        {'origin': 'LTFM', 'dest': 'OMDB', 'dist': 1550, 'ac': 'B77W',
         'base_fuel': 42000, 'freq': 1},
        {'origin': 'OMDB', 'dest': 'LTFM', 'dist': 1550, 'ac': 'B77W',
         'base_fuel': 41000, 'freq': 1},
        {'origin': 'LTFM', 'dest': 'LTAC', 'dist': 190, 'ac': 'B738',
         'base_fuel': 3200, 'freq': 6},
        {'origin': 'LTAC', 'dest': 'LTFM', 'dist': 190, 'ac': 'B738',
         'base_fuel': 3100, 'freq': 6},
        {'origin': 'LTFM', 'dest': 'LTAI', 'dist': 300, 'ac': 'A320',
         'base_fuel': 4200, 'freq': 4},
        {'origin': 'LTAI', 'dest': 'LTFM', 'dist': 300, 'ac': 'A320',
         'base_fuel': 4000, 'freq': 4},
    ]

    flights = []
    start_date = datetime(2025, 1, 1)

    for day in range(180):
        date = start_date + timedelta(days=day)

        for route in routes:
            for _ in range(route['freq']):
                # Yakıt varyasyonu
                fuel_var = np.random.normal(1.0, 0.04)
                fuel = route['base_fuel'] * fuel_var

                # Mevsimsel etki
                month = date.month
                if month in [12, 1, 2]:
                    fuel *= 1.03
                elif month in [6, 7, 8]:
                    fuel *= 0.98

                # Cruise irtifası
                base_alt = 35000 if route['ac'] != 'B77W' else 37000
                alt = base_alt + np.random.choice([-2000, 0, 2000, 4000])

                # Rota verimliliği
                route_eff = np.random.normal(95, 3)
                actual_dist = route['dist'] / (route_eff / 100)

                # Tasarruf potansiyeli
                saving = fuel * np.random.uniform(0.01, 0.04)

                flights.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'month': date.strftime('%Y-%m'),
                    'flight_number': f"GW{np.random.randint(100, 999)}",
                    'origin': route['origin'],
                    'destination': route['dest'],
                    'aircraft_type': route['ac'],
                    'distance_nm': route['dist'],
                    'actual_distance_nm': round(actual_dist, 1),
                    'estimated_fuel_kg': round(fuel),
                    'cruise_altitude_ft': alt,
                    'route_efficiency_pct': round(route_eff, 1),
                    'co2_kg': round(fuel * 3.16),
                    'fuel_per_nm': round(fuel / route['dist'], 2),
                    'potential_saving_kg': round(saving),
                })

    return pd.DataFrame(flights)


# ═══════════════════════════════════════════════════════════
# VERİ YÜKLEME
# ═══════════════════════════════════════════════════════════

demo_df = load_data()

# ─── Havalimanı koordinatları (harita için) ───────────────
try:
    from src.data_collection.airport_database import AirportDatabase
    airport_db = AirportDatabase()
except ImportError:
    airport_db = None


# ═══════════════════════════════════════════════════════════
# RENK PALETİ
# ═══════════════════════════════════════════════════════════

COLORS = {
    'background' : '#1a1a2e',
    'card'       : '#16213e',
    'accent'     : '#0f3460',
    'highlight'  : '#e94560',
    'text'       : '#ffffff',
    'text_sec'   : '#a0a0a0',
    'green'      : '#00b894',
    'yellow'     : '#fdcb6e',
    'red'        : '#d63031',
    'blue'       : '#0984e3',
}


# ═══════════════════════════════════════════════════════════
# KPI HESAPLAMALARI
# ═══════════════════════════════════════════════════════════

def calculate_kpis(df: pd.DataFrame) -> dict:
    """KPI değerlerini hesapla."""
    n = len(df)
    total_fuel = df['estimated_fuel_kg'].sum() / 1000 if 'estimated_fuel_kg' in df.columns else 0
    total_co2  = df['co2_kg'].sum() / 1000 if 'co2_kg' in df.columns else 0
    avg_fuel   = df['estimated_fuel_kg'].mean() if 'estimated_fuel_kg' in df.columns else 0
    avg_eff    = df['route_efficiency_pct'].mean() if 'route_efficiency_pct' in df.columns else 95

    saving_kg  = df['potential_saving_kg'].sum() if 'potential_saving_kg' in df.columns else 0
    saving_usd = saving_kg * 0.85
    saving_co2 = saving_kg * 3.16 / 1000

    return {
        'flights'    : n,
        'fuel_tonnes': total_fuel,
        'co2_tonnes' : total_co2,
        'avg_fuel'   : avg_fuel,
        'avg_eff'    : avg_eff,
        'saving_usd' : saving_usd,
        'saving_co2' : saving_co2,
    }


# ═══════════════════════════════════════════════════════════
# KPI KART BİLEŞENİ
# ═══════════════════════════════════════════════════════════

def kpi_card(title, value, subtitle="", icon="📊", color=COLORS['green']):
    """Tek KPI kartı oluştur."""
    return dbc.Card(
        dbc.CardBody([
            html.Div([
                html.Span(icon, style={'fontSize': '24px', 'marginRight': '8px'}),
                html.Span(title, style={
                    'color': COLORS['text_sec'],
                    'fontSize': '12px',
                    'fontWeight': '500',
                    'textTransform': 'uppercase',
                    'letterSpacing': '1px',
                }),
            ], style={'marginBottom': '6px'}),
            html.H2(value, style={
                'color': color,
                'fontWeight': '700',
                'fontSize': '28px',
                'margin': '0',
            }),
            html.P(subtitle, style={
                'color': COLORS['text_sec'],
                'fontSize': '11px',
                'margin': '4px 0 0 0',
            }) if subtitle else html.Div(),
        ]),
        style={
            'backgroundColor': COLORS['card'],
            'border': f"1px solid {COLORS['accent']}",
            'borderRadius': '12px',
            'padding': '3px',
        },
    )


# ═══════════════════════════════════════════════════════════
# DASH UYGULAMASI
# ═══════════════════════════════════════════════════════════

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title=SYSTEM_NAME,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
    ],
)

# Global KPI'lar (başlangıç)
kpis = calculate_kpis(demo_df)


# ═══════════════════════════════════════════════════════════
# LAYOUT
# ═══════════════════════════════════════════════════════════

app.layout = dbc.Container([

    # ─── HEADER ───────────────────────────────────────────
    dbc.Row([
        dbc.Col([
            html.H1(f"✈️ {SYSTEM_NAME}", style={
                'color': COLORS['green'],
                'fontWeight': '700',
                'marginBottom': '0',
                'fontSize': '26px',
            }),
            html.P("Aviation Fuel Efficiency & Emission Intelligence", style={
                'color': COLORS['text_sec'],
                'fontSize': '13px',
                'marginTop': '2px',
            }),
        ], width=7),
        dbc.Col([
            html.P(f"v{SYSTEM_VERSION} | {datetime.now().strftime('%B %Y')}", style={
                'color': COLORS['text_sec'],
                'textAlign': 'right',
                'fontSize': '12px',
                'marginTop': '15px',
            }),
            html.P(
                f"{'Gerçek Veri' if os.path.exists(os.path.join(REPORTS_OPTIMIZATIONS, 'batch_results.json')) else 'Demo Veri'}",
                style={
                    'color': COLORS['green'] if os.path.exists(os.path.join(REPORTS_OPTIMIZATIONS, 'batch_results.json')) else COLORS['yellow'],
                    'textAlign': 'right',
                    'fontSize': '11px',
                    'fontWeight': '600',
                },
            ),
        ], width=5),
    ], style={
        'padding': '15px 0 8px 0',
        'borderBottom': f"2px solid {COLORS['accent']}",
    }),

    # ─── FİLTRELER ────────────────────────────────────────
    dbc.Row([
        dbc.Col([
            html.Label("Tarih Aralığı", style={
                'color': COLORS['text_sec'], 'fontSize': '11px',
            }),
            dcc.DatePickerRange(
                id='date-range',
                start_date=demo_df['date'].min() if 'date' in demo_df.columns else '2025-01-01',
                end_date=demo_df['date'].max() if 'date' in demo_df.columns else '2025-06-30',
                display_format='DD/MM/YYYY',
                style={'fontSize': '11px'},
            ),
        ], width=4),
        dbc.Col([
            html.Label("Uçak Tipi", style={
                'color': COLORS['text_sec'], 'fontSize': '11px',
            }),
            dcc.Dropdown(
                id='aircraft-filter',
                options=[{'label': 'Tümü', 'value': 'ALL'}] + [
                    {'label': ac, 'value': ac}
                    for ac in sorted(demo_df['aircraft_type'].unique())
                ] if 'aircraft_type' in demo_df.columns else [],
                value='ALL',
                style={'backgroundColor': COLORS['card'], 'color': '#000'},
            ),
        ], width=3),
        dbc.Col([
            html.Label("Rota", style={
                'color': COLORS['text_sec'], 'fontSize': '11px',
            }),
            dcc.Dropdown(
                id='route-filter',
                options=[{'label': 'Tüm Rotalar', 'value': 'ALL'}] + [
                    {'label': f"{r[0]}→{r[1]}", 'value': f"{r[0]}-{r[1]}"}
                    for r in demo_df.groupby(['origin', 'destination']).size().reset_index().values
                ] if 'origin' in demo_df.columns else [],
                value='ALL',
                style={'backgroundColor': COLORS['card'], 'color': '#000'},
            ),
        ], width=5),
    ], style={'padding': '12px 0', 'marginBottom': '8px'}),

    # ─── KPI KARTLARI ─────────────────────────────────────
    html.Div(id='kpi-row'),

    # ─── SATIR 1: TREND + TİP DAĞILIMI ────────────────────
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("📈 Aylık Yakıt Tüketimi ve CO₂ Trendi", style={
                    'backgroundColor': COLORS['card'],
                    'color': COLORS['text'],
                    'borderBottom': f"1px solid {COLORS['accent']}",
                    'fontSize': '13px',
                }),
                dbc.CardBody([
                    dcc.Graph(id='fuel-trend', style={'height': '340px'}),
                ]),
            ], style={
                'backgroundColor': COLORS['card'],
                'border': f"1px solid {COLORS['accent']}",
                'borderRadius': '12px',
            }),
        ], width=8),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("🛩 Uçak Tipi Dağılımı", style={
                    'backgroundColor': COLORS['card'],
                    'color': COLORS['text'],
                    'borderBottom': f"1px solid {COLORS['accent']}",
                    'fontSize': '13px',
                }),
                dbc.CardBody([
                    dcc.Graph(id='aircraft-dist', style={'height': '340px'}),
                ]),
            ], style={
                'backgroundColor': COLORS['card'],
                'border': f"1px solid {COLORS['accent']}",
                'borderRadius': '12px',
            }),
        ], width=4),
    ], style={'marginBottom': '12px'}),

    # ─── SATIR 2: ROTA VERİMLİLİĞİ + HARİTA ─────────────
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("📊 Rota Yakıt Verimliliği (kg/Nm)", style={
                    'backgroundColor': COLORS['card'],
                    'color': COLORS['text'],
                    'borderBottom': f"1px solid {COLORS['accent']}",
                    'fontSize': '13px',
                }),
                dbc.CardBody([
                    dcc.Graph(id='route-eff', style={'height': '380px'}),
                ]),
            ], style={
                'backgroundColor': COLORS['card'],
                'border': f"1px solid {COLORS['accent']}",
                'borderRadius': '12px',
            }),
        ], width=6),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("🗺 Rota Ağı", style={
                    'backgroundColor': COLORS['card'],
                    'color': COLORS['text'],
                    'borderBottom': f"1px solid {COLORS['accent']}",
                    'fontSize': '13px',
                }),
                dbc.CardBody([
                    dcc.Graph(id='route-map', style={'height': '380px'}),
                ]),
            ], style={
                'backgroundColor': COLORS['card'],
                'border': f"1px solid {COLORS['accent']}",
                'borderRadius': '12px',
            }),
        ], width=6),
    ], style={'marginBottom': '12px'}),

    # ─── SATIR 3: TASARRUF + TUTARLILIK ───────────────────
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("💡 Tasarruf Potansiyeli", style={
                    'backgroundColor': COLORS['card'],
                    'color': COLORS['text'],
                    'borderBottom': f"1px solid {COLORS['accent']}",
                    'fontSize': '13px',
                }),
                dbc.CardBody([
                    dcc.Graph(id='savings', style={'height': '340px'}),
                ]),
            ], style={
                'backgroundColor': COLORS['card'],
                'border': f"1px solid {COLORS['accent']}",
                'borderRadius': '12px',
            }),
        ], width=6),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("📐 Yakıt Tutarlılık Analizi", style={
                    'backgroundColor': COLORS['card'],
                    'color': COLORS['text'],
                    'borderBottom': f"1px solid {COLORS['accent']}",
                    'fontSize': '13px',
                }),
                dbc.CardBody([
                    dcc.Graph(id='consistency', style={'height': '340px'}),
                ]),
            ], style={
                'backgroundColor': COLORS['card'],
                'border': f"1px solid {COLORS['accent']}",
                'borderRadius': '12px',
            }),
        ], width=6),
    ], style={'marginBottom': '12px'}),

    # ─── SATIR 4: CORSIA ──────────────────────────────────
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("📋 CORSIA Emisyon Durumu", style={
                    'backgroundColor': COLORS['card'],
                    'color': COLORS['text'],
                    'borderBottom': f"1px solid {COLORS['accent']}",
                    'fontSize': '13px',
                }),
                dbc.CardBody([
                    dcc.Graph(id='corsia', style={'height': '300px'}),
                ]),
            ], style={
                'backgroundColor': COLORS['card'],
                'border': f"1px solid {COLORS['accent']}",
                'borderRadius': '12px',
            }),
        ], width=12),
    ], style={'marginBottom': '12px'}),

    # ─── FOOTER ───────────────────────────────────────────
    dbc.Row([
        dbc.Col([
            html.Hr(style={'borderColor': COLORS['accent']}),
            html.P([
                f"{SYSTEM_NAME} v{SYSTEM_VERSION} © {datetime.now().year} | ",
                "CORSIA Compliant | Data-Driven Optimization | ",
                html.A("Contact", href="mailto:info@greenwinganalytics.com",
                       style={'color': COLORS['green']}),
            ], style={
                'color': COLORS['text_sec'],
                'fontSize': '10px',
                'textAlign': 'center',
            }),
        ]),
    ]),

], fluid=True, style={
    'backgroundColor': COLORS['background'],
    'minHeight': '100vh',
    'padding': '0 15px',
})


# ═══════════════════════════════════════════════════════════
# CALLBACKS
# ═══════════════════════════════════════════════════════════

@app.callback(
    [
        Output('kpi-row', 'children'),
        Output('fuel-trend', 'figure'),
        Output('aircraft-dist', 'figure'),
        Output('route-eff', 'figure'),
        Output('route-map', 'figure'),
        Output('savings', 'figure'),
        Output('consistency', 'figure'),
        Output('corsia', 'figure'),
    ],
    [
        Input('date-range', 'start_date'),
        Input('date-range', 'end_date'),
        Input('aircraft-filter', 'value'),
        Input('route-filter', 'value'),
    ],
)
def update_all(start_date, end_date, aircraft_type, route):
    """Tüm grafikleri filtrelere göre güncelle."""

    # ─── Veriyi filtrele ──────────────────────────────────
    df = demo_df.copy()

    if start_date and end_date and 'date' in df.columns:
        df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]

    if aircraft_type and aircraft_type != 'ALL' and 'aircraft_type' in df.columns:
        df = df[df['aircraft_type'] == aircraft_type]

    if route and route != 'ALL' and 'origin' in df.columns:
        origin, dest = route.split('-')
        df = df[(df['origin'] == origin) & (df['destination'] == dest)]

    if df.empty:
        df = demo_df.copy()

    # ─── KPI'lar ──────────────────────────────────────────
    k = calculate_kpis(df)

    kpi_row = dbc.Row([
        dbc.Col(kpi_card("Toplam Uçuş", f"{k['flights']:,}",
                         "Analiz edilen", "✈️", COLORS['blue']), width=2),
        dbc.Col(kpi_card("Toplam Yakıt", f"{k['fuel_tonnes']:,.0f} t",
                         f"Ort: {k['avg_fuel']:,.0f} kg/uçuş", "⛽", COLORS['yellow']), width=2),
        dbc.Col(kpi_card("CO₂ Emisyon", f"{k['co2_tonnes']:,.0f} t",
                         "CORSIA izleme", "🌍", COLORS['highlight']), width=2),
        dbc.Col(kpi_card("Rota Verimliliği", f"%{k['avg_eff']:.1f}",
                         "Filo ortalaması", "📐", COLORS['green']), width=2),
        dbc.Col(kpi_card("Tasarruf", f"${k['saving_usd']:,.0f}",
                         f"{k['saving_co2']:,.0f} t CO₂", "💰", COLORS['green']), width=2),
        dbc.Col(kpi_card("CO₂ Azaltma", f"{k['saving_co2']:,.0f} t",
                         "Potansiyel", "🌱", COLORS['green']), width=2),
    ], style={'marginBottom': '15px'})

    # ─── Ortak stil ───────────────────────────────────────
    layout_common = dict(
        plot_bgcolor=COLORS['card'],
        paper_bgcolor=COLORS['card'],
        font_color=COLORS['text'],
        margin=dict(l=50, r=40, t=30, b=40),
    )

    # ─── 1. YAKIT TREND ───────────────────────────────────
    if 'month' in df.columns:
        monthly = df.groupby('month').agg({
            'estimated_fuel_kg': 'sum',
            'co2_kg': 'sum',
        }).reset_index()
        monthly['fuel_t'] = monthly['estimated_fuel_kg'] / 1000
        monthly['co2_t']  = monthly['co2_kg'] / 1000
    else:
        monthly = pd.DataFrame({'month': ['N/A'], 'fuel_t': [0], 'co2_t': [0]})

    fig_trend = make_subplots(specs=[[{"secondary_y": True}]])
    fig_trend.add_trace(
        go.Bar(x=monthly['month'], y=monthly['fuel_t'],
               name='Yakıt (ton)', marker_color=COLORS['blue'], opacity=0.7),
        secondary_y=False,
    )
    fig_trend.add_trace(
        go.Scatter(x=monthly['month'], y=monthly['co2_t'],
                   name='CO₂ (ton)', line=dict(color=COLORS['highlight'], width=3),
                   mode='lines+markers'),
        secondary_y=True,
    )
    fig_trend.update_layout(**layout_common, legend=dict(orientation='h', y=1.12))
    fig_trend.update_yaxes(title_text="Yakıt (ton)", secondary_y=False, gridcolor=COLORS['accent'])
    fig_trend.update_yaxes(title_text="CO₂ (ton)", secondary_y=True, gridcolor=COLORS['accent'])

    # ─── 2. UÇAK TİPİ DAĞILIMI ───────────────────────────
    if 'aircraft_type' in df.columns:
        ac_dist = df.groupby('aircraft_type')['estimated_fuel_kg'].sum().reset_index()
    else:
        ac_dist = pd.DataFrame({'aircraft_type': ['B738'], 'estimated_fuel_kg': [1]})

    fig_ac = go.Figure(data=[go.Pie(
        labels=ac_dist['aircraft_type'],
        values=ac_dist['estimated_fuel_kg'],
        hole=0.5,
        marker_colors=[COLORS['blue'], COLORS['green'], COLORS['highlight'], COLORS['yellow']],
        textinfo='label+percent',
        textfont_size=11,
    )])
    fig_ac.update_layout(**layout_common, showlegend=False)

    # ─── 3. ROTA VERİMLİLİĞİ ─────────────────────────────
    if 'origin' in df.columns and 'fuel_per_nm' in df.columns:
        route_stats = df.groupby(['origin', 'destination']).agg({
            'fuel_per_nm': 'mean',
            'date': 'count',
        }).reset_index()
        route_stats.columns = ['origin', 'dest', 'avg_fuel_nm', 'flights']
        route_stats['route'] = route_stats['origin'] + '→' + route_stats['dest']
        route_stats = route_stats.sort_values('avg_fuel_nm', ascending=True)
    else:
        route_stats = pd.DataFrame({'route': ['N/A'], 'avg_fuel_nm': [0], 'flights': [0]})

    industry_avg = 8.5

    colors_bar = [
        COLORS['green'] if x < industry_avg else
        COLORS['yellow'] if x < industry_avg * 1.1 else
        COLORS['red']
        for x in route_stats['avg_fuel_nm']
    ]

    fig_route = go.Figure()
    fig_route.add_trace(go.Bar(
        y=route_stats['route'],
        x=route_stats['avg_fuel_nm'],
        orientation='h',
        marker_color=colors_bar,
        text=route_stats['avg_fuel_nm'].round(1),
        textposition='outside',
        textfont_color=COLORS['text'],
    ))
    fig_route.add_vline(x=industry_avg, line_dash="dash", line_color=COLORS['highlight'],
                        annotation_text=f"Sektör: {industry_avg}",
                        annotation_font_color=COLORS['highlight'])
    fig_route.update_layout(
        **layout_common,
        xaxis_title="kg/Nm",
        xaxis=dict(gridcolor=COLORS['accent']),
        yaxis=dict(gridcolor=COLORS['accent']),
        margin=dict(l=110, r=60, t=20, b=40),
    )

    # ─── 4. ROTA HARİTASI ────────────────────────────────
    fig_map = go.Figure()

    if 'origin' in df.columns and airport_db:
        route_agg = df.groupby(['origin', 'destination']).agg({
            'co2_kg': 'sum', 'date': 'count',
        }).reset_index()
        route_agg.columns = ['origin', 'dest', 'co2', 'flights']

        for _, row in route_agg.iterrows():
            o_info = airport_db.get(row['origin'])
            d_info = airport_db.get(row['dest'])

            if o_info and d_info:
                width = max(1, min(5, row['flights'] / 50))
                co2_avg = row['co2'] / max(row['flights'], 1)

                if co2_avg < 15000:
                    color = COLORS['green']
                elif co2_avg < 40000:
                    color = COLORS['yellow']
                else:
                    color = COLORS['highlight']

                fig_map.add_trace(go.Scattergeo(
                    lon=[o_info['lon'], d_info['lon']],
                    lat=[o_info['lat'], d_info['lat']],
                    mode='lines',
                    line=dict(width=width, color=color),
                    opacity=0.7,
                    showlegend=False,
                    hovertemplate=(
                        f"{row['origin']}→{row['dest']}<br>"
                        f"Uçuş: {row['flights']}<br>"
                        f"CO₂: {row['co2']/1000:.0f} ton<extra></extra>"
                    ),
                ))

        # Havalimanı noktaları
        all_apts = set(route_agg['origin'].tolist() + route_agg['dest'].tolist())
        for apt_code in all_apts:
            apt = airport_db.get(apt_code)
            if apt:
                fig_map.add_trace(go.Scattergeo(
                    lon=[apt['lon']], lat=[apt['lat']],
                    mode='markers+text',
                    marker=dict(size=7, color=COLORS['blue']),
                    text=[apt_code],
                    textposition='top center',
                    textfont=dict(size=8, color=COLORS['text']),
                    showlegend=False,
                ))

    fig_map.update_geos(
        projection_type="natural earth",
        showland=True, landcolor='rgb(30,30,60)',
        showocean=True, oceancolor='rgb(20,20,50)',
        showlakes=False,
        showcountries=True, countrycolor='rgb(60,60,90)',
        center=dict(lat=38, lon=35),
        lonaxis_range=[-10, 70],
        lataxis_range=[15, 60],
    )
    fig_map.update_layout(**layout_common, height=380, margin=dict(l=0, r=0, t=10, b=0))

    # ─── 5. TASARRUF FIRSATLARI ───────────────────────────
    if 'origin' in df.columns and 'potential_saving_kg' in df.columns:
        sav_by_route = df.groupby(['origin', 'destination']).agg({
            'potential_saving_kg': 'sum',
        }).reset_index()
        sav_by_route['route'] = sav_by_route['origin'] + '→' + sav_by_route['destination']
        sav_by_route['usd'] = sav_by_route['potential_saving_kg'] * 0.85
        sav_by_route = sav_by_route.sort_values('usd', ascending=True)
    else:
        sav_by_route = pd.DataFrame({'route': ['N/A'], 'usd': [0]})

    fig_sav = go.Figure()
    fig_sav.add_trace(go.Bar(
        y=sav_by_route['route'],
        x=sav_by_route['usd'],
        orientation='h',
        marker_color=COLORS['green'],
        text=sav_by_route['usd'].apply(lambda x: f"${x:,.0f}"),
        textposition='outside',
        textfont_color=COLORS['text'],
    ))
    fig_sav.update_layout(
        **layout_common,
        xaxis_title="Potansiyel Tasarruf (USD)",
        xaxis=dict(gridcolor=COLORS['accent']),
        margin=dict(l=110, r=70, t=20, b=40),
    )

    # ─── 6. TUTARLILIK (BOX PLOT) ─────────────────────────
    if 'origin' in df.columns and 'fuel_per_nm' in df.columns:
        top_routes_idx = df.groupby(['origin', 'destination'])['estimated_fuel_kg'].count().nlargest(8).index
        top_list = [f"{o}→{d}" for o, d in top_routes_idx]

        df_cons = df.copy()
        df_cons['route'] = df_cons['origin'] + '→' + df_cons['destination']
        df_cons = df_cons[df_cons['route'].isin(top_list)]
    else:
        df_cons = pd.DataFrame({'route': ['N/A'], 'fuel_per_nm': [0]})

    fig_con = go.Figure()
    if not df_cons.empty:
        for route_name in df_cons['route'].unique():
            rd = df_cons[df_cons['route'] == route_name]
            fig_con.add_trace(go.Box(
                y=rd['fuel_per_nm'],
                name=route_name,
                boxmean='sd',
                marker_color=COLORS['blue'],
            ))

    fig_con.update_layout(
        **layout_common,
        yaxis_title="kg/Nm",
        yaxis=dict(gridcolor=COLORS['accent']),
        xaxis=dict(tickangle=45),
        showlegend=False,
        margin=dict(l=50, r=20, t=20, b=80),
    )

    # ─── 7. CORSIA ────────────────────────────────────────
    if 'month' in df.columns and 'co2_kg' in df.columns:
        monthly_co2 = df.groupby('month')['co2_kg'].sum().reset_index()
        monthly_co2['co2_t'] = monthly_co2['co2_kg'] / 1000
        baseline_monthly = monthly_co2['co2_t'].mean() * 0.92
        monthly_co2['baseline'] = baseline_monthly
        monthly_co2['excess'] = (monthly_co2['co2_t'] - baseline_monthly).clip(lower=0)
    else:
        monthly_co2 = pd.DataFrame({
            'month': ['N/A'], 'co2_t': [0], 'baseline': [0], 'excess': [0],
        })

    fig_corsia = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Aylık CO₂ vs Baseline", "CORSIA Offset"),
        column_widths=[0.6, 0.4],
    )

    fig_corsia.add_trace(
        go.Bar(x=monthly_co2['month'], y=monthly_co2['co2_t'],
               name='Gerçek CO₂', marker_color=COLORS['blue']),
        row=1, col=1,
    )
    fig_corsia.add_trace(
        go.Scatter(x=monthly_co2['month'], y=monthly_co2['baseline'],
                   name='Baseline', line=dict(color=COLORS['highlight'], dash='dash', width=2),
                   mode='lines'),
        row=1, col=1,
    )

    total_excess = monthly_co2['excess'].sum()
    total_compliant = monthly_co2['co2_t'].sum() - total_excess

    fig_corsia.add_trace(
        go.Pie(labels=['Baseline', 'Offset Gerekli'],
               values=[max(0, total_compliant), max(0, total_excess)],
               marker_colors=[COLORS['green'], COLORS['highlight']],
               hole=0.5, textinfo='label+percent', textfont_size=10),
        row=1, col=2,
    )

    fig_corsia.update_layout(
        **layout_common,
        legend=dict(orientation='h', y=-0.1),
    )
    fig_corsia.update_yaxes(title_text="CO₂ (ton)", row=1, col=1, gridcolor=COLORS['accent'])

    return (
        kpi_row,
        fig_trend, fig_ac, fig_route, fig_map,
        fig_sav, fig_con, fig_corsia,
    )


# ═══════════════════════════════════════════════════════════
# ÇALIŞTIRMA
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print(f"  🚀 {SYSTEM_NAME} Dashboard")
    print(f"  📡 http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    print(f"  📊 {'Gerçek veri yüklendi' if os.path.exists(os.path.join(REPORTS_OPTIMIZATIONS, 'batch_results.json')) else 'Demo veri kullanılıyor'}")
    print("=" * 60 + "\n")

    app.run(
        debug=DASHBOARD_DEBUG,
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
    )                