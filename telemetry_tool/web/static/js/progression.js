/**
 * progression.js — Driver progression time-series and radar charts.
 *
 * - Pace delta over time
 * - Score progression
 * - Driving style radar chart
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};

    var COLORS = {
        accent:  C.accent || '#ff6b35',
        green:   C.green || '#3fb950',
        blue:    C.blue || '#58a6ff',
        purple:  C.purple || '#bc8cff',
        yellow:  C.yellow || '#d29922',
        red:     C.red || '#f85149',
        grid:    'rgba(48, 54, 61, 0.6)',
        text:    C.textSecondary || '#8b949e',
        bg:      C.bgCard || '#1a1f2e',
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
     * Draw a radar/spider chart for driving style features.
     */
    function drawRadar(canvasId, features) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;

        var ctx = canvas.getContext('2d');
        var container = canvas.parentElement;

        function resize() {
            var rect = container.getBoundingClientRect();
            var size = Math.min(rect.width, 320);
            var dpr = window.devicePixelRatio || 1;
            canvas.width = size * dpr;
            canvas.height = size * dpr;
            canvas.style.width = size + 'px';
            canvas.style.height = size + 'px';
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            draw(size);
        }

        function draw(size) {
            var labels = Object.keys(features);
            var values = Object.values(features);
            var n = labels.length;
            if (n === 0) return;

            var cx = size / 2;
            var cy = size / 2;
            var radius = size * 0.35;

            ctx.clearRect(0, 0, size, size);

            // Grid rings
            for (var ring = 1; ring <= 5; ring++) {
                var r = radius * ring / 5;
                ctx.strokeStyle = COLORS.grid;
                ctx.lineWidth = 1;
                ctx.beginPath();
                for (var i = 0; i <= n; i++) {
                    var angle = (Math.PI * 2 * i / n) - Math.PI / 2;
                    var x = cx + r * Math.cos(angle);
                    var y = cy + r * Math.sin(angle);
                    if (i === 0) ctx.moveTo(x, y);
                    else ctx.lineTo(x, y);
                }
                ctx.stroke();
            }

            // Axis lines + labels
            ctx.font = '10px system-ui, sans-serif';
            ctx.fillStyle = COLORS.text;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            for (var i = 0; i < n; i++) {
                var angle = (Math.PI * 2 * i / n) - Math.PI / 2;
                var x = cx + radius * Math.cos(angle);
                var y = cy + radius * Math.sin(angle);

                ctx.strokeStyle = COLORS.grid;
                ctx.beginPath();
                ctx.moveTo(cx, cy);
                ctx.lineTo(x, y);
                ctx.stroke();

                // Label
                var lx = cx + (radius + 18) * Math.cos(angle);
                var ly = cy + (radius + 18) * Math.sin(angle);
                var label = labels[i].replace(/_/g, ' ');
                // Abbreviate long labels
                if (label.length > 12) {
                    var words = label.split(' ');
                    label = words.map(function(w) { return w.substring(0, 5); }).join(' ');
                }
                ctx.fillText(label, lx, ly);
            }

            // Data polygon
            ctx.beginPath();
            for (var i = 0; i <= n; i++) {
                var idx = i % n;
                var val = Math.max(0, Math.min(1, values[idx] || 0));
                var angle = (Math.PI * 2 * idx / n) - Math.PI / 2;
                var x = cx + radius * val * Math.cos(angle);
                var y = cy + radius * val * Math.sin(angle);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.fillStyle = 'rgba(255, 107, 53, 0.2)';
            ctx.fill();
            ctx.strokeStyle = COLORS.accent;
            ctx.lineWidth = 2;
            ctx.stroke();

            // Data points
            for (var i = 0; i < n; i++) {
                var val = Math.max(0, Math.min(1, values[i] || 0));
                var angle = (Math.PI * 2 * i / n) - Math.PI / 2;
                var x = cx + radius * val * Math.cos(angle);
                var y = cy + radius * val * Math.sin(angle);
                ctx.beginPath();
                ctx.arc(x, y, 4, 0, Math.PI * 2);
                ctx.fillStyle = COLORS.accent;
                ctx.fill();
                ctx.strokeStyle = C.textPrimary || '#fff';
                ctx.lineWidth = 1;
                ctx.stroke();
            }
        }

        var _progResizeTimer;
        window.addEventListener('resize', function () {
            clearTimeout(_progResizeTimer);
            _progResizeTimer = setTimeout(resize, 150);
        });
        resize();
    }

    /**
     * Draw time-series progression charts.
     */
    function init(paceCanvasId, scoreCanvasId, driverId) {
        var paceCanvas = document.getElementById(paceCanvasId);
        var scoreCanvas = document.getElementById(scoreCanvasId);
        if (!paceCanvas && !scoreCanvas) return;

        var data = null;

        function fetchData() {
            FetchHelper.fetch('/drivers/' + driverId + '/api/progression')
                .then(function (json) {
                    data = json;
                    if (!data.progression || data.progression.length === 0) {
                        // Show empty-state message on pace canvas.
                        if (paceCanvas) {
                            var ctx = paceCanvas.getContext('2d');
                            var dpr = window.devicePixelRatio || 1;
                            var rect = paceCanvas.parentElement.getBoundingClientRect();
                            paceCanvas.width = rect.width * dpr;
                            paceCanvas.height = 80 * dpr;
                            paceCanvas.style.width = rect.width + 'px';
                            paceCanvas.style.height = '80px';
                            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
                            ctx.fillStyle = COLORS.text;
                            ctx.font = '14px system-ui, sans-serif';
                            ctx.textAlign = 'center';
                            ctx.fillText('No progression data yet \u2014 analyze more sessions', rect.width / 2, 40);
                        }
                        return;
                    }
                    if (paceCanvas) drawTimeSeries(paceCanvas, data.progression, 'pace_delta_s', 'Pace Delta (s)', COLORS.blue, true);
                    if (scoreCanvas) drawTimeSeries(scoreCanvas, data.progression, 'total_score', 'Total Score', COLORS.green, false);
                })
                .catch(function (err) {
                    console.warn('Progression data load failed:', err);
                });
        }

        function drawTimeSeries(canvas, prog, field, yLabel, color, invertY) {
            if (!prog || prog.length < 1) return;

            var ctx = canvas.getContext('2d');
            var container = canvas.parentElement;
            var rect = container.getBoundingClientRect();
            var dpr = window.devicePixelRatio || 1;
            canvas.width = rect.width * dpr;
            canvas.height = 220 * dpr;
            canvas.style.width = rect.width + 'px';
            canvas.style.height = '220px';
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

            var w = parseFloat(canvas.style.width);
            var h = parseFloat(canvas.style.height);
            var pad = { top: 15, right: 20, bottom: 45, left: 55 };
            var plotW = w - pad.left - pad.right;
            var plotH = h - pad.top - pad.bottom;

            ctx.clearRect(0, 0, w, h);

            var values = prog.map(function (p) { return p[field]; }).filter(function (v) { return v != null; });
            if (values.length < 1) return;

            var yAxis = niceRange(Math.min.apply(null, values), Math.max.apply(null, values), 5);

            function xPos(i) { return pad.left + (i / Math.max(1, prog.length - 1)) * plotW; }
            function yPos(v) {
                var norm = (v - yAxis.min) / (yAxis.max - yAxis.min);
                return invertY
                    ? pad.top + norm * plotH
                    : pad.top + (1 - norm) * plotH;
            }

            // Grid Y
            ctx.strokeStyle = COLORS.grid;
            ctx.lineWidth = 1;
            ctx.font = '11px system-ui, sans-serif';
            ctx.fillStyle = COLORS.text;
            ctx.textAlign = 'right';
            ctx.textBaseline = 'middle';
            for (var v = yAxis.min; v <= yAxis.max + yAxis.step * 0.01; v += yAxis.step) {
                var y = yPos(v);
                ctx.beginPath();
                ctx.moveTo(pad.left, y);
                ctx.lineTo(w - pad.right, y);
                ctx.stroke();
                ctx.fillText(v.toFixed(1), pad.left - 6, y);
            }

            // X dates
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            var maxLabels = Math.floor(plotW / 80);
            var step = Math.max(1, Math.ceil(prog.length / maxLabels));
            for (var i = 0; i < prog.length; i += step) {
                var x = xPos(i);
                var date = (prog[i].session_date || '').substring(0, 10);
                ctx.save();
                ctx.translate(x, h - pad.bottom + 6);
                ctx.rotate(-Math.PI / 6);
                ctx.fillText(date, 0, 0);
                ctx.restore();
            }

            // Line
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            var started = false;
            for (var i = 0; i < prog.length; i++) {
                var val = prog[i][field];
                if (val == null) continue;
                var px = xPos(i);
                var py = yPos(val);
                if (!started) { ctx.moveTo(px, py); started = true; }
                else ctx.lineTo(px, py);
            }
            ctx.stroke();

            // Points
            for (var i = 0; i < prog.length; i++) {
                var val = prog[i][field];
                if (val == null) continue;
                ctx.beginPath();
                ctx.arc(xPos(i), yPos(val), 3, 0, Math.PI * 2);
                ctx.fillStyle = color;
                ctx.fill();
            }

            // Y label
            ctx.save();
            ctx.translate(12, pad.top + plotH / 2);
            ctx.rotate(-Math.PI / 2);
            ctx.fillStyle = COLORS.text;
            ctx.font = '12px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(yLabel, 0, 0);
            ctx.restore();
        }

        fetchData();
    }

    window.Progression = {
        init: init,
        drawRadar: drawRadar,
    };
})();
