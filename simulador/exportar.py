"""Exportación de resultados a Excel y PDF."""

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from .datos import SEMAFOROS
from .prediccion import ResultadoPrediccion, texto_horas_pico
from .reportes import (reporte_bloques, reporte_bloques_ciclos, reporte_horas, reporte_semaforos,
                       reporte_valle_pico)

MAX_FILAS_EXCEL = 1_000_000

NOMBRES = {
    "bloque": "Bloque", "hora": "Hora", "periodo": "Periodo", "semaforo": "Semáforo",
    "ubicacion": "Ubicación", "total": "Total que pasan", "ic95": "± IC 95 %",
    "pct_del_total": "% del total", "ciclos": "Ciclos", "prom_por_ciclo": "Prom. por ciclo",
    "en_valle": "Pasan en horas valle", "pct_valle": "% valle",
    "en_pico": "Pasan en horas pico", "pct_pico": "% pico", "cola_prom": "Cola prom.",
    "pasan": "Pasan", "horas": "Horas", "prom_por_hora": "Prom. por hora",
    "verde_s": "Verde (s)", "rojo_s": "Rojo (s)", "ciclo_s": "Ciclo (s)",
    "capacidad_ciclo": "Capacidad por verde", "llegadas": "Llegadas",
    "inicio": "Inicio del ciclo", "ciclo": "Ciclo", "U1": "U1", "U2": "U2",
    "en_espera": "En espera", "rezagados": "Rezagados", "capacidad": "Capacidad",
    "quedan": "Quedan", "pasan_prom": "Pasan (prom. repeticiones)",
    "quedan_prom": "Quedan (prom. repeticiones)", "llegadas_prom": "Llegadas (prom. repeticiones)",
    "ciclos_txt": "Ciclos", "desde": "Desde", "hasta": "Hasta", "pct_del_semaforo": "% del semáforo",
}
for s in SEMAFOROS:
    NOMBRES[f"{s}_por_ciclo"] = f"{s} prom. por ciclo"


def _legible(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns=NOMBRES)


def parametros(res: ResultadoPrediccion, horas_bloque: int, ciclos_bloque: int = 10) -> pd.DataFrame:
    e = res.escenario
    filas = [
        ("Desde", e.inicio.strftime("%d/%m/%Y %H:%M")),
        ("Hasta", e.fin.strftime("%d/%m/%Y %H:%M")),
        ("Horas simuladas", round((e.fin - e.inicio).total_seconds() / 3600, 2)),
        ("Repeticiones", e.repeticiones),
        ("Semilla del generador", e.semilla),
        ("Números pseudoaleatorios usados", res.numeros_usados),
        ("Demanda (× la observada)", e.factor_demanda),
        ("Bloques del reporte (horas)", horas_bloque),
        ("Bloques del reporte (ciclos)", ciclos_bloque),
        ("Horas pico", texto_horas_pico()),
        ("Horas valle", "todas las demás"),
        ("Generador", "X(n+1) = 16807·X(n) mod 2147483647"),
        ("Generado el", datetime.now().strftime("%d/%m/%Y %H:%M")),
    ]
    for _, r in res.info_semaforos.iterrows():
        filas.append((f"{r['semaforo']} – {r['ubicacion']}",
                      f"verde {r['verde_s']} s, rojo {r['rojo_s']} s, capacidad {r['capacidad_ciclo']} veh/verde"))
    return pd.DataFrame(filas, columns=["Parámetro", "Valor"])


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def _formatear_hoja(ws):
    gris = PatternFill("solid", fgColor="D9D9D9")
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = gris
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, col in enumerate(ws.columns, start=1):
        largo = max((len(str(c.value)) if c.value is not None else 0) for c in list(col)[:200])
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, largo + 2), 45)
    ws.freeze_panes = "A2"


def _escribir(writer, df, hoja, decimales=2):
    df = df.copy()
    for c in df.select_dtypes("float").columns:
        df[c] = df[c].round(decimales)
    df.to_excel(writer, sheet_name=hoja, index=False)
    _formatear_hoja(writer.sheets[hoja])


def excel_prediccion(res: ResultadoPrediccion, horas_bloque: int, campo: pd.DataFrame | None = None,
                     ciclos_bloque: int = 10) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        _escribir(w, parametros(res, horas_bloque, ciclos_bloque), "Parámetros")
        _escribir(w, _legible(reporte_semaforos(res)), "Por semáforo")
        _escribir(w, _legible(reporte_valle_pico(res)), "Valle vs pico")
        _escribir(w, _legible(reporte_bloques(res, horas_bloque).drop(columns=["bloque_ini"])),
                  f"Bloques de {horas_bloque} h")
        horas = reporte_horas(res)
        horas["hora"] = horas["hora"].dt.strftime("%d/%m/%Y %H:%M")
        _escribir(w, _legible(horas), "Por hora")
        bc = reporte_bloques_ciclos(res, ciclos_bloque)
        bc["desde"] = bc["desde"].dt.strftime("%d/%m/%Y %H:%M")
        bc["hasta"] = bc["hasta"].dt.strftime("%d/%m/%Y %H:%M")
        _escribir(w, _legible(bc), f"Bloques de {ciclos_bloque} ciclos")
        ciclos = res.ciclos.drop(columns=["pasan_var"]).copy()
        ciclos["inicio"] = ciclos["inicio"].dt.strftime("%d/%m/%Y %H:%M:%S")
        if len(ciclos) > MAX_FILAS_EXCEL:
            ciclos = ciclos.head(MAX_FILAS_EXCEL)
        _escribir(w, _legible(ciclos), "Por ciclo", decimales=5)
        if campo is not None:
            _escribir(w, campo, "Datos de campo")
    return buf.getvalue()


def excel_datos_campo(campo: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        _escribir(w, campo, "Datos de campo")
        res = campo.groupby(["semaforo", "periodo"]).agg(
            ciclos=("pasan", "size"), pasan_total=("pasan", "sum"), pasan_prom=("pasan", "mean"),
            pasan_max=("pasan", "max"), quedan_total=("quedan", "sum"), quedan_prom=("quedan", "mean"),
        ).reset_index()
        _escribir(w, res, "Resumen")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _tabla_pdf(df: pd.DataFrame, ancho_total: float, decimales: int = 1, max_filas: int = 60):
    df = df.head(max_filas).copy()
    filas = [list(df.columns)]
    for _, r in df.iterrows():
        fila = []
        for v in r:
            if isinstance(v, float):
                fila.append(f"{v:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", "."))
            elif isinstance(v, pd.Timestamp):
                fila.append(v.strftime("%d/%m/%Y %H:%M"))
            else:
                fila.append(str(v))
        filas.append(fila)
    estilo = getSampleStyleSheet()["BodyText"].clone("celda", fontSize=7, leading=8)
    filas = [[Paragraph(str(c), estilo) for c in f] for f in filas]
    t = Table(filas, colWidths=[ancho_total / len(df.columns)] * len(df.columns), repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9D9D9")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _grafico(fig) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=24 * cm, height=8 * cm)


def pdf_prediccion(res: ResultadoPrediccion, horas_bloque: int, ciclos_bloque: int = 10) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm,
                            title="Reporte de predicción – cruce vial")
    ancho = landscape(A4)[0] - 2.4 * cm
    est = getSampleStyleSheet()
    e = res.escenario
    bloques = reporte_bloques(res, horas_bloque)
    vp = reporte_valle_pico(res)
    sem = reporte_semaforos(res)
    total = sem["pasan"].sum()

    h = []
    h.append(Paragraph("Reporte de predicción del tránsito – Cruce vial vía Mesa–Girardot", est["Title"]))
    h.append(Paragraph(
        f"Del {e.inicio:%d/%m/%Y %H:%M} al {e.fin:%d/%m/%Y %H:%M} · {e.repeticiones} repeticiones · "
        f"semilla {e.semilla} · {res.numeros_usados:,} números pseudoaleatorios".replace(",", "."), est["Normal"]))
    h.append(Spacer(1, 0.3 * cm))
    h.append(Paragraph(
        f"<b>Total estimado de vehículos que pasan: {total:,.0f}</b>. Horas pico: {texto_horas_pico()}; "
        f"el resto del día se toma como hora valle. Los valores son el promedio de las repeticiones; "
        f"± IC 95 % = 1,96 · desviación estándar / raíz de R.".replace(",", "X").replace("X", "."), est["Normal"]))
    h.append(Spacer(1, 0.4 * cm))

    h.append(Paragraph("Parámetros", est["Heading2"]))
    h.append(_tabla_pdf(parametros(res, horas_bloque, ciclos_bloque), ancho * 0.7))

    cols = ["semaforo", "ubicacion", "verde_s", "ciclo_s", "capacidad_ciclo", "ciclos", "pasan",
            "ic95", "pct_del_total", "prom_por_ciclo", "cola_prom"]
    h.append(KeepTogether([Paragraph("Resultados por semáforo", est["Heading2"]),
                           _tabla_pdf(_legible(sem[cols]), ancho)]))
    h.append(KeepTogether([Paragraph("Horas valle frente a horas pico", est["Heading2"]),
                           _tabla_pdf(_legible(vp), ancho)]))

    h.append(PageBreak())
    h.append(Paragraph(f"Vehículos que pasan por bloques de {horas_bloque} horas", est["Heading2"]))
    fig, ax = plt.subplots(figsize=(12, 4))
    x = range(len(bloques))
    ax.bar(x, bloques["en_valle"], label="En horas valle", color="#7FA7C9")
    ax.bar(x, bloques["en_pico"], bottom=bloques["en_valle"], label="En horas pico", color="#D9774B")
    paso = max(1, len(bloques) // 24)
    ax.set_xticks(list(x)[::paso])
    ax.set_xticklabels(bloques["bloque_ini"].dt.strftime("%d/%m %H:%M").tolist()[::paso], rotation=60, fontsize=7)
    ax.set_ylabel("Vehículos")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    h.append(_grafico(fig))
    cols = ["bloque"] + SEMAFOROS + ["total", "ic95", "pct_del_total", "ciclos", "prom_por_ciclo",
                                     "en_valle", "pct_valle", "en_pico", "pct_pico"]
    h.append(_tabla_pdf(_legible(bloques[cols]), ancho, max_filas=200))
    if len(bloques) > 200:
        h.append(Paragraph("Se muestran los primeros 200 bloques; el Excel tiene todos.", est["Italic"]))

    h.append(PageBreak())
    h.append(Paragraph("Vehículos que pasan por hora", est["Heading2"]))
    horas = reporte_horas(res)
    fig, ax = plt.subplots(figsize=(12, 4))
    for s in SEMAFOROS:
        ax.plot(horas["hora"], horas[s], label=s)
    ax.set_ylabel("Vehículos por hora")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    h.append(_grafico(fig))
    h.append(_tabla_pdf(_legible(horas[["hora", "periodo"] + SEMAFOROS + ["total", "ic95", "pct_del_total", "ciclos", "cola_prom"]]),
                        ancho, max_filas=200))
    if len(horas) > 200:
        h.append(Paragraph("Se muestran las primeras 200 horas; el Excel tiene todas.", est["Italic"]))

    h.append(PageBreak())
    h.append(Paragraph(f"Vehículos que pasan por bloques de {ciclos_bloque} ciclos", est["Heading2"]))
    bc = reporte_bloques_ciclos(res, ciclos_bloque)
    fig, ax = plt.subplots(figsize=(12, 4))
    for s in SEMAFOROS:
        d = bc[bc["semaforo"] == s]
        ax.plot(d["desde"], d["pasan"], label=s, marker="o" if len(d) < 60 else None)
    ax.set_ylabel(f"Vehículos en {ciclos_bloque} ciclos")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    h.append(_grafico(fig))
    h.append(_tabla_pdf(_legible(bc), ancho, max_filas=200))
    if len(bc) > 200:
        h.append(Paragraph("Se muestran los primeros 200 bloques; el Excel tiene todos.", est["Italic"]))

    doc.build(h)
    return buf.getvalue()


def pdf_datos_campo(campo: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm, title="Datos de campo – cruce vial")
    ancho = landscape(A4)[0] - 2.4 * cm
    est = getSampleStyleSheet()
    res = campo.groupby(["semaforo", "periodo"]).agg(
        ciclos=("pasan", "size"), pasan_total=("pasan", "sum"), pasan_prom=("pasan", "mean"),
        pasan_max=("pasan", "max"), quedan_total=("quedan", "sum"), quedan_prom=("quedan", "mean"),
    ).reset_index()
    h = [Paragraph("Datos de campo – Cruce vial vía Mesa–Girardot", est["Title"]),
         Paragraph(f"{len(campo)} ciclos observados (registro manual por ciclo de verde a rojo).", est["Normal"]),
         Paragraph("Resumen", est["Heading2"]), _tabla_pdf(res, ancho, decimales=2),
         Paragraph("Registros", est["Heading2"]), _tabla_pdf(campo, ancho, decimales=0, max_filas=400)]
    doc.build(h)
    return buf.getvalue()
