/**
 * track_map.js — Canvas-based track map with speed-colored polylines.
 *
 * Replaces the Leaflet GPS map with a lightweight Canvas track map like the PDF report.
 * Supports: multi-lap overlay, corner labels, speed coloring, hover sync.
 *
 * Public API:
 *   window.TrackMap.init(canvasId, sessionId)
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};

    window.TrackMap = { init: init };

    var canvas, ctx;
    var sessionId;
    var allGpsData = {};   // { lapNumber: { lats, lons, dists, speeds } }
    var cornerData = [];   // [{ corner_id, lat, lon }]
    var bestLap = null;
    var projection = null; // { originLat, originLon, scale, offsetX, offsetY, width, height }
    var selectedLaps = [];
    var marker = null;     // { x, y } for hover
    var pad = { top: 40, right: 140, bottom: 50, left: 50 };
    var hoverCb = null;

    function init(canvasId, sid) {
        canvas = document.getElementById(canvasId);
        if (!canvas) return;
        ctx = canvas.getContext('2d');
        sessionId = sid;

        var T = window.TELEMETRY;
        if (!T || !T.gpsLaps || T.gpsLaps.length === 0) {
            _msg('No GPS data available');
            return;
        }
        bestLap = T.bestLap || T.gpsLaps[0];
        selectedLaps = T.gpsLaps.slice();

        // Load all laps + corners in parallel
        var promises = [];
        T.gpsLaps.forEach(function (ln) {
            var url = '/api/session/' + encodeURIComponent(sid) + '/gps/' + ln;
            promises.push(
                FetchHelper.fetch(url)
                    .then(function (data) { if (data) allGpsData[ln] = data; })
                    .catch(function (err) { console.warn('Track map GPS data load failed:', err); })
            );
        });

        // Corner positions
        var cUrl = '/api/session/' + encodeURIComponent(sid) + '/corner-positions';
        promises.push(
            FetchHelper.fetch(cUrl)
                .then(function (data) { if (data && data.corners) cornerData = data.corners; })
                .catch(function (err) { console.warn('Track map corner positions load failed:', err); })
        );

        Promise.all(promises).then(function () {
            _computeProjection();
            _draw();
            _setupEvents();
            _setupControls();

            // Register __redraw for ResizeObserver
            canvas.__redraw = function() {
                _computeProjection();
                _draw();
            };
        });
    }

    // ── Projection: lat/lon → canvas pixel ──
    function _computeProjection() {
        var allLats = [], allLons = [];
        Object.keys(allGpsData).forEach(function (k) {
            var d = allGpsData[k];
            if (!d.latitudes) return;
            for (var i = 0; i < d.latitudes.length; i++) {
                if (d.latitudes[i] !== null && d.longitudes[i] !== null) {
                    allLats.push(d.latitudes[i]);
                    allLons.push(d.longitudes[i]);
                }
            }
        });
        if (allLats.length === 0) return;

        var latMin = Math.min.apply(null, allLats);
        var latMax = Math.max.apply(null, allLats);
        var lonMin = Math.min.apply(null, allLons);
        var lonMax = Math.max.apply(null, allLons);

        var originLat = (latMin + latMax) / 2;
        var originLon = (lonMin + lonMax) / 2;

        // Convert to metres (approximate)
        var mPerDegLat = 111320;
        var mPerDegLon = 111320 * Math.cos(originLat * Math.PI / 180);

        var rangeX = (lonMax - lonMin) * mPerDegLon;
        var rangeY = (latMax - latMin) * mPerDegLat;

        var dpr = window.devicePixelRatio || 1;
        var w = (canvas.parentElement.clientWidth || 700) - 16;
        var h = Math.max(400, Math.min(600, w * 0.75));
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        ctx.scale(dpr, dpr);

        var plotW = w - pad.left - pad.right;
        var plotH = h - pad.top - pad.bottom;

        // Equal aspect ratio
        var scaleX = plotW / Math.max(rangeX, 1);
        var scaleY = plotH / Math.max(rangeY, 1);
        var scale = Math.min(scaleX, scaleY) * 0.92;

        var offsetX = pad.left + (plotW - rangeX * scale) / 2;
        var offsetY = pad.top + (plotH - rangeY * scale) / 2;

        projection = {
            originLat: originLat, originLon: originLon,
            mPerDegLat: mPerDegLat, mPerDegLon: mPerDegLon,
            scale: scale, offsetX: offsetX, offsetY: offsetY,
            width: w, height: h,
            latMin: latMin, latMax: latMax, lonMin: lonMin, lonMax: lonMax,
        };
    }

    function _toPixel(lat, lon) {
        if (!projection) return null;
        var p = projection;
        var mx = (lon - p.lonMin) * p.mPerDegLon;
        var my = (lat - p.latMin) * p.mPerDegLat;
        return {
            x: p.offsetX + mx * p.scale,
            y: p.offsetY + (p.latMax - p.latMin) * p.mPerDegLat * p.scale - my * p.scale,
        };
    }

    // ── Color helpers ──
    function _speedColor(speed, minSpd, maxSpd) {
        var t = maxSpd > minSpd ? (speed - minSpd) / (maxSpd - minSpd) : 0.5;
        t = Math.max(0, Math.min(1, t));
        var r, g, b;
        if (t < 0.33) {
            // Green → Yellow
            var s = t / 0.33;
            r = Math.round(50 + s * 205);
            g = Math.round(200 + s * 55);
            b = Math.round(50 - s * 20);
        } else if (t < 0.66) {
            // Yellow → Orange
            var s = (t - 0.33) / 0.33;
            r = Math.round(255);
            g = Math.round(255 - s * 100);
            b = Math.round(30);
        } else {
            // Orange → Red
            var s = (t - 0.66) / 0.34;
            r = Math.round(255);
            g = Math.round(155 - s * 155);
            b = Math.round(30 + s * 20);
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    var LAP_COLORS = [
        '#636efa', '#ef553b', '#00cc96', '#ab63fa', '#ffa15a',
        '#19d3f3', '#ff6692', '#b6e880', '#ff97ff', '#fecb52',
    ];

    // ── Drawing ──
    function _draw() {
        if (!projection) { _msg('No GPS data'); return; }
        var w = projection.width, h = projection.height;
        ctx.clearRect(0, 0, w, h);

        // Background
        ctx.fillStyle = C.bgCard;
        ctx.fillRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = C.border;
        ctx.lineWidth = 0.5;
        for (var i = 0; i < 5; i++) {
            var gy = pad.top + i * (h - pad.top - pad.bottom) / 4;
            ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(w - pad.right, gy); ctx.stroke();
            var gx = pad.left + i * (w - pad.left - pad.right) / 4;
            ctx.beginPath(); ctx.moveTo(gx, pad.top); ctx.lineTo(gx, h - pad.bottom); ctx.stroke();
        }

        // Title
        ctx.fillStyle = C.textSecondary;
        ctx.font = 'bold 14px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Track Map — ' + selectedLaps.length + ' Lap' +
            (selectedLaps.length !== 1 ? 's' : ''), w / 2, 22);

        // Find global speed range
        var allSpeeds = [];
        selectedLaps.forEach(function (ln) {
            var d = allGpsData[ln];
            if (!d || !d.speeds) return;
            d.speeds.forEach(function (s) {
                if (s !== null && isFinite(s)) allSpeeds.push(s);
            });
        });
        var minSpd = allSpeeds.length > 0 ? Math.min.apply(null, allSpeeds) : 0;
        var maxSpd = allSpeeds.length > 0 ? Math.max.apply(null, allSpeeds) : 1;

        // Draw non-best laps first (faint)
        selectedLaps.forEach(function (ln, idx) {
            if (ln === bestLap) return;
            _drawLap(ln, LAP_COLORS[idx % LAP_COLORS.length], 0.25, 1.5, minSpd, maxSpd, false);
        });

        // Draw best lap (bold, speed-colored)
        if (allGpsData[bestLap]) {
            _drawLap(bestLap, null, 0.95, 3.5, minSpd, maxSpd, true);
        }

        // Start/Finish marker
        var bestData = allGpsData[bestLap];
        if (bestData && bestData.latitudes && bestData.latitudes.length > 0) {
            var sf = _toPixel(bestData.latitudes[0], bestData.longitudes[0]);
            if (sf) {
                ctx.beginPath();
                ctx.arc(sf.x, sf.y, 6, 0, Math.PI * 2);
                ctx.fillStyle = C.accent;
                ctx.fill();
                ctx.strokeStyle = C.textPrimary;
                ctx.lineWidth = 2;
                ctx.stroke();
                ctx.fillStyle = C.textPrimary;
                ctx.font = 'bold 10px system-ui, sans-serif';
                ctx.textAlign = 'left';
                ctx.fillText('S/F', sf.x + 10, sf.y + 4);
            }
        }

        // Corner markers
        _drawCorners();

        // Speed legend (colour bar)
        _drawSpeedLegend(minSpd, maxSpd);

        // Hover marker
        if (marker) {
            ctx.beginPath();
            ctx.arc(marker.x, marker.y, 8, 0, Math.PI * 2);
            ctx.fillStyle = C.accent;
            ctx.fill();
            ctx.strokeStyle = C.textPrimary;
            ctx.lineWidth = 2.5;
            ctx.stroke();
        }

        // Axis labels
        ctx.fillStyle = C.textMuted;
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('← West  |  East →', w / 2, h - 8);
        ctx.save();
        ctx.translate(12, h / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('← South  |  North →', 0, 0);
        ctx.restore();
    }

    function _drawLap(ln, color, opacity, weight, minSpd, maxSpd, speedColored) {
        var d = allGpsData[ln];
        if (!d || !d.latitudes || d.latitudes.length < 2) return;

        ctx.globalAlpha = opacity;
        ctx.lineWidth = weight;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';

        for (var i = 0; i < d.latitudes.length - 1; i++) {
            if (d.latitudes[i] === null || d.latitudes[i + 1] === null) continue;
            var p1 = _toPixel(d.latitudes[i], d.longitudes[i]);
            var p2 = _toPixel(d.latitudes[i + 1], d.longitudes[i + 1]);
            if (!p1 || !p2) continue;

            if (speedColored && d.speeds && d.speeds[i] !== null) {
                ctx.strokeStyle = _speedColor(d.speeds[i], minSpd, maxSpd);
            } else {
                ctx.strokeStyle = color || C.textSecondary;
            }
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
        }
        ctx.globalAlpha = 1.0;
    }

    function _drawCorners() {
        if (!cornerData || cornerData.length === 0) return;
        var COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6'];

        cornerData.forEach(function (c, idx) {
            var p = _toPixel(c.lat, c.lon);
            if (!p) return;
            var col = COLORS[idx % COLORS.length];

            // Circle
            ctx.beginPath();
            ctx.arc(p.x, p.y, 13, 0, Math.PI * 2);
            ctx.fillStyle = col;
            ctx.fill();
            ctx.strokeStyle = C.textPrimary;
            ctx.lineWidth = 2;
            ctx.stroke();

            // Label
            ctx.fillStyle = C.textPrimary;
            ctx.font = 'bold 10px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('C' + c.corner_id, p.x, p.y);
            ctx.textBaseline = 'alphabetic';
        });
    }

    function _drawSpeedLegend(minSpd, maxSpd) {
        if (!projection) return;
        var w = projection.width;
        var legX = w - pad.right + 20;
        var legY = pad.top + 20;
        var legW = 16, legH = 180;

        // Label
        ctx.fillStyle = C.textSecondary;
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.save();
        ctx.translate(legX + legW + 18, legY + legH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('Speed (km/h)', 0, 0);
        ctx.restore();

        // Gradient bar
        for (var i = 0; i < legH; i++) {
            var t = 1 - i / legH;
            var spd = minSpd + t * (maxSpd - minSpd);
            ctx.fillStyle = _speedColor(spd, minSpd, maxSpd);
            ctx.fillRect(legX, legY + i, legW, 1);
        }

        // Border
        ctx.strokeStyle = C.textMuted;
        ctx.lineWidth = 1;
        ctx.strokeRect(legX, legY, legW, legH);

        // Tick labels
        ctx.fillStyle = C.textSecondary;
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'left';
        var maxKmh = (maxSpd * 3.6).toFixed(0);
        var minKmh = (minSpd * 3.6).toFixed(0);
        var midKmh = ((minSpd + maxSpd) / 2 * 3.6).toFixed(0);
        ctx.fillText(maxKmh, legX + legW + 4, legY + 4);
        ctx.fillText(midKmh, legX + legW + 4, legY + legH / 2 + 4);
        ctx.fillText(minKmh, legX + legW + 4, legY + legH + 4);
    }

    function _msg(msg) {
        if (!canvas) return;
        var dpr = window.devicePixelRatio || 1;
        var w = (canvas.parentElement.clientWidth || 600) - 16;
        canvas.width = w * dpr;
        canvas.height = 200 * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = '200px';
        ctx.scale(dpr, dpr);
        ctx.fillStyle = C.bgCard;
        ctx.fillRect(0, 0, w, 200);
        ctx.fillStyle = C.textMuted;
        ctx.font = '14px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(msg, w / 2, 100);
    }

    // ── Hover interaction ──
    function _setupEvents() {
        canvas.addEventListener('mousemove', function (e) {
            var rect = canvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            // Find closest point on best lap
            var bestD = allGpsData[bestLap];
            if (!bestD || !bestD.latitudes) return;

            var closestIdx = -1, closestDist = Infinity;
            for (var i = 0; i < bestD.latitudes.length; i++) {
                if (bestD.latitudes[i] === null) continue;
                var p = _toPixel(bestD.latitudes[i], bestD.longitudes[i]);
                if (!p) continue;
                var dx = p.x - mx, dy = p.y - my;
                var d = dx * dx + dy * dy;
                if (d < closestDist) {
                    closestDist = d;
                    closestIdx = i;
                }
            }

            if (closestIdx >= 0 && closestDist < 400) {
                var cp = _toPixel(bestD.latitudes[closestIdx], bestD.longitudes[closestIdx]);
                marker = cp;
                _draw();

                // Show tooltip
                var spd = bestD.speeds[closestIdx];
                var dist = bestD.distances ? bestD.distances[closestIdx] : null;
                if (spd !== null && isFinite(spd)) {
                    var kmh = (spd * 3.6).toFixed(0);
                    var distStr = dist ? dist.toFixed(0) + 'm' : '';
                    canvas.title = kmh + ' km/h' + (distStr ? ' @ ' + distStr : '');
                }

                // Sync with speed chart
                if (bestD.distances && bestD.distances[closestIdx] !== null) {
                    if (window.ChartSync && window.ChartSync.updateCrosshair) {
                        window.ChartSync.updateCrosshair(bestD.distances[closestIdx]);
                    }
                }
            } else {
                if (marker) {
                    marker = null;
                    _draw();
                    canvas.title = '';
                }
            }
        });

        canvas.addEventListener('mouseleave', function () {
            if (marker) {
                marker = null;
                _draw();
                canvas.title = '';
            }
        });
    }

    // ── Lap selection controls ──
    function _setupControls() {
        // Use the existing toggle-all-laps and lap-select controls
        var allLapsToggle = document.getElementById('toggle-all-laps');
        if (allLapsToggle) {
            allLapsToggle.addEventListener('change', function () {
                var T = window.TELEMETRY;
                if (allLapsToggle.checked) {
                    selectedLaps = T.gpsLaps.slice();
                } else {
                    selectedLaps = [bestLap];
                }
                _draw();
            });
        }

        var lapSel = document.getElementById('lap-select');
        if (lapSel) {
            lapSel.addEventListener('change', function () {
                bestLap = parseInt(lapSel.value, 10);
                if (selectedLaps.indexOf(bestLap) < 0) {
                    selectedLaps = [bestLap];
                }
                _draw();

                // Update speed chart to show this lap's speed trace
                if (window.ChartSync && window.ChartSync.loadSpeedData) {
                    window.ChartSync.loadSpeedData(bestLap);
                }
            });
        }
    }

    // ── External API: update marker from chart hover ──
    window.TrackMap.updateMarkerByDistance = function (distM) {
        if (!allGpsData[bestLap]) return;
        var d = allGpsData[bestLap];
        if (!d.distances || !d.latitudes) return;

        // Binary search for closest distance
        var dists = d.distances;
        var lo = 0, hi = dists.length - 1;
        while (lo < hi) {
            var mid = (lo + hi) >> 1;
            if (dists[mid] < distM) lo = mid + 1;
            else hi = mid;
        }
        if (lo > 0 && Math.abs(dists[lo - 1] - distM) < Math.abs(dists[lo] - distM)) lo--;

        if (d.latitudes[lo] === null) return;
        marker = _toPixel(d.latitudes[lo], d.longitudes[lo]);
        _draw();
    };

})();
