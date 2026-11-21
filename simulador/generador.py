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
        return [self.siguiente() for _ in range(cantidad)]
