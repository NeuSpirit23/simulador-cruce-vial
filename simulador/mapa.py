"""Mapa satelital del cruce con la animación de la simulación.

Usa Leaflet con imágenes satelitales de Esri (gratis, sin clave).
La animación reproduce ciclo por ciclo los resultados de la simulación:
cada carro en cola es un punto, y cuando el semáforo se pone en verde los
carros salen al ritmo de "pasan" de ese ciclo.

Los semáforos se ponen en verde uno después del otro (S1 → S2 → S3 → S4).
"""

import json

import pandas as pd

# Ubicación del cruce (editable desde la app). Cada semáforo se dibuja a cierta
# distancia del centro, en la dirección "rumbo" (grados: 0 = norte, 90 = este).
CENTRO_DEFECTO = (4.30360, -74.80300)
RUMBOS_DEFECTO = {"S1": 0, "S2": 90, "S3": 180, "S4": 270}


def html_mapa(ciclos: pd.DataFrame, info: pd.DataFrame, centro: tuple[float, float],
              rumbos: dict[str, float], inicio_texto: str, alto: int = 620) -> str:
    semaforos = []
    desfase = 0
    for _, r in info.iterrows():
        s = r["semaforo"]
        d = ciclos[ciclos["semaforo"] == s].sort_values("ciclo")
        semaforos.append({
            "id": s, "nombre": r["ubicacion"], "verde": int(r["verde_s"]), "ciclo": int(r["ciclo_s"]),
            "desfase": desfase, "rumbo": float(rumbos.get(s, 0)),
            "espera": d["en_espera"].astype(int).tolist(),
            "pasan": d["pasan"].astype(int).tolist(),
            "quedan": d["quedan"].astype(int).tolist(),
        })
        desfase += int(r["verde_s"])
    datos = json.dumps({"centro": list(centro), "semaforos": semaforos, "inicio": inicio_texto})

    return f"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body {{ margin:0; font-family: system-ui, sans-serif; }}
  #mapa {{ height:{alto - 120}px; width:100%; border-radius:8px; }}
  #barra {{ display:flex; gap:8px; align-items:center; padding:8px 0; flex-wrap:wrap; }}
  #barra button, #barra select {{ padding:6px 12px; border-radius:6px; border:1px solid #bbb; background:#fff; cursor:pointer; font-size:14px; }}
  #reloj {{ font-weight:600; margin-left:8px; }}
  #tablero {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }}
  .tarjeta {{ border:1px solid #ddd; border-radius:8px; padding:6px 10px; font-size:13px; background:#fafafa; }}
  .tarjeta b {{ font-size:14px; }}
  .luz {{ display:inline-block; width:12px; height:12px; border-radius:50%; margin-right:6px; vertical-align:-1px; }}
  .etiqueta {{ background:rgba(0,0,0,.7); color:#fff; border:none; border-radius:4px; font-size:12px; padding:2px 6px; box-shadow:none; }}
  .etiqueta:before {{ display:none; }}
</style></head><body>
<div id="barra">
  <button id="play">▶ Iniciar</button>
  <button id="reset">⟲ Reiniciar</button>
  <label>Velocidad <select id="vel">
    <option value="1">×1 (tiempo real)</option><option value="5">×5</option>
    <option value="10" selected>×10</option><option value="30">×30</option><option value="60">×60</option>
  </select></label>
  <span id="reloj"></span>
</div>
<div id="mapa"></div>
<div id="tablero"></div>
<script>
const D = {datos};
const mapa = L.map('mapa', {{zoomControl:true}}).setView(D.centro, 19);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
  {{maxZoom:20, maxNativeZoom:19, attribution:'Imágenes © Esri'}}).addTo(mapa);

function mover(lat, lon, rumbo, metros) {{
  const r = rumbo * Math.PI / 180;
  const dLat = metros * Math.cos(r) / 111320;
  const dLon = metros * Math.sin(r) / (111320 * Math.cos(lat * Math.PI / 180));
  return [lat + dLat, lon + dLon];
}}

const tablero = document.getElementById('tablero');
const S = D.semaforos.map(s => {{
  const pos = mover(D.centro[0], D.centro[1], s.rumbo, 14);
  const luz = L.circleMarker(pos, {{radius:9, color:'#000', weight:2, fillColor:'#d33', fillOpacity:1}}).addTo(mapa);
  const r = ((s.rumbo % 360) + 360) % 360;
  const dir = r < 45 || r >= 315 ? 'top' : r < 135 ? 'right' : r < 225 ? 'bottom' : 'left';
  const off = {{top:[0,-10], right:[10,0], bottom:[0,10], left:[-10,0]}}[dir];
  luz.bindTooltip(s.id + ' · ' + s.nombre, {{permanent:true, direction:dir, className:'etiqueta', offset:off}});
  const carros = [];
  const t = document.createElement('div'); t.className = 'tarjeta'; tablero.appendChild(t);
  return Object.assign(s, {{pos, luz, carros, tarjeta:t, total:0, ultimoCiclo:-1, salidos:0, moviendo:[]}});
}});

function estado(s, t) {{
  // Cada ciclo: primero rojo (llegan carros) y al final el verde (salen carros)
  const rojo = s.ciclo - s.verde;
  const t0 = s.desfase + s.verde - s.ciclo;          // inicio del ciclo 0
  const local = t - t0;
  const k = Math.floor(local / s.ciclo);
  const u = local - k * s.ciclo;
  if (k < 0) return {{k:-1, verde:false, cola:0, salidos:0}};
  if (k >= s.espera.length) return {{k, fin:true, verde:false, cola:s.quedan[s.quedan.length-1], salidos:0}};
  const antes = k > 0 ? s.quedan[k-1] : 0;
  if (u < rojo) {{
    const cola = Math.round(antes + (s.espera[k] - antes) * u / rojo);
    return {{k, verde:false, cola, salidos:0}};
  }}
  const f = (u - rojo) / s.verde;
  const salidos = Math.min(s.pasan[k], Math.floor(s.pasan[k] * f + 1e-9));
  return {{k, verde:true, cola:s.espera[k] - salidos, salidos}};
}}

function dibujarCola(s, n) {{
  const mostrar = Math.min(n, 40);
  while (s.carros.length < mostrar) {{
    const i = s.carros.length;
    const p = mover(s.pos[0], s.pos[1], s.rumbo, 6 + i * 5.5);
    s.carros.push(L.circleMarker(p, {{radius:4, color:'#fff', weight:1, fillColor:'#ffcc00', fillOpacity:1}}).addTo(mapa));
  }}
  while (s.carros.length > mostrar) mapa.removeLayer(s.carros.pop());
}}

function soltarCarro(s) {{
  const m = L.circleMarker(s.pos, {{radius:4, color:'#fff', weight:1, fillColor:'#33cc66', fillOpacity:1}}).addTo(mapa);
  s.moviendo.push({{m, t:0}});
}}

let t = 0, corriendo = false, ultimo = null;
const tiempoFinal = Math.max(...S.map(s => s.desfase + s.verde - s.ciclo + s.ciclo * s.espera.length));

function formatoHora(seg) {{
  const base = new Date(D.inicio);
  const d = new Date(base.getTime() + seg * 1000);
  return d.toLocaleString('es-CO', {{dateStyle:'short', timeStyle:'medium'}});
}}

function actualizar(dtReal) {{
  S.forEach(s => {{
    const e = estado(s, t);
    if (e.k !== s.ultimoCiclo) {{
      if (s.ultimoCiclo >= 0 && s.ultimoCiclo < s.pasan.length) s.total += s.pasan[s.ultimoCiclo];
      s.ultimoCiclo = e.k; s.salidos = 0;
    }}
    while (s.salidos < e.salidos) {{ soltarCarro(s); s.salidos++; }}
    dibujarCola(s, e.cola);
    s.luz.setStyle({{fillColor: e.verde ? '#2ecc40' : '#d33'}});
    s.moviendo = s.moviendo.filter(c => {{
      c.t += dtReal;
      const p = mover(s.pos[0], s.pos[1], s.rumbo + 180, 28 * Math.min(c.t / 1.2, 1));
      c.m.setLatLng(p);
      if (c.t > 1.2) {{ mapa.removeLayer(c.m); return false; }}
      return true;
    }});
    const ciclo = e.k < 0 ? '–' : Math.min(e.k + 1, s.pasan.length);
    const pasoAhora = (e.k >= 0 && e.k < s.pasan.length) ? s.salidos : 0;
    s.tarjeta.innerHTML = `<b><span class="luz" style="background:${{e.verde ? '#2ecc40' : '#d33'}}"></span>${{s.id}} · ${{s.nombre}}</b><br>
      Ciclo ${{ciclo}} de ${{s.pasan.length}} · verde ${{s.verde}} s / ciclo ${{s.ciclo}} s<br>
      En cola: <b>${{e.cola}}</b> · pasando este verde: <b>${{pasoAhora}}</b><br>
      Total que han pasado: <b>${{s.total + pasoAhora}}</b>`;
  }});
  document.getElementById('reloj').textContent = '🕒 ' + formatoHora(t);
}}

function bucle(ahora) {{
  if (!corriendo) return;
  const dt = ultimo === null ? 0 : (ahora - ultimo) / 1000;
  ultimo = ahora;
  t += dt * Number(document.getElementById('vel').value);
  if (t >= tiempoFinal) {{ t = tiempoFinal; corriendo = false; document.getElementById('play').textContent = '▶ Iniciar'; }}
  actualizar(dt);
  if (corriendo) requestAnimationFrame(bucle);
}}

document.getElementById('play').onclick = () => {{
  corriendo = !corriendo; ultimo = null;
  document.getElementById('play').textContent = corriendo ? '⏸ Pausar' : '▶ Continuar';
  if (corriendo) requestAnimationFrame(bucle);
}};
document.getElementById('reset').onclick = () => {{
  t = 0; corriendo = false; ultimo = null;
  S.forEach(s => {{ s.total = 0; s.ultimoCiclo = -1; s.salidos = 0; s.moviendo.forEach(c => mapa.removeLayer(c.m)); s.moviendo = []; }});
  document.getElementById('play').textContent = '▶ Iniciar';
  actualizar(0);
}};
actualizar(0);
</script></body></html>
"""
