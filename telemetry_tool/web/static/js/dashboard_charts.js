/**
 * dashboard_charts.js — Score trend + lap time sparklines for dashboard.
 *
 * Reads data from window.__dashboardData (embedded by the template).
 * Uses ChartFrame states for empty/ready, Motion.drawLine for animation.
 * Registered with ModuleManager for lifecycle cleanup.
 */
(function () {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    function init() {
        drawScoreTrend();
        drawLapTimes();
    }

    /* ── Score Trend sparkline ─────────────────── */

    function drawScoreTrend() {
        var canvas = document.getElementById('score-trend-canvas');
        if (!canvas) return;
        var frame = document.getElementById('score-trend-frame');

        var data = window.__dashboardData && window.__dashboardData.scoreTrend;
        if (!data || data.length === 0) {
            if (frame) window.ChartFrame.setState(frame, 'empty');
            return;
        }

        // Register __redraw for ResizeObserver
        canvas.__redraw = function () { drawScoreTrend(); };

        var rect = canvas.parentElement.getBoundingClientRect();
        var w = rect.width || 400;
        var h = Math.max(rect.height, 200);
        var ctx = window.sizeCanvas(canvas, w, h);

        var maxVal = Math.max.apply(null, data.map(function (d) { return d.score; }));
        var minVal = Math.min.apply(null, data.map(function (d) { return d.score; }));
        var range = maxVal - minVal || 1;
        var pad = { top: 20, right: 10, bottom: 20, left: 10 };
        var plotW = w - pad.left - pad.right;
        var plotH = h - pad.top - pad.bottom;

        var points = data.map(function (d, i) {
            return {
                x: pad.left + (i / Math.max(data.length - 1, 1)) * plotW,
                y: pad.top + plotH - ((d.score - minVal) / range) * plotH
            };
        });

        // Gradient fill under line
        var gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
        gradient.addColorStop(0, 'rgba(240, 112, 48, 0.15)');
        gradient.addColorStop(1, 'rgba(240, 112, 48, 0)');

        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (var i = 1; i < points.length; i++) {
            ctx.lineTo(points[i].x, points[i].y);
        }
        ctx.lineTo(points[points.length - 1].x, pad.top + plotH);
        ctx.lineTo(points[0].x, pad.top + plotH);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        // Progressive line draw
        var style = getComputedStyle(document.documentElement);
        var accentColor = style.getPropertyValue('--accent').trim() || '#f07030';
        window.Motion.drawLine(ctx, points, 600, { color: accentColor, width: 2 });

        if (frame) window.ChartFrame.setState(frame, 'ready');
    }

    /* ── Lap Times sparkline ──────────────────── */

    function drawLapTimes() {
        var canvas = document.getElementById('lap-times-canvas');
        if (!canvas) return;
        var frame = document.getElementById('lap-times-frame');

        var data = window.__dashboardData && window.__dashboardData.lapTimes;
        if (!data || data.length === 0) {
            if (frame) window.ChartFrame.setState(frame, 'empty');
            return;
        }

        // Register __redraw for ResizeObserver
        canvas.__redraw = function () { drawLapTimes(); };

        var rect = canvas.parentElement.getBoundingClientRect();
        var w = rect.width || 400;
        var h = Math.max(rect.height, 200);
        var ctx = window.sizeCanvas(canvas, w, h);

        var maxVal = Math.max.apply(null, data.map(function (d) { return d.time; }));
        var minVal = Math.min.apply(null, data.map(function (d) { return d.time; }));
        var range = maxVal - minVal || 1;
        var pad = { top: 20, right: 10, bottom: 20, left: 10 };
        var plotW = w - pad.left - pad.right;
        var plotH = h - pad.top - pad.bottom;

        var points = data.map(function (d, i) {
            return {
                x: pad.left + (i / Math.max(data.length - 1, 1)) * plotW,
                y: pad.top + plotH - ((d.time - minVal) / range) * plotH
            };
        });

        // Gradient fill
        var gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
        gradient.addColorStop(0, 'rgba(56, 189, 248, 0.15)');
        gradient.addColorStop(1, 'rgba(56, 189, 248, 0)');

        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (var j = 1; j < points.length; j++) {
            ctx.lineTo(points[j].x, points[j].y);
        }
        ctx.lineTo(points[points.length - 1].x, pad.top + plotH);
        ctx.lineTo(points[0].x, pad.top + plotH);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        // Progressive line draw
        var style = getComputedStyle(document.documentElement);
        var infoColor = style.getPropertyValue('--info').trim() || '#60a5fa';
        window.Motion.drawLine(ctx, points, 600, { color: infoColor, width: 2 });

        if (frame) window.ChartFrame.setState(frame, 'ready');
    }

    /* ── Lifecycle ────────────────────────────── */

    function destroy() {
        // Clear __redraw refs
        var c1 = document.getElementById('score-trend-canvas');
        var c2 = document.getElementById('lap-times-canvas');
        if (c1) c1.__redraw = null;
        if (c2) c2.__redraw = null;
        _lc.destroyAll();
    }

    window.ModuleManager.register('dashboard_charts', {
        init: init,
        destroy: destroy
    });

    // Auto-init when DOM is ready
    if (document.readyState === 'loading') {
        _lc.addListener(document, 'DOMContentLoaded', init);
    } else {
        init();
    }
})();
