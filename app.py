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
from simulador.exportar import (NOMBRES, excel_datos_campo, excel_prediccion, pdf_datos_campo,
                                pdf_prediccion)
from simulador.generador import GeneradorCongruencial
from simulador.mapa import CENTRO_DEFECTO, POSICIONES_DEFECTO, enlaces_google, html_mapa
from simulador.modelo import Escenario, barrido_demanda, simular, tabla_intervalos
from simulador.prediccion import (EscenarioPrediccion, MAX_CICLOS_TOTALES, ciclos_estimados,
                                  predecir, texto_horas_pico)
from simulador.pruebas import prueba_frecuencias, prueba_ks, prueba_promedios
from simulador.reportes import (reporte_bloques, reporte_horas, reporte_semaforos,
                                reporte_valle_pico)

st.set_page_config(page_title="Simulador cruce vial", page_icon="🚦", layout="wide")


@st.cache_data
def datos():
    return cargar_semaforos(), calcular_llegadas(leer_base()), leer_base()


semaforos, base, campo = datos()


def mil(x, dec=0):
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def legible(df):
    return df.rename(columns=NOMBRES)


# ---------------------------------------------------------------------------
# Barra lateral: periodo a predecir
# ---------------------------------------------------------------------------
st.sidebar.title("🚦 Predicción")
with st.sidebar.form("parametros"):
    st.markdown("**Periodo a predecir**")
    hoy = date.today()
    c1, c2 = st.columns(2)
    f_ini = c1.date_input("Desde el día", hoy, format="DD/MM/YYYY")
    h_ini = c2.time_input("a las", time(6, 0), step=timedelta(minutes=30))
    c1, c2 = st.columns(2)
    f_fin = c1.date_input("Hasta el día", hoy, format="DD/MM/YYYY")
    h_fin = c2.time_input("a las ", time(20, 0), step=timedelta(minutes=30))

    st.markdown("**Números pseudoaleatorios**")
    repeticiones = st.number_input("Repeticiones de la simulación", 1, 200, 10,
                                   help="Cada repetición usa números pseudoaleatorios distintos. "
                                        "El resultado es el promedio de todas.")
    semilla = st.number_input("Semilla del generador", 1, 2_147_483_646, 12345, step=1)

    st.markdown("**Escenario**")
    factor = st.slider("Demanda (1.0 = la observada)", 0.5, 3.0, 1.0, step=0.1,
                       help="1.2 significa que llegan 20 % más carros que en la toma de datos")
    with st.expander("Tiempo en verde de cada semáforo"):
        verdes = {s: st.number_input(f"{s} – {semaforos[s].ubicacion} (s)", 5, 120, semaforos[s].verde, step=1)
                  for s in SEMAFOROS}
        st.caption("Rojo: 99 s en los cuatro semáforos.")
    simular_btn = st.form_submit_button("▶ Simular", type="primary", use_container_width=True)

st.sidebar.caption(f"Horas pico (fijas): {texto_horas_pico()}. El resto del día es hora valle.")

inicio = datetime.combine(f_ini, h_ini)
fin = datetime.combine(f_fin, h_fin)
esc = EscenarioPrediccion(inicio, fin, int(repeticiones), int(semilla), factor, verdes)

if simular_btn or "resultado" not in st.session_state:
    if fin <= inicio:
        st.sidebar.error("La fecha y hora final debe ser posterior a la inicial.")
        st.stop()
    est = ciclos_estimados(semaforos, esc)
    if est > MAX_CICLOS_TOTALES:
        st.sidebar.error(f"Son {mil(est)} ciclos en total (rango × repeticiones). El máximo es "
                         f"{mil(MAX_CICLOS_TOTALES)}. Reduzca el rango o las repeticiones.")
        st.stop()
    with st.spinner("Simulando…"):
        st.session_state.resultado = predecir(semaforos, esc)

res = st.session_state.resultado
e = res.escenario
sem_rep = reporte_semaforos(res)
vp = reporte_valle_pico(res)
total = sem_rep["pasan"].sum()
ic_total = (res.horas.groupby("repeticion")["pasan"].sum().std(ddof=1) * 1.96 / e.repeticiones ** 0.5
            if e.repeticiones > 1 else 0)
horas_sim = (e.fin - e.inicio).total_seconds() / 3600

st.title("Simulador del cruce vial · vía Mesa–Girardot")
st.caption(f"Predicción del {e.inicio:%d/%m/%Y %H:%M} al {e.fin:%d/%m/%Y %H:%M} · "
           f"{e.repeticiones} repeticiones · semilla {e.semilla} · "
           f"{mil(res.numeros_usados)} números pseudoaleatorios")

tabs = st.tabs(["Predicción", "Reportes", "Mapa en vivo", "¿Cuánto aguanta el cruce?",
                "Validación", "Datos de campo", "Generador y pruebas", "Cómo funciona"])

# ---------------------------------------------------------------------------
# 1. Predicción
# ---------------------------------------------------------------------------
with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vehículos que pasan", mil(total), help="Promedio de las repeticiones")
    c2.metric("Margen (IC 95 %)", f"± {mil(ic_total)}")
    c3.metric("Horas simuladas", mil(horas_sim, 1))
    c4.metric("Promedio por hora", mil(total / horas_sim))

    st.markdown("#### Por semáforo")
    cols = ["semaforo", "ubicacion", "verde_s", "ciclo_s", "ciclos", "pasan", "ic95",
            "pct_del_total", "prom_por_ciclo", "cola_prom"]
    st.dataframe(legible(sem_rep[cols]).style.format(precision=1, thousands=".", decimal=","),
                 use_container_width=True, hide_index=True)

    st.markdown("#### Horas valle frente a horas pico")
    st.dataframe(legible(vp).style.format(precision=1, thousands=".", decimal=","), use_container_width=True, hide_index=True)
    if len(vp) == 2:
        v, p = vp.set_index("periodo").loc["Valle"], vp.set_index("periodo").loc["Pico"]
        st.info(f"En hora pico pasan en promedio **{mil(p['prom_por_hora'])} vehículos por hora**, frente a "
                f"**{mil(v['prom_por_hora'])}** en hora valle: un **{mil(100 * (p['prom_por_hora'] / v['prom_por_hora'] - 1), 1)} %** más.")

    st.markdown("#### Vehículos que pasan por hora")
    horas = reporte_horas(res)
    fig = px.line(horas, x="hora", y=SEMAFOROS, markers=len(horas) < 80,
                  labels={"hora": "Hora", "value": "Vehículos por hora", "variable": "Semáforo"})
    for h_ini_p in horas.loc[horas["periodo"] == "Pico", "hora"]:
        fig.add_vrect(x0=h_ini_p, x1=h_ini_p + pd.Timedelta(hours=1), fillcolor="orange", opacity=0.15, line_width=0)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Franjas naranjas: horas pico.")

# ---------------------------------------------------------------------------
# 2. Reportes
# ---------------------------------------------------------------------------
with tabs[1]:
    c1, c2 = st.columns([1, 3])
    horas_bloque = c1.selectbox("Tamaño de los bloques", [1, 2, 3, 4, 6, 8, 12, 24], index=1,
                                format_func=lambda h: f"{h} hora" + ("s" if h > 1 else ""))
    c2.markdown(f"Los bloques empiezan a medianoche (00:00–{horas_bloque:02d}:00, …). "
                "Cada valor es el promedio de las repeticiones.")

    bloques = reporte_bloques(res, horas_bloque)
    st.markdown(f"#### Vehículos que pasan por bloques de {horas_bloque} h")
    fig = go.Figure()
    fig.add_bar(name="En horas valle", x=bloques["bloque"], y=bloques["en_valle"], marker_color="#7FA7C9")
    fig.add_bar(name="En horas pico", x=bloques["bloque"], y=bloques["en_pico"], marker_color="#D9774B")
    fig.update_layout(barmode="stack", yaxis_title="Vehículos", height=380)
    st.plotly_chart(fig, use_container_width=True)
    cols = ["bloque"] + SEMAFOROS + ["total", "ic95", "pct_del_total", "ciclos", "prom_por_ciclo",
                                     "en_valle", "pct_valle", "en_pico", "pct_pico"]
    st.dataframe(legible(bloques[cols]).style.format(precision=1, thousands=".", decimal=","),
                 use_container_width=True, hide_index=True)

    st.markdown("#### Por hora")
    h = reporte_horas(res)
    st.dataframe(legible(h).style.format(precision=1, thousands=".", decimal=",").format({"Hora": "{:%d/%m/%Y %H:%M}"}),
                 use_container_width=True, hide_index=True)

    st.markdown("#### Por ciclo (repetición 1)")
    s_sel = st.selectbox("Semáforo", SEMAFOROS, format_func=lambda s: f"{s} – {semaforos[s].ubicacion}")
    det = res.ciclos[res.ciclos["semaforo"] == s_sel]
    st.dataframe(legible(det.head(5000)).style.format(precision=4).format({"Inicio del ciclo": "{:%d/%m/%Y %H:%M:%S}"}),
                 use_container_width=True, hide_index=True)
    if len(det) > 5000:
        st.caption(f"Se muestran 5.000 de {mil(len(det))} ciclos. El Excel tiene todos.")

    st.markdown("#### Descargar reporte")
    c1, c2 = st.columns(2)
    nombre = f"prediccion_{e.inicio:%Y%m%d_%H%M}_{e.fin:%Y%m%d_%H%M}"
    with st.spinner("Preparando archivos…"):
        c1.download_button("⬇ Excel (todas las tablas)", excel_prediccion(res, horas_bloque, campo),
                           f"{nombre}.xlsx", use_container_width=True,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        c2.download_button("⬇ PDF (reporte)", pdf_prediccion(res, horas_bloque), f"{nombre}.pdf",
                           mime="application/pdf", use_container_width=True)

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
                              e.inicio.strftime("%Y-%m-%dT%H:%M:%S")), height=680)

    st.markdown("#### Vista de la calle (Google Maps)")
    st.caption("Abre en otra pestaña la vista de Google Street View desde cada semáforo, mirando como el conductor que llega al cruce, "
               "o su ubicación en Google Maps.")
    cols = st.columns(4)
    for col, s_m in zip(cols, SEMAFOROS):
        enl = enlaces_google(posiciones[s_m], (lat, lon))
        with col:
            st.markdown(f"**{s_m} · {semaforos[s_m].ubicacion}**")
            st.caption(POSICIONES_DEFECTO[s_m]["via"])
            st.link_button("👁 Street View", enl["street_view"], use_container_width=True)
            st.link_button("📍 Google Maps", enl["mapa"], use_container_width=True)

# ---------------------------------------------------------------------------
# 4. Capacidad
# ---------------------------------------------------------------------------
with tabs[3]:
    periodo_cap = st.radio("Hora", PERIODOS, horizontal=True, key="periodo_cap")
    _, resumen = simular(semaforos, Escenario(periodo=periodo_cap, ciclos=500, semilla=int(semilla),
                                              factor_demanda=factor, verdes=verdes))
    st.markdown("**¿Cuántos vehículos puede atender el cruce sin problema?** Se repite la simulación "
                "aumentando la demanda poco a poco y se mira en qué punto la cola deja de despejarse.")
    tabla = resumen[["semaforo", "ubicacion", "capacidad_ciclo", "ciclo_s", "capacidad_hora",
                     "demanda_hora", "utilizacion"]].copy()
    tabla["margen"] = 1 / tabla["utilizacion"]
    st.dataframe(tabla.rename(columns={
        "semaforo": "Semáforo", "ubicacion": "Ubicación", "capacidad_ciclo": "Pasan máx. por verde",
        "ciclo_s": "Ciclo (s)", "capacidad_hora": "Capacidad (veh/h)",
        "demanda_hora": "Demanda actual (veh/h)", "utilizacion": "Uso de capacidad",
        "margen": "La demanda puede crecer hasta ×"}).style.format({
        "Capacidad (veh/h)": "{:.0f}", "Demanda actual (veh/h)": "{:.0f}",
        "Uso de capacidad": "{:.0%}", "La demanda puede crecer hasta ×": "{:.2f}"}),
        use_container_width=True, hide_index=True)
    st.info(f"El cruce completo puede atender como máximo unos **{mil(tabla['capacidad_hora'].sum())} vehículos "
            f"por hora**. En hora {periodo_cap.lower()} llegan unos **{mil(tabla['demanda_hora'].sum())} veh/h**.")
    st.caption("Capacidad (veh/h) = pasan máx. por verde × (3600 ÷ duración del ciclo). "
               "Uso de capacidad = llegadas promedio por ciclo ÷ pasan máx. por verde.")
    with st.spinner("Simulando 26 niveles de demanda…"):
        bar = barrido_demanda(semaforos, periodo_cap, int(semilla))
    fig = px.line(bar, x="factor", y="cola_prom", color="semaforo", markers=True,
                  labels={"factor": "Demanda (× la observada)", "cola_prom": "Cola promedio (veh)", "semaforo": "Semáforo"})
    fig.add_vline(x=1, line_dash="dash", annotation_text="demanda actual")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# 5. Validación
# ---------------------------------------------------------------------------
with tabs[4]:
    st.markdown("Con la demanda observada y los tiempos reales, el simulador debe dar resultados parecidos a la "
                "toma de datos. Se usa el error del método de los 11 pasos: "
                "**error = |simulado − observado| ÷ observado × 100**.")
    filas = []
    for p in PERIODOS:
        _, r_val = simular(semaforos, Escenario(periodo=p, ciclos=1000, semilla=int(semilla)))
        for _, r in r_val.iterrows():
            obs = base[(base["semaforo"] == r["semaforo"]) & (base["periodo"] == p)]
            o = obs["pasan"].mean()
            filas.append({"Periodo": p, "Semáforo": r["semaforo"], "Pasan observado": o,
                          "Pasan simulado": r["pasan_prom"], "Error (%)": abs(r["pasan_prom"] - o) / o * 100,
                          "Cola observada": obs["quedan"].mean(), "Cola simulada": r["cola_prom"]})
    val = pd.DataFrame(filas)
    st.dataframe(val.style.format(precision=2), use_container_width=True, hide_index=True)
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
    c1.download_button("⬇ Datos de campo en Excel", excel_datos_campo(campo), "datos_campo_cruce_vial.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    c2.download_button("⬇ Datos de campo en PDF", pdf_datos_campo(campo), "datos_campo_cruce_vial.pdf",
                       mime="application/pdf", use_container_width=True)
    res_obs = base.groupby(["semaforo", "periodo"]).agg(
        ciclos=("pasan", "size"), pasan_prom=("pasan", "mean"), pasan_max=("pasan", "max"),
        quedan_prom=("quedan", "mean"), llegadas_prom=("llegadas", "mean")).reset_index()
    st.dataframe(res_obs.round(2), use_container_width=True, hide_index=True)
    c1, c2 = st.columns(2)
    s_t = c1.selectbox("Tabla de codificación por intervalos de las llegadas", SEMAFOROS,
                       format_func=lambda s: f"{s} – {semaforos[s].ubicacion}")
    p_t = c2.radio("Periodo", PERIODOS, horizontal=True, key="periodo_tabla")
    st.caption(f"{s_t}, hora {p_t.lower()}: si U cae en [desde, hasta), llegan 'valor' vehículos.")
    st.dataframe(tabla_intervalos(semaforos[s_t].llegadas[p_t]).round(4), use_container_width=True, hide_index=True)
    with st.expander(f"Ver los {len(campo)} registros"):
        st.dataframe(campo, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# 7. Generador y pruebas
# ---------------------------------------------------------------------------
with tabs[6]:
    st.markdown("Generador congruencial: **Xₙ₊₁ = 16807·Xₙ mod 2147483647** y **U = X ÷ 2147483647**.  \n"
                "Antes de confiar en la simulación se comprueba que los U sean uniformes con las pruebas del "
                "capítulo 3 de Coss Bu.  \nH₀: los números provienen de una distribución uniforme.")
    n_u = min(res.numeros_usados, 200_000)
    u = GeneradorCongruencial(int(e.semilla)).lista(n_u)
    filas = []
    for nombre, simb, r in [("Promedios (ec. 3.2)", "|Z₀|", prueba_promedios(u)),
                            ("Frecuencias, 10 subintervalos (ec. 3.3)", "X₀²", prueba_frecuencias(u)),
                            ("Kolmogorov-Smirnov (ec. 3.12)", "Dₙ", prueba_ks(u))]:
        est_v = abs(r["estadistico"]) if simb == "|Z₀|" else r["estadistico"]
        filas.append({"Prueba": nombre, "N": r["N"], "Estadístico": f"{simb} = {est_v:.4f}",
                      "Valor crítico": f"{r['critico']:.4f}",
                      "Decisión": "No se rechaza H₀" if r["no_se_rechaza"] else "Se rechaza H₀"})
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
    st.caption(f"Se prueban los primeros {mil(n_u)} números de la simulación actual, α = 0.05.")
    st.plotly_chart(px.histogram(x=u, nbins=10, labels={"x": "U"}, title="Histograma de los U generados"),
                    use_container_width=True)

# ---------------------------------------------------------------------------
# 8. Cómo funciona
# ---------------------------------------------------------------------------
with tabs[7]:
    st.markdown(f"""
**Periodo.** Se escoge desde qué día y hora hasta qué día y hora predecir. Cada ciclo de cada semáforo se
ubica en el reloj: si empieza en hora pico ({texto_horas_pico()}) se usan los datos de hora pico; si no,
los de hora valle.

**En cada ciclo y para cada semáforo:**

1. **Llegadas.** Se genera U₁ y se busca su intervalo en la tabla de llegadas de ese periodo
   (pestaña *Datos de campo*). Es la codificación por intervalos del método de los 11 pasos.
   Llegadas de campo: `llegadas = pasan + quedan − quedan del ciclo anterior`.
2. **En espera.** `en espera = cola anterior + llegadas`.
3. **Rezagados.** Se genera U₂ y con la tabla de *Quedan* se sortea cuántos carros llegan con el verde
   terminando y no alcanzan a pasar.
4. **Pasan.** `pasan = mín(en espera − rezagados, capacidad)`. La capacidad es el máximo que se vio pasar
   en un verde de ese semáforo y cambia en proporción al tiempo en verde.
5. **Quedan.** `quedan = en espera − pasan`, que pasan a la cola del siguiente ciclo.

**Repeticiones.** Todo se repite R veces con números pseudoaleatorios distintos. El resultado es el promedio
y su margen es el intervalo de confianza del 95 %: `promedio ± 1,96 · desviación estándar ÷ √R`.

**Supuestos.** Total por semáforo (sin separar giros), rojo de 99 s, sin amarillo ni despeje. Las horas que
no se midieron (noche, madrugada, fines de semana) se tratan como hora valle, así que en esas horas la
predicción puede quedar por encima de la realidad.
""")
