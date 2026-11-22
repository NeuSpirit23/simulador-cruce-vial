"""Simulador del cruce vial de 4 semáforos — vía Mesa–Girardot.

Ejecutar:  streamlit run app.py
"""

from datetime import date, datetime, time, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from simulador.datos import PERIODOS, SEMAFOROS, calcular_llegadas, cargar_semaforos, leer_base
from simulador.exportar import _decimales, excel_datos_campo, excel_paquete, pdf_datos_campo, pdf_paquete
from simulador.generador import GeneradorCongruencial
from simulador.mapa import CENTRO_DEFECTO, POSICIONES_DEFECTO, enlaces_google, html_mapa
from simulador.modelo import tabla_intervalos
from simulador.prediccion import (EscenarioPrediccion, MAX_CICLOS_TOTALES, ciclos_estimados,
                                  cubre_valle_y_pico, franjas_pico, predecir,
                                  texto_horas_pico)
from simulador.pruebas import prueba_frecuencias, prueba_ks, prueba_promedios
from simulador.paquete import construir

st.set_page_config(page_title="Simulador cruce vial", page_icon="🚦", layout="wide")


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
st.sidebar.title("🚦 Predicción")
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
sb.markdown("**1. Periodo (fechas y horas)**")
c1, c2 = sb.columns(2)
c1.date_input("Desde el día", key="f_ini", format="DD/MM/YYYY", on_change=_desde_periodo)
c2.time_input("a las", key="h_ini", step=timedelta(minutes=30), on_change=_desde_periodo)
c1, c2 = sb.columns(2)
c1.date_input("Hasta el día", key="f_fin", format="DD/MM/YYYY", on_change=_desde_periodo)
c2.time_input("a las ", key="h_fin", step=timedelta(minutes=30), on_change=_desde_periodo)
sb.markdown("**2. Ciclos** (los 4 semáforos)")
sb.number_input("Ciclos totales", min_value=4, max_value=MAX_CICLOS_TOTALES, step=100, key="ciclos",
                on_change=_desde_ciclos,
                help="Ciclos completos (verde → rojo) que caben en el periodo, sumando los 4 semáforos. "
                     "Si lo cambia, la hora final se ajusta.")
sb.markdown("**3. Números pseudoaleatorios**")
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
sb.caption(f"Periodo de {mil(seg_periodo / 3600, 2)} h → ciclos por semáforo: "
           + ", ".join(f"{s} {mil(por_sem[s])} (÷{DUR_CICLO[s]} s)" for s in SEMAFOROS)
           + f" = **{mil(sum(por_sem.values()))}** ciclos × 2 × {ss.repeticiones} repeticiones = "
             f"**{mil(2 * sum(por_sem.values()) * ss.repeticiones)}** números.")

sb.markdown("**Reportes**")
c1, c2 = sb.columns(2)
horas_bloque = c1.selectbox("Bloques de horas", [1, 2, 3, 4, 6, 8, 12, 24], index=1,
                            format_func=lambda h: f"{h} h")
ciclos_bloque = c2.selectbox("Bloques de ciclos", [5, 10, 20, 30, 50, 100, 250, 500, 1000], index=1)

sb.markdown("**Escenario**")
semilla = int(sb.number_input("Semilla del generador", 1, 2_147_483_646, 12345, step=1))
factor = float(sb.slider("Demanda (1.0 = la observada)", 0.5, 3.0, 1.0, step=0.1,
                         help="1.2 significa que llegan 20 % más carros que en la toma de datos"))

sb.markdown("**Restricciones fijas del cruce**")
sb.dataframe(pd.DataFrame([{"Semáforo": f"{s} {semaforos[s].ubicacion}", "Verde": f"{semaforos[s].verde} s",
                            "Rojo": f"{semaforos[s].rojo} s"} for s in SEMAFOROS]),
             hide_index=True, use_container_width=True)
sb.caption(f"Horas pico (fijas, tomadas del Excel de campo): {texto_horas_pico()}. El resto del día es hora valle. "
           "Toda simulación debe incluir horas valle y horas pico.")

repeticiones = int(ss.repeticiones)
st.title("Simulador del cruce vial · vía Mesa–Girardot")

# --- Validaciones: toda simulación debe tener valle y pico -------------------------------------
if fin <= inicio:
    st.error("La fecha y hora final debe ser posterior a la inicial.")
    st.stop()
hay_valle, hay_pico = cubre_valle_y_pico(inicio, fin)
if not (hay_valle and hay_pico):
    falta = "ninguna hora pico" if not hay_pico else "ninguna hora valle"
    st.error(f"El periodo del {inicio:%d/%m/%Y %H:%M} al {fin:%d/%m/%Y %H:%M} no incluye {falta}. "
             f"Toda simulación debe tener horas valle y horas pico (pico: {texto_horas_pico()}). "
             "Amplíe el periodo, por ejemplo de 10:00 a 14:00.")
    st.stop()
_esc = EscenarioPrediccion(inicio, fin, repeticiones, semilla, factor)
if ciclos_estimados(semaforos, _esc) > MAX_CICLOS_TOTALES:
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


@st.cache_data(show_spinner="Preparando Excel y PDF…", max_entries=6)
def archivos(inicio, fin, repeticiones, semilla, factor, horas_bloque, ciclos_bloque):
    p = armar(inicio, fin, repeticiones, semilla, factor, horas_bloque, ciclos_bloque)
    return excel_paquete(p), pdf_paquete(p)


@st.cache_data
def campo_xlsx():
    return excel_datos_campo(campo)


@st.cache_data
def campo_pdf():
    return pdf_datos_campo(campo)


args = (inicio, fin, repeticiones, semilla, factor)
res = correr(*args)
pq = armar(*args, horas_bloque, ciclos_bloque)
xlsx, pdf = archivos(*args, horas_bloque, ciclos_bloque)
T, K, G = pq.tablas, pq.kpis, pq.graficos
nombre_bh = f"Bloques de {horas_bloque} h"
nombre_bc = f"Bloques de {ciclos_bloque} ciclos"
archivo = f"simulacion_cruce_{inicio:%Y%m%d_%H%M}_{fin:%Y%m%d_%H%M}"

st.caption(f"Periodo: {inicio:%d/%m/%Y %H:%M} a {fin:%d/%m/%Y %H:%M} · Ciclos: {mil(K['Ciclos'])} · "
           f"Números pseudoaleatorios: {mil(K['Números pseudoaleatorios'])} · {repeticiones} repeticiones · "
           f"semilla {semilla} · demanda ×{factor:g}")


def descargas(clave):
    c1, c2 = st.columns(2)
    c1.download_button("⬇ Descargar todo en Excel", xlsx, f"{archivo}.xlsx", key=f"x_{clave}",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True, type="primary")
    c2.download_button("⬇ Descargar todo en PDF", pdf, f"{archivo}.pdf", key=f"p_{clave}",
                       mime="application/pdf", use_container_width=True, type="primary")


def grafico_valle_pico():
    sp = T["Semáforo y periodo"]
    fig = px.bar(sp, x="Semáforo", y="Prom. por hora", color="Periodo", barmode="group",
                 category_orders={"Periodo": ["Valle", "Pico"]},
                 color_discrete_map={"Valle": "#5B8DB8", "Pico": "#E07B39"},
                 labels={"Prom. por hora": "Vehículos por hora"}, title="Vehículos por hora: valle vs pico")
    st.plotly_chart(fig, use_container_width=True)


def grafico_horas(clave):
    hr = G["horas"]
    fig = px.line(hr, x="hora", y=SEMAFOROS, markers=len(hr) < 80,
                  labels={"hora": "Hora", "value": "Vehículos por hora", "variable": "Semáforo"},
                  title="Vehículos que pasan por hora")
    for x0, x1 in franjas_pico(inicio, fin):
        fig.add_vrect(x0=x0, x1=x1, fillcolor="orange", opacity=0.15, line_width=0)
    st.plotly_chart(fig, use_container_width=True, key=f"horas_{clave}")


tabs = st.tabs(["Resumen", "Reportes", "Mapa en vivo", "¿Cuánto aguanta el cruce?",
                "Validación", "Datos de campo", "Generador y pruebas", "Cómo funciona"])

# ---------------------------------------------------------------------------
# 1. Resumen
# ---------------------------------------------------------------------------
with tabs[0]:
    descargas("resumen")
    c = st.columns(4)
    c[0].metric("Vehículos que pasan", mil(K["Vehículos que pasan"]), help="Promedio de las repeticiones")
    c[1].metric("Margen (IC 95 %)", f"± {mil(K['Margen ± IC 95 %'])}")
    c[2].metric("Horas simuladas", mil(K["Horas simuladas"], 1))
    c[3].metric("Promedio por hora", mil(K["Promedio por hora"]))
    c = st.columns(4)
    c[0].metric("Pasan en hora valle", mil(K.get("Pasan en hora valle", 0)))
    c[1].metric("Pasan en hora pico", mil(K.get("Pasan en hora pico", 0)))
    c[2].metric("Prom. por hora valle", mil(K.get("Promedio por hora valle", 0)))
    c[3].metric("Prom. por hora pico", mil(K.get("Promedio por hora pico", 0)))
    if "Promedio por hora valle" in K and "Promedio por hora pico" in K:
        v, p = K["Promedio por hora valle"], K["Promedio por hora pico"]
        st.info(f"En hora pico pasan en promedio **{mil(p)} vehículos por hora**, frente a **{mil(v)}** en hora "
                f"valle: un **{mil(100 * (p / v - 1), 1)} %** más.")

    st.markdown("#### Por semáforo")
    tabla(T["Semáforos"])
    st.markdown("#### Cada semáforo en hora valle y en hora pico")
    tabla(T["Semáforo y periodo"])
    st.markdown("#### Hora valle frente a hora pico (todo el periodo)")
    tabla(T["Valle vs pico"])
    c1, c2 = st.columns(2)
    with c1:
        grafico_valle_pico()
    with c2:
        grafico_horas("resumen")
    with st.expander("Parámetros de esta simulación"):
        tabla(T["Parámetros"])

# ---------------------------------------------------------------------------
# 2. Reportes (todo junto)
# ---------------------------------------------------------------------------
with tabs[1]:
    descargas("reportes")
    st.caption("Todos los reportes incluyen hora valle y hora pico. El tamaño de los bloques se cambia en la "
               "barra lateral. Los valores son el promedio de las repeticiones.")

    st.markdown(f"### 1. Por bloques de {horas_bloque} h")
    st.caption(pq.notas[nombre_bh])
    b = G["bloques"]
    fig = go.Figure()
    fig.add_bar(name="En hora valle", x=b["bloque"], y=b["en_valle"], marker_color="#5B8DB8")
    fig.add_bar(name="En hora pico", x=b["bloque"], y=b["en_pico"], marker_color="#E07B39")
    fig.update_layout(barmode="stack", yaxis_title="Vehículos", height=380, margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True)
    tabla(T[nombre_bh])

    st.markdown("### 2. Por hora")
    grafico_horas("reportes")
    tabla(T["Por hora"], alto=420)

    st.markdown(f"### 3. Por bloques de {ciclos_bloque} ciclos")
    st.caption(pq.notas[nombre_bc])
    bc = G["bloques_ciclos"]
    fig = px.line(bc, x="desde", y="pasan", color="semaforo", markers=len(bc) < 200,
                  labels={"desde": "Inicio del bloque", "pasan": f"Vehículos en {ciclos_bloque} ciclos",
                          "semaforo": "Semáforo"})
    st.plotly_chart(fig, use_container_width=True)
    tabla(T[nombre_bc], alto=420)

    st.markdown("### 4. Cada semáforo en hora valle y en hora pico")
    tabla(T["Semáforo y periodo"])
    st.markdown("### 5. Hora valle frente a hora pico")
    tabla(T["Valle vs pico"])

    st.markdown("### 6. Por ciclo (los 4 semáforos)")
    st.caption("Repetición 1 (U1, U2, llegadas, cola…) y el promedio de cada ciclo entre todas las repeticiones.")
    pc = T["Por ciclo"]
    tabla(pc.head(20000), alto=420)
    if len(pc) > 20000:
        st.caption(f"Se muestran 20.000 de {mil(len(pc))} ciclos. El Excel tiene todos.")

# ---------------------------------------------------------------------------
# 3. Mapa en vivo
# ---------------------------------------------------------------------------
with tabs[2]:
    st.markdown("Animación de la simulación sobre el mapa satelital: los puntos amarillos son carros en cola "
                "y los verdes son carros que pasan. Los semáforos se ponen en verde uno tras otro "
                "(S1 → S2 → S3 → S4). Se reproduce la repetición 1 desde el inicio del periodo.")
    with st.expander("Ajustar la ubicación del cruce y de los semáforos"):
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
    ciclos_anim = st.slider("Ciclos a animar por semáforo", 5, 60, 20)
    anim = res.ciclos.groupby("semaforo").head(ciclos_anim)
    components.html(html_mapa(anim, res.info_semaforos, (lat, lon), posiciones,
                              inicio.strftime("%Y-%m-%dT%H:%M:%S")), height=680)

    st.markdown("#### Vista de la calle (Google Maps)")
    st.caption("Abre en otra pestaña la vista de Google Street View desde cada semáforo, mirando como el conductor "
               "que llega al cruce, o su ubicación en Google Maps.")
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
with tabs[3]:
    st.markdown("**¿Cuántos vehículos puede atender el cruce sin problema?** Se repite la simulación aumentando "
                "la demanda poco a poco, en hora valle y en hora pico, y se mira en qué punto la cola deja de "
                "despejarse.")
    st.caption(pq.notas["Capacidad"])
    cap = T["Capacidad"]
    tabla(cap)
    c1, c2 = st.columns(2)
    for col, per in zip((c1, c2), ("Valle", "Pico")):
        d = cap[cap["Periodo"] == per]
        col.info(f"**Hora {per.lower()}:** el cruce atiende como máximo **{mil(d['Capacidad (veh/h)'].sum())} veh/h** "
                 f"y llegan unos **{mil(d['Demanda (veh/h)'].sum())} veh/h**.")
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
with tabs[4]:
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

# ---------------------------------------------------------------------------
# 6. Datos de campo
# ---------------------------------------------------------------------------
with tabs[5]:
    st.markdown(f"Registro manual por ciclo (verde → rojo): **{len(campo)} ciclos** en los cuatro semáforos.")
    c1, c2 = st.columns(2)
    c1.download_button("⬇ Datos de campo en Excel", campo_xlsx(), "datos_campo_cruce_vial.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    c2.download_button("⬇ Datos de campo en PDF", campo_pdf(), "datos_campo_cruce_vial.pdf",
                       mime="application/pdf", use_container_width=True)
    tabla(T["Datos de campo (resumen)"])
    st.markdown("#### ¿En qué franjas hay más flujo? (datos de campo)")
    st.caption("Vehículos por hora = carros que pasan por ciclo × 3600 ÷ duración del ciclo (s). "
               "'Cruce completo' suma los 4 semáforos y solo aparece si se midieron los 4 en esa franja.")
    tabla(T["Flujo por franja medida"])
    st.markdown("#### Tablas de codificación por intervalos de las llegadas (valle y pico)")
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
with tabs[6]:
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
    st.plotly_chart(px.histogram(x=u, nbins=10, labels={"x": "U"}, title="Histograma de los U generados"),
                    use_container_width=True)

# ---------------------------------------------------------------------------
# 8. Cómo funciona
# ---------------------------------------------------------------------------
with tabs[7]:
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
y su margen es el intervalo de confianza del 95 %: `promedio ± 1,96 · desviación estándar ÷ √R`.

**Supuestos.** Total por semáforo (sin separar giros), rojo de 99 s, sin amarillo ni despeje. Las horas que
no se midieron (noche, madrugada, fines de semana) se tratan como hora valle, así que en esas horas la
predicción puede quedar por encima de la realidad.
""")
