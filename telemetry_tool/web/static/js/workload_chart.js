/**
 * workload_chart.js
 * -----------------
 * Renders driver workload estimation: complexity trend, physical vs
 * cognitive balance, fatigue risk timeline, and event counts.
 *
 * Public API:
 *   window.WorkloadChart.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var C = window.Theme ? window.Theme.colors : {};

    var COLORS = {
        physical:  C.red || "#e74c3c",
        cognitive: "#36a2eb",
        complexity:"#ff9800",
        low:       C.green || "#4caf50",
        moderate:  "#ff9800",
        high:      C.red || "#e74c3c",
    };

    function render(el, data) {
        if (!data || data.n_laps < 2) {
            el.innerHTML = '<div class="no-data"><div class="no-data-text">' +
                (data && data.coaching ? esc(data.coaching) : "Not enough data for workload estimation.") + '</div></div>';
            return;
        }

        var html = "";

        // Summary cards
        html += '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:1rem;">';
        html += _card("Laps", data.n_laps, "var(--text-secondary)");
        html += _card("Avg Complexity", (data.mean_complexity || 0).toFixed(1) + "/100", COLORS.complexity);
        html += _card("Peak", (data.peak_complexity || 0).toFixed(1) + " (L" + (data.peak_complexity_lap || '?') + ")", COLORS.complexity);
        html += _card("Physical", (data.mean_physical || 0).toFixed(1) + "/100", COLORS.physical);
        html += _card("Cognitive", (data.mean_cognitive || 0).toFixed(1) + "/100", COLORS.cognitive);
        html += _card("Trend", esc(data.workload_trend), "var(--text-secondary)");
        html += _card("Brake Events", data.total_brake_events, COLORS.physical);
        html += _card("Accel Events", data.total_accel_events, COLORS.cognitive);
        html += '</div>';

        // Workload chart
        html += '<div style="margin-bottom:1rem;">';
        html += '<div style="font-size:0.75rem;color:var(--text-secondary);text-transform:uppercase;margin-bottom:0.3rem;">Workload per Lap</div>';
        html += '<canvas id="workload-canvas" style="width:100%;"></canvas>';
        html += '</div>';

        // Fatigue risk timeline
        html += '<div style="margin-bottom:1rem;">';
        html += '<div style="font-size:0.75rem;color:var(--text-secondary);text-transform:uppercase;margin-bottom:0.3rem;">Fatigue Risk</div>';
        html += '<div style="display:flex;gap:2px;height:20px;border-radius:4px;overflow:hidden;">';
        (data.lap_workloads || []).forEach(function (w) {
            var col = COLORS[w.fatigue_risk] || COLORS.low;
            html += '<div style="flex:1;background:' + col + ';" title="L' + w.lap_number +
                ': ' + w.fatigue_risk + ' (' + w.complexity_score.toFixed(0) + ')"></div>';
        });
        html += '</div>';
        html += '<div style="display:flex;gap:0.8rem;margin-top:0.3rem;font-size:0.65rem;">';
        html += '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + COLORS.low + ';margin-right:2px;"></span>Low</span>';
        html += '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + COLORS.moderate + ';margin-right:2px;"></span>Moderate</span>';
        html += '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + COLORS.high + ';margin-right:2px;"></span>High</span>';
        html += '</div>';
        html += '</div>';

        if (data.fatigue_onset_lap > 0) {
            html += '<div style="background:rgba(231,76,60,0.08);border-left:3px solid var(--red);' +
                'padding:0.5rem 1rem;border-radius:4px;font-size:0.8rem;color:var(--text-primary);margin-bottom:1rem;">' +
                '<strong style="color:var(--red);">Fatigue Alert:</strong> High fatigue risk detected from Lap ' +
                data.fatigue_onset_lap + '</div>';
        }

        // Coaching
        if (data.coaching) {
            html += '<div style="background:rgba(54,162,235,0.06);border-left:3px solid var(--blue);' +
                'padding:0.6rem 1rem;border-radius:4px;font-size:0.85rem;color:var(--text-primary);">' +
                '<strong style="color:var(--blue);">Workload Insight:</strong> ' +
                esc(data.coaching) + '</div>';
        }

        el.innerHTML = html;

        setTimeout(function () { _drawChart(data); }, 30);
    }

    function _drawChart(data) {
        var canvas = document.getElementById("workload-canvas");
        if (!canvas) return;
        canvas.__redraw = function() { _drawChart(data); };
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth || 700;
        var H = 220;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + "px";
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var pad = { top: 15, right: 15, bottom: 30, left: 40 };
        var plotW = W - pad.left - pad.right;
        var plotH = H - pad.top - pad.bottom;

        ctx.clearRect(0, 0, W, H);

        var laps = data.lap_workloads || [];
        if (laps.length === 0) return;

        var n = laps.length;
        var maxScore = 100;

        function toX(i) { return pad.left + (i / (n - 1 || 1)) * plotW; }
        function toY(v) { return pad.top + plotH - (v / maxScore) * plotH; }

        // Physical load bars (stacked)
        var barW = plotW / n;
        laps.forEach(function (l, i) {
            var x = pad.left + i * barW;
            // Physical bar
            var phH = (l.physical_load / maxScore) * plotH;
            ctx.fillStyle = COLORS.physical + "60";
            ctx.fillRect(x + 1, pad.top + plotH - phH, barW / 2 - 1, phH);
            // Cognitive bar
            var cgH = (l.cognitive_load / maxScore) * plotH;
            ctx.fillStyle = COLORS.cognitive + "60";
            ctx.fillRect(x + barW / 2, pad.top + plotH - cgH, barW / 2 - 1, cgH);
        });

        // Complexity line
        ctx.beginPath();
        ctx.strokeStyle = COLORS.complexity;
        ctx.lineWidth = 2;
        laps.forEach(function (l, i) {
            var x = toX(i);
            var y = toY(l.complexity_score);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Axes
        ctx.strokeStyle = "#555";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top + plotH);
        ctx.lineTo(pad.left + plotW, pad.top + plotH);
        ctx.stroke();

        // Legend
        ctx.font = "10px sans-serif";
        ctx.textAlign = "right";
        ctx.fillStyle = COLORS.physical;
        ctx.fillText("Physical", W - 10, 12);
        ctx.fillStyle = COLORS.cognitive;
        ctx.fillText("Cognitive", W - 10, 24);
        ctx.fillStyle = COLORS.complexity;
        ctx.fillText("Complexity", W - 10, 36);
    }

    function _card(label, value, color) {
        return '<div style="background:var(--card-bg);border-radius:8px;padding:0.3rem 0.6rem;' +
            'text-align:center;min-width:75px;">' +
            '<div style="font-size:0.6rem;color:var(--text-secondary);text-transform:uppercase;">' + label + '</div>' +
            '<div style="font-size:0.85rem;font-weight:700;color:' + color + ';">' + value + '</div>' +
            '</div>';
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/workload", function (data) {
            render(el, data);
        }, {
            loadingText: 'Loading workload analysis\u2026',
        });
    }

    // Auto-init
    document.addEventListener("DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("workload-container", function () {
                init("workload-container", sid);
            });
        } else if (sid) {
            init("workload-container", sid);
        }
    });

    window.WorkloadChart = { init: init };
})();
