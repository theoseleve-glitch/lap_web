/**
 * pace_simulator.js
 * -----------------
 * Canvas 2D visualisation for the Race Pace Simulator.
 * Renders a parameter form, POSTs to /api/session/<sid>/simulate-race,
 * then draws predicted lap times, pit markers, stats sidebar, and coaching.
 *
 * Public API:
 *   window.PaceSimulator.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    var COLORS = {
        line:       "rgba(54, 162, 235, 1)",
        lineFill:   "rgba(54, 162, 235, 0.12)",
        pit:        "rgba(255, 159, 64, 1)",
        grid:       "rgba(160, 160, 160, 0.2)",
        axis:       C.textSecondary || "#888",
        text:       "#ccc",
        good:       C.green || "#4caf50",
        warn:       "#ff9800",
        poor:       C.red || "#e74c3c",
        accent:     "#36a2eb",
    };

    /* ── Helpers ──────────────────────────────── */

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

    function _card(title, value, subtitle, color) {
        color = color || COLORS.accent;
        var html = '<div style="background:var(--bg-secondary);border-radius:8px;padding:0.5rem 0.8rem;flex:1;text-align:center;">';
        html += '<div style="font-size:0.65rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">' + title + '</div>';
        html += '<div style="font-size:1.1rem;font-weight:700;color:' + color + ';">' + value + '</div>';
        if (subtitle) {
            html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#888") + ';">' + subtitle + '</div>';
        }
        html += '</div>';
        return html;
    }

    /* ── Form rendering ──────────────────────── */

    function buildForm(defaults) {
        var d = defaults || {};
        var html = '<div class="sim-form-grid">';

        // Race Scenario group
        html += '<div class="sim-form-group">';
        html += '<div class="sim-group-title">Race Scenario</div>';
        html += _field("race_laps",        "Race Laps",             d.race_laps        || 25,   1, "1");
        html += _field("pit_stop_loss_s",  "Pit Loss (s)",          d.pit_stop_loss_s  || 30.0, 0.1, "0.1");
        html += _field("num_pit_stops",    "Pit Stops",             d.num_pit_stops    || 1,    0, "1");
        html += _field("tire_deg_rate_s",  "Tyre Deg (s/lap)",      d.tire_deg_rate_s  || 0.05, 0, "0.01");
        html += _field("fuel_effect_s",    "Fuel Effect (s/lap)",   d.fuel_effect_s    || 0.00, 0, "0.01");
        html += '</div>';

        // Driver Capability group
        html += '<div class="sim-form-group">';
        html += '<div class="sim-group-title">Driver Capability</div>';
        html += _field("target_lap_time_s",   "Target Lap (s)",     d.target_lap_time_s   || 62.0,  0, "0.1");
        html += _field("consistency_cv_pct",  "Consistency CV%",     d.consistency_cv_pct  || 1.5,   0, "0.1");
        html += _field("fatigue_onset_lap",   "Fatigue Onset Lap",   d.fatigue_onset_lap   || 18,    1, "1");
        html += _field("stint_length",        "Stint Length",        d.stint_length        || 12,    1, "1");
        html += _field("traffic_penalty_s",   "Traffic Penalty (s)", d.traffic_penalty_s   || 0.3,   0, "0.1");
        html += '</div>';

        html += '</div>'; // .sim-form-grid

        html += '<button id="sim-run-btn" class="btn btn-primary" style="margin-top:0.5rem;">';
        html += '<span class="sim-btn-icon">&#9654;</span> Simulate</button>';

        html += '<div id="sim-result-area" style="margin-top:1rem;"></div>';
        return html;
    }

    function _field(name, label, value, min, step) {
        var html = '<div class="sim-field">';
        html += '<label for="sim-' + name + '">' + label + '</label>';
        html += '<input type="number" id="sim-' + name + '" class="sim-input" ';
        html += 'value="' + value + '" ';
        if (min !== null && min !== undefined) html += 'min="' + min + '" ';
        if (step) html += 'step="' + step + '" ';
        html += '/>';
        html += '</div>';
        return html;
    }

    /* ── Collect form values ─────────────────── */

    function _intVal(id, fallback) {
        var v = parseInt(document.getElementById(id).value, 10);
        return isNaN(v) ? fallback : v;
    }
    function _floatVal(id, fallback) {
        var v = parseFloat(document.getElementById(id).value);
        return isNaN(v) ? fallback : v;
    }

    function collectParams() {
        return {
            race_laps:          _intVal("sim-race_laps", 25),
            pit_stop_loss_s:    _floatVal("sim-pit_stop_loss_s", 30.0),
            num_pit_stops:      _intVal("sim-num_pit_stops", 1),
            tire_deg_rate_s:    _floatVal("sim-tire_deg_rate_s", 0.05),
            fuel_effect_s:      _floatVal("sim-fuel_effect_s", 0.0),
            target_lap_time_s:  _floatVal("sim-target_lap_time_s", 62.0),
            consistency_cv_pct: _floatVal("sim-consistency_cv_pct", 1.5),
            fatigue_onset_lap:  _intVal("sim-fatigue_onset_lap", 18),
            stint_length:       _intVal("sim-stint_length", 12),
            traffic_penalty_s:  _floatVal("sim-traffic_penalty_s", 0.3),
        };
    }

    /* ── Canvas chart ────────────────────────── */

    function drawChart(ctx, w, h, result) {
        var laps = result.predicted_laps || [];
        var pitLaps = result.pit_stop_laps || [];

        var ml = 55, mr = 15, mt = 25, mb = 40;
        var pw = w - ml - mr;
        var ph = h - mt - mb;

        ctx.clearRect(0, 0, w, h);

        if (laps.length === 0) {
            ctx.fillStyle = COLORS.text;
            ctx.font = "14px system-ui";
            ctx.textAlign = "center";
            ctx.fillText("No simulation data", w / 2, h / 2);
            return;
        }

        var totalLaps = laps.length;

        // Y range
        var validTimes = laps.filter(function (t) { return t && t > 0; });
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

        // X axis labels
        ctx.textAlign = "center";
        var xStep = Math.max(1, Math.floor(totalLaps / 8));
        for (var xl = 1; xl <= totalLaps; xl += xStep) {
            ctx.fillStyle = COLORS.axis;
            ctx.fillText("L" + xl, xPos(xl), h - mb + 15);
        }

        // Filled area under line
        if (laps.length > 1) {
            ctx.beginPath();
            ctx.moveTo(xPos(1), yPos(yMin));
            for (var fi = 0; fi < laps.length; fi++) {
                ctx.lineTo(xPos(fi + 1), yPos(laps[fi]));
            }
            ctx.lineTo(xPos(laps.length), yPos(yMin));
            ctx.closePath();
            ctx.fillStyle = COLORS.lineFill;
            ctx.fill();
        }

        // Lap time line
        ctx.beginPath();
        for (var li = 0; li < laps.length; li++) {
            var lx = xPos(li + 1);
            var ly = yPos(laps[li]);
            if (li === 0) ctx.moveTo(lx, ly);
            else ctx.lineTo(lx, ly);
        }
        ctx.strokeStyle = COLORS.line;
        ctx.lineWidth = 2.5;
        ctx.stroke();

        // Data points
        for (var di = 0; di < laps.length; di++) {
            var isPit = pitLaps.indexOf(di + 1) !== -1;
            ctx.beginPath();
            ctx.arc(xPos(di + 1), yPos(laps[di]), isPit ? 5 : 3, 0, 2 * Math.PI);
            ctx.fillStyle = isPit ? COLORS.pit : COLORS.line;
            ctx.fill();

            if (isPit) {
                ctx.fillStyle = COLORS.pit;
                ctx.font = "bold 9px system-ui";
                ctx.textAlign = "center";
                ctx.fillText("PIT", xPos(di + 1), yPos(laps[di]) - 8);
            }
        }

        // Title
        ctx.fillStyle = COLORS.text;
        ctx.font = "bold 12px system-ui";
        ctx.textAlign = "left";
        ctx.fillText("Simulated Race Lap Times", ml, mt - 8);
    }

    /* ── Stats sidebar ───────────────────────── */

    function renderStats(el, result) {
        var html = "";

        // Top row: race laps + confidence
        html += '<div style="display:flex;gap:0.8rem;margin-bottom:0.8rem;">';
        html += _card("Race Laps", String((result.predicted_laps || []).length), "");
        var conf = result.confidence || 0;
        var confColor = conf > 0.7 ? COLORS.good : conf > 0.4 ? COLORS.warn : COLORS.poor;
        html += _card("Confidence", (conf * 100).toFixed(0) + "%", "", confColor);
        html += '</div>';

        // Stint pace
        html += '<div style="display:flex;gap:0.8rem;margin-bottom:0.8rem;">';
        html += _card("Best Stint", _fmtLap(result.best_stint_pace_s), "");
        html += _card("Worst Stint", _fmtLap(result.worst_stint_pace_s), "",
                       result.worst_stint_pace_s > (result.best_stint_pace_s || 0) * 1.03 ? COLORS.warn : COLORS.accent);
        html += '</div>';

        // Predicted race time
        if (result.total_race_time_s > 0) {
            html += '<div style="background:var(--bg-secondary);border-radius:8px;padding:0.6rem 1rem;margin-bottom:0.8rem;">';
            html += '<div style="font-size:0.7rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">Predicted Race Time</div>';
            html += '<div style="font-size:1.2rem;font-weight:700;color:var(--text-primary);">' +
                    esc(_fmtRaceTime(result.total_race_time_s)) + '</div>';
            html += '</div>';
        }

        // Time lost breakdown
        var tireLoss = result.tire_impact_s || 0;
        var fatigueLoss = result.fatigue_impact_s || 0;
        if (tireLoss > 0 || fatigueLoss > 0) {
            html += '<div style="background:var(--bg-secondary);border-radius:8px;padding:0.6rem 1rem;margin-bottom:0.8rem;">';
            html += '<div style="font-size:0.7rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">Time Lost</div>';
            if (tireLoss > 0) {
                html += '<div style="font-size:0.85rem;color:var(--text-primary);margin-top:0.2rem;">Tyre Deg: +' + esc(tireLoss.toFixed(1)) + 's</div>';
            }
            if (fatigueLoss > 0) {
                html += '<div style="font-size:0.85rem;color:var(--text-primary);margin-top:0.2rem;">Fatigue: +' + esc(fatigueLoss.toFixed(1)) + 's</div>';
            }
            html += '</div>';
        }

        // Pit stops list
        var pitLaps = result.pit_stop_laps || [];
        if (pitLaps.length > 0) {
            html += '<div style="background:var(--bg-secondary);border-radius:8px;padding:0.6rem 1rem;margin-bottom:0.8rem;">';
            html += '<div style="font-size:0.7rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">Pit Stops</div>';
            for (var pi = 0; pi < pitLaps.length; pi++) {
                html += '<div style="font-size:0.85rem;color:' + COLORS.pit + ';margin-top:0.15rem;">Lap ' + esc(String(pitLaps[pi])) + '</div>';
            }
            html += '</div>';
        }

        el.innerHTML = html;
    }

    /* ── Coaching hint ───────────────────────── */

    function renderCoaching(el, result) {
        if (!result.coaching) { el.innerHTML = ""; return; }
        el.innerHTML = '<div style="background:rgba(76,175,80,0.08);border-left:3px solid ' + (C.green || "#4caf50") + ';' +
            'padding:0.7rem 1rem;border-radius:4px;font-size:0.9rem;color:var(--text-primary);line-height:1.5;">' +
            '<strong style="color:' + (C.green || "#4caf50") + ';">Race Insight:</strong> ' +
            esc(result.coaching) + '</div>';
    }

    /* ── Result area rendering ───────────────── */

    function renderResult(container, result) {
        var html = '<div class="flex-wrap-start">';
        html += '<canvas id="sim-chart" width="560" height="280" class="chart-canvas" aria-label="Simulated race pace chart"></canvas>';
        html += '<div id="sim-stats" class="chart-sidebar" aria-live="polite"></div>';
        html += '</div>';
        html += '<div id="sim-coaching" class="coaching-below"></div>';
        container.innerHTML = html;

        var canvas = document.getElementById("sim-chart");
        var statsEl = document.getElementById("sim-stats");
        var coachEl = document.getElementById("sim-coaching");

        // DPR-aware sizing
        var dpr = window.devicePixelRatio || 1;
        var cw = canvas.clientWidth || 560;
        var ch = canvas.clientHeight || 280;
        canvas.width = cw * dpr;
        canvas.height = ch * dpr;
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);

        drawChart(ctx, cw, ch, result);
        canvas.__redraw = function() {
            var rdpr = window.devicePixelRatio || 1;
            var rcw = canvas.parentElement.clientWidth || 560;
            var rch = canvas.clientHeight || 280;
            canvas.width = rcw * rdpr;
            canvas.height = rch * rdpr;
            canvas.style.width = rcw + "px";
            var rctx = canvas.getContext("2d");
            rctx.scale(rdpr, rdpr);
            drawChart(rctx, rcw, rch, result);
        };
        renderStats(statsEl, result);
        renderCoaching(coachEl, result);

        // Resize support: listen on the canvas element (chart:resize doesn't bubble)
        _lc.addListener(canvas, "chart:resize", function () {
            var rdpr = window.devicePixelRatio || 1;
            var rcw = canvas.parentElement.clientWidth || 560;
            var rch = canvas.clientHeight || 280;
            canvas.width = rcw * rdpr;
            canvas.height = rch * rdpr;
            canvas.style.width = rcw + "px";
            var rctx = canvas.getContext("2d");
            rctx.scale(rdpr, rdpr);
            drawChart(rctx, rcw, rch, result);
        });
    }

    /* ── Prefill from session data ───────────── */

    function prefillDefaults(sessionId, callback) {
        var lapUrl = "/api/session/" + encodeURIComponent(sessionId) + "/lap_times";
        var workUrl = "/api/session/" + encodeURIComponent(sessionId) + "/workload";

        var lapPromise = FetchHelper.fetch(lapUrl);
        var workPromise = FetchHelper.fetch(workUrl).catch(function () { return null; });

        Promise.all([lapPromise, workPromise]).then(function (results) {
            var lapData = results[0];
            var workData = results[1];
            var defaults = {};

            // Best lap time
            var laps = (lapData && lapData.laps) ? lapData.laps : [];
            var validTimes = laps
                .filter(function (l) { return l.is_valid !== false && l.lap_time_s > 0; })
                .map(function (l) { return l.lap_time_s; });

            if (validTimes.length > 0) {
                var best = Math.min.apply(null, validTimes);
                defaults.target_lap_time_s = parseFloat(best.toFixed(3));

                // CV%
                var sum = 0;
                for (var i = 0; i < validTimes.length; i++) sum += validTimes[i];
                var mean = sum / validTimes.length;
                var sqDiff = 0;
                for (var j = 0; j < validTimes.length; j++) sqDiff += (validTimes[j] - mean) * (validTimes[j] - mean);
                var stdDev = Math.sqrt(sqDiff / validTimes.length);
                var cv = (stdDev / mean) * 100;
                defaults.consistency_cv_pct = parseFloat(cv.toFixed(2));
            }

            // Fatigue onset from workload
            if (workData && workData.fatigue_onset_lap) {
                defaults.fatigue_onset_lap = workData.fatigue_onset_lap;
            }

            callback(defaults);
        }).catch(function () {
            callback({});
        });
    }

    /* ── Simulate button handler ─────────────── */

    function runSimulation(sessionId) {
        var btn = document.getElementById("sim-run-btn");
        var resultArea = document.getElementById("sim-result-area");
        if (!btn || !resultArea) return;

        btn.disabled = true;
        btn.textContent = "Simulating...";
        resultArea.innerHTML = '<div class="no-data"><div class="spinner-inline spinner-accent"></div><span class="text-secondary text-sm">Running simulation...</span></div>';

        var params = collectParams();
        var url = "/api/session/" + encodeURIComponent(sessionId) + "/simulate-race";

        FetchHelper.fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(params),
        }).then(function (data) {
            btn.disabled = false;
            btn.innerHTML = '<span class="sim-btn-icon">&#9654;</span> Simulate';

            if (data.error) {
                resultArea.innerHTML = '<div class="no-data"><div class="no-data-text">' + esc(data.error) + '</div></div>';
                return;
            }

            renderResult(resultArea, data);
        }).catch(function (err) {
            btn.disabled = false;
            btn.innerHTML = '<span class="sim-btn-icon">&#9654;</span> Simulate';
            console.error("Race simulation error:", err);
            resultArea.innerHTML = '<div class="no-data"><div class="no-data-text">Simulation failed. Check console for details.</div></div>';
        });
    }

    /* ── Init ────────────────────────────────── */

    function init(containerId, sessionId) {
        var container = document.getElementById(containerId);
        if (!container) return;

        container.innerHTML = '<div class="no-data"><div class="spinner-inline spinner-accent"></div><span class="text-secondary text-sm">Loading simulator...</span></div>';

        prefillDefaults(sessionId, function (defaults) {
            container.innerHTML = buildForm(defaults);

            var btn = document.getElementById("sim-run-btn");
            if (btn) {
                _lc.addListener(btn, "click", function () {
                    runSimulation(sessionId);
                });
            }
        });
    }

    /* ── Auto-init via lazyInit ──────────────── */

    _lc.addListener(document, "DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("pace-simulator-container", function () {
                init("pace-simulator-container", sid);
            });
        } else if (sid) {
            init("pace-simulator-container", sid);
        }
    });

    function destroy() {
        _lc.destroyAll();
    }

    window.PaceSimulator = { init: init };

    window.ModuleManager.register('pace_simulator', {
        init: function () {},
        destroy: destroy
    });
})();
