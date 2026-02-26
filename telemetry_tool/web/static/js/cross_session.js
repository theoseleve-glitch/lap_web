/**
 * cross_session.js — Cross-session speed overlay and comparison widgets.
 *
 * Fetches speed traces from comparable sessions and overlays them
 * on a single chart for visual comparison.
 */
(function () {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    var PALETTE_FALLBACK = [
        '#ff6b35', '#58a6ff', '#3fb950', '#bc8cff', '#d29922', '#f85149',
    ];
    function paletteColor(i) {
        if (window.Theme && window.Theme.lapColor) return window.Theme.lapColor(i);
        return PALETTE_FALLBACK[i % PALETTE_FALLBACK.length];
    }

    var COLORS = {
        grid:   'rgba(48, 54, 61, 0.6)',
        text:   C.textSecondary || '#8b949e',
        bg:     C.bgCard || '#1a1f2e',
    };

    /**
     * Compute nice axis ticks.
     */
    function niceRange(dataMin, dataMax, targetTicks) {
        targetTicks = targetTicks || 6;
        var range = dataMax - dataMin;
        if (range <= 0) range = 1;
        var rough = range / targetTicks;
        var mag = Math.pow(10, Math.floor(Math.log10(rough)));
        var residual = rough / mag;
        var nice;
        if (residual <= 1.5) nice = 1;
        else if (residual <= 3) nice = 2;
        else if (residual <= 7) nice = 5;
        else nice = 10;
        var step = nice * mag;
        return {
            min: Math.floor(dataMin / step) * step,
            max: Math.ceil(dataMax / step) * step,
            step: step,
        };
    }

    /**
     * Initialise the cross-session speed overlay chart.
     * @param {string} canvasId   - Canvas element ID.
     * @param {string} sessionId  - Current session ID for API call.
     */
    function initOverlay(canvasId, sessionId) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;

        var ctx = canvas.getContext('2d');
        var container = canvas.parentElement;
        var data = null;
        var hoverDist = -1;
        var visibleTraces = {};  // session_id -> bool

        // Legend container
        var legendDiv = document.createElement('div');
        legendDiv.className = 'overlay-legend';
        legendDiv.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:8px;';
        container.parentElement.insertBefore(legendDiv, container.nextSibling);

        // Tooltip
        var tooltip = document.createElement('div');
        tooltip.style.cssText = 'position:absolute;display:none;' +
            'background:' + (C.bgSecondary || '#161b22') + ';' +
            'color:' + (C.textPrimary || '#e6edf3') + ';' +
            'padding:8px 12px;border-radius:6px;font-size:12px;pointer-events:none;' +
            'border:1px solid ' + (C.border || '#30363d') + ';z-index:10;white-space:nowrap;';
        container.appendChild(tooltip);

        function fetchData() {
            var url = '/api/session/' + encodeURIComponent(sessionId) + '/speed_overlay';
            FetchHelper.fetch(url)
                .then(function (json) {
                    data = json;
                    // Initialise all traces as visible
                    if (data && data.traces) {
                        var keys = Object.keys(data.traces);
                        for (var i = 0; i < keys.length; i++) {
                            visibleTraces[keys[i]] = true;
                        }
                    }
                    buildLegend();
                    resize();
                })
                .catch(function (err) {
                    console.warn('Cross-session speed overlay load failed:', err);
                });
        }

        function buildLegend() {
            legendDiv.innerHTML = '';
            if (!data || !data.traces) return;
            var keys = Object.keys(data.traces);
            for (var i = 0; i < keys.length; i++) {
                var sid = keys[i];
                var trace = data.traces[sid];
                var color = paletteColor(i);
                var item = document.createElement('label');
                item.style.cssText = 'display:flex;align-items:center;gap:4px;cursor:pointer;' +
                    'font-size:12px;color:' + (C.textPrimary || '#e6edf3') + ';';
                var cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.checked = true;
                cb.dataset.sid = sid;
                _lc.addListener(cb, 'change', function () {
                    visibleTraces[this.dataset.sid] = this.checked;
                    draw();
                });
                var dot = document.createElement('span');
                dot.style.cssText = 'width:10px;height:10px;border-radius:50%;display:inline-block;background:' + color;
                item.appendChild(cb);
                item.appendChild(dot);
                item.appendChild(document.createTextNode(' ' + (trace.label || sid.substring(0, 8))));
                legendDiv.appendChild(item);
            }
        }

        function resize() {
            var rect = container.getBoundingClientRect();
            var dpr = window.devicePixelRatio || 1;
            canvas.width = rect.width * dpr;
            canvas.height = 280 * dpr;
            canvas.style.width = rect.width + 'px';
            canvas.style.height = '280px';
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            draw();

            // Register __redraw for ResizeObserver
            canvas.__redraw = function() { resize(); };
        }

        function draw() {
            var w = parseFloat(canvas.style.width);
            var h = parseFloat(canvas.style.height);
            ctx.clearRect(0, 0, w, h);

            // Count visible traces
            var visibleKeys = [];
            var allKeys = data && data.traces ? Object.keys(data.traces) : [];
            for (var vi = 0; vi < allKeys.length; vi++) {
                if (visibleTraces[allKeys[vi]]) visibleKeys.push(allKeys[vi]);
            }
            var showDelta = visibleKeys.length === 2;

            if (!data || !data.traces || Object.keys(data.traces).length === 0) {
                ctx.fillStyle = COLORS.text;
                ctx.font = '14px system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('No comparable sessions for overlay', w / 2, h / 2);
                return;
            }

            var pad = { top: 15, right: showDelta ? 60 : 20, bottom: 40, left: 55 };
            var plotW = w - pad.left - pad.right;
            var plotH = h - pad.top - pad.bottom;

            // Compute global ranges (speeds converted m/s → km/h)
            var keys = Object.keys(data.traces);
            var maxDist = 0;
            var minSpeed = Infinity, maxSpeed = -Infinity;
            for (var i = 0; i < keys.length; i++) {
                if (!visibleTraces[keys[i]]) continue;
                var tr = data.traces[keys[i]];
                var dists = tr.distances || [];
                var speeds = tr.speeds || [];
                for (var j = 0; j < dists.length; j++) {
                    if (dists[j] > maxDist) maxDist = dists[j];
                }
                for (var j = 0; j < speeds.length; j++) {
                    var sKmh = speeds[j] * 3.6;
                    if (sKmh < minSpeed) minSpeed = sKmh;
                    if (sKmh > maxSpeed) maxSpeed = sKmh;
                }
            }
            if (maxDist === 0 || !isFinite(minSpeed)) return;

            var xAxis = niceRange(0, maxDist, 8);
            var yAxis = niceRange(minSpeed * 0.95, maxSpeed * 1.05, 6);

            function xPos(d) { return pad.left + ((d - xAxis.min) / (xAxis.max - xAxis.min)) * plotW; }
            function yPos(s) { return pad.top + (1 - (s - yAxis.min) / (yAxis.max - yAxis.min)) * plotH; }

            // Grid Y
            ctx.strokeStyle = COLORS.grid;
            ctx.lineWidth = 1;
            ctx.font = '11px system-ui, sans-serif';
            ctx.fillStyle = COLORS.text;
            ctx.textAlign = 'right';
            ctx.textBaseline = 'middle';
            for (var v = yAxis.min; v <= yAxis.max + yAxis.step * 0.001; v += yAxis.step) {
                var y = yPos(v);
                ctx.beginPath();
                ctx.moveTo(pad.left, y);
                ctx.lineTo(w - pad.right, y);
                ctx.stroke();
                ctx.fillText(v.toFixed(1), pad.left - 6, y);
            }

            // Grid X
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            for (var d = xAxis.min; d <= xAxis.max + xAxis.step * 0.001; d += xAxis.step) {
                var x = xPos(d);
                ctx.beginPath();
                ctx.moveTo(x, pad.top);
                ctx.lineTo(x, h - pad.bottom);
                ctx.stroke();
                ctx.fillText(d.toFixed(0) + 'm', x, h - pad.bottom + 4);
            }

            // Draw traces
            for (var i = 0; i < keys.length; i++) {
                var sid = keys[i];
                if (!visibleTraces[sid]) continue;
                var tr = data.traces[sid];
                var dists = tr.distances || [];
                var speeds = tr.speeds || [];
                var color = paletteColor(i);
                var isCurrent = tr.is_current;

                ctx.strokeStyle = color;
                ctx.lineWidth = isCurrent ? 2.5 : 1.5;
                ctx.globalAlpha = isCurrent ? 1.0 : 0.7;
                ctx.beginPath();
                for (var j = 0; j < Math.min(dists.length, speeds.length); j++) {
                    var px = xPos(dists[j]);
                    var py = yPos(speeds[j] * 3.6);
                    if (j === 0) ctx.moveTo(px, py);
                    else ctx.lineTo(px, py);
                }
                ctx.stroke();
                ctx.globalAlpha = 1.0;
            }

            // Time delta overlay (when exactly 2 visible)
            if (showDelta) {
                var trA = data.traces[visibleKeys[0]];
                var trB = data.traces[visibleKeys[1]];
                var deltaData = _computeTimeDelta(trA, trB);
                if (deltaData) {
                    _drawTimeDeltaOverlay(ctx, deltaData, pad, plotW, plotH, w, h);
                }
            }

            // Hover crosshair
            if (hoverDist >= 0) {
                var cx = xPos(hoverDist);
                ctx.strokeStyle = 'rgba(255,255,255,0.3)';
                ctx.lineWidth = 1;
                ctx.setLineDash([4, 4]);
                ctx.beginPath();
                ctx.moveTo(cx, pad.top);
                ctx.lineTo(cx, h - pad.bottom);
                ctx.stroke();
                ctx.setLineDash([]);
            }

            // Y-axis label
            ctx.save();
            ctx.translate(12, pad.top + plotH / 2);
            ctx.rotate(-Math.PI / 2);
            ctx.fillStyle = COLORS.text;
            ctx.font = '12px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Speed (km/h)', 0, 0);
            ctx.restore();
        }

        // Hover handler
        _lc.addListener(canvas, 'mousemove', function (e) {
            if (!data || !data.traces) return;
            var rect = canvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var w = parseFloat(canvas.style.width);
            var h = parseFloat(canvas.style.height);
            var vKeys = Object.keys(data.traces).filter(function(k) { return visibleTraces[k]; });
            var hPad = { top: 15, right: vKeys.length === 2 ? 60 : 20, bottom: 40, left: 55 };
            var plotW = w - hPad.left - hPad.right;

            // Find max distance for x-axis
            var keys = Object.keys(data.traces);
            var maxDist = 0;
            for (var i = 0; i < keys.length; i++) {
                var dists = data.traces[keys[i]].distances || [];
                for (var j = 0; j < dists.length; j++) {
                    if (dists[j] > maxDist) maxDist = dists[j];
                }
            }
            var xAxis = niceRange(0, maxDist, 8);
            var dist = xAxis.min + ((mx - hPad.left) / plotW) * (xAxis.max - xAxis.min);

            if (mx >= hPad.left && mx <= w - hPad.right) {
                hoverDist = dist;

                // Build tooltip with speed at this distance for each trace
                var lines = ['<strong>' + dist.toFixed(0) + 'm</strong>'];
                for (var i = 0; i < keys.length; i++) {
                    if (!visibleTraces[keys[i]]) continue;
                    var tr = data.traces[keys[i]];
                    var dists = tr.distances || [];
                    var speeds = tr.speeds || [];
                    // Binary search for closest distance
                    var idx = 0;
                    for (var j = 1; j < dists.length; j++) {
                        if (Math.abs(dists[j] - dist) < Math.abs(dists[idx] - dist)) idx = j;
                    }
                    var speed = (idx < speeds.length) ? speeds[idx] : null;
                    var color = paletteColor(i);
                    lines.push('<span style="color:' + color + '">' +
                        esc(tr.label || keys[i].substring(0, 8)) + ': ' +
                        (speed != null ? (speed * 3.6).toFixed(1) + ' km/h' : '—') + '</span>');
                }
                tooltip.innerHTML = lines.join('<br>');
                tooltip.style.display = 'block';
                var tx = Math.min(e.clientX - rect.left + 12, w - 200);
                tooltip.style.left = tx + 'px';
                tooltip.style.top = (e.clientY - rect.top - 40) + 'px';
            } else {
                hoverDist = -1;
                tooltip.style.display = 'none';
            }
            draw();
        });

        _lc.addListener(canvas, 'mouseleave', function () {
            hoverDist = -1;
            tooltip.style.display = 'none';
            draw();
        });

        var _csResizeTimer;
        _lc.addListener(window, 'resize', function () {
            clearTimeout(_csResizeTimer);
            _csResizeTimer = _lc.addTimer(resize, 150);
        });
        fetchData();
    }

    /**
     * Render a cross-session metrics summary panel.
     * @param {string} containerId - ID of container div.
     * @param {string} sessionId   - Current session ID.
     */
    function initMetrics(containerId, sessionId) {
        var container = document.getElementById(containerId);
        if (!container) return;

        var url = '/api/session/' + encodeURIComponent(sessionId) + '/cross_session';
        FetchHelper.load(container, url, function (d) {
            if (d.error) {
                container.innerHTML = '<div class="no-data"><div class="no-data-text">No cross-session data available.</div></div>';
                return;
            }
            var html = '<div class="meta-grid">';

            if (d.historical_percentile != null) {
                html += '<div class="meta-item">' +
                    '<span class="meta-label">Track Percentile</span>' +
                    '<span class="meta-value highlight">Top ' + d.historical_percentile.toFixed(0) + '%</span>' +
                    '</div>';
            }
            if (d.improvement && d.improvement.delta_s != null) {
                var arrow = d.improvement.improved ? '&darr;' : '&uarr;';
                var cls = d.improvement.improved ? 'good' : 'warn';
                html += '<div class="meta-item">' +
                    '<span class="meta-label">vs Last Session</span>' +
                    '<span class="meta-value ' + cls + '">' + arrow + ' ' +
                    Math.abs(d.improvement.delta_s).toFixed(3) + 's (' +
                    Math.abs(d.improvement.delta_pct).toFixed(1) + '%)</span>' +
                    '</div>';
            }
            if (d.track_best_time_s != null) {
                html += '<div class="meta-item">' +
                    '<span class="meta-label">Track Best</span>' +
                    '<span class="meta-value">' + d.track_best_time_s.toFixed(3) + 's</span>' +
                    '</div>';
            }
            if (d.comparable_count != null) {
                html += '<div class="meta-item">' +
                    '<span class="meta-label">Comparable Sessions</span>' +
                    '<span class="meta-value">' + d.comparable_count + '</span>' +
                    '</div>';
            }
            html += '</div>';
            container.innerHTML = html;
        }, {
            loadingText: 'Loading cross-session data\u2026',
        });
    }

    /**
     * Compute client-side time delta from two speed traces (speeds in m/s).
     */
    function _computeTimeDelta(traceA, traceB) {
        var dA = traceA.distances || [], sA = traceA.speeds || [];
        var dB = traceB.distances || [], sB = traceB.speeds || [];
        if (dA.length < 2 || dB.length < 2) return null;

        var maxDist = Math.min(dA[dA.length - 1] || 0, dB[dB.length - 1] || 0);
        if (maxDist < 10) return null;

        var nPts = Math.min(Math.floor(maxDist), 500);
        var distances = [], timeDelta = [];
        var cumA = 0, cumB = 0;

        for (var i = 0; i <= nPts; i++) {
            var d = i * maxDist / nPts;
            distances.push(d);
            var spA = _interp(dA, sA, d);
            var spB = _interp(dB, sB, d);
            if (i > 0) {
                var ds = distances[i] - distances[i - 1];
                var pA = _interp(dA, sA, distances[i - 1]);
                var pB = _interp(dB, sB, distances[i - 1]);
                if ((pA + spA) / 2 > 0.1) cumA += ds / ((pA + spA) / 2);
                if ((pB + spB) / 2 > 0.1) cumB += ds / ((pB + spB) / 2);
            }
            timeDelta.push(cumA - cumB);
        }
        return { distances: distances, time_delta: timeDelta };
    }

    function _interp(dists, speeds, target) {
        var j = 0;
        while (j < dists.length - 1 && (dists[j + 1] || 0) < target) j++;
        if (j >= dists.length - 1) return speeds[speeds.length - 1] || 0;
        var d0 = dists[j] || 0, d1 = dists[j + 1] || d0;
        var s0 = speeds[j] || 0, s1 = speeds[j + 1] || s0;
        if (d1 === d0) return s0;
        var t = (target - d0) / (d1 - d0);
        return s0 + (s1 - s0) * Math.max(0, Math.min(1, t));
    }

    function _drawTimeDeltaOverlay(ctx, data, pad, pW, pH, w, h) {
        var dists = data.distances;
        var deltas = data.time_delta;
        if (!dists || !deltas || dists.length === 0) return;

        var maxDist = dists[dists.length - 1] || 1;
        var maxAbs = 0;
        for (var i = 0; i < deltas.length; i++) {
            var a = Math.abs(deltas[i]);
            if (a > maxAbs) maxAbs = a;
        }
        if (maxAbs < 0.01) maxAbs = 0.1;
        maxAbs = Math.ceil(maxAbs * 10) / 10;

        function xToP(d) { return pad.left + (d / maxDist) * pW; }
        function yDelta(v) { return pad.top + pH / 2 - (v / maxAbs) * (pH / 2 - 5); }

        // Zero line
        ctx.strokeStyle = 'rgba(16, 185, 129, 0.3)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(pad.left, yDelta(0));
        ctx.lineTo(pad.left + pW, yDelta(0));
        ctx.stroke();
        ctx.setLineDash([]);

        // Shaded fill
        ctx.save();
        ctx.beginPath();
        ctx.rect(pad.left, pad.top, pW, pH);
        ctx.clip();

        ctx.beginPath();
        ctx.moveTo(xToP(dists[0]), yDelta(0));
        for (var i = 0; i < dists.length; i++) ctx.lineTo(xToP(dists[i]), yDelta(Math.max(0, deltas[i])));
        ctx.lineTo(xToP(dists[dists.length - 1]), yDelta(0));
        ctx.closePath();
        ctx.fillStyle = 'rgba(16, 185, 129, 0.08)';
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(xToP(dists[0]), yDelta(0));
        for (var i = 0; i < dists.length; i++) ctx.lineTo(xToP(dists[i]), yDelta(Math.min(0, deltas[i])));
        ctx.lineTo(xToP(dists[dists.length - 1]), yDelta(0));
        ctx.closePath();
        ctx.fillStyle = 'rgba(239, 68, 68, 0.08)';
        ctx.fill();

        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 3]);
        ctx.beginPath();
        for (var i = 0; i < dists.length; i++) {
            var x = xToP(dists[i]);
            var y = yDelta(deltas[i]);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.restore();

        // Right Y-axis
        ctx.fillStyle = '#10b981';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        var rightX = pad.left + pW + 6;
        ctx.fillText('+' + maxAbs.toFixed(1) + 's', rightX, yDelta(maxAbs));
        ctx.fillText('0s', rightX, yDelta(0));
        ctx.fillText('-' + maxAbs.toFixed(1) + 's', rightX, yDelta(-maxAbs));

        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 1;
        var tickX = pad.left + pW;
        ctx.beginPath();
        ctx.moveTo(tickX, yDelta(maxAbs)); ctx.lineTo(tickX + 4, yDelta(maxAbs));
        ctx.moveTo(tickX, yDelta(0)); ctx.lineTo(tickX + 4, yDelta(0));
        ctx.moveTo(tickX, yDelta(-maxAbs)); ctx.lineTo(tickX + 4, yDelta(-maxAbs));
        ctx.stroke();

        // Final delta annotation
        var finalDelta = deltas[deltas.length - 1];
        if (Math.abs(finalDelta) > 0.001) {
            var sign = finalDelta > 0 ? '+' : '';
            ctx.fillStyle = finalDelta > 0 ? 'rgba(239, 68, 68, 0.9)' : 'rgba(16, 185, 129, 0.9)';
            ctx.font = 'bold 11px system-ui, sans-serif';
            ctx.textAlign = 'right';
            ctx.textBaseline = 'bottom';
            ctx.fillText(sign + finalDelta.toFixed(3) + 's', pad.left + pW, yDelta(finalDelta) - 4);
        }
    }

    function destroy() {
        _lc.destroyAll();
    }

    window.CrossSession = {
        initOverlay: initOverlay,
        initMetrics: initMetrics,
    };

    window.ModuleManager.register('cross_session', {
        init: function () {},
        destroy: destroy
    });
})();
