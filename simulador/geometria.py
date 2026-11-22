"""Geometría real del cruce (Carrera 10 con Av. Ciudad de las Acacias, Girardot).

Las calles se trazaron sobre la imagen de Google Maps que envió el grupo (zoom 20,
centro 4.3072606, -74.8035331). A esa escala 1 píxel ≈ 0,149 m, así que cada punto
(x, y) en píxeles se pasa a metros alrededor del centro del cruce:

    este  = (x − 770) · 0,149        norte = −(y − 375) · 0,149

Sentidos (según las flechas de la imagen):
* Av. Ciudad de las Acacias, ramal norte (oriente del cruce): un solo sentido, hacia el occidente.
  Por ahí llegan los carros de S1 (OXXO).
* Av. Ciudad de las Acacias, ramal sur: un solo sentido, hacia el oriente. Arranca en la
  Carrera 10 a la altura de la Calle 33; por ahí salen los que van hacia el oriente.
* Carrera 10, Av. Acacias (occidente), Calle 33, Carrera 10A y Carrera 11: doble sentido.
"""

import math

PX = 0.1488694          # metros por píxel en la imagen (zoom 20)
CX, CY = 770, 375       # píxel del centro del cruce
CARRIL = 2.6            # distancia del eje de la vía al centro del carril (doble sentido)
CARRIL_1S = 1.4         # en vías de un solo sentido


def m(x, y):
    return (round((x - CX) * PX, 2), round(-(y - CY) * PX, 2))


# Ejes de las vías (de un extremo al otro), ancho en metros y si son de doble sentido
VIAS = [
    {"nombre": "Carrera 10", "pts": [m(580, -150), m(640, 20), m(770, 375), m(850, 560), m(880, 640),
                                      m(1000, 850), m(1060, 960)], "ancho": 10, "doble": True},
    {"nombre": "Av. Ciudad de las Acacias", "pts": [m(-400, -32), m(20, 145), m(280, 255), m(770, 375)],
     "ancho": 10, "doble": True},
    {"nombre": "Av. Ciudad de las Acacias (→ occidente)",
     "pts": [m(770, 375), m(1030, 405), m(1700, 345), m(2300, 300)], "ancho": 8, "doble": False},
    {"nombre": "Av. Ciudad de las Acacias (→ oriente)",
     "pts": [m(868, 580), m(1230, 490), m(1700, 460), m(2300, 440)], "ancho": 8, "doble": False},
    {"nombre": "Calle 33", "pts": [m(875, 635), m(560, 740), m(300, 850), m(-100, 980)], "ancho": 8, "doble": True},
    {"nombre": "Carrera 10A", "pts": [m(712, 125), m(1010, 20), m(1300, -80)], "ancho": 8, "doble": True},
    {"nombre": "Carrera 11", "pts": [m(60, 100), m(90, 195), m(160, 480), m(250, 830), m(300, 1000)],
     "ancho": 8, "doble": True},
]

# Negocios de referencia que se ven en el mapa (para ubicarse en la vista 3D)
REFERENCIAS = [
    {"nombre": "OXXO Acacias", "p": m(860, 300), "color": "#d6332f"},
    {"nombre": "Pollos Pizza", "p": m(715, 300), "color": "#f08a24"},
    {"nombre": "El Caldero", "p": m(670, 455), "color": "#f08a24"},
    {"nombre": "Hot Soul Girardot", "p": m(930, 650), "color": "#f08a24"},
    {"nombre": "Hierros Andinos", "p": m(1090, 120), "color": "#2b6cb0"},
    {"nombre": "Centro de Servicios Gasmotor", "p": m(330, 200), "color": "#64748b"},
    {"nombre": "Sweet coffee", "p": m(450, 690), "color": "#f08a24"},
    {"nombre": "Cherry CK", "p": m(210, 300), "color": "#f08a24"},
]

# Recorridos de llegada (desde lejos hasta el centro del cruce) y de salida (desde el centro hacia afuera)
_NORTE = [m(580, -150), m(640, 20), m(770, 375)]
_SUR = [m(1060, 960), m(1000, 850), m(880, 640), m(850, 560), m(770, 375)]
_OCCIDENTE = [m(-400, -32), m(20, 145), m(280, 255), m(770, 375)]
_ORIENTE_ENTRA = [m(2300, 300), m(1700, 345), m(1030, 405), m(790, 385), m(770, 375)]
_J = m(868, 580)                                   # Carrera 10 con el ramal sur de la avenida
_ORIENTE_SALE = [m(1230, 490), m(1700, 460), m(2300, 440)]

LLEGADAS = {"S1": (_ORIENTE_ENTRA, CARRIL_1S), "S2": (_NORTE, CARRIL),
            "S3": (_OCCIDENTE, CARRIL), "S4": (_SUR, CARRIL)}


def _salida(destino: str):
    """Puntos (y carril de cada tramo) desde el centro hacia afuera."""
    if destino == "N":
        return [(p, CARRIL) for p in _NORTE[::-1]]
    if destino == "O":
        return [(p, CARRIL) for p in _OCCIDENTE[::-1]]
    if destino == "S":
        return [(p, CARRIL) for p in _SUR[::-1]]
    # oriente: baja por la Carrera 10 hasta el ramal sur y sigue por la avenida (un solo sentido)
    return [(m(770, 375), CARRIL), (m(850, 560), CARRIL), (_J, CARRIL)] + [(p, CARRIL_1S) for p in _ORIENTE_SALE]


# Giros posibles desde cada semáforo: (destino, tipo de giro)
GIROS = {
    "S1": [("O", "recto"), ("N", "der"), ("S", "izq")],
    "S2": [("S", "recto"), ("O", "der"), ("E", "izq")],
    "S3": [("E", "recto"), ("N", "izq"), ("S", "der")],
    "S4": [("N", "recto"), ("O", "izq"), ("E", "der")],
}


# ---------------------------------------------------------------------------- utilidades
def _dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _desplazar(puntos_carril):
    """Corre cada punto a la derecha del sentido de marcha la distancia de su carril."""
    pts = [p for p, _ in puntos_carril]
    out = []
    for i, (p, c) in enumerate(puntos_carril):
        a = pts[max(0, i - 1)]
        b = pts[min(len(pts) - 1, i + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1
        out.append((p[0] + dy / n * c, p[1] - dx / n * c))       # derecha = (dy, −dx)
    return out


def _densificar(pts, paso=3.0):
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        k = max(1, int(_dist(a, b) // paso))
        for i in range(1, k + 1):
            out.append((a[0] + (b[0] - a[0]) * i / k, a[1] + (b[1] - a[1]) * i / k))
    return out


def _chaikin(pts, vueltas=3):
    for _ in range(vueltas):
        nuevo = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            nuevo += [(0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]),
                      (0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1])]
        nuevo.append(pts[-1])
        pts = nuevo
    return pts


def _recortar(pts, desde=0.0, hasta=None):
    """Parte de la polilínea entre dos distancias medidas desde el inicio."""
    out, acum = [], 0.0
    total = sum(_dist(a, b) for a, b in zip(pts, pts[1:]))
    hasta = total if hasta is None else hasta
    for a, b in zip(pts, pts[1:]):
        L = _dist(a, b)
        for t in (0.0, 1.0):
            d = acum + t * L
            if desde <= d <= hasta:
                out.append(a if t == 0 else b)
        if acum < desde < acum + L:
            f = (desde - acum) / L
            out.insert(0, (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
        if acum < hasta < acum + L:
            f = (hasta - acum) / L
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
        acum += L
    dedup = [out[0]] if out else []
    for p in out[1:]:
        if _dist(p, dedup[-1]) > 0.05:
            dedup.append(p)
    return dedup


def _largo(pts):
    return sum(_dist(a, b) for a, b in zip(pts, pts[1:]))


def _acumulado(pts):
    L = [0.0]
    for a, b in zip(pts, pts[1:]):
        L.append(L[-1] + _dist(a, b))
    return L


def _proyectar(pts, q):
    """Distancia a lo largo de la polilínea del punto más cercano a q."""
    mejor, d_mejor, acum = 0.0, 1e18, 0.0
    for a, b in zip(pts, pts[1:]):
        L = _dist(a, b) or 1e-9
        t = max(0.0, min(1.0, ((q[0] - a[0]) * (b[0] - a[0]) + (q[1] - a[1]) * (b[1] - a[1])) / L ** 2))
        p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        d = _dist(p, q)
        if d < d_mejor:
            mejor, d_mejor = acum + t * L, d
        acum += L
    return mejor


def construir_rutas(posiciones_m: dict[str, tuple[float, float]], borde: float = 8.0):
    """Para cada semáforo: carril de llegada, distancia a la línea de pare y rutas a cada destino."""
    salida = {}
    for s, (eje, carril) in LLEGADAS.items():
        entrada = _densificar(_desplazar([(p, carril) for p in eje]))
        L_ent = _largo(entrada)
        pare = min(_proyectar(entrada, posiciones_m[s]) - 2.0, L_ent - borde - 1.0)
        tramo_entrada = _recortar(entrada, 0, L_ent - borde)
        rutas = []
        for destino, tipo in GIROS[s]:
            if s == "S4" and destino == "E":
                # S4 gira a la derecha antes del cruce, en el ramal sur de la avenida (no entra al cruce)
                hasta_j = _proyectar(entrada, _J)
                tramo = _recortar(entrada, 0, hasta_j - 4)
                sal = _densificar(_desplazar([(_J, CARRIL_1S)] + [(p, CARRIL_1S) for p in _ORIENTE_SALE]))
                pts = _chaikin(tramo + _recortar(sal, 6), 3)
                pts = [(round(x, 2), round(y, 2)) for x, y in pts]
                rutas.append({"tipo": tipo, "destino": destino, "pts": pts,
                              "L": [round(v, 2) for v in _acumulado(pts)]})
                continue
            sal = _densificar(_desplazar(_salida(destino)))
            tramo_salida = _recortar(sal, borde)
            p1, p2 = tramo_entrada[-1], tramo_salida[0]
            d1 = (p1[0] - tramo_entrada[-2][0], p1[1] - tramo_entrada[-2][1])
            d2 = (tramo_salida[1][0] - p2[0], tramo_salida[1][1] - p2[1])
            den = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(den) > 1e-6:
                t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
                ctrl = (p1[0] + d1[0] * t, p1[1] + d1[1] * t)
                if _dist(ctrl, (0, 0)) > 20:
                    ctrl = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            else:
                ctrl = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            curva = [((1 - u) ** 2 * p1[0] + 2 * (1 - u) * u * ctrl[0] + u ** 2 * p2[0],
                      (1 - u) ** 2 * p1[1] + 2 * (1 - u) * u * ctrl[1] + u ** 2 * p2[1])
                     for u in [i / 12 for i in range(1, 12)]]
            pts = _chaikin(tramo_entrada + curva + tramo_salida, 2)
            pts = [(round(x, 2), round(y, 2)) for x, y in pts]
            rutas.append({"tipo": tipo, "destino": destino, "pts": pts, "L": [round(v, 2) for v in _acumulado(pts)]})
        # punto de pare sobre el carril y su distancia a lo largo de cada ruta (el suavizado la cambia un poco)
        punto_pare = _recortar(entrada, 0, pare)[-1]
        for r in rutas:
            r["pare"] = round(_proyectar(r["pts"], punto_pare), 2)
        pare_ruta = rutas[0]["pare"]
        salida[s] = {"entrada": [(round(x, 2), round(y, 2)) for x, y in entrada],
                     "Lentrada": [round(v, 2) for v in _acumulado(entrada)],
                     "pare": round(pare, 2), "pareRuta": round(pare_ruta, 2), "rutas": rutas}
    return salida
