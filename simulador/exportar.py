"""Exportación de la simulación completa a Excel y PDF.

Ambos archivos se arman con el mismo Paquete de reportes que muestra la app,
así que tienen exactamente la misma información (hora valle y hora pico).
"""

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from .datos import SEMAFOROS
from .paquete import Paquete
from .prediccion import franjas_pico

AZUL = "1F4E78"
AZUL_CLARO = "DDEBF7"
GRIS = "F2F2F2"
COLOR_VALLE = "#5B8DB8"
COLOR_PICO = "#E07B39"
COLORES_SEM = {"S1": "#2E86AB", "S2": "#E07B39", "S3": "#3BB273", "S4": "#C73E1D"}
MAX_FILAS_EXCEL = 1_000_000


# ---------------------------------------------------------------------------
# Formatos numéricos según el nombre de la columna
# ---------------------------------------------------------------------------
def _decimales(col: str) -> int:
    c = col.lower()
    if c in ("u1", "u2") or c.startswith("u ="):
        return 5
    if "veh/h" in c:
        return 0
    if any(k in c for k in ("%", "ic 99", "prom", "cola", "error", "×", "observad", "simulad", "llegadas (")):
        return 1
    return 0


def _formato_excel(col: str, serie: pd.Series) -> str | None:
    if pd.api.types.is_datetime64_any_dtype(serie):
        return "dd/mm/yyyy hh:mm"
    if not pd.api.types.is_numeric_dtype(serie):
        return None
    d = _decimales(col)
    return "#,##0" if d == 0 else "#,##0." + "0" * d


def _mil(v, d=0):
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _texto(v, col: str) -> str:
    if isinstance(v, pd.Timestamp):
        return v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if pd.isna(v):
            return ""
        return _mil(v, _decimales(col))
    return str(v)


# ---------------------------------------------------------------------------
# EXCEL
# ---------------------------------------------------------------------------
_borde = Border(*(Side(style="thin", color="BFBFBF"),) * 4)


def _titulo(ws, texto, fila, sub=None):
    ws.cell(fila, 1, texto).font = Font(bold=True, size=14, color=AZUL)
    if sub:
        ws.cell(fila + 1, 1, sub).font = Font(italic=True, size=9, color="595959")
        return fila + 3
    return fila + 2


def _tabla_excel(ws, df: pd.DataFrame, fila: int, col: int = 1, titulo: str | None = None,
                 filtro: bool = False) -> tuple[int, int]:
    """Escribe df con encabezado azul, filas cebra y formatos. Devuelve (fila encabezado, última fila)."""
    if titulo:
        ws.cell(fila, col, titulo).font = Font(bold=True, size=11, color=AZUL)
        fila += 1
    for j, nombre in enumerate(df.columns):
        c = ws.cell(fila, col + j, nombre)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = _borde
    ws.row_dimensions[fila].height = 32
    formatos = [_formato_excel(n, df[n]) for n in df.columns]
    cebra = PatternFill("solid", fgColor=GRIS)
    for i, fila_datos in enumerate(df.itertuples(index=False), start=1):
        for j, v in enumerate(fila_datos):
            if isinstance(v, pd.Timestamp):
                v = v.to_pydatetime()
            elif hasattr(v, "item"):
                v = v.item()
            c = ws.cell(fila + i, col + j, v)
            c.border = _borde
            if formatos[j]:
                c.number_format = formatos[j]
            if i % 2 == 0:
                c.fill = cebra
    ultima = fila + len(df)
    if filtro and len(df):
        ws.auto_filter.ref = f"{get_column_letter(col)}{fila}:{get_column_letter(col + len(df.columns) - 1)}{ultima}"
    return fila, ultima


def _anchos(ws, minimo=10, maximo=34):
    anchos = {}
    for fila in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 300)):
        for c in fila:
            if c.value is None or (c.font and c.font.size and c.font.size >= 11 and c.font.color
                                    and c.font.color.rgb and str(c.font.color.rgb).endswith(AZUL)
                                    and c.fill.fgColor.rgb in (None, "00000000")):
                continue
            largo = len(c.value) if isinstance(c.value, str) else len(_texto(c.value, ""))
            if c.alignment and c.alignment.wrap_text:
                largo = min(largo, 14)
            anchos[c.column_letter] = max(anchos.get(c.column_letter, 0), largo)
    for letra, largo in anchos.items():
        ws.column_dimensions[letra].width = max(minimo, min(maximo, largo + 3))
    # impresión: horizontal y ajustada al ancho de la hoja
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def _grafico_barras(ws, titulo, cats, datos, ancla, apilado=False, eje_y="Vehículos", alto=8, ancho=18):
    g = BarChart()
    g.type = "col"
    g.title = titulo
    g.y_axis.title = eje_y
    g.height, g.width = alto, ancho
    if apilado:
        g.grouping = "stacked"
        g.overlap = 100
    for ref in datos:
        g.add_data(ref, titles_from_data=True)
    g.set_categories(cats)
    ws.add_chart(g, ancla)


def _hoja_tramo(wb, tramo: dict):
    """Hoja con el tramo elegido en el explorador (de hora a hora o de ciclo a ciclo)."""
    ws = wb.create_sheet("Tramo elegido", 1)
    ws.sheet_view.showGridLines = False
    ind = tramo["ind"]
    f = _titulo(ws, "Tramo elegido en el explorador", 1, tramo["descripcion"])
    filas = [("Vehículos que pasan", ind["pasan"]), ("Pasan en hora valle", ind["valle"]),
             ("Pasan en hora pico", ind["pico"]), ("Vehículos que llegan", ind["llegan"]),
             ("Ciclos en el tramo", ind["ciclos"]), ("Quedan en cola (prom. por ciclo)", ind["cola_prom"]),
             ("Cola máxima (veh)", ind["cola_max"])]
    if "veh_h" in ind:
        filas[3:3] = [("Promedio por hora", ind["veh_h"]), ("Intervalo con más vehículos", ind["intervalo_max"]),
                      ("Intervalo con menos vehículos", ind["intervalo_min"])]
    for k, v in filas:
        a = ws.cell(f, 1, k)
        a.fill = PatternFill("solid", fgColor=AZUL_CLARO)
        a.font = Font(bold=True)
        a.border = _borde
        b = ws.cell(f, 2, v.item() if hasattr(v, "item") else v)
        b.border = _borde
        if isinstance(b.value, float):
            b.number_format = "#,##0.0" if abs(b.value) < 100 else "#,##0"
        f += 1
    tab = tramo["tabla"].drop(columns=[c for c in ("Desde",) if c in tramo["tabla"].columns])
    ini, fin = _tabla_excel(ws, tab, f + 2, titulo="Datos por intervalo", filtro=True)
    if not tramo["por_semaforo"] and len(tab) <= 400:
        cats = Reference(ws, min_col=1, min_row=ini + 1, max_row=fin)
        cols = list(tab.columns)
        datos = [Reference(ws, min_col=cols.index(c) + 1, min_row=ini, max_row=fin)
                 for c in ("Pasan en valle", "Pasan en pico")]
        _grafico_barras(ws, "Vehículos que pasan por intervalo", cats, datos,
                        f"{get_column_letter(len(cols) + 2)}{ini}", apilado=True)
    _anchos(ws, maximo=36)
    ws.column_dimensions["A"].width = 32


def excel_paquete(p: Paquete, tramo: dict | None = None) -> bytes:
    wb = Workbook()
    t = p.tablas

    # --- Resumen -----------------------------------------------------------
    ws = wb.active
    ws.title = "Resumen"
    ws.sheet_view.showGridLines = False
    f = _titulo(ws, "Simulador del cruce vial · vía Mesa–Girardot", 1, p.titulo)
    ws.cell(f, 1, "Indicadores principales").font = Font(bold=True, size=11, color=AZUL)
    f += 1
    for k, v in p.kpis.items():
        a = ws.cell(f, 1, k)
        a.fill = PatternFill("solid", fgColor=AZUL_CLARO)
        a.font = Font(bold=True)
        a.border = _borde
        b = ws.cell(f, 2, v)
        b.number_format = "#,##0.0" if isinstance(v, float) and abs(v) < 1000 else "#,##0"
        b.border = _borde
        f += 1
    f += 1
    _, f = _tabla_excel(ws, t["Conclusiones"], f, titulo="Conclusiones de la simulación")
    ws.cell(f + 1, 1, p.notas["Conclusiones"]).font = Font(italic=True, size=10, color="1d3b5a")
    f += 3
    _, f = _tabla_excel(ws, t["Parámetros"], f, titulo="Parámetros de la simulación")
    f += 2
    _, f = _tabla_excel(ws, t["Semáforos"], f, titulo="Resultados por semáforo")
    f += 2
    _, f = _tabla_excel(ws, t["Valle vs pico"], f, titulo="Hora valle frente a hora pico")
    f += 2
    _, f = _tabla_excel(ws, t["Precisión"], f, titulo="Precisión (confianza 99 %, error objetivo ≤ 1 %)")
    ws.cell(f + 1, 1, p.notas["Precisión"]).font = Font(italic=True, size=9, color="595959")
    _anchos(ws, maximo=40)
    ws.column_dimensions["A"].width = 30

    # --- Semáforo y periodo (con gráfico) -----------------------------------
    ws = wb.create_sheet("Semáforo y periodo")
    ws.sheet_view.showGridLines = False
    f = _titulo(ws, "Vehículos que pasan por semáforo en hora valle y en hora pico", 1, p.notas["Semáforo y periodo"])
    sp = t["Semáforo y periodo"]
    ini, fin = _tabla_excel(ws, sp, f, filtro=True)
    piv = sp.pivot(index="Semáforo", columns="Periodo", values="Prom. por hora").reindex(SEMAFOROS)
    piv = piv[[c for c in ("Valle", "Pico") if c in piv.columns]].reset_index()
    piv.columns = ["Semáforo"] + [f"Prom. por hora {c.lower()}" for c in piv.columns[1:]]
    pi, pf = _tabla_excel(ws, piv, fin + 3, titulo="Promedio de vehículos por hora")
    _grafico_barras(ws, "Vehículos por hora: valle vs pico",
                    Reference(ws, min_col=1, min_row=pi + 1, max_row=pf),
                    [Reference(ws, min_col=c, min_row=pi, max_row=pf) for c in range(2, len(piv.columns) + 1)],
                    f"E{fin + 3}", eje_y="Vehículos por hora")
    _anchos(ws)

    # --- Bloques de horas -----------------------------------------------------
    nombre_b = next(k for k in t if k.startswith("Bloques de") and k.endswith(" h"))
    ws = wb.create_sheet(nombre_b)
    ws.sheet_view.showGridLines = False
    f = _titulo(ws, f"Vehículos que pasan por {nombre_b.lower()}", 1, p.notas[nombre_b])
    bdf = t[nombre_b]
    ini, fin = _tabla_excel(ws, bdf, f, filtro=True)
    cols = list(bdf.columns)
    _grafico_barras(ws, "Vehículos por bloque (valle + pico)",
                    Reference(ws, min_col=1, min_row=ini + 1, max_row=fin),
                    [Reference(ws, min_col=cols.index("En hora valle") + 1, min_row=ini, max_row=fin),
                     Reference(ws, min_col=cols.index("En hora pico") + 1, min_row=ini, max_row=fin)],
                    f"A{fin + 3}", apilado=True, ancho=28, alto=10)
    _anchos(ws)
    ws.column_dimensions["A"].width = 26

    # --- Por hora -------------------------------------------------------------
    ws = wb.create_sheet("Por hora")
    ws.sheet_view.showGridLines = False
    f = _titulo(ws, "Vehículos que pasan por hora", 1, p.notas["Por hora"])
    hdf = t["Por hora"]
    ini, fin = _tabla_excel(ws, hdf, f, filtro=True)
    if len(hdf) <= 2000:
        g = LineChart()
        g.title, g.height, g.width = "Vehículos por hora y semáforo", 10, 28
        g.y_axis.title = "Vehículos"
        cols = list(hdf.columns)
        for s in SEMAFOROS:
            g.add_data(Reference(ws, min_col=cols.index(s) + 1, min_row=ini, max_row=fin), titles_from_data=True)
        g.set_categories(Reference(ws, min_col=1, min_row=ini + 1, max_row=fin))
        ws.add_chart(g, f"A{fin + 3}")
    _anchos(ws)
    ws.column_dimensions["A"].width = 18

    # --- Bloques de ciclos ----------------------------------------------------
    nombre_c = next(k for k in t if k.endswith(" ciclos"))
    ws = wb.create_sheet(nombre_c)
    ws.sheet_view.showGridLines = False
    f = _titulo(ws, f"Vehículos que pasan por {nombre_c.lower()}", 1, p.notas[nombre_c])
    _tabla_excel(ws, t[nombre_c], f, filtro=True)
    _anchos(ws)

    # --- Mapa de calor, colas y prueba de ajuste --------------------------------
    ws = wb.create_sheet("Mapa de calor y colas")
    ws.sheet_view.showGridLines = False
    f = _titulo(ws, "Mapa de calor: vehículos por día y hora", 1, p.notas["Mapa de calor"])
    mc = t["Mapa de calor (día × hora)"].reset_index().rename(columns={"index": "Día"})
    ini, fin = _tabla_excel(ws, mc, f)
    if len(mc):
        rango = f"B{ini + 1}:{get_column_letter(len(mc.columns))}{fin}"
        ws.conditional_formatting.add(rango, ColorScaleRule(start_type="min", start_color="FFFFE0",
                                                            mid_type="percentile", mid_value=50, mid_color="FDAE61",
                                                            end_type="max", end_color="D7191C"))
    _, fin = _tabla_excel(ws, t["Colas"], fin + 3, titulo="Colas al final de cada verde (repetición 1)")
    ws.cell(fin + 1, 1, p.notas["Colas"]).font = Font(italic=True, size=9, color="595959")
    _, fin = _tabla_excel(ws, t["Prueba de ajuste de llegadas"], fin + 3,
                          titulo="Prueba de ajuste de las llegadas (chi-cuadrado, α = 0,01)")
    ws.cell(fin + 1, 1, p.notas["Prueba de ajuste de llegadas"]).font = Font(italic=True, size=9, color="595959")
    _anchos(ws)
    ws.column_dimensions["A"].width = 18

    # --- Capacidad ------------------------------------------------------------
    ws = wb.create_sheet("Capacidad")
    ws.sheet_view.showGridLines = False
    f = _titulo(ws, "¿Cuánto aguanta el cruce? (hora valle y hora pico)", 1, p.notas["Capacidad"])
    ini, fin = _tabla_excel(ws, t["Capacidad"], f, filtro=True)
    bar = p.graficos["barrido"].pivot_table(index="factor", columns=["periodo", "semaforo"], values="cola_prom")
    bar.columns = [f"{s} {per.lower()}" for per, s in bar.columns]
    bar = bar.reset_index().rename(columns={"factor": "Demanda (× observada)"})
    bi, bf = _tabla_excel(ws, bar, fin + 3, titulo="Cola promedio (veh) al aumentar la demanda")
    g = LineChart()
    g.title, g.height, g.width = "Cola promedio al aumentar la demanda", 10, 24
    g.y_axis.title, g.x_axis.title = "Cola promedio (veh)", "Demanda (× la observada)"
    for c in range(2, len(bar.columns) + 1):
        g.add_data(Reference(ws, min_col=c, min_row=bi, max_row=bf), titles_from_data=True)
    g.set_categories(Reference(ws, min_col=1, min_row=bi + 1, max_row=bf))
    ws.add_chart(g, f"K{fin + 3}")
    _anchos(ws)

    # --- Validación -----------------------------------------------------------
    ws = wb.create_sheet("Validación")
    ws.sheet_view.showGridLines = False
    f = _titulo(ws, "Validación: simulado frente a observado", 1, p.notas["Validación"])
    _tabla_excel(ws, t["Validación"], f)
    _anchos(ws)

    # --- Números pseudoaleatorios ------------------------------------------------
    ws = wb.create_sheet("Números pseudoaleatorios")
    f = _titulo(ws, "Números pseudoaleatorios generados y qué significa cada uno", 1)
    ws.cell(f - 1, 1, p.notas["Números pseudoaleatorios"]).alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=f - 1, start_column=1, end_row=f - 1, end_column=13)
    ws.row_dimensions[f - 1].height = 75
    nums = t["Números pseudoaleatorios"]
    _tabla_excel(ws, nums, f + 1, filtro=True)
    _anchos(ws, maximo=60)
    ws.column_dimensions["D"].width = 18
    ws.freeze_panes = f"A{f + 2}"

    # --- Por ciclo --------------------------------------------------------------
    ws = wb.create_sheet("Por ciclo")
    f = _titulo(ws, "Detalle por ciclo", 1, "Repetición 1 (U1, U2, llegadas, cola) y promedio de cada ciclo "
                                         "entre todas las repeticiones.")
    _tabla_excel(ws, t["Por ciclo"].head(MAX_FILAS_EXCEL), f, filtro=True)
    _anchos(ws)
    ws.column_dimensions["C"].width = 18
    ws.freeze_panes = f"A{f + 1}"

    # --- Datos de campo ---------------------------------------------------------
    ws = wb.create_sheet("Datos de campo")
    ws.sheet_view.showGridLines = False
    f = _titulo(ws, "Datos de campo (toma manual por ciclo)", 1, f"{len(t['Datos de campo'])} ciclos observados")
    _, fin = _tabla_excel(ws, t["Datos de campo (resumen)"], f, titulo="Resumen por semáforo y periodo")
    _, fin = _tabla_excel(ws, t["Flujo por franja medida"], fin + 3,
                          titulo="Flujo por franja medida (veh/h = pasan por ciclo × 3600 ÷ ciclo)")
    _tabla_excel(ws, t["Datos de campo"], fin + 3, titulo="Registros", filtro=True)
    _anchos(ws)

    if tramo is not None and not tramo["tabla"].empty:
        _hoja_tramo(wb, tramo)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def excel_datos_campo(campo: pd.DataFrame) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos de campo"
    ws.sheet_view.showGridLines = False
    f = _titulo(ws, "Datos de campo · cruce vial vía Mesa–Girardot", 1, f"{len(campo)} ciclos observados")
    res = campo.groupby(["semaforo", "periodo"]).agg(
        Ciclos=("pasan", "size"), **{"Pasan total": ("pasan", "sum"), "Pasan prom.": ("pasan", "mean"),
                                     "Pasan máx.": ("pasan", "max"), "Quedan total": ("quedan", "sum"),
                                     "Quedan prom.": ("quedan", "mean")}
    ).reset_index().rename(columns={"semaforo": "Semáforo", "periodo": "Periodo"})
    _, fin = _tabla_excel(ws, res, f, titulo="Resumen")
    _tabla_excel(ws, campo, fin + 3, titulo="Registros", filtro=True)
    _anchos(ws)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
_est = getSampleStyleSheet()
_H1 = ParagraphStyle("h1", parent=_est["Heading1"], textColor=colors.HexColor("#" + AZUL), fontSize=14,
                     spaceBefore=4, spaceAfter=5)
_NOTA = ParagraphStyle("nota", parent=_est["Normal"], fontSize=8.5, textColor=colors.HexColor("#595959"),
                       spaceAfter=6)
_CELDA = ParagraphStyle("celda", parent=_est["BodyText"], fontSize=7, leading=8.5)
_CELDA_NUM = ParagraphStyle("celda_num", parent=_CELDA, alignment=TA_RIGHT)
_CAB = ParagraphStyle("cab", parent=_CELDA, textColor=colors.white, fontName="Helvetica-Bold")
_KPI = ParagraphStyle("kpi", parent=_est["BodyText"], fontSize=7, leading=17)


def _tabla_pdf(df: pd.DataFrame, ancho: float, max_filas: int = 400, anchos_rel=None):
    df = df.head(max_filas)
    num = [pd.api.types.is_numeric_dtype(df[c]) for c in df.columns]
    filas = [[Paragraph(str(c), _CAB) for c in df.columns]]
    for _, r in df.iterrows():
        filas.append([Paragraph(_texto(v, c), _CELDA_NUM if num[j] else _CELDA)
                      for j, (c, v) in enumerate(r.items())])
    rel = anchos_rel or [1] * len(df.columns)
    tot = sum(rel)
    t = Table(filas, colWidths=[ancho * x / tot for x in rel], repeatRows=1, hAlign="LEFT")
    estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + AZUL)),
              ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BFBFBF")),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    for i in range(2, len(filas), 2):
        estilo.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#" + GRIS)))
    t.setStyle(TableStyle(estilo))
    return t


def _img(fig, ancho_cm=25, alto_cm=8):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=ancho_cm * cm, height=alto_cm * cm)


def _estilo_ax(ax):
    ax.grid(axis="y", alpha=0.3)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)


def _kpis_pdf(p: Paquete, ancho):
    claves = ["Vehículos que pasan", "Margen ± IC 99 %", "Promedio por hora", "Error relativo IC 99 % (%)",
              "Pasan en hora valle", "Pasan en hora pico", "Ciclos", "Números pseudoaleatorios"]
    celdas = []
    for k in claves:
        v = p.kpis.get(k, 0)
        d = 2 if "Error" in k else (1 if k == "Horas simuladas" else 0)
        valor = ("± " if k.startswith("Margen") else "") + _mil(v, d)
        celdas.append(Paragraph(f"<font size=7.5 color='#595959'>{k}</font><br/>"
                                f"<font size=14 color='#{AZUL}'><b>{valor}</b></font>", _KPI))
    t = Table([celdas[:4], celdas[4:8]], colWidths=[ancho / 4] * 4, rowHeights=[1.45 * cm] * 2)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFBFBF")),
                           ("INNERGRID", (0, 0), (-1, -1), 1.5, colors.white),
                           ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#" + AZUL_CLARO)),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _pie(canvas, doc):
    canvas.saveState()
    ancho, alto = landscape(A4)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#7F7F7F"))
    canvas.drawString(1.2 * cm, 0.7 * cm, "Simulador del cruce vial · vía Mesa–Girardot · Curso de Simulación")
    canvas.drawRightString(ancho - 1.2 * cm, 0.7 * cm, f"Página {doc.page}")
    canvas.setStrokeColor(colors.HexColor("#" + AZUL))
    canvas.setLineWidth(2)
    canvas.line(1.2 * cm, alto - 0.8 * cm, ancho - 1.2 * cm, alto - 0.8 * cm)
    canvas.restoreState()


_GRANDE = ParagraphStyle("grande", parent=_est["BodyText"], fontSize=11.5, leading=15,
                         textColor=colors.HexColor("#1d3b5a"))


def _tarjetas_pdf(items, ancho, alto=2.4):
    """Fila de tarjetas grandes: [(título, valor, detalle, color hex)]."""
    celdas = [Paragraph(f"<font size=8 color='#595959'>{t}</font><br/>"
                        f"<font size=19 color='{c}'><b>{v}</b></font><br/>"
                        f"<font size=7.5 color='#595959'>{d}</font>", ParagraphStyle("tj", parent=_KPI, leading=21))
              for t, v, d, c in items]
    tb = Table([celdas], colWidths=[ancho / len(items)] * len(items), rowHeights=[alto * cm])
    tb.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFBFBF")),
                            ("INNERGRID", (0, 0), (-1, -1), 2, colors.white),
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F8FC")),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return tb


def _resumen_ejecutivo(p: Paquete, W) -> list:
    """Primera página del PDF: lo esencial en una hoja."""
    k, t = p.kpis, p.tablas
    sem = t["Semáforos"].sort_values("Vehículos que pasan")
    mayor = sem.iloc[-1]
    v, pi = k.get("Promedio por hora valle", 0), k.get("Promedio por hora pico", 0)
    err = k.get("Error relativo IC 99 % (%)", float("nan"))
    prec = t["Precisión"]
    cumple = int((prec["¿Cumple ≤ 1 %?"] == "Sí").sum())
    h = [Paragraph("Resumen ejecutivo · Cruce vial vía Mesa–Girardot", _est["Title"]),
         Paragraph(p.titulo + " · Carrera 10 con Av. Ciudad de las Acacias, Girardot", _NOTA)]
    frase = (f"En el periodo simulado pasan <b>{_mil(k['Vehículos que pasan'])} vehículos</b> "
             f"(± {_mil(k['Margen ± IC 99 %'])} con 99 % de confianza), unos <b>{_mil(k['Promedio por hora'])} por hora</b>. ")
    if v and pi:
        frase += (f"En hora pico pasan <b>{_mil(pi)} veh/h</b>, un <b>{_mil(100 * (pi / v - 1), 1)} % más</b> "
                  f"que en hora valle ({_mil(v)} veh/h). ")
    frase += f"La entrada con más tráfico es <b>{mayor['Semáforo']} · {mayor['Ubicación']}</b> ({_mil(mayor['% del total'], 1)} % del total)."
    h += [Paragraph(frase, _GRANDE), Spacer(1, 0.3 * cm)]
    h.append(_tarjetas_pdf([
        ("Vehículos que pasan", _mil(k["Vehículos que pasan"]), f"± {_mil(k['Margen ± IC 99 %'])} (IC 99 %)", "#0f2a44"),
        ("Promedio por hora", _mil(k["Promedio por hora"]), f"en {_mil(k['Horas simuladas'], 1)} h simuladas", "#1f6f8b"),
        ("Hora valle", _mil(k.get("Pasan en hora valle", 0)), f"{_mil(v)} veh/h", COLOR_VALLE),
        ("Hora pico", _mil(k.get("Pasan en hora pico", 0)), f"{_mil(pi)} veh/h", COLOR_PICO),
        ("Error relativo (IC 99 %)", (_mil(err, 2) + " %") if err == err else "—",
         f"{cumple} de {len(prec)} resultados ≤ 1 %", "#1f9d74" if cumple == len(prec) else COLOR_PICO),
    ], W))
    h.append(Spacer(1, 0.35 * cm))
    # gráfico valle vs pico por semáforo + conclusiones
    vp = t["Semáforo y periodo"]
    fig, ax = plt.subplots(figsize=(6.4, 3.7))
    piv = vp.pivot(index="Semáforo", columns="Periodo", values="Prom. por hora").reindex(SEMAFOROS)
    x = list(range(len(piv)))
    for col, dx, color, nom in (("Valle", -0.2, COLOR_VALLE, "Hora valle"), ("Pico", 0.2, COLOR_PICO, "Hora pico")):
        if col in piv:
            barras = ax.bar([i + dx for i in x], piv[col], 0.4, label=nom, color=color)
            ax.bar_label(barras, fmt="%.0f", fontsize=7, padding=2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{s_}\n{u}" for s_, u in zip(piv.index, t["Semáforos"].set_index("Semáforo").reindex(SEMAFOROS)["Ubicación"])],
                       fontsize=8)
    ax.set_ylabel("Vehículos por hora")
    ax.set_title("Vehículos por hora en cada entrada", fontsize=10)
    ax.legend(fontsize=8)
    _estilo_ax(ax)
    puntos = "".join(f"<b>{r['Indicador']}:</b> {r['Resultado']}<br/><font size=7.5 color='#595959'>{r['Detalle']}</font><br/><br/>"
                     for _, r in t["Conclusiones"].iterrows())
    der = [Paragraph("Conclusiones", _H1), Paragraph(puntos, ParagraphStyle("pt", parent=_est["BodyText"], fontSize=8.5, leading=10.5))]
    tb = Table([[[_img(fig, 13.5, 7.8)], der]], colWidths=[W * 0.52, W * 0.48])
    tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    h.append(tb)
    h.append(Paragraph("Valores promedio de todas las repeticiones. Horas pico según los datos de campo; el resto del día "
                       "se toma como hora valle. El detalle completo está en las páginas siguientes y en el Excel.", _NOTA))
    return h


def _seccion_tramo(tramo: dict, W) -> list:
    ind, tab = tramo["ind"], tramo["tabla"]
    h = [Paragraph("Tramo elegido en el explorador", _H1), Paragraph(tramo["descripcion"], _NOTA)]
    items = [("Vehículos que pasan", _mil(ind["pasan"]), f"{ind['ciclos']} ciclos", "#0f2a44"),
             ("Hora valle", _mil(ind["valle"]), f"{_mil(100 * ind['valle'] / ind['pasan'], 1)} %" if ind["pasan"] else "", COLOR_VALLE),
             ("Hora pico", _mil(ind["pico"]), f"{_mil(100 * ind['pico'] / ind['pasan'], 1)} %" if ind["pasan"] else "", COLOR_PICO),
             ("Quedan en cola", _mil(ind["cola_prom"], 1), f"prom. por ciclo · máx. {ind['cola_max']}", "#64748b")]
    if "veh_h" in ind:
        items.insert(3, ("Promedio por hora", _mil(ind["veh_h"]), f"más alto: {ind['intervalo_max']}", "#1f6f8b"))
    h += [_tarjetas_pdf(items, W, 2.3), Spacer(1, 0.3 * cm)]
    tab = tab.drop(columns=[c for c in ("Desde",) if c in tab.columns])
    if not tramo["por_semaforo"]:
        fig, ax = plt.subplots(figsize=(13, 3.4))
        xs = list(range(len(tab)))
        ax.bar(xs, tab["Pasan en valle"], label="En hora valle", color=COLOR_VALLE)
        ax.bar(xs, tab["Pasan en pico"], bottom=tab["Pasan en valle"], label="En hora pico", color=COLOR_PICO)
        paso = max(1, len(tab) // 30)
        ax.set_xticks(xs[::paso])
        ax.set_xticklabels(tab["Intervalo"].tolist()[::paso], rotation=45, fontsize=7, ha="right")
        ax.set_ylabel("Vehículos")
        ax.legend(fontsize=8)
        _estilo_ax(ax)
        h.append(_img(fig, 26, 6.8))
    else:
        piv = tab.pivot_table(index="Intervalo", columns="Semáforo", values="Pasan (veh)", sort=False)
        fig, ax = plt.subplots(figsize=(13, 3.4))
        n = len(piv.columns)
        for j, s_ in enumerate(piv.columns):
            ax.bar([i + (j - (n - 1) / 2) * 0.8 / n for i in range(len(piv))], piv[s_], 0.8 / n, label=s_,
                   color=COLORES_SEM.get(s_))
        paso = max(1, len(piv) // 30)
        ax.set_xticks(list(range(len(piv)))[::paso])
        ax.set_xticklabels(piv.index.tolist()[::paso], rotation=45, fontsize=7, ha="right")
        ax.set_ylabel("Vehículos")
        ax.legend(fontsize=8, ncol=4)
        _estilo_ax(ax)
        h.append(_img(fig, 26, 6.8))
    h.append(_tabla_pdf(tab, W, max_filas=300))
    if len(tab) > 300:
        h.append(Paragraph("Se muestran los primeros 300 intervalos; el Excel tiene todos.", _NOTA))
    return h


def pdf_paquete(p: Paquete, tramo: dict | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.3 * cm,
                            title="Reporte de simulación – cruce vial", author="Simulador cruce vial")
    W = landscape(A4)[0] - 2.4 * cm
    t = p.tablas
    g = p.graficos
    h = []

    # 0. Resumen ejecutivo (una página)
    h += _resumen_ejecutivo(p, W)
    h.append(PageBreak())
    # 1. Resumen
    h.append(Paragraph("Reporte de simulación · Cruce vial vía Mesa–Girardot", _est["Title"]))
    h.append(Paragraph(p.titulo + " · Carrera 10 con Av. Ciudad de las Acacias, Girardot", _NOTA))
    h.append(_kpis_pdf(p, W))
    h.append(Spacer(1, 0.3 * cm))
    izq = [Paragraph("Parámetros", _H1), _tabla_pdf(t["Parámetros"], W * 0.38, anchos_rel=[1.1, 1.6])]
    vp = t["Semáforo y periodo"]
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    piv = vp.pivot(index="Semáforo", columns="Periodo", values="Prom. por hora").reindex(SEMAFOROS)
    x = list(range(len(piv)))
    if "Valle" in piv:
        ax.bar([i - 0.2 for i in x], piv["Valle"], 0.4, label="Hora valle", color=COLOR_VALLE)
    if "Pico" in piv:
        ax.bar([i + 0.2 for i in x], piv["Pico"], 0.4, label="Hora pico", color=COLOR_PICO)
    ax.set_xticks(x)
    ax.set_xticklabels(piv.index)
    ax.set_ylabel("Vehículos por hora")
    ax.set_title("Vehículos por hora en cada semáforo: valle vs pico", fontsize=10)
    ax.legend(fontsize=8)
    _estilo_ax(ax)
    der = [Paragraph("Hora valle frente a hora pico", _H1), _img(fig, 15, 8.2)]
    lado = Table([[izq, der]], colWidths=[W * 0.4, W * 0.6])
    lado.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    h.append(lado)

    h.append(PageBreak())
    h.append(KeepTogether([Paragraph("Conclusiones de la simulación", _H1),
                           Paragraph(p.notas["Conclusiones"], ParagraphStyle("conc", parent=_NOTA, fontSize=10,
                                                                             textColor=colors.HexColor("#1d3b5a"))),
                           _tabla_pdf(t["Conclusiones"], W, anchos_rel=[1.4, 1.8, 3.6])]))
    h.append(Spacer(1, 0.3 * cm))
    h.append(KeepTogether([Paragraph("Resultados por semáforo", _H1), _tabla_pdf(t["Semáforos"], W)]))
    h.append(Spacer(1, 0.3 * cm))
    h.append(KeepTogether([Paragraph("Precisión de la predicción (confianza 99 %, error objetivo ≤ 1 %)", _H1),
                           Paragraph(p.notas["Precisión"], _NOTA), _tabla_pdf(t["Precisión"], W)]))
    h.append(Spacer(1, 0.3 * cm))
    h.append(KeepTogether([Paragraph("Hora valle frente a hora pico (todo el periodo)", _H1),
                           Paragraph(p.notas["Valle vs pico"], _NOTA), _tabla_pdf(t["Valle vs pico"], W)]))
    h.append(Spacer(1, 0.3 * cm))
    h.append(KeepTogether([Paragraph("Cada semáforo en hora valle y en hora pico", _H1),
                           Paragraph(p.notas["Semáforo y periodo"], _NOTA), _tabla_pdf(vp, W)]))

    # 1b. Tramo elegido en el explorador
    if tramo is not None and not tramo["tabla"].empty:
        h.append(PageBreak())
        h += _seccion_tramo(tramo, W)

    # 2. Bloques de horas
    nombre_b = next(k for k in t if k.startswith("Bloques de") and k.endswith(" h"))
    b = g["bloques"]
    h.append(PageBreak())
    h.append(Paragraph(f"Vehículos que pasan por {nombre_b.lower()}", _H1))
    h.append(Paragraph(p.notas[nombre_b], _NOTA))
    fig, ax = plt.subplots(figsize=(13, 3.8))
    xs = list(range(len(b)))
    ax.bar(xs, b["en_valle"], label="En hora valle", color=COLOR_VALLE)
    ax.bar(xs, b["en_pico"], bottom=b["en_valle"], label="En hora pico", color=COLOR_PICO)
    paso = max(1, len(b) // 30)
    ax.set_xticks(xs[::paso])
    ax.set_xticklabels(b["bloque_ini"].dt.strftime("%d/%m %H:%M").tolist()[::paso], rotation=55, fontsize=7, ha="right")
    ax.set_ylabel("Vehículos")
    ax.legend(fontsize=8)
    _estilo_ax(ax)
    h.append(_img(fig, 26, 7.6))
    h.append(_tabla_pdf(t[nombre_b], W, max_filas=300, anchos_rel=[2.6] + [1] * (len(t[nombre_b].columns) - 1)))
    if len(t[nombre_b]) > 300:
        h.append(Paragraph("Se muestran los primeros 300 bloques; el Excel tiene todos.", _NOTA))

    # 3. Por hora
    hr = g["horas"]
    h.append(PageBreak())
    h.append(Paragraph("Vehículos que pasan por hora", _H1))
    h.append(Paragraph(p.notas["Por hora"] + " Franjas naranjas: horas pico.", _NOTA))
    fig, ax = plt.subplots(figsize=(13, 3.8))
    for s in SEMAFOROS:
        ax.plot(hr["hora"], hr[s], label=s, color=COLORES_SEM[s], lw=1.4)
    for x0, x1 in franjas_pico(p.inicio, p.fin):
        ax.axvspan(x0, x1, color=COLOR_PICO, alpha=0.15, lw=0)
    ax.set_ylabel("Vehículos por hora")
    ax.legend(fontsize=8, ncol=4)
    _estilo_ax(ax)
    fig.autofmt_xdate()
    h.append(_img(fig, 26, 7.6))
    h.append(_tabla_pdf(t["Por hora"], W, max_filas=300, anchos_rel=[1.8] + [1] * (len(t["Por hora"].columns) - 1)))
    if len(t["Por hora"]) > 300:
        h.append(Paragraph("Se muestran las primeras 300 horas; el Excel tiene todas.", _NOTA))

    # 4. Bloques de ciclos
    nombre_c = next(k for k in t if k.endswith(" ciclos"))
    bc = g["bloques_ciclos"]
    h.append(PageBreak())
    h.append(Paragraph(f"Vehículos que pasan por {nombre_c.lower()}", _H1))
    h.append(Paragraph(p.notas[nombre_c], _NOTA))
    fig, ax = plt.subplots(figsize=(13, 3.6))
    for s in SEMAFOROS:
        d = bc[bc["semaforo"] == s]
        ax.plot(d["desde"], d["pasan"], label=s, color=COLORES_SEM[s], lw=1.4,
                marker="o" if len(d) < 50 else None, ms=3)
    ax.set_ylabel("Vehículos por bloque")
    ax.legend(fontsize=8, ncol=4)
    _estilo_ax(ax)
    fig.autofmt_xdate()
    h.append(_img(fig, 26, 7.2))
    h.append(_tabla_pdf(t[nombre_c], W, max_filas=300))
    if len(t[nombre_c]) > 300:
        h.append(Paragraph("Se muestran los primeros 300 bloques; el Excel tiene todos.", _NOTA))

    # 4b. Mapa de calor, cajas y colas
    h.append(PageBreak())
    h.append(Paragraph("Mapa de calor: vehículos por día y hora", _H1))
    h.append(Paragraph(p.notas["Mapa de calor"], _NOTA))
    mc = t["Mapa de calor (día × hora)"]
    filas_mc = min(len(mc), 31)
    fig, ax = plt.subplots(figsize=(13, max(1.6, 0.42 * filas_mc + 1)))
    im = ax.imshow(mc.head(filas_mc).to_numpy(dtype=float), aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(24)); ax.set_xticklabels([c[:2] for c in mc.columns], fontsize=7)
    ax.set_yticks(range(filas_mc)); ax.set_yticklabels(mc.index[:filas_mc], fontsize=7)
    ax.set_xlabel("Hora del día")
    fig.colorbar(im, ax=ax, label="Vehículos", fraction=0.025)
    h.append(_img(fig, 26, min(15, max(3.2, 0.55 * filas_mc + 1.6))))
    cic = g["ciclos"]
    fig, axs = plt.subplots(1, 2, figsize=(13, 3.8))
    datos, etiquetas, colores = [], [], []
    for s in SEMAFOROS:
        for per, col in (("Valle", COLOR_VALLE), ("Pico", COLOR_PICO)):
            d = cic[(cic["semaforo"] == s) & (cic["periodo"] == per)]["pasan"]
            if len(d):
                datos.append(d.to_numpy()); etiquetas.append(f"{s}\n{per}"); colores.append(col)
    bp = axs[0].boxplot(datos, patch_artist=True, tick_labels=etiquetas)
    for caja, col in zip(bp["boxes"], colores):
        caja.set_facecolor(col); caja.set_alpha(0.75)
    axs[0].set_title("Vehículos que pasan por ciclo", fontsize=10); axs[0].tick_params(labelsize=7)
    _estilo_ax(axs[0])
    maxq = int(cic["quedan"].max()) if len(cic) else 1
    for s in SEMAFOROS:
        d = cic[cic["semaforo"] == s]["quedan"]
        axs[1].hist(d, bins=range(0, maxq + 2), alpha=0.55, label=s, color=COLORES_SEM[s])
    axs[1].set_title("Histograma de colas al final del verde", fontsize=10)
    axs[1].set_xlabel("Carros en cola"); axs[1].set_ylabel("Ciclos"); axs[1].legend(fontsize=8)
    _estilo_ax(axs[1])
    h.append(Paragraph("Diagramas de caja e histograma de colas", _H1))
    h.append(Paragraph(p.notas["Cajas"] + " " + p.notas["Colas"], _NOTA))
    h.append(_img(fig, 26, 7.4))
    h.append(_tabla_pdf(t["Colas"], W))

    # 5. Capacidad y validación
    h.append(PageBreak())
    h.append(Paragraph("¿Cuánto aguanta el cruce? (hora valle y hora pico)", _H1))
    h.append(Paragraph(p.notas["Capacidad"], _NOTA))
    h.append(_tabla_pdf(t["Capacidad"], W))
    bar = g["barrido"]
    fig, axs = plt.subplots(1, 2, figsize=(13, 3.4), sharey=True)
    for ax, per in zip(axs, ["Valle", "Pico"]):
        d = bar[bar["periodo"] == per]
        for s in SEMAFOROS:
            ds = d[d["semaforo"] == s]
            ax.plot(ds["factor"], ds["cola_prom"], label=s, color=COLORES_SEM[s], marker="o", ms=2.5)
        ax.axvline(1, ls="--", color="grey", lw=1)
        ax.set_title(f"Hora {per.lower()}", fontsize=10)
        ax.set_xlabel("Demanda (× la observada)")
        _estilo_ax(ax)
    axs[0].set_ylabel("Cola promedio (veh)")
    axs[0].legend(fontsize=8)
    h.append(_img(fig, 26, 6.8))
    h.append(KeepTogether([Paragraph("Validación: simulado frente a observado", _H1),
                           Paragraph(p.notas["Validación"], _NOTA), _tabla_pdf(t["Validación"], W * 0.75)]))
    h.append(KeepTogether([Paragraph("Prueba de ajuste de las llegadas (chi-cuadrado, 99 %)", _H1),
                           Paragraph(p.notas["Prueba de ajuste de llegadas"], _NOTA),
                           _tabla_pdf(t["Prueba de ajuste de llegadas"], W)]))

    # 6. Números pseudoaleatorios
    h.append(PageBreak())
    h.append(Paragraph("Números pseudoaleatorios generados y qué significa cada uno", _H1))
    h.append(Paragraph(p.notas["Números pseudoaleatorios"], _NOTA))
    nums = t["Números pseudoaleatorios"].drop(columns=["Inicio del ciclo", "Para qué se usa"])
    h.append(_tabla_pdf(nums, W, max_filas=160, anchos_rel=[0.5, 0.7, 0.5, 0.6, 0.6, 1.1, 1.3, 0.9, 1.3, 0.6, 3.4]))
    if len(nums) > 160:
        h.append(Paragraph(f"Se muestran los primeros 160 de {len(nums):,} números; el Excel tiene la secuencia "
                           "completa.".replace(",", "."), _NOTA))

    # 7. Datos de campo
    h.append(PageBreak())
    h.append(Paragraph("Datos de campo (resumen)", _H1))
    h.append(Paragraph(f"{len(t['Datos de campo'])} ciclos observados por registro manual, de verde a rojo.", _NOTA))
    h.append(_tabla_pdf(t["Datos de campo (resumen)"], W * 0.75))
    h.append(KeepTogether([Paragraph("¿En qué franjas hay más flujo? (datos de campo)", _H1),
                           Paragraph("Vehículos por hora = pasan por ciclo × 3600 ÷ duración del ciclo. 'Cruce completo' "
                                     "suma los 4 semáforos cuando se midieron los 4 en esa franja.", _NOTA),
                           _tabla_pdf(t["Flujo por franja medida"], W)]))

    doc.build(h, onFirstPage=_pie, onLaterPages=_pie)
    return buf.getvalue()


def pdf_datos_campo(campo: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.3 * cm, title="Datos de campo – cruce vial")
    W = landscape(A4)[0] - 2.4 * cm
    res = campo.groupby(["semaforo", "periodo"]).agg(
        Ciclos=("pasan", "size"), **{"Pasan total": ("pasan", "sum"), "Pasan prom.": ("pasan", "mean"),
                                     "Pasan máx.": ("pasan", "max"), "Quedan total": ("quedan", "sum"),
                                     "Quedan prom.": ("quedan", "mean")}
    ).reset_index().rename(columns={"semaforo": "Semáforo", "periodo": "Periodo"})
    h = [Paragraph("Datos de campo · Cruce vial vía Mesa–Girardot", _est["Title"]),
         Paragraph(f"{len(campo)} ciclos observados (registro manual por ciclo de verde a rojo).", _NOTA),
         Paragraph("Resumen", _H1), _tabla_pdf(res, W * 0.75),
         Paragraph("Registros", _H1), _tabla_pdf(campo, W, max_filas=500)]
    doc.build(h, onFirstPage=_pie, onLaterPages=_pie)
    return buf.getvalue()
