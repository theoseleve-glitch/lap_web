# Report Overview Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the session detail Overview tab — rewrite Driving Style as a JS component with enriched API, elevate Next Session Actions visual hierarchy, give Achievements a premium motorsport aesthetic, and add hover tooltips across all sections.

**Architecture:** New `/api/session/<id>/driving-style` endpoint serves enriched feature data (qualitative labels, coaching tips). New `driving_style.js` replaces the Jinja-rendered block. `summary_report.js` and `session_badges.js` get CSS-only visual upgrades plus tooltip spans. All tooltips use the existing `data-tip` CSS pattern.

**Tech Stack:** Python/Flask (backend endpoint), vanilla JS (DOM rendering, same pattern as existing modules), CSS (metallic gradients, glassmorphism), Jinja2 (tooltip spans on server-rendered headings)

---

## Task 1: Driving Style API Endpoint

**Files:**
- Modify: `telemetry_tool/web/routes/api_data.py` (insert after line 2054)
- Reference: `telemetry_tool/web/models.py:877-890` (existing `get_driving_style`)
- Reference: `telemetry_tool/db/schema.py:255-275` (table columns)

**Step 1: Add the endpoint to `api_data.py`**

Insert after the `api_summary_report` function (after line 2054). The endpoint reuses the existing `get_driving_style()` model function and enriches the raw 0–1 values with qualitative labels and coaching tips.

```python
# ------------------------------------------------------------------
# Driving Style (Redesign — JS-rendered)
# ------------------------------------------------------------------

_STYLE_FEATURES = [
    # (db_key, human_label, hint, inverted, coaching_tips_by_tier)
    ("trail_braking_depth", "Trail Braking",
     "How deep into corners you maintain brake pressure — higher means more trail braking",
     False, {
         "low": "Start introducing trail braking: maintain light brake into corner entry",
         "below_avg": "Good awareness — try holding brake pressure 5m deeper into corners",
         "average": "Solid trail braking — extend pressure deeper through mid-corner",
         "good": "Strong trail braking technique — fine-tune release rate for smoother rotation",
         "elite": "Excellent trail braking depth — focus on consistency across all corners",
     }),
    ("brake_point_consistency", "Brake Consistency",
     "How repeatable your braking points are from lap to lap",
     False, {
         "low": "Pick a fixed reference point for each braking zone and hit it every lap",
         "below_avg": "Focus on the 2-3 corners where your braking varies most",
         "average": "Decent consistency — work on matching braking points in long stints",
         "good": "Consistent braker — refine the last 5% with marker-based braking",
         "elite": "Machine-like consistency — maintain this through varying conditions",
     }),
    ("brake_pressure_buildup_rate", "Brake Attack",
     "How quickly you build peak brake pressure — higher means sharper initial braking",
     False, {
         "low": "Practice building brake pressure faster — firm initial hit then modulate",
         "below_avg": "Try a crisper initial stab — aim for peak pressure within 0.2s",
         "average": "Reasonable brake attack — work on faster initial application",
         "good": "Strong brake attack — make sure it stays controlled at corner entry",
         "elite": "Excellent brake attack rate — top-tier initial application",
     }),
    ("apex_speed_ratio", "Apex Speed",
     "Corner speed relative to optimal — higher means faster through apexes",
     False, {
         "low": "You are over-slowing mid-corner — carry more speed past the apex",
         "below_avg": "Try carrying 2-3 km/h more through the apex on medium-speed corners",
         "average": "Reasonable apex speed — focus on the slowest corners for easy gains",
         "good": "Strong mid-corner speed — fine-tune the last km/h with smoother turn-in",
         "elite": "Exceptional apex speed — you are maximizing corner velocity",
     }),
    ("turn_in_aggressiveness", "Turn-in Aggression",
     "How sharply you initiate steering input into corners",
     False, {
         "low": "Be more decisive with initial steering — commit to the turn earlier",
         "below_avg": "Try a slightly quicker steering input at corner entry",
         "average": "Balanced turn-in — experiment with sharper input on slow corners",
         "good": "Assertive turn-in — ensure it matches your trail braking depth",
         "elite": "Aggressive and precise — great commitment to corner entry",
     }),
    ("throttle_onset_delay_m", "Throttle Pickup",
     "Distance after apex before getting on throttle — lower delay means quicker pickup",
     True, {  # inverted: low value = good
         "low": "Excellent throttle pickup — you are on the gas early and decisively",
         "below_avg": "Good throttle pickup — you get on power promptly after the apex",
         "average": "Reasonable pickup — try applying throttle 2-3m earlier on exit",
         "good": "Late to throttle — focus on earlier, progressive throttle application",
         "elite": "Very late throttle pickup — work on getting on power sooner after apex",
     }),
    ("exit_acceleration_efficiency", "Exit Drive",
     "How effectively you convert throttle application to speed on corner exit",
     False, {
         "low": "Focus on smooth, progressive throttle to avoid wheelspin on exit",
         "below_avg": "Work on straightening the wheel before applying full throttle",
         "average": "Decent exit drive — unwind the steering earlier for better traction",
         "good": "Strong exit drive — fine-tune throttle progressivity for the last 2%",
         "elite": "Excellent exit efficiency — top-tier corner exit performance",
     }),
    ("line_variation_index", "Line Variation",
     "How much your racing line changes between laps — lower means more consistent lines",
     True, {  # inverted: low value = good
         "low": "Razor-consistent lines — excellent repeatability lap after lap",
         "below_avg": "Good line consistency — minor variations are normal",
         "average": "Moderate variation — pick a reference line and stick to it",
         "good": "Noticeable line variation — study the fastest lap and replicate that line",
         "elite": "High line variation — focus on following the same path each lap",
     }),
    ("early_vs_late_stint_pace", "Stint Endurance",
     "Pace balance between early and late laps — closer to 0.50 means steadier performance",
     False, {
         "low": "Significant pace drop-off in late stint — work on physical endurance",
         "below_avg": "Noticeable fade — try conserving energy in early laps",
         "average": "Some late-stint fade — focus on mental consistency in final laps",
         "good": "Steady stint pace — good endurance management",
         "elite": "Excellent endurance — virtually no pace drop across the stint",
     }),
    ("smoothness_composite", "Smoothness",
     "Overall smoothness of steering, braking, and throttle transitions combined",
     False, {
         "low": "Focus on smoother inputs — avoid jerky steering and abrupt pedal changes",
         "below_avg": "Work on blending inputs — smooth transitions between brake and throttle",
         "average": "Reasonable smoothness — refine transitions in high-speed corners",
         "good": "Smooth driver — your inputs are well-blended and progressive",
         "elite": "Exceptionally smooth — silky input transitions across all controls",
     }),
]


def _qualify_value(val, inverted):
    """Map a 0–1 feature value to a qualitative tier."""
    if val is None:
        return "unknown", "unknown"
    if inverted:
        # For inverted features, low value = good
        if val <= 0.20:
            return "elite", "Elite"
        elif val <= 0.40:
            return "good", "Good"
        elif val <= 0.60:
            return "average", "Moderate"
        elif val <= 0.80:
            return "below_avg", "Below Avg"
        else:
            return "low", "Low"
    else:
        if val >= 0.80:
            return "elite", "Elite"
        elif val >= 0.60:
            return "good", "Good"
        elif val >= 0.40:
            return "average", "Moderate"
        elif val >= 0.20:
            return "below_avg", "Below Avg"
        else:
            return "low", "Low"


_TIER_TO_RATING = {
    "elite": "excellent",
    "good": "good",
    "average": "average",
    "below_avg": "needs_work",
    "low": "needs_work",
    "unknown": "average",
}

_STYLE_DESCRIPTIONS = {
    "smooth": "Fluid, progressive inputs with excellent control blending",
    "aggressive": "Committed, sharp inputs with decisive corner attack",
    "conservative": "Cautious, margin-focused approach prioritizing consistency",
    "adaptive": "Flexible style that adjusts to changing conditions",
}


@bp.route("/session/<session_id>/driving-style")
def api_driving_style(session_id: str):
    """Return enriched driving style features with qualitative labels and coaching tips."""
    conn = get_db_connection()

    # Get session to find driver_id
    row = conn.execute(
        "SELECT driver_id FROM sessions WHERE session_id = :sid",
        {"sid": session_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "Session not found"}), 404
    if not row["driver_id"]:
        return jsonify({"error": "No driver linked to session"}), 404

    from .models import get_driving_style
    style = get_driving_style(conn, row["driver_id"], session_id)
    if not style:
        return jsonify({"error": "No driving style data for this session"}), 404

    features = []
    radar_labels = []
    radar_values = []
    for db_key, label, hint, inverted, tips in _STYLE_FEATURES:
        val = style.get(db_key)
        tier_key, tier_label = _qualify_value(val, inverted)
        tip = tips.get(tier_key, "")
        rating = _TIER_TO_RATING.get(tier_key, "average")
        features.append({
            "key": db_key,
            "label": label,
            "value": round(val, 3) if val is not None else None,
            "qualitative": tier_label,
            "rating": rating,
            "hint": hint,
            "tip": tip,
            "inverted": inverted,
        })
        radar_labels.append(label)
        radar_values.append(round(val, 3) if val is not None else 0)

    style_label = style.get("style_label") or "Unknown"
    style_key = style_label.lower().replace(" ", "_")
    style_desc = _STYLE_DESCRIPTIONS.get(style_key, "")

    return jsonify({
        "session_id": session_id,
        "style_label": style_label,
        "style_description": style_desc,
        "style_confidence": round(style.get("style_confidence") or 0, 2),
        "features": features,
        "strengths": style.get("strengths", []),
        "weaknesses": style.get("weaknesses", []),
        "radar_labels": radar_labels,
        "radar_values": radar_values,
    })
```

**Step 2: Verify the endpoint works**

Run the Flask app and test with an existing session that has driving style data:
```
curl http://127.0.0.1:5000/api/session/<SOME_SESSION_ID>/driving-style
```
Expected: JSON with `style_label`, `features[]` array with `qualitative`/`rating`/`tip` fields.

**Step 3: Commit**

```bash
git add telemetry_tool/web/routes/api_data.py
git commit -m "feat: add /api/session/<id>/driving-style endpoint with enriched labels"
```

---

## Task 2: Driving Style JS Component

**Files:**
- Create: `telemetry_tool/web/static/js/driving_style.js`

**Step 1: Create the JS module**

This follows the exact same IIFE + `FetchHelper.load` + `_el`/`_text` helper pattern used by `summary_report.js` and `session_badges.js`.

```javascript
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

        // ── Driver profile link ──────────────────────────
        if (data.driver_profile_url) {
            var link = _el("p", "mt-md");
            var a = document.createElement("a");
            a.className = "driver-link";
            a.href = data.driver_profile_url;
            a.textContent = "View full driver profile \u2192";
            link.appendChild(a);
            frag.appendChild(link);
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
        var dpr = window.devicePixelRatio || 1;
        var W = Math.min(canvas.parentElement.clientWidth || 300, 300);
        var H = 300;
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
```

**Step 2: Commit**

```bash
git add telemetry_tool/web/static/js/driving_style.js
git commit -m "feat: add driving_style.js component with qualitative gauges and radar"
```

---

## Task 3: Driving Style CSS

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css` (insert after the existing `.style-fill-warn` block around line 8632)

**Step 1: Add Driving Style component CSS**

Insert after the `.style-fill-warn` line (around line 8632):

```css
/* ══════════════════════════════════════════
   Driving Style — JS-rendered (driving_style.js)
   ══════════════════════════════════════════ */

.dstyle-header {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    margin-bottom: 0.4rem;
}

.dstyle-label-badge {
    display: inline-block;
    padding: 4px 14px;
    border-radius: var(--radius-sm);
    font-size: 0.88rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: capitalize;
    border: 1px solid;
}

.dstyle-confidence {
    font-size: 0.75rem;
    color: var(--text-secondary);
}

.dstyle-description {
    font-size: 0.82rem;
    color: var(--text-secondary);
    margin: 0 0 1rem;
    line-height: 1.5;
}

.dstyle-layout {
    display: grid;
    grid-template-columns: 1fr 300px;
    gap: 1.5rem;
    align-items: start;
}
@media (max-width: 768px) {
    .dstyle-layout { grid-template-columns: 1fr; }
}

.dstyle-gauge-list {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
}

.dstyle-gauge-row {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding: 0.45rem 0;
    border-bottom: 1px solid var(--border-light);
}
.dstyle-gauge-row:last-child { border-bottom: none; }

.dstyle-gauge-name {
    flex: 0 0 120px;
    font-size: 0.82rem;
    color: var(--text-secondary);
    cursor: help;
}

.dstyle-gauge-track {
    flex: 1;
    height: 8px;
    background: var(--bg-secondary);
    border-radius: 4px;
    overflow: hidden;
}

.dstyle-gauge-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
}

.dstyle-gauge-qual {
    flex: 0 0 80px;
    text-align: right;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: help;
}

.dstyle-radar-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
}

.dstyle-radar-canvas {
    display: block;
    max-width: 100%;
}

.dstyle-insights {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin-top: 1rem;
}
@media (max-width: 600px) {
    .dstyle-insights { grid-template-columns: 1fr; }
}
```

**Step 2: Commit**

```bash
git add telemetry_tool/web/static/css/main.css
git commit -m "feat: add driving style component CSS with gauge and radar layout"
```

---

## Task 4: Replace Jinja Driving Style Block in Template

**Files:**
- Modify: `telemetry_tool/web/templates/session_detail.html`
  - Replace lines 163–263 (the `{% if driving_style %}` Jinja block)
  - Add `<script>` include around line 1062 (where `progression.js` was conditionally loaded)
  - Remove the old Jinja-based radar init around lines 1337–1351

**Step 1: Replace the Driving Style Jinja block (lines 163–263)**

Replace everything from `<!-- Driving Style -->` through `{% endif %}` (the block ending at line 263) with:

```html
<!-- Driving Style (JS-rendered) -->
<section class="section">
    <h2>
        Driving Style
        <span class="tip tip-right" data-tip="Your driving fingerprint — 10 input behaviors analyzed across all laps">ⓘ</span>
    </h2>
    <div id="driving-style-container" aria-live="polite">
        <div class="loading-center"><div class="spinner-inline spinner-accent"></div><div class="text-secondary text-sm">Loading driving style...</div></div>
    </div>
</section>
```

**Step 2: Add the `driving_style.js` script include**

In the `<script>` block area (around line 1054), add after the `session_badges.js` include:

```html
<script src="{{ url_for('static', filename='js/driving_style.js') }}"></script>
```

**Step 3: Remove the old Jinja radar init**

Remove the `{% if driving_style %}` block around lines 1337–1351 that called `window.Progression.drawRadar('style-radar-session', ...)`. Also remove the conditional `progression.js` include at line 1061–1063 (since the radar is now self-contained in `driving_style.js`).

Note: Only remove the `progression.js` include if it is ONLY used for the driving style radar on this page. Check if `progression.js` is used elsewhere in the template first. If it powers other charts (e.g., in the driver_profile), keep the include but remove only the style-radar-session call block.

**Step 4: Verify**

Load a session detail page in the browser. The Driving Style section should:
- Show the style label badge with confidence
- Show 10 feature gauges with qualitative labels ("Moderate", "Good", etc.)
- Show hover tooltips on feature names (metric explanation) and qualitative labels (coaching tip)
- Show the radar chart
- Show strengths/weaknesses boxes

**Step 5: Commit**

```bash
git add telemetry_tool/web/templates/session_detail.html
git commit -m "feat: replace Jinja driving style block with JS-rendered component"
```

---

## Task 5: Next Session Actions Hero Styling

**Files:**
- Modify: `telemetry_tool/web/static/js/summary_report.js` (lines 178–205)
- Modify: `telemetry_tool/web/static/css/main.css` (after the existing `.debrief-actions-*` block)

**Step 1: Wrap actions in hero container (JS)**

In `summary_report.js`, modify the actions rendering block (around line 178). Change from appending `actHdr` and `actGrid` directly to `frag`, to wrapping them in a hero container:

Replace lines 178–205:
```javascript
        // ── Next Session Actions (BIGGER, more prominent) ──
        if (data.actions && data.actions.length > 0) {
            var actHero = _el("div", "debrief-actions-hero");

            var actHdr = _el("div", "debrief-actions-header");
            actHdr.appendChild(_text("span", "debrief-actions-title", "\u25B6 Next Session Actions"));
            var tipSpan = _el("span", "tip tip-right tip-wrap");
            tipSpan.setAttribute("data-tip", "Concrete actions to focus on in your next session, ranked by impact");
            tipSpan.textContent = "\u24D8";
            tipSpan.className += " debrief-actions-info";
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
```

**Step 2: Add hero CSS**

In `main.css`, replace the existing `.debrief-actions-header` block (lines 8884–8891) and add the hero wrapper. Insert the hero wrapper before the existing actions header:

```css
/* ── Next Session Actions — Hero wrapper ── */

.debrief-actions-hero {
    margin-top: 2rem;
    padding: 1.2rem;
    background: linear-gradient(135deg, rgba(255,107,53,0.04), rgba(255,107,53,0.08));
    border-left: 3px solid var(--accent);
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
}
```

Update the existing `.debrief-actions-title` to:
```css
.debrief-actions-title {
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: 0.02em;
}
```

Update `.debrief-actions-header` margin to remove top margin (hero wrapper handles it):
```css
.debrief-actions-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 0 0 0.8rem;
    padding-bottom: 0.4rem;
    border-bottom: 2px solid var(--accent);
}
```

Add the info icon style:
```css
.debrief-actions-info {
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-left: 0.4rem;
    cursor: help;
}
```

**Step 3: Verify**

Load a session detail page. The Next Session Actions section should:
- Be wrapped in a distinct container with accent gradient background
- Have a larger title with a ▶ prefix
- Be visually separated from the improvements section above

**Step 4: Commit**

```bash
git add telemetry_tool/web/static/js/summary_report.js telemetry_tool/web/static/css/main.css
git commit -m "feat: elevate Next Session Actions with hero wrapper and larger title"
```

---

## Task 6: Achievements Premium Motorsport CSS

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css` (the badges section, lines 8972–9214)

**Step 1: Replace the badges CSS block**

Replace the entire `/* Achievements & Badges */` section (lines 8972–9214) with the premium motorsport version:

```css
/* ══════════════════════════════════════════
   Achievements & Badges — Premium Motorsport
   ══════════════════════════════════════════ */

/* Star rating hero */
.badges-star-hero {
    text-align: center;
    padding: 1.2rem 0 0.8rem;
}

.badges-star-row {
    display: flex;
    justify-content: center;
    gap: 0.4rem;
    margin-bottom: 0.4rem;
}

.badges-star {
    font-size: 2.4rem;
    line-height: 1;
    transition: transform 0.2s ease;
}
.badges-star.filled {
    background: linear-gradient(135deg, #ffd700, #ffaa00, #ffd700);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    filter: drop-shadow(0 0 6px rgba(255, 215, 0, 0.4));
    animation: starPulse 0.6s ease-out;
}
.badges-star.half {
    background: linear-gradient(135deg, #ffd700, #ffaa00);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    opacity: 0.7;
}
.badges-star.empty {
    color: var(--text-secondary);
    opacity: 0.2;
}

@keyframes starPulse {
    0%   { transform: scale(0.6); opacity: 0; }
    50%  { transform: scale(1.15); }
    100% { transform: scale(1); opacity: 1; }
}

.badges-star-meta {
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-top: 0.2rem;
}

/* Tier counters — metallic */
.badges-tier-row {
    display: flex;
    justify-content: center;
    gap: 1.2rem;
    margin: 0.8rem 0 1.2rem;
}

.badges-tier-box {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0.7rem 1.4rem;
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-md);
    min-width: 78px;
    transition: box-shadow 0.3s ease, transform 0.2s ease;
    cursor: default;
}
.badges-tier-box[data-tier="gold"] {
    border-image: linear-gradient(135deg, #ffd700, #b8860b) 1;
    box-shadow: 0 0 12px rgba(255, 215, 0, 0.15);
}
.badges-tier-box[data-tier="silver"] {
    border-image: linear-gradient(135deg, #e0e0e0, #808080) 1;
    box-shadow: 0 0 12px rgba(192, 192, 192, 0.12);
}
.badges-tier-box[data-tier="bronze"] {
    border-image: linear-gradient(135deg, #cd7f32, #8b4513) 1;
    box-shadow: 0 0 12px rgba(205, 127, 50, 0.12);
}
.badges-tier-box:hover {
    transform: scale(1.03);
}
.badges-tier-box[data-tier="gold"]:hover {
    box-shadow: 0 0 24px rgba(255, 215, 0, 0.3);
}
.badges-tier-box[data-tier="silver"]:hover {
    box-shadow: 0 0 24px rgba(192, 192, 192, 0.25);
}
.badges-tier-box[data-tier="bronze"]:hover {
    box-shadow: 0 0 24px rgba(205, 127, 50, 0.25);
}

.badges-tier-num {
    font-size: 1.6rem;
    font-weight: 800;
    font-family: var(--font-mono);
    line-height: 1;
}
.badges-tier-num[data-tier="gold"] {
    background: linear-gradient(135deg, #ffd700, #ffaa00, #ffd700);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.badges-tier-num[data-tier="silver"] {
    background: linear-gradient(135deg, #e0e0e0, #a0a0a0, #e0e0e0);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.badges-tier-num[data-tier="bronze"] {
    background: linear-gradient(135deg, #cd7f32, #a0622a, #cd7f32);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.badges-tier-label {
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-secondary);
    margin-top: 0.25rem;
}

/* Badge cards grid — premium */
.badges-card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 0.8rem;
    margin-bottom: 1.2rem;
}

.badges-card {
    padding: 0.9rem 1.1rem;
    padding-top: calc(0.9rem + 2px);
    background: var(--bg-card);
    border: 1px solid var(--border-light);
    border-top: 2px solid var(--badge-tier-color, var(--text-secondary));
    border-radius: var(--radius-md);
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.15), 0 0 8px var(--badge-tier-glow, transparent);
    animation: fadeSlideUp 0.3s ease both;
    transition: box-shadow 0.3s ease, transform 0.2s ease;
}
.badges-card:hover {
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.15), 0 0 20px var(--badge-tier-glow, transparent);
    transform: translateY(-1px);
}

.badges-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.35rem;
}

.badges-card-name {
    font-size: 0.9rem;
    font-weight: 800;
    color: var(--text-primary);
}

.badges-card-tier {
    flex-shrink: 0;
    font-size: 0.68rem;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: var(--radius-sm);
}

.badges-card-desc {
    font-size: 0.78rem;
    color: var(--text-secondary);
    line-height: 1.4;
    margin-bottom: 0.4rem;
}

.badges-card-category {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.72rem;
    color: var(--text-secondary);
    text-transform: capitalize;
}

.badges-cat-dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
}

/* Progress to next tier — with glow */
.badges-progress-track {
    height: 4px;
    background: var(--bg-secondary);
    border-radius: 4px;
    overflow: hidden;
    margin-top: 0.5rem;
}

.badges-progress-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
    box-shadow: 0 0 6px var(--badge-tier-glow, transparent);
}

.badges-progress-label {
    font-size: 0.68rem;
    color: var(--text-secondary);
    margin-top: 0.2rem;
}

/* Radar section */
.badges-radar-section {
    margin-top: 1.2rem;
    text-align: center;
}

.badges-radar-label {
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.5rem;
}

.badges-radar-canvas {
    display: block;
    margin: 0 auto;
    max-width: 100%;
}

/* Coaching insight — pit crew note */
.badges-coaching {
    margin-top: 1.2rem;
    padding: 0.8rem 1.1rem;
    background: rgba(255, 255, 255, 0.02);
    border-left: 3px solid;
    border-image: linear-gradient(to bottom, var(--accent), rgba(255,107,53,0.3)) 1;
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    font-size: 0.85rem;
    color: var(--text-primary);
    line-height: 1.5;
}

.badges-coaching-label {
    color: var(--accent);
    font-size: 0.78rem;
    font-family: var(--font-mono);
    letter-spacing: 0.04em;
}

/* ── Shared animation for card entrance ── */
@keyframes fadeSlideUp {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* ── Debrief / Badges responsive ── */
@media (max-width: 600px) {
    .debrief-hero {
        flex-direction: column;
        text-align: center;
    }
    .debrief-hero-numbers {
        justify-content: center;
    }
    .debrief-actions-grid,
    .debrief-highlights,
    .badges-card-grid {
        grid-template-columns: 1fr;
    }
    .badges-tier-row {
        gap: 0.6rem;
    }
    .badges-tier-box {
        min-width: 56px;
        padding: 0.5rem 0.8rem;
    }
}
```

**Step 2: Commit**

```bash
git add telemetry_tool/web/static/css/main.css
git commit -m "feat: premium motorsport styling for achievements badges section"
```

---

## Task 7: Achievements Badges JS — Metallic Data Attributes and Tooltips

**Files:**
- Modify: `telemetry_tool/web/static/js/session_badges.js` (lines 51–159)

**Step 1: Update the tier counter rendering**

In the tier summary counters section (around line 77), add `data-tier` attributes to `.badges-tier-box` and `.badges-tier-num` elements, plus a tooltip on the box:

Replace the tier counter block (lines 77–89) with:

```javascript
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
```

**Step 2: Add tooltip to star rating**

In the star hero section (around line 70), add a tooltip to the star meta line:

Replace line 70–73 with:
```javascript
        var starMeta = _el("div", "badges-star-meta tip tip-bottom tip-wrap");
        starMeta.setAttribute("data-tip", "Star rating computed from your overall badge tier distribution");
        starMeta.textContent = (data.star_rating || 0).toFixed(1) + " / 5.0 stars \u00B7 " +
            (data.badge_count || 0) + " badges earned";
        starHero.appendChild(starMeta);
```

**Step 3: Add per-category tooltip to badge cards**

In the badge card category section (around line 117–122), add a category tooltip:

```javascript
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
```

Note: Move the CATEGORY_TIPS object to the top of the render function (or outside it) to avoid recreating it per-badge. Better pattern: define it once at module scope alongside TIER_COLORS.

**Step 4: Verify**

Load a session with badge data. Verify:
- Stars are larger with gold gradient and glow animation
- Tier counter boxes have metallic borders and glow on hover
- Badge cards have top accent stripe, inner shadow, bolder name
- Hover tooltips appear on tier counters, star rating meta, and category labels
- Coaching box has darker "pit crew note" styling

**Step 5: Commit**

```bash
git add telemetry_tool/web/static/js/session_badges.js
git commit -m "feat: add data-tier attributes and tooltips to badges for premium styling"
```

---

## Task 8: Global Tooltips on Server-Rendered Headings

**Files:**
- Modify: `telemetry_tool/web/templates/session_detail.html`

**Step 1: Add tooltip ⓘ to section headings**

In `session_detail.html`, update the following `<h2>` headings to include a tooltip info icon:

**Score Breakdown** (line 107):
```html
    <h2>Score Breakdown <span class="tip tip-right tip-wrap" data-tip="Weighted score from pace, consistency, execution, and robustness — each pillar measures a different dimension of performance">ⓘ</span></h2>
```

**Session Debrief** (line 267):
```html
    <h2>Session Debrief <span class="tip tip-right tip-wrap" data-tip="AI-generated performance report with highlights, key metrics, areas to improve, and your next-session action plan">ⓘ</span></h2>
```

**Achievements & Rating** (line 276):
```html
    <h2>Achievements & Rating <span class="tip tip-right tip-wrap" data-tip="Badges earned from this session based on pace, consistency, endurance, flow, and improvement. Aim for gold tier.">ⓘ</span></h2>
```

**Performance Fingerprint** — find the Performance Fingerprint `<h2>` in the template and add:
```html
    <h2>Performance Fingerprint <span class="tip tip-right tip-wrap" data-tip="Radar signature of your driving across key performance dimensions">ⓘ</span></h2>
```

Note: The Driving Style `<h2>` tooltip was already added in Task 4. The Score sub-bar tooltips already exist (line 120 uses `data-tip`). The debrief sub-label tooltips will be added in summary_report.js.

**Step 2: Add tooltips to debrief sub-labels in `summary_report.js`**

In `summary_report.js`, where section labels are created, add tooltips:

For "Highlights" label (around line 94):
```javascript
            var hlLabel = _text("div", "debrief-section-label", "Highlights");
            var hlTip = _el("span", "tip tip-right tip-wrap debrief-section-tip");
            hlTip.setAttribute("data-tip", "The strongest aspects of this session — what went well");
            hlTip.textContent = "\u24D8";
            hlLabel.appendChild(hlTip);
            frag.appendChild(hlLabel);
```

For "Key Metrics" label (around line 117):
```javascript
            var mLabel = _text("div", "debrief-section-label", "Key Metrics");
            var mTip = _el("span", "tip tip-right tip-wrap debrief-section-tip");
            mTip.setAttribute("data-tip", "Core performance numbers with context — how your metrics compare to expectations");
            mTip.textContent = "\u24D8";
            mLabel.appendChild(mTip);
            frag.appendChild(mLabel);
```

For "Areas for Improvement" label (around line 160):
```javascript
            var impLabel = _text("div", "debrief-section-label", "Areas for Improvement");
            var impTip = _el("span", "tip tip-right tip-wrap debrief-section-tip");
            impTip.setAttribute("data-tip", "Priority-ranked areas where focused practice will have the biggest impact");
            impTip.textContent = "\u24D8";
            impLabel.appendChild(impTip);
            frag.appendChild(impLabel);
```

Add small CSS for the debrief section tip icon:
```css
.debrief-section-tip {
    font-size: 0.72rem;
    color: var(--text-secondary);
    margin-left: 0.4rem;
    cursor: help;
    vertical-align: middle;
}
```

**Step 3: Verify**

- Hover over each section heading `ⓘ` icon — tooltip should appear
- Hover over Highlights, Key Metrics, Areas for Improvement sub-labels — tooltips should appear
- Tooltips should match the existing `data-tip` styling already in the CSS

**Step 4: Commit**

```bash
git add telemetry_tool/web/templates/session_detail.html telemetry_tool/web/static/js/summary_report.js telemetry_tool/web/static/css/main.css
git commit -m "feat: add hover tooltips across all overview section headings and sub-labels"
```

---

## Task 9: Final Integration Verification

**Step 1: Full page test**

Load a session detail page that has:
- Score data
- Driving style data
- Lap data (for debrief/badges)

Verify all four sections:
1. **Driving Style**: Qualitative labels, color-coded gauges, coaching tooltips, radar chart, strengths/weaknesses
2. **Next Session Actions**: Hero wrapper with accent gradient, larger title, visually separated
3. **Achievements**: Metallic stars with pulse animation, glassmorphism tier counters, premium badge cards with top stripe
4. **Tooltips**: ⓘ icons on all `<h2>` headings, tooltips on debrief sub-labels, tooltips on tier counters, star rating, category dots, and all driving style features

**Step 2: Test empty/missing data states**

- Load a session with NO driving style data → should show "No driving style data" or the container should not appear
- Load a session with < 3 laps → badges should show the coaching text fallback
- Load a session with no score data → score section should be hidden (existing `{% if score %}` guard)

**Step 3: Test responsive layout**

Resize browser to < 768px:
- Driving style layout should stack (gauges above, radar below)
- Badge card grid should go single-column
- Tier counters should shrink
- Actions hero should remain full-width

**Step 4: Final commit**

If any tweaks were needed during integration testing, commit them:
```bash
git add -u
git commit -m "fix: integration tweaks for report overview redesign"
```
