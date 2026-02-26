/**
 * throttle_heatmap.js — Throttle onset heatmap visualization.
 *
 * Draws a laps × corners heatmap where cell color indicates
 * the throttle onset point (distance in metres from corner entry).
 * Darker = later throttle application.
 */
(function() {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    window.ThrottleHeatmap = { init: init };

    function init(canvasId, sessionId) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var container = canvas.parentElement;
        var url = '/api/session/' + encodeURIComponent(sessionId) + '/throttle-map';

        FetchHelper.load(container, url, function(data) {
            if (data.error) { _showMessage(canvas, data.error); return; }
            _draw(canvas, data);
            // Register __redraw for ResizeObserver
            canvas.__redraw = function() { _draw(canvas, data); };
        }, {
            loadingText: 'Loading throttle map\u2026',
            emptyCheck: function(d) { return !d || (!d.laps && !d.corners); },
            emptyIcon: '&#x1F525;',
            emptyText: 'No throttle map data available.',
        });
    }

    function _showMessage(canvas, msg) {
        var ctx = canvas.getContext('2d');
        canvas.width = canvas.parentElement.clientWidth || 600;
        canvas.height = 200;
        ctx.fillStyle = C.textSecondary || '#888';
        ctx.font = '14px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(msg, canvas.width / 2, canvas.height / 2);
    }

    function _draw(canvas, data) {
        var hm = data.heatmap;
        if (!hm || !hm.laps || hm.laps.length === 0) {
            _showMessage(canvas, 'No throttle data available');
            return;
        }

        var laps = hm.laps;
        var corners = hm.corners;
        var values = hm.values;
        var nLaps = laps.length;
        var nCorners = corners.length;

        var cellW = Math.min(60, Math.max(30, 500 / nCorners));
        var cellH = Math.min(28, Math.max(18, 400 / nLaps));
        var padL = 70, padT = 60, padR = 120, padB = 20;

        var W = padL + nCorners * cellW + padR;
        var H = padT + nLaps * cellH + padB;
        var dpr = window.devicePixelRatio || 1;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        // Find value range for color mapping
        var allVals = [];
        values.forEach(function(row) {
            row.forEach(function(v) { if (v !== null) allVals.push(v); });
        });
        if (allVals.length === 0) {
            _showMessage(canvas, 'No valid throttle data');
            return;
        }
        var minVal = Math.min.apply(null, allVals);
        var maxVal = Math.max.apply(null, allVals);
        var range = maxVal - minVal || 1;

        // Title
        ctx.fillStyle = C.textPrimary || '#ddd';
        ctx.font = 'bold 14px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Throttle Onset Map — Score: ' +
            (data.overall_throttle_score || 0).toFixed(1), padL, 20);

        // Column headers
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        corners.forEach(function(cid, ci) {
            ctx.fillStyle = C.textSecondary || '#aaa';
            ctx.fillText('C' + cid, padL + ci * cellW + cellW / 2, padT - 8);
        });

        // Row headers + cells
        laps.forEach(function(lap, li) {
            var y = padT + li * cellH;

            ctx.fillStyle = C.textSecondary || '#aaa';
            ctx.font = '10px system-ui, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText('Lap ' + lap, padL - 6, y + cellH / 2 + 3);

            corners.forEach(function(cid, ci) {
                var x = padL + ci * cellW;
                var val = values[li][ci];

                if (val === null) {
                    ctx.fillStyle = C.bgTertiary || '#1a1a1a';
                } else {
                    var t = (val - minVal) / range;
                    // Green (early) → Red (late)
                    var r = Math.round(50 + t * 180);
                    var g = Math.round(180 - t * 130);
                    var b = Math.round(50);
                    ctx.fillStyle = 'rgb(' + r + ',' + g + ',' + b + ')';
                }
                ctx.fillRect(x + 1, y + 1, cellW - 2, cellH - 2);

                // Value text
                if (val !== null) {
                    ctx.fillStyle = C.textPrimary || '#fff';
                    ctx.font = '9px system-ui, sans-serif';
                    ctx.textAlign = 'center';
                    ctx.fillText(val.toFixed(0) + 'm', x + cellW / 2, y + cellH / 2 + 3);
                }
            });
        });

        // Per-corner scores on the right
        var perCorner = data.per_corner || [];
        ctx.font = '10px system-ui, sans-serif';
        perCorner.forEach(function(pc, ci) {
            var x = padL + nCorners * cellW + 10;
            var y = padT + ci * 16;
            var sc = pc.throttle_score || 0;
            var color = sc >= 80 ? (C.green || '#4caf50') : sc >= 50 ? (C.accent || '#f5a623') : (C.red || '#ef5350');
            ctx.fillStyle = color;
            ctx.textAlign = 'left';
            ctx.fillText('C' + pc.corner_id + ': ' + sc.toFixed(0) + '%', x, y + 12);
        });
    }

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('throttle_heatmap', {
        init: function () {},
        destroy: destroy
    });
})();
