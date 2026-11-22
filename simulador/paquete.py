"""Arma TODOS los reportes de una simulación en un solo paquete.

La app, el Excel y el PDF usan exactamente las mismas tablas, así que siempre
muestran la misma información. Todos los reportes incluyen hora valle y hora
pico al mismo tiempo.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from .datos import PERIODOS, SEMAFOROS, DatosSemaforo
from .generador import A, M
from .modelo import Escenario, barrido_demanda, simular, tabla_intervalos
from .prediccion import FRANJA_MIN, ResultadoPrediccion, texto_horas_pico
from .reportes import (NIVEL_CONFIANZA, Z, reporte_bloques, reporte_bloques_ciclos, reporte_horas, reporte_semaforos,
                       reporte_valle_pico)


@dataclass
class Paquete:
    titulo: str
    kpis: dict
    tablas: dict = field(default_factory=dict)      # nombre -> DataFrame con columnas en español
    notas: dict = field(default_factory=dict)       # nombre -> texto explicativo
    graficos: dict = field(default_factory=dict)    # datos para gráficos (DataFrames)
    inicio: datetime | None = None
    fin: datetime | None = None


def _por_semaforo_y_periodo(res: ResultadoPrediccion) -> pd.DataFrame:
    h = res.horas
    r = res.escenario.repeticiones
    filas = []
    for s in SEMAFOROS:
        total_s = h[h["semaforo"] == s].groupby("repeticion")["pasan"].sum().mean()
        for p in PERIODOS:
            d = h[(h["semaforo"] == s) & (h["periodo"] == p)]
            if d.empty:
                continue
            rep = d.groupby("repeticion")[["pasan", "ciclos", "llegadas", "cola_suma"]].sum()
            m = rep.mean()
            ic = Z * rep["pasan"].std(ddof=1) / math.sqrt(r) if r > 1 else 0.0
            horas = d["hora"].nunique() * FRANJA_MIN / 60
            filas.append({
                "Semáforo": s, "Periodo": p, "Horas": horas, "Ciclos": m["ciclos"],
                "Vehículos que pasan": m["pasan"], "± IC 99 %": ic,
                "% del semáforo": 100 * m["pasan"] / total_s if total_s else 0,
                "Prom. por ciclo": m["pasan"] / m["ciclos"], "Prom. por hora": m["pasan"] / horas,
                "Llegadas": m["llegadas"], "Cola prom. (veh)": m["cola_suma"] / m["ciclos"],
            })
    return pd.DataFrame(filas)


MAX_NUMEROS_REPORTE = 200_000


def secuencia_numeros(res: ResultadoPrediccion, semaforos: dict[str, DatosSemaforo],
                      max_filas: int = MAX_NUMEROS_REPORTE) -> pd.DataFrame:
    """Cada número pseudoaleatorio de la repetición 1, en el orden en que se generó, y qué produjo.

    Orden: semáforo S1 (todos sus ciclos), luego S2, S3 y S4. En cada ciclo se generan 2 números:
      U1 → cuántos carros llegan (tabla de llegadas del periodo)
      U2 → cuántos llegan tarde y no alcanzan a pasar (tabla de "Quedan" del periodo)
    X(n) = 16807 · X(n−1) mod 2147483647   y   U = X(n) ÷ 2147483647
    """
    e = res.escenario
    orden = {s: i for i, s in enumerate(SEMAFOROS)}
    c = res.ciclos.assign(_o=res.ciclos["semaforo"].map(orden)).sort_values(["_o", "ciclo"])
    c = c.head((max_filas + 1) // 2).reset_index(drop=True)

    # Secuencia X(n) desde la semilla
    n_num = 2 * len(c)
    xs = np.empty(n_num + 1, dtype=np.int64)
    xs[0] = e.semilla % M
    for i in range(1, n_num + 1):
        xs[i] = (A * int(xs[i - 1])) % M

    # Intervalo de la tabla donde cae cada U (por semáforo y periodo)
    desde = {"U1": np.zeros(len(c)), "U2": np.zeros(len(c))}
    hasta = {"U1": np.zeros(len(c)), "U2": np.zeros(len(c))}
    valor = {"U1": np.zeros(len(c), dtype=int), "U2": np.zeros(len(c), dtype=int)}
    for (s, p), idx in c.groupby(["semaforo", "periodo"]).groups.items():
        sem = semaforos[s]
        for uso, datos in (("U1", sem.llegadas[p]), ("U2", sem.quedan[p])):
            t = tabla_intervalos(datos)
            k = np.minimum(np.searchsorted(t["hasta"].to_numpy(), c.loc[idx, uso].to_numpy(), side="right"),
                           len(t) - 1)
            desde[uso][idx] = t["desde"].to_numpy()[k]
            hasta[uso][idx] = t["hasta"].to_numpy()[k]
            valor[uso][idx] = t["valor"].to_numpy()[k]

    sufijo = f" (valor × {e.factor_demanda:g})" if e.factor_demanda != 1 else ""
    res_u1 = "Llegan " + c["llegadas"].astype(str) + " carros" + sufijo
    res_u2 = (c["rezagados"].astype(str) + " rezagados → pasan " + c["pasan"].astype(str) + ", quedan "
              + c["quedan"].astype(str) + " (en espera " + c["en_espera"].astype(str) + ", capacidad "
              + c["capacidad"].astype(str) + ")")

    partes = []
    for j, (uso, que, resultado) in enumerate((("U1", "Carros que llegan", res_u1),
                                               ("U2", "Carros que no alcanzan a pasar", res_u2))):
        pos = 2 * np.arange(len(c)) + j + 1          # posición en la secuencia
        partes.append(pd.DataFrame({
            "N°": pos, "Semáforo": c["semaforo"], "Ciclo": c["ciclo"], "Inicio del ciclo": c["inicio"],
            "Periodo": c["periodo"], "Número": uso, "Para qué se usa": que,
            "X anterior": xs[pos - 1], "X(n) = 16807·X anterior mod 2147483647": xs[pos],
            "U = X(n) ÷ 2147483647": xs[pos] / M,
            "Intervalo donde cae U": ["[" + f"{a:.4f}" + " ; " + f"{b:.4f}" + ")" for a, b in zip(desde[uso], hasta[uso])],
            "Valor de la tabla": valor[uso], "Resultado en el ciclo": resultado,
        }))
    out = pd.concat(partes).sort_values("N°").reset_index(drop=True)
    return out.head(max_filas)


ERROR_OBJETIVO = 0.01   # 1 % de error relativo


def precision(res: ResultadoPrediccion) -> tuple[pd.DataFrame, pd.DataFrame]:
    """¿Qué tan exacta es la predicción con estas repeticiones?

    Para cada resultado se calcula, entre las R repeticiones:
      media x̄, desviación s, semiancho del IC 99 % h = Z·s/√R,
      error relativo = h ÷ x̄, y repeticiones necesarias para error ≤ 1 %:
      R* = (Z·s ÷ (0,01·x̄))²
    Devuelve (tabla de precisión, convergencia del total por repetición).
    """
    h = res.horas
    r = res.escenario.repeticiones
    series = {"Total del cruce": h.groupby("repeticion")["pasan"].sum()}
    for p in PERIODOS:
        series[f"Total en hora {p.lower()}"] = h[h["periodo"] == p].groupby("repeticion")["pasan"].sum()
    for s_ in SEMAFOROS:
        series[f"Semáforo {s_}"] = h[h["semaforo"] == s_].groupby("repeticion")["pasan"].sum()
    filas = []
    for nombre, x in series.items():
        if x.empty:
            continue
        m, sd = x.mean(), (x.std(ddof=1) if r > 1 else 0.0)
        hw = Z * sd / math.sqrt(r) if r > 1 else float("nan")
        err = hw / m if m and r > 1 else float("nan")
        necesarias = math.ceil((Z * sd / (ERROR_OBJETIVO * m)) ** 2) if m and r > 1 else float("nan")
        filas.append({"Resultado": nombre, "Promedio": m, "Desviación entre repeticiones": sd,
                      "± IC 99 %": hw, "Error relativo (%)": 100 * err,
                      "Repeticiones para error ≤ 1 %": max(2, necesarias) if necesarias == necesarias else necesarias,
                      "¿Cumple ≤ 1 %?": ("Sí" if err <= ERROR_OBJETIVO else "No") if err == err else "Faltan repeticiones"})
    tot = series["Total del cruce"].sort_index()
    conv = pd.DataFrame({"Repeticiones": range(1, len(tot) + 1), "Total": tot.to_numpy()})
    conv["Promedio acumulado"] = conv["Total"].expanding().mean()
    sd_acum = conv["Total"].expanding().std(ddof=1)
    conv["Límite inferior IC 99 %"] = conv["Promedio acumulado"] - Z * sd_acum / np.sqrt(conv["Repeticiones"])
    conv["Límite superior IC 99 %"] = conv["Promedio acumulado"] + Z * sd_acum / np.sqrt(conv["Repeticiones"])
    return pd.DataFrame(filas), conv


def mapa_calor(res: ResultadoPrediccion) -> pd.DataFrame:
    """Vehículos que pasan por día (filas) y hora del día (columnas), promedio de las repeticiones."""
    h = res.horas.copy()
    h["dia"] = h["hora"].dt.normalize()
    h["h"] = h["hora"].dt.hour
    t = h.groupby(["repeticion", "dia", "h"])["pasan"].sum().groupby(["dia", "h"]).mean().unstack("h")
    t = t.reindex(columns=range(24))
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    t.index = [f"{dias[d.weekday()]} {d:%d/%m/%Y}" for d in t.index]
    t.columns = [f"{c:02d}:00" for c in t.columns]
    return t


def colas(res: ResultadoPrediccion) -> pd.DataFrame:
    """Cola que queda al final de cada ciclo (repetición 1): promedio, percentil 95 y máximo."""
    c = res.ciclos
    filas = []
    for s_ in SEMAFOROS:
        for p in PERIODOS + ["Todo"]:
            d = c[(c["semaforo"] == s_) & ((c["periodo"] == p) | (p == "Todo"))]["quedan"]
            if d.empty:
                continue
            filas.append({"Semáforo": s_, "Periodo": p, "Ciclos": len(d), "Cola prom. (veh)": d.mean(),
                          "Percentil 95 (veh)": d.quantile(0.95), "Máxima (veh)": int(d.max()),
                          "% de ciclos con cola": 100 * (d > 0).mean()})
    return pd.DataFrame(filas)


def prueba_ajuste_llegadas(res: ResultadoPrediccion, semaforos: dict[str, DatosSemaforo],
                           alfa: float = 0.01) -> pd.DataFrame:
    """¿Las llegadas que generó el simulador siguen la distribución observada en campo?

    Para cada semáforo y periodo (repetición 1):
      FO = cuántos ciclos simulados tuvieron cada cantidad de llegadas
      FE = total de ciclos × probabilidad observada en campo de esa cantidad
    Se juntan valores vecinos hasta que cada FE ≥ 5 (regla de Coss Bu) y se calcula
      X₀² = Σ (FO − FE)² ÷ FE,  con k − 1 grados de libertad.
    H₀: las llegadas simuladas siguen la distribución de campo. Nivel de significancia 1 % (99 % de confianza).
    """
    from scipy import stats

    filas = []
    factor = res.escenario.factor_demanda
    for s_ in SEMAFOROS:
        for p in PERIODOS:
            sim = res.ciclos[(res.ciclos["semaforo"] == s_) & (res.ciclos["periodo"] == p)]["llegadas"]
            if len(sim) < 10:
                continue
            obs = pd.Series(semaforos[s_].llegadas[p])
            valores = sorted(obs.unique())
            prob = obs.value_counts(normalize=True).reindex(valores).to_numpy()
            if factor != 1:
                valores = [round(v * factor) for v in valores]
            fo = np.array([(sim == v).sum() for v in valores], dtype=float)
            fe = prob * len(sim)
            # agrupar vecinos hasta FE ≥ 5
            grupos_fo, grupos_fe, acum_o, acum_e = [], [], 0.0, 0.0
            for o, e in zip(fo, fe):
                acum_o += o
                acum_e += e
                if acum_e >= 5:
                    grupos_fo.append(acum_o); grupos_fe.append(acum_e); acum_o = acum_e = 0.0
            if acum_e > 0 and grupos_fe:
                grupos_fo[-1] += acum_o; grupos_fe[-1] += acum_e
            k = len(grupos_fe)
            if k < 2:
                continue
            x2 = float(sum((o - e) ** 2 / e for o, e in zip(grupos_fo, grupos_fe)))
            critico = float(stats.chi2.ppf(1 - alfa, k - 1))
            filas.append({"Semáforo": s_, "Periodo": p, "Ciclos simulados": len(sim), "Clases (FE ≥ 5)": k,
                          "X₀²": x2, "Grados de libertad": k - 1, "Valor crítico (α = 0,01)": critico,
                          "Decisión": "No se rechaza H₀" if x2 < critico else "Se rechaza H₀"})
    return pd.DataFrame(filas)


def conclusiones(res: ResultadoPrediccion, tablas: dict) -> tuple[pd.DataFrame, list[str]]:
    """Conclusiones automáticas para tomar decisiones (horas de más y menos flujo, dónde se espera más, margen).

    Se calculan por hora del día, promediando todos los días del periodo y las repeticiones.
    """
    h = res.horas.copy()
    r = res.escenario.repeticiones
    h["h"] = h["hora"].dt.hour
    h["dia"] = h["hora"].dt.normalize()
    # vehículos por hora del día (promedio entre días y repeticiones)
    por_hora = (h.groupby(["repeticion", "dia", "h"])["pasan"].sum().groupby("h").mean())
    cola_hora = (h.groupby("h")["cola_suma"].sum() / h.groupby("h")["ciclos"].sum())
    periodo_hora = h.groupby("h")["periodo"].agg(lambda x: x.iloc[0] if x.nunique() == 1 else "Valle y pico")
    medidas = set(range(10, 13)) | set(range(16, 19))          # horas con datos de campo
    hh = pd.DataFrame({"veh": por_hora, "cola": cola_hora, "periodo": periodo_hora})
    rot = lambda x: f"{int(x):02d}:00–{int(x) + 1:02d}:00"
    filas, frases = [], []
    top = hh.sort_values("veh", ascending=False).head(3)
    filas.append({"Indicador": "Horas de MAYOR flujo", "Resultado": ", ".join(rot(i) for i in top.index),
                  "Detalle": " · ".join(f"{rot(i)}: {v:,.0f} veh/h".replace(",", ".") for i, v in top["veh"].items())})
    bajo = hh[hh.index.isin(medidas)].sort_values("veh").head(3)
    if len(bajo):
        filas.append({"Indicador": "Horas de MENOR flujo (entre las medidas)", "Resultado": ", ".join(rot(i) for i in bajo.index),
                      "Detalle": " · ".join(f"{rot(i)}: {v:,.0f} veh/h".replace(",", ".") for i, v in bajo["veh"].items())
                      + ". Las horas no medidas se suponen como valle."})
    cola_top = hh[hh.index.isin(medidas)].sort_values("cola", ascending=False).head(3)
    filas.append({"Indicador": "Horas con MÁS carros esperando (entre las medidas)", "Resultado": ", ".join(rot(i) for i in cola_top.index),
                  "Detalle": " · ".join(f"{rot(i)}: {v:.1f} carros en cola por ciclo".replace(".", ",") for i, v in cola_top["cola"].items())})
    sem = tablas["Semáforos"].set_index("Semáforo")
    colas_t = tablas["Colas"]
    ct = colas_t[colas_t["Periodo"] == "Todo"].set_index("Semáforo")
    s_mas = ct["% de ciclos con cola"].idxmax(); s_menos = ct["% de ciclos con cola"].idxmin()
    filas.append({"Indicador": "Entrada con MÁS espera", "Resultado": f"{s_mas} · {sem.loc[s_mas, 'Ubicación']}",
                  "Detalle": f"queda cola en el {ct.loc[s_mas, '% de ciclos con cola']:.0f} % de los ciclos; máximo "
                             f"{int(ct.loc[s_mas, 'Máxima (veh)'])} carros".replace(".", ",")})
    filas.append({"Indicador": "Entrada con MENOS espera", "Resultado": f"{s_menos} · {sem.loc[s_menos, 'Ubicación']}",
                  "Detalle": f"queda cola solo en el {ct.loc[s_menos, '% de ciclos con cola']:.0f} % de los ciclos".replace(".", ",")})
    s_flujo = sem["Vehículos que pasan"].idxmax()
    filas.append({"Indicador": "Semáforo que mueve más carros", "Resultado": f"{s_flujo} · {sem.loc[s_flujo, 'Ubicación']}",
                  "Detalle": f"{sem.loc[s_flujo, '% del total']:.1f} % del total, {sem.loc[s_flujo, 'Prom. por ciclo']:.1f} carros por ciclo".replace(".", ",")})
    cap = tablas["Capacidad"]
    pico = cap[cap["Periodo"] == "Pico"] if (cap["Periodo"] == "Pico").any() else cap
    fila_lim = pico.loc[pico["Uso de capacidad (%)"].idxmax()]
    margen = 100 * (100 / fila_lim["Uso de capacidad (%)"] - 1)
    filas.append({"Indicador": "Margen antes de saturarse (hora pico)", "Resultado": f"{margen:.0f} % más tráfico".replace(".", ","),
                  "Detalle": f"el primero en saturarse sería {fila_lim['Semáforo']} · {fila_lim['Ubicación']} "
                             f"(hoy usa el {fila_lim['Uso de capacidad (%)']:.0f} % de su capacidad)"})
    if h["dia"].nunique() > 1:
        por_dia = h.groupby(["repeticion", "dia"])["pasan"].sum().groupby("dia").mean()
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        d_max = por_dia.idxmax()
        filas.append({"Indicador": "Día con más tráfico del periodo",
                      "Resultado": f"{dias[d_max.weekday()]} {d_max:%d/%m/%Y}",
                      "Detalle": f"{por_dia.max():,.0f} vehículos; la diferencia entre días es pequeña porque todos los "
                                 "días usan los mismos datos de campo".replace(",", ".")})
    maximo = f"{top['veh'].iloc[0]:,.0f}".replace(",", ".")
    frases.append(f"Para transitar con menos carros conviene evitar {' y '.join(rot(i) for i in top.index[:2])}; "
                  f"en esas horas pasan hasta {maximo} vehículos por hora.")
    frases.append(f"La entrada con menos espera es {s_menos} ({sem.loc[s_menos, 'Ubicación']}) y la de más espera es "
                  f"{s_mas} ({sem.loc[s_mas, 'Ubicación']}).")
    frases.append(f"En hora pico el cruce aguanta cerca de {margen:.0f} % más tráfico antes de que "
                  f"{fila_lim['Semáforo']} ({fila_lim['Ubicación']}) se sature.")
    return pd.DataFrame(filas), frases


def flujo_por_franja(base: pd.DataFrame) -> pd.DataFrame:
    """Flujo observado en campo por franja horaria: vehículos por hora = pasan por ciclo × 3600 ÷ ciclo (s).

    Sirve para ver con los propios datos en qué franjas hay más movimiento.
    """
    b = base.copy()
    b["veh_h"] = b["pasan"] * 3600 / (b["verde"] + b["rojo"])
    g = b.groupby(["bloque", "semaforo"]).agg(veh_h=("veh_h", "mean"), ciclos=("pasan", "size"),
                                              periodo=("periodo", "first")).reset_index()
    t = g.pivot(index="bloque", columns="semaforo", values="veh_h").reindex(columns=SEMAFOROS)
    t.columns = [f"{s} (veh/h)" for s in t.columns]
    t["Ciclos medidos"] = g.groupby("bloque")["ciclos"].sum()
    t["Cruce completo (veh/h)"] = t[[f"{s} (veh/h)" for s in SEMAFOROS]].sum(axis=1, min_count=4)
    per = g.groupby("bloque")["periodo"].agg(lambda x: x.iloc[0] if x.nunique() == 1 else "Pico (S3 valle)")
    t.insert(0, "Periodo en el Excel", per)
    t = t.reset_index().rename(columns={"bloque": "Franja medida"})
    t["Puesto (más flujo = 1)"] = t["Cruce completo (veh/h)"].rank(ascending=False, method="min")
    return t


def _capacidad(semaforos, semilla, factor):
    filas, barridos = [], []
    for p in PERIODOS:
        _, res = simular(semaforos, Escenario(periodo=p, ciclos=500, semilla=semilla, factor_demanda=factor))
        for _, r in res.iterrows():
            filas.append({
                "Periodo": p, "Semáforo": r["semaforo"], "Ubicación": r["ubicacion"],
                "Pasan máx. por verde": r["capacidad_ciclo"], "Ciclo (s)": r["ciclo_s"],
                "Capacidad (veh/h)": r["capacidad_hora"], "Demanda (veh/h)": r["demanda_hora"],
                "Uso de capacidad (%)": 100 * r["utilizacion"],
                "La demanda puede crecer hasta ×": 1 / r["utilizacion"],
                "Cola prom. (veh)": r["cola_prom"],
            })
        b = barrido_demanda(semaforos, p, semilla)
        b["periodo"] = p
        barridos.append(b)
    return pd.DataFrame(filas), pd.concat(barridos, ignore_index=True)


def _validacion(semaforos, base, semilla):
    filas = []
    for p in PERIODOS:
        _, r_val = simular(semaforos, Escenario(periodo=p, ciclos=1000, semilla=semilla))
        for _, r in r_val.iterrows():
            obs = base[(base["semaforo"] == r["semaforo"]) & (base["periodo"] == p)]
            o = obs["pasan"].mean()
            filas.append({"Periodo": p, "Semáforo": r["semaforo"], "Pasan observado": o,
                          "Pasan simulado": r["pasan_prom"],
                          "Error (%)": abs(r["pasan_prom"] - o) / o * 100,
                          "Cola observada": obs["quedan"].mean(), "Cola simulada": r["cola_prom"]})
    return pd.DataFrame(filas)


def construir(res: ResultadoPrediccion, semaforos: dict[str, DatosSemaforo], base: pd.DataFrame,
              horas_bloque: int = 2, ciclos_bloque: int = 10) -> Paquete:
    e = res.escenario
    sem = reporte_semaforos(res)
    total = sem["pasan"].sum()
    por_rep = res.horas.groupby("repeticion")["pasan"].sum()
    ic_total = Z * por_rep.std(ddof=1) / math.sqrt(e.repeticiones) if e.repeticiones > 1 else 0.0
    horas_sim = (e.fin - e.inicio).total_seconds() / 3600
    ciclos_tot = int(res.info_semaforos["ciclos"].sum())
    vp = reporte_valle_pico(res)

    kpis = {
        "Vehículos que pasan": total, "Margen ± IC 99 %": ic_total, "Horas simuladas": horas_sim,
        "Promedio por hora": total / horas_sim if horas_sim else 0, "Ciclos": ciclos_tot,
        "Números pseudoaleatorios": res.numeros_usados, "Repeticiones": e.repeticiones,
    }
    for _, r in vp.iterrows():
        kpis[f"Pasan en hora {r['periodo'].lower()}"] = r["pasan"]
        kpis[f"Promedio por hora {r['periodo'].lower()}"] = r["prom_por_hora"]

    t = {}
    t["Parámetros"] = pd.DataFrame([
        ("Periodo desde", e.inicio.strftime("%d/%m/%Y %H:%M")),
        ("Periodo hasta", e.fin.strftime("%d/%m/%Y %H:%M")),
        ("Horas simuladas", f"{horas_sim:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")),
        ("Ciclos (4 semáforos)", f"{ciclos_tot:,}".replace(",", ".")),
        ("Números pseudoaleatorios", f"{res.numeros_usados:,}".replace(",", ".")),
        ("Repeticiones", e.repeticiones),
        ("Semilla del generador", e.semilla),
        ("Generador", "X(n+1) = 16807 · X(n) mod 2147483647"),
        ("Demanda (× la observada)", e.factor_demanda),
        ("Horas pico (fijas, del Excel de campo)", texto_horas_pico()),
        ("Horas valle", "todas las demás"),
        ("Nivel de confianza", "99 % (Z = 2,576)"),
        ("Error relativo objetivo", "≤ 1 %"),
        ("Bloques de horas del reporte", f"{horas_bloque} h"),
        ("Bloques de ciclos del reporte", f"{ciclos_bloque} ciclos"),
        ("Generado el", datetime.now().strftime("%d/%m/%Y %H:%M")),
    ], columns=["Parámetro", "Valor"]).astype(str)

    t["Semáforos"] = pd.DataFrame([{
        "Semáforo": r["semaforo"], "Ubicación": r["ubicacion"], "Verde (s)": r["verde_s"],
        "Rojo (s)": r["rojo_s"], "Ciclo (s)": r["ciclo_s"], "Capacidad por verde": r["capacidad_ciclo"],
        "Ciclos": r["ciclos"], "Vehículos que pasan": r["pasan"], "± IC 99 %": r["ic"],
        "% del total": r["pct_del_total"], "Prom. por ciclo": r["prom_por_ciclo"],
        "Cola prom. (veh)": r["cola_prom"]} for _, r in sem.iterrows()])

    t["Semáforo y periodo"] = _por_semaforo_y_periodo(res)

    vp_t = vp.rename(columns={"periodo": "Periodo", "horas": "Horas", "pasan": "Vehículos que pasan",
                              "pct_del_total": "% del total", "prom_por_hora": "Prom. por hora"})
    vp_t = vp_t.rename(columns={f"{s}_por_ciclo": f"{s} prom. por ciclo" for s in SEMAFOROS})
    t["Valle vs pico"] = vp_t

    b = reporte_bloques(res, horas_bloque)
    t[f"Bloques de {horas_bloque} h"] = b.drop(columns=["bloque_ini"]).rename(columns={
        "bloque": "Bloque", "total": "Total que pasan", "ic": "± IC 99 %", "pct_del_total": "% del total",
        "ciclos": "Ciclos", "prom_por_ciclo": "Prom. por ciclo", "en_valle": "En hora valle",
        "pct_valle": "% valle", "en_pico": "En hora pico", "pct_pico": "% pico"})

    hr = reporte_horas(res)
    t["Por hora"] = hr.rename(columns={
        "hora": "Hora", "periodo": "Periodo", "total": "Total que pasan", "ic": "± IC 99 %",
        "ciclos": "Ciclos", "cola_prom": "Cola prom. (veh)", "pct_del_total": "% del total"})

    bc = reporte_bloques_ciclos(res, ciclos_bloque)
    t[f"Bloques de {ciclos_bloque} ciclos"] = bc.rename(columns={
        "semaforo": "Semáforo", "ciclos": "Ciclos", "desde": "Desde", "hasta": "Hasta", "periodo": "Periodo",
        "pasan": "Vehículos que pasan", "ic": "± IC 99 %", "pct_del_semaforo": "% del semáforo",
        "prom_por_ciclo": "Prom. por ciclo", "llegadas": "Llegadas", "cola_prom": "Cola prom. (veh)"})

    cap, barrido = _capacidad(semaforos, e.semilla, e.factor_demanda)
    t["Capacidad"] = cap
    t["Validación"] = _validacion(semaforos, base, e.semilla)

    t["Por ciclo"] = res.ciclos.drop(columns=["pasan_var"]).rename(columns={
        "semaforo": "Semáforo", "ciclo": "Ciclo", "inicio": "Inicio del ciclo", "periodo": "Periodo",
        "llegadas": "Llegadas", "en_espera": "En espera", "rezagados": "Rezagados", "capacidad": "Capacidad",
        "pasan": "Pasan", "quedan": "Quedan", "pasan_prom": "Pasan (prom. repeticiones)",
        "quedan_prom": "Quedan (prom. repeticiones)", "llegadas_prom": "Llegadas (prom. repeticiones)"})

    t["Datos de campo (resumen)"] = base.groupby(["semaforo", "periodo"]).agg(
        Ciclos=("pasan", "size"), **{"Pasan total": ("pasan", "sum"), "Pasan prom.": ("pasan", "mean"),
                                     "Pasan máx.": ("pasan", "max"), "Quedan prom.": ("quedan", "mean"),
                                     "Llegadas prom.": ("llegadas", "mean")}
    ).reset_index().rename(columns={"semaforo": "Semáforo", "periodo": "Periodo"})
    t["Flujo por franja medida"] = flujo_por_franja(base)
    t["Precisión"], conv = precision(res)
    t["Mapa de calor (día × hora)"] = mapa_calor(res)
    t["Colas"] = colas(res)
    t["Prueba de ajuste de llegadas"] = prueba_ajuste_llegadas(res, semaforos)
    t["Números pseudoaleatorios"] = secuencia_numeros(res, semaforos)
    t["Datos de campo"] = base.rename(columns={
        "semaforo": "Semáforo", "ubicacion": "Ubicación", "jornada": "Jornada", "periodo": "Periodo",
        "bloque": "Bloque horario", "iteracion": "Iteración", "pasan": "Pasan", "quedan": "Quedan",
        "verde": "Verde (s)", "rojo": "Rojo (s)", "quedan_anterior": "Quedan ciclo anterior",
        "llegadas": "Llegadas"})

    notas = {
        "Semáforo y periodo": "Cada semáforo separado en hora valle y hora pico.",
        "Valle vs pico": "Todas las horas valle frente a todas las horas pico del periodo simulado.",
        f"Bloques de {horas_bloque} h": "Bloques de horas desde la medianoche. Cuántos vehículos pasan, qué % del "
                                         "total representa y cuánto de eso fue en hora valle y en hora pico.",
        "Por hora": "Vehículos que pasan en cada hora del periodo, por semáforo. 'Valle y pico' = hora que "
                    "tiene media hora de cada una (por ejemplo 18:00–19:00).",
        f"Bloques de {ciclos_bloque} ciclos": "Ciclos agrupados de a " + str(ciclos_bloque) + " por semáforo.",
        "Capacidad": "Capacidad (veh/h) = pasan máx. por verde × 3600 ÷ ciclo. Uso = llegadas prom. ÷ capacidad "
                     "por verde. Si el uso llega a 100 %, el semáforo se satura.",
        "Validación": "Error = |simulado − observado| ÷ observado × 100 (1000 ciclos por semáforo).",
        "Números pseudoaleatorios": (
            f"Secuencia de la repetición 1, en el orden en que se generó, desde la semilla {e.semilla}. "
            "Cada número sale del anterior: X(n) = 16807 · X(n−1) mod 2147483647, y U = X(n) ÷ 2147483647. "
            "En cada ciclo se usan 2: U1 se busca en la tabla de llegadas del periodo (valle o pico) y dice cuántos "
            "carros llegan; U2 se busca en la tabla de 'Quedan' y dice cuántos llegan tarde y no alcanzan a pasar. "
            "Con eso: en espera = cola anterior + llegadas; pasan = mín(en espera − rezagados, capacidad); "
            "quedan = en espera − pasan. "
            + (f"Las repeticiones 2 a {e.repeticiones} siguen la misma secuencia a continuación "
               f"({2 * int(res.info_semaforos['ciclos'].sum())} números cada una)." if e.repeticiones > 1 else "")),
    }
    t["Conclusiones"], frases = conclusiones(res, t)
    notas["Conclusiones"] = " ".join(frases)
    graficos = {"bloques": b, "horas": hr, "bloques_ciclos": bc, "barrido": barrido, "convergencia": conv,
                "ciclos": res.ciclos[["semaforo", "periodo", "pasan", "quedan", "llegadas"]]}
    fila_tot = t["Precisión"].iloc[0]
    kpis["Error relativo IC 99 % (%)"] = fila_tot["Error relativo (%)"]
    kpis["Repeticiones para error ≤ 1 %"] = fila_tot["Repeticiones para error ≤ 1 %"]
    notas["Mapa de calor"] = ("Vehículos que pasan en cada hora (columnas) de cada día (filas), sumando los 4 semáforos. "
                              "Entre más oscuro, más tráfico. Horas fuera del periodo simulado quedan en blanco.")
    notas["Cajas"] = ("Cada caja resume los vehículos que pasan por ciclo: la línea del medio es la mediana, la caja va "
                      "del 25 % al 75 % de los ciclos y los bigotes muestran el rango normal; los puntos sueltos son "
                      "ciclos atípicos.")
    notas["Colas"] = ("Carros que quedan esperando al final de cada verde. El percentil 95 es la cola que no se supera "
                      "en el 95 % de los ciclos.")
    notas["Prueba de ajuste de llegadas"] = (
        "Comprueba que las llegadas que generó el simulador siguen la distribución medida en campo. "
        "FE = ciclos × probabilidad observada; se juntan valores hasta FE ≥ 5; X₀² = Σ(FO − FE)² ÷ FE con k − 1 "
        "grados de libertad. H₀: las llegadas simuladas siguen la distribución de campo (α = 0,01).")
    notas["Precisión"] = ("Con un nivel de confianza del 99 % (Z = 2,576): semiancho h = Z · s ÷ √R; error relativo = "
                          "h ÷ promedio; repeticiones necesarias para un error de 1 %: R* = (Z · s ÷ (0,01 · promedio))². "
                          "s es la desviación estándar del resultado entre las R repeticiones.")
    titulo = (f"Predicción del {e.inicio:%d/%m/%Y %H:%M} al {e.fin:%d/%m/%Y %H:%M}")
    return Paquete(titulo, kpis, t, notas, graficos, e.inicio, e.fin)
