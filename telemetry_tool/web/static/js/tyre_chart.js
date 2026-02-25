/**
 * tyre_chart.js
 * -------------
 * Renders tyre compound comparison: stint profile cards, comparison table,
 * and recommendation badge.
 *
 * Public API:
 *   window.TyreChart.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var C = window.Theme ? window.Theme.colors : {};

    var STINT_COLORS = [
        "#36a2eb", "#ff6384", C.green || "#4caf50", "#ff9800", "#9c27b0", "#00bcd4"
    ];

    function render(el, data) {
        var profiles = data.stint_profiles || [];
        var comparisons = data.comparisons || [];

        if (profiles.length === 0) {
            el.innerHTML = '<div class="no-data"><div class="no-data-text">' +
                esc(data.coaching || "No tyre data available.") + '</div></div>';
            return;
        }

        var html = "";

        // Stint profile cards
        html += '<div style="display:flex;flex-wrap:wrap;gap:1rem;margin-bottom:1rem;">';
        profiles.forEach(function (sp, idx) {
            var color = STINT_COLORS[idx % STINT_COLORS.length];
            html += '<div style="background:var(--card-bg);border-radius:8px;padding:0.8rem 1rem;' +
                'border-top:3px solid ' + color + ';min-width:180px;flex:1;">';
            html += '<div style="font-size:1rem;font-weight:700;color:' + color + ';">' +
                esc(sp.compound_label) + '</div>';
            html += '<div style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.5rem;">Laps ' +
                sp.lap_start + ' - ' + sp.lap_end + ' (' + sp.n_laps + ' laps)</div>';

            html += _stat("Fresh Pace", sp.fresh_pace_s.toFixed(3) + "s");
            html += _stat("Mean Pace", sp.mean_pace_s.toFixed(3) + "s");
            html += _stat("Best Pace", sp.best_pace_s.toFixed(3) + "s");
            html += _stat("Degradation", "+" + (sp.degradation_s_per_lap * 1000).toFixed(0) + "ms/lap",
                sp.degradation_s_per_lap > 0.1 ? (C.red || "#e74c3c") :
                sp.degradation_s_per_lap > 0.03 ? "#ff9800" : (C.green || "#4caf50"));
            html += _stat("Consistency", "CV " + sp.cv_pct.toFixed(1) + "%");
            html += '</div>';
        });
        html += '</div>';

        // Comparison table
        if (comparisons.length > 0) {
            html += '<div style="margin-bottom:1rem;">';
            html += '<div style="font-size:0.75rem;color:var(--text-secondary);text-transform:uppercase;margin-bottom:0.3rem;">Stint Comparisons</div>';
            html += '<div class="table-wrap"><table style="width:100%;border-collapse:collapse;font-size:0.8rem;">';
            html += '<caption class="sr-only">Stint comparisons</caption>';
            html += '<thead><tr>';
            html += '<th style="padding:4px 8px;color:var(--text-secondary);text-align:left;">Comparison</th>';
            html += '<th style="padding:4px 8px;color:var(--text-secondary);">Fresh Pace Delta</th>';
            html += '<th style="padding:4px 8px;color:var(--text-secondary);">Mean Pace Delta</th>';
            html += '<th style="padding:4px 8px;color:var(--text-secondary);">Deg Delta</th>';
            html += '<th style="padding:4px 8px;color:var(--text-secondary);">Crossover</th>';
            html += '<th style="padding:4px 8px;color:var(--text-secondary);">Recommended</th>';
            html += '</tr></thead><tbody>';

            comparisons.forEach(function (c) {
                html += '<tr>';
                html += '<td style="padding:4px 8px;color:var(--text-secondary);">' + esc(c.stint_a) + ' vs ' + esc(c.stint_b) + '</td>';
                html += '<td style="padding:4px 8px;text-align:center;color:' +
                    _deltaColor(c.fresh_pace_delta_s) + ';">' +
                    _fmtDelta(c.fresh_pace_delta_s) + '</td>';
                html += '<td style="padding:4px 8px;text-align:center;color:' +
                    _deltaColor(c.mean_pace_delta_s) + ';">' +
                    _fmtDelta(c.mean_pace_delta_s) + '</td>';
                html += '<td style="padding:4px 8px;text-align:center;color:' +
                    _deltaColor(c.degradation_delta_s) + ';">' +
                    _fmtDelta(c.degradation_delta_s) + '/lap</td>';
                html += '<td style="padding:4px 8px;text-align:center;color:var(--text-secondary);">' +
                    (c.crossover_lap > 0 ? 'Lap ' + c.crossover_lap : '--') + '</td>';
                html += '<td style="padding:4px 8px;text-align:center;color:var(--green);font-weight:600;">' +
                    esc(c.recommended) + '</td>';
                html += '</tr>';
            });

            html += '</tbody></table></div></div>';
        }

        // Recommendation
        if (data.recommendation) {
            html += '<div style="background:rgba(76,175,80,0.08);border-left:3px solid var(--green);' +
                'padding:0.6rem 1rem;border-radius:4px;font-size:0.85rem;color:var(--text-primary);margin-bottom:0.5rem;">' +
                '<strong style="color:var(--green);">Recommendation:</strong> ' +
                esc(data.recommendation) + '</div>';
        }

        // Coaching
        if (data.coaching) {
            html += '<div style="background:rgba(54,162,235,0.06);border-left:3px solid var(--blue);' +
                'padding:0.6rem 1rem;border-radius:4px;font-size:0.85rem;color:var(--text-primary);">' +
                '<strong style="color:var(--blue);">Tyre Insight:</strong> ' +
                esc(data.coaching) + '</div>';
        }

        el.innerHTML = html;
    }

    function _stat(label, value, color) {
        color = color || "var(--text-secondary)";
        return '<div style="display:flex;justify-content:space-between;font-size:0.8rem;' +
            'padding:0.1rem 0;border-bottom:1px solid rgba(255,255,255,0.04);">' +
            '<span style="color:var(--text-secondary);">' + label + '</span>' +
            '<span style="color:' + color + ';font-weight:600;">' + value + '</span>' +
            '</div>';
    }

    function _deltaColor(d) {
        if (d < -0.01) return C.green || "#4caf50";
        if (d > 0.01) return C.red || "#e74c3c";
        return C.textSecondary || "#aaa";
    }

    function _fmtDelta(d) {
        var sign = d >= 0 ? "+" : "";
        return sign + (d * 1000).toFixed(0) + "ms";
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/tyre-analysis", function (data) {
            render(el, data);
        }, {
            loadingText: 'Loading tyre analysis\u2026',
        });
    }

    // Auto-init
    document.addEventListener("DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("tyre-analysis-container", function () {
                init("tyre-analysis-container", sid);
            });
        } else if (sid) {
            init("tyre-analysis-container", sid);
        }
    });

    window.TyreChart = { init: init };
})();
