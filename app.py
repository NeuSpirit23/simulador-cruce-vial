"""Simulador del cruce vial de 4 semáforos — vía Mesa–Girardot.

Ejecutar:  streamlit run app.py
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from simulador.datos import PERIODOS, SEMAFOROS, cargar_semaforos, calcular_llegadas, leer_base
from simulador.generador import GeneradorCongruencial
from simulador.modelo import Escenario, barrido_demanda, estado, simular, tabla_intervalos
from simulador.pruebas import prueba_frecuencias, prueba_ks, prueba_promedios

st.set_page_config(page_title="Simulador cruce vial", page_icon="🚦", layout="wide")


@st.cache_data
def datos():
    return cargar_semaforos(), calcular_llegadas(leer_base())


semaforos, base = datos()

# ---------------------------------------------------------------------------
# Barra lateral: parámetros del escenario
# ---------------------------------------------------------------------------
st.sidebar.title("🚦 Parámetros")
periodo = st.sidebar.radio("Hora", PERIODOS, horizontal=True)
ciclos = st.sidebar.slider("Ciclos a simular por semáforo", 20, 1000, 200, step=10)
semilla = st.sidebar.number_input("Semilla del generador", 1, 2_147_483_646, 12345, step=1)
factor = st.sidebar.slider("Demanda (1.0 = la observada)", 0.5, 3.0, 1.0, step=0.1,
                           help="1.2 significa que llegan 20 % más carros que en la toma de datos")
st.sidebar.markdown("**Tiempo en verde (s)**")
verdes = {}
for s in SEMAFOROS:
    sem = semaforos[s]
    verdes[s] = st.sidebar.number_input(f"{s} – {sem.ubicacion}", 5, 120, sem.verde, step=1)
st.sidebar.caption("Rojo: 99 s en los cuatro semáforos.")

esc = Escenario(periodo=periodo, ciclos=ciclos, semilla=int(semilla),
                factor_demanda=factor, verdes=verdes)
detalle, resumen = simular(semaforos, esc)

st.title("Simulador del cruce vial · vía Mesa–Girardot")
st.caption("Curso de Simulación · Universidad Piloto de Colombia · Datos de campo: 221 ciclos observados")

tab_sim, tab_cap, tab_val, tab_datos, tab_gen, tab_modelo = st.tabs([
    "Simulación", "¿Cuánto aguanta el cruce?", "Validación", "Datos de campo",
    "Generador y pruebas", "Cómo funciona",
])

# ---------------------------------------------------------------------------
# 1. Simulación
# ---------------------------------------------------------------------------
with tab_sim:
    total_pasan = int(resumen["pasan_total"].sum())
    horas = (resumen["ciclo_s"] * ciclos).max() / 3600
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vehículos que pasaron", f"{total_pasan:,}".replace(",", "."))
    c2.metric("Tiempo simulado", f"{horas:.1f} h")
    c3.metric("Cola promedio total", f"{resumen['cola_prom'].sum():.1f} veh")
    c4.metric("Capacidad del cruce", f"{resumen['capacidad_hora'].sum():,.0f} veh/h".replace(",", "."))

    cols = st.columns(4)
    for col, (_, r) in zip(cols, resumen.iterrows()):
        with col:
            st.subheader(f"{r['semaforo']} · {r['ubicacion']}")
            st.write(f"Verde {r['verde_s']} s · ciclo {r['ciclo_s']} s")
            st.metric("Pasan por ciclo (prom.)", f"{r['pasan_prom']:.1f}")
            st.metric("Quedan en cola (prom.)", f"{r['cola_prom']:.1f}")
            st.metric("Uso de la capacidad", f"{100 * r['utilizacion']:.0f} %")
            texto = estado(r["utilizacion"], r["pct_ciclos_con_cola"])
            (st.error if texto.startswith("Saturado") else
             st.warning if texto.startswith("Al límite") else st.success)(texto)

    st.markdown("#### Cola al final de cada ciclo")
    fig = px.line(detalle, x="ciclo", y="quedan", color="semaforo",
                  labels={"ciclo": "Ciclo", "quedan": "Vehículos en cola", "semaforo": "Semáforo"})
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Vehículos que pasan por ciclo")
    fig = px.line(detalle, x="ciclo", y="pasan", color="semaforo",
                  labels={"ciclo": "Ciclo", "pasan": "Vehículos que pasan", "semaforo": "Semáforo"})
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Ver tabla ciclo por ciclo"):
        st.dataframe(detalle.round(5), use_container_width=True, hide_index=True)
        st.download_button("Descargar CSV", detalle.to_csv(index=False).encode("utf-8"),
                           "simulacion.csv", "text/csv")

# ---------------------------------------------------------------------------
# 2. Capacidad máxima
# ---------------------------------------------------------------------------
with tab_cap:
    st.markdown(
        "Aquí se responde la pregunta del proyecto: **¿cuántos vehículos puede atender el cruce "
        "sin problema?** Se repite la simulación aumentando la demanda poco a poco y se mira "
        "en qué punto la cola deja de despejarse."
    )
    tabla = resumen[["semaforo", "ubicacion", "capacidad_ciclo", "ciclo_s",
                     "capacidad_hora", "demanda_hora", "utilizacion"]].copy()
    tabla["demanda_max"] = tabla["capacidad_hora"]
    tabla["margen"] = 1 / tabla["utilizacion"]
    st.dataframe(
        tabla.rename(columns={
            "semaforo": "Semáforo", "ubicacion": "Ubicación",
            "capacidad_ciclo": "Pasan máx. por verde", "ciclo_s": "Ciclo (s)",
            "capacidad_hora": "Capacidad (veh/h)", "demanda_hora": "Demanda actual (veh/h)",
            "utilizacion": "Uso de capacidad", "demanda_max": "Máx. sin saturar (veh/h)",
            "margen": "La demanda puede crecer hasta ×",
        }).style.format({
            "Capacidad (veh/h)": "{:.0f}", "Demanda actual (veh/h)": "{:.0f}",
            "Uso de capacidad": "{:.0%}", "Máx. sin saturar (veh/h)": "{:.0f}",
            "La demanda puede crecer hasta ×": "{:.2f}",
        }),
        use_container_width=True, hide_index=True,
    )
    st.info(
        f"Con los tiempos actuales, el cruce completo puede atender como máximo unos "
        f"**{tabla['capacidad_hora'].sum():,.0f} vehículos por hora** entre los cuatro semáforos. "
        f"En hora {periodo.lower()} hoy llegan unos **{tabla['demanda_hora'].sum():,.0f} veh/h**."
        .replace(",", ".")
    )
    st.caption("Capacidad (veh/h) = pasan máx. por verde × (3600 ÷ duración del ciclo). "
               "Uso de capacidad = llegadas promedio por ciclo ÷ pasan máx. por verde.")

    with st.spinner("Simulando 26 niveles de demanda…"):
        bar = barrido_demanda(semaforos, periodo, int(semilla))
    fig = px.line(bar, x="factor", y="cola_prom", color="semaforo", markers=True,
                  labels={"factor": "Demanda (× la observada)", "cola_prom": "Cola promedio (veh)",
                          "semaforo": "Semáforo"})
    fig.add_vline(x=1, line_dash="dash", annotation_text="demanda actual")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Donde la curva se dispara, el semáforo se satura: llegan más carros de los que alcanzan a pasar.")

# ---------------------------------------------------------------------------
# 3. Validación: simulado vs observado
# ---------------------------------------------------------------------------
with tab_val:
    st.markdown(
        "Para confiar en el simulador, con la demanda observada (×1.0) y los tiempos reales "
        "debe dar resultados parecidos a la toma de datos. Se usa el mismo error del método "
        "de los 11 pasos:  **error = |simulado − observado| ÷ observado × 100**."
    )
    filas = []
    for p in PERIODOS:
        _, res = simular(semaforos, Escenario(periodo=p, ciclos=1000, semilla=int(semilla)))
        for _, r in res.iterrows():
            obs = base[(base["semaforo"] == r["semaforo"]) & (base["periodo"] == p)]
            o = obs["pasan"].mean()
            filas.append({"Periodo": p, "Semáforo": r["semaforo"],
                          "Pasan observado": o, "Pasan simulado": r["pasan_prom"],
                          "Error (%)": abs(r["pasan_prom"] - o) / o * 100,
                          "Cola observada": obs["quedan"].mean(),
                          "Cola simulada": r["cola_prom"]})
    val = pd.DataFrame(filas)
    st.dataframe(val.style.format({c: "{:.2f}" for c in val.columns if c not in ("Periodo", "Semáforo")}),
                 use_container_width=True, hide_index=True)
    st.caption("Simulación de 1000 ciclos por semáforo con la semilla elegida.")
    fig = go.Figure()
    etiquetas = val["Semáforo"] + " " + val["Periodo"]
    fig.add_bar(name="Observado", x=etiquetas, y=val["Pasan observado"])
    fig.add_bar(name="Simulado", x=etiquetas, y=val["Pasan simulado"])
    fig.update_layout(barmode="group", yaxis_title="Vehículos que pasan por ciclo")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# 4. Datos de campo
# ---------------------------------------------------------------------------
with tab_datos:
    st.markdown("Registro manual por ciclo (verde → rojo) en los cuatro semáforos.")
    res_obs = base.groupby(["semaforo", "periodo"]).agg(
        ciclos=("pasan", "size"), pasan_prom=("pasan", "mean"), pasan_max=("pasan", "max"),
        quedan_prom=("quedan", "mean"), llegadas_prom=("llegadas", "mean")).reset_index()
    st.dataframe(res_obs.round(2), use_container_width=True, hide_index=True)

    s_sel = st.selectbox("Tabla de codificación por intervalos de las llegadas", SEMAFOROS,
                         format_func=lambda s: f"{s} – {semaforos[s].ubicacion}")
    t = tabla_intervalos(semaforos[s_sel].llegadas[periodo])
    st.caption(f"{s_sel}, hora {periodo.lower()}: si U cae en [desde, hasta), llegan 'valor' vehículos.")
    st.dataframe(t.round(4), use_container_width=True, hide_index=True)

    with st.expander("Ver los 221 registros"):
        st.dataframe(base, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# 5. Generador y pruebas de Coss Bu
# ---------------------------------------------------------------------------
with tab_gen:
    st.markdown(
        "Generador congruencial: **Xₙ₊₁ = 16807·Xₙ mod 2147483647** y **U = X ÷ 2147483647**.  \n"
        "Antes de simular se comprueba que los U sean uniformes con las pruebas del capítulo 3 "
        "de Coss Bu.  \nH₀: los números provienen de una distribución uniforme."
    )
    n_u = 2 * ciclos * len(SEMAFOROS)
    u = GeneradorCongruencial(int(semilla)).lista(n_u)
    pruebas = [
        ("Promedios (ec. 3.2)", "|Z₀|", prueba_promedios(u)),
        ("Frecuencias, 10 subintervalos (ec. 3.3)", "X₀²", prueba_frecuencias(u)),
        ("Kolmogorov-Smirnov (ec. 3.12)", "Dₙ", prueba_ks(u)),
    ]
    filas = []
    for nombre, simb, r in pruebas:
        est = abs(r["estadistico"]) if simb == "|Z₀|" else r["estadistico"]
        filas.append({"Prueba": nombre, "N": r["N"], "Estadístico": f"{simb} = {est:.4f}",
                      "Valor crítico": f"{r['critico']:.4f}",
                      "Decisión": "No se rechaza H₀" if r["no_se_rechaza"] else "Se rechaza H₀"})
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
    st.caption(f"Se prueban los {n_u} números que usa la simulación actual (2 por ciclo y semáforo), α = 0.05.")
    st.plotly_chart(px.histogram(x=u, nbins=10, labels={"x": "U"}, title="Histograma de los U generados"),
                    use_container_width=True)

# ---------------------------------------------------------------------------
# 6. Explicación del modelo
# ---------------------------------------------------------------------------
with tab_modelo:
    st.markdown("""
**En cada ciclo y para cada semáforo:**

1. **Llegadas.** Se genera U₁ y se busca en qué intervalo de la tabla de llegadas cae
   (pestaña *Datos de campo*). Ese intervalo dice cuántos carros llegan. Es la misma
   codificación por intervalos del método de los 11 pasos.
   Las llegadas de campo se calcularon así: `llegadas = pasan + quedan − quedan del ciclo anterior`.
2. **En espera.** `en espera = cola anterior + llegadas`.
3. **Rezagados.** Se genera U₂ y, con la tabla de frecuencias de *Quedan*, se sortea cuántos
   carros llegan con el verde terminando y no alcanzan a pasar aunque haya espacio.
4. **Pasan.** Pasan como máximo los que caben en el verde (la *capacidad*, que es el máximo que
   se vio pasar en un verde de ese semáforo):
   `pasan = mín(en espera − rezagados, capacidad)`.
   Si se cambia el tiempo en verde, la capacidad cambia en la misma proporción.
5. **Quedan.** `quedan = en espera − pasan`. Esos carros pasan a la cola del siguiente ciclo.

**Supuestos:** no se separan giros (se cuenta el total por semáforo), el rojo dura 99 s,
no se modelan amarillo ni despeje, y cada semáforo se simula por separado.
""")
