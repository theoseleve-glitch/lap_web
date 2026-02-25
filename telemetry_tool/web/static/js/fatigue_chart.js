/**
 * fatigue_chart.js
 * ----------------
 * Displays driver fatigue / concentration analysis as a dashboard card.
 * Shows concentration index gauge, fatigue indicators, and mental lapse markers.
 */
(function () {
    "use strict";

    var C = window.Theme ? window.Theme.colors : {};

    var container;

    function _doInit() {
        var T = window.TELEMETRY;
        if (!T || !T.sessionId) return;

        container = document.getElementById("fatigue-analysis-container");
        if (!container) return;

        var url = "/api/session/" + encodeURIComponent(T.sessionId) + "/fatigue-analysis";

        FetchHelper.load(container, url, function (data) {
            render(data);
        }, {
            loadingText: 'Loading fatigue analysis\u2026',
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("fatigue-analysis-container", function () {
                _doInit();
            });
        } else if (sid) {
            _doInit();
        }
    });

    function levelColor(level) {
        switch (level) {
            case "fresh": return C.green || "#22c55e";
            case "mild": return C.yellow || "#eab308";
            case "moderate": return "#f97316";
            case "severe": return C.red || "#ef4444";
            default: return C.textSecondary || "#888";
        }
    }

    function gaugeColor(pct) {
        if (pct >= 85) return C.green || "#22c55e";
        if (pct >= 65) return C.yellow || "#eab308";
        if (pct >= 40) return "#f97316";
        return C.red || "#ef4444";
    }

    function render(data) {
        if (!data || data.fatigue_level === "insufficient_data") {
            container.innerHTML = '<div class="no-data"><div class="no-data-text">'
                + (data && data.coaching_hint ? esc(data.coaching_hint) : 'Insufficient data for fatigue analysis.')
                + '</div></div>';
            return;
        }

        var ci = data.concentration_index || 100;
        var level = data.fatigue_level || "fresh";
        var color = levelColor(level);
        var gColor = gaugeColor(ci);

        var html = '<div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start;">';

        // Concentration gauge
        html += '<div style="text-align:center;min-width:140px;">'
            + '<div style="position:relative;width:120px;height:120px;margin:0 auto;">'
            + '<svg viewBox="0 0 120 120" width="120" height="120">'
            + '<circle cx="60" cy="60" r="52" fill="none" stroke="#333" stroke-width="8"/>'
            + '<circle cx="60" cy="60" r="52" fill="none" stroke="' + gColor + '" '
            + 'stroke-width="8" stroke-dasharray="' + (ci / 100 * 326.7).toFixed(1) + ' 326.7" '
            + 'stroke-linecap="round" transform="rotate(-90 60 60)"/>'
            + '<text x="60" y="56" text-anchor="middle" fill="' + (C.textPrimary || "#fff") + '" font-size="28" font-weight="700">'
            + Math.round(ci) + '</text>'
            + '<text x="60" y="74" text-anchor="middle" fill="' + (C.textSecondary || "#aaa") + '" font-size="11">/100</text>'
            + '</svg></div>'
            + '<div style="margin-top:4px;font-size:14px;font-weight:700;color:' + color + ';text-transform:uppercase;">'
            + level + '</div>'
            + '<div style="font-size:11px;color:' + (C.textSecondary || "#888") + ';">Concentration Index</div>'
            + '</div>';

        // Indicators grid
        html += '<div style="flex:1;display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;">';

        // Smoothness
        var sDeg = data.smoothness_degradation_pct || 0;
        var sColor = sDeg > 20 ? (C.red || "#ef4444") : sDeg > 10 ? (C.yellow || "#eab308") : (C.green || "#22c55e");
        html += _indicatorCard("Smoothness", sDeg.toFixed(1) + "%",
            sDeg > 0 ? "degradation" : "improvement", sColor);

        // Braking consistency
        var bDec = data.braking_consistency_decay_pct || 0;
        var bColor = bDec > 30 ? (C.red || "#ef4444") : bDec > 15 ? (C.yellow || "#eab308") : (C.green || "#22c55e");
        html += _indicatorCard("Brake Scatter", bDec.toFixed(1) + "%",
            bDec > 0 ? "more scattered" : "consistent", bColor);

        // Mental lapses
        var lapses = data.lapse_count || 0;
        var lColor = lapses >= 3 ? (C.red || "#ef4444") : lapses >= 1 ? (C.yellow || "#eab308") : (C.green || "#22c55e");
        var lDetail = lapses > 0 ? "laps: " + (data.lapse_laps || []).join(", ") : "none detected";
        html += _indicatorCard("Mental Lapses", lapses.toString(), lDetail, lColor);

        // Pace trend
        var pSlope = data.pace_slope_s_per_lap || 0;
        var pColor = pSlope > 0.1 ? (C.red || "#ef4444") : pSlope > 0.03 ? (C.yellow || "#eab308") : (C.green || "#22c55e");
        html += _indicatorCard("Pace Trend",
            (pSlope > 0 ? "+" : "") + pSlope.toFixed(3) + " s/lap",
            pSlope > 0 ? "slowing" : "stable/improving", pColor);

        html += '</div></div>';

        // Coaching hint
        if (data.coaching_hint) {
            html += '<div style="margin-top:12px;padding:8px 12px;background:' + (C.bgCard || "#1a1a2e") + ';'
                + 'border-left:3px solid ' + color + ';border-radius:4px;'
                + 'font-size:12px;color:var(--text-secondary);">'
                + esc(data.coaching_hint) + '</div>';
        }

        container.innerHTML = html;
    }

    function _indicatorCard(title, value, subtitle, color) {
        return '<div style="background:' + (C.bgCard || "#1a1a2e") + ';border:1px solid #333;border-radius:6px;padding:10px;">'
            + '<div style="font-size:11px;color:' + (C.textSecondary || "#888") + ';margin-bottom:2px;">' + title + '</div>'
            + '<div style="font-size:20px;font-weight:700;color:' + color + ';">' + value + '</div>'
            + '<div style="font-size:10px;color:var(--text-muted);">' + subtitle + '</div>'
            + '</div>';
    }
})();
