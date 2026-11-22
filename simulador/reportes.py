"""Reportes de la predicción: por bloques de horas, por hora, por ciclo y valle vs pico.

Todos los valores son el PROMEDIO de las repeticiones. Cuando hay más de una
repetición se agrega el intervalo de confianza del 95 %:

    IC 95 % = promedio ± 1,96 · (desviación estándar / √R)
"""

import math

import pandas as pd

from .datos import SEMAFOROS
from .prediccion import FRANJA_MIN, ResultadoPrediccion


def _promedio_repeticiones(horas: pd.DataFrame, claves: list[str]) -> pd.DataFrame:
    """Suma por repetición y luego promedia entre repeticiones."""
    por_rep = horas.groupby(["repeticion"] + claves, as_index=False)[["ciclos", "pasan", "llegadas", "cola_suma"]].sum()
    g = por_rep.groupby(claves)
    res = g[["ciclos", "pasan", "llegadas", "cola_suma"]].mean().reset_index()
    sd = g["pasan"].std(ddof=1).fillna(0).reset_index(drop=True)
    r = horas["repeticion"].nunique()
    res["ic95"] = 1.96 * sd / math.sqrt(r) if r > 1 else 0.0
    return res



def reporte_bloques(res: ResultadoPrediccion, horas_bloque: int = 2) -> pd.DataFrame:
    """Bloques de N horas (00–02, 02–04, …): cuántos pasan, % del total, valle y pico."""
    h = res.horas.copy()
    h["dia"] = h["hora"].dt.normalize()
    h["bloque_ini"] = h["dia"] + pd.to_timedelta((h["hora"].dt.hour // horas_bloque) * horas_bloque, unit="h")

    # Total por bloque y repetición (para el intervalo de confianza)
    tot = h.groupby(["repeticion", "bloque_ini"], as_index=False)[["pasan", "ciclos"]].sum()
    g = tot.groupby("bloque_ini")
    r = h["repeticion"].nunique()
    base = g["pasan"].mean().rename("total").to_frame()
    base["ciclos"] = g["ciclos"].mean()
    base["ic95"] = (1.96 * g["pasan"].std(ddof=1).fillna(0) / math.sqrt(r)) if r > 1 else 0.0

    # Por semáforo
    sem = h.groupby(["repeticion", "bloque_ini", "semaforo"], as_index=False)["pasan"].sum()
    sem = sem.groupby(["bloque_ini", "semaforo"])["pasan"].mean().unstack("semaforo")
    sem = sem.reindex(columns=SEMAFOROS).fillna(0)

    # Valle y pico dentro del bloque
    vp = h.groupby(["repeticion", "bloque_ini", "periodo"], as_index=False)["pasan"].sum()
    vp = vp.groupby(["bloque_ini", "periodo"])["pasan"].mean().unstack("periodo")
    vp = vp.reindex(columns=["Valle", "Pico"]).fillna(0)

    out = sem.join(base).join(vp.rename(columns={"Valle": "en_valle", "Pico": "en_pico"})).reset_index()
    out["bloque_fin"] = out["bloque_ini"] + pd.Timedelta(hours=horas_bloque)
    total_general = out["total"].sum()
    out["pct_del_total"] = 100 * out["total"] / total_general if total_general else 0
    out["prom_por_ciclo"] = out["total"] / out["ciclos"]
    out["pct_valle"] = 100 * out["en_valle"] / out["total"].where(out["total"] > 0, 1)
    out["pct_pico"] = 100 * out["en_pico"] / out["total"].where(out["total"] > 0, 1)
    out["bloque"] = (out["bloque_ini"].dt.strftime("%d/%m/%Y %H:%M") + " – "
                     + out["bloque_fin"].dt.strftime("%H:%M"))
    return out[["bloque", "bloque_ini"] + SEMAFOROS +
               ["total", "ic95", "pct_del_total", "ciclos", "prom_por_ciclo",
                "en_valle", "pct_valle", "en_pico", "pct_pico"]]


def _a_horas(horas: pd.DataFrame) -> pd.DataFrame:
    """Junta las franjas de 30 min en horas. Si una hora tiene franjas valle y pico, queda 'Valle y pico'."""
    h = horas.copy()
    h["hora"] = h["hora"].dt.floor("h")
    etiqueta = h.groupby("hora")["periodo"].agg(lambda x: x.iloc[0] if x.nunique() == 1 else "Valle y pico")
    h = h.groupby(["repeticion", "semaforo", "hora"], as_index=False)[["ciclos", "llegadas", "pasan", "cola_suma"]].sum()
    h["periodo"] = h["hora"].map(etiqueta)
    return h


def reporte_horas(res: ResultadoPrediccion) -> pd.DataFrame:
    hh = _a_horas(res.horas)
    p = _promedio_repeticiones(hh, ["hora", "periodo", "semaforo"])
    tabla = p.pivot_table(index=["hora", "periodo"], columns="semaforo", values="pasan").reindex(columns=SEMAFOROS).fillna(0)
    tabla["total"] = tabla[SEMAFOROS].sum(axis=1)
    tot = _promedio_repeticiones(hh, ["hora"]).set_index("hora")
    tabla = tabla.reset_index().set_index("hora")
    tabla["ic95"] = tot["ic95"]
    tabla["ciclos"] = tot["ciclos"]
    tabla["cola_prom"] = tot["cola_suma"] / tot["ciclos"]
    tabla = tabla.reset_index()
    tabla["pct_del_total"] = 100 * tabla["total"] / tabla["total"].sum()
    return tabla


def reporte_valle_pico(res: ResultadoPrediccion) -> pd.DataFrame:
    """Comparación de todas las horas valle frente a todas las horas pico."""
    h = res.horas
    filas = []
    total = h.groupby("repeticion")["pasan"].sum().mean()
    for periodo in ("Valle", "Pico"):
        d = h[h["periodo"] == periodo]
        if d.empty:
            continue
        horas_n = d["hora"].nunique() * FRANJA_MIN / 60
        por_rep = d.groupby("repeticion")["pasan"].sum()
        fila = {"periodo": periodo, "horas": horas_n, "pasan": por_rep.mean(),
                "pct_del_total": 100 * por_rep.mean() / total if total else 0,
                "prom_por_hora": por_rep.mean() / horas_n}
        for s in SEMAFOROS:
            ds = d[d["semaforo"] == s].groupby("repeticion")[["pasan", "ciclos"]].sum().mean()
            fila[f"{s}_por_ciclo"] = ds["pasan"] / ds["ciclos"] if ds["ciclos"] else 0
        filas.append(fila)
    return pd.DataFrame(filas)


def reporte_semaforos(res: ResultadoPrediccion) -> pd.DataFrame:
    p = _promedio_repeticiones(res.horas, ["semaforo"]).set_index("semaforo")
    info = res.info_semaforos.set_index("semaforo")
    out = info.join(p[["pasan", "ic95", "llegadas", "cola_suma"]])
    out["prom_por_ciclo"] = out["pasan"] / out["ciclos"]
    out["cola_prom"] = out["cola_suma"] / out["ciclos"]
    out["pct_del_total"] = 100 * out["pasan"] / out["pasan"].sum()
    return out.drop(columns=["cola_suma"]).reset_index()


def reporte_bloques_ciclos(res: ResultadoPrediccion, ciclos_bloque: int = 10) -> pd.DataFrame:
    """Ciclos agrupados de N en N (1–10, 11–20, …) por semáforo.

    Pasan = suma de los vehículos que pasan en esos N ciclos (promedio de las repeticiones).
    """
    c = res.ciclos.copy()
    c["grupo"] = (c["ciclo"] - 1) // ciclos_bloque
    r = res.escenario.repeticiones
    g = c.groupby(["semaforo", "grupo"])
    out = g.agg(ciclo_desde=("ciclo", "min"), ciclo_hasta=("ciclo", "max"),
                desde=("inicio", "min"), hasta=("inicio", "max"),
                pasan=("pasan_prom", "sum"), var=("pasan_var", "sum"),
                llegadas=("llegadas_prom", "sum"), cola_prom=("quedan_prom", "mean"),
                ciclos_pico=("periodo", lambda x: int((x == "Pico").sum()))).reset_index()
    out["ciclos"] = out["ciclo_hasta"] - out["ciclo_desde"] + 1
    out["ic95"] = 1.96 * (out["var"] ** 0.5) / math.sqrt(r) if r > 1 else 0.0
    out["prom_por_ciclo"] = out["pasan"] / out["ciclos"]
    out["pct_del_semaforo"] = 100 * out["pasan"] / out.groupby("semaforo")["pasan"].transform("sum")
    out["ciclos"] = out["ciclo_desde"].astype(str) + "–" + out["ciclo_hasta"].astype(str)
    out["periodo"] = out.apply(lambda x: "Pico" if x["ciclos_pico"] == x["ciclo_hasta"] - x["ciclo_desde"] + 1
                               else ("Valle" if x["ciclos_pico"] == 0 else "Valle y pico"), axis=1)
    return out[["semaforo", "ciclos", "desde", "hasta", "periodo", "pasan", "ic95", "pct_del_semaforo",
                "prom_por_ciclo", "llegadas", "cola_prom"]]
