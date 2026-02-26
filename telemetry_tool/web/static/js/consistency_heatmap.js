/**
 * consistency_heatmap.js — Lap × Corner consistency heatmap.
 *
 * Each cell shows time loss (ms) at a corner on a given lap.
 * Green = minimal loss, yellow = moderate, red = significant.
 * Includes per-corner classification badges (consistent / variable / erratic).
 */
(function() {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    // Polyfill for CanvasRenderingContext2D.roundRect (older browsers)
    if (typeof CanvasRenderingContext2D !== 'undefined' &&
        !CanvasRenderingContext2D.prototype.roundRect) {
        CanvasRenderingContext2D.prototype.roundRect = function(x, y, w, h, r) {
            if (typeof r === 'number') r = [r, r, r, r];
            else if (!r) r = [0, 0, 0, 0];
            var rr = r[0];
            this.moveTo(x + rr, y);
            this.lineTo(x + w - rr, y);
            this.quadraticCurveTo(x + w, y, x + w, y + rr);
            this.lineTo(x + w, y + h - rr);
            this.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
            this.lineTo(x + rr, y + h);
            this.quadraticCurveTo(x, y + h, x, y + h - rr);
            this.lineTo(x, y + rr);
            this.quadraticCurveTo(x, y, x + rr, y);
            this.closePath();
            return this;
        };
    }

    window.ConsistencyHeatmap = { init: init };

    function init(canvasId, sessionId) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var container = canvas.parentElement;
        var url = '/api/session/' + encodeURIComponent(sessionId) + '/consistency-heatmap';

        FetchHelper.load(container, url, function(data) {
            if (data.error) { _showMessage(canvas, data.error); return; }
            _draw(canvas, data);
            // Register __redraw for ResizeObserver
            canvas.__redraw = function() { _draw(canvas, data); };
        }, {
            loadingText: 'Loading consistency heatmap\u2026',
            emptyCheck: function(d) { return !d || !d.matrix || d.matrix.length === 0; },
            emptyIcon: '&#x1F3AF;',
            emptyText: 'No consistency data available.',
        });
    }

    function _showMessage(canvas, msg) {
        var ctx = canvas.getContext('2d');
        canvas.width = canvas.parentElement.clientWidth || 600;
        canvas.height = 200;
        ctx.fillStyle = C.textSecondary || '#8b949e';
        ctx.font = '14px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(msg, canvas.width / 2, canvas.height / 2);
    }

    function _draw(canvas, data) {
        var laps = data.laps || [];
        var corners = data.corners || [];
        var values = data.values || [];
        var classifications = data.classifications || [];

        if (laps.length === 0 || corners.length === 0) {
            _showMessage(canvas, 'No consistency data available');
            return;
        }

        var nLaps = laps.length;
        var nCorners = corners.length;

        var cellW = Math.min(80, Math.max(40, 600 / nCorners));
        var cellH = Math.min(30, Math.max(20, 500 / nLaps));
        var padL = 80, padT = 80, padR = 50, padB = 60;

        var W = padL + nCorners * cellW + padR;
        var H = padT + nLaps * cellH + padB;
        var dpr = window.devicePixelRatio || 1;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        // Background
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, W, H);

        // Title
        ctx.fillStyle = C.textMuted || '#ccc';
        ctx.font = 'bold 14px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Consistency Heatmap — Total Loss: ' +
            (data.total_time_loss_ms || 0).toFixed(0) + 'ms, Mean: ' +
            (data.mean_time_loss_ms || 0).toFixed(1) + 'ms/corner', padL, 20);

        // Classification badges with colored pill backgrounds
        classifications.forEach(function(cl, ci) {
            var x = padL + ci * cellW + cellW / 2;
            var color = cl.classification === 'consistent' ? (C.green || '#4caf50') :
                        cl.classification === 'variable' ? (C.yellow || '#f5a623') : (C.red || '#ef5350');
            var pillW = ctx.measureText(cl.classification).width + 12;

            ctx.font = '10px system-ui, sans-serif';
            ctx.textAlign = 'center';

            // Pill background
            var pillH = 16, pillY = padT - 34;
            ctx.fillStyle = color + '33';
            ctx.beginPath();
            ctx.roundRect(x - pillW / 2, pillY, pillW, pillH, 4);
            ctx.fill();
            ctx.fillStyle = color;
            ctx.fillText(cl.classification, x, pillY + 12);
        });

        // Column headers
        ctx.font = 'bold 11px system-ui, sans-serif';
        corners.forEach(function(cid, ci) {
            ctx.fillStyle = C.textMuted || '#ccc';
            ctx.textAlign = 'center';
            ctx.fillText('C' + cid, padL + ci * cellW + cellW / 2, padT - 8);
        });

        // Color scale: use a capped scale based on percentile rather than max
        // This prevents one massive outlier from washing out all the rest
        var allVals = [];
        values.forEach(function(row) {
            row.forEach(function(v) {
                if (v !== null && isFinite(v)) allVals.push(v);
            });
        });
        allVals.sort(function(a, b) { return a - b; });

        // Use 90th percentile as scale cap (not max), minimum 50ms for sane coloring
        var capLoss;
        if (allVals.length > 0) {
            var p90idx = Math.min(allVals.length - 1, Math.floor(allVals.length * 0.9));
            capLoss = Math.max(50, allVals[p90idx] * 1.2);
        } else {
            capLoss = 100;
        }

        // Color mapping function: Green → Yellow → Orange → Red
        function lossColor(val) {
            var t = Math.min(1, Math.max(0, val / capLoss));
            if (window.Theme && window.Theme.heatColor) {
                return window.Theme.heatColor(t);
            }
            var r, g, b;
            if (t < 0.3) {
                // Dark green → bright green
                var s = t / 0.3;
                r = Math.round(30 + s * 50);
                g = Math.round(120 + s * 80);
                b = Math.round(60 - s * 20);
            } else if (t < 0.6) {
                // Green → Yellow
                var s = (t - 0.3) / 0.3;
                r = Math.round(80 + s * 175);
                g = Math.round(200 - s * 20);
                b = Math.round(40 - s * 10);
            } else if (t < 0.85) {
                // Yellow → Orange-Red
                var s = (t - 0.6) / 0.25;
                r = Math.round(255);
                g = Math.round(180 - s * 120);
                b = Math.round(30);
            } else {
                // Deep red
                var s = (t - 0.85) / 0.15;
                r = Math.round(255 - s * 20);
                g = Math.round(60 - s * 40);
                b = Math.round(30 + s * 20);
            }
            return 'rgb(' + r + ',' + g + ',' + b + ')';
        }

        // Draw cells
        laps.forEach(function(lap, li) {
            var y = padT + li * cellH;

            // Row label
            ctx.fillStyle = C.textMuted || '#aaa';
            ctx.font = '10px system-ui, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText('Lap ' + lap, padL - 8, y + cellH / 2 + 3);

            corners.forEach(function(cid, ci) {
                var x = padL + ci * cellW;
                var val = values[li][ci];

                if (val === null) {
                    ctx.fillStyle = C.bgTertiary || '#252a3a';
                } else {
                    ctx.fillStyle = lossColor(val);
                }

                // Rounded cells
                ctx.beginPath();
                ctx.roundRect(x + 1, y + 1, cellW - 2, cellH - 2, 3);
                ctx.fill();

                // Value text
                if (val !== null) {
                    var t = Math.min(1, val / capLoss);
                    ctx.fillStyle = t > 0.5 ? (C.textPrimary || '#e6edf3') : (C.textMuted || '#ccc');
                    ctx.font = 'bold 10px system-ui, sans-serif';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(val.toFixed(0), x + cellW / 2, y + cellH / 2);
                    ctx.textBaseline = 'alphabetic';
                }
            });
        });

        // Grid lines (subtle)
        ctx.strokeStyle = C.border || '#30363d';
        ctx.lineWidth = 0.5;
        for (var ci = 0; ci <= nCorners; ci++) {
            var gx = padL + ci * cellW;
            ctx.beginPath(); ctx.moveTo(gx, padT); ctx.lineTo(gx, padT + nLaps * cellH); ctx.stroke();
        }
        for (var li = 0; li <= nLaps; li++) {
            var gy = padT + li * cellH;
            ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + nCorners * cellW, gy); ctx.stroke();
        }

        // Legend
        var legY = padT + nLaps * cellH + 20;
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillStyle = C.textSecondary || '#8b949e';
        ctx.fillText('Time loss (ms):', padL, legY + 2);

        var legW = 150, legH = 12;
        var legX = padL + 95;
        for (var i = 0; i < legW; i++) {
            var t = i / legW;
            ctx.fillStyle = lossColor(t * capLoss);
            ctx.fillRect(legX + i, legY - 6, 1, legH);
        }
        ctx.strokeStyle = C.textSecondary || '#555';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(legX, legY - 6, legW, legH);

        ctx.fillStyle = C.textMuted || '#aaa';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('0', legX, legY + 18);
        ctx.fillText(Math.round(capLoss / 2).toString(), legX + legW / 2, legY + 18);
        ctx.fillText(Math.round(capLoss).toString() + '+', legX + legW, legY + 18);
    }

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('consistency_heatmap', {
        init: function () {},
        destroy: destroy
    });
})();
