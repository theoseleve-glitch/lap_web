/**
 * comparison_matrix.js
 * --------------------
 * Renders a session comparison matrix: summary cards for each session,
 * pairwise delta table, best-per-metric badges, and net assessment.
 *
 * Public API:
 *   window.ComparisonMatrix.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    var ASSESS_COLORS = {
        improved:  C.green || "#4caf50",
        regressed: C.red || "#e74c3c",
        mixed:     "#ff9800",
        unchanged: C.textSecondary || "#888"
    };

    var ASSESS_ICONS = {
        improved:  "\u25B2",
        regressed: "\u25BC",
        mixed:     "\u25C6",
        unchanged: "\u25CF"
    };

    function render(el, data) {
        var sessions = data.sessions || [];
        var pairwise = data.pairwise || [];
        var bestPer = data.best_per_metric || {};
        var labels = data.metric_labels || {};
        var lowerBetter = data.lower_is_better || [];
        var focusId = data.focus_session_id || "";

        if (sessions.length < 2) {
            el.innerHTML = '<div class="no-data"><div class="no-data-text">Need at least 2 sessions on the same track to compare.</div></div>';
            return;
        }

        var html = "";

        // Session summary cards
        html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;margin-bottom:0.4rem;">Sessions Compared</div>';
        html += '<div style="display:flex;flex-wrap:wrap;gap:0.6rem;margin-bottom:1rem;">';
        sessions.forEach(function (s) {
            var isFocus = (s.session_id === focusId);
            var border = isFocus ? "2px solid var(--blue)" : "1px solid rgba(255,255,255,0.08)";
            html += '<div style="background:var(--card-bg);border-radius:8px;padding:0.6rem 0.8rem;' +
                'border:' + border + ';min-width:150px;flex:1;max-width:220px;">';
            html += '<div style="font-size:0.85rem;font-weight:700;color:' +
                (isFocus ? 'var(--blue)' : 'var(--text-secondary)') + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' +
                _escHtml(s.session_id) + '</div>';
            html += '<div style="font-size:0.7rem;color:' + (C.textSecondary || "#888") + ';">' + _escHtml(s.session_date || "—") +
                ' &middot; ' + _escHtml(s.session_type || "—") + '</div>';
            html += _miniStat("Best", s.best_lap_time_s > 0 ? s.best_lap_time_s.toFixed(3) + "s" : "—");
            html += _miniStat("Mean", s.mean_lap_time_s > 0 ? s.mean_lap_time_s.toFixed(3) + "s" : "—");
            html += _miniStat("Score", s.total_score > 0 ? s.total_score.toFixed(1) : "—");
            html += _miniStat("Laps", s.n_laps);
            html += _miniStat("CV%", s.cv_pct > 0 ? s.cv_pct.toFixed(2) + "%" : "—");
            html += '</div>';
        });
        html += '</div>';

        // Best-per-metric badges
        var hasAnyBest = Object.keys(bestPer).length > 0;
        if (hasAnyBest) {
            html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;margin-bottom:0.3rem;">Records</div>';
            html += '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:1rem;">';
            Object.keys(bestPer).forEach(function (metric) {
                var sessId = bestPer[metric];
                var label = labels[metric] || metric;
                html += '<span style="background:rgba(255,215,0,0.10);color:' + (C.yellow || "#ffd700") + ';padding:0.2rem 0.6rem;' +
                    'border-radius:12px;font-size:0.72rem;border:1px solid rgba(255,215,0,0.2);">' +
                    label + ': <strong>' + _escHtml(_truncId(sessId)) + '</strong></span>';
            });
            html += '</div>';
        }

        // Pairwise comparison table
        if (pairwise.length > 0) {
            html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;margin-bottom:0.3rem;">Pairwise Comparisons</div>';
            html += '<div class="table-wrap" style="margin-bottom:1rem;">';
            html += '<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">';
            html += '<caption class="sr-only">Pairwise session comparisons</caption>';
            html += '<thead><tr>';
            html += '<th style="padding:4px 8px;color:' + (C.textSecondary || "#aaa") + ';text-align:left;">A vs B</th>';
            html += '<th style="padding:4px 8px;color:' + (C.textSecondary || "#aaa") + ';">Assessment</th>';

            var metricKeys = Object.keys(labels);
            metricKeys.forEach(function (m) {
                html += '<th style="padding:4px 8px;color:' + (C.textSecondary || "#aaa") + ';">' + labels[m] + '</th>';
            });
            html += '</tr></thead><tbody>';

            pairwise.forEach(function (p) {
                var aColor = ASSESS_COLORS[p.net_assessment] || (C.textSecondary || "#888");
                var aIcon = ASSESS_ICONS[p.net_assessment] || "";
                html += '<tr>';
                html += '<td style="padding:4px 8px;color:var(--text-secondary);white-space:nowrap;max-width:160px;overflow:hidden;text-overflow:ellipsis;">' +
                    _escHtml(_truncId(p.session_a.session_id)) + ' &rarr; ' +
                    _escHtml(_truncId(p.session_b.session_id)) + '</td>';
                html += '<td style="padding:4px 8px;text-align:center;color:' + aColor + ';font-weight:600;">' +
                    aIcon + ' ' + p.net_assessment + '</td>';

                metricKeys.forEach(function (m) {
                    var d = p.deltas[m];
                    if (d === undefined || d === null) {
                        html += '<td style="padding:4px 8px;text-align:center;color:var(--text-muted);">—</td>';
                        return;
                    }
                    var isLowerBetter = lowerBetter.indexOf(m) >= 0;
                    var isGood = isLowerBetter ? (d < -0.001) : (d > 0.001);
                    var isBad = isLowerBetter ? (d > 0.001) : (d < -0.001);
                    var color = isGood ? (C.green || "#4caf50") : (isBad ? (C.red || "#e74c3c") : (C.textSecondary || "#888"));
                    var sign = d >= 0 ? "+" : "";

                    // Format delta based on metric
                    var formatted;
                    if (m === "n_laps") {
                        formatted = sign + d.toFixed(0);
                    } else if (m === "total_score" || m === "consistency_pct") {
                        formatted = sign + d.toFixed(1);
                    } else if (m === "cv_pct") {
                        formatted = sign + d.toFixed(2) + "%";
                    } else {
                        formatted = sign + (d * 1000).toFixed(0) + "ms";
                    }

                    html += '<td style="padding:4px 8px;text-align:center;color:' + color + ';">' +
                        formatted + '</td>';
                });
                html += '</tr>';
            });

            html += '</tbody></table></div>';
        }

        // Summary
        if (data.summary) {
            html += '<div style="background:rgba(54,162,235,0.06);border-left:3px solid var(--blue);' +
                'padding:0.6rem 1rem;border-radius:4px;font-size:0.85rem;color:var(--text-primary);">' +
                '<strong style="color:var(--blue);">Comparison Summary:</strong> ' +
                _escHtml(data.summary) + '</div>';
        }

        el.innerHTML = html;
    }

    function _miniStat(label, value) {
        return '<div style="display:flex;justify-content:space-between;font-size:0.72rem;' +
            'padding:0.05rem 0;border-bottom:1px solid rgba(255,255,255,0.03);">' +
            '<span style="color:var(--text-secondary);">' + label + '</span>' +
            '<span style="color:var(--text-secondary);font-weight:600;">' + value + '</span></div>';
    }

    function _truncId(id) {
        if (!id) return "—";
        return id.length > 16 ? id.substring(0, 14) + "\u2026" : id;
    }

    function _escHtml(s) {
        if (!s) return "";
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/comparison-matrix", function (data) {
            if (data.error) {
                el.innerHTML = '<div class="no-data"><div class="no-data-text">' + _escHtml(data.error) + '</div></div>';
                return;
            }
            render(el, data);
        }, {
            loadingText: 'Loading comparison matrix\u2026',
        });
    }

    // Auto-init
    _lc.addListener(document, "DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("comparison-matrix-container", function () {
                init("comparison-matrix-container", sid);
            });
        } else if (sid) {
            init("comparison-matrix-container", sid);
        }
    });

    window.ComparisonMatrix = { init: init };

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('comparison_matrix', {
        init: function () {},
        destroy: destroy
    });
})();
