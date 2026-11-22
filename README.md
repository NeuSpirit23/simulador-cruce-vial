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

En la barra lateral, **toda simulación usa siempre estos 3 parámetros, enlazados entre sí**:

1. **Periodo:** desde qué día y hora hasta qué día y hora.
2. **Ciclos:** cuántos ciclos (verde → rojo) caben en el periodo, sumando los 4 semáforos. En cada semáforo, `ciclos = segundos del periodo ÷ duración de su ciclo` (124, 129, 124 y 134 s).
3. **Números pseudoaleatorios:** cada ciclo usa 2 (U1 y U2) en cada repetición, así que `números = 2 × ciclos × repeticiones`.

Si se cambia cualquiera de los tres, los otros se recalculan solos. Por ejemplo, si se escriben más ciclos o más números, la hora final se corre para que todo cuadre.

Además se escogen las **repeticiones**, la **semilla** y el nivel de demanda, y luego se da clic en **Simular**.

**Restricciones fijas:** los 4 semáforos con sus tiempos (verde 25/30/25/35 s y rojo 99 s) y las **horas pico** 12:00–13:00 y 17:00–18:00, que son las medidas en campo. El resto del día es hora valle. **Toda simulación debe incluir horas valle y horas pico**; si el periodo no las tiene, el programa avisa y no simula. El límite es de 4 millones de ciclos en total (ciclos × semáforos × repeticiones), por ejemplo un año completo con 3 repeticiones.

| Pestaña | Qué muestra |
|---|---|
| **Predicción** | Total de vehículos que pasan con su margen (IC 95 %), los resultados por semáforo, la comparación valle frente a pico y la gráfica por hora. |
| **Reportes** | Bloques de horas ajustables (2 h por defecto: 00–02, 02–04…) con cuántos pasan, el % del total y cuántos pasan en horas valle y en horas pico. Bloques de ciclos ajustables (10 por defecto: ciclos 1–10, 11–20…). Tablas por hora y por ciclo. Todo se descarga en **Excel** y en **PDF**. |
| **Mapa en vivo** | Mapa satelital del cruce con la animación de los carros en cola y los que pasan, ciclo por ciclo y semáforo por semáforo. |
| **¿Cuánto aguanta el cruce?** | La capacidad en vehículos por hora y hasta cuánto puede crecer la demanda antes de saturarse. |
| **Validación** | Compara lo simulado con lo observado usando el error del método de los 11 pasos. |
| **Datos de campo** | Los 221 registros (se descargan en Excel y PDF) y las tablas de codificación por intervalos. |
| **Generador y pruebas** | El generador congruencial y las pruebas de promedios, frecuencias y Kolmogorov-Smirnov (Coss Bu, cap. 3). |
| **Cómo funciona** | La explicación del modelo, paso a paso. |

**Ubicación en el mapa:** el cruce es la Carrera 10 con la Av. Ciudad de las Acacias (Girardot). S1 OXXO recibe a los carros que llegan por la avenida desde el oriente, S2 Mesa a los que llegan por la Carrera 10 desde el norte, S3 El Caldero a los que llegan por la avenida desde el occidente y S4 Vía Jumbo a los que llegan por la Carrera 10 desde el sur. En la pestaña *Mapa en vivo* → "Ajustar la ubicación" se pueden cambiar la latitud y longitud del centro del cruce (en Google Maps se sacan con clic derecho sobre el cruce) y la dirección de cada semáforo. Los valores por defecto están en `simulador/mapa.py`.

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

**Periodo y repeticiones.** Cada ciclo se ubica en el reloj: si empieza en hora pico usa las tablas de hora pico y, si no, las de hora valle. Todo se repite R veces y se reporta el promedio con su intervalo de confianza del 95 %: `promedio ± 1,96 · desviación estándar ÷ √R`.

**Supuestos:** se cuenta el total de vehículos por semáforo (no se separan giros), no se miden amarillo ni despeje, y cada semáforo se simula por separado. Las horas que no se midieron (noche, madrugada, fines de semana) se tratan como hora valle.

---

## Estructura

```
app.py                  Aplicación web (Streamlit)
simulador/datos.py      Lectura del Excel y cálculo de llegadas
simulador/generador.py  Generador congruencial
simulador/modelo.py     Tablas de intervalos y simulación por ciclos
simulador/prediccion.py Predicción por rango de fechas y horas con repeticiones
simulador/reportes.py   Reportes por bloques, por hora, valle vs pico
simulador/exportar.py   Exportación a Excel y PDF
simulador/mapa.py       Mapa satelital con la animación
simulador/pruebas.py    Pruebas de uniformidad (Coss Bu, cap. 3)
data/registro_transito.xlsx   Datos de campo
tests/                  Pruebas automáticas (pytest)
```

Para correr las pruebas: `python -m pytest`
