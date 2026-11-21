"""Modelo de simulación del cruce vial de 4 semáforos.

Idea general (ciclo por ciclo, para cada semáforo):

1. Llegan vehículos. La cantidad se sortea con un número pseudoaleatorio U1
   usando la tabla de frecuencias de las llegadas observadas en campo
   (codificación por intervalos, igual que en el método de los 11 pasos).
2. Se suman a los que ya estaban esperando:
       en_espera = cola_anterior + llegadas
3. Algunos llegan cuando el verde ya se está acabando y no alcanzan a pasar
   aunque haya espacio ("rezagados"). Su cantidad se sortea con U2 usando la
   tabla de frecuencias de "Quedan" observada en campo.
4. Durante el verde pasan como máximo "capacidad" vehículos (el máximo que se
   vio pasar en un verde de ese semáforo):
       pasan  = min(en_espera - rezagados, capacidad)
       quedan = en_espera - pasan
5. Los que quedan esperan al siguiente ciclo.
"""

from dataclasses import dataclass

import pandas as pd

from .datos import DatosSemaforo
from .generador import GeneradorCongruencial


# ---------------------------------------------------------------------------
# Tabla de frecuencias y codificación por intervalos
# ---------------------------------------------------------------------------
def tabla_intervalos(valores: list[int]) -> pd.DataFrame:
    """Tabla de frecuencias con su intervalo de codificación.

    Cada valor observado recibe un intervalo [desde, hasta) dentro de [0, 1)
    cuyo ancho es su probabilidad (frecuencia / total).
    """
    serie = pd.Series(valores).value_counts().sort_index()
    total = int(serie.sum())
    tabla = pd.DataFrame({
        "valor": serie.index.astype(int),
        "frecuencia": serie.values.astype(int),
    })
    tabla["probabilidad"] = tabla["frecuencia"] / total
    tabla["acumulada"] = tabla["probabilidad"].cumsum()
    tabla["desde"] = tabla["acumulada"] - tabla["probabilidad"]
    tabla["hasta"] = tabla["acumulada"]
    tabla.loc[tabla.index[-1], "hasta"] = 1.0   # evita errores de redondeo
    return tabla


def sortear(tabla: pd.DataFrame, u: float) -> int:
    """Devuelve el valor cuyo intervalo contiene a U."""
    for valor, hasta in zip(tabla["valor"], tabla["hasta"]):
        if u < hasta:
            return int(valor)
    return int(tabla["valor"].iloc[-1])


# ---------------------------------------------------------------------------
# Simulación
# ---------------------------------------------------------------------------
@dataclass
class Escenario:
    periodo: str = "Valle"          # "Valle" o "Pico"
    ciclos: int = 100               # ciclos a simular por semáforo
    semilla: int = 12345
    factor_demanda: float = 1.0     # 1.0 = demanda observada; 1.2 = 20 % más carros
    verdes: dict | None = None      # tiempo en verde por semáforo (None = el real)


def capacidad_con_verde(sem: DatosSemaforo, verde: int) -> int:
    """La capacidad crece en proporción al tiempo en verde."""
    return max(1, round(sem.capacidad * verde / sem.verde))


def simular(semaforos: dict[str, DatosSemaforo], esc: Escenario):
    """Simula todos los semáforos. Devuelve (detalle por ciclo, resumen)."""
    gen = GeneradorCongruencial(esc.semilla)
    filas = []
    resumen = []

    for s, sem in semaforos.items():
        verde = (esc.verdes or {}).get(s, sem.verde)
        cap = capacidad_con_verde(sem, verde)
        ciclo_seg = verde + sem.rojo
        tabla_lleg = tabla_intervalos(sem.llegadas[esc.periodo])
        tabla_rez = tabla_intervalos(sem.quedan[esc.periodo])

        cola = 0
        for c in range(1, esc.ciclos + 1):
            u1 = gen.siguiente()
            u2 = gen.siguiente()
            llegadas = round(sortear(tabla_lleg, u1) * esc.factor_demanda)
            en_espera = cola + llegadas
            rezagados = min(sortear(tabla_rez, u2), llegadas)
            pasan = min(en_espera - rezagados, cap)
            cola = en_espera - pasan
            filas.append({
                "semaforo": s, "ciclo": c, "U1": u1, "llegadas": llegadas,
                "en_espera": en_espera, "U2": u2, "rezagados": rezagados,
                "capacidad": cap, "pasan": pasan, "quedan": cola,
            })

        d = pd.DataFrame([f for f in filas if f["semaforo"] == s])
        ciclos_hora = 3600 / ciclo_seg
        llegadas_media = d["llegadas"].mean()
        resumen.append({
            "semaforo": s,
            "ubicacion": sem.ubicacion,
            "verde_s": verde,
            "rojo_s": sem.rojo,
            "ciclo_s": ciclo_seg,
            "capacidad_ciclo": cap,
            "llegadas_prom": llegadas_media,
            "pasan_prom": d["pasan"].mean(),
            "pasan_total": int(d["pasan"].sum()),
            "cola_prom": d["quedan"].mean(),
            "cola_max": int(d["quedan"].max()),
            "cola_final": int(d["quedan"].iloc[-1]),
            "pct_ciclos_con_cola": 100 * (d["quedan"] > 0).mean(),
            "utilizacion": llegadas_media / cap,
            "capacidad_hora": cap * ciclos_hora,
            "demanda_hora": llegadas_media * ciclos_hora,
        })

    return pd.DataFrame(filas), pd.DataFrame(resumen)


def estado(utilizacion: float, pct_cola: float) -> str:
    if utilizacion >= 1:
        return "Saturado: llegan más carros de los que pueden pasar; la cola crece sin parar"
    if utilizacion >= 0.85 or pct_cola >= 50:
        return "Al límite: funciona, pero con colas frecuentes"
    return "Sin problema: la cola se despeja casi siempre"


def barrido_demanda(semaforos, periodo: str, semilla: int, ciclos: int = 200,
                    factores=None) -> pd.DataFrame:
    """Repite la simulación aumentando la demanda para ver cuándo se satura."""
    factores = factores or [round(0.5 + 0.1 * i, 1) for i in range(26)]  # 0.5 a 3.0
    filas = []
    for f in factores:
        _, res = simular(semaforos, Escenario(periodo=periodo, ciclos=ciclos,
                                              semilla=semilla, factor_demanda=f))
        for _, r in res.iterrows():
            filas.append({"factor": f, "semaforo": r["semaforo"],
                          "cola_prom": r["cola_prom"], "utilizacion": r["utilizacion"],
                          "pct_ciclos_con_cola": r["pct_ciclos_con_cola"]})
    return pd.DataFrame(filas)
