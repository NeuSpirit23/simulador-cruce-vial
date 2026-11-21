"""Pruebas de uniformidad del libro de Coss Bu (capítulo 3) aplicadas al generador.

Antes de simular hay que comprobar que los números U se comportan como
uniformes entre 0 y 1.

H0: los números provienen de una distribución uniforme.
H1: los números no provienen de una distribución uniforme.
"""

import math

from scipy import stats


def prueba_promedios(u: list[float], alfa: float = 0.05) -> dict:
    """Ec. 3.1 y 3.2:  x̄ = ΣU/N ;  Z0 = (x̄ - 0.5)·√N / √(1/12)."""
    n = len(u)
    media = sum(u) / n
    z0 = (media - 0.5) * math.sqrt(n) / math.sqrt(1 / 12)
    critico = stats.norm.ppf(1 - alfa / 2)
    return {"N": n, "media": media, "estadistico": z0, "critico": critico,
            "no_se_rechaza": abs(z0) < critico}


def prueba_frecuencias(u: list[float], subintervalos: int = 10, alfa: float = 0.05) -> dict:
    """Ec. 3.3:  FE = N/n ;  X0² = Σ (FO - FE)² / FE ;  g.l. = n - 1."""
    n = len(u)
    fo = [0] * subintervalos
    for x in u:
        fo[min(int(x * subintervalos), subintervalos - 1)] += 1
    fe = n / subintervalos
    x2 = sum((o - fe) ** 2 / fe for o in fo)
    critico = stats.chi2.ppf(1 - alfa, subintervalos - 1)
    return {"N": n, "FO": fo, "FE": fe, "estadistico": x2, "critico": critico,
            "no_se_rechaza": x2 < critico}


def prueba_ks(u: list[float], alfa: float = 0.05) -> dict:
    """Ec. 3.11 y 3.12:  Dn = máx |i/n - Xi|  con los números ordenados.

    Valor crítico para n > 35 (tabla 3.5): 1.22/√n (10 %), 1.36/√n (5 %), 1.63/√n (1 %).
    """
    xs = sorted(u)
    n = len(xs)
    dn = max(abs((i + 1) / n - x) for i, x in enumerate(xs))
    constante = {0.10: 1.22, 0.05: 1.36, 0.01: 1.63}.get(alfa, 1.36)
    critico = constante / math.sqrt(n)
    return {"N": n, "estadistico": dn, "critico": critico,
            "no_se_rechaza": dn <= critico}
