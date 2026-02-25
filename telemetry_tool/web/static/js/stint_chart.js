/**
 * stint_chart.js
 * ---------------
 * Canvas 2D visualisation for stint analysis data.
 *
 * Draws a horizontal stint timeline showing per-stint KPIs:
 * mean pace, CV%, pace fade, and tyre cliff markers.
 */
(function () {
    "use strict";

    var C = window.Theme ? window.Theme.colors : {};

    var container, canvas;

    function _doInit() {
        var T = window.TELEMETRY;
        if (!T || !T.sessionId) return;

        container = document.getElementById("stint-analysis-container");
        canvas    = document.getElementById("stint-pace-chart");
        if (!container || !canvas) return;

        var url = "/api/session/" + encodeURIComponent(T.sessionId) + "/stint-analysis";

        FetchHelper.load(container, url, function (data) {
            try { render(data); } catch(e) { console.error('Stint render error:', e); container.innerHTML = '<div class="no-data"><div class="no-data-text">Failed to render stint data.</div></div>'; }
        }, {
            loadingText: 'Loading stint analysis\u2026',
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("stint-analysis-container", function () {
                _doInit();
            });
        } else if (sid) {
            _doInit();
        }
    });

    // Responsive resize support
    (function() {
        var _stintCanvas = document.getElementById('stint-pace-chart');
        if (_stintCanvas) {
            _stintCanvas.addEventListener('chart:resize', function() {
                if (_lastMetrics && _lastMetrics.length > 0) {
                    drawStintChart(_lastMetrics);
                }
            });
        }
    })();

    // -- Colours
    var COLORS = {
        good:    C.green || "#22c55e",
        ok:      C.yellow || "#eab308",
        bad:     C.red || "#ef4444",
        bg:      "#1e1e2e",
        grid:    "#333346",
        text:    "#c8c8d4",
        accent:  "#60a5fa",
        cliff:   "#f97316",
    };

    function gradeColor(cv) {
        if (cv <= 1.5) return COLORS.good;
        if (cv <= 3.0) return COLORS.ok;
        return COLORS.bad;
    }

    function render(data) {
        if (!data || !data.stint_metrics || data.stint_metrics.length === 0) {
            container.innerHTML = '<div class="no-data"><div class="no-data-text">Single stint detected (no pit stops).</div></div>';
            return;
        }

        // Build HTML summary cards
        var html = '<div class="stint-cards" style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;">';
        var metrics = data.stint_metrics;

        for (var i = 0; i < metrics.length; i++) {
            var m = metrics[i];
            var cvColor = gradeColor(m.cv_pct || 0);
            var fadeLabel = (m.pace_fade_pct || 0).toFixed(1);
            var cliffTag = m.tyre_cliff_lap
                ? '<span style="color:' + COLORS.cliff + ';font-weight:600;"> | Cliff @ L' + m.tyre_cliff_lap + '</span>'
                : '';

            html += '<div class="stint-card" style="'
                + 'background:' + (C.bgCard || "#1a1a2e") + ';border:1px solid var(--border);border-radius:8px;padding:10px 14px;min-width:180px;flex:1;">'
                + '<div style="font-weight:700;font-size:14px;color:var(--text-primary);">Stint ' + m.stint_number + '</div>'
                + '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:6px;">Laps ' + m.lap_start + '&ndash;' + m.lap_end
                + ' (' + m.lap_count + ' laps)</div>'
                + '<div style="display:flex;gap:16px;font-size:13px;">'
                + '<div><span style="color:var(--text-secondary);">Best</span><br><strong style="color:var(--text-primary);">' + (m.best_time_s || 0).toFixed(3) + 's</strong></div>'
                + '<div><span style="color:var(--text-secondary);">Mean</span><br><strong style="color:var(--text-primary);">' + (m.mean_time_s || 0).toFixed(3) + 's</strong></div>'
                + '<div><span style="color:var(--text-secondary);">CV%</span><br><strong style="color:' + cvColor + ';">' + (m.cv_pct || 0).toFixed(1) + '%</strong></div>'
                + '<div><span style="color:var(--text-secondary);">Fade</span><br><strong style="color:' + (parseFloat(fadeLabel) > 3 ? COLORS.bad : COLORS.text) + ';">'
                + fadeLabel + '%</strong></div>'
                + '</div>'
                + cliffTag
                + (m.coaching_hint ? '<div style="margin-top:6px;font-size:11px;color:var(--text-secondary);font-style:italic;">' + m.coaching_hint + '</div>' : '')
                + '</div>';
        }
        html += '</div>';

        // Session-level coaching
        if (data.session_coaching && data.session_coaching.length > 0) {
            html += '<div style="margin-bottom:8px;">';
            for (var c = 0; c < data.session_coaching.length; c++) {
                html += '<div style="font-size:12px;color:var(--text-primary);padding:4px 0;border-left:3px solid '
                    + COLORS.accent + ';padding-left:8px;margin-bottom:4px;">'
                    + data.session_coaching[c] + '</div>';
            }
            html += '</div>';
        }

        container.innerHTML = html;

        // Draw stint timeline chart
        drawStintChart(metrics);
    }

    // Keep last metrics for resize redraws
    var _lastMetrics = null;

    function drawStintChart(metrics) {
        _lastMetrics = metrics;
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth || 700;
        var H = 200;
        canvas.width  = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width  = W + "px";
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);

        // Margins
        var ml = 55, mr = 20, mt = 30, mb = 35;
        var pw = W - ml - mr;
        var ph = H - mt - mb;

        // Background
        ctx.fillStyle = COLORS.bg;
        ctx.fillRect(0, 0, W, H);

        // Collect all laps across stints for x-axis
        var allLaps = [];
        var stintRanges = [];
        for (var i = 0; i < metrics.length; i++) {
            var m = metrics[i];
            stintRanges.push({ start: m.lap_start, end: m.lap_end, idx: i });
            for (var l = m.lap_start; l <= m.lap_end; l++) {
                allLaps.push(l);
            }
        }

        if (allLaps.length === 0) return;

        var minLap = Math.min.apply(null, allLaps);
        var maxLap = Math.max.apply(null, allLaps);
        var lapRange = Math.max(maxLap - minLap, 1);

        // Y axis: mean pace range
        var times = metrics.map(function (m) { return m.mean_time_s || 0; }).filter(function (t) { return t > 0; });
        var bestTimes = metrics.map(function (m) { return m.best_time_s || 0; }).filter(function (t) { return t > 0; });
        var allTimes = times.concat(bestTimes);
        if (allTimes.length === 0) return;

        var yMin = Math.min.apply(null, allTimes) - 0.5;
        var yMax = Math.max.apply(null, allTimes) + 0.5;
        var yRange = Math.max(yMax - yMin, 0.1);

        function xPos(lap) { return ml + ((lap - minLap) / lapRange) * pw; }
        function yPos(t)   { return mt + (1 - (t - yMin) / yRange) * ph; }

        // Grid
        ctx.strokeStyle = COLORS.grid;
        ctx.lineWidth = 0.5;
        var nGridY = 5;
        for (var g = 0; g <= nGridY; g++) {
            var gy = mt + (g / nGridY) * ph;
            ctx.beginPath(); ctx.moveTo(ml, gy); ctx.lineTo(W - mr, gy); ctx.stroke();
            var gVal = yMax - (g / nGridY) * yRange;
            ctx.fillStyle = COLORS.text;
            ctx.font = "11px monospace";
            ctx.textAlign = "right";
            ctx.fillText(gVal.toFixed(1) + "s", ml - 5, gy + 4);
        }

        // X axis labels
        ctx.textAlign = "center";
        var xStep = Math.max(1, Math.floor(lapRange / 10));
        for (var xl = minLap; xl <= maxLap; xl += xStep) {
            ctx.fillStyle = COLORS.text;
            ctx.font = "11px monospace";
            ctx.fillText("L" + xl, xPos(xl), H - mb + 18);
        }

        // Draw stint zones
        var stintColors = ["#3b82f6", "#8b5cf6", "#06b6d4", C.green || "#22c55e", "#f59e0b"];
        for (var s = 0; s < metrics.length; s++) {
            var sm = metrics[s];
            var x1 = xPos(sm.lap_start) - 2;
            var x2 = xPos(sm.lap_end) + 2;
            ctx.fillStyle = stintColors[s % stintColors.length] + "15";
            ctx.fillRect(x1, mt, x2 - x1, ph);

            // Stint label at top
            ctx.fillStyle = stintColors[s % stintColors.length];
            ctx.font = "bold 11px sans-serif";
            ctx.textAlign = "center";
            ctx.fillText("Stint " + sm.stint_number, (x1 + x2) / 2, mt - 8);

            // Mean pace line
            if (sm.mean_time_s > 0) {
                var my = yPos(sm.mean_time_s);
                ctx.strokeStyle = stintColors[s % stintColors.length];
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 4]);
                ctx.beginPath();
                ctx.moveTo(x1, my);
                ctx.lineTo(x2, my);
                ctx.stroke();
                ctx.setLineDash([]);
            }

            // Best lap marker
            if (sm.best_time_s > 0) {
                var bx = xPos(sm.best_lap);
                var by = yPos(sm.best_time_s);
                ctx.fillStyle = stintColors[s % stintColors.length];
                ctx.beginPath();
                ctx.arc(bx, by, 5, 0, Math.PI * 2);
                ctx.fill();
                ctx.fillStyle = C.textPrimary || "#fff";
                ctx.font = "bold 10px monospace";
                ctx.textAlign = "center";
                ctx.fillText(sm.best_time_s.toFixed(2), bx, by - 9);
            }

            // Tyre cliff marker
            if (sm.tyre_cliff_lap) {
                var cx = xPos(sm.tyre_cliff_lap);
                ctx.strokeStyle = COLORS.cliff;
                ctx.lineWidth = 2;
                ctx.setLineDash([3, 3]);
                ctx.beginPath();
                ctx.moveTo(cx, mt);
                ctx.lineTo(cx, mt + ph);
                ctx.stroke();
                ctx.setLineDash([]);

                ctx.fillStyle = COLORS.cliff;
                ctx.font = "bold 10px sans-serif";
                ctx.textAlign = "center";
                ctx.fillText("CLIFF", cx, mt + ph + 12);
            }
        }

        // Title
        ctx.fillStyle = COLORS.text;
        ctx.font = "bold 13px sans-serif";
        ctx.textAlign = "left";
        ctx.fillText("Stint Pace Timeline", ml, mt - 15);
    }
})();
