/**
 * weather_chart.js — Scatter plots for weather-pace correlation.
 */
(function() {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};
    window.WeatherChart = { draw: draw };

    function draw(canvasId, data) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        canvas.__redraw = function() { draw(canvasId, data); };
        var scatter = data.scatter_data || {};
        var keys = Object.keys(scatter);
        if (keys.length === 0) return;

        var nCharts = keys.length;
        var chartH = 200;
        var W = canvas.parentElement.clientWidth || 700;
        var H = nCharts * chartH + 40;
        var dpr = window.devicePixelRatio || 1;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        var padL = 80, padR = 30, padT = 30, padB = 30;
        var colors = [C.yellow || '#f5a623', C.green || '#4caf50', C.blue || '#2196f3', C.red || '#ef5350'];

        keys.forEach(function(key, idx) {
            var points = scatter[key];
            if (!points || points.length === 0) return;
            var corr = (data.correlations || {})[key] || {};
            var yOff = idx * chartH;

            var xs = points.map(function(p) { return p.x; });
            var ys = points.map(function(p) { return p.y; });
            var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
            var yMin = Math.min.apply(null, ys), yMax = Math.max.apply(null, ys);
            var xRange = xMax - xMin || 1;
            var yRange = yMax - yMin || 1;
            var plotW = W - padL - padR;
            var plotH = chartH - padT - padB;

            // Title
            ctx.fillStyle = '#ddd';
            ctx.font = 'bold 12px system-ui, sans-serif';
            ctx.textAlign = 'left';
            var title = (corr.label || key) + (corr.r !== null ? ' (r=' + corr.r.toFixed(3) + ')' : '');
            ctx.fillText(title, padL, yOff + 16);

            // Axes
            ctx.strokeStyle = '#333';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(padL, yOff + padT);
            ctx.lineTo(padL, yOff + padT + plotH);
            ctx.lineTo(padL + plotW, yOff + padT + plotH);
            ctx.stroke();

            // Points
            ctx.fillStyle = colors[idx % colors.length];
            points.forEach(function(p) {
                var px = padL + (p.x - xMin) / xRange * plotW;
                var py = yOff + padT + plotH - (p.y - yMin) / yRange * plotH;
                ctx.beginPath();
                ctx.arc(px, py, 4, 0, Math.PI * 2);
                ctx.fill();
            });

            // Axis labels
            ctx.fillStyle = C.textSecondary || '#888';
            ctx.font = '10px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(xMin.toFixed(1), padL, yOff + padT + plotH + 14);
            ctx.fillText(xMax.toFixed(1), padL + plotW, yOff + padT + plotH + 14);
            ctx.textAlign = 'right';
            ctx.fillText(yMin.toFixed(1) + 's', padL - 4, yOff + padT + plotH);
            ctx.fillText(yMax.toFixed(1) + 's', padL - 4, yOff + padT + 10);
        });
    }

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('weather_chart', {
        init: function () {},
        destroy: destroy
    });
})();
