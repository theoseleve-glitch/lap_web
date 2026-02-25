/**
 * energy_balance.js
 * -----------------
 * Renders energy balance analysis: per-lap energy bars (braking vs accel),
 * efficiency trend line, smoothness gauge, and coaching hints.
 *
 * Public API:
 *   window.EnergyBalance.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var C = window.Theme ? window.Theme.colors : {};

    var COLORS = {
        braking:  C.red || "#e74c3c",
        accel:    C.green || "#4caf50",
        eff:      "#36a2eb",
        smooth:   "#ff9800",
        text:     "#ccc",
        muted:    C.textSecondary || "#888",
    };

    function render(el, data) {
        if (!data || data.n_laps < 2) {
            el.innerHTML = '<div class="no-data"><div class="no-data-text">' +
                (data && data.coaching ? esc(data.coaching) : "Not enough data for energy analysis.") + '</div></div>';
            return;
        }

        var html = "";

        // Summary cards
        html += '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:1rem;">';
        html += _card("Laps", data.n_laps, COLORS.text);
        html += _card("Mass", (data.vehicle_mass_kg || 0).toFixed(0) + "kg", COLORS.text);
        html += _card("Recovery Ratio",
            (data.recovery_ratio || 0).toFixed(0) + "%",
            data.recovery_ratio > 110 ? COLORS.braking :
            data.recovery_ratio < 90 ? COLORS.accel : COLORS.text);
        html += _card("Total Braking", (data.total_braking_kj || 0).toFixed(1) + " kJ", COLORS.braking);
        html += _card("Total Accel", (data.total_accel_kj || 0).toFixed(1) + " kJ", COLORS.accel);
        html += '</div>';

        // Energy per-lap chart
        html += '<div style="margin-bottom:1rem;">';
        html += '<div style="font-size:0.75rem;color:var(--text-secondary);text-transform:uppercase;margin-bottom:0.3rem;">Energy Balance per Lap</div>';
        html += '<canvas id="energy-balance-canvas" width="700" height="220" style="width:100%;max-width:700px;"></canvas>';
        html += '</div>';

        // Coaching
        if (data.coaching) {
            html += '<div style="background:rgba(54,162,235,0.06);border-left:3px solid var(--blue);' +
                'padding:0.6rem 1rem;border-radius:4px;font-size:0.85rem;color:var(--text-primary);">' +
                '<strong style="color:var(--blue);">Energy Insight:</strong> ' +
                esc(data.coaching) + '</div>';
        }

        el.innerHTML = html;

        setTimeout(function () {
            _drawEnergyBars(data);
        }, 30);
    }

    function _drawEnergyBars(data) {
        var canvas = document.getElementById("energy-balance-canvas");
        if (!canvas) return;
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth || 700;
        var H = 220;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + "px";
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var pad = { top: 15, right: 15, bottom: 30, left: 55 };
        var plotW = W - pad.left - pad.right;
        var plotH = H - pad.top - pad.bottom;

        ctx.clearRect(0, 0, W, H);

        var laps = data.lap_metrics || [];
        if (laps.length === 0) return;

        var maxE = 0;
        laps.forEach(function (l) {
            if (l.braking_energy_kj > maxE) maxE = l.braking_energy_kj;
            if (l.accel_energy_kj > maxE) maxE = l.accel_energy_kj;
        });
        maxE *= 1.1;

        var barGroupW = plotW / laps.length;
        var barW = barGroupW * 0.35;

        laps.forEach(function (l, i) {
            var gx = pad.left + i * barGroupW;

            // Braking bar (left)
            var bH = (l.braking_energy_kj / maxE) * plotH;
            ctx.fillStyle = COLORS.braking + "90";
            ctx.fillRect(gx + 2, pad.top + plotH - bH, barW, bH);

            // Accel bar (right)
            var aH = (l.accel_energy_kj / maxE) * plotH;
            ctx.fillStyle = COLORS.accel + "90";
            ctx.fillRect(gx + barW + 3, pad.top + plotH - aH, barW, aH);

            // Lap label
            ctx.fillStyle = COLORS.muted;
            ctx.font = "9px sans-serif";
            ctx.textAlign = "center";
            if (i % Math.max(1, Math.floor(laps.length / 10)) === 0) {
                ctx.fillText("L" + l.lap_number, gx + barGroupW / 2, pad.top + plotH + 14);
            }
        });

        // Highlight worst braking laps
        var worstLaps = data.worst_braking_laps || [];
        laps.forEach(function (l, i) {
            if (worstLaps.indexOf(l.lap_number) !== -1) {
                var gx = pad.left + i * barGroupW;
                var bH = (l.braking_energy_kj / maxE) * plotH;
                ctx.strokeStyle = COLORS.braking;
                ctx.lineWidth = 2;
                ctx.strokeRect(gx + 1, pad.top + plotH - bH - 1, barW + 2, bH + 2);
            }
        });

        // Delta arrows vs previous lap
        laps.forEach(function (l, i) {
            if (i === 0) return;
            var prevBraking = laps[i - 1].braking_energy_kj;
            var delta = l.braking_energy_kj - prevBraking;
            if (Math.abs(delta) > 0.5) {
                var gx = pad.left + i * barGroupW;
                var bH = (l.braking_energy_kj / maxE) * plotH;
                var arrowX = gx + barGroupW / 2;
                var arrowY = pad.top + plotH - bH - 8;
                ctx.fillStyle = delta > 0 ? COLORS.braking : COLORS.accel;
                ctx.font = "10px sans-serif";
                ctx.textAlign = "center";
                ctx.fillText(delta > 0 ? "\u25B2" : "\u25BC", arrowX, arrowY);
            }
        });

        // Axes
        ctx.strokeStyle = "#555";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top + plotH);
        ctx.lineTo(pad.left + plotW, pad.top + plotH);
        ctx.stroke();

        // Y-axis label
        ctx.save();
        ctx.translate(12, pad.top + plotH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = COLORS.muted;
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Energy (kJ)", 0, 0);
        ctx.restore();

        // Legend
        ctx.fillStyle = COLORS.braking;
        ctx.fillRect(W - 120, 5, 10, 10);
        ctx.fillStyle = COLORS.muted;
        ctx.font = "10px sans-serif";
        ctx.textAlign = "left";
        ctx.fillText("Braking", W - 107, 14);

        ctx.fillStyle = COLORS.accel;
        ctx.fillRect(W - 55, 5, 10, 10);
        ctx.fillStyle = COLORS.muted;
        ctx.fillText("Accel", W - 42, 14);
    }

    function _card(label, value, color) {
        return '<div style="background:var(--card-bg);border-radius:8px;padding:0.3rem 0.6rem;' +
            'text-align:center;min-width:80px;">' +
            '<div style="font-size:0.6rem;color:var(--text-secondary);text-transform:uppercase;">' + label + '</div>' +
            '<div style="font-size:0.85rem;font-weight:700;color:' + color + ';">' + value + '</div>' +
            '</div>';
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/energy-balance", function (data) {
            render(el, data);
        }, {
            loadingText: 'Loading energy balance\u2026',
        });
    }

    // Auto-init
    document.addEventListener("DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("energy-balance-container", function () {
                init("energy-balance-container", sid);
            });
        } else if (sid) {
            init("energy-balance-container", sid);
        }
    });

    window.EnergyBalance = { init: init };
})();
