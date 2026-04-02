"""Generate self-contained HTML preview for sim optimizer results."""
from __future__ import annotations

import json


def build_preview_html(result: dict) -> str:
    """Build a self-contained HTML page with interactive charts."""
    data_json = json.dumps(result)
    return _TEMPLATE.replace("__DATA_JSON__", data_json)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sim Optimizer Preview</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#000;color:#F0EDE5;font-family:'JetBrains Mono','Courier New',monospace}
.header{padding:20px 30px;border-bottom:1px solid #333;display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:18px;letter-spacing:2px;text-transform:uppercase}
.header .meta{font-size:13px;color:#949494}
.header .meta span{color:#C9A84C;font-weight:bold}
.stats{display:flex;gap:40px;padding:15px 30px;background:#0a0a0a;border-bottom:1px solid #222;flex-wrap:wrap}
.stat{text-align:center}
.stat .label{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#949494}
.stat .value{font-size:22px;font-weight:bold;margin-top:2px}
.stat .value.gain{color:#22C55E}.stat .value.loss{color:#FF2A2A}.stat .value.gold{color:#C9A84C}
.charts{padding:20px 30px;display:flex;flex-direction:column;gap:8px}
.chart-row{background:#141414;border-radius:8px;border:1px solid #222;padding:12px 16px}
.chart-row h3{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#949494;margin-bottom:8px}
canvas{width:100%;height:160px;display:block}
canvas.tall{height:200px}
.legend{display:flex;gap:16px;margin-top:6px;font-size:10px;color:#949494}
.legend .item{display:flex;align-items:center;gap:4px}
.legend .swatch{width:20px;height:2px}
.legend .swatch.dashed{border-top:2px dashed;background:none;height:0}
.hover-line{position:fixed;top:0;bottom:0;width:1px;background:rgba(240,237,229,0.3);pointer-events:none;display:none;z-index:100}
.tooltip{position:fixed;background:#1a1a1a;border:1px solid #444;border-radius:4px;padding:8px 12px;font-size:11px;pointer-events:none;display:none;z-index:101}
.tt-row{display:flex;justify-content:space-between;gap:20px}
.tt-lbl{color:#949494}.tt-theo{color:rgba(240,237,229,0.5)}
</style>
</head>
<body>
<div class="header">
  <h1>Sim Optimizer Preview</h1>
  <div class="meta">
    <span id="h-track"></span> &mdash; <span id="h-car"></span> &mdash; Lap <span id="h-lap"></span>
  </div>
</div>
<div class="stats" id="stats-bar"></div>
<div class="charts" id="charts-container"></div>
<div class="hover-line" id="hover-line"></div>
<div class="tooltip" id="tooltip"></div>

<script>
"use strict";
const DATA = __DATA_JSON__;
const A = DATA.actual, T = DATA.theoretical, D = DATA.delta;

// ── Header ──
document.getElementById('h-track').textContent = DATA.session.track;
document.getElementById('h-car').textContent = DATA.session.car;
document.getElementById('h-lap').textContent = String(DATA.session.best_lap);

// ── Stats bar (safe DOM building) ──
(function buildStats() {
  const bar = document.getElementById('stats-bar');
  const dt = DATA.session.actual_lap_time_s - DATA.session.theoretical_lap_time_s;
  const items = [
    { label: 'Your Lap', value: DATA.session.actual_lap_time_s.toFixed(3) + 's', cls: 'gold' },
    { label: 'Theoretical', value: DATA.session.theoretical_lap_time_s.toFixed(3) + 's', cls: '' },
    { label: 'Delta', value: (dt >= 0 ? '+' : '') + dt.toFixed(3) + 's', cls: dt > 0 ? 'loss' : 'gain' },
    { label: 'Tyre mu', value: DATA.vehicle.tyre.mu_lat.toFixed(2), cls: '' },
    { label: 'CdA', value: DATA.vehicle.aero.cda.toFixed(2), cls: '' },
    { label: 'Max Brake', value: DATA.vehicle.brake.max_decel_mps2.toFixed(1) + ' m/s\u00B2', cls: '' },
  ];
  items.forEach(function(it) {
    const div = document.createElement('div');
    div.className = 'stat';
    const lbl = document.createElement('div');
    lbl.className = 'label';
    lbl.textContent = it.label;
    const val = document.createElement('div');
    val.className = 'value ' + it.cls;
    val.textContent = it.value;
    div.appendChild(lbl);
    div.appendChild(val);
    bar.appendChild(div);
  });
})();

// ── Chart infrastructure ──
const xMin = 0;
const xMax = Math.max(
  A.distance_m.length ? A.distance_m[A.distance_m.length - 1] : 0,
  T.distance_m.length ? T.distance_m[T.distance_m.length - 1] : 0
);

function setupCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  return { ctx: ctx, w: rect.width, h: rect.height };
}

function drawChart(canvas, opts) {
  var sc = setupCanvas(canvas);
  var ctx = sc.ctx, w = sc.w, h = sc.h;
  var pad = { l: 55, r: 15, t: 5, b: 20 };
  var pw = w - pad.l - pad.r;
  var ph = h - pad.t - pad.b;
  var yMin = opts.yMin, yMax = opts.yMax;

  function toX(v) { return pad.l + ((v - xMin) / (xMax - xMin)) * pw; }
  function toY(v) { return pad.t + ph - ((v - yMin) / (yMax - yMin)) * ph; }

  // Grid
  ctx.strokeStyle = '#222'; ctx.lineWidth = 0.5;
  for (var i = 0; i <= 4; i++) {
    var gy = pad.t + (ph / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w - pad.r, gy); ctx.stroke();
    ctx.fillStyle = '#666'; ctx.font = '10px monospace'; ctx.textAlign = 'right';
    var yVal = yMax - (yMax - yMin) * i / 4;
    ctx.fillText(yVal.toFixed(opts.yDec || 0), pad.l - 5, gy + 3);
  }

  // Zero line
  if (opts.zeroLine && yMin < 0 && yMax > 0) {
    ctx.save(); ctx.strokeStyle = '#555'; ctx.setLineDash([4,4]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.l, toY(0)); ctx.lineTo(w - pad.r, toY(0)); ctx.stroke();
    ctx.restore();
  }

  // Fill (delta chart)
  if (opts.fill && opts.actual) {
    var d = opts.actual;
    ctx.beginPath();
    ctx.moveTo(toX(d.x[0]), toY(0));
    for (var fi = 0; fi < d.x.length; fi++) ctx.lineTo(toX(d.x[fi]), toY(d.y[fi]));
    ctx.lineTo(toX(d.x[d.x.length - 1]), toY(0));
    ctx.closePath();
    var zeroY = (-yMin) / (yMax - yMin);
    var grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + ph);
    grad.addColorStop(0, 'rgba(255,42,42,0.3)');
    grad.addColorStop(Math.max(0, Math.min(1, 1 - zeroY)), 'rgba(255,42,42,0.05)');
    grad.addColorStop(Math.max(0, Math.min(1, 1 - zeroY)), 'rgba(34,197,94,0.05)');
    grad.addColorStop(1, 'rgba(34,197,94,0.3)');
    ctx.fillStyle = grad; ctx.fill();
  }

  // Actual trace
  if (opts.actual) {
    var da = opts.actual;
    ctx.strokeStyle = da.color || '#C9A84C'; ctx.lineWidth = 1.5; ctx.setLineDash([]);
    ctx.beginPath();
    for (var ai = 0; ai < da.x.length; ai++) {
      var ax = toX(da.x[ai]), ay = toY(da.y[ai]);
      if (ai === 0) ctx.moveTo(ax, ay); else ctx.lineTo(ax, ay);
    }
    ctx.stroke();
  }

  // Theoretical trace
  if (opts.theoretical) {
    var dt2 = opts.theoretical;
    ctx.strokeStyle = dt2.color || 'rgba(240,237,229,0.6)'; ctx.lineWidth = 1.5; ctx.setLineDash([6,4]);
    ctx.beginPath();
    for (var ti = 0; ti < dt2.x.length; ti++) {
      var tx = toX(dt2.x[ti]), ty = toY(dt2.y[ti]);
      if (ti === 0) ctx.moveTo(tx, ty); else ctx.lineTo(tx, ty);
    }
    ctx.stroke(); ctx.setLineDash([]);
  }

  return { pad: pad, pw: pw, ph: ph };
}

// ── Build chart rows via DOM ──
var chartDefs = [
  { id: 'speed', title: 'Speed (km/h)', tall: true,
    actual: { x: A.distance_m, y: A.speed_kph, color: '#C9A84C' },
    theoretical: { x: T.distance_m, y: T.speed_kph },
    yMin: 0, yMax: Math.ceil(Math.max.apply(null, A.speed_kph.concat(T.speed_kph)) * 1.05),
    legend: [['Your lap','#C9A84C',false],['Theoretical','rgba(240,237,229,0.6)',true]] },
  { id: 'delta', title: 'Time Delta (s) \u2014 positive = losing time',
    actual: { x: D.distance_m, y: D.time_delta_s, color: '#F0EDE5' },
    fill: true, zeroLine: true, yDec: 1,
    yMin: -Math.max.apply(null, D.time_delta_s.map(Math.abs).concat([0.5])) * 1.2,
    yMax: Math.max.apply(null, D.time_delta_s.map(Math.abs).concat([0.5])) * 1.2 },
  { id: 'throttle', title: 'Throttle',
    actual: { x: A.distance_m, y: A.throttle, color: '#22C55E' },
    theoretical: { x: T.distance_m, y: T.throttle, color: 'rgba(34,197,94,0.6)' },
    yMin: 0, yMax: 1.05, yDec: 1,
    legend: [['Your throttle','#22C55E',false],['Theoretical','rgba(34,197,94,0.6)',true]] },
  { id: 'brake', title: 'Brake',
    actual: { x: A.distance_m, y: A.brake, color: '#FF2A2A' },
    theoretical: { x: T.distance_m, y: T.brake, color: 'rgba(255,42,42,0.6)' },
    yMin: 0, yMax: 1.05, yDec: 1,
    legend: [['Your brake','#FF2A2A',false],['Theoretical','rgba(255,42,42,0.6)',true]] },
  { id: 'steering', title: 'Steering (deg)',
    actual: { x: A.distance_m, y: A.steering_deg, color: '#3B82F6' },
    theoretical: { x: T.distance_m, y: T.steering_deg, color: 'rgba(240,237,229,0.5)' },
    zeroLine: true,
    yMin: -Math.max.apply(null, A.steering_deg.map(Math.abs).concat(T.steering_deg.map(Math.abs))) * 1.1,
    yMax: Math.max.apply(null, A.steering_deg.map(Math.abs).concat(T.steering_deg.map(Math.abs))) * 1.1,
    legend: [['Your steering','#3B82F6',false],['Theoretical','rgba(240,237,229,0.5)',true]] },
  { id: 'gear', title: 'Gear',
    actual: { x: A.distance_m, y: A.gear, color: '#8B5CF6' },
    theoretical: { x: T.distance_m, y: T.gear, color: 'rgba(240,237,229,0.5)' },
    yMin: 0, yMax: Math.max.apply(null, A.gear.concat(T.gear)) + 0.5 },
];

var container = document.getElementById('charts-container');
var canvasMap = {};
chartDefs.forEach(function(def) {
  var row = document.createElement('div');
  row.className = 'chart-row';
  var h3 = document.createElement('h3');
  h3.textContent = def.title;
  row.appendChild(h3);
  var cvs = document.createElement('canvas');
  cvs.id = 'chart-' + def.id;
  cvs.className = def.tall ? 'tall' : '';
  row.appendChild(cvs);
  if (def.legend) {
    var leg = document.createElement('div');
    leg.className = 'legend';
    def.legend.forEach(function(l) {
      var item = document.createElement('div');
      item.className = 'item';
      var sw = document.createElement('div');
      sw.className = 'swatch' + (l[2] ? ' dashed' : '');
      sw.style.background = l[2] ? 'none' : l[1];
      if (l[2]) sw.style.borderColor = l[1];
      item.appendChild(sw);
      var txt = document.createTextNode(' ' + l[0]);
      item.appendChild(txt);
      leg.appendChild(item);
    });
    row.appendChild(leg);
  }
  container.appendChild(row);
  canvasMap[def.id] = cvs;
});

// Draw all charts
var firstBounds = null;
chartDefs.forEach(function(def) {
  var b = drawChart(canvasMap[def.id], def);
  if (!firstBounds) firstBounds = b;
});

// ── Hover sync ──
var hoverLine = document.getElementById('hover-line');
var tooltipEl = document.getElementById('tooltip');

function findNearest(arr, val) {
  var best = 0, bestD = Math.abs(arr[0] - val);
  for (var i = 1; i < arr.length; i++) {
    var d = Math.abs(arr[i] - val);
    if (d < bestD) { bestD = d; best = i; }
  }
  return best;
}

container.addEventListener('mousemove', function(e) {
  var rect = canvasMap['speed'].getBoundingClientRect();
  var relX = e.clientX - rect.left - firstBounds.pad.l;
  if (relX < 0 || relX > firstBounds.pw) {
    hoverLine.style.display = 'none'; tooltipEl.style.display = 'none'; return;
  }
  var dist = xMin + (relX / firstBounds.pw) * (xMax - xMin);
  hoverLine.style.display = 'block';
  hoverLine.style.left = e.clientX + 'px';

  var ai = findNearest(A.distance_m, dist);
  var ti = findNearest(T.distance_m, dist);
  var di = findNearest(D.distance_m, dist);

  // Build tooltip via DOM
  tooltipEl.style.display = 'block';
  tooltipEl.style.left = (e.clientX + 15) + 'px';
  tooltipEl.style.top = (e.clientY - 10) + 'px';

  while (tooltipEl.firstChild) tooltipEl.removeChild(tooltipEl.firstChild);

  var rows = [
    ['Distance', dist.toFixed(0) + 'm', ''],
    ['Speed', (A.speed_kph[ai] || 0).toFixed(1), (T.speed_kph[ti] || 0).toFixed(1) + ' km/h'],
    ['Delta', (D.time_delta_s[di] > 0 ? '+' : '') + (D.time_delta_s[di] || 0).toFixed(3) + 's', ''],
    ['Throttle', ((A.throttle[ai] || 0) * 100).toFixed(0), ((T.throttle[ti] || 0) * 100).toFixed(0) + '%'],
    ['Brake', ((A.brake[ai] || 0) * 100).toFixed(0), ((T.brake[ti] || 0) * 100).toFixed(0) + '%'],
    ['Steering', (A.steering_deg[ai] || 0).toFixed(1), (T.steering_deg[ti] || 0).toFixed(1) + '\u00B0'],
    ['Gear', String(A.gear[ai] || 0), String(T.gear[ti] || 0)],
  ];
  rows.forEach(function(r) {
    var div = document.createElement('div');
    div.className = 'tt-row';
    var lbl = document.createElement('span');
    lbl.className = 'tt-lbl';
    lbl.textContent = r[0];
    div.appendChild(lbl);
    var val = document.createElement('span');
    if (r[0] === 'Delta') {
      val.style.color = D.time_delta_s[di] > 0 ? '#FF2A2A' : '#22C55E';
      val.textContent = r[1];
    } else if (r[2]) {
      val.textContent = r[1] + ' / ';
      var theo = document.createElement('span');
      theo.className = 'tt-theo';
      theo.textContent = r[2];
      val.appendChild(theo);
    } else {
      val.textContent = r[1];
    }
    div.appendChild(val);
    tooltipEl.appendChild(div);
  });
});

container.addEventListener('mouseleave', function() {
  hoverLine.style.display = 'none';
  tooltipEl.style.display = 'none';
});

window.addEventListener('resize', function() { location.reload(); });
</script>
</body>
</html>"""
