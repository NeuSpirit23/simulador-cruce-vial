"""Explorador de resultados: elegir un tramo (de hora a hora o de ciclo a ciclo) y una frecuencia
(cada 30 min, 1 h, 2 h… o cada N ciclos) y ver los datos agrupados así.

Trabaja sobre el detalle por ciclo de la simulación (`ResultadoPrediccion.ciclos`), usando los
promedios de cada ciclo entre todas las repeticiones (pasan_prom, llegadas_prom, quedan_prom).
"""

from __future__ import annotations

import pandas as pd

FRECUENCIAS_HORA = {"30 min": 30, "1 h": 60, "2 h": 120, "3 h": 180, "4 h": 240, "6 h": 360, "12 h": 720,
                    "1 día": 1440}


def _etiqueta(ini: pd.Timestamp, fin: pd.Timestamp, varios_dias: bool) -> str:
    """'12:00–14:00' (o '22/11 12:00–14:00' si el tramo abarca varios días). Medianoche final = 24:00."""
    fin_txt = "24:00" if fin.normalize() > ini.normalize() and fin.strftime("%H:%M") == "00:00" else fin.strftime("%H:%M")
    if fin.normalize() > ini.normalize() and fin_txt != "24:00":
        fin_txt = fin.strftime("%d/%m %H:%M")
    return (ini.strftime("%d/%m %H:%M") if varios_dias else ini.strftime("%H:%M")) + "–" + fin_txt


def explorar(ciclos: pd.DataFrame, modo: str, semaforos: list[str], *, desde=None, hasta=None,
             frecuencia_min: int = 120, ciclo_desde: int = 1, ciclo_hasta: int = 10, cada_ciclos: int = 10,
             por_semaforo: bool = False) -> tuple[pd.DataFrame, dict]:
    """Devuelve (tabla por intervalo, indicadores del tramo completo).

    modo = "horas": ciclos que empiezan en [desde, hasta), agrupados cada `frecuencia_min` minutos
                    contados desde la medianoche (0–2, 2–4, …).
    modo = "ciclos": ciclos número [ciclo_desde, ciclo_hasta], agrupados cada `cada_ciclos`.
    """
    c = ciclos[ciclos["semaforo"].isin(semaforos)].copy()
    if modo == "horas":
        c = c[(c["inicio"] >= pd.Timestamp(desde)) & (c["inicio"] < pd.Timestamp(hasta))]
        paso = pd.Timedelta(minutes=frecuencia_min)
        dia = c["inicio"].dt.normalize()
        c["_ini"] = dia + ((c["inicio"] - dia) // paso) * paso
        varios = c["inicio"].dt.date.nunique() > 1 if len(c) else False
        unicos = c["_ini"].drop_duplicates()
        nombres = {a: _etiqueta(a, a + paso, varios) for a in unicos}   # una etiqueta por intervalo, no por ciclo
        c["Intervalo"] = c["_ini"].map(nombres)
        claves = ["_ini", "Intervalo"]
    else:
        c = c[(c["ciclo"] >= ciclo_desde) & (c["ciclo"] <= ciclo_hasta)]
        c["_ini"] = ciclo_desde + ((c["ciclo"] - ciclo_desde) // cada_ciclos) * cada_ciclos
        nombres = {a: f"Ciclos {a}–{min(a + cada_ciclos - 1, ciclo_hasta)}" for a in c["_ini"].unique()}
        c["Intervalo"] = c["_ini"].map(nombres)
        claves = ["_ini", "Intervalo"]
    if por_semaforo:
        claves = claves + ["semaforo"]
    if c.empty:
        return pd.DataFrame(), {}
    c["_pico"] = c["pasan_prom"].where(c["periodo"] == "Pico", 0.0)
    t = c.groupby(claves, sort=True).agg(**{
        "Inicia": ("inicio", "min"), "Ciclos": ("ciclo", "size"), "Llegan (veh)": ("llegadas_prom", "sum"),
        "Pasan (veh)": ("pasan_prom", "sum"), "Pasan en pico": ("_pico", "sum"),
        "Quedan prom. (veh/ciclo)": ("quedan_prom", "mean"), "Cola máx. (veh, rep. 1)": ("quedan", "max"),
    }).reset_index()
    t.insert(t.columns.get_loc("Pasan en pico"), "Pasan en valle", t["Pasan (veh)"] - t["Pasan en pico"])
    t.insert(t.columns.get_loc("Pasan en pico") + 1, "% en pico",
             (100 * t["Pasan en pico"] / t["Pasan (veh)"].where(t["Pasan (veh)"] != 0)).fillna(0.0))
    if modo == "horas":
        horas = frecuencia_min / 60
        t["Veh/h"] = t["Pasan (veh)"] / horas
        # Hora de inicio del intervalo para graficar
        t = t.rename(columns={"_ini": "Desde"}).drop(columns="Inicia")
    else:
        t = t.drop(columns="_ini")
    if por_semaforo:
        t = t.rename(columns={"semaforo": "Semáforo"})
    t["Ciclos"] = t["Ciclos"].astype(int)

    pasan = c["pasan_prom"].sum()
    pico = c.loc[c["periodo"] == "Pico", "pasan_prom"].sum()
    ind = {
        "pasan": pasan, "llegan": c["llegadas_prom"].sum(), "pico": pico, "valle": pasan - pico,
        "ciclos": len(c), "cola_prom": c["quedan_prom"].mean(), "cola_max": int(c["quedan"].max()),
        "intervalos": t["Intervalo"].nunique(),
        "inicio": c["inicio"].min(), "fin": c["inicio"].max(),
    }
    if modo == "horas":
        horas_tramo = (pd.Timestamp(hasta) - pd.Timestamp(desde)).total_seconds() / 3600
        ind["veh_h"] = pasan / horas_tramo if horas_tramo else 0.0
        mayor = t.groupby("Intervalo", sort=False)["Pasan (veh)"].sum()
        ind["intervalo_max"] = mayor.idxmax()
        ind["intervalo_min"] = mayor.idxmin()
    return t, ind
