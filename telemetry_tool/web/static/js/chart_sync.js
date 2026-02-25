/**
 * chart_sync.js — Speed-vs-distance chart with bidirectional hover sync.
 *
 * Draws a speed chart on <canvas id="speed-chart">.
 * Syncs with gps_trace.js:
 *   - Chart hover → updates map marker via gpsTrace.updateMarkerByDistance()
 *   - Map hover → updates chart crosshair via chartSync.updateCrosshair()
 *
 * Also draws a lap-times bar chart on <canvas id="lap-times-chart">.
 * Fetches & overlays the theoretical speed envelope (dashed gold line).
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};

    var speedCanvas = null;
    var speedCtx = null;
    var lapCanvas = null;
    var lapCtx = null;
    var crosshairEl = null;
    var tooltipEl = null;

    var chartData = null;      // { distances, speeds }
    var chartBounds = null;    // { xMin, xMax, yMin, yMax, plotX, plotY, plotW, plotH }
    var theoreticalData = null; // { distances, speeds } from API
    var _lastLaps = null;      // Stored for lap-times __redraw

    // ── Public API ──────────────────────────────────
    window.ChartSync = {
        onLapLoaded: onLapLoaded,
        updateCrosshair: updateCrosshair,
        loadSpeedData: loadSpeedDataForLap,
        getChartData: function () { return chartData; },
        getChartBounds: function () { return chartBounds; },
        getCanvas: function () { return speedCanvas; },
    };

    document.addEventListener('DOMContentLoaded', function () {
        speedCanvas = document.getElementById('speed-chart');
        lapCanvas = document.getElementById('lap-times-chart');
        crosshairEl = document.getElementById('chart-crosshair');
        tooltipEl = document.getElementById('chart-tooltip');

        if (speedCanvas) {
            speedCtx = speedCanvas.getContext('2d');
            setupSpeedChartEvents();
            loadTheoreticalData();
            // Self-load speed data from best lap GPS (no gps_trace dependency)
            _autoLoadBestLapSpeed();
        }

        // Load lap times chart.
        if (lapCanvas) {
            lapCtx = lapCanvas.getContext('2d');
            loadLapTimes();
        }

        // Register as map-hover consumer (TrackMap or legacy gpsTrace).
        if (window.TrackMap && window.TrackMap.onMapHover) {
            window.TrackMap.onMapHover = function (distance, speed, idx) {
                updateCrosshair(distance);
            };
        } else if (window.GpsTrace) {
            window.GpsTrace.onMapHover = function (distance, speed, idx) {
                updateCrosshair(distance);
            };
        }
    });

    // ── Auto-load speed data from best lap GPS ──────
    function _autoLoadBestLapSpeed() {
        var T = window.TELEMETRY;
        if (!T || !T.sessionId) return;

        var lapNum = T.bestLap;
        if (!lapNum && T.gpsLaps && T.gpsLaps.length > 0) {
            lapNum = T.gpsLaps[0];
        }
        if (!lapNum) return;

        loadSpeedDataForLap(lapNum);
    }

    function loadSpeedDataForLap(lapNum) {
        var T = window.TELEMETRY;
        if (!T || !T.sessionId) return;

        var url = '/api/session/' + encodeURIComponent(T.sessionId) + '/gps/' + lapNum;
        FetchHelper.fetch(url)
            .then(function (data) {
                if (data.distances && data.speeds) {
                    onLapLoaded({ distances: data.distances, speeds: data.speeds });
                }
            })
            .catch(function (err) {
                console.warn('Speed data load failed:', err);
            });
    }

    // ── Load theoretical speed envelope ──────────────
    function loadTheoreticalData() {
        var T = window.TELEMETRY;
        if (!T || !T.sessionId) return;

        var url = '/api/session/' + encodeURIComponent(T.sessionId) + '/theoretical';
        FetchHelper.fetch(url)
            .then(function (data) {
                if (data.distances && data.speeds) {
                    theoreticalData = { distances: data.distances, speeds: data.speeds };
                    if (chartData) drawSpeedChart();
                }
            })
            .catch(function (err) {
                console.warn('Theoretical data not available:', err);
            });
    }

    // ── Called when gps_trace loads a new lap ────────
    function onLapLoaded(data) {
        chartData = data;
        drawSpeedChart();
    }

    // ── Speed chart drawing ─────────────────────────
    function drawSpeedChart() {
        if (!speedCtx || !chartData) return;

        var canvas = speedCanvas;
        canvas.__redraw = function() { drawSpeedChart(); };
        var dpr = window.devicePixelRatio || 1;
        canvas.style.width = '';  // Reset to let CSS 100% take effect
        var w = canvas.clientWidth || canvas.parentElement.clientWidth || 700;
        var h = 250;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        speedCtx.scale(dpr, dpr);

        var ctx = speedCtx;
        var dists = chartData.distances;
        var speeds = chartData.speeds;
        if (!dists || dists.length < 2) return;

        // Chart area.
        var pad = { top: 20, right: 20, bottom: 40, left: 60 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        // Data ranges.
        var validDists = dists.filter(function (d) { return d !== null; });
        var validSpds = speeds.filter(function (s) { return s !== null && isFinite(s); });
        var xMin = 0;
        var xMax = Math.max.apply(null, validDists);
        var spdArr = validSpds.length > 0 ? validSpds : [0, 1];
        var yMin = 0;
        var yMax = Math.max.apply(null, spdArr) * 3.6 * 1.1;  // km/h with headroom

        // If theoretical data exists, extend yMax if needed.
        if (theoreticalData && theoreticalData.speeds) {
            var theoSpds = theoreticalData.speeds.filter(function (s) { return s !== null && isFinite(s); });
            if (theoSpds.length > 0) {
                var theoMax = Math.max.apply(null, theoSpds) * 3.6 * 1.1;
                if (theoMax > yMax) yMax = theoMax;
            }
        }

        chartBounds = {
            xMin: xMin, xMax: xMax, yMin: yMin, yMax: yMax,
            plotX: pad.left, plotY: pad.top, plotW: pW, plotH: pH,
        };

        function xToPixel(v) { return pad.left + (v - xMin) / (xMax - xMin) * pW; }
        function yToPixel(v) { return pad.top + pH - (v - yMin) / (yMax - yMin) * pH; }

        // Clear.
        ctx.clearRect(0, 0, w, h);

        // Background.
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, w, h);

        // Grid lines.
        ctx.strokeStyle = C.border || '#30363d';
        ctx.lineWidth = 0.5;
        var yTicks = niceRange(yMin, yMax, 5);
        for (var i = 0; i < yTicks.length; i++) {
            var y = yToPixel(yTicks[i]);
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(w - pad.right, y);
            ctx.stroke();
        }
        var xTicks = niceRange(xMin, xMax, 6);
        for (var i = 0; i < xTicks.length; i++) {
            var x = xToPixel(xTicks[i]);
            ctx.beginPath();
            ctx.moveTo(x, pad.top);
            ctx.lineTo(x, pad.top + pH);
            ctx.stroke();
        }

        // Y axis labels.
        ctx.fillStyle = C.textSecondary || '#8b949e';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var i = 0; i < yTicks.length; i++) {
            ctx.fillText(yTicks[i].toFixed(0), pad.left - 8, yToPixel(yTicks[i]));
        }

        // X axis labels.
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        for (var i = 0; i < xTicks.length; i++) {
            ctx.fillText(xTicks[i].toFixed(0) + 'm', xToPixel(xTicks[i]), pad.top + pH + 8);
        }

        // Axis titles.
        ctx.fillStyle = C.textSecondary || '#8b949e';
        ctx.font = '12px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Distance (m)', pad.left + pW / 2, h - 5);

        ctx.save();
        ctx.translate(14, pad.top + pH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('Speed (km/h)', 0, 0);
        ctx.restore();

        // ── Theoretical speed envelope (dashed gold) ────
        if (theoreticalData && theoreticalData.distances && theoreticalData.speeds) {
            ctx.strokeStyle = C.yellow || '#d29922';
            ctx.lineWidth = 2;
            ctx.setLineDash([8, 4]);
            ctx.beginPath();
            var theoDists = theoreticalData.distances;
            var theoSpds = theoreticalData.speeds;
            var started = false;
            for (var i = 0; i < theoDists.length; i++) {
                if (theoDists[i] === null || theoSpds[i] === null) continue;
                if (!isFinite(theoDists[i]) || !isFinite(theoSpds[i])) continue;
                var tx = xToPixel(theoDists[i]);
                var ty = yToPixel(theoSpds[i] * 3.6);
                if (!started) {
                    ctx.moveTo(tx, ty);
                    started = true;
                } else {
                    ctx.lineTo(tx, ty);
                }
            }
            ctx.stroke();
            ctx.setLineDash([]);

            // Legend.
            ctx.fillStyle = C.yellow || '#d29922';
            ctx.font = '10px -apple-system, sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'top';
            ctx.fillText('--- Theoretical', pad.left + 8, pad.top + 4);
        }

        // Speed line with colour gradient.
        ctx.lineWidth = 2;
        var spdMin = validSpds.length > 0 ? Math.min.apply(null, validSpds) : 0;
        var spdMax = validSpds.length > 0 ? Math.max.apply(null, validSpds) : 1;

        for (var i = 0; i < dists.length - 1; i++) {
            if (dists[i] === null || speeds[i] === null) continue;
            if (dists[i + 1] === null || speeds[i + 1] === null) continue;

            var sKmh = speeds[i] * 3.6;
            var sKmh2 = speeds[i + 1] * 3.6;
            ctx.strokeStyle = speedToColor(speeds[i], spdMin, spdMax);
            ctx.beginPath();
            ctx.moveTo(xToPixel(dists[i]), yToPixel(sKmh));
            ctx.lineTo(xToPixel(dists[i + 1]), yToPixel(sKmh2));
            ctx.stroke();
        }

        // Notify SpeedTraceZoom that the overview was redrawn (corner markers, selection)
        if (window.SpeedTraceZoom && window.SpeedTraceZoom.onOverviewRedrawn) {
            window.SpeedTraceZoom.onOverviewRedrawn();
        }
    }

    // ── Chart hover → map sync ──────────────────────
    function setupSpeedChartEvents() {
        speedCanvas.addEventListener('mousemove', function (e) {
            if (!chartBounds || !chartData) return;

            var rect = speedCanvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;
            var b = chartBounds;

            // Convert pixel X to distance.
            var distM = b.xMin + (mx - b.plotX) / b.plotW * (b.xMax - b.xMin);
            if (distM < b.xMin || distM > b.xMax) {
                hideCrosshair();
                return;
            }

            showCrosshair(mx);
            showTooltip(mx, my, distM);

            // Update map marker (canvas track map or legacy Leaflet).
            if (window.TrackMap && window.TrackMap.updateMarkerByDistance) {
                window.TrackMap.updateMarkerByDistance(distM);
            } else if (window.GpsTrace) {
                window.GpsTrace.updateMarkerByDistance(distM);
            }
        });

        speedCanvas.addEventListener('mouseleave', function () {
            hideCrosshair();
            hideTooltip();
        });

        // Touch support for mobile — reuse the same crosshair/tooltip logic as mousemove
        function handleSpeedChartTouch(e) {
            if (!chartBounds || !chartData) return;
            if (e.touches.length !== 1) return;

            var rect = speedCanvas.getBoundingClientRect();
            var mx = e.touches[0].clientX - rect.left;
            var my = e.touches[0].clientY - rect.top;
            var b = chartBounds;

            // Convert pixel X to distance.
            var distM = b.xMin + (mx - b.plotX) / b.plotW * (b.xMax - b.xMin);
            if (distM < b.xMin || distM > b.xMax) {
                hideCrosshair();
                return;
            }

            showCrosshair(mx);
            showTooltip(mx, my, distM);

            // Update map marker (canvas track map or legacy Leaflet).
            if (window.TrackMap && window.TrackMap.updateMarkerByDistance) {
                window.TrackMap.updateMarkerByDistance(distM);
            } else if (window.GpsTrace) {
                window.GpsTrace.updateMarkerByDistance(distM);
            }
        }

        speedCanvas.addEventListener('touchstart', handleSpeedChartTouch, { passive: true });
        speedCanvas.addEventListener('touchmove', handleSpeedChartTouch, { passive: true });
    }

    // ── Crosshair (from map hover) ──────────────────
    function updateCrosshair(distanceM) {
        if (!chartBounds || !crosshairEl) return;
        var b = chartBounds;
        var px = b.plotX + (distanceM - b.xMin) / (b.xMax - b.xMin) * b.plotW;
        showCrosshair(px);

        // Also show tooltip when syncing from map.
        showTooltip(px, null, distanceM);
    }

    function showCrosshair(pxX) {
        if (!crosshairEl) return;
        crosshairEl.style.left = pxX + 'px';
        crosshairEl.classList.add('visible');
    }

    function hideCrosshair() {
        if (!crosshairEl) return;
        crosshairEl.classList.remove('visible');
    }

    // ── Tooltip showing speed/distance ──────────────
    function showTooltip(pxX, pxY, distM) {
        if (!tooltipEl || !chartData) return;

        // Find speed at this distance via binary search.
        var dists = chartData.distances;
        var speeds = chartData.speeds;
        var idx = closestIndex(dists, distM);
        if (idx < 0 || idx >= speeds.length) {
            hideTooltip();
            return;
        }

        var speedMps = speeds[idx];
        if (speedMps === null || !isFinite(speedMps)) {
            hideTooltip();
            return;
        }

        var kmh = (speedMps * 3.6).toFixed(0);
        var distStr = distM.toFixed(0);
        tooltipEl.textContent = kmh + ' km/h @ ' + distStr + 'm';
        tooltipEl.style.left = (pxX + 10) + 'px';

        // Position tooltip above the crosshair.
        if (pxY !== null) {
            tooltipEl.style.top = (pxY - 24) + 'px';
        } else {
            tooltipEl.style.top = '8px';
        }

        tooltipEl.classList.add('visible');
    }

    function hideTooltip() {
        if (!tooltipEl) return;
        tooltipEl.classList.remove('visible');
    }

    function closestIndex(arr, target) {
        if (!arr || arr.length === 0) return -1;
        var lo = 0, hi = arr.length - 1;
        while (lo < hi) {
            var mid = (lo + hi) >> 1;
            if (arr[mid] < target) lo = mid + 1;
            else hi = mid;
        }
        if (lo > 0 && Math.abs(arr[lo - 1] - target) < Math.abs(arr[lo] - target)) {
            return lo - 1;
        }
        return lo;
    }

    // ── Lap times bar chart ─────────────────────────
    function loadLapTimes() {
        var T = window.TELEMETRY;
        if (!T) return;

        var url = '/api/session/' + encodeURIComponent(T.sessionId) + '/lap_times';
        FetchHelper.fetch(url)
            .then(function (data) { drawLapTimesChart(data.laps); })
            .catch(function (err) { console.warn('Lap times load failed:', err); });
    }

    function drawLapTimesChart(laps) {
        if (!lapCtx || !laps || laps.length === 0) return;
        _lastLaps = laps;  // Store for __redraw

        var canvas = lapCanvas;
        canvas.__redraw = function() { drawLapTimesChart(_lastLaps); };
        var dpr = window.devicePixelRatio || 1;
        canvas.style.width = '';  // Reset to let CSS 100% take effect
        var w = canvas.clientWidth || canvas.parentElement.clientWidth || 700;
        var h = 250;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        lapCtx.scale(dpr, dpr);

        var ctx = lapCtx;
        var pad = { top: 20, right: 20, bottom: 40, left: 60 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        var times = laps.map(function (l) { return l.lap_time_s; });
        var labels = laps.map(function (l) { return l.lap_number; });
        var isBest = laps.map(function (l) { return l.is_best; });
        var isValid = laps.map(function (l) { return l.is_valid !== false; });

        // Use only valid laps for Y-axis scaling and mean
        var validTimes = [];
        for (var i = 0; i < times.length; i++) {
            if (isValid[i]) validTimes.push(times[i]);
        }
        if (validTimes.length === 0) validTimes = times;

        var tMin = Math.min.apply(null, validTimes) * 0.98;
        var tMax = Math.max.apply(null, validTimes) * 1.02;

        function yToPixel(v) { return pad.top + pH - (v - tMin) / (tMax - tMin) * pH; }

        // Clear & background.
        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, w, h);

        // Grid.
        ctx.strokeStyle = C.border || '#30363d';
        ctx.lineWidth = 0.5;
        var yTicks = niceRange(tMin, tMax, 5);
        for (var i = 0; i < yTicks.length; i++) {
            var y = yToPixel(yTicks[i]);
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(w - pad.right, y);
            ctx.stroke();
        }

        // Y axis labels.
        ctx.fillStyle = C.textSecondary || '#8b949e';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var i = 0; i < yTicks.length; i++) {
            ctx.fillText(yTicks[i].toFixed(2) + 's', pad.left - 8, yToPixel(yTicks[i]));
        }

        // Bars.
        var barW = Math.min(30, pW / laps.length * 0.7);
        var gap = (pW - barW * laps.length) / (laps.length + 1);

        for (var i = 0; i < laps.length; i++) {
            var x = pad.left + gap + i * (barW + gap);
            var clampedTime = Math.max(tMin, Math.min(tMax, times[i]));
            var y = yToPixel(clampedTime);
            var barH = pad.top + pH - y;

            if (!isValid[i]) {
                // Invalid/incomplete laps: dim red with striped pattern
                ctx.fillStyle = C.bgTertiary || '#5c2020';
            } else if (isBest[i]) {
                ctx.fillStyle = C.accent || '#ff6b35';
            } else {
                ctx.fillStyle = C.blue ? (C.blue + '80') : '#30536d';
            }
            ctx.fillRect(x, y, barW, barH);

            // Mark invalid laps with a cross-hatch
            if (!isValid[i]) {
                ctx.strokeStyle = C.red || '#f85149';
                ctx.lineWidth = 1;
                ctx.setLineDash([2, 2]);
                for (var hh = y; hh < pad.top + pH; hh += 6) {
                    ctx.beginPath();
                    ctx.moveTo(x, hh);
                    ctx.lineTo(x + barW, hh);
                    ctx.stroke();
                }
                ctx.setLineDash([]);
            }

            // Lap number label.
            ctx.fillStyle = isValid[i] ? (C.textSecondary || '#8b949e') : (C.red || '#f85149');
            ctx.font = '10px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText(labels[i], x + barW / 2, pad.top + pH + 6);
        }

        // Axis titles.
        ctx.fillStyle = C.textSecondary || '#8b949e';
        ctx.font = '12px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Lap Number', pad.left + pW / 2, h - 5);

        ctx.save();
        ctx.translate(14, pad.top + pH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('Lap Time (s)', 0, 0);
        ctx.restore();

        // Mean line — EXCLUDE invalid/flagged laps.
        var mean = validTimes.reduce(function (a, b) { return a + b; }, 0) / validTimes.length;
        var meanY = yToPixel(mean);
        ctx.strokeStyle = C.yellow || '#d29922';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(pad.left, meanY);
        ctx.lineTo(w - pad.right, meanY);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = C.yellow || '#d29922';
        ctx.font = '10px -apple-system, sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'bottom';
        ctx.fillText('Mean: ' + mean.toFixed(3) + 's (' + validTimes.length + ' valid laps)', pad.left + 4, meanY - 3);

        // Store bar data for hover
        lapCanvas._barData = {
            bars: laps.map(function(l, i) {
                return {
                    x: pad.left + gap + i * (barW + gap),
                    w: barW,
                    lapNum: l.lap_number,
                    time: l.lap_time_s,
                    isBest: l.is_best,
                    isValid: l.is_valid !== false,
                };
            }),
            padTop: pad.top,
            plotBottom: pad.top + pH,
            tMin: tMin, tMax: tMax,
            yToPixel: yToPixel,
        };

        // Hover event for lap time tooltip
        if (!lapCanvas._hoverBound) {
            lapCanvas._hoverBound = true;
            lapCanvas.addEventListener('mousemove', function(e) {
                var tipEl = document.getElementById('lap-time-tooltip');
                if (!tipEl || !lapCanvas._barData) return;
                var rect = lapCanvas.getBoundingClientRect();
                var mx = e.clientX - rect.left;
                var my = e.clientY - rect.top;
                var bd = lapCanvas._barData;
                var hit = null;
                for (var bi = 0; bi < bd.bars.length; bi++) {
                    var b = bd.bars[bi];
                    if (mx >= b.x && mx <= b.x + b.w && my >= bd.padTop && my <= bd.plotBottom) {
                        hit = b;
                        break;
                    }
                }
                if (hit) {
                    var delta = hit.time - laps[0].lap_time_s;
                    var bestTime = Math.min.apply(null, laps.map(function(l){return l.lap_time_s;}));
                    var deltaVsBest = hit.time - bestTime;
                    tipEl.innerHTML = '<strong>Lap ' + hit.lapNum + '</strong><br>' +
                        hit.time.toFixed(3) + 's' +
                        (deltaVsBest > 0.001 ? '<br><span style="color:var(--accent)">+' + deltaVsBest.toFixed(3) + 's vs best</span>' : '<br><span style="color:var(--green)">Best lap!</span>');
                    tipEl.style.display = 'block';
                    tipEl.style.left = (mx + 15) + 'px';
                    tipEl.style.top = (my - 10) + 'px';
                } else {
                    tipEl.style.display = 'none';
                }
            });
            lapCanvas.addEventListener('mouseleave', function() {
                var tipEl = document.getElementById('lap-time-tooltip');
                if (tipEl) tipEl.style.display = 'none';
            });
        }
    }

    // ── Colour helper (same as gps_trace) ───────────
    function speedToColor(speed, minSpd, maxSpd) {
        var t = maxSpd > minSpd ? (speed - minSpd) / (maxSpd - minSpd) : 0.5;
        t = Math.max(0, Math.min(1, t));
        var r, g, b;
        if (t < 0.25) {
            r = 0; g = Math.round(255 * (t / 0.25)); b = 255;
        } else if (t < 0.5) {
            r = 0; g = 255; b = Math.round(255 * (1 - (t - 0.25) / 0.25));
        } else if (t < 0.75) {
            r = Math.round(255 * ((t - 0.5) / 0.25)); g = 255; b = 0;
        } else {
            r = 255; g = Math.round(255 * (1 - (t - 0.75) / 0.25)); b = 0;
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    // ── Nice range for axis ticks ───────────────────
    function niceRange(lo, hi, count) {
        var range = hi - lo;
        if (range <= 0) return [lo];
        var step = range / count;
        var mag = Math.pow(10, Math.floor(Math.log10(step)));
        var residual = step / mag;
        var niceStep;
        if (residual <= 1.5) niceStep = 1;
        else if (residual <= 3) niceStep = 2;
        else if (residual <= 7) niceStep = 5;
        else niceStep = 10;
        niceStep *= mag;

        var ticks = [];
        var start = Math.ceil(lo / niceStep) * niceStep;
        for (var v = start; v <= hi; v += niceStep) {
            ticks.push(v);
        }
        return ticks;
    }

})();
