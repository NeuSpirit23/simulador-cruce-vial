"""Generador de números pseudoaleatorios.

Usa el mismo generador congruencial multiplicativo del curso:

    X(n+1) = 16807 * X(n)  mod  2147483647
    U(n+1) = X(n+1) / 2147483647

Con la misma semilla siempre salen los mismos números, así que cualquier
resultado del simulador se puede repetir y comprobar.
"""

A = 16807
M = 2_147_483_647


class GeneradorCongruencial:
    def __init__(self, semilla: int = 12345):
        semilla = int(semilla) % M
        if semilla == 0:
            raise ValueError("La semilla no puede ser 0 ni múltiplo de 2147483647.")
        self.semilla = semilla
        self.x = semilla

    def siguiente(self) -> float:
        """Devuelve el siguiente número U entre 0 y 1."""
        self.x = (A * self.x) % M
        return self.x / M

    def lista(self, cantidad: int) -> list[float]:
        return self.arreglo(cantidad).tolist()

    def arreglo(self, cantidad: int):
        """Los siguientes `cantidad` números U como arreglo de numpy (misma secuencia que siguiente()).

        Para ir rápido se usa que X(n+i) = (Aⁱ mod M) · X(n) mod M: con las potencias de A ya calculadas,
        un bloque entero sale de una sola multiplicación. Aⁱ mod M y X(n) son menores que 2³¹, así que el
        producto cabe en un entero de 64 bits y el resultado es exacto.
        """
        import numpy as np

        cantidad = int(cantidad)
        salida = np.empty(cantidad, dtype=np.float64)
        pot = _potencias()
        hecho = 0
        while hecho < cantidad:
            b = min(len(pot), cantidad - hecho)
            xs = (pot[:b] * np.int64(self.x)) % M
            salida[hecho:hecho + b] = xs / M
            self.x = int(xs[-1])
            hecho += b
        return salida


_POT = None


def _potencias(bloque: int = 65_536):
    """A¹, A², …, A^bloque (mod M), calculadas una sola vez."""
    global _POT
    if _POT is None:
        import numpy as np

        pot = np.empty(bloque, dtype=np.int64)
        v = 1
        for i in range(bloque):
            v = (A * v) % M
            pot[i] = v
        _POT = pot
    return _POT
