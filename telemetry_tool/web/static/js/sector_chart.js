/**
 * sector_chart.js
 * ---------------
 * Renders sector performance analysis: ideal lap card, per-sector stats,
 * sector heatmap grid, and coaching hints.
 *
 * Public API:
 *   window.SectorChart.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var C = window.Theme ? window.Theme.colors : {};

    var COLORS = {
        best:   C.yellow || "#ffd700",
        good:   C.green || "#4caf50",
        avg:    "#36a2eb",
        warn:   "#ff9800",
        poor:   C.red || "#e74c3c",
        text:   "#ccc",
        muted:  C.textSecondary || "#888",
        bg:     "var(--card-bg)",
    };

    function cellColor(val, best, worst) {
        if (worst === best) return COLORS.avg;
        var ratio = (val - best) / (worst - best);
        if (ratio < 0.25) return COLORS.good;
        if (ratio < 0.5) return COLORS.avg;
        if (ratio < 0.75) return COLORS.warn;
        return COLORS.poor;
    }

    function render(el, data) {
        if (!data || data.n_laps === 0) {
            el.innerHTML = '<div class="no-data"><div class="no-data-text">Not enough data for sector analysis.</div></div>';
            if (data && data.coaching) {
                el.innerHTML += '<div class="no-data"><div class="no-data-text">' + esc(data.coaching) + '</div></div>';
            }
            return;
        }

        var html = "";
        var stats = data.sector_stats || [];
        var timings = data.sector_timings || [];
        var ns = data.n_sectors || 3;

        // Ideal lap card
        html += '<div style="display:flex;flex-wrap:wrap;gap:0.8rem;margin-bottom:1rem;">';
        html += _card("Ideal Sector Lap", data.ideal_lap_time_s != null ? data.ideal_lap_time_s.toFixed(3) + "s" : "—", COLORS.best);
        html += _card("Actual Best", data.actual_best_lap_time_s != null ? data.actual_best_lap_time_s.toFixed(3) + "s" : "—", COLORS.avg);
        if (data.ideal_gap_s > 0) {
            html += _card("Potential Gain", "-" + data.ideal_gap_s.toFixed(3) + "s", COLORS.good);
        }
        html += _card("Sectors", data.n_sectors, COLORS.text);
        html += _card("Laps Analyzed", data.n_laps, COLORS.text);
        html += '</div>';

        // Per-sector stats bars
        html += '<div style="margin-bottom:1rem;">';
        html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;margin-bottom:0.4rem;">Sector Breakdown</div>';

        var maxLoss = 0;
        stats.forEach(function(s) { if (s.loss_vs_best_s > maxLoss) maxLoss = s.loss_vs_best_s; });

        stats.forEach(function(ss) {
            var barPct = maxLoss > 0 ? (ss.loss_vs_best_s / maxLoss * 100) : 0;
            var barColor = ss.weakness_rank === 1 ? COLORS.poor :
                           ss.weakness_rank === ns ? COLORS.good : COLORS.warn;

            html += '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;">';
            html += '<span style="width:30px;font-size:0.85rem;font-weight:600;color:' + COLORS.text + ';">' +
                    esc(ss.sector_label) + '</span>';

            // Stats
            html += '<span style="width:70px;font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';">Best: ' +
                    ss.best_time_s.toFixed(3) + '</span>';

            // Loss bar
            html += '<div style="flex:1;background:rgba(255,255,255,0.06);border-radius:4px;height:14px;overflow:hidden;">';
            html += '<div style="width:' + Math.max(2, barPct) + '%;height:100%;background:' + barColor +
                    ';border-radius:4px;transition:width 0.5s ease;"></div>';
            html += '</div>';

            html += '<span style="width:65px;font-size:0.75rem;color:' + barColor + ';text-align:right;">' +
                    '+' + ss.loss_vs_best_s.toFixed(3) + 's</span>';
            html += '<span style="width:50px;font-size:0.7rem;color:' + (C.textSecondary || "#888") + ';">CV ' +
                    ss.cv_pct.toFixed(1) + '%</span>';
            html += '</div>';
        });
        html += '</div>';

        // Sector heatmap grid (laps x sectors)
        if (timings.length > 0 && timings.length <= 40) {
            html += '<div style="margin-bottom:1rem;">';
            html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;margin-bottom:0.3rem;">Sector Heatmap (Lap x Sector)</div>';
            html += '<div style="overflow-x:auto;">';
            html += '<table style="border-collapse:collapse;font-size:0.75rem;width:100%;">';

            // Header
            html += '<tr>';
            html += '<th style="padding:3px 6px;color:' + (C.textSecondary || "#888") + ';text-align:left;">Lap</th>';
            for (var s = 0; s < ns; s++) {
                html += '<th style="padding:3px 6px;color:' + (C.textSecondary || "#aaa") + ';">S' + (s + 1) + '</th>';
            }
            html += '<th style="padding:3px 6px;color:' + (C.textSecondary || "#aaa") + ';">Total</th>';
            html += '</tr>';

            // Find global min/max for color scale
            var allSectorTimes = [];
            timings.forEach(function(lt) {
                lt.forEach(function(st) { if (st.sector_time_s > 0) allSectorTimes.push(st.sector_time_s); });
            });
            var globalMin = Math.min.apply(null, allSectorTimes);
            var globalMax = Math.max.apply(null, allSectorTimes);

            timings.forEach(function(lapSectors, idx) {
                var lapTotal = 0;
                html += '<tr>';
                html += '<td style="padding:2px 6px;color:var(--text-secondary);font-weight:600;">L' +
                        lapSectors[0].lap_number + '</td>';
                for (var si = 0; si < ns; si++) {
                    var st = lapSectors[si] || {};
                    var t = st.sector_time_s || 0;
                    lapTotal += t;
                    var bg = cellColor(t, globalMin, globalMax);
                    var border = st.is_best_in_sector ? '2px solid ' + COLORS.best : '1px solid rgba(100,100,100,0.2)';
                    html += '<td style="padding:2px 6px;text-align:center;color:' + (C.textPrimary || "#ddd") + ';' +
                            'background:' + bg + '20;border:' + border + ';">' +
                            t.toFixed(3) + '</td>';
                }
                html += '<td style="padding:2px 6px;text-align:center;color:' + (C.textSecondary || "#aaa") + ';font-weight:600;">' +
                        lapTotal.toFixed(3) + '</td>';
                html += '</tr>';
            });

            html += '</table></div></div>';
        }

        // Coaching
        if (data.coaching) {
            html += '<div style="background:rgba(255,215,0,0.06);border-left:3px solid ' + (C.yellow || "#ffd700") + ';' +
                'padding:0.7rem 1rem;border-radius:4px;font-size:0.9rem;color:var(--text-primary);line-height:1.5;">' +
                '<strong style="color:' + (C.yellow || "#ffd700") + ';">Sector Insight:</strong> ' +
                esc(data.coaching) + '</div>';
        }

        el.innerHTML = html;
    }

    function _card(label, value, color) {
        return '<div style="background:' + COLORS.bg + ';border-radius:8px;padding:0.4rem 0.8rem;' +
            'text-align:center;min-width:80px;">' +
            '<div style="font-size:0.65rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">' + label + '</div>' +
            '<div style="font-size:1rem;font-weight:700;color:' + color + ';">' + value + '</div>' +
            '</div>';
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/sector-analysis", function (data) {
            if (data.error) {
                el.innerHTML = '<div class="no-data"><div class="no-data-text">' + esc(data.error) + '</div></div>';
                return;
            }
            render(el, data);
        }, {
            loadingText: 'Loading sector analysis\u2026',
        });
    }

    // Auto-init
    document.addEventListener("DOMContentLoaded", function() {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("sector-analysis-container", function () {
                init("sector-analysis-container", sid);
            });
        } else if (sid) {
            init("sector-analysis-container", sid);
        }
    });

    window.SectorChart = { init: init };
})();
