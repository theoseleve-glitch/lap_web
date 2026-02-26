/**
 * summary_report.js
 * -----------------
 * Renders comprehensive session summary: overview card, highlights,
 * improvements, key metrics table, actions, and narratives.
 *
 * Public API:
 *   window.SummaryReport.init(containerId, sessionId)
 */
(function () {
    "use strict";

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    var GRADE_COLORS = {
        "A+": C.yellow || "#ffd700", "A": C.green || "#4caf50", "B+": "#36a2eb", "B": "#36a2eb",
        "C+": "#ff9800", "C": "#ff9800", "D": C.red || "#e74c3c", "F": C.red || "#e74c3c", "N/A": C.textSecondary || "#888"
    };

    var GRADE_GLOW = {
        "A+": "rgba(255,215,0,0.25)", "A": "rgba(76,175,80,0.2)", "B+": "rgba(54,162,235,0.2)", "B": "rgba(54,162,235,0.15)",
        "C+": "rgba(255,152,0,0.15)", "C": "rgba(255,152,0,0.1)", "D": "rgba(248,81,73,0.15)", "F": "rgba(248,81,73,0.2)"
    };

    var RATING_COLORS = {
        excellent:  C.green || "#4caf50",
        good:       "#36a2eb",
        average:    "#ff9800",
        needs_work: C.red || "#e74c3c",
    };

    var CATEGORY_ICONS = {
        pace:        "\u26A1",
        consistency: "\u2261",
        improvement: "\u2191",
        endurance:   "\u23F1",
        technique:   "\u2699",
    };

    var DIFFICULTY_ICONS = {
        easy:   "\u25CB",
        medium: "\u25D2",
        hard:   "\u25CF",
    };

    /* All HTML assembled from API data (trusted backend, not user input) */
    function render(el, data) {
        if (!data || !data.overview) {
            el.textContent = (data && data.executive_summary) ? data.executive_summary : "No summary data available.";
            return;
        }

        var ov = data.overview;
        var frag = document.createDocumentFragment();

        // ── Overview hero card ──────────────────────────────
        var gCol = GRADE_COLORS[ov.grade] || (C.textSecondary || "#888");
        var gGlow = GRADE_GLOW[ov.grade] || "rgba(255,255,255,0.05)";

        var hero = _el("div", "debrief-hero");

        // Grade ring
        var ring = _el("div", "debrief-grade-ring");
        ring.style.setProperty("--grade-color", gCol);
        ring.style.setProperty("--grade-glow", gGlow);
        ring.appendChild(_text("span", "debrief-grade-letter", ov.grade));
        ring.appendChild(_text("span", "debrief-grade-label", "GRADE"));
        hero.appendChild(ring);

        // Quick stats
        var stats = _el("div", "debrief-hero-stats");
        var meta = _el("div", "debrief-hero-meta");
        meta.textContent = (ov.driver_name || "Driver") + " \u00B7 " + (ov.session_type || "Session") + " \u00B7 " + (ov.session_date || "");
        stats.appendChild(meta);

        var nums = _el("div", "debrief-hero-numbers");
        nums.appendChild(_statPill("Laps", String(ov.n_laps), "var(--text-primary)"));
        nums.appendChild(_statPill("Duration", "~" + ov.duration_estimate_min.toFixed(1) + " min", "var(--text-primary)"));
        nums.appendChild(_statPill("Score", ov.total_score.toFixed(1) + "/100", gCol));
        stats.appendChild(nums);
        hero.appendChild(stats);
        frag.appendChild(hero);

        // ── Executive summary ──────────────────────────────
        if (data.executive_summary) {
            var exec = _el("div", "debrief-executive");
            exec.style.borderLeftColor = gCol;
            exec.textContent = data.executive_summary;
            frag.appendChild(exec);
        }

        // ── Highlights ──────────────────────────────────────
        if (data.highlights && data.highlights.length > 0) {
            var hlLabel = _text("div", "debrief-section-label", "Highlights ");
            var hlTip = _el("span", "tip tip-right tip-wrap debrief-section-tip");
            hlTip.setAttribute("data-tip", "The strongest aspects of this session \u2014 what went well");
            hlTip.textContent = "\u24D8";
            hlLabel.appendChild(hlTip);
            frag.appendChild(hlLabel);
            var hlWrap = _el("div", "debrief-highlights");
            data.highlights.forEach(function (h, i) {
                var icon = CATEGORY_ICONS[h.category] || "\u2605";
                var card = _el("div", "debrief-highlight-card");
                card.style.animationDelay = (i * 80) + "ms";
                var ic = _text("div", "debrief-highlight-icon", icon);
                ic.style.color = C.green || "#4caf50";
                card.appendChild(ic);
                var body = _el("div", "debrief-highlight-body");
                body.appendChild(_text("div", "debrief-highlight-title", h.title));
                body.appendChild(_text("div", "debrief-highlight-detail", h.detail));
                var mv = _text("div", "debrief-highlight-metric", h.metric_value);
                mv.style.color = C.green || "#4caf50";
                body.appendChild(mv);
                card.appendChild(body);
                hlWrap.appendChild(card);
            });
            frag.appendChild(hlWrap);
        }

        // ── Key metrics table ──────────────────────────────
        if (data.key_metrics && data.key_metrics.length > 0) {
            var mLabel = _text("div", "debrief-section-label", "Key Metrics ");
            var mTip = _el("span", "tip tip-right tip-wrap debrief-section-tip");
            mTip.setAttribute("data-tip", "Core performance numbers with context \u2014 how your metrics compare to expectations");
            mTip.textContent = "\u24D8";
            mLabel.appendChild(mTip);
            frag.appendChild(mLabel);
            var tw = _el("div", "table-wrap debrief-metrics-table");
            var tbl = document.createElement("table");
            tbl.className = "data-table compact";
            var cap = document.createElement("caption");
            cap.className = "sr-only";
            cap.textContent = "Key performance metrics";
            tbl.appendChild(cap);
            var thead = document.createElement("thead");
            var thr = document.createElement("tr");
            ["Metric", "Value", "Rating", "Context"].forEach(function (t) {
                var th = document.createElement("th");
                th.textContent = t;
                thr.appendChild(th);
            });
            thead.appendChild(thr);
            tbl.appendChild(thead);
            var tbody = document.createElement("tbody");
            data.key_metrics.forEach(function (m) {
                var rCol = RATING_COLORS[m.rating] || (C.textSecondary || "#888");
                var tr = document.createElement("tr");
                var td1 = _text("td", "debrief-metric-name", m.name);
                var td2 = _text("td", "col-numeric", m.value);
                var td3 = document.createElement("td");
                td3.className = "col-numeric";
                var pill = _text("span", "debrief-rating-pill", m.rating.replace("_", " "));
                pill.style.color = rCol;
                pill.style.background = rCol + "18";
                td3.appendChild(pill);
                var td4 = _text("td", "debrief-metric-context", m.context);
                tr.appendChild(td1);
                tr.appendChild(td2);
                tr.appendChild(td3);
                tr.appendChild(td4);
                tbody.appendChild(tr);
            });
            tbl.appendChild(tbody);
            tw.appendChild(tbl);
            frag.appendChild(tw);
        }

        // ── Improvements ────────────────────────────────────
        if (data.improvements && data.improvements.length > 0) {
            var impLabel = _text("div", "debrief-section-label", "Areas for Improvement ");
            var impTip = _el("span", "tip tip-right tip-wrap debrief-section-tip");
            impTip.setAttribute("data-tip", "Priority-ranked areas where focused practice will have the biggest impact");
            impTip.textContent = "\u24D8";
            impLabel.appendChild(impTip);
            frag.appendChild(impLabel);
            var impWrap = _el("div", "debrief-improvements");
            data.improvements.forEach(function (imp) {
                var card = _el("div", "debrief-improvement-card");
                var hdr = _el("div", "debrief-improvement-header");
                hdr.appendChild(_text("span", "debrief-improvement-area", imp.area));
                hdr.appendChild(_text("span", "debrief-improvement-priority", "P" + imp.priority));
                card.appendChild(hdr);
                card.appendChild(_text("div", "debrief-improvement-explain", imp.explanation));
                var drill = _el("div", "debrief-improvement-drill");
                drill.appendChild(_text("span", "debrief-drill-tag", "DRILL"));
                drill.appendChild(document.createTextNode(" " + imp.suggested_drill));
                card.appendChild(drill);
                impWrap.appendChild(card);
            });
            frag.appendChild(impWrap);
        }

        // ── Next Session Actions — Hero section ──
        if (data.actions && data.actions.length > 0) {
            var actHero = _el("div", "debrief-actions-hero");

            var actHdr = _el("div", "debrief-actions-header");
            actHdr.appendChild(_text("span", "debrief-actions-title", "\u25B6 Next Session Actions"));
            var tipSpan = _el("span", "tip tip-right tip-wrap debrief-actions-info");
            tipSpan.setAttribute("data-tip", "Concrete actions to focus on in your next session, ranked by impact");
            tipSpan.textContent = "\u24D8";
            actHdr.appendChild(tipSpan);
            actHdr.appendChild(_text("span", "debrief-actions-count",
                data.actions.length + " action" + (data.actions.length > 1 ? "s" : "")));
            actHero.appendChild(actHdr);

            var actGrid = _el("div", "debrief-actions-grid");
            data.actions.forEach(function (a, i) {
                var diffCol = a.difficulty === "hard" ? (C.red || "#e74c3c") : a.difficulty === "medium" ? "#ff9800" : (C.green || "#4caf50");
                var diffIcon = DIFFICULTY_ICONS[a.difficulty] || "\u25CB";
                var card = _el("div", "debrief-action-card");
                card.style.animationDelay = (i * 60) + "ms";
                card.appendChild(_text("div", "debrief-action-number", String(i + 1)));
                var body = _el("div", "debrief-action-body");
                body.appendChild(_text("div", "debrief-action-text", a.action));
                var ameta = _el("div", "debrief-action-meta");
                var diff = _text("span", "debrief-action-difficulty", diffIcon + " " + a.difficulty);
                diff.style.color = diffCol;
                ameta.appendChild(diff);
                ameta.appendChild(_text("span", "debrief-action-category", a.category));
                body.appendChild(ameta);
                card.appendChild(body);
                actGrid.appendChild(card);
            });
            actHero.appendChild(actGrid);

            frag.appendChild(actHero);
        }

        el.textContent = "";
        el.appendChild(frag);
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

    function _statPill(label, value, color) {
        var pill = _el("div", "debrief-stat-pill");
        pill.appendChild(_text("span", "debrief-stat-label", label));
        var val = _text("span", "debrief-stat-value", value);
        val.style.color = color;
        pill.appendChild(val);
        return pill;
    }

    function init(containerId, sessionId) {
        var el = document.getElementById(containerId);
        if (!el) return;

        FetchHelper.load(el, "/api/session/" + encodeURIComponent(sessionId) + "/summary-report", function (data) {
            if (data.error) {
                el.textContent = data.error;
                return;
            }
            render(el, data);
        }, {
            loadingText: 'Loading session summary\u2026',
        });
    }

    // Auto-init
    _lc.addListener(document, "DOMContentLoaded", function () {
        var sid = window.TELEMETRY && window.TELEMETRY.sessionId;
        if (sid && window.FetchHelper && FetchHelper.lazyInit) {
            FetchHelper.lazyInit("summary-report-container", function () {
                init("summary-report-container", sid);
            });
        } else if (sid) {
            init("summary-report-container", sid);
        }
    });

    window.SummaryReport = { init: init };

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('summary_report', {
        init: function () {},
        destroy: destroy
    });
})();
