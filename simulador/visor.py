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
<style>__LEAFLET_CSS__</style>
<script>__LEAFLET_JS__</script>
<script type="importmap">__IMPORTMAP__</script>
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
 .ref{background:rgba(255,255,255,.85);color:#475569;border:0;box-shadow:none;font-size:10px;padding:1px 5px;border-radius:5px}
 .ref::before{display:none}
 .etq{background:rgba(15,42,68,.88);color:#fff;border:none;border-radius:6px;font-size:11.5px;padding:2px 7px;box-shadow:none;font-weight:600}
 .etq:before{display:none}
 #aviso3d{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#cfd8e3;font-size:13px;text-align:center;padding:20px}
</style></head><body>
<div id="barra">
 <button id="play" class="prim">Iniciar</button>
 <button id="reset">Reiniciar</button>
 <label>Velocidad <select id="vel">
  <option value="1">×1 tiempo real</option><option value="3">×3</option><option value="5" selected>×5</option>
  <option value="10">×10</option><option value="20">×20</option><option value="40">×40</option></select></label>
 <div class="seg" id="modo"><button data-m="mapa">Mapa</button><button data-m="ambos" class="on">Ambos</button><button data-m="tres">3D</button></div>
 <span id="fases" style="font-size:12px;opacity:.85"></span><span id="reloj"></span>
</div>
<div id="vistas"><div id="mapa"></div><div id="tres"><div id="aviso3d">Cargando vista 3D…</div></div></div>
<div id="tablero"></div>
<script>
const D = __DATOS__;
// ---------------------------------------------------------------- geometría (metros: x = este, y = norte)
const rad = g => g*Math.PI/180;
const rumboDe = v => (Math.atan2(v[0], v[1])*180/Math.PI + 360) % 360;
// generador congruencial del curso para escoger destinos (mismo que la simulación)
let X = D.semilla % 2147483647 || 1;
const U = () => (X = (16807 * X) % 2147483647) / 2147483647;
// punto y rumbo a una distancia d sobre una polilínea (pts) con largos acumulados (L)
function enLinea(pts, L, d){
  d = Math.max(0, Math.min(L[L.length-1], d));
  let lo = 1, hi = L.length - 1;
  while (lo < hi){ const mid = (lo + hi) >> 1; if (L[mid] < d) lo = mid + 1; else hi = mid; }
  const a = pts[lo-1], b = pts[lo], f = (d - L[lo-1]) / ((L[lo] - L[lo-1]) || 1);
  return {p:[a[0] + (b[0]-a[0])*f, a[1] + (b[1]-a[1])*f], rumbo: rumboDe([b[0]-a[0], b[1]-a[1]])};
}
const S = D.semaforos.map(s => Object.assign(s, {cola:[], moviendo:[], total:0, ultimoCiclo:-1, salidos:0,
                                                  giros:{izq:0, recto:0, der:0}}));
// probabilidad de cada destino según el tipo de giro
S.forEach(a => {
  const peso = {izq: D.prob.izq, recto: D.prob.recto, der: D.prob.der};
  const tot = a.rutas.reduce((x, r) => x + peso[r.tipo], 0) || 1;
  let acum = 0;
  a.rutas.forEach(r => { acum += peso[r.tipo] / tot; r.hasta = acum; });
});
const COLOR = {izq:"#a855f7", recto:"#22d3ee", der:"#facc15", cola:"#f8fafc"};
const posCola = (s, i) => enLinea(s.entrada, s.Lentrada, s.pare - 1.5 - i*6.2);

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
      const r = U(); const d = s.rutas.find(x => r < x.hasta) || s.rutas[s.rutas.length-1];
      s.giros[d.tipo]++;
      const c = s.cola.shift() || {id: Math.random()};
      c.ruta = d; c.tipo = d.tipo; c.t0 = t; c.d = d.pare;
      s.moviendo.push(c);
    }
    // la cola visible sigue al conteo de la simulación
    const objetivo = Math.min(e.cola, MAX_COLA);
    while (s.cola.length < objetivo){ const i = s.cola.length; const q = enLinea(s.entrada, s.Lentrada, s.pare - 60 - i*6.2);
      s.cola.push({id: Math.random(), x:q.p[0], y:q.p[1], rumbo: q.rumbo}); }
    while (s.cola.length > objetivo) s.cola.pop();
    s.cola.forEach((c, i) => { const q = posCola(s, i), f = Math.min(1, dtMov*1.2);
      c.x += (q.p[0]-c.x)*f; c.y += (q.p[1]-c.y)*f; c.rumbo = q.rumbo; c.tipo = "cola"; });
    s.moviendo = s.moviendo.filter(c => { c.d = c.ruta.pare + VEL*(t - c.t0); const L = c.ruta.L;
      if (c.d >= L[L.length-1]) return false;
      const q = enLinea(c.ruta.pts, L, c.d); c.x = q.p[0]; c.y = q.p[1]; c.rumbo = q.rumbo; return true; });
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
  document.getElementById('reloj').textContent = '' + hora(t);
}
function bucle(ahora){
  if (!corriendo) return;
  const dt = ultimo === null ? 0 : Math.min(0.1, (ahora - ultimo)/1000); ultimo = ahora;
  t += dt * Number(document.getElementById('vel').value);
  if (t >= tFinal){ t = tFinal; corriendo = false; document.getElementById('play').textContent = 'Iniciar'; }
  paso(dt);
  if (corriendo) requestAnimationFrame(bucle);
}
document.getElementById('play').onclick = () => { corriendo = !corriendo; ultimo = null;
  document.getElementById('play').textContent = corriendo ? 'Pausar' : 'Continuar';
  if (corriendo) requestAnimationFrame(bucle); };
document.getElementById('reset').onclick = () => { t = 0; corriendo = false; ultimo = null; X = D.semilla % 2147483647 || 1;
  S.forEach(s => { s.total = 0; s.ultimoCiclo = -1; s.salidos = 0; s.cola = []; s.moviendo = []; s.giros = {izq:0, recto:0, der:0}; });
  document.getElementById('play').textContent = 'Iniciar'; paso(0); };
document.querySelectorAll('#modo button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#modo button').forEach(x => x.classList.toggle('on', x === b));
  const m = b.dataset.m;
  document.getElementById('mapa').style.display = m === 'tres' ? 'none' : 'block';
  document.getElementById('tres').style.display = m === 'mapa' ? 'none' : 'block';
  vistas.forEach(v => v.redimensionar && v.redimensionar());
});

// ---------------------------------------------------------------- vista 1: mapa satelital (Leaflet)
(function(){
  if (typeof L === 'undefined'){ document.getElementById('mapa').innerHTML = '<div id="aviso3d">No se pudo cargar el mapa.</div>'; return; }
  const c0 = D.centro, kx = 111320*Math.cos(rad(c0[0]));
  const ll = p => [c0[0] + p[1]/111320, c0[1] + p[0]/kx];
  const mapa = L.map('mapa', {zoomControl:true, attributionControl:true}).setView(c0, 19);
  const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:21, maxNativeZoom:19, attribution:'Imágenes © Esri'}).addTo(mapa);
  // Sin internet no llegan las fotos satelitales: se dibuja un plano con las vías reales, a escala
  let fotos = 0, plano = null;
  sat.on('tileload', () => { fotos++; });
  function dibujarPlano(){
    if (plano || fotos > 0) return;
    mapa.removeLayer(sat);
    document.getElementById('mapa').style.background = '#dfe8d6';
    mapa.createPane('plano').style.zIndex = 350;   // debajo de las guías, semáforos y carros
    mapa.createPane('refs').style.zIndex = 380;    // nombres de negocios, debajo de las etiquetas S1–S4
    plano = L.layerGroup().addTo(mapa);
    const mpp = () => 40075016.686 * Math.cos(rad(c0[0])) / Math.pow(2, mapa.getZoom() + 8);  // metros por píxel
    const capas = [];
    D.vias.forEach(v => {
      const a = L.polyline(v.pts.map(ll), {pane:'plano', color:'#cfcac0', weight:1, lineCap:'round', interactive:false}).addTo(plano);
      const b = L.polyline(v.pts.map(ll), {pane:'plano', color:'#3b3f45', weight:1, lineCap:'round', interactive:false}).addTo(plano);
      capas.push([a, v.ancho + 4.2], [b, v.ancho]);
    });
    const plaza = L.circle(c0, {pane:'plano', radius:11, stroke:false, fillColor:'#3b3f45', fillOpacity:1, interactive:false}).addTo(plano);
    D.referencias.forEach(r => L.tooltip({pane:'refs', permanent:true, direction:'center', className:'ref'}).setLatLng(ll(r.p))
      .setContent(r.nombre).addTo(plano));
    const ajustar = () => capas.forEach(([l, w]) => l.setStyle({weight: Math.max(2, w / mpp())}));
    mapa.on('zoomend', ajustar); ajustar();
    mapa.attributionControl.setPrefix('Plano dibujado (sin conexión)');
  }
  sat.on('tileerror', () => setTimeout(dibujarPlano, 1500));
  setTimeout(dibujarPlano, 6000);
  // ejes de las vías y carriles de llegada (guías)
  D.vias.forEach(v => L.polyline(v.pts.map(ll), {color:'#ffffff', weight:1, opacity:.22, dashArray: v.doble ? null : '6 6'}).addTo(mapa));
  S.forEach(s => {
    const desde = Math.max(0, s.pare - 90), tramo = s.entrada.filter((p, i) => s.Lentrada[i] >= desde && s.Lentrada[i] <= s.pare);
    L.polyline(tramo.map(ll), {color:'#ffffff', weight:1.5, opacity:.45, dashArray:'4 6'}).addTo(mapa);
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
  const {OrbitControls} = await import('three/addons/controls/OrbitControls.js');  // incluidas en el HTML
  document.getElementById('aviso3d').remove();
  const escena = new THREE.Scene();
  escena.background = new THREE.Color(0xbcd7ee);
  escena.fog = new THREE.Fog(0xbcd7ee, 160, 420);
  const cam = new THREE.PerspectiveCamera(45, 1, 0.5, 1000);
  cam.position.set(95, 105, 120);
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
  // utilidades 2D para la escena
  const sub = (a, b) => [a[0]-b[0], a[1]-b[1]], lon = v => Math.hypot(v[0], v[1]);
  const der = v => { const n = lon(v) || 1; return [v[1]/n, -v[0]/n]; };
  function distSeg(p, a, b){ const ab = sub(b, a), t = Math.max(0, Math.min(1, ((p[0]-a[0])*ab[0] + (p[1]-a[1])*ab[1]) / ((ab[0]**2 + ab[1]**2) || 1)));
    return lon(sub(p, [a[0] + ab[0]*t, a[1] + ab[1]*t])); }
  function franja(a, b, ancho, y, material){       // rectángulo plano de a a b
    const v = sub(b, a), L = lon(v); if (L < 0.01) return;
    const g = new THREE.Mesh(new THREE.PlaneGeometry(ancho, L), material);
    g.rotation.x = -Math.PI/2; g.rotation.z = -Math.atan2(v[0], v[1]);
    const c = P((a[0]+b[0])/2, (a[1]+b[1])/2); g.position.set(c.x, y, c.z); g.receiveShadow = true; escena.add(g);
  }
  function letrero(texto, pos, alto, escala, fondo){
    const cv = document.createElement('canvas'); cv.width = 512; cv.height = 96; const cx = cv.getContext('2d');
    cx.fillStyle = fondo || 'rgba(15,42,68,.9)'; cx.fillRect(0, 0, 512, 96); cx.fillStyle = '#fff'; cx.font = 'bold 40px sans-serif';
    cx.textAlign = 'center'; cx.fillText(texto, 256, 62);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(cv), depthTest: false}));
    sp.scale.set(escala, escala * 96/512, 1); sp.position.copy(P(pos[0], pos[1])); sp.position.y = alto; escena.add(sp); return sp;
  }
  // vías reales del cruce (trazadas sobre la imagen de Google Maps)
  const via = mat(0x3b3f45), anden = mat(0xcfcac0), blanca = new THREE.MeshBasicMaterial({color:0xf4f4f4}),
        amarilla = new THREE.MeshBasicMaterial({color:0xf2c230});
  D.vias.forEach(v => {
    for (let i = 1; i < v.pts.length; i++){
      const a = v.pts[i-1], b = v.pts[i], n = der(sub(b, a));
      franja(a, b, v.ancho + 4.2, 0.012, anden);                     // andenes
      franja(a, b, v.ancho, 0.03, via);                              // calzada
      if (v.doble) franja(a, b, 0.25, 0.05, amarilla);               // línea central
      else { const L = lon(sub(b, a)); for (let d = 2; d < L - 2; d += 7){ const f0 = d/L, f1 = Math.min(1, (d+3)/L);
        franja([a[0]+(b[0]-a[0])*f0, a[1]+(b[1]-a[1])*f0], [a[0]+(b[0]-a[0])*f1, a[1]+(b[1]-a[1])*f1], 0.2, 0.05, blanca); } }
    }
    v.pts.forEach(p => { const d = new THREE.Mesh(new THREE.CircleGeometry(v.ancho/2, 24), via); d.rotation.x = -Math.PI/2;
      const q = P(p[0], p[1]); d.position.set(q.x, 0.031, q.z); escena.add(d); });
  });
  // nombres de las calles sobre el piso
  D.vias.forEach(v => { const i = Math.max(1, Math.floor(v.pts.length/2)); const a = v.pts[i-1], b = v.pts[i];
    letrero(v.nombre, [(a[0]*0.4 + b[0]*0.6), (a[1]*0.4 + b[1]*0.6)], 2.2, 18, 'rgba(31,41,55,.78)'); });
  const plaza = new THREE.Mesh(new THREE.CircleGeometry(11, 40), via); plaza.rotation.x = -Math.PI/2; plaza.position.y = 0.035; escena.add(plaza);
  // cebras en cada llegada al cruce
  S.forEach(s => { const L = s.Lentrada, fin = L[L.length-1];
    const q = enLinea(s.entrada, L, Math.min(s.pare + 3.5, fin - 2)); const dir = [Math.sin(rad(q.rumbo)), Math.cos(rad(q.rumbo))], n = der(dir);
    for (let i = -4; i <= 4; i++){ const c = [q.p[0] + n[0]*i*1.1 - n[0]*2.6, q.p[1] + n[1]*i*1.1 - n[1]*2.6];
      franja([c[0] - dir[0]*1.5, c[1] - dir[1]*1.5], [c[0] + dir[0]*1.5, c[1] + dir[1]*1.5], 0.6, 0.06, blanca); } });
  // --- ubicación de edificios: nunca encima de la vía ni del andén --------------------------------
  const MARGEN_ANDEN = 2.1 + 0.8;                 // andén (2,1 m) + 0,8 m de antejardín
  function viaCercana(p){
    let mejor = {d: 1e9};
    D.vias.forEach(v => { for (let i = 1; i < v.pts.length; i++){ const a = v.pts[i-1], b = v.pts[i];
      const d = distSeg(p, a, b) - v.ancho/2; if (d < mejor.d){ const ab = sub(b, a), L = lon(ab) || 1;
        mejor = {d, dir:[ab[0]/L, ab[1]/L], a, b}; } } });
    return mejor;
  }
  function esquinas(c, w, d, ang){                 // ang = rumbo (rad) del lado largo "d"
    const al = [Math.sin(ang), Math.cos(ang)], pe = [Math.cos(ang), -Math.sin(ang)];
    const out = [c];
    [[1,1],[1,-1],[-1,1],[-1,-1],[1,0],[-1,0],[0,1],[0,-1]].forEach(([i, j]) =>
      out.push([c[0] + al[0]*i*d/2 + pe[0]*j*w/2, c[1] + al[1]*i*d/2 + pe[1]*j*w/2]));
    return out;
  }
  // distancia real entre el rectángulo del edificio y cada tramo de vía (no solo sus esquinas):
  // 0 si el tramo lo corta o queda adentro; si no, la menor distancia entre bordes
  const cruz = (o, a, b) => (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0]);
  function seCortan(p1, p2, q1, q2){
    const d1 = cruz(q1, q2, p1), d2 = cruz(q1, q2, p2), d3 = cruz(p1, p2, q1), d4 = cruz(p1, p2, q2);
    return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
  }
  function dentroRect(p, r){                       // r = 4 esquinas en orden
    let s0 = 0; for (let i = 0; i < 4; i++){ const c = cruz(r[i], r[(i+1)%4], p); if (c === 0) continue;
      if (s0 === 0) s0 = Math.sign(c); else if (Math.sign(c) !== s0) return false; } return true;
  }
  function rect(c, w, d, ang){
    const al = [Math.sin(ang), Math.cos(ang)], pe = [Math.cos(ang), -Math.sin(ang)];
    return [[1,1],[1,-1],[-1,-1],[-1,1]].map(([i, j]) => [c[0] + al[0]*i*d/2 + pe[0]*j*w/2, c[1] + al[1]*i*d/2 + pe[1]*j*w/2]);
  }
  function distRectSeg(r, a, b){
    if (dentroRect(a, r) || dentroRect(b, r)) return 0;
    let m = 1e9;
    for (let i = 0; i < 4; i++){ const e1 = r[i], e2 = r[(i+1)%4];
      if (seCortan(a, b, e1, e2)) return 0;
      m = Math.min(m, distSeg(e1, a, b), distSeg(a, e1, e2), distSeg(b, e1, e2)); }
    return m;
  }
  function holguraVias(c, w, d, ang){              // espacio libre (m) que queda detrás del andén
    const r = rect(c, w, d, ang); let m = 1e9;
    D.vias.forEach(v => { for (let i = 1; i < v.pts.length; i++)
      m = Math.min(m, distRectSeg(r, v.pts[i-1], v.pts[i]) - v.ancho/2 - MARGEN_ANDEN); });
    return m;
  }
  const fueraDeVias = (c, w, d, ang) => holguraVias(c, w, d, ang) >= 0;
  const ocupados = [];                             // círculos de lo ya construido
  const libreDeOtros = (c, radio) => ocupados.every(o => Math.hypot(c[0]-o[0], c[1]-o[1]) > o[2] + radio + 1.2);
  window._edificios = [];
  function edificio(c, w, d, h, ang, color){
    window._edificios.push({c, w, d, ang, holgura: holguraVias(c, w, d, ang)});
    const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(color));
    b.position.copy(P(c[0], c[1])); b.position.y = h/2; b.rotation.y = -ang; b.castShadow = b.receiveShadow = true; escena.add(b);
    ocupados.push([c[0], c[1], Math.hypot(w, d)/2]); return b;
  }
  // negocios de referencia (los que aparecen en el mapa): se alinean con su vía y se corren hacia
  // adentro de la manzana hasta que quedan detrás del andén
  D.referencias.forEach(r => {
    const w = 10, d = 10, h = 5 + (r.nombre.length % 3);
    let c = [r.p[0], r.p[1]];
    const vc = viaCercana(c), ang = Math.atan2(vc.dir[0], vc.dir[1]);
    const ab = sub(vc.b, vc.a), t = Math.max(0, Math.min(1, ((c[0]-vc.a[0])*ab[0] + (c[1]-vc.a[1])*ab[1]) / ((ab[0]**2 + ab[1]**2) || 1)));
    const pie = [vc.a[0] + ab[0]*t, vc.a[1] + ab[1]*t];
    let nrm = sub(c, pie); const nl = lon(nrm) || 1; nrm = [nrm[0]/nl, nrm[1]/nl];
    const valido = q => fueraDeVias(q, w, d, ang) && libreDeOtros(q, Math.hypot(w, d)/2);
    let ok = null;
    for (let k = 0; k <= 60 && !ok; k++){ const q = [c[0] + nrm[0]*k*0.5, c[1] + nrm[1]*k*0.5]; if (valido(q)) ok = q; }
    // si hacia adentro no cabe (manzana angosta entre dos vías), busca el lugar libre más cercano alrededor
    for (let rr = 2; rr <= 40 && !ok; rr += 2) for (let a = 0; a < 24 && !ok; a++){
      const q = [r.p[0] + rr*Math.cos(a*Math.PI/12), r.p[1] + rr*Math.sin(a*Math.PI/12)]; if (valido(q)) ok = q; }
    if (!ok){ letrero(r.nombre, r.p, 6, 13, r.color); return; }
    c = ok;
    edificio(c, w, d, h, ang, 0xece6db);
    const techo = new THREE.Mesh(new THREE.BoxGeometry(w + 0.4, 0.6, d + 0.4), mat(new THREE.Color(r.color).getHex()));
    techo.position.copy(P(c[0], c[1])); techo.position.y = h + 0.3; techo.rotation.y = -ang; escena.add(techo);
    letrero(r.nombre, c, h + 3.2, 13, r.color);
  });
  // edificios genéricos: alineados con la vía más cercana, detrás del andén y sin chocar entre sí
  let sx = 7;  const rnd = () => (sx = (16807*sx) % 2147483647) / 2147483647;
  const tonos = [0xe8e1d5, 0xd9cbb4, 0xc7d0d9, 0xe3d3c3, 0xb8c4b1, 0xf0e6da];
  for (let i = 0; i < 900 && ocupados.length < 230; i++){
    const c = [(rnd()-0.5)*320, (rnd()-0.5)*300], w = 7 + rnd()*10, d = 7 + rnd()*12;
    const vc = viaCercana(c); if (vc.d > 60) continue;
    const ang = Math.atan2(vc.dir[0], vc.dir[1]);
    if (!fueraDeVias(c, w, d, ang) || !libreDeOtros(c, Math.hypot(w, d)/2)) continue;
    edificio(c, w, d, 3 + Math.pow(rnd(), 2.2)*14, ang, tonos[Math.floor(rnd()*tonos.length)]);
  }
  const libre = (x, y, radio) => fueraDeVias([x, y], radio*2, radio*2, 0) && libreDeOtros([x, y], radio);

  // árboles
  for (let i = 0; i < 160; i++){ const x = (rnd()-0.5)*300, y = (rnd()-0.5)*280; if (!libre(x, y, 2.5)) continue;
    const tr = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.3, 2.5), mat(0x6b4f2a)); tr.position.copy(P(x, y)); tr.position.y = 1.25; escena.add(tr);
    const co = new THREE.Mesh(new THREE.SphereGeometry(2 + rnd()*1.5, 10, 8), mat(0x4f7d3a)); co.position.copy(P(x, y)); co.position.y = 3.8; co.castShadow = true; escena.add(co); }
  // semáforos: poste en la esquina y cabeza sobre el carril, mirando a los carros que llegan
  S.forEach(s => {
    const q = enLinea(s.entrada, s.Lentrada, s.pare), dir = [Math.sin(rad(q.rumbo)), Math.cos(rad(q.rumbo))], n = der(dir);
    const poste = [q.p[0] + n[0]*4.5, q.p[1] + n[1]*4.5], cabeza = [q.p[0] - n[0]*0.3, q.p[1] - n[1]*0.3];
    const pm = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 6.2), mat(0x2b2b2b)); pm.position.copy(P(...poste)); pm.position.y = 3.1; pm.castShadow = true; escena.add(pm);
    const brazo = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, lon(sub(poste, cabeza))), mat(0x2b2b2b));
    brazo.position.copy(P((poste[0]+cabeza[0])/2, (poste[1]+cabeza[1])/2)); brazo.position.y = 6.1;
    brazo.rotation.y = -Math.atan2(n[0], n[1]); escena.add(brazo);
    const cab = new THREE.Mesh(new THREE.BoxGeometry(0.8, 2, 0.6), mat(0x111111)); cab.position.copy(P(...cabeza)); cab.position.y = 5.6;
    cab.rotation.y = -Math.atan2(dir[0], dir[1]); escena.add(cab);
    const frente = [cabeza[0] - dir[0]*0.35, cabeza[1] - dir[1]*0.35];
    const mk = (y, c) => { const m = new THREE.MeshStandardMaterial({color:c, emissive:c, emissiveIntensity:0.1});
      const b = new THREE.Mesh(new THREE.SphereGeometry(0.28, 14, 10), m); b.position.copy(P(...frente)); b.position.y = y; escena.add(b); return m; };
    s.rojo3 = mk(6.15, 0xff3b30); s.verde3 = mk(5.05, 0x22c55e);
    s.luzPunto = new THREE.PointLight(0xff3b30, 0, 16); s.luzPunto.position.copy(P(...frente)); s.luzPunto.position.y = 5.5; escena.add(s.luzPunto);
    letrero(s.id + ' · ' + s.nombre, poste, 9, 12);
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


from .geometria import REFERENCIAS, VIAS, construir_rutas

import base64
from functools import lru_cache
from pathlib import Path

_VENDOR = Path(__file__).with_name("vendor")


@lru_cache(maxsize=1)
def _librerias() -> dict[str, str]:
    """Leaflet y three.js van dentro del HTML (carpeta simulador/vendor), así el mapa y la maqueta 3D
    funcionan sin internet. Solo las fotos satelitales necesitan conexión; si no hay, se dibuja un plano."""
    def leer(n):
        return (_VENDOR / n).read_text(encoding="utf-8")

    def data_url(n):
        return "data:text/javascript;base64," + base64.b64encode(leer(n).encode("utf-8")).decode("ascii")

    mapa = {"imports": {"three": data_url("three.module.min.js"),
                        "three/addons/controls/OrbitControls.js": data_url("OrbitControls.js")}}
    return {"__LEAFLET_CSS__": leer("leaflet.css"), "__LEAFLET_JS__": leer("leaflet.js"),
            "__IMPORTMAP__": json.dumps(mapa)}


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
    posiciones_m = {r["semaforo"]: _metros(centro[0], centro[1], posiciones[r["semaforo"]]["lat"],
                                             posiciones[r["semaforo"]]["lon"]) for _, r in info.iterrows()}
    rutas = construir_rutas(posiciones_m)
    semaforos = []
    desfase = 0.0
    for _, r in info.iterrows():
        s = r["semaforo"]
        d = ciclos[ciclos["semaforo"] == s].sort_values("ciclo")
        x, y = posiciones_m[s]
        g = rutas[s]
        semaforos.append({
            "id": s, "nombre": r["ubicacion"], "verde": int(r["verde_s"]), "ciclo": ciclo_comun,
            "cicloReal": int(r["ciclo_s"]), "desfase": desfase, "rumbo": float(posiciones[s]["rumbo"]),
            "x": x, "y": y, "entrada": g["entrada"], "Lentrada": g["Lentrada"], "pare": g["pare"],
            "rutas": g["rutas"],
            "espera": d["en_espera"].astype(int).tolist(), "pasan": d["pasan"].astype(int).tolist(),
            "quedan": d["quedan"].astype(int).tolist(),
        })
        desfase += int(r["verde_s"]) + despeje
    datos = {"centro": list(centro), "semaforos": semaforos, "inicio": inicio_texto,
             "vias": VIAS, "referencias": REFERENCIAS,
             "semilla": int(semilla), "prob": prob, "cicloComun": ciclo_comun, "despeje": despeje}
    html = _PLANTILLA.replace("__DATOS__", json.dumps(datos)).replace("__ALTO_VISTA__", str(alto_vista))
    for clave, valor in _librerias().items():
        html = html.replace(clave, valor, 1)
    return html
