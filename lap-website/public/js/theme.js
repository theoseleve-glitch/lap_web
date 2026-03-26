/**
 * theme.js — Theme detection/toggle + centralized canvas color palette.
 *
 * Theme toggle: auto-detects system preference on first visit, saves to
 * localStorage, prevents flash by running in <head> before CSS paints.
 *
 * Canvas palette: reads colors from :root CSS variables so all canvas-based
 * charts use the design system rather than hardcoded hex values.
 *
 * Usage:
 *   var C = window.Theme.colors;
 *   ctx.fillStyle = C.bgCard;      // was '#1a1f2e'
 *   ctx.strokeStyle = C.accent;    // was '#ff6b35'
 *   ctx.fillStyle = C.textPrimary; // was '#e6edf3'
 *
 * Also provides:
 *   window.Theme.lapColor(index) — deterministic lap palette color
 *   window.Theme.heatColor(t)    — 0..1 interpolation (green→yellow→red)
 *   window.toggleTheme()         — toggle light/dark
 */

// ── Theme detection and toggle (runs immediately) ──
(function() {
    var html = document.documentElement;

    function getPreferred() {
        // Dark theme only — light theme suppressed
        return 'dark';
    }

    function applyTheme(theme) {
        html.setAttribute('data-theme', theme);
        try { localStorage.setItem('theme', theme); } catch(e) {}
        var btn = document.getElementById('theme-toggle');
        if (btn) btn.textContent = theme === 'dark' ? '\u2600' : '\u263E';
    }

    applyTheme(getPreferred());

    window.toggleTheme = function() {
        // Dark theme only — toggle suppressed
    };
})();

// ── Language selector ──
window.setLang = function(lang) {
    document.cookie = 'lang=' + lang + ';path=/;max-age=31536000';
    location.reload();
};

(function () {
    'use strict';

    /* ── Read a CSS variable from :root ────────── */
    function cssVar(name, fallback) {
        var val = getComputedStyle(document.documentElement)
            .getPropertyValue(name)
            .trim();
        return val || fallback;
    }

    /* ── Color palette — mirrors :root in main.css ── */
    var colors = {
        /* Backgrounds */
        bgPrimary:   '#000000',
        bgSecondary: '#141414',
        bgTertiary:  'rgba(240, 237, 229, 0.04)',
        bgCard:      '#141414',
        bgHover:     'rgba(240, 237, 229, 0.06)',

        /* Text */
        textPrimary:   '#F0EDE5',
        textSecondary: '#949494',
        textMuted:     '#9CA3AF',

        /* Accent */
        accent:     '#F0EDE5',
        accentDim:  'rgba(240, 237, 229, 0.22)',

        /* Status */
        green:      '#22C55E',
        greenDim:   'rgba(34, 197, 94, 0.2)',
        yellow:     '#FACC15',
        red:        '#FF2A2A',
        blue:       '#3B82F6',
        cyan:       '#3B82F6',
        purple:     '#8B5CF6',

        /* Borders */
        border:      'rgba(148, 148, 148, 0.2)',
        borderLight: 'rgba(148, 148, 148, 0.1)',
    };

    var fonts = {
        body: '"Inter", "Segoe UI", sans-serif',
        mono: '"Space Mono", "Fira Code", monospace',
        display: '"Space Grotesk", "Arial Black", sans-serif',
    };

    /* ── Hydrate from live CSS (override defaults when DOM ready) ── */
    function hydrate() {
        colors.bgPrimary    = cssVar('--bg-primary',    colors.bgPrimary);
        colors.bgSecondary  = cssVar('--bg-secondary',  colors.bgSecondary);
        colors.bgTertiary   = cssVar('--bg-tertiary',   colors.bgTertiary);
        colors.bgCard       = cssVar('--bg-card',        colors.bgCard);
        colors.bgHover      = cssVar('--bg-hover',      colors.bgHover);

        colors.textPrimary   = cssVar('--text-primary',   colors.textPrimary);
        colors.textSecondary = cssVar('--text-secondary', colors.textSecondary);
        colors.textMuted     = cssVar('--text-muted',     colors.textMuted);

        colors.accent    = cssVar('--accent',     colors.accent);
        colors.accentDim = cssVar('--accent-dim', colors.accentDim);

        colors.green    = cssVar('--green',   colors.green);
        colors.greenDim = cssVar('--success-dim', colors.greenDim);
        colors.yellow   = cssVar('--yellow',  colors.yellow);
        colors.red      = cssVar('--red',     colors.red);
        colors.blue     = cssVar('--blue',    colors.blue);
        colors.cyan     = cssVar('--cyan',    colors.cyan);
        colors.purple   = cssVar('--purple',  colors.purple);

        colors.border      = cssVar('--border',       colors.border);
        colors.borderLight = cssVar('--border-subtle',  colors.borderLight);

        fonts.body = cssVar('--font-body', fonts.body);
        fonts.mono = cssVar('--font-mono', fonts.mono);
        fonts.display = cssVar('--font-display', fonts.display);
    }

    /* Hydrate immediately (CSS should be loaded before JS) */
    if (document.readyState !== 'loading') {
        hydrate();
    } else {
        document.addEventListener('DOMContentLoaded', hydrate);
    }

    /* ── Chart color themes ────────────────────── */
    var CHART_THEMES = {
        default: [
            '#22C55E', '#3B82F6', '#C9A84C', '#FF2A2A', '#8B5CF6',
            '#FACC15', '#EC4899', '#A78BFA', '#F59E0B', '#EF4444',
        ],
        highContrast: [
            '#F0EDE5', '#22C55E', '#3B82F6', '#C9A84C', '#FF2A2A',
            '#FACC15', '#8B5CF6', '#FFFFFF', '#22C55E', '#3B82F6',
        ],
        colorblind: [
            '#0077BB', '#EE7733', '#009988', '#CC3311', '#33BBEE',
            '#EE3377', '#BBBBBB', '#0077BB', '#EE7733', '#009988',
            '#CC3311', '#33BBEE', '#EE3377', '#BBBBBB', '#0077BB',
        ],
    };

    var activeThemeName = 'default';
    try {
        var stored = localStorage.getItem('chart_color_theme');
        if (stored && CHART_THEMES[stored]) activeThemeName = stored;
    } catch(e) {}

    var LAP_PALETTE = CHART_THEMES[activeThemeName].slice();

    function lapColor(index) {
        return LAP_PALETTE[index % LAP_PALETTE.length];
    }

    function setChartTheme(name) {
        if (!CHART_THEMES[name]) return;
        activeThemeName = name;
        var pal = CHART_THEMES[name];
        LAP_PALETTE.length = 0;
        for (var i = 0; i < pal.length; i++) LAP_PALETTE.push(pal[i]);
        try { localStorage.setItem('chart_color_theme', name); } catch(e) {}
    }

    function getChartThemeName() { return activeThemeName; }
    function getChartThemeNames() { return Object.keys(CHART_THEMES); }

    /* ── Heat color interpolation (0=green, 0.5=yellow, 1=red) ── */
    function heatColor(t) {
        t = Math.max(0, Math.min(1, t));
        if (t < 0.5) {
            // green → yellow
            var r = Math.round(63 + (210 - 63) * (t * 2));
            var g = Math.round(185 + (153 - 185) * (t * 2));
            var b = Math.round(80 + (34 - 80) * (t * 2));
            return 'rgb(' + r + ',' + g + ',' + b + ')';
        } else {
            // yellow → red
            var p = (t - 0.5) * 2;
            var r2 = Math.round(210 + (248 - 210) * p);
            var g2 = Math.round(153 + (81 - 153) * p);
            var b2 = Math.round(34 + (73 - 34) * p);
            return 'rgb(' + r2 + ',' + g2 + ',' + b2 + ')';
        }
    }

    /* ── Speed color (blue=slow → green=fast) ──── */
    function speedColor(t) {
        t = Math.max(0, Math.min(1, t));
        if (t < 0.5) {
            var r = Math.round(88 + (63 - 88) * (t * 2));
            var g = Math.round(166 + (185 - 166) * (t * 2));
            var b = Math.round(255 + (80 - 255) * (t * 2));
            return 'rgb(' + r + ',' + g + ',' + b + ')';
        } else {
            var p = (t - 0.5) * 2;
            var r2 = Math.round(63 + (255 - 63) * p);
            var g2 = Math.round(185 + (107 - 185) * p);
            var b2 = Math.round(80 + (53 - 80) * p);
            return 'rgb(' + r2 + ',' + g2 + ',' + b2 + ')';
        }
    }

    /* ── Public API ────────────────────────────── */
    window.Theme = {
        colors:           colors,
        fonts:            fonts,
        lapColor:         lapColor,
        heatColor:        heatColor,
        speedColor:       speedColor,
        hydrate:          hydrate,
        setChartTheme:    setChartTheme,
        getChartThemeName:  getChartThemeName,
        getChartThemeNames: getChartThemeNames,
        CHART_THEMES:     CHART_THEMES,
    };

    window.ModuleManager.register('theme', { init: function(){}, destroy: function(){} });
})();
