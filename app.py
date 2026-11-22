"""Simulador del cruce vial de 4 semáforos — vía Mesa–Girardot.

Ejecutar:  streamlit run app.py
"""

from datetime import date, datetime, time, timedelta

import math
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from simulador.datos import PERIODOS, SEMAFOROS, calcular_llegadas, cargar_semaforos, leer_base
from simulador.exportar import _decimales, excel_paquete, pdf_paquete
from simulador.explorador import FRECUENCIAS_HORA, explorar
from simulador.casos import CAMPOS, correr_casos
from simulador.generador import GeneradorCongruencial
from simulador.mapa import CENTRO_DEFECTO, POSICIONES_DEFECTO, enlaces_google
from simulador.modelo import tabla_intervalos
from simulador.prediccion import (EscenarioPrediccion, MAX_CICLOS_TOTALES, ciclos_estimados,
                                  cubre_valle_y_pico, franjas_pico, predecir,
                                  texto_horas_pico)
from simulador.pruebas import prueba_frecuencias, prueba_ks, prueba_promedios
from simulador.paquete import construir
from simulador.estilo import CSS, PICO, VALLE, VERDE, configurar_plotly, hero, kpis, nota, paso, seccion
from simulador.visor import html_visor

st.set_page_config(page_title="Simulador cruce vial · Mesa–Girardot", page_icon="🚦", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)
configurar_plotly()


@st.cache_data
def datos():
    return cargar_semaforos(), calcular_llegadas(leer_base()), leer_base()


semaforos, base, campo = datos()


def mil(x, dec=0):
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tabla(df, alto=None):
    """Muestra una tabla con separador de miles '.', decimales ',' y fechas dd/mm/aaaa."""
    fmt = {}
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            fmt[c] = "{:%d/%m/%Y %H:%M}"
        elif pd.api.types.is_float_dtype(df[c]):
            serie = df[c].dropna()
            d = _decimales(c)
            if d == 0 and len(serie) and not (serie == serie.round()).all() and "veh/h" not in c.lower():
                d = 1
            fmt[c] = lambda v, d=d: "" if pd.isna(v) else mil(v, d)
        elif pd.api.types.is_integer_dtype(df[c]):
            fmt[c] = lambda v: mil(v)
    kw = {"height": alto} if alto else {}
    st.dataframe(df.style.format(fmt), use_container_width=True, hide_index=True, **kw)


# ---------------------------------------------------------------------------
# Barra lateral: periodo a predecir
# ---------------------------------------------------------------------------
st.sidebar.markdown("## 🚦 Panel de simulación")
st.sidebar.caption("Defina el periodo y los números pseudoaleatorios. Todo se recalcula al instante.")
# --- Los 3 parámetros enlazados: periodo ↔ ciclos ↔ números pseudoaleatorios -------------------
DUR_CICLO = {s: semaforos[s].verde + semaforos[s].rojo for s in SEMAFOROS}


def ciclos_en(segundos: float) -> dict:
    """Ciclos completos de cada semáforo en el periodo: segundos ÷ duración del ciclo."""
    return {s: int(segundos // DUR_CICLO[s]) for s in SEMAFOROS}


def segundos_para(ciclos_totales: int) -> int:
    """Menor duración (en minutos enteros) en la que caben al menos esos ciclos entre los 4 semáforos."""
    seg = int(ciclos_totales / sum(1 / c for c in DUR_CICLO.values()))
    seg = -(-seg // 60) * 60
    while sum(ciclos_en(seg).values()) < ciclos_totales:
        seg += 60
    return seg


def _inicio():
    ss = st.session_state
    return datetime.combine(ss.f_ini, ss.h_ini)


def _fijar_fin(fin):
    ss = st.session_state
    ss.f_fin, ss.h_fin = fin.date(), fin.time().replace(second=0, microsecond=0)


def _desde_periodo():
    ss = st.session_state
    seg = max(0, (datetime.combine(ss.f_fin, ss.h_fin) - _inicio()).total_seconds())
    ss.ciclos = sum(ciclos_en(seg).values())
    ss.numeros = 2 * ss.ciclos * ss.repeticiones


def _desde_ciclos():
    ss = st.session_state
    _fijar_fin(_inicio() + timedelta(seconds=segundos_para(max(4, ss.ciclos))))
    _desde_periodo()


def _desde_numeros():
    ss = st.session_state
    ss.ciclos = max(4, -(-ss.numeros // (2 * ss.repeticiones)))
    _desde_ciclos()


ss = st.session_state
if "f_ini" not in ss:
    ss.f_ini, ss.h_ini = date.today(), time(6, 0)
    ss.f_fin, ss.h_fin = date.today(), time(20, 0)
    ss.repeticiones = 10
    _desde_periodo()

sb = st.sidebar
sb.markdown(paso(1, "Periodo (fechas y horas)"), unsafe_allow_html=True)
c1, c2 = sb.columns(2)
c1.date_input("Desde el día", key="f_ini", format="DD/MM/YYYY", on_change=_desde_periodo)
c2.time_input("a las", key="h_ini", step=timedelta(minutes=30), on_change=_desde_periodo)
c1, c2 = sb.columns(2)
c1.date_input("Hasta el día", key="f_fin", format="DD/MM/YYYY", on_change=_desde_periodo)
c2.time_input("a las ", key="h_fin", step=timedelta(minutes=30), on_change=_desde_periodo)
sb.markdown(paso(2, "Ciclos (los 4 semáforos)"), unsafe_allow_html=True)
sb.number_input("Ciclos totales", min_value=4, max_value=MAX_CICLOS_TOTALES, step=100, key="ciclos",
                on_change=_desde_ciclos,
                help="Ciclos completos (verde → rojo) que caben en el periodo, sumando los 4 semáforos. "
                     "Si lo cambia, la hora final se ajusta.")
sb.markdown(paso(3, "Números pseudoaleatorios"), unsafe_allow_html=True)
sb.number_input("Números a generar", min_value=8, max_value=2 * MAX_CICLOS_TOTALES, step=1000, key="numeros",
                on_change=_desde_numeros,
                help="Cada ciclo usa 2 números (U1 y U2) en cada repetición: números = 2 × ciclos × repeticiones. "
                     "Si lo cambia, se ajustan los ciclos y la hora final.")
sb.number_input("Repeticiones de la simulación", 1, 200, key="repeticiones", on_change=_desde_periodo,
                help="Cada repetición usa números pseudoaleatorios distintos. El resultado es el promedio.")

inicio = _inicio()
fin = datetime.combine(ss.f_fin, ss.h_fin)
seg_periodo = max(0, (fin - inicio).total_seconds())
por_sem = ciclos_en(seg_periodo)
sb.markdown('<div class="calc">🧮 <b>' + mil(seg_periodo / 3600, 2) + ' h</b> → ciclos por semáforo:<br>'
            + "<br>".join(f"{s}: {mil(seg_periodo)} ÷ {DUR_CICLO[s]} s = <b>{mil(por_sem[s])}</b>" for s in SEMAFOROS)
            + f"<br>Total <b>{mil(sum(por_sem.values()))}</b> ciclos × 2 × {ss.repeticiones} rep. = "
              f"<b>{mil(2 * sum(por_sem.values()) * ss.repeticiones)}</b> números</div>", unsafe_allow_html=True)

sb.markdown(paso("📑", "Reportes"), unsafe_allow_html=True)
c1, c2 = sb.columns(2)
horas_bloque = c1.selectbox("Bloques de horas", [1, 2, 3, 4, 6, 8, 12, 24], index=1,
                            format_func=lambda h: f"{h} h")
ciclos_bloque = c2.selectbox("Bloques de ciclos", [5, 10, 20, 30, 50, 100, 250, 500, 1000], index=1)

sb.markdown(paso("🎛", "Escenario"), unsafe_allow_html=True)
semilla = int(sb.number_input("Semilla del generador", 1, 2_147_483_646, 12345, step=1))
factor = float(sb.slider("Demanda (1.0 = la observada)", 0.5, 3.0, 1.0, step=0.1,
                         help="1.2 significa que llegan 20 % más carros que en la toma de datos"))

sb.markdown(paso("🔒", "Restricciones fijas del cruce"), unsafe_allow_html=True)
sb.dataframe(pd.DataFrame([{"Semáforo": f"{s} {semaforos[s].ubicacion}", "Verde": f"{semaforos[s].verde} s",
                            "Rojo": f"{semaforos[s].rojo} s"} for s in SEMAFOROS]),
             hide_index=True, use_container_width=True)
sb.caption(f"Horas pico (fijas, tomadas del Excel de campo): {texto_horas_pico()}. El resto del día es hora valle. "
           "Toda simulación debe incluir horas valle y horas pico.")

repeticiones = int(ss.repeticiones)

# --- Validaciones: toda simulación debe tener valle y pico -------------------------------------
_hero_simple = hero("Simulador del cruce vial · vía Mesa–Girardot",
                    "Carrera 10 con Av. Ciudad de las Acacias, Girardot · Curso de Simulación", [])
if fin <= inicio:
    st.markdown(_hero_simple, unsafe_allow_html=True)
    st.error("La fecha y hora final debe ser posterior a la inicial.")
    st.stop()
hay_valle, hay_pico = cubre_valle_y_pico(inicio, fin)
if not (hay_valle and hay_pico):
    falta = "ninguna hora pico" if not hay_pico else "ninguna hora valle"
    st.markdown(_hero_simple, unsafe_allow_html=True)
    st.error(f"El periodo del {inicio:%d/%m/%Y %H:%M} al {fin:%d/%m/%Y %H:%M} no incluye {falta}. "
             f"Toda simulación debe tener horas valle y horas pico (pico: {texto_horas_pico()}). "
             "Amplíe el periodo, por ejemplo de 10:00 a 14:00.")
    st.stop()
_esc = EscenarioPrediccion(inicio, fin, repeticiones, semilla, factor)
if ciclos_estimados(semaforos, _esc) > MAX_CICLOS_TOTALES:
    st.markdown(_hero_simple, unsafe_allow_html=True)
    st.error(f"Son {mil(ciclos_estimados(semaforos, _esc))} ciclos a simular (ciclos × repeticiones). "
             f"El máximo es {mil(MAX_CICLOS_TOTALES)}. Reduzca el periodo, los ciclos, los números o las repeticiones.")
    st.stop()


# --- Simulación y reportes: se recalculan solos con cada cambio --------------------------------
@st.cache_data(show_spinner="Simulando…", max_entries=6)
def correr(inicio, fin, repeticiones, semilla, factor):
    return predecir(semaforos, EscenarioPrediccion(inicio, fin, repeticiones, semilla, factor))


@st.cache_data(show_spinner="Armando los reportes…", max_entries=6)
def armar(inicio, fin, repeticiones, semilla, factor, horas_bloque, ciclos_bloque):
    return construir(correr(inicio, fin, repeticiones, semilla, factor), semaforos, base, horas_bloque, ciclos_bloque)


def describir_tramo(cfg) -> str:
    modo, sems, por_sem, desde, hasta, frec, cd, ch, cada = cfg
    quienes = "los 4 semáforos" if len(sems) == len(SEMAFOROS) else ", ".join(sems)
    vista = "cada semáforo por separado" if por_sem else "juntos"
    if modo == "horas":
        nombre_f = next(k for k, v in FRECUENCIAS_HORA.items() if v == frec)
        return f"De {desde:%d/%m/%Y %H:%M} a {hasta:%d/%m/%Y %H:%M}, agrupado cada {nombre_f} · {quienes} ({vista})"
    return f"Del ciclo {cd} al {ch}, agrupado cada {cada} ciclos · {quienes} ({vista})"


def calcular_tramo(res_, cfg) -> dict:
    modo, sems, por_sem, desde, hasta, frec, cd, ch, cada = cfg
    kw = (dict(desde=desde, hasta=hasta, frecuencia_min=frec) if modo == "horas"
          else dict(ciclo_desde=cd, ciclo_hasta=ch, cada_ciclos=cada))
    t, ind = explorar(res_.ciclos, modo, list(sems), por_semaforo=por_sem, **kw)
    return {"descripcion": describir_tramo(cfg), "tabla": t, "ind": ind, "por_semaforo": por_sem}


@st.cache_data(show_spinner="Preparando Excel y PDF…", max_entries=6)
def archivos(inicio, fin, repeticiones, semilla, factor, horas_bloque, ciclos_bloque, tramo_cfg):
    p = armar(inicio, fin, repeticiones, semilla, factor, horas_bloque, ciclos_bloque)
    tramo = calcular_tramo(correr(inicio, fin, repeticiones, semilla, factor), tramo_cfg)
    return excel_paquete(p, tramo), pdf_paquete(p, tramo)


args = (inicio, fin, repeticiones, semilla, factor)
res = correr(*args)
pq = armar(*args, horas_bloque, ciclos_bloque)
# Tramo del explorador que va en el Excel y el PDF (por defecto: todo el periodo, cada 2 h, los 4 juntos)
tramo_defecto = ("horas", tuple(SEMAFOROS), False, inicio, fin, 120, 1, 10, 10)
_guardado = ss.get("tramo_export")
tramo_cfg = _guardado[1] if _guardado and _guardado[0] == args else tramo_defecto
xlsx, pdf = archivos(*args, horas_bloque, ciclos_bloque, tramo_cfg)
T, K, G = pq.tablas, pq.kpis, pq.graficos
nombre_bh = f"Bloques de {horas_bloque} h"
nombre_bc = f"Bloques de {ciclos_bloque} ciclos"
archivo = f"simulacion_cruce_{inicio:%Y%m%d_%H%M}_{fin:%Y%m%d_%H%M}"

st.markdown(hero("Simulador del cruce vial · vía Mesa–Girardot",
                 "Carrera 10 con Av. Ciudad de las Acacias, Girardot · Curso de Simulación · Universidad Piloto de Colombia",
                 [("📅", f"{inicio:%d/%m/%Y %H:%M} → {fin:%d/%m/%Y %H:%M}"), ("🔁 Ciclos", mil(K["Ciclos"])),
                  ("🎲 Números", mil(K["Números pseudoaleatorios"])), ("♻️ Repeticiones", str(repeticiones)),
                  ("🌱 Semilla", str(semilla)), ("🚗 Demanda", f"×{factor:g}"),
                  ("⏰ Pico", texto_horas_pico())]), unsafe_allow_html=True)


def descargas():
    """Los dos únicos botones de descarga de la app: el reporte completo en Excel y en PDF."""
    c1, c2 = st.columns(2)
    c1.download_button("📗 Descargar Excel", xlsx, f"{archivo}.xlsx", key="desc_excel", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True,
                       help="Todas las hojas: resumen, conclusiones, bloques, por hora, por ciclo, mapa de calor, "
                            "capacidad, validación, números pseudoaleatorios y datos de campo.")
    c2.download_button("📕 Descargar PDF", pdf, f"{archivo}.pdf", key="desc_pdf", type="primary",
                       mime="application/pdf", use_container_width=True,
                       help="El mismo reporte en PDF, con gráficos y tablas, listo para imprimir o entregar.")
    st.caption(f"📎 Los dos archivos traen el resumen ejecutivo, todos los reportes y el tramo del explorador: "
               f"{describir_tramo(tramo_cfg)}. Puede cambiarlo en 📑 Reportes → Explorador.")


def grafico_valle_pico():
    sp = T["Semáforo y periodo"]
    fig = px.bar(sp, x="Semáforo", y="Prom. por hora", color="Periodo", barmode="group",
                 category_orders={"Periodo": ["Valle", "Pico"]},
                 color_discrete_map={"Valle": VALLE, "Pico": PICO}, text_auto=".0f",
                 labels={"Prom. por hora": "Vehículos por hora"}, title="Vehículos por hora: valle vs pico")
    fig.update_layout(legend_title_text="")
    st.plotly_chart(fig, use_container_width=True)


def grafico_horas(clave):
    hr = G["horas"]
    fig = px.line(hr, x="hora", y=SEMAFOROS, markers=len(hr) < 80,
                  labels={"hora": "Hora", "value": "Vehículos por hora", "variable": "Semáforo"},
                  title="Vehículos que pasan por hora")
    fig.update_layout(legend_title_text="")
    for x0, x1 in franjas_pico(inicio, fin):
        fig.add_vrect(x0=x0, x1=x1, fillcolor=PICO, opacity=0.13, line_width=0)
    st.plotly_chart(fig, use_container_width=True, key=f"horas_{clave}")


@st.fragment
def explorador():
    """Elegir de qué hora a qué hora (o de qué ciclo a qué ciclo) y cada cuánto agrupar. Solo se recalcula esta
    sección, así que responde al instante."""
    st.markdown(seccion("🔎", "Explorador: elija el tramo y la frecuencia",
                        "Escoja de qué hora a qué hora (o de qué ciclo a qué ciclo) quiere ver los datos y cada cuánto "
                        "agruparlos: 0–2, 2–4, 4–6… o cada N ciclos. Usa la simulación que ya está corrida, sin volver a "
                        "simular. Las cifras son el promedio de las repeticiones."), unsafe_allow_html=True)
    cic = res.ciclos
    t_min, t_max = cic["inicio"].min().to_pydatetime(), fin
    with st.container(border=True):
        c0, c1, c2 = st.columns([1.1, 1.6, 1.3])
        modo = c0.radio("Ver por", ["Horas", "Ciclos"], horizontal=True, key="exp_modo")
        sems = c1.multiselect("Semáforos", SEMAFOROS, default=SEMAFOROS, key="exp_sems",
                              format_func=lambda x: f"{x} · {semaforos[x].ubicacion}")
        vista = c2.radio("Mostrar", ["Los 4 juntos", "Cada semáforo"], horizontal=True, key="exp_vista")
        if modo == "Horas":
            c1, c2, c3, c4, c5 = st.columns([1, .8, 1, .8, 1])
            d_ini = c1.date_input("Desde el día", inicio.date(), min_value=inicio.date(), max_value=fin.date(),
                                  format="DD/MM/YYYY", key="exp_dini")
            h_ini_ = c2.time_input("hora", inicio.time(), step=1800, key="exp_hini")
            d_fin = c3.date_input("Hasta el día", fin.date(), min_value=inicio.date(), max_value=fin.date(),
                                  format="DD/MM/YYYY", key="exp_dfin")
            h_fin_ = c4.time_input("hora ", fin.time(), step=1800, key="exp_hfin")
            frec = c5.selectbox("Agrupar cada", list(FRECUENCIAS_HORA), index=2, key="exp_frec")
            desde = max(datetime.combine(d_ini, h_ini_), inicio)
            hasta = min(datetime.combine(d_fin, h_fin_), fin)
            if hasta <= desde:
                st.warning("La hora final debe ser posterior a la inicial (y dentro del periodo simulado).")
                return
            kw = dict(desde=desde, hasta=hasta, frecuencia_min=FRECUENCIAS_HORA[frec])
            cfg = ("horas", tuple(sems), vista == "Cada semáforo", desde, hasta, FRECUENCIAS_HORA[frec], 1, 10, 10)
        else:
            max_c = int(cic["ciclo"].max())
            c1, c2, c3 = st.columns(3)
            cd = c1.number_input("Desde el ciclo", 1, max_c, 1, key="exp_cd")
            ch = c2.number_input("Hasta el ciclo", 1, max_c, min(max_c, 100), key="exp_ch")
            cada = c3.number_input("Agrupar cada (ciclos)", 1, max_c, 10, key="exp_cada")
            if ch < cd:
                st.warning("El ciclo final debe ser mayor o igual al inicial.")
                return
            kw = dict(ciclo_desde=int(cd), ciclo_hasta=int(ch), cada_ciclos=int(cada))
            cfg = ("ciclos", tuple(sems), vista == "Cada semáforo", inicio, fin, 120, int(cd), int(ch), int(cada))
    if not sems:
        st.info("Escoja al menos un semáforo.")
        return
    por_sem = vista == "Cada semáforo"
    c1, c2 = st.columns([1, 2.2], vertical_alignment="center")
    if cfg == tramo_cfg:
        c1.button("✅ Este tramo ya va en el Excel y el PDF", disabled=True, use_container_width=True, key="exp_ya")
    elif c1.button("📎 Usar este tramo en el Excel y el PDF", type="primary", use_container_width=True, key="exp_usar"):
        ss["tramo_export"] = (args, cfg)
        st.rerun(scope="app")
    c2.caption("Al pulsarlo, los botones de descarga de arriba preparan el Excel y el PDF con una hoja y una página "
               "de este tramo, además de todo lo demás.")
    t, ind = explorar(cic, "horas" if modo == "Horas" else "ciclos", sems, por_semaforo=por_sem, **kw)
    if t.empty:
        st.info("No hay ciclos en ese tramo.")
        return
    tramo = (f"{kw['desde']:%d/%m %H:%M} → {kw['hasta']:%d/%m %H:%M}" if modo == "Horas"
             else f"ciclos {kw['ciclo_desde']} a {kw['ciclo_hasta']} ({ind['inicio']:%d/%m %H:%M} → {ind['fin']:%d/%m %H:%M})")
    tarjetas = [
        ("Vehículos que pasan", mil(ind["pasan"]), tramo, "#0f2a44"),
        ("En hora valle", mil(ind["valle"]), f"{mil(100 * ind['valle'] / ind['pasan'], 1)} %" if ind["pasan"] else "", VALLE),
        ("En hora pico", mil(ind["pico"]), f"{mil(100 * ind['pico'] / ind['pasan'], 1)} %" if ind["pasan"] else "", PICO),
        ("Quedan en cola", mil(ind["cola_prom"], 1) + " veh", f"promedio por ciclo · máx. {ind['cola_max']}", "#64748b"),
    ]
    if modo == "Horas":
        tarjetas[3:3] = [("Promedio por hora", mil(ind["veh_h"]), f"más alto: {ind['intervalo_max']}", "#1f6f8b")]
    st.markdown(kpis(tarjetas), unsafe_allow_html=True)

    eje = "Intervalo"
    if por_sem:
        fig = px.bar(t, x=eje, y="Pasan (veh)", color="Semáforo", barmode="group",
                     labels={"Pasan (veh)": "Vehículos que pasan"})
    else:
        fig = go.Figure()
        fig.add_bar(name="En hora valle", x=t[eje], y=t["Pasan en valle"], marker_color=VALLE)
        fig.add_bar(name="En hora pico", x=t[eje], y=t["Pasan en pico"], marker_color=PICO)
        fig.update_layout(barmode="stack", yaxis_title="Vehículos que pasan")
    fig.update_layout(height=360, margin=dict(t=30), xaxis_title="", legend_title_text="")
    st.plotly_chart(fig, use_container_width=True, key="exp_graf")
    tabla(t.drop(columns=[c for c in ("Desde",) if c in t.columns]), alto=min(460, 40 + 35 * len(t)))
    if modo == "Horas":
        st.caption(f"Intervalo con más vehículos: {ind['intervalo_max']} · con menos: {ind['intervalo_min']}. "
                   "Los intervalos se cuentan desde la medianoche; si el tramo empieza a mitad de uno, ese intervalo "
                   "queda incompleto. La cola máxima es de la repetición 1. Estos datos están también en el Excel y el "
                   "PDF por bloques de horas y de ciclos.")


descargas()

# --- Panel para llegar al 1 % de error ------------------------------------------------------------
_prec = T["Precisión"]
_err_max = float(np.nanmax(_prec["Error relativo (%)"])) if _prec["Error relativo (%)"].notna().any() else float("nan")
_rep_nec = int(np.nanmax(_prec["Repeticiones para error ≤ 1 %"])) if _prec["Repeticiones para error ≤ 1 %"].notna().any() else 2
_cumple_todo = bool((_prec["¿Cumple ≤ 1 %?"] == "Sí").all())
# El error relativo baja como 1/√(ciclos): para pasar de e % a 1 % hacen falta (e/1)² veces los ciclos actuales
_ciclos_nec = int(min(MAX_CICLOS_TOTALES // max(1, repeticiones),
                      math.ceil(K["Ciclos"] * (max(_err_max, 1.0) / 0.95) ** 2))) if _err_max == _err_max else K["Ciclos"]


def _ajustar_repeticiones():
    """Sube las repeticiones con R = (Z·s ÷ (0,01·x̄))² y comprueba simulando, porque s cambia al repetir más."""
    from simulador.paquete import precision
    r_ = int(min(max(_rep_nec, repeticiones), 200))
    for _ in range(6):
        if ciclos_estimados(semaforos, EscenarioPrediccion(inicio, fin, r_, semilla, factor)) > MAX_CICLOS_TOTALES:
            break
        tabla_p, _ = precision(correr(inicio, fin, r_, semilla, factor))
        if (tabla_p["¿Cumple ≤ 1 %?"] == "Sí").all() or r_ >= 200:
            break
        r_ = int(min(200, max(r_ + 2, np.nanmax(tabla_p["Repeticiones para error ≤ 1 %"]) * 1.1)))
    st.session_state.repeticiones = r_
    _desde_periodo()


def _ajustar_ciclos():
    """Busca los ciclos necesarios simulando: estima con (error ÷ 1 %)² y comprueba hasta que todo cumpla."""
    from simulador.paquete import precision
    c = int(_ciclos_nec)
    for _ in range(6):
        fin_c = inicio + timedelta(seconds=segundos_para(c))
        esc_c = EscenarioPrediccion(inicio, fin_c, repeticiones, semilla, factor)
        if ciclos_estimados(semaforos, esc_c) > MAX_CICLOS_TOTALES:
            break
        tabla_p, _ = precision(correr(inicio, fin_c, repeticiones, semilla, factor))
        e = float(np.nanmax(tabla_p["Error relativo (%)"]))
        if e <= 1:
            break
        c = int(math.ceil(c * (e / 0.97) ** 2))
    st.session_state.ciclos = int(c)
    _desde_ciclos()


def panel_precision(clave):
    if _cumple_todo:
        st.success(f"✅ Todos los resultados tienen error ≤ 1 % con confianza del 99 % "
                   f"(el mayor es {mil(_err_max, 2)} %). No hace falta ajustar nada.")
        return
    with st.expander(f"⚠️ Hay resultados con más de 1 % de error (el mayor es {mil(_err_max, 2)} %). "
                     "Ver cómo ajustarlo", expanded=(clave == "global")):
        st.markdown(
            "Con los datos que puso, algunos resultados quedan por encima del **1 % de error** (confianza 99 %). "
            "Hay dos formas de corregirlo; elija la que prefiera:")
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            st.markdown(f"**Opción 1 · Más repeticiones** (mismo periodo)  \n"
                        f"Repetir la simulación unas **{min(_rep_nec, 200)}** veces o más en lugar de {repeticiones}; "
                        "el programa simula y comprueba hasta que todo quede ≤ 1 %.  \n"
                        "`R = (2,576 × s ÷ (0,01 × promedio))²`")
            st.button("🎯 Ajustar las repeticiones", on_click=_ajustar_repeticiones,
                      key=f"rep_{clave}", type="primary", use_container_width=True)
            if _rep_nec > 200:
                st.caption("Se necesitan más de 200; se ajusta al máximo. Combínelo con la opción 2.")
        with c2, st.container(border=True):
            st.markdown(f"**Opción 2 · Más ciclos** (mismas repeticiones)  \n"
                        f"Alargar el periodo a unos **{mil(_ciclos_nec)} ciclos** o más (hoy {mil(K['Ciclos'])}); el programa "
                        "simula y comprueba hasta encontrar los necesarios, y la hora final se corre sola.  \n"
                        "`ciclos = ciclos actuales × (error mayor ÷ 1 %)²`")
            st.button("🔁 Ajustar los ciclos (y la hora final)", on_click=_ajustar_ciclos,
                      key=f"cic_{clave}", use_container_width=True)
        st.caption(f"La semilla actual es {semilla}. Cambiar la semilla mueve un poco los resultados, pero no reduce el "
                   "error de forma confiable: lo que lo reduce son más repeticiones o más ciclos.")


panel_precision("global")

tabs = st.tabs(["📊 Resumen", "📑 Reportes", "🧪 Análisis y casos", "🚗 Simulación en vivo", "🚦 Capacidad",
                "✅ Validación", "📋 Datos de campo", "🎲 Generador", "📘 Cómo funciona"])

# ---------------------------------------------------------------------------
# 1. Resumen
# ---------------------------------------------------------------------------
with tabs[0]:
    st.markdown(seccion("🧭", "Conclusiones de la simulación", "Calculadas solas con los resultados: sirven para decidir "
                        "a qué horas y por qué entrada hay más o menos tráfico."), unsafe_allow_html=True)
    st.markdown(nota("💡 " + pq.notas["Conclusiones"]), unsafe_allow_html=True)
    conc = T["Conclusiones"]
    cols_c = st.columns(4)
    for i, (_, fila) in enumerate(conc.iterrows()):
        with cols_c[i % 4]:
            st.markdown(f'<div class="kpi" style="--c:{["#C73E1D", VERDE, PICO, "#C73E1D", VERDE, "#1f6f8b", "#7c3aed", "#64748b"][i % 8]};'
                        f'margin-bottom:12px"><div class="et">{fila["Indicador"]}</div>'
                        f'<div class="va" style="font-size:1.05rem">{fila["Resultado"]}</div>'
                        f'<div class="su">{fila["Detalle"]}</div></div>', unsafe_allow_html=True)
    st.markdown(seccion("📊", "Indicadores principales"), unsafe_allow_html=True)
    st.markdown(kpis([
        ("Vehículos que pasan", mil(K["Vehículos que pasan"]), f"± {mil(K['Margen ± IC 99 %'])} (IC 99 %)", "#0f2a44"),
        ("Promedio por hora", mil(K["Promedio por hora"]), f"en {mil(K['Horas simuladas'], 1)} h simuladas", "#1f6f8b"),
        ("Ciclos simulados", mil(K["Ciclos"]), "verde → rojo, 4 semáforos", VERDE),
        ("Números pseudoaleatorios", mil(K["Números pseudoaleatorios"]), f"{repeticiones} repeticiones · semilla {semilla}", "#7c3aed"),
        ("Pasan en hora valle", mil(K.get("Pasan en hora valle", 0)), f"{mil(K.get('Promedio por hora valle', 0))} veh/h", VALLE),
        ("Pasan en hora pico", mil(K.get("Pasan en hora pico", 0)), f"{mil(K.get('Promedio por hora pico', 0))} veh/h", PICO),
        ("Semáforo con más flujo", T["Semáforos"].sort_values("Vehículos que pasan").iloc[-1]["Semáforo"] + " · "
         + T["Semáforos"].sort_values("Vehículos que pasan").iloc[-1]["Ubicación"],
         f"{mil(T['Semáforos']['% del total'].max(), 1)} % del total", "#C73E1D"),
        ("Cola promedio", mil(T["Semáforos"]["Cola prom. (veh)"].mean(), 1) + " veh", "por semáforo y ciclo", "#64748b"),
    ]), unsafe_allow_html=True)
    if "Promedio por hora valle" in K and "Promedio por hora pico" in K:
        v, p = K["Promedio por hora valle"], K["Promedio por hora pico"]
        st.markdown(nota(f"📈 En <b>hora pico</b> pasan en promedio <b>{mil(p)} vehículos por hora</b>, frente a "
                         f"<b>{mil(v)}</b> en hora valle: un <b>{mil(100 * (p / v - 1), 1)} % más</b>."), unsafe_allow_html=True)
    prec = T["Precisión"]
    rep_necesarias = int(np.nanmax(prec["Repeticiones para error ≤ 1 %"])) if prec["Repeticiones para error ≤ 1 %"].notna().any() else 2
    err_tot = K.get("Error relativo IC 99 % (%)", float("nan"))
    cumple = bool((prec["¿Cumple ≤ 1 %?"] == "Sí").all())
    st.markdown(seccion("🎯", "Precisión de la predicción (confianza 99 %, error objetivo ≤ 1 %)", pq.notas["Precisión"]),
                unsafe_allow_html=True)
    st.markdown(kpis([
        ("Nivel de confianza", "99 %", "Z = 2,576", "#0f2a44"),
        ("Error relativo del total", (mil(err_tot, 2) + " %") if err_tot == err_tot else "—",
         "objetivo ≤ 1 %", VERDE if err_tot == err_tot and err_tot <= 1 else PICO),
        ("Resultados que cumplen ≤ 1 %", f"{int((prec['¿Cumple ≤ 1 %?'] == 'Sí').sum())} de {len(prec)}",
         "total, valle, pico y cada semáforo", VERDE if cumple else PICO),
        ("Repeticiones para que todo cumpla", mil(min(rep_necesarias, 200)), f"hoy: {repeticiones}", "#7c3aed"),
    ]), unsafe_allow_html=True)
    panel_precision("resumen")
    c1, c2 = st.columns([1.2, 1])
    with c1:
        tabla(prec)
    with c2, st.container(border=True):
        cv = G["convergencia"]
        figc = go.Figure()
        figc.add_scatter(x=cv["Repeticiones"], y=cv["Límite superior IC 99 %"], line=dict(width=0), showlegend=False,
                         hoverinfo="skip")
        figc.add_scatter(x=cv["Repeticiones"], y=cv["Límite inferior IC 99 %"], fill="tonexty", line=dict(width=0),
                         fillcolor="rgba(31,111,139,.18)", name="IC 99 %")
        figc.add_scatter(x=cv["Repeticiones"], y=cv["Promedio acumulado"], mode="lines+markers", name="Promedio acumulado",
                         line=dict(color="#0f2a44"))
        figc.add_scatter(x=cv["Repeticiones"], y=cv["Total"], mode="markers", name="Cada repetición",
                         marker=dict(color="#9aa5b1", size=6))
        figc.update_layout(title="Convergencia del total al aumentar las repeticiones", height=330,
                           xaxis_title="Repeticiones", yaxis_title="Vehículos")
        st.plotly_chart(figc, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        grafico_valle_pico()
    with c2, st.container(border=True):
        grafico_horas("resumen")
    st.markdown(seccion("🚦", "Resultados por semáforo", ''), unsafe_allow_html=True)
    tabla(T["Semáforos"])
    st.markdown(seccion("🌗", "Cada semáforo en hora valle y en hora pico", ''), unsafe_allow_html=True)
    tabla(T["Semáforo y periodo"])
    st.markdown(seccion("⚖️", "Hora valle frente a hora pico", 'Todo el periodo simulado.'), unsafe_allow_html=True)
    tabla(T["Valle vs pico"])
    with st.expander("⚙️ Parámetros de esta simulación"):
        tabla(T["Parámetros"])

# ---------------------------------------------------------------------------
# 2. Reportes (todo junto)
# ---------------------------------------------------------------------------
with tabs[1]:
    explorador()
    st.markdown(nota("📑 Todos los reportes incluyen <b>hora valle y hora pico</b>. El tamaño de los bloques se "
                     "cambia en la barra lateral. Los valores son el promedio de las repeticiones."), unsafe_allow_html=True)
    st.markdown(seccion("🕑", f"1 · Por bloques de {horas_bloque} h", pq.notas[nombre_bh]), unsafe_allow_html=True)
    b = G["bloques"]
    fig = go.Figure()
    fig.add_bar(name="En hora valle", x=b["bloque"], y=b["en_valle"], marker_color=VALLE)
    fig.add_bar(name="En hora pico", x=b["bloque"], y=b["en_pico"], marker_color=PICO)
    fig.update_layout(barmode="stack", yaxis_title="Vehículos", height=380, margin=dict(t=30))
    st.plotly_chart(fig, use_container_width=True)
    tabla(T[nombre_bh])

    st.markdown(seccion("⏱️", "2 · Por hora", pq.notas["Por hora"]), unsafe_allow_html=True)
    grafico_horas("reportes")
    tabla(T["Por hora"], alto=420)

    st.markdown(seccion("🔁", f"3 · Por bloques de {ciclos_bloque} ciclos", pq.notas[nombre_bc]), unsafe_allow_html=True)
    bc = G["bloques_ciclos"]
    fig = px.line(bc, x="desde", y="pasan", color="semaforo", markers=len(bc) < 200,
                  labels={"desde": "Inicio del bloque", "pasan": f"Vehículos en {ciclos_bloque} ciclos",
                          "semaforo": "Semáforo"})
    st.plotly_chart(fig, use_container_width=True)
    tabla(T[nombre_bc], alto=420)

    st.markdown(seccion("🔥", "Mapa de calor: vehículos por día y hora", pq.notas["Mapa de calor"]), unsafe_allow_html=True)
    mc = T["Mapa de calor (día × hora)"]
    figm = px.imshow(mc, aspect="auto", color_continuous_scale="YlOrRd", labels=dict(x="Hora del día", y="Día", color="Vehículos"),
                     text_auto=".0f" if mc.size <= 24 * 8 else False)
    figm.update_layout(height=max(260, 70 + 34 * len(mc)))
    st.plotly_chart(figm, use_container_width=True)

    st.markdown(seccion("📦", "Diagramas de caja: vehículos que pasan por ciclo", pq.notas["Cajas"]), unsafe_allow_html=True)
    cic = G["ciclos"]
    figb = px.box(cic, x="semaforo", y="pasan", color="periodo", category_orders={"periodo": ["Valle", "Pico"]},
                  color_discrete_map={"Valle": VALLE, "Pico": PICO},
                  labels={"semaforo": "Semáforo", "pasan": "Vehículos que pasan por ciclo", "periodo": ""})
    figb.update_layout(height=380)
    st.plotly_chart(figb, use_container_width=True)

    st.markdown(seccion("🚥", "Colas al final de cada verde", pq.notas["Colas"]), unsafe_allow_html=True)
    c1, c2 = st.columns([1.1, 1])
    with c1, st.container(border=True):
        figh = px.histogram(cic, x="quedan", color="semaforo", barmode="group", nbins=int(max(5, cic["quedan"].max() + 1)),
                            labels={"quedan": "Carros que quedan en cola", "semaforo": "Semáforo", "count": "Ciclos"})
        figh.update_layout(height=340, yaxis_title="Ciclos", title="Histograma de colas")
        st.plotly_chart(figh, use_container_width=True)
    with c2:
        tabla(T["Colas"], alto=340)

    st.markdown(seccion("🌗", "4 · Cada semáforo en hora valle y en hora pico"), unsafe_allow_html=True)
    tabla(T["Semáforo y periodo"])
    st.markdown(seccion("⚖️", "5 · Hora valle frente a hora pico", ), unsafe_allow_html=True)
    tabla(T["Valle vs pico"])

    st.markdown(seccion("🎲", "6 · Números pseudoaleatorios: qué significa cada uno", pq.notas["Números pseudoaleatorios"]), unsafe_allow_html=True)
    nums = T["Números pseudoaleatorios"]
    tabla(nums.head(20000), alto=460)
    total_num = K["Números pseudoaleatorios"]
    st.caption(f"Se muestran {mil(min(len(nums), 20000))} números de la repetición 1. En total la simulación usó "
               f"{mil(total_num)} ({repeticiones} repeticiones). El Excel trae hasta {mil(len(nums))}.")

    st.markdown(seccion("🔍", "7 · Por ciclo (los 4 semáforos)", "Repetición 1 (U1, U2, llegadas, cola…) y el promedio de cada ciclo entre todas las repeticiones."), unsafe_allow_html=True)
    pc = T["Por ciclo"]
    tabla(pc.head(20000), alto=420)
    if len(pc) > 20000:
        st.caption(f"Se muestran 20.000 de {mil(len(pc))} ciclos. El Excel tiene todos.")

# ---------------------------------------------------------------------------
# 2b. Análisis: esquema y casos de prueba
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Corriendo los casos de prueba…", max_entries=4)
def casos_prueba(inicio, fin, repeticiones, semilla, factor):
    return correr_casos(semaforos, EscenarioPrediccion(inicio, fin, repeticiones, semilla, factor),
                        correr(inicio, fin, repeticiones, semilla, factor))


with tabs[2]:
    st.markdown(seccion("🗺️", "Esquema: cómo viaja cada dato por el simulador",
                        "De arriba abajo: lo que usted escribe en la barra lateral, cómo se convierte en números "
                        "pseudoaleatorios, cómo el modelo los usa ciclo a ciclo y en qué reportes termina."), unsafe_allow_html=True)
    st.graphviz_chart("""
digraph G {
  rankdir=TB; bgcolor="transparent"; nodesep=0.3; ranksep=0.35; newrank=true;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, color="#cbd5e1", fillcolor="#ffffff"];
  edge [color="#64748b", fontname="Helvetica", fontsize=8.5];
  subgraph cluster_e { label="1 · Lo que usted define"; fontname="Helvetica-Bold"; fontsize=10; color="#1f9d74"; style="rounded";
    per [label="Periodo\\n(inicio y fin)"]; cic [label="Ciclos"]; num [label="Números\\npseudoaleatorios"];
    rep [label="Repeticiones (R)"]; sem [label="Semilla"]; dem [label="Demanda (×)"]; }
  subgraph cluster_g { label="2 · Generador congruencial"; fontname="Helvetica-Bold"; fontsize=10; color="#7c3aed"; style="rounded";
    lcg [label="Xₙ₊₁ = 16.807·Xₙ mod (2³¹−1)\\nU = X ÷ (2³¹−1)", fillcolor="#f5f3ff"]; }
  subgraph cluster_d { label="Datos de campo (Excel)"; fontname="Helvetica-Bold"; fontsize=10; color="#5B8DB8"; style="rounded";
    tab [label="Tablas de intervalos\\nllegadas y quedan\\nvalle / pico por semáforo", fillcolor="#eef4fb"];
    hor [label="Horas pico\\n12:00–13:00 y 17:00–18:30", fillcolor="#fdf0e7"]; }
  subgraph cluster_m { label="3 · Modelo, cada ciclo y semáforo"; fontname="Helvetica-Bold"; fontsize=10; color="#0f2a44"; style="rounded";
    lle [label="U1 → llegadas (× demanda)"]; esp [label="en espera = cola anterior + llegadas"];
    rez [label="U2 → rezagados"]; pas [label="pasan = mín(en espera − rezagados, capacidad)"];
    que [label="quedan = en espera − pasan\\n(→ cola del siguiente ciclo)"]; }
  subgraph cluster_s { label="4 · Resultados"; fontname="Helvetica-Bold"; fontsize=10; color="#E07B39"; style="rounded";
    prom [label="Promedio de R repeticiones\\n± IC 99 % y error relativo", fillcolor="#fff7ed"];
    rpt [label="Reportes: bloques de horas y ciclos,\\npor hora, mapa de calor, explorador"];
    arc [label="Excel y PDF"]; viv [label="Simulación en vivo\\n(mapa y 3D, % de giros)"]; }
  per -> cic [label="÷ duración del ciclo", dir=both]; cic -> num [label="× 2 × R", dir=both]; rep -> num;
  sem -> lcg; num -> lcg [label="cuántos U"]; lcg -> lle [label="U1"]; lcg -> rez [label="U2"];
  tab -> lle; tab -> rez; hor -> lle [label="valle o pico\\nsegún la hora"]; dem -> lle;
  lle -> esp -> pas; rez -> pas; pas -> que; que -> esp [style=dashed, label="siguiente ciclo"];
  pas -> prom; que -> prom; rep -> prom; prom -> rpt -> arc; pas -> viv [label="repetición 1"];
}
""", use_container_width=True)

    st.markdown(seccion("🧩", "Qué hace cada campo", "Qué es, qué parte de la simulación toca y cómo cambia el resultado."),
                unsafe_allow_html=True)
    cols_f = st.columns(3)
    for i, (_, f) in enumerate(CAMPOS.iterrows()):
        with cols_f[i % 3], st.container(border=True):
            st.markdown(f"**{f['Campo']}**  \n{f['Qué es']}")
            st.markdown(f"<span style='color:#64748b;font-size:.86rem'><b>Afecta:</b> {f['Qué afecta']}<br/>"
                        f"<b>Cómo cambia:</b> {f['Cómo cambia la simulación']}</span>", unsafe_allow_html=True)
            st.code(f["Fórmula"], language=None, wrap_lines=True)

    st.markdown(seccion("🧪", "Casos de prueba sobre su simulación actual",
                        "Cada caso cambia un solo campo y deja todo lo demás igual que su simulación. Así se ve qué "
                        "efecto tiene cada uno. Si cambia la barra lateral, los casos se vuelven a calcular con los nuevos "
                        "datos."), unsafe_allow_html=True)
    total_ciclos_rep = K["Ciclos"] * repeticiones
    if total_ciclos_rep > 600_000 and not ss.get("casos_ok"):
        st.info(f"Su simulación es grande ({mil(total_ciclos_rep)} ciclos con repeticiones): los 5 casos pueden tardar "
                "un poco. Pulse el botón para correrlos.")
        if st.button("▶ Correr los casos de prueba", type="primary", key="casos_btn"):
            ss["casos_ok"] = True
            st.rerun()
    else:
        cp = casos_prueba(*args)
        base_v = cp.iloc[0]
        cols = st.columns(3)
        for i, (_, f) in enumerate(cp.iloc[1:].iterrows()):
            delta = f["Δ vehículos vs base (%)"]
            color = "#1f9d74" if abs(delta) < 1 else (PICO if delta > 0 else VALLE)
            with cols[i % 3]:
                st.markdown(
                    f'<div class="kpi" style="--c:{color};margin-bottom:12px"><div class="et">{f["Caso"]} · '
                    f'{f["Campo que cambia"]}</div><div class="va" style="font-size:1.05rem">{f["Cambio"]}</div>'
                    f'<div class="su"><b>{mil(f["Vehículos que pasan"])}</b> vehículos ({"+" if delta >= 0 else ""}'
                    f'{mil(delta, 1)} %) · error {mil(f["Error relativo (%)"], 2)} % (base {mil(base_v["Error relativo (%)"], 2)} %)'
                    f' · cola máx. {f["Cola máx. (veh)"]}<br/>{f["Qué pasó"]}</div></div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            fig = go.Figure()
            fig.add_bar(name="En hora valle", x=cp["Caso"], y=cp["En hora valle"], marker_color=VALLE)
            fig.add_bar(name="En hora pico", x=cp["Caso"], y=cp["En hora pico"], marker_color=PICO)
            fig.update_layout(barmode="stack", title="Vehículos que pasan en cada caso", height=360,
                              yaxis_title="Vehículos", legend_title_text="")
            st.plotly_chart(fig, use_container_width=True, key="casos_veh")
        with c2, st.container(border=True):
            fig = go.Figure()
            fig.add_bar(x=cp["Caso"], y=cp["Error relativo (%)"],
                        marker_color=[VERDE if e <= 1 else PICO for e in cp["Error relativo (%)"]],
                        text=[mil(e, 2) + " %" for e in cp["Error relativo (%)"]], textposition="outside")
            fig.add_hline(y=1, line_dash="dash", line_color="#C73E1D", annotation_text="objetivo 1 %")
            fig.update_layout(title="Error relativo del total (IC 99 %)", height=360, yaxis_title="%", showlegend=False)
            st.plotly_chart(fig, use_container_width=True, key="casos_err")
        tabla(cp)
        st.caption("Bloques de horas, bloques de ciclos, explorador y % de giros no aparecen como casos porque no "
                   "cambian la simulación: solo cambian cómo se muestra (ver la tabla de campos).")

# ---------------------------------------------------------------------------
# 3. Mapa en vivo
# ---------------------------------------------------------------------------
with tabs[3]:
    st.markdown(nota("🚗 Reproducción de la simulación (repetición 1) desde el inicio del periodo, en el <b>mapa "
                     "satelital</b> y en una <b>maqueta 3D</b> sincronizados. Los semáforos se ponen en verde uno tras "
                     "otro (S1 → S2 → S3 → S4). Cada carro que pasa escoge al azar si gira a la <b>izquierda</b> "
                     "(morado), sigue <b>derecho</b> (cian) o gira a la <b>derecha</b> (amarillo); los blancos esperan "
                     "en cola. En la vista 3D se gira la cámara con el mouse y se hace zoom con la rueda."),
                unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1])
    ciclos_anim = c1.slider("Ciclos a reproducir por semáforo", 5, 80, 25)
    p_izq = c2.slider("% gira a la izquierda", 0, 100, 30, step=5)
    p_der = c3.slider("% gira a la derecha", 0, 100 - p_izq, min(30, 100 - p_izq), step=5)
    c4.metric("% sigue derecho", f"{100 - p_izq - p_der} %")
    st.caption("Los porcentajes de giro son solo para la animación: no se midieron en campo y no cambian los conteos. "
               "En la animación los 4 semáforos comparten un ciclo de 134 s con las fases en orden (S1 25 s → S2 30 s → "
               "S3 25 s → S4 35 s) y 4,75 s de todo en rojo entre fases, para que nunca haya dos verdes a la vez y el "
               "cruce quede libre antes del siguiente verde. Los carros que pasan en cada ciclo son los de la simulación.")
    with st.expander("📍 Ajustar la ubicación del cruce y de los semáforos"):
        st.caption("Cruce de la Carrera 10 con la Av. Ciudad de las Acacias (Girardot). Para sacar coordenadas: "
                   "en Google Maps, clic derecho sobre el punto y clic en los números (se copian). "
                   "Dirección = de dónde llegan los carros: 0 = norte, 90 = este, 180 = sur, 270 = oeste.")
        c1, c2 = st.columns(2)
        lat = c1.number_input("Latitud del centro del cruce", value=CENTRO_DEFECTO[0], format="%.7f")
        lon = c2.number_input("Longitud del centro del cruce", value=CENTRO_DEFECTO[1], format="%.7f")
        posiciones = {}
        for s_m in SEMAFOROS:
            d = POSICIONES_DEFECTO[s_m]
            st.markdown(f"**{s_m} · {semaforos[s_m].ubicacion}** — {d['via']}")
            c1, c2, c3 = st.columns(3)
            posiciones[s_m] = {
                "lat": c1.number_input("Latitud", value=d["lat"], format="%.7f", key=f"lat_{s_m}"),
                "lon": c2.number_input("Longitud", value=d["lon"], format="%.7f", key=f"lon_{s_m}"),
                "rumbo": c3.number_input("Dirección (°)", 0, 359, d["rumbo"], step=1, key=f"rumbo_{s_m}"),
            }
    anim = res.ciclos.groupby("semaforo").head(ciclos_anim)
    components.html(html_visor(anim, res.info_semaforos, (lat, lon), posiciones,
                               inicio.strftime("%Y-%m-%dT%H:%M:%S"), semilla,
                               {"izq": p_izq, "recto": 100 - p_izq - p_der, "der": p_der}), height=770)

    st.markdown(seccion("🛣️", "Vista de la calle (Google Maps)", "Abre en otra pestaña Google Street View desde cada "
                        "semáforo, mirando como el conductor que llega al cruce, o su ubicación en Google Maps."),
                unsafe_allow_html=True)
    cols = st.columns(4)
    for col, s_m in zip(cols, SEMAFOROS):
        enl = enlaces_google(posiciones[s_m], (lat, lon))
        with col:
            st.markdown(f"**{s_m} · {semaforos[s_m].ubicacion}**")
            st.caption(POSICIONES_DEFECTO[s_m]["via"])
            st.link_button("👁 Street View", enl["street_view"], use_container_width=True)
            st.link_button("📍 Google Maps", enl["mapa"], use_container_width=True)

# ---------------------------------------------------------------------------
# 4. Capacidad (valle y pico)
# ---------------------------------------------------------------------------
with tabs[4]:
    st.markdown("**¿Cuántos vehículos puede atender el cruce sin problema?** Se repite la simulación aumentando "
                "la demanda poco a poco, en hora valle y en hora pico, y se mira en qué punto la cola deja de "
                "despejarse.")
    st.caption(pq.notas["Capacidad"])
    cap = T["Capacidad"]
    tabla(cap)
    c1, c2 = st.columns(2)
    for col, per in zip((c1, c2), ("Valle", "Pico")):
        d = cap[cap["Periodo"] == per]
        col.markdown(kpis([(f"Hora {per.lower()}: capacidad del cruce", f"{mil(d['Capacidad (veh/h)'].sum())} veh/h",
                            f"hoy llegan {mil(d['Demanda (veh/h)'].sum())} veh/h "
                            f"({mil(100 * d['Demanda (veh/h)'].sum() / d['Capacidad (veh/h)'].sum())} % de uso)",
                            VALLE if per == "Valle" else PICO)]).replace("repeat(4", "repeat(1"), unsafe_allow_html=True)
    bar = G["barrido"]
    c1, c2 = st.columns(2)
    for col, per in zip((c1, c2), ("Valle", "Pico")):
        fig = px.line(bar[bar["periodo"] == per], x="factor", y="cola_prom", color="semaforo", markers=True,
                      title=f"Hora {per.lower()}",
                      labels={"factor": "Demanda (× la observada)", "cola_prom": "Cola promedio (veh)",
                              "semaforo": "Semáforo"})
        fig.add_vline(x=1, line_dash="dash", annotation_text="demanda actual")
        col.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# 5. Validación
# ---------------------------------------------------------------------------
with tabs[5]:
    st.markdown("Con la demanda observada, el simulador debe dar resultados parecidos a la toma de datos. "
                "Se usa el error del método de los 11 pasos: **error = |simulado − observado| ÷ observado × 100**.")
    val = T["Validación"]
    tabla(val)
    fig = go.Figure()
    etiquetas = val["Semáforo"] + " " + val["Periodo"]
    fig.add_bar(name="Observado", x=etiquetas, y=val["Pasan observado"])
    fig.add_bar(name="Simulado", x=etiquetas, y=val["Pasan simulado"])
    fig.update_layout(barmode="group", yaxis_title="Vehículos que pasan por ciclo")
    st.plotly_chart(fig, use_container_width=True)
    st.markdown(seccion("🧪", "Prueba de ajuste de las llegadas (chi-cuadrado, 99 %)", pq.notas["Prueba de ajuste de llegadas"]),
                unsafe_allow_html=True)
    tabla(T["Prueba de ajuste de llegadas"])

# ---------------------------------------------------------------------------
# 6. Datos de campo
# ---------------------------------------------------------------------------
with tabs[6]:
    st.markdown(f"Registro manual por ciclo (verde → rojo): **{len(campo)} ciclos** en los cuatro semáforos.")
    tabla(T["Datos de campo (resumen)"])
    st.markdown(seccion("📈", "¿En qué franjas hay más flujo? (datos de campo)"), unsafe_allow_html=True)
    st.caption("Vehículos por hora = carros que pasan por ciclo × 3600 ÷ duración del ciclo (s). "
               "'Cruce completo' suma los 4 semáforos y solo aparece si se midieron los 4 en esa franja.")
    tabla(T["Flujo por franja medida"])
    st.markdown(seccion("🎯", "Tablas de codificación por intervalos de las llegadas (valle y pico)"), unsafe_allow_html=True)
    st.caption("Si U cae en [desde, hasta), llegan 'valor' vehículos en ese ciclo.")
    for s_t in SEMAFOROS:
        st.markdown(f"**{s_t} · {semaforos[s_t].ubicacion}**")
        c1, c2 = st.columns(2)
        for col, per in zip((c1, c2), ("Valle", "Pico")):
            with col:
                st.caption(f"Hora {per.lower()}")
                ti = tabla_intervalos(semaforos[s_t].llegadas[per]).rename(columns={
                    "valor": "Llegadas", "frecuencia": "Frecuencia", "probabilidad": "Probabilidad",
                    "acumulada": "Acumulada", "desde": "Desde", "hasta": "Hasta"})
                st.dataframe(ti.round(4), use_container_width=True, hide_index=True, height=220)
    with st.expander(f"Ver los {len(campo)} registros"):
        tabla(T["Datos de campo"])

# ---------------------------------------------------------------------------
# 7. Generador y pruebas
# ---------------------------------------------------------------------------
with tabs[7]:
    st.markdown("Generador congruencial: **Xₙ₊₁ = 16807·Xₙ mod 2147483647** y **U = X ÷ 2147483647**.  \n"
                "Antes de confiar en la simulación se comprueba que los U sean uniformes con las pruebas del "
                "capítulo 3 de Coss Bu.  \nH₀: los números provienen de una distribución uniforme.")
    n_u = min(res.numeros_usados, 200_000)
    u = GeneradorCongruencial(semilla).lista(n_u)
    filas = []
    for nombre, simb, r in [("Promedios (ec. 3.2)", "|Z₀|", prueba_promedios(u)),
                            ("Frecuencias, 10 subintervalos (ec. 3.3)", "X₀²", prueba_frecuencias(u)),
                            ("Kolmogorov-Smirnov (ec. 3.12)", "Dₙ", prueba_ks(u))]:
        est_v = abs(r["estadistico"]) if simb == "|Z₀|" else r["estadistico"]
        filas.append({"Prueba": nombre, "N": r["N"], "Estadístico": f"{simb} = {est_v:.4f}",
                      "Valor crítico": f"{r['critico']:.4f}",
                      "Decisión": "No se rechaza H₀" if r["no_se_rechaza"] else "Se rechaza H₀"})
    tabla(pd.DataFrame(filas))
    st.caption(f"Se prueban los primeros {mil(n_u)} números de la simulación actual, α = 0.05.")
    st.markdown(seccion("🔢", "Primeros números de la secuencia y qué produjo cada uno", "La tabla completa está en Reportes."), unsafe_allow_html=True)
    tabla(T["Números pseudoaleatorios"].head(20))
    st.plotly_chart(px.histogram(x=u, nbins=10, labels={"x": "U"}, title="Histograma de los U generados"),
                    use_container_width=True)

# ---------------------------------------------------------------------------
# 8. Cómo funciona
# ---------------------------------------------------------------------------
with tabs[8]:
    st.markdown(f"""
**Los 3 parámetros van enlazados en toda simulación.**
- Periodo → ciclos: cada semáforo cumple `ciclos = segundos del periodo ÷ duración de su ciclo` (124, 129, 124 y 134 s).
  Los ciclos totales son la suma de los 4.
- Ciclos → números: cada ciclo usa 2 números (U1 y U2) en cada repetición:
  `números = 2 × ciclos totales × repeticiones`.
- Si se cambian los ciclos o los números, la hora final se ajusta para que todo cuadre.

Toda simulación debe incluir horas valle y horas pico. Los semáforos y sus tiempos son fijos. Cada ciclo de cada
semáforo se ubica en el reloj: si empieza en hora pico ({texto_horas_pico()}) usa los datos de hora pico; si no,
los de hora valle. **Todo se recalcula solo** al cambiar cualquier dato de la barra lateral.

**En cada ciclo y para cada semáforo:**

1. **Llegadas.** Se genera U₁ y se busca su intervalo en la tabla de llegadas de ese periodo
   (pestaña *Datos de campo*). Es la codificación por intervalos del método de los 11 pasos.
   Llegadas de campo: `llegadas = pasan + quedan − quedan del ciclo anterior`.
2. **En espera.** `en espera = cola anterior + llegadas`.
3. **Rezagados.** Se genera U₂ y con la tabla de *Quedan* se sortea cuántos carros llegan con el verde
   terminando y no alcanzan a pasar.
4. **Pasan.** `pasan = mín(en espera − rezagados, capacidad)`. La capacidad es el máximo que se vio pasar
   en un verde de ese semáforo.
5. **Quedan.** `quedan = en espera − pasan`, que pasan a la cola del siguiente ciclo.

**Repeticiones.** Todo se repite R veces con números pseudoaleatorios distintos. El resultado es el promedio
y su margen es el intervalo de confianza del 99 %: `promedio ± 2,576 · desviación estándar ÷ √R`.

**Supuestos.** Total por semáforo (sin separar giros), rojo de 99 s, sin amarillo ni despeje. Las horas que
no se midieron (noche, madrugada, fines de semana) se tratan como hora valle, así que en esas horas la
predicción puede quedar por encima de la realidad.
""")
