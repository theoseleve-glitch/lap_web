/**
 * comparison.js — Head-to-head comparison charts.
 *
 * - Speed overlay for two sessions
 * - Lap time comparison bar chart
 * - Progression overlay for two drivers
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};

    var COLORS = {
        a:       C.accent        || '#ff6b35',   // accent (orange)
        b:       C.blue          || '#58a6ff',   // blue
        grid:    (C.border || '#30363d') + '99',  // border with 60% alpha
        text:    C.textSecondary || '#8b949e',
        bg:      C.bgCard        || '#1a1f2e',
    };

    function niceRange(min, max, ticks) {
        ticks = ticks || 6;
        var range = max - min;
        if (range <= 0) range = 1;
        var rough = range / ticks;
        var mag = Math.pow(10, Math.floor(Math.log10(rough)));
        var res = rough / mag;
        var nice;
        if (res <= 1.5) nice = 1;
        else if (res <= 3) nice = 2;
        else if (res <= 7) nice = 5;
        else nice = 10;
        var step = nice * mag;
        return {
            min: Math.floor(min / step) * step,
            max: Math.ceil(max / step) * step,
            step: step,
        };
    }

    /**
     * Fetch speed traces for two sessions and draw overlay chart.
     */
    function initSpeedOverlay(canvasId, sessionA, sessionB) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;

        var url = '/compare/api/session_pair?a=' + encodeURIComponent(sessionA)
                + '&b=' + encodeURIComponent(sessionB);

        FetchHelper.fetch(url)
            .then(function (data) {
                var traces = data.traces || {};
                var keys = Object.keys(traces);
                if (keys.length === 0) return;

                drawSpeedOverlay(canvas, traces, keys);
            })
            .catch(function (err) {
                console.warn('Comparison speed overlay load failed:', err);
            });
    }

    function drawSpeedOverlay(canvas, traces, keys) {
        var ctx = canvas.getContext('2d');
        var container = canvas.parentElement;
        var rect = container.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        var showDelta = keys.length === 2;
        canvas.width = rect.width * dpr;
        canvas.height = 280 * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = '280px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        var w = parseFloat(canvas.style.width);
        var h = parseFloat(canvas.style.height);
        var pad = { top: 15, right: showDelta ? 60 : 20, bottom: 40, left: 55 };
        var plotW = w - pad.left - pad.right;
        var plotH = h - pad.top - pad.bottom;

        ctx.clearRect(0, 0, w, h);

        // Find global range.
        var allD = [], allS = [];
        keys.forEach(function (k) {
            var t = traces[k];
            if (t.distances) t.distances.forEach(function (d) { if (d != null) allD.push(d); });
            if (t.speeds) t.speeds.forEach(function (s) { if (s != null) allS.push(s); });
        });

        if (allD.length === 0 || allS.length === 0) return;

        var xMin = Math.min.apply(null, allD);
        var xMax = Math.max.apply(null, allD);
        var yAxis = niceRange(Math.min.apply(null, allS), Math.max.apply(null, allS), 5);

        function xPos(d) { return pad.left + ((d - xMin) / Math.max(1, xMax - xMin)) * plotW; }
        function yPos(s) { return pad.top + (1 - (s - yAxis.min) / (yAxis.max - yAxis.min)) * plotH; }

        // Y grid.
        ctx.font = '11px system-ui, sans-serif';
        ctx.fillStyle = COLORS.text;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var v = yAxis.min; v <= yAxis.max + yAxis.step * 0.01; v += yAxis.step) {
            var y = yPos(v);
            ctx.strokeStyle = COLORS.grid;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(w - pad.right, y);
            ctx.stroke();
            ctx.fillText(v.toFixed(1), pad.left - 6, y);
        }

        // X axis labels.
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        var xRange = niceRange(xMin, xMax, Math.floor(plotW / 80));
        for (var d = xRange.min; d <= xRange.max + xRange.step * 0.01; d += xRange.step) {
            var x = xPos(d);
            if (x >= pad.left && x <= w - pad.right) {
                ctx.fillText(Math.round(d) + 'm', x, h - pad.bottom + 6);
            }
        }

        // Draw traces.
        var colors = [COLORS.a, COLORS.b];
        keys.forEach(function (k, idx) {
            var t = traces[k];
            var color = colors[idx % colors.length];
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            var started = false;
            for (var i = 0; i < (t.distances || []).length; i++) {
                var dx = t.distances[i];
                var sx = t.speeds[i];
                if (dx == null || sx == null) continue;
                var px = xPos(dx);
                var py = yPos(sx);
                if (!started) { ctx.moveTo(px, py); started = true; }
                else ctx.lineTo(px, py);
            }
            ctx.stroke();
        });

        // Time delta overlay (when 2 sessions)
        if (showDelta) {
            var tA = traces[keys[0]], tB = traces[keys[1]];
            var deltaData = _computeTimeDelta(tA, tB);
            if (deltaData) {
                _drawTimeDeltaOverlay(ctx, deltaData, pad, plotW, plotH, w, h,
                    (tA.label || keys[0]).substring(0, 12),
                    (tB.label || keys[1]).substring(0, 12));
            }
        }

        // Legend.
        var legendY = pad.top + 10;
        keys.forEach(function (k, idx) {
            var color = colors[idx % colors.length];
            var label = traces[k].label || k.substring(0, 16);
            ctx.fillStyle = color;
            ctx.fillRect(pad.left + 10, legendY + idx * 18, 14, 3);
            ctx.fillStyle = COLORS.text;
            ctx.font = '11px system-ui, sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, pad.left + 30, legendY + idx * 18 + 2);
        });
        if (showDelta) {
            ctx.strokeStyle = '#10b981';
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 3]);
            ctx.beginPath();
            ctx.moveTo(pad.left + 10, legendY + keys.length * 18 + 2);
            ctx.lineTo(pad.left + 24, legendY + keys.length * 18 + 2);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = '#10b981';
            ctx.font = '11px system-ui, sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText('Time Δ (s)', pad.left + 30, legendY + keys.length * 18 + 2);
        }

        // Y label.
        ctx.save();
        ctx.translate(12, pad.top + plotH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = COLORS.text;
        ctx.font = '12px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Speed (m/s)', 0, 0);
        ctx.restore();
    }

    /**
     * Draw side-by-side lap time chart.
     */
    function initLapTimeChart(canvasId, lapsA, lapsB, labelA, labelB) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;

        var timesA = lapsA.filter(function (l) { return l.lap_time_s != null; })
                         .map(function (l) { return { n: l.lap_number, t: l.lap_time_s }; });
        var timesB = lapsB.filter(function (l) { return l.lap_time_s != null; })
                         .map(function (l) { return { n: l.lap_number, t: l.lap_time_s }; });

        if (timesA.length === 0 && timesB.length === 0) return;

        var ctx = canvas.getContext('2d');
        var container = canvas.parentElement;
        var rect = container.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = 250 * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = '250px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        var w = parseFloat(canvas.style.width);
        var h = parseFloat(canvas.style.height);
        var pad = { top: 20, right: 20, bottom: 40, left: 55 };
        var plotW = w - pad.left - pad.right;
        var plotH = h - pad.top - pad.bottom;

        ctx.clearRect(0, 0, w, h);

        var allT = timesA.map(function (x) { return x.t; })
                   .concat(timesB.map(function (x) { return x.t; }));
        var maxLap = Math.max(
            timesA.length > 0 ? timesA[timesA.length - 1].n : 0,
            timesB.length > 0 ? timesB[timesB.length - 1].n : 0
        );

        var yAxis = niceRange(Math.min.apply(null, allT), Math.max.apply(null, allT), 5);

        function xPos(n) { return pad.left + ((n - 1) / Math.max(1, maxLap - 1)) * plotW; }
        function yPos(t) { return pad.top + (1 - (t - yAxis.min) / (yAxis.max - yAxis.min)) * plotH; }

        // Grid.
        ctx.font = '11px system-ui, sans-serif';
        ctx.fillStyle = COLORS.text;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var v = yAxis.min; v <= yAxis.max + yAxis.step * 0.01; v += yAxis.step) {
            var y = yPos(v);
            ctx.strokeStyle = COLORS.grid;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(w - pad.right, y);
            ctx.stroke();
            ctx.fillText(v.toFixed(1), pad.left - 6, y);
        }

        // Draw lines + dots for each.
        var datasets = [
            { data: timesA, color: COLORS.a, label: labelA },
            { data: timesB, color: COLORS.b, label: labelB },
        ];

        datasets.forEach(function (ds) {
            if (ds.data.length === 0) return;

            // Line.
            ctx.strokeStyle = ds.color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ds.data.forEach(function (pt, i) {
                var px = xPos(pt.n);
                var py = yPos(pt.t);
                if (i === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
            });
            ctx.stroke();

            // Dots.
            ds.data.forEach(function (pt) {
                ctx.beginPath();
                ctx.arc(xPos(pt.n), yPos(pt.t), 3, 0, Math.PI * 2);
                ctx.fillStyle = ds.color;
                ctx.fill();
            });
        });

        // Legend.
        var legendY = pad.top + 8;
        datasets.forEach(function (ds, idx) {
            ctx.fillStyle = ds.color;
            ctx.fillRect(pad.left + 10, legendY + idx * 18, 14, 3);
            ctx.fillStyle = COLORS.text;
            ctx.font = '11px system-ui, sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(ds.label, pad.left + 30, legendY + idx * 18 + 2);
        });

        // Y label.
        ctx.save();
        ctx.translate(12, pad.top + plotH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = COLORS.text;
        ctx.font = '12px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Lap Time (s)', 0, 0);
        ctx.restore();

        // X label.
        ctx.fillStyle = COLORS.text;
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        var step = Math.max(1, Math.ceil(maxLap / (plotW / 40)));
        for (var n = 1; n <= maxLap; n += step) {
            ctx.fillText(n.toString(), xPos(n), h - pad.bottom + 6);
        }
    }

    /**
     * Draw overlaid score progression for two drivers.
     */
    function initProgressionOverlay(canvasId, progA, progB, nameA, nameB) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;

        var ctx = canvas.getContext('2d');
        var container = canvas.parentElement;
        var rect = container.getBoundingClientRect();
        var dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = 250 * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = '250px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        var w = parseFloat(canvas.style.width);
        var h = parseFloat(canvas.style.height);
        var pad = { top: 20, right: 20, bottom: 45, left: 55 };
        var plotW = w - pad.left - pad.right;
        var plotH = h - pad.top - pad.bottom;

        ctx.clearRect(0, 0, w, h);

        // Parse dates and scores.
        function parse(prog) {
            return (prog || []).filter(function (p) { return p.total_score != null; })
                .map(function (p) {
                    return { date: p.session_date || '', score: p.total_score };
                });
        }

        var pA = parse(progA);
        var pB = parse(progB);

        if (pA.length === 0 && pB.length === 0) return;

        // Merge all scores for Y range.
        var allScores = pA.map(function (p) { return p.score; })
                        .concat(pB.map(function (p) { return p.score; }));
        var yAxis = niceRange(Math.min.apply(null, allScores), Math.max.apply(null, allScores), 5);

        var maxLen = Math.max(pA.length, pB.length);

        function xPos(i, total) { return pad.left + (i / Math.max(1, total - 1)) * plotW; }
        function yPos(v) { return pad.top + (1 - (v - yAxis.min) / (yAxis.max - yAxis.min)) * plotH; }

        // Grid.
        ctx.font = '11px system-ui, sans-serif';
        ctx.fillStyle = COLORS.text;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var v = yAxis.min; v <= yAxis.max + yAxis.step * 0.01; v += yAxis.step) {
            var y = yPos(v);
            ctx.strokeStyle = COLORS.grid;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(w - pad.right, y);
            ctx.stroke();
            ctx.fillText(v.toFixed(0), pad.left - 6, y);
        }

        // Draw each.
        var datasets = [
            { data: pA, color: COLORS.a, label: nameA },
            { data: pB, color: COLORS.b, label: nameB },
        ];

        datasets.forEach(function (ds) {
            if (ds.data.length === 0) return;
            ctx.strokeStyle = ds.color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ds.data.forEach(function (pt, i) {
                var px = xPos(i, ds.data.length);
                var py = yPos(pt.score);
                if (i === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
            });
            ctx.stroke();

            ds.data.forEach(function (pt, i) {
                ctx.beginPath();
                ctx.arc(xPos(i, ds.data.length), yPos(pt.score), 3, 0, Math.PI * 2);
                ctx.fillStyle = ds.color;
                ctx.fill();
            });
        });

        // Legend.
        var legendY = pad.top + 8;
        datasets.forEach(function (ds, idx) {
            ctx.fillStyle = ds.color;
            ctx.fillRect(pad.left + 10, legendY + idx * 18, 14, 3);
            ctx.fillStyle = COLORS.text;
            ctx.font = '11px system-ui, sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(ds.label, pad.left + 30, legendY + idx * 18 + 2);
        });

        // Y label.
        ctx.save();
        ctx.translate(12, pad.top + plotH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = COLORS.text;
        ctx.font = '12px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Total Score', 0, 0);
        ctx.restore();
    }

    /**
     * Compute client-side time delta from two speed traces.
     */
    function _computeTimeDelta(traceA, traceB) {
        var dA = traceA.distances || [], sA = traceA.speeds || [];
        var dB = traceB.distances || [], sB = traceB.speeds || [];
        if (dA.length < 2 || dB.length < 2) return null;

        var maxDist = Math.min(dA[dA.length - 1] || 0, dB[dB.length - 1] || 0);
        if (maxDist < 10) return null;

        var nPoints = Math.min(Math.floor(maxDist), 500);
        var distances = [], timeDelta = [];
        var cumA = 0, cumB = 0;
        var jA = 0, jB = 0;

        for (var i = 0; i <= nPoints; i++) {
            var d = i * maxDist / nPoints;
            distances.push(d);

            // Interpolate speed at distance d for both traces
            var spA = _interpSpeed(dA, sA, d, jA);
            var spB = _interpSpeed(dB, sB, d, jB);

            if (i > 0) {
                var ds = distances[i] - distances[i - 1];
                var prevSpA = _interpSpeed(dA, sA, distances[i - 1], jA);
                var prevSpB = _interpSpeed(dB, sB, distances[i - 1], jB);
                var avgA = (prevSpA + spA) / 2;
                var avgB = (prevSpB + spB) / 2;
                if (avgA > 0.1) cumA += ds / avgA;
                if (avgB > 0.1) cumB += ds / avgB;
            }
            timeDelta.push(cumA - cumB);
        }
        return { distances: distances, time_delta: timeDelta };
    }

    function _interpSpeed(dists, speeds, target) {
        var j = 0;
        while (j < dists.length - 1 && (dists[j + 1] || 0) < target) j++;
        if (j >= dists.length - 1) return speeds[speeds.length - 1] || 0;
        var d0 = dists[j] || 0, d1 = dists[j + 1] || d0;
        var s0 = speeds[j] || 0, s1 = speeds[j + 1] || s0;
        if (d1 === d0) return s0;
        var t = (target - d0) / (d1 - d0);
        return s0 + (s1 - s0) * Math.max(0, Math.min(1, t));
    }

    /**
     * Draw time-delta overlay on a speed chart.
     */
    function _drawTimeDeltaOverlay(ctx, data, pad, pW, pH, w, h, labelA, labelB) {
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

    window.Comparison = {
        initSpeedOverlay: initSpeedOverlay,
        initLapTimeChart: initLapTimeChart,
        initProgressionOverlay: initProgressionOverlay,
    };
})();
