/**
 * corner_mastery.js
 * -----------------
 * Renders per-corner mastery report cards with radar charts and grades.
 */
(function () {
    "use strict";

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    var container;

    function _doInit() {
        var T = window.TELEMETRY;
        if (!T || !T.sessionId) return;

        container = document.getElementById("corner-mastery-container");
        if (!container) return;

        var url = "/api/session/" + encodeURIComponent(T.sessionId) + "/corner-mastery";

        FetchHelper.load(container, url, function (data) {
            try { render(data); } catch(e) { console.error('Corner mastery render error:', e); container.innerHTML = '<div class="no-data"><div class="no-data-text">Failed to render corner mastery data.</div></div>'; }
        }, {
            loadingText: 'Loading corner mastery\u2026',
            emptyCheck: function (data) { return !data || !data.corners || data.corners.length === 0; },
            emptyIcon: '&#x1F3CE;',
            emptyText: 'No corner mastery data available for this session.',
        });
    }

    _lc.addListener(document, "DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("corner-mastery-container", function () {
                _doInit();
            });
        } else if (sid) {
            _doInit();
        }
    });

    function gradeColor(grade) {
        switch (grade) {
            case "S": return C.purple || "#a855f7";
            case "A": return C.green  || "#22c55e";
            case "B": return C.blue   || "#60a5fa";
            case "C": return C.yellow || "#eab308";
            case "D": return C.accent || "#f97316";
            default:  return C.red    || "#ef4444";
        }
    }

    function scoreColor(s) {
        if (s >= 85) return C.green  || "#22c55e";
        if (s >= 65) return C.blue   || "#60a5fa";
        if (s >= 50) return C.yellow || "#eab308";
        return C.red || "#ef4444";
    }

    function render(data) {
        if (!data || !data.corners || data.corners.length === 0) {
            container.innerHTML = '<div class="no-data"><div class="no-data-text">No corner data available.</div></div>';
            return;
        }

        var html = '';

        // Overall summary bar
        var ovr = data.overall_mastery || 0;
        var oGrade = data.overall_grade || "F";
        html += '<div style="display:flex;align-items:center;gap:16px;margin-bottom:16px;'
            + 'padding:12px 16px;background:' + (C.bgCard || '#1a1a2e') + ';border-radius:8px;border:1px solid ' + (C.bgTertiary || '#333') + ';">'
            + '<div style="font-size:36px;font-weight:800;color:' + gradeColor(oGrade) + ';">'
            + oGrade + '</div>'
            + '<div>'
            + '<div style="font-size:18px;font-weight:700;color:' + (C.textPrimary || '#e0e0f0') + ';">Overall Corner Mastery: '
            + ovr.toFixed(0) + '/100</div>'
            + '<div style="font-size:12px;color:' + (C.textSecondary || '#888') + ';">' + (data.summary || '') + '</div>'
            + '</div></div>';

        // Corner cards
        html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;">';

        for (var i = 0; i < data.corners.length; i++) {
            var c = data.corners[i];
            var gClr = gradeColor(c.grade || 'C');
            html += '<div style="background:' + (C.bgCard || '#1a1a2e') + ';border:1px solid ' + (C.bgTertiary || '#333') + ';border-radius:8px;padding:14px;">';

            // Header
            html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
                + '<div style="font-size:16px;font-weight:700;color:' + (C.textPrimary || '#e0e0f0') + ';">Corner ' + c.corner_id + '</div>'
                + '<div style="font-size:28px;font-weight:800;color:' + gClr + ';">' + (c.grade || '—') + '</div>'
                + '</div>';

            // Score bar
            html += '<div style="font-size:22px;font-weight:700;color:var(--text-primary);margin-bottom:8px;">'
                + (c.mastery_score || 0).toFixed(0) + '<span style="font-size:14px;color:' + (C.textSecondary || '#888') + ';">/100</span></div>';

            // Sub-score bars
            var subs = [
                { name: "Brake", val: c.brake_precision_score || 0 },
                { name: "Apex", val: c.apex_speed_score || 0 },
                { name: "Exit", val: c.exit_utilisation_score || 0 },
                { name: "Consistency", val: c.consistency_score || 0 },
                { name: "Grip", val: c.grip_utilisation_score || 0 },
            ];

            for (var j = 0; j < subs.length; j++) {
                var s = subs[j];
                var sc = scoreColor(s.val);
                html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
                    + '<div style="width:70px;font-size:11px;color:' + (C.textSecondary || '#888') + ';">' + s.name + '</div>'
                    + '<div style="flex:1;height:6px;background:' + (C.bgTertiary || '#333') + ';border-radius:3px;overflow:hidden;">'
                    + '<div style="width:' + s.val + '%;height:100%;background:' + sc
                    + ';border-radius:3px;transition:width 0.5s;"></div></div>'
                    + '<div style="width:30px;font-size:11px;color:' + sc + ';text-align:right;">'
                    + s.val.toFixed(0) + '</div></div>';
            }

            // Strengths/weaknesses
            html += '<div style="margin-top:8px;font-size:11px;">'
                + '<span style="color:' + (C.green || '#22c55e') + ';">+ ' + (c.strongest_area || '') + '</span> | '
                + '<span style="color:' + (C.red || '#ef4444') + ';">- ' + (c.weakest_area || '') + '</span></div>';

            // Coaching
            if (c.coaching_hint) {
                html += '<div style="margin-top:6px;font-size:11px;color:var(--text-secondary);font-style:italic;'
                    + 'border-top:1px solid ' + (C.bgTertiary || '#333') + ';padding-top:6px;">'
                    + c.coaching_hint + '</div>';
            }

            html += '</div>';
        }

        html += '</div>';
        container.innerHTML = html;
    }

    function destroy() {
        _lc.destroyAll();
        container = null;
    }

    window.ModuleManager.register('corner_mastery', {
        init: function () {},
        destroy: destroy
    });
})();
