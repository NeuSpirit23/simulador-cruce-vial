"""Predicción del tránsito para cualquier rango de fechas y horas.

El usuario escoge desde qué día y hora hasta qué día y hora quiere predecir.
Cada ciclo de cada semáforo se ubica en el reloj: si empieza en una hora pico
se usan las tablas de frecuencias de hora pico; si no, las de hora valle.

Horas pico fijas (las que se midieron en campo): 12:00–13:00 y 17:00–18:00.
El resto del día se toma como hora valle.

La simulación se repite R veces (repeticiones). Cada repetición usa números
pseudoaleatorios distintos del mismo generador, así que el resultado final es
el promedio de las R repeticiones, con su intervalo de confianza del 95 %.
"""

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from .datos import DatosSemaforo
from .generador import GeneradorCongruencial
from .modelo import capacidad_con_verde, tabla_intervalos

HORAS_PICO = (12, 17)          # la hora h cubre de h:00 a h:59
MAX_CICLOS_TOTALES = 4_000_000  # límite de cálculo (ciclos × repeticiones)


def periodo_de_hora(hora: int) -> str:
    return "Pico" if hora in HORAS_PICO else "Valle"


def texto_horas_pico() -> str:
    return " y ".join(f"{h:02d}:00–{h + 1:02d}:00" for h in HORAS_PICO)


@dataclass
class EscenarioPrediccion:
    inicio: datetime
    fin: datetime
    repeticiones: int = 10
    semilla: int = 12345
    factor_demanda: float = 1.0
    verdes: dict | None = None


@dataclass
class ResultadoPrediccion:
    escenario: EscenarioPrediccion
    ciclos: pd.DataFrame          # detalle ciclo por ciclo (repetición 1)
    horas: pd.DataFrame           # totales por hora, semáforo y repetición
    numeros_usados: int
    info_semaforos: pd.DataFrame = field(default_factory=pd.DataFrame)


def ciclos_estimados(semaforos: dict[str, DatosSemaforo], esc: EscenarioPrediccion) -> int:
    seg = (esc.fin - esc.inicio).total_seconds()
    total = 0
    for s, sem in semaforos.items():
        verde = (esc.verdes or {}).get(s, sem.verde)
        total += int(seg // (verde + sem.rojo))
    return total * esc.repeticiones


def _tablas(valores: list[int]):
    t = tabla_intervalos(valores)
    return t["valor"].to_numpy(), t["hasta"].to_numpy()


def _sortear_vector(valores, hastas, u):
    idx = np.searchsorted(hastas, u, side="right")
    return valores[np.minimum(idx, len(valores) - 1)]


def predecir(semaforos: dict[str, DatosSemaforo], esc: EscenarioPrediccion) -> ResultadoPrediccion:
    if esc.fin <= esc.inicio:
        raise ValueError("La fecha y hora final debe ser posterior a la inicial.")
    if ciclos_estimados(semaforos, esc) > MAX_CICLOS_TOTALES:
        raise ValueError("El rango es demasiado grande para tantas repeticiones. "
                         "Reduzca el rango o el número de repeticiones.")

    gen = GeneradorCongruencial(esc.semilla)
    segundos_total = (esc.fin - esc.inicio).total_seconds()
    inicio_dia = esc.inicio.replace(hour=0, minute=0, second=0, microsecond=0)
    seg_desde_medianoche = (esc.inicio - inicio_dia).total_seconds()

    tablas = {}
    for s, sem in semaforos.items():
        tablas[s] = {p: (_tablas(sem.llegadas[p]), _tablas(sem.quedan[p])) for p in ("Valle", "Pico")}

    filas_detalle = []
    filas_horas = []
    info = []
    usados = 0

    for rep in range(1, esc.repeticiones + 1):
        for s, sem in semaforos.items():
            verde = (esc.verdes or {}).get(s, sem.verde)
            cap = capacidad_con_verde(sem, verde)
            ciclo = verde + sem.rojo
            n = int(segundos_total // ciclo)
            if n == 0:
                continue
            if rep == 1:
                info.append({"semaforo": s, "ubicacion": sem.ubicacion, "verde_s": verde,
                             "rojo_s": sem.rojo, "ciclo_s": ciclo, "capacidad_ciclo": cap,
                             "ciclos": n})

            k = np.arange(n)
            seg_inicio = seg_desde_medianoche + k * ciclo          # desde la medianoche del día inicial
            hora_abs = (seg_inicio // 3600).astype(np.int64)        # hora absoluta desde ese día
            hora_dia = hora_abs % 24
            es_pico = np.isin(hora_dia, HORAS_PICO)

            u = np.array(gen.lista(2 * n))
            usados += 2 * n
            u1, u2 = u[0::2], u[1::2]

            (lv_v, lv_h), (qv_v, qv_h) = tablas[s]["Valle"]
            (lp_v, lp_h), (qp_v, qp_h) = tablas[s]["Pico"]
            lleg = np.where(es_pico, _sortear_vector(lp_v, lp_h, u1), _sortear_vector(lv_v, lv_h, u1))
            lleg = np.rint(lleg * esc.factor_demanda).astype(np.int64)
            rez = np.where(es_pico, _sortear_vector(qp_v, qp_h, u2), _sortear_vector(qv_v, qv_h, u2))
            rez = np.minimum(rez, lleg)

            pasan = np.empty(n, dtype=np.int64)
            quedan = np.empty(n, dtype=np.int64)
            espera = np.empty(n, dtype=np.int64)
            cola = 0
            for i in range(n):          # la cola depende del ciclo anterior
                e = cola + int(lleg[i])
                p = min(e - int(rez[i]), cap)
                cola = e - p
                espera[i], pasan[i], quedan[i] = e, p, cola

            # Totales por hora (todas las repeticiones)
            horas_unicas, inv = np.unique(hora_abs, return_inverse=True)
            n_ciclos = np.bincount(inv)
            filas_horas.append(pd.DataFrame({
                "repeticion": rep, "semaforo": s,
                "hora": [inicio_dia + pd.Timedelta(hours=int(h)) for h in horas_unicas],
                "periodo": [periodo_de_hora(int(h) % 24) for h in horas_unicas],
                "ciclos": n_ciclos,
                "llegadas": np.bincount(inv, weights=lleg),
                "pasan": np.bincount(inv, weights=pasan),
                "cola_suma": np.bincount(inv, weights=quedan),
            }))

            if rep == 1:
                filas_detalle.append(pd.DataFrame({
                    "semaforo": s, "ciclo": k + 1,
                    "inicio": [esc.inicio + pd.Timedelta(seconds=float(x)) for x in k * ciclo],
                    "periodo": np.where(es_pico, "Pico", "Valle"),
                    "U1": u1, "llegadas": lleg, "en_espera": espera, "U2": u2,
                    "rezagados": rez, "capacidad": cap, "pasan": pasan, "quedan": quedan,
                }))

    horas = pd.concat(filas_horas, ignore_index=True)
    horas["cola_prom"] = horas["cola_suma"] / horas["ciclos"]
    return ResultadoPrediccion(esc, pd.concat(filas_detalle, ignore_index=True), horas,
                               usados, pd.DataFrame(info))
