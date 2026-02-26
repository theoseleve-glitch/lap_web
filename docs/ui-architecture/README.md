# UI Architecture

Front-end design system for the Telemetry Analysis web dashboard. All CSS/JS is vanilla (no npm, no bundler). Chart.js via CDN. Canvas 2D for custom visualizations.

## Design Tokens (`tokens.css`)

Single source of truth for all visual values. Every color, spacing, shadow, radius, font, and motion timing is a CSS custom property.

**Backgrounds:** `--bg-void` through `--bg-active` (6 stops, dark-to-light)
**Text:** `--text-primary`, `--text-secondary`, `--text-muted`, `--text-inverse`
**Accent:** `--accent`, `--accent-hover`, `--accent-dim`, `--accent-glow`
**Status:** `--success`, `--warning`, `--danger`, `--info` (each with `-dim` variant)
**Spacing:** `--space-0` through `--space-8` (fluid via `clamp()`)
**Radii:** `--radius-xs` through `--radius-pill`
**Shadows:** `--shadow-sm`, `--shadow`, `--shadow-lg`, `--shadow-glow`
**Glass:** `--glass-bg`, `--glass-border`, `--glass-blur`
**Motion:** `--duration-instant` through `--duration-slower`, four easing curves
**Z-index:** `--z-base` (1) through `--z-skip` (10000)
**Touch:** `--touch-min` (44px), `--touch-comfortable` (48px)

### Theming

`tokens.css` defines dark (`:root`) and light (`:root[data-theme="light"]`) palettes. `theme.js` reads/writes `data-theme` attribute on `<html>`. Canvas charts hydrate colors from CSS variables via `Theme.colors`.

## Component Library

### Buttons (`.btn`)
Variants: `.btn-primary`, `.btn-ghost`, `.btn-danger`, `.btn-sm`, `.btn-lg`, `.btn-icon`, `.btn-loading`. All have `min-height: var(--touch-min)` except `.btn-sm` (36px).

### Cards (`.card`)
Variants: `.card--glass`, `.card--elevated`, `.card--interactive`. Sub-elements: `.card__header`, `.card__body`, `.card__footer`.

### Tables (`.data-table`)
Modifiers: `.compact`, `.striped`. Wrap in `.table-wrap` for horizontal scroll.

### Forms (`.form-input`, `.form-select`)
All have `min-height: var(--touch-min)`. `.form-group` with label auto-highlights on focus. `.is-invalid` + `.form-error` for validation.

### Chart Frame (`.chart-frame`)
Container for all charts. Sub-elements: `__header`, `__body`, `__footer`. States managed by `ChartFrame.setState()`: loading, empty, error, ready. Every chart-frame has `role="img"` and `aria-label`.

### Modal (`modal.js`)
`Modal.open({ title, body, footer })`. Focus trap, Escape to close, backdrop click. `z-index: var(--z-modal)`.

### Toast (`toast.js`)
`Toast.show(message, type)`. Types: success, error, info, warning. `z-index: var(--z-toast)`.

### Badges
`.badge` with status variants (`.badge-green`, `.badge-red`, etc.).

### KPI Cards (`.kpi-card`)
Glass-morphism stat cards with `.kpi-value` and `.kpi-label`.

## Responsive Strategy

Fluid tokens (`clamp()` spacing/fonts) handle most adaptation. Explicit breakpoints for layout shifts:

- **< 768px**: Single column, stacked cards, bottom-sheet modals
- **768px - 1280px**: Two-column grids, condensed nav
- **> 1280px**: Full multi-column layouts

## Z-Index Scale

| Layer | Token | Value | Usage |
|-------|-------|-------|-------|
| Base | `--z-base` | 1 | Elevated cards |
| Elevated | `--z-elevated` | 2 | Sticky section headers |
| Sticky | `--z-sticky` | 100 | Top nav |
| Dropdown | `--z-dropdown` | 200 | Menus, tabs |
| Overlay | `--z-overlay` | 1000 | Tooltips, context menus |
| Modal | `--z-modal` | 5000 | Modal dialogs |
| Toast | `--z-toast` | 9000 | Toast notifications |
| Skip | `--z-skip` | 10000 | Skip link |

## Motion Rules

1. Use token durations (`--duration-fast` through `--duration-slower`)
2. Use token easings (`--ease-out`, `--ease-in-out`, `--ease-spring`)
3. `prefers-reduced-motion` automatically zeros all durations via `tokens.css`
4. Theme transitions use `--duration-slow` on structural elements

## Module Lifecycle

All JS modules register with `ModuleManager.register(name, { init, destroy })`. Pages call `ModuleManager.activate([names])` to initialize a set and auto-destroy the previous set.

## File Structure

```
web/static/
  css/
    tokens.css          — Design tokens (loaded first)
    main.css            — Core styles, components, layout
    charts.css          — ChartFrame component
    utilities.css       — Utility classes
    motion.css          — Animation keyframes
    corner_replay.css   — Corner replay widget
    focus_mode.css      — Focus mode overlay
    gg_explorer.css     — G-G explorer
    speed_trace_zoom.css — Speed trace zoom
    race_strategy.css   — Race strategy pages
  js/
    theme.js            — Theme detection + canvas color palette
    toast.js            — Toast notifications
    fetch_helper.js     — Centralized fetch with error handling
    chart_frame.js      — Chart container state management
    module_manager.js   — Module lifecycle coordinator
    modal.js            — Modal dialog with focus trap
    ...                 — Feature-specific modules
```

## Performance Budgets

Enforced by `telemetry_tool/tests/performance/test_bundle_size.py`:
- CSS total: < 420 KB
- JS total: < 1.1 MB
- No single CSS file > 300 KB
- No single JS file > 80 KB
