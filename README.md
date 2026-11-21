# Simulador del cruce vial · vía Mesa–Girardot

Proyecto del curso de **Simulación**, Universidad Piloto de Colombia.

Simula un cruce con 4 semáforos usando los datos tomados en campo: 221 ciclos en hora valle y en hora pico. Responde la pregunta del proyecto: **¿cuántos vehículos puede atender el cruce sin problema?**

| Semáforo | Ubicación | Verde | Rojo | Ciclo |
|---|---|---|---|---|
| S1 | OXXO Acacias | 25 s | 99 s | 124 s |
| S2 | Mesa | 30 s | 99 s | 129 s |
| S3 | El Caldero | 25 s | 99 s | 124 s |
| S4 | Vía Jumbo | 35 s | 99 s | 134 s |

---

## Cómo abrirlo en cualquier PC (con Docker)

Requisitos: [Git](https://git-scm.com/downloads) y [Docker Desktop](https://www.docker.com/products/docker-desktop/) abierto.

```bash
git clone https://github.com/NeuSpirit23/simulador-cruce-vial.git
cd simulador-cruce-vial
docker compose up --build
```

Luego abre en el navegador: **http://localhost:8501**

Para apagarlo: `Ctrl + C` en la terminal o `docker compose down`.

### Sin Docker (solo Python 3.10 o superior)

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## Qué tiene la aplicación

| Pestaña | Qué muestra |
|---|---|
| **Simulación** | Vehículos que pasan y que quedan en cola, ciclo por ciclo, para cada semáforo. |
| **¿Cuánto aguanta el cruce?** | La capacidad en vehículos por hora y hasta cuánto puede crecer la demanda antes de saturarse. |
| **Validación** | Compara lo simulado con lo observado en campo usando el error del método de los 11 pasos. |
| **Datos de campo** | Los 221 registros y la tabla de codificación por intervalos de las llegadas. |
| **Generador y pruebas** | Generador congruencial y pruebas de promedios, frecuencias y Kolmogorov-Smirnov (Coss Bu, cap. 3). |
| **Cómo funciona** | La explicación del modelo, paso a paso. |

En la barra lateral se escoge: hora valle o pico, número de ciclos, semilla, nivel de demanda y el tiempo en verde de cada semáforo.

---

## El modelo, paso a paso

**Generador.** `Xₙ₊₁ = 16807 · Xₙ mod 2147483647` y `U = X / 2147483647`. Es el mismo generador del curso. Con la misma semilla, los resultados siempre son iguales.

En cada ciclo, para cada semáforo:

1. **Llegadas.** Se genera U₁ y se busca su intervalo en la tabla de frecuencias de llegadas observadas (codificación por intervalos). Las llegadas de campo se calculan así: `llegadas = pasan + quedan − quedan del ciclo anterior`.
2. **En espera.** `en espera = cola anterior + llegadas`.
3. **Rezagados.** Se genera U₂ y, con la tabla de frecuencias de *Quedan*, se sortea cuántos carros llegan con el verde terminando y no alcanzan a pasar.
4. **Pasan.** `pasan = mín(en espera − rezagados, capacidad)`. La capacidad es el máximo de vehículos que se vio pasar en un verde de ese semáforo (S1 33, S2 32, S3 30, S4 45) y cambia en proporción al tiempo en verde.
5. **Quedan.** `quedan = en espera − pasan`. Esos carros pasan al siguiente ciclo.

**Capacidad por hora** = capacidad por verde × (3600 ÷ duración del ciclo).
**Uso de la capacidad** = llegadas promedio por ciclo ÷ capacidad por verde. Si llega al 100 %, el semáforo se satura.

**Supuestos:** se cuenta el total de vehículos por semáforo (no se separan giros), no se miden amarillo ni despeje, y cada semáforo se simula por separado.

---

## Estructura

```
app.py                  Aplicación web (Streamlit)
simulador/datos.py      Lectura del Excel y cálculo de llegadas
simulador/generador.py  Generador congruencial
simulador/modelo.py     Tablas de intervalos y simulación por ciclos
simulador/pruebas.py    Pruebas de uniformidad (Coss Bu, cap. 3)
data/registro_transito.xlsx   Datos de campo
tests/                  Pruebas automáticas (pytest)
```

Para correr las pruebas: `python -m pytest`
