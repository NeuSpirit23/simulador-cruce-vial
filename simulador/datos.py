"""Lectura de los datos de campo del cruce vial (vía Mesa–Girardot)."""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

RUTA_DATOS = Path(__file__).resolve().parent.parent / "data" / "registro_transito.xlsx"

UBICACIONES = {
    "S1": "OXXO Acacias",
    "S2": "Mesa",
    "S3": "El Caldero",
    "S4": "Vía Jumbo",
}
SEMAFOROS = list(UBICACIONES)
PERIODOS = ["Valle", "Pico"]


@dataclass
class DatosSemaforo:
    semaforo: str
    ubicacion: str
    verde: int                      # segundos en verde
    rojo: int                       # segundos en rojo
    capacidad: int                  # máximo de vehículos observados en un verde
    llegadas: dict = field(default_factory=dict)   # periodo -> lista de llegadas por ciclo
    pasan: dict = field(default_factory=dict)      # periodo -> lista de "Pasan" observados
    quedan: dict = field(default_factory=dict)     # periodo -> lista de "Quedan" observados

    @property
    def ciclo(self) -> int:
        return self.verde + self.rojo


def leer_base(ruta: Path = RUTA_DATOS) -> pd.DataFrame:
    df = pd.read_excel(ruta, sheet_name="Base de datos")
    df = df.rename(columns={
        "Semáforo": "semaforo", "Ubicación": "ubicacion", "Jornada": "jornada",
        "Periodo": "periodo", "Bloque horario": "bloque", "Iteración": "iteracion",
        "Pasan": "pasan", "Quedan": "quedan", "Tiempo verde (s)": "verde",
        "Tiempo rojo (s)": "rojo",
    })
    return df[["semaforo", "ubicacion", "jornada", "periodo", "bloque",
               "iteracion", "pasan", "quedan", "verde", "rojo"]]


def calcular_llegadas(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula cuántos vehículos NUEVOS llegaron en cada ciclo.

    En cada ciclo los que pasan incluyen a los que se quedaron del ciclo
    anterior. Por eso:

        llegadas(t) = pasan(t) + quedan(t) - quedan(t-1)

    El primer ciclo de cada toma (mismo semáforo y jornada) usa
    quedan(t-1) = 0. Si por error de conteo da negativo, se toma 0.
    """
    df = df.copy()
    df["quedan_anterior"] = (
        df.groupby(["semaforo", "jornada"])["quedan"].shift(1).fillna(0).astype(int)
    )
    df["llegadas"] = (df["pasan"] + df["quedan"] - df["quedan_anterior"]).clip(lower=0)
    return df


def cargar_semaforos(ruta: Path = RUTA_DATOS) -> dict[str, DatosSemaforo]:
    df = calcular_llegadas(leer_base(ruta))
    semaforos = {}
    for s in SEMAFOROS:
        d = df[df["semaforo"] == s]
        info = DatosSemaforo(
            semaforo=s,
            ubicacion=UBICACIONES[s],
            verde=int(d["verde"].iloc[0]),
            rojo=int(d["rojo"].iloc[0]),
            capacidad=int(d["pasan"].max()),
        )
        for p in PERIODOS:
            dp = d[d["periodo"] == p]
            info.llegadas[p] = dp["llegadas"].astype(int).tolist()
            info.pasan[p] = dp["pasan"].astype(int).tolist()
            info.quedan[p] = dp["quedan"].astype(int).tolist()
        semaforos[s] = info
    return semaforos
