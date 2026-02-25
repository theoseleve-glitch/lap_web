# Race Strategy Tier 3 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add TeamTalk live chat, light/dark theme, multilingual (7 languages), and weather integration to the race strategy tool.

**Architecture:** Schema v21 adds `race_messages` table and `com_channel` column. Theme toggle via CSS custom properties on `:root[data-theme]`. i18n via JSON files + Flask `before_request` injection. Weather reuses existing meteo module APIs with new live dashboard cards.

**Tech Stack:** Python/Flask, SQLite, vanilla JS, CSS custom properties, Open-Meteo API, RainViewer API.

---

### Task 1: Schema — race_messages Table + com_channel Column

**Files:**
- Modify: `telemetry_tool/db/schema.py`
- Modify: `telemetry_tool/db/migrate.py`
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestTier3Schema:
    """Tier 3 schema: race_messages table and com_channel column."""

    def test_race_messages_table_exists(self, strategy_db):
        strategy_db.execute(
            "INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)"
        )
        strategy_db.execute(
            "INSERT INTO race_messages (race_id, author, message, category) "
            "VALUES (1, 'Engineer', 'Box box box', 'pit')"
        )
        row = strategy_db.execute("SELECT * FROM race_messages WHERE race_id = 1").fetchone()
        assert row["author"] == "Engineer"
        assert row["category"] == "pit"

    def test_race_messages_cascade_delete(self, strategy_db):
        strategy_db.execute("PRAGMA foreign_keys = ON")
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_messages (race_id, author, message) VALUES (1, 'A', 'test')")
        strategy_db.commit()
        strategy_db.execute("DELETE FROM race_configs WHERE race_id = 1")
        assert strategy_db.execute("SELECT COUNT(*) FROM race_messages").fetchone()[0] == 0

    def test_com_channel_column_exists(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, com_channel) "
            "VALUES (1, 'Alice', 1, 'CH 7')"
        )
        row = strategy_db.execute("SELECT com_channel FROM race_drivers WHERE race_id = 1").fetchone()
        assert row["com_channel"] == "CH 7"

    def test_schema_version_is_21(self, strategy_db):
        row = strategy_db.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        assert row["v"] == 21
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestTier3Schema -v`
Expected: FAIL — race_messages table doesn't exist

**Step 3: Implement schema changes**

In `telemetry_tool/db/schema.py`:

1. Change `SCHEMA_VERSION = 20` to `SCHEMA_VERSION = 21`

2. Add after PHASE_15_TABLES:

```python
# ------------------------------------------------------------------
# Phase 16 tables  (Tier 3: TeamTalk + driver COM)
# ------------------------------------------------------------------

_RACE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS race_messages (
    msg_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id      INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    author       TEXT    NOT NULL,
    message      TEXT    NOT NULL,
    category     TEXT    DEFAULT 'general',
    created_at   TEXT    DEFAULT (datetime('now'))
);
"""

PHASE_16_TABLES = [
    ("race_messages", _RACE_MESSAGES_TABLE),
]
```

3. Append `PHASE_16_TABLES` to `ALL_TABLES`:

```python
ALL_TABLES = (
    ...existing...
    + PHASE_16_TABLES
)
```

4. In the `_RACE_DRIVERS_TABLE` DDL (in PHASE_15_TABLES), add `com_channel TEXT` after `weight_kg REAL`.

In `telemetry_tool/db/migrate.py`, add after the version 20 entry:

```python
cur.execute(
    "INSERT OR IGNORE INTO schema_version (version, description) "
    "VALUES (?, ?);",
    (21, "Phase 16 — race messages + driver com_channel"),
)
```

**Step 4: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestTier3Schema -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add telemetry_tool/db/schema.py telemetry_tool/db/migrate.py telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(race-strategy): add race_messages table and com_channel column (schema v21)"
```

---

### Task 2: TeamTalk — API + Tests + Live Dashboard Card

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py`
- Modify: `telemetry_tool/web/templates/race_strategy/live.html`
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js`
- Modify: `telemetry_tool/web/static/css/race_strategy.css`
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestTeamTalk:
    """TeamTalk message CRUD."""

    def test_insert_and_retrieve_messages(self, strategy_db):
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_messages (race_id, author, message, category) VALUES (1, 'Eng', 'Box now', 'pit')")
        strategy_db.execute("INSERT INTO race_messages (race_id, author, message, category) VALUES (1, 'Spotter', 'Rain in 10', 'weather')")
        strategy_db.commit()
        msgs = strategy_db.execute("SELECT * FROM race_messages WHERE race_id = 1 ORDER BY msg_id").fetchall()
        assert len(msgs) == 2
        assert msgs[0]["category"] == "pit"
        assert msgs[1]["category"] == "weather"

    def test_messages_included_in_export(self, strategy_db):
        from web.routes.race_strategy_v2 import _build_export_dict
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute("INSERT INTO race_messages (race_id, author, message) VALUES (1, 'A', 'hello')")
        strategy_db.commit()
        result = _build_export_dict(strategy_db, 1)
        assert "messages" in result
        assert len(result["messages"]) == 1

    def test_com_channel_in_export(self, strategy_db):
        from web.routes.race_strategy_v2 import _build_export_dict
        strategy_db.execute("INSERT INTO race_configs (race_name, race_duration_s) VALUES ('R', 3600)")
        strategy_db.execute(
            "INSERT INTO race_drivers (race_id, driver_name, driver_order, com_channel) "
            "VALUES (1, 'A', 1, 'CH 5')"
        )
        strategy_db.commit()
        result = _build_export_dict(strategy_db, 1)
        assert result["drivers"][0]["com_channel"] == "CH 5"
```

**Step 2: Run tests to verify they fail**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestTeamTalk -v`
Expected: FAIL — `messages` key not in export

**Step 3: Add messages API route**

In `telemetry_tool/web/routes/race_strategy_v2.py`, add after the `api_reoptimize` route:

```python
@bp.route("/<int:race_id>/api/messages", methods=["GET", "POST"])
def api_messages(race_id: int):
    """Get or post race messages."""
    conn = get_db_connection()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        author = data.get("author", "").strip()
        message = data.get("message", "").strip()
        category = data.get("category", "general")
        if not author or not message:
            return jsonify({"error": "author and message required"}), 400
        conn.execute(
            "INSERT INTO race_messages (race_id, author, message, category) VALUES (?,?,?,?)",
            (race_id, author, message, category),
        )
        conn.commit()
        return jsonify({"ok": True})

    # GET: return all messages
    msgs = _rows_to_list(conn.execute(
        "SELECT * FROM race_messages WHERE race_id = ? ORDER BY msg_id", (race_id,)
    ).fetchall())
    return jsonify({"messages": msgs})
```

**Step 4: Add messages to api_state response**

In the `api_state` function, add after the `pit_stops` query:

```python
    messages = _rows_to_list(conn.execute(
        "SELECT * FROM race_messages WHERE race_id = ? ORDER BY msg_id", (race_id,)
    ).fetchall())
```

And add `"messages": messages,` to the returned jsonify dict.

**Step 5: Add messages to export and import**

In `_build_export_dict`, add after pit_stops query:

```python
    messages = _rows_to_list(conn.execute(
        "SELECT * FROM race_messages WHERE race_id = ? ORDER BY msg_id", (race_id,)
    ).fetchall())
```

And add `"messages": messages,` to the returned dict.

In `_import_race_from_dict`, add after pit stops import:

```python
    for m in data.get("messages", []):
        conn.execute(
            "INSERT INTO race_messages (race_id, author, message, category) VALUES (?,?,?,?)",
            (new_race_id, m.get("author", ""), m.get("message", ""), m.get("category", "general")),
        )
```

**Step 6: Add COM channel to config form driver rows**

In `telemetry_tool/web/templates/race_strategy/config.html`, add a COM channel input in each driver row (after weight field).

In `_save_drivers` function in the routes file, add `com_channel` to the INSERT:

```python
conn.execute(
    """INSERT INTO race_drivers (
        race_id, driver_name, driver_order, min_stint_s, max_stint_s,
        min_cumulative_s, max_cumulative_s, min_rest_s, weight_kg, com_channel
    ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
    (...existing params..., form.get(f"driver_com_{i}") or None),
)
```

**Step 7: Add COM column to detail page drivers table and live driver card**

In `detail.html`, add `<th>COM</th>` header and `<td>{{ d.com_channel or '—' }}</td>` cell.

In `live.html`, add a TeamTalk card (full-width) after the Race Summary card:

```html
    <!-- 7. TeamTalk -->
    <div class="rs-live-card" style="grid-column: 1 / -1;">
        <h3>Team Talk</h3>
        <div class="rs-chat-log" id="rs-chat-log"></div>
        <div class="rs-chat-input">
            <input type="text" id="rs-chat-author" placeholder="Name" style="width:100px;">
            <select id="rs-chat-category">
                <option value="general">General</option>
                <option value="pit">Pit</option>
                <option value="driver">Driver</option>
                <option value="weather">Weather</option>
                <option value="flag">Flag</option>
            </select>
            <input type="text" id="rs-chat-message" placeholder="Message..." style="flex:1;">
            <button type="button" id="rs-chat-send" class="btn btn-primary">Send</button>
        </div>
    </div>
```

**Step 8: Add JS rendering for TeamTalk**

In `race_strategy_live.js`, add a `updateChat()` function and wire the send button:

```javascript
    // ── TeamTalk ────────────────────────────

    var CATEGORY_COLORS = {
        pit: 'var(--red, #f85149)', weather: 'var(--blue)', flag: 'var(--yellow, #d29922)',
        driver: 'var(--green)', general: 'var(--text-secondary)'
    };
    var lastMsgCount = 0;

    function updateChat() {
        if (!state || !state.messages) return;
        var log = document.getElementById('rs-chat-log');
        if (!log || state.messages.length === lastMsgCount) return;
        lastMsgCount = state.messages.length;

        clearChildren(log);
        state.messages.forEach(function(m) {
            var row = document.createElement('div');
            row.className = 'rs-chat-row';
            var cat = document.createElement('span');
            cat.className = 'rs-chat-cat';
            cat.style.color = CATEGORY_COLORS[m.category] || CATEGORY_COLORS.general;
            cat.textContent = '[' + (m.category || 'general').toUpperCase() + ']';
            var author = document.createElement('strong');
            author.textContent = ' ' + m.author + ': ';
            var text = document.createElement('span');
            text.textContent = m.message;
            var time = document.createElement('span');
            time.className = 'rs-chat-time';
            time.textContent = m.created_at ? m.created_at.substring(11, 16) : '';
            row.appendChild(cat);
            row.appendChild(author);
            row.appendChild(text);
            row.appendChild(time);
            log.appendChild(row);
        });
        log.scrollTop = log.scrollHeight;
    }

    var chatSend = document.getElementById('rs-chat-send');
    if (chatSend) {
        chatSend.addEventListener('click', function() {
            var author = document.getElementById('rs-chat-author').value.trim();
            var message = document.getElementById('rs-chat-message').value.trim();
            var category = document.getElementById('rs-chat-category').value;
            if (!author || !message) return;
            fetch('/race-strategy/' + RACE_ID + '/api/messages', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({author: author, message: message, category: category})
            }).then(function() {
                document.getElementById('rs-chat-message').value = '';
                fetchState();
            });
        });
    }
```

Add `updateChat()` call after `updateStintLog()` in the `fetchState` callback.

**Step 9: Add CSS for TeamTalk**

Append to `race_strategy.css`:

```css
/* TeamTalk chat */
.rs-chat-log {
    max-height: 200px;
    overflow-y: auto;
    margin-bottom: 0.5rem;
    font-size: 0.85rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.5rem;
}
.rs-chat-row { padding: 0.15rem 0; }
.rs-chat-cat { font-size: 0.7rem; font-weight: 600; }
.rs-chat-time { float: right; font-size: 0.7rem; color: var(--text-secondary); }
.rs-chat-input {
    display: flex;
    gap: 0.5rem;
    align-items: center;
}
.rs-chat-input input, .rs-chat-input select {
    padding: 0.3rem 0.5rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg-secondary, #161b22);
    color: var(--text-primary, #e6edf3);
    font-size: 0.85rem;
}
```

Also add COM channel display in the Active Driver card: show `state.active_stint.com_channel` if present.

**Step 10: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestTeamTalk -v`
Expected: 3 PASSED

**Step 11: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/web/templates/race_strategy/ telemetry_tool/web/static/js/race_strategy_live.js telemetry_tool/web/static/css/race_strategy.css telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(race-strategy): add TeamTalk live chat and driver COM channel"
```

---

### Task 3: Light/Dark Theme Toggle

**Files:**
- Modify: `telemetry_tool/web/static/css/main.css`
- Modify: `telemetry_tool/web/static/js/theme.js`
- Modify: `telemetry_tool/web/templates/base.html`

**Step 1: Add light theme CSS variables**

In `telemetry_tool/web/static/css/main.css`, after the `:root {` block with dark theme variables, add:

```css
:root[data-theme="light"] {
    --bg-primary: #ffffff;
    --bg-secondary: #f6f8fa;
    --bg-tertiary: #eaeef2;
    --bg-card: #ffffff;
    --bg-hover: rgba(0,0,0,0.04);
    --text-primary: #1f2328;
    --text-secondary: #656d76;
    --text-muted: #8b949e;
    --accent: #0969da;
    --accent-dim: rgba(9,105,218,0.1);
    --accent-glow: rgba(9,105,218,0.3);
    --green: #1a7f37;
    --green-dim: rgba(26,127,55,0.1);
    --yellow: #9a6700;
    --red: #cf222e;
    --blue: #0969da;
    --purple: #8250df;
    --border: #d0d7de;
    --border-light: #e1e4e8;
    --shadow: 0 1px 3px rgba(0,0,0,0.12);
}
```

**Step 2: Update theme.js to handle toggle**

The existing `theme.js` reads CSS variables for canvas charts. Add theme detection and toggle logic at the top of the file (before the existing `colors` object):

```javascript
// ── Theme detection and toggle ──────────────
(function() {
    var html = document.documentElement;

    function getPreferred() {
        try {
            var saved = localStorage.getItem('theme');
            if (saved === 'light' || saved === 'dark') return saved;
        } catch(e) {}
        return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }

    function applyTheme(theme) {
        html.setAttribute('data-theme', theme);
        try { localStorage.setItem('theme', theme); } catch(e) {}
        // Update toggle button icon if present
        var btn = document.getElementById('theme-toggle');
        if (btn) btn.textContent = theme === 'dark' ? '\u2600' : '\u263E';
    }

    // Apply immediately (prevents flash)
    applyTheme(getPreferred());

    // Expose toggle for the nav button
    window.toggleTheme = function() {
        var current = html.getAttribute('data-theme') || 'dark';
        applyTheme(current === 'dark' ? 'light' : 'dark');
        // Re-hydrate canvas colors
        if (window.ThemeColors && window.ThemeColors.hydrate) {
            window.ThemeColors.hydrate();
        }
    };
})();
```

**Step 3: Add toggle button to base.html nav**

In `telemetry_tool/web/templates/base.html`, add a theme toggle button in the nav, before the `+ Analyze` link:

```html
            <button type="button" id="theme-toggle" class="nav-theme-toggle"
                    onclick="toggleTheme()" title="Toggle light/dark theme"
                    aria-label="Toggle theme">&#x263E;</button>
```

**Step 4: Add CSS for the toggle button**

In `main.css`, add:

```css
.nav-theme-toggle {
    background: none;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.2rem 0.5rem;
    font-size: 1rem;
    cursor: pointer;
    color: var(--text-primary);
    line-height: 1;
}
```

**Step 5: Move theme.js to load in head**

In `base.html`, move the theme.js script tag from the bottom to inside `<head>`, after the CSS link:

```html
    <link rel="stylesheet" href="/static/css/main.css">
    <script src="{{ url_for('static', filename='js/theme.js') }}"></script>
```

Remove the duplicate script tag from the bottom of the file.

**Step 6: Verify manually**

Load any page, click toggle, verify colors switch. Reload, verify preference persists. In a fresh browser with system light mode, verify auto-detect works.

**Step 7: Commit**

```bash
git add telemetry_tool/web/static/css/main.css telemetry_tool/web/static/js/theme.js telemetry_tool/web/templates/base.html
git commit -m "feat: add light/dark theme toggle with system preference detection"
```

---

### Task 4: Multilingual (i18n) — 7 Languages

**Files:**
- Create: `telemetry_tool/web/i18n/en.json`
- Create: `telemetry_tool/web/i18n/fr.json`
- Create: `telemetry_tool/web/i18n/it.json`
- Create: `telemetry_tool/web/i18n/de.json`
- Create: `telemetry_tool/web/i18n/es.json`
- Create: `telemetry_tool/web/i18n/pt.json`
- Create: `telemetry_tool/web/i18n/zh.json`
- Modify: `telemetry_tool/web/app.py`
- Modify: `telemetry_tool/web/templates/base.html`
- Modify: all 5 race strategy templates
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestI18n:
    """Multilingual translation loading."""

    def test_load_english(self):
        from web.i18n import load_translations
        t = load_translations("en")
        assert t["race_strategy"] == "Race Strategy"
        assert t["driver"] == "Driver"

    def test_load_french(self):
        from web.i18n import load_translations
        t = load_translations("fr")
        assert t["race_strategy"] == "Stratégie de Course"

    def test_fallback_to_english(self):
        from web.i18n import load_translations
        t = load_translations("xx")  # unknown language
        assert t["race_strategy"] == "Race Strategy"

    def test_missing_key_returns_english(self):
        from web.i18n import load_translations
        t = load_translations("fr")
        # Access a key that exists in en but might be missing in fr
        # The loader should merge with English fallback
        assert "race_strategy" in t
```

**Step 2: Create the i18n module**

Create `telemetry_tool/web/i18n/__init__.py`:

```python
"""Lightweight i18n for race strategy pages."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_I18N_DIR = Path(__file__).parent
_CACHE = {}
SUPPORTED_LANGUAGES = ["en", "fr", "it", "de", "es", "pt", "zh"]


def load_translations(lang: str) -> dict:
    """Load translations for a language, falling back to English for missing keys."""
    if lang not in SUPPORTED_LANGUAGES:
        lang = "en"

    if lang in _CACHE:
        return _CACHE[lang]

    # Always load English as base
    en_path = _I18N_DIR / "en.json"
    try:
        en = json.loads(en_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        en = {}

    if lang == "en":
        _CACHE["en"] = en
        return en

    # Load target language and merge with English fallback
    lang_path = _I18N_DIR / f"{lang}.json"
    try:
        translations = json.loads(lang_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("Translation file %s not found, falling back to English", lang_path)
        translations = {}

    merged = {**en, **translations}
    _CACHE[lang] = merged
    return merged
```

**Step 3: Create en.json (source of truth)**

Create `telemetry_tool/web/i18n/en.json`:

```json
{
    "race_strategy": "Race Strategy",
    "new_race": "New Race",
    "import": "Import",
    "export_json": "Export JSON",
    "back": "Back",
    "edit_config": "Edit Config",
    "delete": "Delete",
    "duplicate": "Duplicate",
    "save": "Save",
    "cancel": "Cancel",
    "race": "Race",
    "race_name": "Race Name",
    "track": "Track",
    "team": "Team",
    "duration": "Duration",
    "desired_stints": "Desired Stints",
    "min_pit_stop": "Min Pit Stop",
    "fuel_autonomy": "Fuel Autonomy",
    "stints": "Stints",
    "stint": "Stint",
    "stint_plan": "Stint Plan",
    "stint_log": "Stint Log",
    "stint_order": "Stint Order",
    "drivers": "Drivers",
    "driver": "Driver",
    "driver_name": "Driver Name",
    "weight": "Weight",
    "min_stint": "Min Stint",
    "max_stint": "Max Stint",
    "min_cumulative": "Min Cumul.",
    "max_cumulative": "Max Cumul.",
    "min_rest": "Min Rest",
    "com_channel": "COM Channel",
    "pit_stops": "Pit Stops",
    "pit_window": "Pit Window",
    "pit_open": "Pit Open",
    "pit_close": "Pit Close",
    "optimize": "Optimize Stints",
    "go_live": "Go Live",
    "finish_race": "Finish Race",
    "open_live": "Open Live Dashboard",
    "view_summary": "View Summary",
    "view_config": "View Config",
    "status": "Status",
    "draft": "Draft",
    "ready": "Ready",
    "live": "Live",
    "finished": "Finished",
    "planned": "Planned",
    "actual": "Actual",
    "delta": "Delta",
    "ballast": "Ballast",
    "notes": "Notes",
    "fuel": "Fuel",
    "fuel_ballast": "Fuel & Ballast",
    "qualifying": "Qualifying",
    "refuel_after": "Refuel After",
    "first_stint_fuel": "First Stint Fuel",
    "team_talk": "Team Talk",
    "send": "Send",
    "message": "Message",
    "name": "Name",
    "general": "General",
    "pit": "Pit",
    "flag": "Flag",
    "weather": "Weather",
    "remaining": "Remaining",
    "elapsed": "Elapsed",
    "race_timer": "Race Timer",
    "current_driver": "Current Driver",
    "next_driver": "Next Driver",
    "race_summary": "Race Summary",
    "on_plan": "ON PLAN",
    "ahead": "AHEAD",
    "behind": "BEHIND",
    "grid_view": "Grid",
    "vertical_view": "Vertical",
    "saved_races": "Saved Races",
    "no_races": "No races yet. Create your first race to get started.",
    "no_drivers": "No drivers added yet.",
    "created": "Created",
    "start": "Start",
    "end": "End",
    "after_stint": "After Stint",
    "at": "At",
    "driver_change": "Driver Change",
    "refuel": "Refuel",
    "yes": "Yes",
    "no": "No",
    "total_drive_time": "Total Drive Time",
    "total_pit_time": "Total Pit Time",
    "driver_stats": "Driver Stats",
    "longest": "Longest",
    "shortest": "Shortest",
    "end_stint": "End Stint",
    "reoptimize": "Re-Optimize",
    "duplicate_race": "Duplicate Race",
    "language": "Language"
}
```

**Step 4: Create fr.json**

```json
{
    "race_strategy": "Stratégie de Course",
    "new_race": "Nouvelle Course",
    "import": "Importer",
    "export_json": "Exporter JSON",
    "back": "Retour",
    "edit_config": "Modifier Config",
    "delete": "Supprimer",
    "duplicate": "Dupliquer",
    "save": "Enregistrer",
    "cancel": "Annuler",
    "race": "Course",
    "race_name": "Nom de Course",
    "track": "Circuit",
    "team": "Équipe",
    "duration": "Durée",
    "desired_stints": "Relais Souhaités",
    "min_pit_stop": "Arrêt Min.",
    "fuel_autonomy": "Autonomie Carburant",
    "stints": "Relais",
    "stint": "Relai",
    "stint_plan": "Plan de Relais",
    "stint_log": "Journal des Relais",
    "stint_order": "Ordre des Relais",
    "drivers": "Pilotes",
    "driver": "Pilote",
    "driver_name": "Nom du Pilote",
    "weight": "Poids",
    "min_stint": "Relai Min.",
    "max_stint": "Relai Max.",
    "min_cumulative": "Cumul. Min.",
    "max_cumulative": "Cumul. Max.",
    "min_rest": "Repos Min.",
    "com_channel": "Canal COM",
    "pit_stops": "Arrêts au Stand",
    "pit_window": "Fenêtre de Stand",
    "pit_open": "Ouverture Stand",
    "pit_close": "Fermeture Stand",
    "optimize": "Optimiser les Relais",
    "go_live": "Démarrer",
    "finish_race": "Terminer la Course",
    "open_live": "Ouvrir le Tableau de Bord",
    "view_summary": "Voir le Résumé",
    "view_config": "Voir la Config",
    "status": "Statut",
    "draft": "Brouillon",
    "ready": "Prêt",
    "live": "En Direct",
    "finished": "Terminé",
    "planned": "Planifié",
    "actual": "Réel",
    "delta": "Écart",
    "ballast": "Lest",
    "notes": "Notes",
    "fuel": "Carburant",
    "fuel_ballast": "Carburant & Lest",
    "qualifying": "Qualifications",
    "refuel_after": "Ravitaillement Après",
    "first_stint_fuel": "Carburant 1er Relai",
    "team_talk": "Com. Équipe",
    "send": "Envoyer",
    "message": "Message",
    "name": "Nom",
    "general": "Général",
    "pit": "Stand",
    "flag": "Drapeau",
    "weather": "Météo",
    "remaining": "Restant",
    "elapsed": "Écoulé",
    "race_timer": "Chrono Course",
    "current_driver": "Pilote Actuel",
    "next_driver": "Prochain Pilote",
    "race_summary": "Résumé de Course",
    "on_plan": "DANS LE PLAN",
    "ahead": "EN AVANCE",
    "behind": "EN RETARD",
    "grid_view": "Grille",
    "vertical_view": "Vertical",
    "saved_races": "Courses Enregistrées",
    "no_races": "Aucune course. Créez votre première course.",
    "no_drivers": "Aucun pilote ajouté.",
    "created": "Créé",
    "start": "Début",
    "end": "Fin",
    "after_stint": "Après Relai",
    "at": "À",
    "driver_change": "Changement Pilote",
    "refuel": "Ravitaillement",
    "yes": "Oui",
    "no": "Non",
    "total_drive_time": "Temps de Conduite Total",
    "total_pit_time": "Temps d'Arrêt Total",
    "driver_stats": "Stats Pilotes",
    "longest": "Plus Long",
    "shortest": "Plus Court",
    "end_stint": "Fin de Relai",
    "reoptimize": "Ré-Optimiser",
    "duplicate_race": "Dupliquer la Course",
    "language": "Langue"
}
```

**Step 5: Create remaining language files (it, de, es, pt, zh)**

Create each as a JSON file with translated values. Follow the same key structure as en.json.

**Step 6: Wire i18n into Flask app**

In `telemetry_tool/web/app.py`, add a `before_request` hook:

```python
@app.before_request
def load_i18n():
    """Load translations for race strategy pages."""
    from web.i18n import load_translations, SUPPORTED_LANGUAGES
    lang = request.cookies.get("lang") or request.args.get("lang", "en")
    if lang not in SUPPORTED_LANGUAGES:
        lang = "en"
    g.t = load_translations(lang)
    g.lang = lang
    g.supported_languages = SUPPORTED_LANGUAGES
```

And make `g.t` available in templates via context processor:

```python
@app.context_processor
def inject_i18n():
    from flask import g
    return {"t": getattr(g, "t", {}), "lang": getattr(g, "lang", "en"),
            "supported_languages": getattr(g, "supported_languages", ["en"])}
```

**Step 7: Add language picker to base.html nav**

Add a small select dropdown in the nav bar, before the theme toggle:

```html
            <select id="lang-picker" class="nav-lang-picker" onchange="setLang(this.value)" title="Language">
                {% for l in supported_languages %}
                <option value="{{ l }}" {% if l == lang %}selected{% endif %}>{{ l.upper() }}</option>
                {% endfor %}
            </select>
```

With JS:
```javascript
window.setLang = function(lang) {
    document.cookie = 'lang=' + lang + ';path=/;max-age=31536000';
    location.reload();
};
```

**Step 8: Update race strategy templates to use `{{ t.key }}`**

Replace hardcoded English strings in all 5 race strategy templates with `{{ t.key_name }}` lookups. Example replacements:

- `"Race Strategy"` → `{{ t.race_strategy }}`
- `"Drivers"` → `{{ t.drivers }}`
- `"Stints"` → `{{ t.stints }}`
- `"Export JSON"` → `{{ t.export_json }}`
- etc.

**Step 9: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestI18n -v`
Expected: 4 PASSED

**Step 10: Commit**

```bash
git add telemetry_tool/web/i18n/ telemetry_tool/web/app.py telemetry_tool/web/templates/ telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(race-strategy): add multilingual support — 7 languages"
```

---

### Task 5: Weather Integration — Conditions, Forecast, Pace, Fuel, Radar

**Files:**
- Modify: `telemetry_tool/web/routes/race_strategy_v2.py`
- Modify: `telemetry_tool/web/templates/race_strategy/live.html`
- Modify: `telemetry_tool/web/static/js/race_strategy_live.js`
- Modify: `telemetry_tool/web/static/css/race_strategy.css`
- Modify: `telemetry_tool/tests/test_race_strategy_v2.py`

**Step 1: Write the failing tests**

Append to `telemetry_tool/tests/test_race_strategy_v2.py`:

```python
class TestWeatherIntegration:
    """Weather features for race strategy."""

    def test_fuel_adjustment_wet(self):
        """Wet grip factor reduces effective fuel autonomy."""
        from wet_physics import get_grip_factor
        grip = get_grip_factor("wet")
        base_autonomy = 2400
        adjusted = int(base_autonomy * grip)
        assert adjusted < base_autonomy
        assert adjusted > 0

    def test_fuel_adjustment_dry(self):
        """Dry conditions don't reduce autonomy."""
        from wet_physics import get_grip_factor
        grip = get_grip_factor("dry")
        base_autonomy = 2400
        adjusted = int(base_autonomy * grip)
        assert adjusted == base_autonomy

    def test_track_conditions_from_weather(self):
        """estimate_track_conditions returns grip info."""
        from meteo_service import estimate_track_conditions
        weather = {
            "air_temp_c": 20, "humidity_pct": 50, "wind_speed_mps": 3,
            "rain_mm": 0, "cloud_cover_pct": 30
        }
        result = estimate_track_conditions(weather)
        assert "track_state" in result
        assert "grip_score" in result
```

**Step 2: Add weather API route for race strategy**

In `telemetry_tool/web/routes/race_strategy_v2.py`, add:

```python
@bp.route("/<int:race_id>/api/weather")
def api_weather(race_id: int):
    """Current weather + forecast + pace estimate for race track."""
    conn = get_db_connection()
    race = _row_to_dict(conn.execute("SELECT * FROM race_configs WHERE race_id = ?", (race_id,)).fetchone())
    if not race:
        return jsonify({"error": "not found"}), 404

    track_name = race.get("track_name")
    if not track_name:
        return jsonify({"error": "no track configured"}), 400

    # Find track coordinates
    try:
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
        from meteo_service import get_known_tracks, fetch_current_weather, get_weather_forecast, estimate_track_conditions

        tracks = get_known_tracks(conn)
        track = next((t for t in tracks if t.get("track_name", "").lower() == track_name.lower()), None)
        if not track or not track.get("lat") or not track.get("lon"):
            return jsonify({"error": "track coordinates not found"}), 400

        lat, lon = track["lat"], track["lon"]

        # Current conditions
        current = fetch_current_weather(lat, lon)
        conditions = estimate_track_conditions(current) if current else {}

        # Forecast
        race_hours = max(1, (race.get("race_duration_s") or 3600) // 3600 + 1)
        forecast = get_weather_forecast(lat, lon, hours=race_hours)

        # Fuel adjustment
        fuel_autonomy = race.get("fuel_autonomy_s")
        adjusted_autonomy = None
        if fuel_autonomy and conditions.get("grip_score"):
            from wet_physics import get_grip_factor
            grip = get_grip_factor(conditions.get("track_state", "dry"))
            adjusted_autonomy = int(fuel_autonomy * grip)

        return jsonify({
            "current": current,
            "conditions": conditions,
            "forecast": forecast,
            "fuel_autonomy_adjusted_s": adjusted_autonomy,
            "lat": lat,
            "lon": lon,
        })
    except Exception as e:
        logger.warning("Weather fetch failed: %s", e)
        return jsonify({"error": str(e)}), 500
```

**Step 3: Add weather card and radar to live.html**

Add data attribute for track name on the root div:
```
     data-track-name="{{ race.track_name or '' }}"
```

Add two new cards after TeamTalk:

```html
    <!-- 8. Weather -->
    <div class="rs-live-card" id="rs-weather-card" style="display:none;">
        <h3>{{ t.weather if t else 'Weather' }}</h3>
        <div id="rs-weather-data"></div>
        <div id="rs-weather-pace" style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.5rem;"></div>
    </div>

    <!-- 9. Rain Radar -->
    <div class="rs-live-card" id="rs-radar-card" style="display:none;">
        <h3>Rain Radar</h3>
        <div id="rs-radar-wrap" style="height:200px;border-radius:4px;overflow:hidden;"></div>
    </div>
```

**Step 4: Add forecast overlay to stint timeline**

Add a div above the stint timeline card for hourly forecast:

```html
        <div id="rs-forecast-bar" class="rs-forecast-bar" style="display:none;"></div>
```

**Step 5: Add JS weather logic**

In `race_strategy_live.js`, add weather fetch and rendering:

```javascript
    // ── Weather ────────────────────────────

    var weatherData = null;
    var TRACK_NAME = root.getAttribute('data-track-name') || '';

    function fetchWeather() {
        if (!TRACK_NAME) return;
        fetch('/race-strategy/' + RACE_ID + '/api/weather')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) return;
                weatherData = data;
                renderWeather();
                renderForecast();
                renderRadar(data.lat, data.lon);
                updateFuelWeather();
            })
            .catch(function() {});
    }

    function renderWeather() {
        if (!weatherData || !weatherData.current) return;
        var card = document.getElementById('rs-weather-card');
        var el = document.getElementById('rs-weather-data');
        if (!card || !el) return;
        card.style.display = '';

        var w = weatherData.current;
        var c = weatherData.conditions || {};
        clearChildren(el);

        var items = [
            ['Temp', (w.air_temp_c || '--') + '°C'],
            ['Humidity', (w.humidity_pct || '--') + '%'],
            ['Wind', (w.wind_speed_mps ? (w.wind_speed_mps * 3.6).toFixed(0) + ' km/h' : '--')],
            ['Rain', (w.rain_mm || 0) + ' mm'],
            ['Grip', c.track_state || 'unknown'],
        ];
        items.forEach(function(item) {
            var row = document.createElement('div');
            row.className = 'rs-kv';
            row.style.fontSize = '0.85rem';
            var label = document.createElement('span');
            label.className = 'rs-kv-label';
            label.textContent = item[0];
            var val = document.createElement('span');
            val.textContent = item[1];
            row.appendChild(label);
            row.appendChild(val);
            el.appendChild(row);
        });

        // Pace estimate
        var paceEl = document.getElementById('rs-weather-pace');
        if (paceEl && c.grip_score) {
            paceEl.textContent = 'Grip score: ' + (c.grip_score * 100).toFixed(0) + '%';
        }
    }

    function renderForecast() {
        if (!weatherData || !weatherData.forecast) return;
        var bar = document.getElementById('rs-forecast-bar');
        if (!bar) return;
        bar.style.display = 'flex';
        clearChildren(bar);

        var hours = weatherData.forecast.hourly || [];
        hours.forEach(function(h) {
            var block = document.createElement('div');
            block.className = 'rs-forecast-hour';
            block.style.flex = '1';
            var rain = h.rain_mm || 0;
            var opacity = Math.min(1, rain / 5);
            block.style.background = 'rgba(88,166,255,' + opacity + ')';
            block.title = (h.time || '') + ': ' + (h.air_temp_c || '--') + '°C, rain: ' + rain + 'mm';
            bar.appendChild(block);
        });
    }

    function renderRadar(lat, lon) {
        if (!lat || !lon) return;
        var card = document.getElementById('rs-radar-card');
        var wrap = document.getElementById('rs-radar-wrap');
        if (!card || !wrap) return;
        card.style.display = '';

        // RainViewer API: get latest radar frame
        fetch('https://api.rainviewer.com/public/weather-maps.json')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.radar || !data.radar.past || !data.radar.past.length) return;
                var latest = data.radar.past[data.radar.past.length - 1];
                var tileUrl = data.host + latest.path + '/256/6/'
                    + Math.floor(lat / (180 / Math.pow(2, 5)))
                    + '/' + Math.floor((lon + 180) / (360 / Math.pow(2, 6)))
                    + '/2/1_1.png';
                wrap.style.backgroundImage = 'url(' + tileUrl + ')';
                wrap.style.backgroundSize = 'cover';
                wrap.style.backgroundPosition = 'center';
            })
            .catch(function() {});
    }

    function updateFuelWeather() {
        if (!weatherData || !weatherData.fuel_autonomy_adjusted_s) return;
        if (!FUEL_AUTONOMY) return;
        var adj = weatherData.fuel_autonomy_adjusted_s;
        if (adj < FUEL_AUTONOMY) {
            var el = document.getElementById('rs-fuel-autonomy');
            if (el) {
                var current = el.textContent;
                el.textContent = current + ' (wet: ~' + fmtShort(adj) + ')';
            }
        }
    }

    // Fetch weather on load and every 5 minutes
    if (TRACK_NAME) {
        fetchWeather();
        setInterval(fetchWeather, 300000);
    }
```

**Step 6: Add CSS for weather and forecast**

Append to `race_strategy.css`:

```css
/* Weather card */
#rs-weather-card .rs-kv { display: flex; justify-content: space-between; padding: 0.15rem 0; }

/* Forecast bar */
.rs-forecast-bar {
    display: flex;
    height: 16px;
    gap: 1px;
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 0.5rem;
}
.rs-forecast-hour {
    min-width: 4px;
    border-radius: 2px;
}

/* Radar */
#rs-radar-wrap {
    background: var(--bg-secondary);
}
```

**Step 7: Run tests to verify they pass**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py::TestWeatherIntegration -v`
Expected: 3 PASSED

**Step 8: Commit**

```bash
git add telemetry_tool/web/routes/race_strategy_v2.py telemetry_tool/web/templates/race_strategy/live.html telemetry_tool/web/static/js/race_strategy_live.js telemetry_tool/web/static/css/race_strategy.css telemetry_tool/tests/test_race_strategy_v2.py
git commit -m "feat(race-strategy): add weather integration — conditions, forecast, fuel adjust, radar"
```

---

### Task 6: Final Verification

**Step 1: Run full race strategy tests**

Run: `pytest telemetry_tool/tests/test_race_strategy_v2.py -v`
Expected: ALL tests pass (schema + optimizer + ballast + import/export + qualifying + pit windows + tier3 schema + teamtalk + i18n + weather)

**Step 2: Run full test suite**

Run: `pytest telemetry_tool/tests/ -x -q`
Expected: ALL PASSED, no regressions

**Step 3: Commit any cleanup**

If any fixes needed, commit with appropriate message.
