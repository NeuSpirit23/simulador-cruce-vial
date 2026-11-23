"""Casos de prueba: cambia un solo campo a la vez sobre la simulación actual y mide qué pasa.

Sirven para explicar qué hace cada campo de la barra lateral. Como parten de la simulación que
el usuario tiene configurada, los números cambian con cada simulación.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pandas as pd

from .prediccion import MAX_CICLOS_TOTALES, EscenarioPrediccion, ResultadoPrediccion, predecir


def indicadores(res: ResultadoPrediccion) -> dict:
    """Lo que se compara entre casos (promedios de las repeticiones)."""
    from .paquete import precision

    prec, _ = precision(res)
    fila = prec.set_index("Resultado")
    c = res.ciclos
    tot = fila.loc["Total del cruce"]
    return {
        "Ciclos": int(len(c)),
        "Números pseudoaleatorios": int(res.numeros_usados),
        "Vehículos que pasan": float(tot["Promedio"]),
        "± IC 99 %": float(tot["± IC 99 %"]),
        "Error relativo (%)": float(tot["Error relativo (%)"]) if pd.notna(tot["Error relativo (%)"]) else float("nan"),
        "En hora valle": float(fila.loc["Total en hora valle", "Promedio"]) if "Total en hora valle" in fila.index else 0.0,
        "En hora pico": float(fila.loc["Total en hora pico", "Promedio"]) if "Total en hora pico" in fila.index else 0.0,
        "Cola prom. (veh/ciclo)": float(c["quedan_prom"].mean()),
        "Cola máx. (veh)": int(c["quedan"].max()),
        "¿Todo ≤ 1 %?": "Sí" if (prec["¿Cumple ≤ 1 %?"] == "Sí").all() else "No",
    }


def _x(v: float) -> str:
    return f"×{v:g}".replace(".", ",")


def definir_casos(esc: EscenarioPrediccion, ciclos_totales: int) -> list[dict]:
    """Cada caso cambia UN campo respecto al caso base."""
    r2 = min(esc.repeticiones * 2, max(esc.repeticiones + 1, MAX_CICLOS_TOTALES // max(1, ciclos_totales)))
    casos = [
        {"caso": "Caso base", "campo": "—", "cambio": "Su simulación actual", "esc": esc,
         "explica": "Es el punto de comparación. Todos los demás casos cambian un solo campo."},
        {"caso": "Otra semilla", "campo": "Semilla", "cambio": f"{esc.semilla} → {esc.semilla + 1}",
         "esc": replace(esc, semilla=esc.semilla + 1),
         "explica": "Cambia la secuencia de números pseudoaleatorios. El total se mueve un poco (dentro del margen ± IC 99 %), "
                    "pero el error no baja: la semilla no hace la predicción más precisa."},
        {"caso": "Más repeticiones", "campo": "Repeticiones", "cambio": f"{esc.repeticiones} → {r2}",
         "esc": replace(esc, repeticiones=r2),
         "explica": "Se repite la simulación más veces y se promedia. El total casi no cambia, pero el margen se achica: "
                    "el error baja más o menos como 1 ÷ √R (con el doble de repeticiones, cerca de 29 % menos error). "
                    "Los números pseudoaleatorios se duplican."},
        {"caso": "Más tráfico", "campo": "Demanda", "cambio": f"{_x(esc.factor_demanda)} → {_x(round(esc.factor_demanda * 1.2, 3))}",
         "esc": replace(esc, factor_demanda=esc.factor_demanda * 1.2),
         "explica": "Las llegadas de cada ciclo se multiplican por 1,2. Pasan más carros y crecen las colas; si una entrada "
                    "llega a su capacidad por verde, ya no puede pasar más y la cola se acumula."},
        {"caso": "Menos tráfico", "campo": "Demanda", "cambio": f"{_x(esc.factor_demanda)} → {_x(round(esc.factor_demanda * 0.8, 3))}",
         "esc": replace(esc, factor_demanda=esc.factor_demanda * 0.8),
         "explica": "Las llegadas se multiplican por 0,8: pasan menos carros y casi no quedan colas."},
        {"caso": "Periodo más largo", "campo": "Periodo (fecha y hora final)",
         "cambio": f"hasta {esc.fin:%d/%m %H:%M} → {esc.fin + timedelta(hours=2):%d/%m %H:%M}",
         "esc": replace(esc, fin=esc.fin + timedelta(hours=2)),
         "explica": "Dos horas más de reloj: más ciclos, más números pseudoaleatorios y más vehículos. Con más ciclos el "
                    "error relativo del total baja un poco, porque se suman más datos."},
    ]
    return casos


def correr_casos(semaforos, esc: EscenarioPrediccion, res_base: ResultadoPrediccion) -> pd.DataFrame:
    """Corre todos los casos (el base se reutiliza) y arma la tabla comparativa."""
    filas = []
    base = indicadores(res_base)
    for c in definir_casos(esc, base["Ciclos"]):
        ind = base if c["caso"] == "Caso base" else indicadores(predecir(semaforos, c["esc"]))
        fila = {"Caso": c["caso"], "Campo que cambia": c["campo"], "Cambio": c["cambio"], **ind}
        fila["Δ vehículos vs base (%)"] = 100 * (ind["Vehículos que pasan"] / base["Vehículos que pasan"] - 1)
        fila["Qué pasó"] = c["explica"]
        filas.append(fila)
    t = pd.DataFrame(filas)
    orden = ["Caso", "Campo que cambia", "Cambio", "Ciclos", "Números pseudoaleatorios", "Vehículos que pasan",
             "Δ vehículos vs base (%)", "± IC 99 %", "Error relativo (%)", "¿Todo ≤ 1 %?", "En hora valle",
             "En hora pico", "Cola prom. (veh/ciclo)", "Cola máx. (veh)", "Qué pasó"]
    return t[orden]


# Qué hace cada campo de la barra lateral (para la tabla de la pestaña de análisis)
CAMPOS = pd.DataFrame([
    ("1 · Periodo (fecha y hora de inicio y fin)", "El tramo de reloj que se quiere predecir.",
     "Ciclos, números pseudoaleatorios, cuántas horas son valle o pico, totales.",
     "Más horas = más ciclos = más vehículos. Si el periodo incluye 12:00–13:00 o 17:00–18:30, esos ciclos usan los datos de pico.",
     "ciclos de un semáforo = segundos del periodo ÷ duración de su ciclo (124, 129, 124 o 134 s)"),
    ("1 · Ciclos", "Cuántos ciclos verde → rojo se simulan (suma de los 4 semáforos).",
     "La hora final (se corre sola) y los números pseudoaleatorios.",
     "Es otra forma de fijar el periodo: más ciclos = periodo más largo.",
     "segundos = ciclos de un semáforo × duración de su ciclo"),
    ("1 · Números pseudoaleatorios", "Cuántos U (0 a 1) se generan en total.",
     "Ciclos y hora final (se ajustan solos).",
     "Cada ciclo usa 2 números: U1 sortea las llegadas y U2 los rezagados.",
     "números = 2 × ciclos × repeticiones"),
    ("2 · Repeticiones", "Cuántas veces se repite la simulación completa con números distintos.",
     "Precisión: margen ± IC 99 % y error relativo. También los números pseudoaleatorios.",
     "El promedio casi no cambia; el margen se achica. Es la forma más directa de llegar a error ≤ 1 %.",
     "margen = 2,576 × desviación ÷ √R  ·  error = margen ÷ promedio"),
    ("3 · Semilla", "El número con que arranca el generador congruencial.",
     "La secuencia de U, y por eso cada resultado individual.",
     "Misma semilla = mismos resultados (se puede repetir). Otra semilla = resultados un poco distintos, mismo nivel de error.",
     "Xₙ₊₁ = 16.807 × Xₙ mod 2.147.483.647  ·  U = X ÷ 2.147.483.647"),
    ("Demanda (×)", "Multiplica las llegadas de cada ciclo.",
     "Llegadas, vehículos que pasan, colas y qué tan cerca está cada semáforo de saturarse.",
     "×1 = como en el aforo. ×1,2 = 20 % más carros. Si se pasa la capacidad por verde, crecen las colas.",
     "llegadas del ciclo × factor (redondeado)"),
    ("Bloques de horas / de ciclos", "Cada cuánto se agrupan los reportes (0–2, 2–4… o cada N ciclos).",
     "Solo la forma de mostrar los resultados.",
     "No cambia la simulación: el total es el mismo, solo se reparte en más o menos filas.",
     "suma de los bloques = total de la simulación"),
    ("Explorador (Reportes)", "Ver un tramo de hora a hora o de ciclo a ciclo, con la frecuencia que se quiera.",
     "La vista y, si se pulsa \"Usar este tramo en el Excel y el PDF\", la hoja y la página del tramo en Excel y PDF.",
     "No vuelve a simular: toma los ciclos ya simulados de ese tramo.",
     "vehículos del tramo = suma de los ciclos que empiezan dentro del tramo"),
    ("% de giros (Simulación en vivo)", "Qué parte de los carros gira a la izquierda, sigue derecho o gira a la derecha.",
     "Solo la animación del mapa y la maqueta 3D.",
     "No cambia ningún conteo ni reporte: los giros no se midieron en campo.",
     "izquierda + derecho + derecha = 100 %"),
], columns=["Campo", "Qué es", "Qué afecta", "Cómo cambia la simulación", "Fórmula"])
