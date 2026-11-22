"""Arma TODOS los reportes de una simulación en un solo paquete.

La app, el Excel y el PDF usan exactamente las mismas tablas, así que siempre
muestran la misma información. Todos los reportes incluyen hora valle y hora
pico al mismo tiempo.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from .datos import PERIODOS, SEMAFOROS, DatosSemaforo
from .modelo import Escenario, barrido_demanda, simular
from .prediccion import FRANJA_MIN, ResultadoPrediccion, texto_horas_pico
from .reportes import (reporte_bloques, reporte_bloques_ciclos, reporte_horas, reporte_semaforos,
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
            ic = 1.96 * rep["pasan"].std(ddof=1) / math.sqrt(r) if r > 1 else 0.0
            horas = d["hora"].nunique() * FRANJA_MIN / 60
            filas.append({
                "Semáforo": s, "Periodo": p, "Horas": horas, "Ciclos": m["ciclos"],
                "Vehículos que pasan": m["pasan"], "± IC 95 %": ic,
                "% del semáforo": 100 * m["pasan"] / total_s if total_s else 0,
                "Prom. por ciclo": m["pasan"] / m["ciclos"], "Prom. por hora": m["pasan"] / horas,
                "Llegadas": m["llegadas"], "Cola prom. (veh)": m["cola_suma"] / m["ciclos"],
            })
    return pd.DataFrame(filas)


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
    ic_total = 1.96 * por_rep.std(ddof=1) / math.sqrt(e.repeticiones) if e.repeticiones > 1 else 0.0
    horas_sim = (e.fin - e.inicio).total_seconds() / 3600
    ciclos_tot = int(res.info_semaforos["ciclos"].sum())
    vp = reporte_valle_pico(res)

    kpis = {
        "Vehículos que pasan": total, "Margen ± IC 95 %": ic_total, "Horas simuladas": horas_sim,
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
        ("Bloques de horas del reporte", f"{horas_bloque} h"),
        ("Bloques de ciclos del reporte", f"{ciclos_bloque} ciclos"),
        ("Generado el", datetime.now().strftime("%d/%m/%Y %H:%M")),
    ], columns=["Parámetro", "Valor"]).astype(str)

    t["Semáforos"] = pd.DataFrame([{
        "Semáforo": r["semaforo"], "Ubicación": r["ubicacion"], "Verde (s)": r["verde_s"],
        "Rojo (s)": r["rojo_s"], "Ciclo (s)": r["ciclo_s"], "Capacidad por verde": r["capacidad_ciclo"],
        "Ciclos": r["ciclos"], "Vehículos que pasan": r["pasan"], "± IC 95 %": r["ic95"],
        "% del total": r["pct_del_total"], "Prom. por ciclo": r["prom_por_ciclo"],
        "Cola prom. (veh)": r["cola_prom"]} for _, r in sem.iterrows()])

    t["Semáforo y periodo"] = _por_semaforo_y_periodo(res)

    vp_t = vp.rename(columns={"periodo": "Periodo", "horas": "Horas", "pasan": "Vehículos que pasan",
                              "pct_del_total": "% del total", "prom_por_hora": "Prom. por hora"})
    vp_t = vp_t.rename(columns={f"{s}_por_ciclo": f"{s} prom. por ciclo" for s in SEMAFOROS})
    t["Valle vs pico"] = vp_t

    b = reporte_bloques(res, horas_bloque)
    t[f"Bloques de {horas_bloque} h"] = b.drop(columns=["bloque_ini"]).rename(columns={
        "bloque": "Bloque", "total": "Total que pasan", "ic95": "± IC 95 %", "pct_del_total": "% del total",
        "ciclos": "Ciclos", "prom_por_ciclo": "Prom. por ciclo", "en_valle": "En hora valle",
        "pct_valle": "% valle", "en_pico": "En hora pico", "pct_pico": "% pico"})

    hr = reporte_horas(res)
    t["Por hora"] = hr.rename(columns={
        "hora": "Hora", "periodo": "Periodo", "total": "Total que pasan", "ic95": "± IC 95 %",
        "ciclos": "Ciclos", "cola_prom": "Cola prom. (veh)", "pct_del_total": "% del total"})

    bc = reporte_bloques_ciclos(res, ciclos_bloque)
    t[f"Bloques de {ciclos_bloque} ciclos"] = bc.rename(columns={
        "semaforo": "Semáforo", "ciclos": "Ciclos", "desde": "Desde", "hasta": "Hasta", "periodo": "Periodo",
        "pasan": "Vehículos que pasan", "ic95": "± IC 95 %", "pct_del_semaforo": "% del semáforo",
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
    }
    graficos = {"bloques": b, "horas": hr, "bloques_ciclos": bc, "barrido": barrido}
    titulo = (f"Predicción del {e.inicio:%d/%m/%Y %H:%M} al {e.fin:%d/%m/%Y %H:%M}")
    return Paquete(titulo, kpis, t, notas, graficos, e.inicio, e.fin)
