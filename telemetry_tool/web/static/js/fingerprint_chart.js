/**
 * fingerprint_chart.js
 * --------------------
 * Canvas 2D radar / spider chart for the 6-dimension Performance Fingerprint.
 * Plus stats panel with dimension bars, overall rating, and balance score.
 *
 * Public API:
 *   window.FingerprintChart.init(canvasId, statsId, sessionId)
 */
(function () {
    "use strict";

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    // ---- colour palette ----
    var FILL   = "rgba(54, 162, 235, 0.25)";
    var STROKE = "rgba(54, 162, 235, 1)";
    var GRID   = "rgba(160, 160, 160, 0.30)";
    var TEXT   = "#ccc";
    var LABEL  = "#e0e0e0";
    var ACCENT = "#36a2eb";
    var GOOD   = C.green || "#4caf50";
    var WARN   = "#ff9800";
    var POOR   = C.red || "#e74c3c";

    function gradeColor(v) {
        if (v >= 80) return GOOD;
        if (v >= 50) return WARN;
        return POOR;
    }

    function gradeLetter(v) {
        if (v >= 90) return "S";
        if (v >= 80) return "A";
        if (v >= 70) return "B";
        if (v >= 60) return "C";
        if (v >= 50) return "D";
        return "F";
    }

    // ---- radar drawing ----
    function drawRadar(ctx, w, h, values, labels) {
        var n = values.length;
        if (n < 3) return;
        var cx = w / 2;
        var cy = h / 2;
        var R  = Math.min(cx, cy) - 50;
        var angleStep = (2 * Math.PI) / n;
        var startAngle = -Math.PI / 2; // top

        function polar(idx, r) {
            var a = startAngle + idx * angleStep;
            return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
        }

        ctx.clearRect(0, 0, w, h);

        // Grid rings (0, 25, 50, 75, 100)
        [20, 40, 60, 80, 100].forEach(function (pct) {
            var r = R * pct / 100;
            ctx.beginPath();
            for (var i = 0; i <= n; i++) {
                var p = polar(i % n, r);
                if (i === 0) ctx.moveTo(p.x, p.y);
                else ctx.lineTo(p.x, p.y);
            }
            ctx.closePath();
            ctx.strokeStyle = GRID;
            ctx.lineWidth = 1;
            ctx.stroke();

            // Ring label
            if (pct < 100) {
                ctx.fillStyle = "rgba(160,160,160,0.5)";
                ctx.font = "10px system-ui";
                ctx.textAlign = "left";
                ctx.fillText(String(pct), cx + 3, cy - r + 10);
            }
        });

        // Axis lines + labels
        ctx.font = "12px system-ui";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        for (var i = 0; i < n; i++) {
            var pEnd = polar(i, R);
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(pEnd.x, pEnd.y);
            ctx.strokeStyle = GRID;
            ctx.lineWidth = 1;
            ctx.stroke();

            // Label position (just beyond the outer ring)
            var pLabel = polar(i, R + 28);
            ctx.fillStyle = LABEL;
            ctx.font = "bold 11px system-ui";
            ctx.fillText(labels[i], pLabel.x, pLabel.y);

            // Value next to label
            ctx.fillStyle = gradeColor(values[i]);
            ctx.font = "bold 12px system-ui";
            var pVal = polar(i, R + 14);
            ctx.fillText(Math.round(values[i]), pVal.x, pVal.y);
        }

        // Data polygon
        ctx.beginPath();
        for (var j = 0; j <= n; j++) {
            var pData = polar(j % n, R * values[j % n] / 100);
            if (j === 0) ctx.moveTo(pData.x, pData.y);
            else ctx.lineTo(pData.x, pData.y);
        }
        ctx.closePath();
        ctx.fillStyle = FILL;
        ctx.fill();
        ctx.strokeStyle = STROKE;
        ctx.lineWidth = 2.5;
        ctx.stroke();

        // Data points
        for (var k = 0; k < n; k++) {
            var pDot = polar(k, R * values[k] / 100);
            ctx.beginPath();
            ctx.arc(pDot.x, pDot.y, 4, 0, 2 * Math.PI);
            ctx.fillStyle = STROKE;
            ctx.fill();
            ctx.strokeStyle = C.textPrimary || "#fff";
            ctx.lineWidth = 1.5;
            ctx.stroke();
        }
    }

    // ---- stats panel ----
    function renderStats(el, data) {
        var dims = data.dimensions || {};
        var names = data.dimension_names || [];
        var vector = data.vector || [];
        var overall = data.overall_rating || 0;
        var balance = data.balance_score || 0;

        var html = "";

        // Overall + Balance header
        html += '<div style="display:flex;gap:1rem;margin-bottom:1rem;">';
        html += '<div style="background:var(--card-bg);border-radius:8px;padding:0.6rem 1rem;flex:1;text-align:center;">';
        html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">Overall</div>';
        html += '<div style="font-size:1.5rem;font-weight:700;color:' + gradeColor(overall) + ';">' +
                overall.toFixed(1) + '</div>';
        html += '<div style="font-size:0.85rem;color:' + gradeColor(overall) + ';font-weight:600;">' +
                gradeLetter(overall) + '</div>';
        html += '</div>';
        html += '<div style="background:var(--card-bg);border-radius:8px;padding:0.6rem 1rem;flex:1;text-align:center;">';
        html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">Balance</div>';
        html += '<div style="font-size:1.5rem;font-weight:700;color:' + gradeColor(balance) + ';">' +
                balance.toFixed(1) + '</div>';
        html += '<div style="font-size:0.85rem;color:' + (C.textSecondary || "#aaa") + ';">' + (balance >= 75 ? "Well-rounded" :
                balance >= 50 ? "Moderate" : "Specialist") + '</div>';
        html += '</div>';
        html += '</div>';

        // Dimension bars
        var dimKeys = ["raw_pace", "consistency", "racecraft", "technical_skill", "tyre_management", "mental_fortitude"];
        var dimLabels = ["Raw Pace", "Consistency", "Racecraft", "Technical", "Tyre Mgmt", "Mental"];

        html += '<div style="display:flex;flex-direction:column;gap:0.4rem;">';
        for (var i = 0; i < dimKeys.length; i++) {
            var val = dims[dimKeys[i]] || 0;
            var col = gradeColor(val);
            html += '<div style="display:flex;align-items:center;gap:0.5rem;">';
            html += '<span style="width:70px;font-size:0.8rem;color:' + (C.textSecondary || "#aaa") + ';text-align:right;">' + dimLabels[i] + '</span>';
            html += '<div style="flex:1;background:rgba(255,255,255,0.07);border-radius:4px;height:16px;overflow:hidden;">';
            html += '<div style="width:' + val + '%;height:100%;background:' + col + ';border-radius:4px;' +
                    'transition:width 0.6s ease;"></div>';
            html += '</div>';
            html += '<span style="width:35px;font-size:0.8rem;font-weight:600;color:' + col + ';">' +
                    val.toFixed(0) + '</span>';
            html += '</div>';
        }
        html += '</div>';

        // Driver + Session
        if (data.driver_name) {
            html += '<p style="margin-top:0.8rem;font-size:0.8rem;color:' + (C.textSecondary || "#888") + ';">Driver: <strong style="color:var(--text-secondary);">' +
                    esc(data.driver_name) + '</strong></p>';
        }

        el.innerHTML = html;
    }

    // ---- init ----
    function init(canvasId, statsId, sessionId) {
        var canvas = document.getElementById(canvasId);
        var statsEl = document.getElementById(statsId);
        if (!canvas || !statsEl) return;

        FetchHelper.load(statsEl, "/api/session/" + encodeURIComponent(sessionId) + "/fingerprint", function(data) {
            var ctx = canvas.getContext("2d");
            var dpr = window.devicePixelRatio || 1;
            var w = canvas.clientWidth || 380;
            var h = canvas.clientHeight || 380;
            canvas.width = w * dpr;
            canvas.height = h * dpr;
            ctx.scale(dpr, dpr);

            var labels = data.dimension_names || [
                "Raw Pace", "Consistency", "Racecraft",
                "Technical", "Tyre Mgmt", "Mental"
            ];
            var values = data.vector || [50, 50, 50, 50, 50, 50];

            drawRadar(ctx, w, h, values, labels);
            renderStats(statsEl, data);

            // Register __redraw for ResizeObserver
            canvas.__redraw = function() {
                var dpr2 = window.devicePixelRatio || 1;
                var w2 = canvas.clientWidth || 380;
                var h2 = canvas.clientHeight || 380;
                canvas.width = w2 * dpr2;
                canvas.height = h2 * dpr2;
                var ctx2 = canvas.getContext("2d");
                ctx2.scale(dpr2, dpr2);
                drawRadar(ctx2, w2, h2, values, labels);
            };
        }, {
            loadingText: 'Loading fingerprint\u2026',
        });
    }

    // Auto-init on DOMContentLoaded
    _lc.addListener(document, "DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid) {
            init("fingerprint-radar", "fingerprint-stats", sid);
        }
    });

    window.FingerprintChart = { init: init };

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('fingerprint_chart', {
        init: function () {},
        destroy: destroy
    });
})();
