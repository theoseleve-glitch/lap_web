/**
 * lap_overlay.js — Multi-lap speed overlay chart.
 *
 * Allows users to select multiple laps via checkboxes, each drawn
 * with a distinct colour on a shared distance-vs-speed chart.
 *
 * Reads: window.TELEMETRY = { sessionId, gpsLaps, bestLap }
 * Provides: window.LapOverlay.init()
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};

    // Distinct colours for up to 20 laps.
    var COLOURS = [
        C.accent || '#ff6b35', '#3b82f6', '#10b981', '#f59e0b', '#ef4444',
        '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1',
        '#84cc16', '#06b6d4', '#e11d48', '#a855f7', '#0ea5e9',
        '#d946ef', '#22d3ee', '#facc15', '#fb923c', '#4ade80',
    ];

    var canvas = null;
    var ctx = null;
    var legendEl = null;
    var lapDataCache = {};   // { lapNumber: { distances, speeds } }
    var deltaCache = {};     // { "lapA-lapB": { distances, time_delta } }
    var _pendingDelta = null;
    var selectedLaps = [];   // ordered list of checked laps

    // Chart state for hover
    var chartBounds = null;  // { xMax, yMax, pad, pW, pH, w, h }
    var lapColourMap = {};

    window.LapOverlay = { init: init };

    function init() {
        canvas = document.getElementById('speed-overlay-chart');
        legendEl = document.getElementById('overlay-legend');
        if (!canvas) return;
        ctx = canvas.getContext('2d');

        var checkboxes = document.querySelectorAll('.lap-overlay-cb');
        if (checkboxes.length === 0) return;

        // Wire up checkbox events.
        checkboxes.forEach(function (cb) {
            cb.addEventListener('change', onCheckboxChange);
        });

        // Select-all / clear-all buttons.
        var selAll = document.getElementById('overlay-select-all');
        var clrAll = document.getElementById('overlay-clear-all');
        if (selAll) selAll.addEventListener('click', function () {
            checkboxes.forEach(function (cb) { cb.checked = true; });
            onCheckboxChange();
        });
        if (clrAll) clrAll.addEventListener('click', function () {
            checkboxes.forEach(function (cb) { cb.checked = false; });
            onCheckboxChange();
        });

        // Assign swatch colours.
        checkboxes.forEach(function (cb, idx) {
            var swatch = cb.parentElement.querySelector('.lap-color-swatch');
            if (swatch) {
                swatch.style.display = 'inline-block';
                swatch.style.width = '12px';
                swatch.style.height = '12px';
                swatch.style.borderRadius = '2px';
                swatch.style.marginRight = '4px';
                swatch.style.verticalAlign = 'middle';
                swatch.style.backgroundColor = COLOURS[idx % COLOURS.length];
            }
        });

        // Initial draw from pre-checked checkboxes.
        onCheckboxChange();

        // Hover tooltip.
        canvas.addEventListener('mousemove', function (e) {
            if (!chartBounds || selectedLaps.length === 0) return;
            var rect = canvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;
            var b = chartBounds;

            if (mx < b.pad.left || mx > b.pad.left + b.pW) {
                _hideOverlayTooltip();
                return;
            }

            var distM = (mx - b.pad.left) / b.pW * b.xMax;

            // Redraw to remove old tooltip line, then draw crosshair
            draw();

            // Draw crosshair
            ctx.strokeStyle = 'rgba(255,255,255,0.3)';
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(mx, b.pad.top);
            ctx.lineTo(mx, b.pad.top + b.pH);
            ctx.stroke();
            ctx.setLineDash([]);

            // Build tooltip showing speed for each lap at this distance
            var T = window.TELEMETRY;
            var lines = ['<strong>' + distM.toFixed(0) + 'm</strong>'];
            var bestSpeed = null;

            selectedLaps.forEach(function (lapNum) {
                var d = lapDataCache[lapNum];
                if (!d || !d.distances || !d.speeds) return;
                var idx = _closestIdx(d.distances, distM);
                if (idx < 0 || idx >= d.speeds.length) return;
                var spd = d.speeds[idx];
                if (spd === null || !isFinite(spd)) return;
                var kmh = (spd * 3.6).toFixed(1);
                var colour = lapColourMap[lapNum] || (C.textPrimary || '#fff');
                var label = 'Lap ' + lapNum;
                if (lapNum === T.bestLap) {
                    label += ' (Best)';
                    bestSpeed = spd;
                }
                lines.push('<span style="color:' + colour + '">' + label + ': ' + kmh + ' km/h</span>');
            });

            // Show delta vs best if best lap is selected
            if (bestSpeed !== null && selectedLaps.length > 1) {
                lines.push('<hr style="margin:2px 0;border-color:var(--border);">');
                selectedLaps.forEach(function (lapNum) {
                    if (lapNum === T.bestLap) return;
                    var d = lapDataCache[lapNum];
                    if (!d || !d.distances || !d.speeds) return;
                    var idx = _closestIdx(d.distances, distM);
                    if (idx < 0) return;
                    var spd = d.speeds[idx];
                    if (spd === null || !isFinite(spd)) return;
                    var delta = (spd - bestSpeed) * 3.6;
                    var sign = delta >= 0 ? '+' : '';
                    var color = delta >= 0 ? (C.green || '#10b981') : (C.red || '#ef4444');
                    var colour = lapColourMap[lapNum] || (C.textPrimary || '#fff');
                    lines.push('<span style="color:' + color + '">Δ Lap ' + esc(lapNum) + ': ' + sign + delta.toFixed(1) + ' km/h</span>');
                });
            }

            _showOverlayTooltip(mx, my, lines.join('<br>'));
        });

        canvas.addEventListener('mouseleave', function () {
            _hideOverlayTooltip();
            draw();  // Redraw without crosshair
        });
    }

    var _overlayTooltipEl = null;
    function _showOverlayTooltip(x, y, html) {
        if (!_overlayTooltipEl) {
            _overlayTooltipEl = document.createElement('div');
            _overlayTooltipEl.style.cssText = 'position:absolute;z-index:10;background:rgba(0,0,0,0.85);' +
                'color:var(--text-primary);padding:8px 12px;border-radius:6px;font-size:12px;pointer-events:none;' +
                'line-height:1.5;max-width:300px;white-space:nowrap;border:1px solid var(--border);';
            canvas.parentElement.appendChild(_overlayTooltipEl);
        }
        _overlayTooltipEl.innerHTML = html;
        _overlayTooltipEl.style.display = 'block';
        // Position to the right of cursor, flip if near edge
        var parentW = canvas.parentElement.clientWidth;
        var tipW = _overlayTooltipEl.offsetWidth || 150;
        var left = x + 15;
        if (left + tipW > parentW - 20) left = x - tipW - 15;
        _overlayTooltipEl.style.left = left + 'px';
        _overlayTooltipEl.style.top = Math.max(5, y - 30) + 'px';
    }

    function _hideOverlayTooltip() {
        if (_overlayTooltipEl) _overlayTooltipEl.style.display = 'none';
    }

    function _closestIdx(arr, target) {
        if (!arr || arr.length === 0) return -1;
        var lo = 0, hi = arr.length - 1;
        while (lo < hi) {
            var mid = (lo + hi) >> 1;
            if (arr[mid] < target) lo = mid + 1;
            else hi = mid;
        }
        if (lo > 0 && Math.abs(arr[lo - 1] - target) < Math.abs(arr[lo] - target)) return lo - 1;
        return lo;
    }

    function onCheckboxChange() {
        var checkboxes = document.querySelectorAll('.lap-overlay-cb');
        selectedLaps = [];
        checkboxes.forEach(function (cb) {
            if (cb.checked) {
                selectedLaps.push(parseInt(cb.dataset.lap, 10));
            }
        });
        loadAndDraw();
    }

    function loadAndDraw() {
        if (selectedLaps.length === 0) {
            clearChart();
            return;
        }

        var T = window.TELEMETRY;
        if (!T || !T.sessionId) return;

        // Load missing lap data, then draw.
        var toLoad = selectedLaps.filter(function (n) { return !lapDataCache[n]; });
        if (toLoad.length === 0) {
            draw();
            return;
        }

        var promises = toLoad.map(function (lapNum) {
            var url = '/api/session/' + encodeURIComponent(T.sessionId) + '/gps/' + lapNum;
            return FetchHelper.fetch(url).then(function (data) {
                lapDataCache[lapNum] = data;
            }).catch(function (err) { console.warn('Lap overlay data load failed:', err); });
        });

        Promise.all(promises).then(draw);
    }

    function clearChart() {
        if (!ctx || !canvas) return;
        var dpr = window.devicePixelRatio || 1;
        var w = canvas.parentElement.clientWidth - 32;
        var h = 280;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, w, h);
        ctx.fillStyle = C.textSecondary || '#8b949e';
        ctx.font = '13px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Select laps above to compare speed profiles', w / 2, h / 2);
        if (legendEl) legendEl.innerHTML = '';
    }

    function draw() {
        if (!ctx || !canvas || selectedLaps.length === 0) return;

        var showDelta = selectedLaps.length === 2;
        var dpr = window.devicePixelRatio || 1;
        var w = canvas.parentElement.clientWidth - 32;
        var h = 280;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        var pad = { top: 20, right: showDelta ? 60 : 20, bottom: 40, left: 60 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        // Save bounds for hover
        chartBounds = { xMax: 0, yMax: 0, pad: pad, pW: pW, pH: pH, w: w, h: h };

        // Compute global ranges across all selected laps.
        var xMax = 0, yMax = 0;
        var allCheckboxes = document.querySelectorAll('.lap-overlay-cb');
        lapColourMap = {};
        allCheckboxes.forEach(function (cb, idx) {
            lapColourMap[parseInt(cb.dataset.lap, 10)] = COLOURS[idx % COLOURS.length];
        });

        selectedLaps.forEach(function (lapNum) {
            var d = lapDataCache[lapNum];
            if (!d || !d.distances || !d.speeds) return;
            var maxD = 0, maxS = 0;
            for (var i = 0; i < d.distances.length; i++) {
                if (d.distances[i] !== null && d.distances[i] > maxD) maxD = d.distances[i];
                if (d.speeds[i] !== null && isFinite(d.speeds[i]) && d.speeds[i] * 3.6 > maxS)
                    maxS = d.speeds[i] * 3.6;
            }
            if (maxD > xMax) xMax = maxD;
            if (maxS > yMax) yMax = maxS;
        });

        yMax *= 1.1; // headroom
        if (xMax <= 0) xMax = 1;
        if (yMax <= 0) yMax = 1;
        chartBounds.xMax = xMax;
        chartBounds.yMax = yMax;

        function xToPixel(v) { return pad.left + (v / xMax) * pW; }
        function yToPixel(v) { return pad.top + pH - (v / yMax) * pH; }

        // Background.
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, w, h);

        // Grid.
        ctx.strokeStyle = C.border || '#30363d';
        ctx.lineWidth = 0.5;
        var yTicks = niceRange(0, yMax, 5);
        for (var i = 0; i < yTicks.length; i++) {
            ctx.beginPath();
            ctx.moveTo(pad.left, yToPixel(yTicks[i]));
            ctx.lineTo(w - pad.right, yToPixel(yTicks[i]));
            ctx.stroke();
        }
        var xTicks = niceRange(0, xMax, 6);
        for (var i = 0; i < xTicks.length; i++) {
            ctx.beginPath();
            ctx.moveTo(xToPixel(xTicks[i]), pad.top);
            ctx.lineTo(xToPixel(xTicks[i]), pad.top + pH);
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

        // Draw each selected lap.
        var T = window.TELEMETRY;
        var legendHtml = '';
        selectedLaps.forEach(function (lapNum) {
            var d = lapDataCache[lapNum];
            if (!d || !d.distances || !d.speeds) return;

            var colour = lapColourMap[lapNum] || '#ffffff';
            ctx.strokeStyle = colour;
            ctx.lineWidth = lapNum === T.bestLap ? 2.5 : 1.5;
            ctx.globalAlpha = lapNum === T.bestLap ? 1.0 : 0.8;
            ctx.beginPath();
            var started = false;
            for (var i = 0; i < d.distances.length; i++) {
                if (d.distances[i] === null || d.speeds[i] === null) continue;
                var px = xToPixel(d.distances[i]);
                var py = yToPixel(d.speeds[i] * 3.6);
                if (!started) { ctx.moveTo(px, py); started = true; }
                else { ctx.lineTo(px, py); }
            }
            ctx.stroke();
            ctx.globalAlpha = 1.0;

            var label = 'Lap ' + lapNum;
            if (lapNum === T.bestLap) label += ' (Best)';
            legendHtml += '<span style="color:' + colour + '; margin-right:10px;">'
                + '<span style="display:inline-block;width:16px;height:3px;background:'
                + colour + ';vertical-align:middle;margin-right:3px;"></span>'
                + label + '</span>';
        });

        // Time delta overlay when exactly 2 laps selected
        if (showDelta && T && T.sessionId) {
            var lapA = selectedLaps[0], lapB = selectedLaps[1];
            var deltaKey = lapA + '-' + lapB;
            var cached = deltaCache[deltaKey];
            if (cached) {
                _drawTimeDelta(ctx, cached, pad, pW, pH, w, h, lapA, lapB);
                legendHtml += '<span style="color:#10b981; margin-right:10px;">'
                    + '<span style="display:inline-block;width:16px;height:0;border-top:2px dashed #10b981;vertical-align:middle;margin-right:3px;"></span>'
                    + 'Time Δ (s)</span>';
            } else if (_pendingDelta !== deltaKey) {
                _pendingDelta = deltaKey;
                FetchHelper.fetch('/api/session/' + encodeURIComponent(T.sessionId) + '/delta?lap_a=' + lapA + '&lap_b=' + lapB)
                    .then(function (data) {
                        if (data && data.distances) {
                            deltaCache[deltaKey] = data;
                            _pendingDelta = null;
                            draw();
                        }
                    })
                    .catch(function () { _pendingDelta = null; });
            }
        }

        if (legendEl) legendEl.innerHTML = legendHtml;

        // Register __redraw for ResizeObserver
        canvas.__redraw = function() { draw(); };
    }

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
        for (var v = start; v <= hi; v += niceStep) ticks.push(v);
        return ticks;
    }

    /**
     * Draw time-delta line with right Y-axis on the speed chart.
     */
    function _drawTimeDelta(ctx, data, pad, pW, pH, w, h, lapA, lapB) {
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

        // Delta line
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
        ctx.font = '10px -apple-system, sans-serif';
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
            ctx.font = 'bold 11px -apple-system, sans-serif';
            ctx.textAlign = 'right';
            ctx.textBaseline = 'bottom';
            ctx.fillText('Lap ' + lapA + ' ' + sign + finalDelta.toFixed(3) + 's', pad.left + pW, yDelta(finalDelta) - 4);
        }
    }

})();
