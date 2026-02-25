/**
 * rival_chart.js — Rival comparison bar chart.
 */
(function() {
    'use strict';
    var C = window.Theme ? window.Theme.colors : {};
    window.RivalChart = { draw: draw };

    function draw(canvasId, data) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        canvas.__redraw = function() { draw(canvasId, data); };
        var rankings = data.rankings || [];
        if (rankings.length === 0) return;

        var W = canvas.parentElement.clientWidth || 700;
        var barH = 40;
        var H = rankings.length * (barH + 10) + 80;
        var dpr = window.devicePixelRatio || 1;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        var ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        var padL = 120, padR = 80;
        var plotW = W - padL - padR;

        // Find max gap
        var maxGap = 0;
        rankings.forEach(function(r) { if (r.gap_to_leader_s > maxGap) maxGap = r.gap_to_leader_s; });
        maxGap = maxGap || 1;

        var colors = [C.green || '#4caf50', C.yellow || '#f5a623', C.blue || '#2196f3', C.red || '#ef5350', C.purple || '#9c27b0'];

        // Title
        ctx.fillStyle = C.textPrimary || '#ddd';
        ctx.font = 'bold 14px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Gap to Leader', padL, 24);

        rankings.forEach(function(r, i) {
            var y = 40 + i * (barH + 10);
            var barW = r.gap_to_leader_s === 0 ? plotW : (r.gap_to_leader_s / maxGap) * plotW;

            // Name
            ctx.fillStyle = '#aaa';
            ctx.font = '12px system-ui, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(r.position + '. ' + r.driver_name, padL - 8, y + barH / 2 + 4);

            // Bar
            ctx.fillStyle = colors[i % colors.length];
            if (r.gap_to_leader_s === 0) {
                ctx.fillRect(padL, y, barW, barH);
            } else {
                ctx.fillRect(padL, y, barW, barH);
            }

            // Label
            ctx.fillStyle = C.textPrimary || '#fff';
            ctx.font = '11px system-ui, sans-serif';
            ctx.textAlign = 'left';
            var label = r.best_lap_time_s != null ? r.best_lap_time_s.toFixed(3) + 's' : '—';
            if (r.gap_to_leader_s > 0) label += ' (+' + r.gap_to_leader_s.toFixed(3) + ')';
            ctx.fillText(label, padL + barW + 8, y + barH / 2 + 4);
        });
    }
})();
