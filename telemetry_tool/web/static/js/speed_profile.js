/**
 * speed_profile.js
 * ----------------
 * Renders track segment speed profile: zone-coloured bar chart,
 * speed envelope overlay, zone summary, and improvement hints.
 *
 * Public API:
 *   window.SpeedProfile.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    var ZONE_COLORS = {
        braking:      C.red || "#e74c3c",
        acceleration: C.green || "#4caf50",
        corner:       "#ff9800",
        straight:     "#36a2eb",
    };

    function render(el, data) {
        if (!data || data.n_laps < 2) {
            el.innerHTML = '<div class="no-data"><div class="no-data-text">' +
                (data && data.coaching ? esc(data.coaching) : "Not enough data for speed profile.") + '</div></div>';
            return;
        }

        var html = "";

        // Zone summary cards
        html += '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:1rem;">';
        (data.zone_summary || []).forEach(function (z) {
            var col = ZONE_COLORS[z.zone_type] || (C.textSecondary || "#888");
            html += '<div style="background:var(--card-bg);border-radius:8px;padding:0.5rem 0.8rem;' +
                'border-top:3px solid ' + col + ';min-width:120px;flex:1;max-width:180px;">';
            html += '<div style="font-size:0.8rem;font-weight:700;color:' + col + ';text-transform:capitalize;">' +
                z.zone_type + '</div>';
            html += _miniStat("Segments", z.count);
            html += _miniStat("Time Lost", z.total_time_loss_ms.toFixed(0) + "ms");
            html += _miniStat("Avg Speed", z.avg_speed_mps.toFixed(1) + " m/s");
            html += '</div>';
        });
        html += '</div>';

        // Segment chart canvas
        html += '<div style="margin-bottom:1rem;">';
        html += '<div style="font-size:0.75rem;color:var(--text-secondary);text-transform:uppercase;margin-bottom:0.3rem;">Segment Speed vs Best Lap</div>';
        html += '<canvas id="speed-profile-canvas" style="width:100%;"></canvas>';
        html += '</div>';

        // Time loss bar chart
        html += '<div style="margin-bottom:1rem;">';
        html += '<div style="font-size:0.75rem;color:var(--text-secondary);text-transform:uppercase;margin-bottom:0.3rem;">Time Loss by Segment</div>';
        html += '<canvas id="time-loss-canvas" style="width:100%;"></canvas>';
        html += '</div>';

        // Coaching
        if (data.coaching) {
            var borderCol = ZONE_COLORS[data.best_improvement_zone] || "#36a2eb";
            html += '<div style="background:rgba(54,162,235,0.06);border-left:3px solid ' + borderCol + ';' +
                'padding:0.6rem 1rem;border-radius:4px;font-size:0.85rem;color:var(--text-primary);">' +
                '<strong style="color:' + borderCol + ';">Speed Profile Insight:</strong> ' +
                esc(data.coaching) + '</div>';
        }

        el.innerHTML = html;

        _lc.addTimer(function () {
            _drawSpeedChart(data);
            _drawTimeLoss(data);

            // Register __redraw for ResizeObserver on dynamically created canvases
            var spCanvas = document.getElementById("speed-profile-canvas");
            if (spCanvas) {
                spCanvas.__redraw = function() { _drawSpeedChart(data); };
            }
            var tlCanvas = document.getElementById("time-loss-canvas");
            if (tlCanvas) {
                tlCanvas.__redraw = function() { _drawTimeLoss(data); };
            }
        }, 30);
    }

    function _drawSpeedChart(data) {
        var canvas = document.getElementById("speed-profile-canvas");
        if (!canvas) return;
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth || 700;
        var H = 240;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + "px";
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var pad = { top: 15, right: 15, bottom: 30, left: 50 };
        var plotW = W - pad.left - pad.right;
        var plotH = H - pad.top - pad.bottom;

        ctx.clearRect(0, 0, W, H);

        var segs = data.segments || [];
        if (segs.length === 0) return;

        // Find max speed for scale
        var maxSpeed = 0;
        segs.forEach(function (s) {
            if (s.max_speed_mps > maxSpeed) maxSpeed = s.max_speed_mps;
            if (s.best_lap_speed_mps > maxSpeed) maxSpeed = s.best_lap_speed_mps;
        });
        maxSpeed *= 1.1;

        var barW = plotW / segs.length;

        // Draw segment bars (mean speed)
        segs.forEach(function (s, i) {
            var barH = (s.mean_speed_mps / maxSpeed) * plotH;
            var x = pad.left + i * barW;
            var y = pad.top + plotH - barH;
            var col = ZONE_COLORS[s.zone_type] || (C.textSecondary || "#888");
            ctx.fillStyle = col + "60";
            ctx.fillRect(x + 1, y, barW - 2, barH);
            ctx.strokeStyle = col;
            ctx.lineWidth = 1;
            ctx.strokeRect(x + 1, y, barW - 2, barH);
        });

        // Best lap line
        ctx.beginPath();
        ctx.strokeStyle = C.yellow || "#ffd700";
        ctx.lineWidth = 2;
        segs.forEach(function (s, i) {
            var x = pad.left + (i + 0.5) * barW;
            var y = pad.top + plotH - (s.best_lap_speed_mps / maxSpeed) * plotH;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Axes
        ctx.strokeStyle = "#555";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top + plotH);
        ctx.lineTo(pad.left + plotW, pad.top + plotH);
        ctx.stroke();

        // X-axis labels
        ctx.fillStyle = C.textSecondary || "#888";
        ctx.font = "9px sans-serif";
        ctx.textAlign = "center";
        for (var i = 0; i < segs.length; i += 2) {
            ctx.fillText("S" + (i + 1), pad.left + (i + 0.5) * barW, pad.top + plotH + 14);
        }

        // Y-axis label
        ctx.save();
        ctx.translate(12, pad.top + plotH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = C.textSecondary || "#888";
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Speed (m/s)", 0, 0);
        ctx.restore();

        // Legend
        ctx.fillStyle = C.yellow || "#ffd700";
        ctx.font = "10px sans-serif";
        ctx.textAlign = "right";
        ctx.fillText("Best Lap", W - 10, 12);
    }

    function _drawTimeLoss(data) {
        var canvas = document.getElementById("time-loss-canvas");
        if (!canvas) return;
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth || 700;
        var H = 140;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + "px";
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var pad = { top: 10, right: 15, bottom: 25, left: 50 };
        var plotW = W - pad.left - pad.right;
        var plotH = H - pad.top - pad.bottom;

        ctx.clearRect(0, 0, W, H);

        var segs = data.segments || [];
        if (segs.length === 0) return;

        var maxLoss = 0;
        segs.forEach(function (s) { if (s.time_loss_ms > maxLoss) maxLoss = s.time_loss_ms; });
        if (maxLoss === 0) maxLoss = 1;
        maxLoss *= 1.1;

        var barW = plotW / segs.length;

        segs.forEach(function (s, i) {
            var barH = (s.time_loss_ms / maxLoss) * plotH;
            var x = pad.left + i * barW;
            var y = pad.top + plotH - barH;
            var col = ZONE_COLORS[s.zone_type] || (C.textSecondary || "#888");
            var isWorst = (s.segment_id === data.worst_segment_id);

            ctx.fillStyle = isWorst ? col : col + "80";
            ctx.fillRect(x + 1, y, barW - 2, barH);

            if (isWorst) {
                ctx.strokeStyle = C.yellow || "#ffd700";
                ctx.lineWidth = 2;
                ctx.strokeRect(x + 1, y, barW - 2, barH);
            }
        });

        // Axis
        ctx.strokeStyle = "#555";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top + plotH);
        ctx.lineTo(pad.left + plotW, pad.top + plotH);
        ctx.stroke();

        // Y label
        ctx.save();
        ctx.translate(12, pad.top + plotH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = C.textSecondary || "#888";
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Loss (ms)", 0, 0);
        ctx.restore();
    }

    function _miniStat(label, value) {
        return '<div style="display:flex;justify-content:space-between;font-size:0.72rem;' +
            'padding:0.05rem 0;border-bottom:1px solid rgba(255,255,255,0.03);">' +
            '<span style="color:var(--text-secondary);">' + label + '</span>' +
            '<span style="color:var(--text-primary);font-weight:600;">' + value + '</span></div>';
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/speed-profile", function (data) {
            if (data.error) {
                el.innerHTML = '<div class="no-data"><div class="no-data-text">' + esc(data.error) + '</div></div>';
                return;
            }
            render(el, data);
        }, {
            loadingText: 'Loading speed profile\u2026',
        });
    }

    // Auto-init
    _lc.addListener(document, "DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("speed-profile-container", function () {
                init("speed-profile-container", sid);
            });
        } else if (sid) {
            init("speed-profile-container", sid);
        }
    });

    window.SpeedProfile = { init: init };

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('speed_profile', {
        init: function () {},
        destroy: destroy
    });
})();
