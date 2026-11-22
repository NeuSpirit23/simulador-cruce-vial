"""Simulación en vivo del cruce: mapa satelital (2D) y maqueta 3D, sincronizados.

Un solo motor de animación mueve los carros en las dos vistas:

* Cada semáforo reproduce, ciclo por ciclo, lo que dio la simulación
  (en espera, pasan, quedan). Primero rojo (llegan carros a la cola) y al final
  el verde (salen al ritmo de "pasan").
* Cada carro que sale escoge al azar si gira a la izquierda, sigue derecho o
  gira a la derecha (con el mismo generador congruencial del curso), y recorre
  su trayectoria por los carriles del cruce. Los giros son solo visuales: no se
  midieron en campo y no cambian los conteos.
* Coordenadas en metros alrededor del centro del cruce (x = este, y = norte).
  En el mapa se convierten a latitud/longitud; en la vista 3D se usan directo.
"""

import json
import math

import pandas as pd

_PLANTILLA = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script type="importmap">{"imports":{"three":"https://unpkg.com/three@0.160.0/build/three.module.js",
"three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}</script>
<style>
 *{box-sizing:border-box}
 body{margin:0;font-family:"Inter",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#1d2433;background:transparent}
 #barra{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px 10px;background:#0f2a44;border-radius:12px 12px 0 0;color:#fff}
 #barra button,#barra select{padding:6px 12px;border-radius:8px;border:1px solid rgba(255,255,255,.25);background:rgba(255,255,255,.08);color:#fff;cursor:pointer;font-size:13px}
 #barra button.prim{background:#1f9d74;border-color:#1f9d74;font-weight:600}
 #barra select option{color:#000}
 #reloj{margin-left:auto;font-weight:600;font-variant-numeric:tabular-nums;background:rgba(255,255,255,.1);padding:5px 10px;border-radius:8px}
 .seg{display:inline-flex;border:1px solid rgba(255,255,255,.25);border-radius:8px;overflow:hidden}
 .seg button{border:none!important;border-radius:0!important}
 .seg button.on{background:#e9eef5!important;color:#0f2a44!important;font-weight:600}
 #vistas{display:flex;gap:6px;height:__ALTO_VISTA__px;background:#0f2a44;padding:0 6px 6px}
 #mapa,#tres{flex:1;border-radius:8px;overflow:hidden;position:relative;background:#1b2b3c}
 #tablero{display:grid;grid-template-columns:repeat(4,1fr) 1.1fr;gap:8px;margin-top:8px}
 .tarjeta{border:1px solid #e3e8ef;border-radius:10px;padding:8px 10px;font-size:12.5px;background:#fff;box-shadow:0 1px 2px rgba(16,24,40,.05)}
 .tarjeta b.t{font-size:13.5px;display:block;margin-bottom:3px}
 .luz{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px;vertical-align:-1px;box-shadow:0 0 6px currentColor}
 .num{font-variant-numeric:tabular-nums;font-weight:600}
 .ley{display:flex;gap:10px;flex-wrap:wrap;font-size:12px;margin-top:4px}
 .ley span{display:inline-flex;align-items:center;gap:4px}
 .chip{width:16px;height:8px;border-radius:2px;display:inline-block}
 .carro{width:15px;height:7px;border-radius:2px;border:1px solid rgba(0,0,0,.55);box-shadow:0 0 3px rgba(0,0,0,.5)}
 .etq{background:rgba(15,42,68,.88);color:#fff;border:none;border-radius:6px;font-size:11.5px;padding:2px 7px;box-shadow:none;font-weight:600}
 .etq:before{display:none}
 #aviso3d{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#cfd8e3;font-size:13px;text-align:center;padding:20px}
</style></head><body>
<div id="barra">
 <button id="play" class="prim">▶ Iniciar</button>
 <button id="reset">⟲ Reiniciar</button>
 <label>Velocidad <select id="vel">
  <option value="1">×1 tiempo real</option><option value="3">×3</option><option value="5" selected>×5</option>
  <option value="10">×10</option><option value="20">×20</option><option value="40">×40</option></select></label>
 <div class="seg" id="modo"><button data-m="mapa">🗺️ Mapa</button><button data-m="ambos" class="on">Ambos</button><button data-m="tres">🧊 3D</button></div>
 <span id="fases" style="font-size:12px;opacity:.85"></span><span id="reloj"></span>
</div>
<div id="vistas"><div id="mapa"></div><div id="tres"><div id="aviso3d">Cargando vista 3D…</div></div></div>
<div id="tablero"></div>
<script>
const D = __DATOS__;
// ---------------------------------------------------------------- utilidades geométricas (metros)
const rad = g => g*Math.PI/180;
const uDe = rumbo => [Math.sin(rad(rumbo)), Math.cos(rad(rumbo))];        // vector unitario (x este, y norte)
const derecha = v => [v[1], -v[0]];                                        // giro 90° horario
const suma = (a,b,k=1) => [a[0]+b[0]*k, a[1]+b[1]*k];
const rumboDe = v => (Math.atan2(v[0], v[1])*180/Math.PI + 360) % 360;
const CARRIL = 2.6, BORDE = 8;

// generador congruencial del curso para escoger destinos (mismo que la simulación)
let X = D.semilla % 2147483647 || 1;
const U = () => (X = (16807 * X) % 2147483647) / 2147483647;

const S = D.semaforos.map(s => {
  const u = uDe(s.rumbo);
  return Object.assign(s, {u, dentro:[-u[0],-u[1]], cola:[], moviendo:[], total:0, ultimoCiclo:-1,
                           salidos:0, giros:{izq:0, recto:0, der:0}});
});
// punto sobre el carril de entrada (hacia el cruce) o de salida (alejándose) de una calle
const pEntrada = (s, r) => suma([s.u[0]*r, s.u[1]*r], derecha(s.dentro), CARRIL);
const pSalida  = (s, r) => suma([s.u[0]*r, s.u[1]*r], derecha(s.u), CARRIL);

function cruceLineas(p, d, q, e){            // intersección de p + t·d con q + s·e
  const den = d[0]*e[1] - d[1]*e[0];
  if (Math.abs(den) < 0.15) return null;
  const t = ((q[0]-p[0])*e[1] - (q[1]-p[1])*e[0]) / den;
  return [p[0]+d[0]*t, p[1]+d[1]*t];
}
function tipoGiro(a, b){
  const z = a.dentro[0]*b.u[1] - a.dentro[1]*b.u[0];
  return z > 0.35 ? "izq" : (z < -0.35 ? "der" : "recto");
}
function ruta(a, b){                         // lista de puntos desde la línea de pare de a hasta salir por b
  const p0 = pEntrada(a, a.pare), p1 = pEntrada(a, BORDE), p2 = pSalida(b, BORDE), p3 = pSalida(b, 95);
  let c = cruceLineas(p1, a.dentro, p2, b.u);
  if (!c || Math.hypot(c[0], c[1]) > 25) c = [(p1[0]+p2[0])/2*0.5, (p1[1]+p2[1])/2*0.5];
  const pts = [p0];
  for (let i = 0; i <= 14; i++){              // curva de Bézier cuadrática dentro del cruce
    const t = i/14, m = 1-t;
    pts.push([m*m*p1[0] + 2*m*t*c[0] + t*t*p2[0], m*m*p1[1] + 2*m*t*c[1] + t*t*p2[1]]);
  }
  pts.push(p3);
  const L = [0];
  for (let i = 1; i < pts.length; i++) L.push(L[i-1] + Math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1]));
  return {pts, L, largo: L[L.length-1]};
}
function enRuta(r, d){                        // posición y rumbo a una distancia d de la ruta
  let i = 1; while (i < r.L.length-1 && r.L[i] < d) i++;
  const a = r.pts[i-1], b = r.pts[i], f = Math.min(1, Math.max(0, (d - r.L[i-1]) / ((r.L[i]-r.L[i-1]) || 1)));
  return {p:[a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f], rumbo: rumboDe([b[0]-a[0], b[1]-a[1]])};
}
// destinos posibles de cada semáforo, con su tipo de giro y probabilidad
S.forEach(a => {
  a.destinos = S.filter(b => b !== a).map(b => ({b, tipo: tipoGiro(a, b), ruta: ruta(a, b)}));
  const peso = {izq: D.prob.izq, recto: D.prob.recto, der: D.prob.der};
  const tot = a.destinos.reduce((s, d) => s + peso[d.tipo], 0) || 1;
  let acum = 0;
  a.destinos.forEach(d => { acum += peso[d.tipo] / tot; d.hasta = acum; });
});
const COLOR = {izq:"#a855f7", recto:"#22d3ee", der:"#facc15", cola:"#f8fafc"};

// ---------------------------------------------------------------- estado de cada semáforo en el tiempo t
function estado(s, t){
  const rojo = s.ciclo - s.verde, t0 = s.desfase + s.verde - s.ciclo, local = t - t0;
  const k = Math.floor(local / s.ciclo), u = local - k*s.ciclo;
  if (k < 0) return {k:-1, verde:false, cola:0, salidos:0};
  if (k >= s.espera.length) return {k, verde:false, cola:s.quedan[s.quedan.length-1], salidos:0, fin:true};
  const antes = k > 0 ? s.quedan[k-1] : 0;
  if (u < rojo) return {k, verde:false, cola:Math.round(antes + (s.espera[k]-antes)*u/rojo), salidos:0};
  const util = Math.max(1, s.verde - MARGEN);                // los últimos salen antes de que acabe el verde
  const salidos = Math.min(s.pasan[k], Math.floor(s.pasan[k]*(u-rojo)/util + 1e-9));
  return {k, verde:true, cola:s.espera[k]-salidos, salidos};
}
const MAX_COLA = 28, VEL = 12, MARGEN = 1.5;  // carros dibujados por cola; velocidad (m/s ≈ 43 km/h); margen de salida (s)
const slot = (s, i) => pEntrada(s, s.pare + 1.5 + i*6.2);

let t = 0, corriendo = false, ultimo = null;
const tFinal = Math.max(...S.map(s => s.desfase + s.verde - s.ciclo + s.ciclo*s.espera.length)) + D.despeje + 8;
const vistas = [];                            // renderizadores (mapa y 3D)

function paso(dtReal){
  const vel = Number(document.getElementById('vel').value);
  const dtMov = dtReal * vel;                  // todo se mueve con el reloj de la simulación
  S.forEach(s => {
    const e = estado(s, t);
    if (e.k !== s.ultimoCiclo){
      if (s.ultimoCiclo >= 0 && s.ultimoCiclo < s.pasan.length) s.total += s.pasan[s.ultimoCiclo];
      s.ultimoCiclo = e.k; s.salidos = 0;
    }
    s.enVerde = e.verde; s.e = e;
    // salen carros: el primero de la cola toma un destino al azar
    while (s.salidos < e.salidos){
      s.salidos++;
      const r = U(); const d = s.destinos.find(x => r < x.hasta) || s.destinos[s.destinos.length-1];
      s.giros[d.tipo]++;
      const c = s.cola.shift() || {id: Math.random()};
      c.ruta = d.ruta; c.tipo = d.tipo; c.t0 = t; c.d = 0;
      s.moviendo.push(c);
    }
    // la cola visible sigue al conteo de la simulación
    const objetivo = Math.min(e.cola, MAX_COLA);
    while (s.cola.length < objetivo){ const i = s.cola.length; const p = pEntrada(s, s.pare + 60 + i*6.2);
      s.cola.push({id: Math.random(), x:p[0], y:p[1], rumbo: rumboDe(s.dentro)}); }
    while (s.cola.length > objetivo) s.cola.pop();
    s.cola.forEach((c, i) => { const p = slot(s, i), f = Math.min(1, dtMov*1.2);
      c.x += (p[0]-c.x)*f; c.y += (p[1]-c.y)*f; c.rumbo = rumboDe(s.dentro); c.tipo = "cola"; });
    s.moviendo = s.moviendo.filter(c => { c.d = VEL*(t - c.t0); if (c.d >= c.ruta.largo) return false;
      const q = enRuta(c.ruta, c.d); c.x = q.p[0]; c.y = q.p[1]; c.rumbo = q.rumbo; return true; });
  });
  vistas.forEach(v => v.dibujar());
  tablero();
}

function hora(seg){ const d = new Date(new Date(D.inicio).getTime() + seg*1000);
  return d.toLocaleString('es-CO', {weekday:'short', day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit'}); }
document.getElementById('fases').textContent = 'Ciclo del cruce ' + Math.round(D.cicloComun) + ' s: '
  + S.map(s => s.id + ' ' + s.verde + ' s').join(' → ') + ' · todo rojo ' + D.despeje.toFixed(2).replace('.', ',') + ' s entre fases';
const tab = document.getElementById('tablero');
S.forEach(s => { s.tarjeta = document.createElement('div'); s.tarjeta.className = 'tarjeta'; tab.appendChild(s.tarjeta); });
const tarjTot = document.createElement('div'); tarjTot.className = 'tarjeta'; tab.appendChild(tarjTot);
function tablero(){
  let tot = 0, g = {izq:0, recto:0, der:0};
  S.forEach(s => { const e = s.e || {k:-1, cola:0};
    const ahora = (e.k >= 0 && e.k < s.pasan.length) ? s.salidos : 0; tot += s.total + ahora;
    ['izq','recto','der'].forEach(k => g[k] += s.giros[k]);
    const col = s.enVerde ? '#22c55e' : '#ef4444';
    s.tarjeta.innerHTML = `<b class="t"><span class="luz" style="background:${col};color:${col}"></span>${s.id} · ${s.nombre}</b>
      Ciclo <span class="num">${e.k < 0 ? '–' : Math.min(e.k+1, s.pasan.length)}</span> de ${s.pasan.length} · ${s.enVerde ? 'VERDE' : 'ROJO'} · verde ${s.verde} s<br>
      En cola <span class="num">${e.cola}</span> · pasando <span class="num">${ahora}</span><br>
      Total que han pasado <span class="num">${s.total + ahora}</span><br>
      <span style="color:#6b7280">↰ ${s.giros.izq} · ↑ ${s.giros.recto} · ↱ ${s.giros.der}</span>`; });
  const enVerde = S.find(s => s.enVerde);
  const fase = enVerde ? `<span style="color:#16a34a;font-weight:700">● ${enVerde.id} en verde</span>`
                       : `<span style="color:#dc2626;font-weight:700">● Todo en rojo (despeje ${D.despeje.toFixed(2).replace('.', ',')} s)</span>`;
  tarjTot.innerHTML = `<b class="t">Cruce completo</b>${fase}<br>Han pasado <span class="num">${tot}</span> vehículos<br>
    <div class="ley"><span><i class="chip" style="background:${COLOR.izq}"></i>izquierda ${g.izq}</span>
    <span><i class="chip" style="background:${COLOR.recto}"></i>derecho ${g.recto}</span>
    <span><i class="chip" style="background:${COLOR.der}"></i>derecha ${g.der}</span>
    <span><i class="chip" style="background:${COLOR.cola}; border:1px solid #999"></i>en cola</span></div>`;
  document.getElementById('reloj').textContent = '🕒 ' + hora(t);
}
function bucle(ahora){
  if (!corriendo) return;
  const dt = ultimo === null ? 0 : Math.min(0.1, (ahora - ultimo)/1000); ultimo = ahora;
  t += dt * Number(document.getElementById('vel').value);
  if (t >= tFinal){ t = tFinal; corriendo = false; document.getElementById('play').textContent = '▶ Iniciar'; }
  paso(dt);
  if (corriendo) requestAnimationFrame(bucle);
}
document.getElementById('play').onclick = () => { corriendo = !corriendo; ultimo = null;
  document.getElementById('play').textContent = corriendo ? '⏸ Pausar' : '▶ Continuar';
  if (corriendo) requestAnimationFrame(bucle); };
document.getElementById('reset').onclick = () => { t = 0; corriendo = false; ultimo = null; X = D.semilla % 2147483647 || 1;
  S.forEach(s => { s.total = 0; s.ultimoCiclo = -1; s.salidos = 0; s.cola = []; s.moviendo = []; s.giros = {izq:0, recto:0, der:0}; });
  document.getElementById('play').textContent = '▶ Iniciar'; paso(0); };
document.querySelectorAll('#modo button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#modo button').forEach(x => x.classList.toggle('on', x === b));
  const m = b.dataset.m;
  document.getElementById('mapa').style.display = m === 'tres' ? 'none' : 'block';
  document.getElementById('tres').style.display = m === 'mapa' ? 'none' : 'block';
  vistas.forEach(v => v.redimensionar && v.redimensionar());
});

// ---------------------------------------------------------------- vista 1: mapa satelital (Leaflet)
(function(){
  if (typeof L === 'undefined'){ document.getElementById('mapa').innerHTML = '<div id="aviso3d">No se pudo cargar el mapa (sin internet).</div>'; return; }
  const c0 = D.centro, kx = 111320*Math.cos(rad(c0[0]));
  const ll = p => [c0[0] + p[1]/111320, c0[1] + p[0]/kx];
  const mapa = L.map('mapa', {zoomControl:true, attributionControl:true}).setView(c0, 19);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:21, maxNativeZoom:19, attribution:'Imágenes © Esri'}).addTo(mapa);
  // carriles de entrada y salida (guías)
  S.forEach(s => {
    L.polyline([ll(pEntrada(s, s.pare + 80)), ll(pEntrada(s, s.pare))], {color:'#ffffff', weight:1.5, opacity:.45, dashArray:'4 6'}).addTo(mapa);
    L.polyline([ll(pSalida(s, BORDE)), ll(pSalida(s, 95))], {color:'#ffffff', weight:1.5, opacity:.25, dashArray:'2 8'}).addTo(mapa);
    s.luz2d = L.circleMarker(ll([s.x, s.y]), {radius:9, color:'#111', weight:2, fillColor:'#ef4444', fillOpacity:1}).addTo(mapa);
    const r = (s.rumbo % 360 + 360) % 360;
    const dir = r < 45 || r >= 315 ? 'top' : r < 135 ? 'right' : r < 225 ? 'bottom' : 'left';
    s.luz2d.bindTooltip(s.id + ' · ' + s.nombre, {permanent:true, direction:dir, className:'etq', offset:{top:[0,-10],right:[10,0],bottom:[0,10],left:[-10,0]}[dir]});
  });
  const marcas = new Map();
  function marca(c){
    let m = marcas.get(c.id);
    if (!m){ m = L.marker(ll([c.x, c.y]), {icon: L.divIcon({className:'', html:'<div class="carro"></div>', iconSize:[15,7], iconAnchor:[7,3]}), interactive:false}).addTo(mapa);
             marcas.set(c.id, m); }
    m.setLatLng(ll([c.x, c.y]));
    const el = m.getElement() && m.getElement().firstChild;
    if (el){ el.style.transform = `rotate(${c.rumbo - 90}deg)`; el.style.background = COLOR[c.tipo] || COLOR.cola; }
    return c.id;
  }
  vistas.push({
    dibujar(){
      const vivos = new Set();
      S.forEach(s => { s.luz2d.setStyle({fillColor: s.enVerde ? '#22c55e' : '#ef4444'});
        s.cola.forEach(c => vivos.add(marca(c))); s.moviendo.forEach(c => vivos.add(marca(c))); });
      for (const [id, m] of marcas) if (!vivos.has(id)){ mapa.removeLayer(m); marcas.delete(id); }
    },
    redimensionar(){ setTimeout(() => mapa.invalidateSize(), 50); }
  });
})();
</script>
<script type="module">
// ---------------------------------------------------------------- vista 2: maqueta 3D (three.js)
const caja = document.getElementById('tres');
try {
  const THREE = await import('three');
  const {OrbitControls} = await import('three/addons/controls/OrbitControls.js');
  document.getElementById('aviso3d').remove();
  const escena = new THREE.Scene();
  escena.background = new THREE.Color(0xbcd7ee);
  escena.fog = new THREE.Fog(0xbcd7ee, 160, 420);
  const cam = new THREE.PerspectiveCamera(45, 1, 0.5, 1000);
  cam.position.set(70, 75, 85);
  const render = new THREE.WebGLRenderer({antialias:true});
  render.setPixelRatio(Math.min(2, window.devicePixelRatio));
  render.shadowMap.enabled = true;
  caja.appendChild(render.domElement);
  const ctl = new OrbitControls(cam, render.domElement);
  ctl.target.set(0, 0, 0); ctl.maxPolarAngle = Math.PI/2.1; ctl.enableDamping = true;
  escena.add(new THREE.HemisphereLight(0xffffff, 0x58704a, 0.9));
  const sol = new THREE.DirectionalLight(0xffffff, 1.1); sol.position.set(60, 120, 40); sol.castShadow = true;
  sol.shadow.camera.left = sol.shadow.camera.bottom = -150; sol.shadow.camera.right = sol.shadow.camera.top = 150;
  sol.shadow.mapSize.set(2048, 2048); escena.add(sol);
  const P = (x, y) => new THREE.Vector3(x, 0, -y);           // metros (este, norte) → escena
  const mat = c => new THREE.MeshStandardMaterial({color:c, roughness:.85});
  // suelo
  const suelo = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), mat(0x8fae74)); suelo.rotation.x = -Math.PI/2; suelo.receiveShadow = true; escena.add(suelo);
  // vías
  const via = mat(0x3b3f45), linea = new THREE.MeshBasicMaterial({color:0xf4f4f4}), amarilla = new THREE.MeshBasicMaterial({color:0xf2c230});
  const plaza = new THREE.Mesh(new THREE.CircleGeometry(13, 40), via); plaza.rotation.x = -Math.PI/2; plaza.position.y = 0.02; plaza.receiveShadow = true; escena.add(plaza);
  S.forEach(s => {
    const largo = 140, g = new THREE.Mesh(new THREE.PlaneGeometry(10.5, largo), via);
    g.rotation.x = -Math.PI/2; g.rotation.z = -rad(s.rumbo); const m = P(s.u[0]*largo/2, s.u[1]*largo/2);
    g.position.set(m.x, 0.03, m.z); g.receiveShadow = true; escena.add(g);
    // andén
    [1, -1].forEach(lado => { const a = new THREE.Mesh(new THREE.BoxGeometry(2.2, 0.25, largo - 14), mat(0xc9c5bb));
      const off = derecha(s.u), c = suma([s.u[0]*(largo/2 + 7), s.u[1]*(largo/2 + 7)], off, 6.4*lado);
      a.position.copy(P(c[0], c[1])); a.position.y = 0.12; a.rotation.y = -rad(s.rumbo); a.receiveShadow = true; escena.add(a); });
    // línea central amarilla y líneas de borde
    const lc = new THREE.Mesh(new THREE.PlaneGeometry(0.25, largo - 14), amarilla);
    const cc = [s.u[0]*(largo/2 + 7), s.u[1]*(largo/2 + 7)];
    lc.rotation.x = -Math.PI/2; lc.rotation.z = -rad(s.rumbo); lc.position.set(P(...cc).x, 0.05, P(...cc).z); escena.add(lc);
    // paso peatonal (cebra)
    for (let i = -4; i <= 4; i++){ const z = new THREE.Mesh(new THREE.PlaneGeometry(0.6, 3), linea);
      const p = suma([s.u[0]*(BORDE + 4.5), s.u[1]*(BORDE + 4.5)], derecha(s.u), i*1.1);
      z.rotation.x = -Math.PI/2; z.rotation.z = -rad(s.rumbo); z.position.set(P(...p).x, 0.05, P(...p).z); escena.add(z); }
  });
  // edificios (aleatorios pero siempre iguales)
  let sx = 7;  const rnd = () => (sx = (16807*sx) % 2147483647) / 2147483647;
  const libre = (x, y) => S.every(s => { const d = x*s.u[0] + y*s.u[1]; const perp = Math.abs(x*s.u[1] - y*s.u[0]); return d < 0 || perp > 14; }) && Math.hypot(x, y) > 22;
  const tonos = [0xe8e1d5, 0xd9cbb4, 0xc7d0d9, 0xe3d3c3, 0xb8c4b1, 0xf0e6da];
  for (let i = 0; i < 160; i++){
    const x = (rnd()-0.5)*260, y = (rnd()-0.5)*260; if (!libre(x, y)) continue;
    const w = 8 + rnd()*14, d = 8 + rnd()*14, h = 3 + Math.pow(rnd(), 2)*18;
    const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(tonos[Math.floor(rnd()*tonos.length)]));
    b.position.copy(P(x, y)); b.position.y = h/2; b.castShadow = b.receiveShadow = true; escena.add(b);
  }
  // árboles
  for (let i = 0; i < 70; i++){ const x = (rnd()-0.5)*240, y = (rnd()-0.5)*240; if (!libre(x, y)) continue;
    const tr = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.3, 2.5), mat(0x6b4f2a)); tr.position.copy(P(x, y)); tr.position.y = 1.25; escena.add(tr);
    const co = new THREE.Mesh(new THREE.SphereGeometry(2 + rnd()*1.5, 10, 8), mat(0x4f7d3a)); co.position.copy(P(x, y)); co.position.y = 3.8; co.castShadow = true; escena.add(co); }
  // semáforos: poste + cabeza con luz roja y verde
  S.forEach(s => {
    const base = pEntrada(s, s.pare), lado = suma(base, derecha(s.dentro), 4.2);
    const poste = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 6), mat(0x2b2b2b));
    poste.position.copy(P(...lado)); poste.position.y = 3; poste.castShadow = true; escena.add(poste);
    const brazo = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, 4.4), mat(0x2b2b2b));
    const mitad = suma(lado, derecha(s.dentro), -2.1); brazo.position.copy(P(...mitad)); brazo.position.y = 6;
    brazo.rotation.y = -rad(rumboDe(derecha(s.dentro))); escena.add(brazo);
    const cab = new THREE.Mesh(new THREE.BoxGeometry(0.8, 2, 0.6), mat(0x111111));
    const pc = suma(lado, derecha(s.dentro), -4.1); cab.position.copy(P(...pc)); cab.position.y = 5.6; escena.add(cab);
    const mk = (y, c) => { const m = new THREE.MeshStandardMaterial({color:c, emissive:c, emissiveIntensity:0.1});
      const b = new THREE.Mesh(new THREE.SphereGeometry(0.28, 14, 10), m); b.position.copy(P(...suma(pc, s.dentro, -0.35))); b.position.y = y; escena.add(b); return m; };
    s.rojo3 = mk(6.15, 0xff3b30); s.verde3 = mk(5.05, 0x22c55e);
    s.luzPunto = new THREE.PointLight(0xff3b30, 0, 14); s.luzPunto.position.copy(P(...pc)); s.luzPunto.position.y = 5.5; escena.add(s.luzPunto);
    // letrero
    const cv = document.createElement('canvas'); cv.width = 256; cv.height = 64; const cx = cv.getContext('2d');
    cx.fillStyle = 'rgba(15,42,68,.9)'; cx.fillRect(0, 0, 256, 64); cx.fillStyle = '#fff'; cx.font = 'bold 30px sans-serif';
    cx.fillText(s.id + ' · ' + s.nombre, 12, 43);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(cv)})); sp.scale.set(10, 2.5, 1);
    sp.position.copy(P(...lado)); sp.position.y = 8.6; escena.add(sp);
  });
  // carros
  const colores = {izq:0xa855f7, recto:0x22d3ee, der:0xfacc15, cola:0xe5e7eb};
  const geoCuerpo = new THREE.BoxGeometry(1.9, 1.0, 4.3), geoCabina = new THREE.BoxGeometry(1.7, 0.75, 2.2);
  const matCabina = new THREE.MeshStandardMaterial({color:0x1f2937, roughness:.3, metalness:.4});
  const carros = new Map();
  function carro(c){
    let m = carros.get(c.id);
    if (!m){ m = new THREE.Group(); const cu = new THREE.Mesh(geoCuerpo, new THREE.MeshStandardMaterial({color:colores.cola, roughness:.5, metalness:.2}));
      cu.position.y = 0.75; cu.castShadow = true; m.add(cu); const ca = new THREE.Mesh(geoCabina, matCabina); ca.position.set(0, 1.6, -0.2); m.add(ca);
      m.userData.cuerpo = cu; escena.add(m); carros.set(c.id, m); }
    m.position.copy(P(c.x, c.y)); m.rotation.y = -rad(c.rumbo) + Math.PI;
    m.userData.cuerpo.material.color.setHex(colores[c.tipo] || colores.cola);
    return c.id;
  }
  function tam(){ const w = caja.clientWidth || 600, h = caja.clientHeight || 400; render.setSize(w, h); cam.aspect = w/h; cam.updateProjectionMatrix(); }
  tam(); window.addEventListener('resize', tam);
  vistas.push({
    dibujar(){
      const vivos = new Set();
      S.forEach(s => { s.rojo3.emissiveIntensity = s.enVerde ? 0.05 : 2.2; s.verde3.emissiveIntensity = s.enVerde ? 2.2 : 0.05;
        s.luzPunto.color.setHex(s.enVerde ? 0x22c55e : 0xff3b30); s.luzPunto.intensity = 12;
        s.cola.forEach(c => vivos.add(carro(c))); s.moviendo.forEach(c => vivos.add(carro(c))); });
      for (const [id, m] of carros) if (!vivos.has(id)){ escena.remove(m); carros.delete(id); }
    },
    redimensionar(){ setTimeout(tam, 60); }
  });
  (function loop(){ ctl.update(); render.render(escena, cam); requestAnimationFrame(loop); })();
  paso(0);
} catch (err) {
  document.getElementById('aviso3d').textContent = 'No se pudo cargar la vista 3D (se necesita internet y un navegador con WebGL).';
}
</script>
<script>paso(0);</script>
</body></html>"""


def _metros(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    return ((lon - lon0) * 111320 * math.cos(math.radians(lat0)), (lat - lat0) * 111320)


def html_visor(ciclos: pd.DataFrame, info: pd.DataFrame, centro: tuple[float, float],
               posiciones: dict[str, dict], inicio_texto: str, semilla: int,
               prob_giros: dict | None = None, alto_vista: int = 470) -> str:
    """HTML del visor (mapa + 3D). prob_giros = {'izq': %, 'recto': %, 'der': %} (solo visual)."""
    prob = prob_giros or {"izq": 30, "recto": 40, "der": 30}
    # Un solo ciclo para todo el cruce (el más largo) con las fases en secuencia S1 → S2 → S3 → S4 y un
    # tiempo de "todo en rojo" (despeje) entre fases, para que nunca haya dos verdes a la vez.
    ciclo_comun = int(info["ciclo_s"].max())
    despeje = max(2.0, (ciclo_comun - int(info["verde_s"].sum())) / len(info))
    ciclo_comun = int(info["verde_s"].sum()) + despeje * len(info)
    semaforos = []
    desfase = 0.0
    for _, r in info.iterrows():
        s = r["semaforo"]
        d = ciclos[ciclos["semaforo"] == s].sort_values("ciclo")
        pos = posiciones[s]
        x, y = _metros(centro[0], centro[1], pos["lat"], pos["lon"])
        rumbo = float(pos["rumbo"])
        u = (math.sin(math.radians(rumbo)), math.cos(math.radians(rumbo)))
        pare = max(9.0, x * u[0] + y * u[1])          # distancia de la línea de pare al centro, sobre la calle
        semaforos.append({
            "id": s, "nombre": r["ubicacion"], "verde": int(r["verde_s"]), "ciclo": ciclo_comun,
            "cicloReal": int(r["ciclo_s"]),
            "desfase": desfase, "rumbo": rumbo, "x": x, "y": y, "pare": pare,
            "espera": d["en_espera"].astype(int).tolist(), "pasan": d["pasan"].astype(int).tolist(),
            "quedan": d["quedan"].astype(int).tolist(),
        })
        desfase += int(r["verde_s"]) + despeje
    datos = {"centro": list(centro), "semaforos": semaforos, "inicio": inicio_texto,
             "semilla": int(semilla), "prob": prob, "cicloComun": ciclo_comun, "despeje": despeje}
    return (_PLANTILLA.replace("__DATOS__", json.dumps(datos))
            .replace("__ALTO_VISTA__", str(alto_vista)))
