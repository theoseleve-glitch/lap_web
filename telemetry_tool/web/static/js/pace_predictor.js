/**
 * pace_predictor.js
 * -----------------
 * Canvas 2D visualisation for the Race Pace Predictor.
 * Shows actual laps vs predicted laps, degradation trend, and pace stats.
 *
 * Public API:
 *   window.PacePredictor.init(canvasId, statsId, coachId, sessionId)
 */
(function () {
    "use strict";

    var C = window.Theme ? window.Theme.colors : {};

    var COLORS = {
        actual:      "rgba(54, 162, 235, 1)",
        actualFill:  "rgba(54, 162, 235, 0.12)",
        predicted:   "rgba(255, 159, 64, 1)",
        predFill:    "rgba(255, 159, 64, 0.10)",
        rolling:     "rgba(76, 175, 80, 0.8)",
        grid:        "rgba(160, 160, 160, 0.2)",
        axis:        C.textSecondary || "#888",
        text:        "#ccc",
        good:        C.green || "#4caf50",
        warn:        "#ff9800",
        poor:        C.red || "#e74c3c",
        accent:      "#36a2eb",
    };

    function drawChart(ctx, w, h, data) {
        var pp = data.pace_prediction || {};
        var predicted = pp.predicted_laps || [];
        var lapsCompleted = pp.laps_completed || 0;
        var raceLaps = pp.race_laps || 0;
        var rollingPace = pp.current_rolling_pace_s || 0;

        // We need actual lap times from the fetch. Stored in data._actual_laps externally
        var actualLaps = data._actual_laps || [];

        var ml = 55, mr = 15, mt = 25, mb = 40;
        var pw = w - ml - mr;
        var ph = h - mt - mb;

        ctx.clearRect(0, 0, w, h);

        // Build complete timeline
        var allTimes = actualLaps.concat(predicted);
        var totalLaps = allTimes.length;
        if (totalLaps === 0) {
            ctx.fillStyle = COLORS.text;
            ctx.font = "14px system-ui";
            ctx.textAlign = "center";
            ctx.fillText("No lap data available", w / 2, h / 2);
            return;
        }

        // Y range
        var validTimes = allTimes.filter(function(t) { return t && t > 0; });
        if (validTimes.length === 0) return;
        var yMin = Math.min.apply(null, validTimes) - 0.5;
        var yMax = Math.max.apply(null, validTimes) + 0.5;

        function xPos(lap) { return ml + (lap / Math.max(1, totalLaps)) * pw; }
        function yPos(val) { return mt + ph - ((val - yMin) / (yMax - yMin)) * ph; }

        // Grid
        ctx.strokeStyle = COLORS.grid;
        ctx.lineWidth = 1;
        var yTicks = 5;
        for (var t = 0; t <= yTicks; t++) {
            var yv = yMin + (yMax - yMin) * t / yTicks;
            var yy = yPos(yv);
            ctx.beginPath();
            ctx.moveTo(ml, yy);
            ctx.lineTo(w - mr, yy);
            ctx.stroke();
            ctx.fillStyle = COLORS.axis;
            ctx.font = "10px system-ui";
            ctx.textAlign = "right";
            ctx.fillText(yv.toFixed(2) + "s", ml - 5, yy + 3);
        }

        // X axis
        ctx.textAlign = "center";
        var xStep = Math.max(1, Math.floor(totalLaps / 8));
        for (var xl = 1; xl <= totalLaps; xl += xStep) {
            ctx.fillStyle = COLORS.axis;
            ctx.fillText("L" + xl, xPos(xl), h - mb + 15);
        }

        // Boundary line between actual and predicted
        if (lapsCompleted > 0 && predicted.length > 0) {
            var bx = xPos(lapsCompleted);
            ctx.beginPath();
            ctx.moveTo(bx, mt);
            ctx.lineTo(bx, mt + ph);
            ctx.strokeStyle = "rgba(255,255,255,0.15)";
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 3]);
            ctx.stroke();
            ctx.setLineDash([]);

            ctx.fillStyle = "rgba(255,255,255,0.3)";
            ctx.font = "9px system-ui";
            ctx.fillText("Actual | Predicted", bx, mt + 12);
        }

        // Actual laps fill
        if (actualLaps.length > 1) {
            ctx.beginPath();
            ctx.moveTo(xPos(1), yPos(yMin));
            for (var ai = 0; ai < actualLaps.length; ai++) {
                ctx.lineTo(xPos(ai + 1), yPos(actualLaps[ai]));
            }
            ctx.lineTo(xPos(actualLaps.length), yPos(yMin));
            ctx.closePath();
            ctx.fillStyle = COLORS.actualFill;
            ctx.fill();
        }

        // Actual laps line
        if (actualLaps.length > 0) {
            ctx.beginPath();
            for (var a2 = 0; a2 < actualLaps.length; a2++) {
                var ax = xPos(a2 + 1);
                var ay = yPos(actualLaps[a2]);
                if (a2 === 0) ctx.moveTo(ax, ay);
                else ctx.lineTo(ax, ay);
            }
            ctx.strokeStyle = COLORS.actual;
            ctx.lineWidth = 2.5;
            ctx.stroke();

            // Points
            for (var a3 = 0; a3 < actualLaps.length; a3++) {
                ctx.beginPath();
                ctx.arc(xPos(a3 + 1), yPos(actualLaps[a3]), 3, 0, 2 * Math.PI);
                ctx.fillStyle = COLORS.actual;
                ctx.fill();
            }
        }

        // Predicted laps fill
        if (predicted.length > 1) {
            ctx.beginPath();
            ctx.moveTo(xPos(lapsCompleted + 1), yPos(yMin));
            for (var pi = 0; pi < predicted.length; pi++) {
                ctx.lineTo(xPos(lapsCompleted + pi + 1), yPos(predicted[pi]));
            }
            ctx.lineTo(xPos(lapsCompleted + predicted.length), yPos(yMin));
            ctx.closePath();
            ctx.fillStyle = COLORS.predFill;
            ctx.fill();
        }

        // Predicted laps line (dashed)
        if (predicted.length > 0) {
            ctx.beginPath();
            // Connect from last actual lap
            if (actualLaps.length > 0) {
                ctx.moveTo(xPos(lapsCompleted), yPos(actualLaps[actualLaps.length - 1]));
            }
            for (var p2 = 0; p2 < predicted.length; p2++) {
                ctx.lineTo(xPos(lapsCompleted + p2 + 1), yPos(predicted[p2]));
            }
            ctx.strokeStyle = COLORS.predicted;
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 3]);
            ctx.stroke();
            ctx.setLineDash([]);

            // Predicted points (hollow)
            for (var p3 = 0; p3 < predicted.length; p3++) {
                ctx.beginPath();
                ctx.arc(xPos(lapsCompleted + p3 + 1), yPos(predicted[p3]), 3, 0, 2 * Math.PI);
                ctx.strokeStyle = COLORS.predicted;
                ctx.lineWidth = 1.5;
                ctx.stroke();
            }
        }

        // Rolling pace line
        if (rollingPace > 0 && rollingPace >= yMin && rollingPace <= yMax) {
            ctx.beginPath();
            ctx.moveTo(ml, yPos(rollingPace));
            ctx.lineTo(w - mr, yPos(rollingPace));
            ctx.strokeStyle = COLORS.rolling;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([3, 3]);
            ctx.stroke();
            ctx.setLineDash([]);

            ctx.fillStyle = COLORS.rolling;
            ctx.font = "10px system-ui";
            ctx.textAlign = "left";
            ctx.fillText("Rolling: " + rollingPace.toFixed(3) + "s", ml + 5, yPos(rollingPace) - 5);
        }

        // Title
        ctx.fillStyle = COLORS.text;
        ctx.font = "bold 12px system-ui";
        ctx.textAlign = "left";
        ctx.fillText("Pace Prediction (Actual vs Projected)", ml, mt - 8);
    }

    function renderStats(el, data) {
        var pp = data.pace_prediction || {};
        var pct = data.pace_percentile || 50;
        var pos = data.estimated_position || 0;
        var field = data.field_size || 0;

        var html = "";

        // Race progress
        html += '<div style="display:flex;gap:0.8rem;margin-bottom:0.8rem;">';
        html += _card("Completed", pp.laps_completed + "/" + pp.race_laps, "laps");
        var confColor = pp.confidence > 0.7 ? COLORS.good : pp.confidence > 0.4 ? COLORS.warn : COLORS.poor;
        html += _card("Confidence", (pp.confidence * 100).toFixed(0) + "%", "", confColor);
        html += '</div>';

        // Pace stats
        html += '<div style="display:flex;gap:0.8rem;margin-bottom:0.8rem;">';
        html += _card("Rolling Pace", _fmtLap(pp.current_rolling_pace_s), "");
        html += _card("Degradation", "+" + (pp.degradation_rate_s * 1000).toFixed(0) + "ms/lap", "",
                       pp.degradation_rate_s > 0.1 ? COLORS.poor :
                       pp.degradation_rate_s > 0.03 ? COLORS.warn : COLORS.good);
        html += '</div>';

        // Predicted finish
        if (pp.predicted_total_s > 0) {
            html += '<div style="background:var(--card-bg);border-radius:8px;padding:0.6rem 1rem;margin-bottom:0.8rem;">';
            html += '<div style="font-size:0.7rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">Predicted Race Time</div>';
            html += '<div style="font-size:1.2rem;font-weight:700;color:var(--text-primary);">' +
                    _fmtRaceTime(pp.predicted_total_s) + '</div>';
            if (pp.remaining_s > 0) {
                html += '<div style="font-size:0.8rem;color:' + (C.textSecondary || "#aaa") + ';">Remaining: ' +
                        _fmtRaceTime(pp.remaining_s) + '</div>';
            }
            html += '</div>';
        }

        // Pace percentile
        if (field > 0) {
            var pctColor = pct >= 75 ? COLORS.good : pct >= 40 ? COLORS.warn : COLORS.poor;
            html += '<div style="background:var(--card-bg);border-radius:8px;padding:0.6rem 1rem;margin-bottom:0.8rem;">';
            html += '<div style="font-size:0.7rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">Historical Ranking</div>';
            html += '<div style="display:flex;align-items:baseline;gap:0.5rem;">';
            html += '<span style="font-size:1.2rem;font-weight:700;color:' + pctColor + ';">' +
                    pct.toFixed(0) + 'th pct</span>';
            if (pos > 0) {
                html += '<span style="font-size:0.85rem;color:' + (C.textSecondary || "#aaa") + ';">Est. P' + pos + '/' + field + '</span>';
            }
            html += '</div>';

            // Percentile bar
            html += '<div style="background:rgba(255,255,255,0.07);border-radius:4px;height:8px;margin-top:0.3rem;">';
            html += '<div style="width:' + pct + '%;height:100%;background:' + pctColor + ';border-radius:4px;"></div>';
            html += '</div>';
            html += '</div>';
        }

        el.innerHTML = html;
    }

    function _card(title, value, subtitle, color) {
        color = color || COLORS.accent;
        var html = '<div style="background:var(--card-bg);border-radius:8px;padding:0.5rem 0.8rem;flex:1;text-align:center;">';
        html += '<div style="font-size:0.65rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">' + title + '</div>';
        html += '<div style="font-size:1.1rem;font-weight:700;color:' + color + ';">' + value + '</div>';
        if (subtitle) {
            html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#888") + ';">' + subtitle + '</div>';
        }
        html += '</div>';
        return html;
    }

    function _fmtLap(s) {
        if (!s || s <= 0) return "--";
        return s.toFixed(3) + "s";
    }

    function _fmtRaceTime(s) {
        if (!s || s <= 0) return "--";
        var m = Math.floor(s / 60);
        var sec = (s % 60).toFixed(1);
        return m + ":" + (sec < 10 ? "0" : "") + sec;
    }

    function renderCoaching(el, data) {
        if (!data.coaching) { el.innerHTML = ""; return; }
        el.innerHTML = '<div style="background:rgba(76,175,80,0.08);border-left:3px solid ' + (C.green || "#4caf50") + ';' +
            'padding:0.7rem 1rem;border-radius:4px;font-size:0.9rem;color:var(--text-primary);line-height:1.5;">' +
            '<strong style="color:' + (C.green || "#4caf50") + ';">Pace Insight:</strong> ' +
            esc(data.coaching) + '</div>';
    }

    function init(canvasId, statsId, coachId, sessionId) {
        var canvas = document.getElementById(canvasId);
        var statsEl = document.getElementById(statsId);
        var coachEl = document.getElementById(coachId);
        if (!canvas || !statsEl) return;

        // Show loading state (FetchHelper.load only handles single URL fetches)
        statsEl.innerHTML = '<div class="no-data p-lg"><div class="spinner-inline spinner-accent"></div><div class="text-secondary text-sm">Loading predictions...</div></div>';

        // We need the actual lap times for the chart, so fetch them separately
        var lapTimesPromise = FetchHelper.fetch("/api/session/" + encodeURIComponent(sessionId) + "/lap_times");
        var predictionPromise = FetchHelper.fetch("/api/session/" + encodeURIComponent(sessionId) + "/pace-prediction");

        Promise.all([lapTimesPromise, predictionPromise])
            .then(function(results) {
                var lapData = results[0];
                var predData = results[1];

                if (predData.error) {
                    statsEl.innerHTML = '<div class="no-data"><div class="no-data-text">' + esc(predData.error) + '</div></div>';
                    return;
                }

                // Extract actual valid lap times
                var laps = (lapData.laps || []).filter(function(l) {
                    return l.is_valid !== false && l.lap_time_s;
                }).map(function(l) { return l.lap_time_s; });

                predData._actual_laps = laps;
                _lastCanvasId = canvasId;
                _lastData = predData;

                var ctx = canvas.getContext("2d");
                var dpr = window.devicePixelRatio || 1;
                var cw = canvas.clientWidth || 560;
                var ch = canvas.clientHeight || 280;
                canvas.width = cw * dpr;
                canvas.height = ch * dpr;
                ctx.scale(dpr, dpr);

                drawChart(ctx, cw, ch, predData);
                canvas.__redraw = function() {
                    var rdpr = window.devicePixelRatio || 1;
                    var rcw = canvas.parentElement.clientWidth || 560;
                    var rch = canvas.clientHeight || 280;
                    canvas.width = rcw * rdpr;
                    canvas.height = rch * rdpr;
                    canvas.style.width = rcw + 'px';
                    var rctx = canvas.getContext('2d');
                    rctx.scale(rdpr, rdpr);
                    drawChart(rctx, rcw, rch, predData);
                };
                renderStats(statsEl, predData);
                if (coachEl) renderCoaching(coachEl, predData);
            })
            .catch(function(err) {
                console.error("Pace predictor error:", err);
                statsEl.innerHTML = '<div class="no-data"><div class="no-data-text">Failed to load pace prediction.</div></div>';
                if (coachEl) coachEl.innerHTML = '';
                var pCtx = canvas.getContext('2d');
                pCtx.clearRect(0, 0, canvas.width, canvas.height);
            });
    }

    // Auto-init
    document.addEventListener("DOMContentLoaded", function() {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("pace-predictor-container", function () {
                init("pace-predictor-chart", "pace-predictor-stats", "pace-predictor-coaching", sid);
            });
        } else if (sid) {
            init("pace-predictor-chart", "pace-predictor-stats", "pace-predictor-coaching", sid);
        }
    });

    // Store last data for responsive resize
    var _lastCanvasId = null, _lastData = null;

    // Responsive resize support
    document.addEventListener("DOMContentLoaded", function() {
        var ppCanvas = document.getElementById('pace-predictor-chart');
        if (ppCanvas) {
            ppCanvas.addEventListener('chart:resize', function() {
                if (_lastData && _lastCanvasId) {
                    var c = document.getElementById(_lastCanvasId);
                    if (!c) return;
                    var ctx = c.getContext('2d');
                    var dpr = window.devicePixelRatio || 1;
                    var cw = c.parentElement.clientWidth || 560;
                    var ch = c.clientHeight || 280;
                    c.width = cw * dpr;
                    c.height = ch * dpr;
                    c.style.width = cw + 'px';
                    ctx.scale(dpr, dpr);
                    drawChart(ctx, cw, ch, _lastData);
                }
            });
        }
    });

    window.PacePredictor = { init: init };
})();
