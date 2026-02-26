/**
 * session_timeline.js
 * -------------------
 * Renders the Session Replay Timeline as an interactive event feed.
 * Shows a vertical timeline with lap events, severity badges, and a summary.
 *
 * Public API:
 *   window.SessionTimeline.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    var SEVERITY_COLORS = {
        highlight: { bg: "rgba(255, 215, 0, 0.12)", border: C.yellow || "#ffd700", icon: "star" },
        positive:  { bg: "rgba(76, 175, 80, 0.10)", border: C.green || "#4caf50", icon: "check" },
        warning:   { bg: "rgba(255, 152, 0, 0.10)", border: "#ff9800", icon: "alert" },
        info:      { bg: "rgba(54, 162, 235, 0.08)", border: "#36a2eb", icon: "info" },
    };

    var EVENT_ICONS = {
        pb:              "\u2605",   // star
        hot_lap:         "\u26A1",   // lightning
        slow_lap:        "\u26A0",   // warning
        momentum_up:     "\u2191",   // up arrow
        momentum_down:   "\u2193",   // down arrow
        first_lap:       "\u25B6",   // play
        final_lap:       "\u2588",   // block (finish)
        consistent_run:  "\u2261",   // triple bar
        stint_start:     "\u27A4",   // arrow
    };

    function render(el, data) {
        if (!data || data.total_laps === 0) {
            el.innerHTML = '<div class="no-data"><div class="no-data-text">No timeline data available.</div></div>';
            return;
        }

        var html = "";

        // Summary bar
        html += '<div style="display:flex;flex-wrap:wrap;gap:0.8rem;margin-bottom:1rem;">';
        html += _summaryCard("Total Laps", data.total_laps, "var(--blue)");
        html += _summaryCard("Best Lap", "L" + (data.best_lap || '?') + " (" + (data.best_time_s || 0).toFixed(3) + "s)", C.yellow || "#ffd700");

        var counts = data.event_counts || {};
        var pbCount = counts.pb || 0;
        var slowCount = counts.slow_lap || 0;
        var hotCount = counts.hot_lap || 0;
        html += _summaryCard("PBs Set", pbCount, C.green || "#4caf50");
        html += _summaryCard("Hot Laps", hotCount, "var(--accent)");
        if (slowCount > 0) {
            html += _summaryCard("Slow Laps", slowCount, C.red || "#e74c3c");
        }
        html += '</div>';

        // Summary text
        if (data.summary) {
            html += '<div style="background:rgba(54,162,235,0.06);padding:0.6rem 1rem;' +
                'border-radius:6px;font-size:0.85rem;color:var(--text-secondary);margin-bottom:1rem;">' +
                data.summary + '</div>';
        }

        // Timeline events
        var events = data.events || [];
        if (events.length > 0) {
            html += '<div style="position:relative;padding-left:30px;">';

            // Vertical line
            html += '<div style="position:absolute;left:12px;top:0;bottom:0;' +
                'width:2px;background:rgba(160,160,160,0.2);"></div>';

            events.forEach(function (evt, idx) {
                var sev = SEVERITY_COLORS[evt.severity] || SEVERITY_COLORS.info;
                var icon = EVENT_ICONS[evt.event_type] || "\u2022";

                html += '<div style="position:relative;margin-bottom:0.6rem;padding:0.5rem 0.8rem;' +
                    'background:' + sev.bg + ';border-left:3px solid ' + sev.border + ';' +
                    'border-radius:0 6px 6px 0;">';

                // Dot on timeline
                html += '<div style="position:absolute;left:-24px;top:50%;transform:translateY(-50%);' +
                    'width:12px;height:12px;border-radius:50%;background:' + sev.border + ';' +
                    'border:2px solid var(--bg-primary, #1a1a2e);z-index:1;"></div>';

                // Header row
                html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
                html += '<span style="font-size:0.85rem;font-weight:600;color:' + sev.border + ';">';
                html += icon + ' Lap ' + evt.lap;
                html += '</span>';
                html += '<span style="font-size:0.75rem;color:' + (C.textSecondary || "#888") + ';">';
                html += evt.lap_time_s.toFixed(3) + 's';
                if (evt.delta_to_best_s > 0) {
                    html += ' (+' + evt.delta_to_best_s.toFixed(3) + ')';
                }
                html += '</span>';
                html += '</div>';

                // Description
                html += '<div style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.2rem;">';
                html += evt.description;
                html += '</div>';

                html += '</div>';
            });

            html += '</div>';
        }

        el.innerHTML = html;
    }

    function _summaryCard(label, value, color) {
        return '<div style="background:var(--bg-secondary);border-radius:8px;padding:0.4rem 0.8rem;' +
            'text-align:center;min-width:80px;">' +
            '<div style="font-size:0.65rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">' + label + '</div>' +
            '<div style="font-size:1rem;font-weight:700;color:' + color + ';">' + value + '</div>' +
            '</div>';
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/timeline", function(data) {
            try { render(el, data); } catch(e) { console.error('Timeline render error:', e); el.innerHTML = '<div class="no-data"><div class="no-data-text">Failed to render timeline data.</div></div>'; }
        }, {
            loadingText: 'Loading timeline\u2026',
        });
    }

    // Auto-init
    _lc.addListener(document, "DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("session-timeline-container", function () {
                init("session-timeline-container", sid);
            });
        } else if (sid) {
            init("session-timeline-container", sid);
        }
    });

    function destroy() {
        _lc.destroyAll();
    }

    window.SessionTimeline = { init: init };

    window.ModuleManager.register('session_timeline', {
        init: function () {},
        destroy: destroy
    });
})();
