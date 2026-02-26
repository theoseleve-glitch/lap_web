/**
 * pit_window_chart.js
 * -------------------
 * Canvas 2D visualisation for the Optimal Pit Window Calculator.
 * Shows degradation curve, crossover point, pit window zone, and strategy cards.
 *
 * Public API:
 *   window.PitWindowChart.init(canvasId, statsId, coachId, sessionId)
 */
(function () {
    "use strict";

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    var COLORS = {
        bg:        "rgba(30, 30, 30, 1)",
        grid:      "rgba(160, 160, 160, 0.2)",
        axis:      C.textSecondary || "#888",
        deg:       "rgba(255, 99, 132, 1)",
        degFill:   "rgba(255, 99, 132, 0.15)",
        pitLine:   "rgba(54, 162, 235, 1)",
        window:    "rgba(76, 175, 80, 0.20)",
        windowBdr: "rgba(76, 175, 80, 0.7)",
        crossover: "#ff9800",
        text:      "#ccc",
        good:      C.green || "#4caf50",
        warn:      "#ff9800",
        poor:      C.red || "#e74c3c",
        accent:    "#36a2eb",
    };

    function drawChart(ctx, w, h, data) {
        var model = data.degradation_model || {};
        var raceLaps = data.race_laps || 30;
        var pitLoss = data.pit_loss_s || 25;
        var crossover = data.crossover_lap || 0;
        var optWindow = data.optimal_window || [0, 0];

        // Margins
        var ml = 55, mr = 20, mt = 25, mb = 40;
        var pw = w - ml - mr;
        var ph = h - mt - mb;

        ctx.clearRect(0, 0, w, h);

        // Build cumulative degradation curve
        var maxLaps = Math.min(raceLaps, 60);
        var cumLoss = [];
        var maxLoss = 0;
        for (var i = 1; i <= maxLaps; i++) {
            var loss = 0;
            if (model.model_type !== "flat" && model.base_deg_s > 0) {
                // Sum degradation lap by lap
                for (var j = 1; j <= i; j++) {
                    loss += model.base_deg_s * (j - 1);
                }
            }
            cumLoss.push(loss);
            if (loss > maxLoss) maxLoss = loss;
        }

        // Y scale: max of maxLoss or pitLoss * 1.5
        var yMax = Math.max(maxLoss * 1.2, pitLoss * 1.5, 10);

        function xPos(lap) { return ml + (lap - 1) / Math.max(1, maxLaps - 1) * pw; }
        function yPos(val) { return mt + ph - (val / yMax) * ph; }

        // Grid
        ctx.strokeStyle = COLORS.grid;
        ctx.lineWidth = 1;
        var yTicks = 5;
        for (var t = 0; t <= yTicks; t++) {
            var yv = yMax * t / yTicks;
            var yy = yPos(yv);
            ctx.beginPath();
            ctx.moveTo(ml, yy);
            ctx.lineTo(w - mr, yy);
            ctx.stroke();
            ctx.fillStyle = COLORS.axis;
            ctx.font = "10px system-ui";
            ctx.textAlign = "right";
            ctx.fillText(yv.toFixed(1) + "s", ml - 5, yy + 3);
        }

        // X axis labels
        ctx.textAlign = "center";
        var xStep = Math.max(1, Math.floor(maxLaps / 8));
        for (var xl = 1; xl <= maxLaps; xl += xStep) {
            ctx.fillStyle = COLORS.axis;
            ctx.fillText("L" + xl, xPos(xl), h - mb + 15);
        }

        // Pit window zone
        if (optWindow[0] > 0 && optWindow[1] > 0) {
            var wx1 = xPos(optWindow[0]);
            var wx2 = xPos(optWindow[1]);
            ctx.fillStyle = COLORS.window;
            ctx.fillRect(wx1, mt, wx2 - wx1, ph);
            ctx.strokeStyle = COLORS.windowBdr;
            ctx.lineWidth = 2;
            ctx.setLineDash([5, 3]);
            ctx.strokeRect(wx1, mt, wx2 - wx1, ph);
            ctx.setLineDash([]);

            // Label
            ctx.fillStyle = COLORS.good;
            ctx.font = "bold 11px system-ui";
            ctx.textAlign = "center";
            ctx.fillText("PIT WINDOW", (wx1 + wx2) / 2, mt + 15);
            ctx.font = "10px system-ui";
            ctx.fillText("L" + optWindow[0] + " - L" + optWindow[1], (wx1 + wx2) / 2, mt + 28);
        }

        // Pit loss horizontal line
        if (pitLoss < yMax) {
            var pitY = yPos(pitLoss);
            ctx.beginPath();
            ctx.moveTo(ml, pitY);
            ctx.lineTo(w - mr, pitY);
            ctx.strokeStyle = COLORS.pitLine;
            ctx.lineWidth = 2;
            ctx.setLineDash([8, 4]);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = COLORS.pitLine;
            ctx.font = "bold 10px system-ui";
            ctx.textAlign = "left";
            ctx.fillText("Pit Loss: " + pitLoss.toFixed(0) + "s", ml + 5, pitY - 5);
        }

        // Degradation curve
        if (cumLoss.length > 1) {
            // Fill under curve
            ctx.beginPath();
            ctx.moveTo(xPos(1), yPos(0));
            for (var ci = 0; ci < cumLoss.length; ci++) {
                ctx.lineTo(xPos(ci + 1), yPos(cumLoss[ci]));
            }
            ctx.lineTo(xPos(cumLoss.length), yPos(0));
            ctx.closePath();
            ctx.fillStyle = COLORS.degFill;
            ctx.fill();

            // Line
            ctx.beginPath();
            for (var ci2 = 0; ci2 < cumLoss.length; ci2++) {
                var px = xPos(ci2 + 1);
                var py = yPos(cumLoss[ci2]);
                if (ci2 === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
            }
            ctx.strokeStyle = COLORS.deg;
            ctx.lineWidth = 2.5;
            ctx.stroke();
        }

        // Crossover point
        if (crossover > 0 && crossover <= maxLaps) {
            var cx = xPos(crossover);
            var cy = yPos(cumLoss[crossover - 1] || 0);
            ctx.beginPath();
            ctx.arc(cx, cy, 6, 0, 2 * Math.PI);
            ctx.fillStyle = COLORS.crossover;
            ctx.fill();
            ctx.strokeStyle = C.textPrimary || "#fff";
            ctx.lineWidth = 2;
            ctx.stroke();

            ctx.fillStyle = COLORS.crossover;
            ctx.font = "bold 11px system-ui";
            ctx.textAlign = "center";
            ctx.fillText("Crossover L" + crossover, cx, cy - 12);
        }

        // Title
        ctx.fillStyle = COLORS.text;
        ctx.font = "bold 12px system-ui";
        ctx.textAlign = "left";
        ctx.fillText("Cumulative Degradation vs Pit Penalty", ml, mt - 8);

        // Y axis label
        ctx.save();
        ctx.translate(14, mt + ph / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = COLORS.axis;
        ctx.font = "10px system-ui";
        ctx.textAlign = "center";
        ctx.fillText("Cumulative Time Loss (s)", 0, 0);
        ctx.restore();
    }

    function renderStats(el, data) {
        var model = data.degradation_model || {};
        var best = data.best_strategy;
        var strategies = data.strategies || [];

        var html = "";

        // Degradation model card
        html += '<div style="background:var(--card-bg);border-radius:8px;padding:0.7rem 1rem;margin-bottom:0.8rem;">';
        html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">Degradation Model</div>';
        html += '<div style="font-size:1.1rem;font-weight:600;color:var(--text-primary);margin-top:0.2rem;">';
        html += model.model_type === "flat" ? "Flat (no deg)" :
                model.model_type === "exponential" ? "Exponential (cliff)" : "Linear";
        html += '</div>';
        if (model.base_deg_s > 0) {
            html += '<div style="font-size:0.85rem;color:' + (C.textSecondary || "#aaa") + ';margin-top:0.2rem;">';
            html += (model.base_deg_s * 1000).toFixed(0) + 'ms/lap deg';
            html += ' | R&sup2; ' + (model.r_squared * 100).toFixed(0) + '%';
            html += '</div>';
        }
        html += '</div>';

        // Best strategy card
        if (best) {
            var stratColor = best.n_stops === 0 ? COLORS.good :
                             best.n_stops === 1 ? COLORS.accent : COLORS.warn;
            html += '<div style="background:var(--card-bg);border-radius:8px;padding:0.7rem 1rem;margin-bottom:0.8rem;border-left:3px solid ' + stratColor + ';">';
            html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">Best Strategy</div>';
            html += '<div style="font-size:1.3rem;font-weight:700;color:' + stratColor + ';margin-top:0.2rem;">';
            html += best.n_stops + '-STOP</div>';
            if (best.pit_laps && best.pit_laps.length > 0) {
                html += '<div style="font-size:0.85rem;color:var(--text-secondary);">Pit on: ';
                html += best.pit_laps.map(function(l) { return 'L' + l; }).join(', ');
                html += '</div>';
            }
            if (best.advantage_vs_no_stop_s > 0) {
                html += '<div style="font-size:0.85rem;color:' + COLORS.good + ';">Saves ';
                html += best.advantage_vs_no_stop_s.toFixed(1) + 's vs no-stop</div>';
            }
            html += '</div>';
        }

        // All strategies
        if (strategies.length > 1) {
            html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;margin-bottom:0.3rem;">All Strategies</div>';
            strategies.forEach(function (s) {
                var isBest = best && s.n_stops === best.n_stops;
                var bg = isBest ? 'rgba(54,162,235,0.1)' : 'transparent';
                html += '<div style="display:flex;justify-content:space-between;font-size:0.8rem;padding:0.2rem 0.4rem;background:' + bg + ';border-radius:4px;">';
                html += '<span style="color:var(--text-secondary);">' + s.n_stops + '-stop</span>';
                html += '<span style="color:' + (C.textSecondary || "#aaa") + ';">stints: ' + s.stint_lengths.join('+') + '</span>';
                html += '<span style="color:' + (C.textSecondary || "#aaa") + ';">' + _fmtTime(s.total_race_time_s) + '</span>';
                html += '</div>';
            });
        }

        el.innerHTML = html;
    }

    function _fmtTime(s) {
        if (!s || s <= 0) return "--";
        var min = Math.floor(s / 60);
        var sec = (s % 60).toFixed(1);
        return min + ":" + (sec < 10 ? "0" : "") + sec;
    }

    function renderCoaching(el, data) {
        if (!data.coaching) {
            el.innerHTML = "";
            return;
        }
        el.innerHTML = '<div style="background:rgba(54,162,235,0.08);border-left:3px solid var(--blue);' +
            'padding:0.7rem 1rem;border-radius:4px;font-size:0.9rem;color:var(--text-primary);line-height:1.5;">' +
            '<strong style="color:var(--blue);">Strategy Insight:</strong> ' +
            esc(data.coaching) + '</div>';
    }

    function init(canvasId, statsId, coachId, sessionId) {
        var canvas = document.getElementById(canvasId);
        var statsEl = document.getElementById(statsId);
        var coachEl = document.getElementById(coachId);
        if (!canvas || !statsEl) return;

        FetchHelper.load(statsEl, "/api/session/" + encodeURIComponent(sessionId) + "/pit-window", function(data) {
            var ctx = canvas.getContext("2d");
            var dpr = window.devicePixelRatio || 1;
            var cw = canvas.clientWidth || 560;
            var ch = canvas.clientHeight || 280;
            canvas.width = cw * dpr;
            canvas.height = ch * dpr;
            ctx.scale(dpr, dpr);

            drawChart(ctx, cw, ch, data);
            renderStats(statsEl, data);
            if (coachEl) renderCoaching(coachEl, data);

            // Register __redraw for ResizeObserver
            canvas.__redraw = function() {
                var dpr2 = window.devicePixelRatio || 1;
                var cw2 = canvas.clientWidth || 560;
                var ch2 = canvas.clientHeight || 280;
                canvas.width = cw2 * dpr2;
                canvas.height = ch2 * dpr2;
                var ctx2 = canvas.getContext("2d");
                ctx2.scale(dpr2, dpr2);
                drawChart(ctx2, cw2, ch2, data);
            };
        }, {
            loadingText: 'Loading pit window\u2026',
        });
    }

    // Auto-init
    _lc.addListener(document, "DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("pit-window-container", function () {
                init("pit-window-chart", "pit-window-stats", "pit-window-coaching", sid);
            });
        } else if (sid) {
            init("pit-window-chart", "pit-window-stats", "pit-window-coaching", sid);
        }
    });

    window.PitWindowChart = { init: init };

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('pit_window_chart', {
        init: function () {},
        destroy: destroy
    });
})();
