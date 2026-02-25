/**
 * session_badges.js
 * -----------------
 * Renders session badges and rating: star display, badge grid with
 * tier indicators, category radar, and coaching.
 *
 * Public API:
 *   window.SessionBadges.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var C = window.Theme ? window.Theme.colors : {};

    var TIER_COLORS = {
        gold:   C.yellow || "#ffd700",
        silver: "#c0c0c0",
        bronze: "#cd7f32",
    };

    var TIER_GLOW = {
        gold:   "rgba(255,215,0,0.3)",
        silver: "rgba(192,192,192,0.2)",
        bronze: "rgba(205,127,50,0.2)",
    };

    var TIER_LABELS = {
        gold:   "\u2605 Gold",
        silver: "\u2605 Silver",
        bronze: "\u2605 Bronze",
    };

    var CATEGORY_COLORS = {
        consistency:  "#36a2eb",
        pace:         C.red || "#e74c3c",
        endurance:    C.green || "#4caf50",
        flow:         "#ff6384",
        improvement:  "#ff9800",
        mastery:      "#9c27b0",
    };

    /* Build DOM safely — no innerHTML */
    function render(el, data) {
        if (!data || data.n_laps < 3) {
            el.textContent = (data && data.coaching) ? data.coaching : "Not enough data for badge evaluation.";
            return;
        }

        var frag = document.createDocumentFragment();

        // ── Star rating hero ────────────────────────────────
        var starHero = _el("div", "badges-star-hero");
        var starRow = _el("div", "badges-star-row");
        for (var s = 1; s <= 5; s++) {
            var star = _el("span", "badges-star");
            if (s <= data.star_rating_int) {
                star.classList.add("filled");
                star.textContent = "\u2605";
            } else if (s - 0.5 <= data.star_rating) {
                star.classList.add("half");
                star.textContent = "\u2606";
            } else {
                star.classList.add("empty");
                star.textContent = "\u2606";
            }
            starRow.appendChild(star);
        }
        starHero.appendChild(starRow);

        var starMeta = _el("div", "badges-star-meta tip tip-bottom tip-wrap");
        starMeta.setAttribute("data-tip", "Star rating computed from your overall badge tier distribution");
        starMeta.textContent = (data.star_rating || 0).toFixed(1) + " / 5.0 stars \u00B7 " +
            (data.badge_count || 0) + " badges earned";
        starHero.appendChild(starMeta);
        frag.appendChild(starHero);

        // ── Tier summary counters ───────────────────────────
        var TIER_TIPS = {
            gold:   "Gold: Awarded for exceptional, top-tier performance in a category",
            silver: "Silver: Awarded for strong, above-average performance",
            bronze: "Bronze: Awarded for solid baseline achievement",
        };
        var tierRow = _el("div", "badges-tier-row");
        ["gold", "silver", "bronze"].forEach(function (tier) {
            var count = data[tier + "_count"] || 0;
            var box = _el("div", "badges-tier-box tip tip-bottom tip-wrap");
            box.setAttribute("data-tier", tier);
            box.setAttribute("data-tip", TIER_TIPS[tier]);
            var num = _text("div", "badges-tier-num", String(count));
            num.setAttribute("data-tier", tier);
            box.appendChild(num);
            box.appendChild(_text("div", "badges-tier-label", tier.charAt(0).toUpperCase() + tier.slice(1)));
            tierRow.appendChild(box);
        });
        frag.appendChild(tierRow);

        // ── Badge cards ─────────────────────────────────────
        if (data.badges && data.badges.length > 0) {
            var grid = _el("div", "badges-card-grid");
            data.badges.forEach(function (b, i) {
                var tierCol = TIER_COLORS[b.tier] || (C.textSecondary || "#888");
                var tierGlow = TIER_GLOW[b.tier] || "transparent";
                var catCol = CATEGORY_COLORS[b.category] || (C.textSecondary || "#888");

                var card = _el("div", "badges-card");
                card.style.setProperty("--badge-tier-color", tierCol);
                card.style.setProperty("--badge-tier-glow", tierGlow);
                card.style.animationDelay = (i * 50) + "ms";

                // Header: name + tier
                var hdr = _el("div", "badges-card-header");
                hdr.appendChild(_text("span", "badges-card-name", b.name));
                var tierPill = _text("span", "badges-card-tier", TIER_LABELS[b.tier] || b.tier);
                tierPill.style.color = tierCol;
                tierPill.style.background = tierCol + "18";
                hdr.appendChild(tierPill);
                card.appendChild(hdr);

                // Description
                card.appendChild(_text("div", "badges-card-desc", b.description));

                // Category with tooltip
                var CATEGORY_TIPS = {
                    consistency: "Consistency: Measures lap-to-lap repeatability and steady performance",
                    pace:        "Pace: Measures raw speed and lap time performance",
                    endurance:   "Endurance: Measures performance maintenance across long stints",
                    flow:        "Flow: Measures smoothness of racing line and input transitions",
                    improvement: "Improvement: Measures progress and learning rate within the session",
                    mastery:     "Mastery: Measures overall skill level across multiple dimensions",
                };
                var catLine = _el("div", "badges-card-category tip tip-right tip-wrap");
                catLine.setAttribute("data-tip", CATEGORY_TIPS[b.category] || b.category);
                var catDot = _el("span", "badges-cat-dot");
                catDot.style.background = catCol;
                catLine.appendChild(catDot);
                catLine.appendChild(document.createTextNode(b.category));
                card.appendChild(catLine);

                // Progress bar to next tier
                if (b.tier !== "gold" && b.progress_to_next > 0) {
                    var progWrap = _el("div", "badges-progress-track");
                    var progFill = _el("div", "badges-progress-fill");
                    progFill.style.width = (b.progress_to_next * 100) + "%";
                    progFill.style.background = tierCol;
                    progWrap.appendChild(progFill);
                    card.appendChild(progWrap);
                    card.appendChild(_text("div", "badges-progress-label",
                        Math.round(b.progress_to_next * 100) + "% to next tier"));
                }

                grid.appendChild(card);
            });
            frag.appendChild(grid);
        }

        // ── Category radar canvas ───────────────────────────
        var radarSection = _el("div", "badges-radar-section");
        radarSection.appendChild(_text("div", "badges-radar-label", "Category Performance"));
        var canvas = document.createElement("canvas");
        canvas.id = "badge-category-canvas";
        canvas.className = "badges-radar-canvas";
        canvas.setAttribute("aria-label", "Badge category performance radar chart");
        radarSection.appendChild(canvas);
        frag.appendChild(radarSection);

        // ── Coaching insight ────────────────────────────────
        if (data.coaching) {
            var coach = _el("div", "badges-coaching");
            coach.appendChild(_text("strong", "badges-coaching-label", "Badge Insight: "));
            coach.appendChild(document.createTextNode(data.coaching));
            frag.appendChild(coach);
        }

        el.textContent = "";
        el.appendChild(frag);

        setTimeout(function () {
            _drawCategoryRadar(data);
            // Register for resize observer
            if (window.TelemetryResize) {
                TelemetryResize.observe(radarSection);
            }
        }, 30);
    }

    function _drawCategoryRadar(data) {
        var canvas = document.getElementById("badge-category-canvas");
        if (!canvas) return;
        canvas.__redraw = function() { _drawCategoryRadar(data); };
        var dpr = window.devicePixelRatio || 1;
        var W = canvas.parentElement.clientWidth || 400;
        var H = Math.round(Math.min(W * 0.55, 500));
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + "px";
        canvas.style.height = H + "px";
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        var cx = W / 2, cy = H / 2;
        var radius = Math.min(cx, cy) - 30;

        ctx.clearRect(0, 0, W, H);

        var cats = Object.keys(data.category_scores || {});
        if (cats.length === 0) return;

        var n = cats.length;
        var angleStep = (2 * Math.PI) / n;

        // Draw grid rings
        [0.25, 0.5, 0.75, 1.0].forEach(function (pct) {
            ctx.beginPath();
            ctx.strokeStyle = "rgba(255,255,255,0.07)";
            ctx.lineWidth = 1;
            for (var i = 0; i <= n; i++) {
                var angle = -Math.PI / 2 + i * angleStep;
                var x = cx + Math.cos(angle) * radius * pct;
                var y = cy + Math.sin(angle) * radius * pct;
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
        });

        // Draw data polygon — gradient fill
        ctx.beginPath();
        var grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
        grad.addColorStop(0, "rgba(255,107,53,0.35)");
        grad.addColorStop(1, "rgba(255,107,53,0.05)");
        ctx.fillStyle = grad;
        ctx.strokeStyle = "rgba(255,107,53,0.9)";
        ctx.lineWidth = 2;
        cats.forEach(function (cat, i) {
            var val = (data.category_scores[cat] || 0) / 100;
            var angle = -Math.PI / 2 + i * angleStep;
            var x = cx + Math.cos(angle) * radius * val;
            var y = cy + Math.sin(angle) * radius * val;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Data point dots
        cats.forEach(function (cat, i) {
            var val = (data.category_scores[cat] || 0) / 100;
            var angle = -Math.PI / 2 + i * angleStep;
            var x = cx + Math.cos(angle) * radius * val;
            var y = cy + Math.sin(angle) * radius * val;
            ctx.beginPath();
            ctx.arc(x, y, 3, 0, 2 * Math.PI);
            ctx.fillStyle = "rgba(255,107,53,1)";
            ctx.fill();
        });

        // Labels
        ctx.font = "11px -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.textAlign = "center";
        cats.forEach(function (cat, i) {
            var angle = -Math.PI / 2 + i * angleStep;
            var lx = cx + Math.cos(angle) * (radius + 20);
            var ly = cy + Math.sin(angle) * (radius + 20) + 4;
            var col = CATEGORY_COLORS[cat] || (C.textSecondary || "#aaa");
            ctx.fillStyle = col;
            ctx.fillText(cat, lx, ly);
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

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/badges", function (data) {
            render(el, data);
        }, {
            loadingText: 'Loading session badges\u2026',
        });
    }

    // Auto-init
    document.addEventListener("DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("session-badges-container", function () {
                init("session-badges-container", sid);
            });
        } else if (sid) {
            init("session-badges-container", sid);
        }
    });

    window.SessionBadges = { init: init };
})();
