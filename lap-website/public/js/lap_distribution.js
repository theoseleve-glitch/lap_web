/**
 * lap_distribution.js
 * -------------------
 * Renders lap time distribution: histogram with KDE overlay, box-plot,
 * outlier badges, shape classification, and stats cards.
 *
 * Public API:
 *   window.LapDistribution.init(containerId, sessionId)
 */
(function () {
    "use strict";

    function esc(s) { if (!s) return ''; var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    var COLORS = {
        bar:      "rgba(54, 162, 235, 0.5)",
        barEdge:  "rgba(54, 162, 235, 0.8)",
        kde:      "#ff6384",
        median:   C.yellow || "#ffd700",
        q1q3:     "rgba(255, 215, 0, 0.15)",
        outlierSlow: C.red || "#e74c3c",
        outlierFast: C.green || "#4caf50",
        whisker:  C.textSecondary || "#aaa",
        text:     "#ccc",
        muted:    C.textSecondary || "#888",
        bg:       "var(--bg-secondary)",
    };

    var SHAPE_LABELS = {
        normal:       "Normal",
        right_skewed: "Right-Skewed",
        left_skewed:  "Left-Skewed",
        bimodal:      "Bimodal",
        tight:        "Tight Cluster",
    };

    function render(el, data) {
        if (!data || data.n_laps < 2) {
            el.innerHTML = '<div class="no-data"><div class="no-data-text">' +
                (data && data.coaching ? esc(data.coaching) : "Not enough data for distribution analysis.") + '</div></div>';
            return;
        }

        var html = "";

        // Stats cards row
        html += '<div style="display:flex;flex-wrap:wrap;gap:0.6rem;margin-bottom:1rem;">';
        html += _card("Laps", data.n_laps, COLORS.text);
        html += _card("Mean", (data.mean_s || 0).toFixed(3) + "s", "var(--blue)");
        html += _card("Std Dev", (data.std_s || 0).toFixed(3) + "s", COLORS.text);
        html += _card("Range", (data.range_s || 0).toFixed(3) + "s", COLORS.text);
        html += _card("Shape", esc(SHAPE_LABELS[data.shape] || data.shape || '—'), "#ff6384");
        html += _card("Median", data.quartiles ? data.quartiles.median.toFixed(3) + "s" : "—", COLORS.median);
        html += _card("IQR", data.quartiles ? data.quartiles.iqr.toFixed(3) + "s" : "—", COLORS.text);
        html += _card("Skewness", (data.skewness || 0).toFixed(2), COLORS.text);
        html += '</div>';

        // Canvas for histogram + KDE
        html += '<div style="margin-bottom:1rem;">';
        html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;margin-bottom:0.3rem;">Distribution</div>';
        html += '<canvas id="dist-canvas" style="width:100%;"></canvas>';
        html += '</div>';

        // Box plot (mini)
        html += '<div style="margin-bottom:1rem;">';
        html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;margin-bottom:0.3rem;">Box Plot</div>';
        html += '<canvas id="boxplot-canvas" style="width:100%;"></canvas>';
        html += '</div>';

        // Outliers
        if (data.outliers && data.outliers.length > 0) {
            html += '<div style="font-size:0.75rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;margin-bottom:0.3rem;">Outliers (' + data.outliers.length + ')</div>';
            html += '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:1rem;">';
            data.outliers.forEach(function (o) {
                var col = o.direction === "slow" ? COLORS.outlierSlow : COLORS.outlierFast;
                var icon = o.direction === "slow" ? "\u25BC" : "\u25B2";
                html += '<span style="background:' + col + '15;color:' + col + ';padding:0.2rem 0.5rem;' +
                    'border-radius:10px;font-size:0.72rem;border:1px solid ' + col + '40;">' +
                    icon + ' L' + o.lap_number + ' ' + o.lap_time_s.toFixed(3) + 's (' +
                    (o.direction === "slow" ? "+" : "-") + o.deviation_s.toFixed(3) + 's)</span>';
            });
            html += '</div>';
        }

        // Coaching
        if (data.coaching) {
            html += '<div style="background:rgba(54,162,235,0.06);border-left:3px solid var(--blue);' +
                'padding:0.6rem 1rem;border-radius:4px;font-size:0.85rem;color:var(--text-primary);">' +
                '<strong style="color:var(--blue);">Distribution Insight:</strong> ' +
                esc(data.coaching) + '</div>';
        }

        el.innerHTML = html;

        // Draw charts after DOM update
        _lc.addTimer(function () {
            _drawHistogram(data);
            _drawBoxplot(data);

            // Register __redraw for ResizeObserver on dynamically created canvases
            var distCanvas = document.getElementById("dist-canvas");
            if (distCanvas) {
                distCanvas.__redraw = function() { _drawHistogram(data); };
            }
            var boxCanvas = document.getElementById("boxplot-canvas");
            if (boxCanvas) {
                boxCanvas.__redraw = function() { _drawBoxplot(data); };
            }
        }, 30);
    }

    function _drawHistogram(data) {
        var canvas = document.getElementById("dist-canvas");
        if (!canvas) return;
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth || 700;
        var H = 280;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + "px";
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var pad = { top: 15, right: 20, bottom: 35, left: 55 };
        var plotW = W - pad.left - pad.right;
        var plotH = H - pad.top - pad.bottom;

        ctx.clearRect(0, 0, W, H);

        var bins = data.histogram || [];
        if (bins.length === 0) return;

        var maxFreq = 0;
        bins.forEach(function (b) { if (b.frequency > maxFreq) maxFreq = b.frequency; });

        var xMin = bins[0].bin_start;
        var xMax = bins[bins.length - 1].bin_end;
        var xRange = xMax - xMin || 1;

        // Scale KDE to histogram frequency
        var kdeMaxY = 0;
        if (data.kde_y) {
            data.kde_y.forEach(function (v) { if (v > kdeMaxY) kdeMaxY = v; });
        }

        // Draw histogram bars
        var barW = plotW / bins.length;
        bins.forEach(function (b, i) {
            var barH = (b.frequency / (maxFreq * 1.1)) * plotH;
            var x = pad.left + i * barW;
            var y = pad.top + plotH - barH;
            ctx.fillStyle = COLORS.bar;
            ctx.fillRect(x, y, barW - 1, barH);
            ctx.strokeStyle = COLORS.barEdge;
            ctx.lineWidth = 1;
            ctx.strokeRect(x, y, barW - 1, barH);
        });

        // Draw KDE overlay
        if (data.kde_x && data.kde_x.length > 1 && kdeMaxY > 0) {
            var kdeScale = maxFreq / kdeMaxY;
            ctx.beginPath();
            ctx.strokeStyle = COLORS.kde;
            ctx.lineWidth = 2;
            for (var i = 0; i < data.kde_x.length; i++) {
                var kx = pad.left + ((data.kde_x[i] - xMin) / xRange) * plotW;
                var ky = pad.top + plotH - ((data.kde_y[i] * kdeScale) / (maxFreq * 1.1)) * plotH;
                if (i === 0) ctx.moveTo(kx, ky);
                else ctx.lineTo(kx, ky);
            }
            ctx.stroke();
        }

        // Draw median line
        var medX = pad.left + ((data.quartiles.median - xMin) / xRange) * plotW;
        ctx.beginPath();
        ctx.strokeStyle = COLORS.median;
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.moveTo(medX, pad.top);
        ctx.lineTo(medX, pad.top + plotH);
        ctx.stroke();
        ctx.setLineDash([]);

        // Axes
        ctx.strokeStyle = "#555";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top + plotH);
        ctx.lineTo(pad.left + plotW, pad.top + plotH);
        ctx.stroke();

        // X-axis labels
        ctx.fillStyle = COLORS.muted;
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        var nLabels = Math.min(6, bins.length);
        var step = Math.max(1, Math.floor(bins.length / nLabels));
        for (var j = 0; j < bins.length; j += step) {
            var lx = pad.left + (j + 0.5) * barW;
            ctx.fillText(bins[j].bin_center.toFixed(2), lx, pad.top + plotH + 14);
        }

        // Y-axis label
        ctx.save();
        ctx.translate(12, pad.top + plotH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = COLORS.muted;
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Frequency", 0, 0);
        ctx.restore();

        // Legend
        ctx.fillStyle = COLORS.kde;
        ctx.font = "10px sans-serif";
        ctx.textAlign = "left";
        ctx.fillText("KDE", W - 60, 12);
        ctx.fillStyle = COLORS.median;
        ctx.fillText("Median", W - 60, 24);
    }

    function _drawBoxplot(data) {
        var canvas = document.getElementById("boxplot-canvas");
        if (!canvas) return;
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth || 700;
        var H = 60;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + "px";
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var pad = { left: 55, right: 20 };
        var plotW = W - pad.left - pad.right;
        var midY = H / 2;

        ctx.clearRect(0, 0, W, H);

        var q = data.quartiles;
        var xMin = q.lower_whisker - q.iqr * 0.3;
        var xMax = q.upper_whisker + q.iqr * 0.3;
        var xRange = xMax - xMin || 1;

        function toX(val) { return pad.left + ((val - xMin) / xRange) * plotW; }

        // Whisker line
        ctx.strokeStyle = COLORS.whisker;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(toX(q.lower_whisker), midY);
        ctx.lineTo(toX(q.upper_whisker), midY);
        ctx.stroke();

        // Whisker caps
        [q.lower_whisker, q.upper_whisker].forEach(function (w) {
            ctx.beginPath();
            ctx.moveTo(toX(w), midY - 10);
            ctx.lineTo(toX(w), midY + 10);
            ctx.stroke();
        });

        // Q1-Q3 box
        var boxLeft = toX(q.q1);
        var boxRight = toX(q.q3);
        ctx.fillStyle = COLORS.q1q3;
        ctx.fillRect(boxLeft, midY - 15, boxRight - boxLeft, 30);
        ctx.strokeStyle = COLORS.median;
        ctx.lineWidth = 1;
        ctx.strokeRect(boxLeft, midY - 15, boxRight - boxLeft, 30);

        // Median line
        ctx.beginPath();
        ctx.strokeStyle = COLORS.median;
        ctx.lineWidth = 2;
        var mx = toX(q.median);
        ctx.moveTo(mx, midY - 15);
        ctx.lineTo(mx, midY + 15);
        ctx.stroke();

        // Labels
        ctx.fillStyle = COLORS.muted;
        ctx.font = "9px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Q1:" + q.q1.toFixed(3), boxLeft, midY + 28);
        ctx.fillText("Med:" + q.median.toFixed(3), mx, midY - 20);
        ctx.fillText("Q3:" + q.q3.toFixed(3), boxRight, midY + 28);

        // Outlier dots
        if (data.outliers) {
            data.outliers.forEach(function (o) {
                var ox = toX(o.lap_time_s);
                if (ox >= pad.left && ox <= W - pad.right) {
                    ctx.beginPath();
                    ctx.arc(ox, midY, 4, 0, Math.PI * 2);
                    ctx.fillStyle = o.direction === "slow" ? COLORS.outlierSlow : COLORS.outlierFast;
                    ctx.fill();
                }
            });
        }
    }

    function _card(label, value, color) {
        return '<div style="background:var(--bg-secondary);border-radius:8px;padding:0.3rem 0.6rem;' +
            'text-align:center;min-width:70px;">' +
            '<div style="font-size:0.6rem;color:' + (C.textSecondary || "#aaa") + ';text-transform:uppercase;">' + label + '</div>' +
            '<div style="font-size:0.9rem;font-weight:700;color:' + color + ';">' + value + '</div>' +
            '</div>';
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/lap-distribution", function (data) {
            if (data.error) {
                el.innerHTML = '<div class="no-data"><div class="no-data-text">' + esc(data.error) + '</div></div>';
                return;
            }
            render(el, data);
        }, {
            loadingText: 'Loading lap distribution\u2026',
        });
    }

    // Auto-init
    _lc.addListener(document, "DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("lap-distribution-container", function () {
                init("lap-distribution-container", sid);
            });
        } else if (sid) {
            init("lap-distribution-container", sid);
        }
    });

    window.LapDistribution = { init: init };

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('lap_distribution', {
        init: function () {},
        destroy: destroy
    });
})();
