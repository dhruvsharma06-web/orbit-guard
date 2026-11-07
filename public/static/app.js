// OrbitGuard frontend: 3D globe (three.js), event list, maneuver simulator, AI briefing, stats.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const R_EARTH = 6371;
const COLORS = { sat: new THREE.Color('#2ee6ff'), deb: new THREE.Color('#ff9a2e') };

// ---------------------------------------------------------------- scene
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
$('scene').appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.01, 200);
camera.position.set(2.2, 1.4, 3.2);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.minDistance = 1.3;
controls.maxDistance = 12;

scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(5, 2, 4);
scene.add(sun);

// starfield
{
  const n = 2500, p = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const v = new THREE.Vector3().randomDirection().multiplyScalar(40 + Math.random() * 40);
    p.set([v.x, v.y, v.z], i * 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0x9fb8c8, size: 0.08, sizeAttenuation: true })));
}

// everything Earth-fixed lives in this group so it rotates together
const globe = new THREE.Group();
scene.add(globe);
const earth = new THREE.Mesh(
  new THREE.SphereGeometry(1, 96, 64),
  new THREE.MeshPhongMaterial({ map: new THREE.TextureLoader().load('/static/earth.jpg'), shininess: 8 })
);
globe.add(earth);
// atmosphere glow
globe.add(new THREE.Mesh(
  new THREE.SphereGeometry(1.025, 64, 48),
  new THREE.MeshBasicMaterial({ color: 0x3fb8ff, transparent: true, opacity: 0.08, side: THREE.BackSide })
));

// lat/lon/alt -> xyz, matching three.js sphere UVs (lon 0 at +X, east towards -Z)
function geoToVec(lat, lon, alt, out = new THREE.Vector3()) {
  const r = 1 + alt / R_EARTH, la = THREE.MathUtils.degToRad(lat), lo = THREE.MathUtils.degToRad(lon);
  return out.set(r * Math.cos(la) * Math.cos(lo), r * Math.sin(la), -r * Math.cos(la) * Math.sin(lo));
}

// round sprite for points
function dotTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d'), grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, 'rgba(255,255,255,1)'); grd.addColorStop(0.4, 'rgba(255,255,255,.8)'); grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}
const pointsMat = new THREE.PointsMaterial({
  size: 0.022, map: dotTexture(), vertexColors: true, transparent: true, depthWrite: false,
  blending: THREE.AdditiveBlending, sizeAttenuation: true,
});
let points = null, lastPos = null;

// event visuals
const eventGroup = new THREE.Group();
globe.add(eventGroup);
const marker = new THREE.Mesh(new THREE.SphereGeometry(0.018, 24, 16),
  new THREE.MeshBasicMaterial({ color: 0xff3b5c, transparent: true, opacity: 0.9 }));
const ring = new THREE.Mesh(new THREE.SphereGeometry(0.03, 24, 16),
  new THREE.MeshBasicMaterial({ color: 0xff3b5c, transparent: true, opacity: 0.25, wireframe: true }));
marker.visible = ring.visible = false;
globe.add(marker, ring);

// ---------------------------------------------------------------- state
let events = [], filter = 'ALL', selected = null, idle = true, playing = false, hours = 24, RUN = null;
let idleTimer;
controls.addEventListener('start', () => { idle = false; clearTimeout(idleTimer); });
controls.addEventListener('end', () => { idleTimer = setTimeout(() => (idle = true), 6000); });

// ---------------------------------------------------------------- helpers
function toast(msg) {
  $('toast').textContent = msg; $('toast').classList.remove('hidden');
  setTimeout(() => $('toast').classList.add('hidden'), 4500);
}
function loading(on, text = 'propagating orbits…') {
  $('loadingText').textContent = text; $('loading').classList.toggle('hidden', !on);
}
async function api(url, opts) {
  const r = await fetch(url, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `${r.status} ${r.statusText}`);
  return j;
}
const fmtMin = (m) => `T+${Math.floor(m / 60)}h ${String(Math.round(m % 60)).padStart(2, '0')}m`;

// ---------------------------------------------------------------- controls
for (const [id, out, fmt] of [['limit', 'limitOut'], ['hours', 'hoursOut'], ['thr', 'thrOut'],
  ['dv', 'dvOut', (v) => (+v).toFixed(2)], ['lead', 'leadOut']]) {
  $(id).addEventListener('input', () => ($(out).textContent = fmt ? fmt($(id).value) : $(id).value));
}

$('runBtn').onclick = async () => {
  loading(true, 'propagating orbits & screening for collisions…');
  $('runBtn').disabled = true;
  try {
    hours = +$('hours').value;
    const res = await api(`/api/run?limit=${$('limit').value}&hours=${hours}&threshold=${$('thr').value}`, { method: 'POST' });
    const s = res.summary; RUN = s;
    $('summary').innerHTML =
      `<b>${s.objects}</b> objects tracked (<b>${s.debris}</b> debris)<br>` +
      `<b>${s.events}</b> close approaches &lt; ${$('thr').value} km in ${s.hours} h<br>` +
      `<span style="color:var(--dim)">propagate ${s.seconds.propagate}s · screen ${s.seconds.screen}s` +
      (s.dropped ? ` · ${s.dropped} decayed TLEs skipped` : '') + `</span>`;
    $('summary').classList.remove('hidden');
    $('filters').classList.remove('hidden');
    $('timebar').classList.remove('hidden');
    $('statsBtn').disabled = false;
    $('time').max = hours * 60 - 1; $('time').value = 0;
    events = res.events;
    renderEvents();
    clearSelection();
    await loadPositions(0);
  } catch (e) { toast(e.message); }
  finally { loading(false); $('runBtn').disabled = false; }
};

document.querySelectorAll('#filters button').forEach((b) => (b.onclick = () => {
  document.querySelectorAll('#filters button').forEach((x) => x.classList.remove('on'));
  b.classList.add('on'); filter = b.dataset.f; renderEvents();
}));

function renderEvents() {
  const list = events.filter((e) => filter === 'ALL' || e.risk_label === filter);
  $('events').innerHTML = list.length ? '' : '<li style="cursor:default;color:var(--dim)">No events in this filter.</li>';
  for (const e of list.slice(0, 300)) {
    const li = document.createElement('li');
    li.className = e.risk_label + (selected && selected.id === e.id ? ' sel' : '');
    li.innerHTML = `<div class="names">${e.a_name} ⇄ ${e.b_name}</div>
      <div class="meta"><span class="tag">${e.risk_label} ${e.risk_score}</span>
      <span>${e.miss_km.toFixed(2)} km · ${e.rel_speed_kms.toFixed(1)} km/s</span><span>${fmtMin(e.tca_minute)}</span></div>`;
    li.onclick = () => selectEvent(e);
    $('events').appendChild(li);
  }
}

// ---------------------------------------------------------------- positions
async function loadPositions(minute) {
  if (!RUN) return;
  const d = await api(`/api/positions?limit=${RUN.limit}&start=${encodeURIComponent(RUN.start_utc)}&t=${minute}`);
  lastPos = d;
  const n = d.ids.length, pos = new Float32Array(n * 3), col = new Float32Array(n * 3), v = new THREE.Vector3();
  for (let i = 0; i < n; i++) {
    geoToVec(d.lat[i], d.lon[i], d.alt[i], v);
    pos.set([v.x, v.y, v.z], i * 3);
    const c = d.debris[i] ? COLORS.deb : COLORS.sat;
    col.set([c.r, c.g, c.b], i * 3);
  }
  if (!points || points.geometry.attributes.position.count !== n) {
    if (points) { globe.remove(points); points.geometry.dispose(); }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    points = new THREE.Points(g, pointsMat);
    globe.add(points);
  } else {
    points.geometry.attributes.position.array.set(pos);
    points.geometry.attributes.position.needsUpdate = true;
    points.geometry.attributes.color.array.set(col);
    points.geometry.attributes.color.needsUpdate = true;
    points.geometry.computeBoundingSphere();
  }
  $('timeLabel').textContent = `${fmtMin(+minute)} · ${d.time_utc.slice(11, 16)} UTC`;
}

let tTimer;
$('time').addEventListener('input', () => {
  clearTimeout(tTimer);
  tTimer = setTimeout(() => loadPositions($('time').value).catch((e) => toast(e.message)), 120);
});
$('playBtn').onclick = () => { playing = !playing; $('playBtn').textContent = playing ? '❚❚' : '▶'; if (playing) play(); };
async function play() {
  while (playing) {
    const t = (+$('time').value + 2) % (+$('time').max + 1);
    $('time').value = t;
    try { await loadPositions(t); } catch { playing = false; }
    await new Promise((r) => setTimeout(r, 60));
  }
  $('playBtn').textContent = '▶';
}

// ---------------------------------------------------------------- event selection
function clearSelection() {
  selected = null;
  eventGroup.clear();
  marker.visible = ring.visible = false;
  $('detail').classList.add('hidden');
}
$('closeDetail').onclick = () => { clearSelection(); renderEvents(); };

function trackLine(t, color) {
  const pts = t.lat.map((_, i) => geoToVec(t.lat[i], t.lon[i], t.alt[i]));
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  return new THREE.Line(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.85 }));
}

async function selectEvent(e) {
  selected = e; renderEvents();
  playing = false;
  const m = Math.round(e.tca_minute);
  $('time').value = Math.min(m, +$('time').max);
  try {
    const [ta, tb] = await Promise.all([
      api(`/api/track/${e.a_id}?at=${encodeURIComponent(e.tca_utc)}`), api(`/api/track/${e.b_id}?at=${encodeURIComponent(e.tca_utc)}`),
      loadPositions($('time').value),
    ]);
    eventGroup.clear();
    eventGroup.add(trackLine(ta, e.a_debris ? 0xff9a2e : 0x2ee6ff), trackLine(tb, e.b_debris ? 0xff9a2e : 0x2ee6ff));
    const c = ta.center;
    geoToVec(ta.lat[c], ta.lon[c], ta.alt[c], marker.position);
    ring.position.copy(marker.position);
    marker.visible = ring.visible = true;
    // fly camera towards the event
    idle = false; clearTimeout(idleTimer); idleTimer = setTimeout(() => (idle = true), 15000);
    const target = marker.position.clone().applyMatrix4(globe.matrixWorld).normalize().multiplyScalar(2.6);
    flyTo(target);
  } catch (err) { toast(err.message); }

  $('detailBody').innerHTML = `
    <h2>${e.a_name} ⇄ ${e.b_name}</h2>
    <div style="color:var(--dim);font-size:11px">NORAD ${e.a_id} ${e.a_debris ? '(debris)' : ''} · NORAD ${e.b_id} ${e.b_debris ? '(debris)' : ''}</div>
    <div class="kv ${e.risk_label}" style="border:0">
      <div><small>Risk</small><b class="tag">${e.risk_label} ${e.risk_score}</b></div>
      <div><small>Miss distance</small><b>${e.miss_km.toFixed(3)} km</b></div>
      <div><small>Relative speed</small><b>${e.rel_speed_kms.toFixed(2)} km/s</b></div>
      <div><small>Probability*</small><b>${e.probability.toExponential(2)}</b></div>
      <div style="grid-column:1/-1"><small>Time of closest approach</small><b>${e.tca_utc.replace('T', ' ')} · ${fmtMin(e.tca_minute)}</b></div>
    </div>
    <div style="color:var(--dim);font-size:10px">*simplified educational model</div>`;
  $('briefing').textContent = e.briefing || '';
  $('mvResult').innerHTML = '';
  $('detail').classList.remove('hidden');
}

let fly = null;
function flyTo(target) { fly = { from: camera.position.clone(), to: target, t: 0 }; }

// ---------------------------------------------------------------- maneuver + briefing
$('mvBtn').onclick = async () => {
  if (!selected) return;
  try {
    const r = await api('/api/maneuver', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event: selected, which: $('mvWhich').value, delta_v_ms: +$('dv').value, lead_hours: +$('lead').value }),
    });
    const better = r.new_miss_km > r.old_miss_km;
    $('mvResult').innerHTML = `Along-track shift at TCA: <b>${r.shift_km} km</b><br>
      Miss: ${r.old_miss_km} km → <b style="color:${better ? 'var(--green)' : 'var(--red)'}">${r.new_miss_km} km</b><br>
      Risk: ${r.old_risk[1]} ${r.old_risk[0]} → <b>${r.new_risk[1]} ${r.new_risk[0]}</b>`;
  } catch (e) { toast(e.message); }
};

$('briefBtn').onclick = async () => {
  if (!selected) return;
  const ev = selected;
  $('briefBtn').disabled = true;
  $('briefing').textContent = 'Analysing… (local AI, may take ~30 s)';
  try {
    const { briefing } = await api('/api/brief', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event: ev }) });
    ev.briefing = briefing;
    if (selected !== ev) return;
    $('briefing').textContent = '';
    for (let i = 0; i < briefing.length; i += 3) {
      if (selected !== ev) return;
      $('briefing').textContent = briefing.slice(0, i + 3);
      await new Promise((r) => setTimeout(r, 8));
    }
  } catch (e) { toast(e.message); $('briefing').textContent = ''; }
  finally { $('briefBtn').disabled = false; }
};

// ---------------------------------------------------------------- hover tooltip
const ray = new THREE.Raycaster(); ray.params.Points.threshold = 0.015;
const mouse = new THREE.Vector2();
renderer.domElement.addEventListener('mousemove', (ev) => {
  if (!points || !lastPos) return;
  mouse.set((ev.clientX / innerWidth) * 2 - 1, -(ev.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(mouse, camera);
  const hit = ray.intersectObject(points)[0];
  const h = $('hover');
  if (hit) {
    const i = hit.index;
    h.innerHTML = `${lastPos.names[i]}<br><span style="color:var(--dim)">NORAD ${lastPos.ids[i]} · ${lastPos.alt[i]} km</span>`;
    h.style.left = ev.clientX + 14 + 'px'; h.style.top = ev.clientY + 14 + 'px';
    h.classList.remove('hidden');
  } else h.classList.add('hidden');
});

// ---------------------------------------------------------------- stats modal
let charts = [];
$('statsBtn').onclick = async () => {
  try {
    const s = await api('/api/stats', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events, hours: RUN.hours, limit: RUN.limit, start_utc: RUN.start_utc }) });
    charts.forEach((c) => c.destroy());
    Chart.defaults.color = '#6f8f88'; Chart.defaults.borderColor = 'rgba(0,255,200,.08)';
    Chart.defaults.font.family = 'ui-monospace, Consolas, monospace';
    Chart.defaults.maintainAspectRatio = false;
    charts = [
      new Chart($('cMiss'), { type: 'bar', data: { labels: s.miss_labels, datasets: [{ label: 'events', data: s.miss_bins, backgroundColor: '#ff3b5c' }] }, options: { plugins: { legend: { display: false } } } }),
      new Chart($('cHour'), { type: 'line', data: { labels: s.hour_labels, datasets: [{ label: 'events', data: s.per_hour, borderColor: '#39ff9f', backgroundColor: 'rgba(57,255,159,.15)', fill: true, tension: .3 }] }, options: { plugins: { legend: { display: false } } } }),
      new Chart($('cAlt'), { type: 'bar', data: { labels: s.alt_labels, datasets: [
        { label: 'satellites', data: s.alt_active, backgroundColor: '#2ee6ff' },
        { label: 'debris', data: s.alt_debris, backgroundColor: '#ff9a2e' }] },
        options: { scales: { x: { stacked: true }, y: { stacked: true } } } }),
    ];
    $('statsModal').classList.remove('hidden');
  } catch (e) { toast(e.message); }
};
$('closeStats').onclick = () => $('statsModal').classList.add('hidden');

// ---------------------------------------------------------------- loop
addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = clock.getDelta(), t = clock.elapsedTime;
  if (idle && !selected) globe.rotation.y += dt * 0.04;
  if (fly) {
    fly.t = Math.min(1, fly.t + dt * 0.8);
    const k = 1 - Math.pow(1 - fly.t, 3);
    camera.position.lerpVectors(fly.from, fly.to, k);
    if (fly.t >= 1) fly = null;
  }
  if (ring.visible) { const s = 1 + 0.6 * Math.abs(Math.sin(t * 3)); ring.scale.setScalar(s); }
  controls.update();
  renderer.render(scene, camera);
});
