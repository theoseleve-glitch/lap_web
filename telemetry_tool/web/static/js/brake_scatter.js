/**
 * brake_scatter.js — Brake precision scatter chart.
 *
 * Draws a per-corner brake-point scatter plot showing how consistently
 * the driver brakes at each corner across laps.  Individual lap dots are
 * plotted along with the mean marker and precision score bar.
 */
(function() {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};

    window.BrakeScatter = { init: init };

    function init(canvasId, sessionId) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var container = canvas.parentElement;
        var url = '/api/session/' + encodeURIComponent(sessionId) + '/brake-precision';

        FetchHelper.load(container, url, function(data) {
            if (data.error) { _showMessage(canvas, data.error); return; }
            _draw(canvas, data);
            // Register __redraw for ResizeObserver
            canvas.__redraw = function() { _draw(canvas, data); };
        }, {
            loadingText: 'Loading brake precision\u2026',
            emptyCheck: function(d) { return !d || !d.corners || d.corners.length === 0; },
            emptyIcon: '&#x1F3AF;',
            emptyText: 'No brake precision data available.',
        });
    }

    function _showMessage(canvas, msg) {
        var ctx = canvas.getContext('2d');
        canvas.width = canvas.parentElement.clientWidth || 600;
        canvas.height = 300;
        ctx.fillStyle = C.textSecondary || '#8b949e';
        ctx.font = '14px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(msg, canvas.width / 2, canvas.height / 2);
    }

    function _draw(canvas, data) {
        var corners = data.per_corner || [];
        var scatter = data.scatter || {};
        if (corners.length === 0) {
            _showMessage(canvas, 'No brake precision data');
            return;
        }

        var W = canvas.parentElement.clientWidth || 700;
        var rowH = 80;
        var H = Math.max(300, corners.length * rowH + 100);
        var dpr = window.devicePixelRatio || 1;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        var padL = 90, padR = 120, padT = 50, padB = 30;
        var plotW = W - padL - padR;

        // Title
        ctx.fillStyle = C.textPrimary || '#e6edf3';
        ctx.font = 'bold 14px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Brake Precision — Overall: ' + (data.overall_score || 0).toFixed(1) + '%', padL, 24);

        // Colours for dots per corner
        var dotColorsFallback = [
            C.blue || '#4fc3f7', C.green || '#81c784', C.yellow || '#ffb74d',
            C.red || '#e57373', C.purple || '#ba68c8'
        ];

        // Draw each corner
        corners.forEach(function(c, i) {
            var y = padT + i * rowH + rowH / 2 + 10;
            var cid = c.corner_id;

            // Label
            ctx.fillStyle = C.textMuted || '#aaa';
            ctx.font = '12px system-ui, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText('Corner ' + cid, padL - 10, y + 4);

            // Scale range for this corner
            var meanM = c.mean_brake_m || 0;
            var minM = c.min_brake_m || meanM;
            var maxM = c.max_brake_m || meanM;
            var rangeM = c.range_brake_m || 0;
            var scaleRange = Math.max(rangeM * 1.5, 10);
            var scaleMin = meanM - scaleRange / 2;
            var scaleMax = meanM + scaleRange / 2;

            // Scale axis
            ctx.strokeStyle = C.border || '#30363d';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(padL, y);
            ctx.lineTo(padL + plotW, y);
            ctx.stroke();

            // Tick marks for scale
            ctx.fillStyle = C.textSecondary || '#666';
            ctx.font = '9px system-ui, sans-serif';
            ctx.textAlign = 'center';
            var nTicks = 5;
            for (var t = 0; t <= nTicks; t++) {
                var tickVal = scaleMin + (scaleMax - scaleMin) * t / nTicks;
                var tx = padL + (tickVal - scaleMin) / (scaleMax - scaleMin) * plotW;
                ctx.beginPath();
                ctx.moveTo(tx, y - 3);
                ctx.lineTo(tx, y + 3);
                ctx.stroke();
                ctx.fillText(tickVal.toFixed(1) + 'm', tx, y + 15);
            }

            // Draw individual lap dots
            var points = scatter[String(cid)] || [];
            var dotColor = window.Theme && window.Theme.lapColor
                ? window.Theme.lapColor(i)
                : dotColorsFallback[i % dotColorsFallback.length];

            // Vertical jitter for overlapping dots
            points.forEach(function(p, pi) {
                var bm = p.brake_m;
                var px = padL + (bm - scaleMin) / (scaleMax - scaleMin) * plotW;
                // Jitter vertically
                var jitter = (pi % 5 - 2) * 4;
                var py = y - 18 + jitter;

                // Dot
                ctx.globalAlpha = 0.7;
                ctx.fillStyle = dotColor;
                ctx.beginPath();
                ctx.arc(px, py, 3.5, 0, Math.PI * 2);
                ctx.fill();
                ctx.globalAlpha = 1.0;
            });

            // Mean marker (larger, prominent)
            var meanX = padL + (meanM - scaleMin) / (scaleMax - scaleMin) * plotW;
            ctx.fillStyle = C.accent || '#ff6b35';
            ctx.strokeStyle = C.textPrimary || '#e6edf3';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.arc(meanX, y - 18, 6, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();

            // Mean label
            ctx.fillStyle = C.accent || '#ff6b35';
            ctx.font = '10px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Mean: ' + meanM.toFixed(1) + 'm', meanX, y - 28);

            // Std dev range lines
            if (c.std_brake_m > 0) {
                var sdLeft = padL + (meanM - c.std_brake_m - scaleMin) / (scaleMax - scaleMin) * plotW;
                var sdRight = padL + (meanM + c.std_brake_m - scaleMin) / (scaleMax - scaleMin) * plotW;
                ctx.strokeStyle = C.accent || '#ff6b35';
                ctx.lineWidth = 1.5;
                ctx.setLineDash([4, 3]);
                ctx.beginPath();
                ctx.moveTo(sdLeft, y - 24);
                ctx.lineTo(sdLeft, y - 12);
                ctx.moveTo(sdRight, y - 24);
                ctx.lineTo(sdRight, y - 12);
                ctx.moveTo(sdLeft, y - 18);
                ctx.lineTo(sdRight, y - 18);
                ctx.stroke();
                ctx.setLineDash([]);
            }

            // Precision score bar on the right
            var barW = 80;
            var barH = 14;
            var scoreX = padL + plotW + 15;
            ctx.fillStyle = C.bgCard || '#1a1f2e';
            ctx.fillRect(scoreX, y - barH / 2 - 18, barW, barH);

            var scoreW = (c.precision_score / 100) * barW;
            var scoreColor = c.precision_score >= 80 ? (C.green || '#4caf50') :
                             c.precision_score >= 50 ? (C.accent || '#ff6b35') : (C.red || '#ef5350');
            ctx.fillStyle = scoreColor;
            ctx.fillRect(scoreX, y - barH / 2 - 18, scoreW, barH);

            ctx.fillStyle = C.textPrimary || '#e6edf3';
            ctx.font = '11px system-ui, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText((c.precision_score || 0).toFixed(0) + '%', scoreX + barW + 4, y - 14);

            // n samples
            ctx.fillStyle = C.textSecondary || '#666';
            ctx.font = '9px system-ui, sans-serif';
            ctx.fillText('(' + c.n_samples + ' laps)', scoreX, y + 2);
        });
    }
})();
