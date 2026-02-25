/**
 * lap_progress.js
 * ---------------
 * Renders lap-over-lap progress: running PB line, pace zones,
 * flow state highlights, rolling CV, and momentum summary.
 *
 * Public API:
 *   window.LapProgress.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var C = window.Theme ? window.Theme.colors : {};

    var ZONE_COLORS = {
        hot:     C.yellow,
        good:    C.green,
        average: C.blue,
        slow:    C.accent,
        cold:    C.red,
    };

    var MOMENTUM_LABELS = {
        building:  "\u25B2 Building",
        fading:    "\u25BC Fading",
        plateaued: "\u25CF Plateaued",
        volatile:  "\u25C6 Volatile",
    };
    var MOMENTUM_COLORS = {
        building:  C.green,
        fading:    C.red,
        plateaued: C.accent,
        volatile:  C.textSecondary,
    };

    function render(el, data) {
        if (!data || data.n_laps < 2) {
            el.innerHTML = '<div class="no-data"><div class="no-data-text">' +
                (data && data.coaching ? esc(data.coaching) : "Not enough data for progress tracking.") + '</div></div>';
            return;
        }

        var html = "";

        // Summary cards
        html += '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:1rem;">';
        html += _card("Laps", data.n_laps, C.textSecondary);
        html += _card("PBs Set", data.pb_count, C.yellow);
        html += _card("Best", (data.final_pb_s || 0).toFixed(3) + "s", C.green);
        html += _card("Improvement", "-" + (data.total_improvement_s || 0).toFixed(3) + "s", C.green);
        html += _card("Momentum",
            esc(MOMENTUM_LABELS[data.session_momentum] || data.session_momentum),
            MOMENTUM_COLORS[data.session_momentum] || C.textSecondary);
        if (data.longest_flow > 0) {
            html += _card("Flow Streak", data.longest_flow + " laps", C.red);
        }
        html += '</div>';

        // Pace zone distribution
        var zones = data.pace_zone_counts || {};
        html += '<div style="display:flex;gap:0.3rem;margin-bottom:1rem;height:20px;border-radius:4px;overflow:hidden;">';
        var total = data.n_laps;
        ["hot", "good", "average", "slow", "cold"].forEach(function (z) {
            var count = zones[z] || 0;
            if (count > 0) {
                var pct = (count / total * 100);
                html += '<div style="flex:' + count + ';background:' + ZONE_COLORS[z] +
                    ';min-width:4px;" title="' + z + ': ' + count + ' laps (' + pct.toFixed(0) + '%)"></div>';
            }
        });
        html += '</div>';

        // Zone legend
        html += '<div style="display:flex;gap:0.8rem;margin-bottom:1rem;font-size:0.7rem;">';
        ["hot", "good", "average", "slow"].forEach(function (z) {
            var count = zones[z] || 0;
            html += '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;' +
                'background:' + ZONE_COLORS[z] + ';margin-right:3px;"></span>' +
                z + ' (' + count + ')</span>';
        });
        html += '</div>';

        // Progress chart
        html += '<div style="margin-bottom:1rem;">';
        html += '<div style="font-size:0.75rem;color:' + C.textSecondary + ';text-transform:uppercase;margin-bottom:0.3rem;">Lap Times & Running PB</div>';
        html += '<canvas id="lap-progress-canvas" width="700" height="240" style="width:100%;max-width:700px;"></canvas>';
        html += '</div>';

        // Flow streaks
        if (data.flow_streaks && data.flow_streaks.length > 0) {
            html += '<div style="font-size:0.75rem;color:' + C.textSecondary + ';text-transform:uppercase;margin-bottom:0.3rem;">Flow Streaks</div>';
            html += '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:1rem;">';
            data.flow_streaks.forEach(function (f) {
                html += '<span style="background:rgba(248,81,73,0.1);color:' + C.red + ';padding:0.2rem 0.6rem;' +
                    'border-radius:10px;font-size:0.72rem;border:1px solid rgba(248,81,73,0.3);">' +
                    'L' + f.start_lap + '-L' + f.end_lap + ' (' + f.length + ' laps, ' +
                    f.improvement_s.toFixed(3) + 's gained)</span>';
            });
            html += '</div>';
        }

        // Coaching
        if (data.coaching) {
            var mCol = MOMENTUM_COLORS[data.session_momentum] || C.blue;
            html += '<div style="background:rgba(88,166,255,0.06);border-left:3px solid ' + mCol + ';' +
                'padding:0.6rem 1rem;border-radius:4px;font-size:0.85rem;color:' + C.textPrimary + ';">' +
                '<strong style="color:' + mCol + ';">Progress Insight:</strong> ' +
                esc(data.coaching) + '</div>';
        }

        el.innerHTML = html;

        setTimeout(function () { _drawChart(data); }, 30);
    }

    function _drawChart(data) {
        var canvas = document.getElementById("lap-progress-canvas");
        if (!canvas) return;
        canvas.__redraw = function() { _drawChart(data); };
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth || 700;
        var H = 240;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + "px";
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var pad = { top: 15, right: 15, bottom: 30, left: 55 };
        var plotW = W - pad.left - pad.right;
        var plotH = H - pad.top - pad.bottom;

        ctx.clearRect(0, 0, W, H);

        var laps = data.laps || [];
        if (laps.length === 0) return;

        // Find time range
        var minT = Infinity, maxT = 0;
        laps.forEach(function (l) {
            if (l.lap_time_s < minT) minT = l.lap_time_s;
            if (l.lap_time_s > maxT) maxT = l.lap_time_s;
        });
        var range = maxT - minT || 1;
        minT -= range * 0.05;
        maxT += range * 0.05;
        range = maxT - minT;

        var n = laps.length;

        function toX(i) { return pad.left + (i / (n - 1)) * plotW; }
        function toY(t) { return pad.top + ((maxT - t) / range) * plotH; }

        // Flow state backgrounds
        laps.forEach(function (l, i) {
            if (l.in_flow_state) {
                var x = toX(i) - plotW / n / 2;
                ctx.fillStyle = "rgba(248, 81, 73, 0.08)";
                ctx.fillRect(x, pad.top, plotW / n, plotH);
            }
        });

        // Lap time dots (coloured by zone)
        laps.forEach(function (l, i) {
            var x = toX(i);
            var y = toY(l.lap_time_s);
            ctx.beginPath();
            ctx.arc(x, y, l.is_pb ? 5 : 3.5, 0, Math.PI * 2);
            ctx.fillStyle = ZONE_COLORS[l.pace_zone] || C.textSecondary;
            ctx.fill();
            if (l.is_pb) {
                ctx.strokeStyle = C.yellow;
                ctx.lineWidth = 2;
                ctx.stroke();
            }
        });

        // Running PB line
        ctx.beginPath();
        ctx.strokeStyle = C.yellow;
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 3]);
        laps.forEach(function (l, i) {
            var x = toX(i);
            var y = toY(l.running_pb_s);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.setLineDash([]);

        // Cumulative mean line
        ctx.beginPath();
        ctx.strokeStyle = C.blue + "80";
        ctx.lineWidth = 1.5;
        laps.forEach(function (l, i) {
            var x = toX(i);
            var y = toY(l.cumulative_mean_s);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Axes
        ctx.strokeStyle = C.textMuted;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top + plotH);
        ctx.lineTo(pad.left + plotW, pad.top + plotH);
        ctx.stroke();

        // Y-axis labels
        ctx.fillStyle = C.textSecondary;
        ctx.font = "10px sans-serif";
        ctx.textAlign = "right";
        for (var t = 0; t <= 4; t++) {
            var val = minT + (range * t / 4);
            var yp = pad.top + plotH - (t / 4) * plotH;
            ctx.fillText(val.toFixed(2), pad.left - 5, yp + 3);
        }

        // Legend
        ctx.textAlign = "left";
        ctx.fillStyle = C.yellow;
        ctx.fillText("Running PB", W - 100, 12);
        ctx.fillStyle = C.blue;
        ctx.fillText("Avg Pace", W - 100, 24);
    }

    function _card(label, value, color) {
        return '<div style="background:var(--card-bg);border-radius:8px;padding:0.3rem 0.6rem;' +
            'text-align:center;min-width:80px;">' +
            '<div style="font-size:0.6rem;color:' + C.textSecondary + ';text-transform:uppercase;">' + label + '</div>' +
            '<div style="font-size:0.85rem;font-weight:700;color:' + color + ';">' + value + '</div>' +
            '</div>';
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/lap-progress", function (data) {
            if (data.error) {
                el.innerHTML = '<div class="no-data"><div class="no-data-text">' + esc(data.error) + '</div></div>';
                return;
            }
            render(el, data);
        }, {
            loadingText: 'Loading lap progress\u2026',
        });
    }

    // Auto-init
    document.addEventListener("DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("lap-progress-container", function () {
                init("lap-progress-container", sid);
            });
        } else if (sid) {
            init("lap-progress-container", sid);
        }
    });

    window.LapProgress = { init: init };
})();
