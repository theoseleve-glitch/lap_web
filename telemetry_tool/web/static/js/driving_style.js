/**
 * driving_style.js
 * ----------------
 * Renders enriched driving style: style badge, feature gauges with
 * qualitative labels and coaching tooltips, radar chart, strengths/weaknesses.
 *
 * Public API:
 *   window.DrivingStyle.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var C = window.Theme ? window.Theme.colors : {};

    var RATING_COLORS = {
        excellent:  C.green  || "#4caf50",
        good:       "#36a2eb",
        average:    "#ff9800",
        needs_work: C.red    || "#e74c3c",
    };

    var STYLE_COLORS = {
        smooth:       "#58a6ff",
        aggressive:   "#ff8a82",
        conservative: "#e5a73a",
        adaptive:     "#c89cff",
    };

    function render(el, data) {
        if (!data || !data.features || data.features.length === 0) {
            el.textContent = data && data.error ? data.error : "No driving style data available.";
            return;
        }

        var frag = document.createDocumentFragment();

        // ── Style header ─────────────────────────────────
        var header = _el("div", "dstyle-header");

        var labelBadge = _el("span", "dstyle-label-badge");
        var styleKey = (data.style_label || "").toLowerCase().replace(/\s+/g, "_");
        var styleCol = STYLE_COLORS[styleKey] || (C.accent || "#ff6b35");
        labelBadge.textContent = data.style_label || "Unknown";
        labelBadge.style.color = styleCol;
        labelBadge.style.background = styleCol + "1a";
        labelBadge.style.borderColor = styleCol + "40";
        header.appendChild(labelBadge);

        if (data.style_confidence) {
            var conf = _text("span", "dstyle-confidence",
                Math.round(data.style_confidence * 100) + "% confidence");
            header.appendChild(conf);
        }

        frag.appendChild(header);

        if (data.style_description) {
            var desc = _text("p", "dstyle-description", data.style_description);
            frag.appendChild(desc);
        }

        // ── Feature gauges ───────────────────────────────
        var gaugeSection = _el("div", "dstyle-layout");
        var gaugeList = _el("div", "dstyle-gauge-list");

        data.features.forEach(function (f) {
            if (f.value === null) return;

            var row = _el("div", "dstyle-gauge-row");

            // Feature name with hint tooltip
            var name = _el("span", "dstyle-gauge-name tip tip-right tip-wrap");
            name.setAttribute("data-tip", f.hint);
            name.textContent = f.label;
            row.appendChild(name);

            // Gauge bar
            var bar = _el("div", "dstyle-gauge-track");
            bar.setAttribute("role", "progressbar");
            bar.setAttribute("aria-valuenow", String(f.value));
            bar.setAttribute("aria-valuemin", "0");
            bar.setAttribute("aria-valuemax", "1");
            bar.setAttribute("aria-label", f.label);

            var fill = _el("div", "dstyle-gauge-fill");
            var pct = Math.round(f.value * 100);
            fill.style.width = pct + "%";
            fill.style.background = RATING_COLORS[f.rating] || "#ff9800";
            bar.appendChild(fill);
            row.appendChild(bar);

            // Qualitative label with coaching tip tooltip
            var qual = _el("span", "dstyle-gauge-qual tip tip-left tip-wrap");
            qual.setAttribute("data-tip", f.tip);
            qual.textContent = f.qualitative;
            qual.style.color = RATING_COLORS[f.rating] || "#ff9800";
            row.appendChild(qual);

            gaugeList.appendChild(row);
        });

        gaugeSection.appendChild(gaugeList);

        // ── Radar chart ──────────────────────────────────
        var radarWrap = _el("div", "dstyle-radar-wrap");
        var canvas = document.createElement("canvas");
        canvas.id = "dstyle-radar-canvas";
        canvas.className = "dstyle-radar-canvas";
        canvas.setAttribute("aria-label", "Driving style radar chart");
        radarWrap.appendChild(canvas);
        gaugeSection.appendChild(radarWrap);

        frag.appendChild(gaugeSection);

        // ── Strengths / Weaknesses ───────────────────────
        if ((data.strengths && data.strengths.length) || (data.weaknesses && data.weaknesses.length)) {
            var grid = _el("div", "dstyle-insights");

            if (data.strengths && data.strengths.length) {
                var good = _el("div", "insight-box good");
                good.appendChild(_text("h3", "", "Style Strengths"));
                var ul = document.createElement("ul");
                data.strengths.forEach(function (s) {
                    ul.appendChild(_text("li", "", s));
                });
                good.appendChild(ul);
                grid.appendChild(good);
            }

            if (data.weaknesses && data.weaknesses.length) {
                var warn = _el("div", "insight-box warn");
                warn.appendChild(_text("h3", "", "Style Weaknesses"));
                var ul2 = document.createElement("ul");
                data.weaknesses.forEach(function (w) {
                    ul2.appendChild(_text("li", "", w));
                });
                warn.appendChild(ul2);
                grid.appendChild(warn);
            }

            frag.appendChild(grid);
        }

        el.textContent = "";
        el.appendChild(frag);

        // Draw radar after DOM insertion
        setTimeout(function () {
            _drawRadar(data.radar_labels || [], data.radar_values || []);
        }, 30);
    }

    function _drawRadar(labels, values) {
        var canvas = document.getElementById("dstyle-radar-canvas");
        if (!canvas || labels.length === 0) return;
        canvas.__redraw = function() { _drawRadar(labels, values); };
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth || 300;
        var H = W;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + "px";
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var cx = W / 2, cy = H / 2;
        var radius = Math.min(cx, cy) - 30;
        ctx.clearRect(0, 0, W, H);

        var n = labels.length;
        var angleStep = (2 * Math.PI) / n;

        // Grid rings
        [0.25, 0.5, 0.75, 1.0].forEach(function (pct) {
            ctx.beginPath();
            ctx.strokeStyle = "rgba(255,255,255,0.08)";
            ctx.lineWidth = 1;
            for (var i = 0; i <= n; i++) {
                var angle = -Math.PI / 2 + i * angleStep;
                var x = cx + Math.cos(angle) * radius * pct;
                var y = cy + Math.sin(angle) * radius * pct;
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
            ctx.stroke();
        });

        // Spoke lines
        ctx.strokeStyle = "rgba(255,255,255,0.05)";
        ctx.lineWidth = 1;
        for (var s = 0; s < n; s++) {
            var a = -Math.PI / 2 + s * angleStep;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(cx + Math.cos(a) * radius, cy + Math.sin(a) * radius);
            ctx.stroke();
        }

        // Data polygon
        ctx.beginPath();
        var grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
        grad.addColorStop(0, "rgba(255,107,53,0.35)");
        grad.addColorStop(1, "rgba(255,107,53,0.08)");
        ctx.fillStyle = grad;
        ctx.strokeStyle = "rgba(255,107,53,0.9)";
        ctx.lineWidth = 2;
        values.forEach(function (val, i) {
            var angle = -Math.PI / 2 + i * angleStep;
            var x = cx + Math.cos(angle) * radius * val;
            var y = cy + Math.sin(angle) * radius * val;
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Data dots
        values.forEach(function (val, i) {
            var angle = -Math.PI / 2 + i * angleStep;
            var x = cx + Math.cos(angle) * radius * val;
            var y = cy + Math.sin(angle) * radius * val;
            ctx.beginPath();
            ctx.arc(x, y, 4, 0, 2 * Math.PI);
            ctx.fillStyle = "#ff6b35";
            ctx.fill();
            ctx.strokeStyle = "rgba(255,107,53,0.4)";
            ctx.lineWidth = 4;
            ctx.stroke();
        });

        // Labels
        ctx.font = "11px -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        labels.forEach(function (label, i) {
            var angle = -Math.PI / 2 + i * angleStep;
            var lx = cx + Math.cos(angle) * (radius + 22);
            var ly = cy + Math.sin(angle) * (radius + 22);
            ctx.fillStyle = "rgba(255,255,255,0.6)";
            ctx.fillText(label, lx, ly);
        });
    }

    function _el(tag, cls) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        return e;
    }

    function _text(tag, cls, txt) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        e.textContent = txt;
        return e;
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;
        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/driving-style", function (data) {
            if (data.error) {
                el.textContent = data.error;
                return;
            }
            render(el, data);
        }, {
            loadingText: "Loading driving style\u2026",
        });
    }

    // Auto-init
    document.addEventListener("DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("driving-style-container", function () {
                init("driving-style-container", sid);
            });
        } else if (sid) {
            init("driving-style-container", sid);
        }
    });

    window.DrivingStyle = { init: init };
})();
