/**
 * focus_tools.js — Tool registrations for Focus Mode.
 *
 * Registers 12 tools across 4 tabs: Analytics, Corners, Performance, Overview.
 * Each tool provides a render(container, sessionId) function that creates
 * a canvas, fetches data, and draws a visualization.
 *
 * Depends on:
 *   - window.FocusMode (focus_mode.js)
 *   - window.FetchHelper (fetch_helper.js)
 *   - window.Theme (theme.js)
 *   - window.TELEMETRY ({ sessionId, gpsLaps, bestLap })
 */
(function () {
    'use strict';

    // -----------------------------------------------------------------
    // Theme colors (fallback if Theme not loaded yet)
    // -----------------------------------------------------------------

    var C = window.Theme ? window.Theme.colors : {
        bgCard: '#1e1e2e', border: '#333', textPrimary: '#e0e0e0',
        textSecondary: '#aaa', textMuted: '#777', accent: '#f97316'
    };

    // -----------------------------------------------------------------
    // TELEMETRY + availability helpers
    // -----------------------------------------------------------------

    var T = function () { return window.TELEMETRY || {}; };
    var hasGps = function () { var t = T(); return t.gpsLaps && t.gpsLaps.length > 0; };
    var hasMultiLap = function () { var t = T(); return t.gpsLaps && t.gpsLaps.length > 1; };

    // -----------------------------------------------------------------
    // Shared: canvas setup (DPR-aware)
    // -----------------------------------------------------------------

    function _setupCanvas(canvas, optWidth, optHeight) {
        var dpr = window.devicePixelRatio || 1;
        canvas.style.width = '';
        canvas.style.height = '';
        var w = optWidth || canvas.clientWidth || canvas.parentElement.clientWidth || 600;
        var h = optHeight || canvas.clientHeight || canvas.parentElement.clientHeight || 300;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        var ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        return { ctx: ctx, w: w, h: h, dpr: dpr };
    }

    // -----------------------------------------------------------------
    // Shared: centered message on dark background
    // -----------------------------------------------------------------

    function _focusMsg(canvas, text) {
        var s = _setupCanvas(canvas);
        var ctx = s.ctx;
        ctx.fillStyle = C.bgCard || '#1e1e2e';
        ctx.fillRect(0, 0, s.w, s.h);
        ctx.fillStyle = C.textMuted || '#777';
        ctx.font = '14px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(text, s.w / 2, s.h / 2);
    }

    // -----------------------------------------------------------------
    // Shared: speed color (green=slow, yellow=mid, red=fast)
    // -----------------------------------------------------------------

    function _speedColor(speed, minSpd, maxSpd) {
        var t = maxSpd > minSpd ? (speed - minSpd) / (maxSpd - minSpd) : 0.5;
        t = Math.max(0, Math.min(1, t));
        var r, g, b;
        if (t < 0.33) {
            var s = t / 0.33;
            r = Math.round(50 + s * 205);
            g = Math.round(200 + s * 55);
            b = Math.round(50 - s * 20);
        } else if (t < 0.66) {
            var s2 = (t - 0.33) / 0.33;
            r = 255;
            g = Math.round(255 - s2 * 100);
            b = 30;
        } else {
            var s3 = (t - 0.66) / 0.34;
            r = 255;
            g = Math.round(155 - s3 * 155);
            b = Math.round(30 + s3 * 20);
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    // -----------------------------------------------------------------
    // Shared: density color for scatter plots
    // -----------------------------------------------------------------

    function _densityColor(t) {
        t = Math.max(0, Math.min(1, t));
        var r, g, b;
        if (t < 0.25) {
            r = 0; g = Math.round(100 + 155 * (t / 0.25)); b = 255;
        } else if (t < 0.5) {
            r = 0; g = 255; b = Math.round(255 * (1 - (t - 0.25) / 0.25));
        } else if (t < 0.75) {
            r = Math.round(255 * ((t - 0.5) / 0.25)); g = 255; b = 0;
        } else {
            r = 255; g = Math.round(255 * (1 - (t - 0.75) / 0.25)); b = 0;
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    // -----------------------------------------------------------------
    // _drawTrackMap — GPS trace with speed coloring
    // -----------------------------------------------------------------

    function _drawTrackMap(canvas, data) {
        if (!data || !data.latitudes || data.latitudes.length < 2) {
            _focusMsg(canvas, 'No GPS data');
            return;
        }

        var lats = data.latitudes;
        var lons = data.longitudes;
        var speeds = data.speeds || [];

        // Compute projection bounds
        var allLats = [], allLons = [];
        for (var i = 0; i < lats.length; i++) {
            if (lats[i] !== null && lons[i] !== null) {
                allLats.push(lats[i]);
                allLons.push(lons[i]);
            }
        }
        if (allLats.length < 2) { _focusMsg(canvas, 'Insufficient GPS points'); return; }

        var latMin = Math.min.apply(null, allLats);
        var latMax = Math.max.apply(null, allLats);
        var lonMin = Math.min.apply(null, allLons);
        var lonMax = Math.max.apply(null, allLons);

        var originLat = (latMin + latMax) / 2;
        var mPerDegLat = 111320;
        var mPerDegLon = 111320 * Math.cos(originLat * Math.PI / 180);

        var rangeX = (lonMax - lonMin) * mPerDegLon;
        var rangeY = (latMax - latMin) * mPerDegLat;

        var s = _setupCanvas(canvas);
        var ctx = s.ctx;
        var w = s.w;
        var h = s.h;

        var pad = { top: 30, right: 30, bottom: 30, left: 30 };
        var plotW = w - pad.left - pad.right;
        var plotH = h - pad.top - pad.bottom;

        var scaleX = plotW / Math.max(rangeX, 1);
        var scaleY = plotH / Math.max(rangeY, 1);
        var scale = Math.min(scaleX, scaleY) * 0.92;

        var offsetX = pad.left + (plotW - rangeX * scale) / 2;
        var offsetY = pad.top + (plotH - rangeY * scale) / 2;

        function toPixel(lat, lon) {
            var mx = (lon - lonMin) * mPerDegLon;
            var my = (lat - latMin) * mPerDegLat;
            return {
                x: offsetX + mx * scale,
                y: offsetY + (latMax - latMin) * mPerDegLat * scale - my * scale
            };
        }

        // Background
        ctx.fillStyle = C.bgCard || '#1e1e2e';
        ctx.fillRect(0, 0, w, h);

        // Speed range
        var validSpeeds = [];
        for (var si = 0; si < speeds.length; si++) {
            if (speeds[si] !== null && isFinite(speeds[si])) validSpeeds.push(speeds[si]);
        }
        var minSpd = validSpeeds.length > 0 ? Math.min.apply(null, validSpeeds) : 0;
        var maxSpd = validSpeeds.length > 0 ? Math.max.apply(null, validSpeeds) : 1;

        // Draw trace
        ctx.lineWidth = 3;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';

        for (var di = 0; di < lats.length - 1; di++) {
            if (lats[di] === null || lats[di + 1] === null) continue;
            var p1 = toPixel(lats[di], lons[di]);
            var p2 = toPixel(lats[di + 1], lons[di + 1]);

            if (speeds[di] !== null && speeds[di] !== undefined && isFinite(speeds[di])) {
                ctx.strokeStyle = _speedColor(speeds[di], minSpd, maxSpd);
            } else {
                ctx.strokeStyle = C.accent || '#f97316';
            }
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
        }

        // Start/finish marker
        if (allLats.length > 0) {
            var sf = toPixel(allLats[0], allLons[0]);
            ctx.beginPath();
            ctx.arc(sf.x, sf.y, 5, 0, Math.PI * 2);
            ctx.fillStyle = C.accent || '#f97316';
            ctx.fill();
            ctx.strokeStyle = C.textPrimary || '#e0e0e0';
            ctx.lineWidth = 2;
            ctx.stroke();
        }

        // Title
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = 'bold 12px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText('Track Map', w / 2, 6);
    }

    // -----------------------------------------------------------------
    // _drawSpeedTrace — speed (km/h) vs distance line chart
    // -----------------------------------------------------------------

    function _drawSpeedTrace(canvas, data, color) {
        if (!data || !data.distances || !data.speeds || data.distances.length < 2) {
            _focusMsg(canvas, 'No speed data');
            return;
        }

        var dists = data.distances;
        var speeds = data.speeds;
        var lineColor = color || (C.accent || '#f97316');

        var s = _setupCanvas(canvas);
        var ctx = s.ctx;
        var w = s.w;
        var h = s.h;

        var pad = { top: 30, right: 20, bottom: 45, left: 55 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        // Convert speeds to km/h and find ranges
        var kmhSpeeds = [];
        var validDists = [];
        for (var i = 0; i < speeds.length; i++) {
            if (speeds[i] !== null && isFinite(speeds[i]) &&
                dists[i] !== null && isFinite(dists[i])) {
                kmhSpeeds.push(speeds[i] * 3.6);
                validDists.push(dists[i]);
            }
        }
        if (kmhSpeeds.length < 2) { _focusMsg(canvas, 'Insufficient speed data'); return; }

        var distMin = Math.min.apply(null, validDists);
        var distMax = Math.max.apply(null, validDists);
        var spdMin = Math.min.apply(null, kmhSpeeds);
        var spdMax = Math.max.apply(null, kmhSpeeds);

        // Add padding to Y range
        var spdRange = spdMax - spdMin;
        spdMin = Math.max(0, spdMin - spdRange * 0.05);
        spdMax = spdMax + spdRange * 0.05;

        // Background
        ctx.fillStyle = C.bgCard || '#1e1e2e';
        ctx.fillRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = C.border || '#333';
        ctx.lineWidth = 0.5;
        for (var gi = 0; gi <= 4; gi++) {
            var gy = pad.top + gi * pH / 4;
            ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(pad.left + pW, gy); ctx.stroke();
            var gx = pad.left + gi * pW / 4;
            ctx.beginPath(); ctx.moveTo(gx, pad.top); ctx.lineTo(gx, pad.top + pH); ctx.stroke();
        }

        // Speed line
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.beginPath();
        var first = true;
        for (var li = 0; li < validDists.length; li++) {
            var x = pad.left + (validDists[li] - distMin) / Math.max(distMax - distMin, 1) * pW;
            var y = pad.top + pH - (kmhSpeeds[li] - spdMin) / Math.max(spdMax - spdMin, 1) * pH;
            if (first) { ctx.moveTo(x, y); first = false; }
            else { ctx.lineTo(x, y); }
        }
        ctx.stroke();

        // Y axis labels
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var yi = 0; yi <= 4; yi++) {
            var yy = pad.top + yi * pH / 4;
            var val = spdMax - yi * (spdMax - spdMin) / 4;
            ctx.fillText(val.toFixed(0), pad.left - 6, yy);
        }

        // X axis labels
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        for (var xi = 0; xi <= 4; xi++) {
            var xx = pad.left + xi * pW / 4;
            var dv = distMin + xi * (distMax - distMin) / 4;
            ctx.fillText(dv.toFixed(0) + 'm', xx, pad.top + pH + 6);
        }

        // Axis titles
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = 'bold 11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText('Distance (m)', pad.left + pW / 2, h - 12);
        ctx.save();
        ctx.translate(14, pad.top + pH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.textBaseline = 'middle';
        ctx.fillText('Speed (km/h)', 0, 0);
        ctx.restore();

        // Title
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = 'bold 12px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText('Speed Trace', w / 2, 6);
    }

    // -----------------------------------------------------------------
    // _drawGG — G-G scatter with grid circles and axes
    // -----------------------------------------------------------------

    function _drawGG(canvas, data) {
        if (!data || !data.lat_g || !data.lon_g || data.lat_g.length < 2) {
            _focusMsg(canvas, 'No acceleration data');
            return;
        }

        var latG = [];
        var lonG = [];
        var maxG = 0;
        for (var i = 0; i < data.lat_g.length; i++) {
            if (data.lat_g[i] === null || data.lon_g[i] === null) continue;
            if (!isFinite(data.lat_g[i]) || !isFinite(data.lon_g[i])) continue;
            latG.push(data.lat_g[i]);
            lonG.push(data.lon_g[i]);
            var mag = Math.sqrt(data.lat_g[i] * data.lat_g[i] + data.lon_g[i] * data.lon_g[i]);
            if (mag > maxG) maxG = mag;
        }
        if (latG.length < 2) { _focusMsg(canvas, 'Insufficient G data'); return; }

        var s = _setupCanvas(canvas);
        var ctx = s.ctx;
        var w = s.w;
        var h = s.h;

        var pad = { top: 30, right: 30, bottom: 45, left: 55 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        var axisMax = Math.ceil(maxG * 1.15 * 10) / 10;
        if (axisMax < 0.5) axisMax = 0.5;

        function xToPixel(v) { return pad.left + (v + axisMax) / (2 * axisMax) * pW; }
        function yToPixel(v) { return pad.top + pH - (v + axisMax) / (2 * axisMax) * pH; }

        // Background
        ctx.fillStyle = C.bgCard || '#1e1e2e';
        ctx.fillRect(0, 0, w, h);

        // Grid circles
        ctx.strokeStyle = C.border || '#333';
        ctx.lineWidth = 0.5;
        var cx = xToPixel(0);
        var cy = yToPixel(0);
        var circleStep = axisMax <= 0.5 ? 0.25 : 0.5;
        for (var r = circleStep; r <= axisMax; r += circleStep) {
            var rPx = r / axisMax * (pW / 2);
            ctx.beginPath();
            ctx.arc(cx, cy, rPx, 0, Math.PI * 2);
            ctx.stroke();
        }

        // Axes through origin
        ctx.strokeStyle = C.textMuted || '#777';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(cx, pad.top); ctx.lineTo(cx, pad.top + pH); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(pad.left, cy); ctx.lineTo(pad.left + pW, cy); ctx.stroke();

        // Friction circle envelope
        var frictionR = maxG * 0.95;
        var frPx = frictionR / axisMax * (pW / 2);
        ctx.strokeStyle = 'rgba(139, 148, 158, 0.8)';
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.arc(cx, cy, frPx, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);

        // Density grid
        var gridSize = 30;
        var grid = {};
        for (var gi = 0; gi < latG.length; gi++) {
            var gpx = xToPixel(latG[gi]);
            var gpy = yToPixel(lonG[gi]);
            var gk = Math.floor(gpx / gridSize) + ',' + Math.floor(gpy / gridSize);
            grid[gk] = (grid[gk] || 0) + 1;
        }
        var maxDensity = 0;
        var gKeys = Object.keys(grid);
        for (var gki = 0; gki < gKeys.length; gki++) {
            if (grid[gKeys[gki]] > maxDensity) maxDensity = grid[gKeys[gki]];
        }

        // Draw scatter points
        var dotR = latG.length > 5000 ? 1.2 : latG.length > 1000 ? 1.8 : 2.5;
        ctx.globalAlpha = 0.7;
        for (var pi = 0; pi < latG.length; pi++) {
            var px = xToPixel(latG[pi]);
            var py = yToPixel(lonG[pi]);
            if (px < pad.left || px > pad.left + pW) continue;
            if (py < pad.top || py > pad.top + pH) continue;

            var dk = Math.floor(px / gridSize) + ',' + Math.floor(py / gridSize);
            var density = grid[dk] || 1;
            var dt = Math.min(1, density / Math.max(1, maxDensity * 0.6));
            ctx.fillStyle = _densityColor(dt);
            ctx.beginPath();
            ctx.arc(px, py, dotR, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.globalAlpha = 1;

        // Axis labels
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = 'bold 11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText('Lateral G', pad.left + pW / 2, h - 12);
        ctx.save();
        ctx.translate(14, pad.top + pH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.textBaseline = 'middle';
        ctx.fillText('Longitudinal G', 0, 0);
        ctx.restore();

        // Quadrant labels
        ctx.fillStyle = C.textMuted || '#777';
        ctx.font = 'bold 10px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        if (cy > pad.top + 20 && cy < pad.top + pH - 20) {
            ctx.fillText('BRAKING', cx, Math.max(pad.top + 16, cy - pH * 0.3));
            ctx.fillText('ACCEL', cx, Math.min(pad.top + pH - 12, cy + pH * 0.3));
        }

        // Stats
        ctx.fillStyle = C.textMuted || '#777';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(latG.length + ' pts | Max: ' + maxG.toFixed(2) + 'G', pad.left + 4, pad.top + 4);

        // Title
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = 'bold 12px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText('G-G Diagram', w / 2, 6);
    }

    // -----------------------------------------------------------------
    // _drawDistribution — histogram bars
    // -----------------------------------------------------------------

    function _drawDistribution(canvas, data) {
        if (!data || !data.bins || !data.counts || data.bins.length < 2) {
            _focusMsg(canvas, 'No distribution data');
            return;
        }

        var bins = data.bins;
        var counts = data.counts;

        var s = _setupCanvas(canvas);
        var ctx = s.ctx;
        var w = s.w;
        var h = s.h;

        var pad = { top: 30, right: 20, bottom: 45, left: 50 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        var maxCount = 0;
        for (var mi = 0; mi < counts.length; mi++) {
            if (counts[mi] > maxCount) maxCount = counts[mi];
        }
        if (maxCount === 0) maxCount = 1;

        // Background
        ctx.fillStyle = C.bgCard || '#1e1e2e';
        ctx.fillRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = C.border || '#333';
        ctx.lineWidth = 0.5;
        for (var gi = 0; gi <= 4; gi++) {
            var gy = pad.top + gi * pH / 4;
            ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(pad.left + pW, gy); ctx.stroke();
        }

        // Bar width (bins has n+1 edges for n bars)
        var nBars = counts.length;
        var barW = pW / nBars;
        var gap = Math.max(1, barW * 0.1);

        // Draw bars
        for (var bi = 0; bi < nBars; bi++) {
            var barH = (counts[bi] / maxCount) * pH;
            var bx = pad.left + bi * barW + gap / 2;
            var by = pad.top + pH - barH;
            var bw = barW - gap;

            ctx.fillStyle = 'rgba(54, 162, 235, 0.6)';
            ctx.fillRect(bx, by, bw, barH);
            ctx.strokeStyle = 'rgba(54, 162, 235, 0.9)';
            ctx.lineWidth = 1;
            ctx.strokeRect(bx, by, bw, barH);
        }

        // Y axis labels (counts)
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var yi = 0; yi <= 4; yi++) {
            var yy = pad.top + yi * pH / 4;
            var cv = maxCount - yi * maxCount / 4;
            ctx.fillText(cv.toFixed(0), pad.left - 6, yy);
        }

        // X axis labels (bin edges)
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        var nLabels = Math.min(6, bins.length);
        var labelStep = Math.max(1, Math.floor(bins.length / nLabels));
        for (var xi = 0; xi < bins.length; xi += labelStep) {
            var xx = pad.left + (xi / Math.max(bins.length - 1, 1)) * pW;
            ctx.fillText(bins[xi].toFixed(1) + 's', xx, pad.top + pH + 6);
        }

        // Axis titles
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = 'bold 11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText('Lap Time (s)', pad.left + pW / 2, h - 12);

        // Title
        ctx.font = 'bold 12px system-ui, sans-serif';
        ctx.fillText('Lap Distribution', w / 2, 6);
    }

    // -----------------------------------------------------------------
    // _drawProgress — lap time trend line
    // -----------------------------------------------------------------

    function _drawProgress(canvas, data) {
        if (!data || !data.laps || data.laps.length < 2) {
            _focusMsg(canvas, 'Not enough laps for trend');
            return;
        }

        var laps = data.laps;

        var s = _setupCanvas(canvas);
        var ctx = s.ctx;
        var w = s.w;
        var h = s.h;

        var pad = { top: 30, right: 20, bottom: 45, left: 55 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        var tMin = Infinity, tMax = -Infinity;
        for (var mi = 0; mi < laps.length; mi++) {
            if (laps[mi] !== null && isFinite(laps[mi])) {
                if (laps[mi] < tMin) tMin = laps[mi];
                if (laps[mi] > tMax) tMax = laps[mi];
            }
        }
        if (!isFinite(tMin) || !isFinite(tMax)) { _focusMsg(canvas, 'No valid lap times'); return; }

        var tRange = tMax - tMin;
        tMin = tMin - tRange * 0.05;
        tMax = tMax + tRange * 0.05;
        if (tMax <= tMin) tMax = tMin + 1;

        // Background
        ctx.fillStyle = C.bgCard || '#1e1e2e';
        ctx.fillRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = C.border || '#333';
        ctx.lineWidth = 0.5;
        for (var gi = 0; gi <= 4; gi++) {
            var gy = pad.top + gi * pH / 4;
            ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(pad.left + pW, gy); ctx.stroke();
        }

        // Trend line
        ctx.strokeStyle = C.accent || '#f97316';
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.beginPath();
        var first = true;
        for (var li = 0; li < laps.length; li++) {
            if (laps[li] === null || !isFinite(laps[li])) continue;
            var x = pad.left + li / Math.max(laps.length - 1, 1) * pW;
            var y = pad.top + pH - (laps[li] - tMin) / (tMax - tMin) * pH;
            if (first) { ctx.moveTo(x, y); first = false; }
            else { ctx.lineTo(x, y); }
        }
        ctx.stroke();

        // Data points
        ctx.fillStyle = C.accent || '#f97316';
        for (var di = 0; di < laps.length; di++) {
            if (laps[di] === null || !isFinite(laps[di])) continue;
            var dx = pad.left + di / Math.max(laps.length - 1, 1) * pW;
            var dy = pad.top + pH - (laps[di] - tMin) / (tMax - tMin) * pH;
            ctx.beginPath();
            ctx.arc(dx, dy, 3, 0, Math.PI * 2);
            ctx.fill();
        }

        // Y axis labels
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var yi = 0; yi <= 4; yi++) {
            var yy = pad.top + yi * pH / 4;
            var val = tMax - yi * (tMax - tMin) / 4;
            ctx.fillText(val.toFixed(1) + 's', pad.left - 6, yy);
        }

        // X axis labels
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        var nLabels = Math.min(laps.length, 8);
        var labelStep = Math.max(1, Math.floor(laps.length / nLabels));
        for (var xi = 0; xi < laps.length; xi += labelStep) {
            var xx = pad.left + xi / Math.max(laps.length - 1, 1) * pW;
            ctx.fillText('L' + (xi + 1), xx, pad.top + pH + 6);
        }

        // Axis titles
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = 'bold 11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText('Lap Number', pad.left + pW / 2, h - 12);
        ctx.save();
        ctx.translate(14, pad.top + pH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.textBaseline = 'middle';
        ctx.fillText('Lap Time (s)', 0, 0);
        ctx.restore();

        // Title
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = 'bold 12px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText('Lap Progress', w / 2, 6);
    }

    // -----------------------------------------------------------------
    // _drawScatter — generic scatter plot
    // -----------------------------------------------------------------

    function _drawScatter(canvas, data, title) {
        if (!data || !data.x || !data.y || data.x.length < 2) {
            _focusMsg(canvas, 'No scatter data');
            return;
        }

        var xs = data.x;
        var ys = data.y;

        var s = _setupCanvas(canvas);
        var ctx = s.ctx;
        var w = s.w;
        var h = s.h;

        var pad = { top: 30, right: 20, bottom: 45, left: 55 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        var xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
        for (var i = 0; i < xs.length; i++) {
            if (xs[i] !== null && isFinite(xs[i]) && ys[i] !== null && isFinite(ys[i])) {
                if (xs[i] < xMin) xMin = xs[i];
                if (xs[i] > xMax) xMax = xs[i];
                if (ys[i] < yMin) yMin = ys[i];
                if (ys[i] > yMax) yMax = ys[i];
            }
        }
        if (!isFinite(xMin)) { _focusMsg(canvas, 'No valid data'); return; }

        var xRange = xMax - xMin || 1;
        var yRange = yMax - yMin || 1;
        xMin -= xRange * 0.05; xMax += xRange * 0.05;
        yMin -= yRange * 0.05; yMax += yRange * 0.05;

        // Background
        ctx.fillStyle = C.bgCard || '#1e1e2e';
        ctx.fillRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = C.border || '#333';
        ctx.lineWidth = 0.5;
        for (var gi = 0; gi <= 4; gi++) {
            var gy = pad.top + gi * pH / 4;
            ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(pad.left + pW, gy); ctx.stroke();
            var gx = pad.left + gi * pW / 4;
            ctx.beginPath(); ctx.moveTo(gx, pad.top); ctx.lineTo(gx, pad.top + pH); ctx.stroke();
        }

        // Draw points
        ctx.fillStyle = C.accent || '#f97316';
        ctx.globalAlpha = 0.7;
        var dotR = xs.length > 1000 ? 1.5 : 3;
        for (var pi = 0; pi < xs.length; pi++) {
            if (xs[pi] === null || !isFinite(xs[pi]) || ys[pi] === null || !isFinite(ys[pi])) continue;
            var px = pad.left + (xs[pi] - xMin) / (xMax - xMin) * pW;
            var py = pad.top + pH - (ys[pi] - yMin) / (yMax - yMin) * pH;
            ctx.beginPath();
            ctx.arc(px, py, dotR, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.globalAlpha = 1;

        // Y axis labels
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var yi = 0; yi <= 4; yi++) {
            var yy = pad.top + yi * pH / 4;
            var yv = yMax - yi * (yMax - yMin) / 4;
            ctx.fillText(yv.toFixed(2), pad.left - 6, yy);
        }

        // X axis labels
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        for (var xi = 0; xi <= 4; xi++) {
            var xx = pad.left + xi * pW / 4;
            var xv = xMin + xi * (xMax - xMin) / 4;
            ctx.fillText(xv.toFixed(2), xx, pad.top + pH + 6);
        }

        // Title
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = 'bold 12px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(title || 'Scatter', w / 2, 6);
    }

    // -----------------------------------------------------------------
    // _drawBarChart — generic bar chart
    // -----------------------------------------------------------------

    function _drawBarChart(canvas, data, title) {
        if (!data || !data.labels || !data.values || data.labels.length === 0) {
            _focusMsg(canvas, 'No bar chart data');
            return;
        }

        var labels = data.labels;
        var values = data.values;

        var s = _setupCanvas(canvas);
        var ctx = s.ctx;
        var w = s.w;
        var h = s.h;

        var pad = { top: 30, right: 20, bottom: 50, left: 50 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        var maxVal = 0;
        for (var mi = 0; mi < values.length; mi++) {
            if (values[mi] > maxVal) maxVal = values[mi];
        }
        if (maxVal === 0) maxVal = 1;

        // Background
        ctx.fillStyle = C.bgCard || '#1e1e2e';
        ctx.fillRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = C.border || '#333';
        ctx.lineWidth = 0.5;
        for (var gi = 0; gi <= 4; gi++) {
            var gy = pad.top + gi * pH / 4;
            ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(pad.left + pW, gy); ctx.stroke();
        }

        // Bars
        var barW = pW / labels.length;
        var gap = Math.max(2, barW * 0.15);
        for (var bi = 0; bi < labels.length; bi++) {
            var barH = (values[bi] / maxVal) * pH;
            var bx = pad.left + bi * barW + gap / 2;
            var by = pad.top + pH - barH;
            var bw = barW - gap;

            ctx.fillStyle = C.accent || '#f97316';
            ctx.globalAlpha = 0.8;
            ctx.fillRect(bx, by, bw, barH);
            ctx.globalAlpha = 1;
            ctx.strokeStyle = C.accent || '#f97316';
            ctx.lineWidth = 1;
            ctx.strokeRect(bx, by, bw, barH);
        }

        // Y axis labels
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var yi = 0; yi <= 4; yi++) {
            var yy = pad.top + yi * pH / 4;
            var val = maxVal - yi * maxVal / 4;
            ctx.fillText(val.toFixed(1), pad.left - 6, yy);
        }

        // X axis labels
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.font = '9px system-ui, sans-serif';
        for (var xi = 0; xi < labels.length; xi++) {
            var xx = pad.left + (xi + 0.5) * barW;
            ctx.fillText(labels[xi], xx, pad.top + pH + 6);
        }

        // Title
        ctx.fillStyle = C.textSecondary || '#aaa';
        ctx.font = 'bold 12px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(title || 'Bar Chart', w / 2, 6);
    }

    // -----------------------------------------------------------------
    // Shared: placeholder message (DOM, no innerHTML)
    // -----------------------------------------------------------------

    function _placeholderMsg(container, text) {
        var div = document.createElement('div');
        div.style.display = 'flex';
        div.style.alignItems = 'center';
        div.style.justifyContent = 'center';
        div.style.height = '100%';
        div.style.minHeight = '200px';
        div.style.color = C.textMuted || '#777';
        div.style.fontSize = '14px';
        div.style.fontFamily = 'system-ui, sans-serif';
        div.textContent = text;
        container.appendChild(div);
    }

    // -----------------------------------------------------------------
    // Shared: destroy pattern
    // -----------------------------------------------------------------

    function _destroyContainer(container) {
        while (container.firstChild) container.removeChild(container.firstChild);
    }

    // -----------------------------------------------------------------
    // Shared: create canvas inside container
    // -----------------------------------------------------------------

    function _makeCanvas(container) {
        var canvas = document.createElement('canvas');
        canvas.style.width = '100%';
        canvas.style.display = 'block';
        container.appendChild(canvas);
        return canvas;
    }

    // =====================================================================
    // TOOL 1: track-map
    // =====================================================================

    FocusMode.registerTool('track-map', {
        icon: '\uD83D\uDDFA',
        label: 'Track Map',
        tabs: ['analytics', 'corners'],
        available: hasGps(),
        render: function (container, sessionId) {
            var canvas = _makeCanvas(container);
            var drawn = false;

            function draw(data) {
                _drawTrackMap(canvas, data);
                drawn = true;
            }

            _focusMsg(canvas, 'Loading track map...');
            var t = T();
            var bestLap = t.bestLap || (t.gpsLaps && t.gpsLaps[0]) || 1;
            var url = '/api/session/' + encodeURIComponent(sessionId) + '/gps/' + bestLap;
            FetchHelper.fetch(url)
                .then(function (data) { draw(data); })
                .catch(function () { _focusMsg(canvas, 'Failed to load GPS data'); });

            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () { if (drawn) { /* re-fetch would be needed; skip for resize */ } }
            };
        }
    });

    // =====================================================================
    // TOOL 2: speed-trace
    // =====================================================================

    FocusMode.registerTool('speed-trace', {
        icon: '\uD83D\uDCC8',
        label: 'Speed Trace',
        tabs: ['analytics'],
        available: hasGps(),
        render: function (container, sessionId) {
            var canvas = _makeCanvas(container);
            var _data = null;

            _focusMsg(canvas, 'Loading speed trace...');
            var t = T();
            var bestLap = t.bestLap || (t.gpsLaps && t.gpsLaps[0]) || 1;
            var url = '/api/session/' + encodeURIComponent(sessionId) + '/gps/' + bestLap;
            FetchHelper.fetch(url)
                .then(function (data) {
                    _data = data;
                    _drawSpeedTrace(canvas, data, C.accent || '#f97316');
                })
                .catch(function () { _focusMsg(canvas, 'Failed to load speed data'); });

            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () {
                    if (_data) _drawSpeedTrace(canvas, _data, C.accent || '#f97316');
                }
            };
        }
    });

    // =====================================================================
    // TOOL 3: gg-diagram
    // =====================================================================

    FocusMode.registerTool('gg-diagram', {
        icon: '\u26A1',
        label: 'G-G Diagram',
        tabs: ['analytics', 'corners'],
        available: hasGps(),
        render: function (container, sessionId) {
            var canvas = _makeCanvas(container);
            var _data = null;

            _focusMsg(canvas, 'Loading G-G data...');
            var url = '/api/session/' + encodeURIComponent(sessionId) + '/gg_data';
            FetchHelper.fetch(url)
                .then(function (data) {
                    _data = data;
                    _drawGG(canvas, data);
                })
                .catch(function () { _focusMsg(canvas, 'Failed to load G-G data'); });

            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () {
                    if (_data) _drawGG(canvas, _data);
                }
            };
        }
    });

    // =====================================================================
    // TOOL 4: lap-overlay
    // =====================================================================

    FocusMode.registerTool('lap-overlay', {
        icon: '\uD83D\uDCCA',
        label: 'Lap Overlay',
        tabs: ['analytics'],
        available: hasMultiLap(),
        render: function (container, sessionId) {
            var canvas = _makeCanvas(container);
            var _data = null;

            _focusMsg(canvas, 'Loading lap overlay...');
            var t = T();
            var bestLap = t.bestLap || (t.gpsLaps && t.gpsLaps[0]) || 1;
            var url = '/api/session/' + encodeURIComponent(sessionId) + '/gps/' + bestLap;
            FetchHelper.fetch(url)
                .then(function (data) {
                    _data = data;
                    _drawSpeedTrace(canvas, data, '#4fc3f7');
                })
                .catch(function () { _focusMsg(canvas, 'Failed to load overlay data'); });

            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () {
                    if (_data) _drawSpeedTrace(canvas, _data, '#4fc3f7');
                }
            };
        }
    });

    // =====================================================================
    // TOOL 5: lap-distribution
    // =====================================================================

    FocusMode.registerTool('lap-distribution', {
        icon: '\uD83D\uDCC9',
        label: 'Lap Distribution',
        tabs: ['analytics'],
        available: true,
        render: function (container, sessionId) {
            var canvas = _makeCanvas(container);
            var _data = null;

            _focusMsg(canvas, 'Loading distribution...');
            var url = '/api/session/' + encodeURIComponent(sessionId) + '/lap-distribution';
            FetchHelper.fetch(url)
                .then(function (data) {
                    _data = data;
                    _drawDistribution(canvas, data);
                })
                .catch(function () { _focusMsg(canvas, 'Failed to load distribution data'); });

            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () {
                    if (_data) _drawDistribution(canvas, _data);
                }
            };
        }
    });

    // =====================================================================
    // TOOL 6: lap-progress
    // =====================================================================

    FocusMode.registerTool('lap-progress', {
        icon: '\uD83C\uDFAF',
        label: 'Lap Progress',
        tabs: ['analytics'],
        available: true,
        render: function (container, sessionId) {
            var canvas = _makeCanvas(container);
            var _data = null;

            _focusMsg(canvas, 'Loading lap progress...');
            var url = '/api/session/' + encodeURIComponent(sessionId) + '/lap-progress';
            FetchHelper.fetch(url)
                .then(function (data) {
                    _data = data;
                    _drawProgress(canvas, data);
                })
                .catch(function () { _focusMsg(canvas, 'Failed to load progress data'); });

            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () {
                    if (_data) _drawProgress(canvas, _data);
                }
            };
        }
    });

    // =====================================================================
    // TOOL 7: brake-precision
    // =====================================================================

    FocusMode.registerTool('brake-precision', {
        icon: '\uD83D\uDED1',
        label: 'Brake Precision',
        tabs: ['corners'],
        available: hasGps(),
        render: function (container, sessionId) {
            var canvas = _makeCanvas(container);
            var _data = null;

            _focusMsg(canvas, 'Loading brake scatter...');
            var url = '/api/session/' + encodeURIComponent(sessionId) + '/brake-scatter';
            FetchHelper.fetch(url)
                .then(function (data) {
                    _data = data;
                    _drawScatter(canvas, data, 'Brake Precision');
                })
                .catch(function () { _focusMsg(canvas, 'Failed to load brake data'); });

            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () {
                    if (_data) _drawScatter(canvas, _data, 'Brake Precision');
                }
            };
        }
    });

    // =====================================================================
    // TOOL 8: stint-analysis
    // =====================================================================

    FocusMode.registerTool('stint-analysis', {
        icon: '\u23F1',
        label: 'Stint Analysis',
        tabs: ['performance'],
        available: true,
        render: function (container, sessionId) {
            var canvas = _makeCanvas(container);
            var _data = null;

            _focusMsg(canvas, 'Loading stint data...');
            var url = '/api/session/' + encodeURIComponent(sessionId) + '/stint-data';
            FetchHelper.fetch(url)
                .then(function (data) {
                    _data = data;
                    _drawBarChart(canvas, data, 'Stint Analysis');
                })
                .catch(function () { _focusMsg(canvas, 'Failed to load stint data'); });

            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () {
                    if (_data) _drawBarChart(canvas, _data, 'Stint Analysis');
                }
            };
        }
    });

    // =====================================================================
    // TOOL 9: driver-workload
    // =====================================================================

    FocusMode.registerTool('driver-workload', {
        icon: '\uD83D\uDCAA',
        label: 'Driver Workload',
        tabs: ['performance'],
        available: true,
        render: function (container) {
            _placeholderMsg(container, 'Driver Workload \u2014 use main page for full view');
            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () { /* static placeholder */ }
            };
        }
    });

    // =====================================================================
    // TOOL 10: session-timeline
    // =====================================================================

    FocusMode.registerTool('session-timeline', {
        icon: '\uD83D\uDCC5',
        label: 'Session Timeline',
        tabs: ['performance'],
        available: true,
        render: function (container) {
            _placeholderMsg(container, 'Session Timeline \u2014 use main page for full view');
            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () { /* static placeholder */ }
            };
        }
    });

    // =====================================================================
    // TOOL 11: fingerprint
    // =====================================================================

    FocusMode.registerTool('fingerprint', {
        icon: '\uD83D\uDD78',
        label: 'Fingerprint',
        tabs: ['overview'],
        available: true,
        render: function (container) {
            _placeholderMsg(container, 'Driving Fingerprint \u2014 use main page for full view');
            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () { /* static placeholder */ }
            };
        }
    });

    // =====================================================================
    // TOOL 12: badges
    // =====================================================================

    FocusMode.registerTool('badges', {
        icon: '\u2B50',
        label: 'Badges',
        tabs: ['overview'],
        available: true,
        render: function (container) {
            _placeholderMsg(container, 'Session Badges \u2014 use main page for full view');
            return {
                destroy: function () { _destroyContainer(container); },
                redraw: function () { /* static placeholder */ }
            };
        }
    });

})();
