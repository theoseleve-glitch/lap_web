/**
 * trend_chart.js — Multi-session pace trend line chart.
 */
(function() {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};
    window.TrendChart = { draw: draw };

    function draw(canvasId, data) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var points = data.trend_points || [];
        if (points.length === 0) return;

        // Register __redraw for ResizeObserver
        canvas.__redraw = function() { draw(canvasId, data); };

        var W = canvas.parentElement.clientWidth || 700;
        var H = 350;
        var dpr = window.devicePixelRatio || 1;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        var padL = 70, padR = 30, padT = 30, padB = 50;
        var plotW = W - padL - padR;
        var plotH = H - padT - padB;

        var ys = points.map(function(p) { return p.y_actual; });
        var yMin = Math.min.apply(null, ys) - 0.5;
        var yMax = Math.max.apply(null, ys) + 0.5;
        var yRange = yMax - yMin || 1;
        var n = points.length;

        // Confidence band
        var lower = data.confidence_band ? data.confidence_band.lower : [];
        var upper = data.confidence_band ? data.confidence_band.upper : [];
        if (lower.length === n && upper.length === n) {
            ctx.fillStyle = 'rgba(245,166,35,0.1)';
            ctx.beginPath();
            for (var i = 0; i < n; i++) {
                var x = padL + (i / (n - 1)) * plotW;
                var y = padT + plotH - (upper[i] - yMin) / yRange * plotH;
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            for (var i = n - 1; i >= 0; i--) {
                var x = padL + (i / (n - 1)) * plotW;
                var y = padT + plotH - (lower[i] - yMin) / yRange * plotH;
                ctx.lineTo(x, y);
            }
            ctx.closePath();
            ctx.fill();
        }

        // Fitted line
        ctx.strokeStyle = '#f5a623';
        ctx.lineWidth = 2;
        ctx.beginPath();
        points.forEach(function(p, i) {
            var x = padL + (i / (n - 1)) * plotW;
            var y = padT + plotH - (p.y_fitted - yMin) / yRange * plotH;
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Actual points
        ctx.fillStyle = C.green || '#4caf50';
        points.forEach(function(p, i) {
            var x = padL + (i / (n - 1)) * plotW;
            var y = padT + plotH - (p.y_actual - yMin) / yRange * plotH;
            ctx.beginPath();
            ctx.arc(x, y, 5, 0, Math.PI * 2);
            ctx.fill();
        });

        // Axes
        ctx.strokeStyle = '#444';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padL, padT);
        ctx.lineTo(padL, padT + plotH);
        ctx.lineTo(padL + plotW, padT + plotH);
        ctx.stroke();

        // Y axis labels
        ctx.fillStyle = C.textSecondary || '#888';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'right';
        for (var i = 0; i <= 4; i++) {
            var val = yMin + (yRange * i / 4);
            var y = padT + plotH - (i / 4) * plotH;
            ctx.fillText(val.toFixed(2) + 's', padL - 6, y + 3);
        }

        // X axis labels (dates)
        ctx.textAlign = 'center';
        var step = Math.max(1, Math.floor(n / 6));
        points.forEach(function(p, i) {
            if (i % step === 0 || i === n - 1) {
                var x = padL + (i / (n - 1)) * plotW;
                ctx.fillText(p.session_date || ('S' + i), x, padT + plotH + 16);
            }
        });
    }

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('trend_chart', {
        init: function () {},
        destroy: destroy
    });
})();
