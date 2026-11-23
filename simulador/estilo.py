"""Estilo visual de la aplicación: colores, CSS, encabezado, tarjetas y gráficas."""

import plotly.graph_objects as go
import plotly.io as pio

AZUL_OSCURO = "#0f2a44"
VERDE = "#1f9d74"
VALLE = "#5B8DB8"
PICO = "#E07B39"
COLORES_SEM = {"S1": "#2E86AB", "S2": "#E07B39", "S3": "#3BB273", "S4": "#C73E1D"}
SECUENCIA = [COLORES_SEM[s] for s in ("S1", "S2", "S3", "S4")] + ["#7c3aed", "#0891b2", "#ca8a04"]

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, .stDataFrame, button, input, select, textarea {
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif !important; }
.block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1500px; }
header[data-testid="stHeader"] { background: transparent; }

/* Encabezado */
.hero { background: linear-gradient(120deg, #0f2a44 0%, #16406a 55%, #1f6f8b 100%); color: #fff;
  border-radius: 18px; padding: 22px 28px; margin-bottom: 14px; position: relative; overflow: hidden;
  box-shadow: 0 10px 30px rgba(15,42,68,.18); }
.hero:after { content: ""; position: absolute; right: 26px; top: 6px; font-size: 92px; opacity: .14; }
.hero h1 { font-size: 1.85rem; font-weight: 800; margin: 0 0 2px 0; color: #fff; letter-spacing: -.02em; }
.hero p { margin: 0; opacity: .85; font-size: .95rem; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
.chip { background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.18); padding: 5px 11px;
  border-radius: 999px; font-size: .8rem; font-weight: 500; white-space: nowrap; }
.chip b { font-weight: 700; }

/* Tarjetas de indicadores */
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 6px 0 14px; }
.kpi { background: #fff; border: 1px solid #e6eaf0; border-radius: 14px; padding: 14px 16px;
  box-shadow: 0 1px 3px rgba(16,24,40,.06); position: relative; overflow: hidden; }
.kpi:before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 5px; background: var(--c, #1f6f8b); }
.kpi .et { color: #5b6474; font-size: .78rem; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
.kpi .va { font-size: 1.75rem; font-weight: 800; color: #0f2a44; line-height: 1.15; margin-top: 4px;
  font-variant-numeric: tabular-nums; }
.kpi .su { color: #6b7280; font-size: .8rem; margin-top: 2px; }

/* Títulos de sección */
.sec { display: flex; align-items: center; gap: 10px; margin: 22px 0 6px; }
.sec .barra { width: 5px; height: 26px; border-radius: 3px; background: #1f9d74; }
.sec .ic { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center;
  background: #e8f1fb; font-size: 18px; }
.sec h3 { margin: 0; font-size: 1.15rem; font-weight: 700; color: #0f2a44; }
.sec .de { color: #6b7280; font-size: .85rem; margin: 0 0 8px 44px; }

/* Aviso destacado */
.nota { background: #f3f8ff; border: 1px solid #d6e6fb; border-left: 5px solid #1f6f8b; border-radius: 10px;
  padding: 10px 14px; color: #1d3b5a; font-size: .92rem; margin: 6px 0 10px; }

/* Pestañas */
.stTabs [data-baseweb="tab-list"] { gap: 4px; background: #f1f4f8; padding: 5px; border-radius: 12px; }
.stTabs [data-baseweb="tab"] { height: 40px; padding: 0 14px; border-radius: 9px; font-weight: 600; color: #42526e; }
.stTabs [aria-selected="true"] { background: #fff !important; color: #0f2a44 !important;
  box-shadow: 0 1px 3px rgba(16,24,40,.12); }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none; }

/* Barra lateral */
section[data-testid="stSidebar"] { background: #0f2a44; }
section[data-testid="stSidebar"] * { color: #e7eef7; }
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] [data-baseweb="select"] * { color: #0f2a44 !important; }
section[data-testid="stSidebar"] .paso { display: flex; align-items: center; gap: 8px; margin: 14px 0 4px;
  font-weight: 700; font-size: .92rem; }
section[data-testid="stSidebar"] .paso span { background: #1f9d74; color: #fff; width: 22px; height: 22px;
  border-radius: 50%; display: grid; place-items: center; font-size: .78rem; }
section[data-testid="stSidebar"] .calc { background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.12);
  border-radius: 10px; padding: 8px 10px; font-size: .78rem; line-height: 1.45; }
section[data-testid="stSidebar"] button[data-testid^="stNumberInput"] { background: #e7eef7 !important; }
section[data-testid="stSidebar"] button[data-testid^="stNumberInput"] svg { fill: #0f2a44 !important; color: #0f2a44 !important; }
section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.15); }

/* Botones de descarga */
.stDownloadButton button { border-radius: 10px; font-weight: 700; height: 44px; }
div[data-testid="stDataFrame"] { border-radius: 10px; }
</style>
"""


def hero(titulo: str, subtitulo: str, chips: list[tuple[str, str]]) -> str:
    c = "".join(f'<span class="chip">{k} <b>{v}</b></span>' for k, v in chips)
    return f'<div class="hero"><h1>{titulo}</h1><p>{subtitulo}</p><div class="chips">{c}</div></div>'


def kpis(items: list[tuple[str, str, str, str]]) -> str:
    """items = [(etiqueta, valor, subtítulo, color)]"""
    tarjetas = "".join(f'<div class="kpi" style="--c:{col}"><div class="et">{et}</div><div class="va">{va}</div>'
                       f'<div class="su">{su}</div></div>' for et, va, su, col in items)
    return f'<div class="kpis">{tarjetas}</div>'


def seccion(icono: str, titulo: str, descripcion: str = "") -> str:
    d = f'<div class="de">{descripcion}</div>' if descripcion else ""
    ic = f'<div class="ic">{icono}</div>' if icono.strip() else '<div class="barra"></div>'
    return f'<div class="sec">{ic}<h3>{titulo}</h3></div>{d}'


def nota(texto: str) -> str:
    return f'<div class="nota">{texto}</div>'


def paso(n, texto: str) -> str:
    marca = f'<span>{n}</span>' if str(n).strip() else ""
    return f'<div class="paso">{marca}{texto}</div>'


def configurar_plotly():
    t = go.layout.Template(pio.templates["plotly_white"])
    t.layout.font = dict(family="Inter, system-ui, sans-serif", size=13, color="#1d2433")
    t.layout.colorway = SECUENCIA
    t.layout.title = dict(font=dict(size=15, color="#0f2a44"), x=0.01, xanchor="left")
    t.layout.margin = dict(l=50, r=20, t=50, b=40)
    t.layout.legend = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, title_text="")
    t.layout.hoverlabel = dict(font_family="Inter, sans-serif")
    t.layout.xaxis = dict(gridcolor="#eef1f5", linecolor="#d5dbe3")
    t.layout.yaxis = dict(gridcolor="#eef1f5", linecolor="#d5dbe3", zerolinecolor="#d5dbe3")
    pio.templates["cruce"] = t
    pio.templates.default = "cruce"
