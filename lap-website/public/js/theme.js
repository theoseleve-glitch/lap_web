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
        bgPrimary:   '#0d1117',
        bgSecondary: '#161b22',
        bgTertiary:  '#1c2333',
        bgCard:      '#1a1f2e',
        bgHover:     '#21273a',

        /* Text */
        textPrimary:   '#e6edf3',
        textSecondary: '#9CA3AF',
        textMuted:     '#6B7280',

        /* Accent */
        accent:     '#ff6b35',
        accentDim:  '#cc5529',

        /* Status */
        green:      '#3fb950',
        greenDim:   '#238636',
        yellow:     '#d29922',
        red:        '#f85149',
        blue:       '#58a6ff',
        purple:     '#bc8cff',

        /* Borders */
        border:      '#30363d',
        borderLight: '#21262d',
    };

    /* ── Hydrate from live CSS (override defaults when DOM ready) ── */
    function hydrate() {
        colors.bgPrimary    = cssVar('--bg-primary',    colors.bgPrimary);
        colors.bgSecondary  = cssVar('--bg-secondary',  colors.bgSecondary);
        colors.bgTertiary   = cssVar('--bg-tertiary',   colors.bgTertiary);
        colors.bgCard       = cssVar('--bg-secondary',   colors.bgCard);
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
        colors.purple   = cssVar('--purple',  colors.purple);

        colors.border      = cssVar('--border',       colors.border);
        colors.borderLight = cssVar('--border-subtle',  colors.borderLight);
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
            '#ff6b35', '#58a6ff', '#3fb950', '#d29922', '#bc8cff',
            '#f85149', '#79c0ff', '#56d364', '#e3b341', '#d2a8ff',
            '#ff7b72', '#a5d6ff', '#7ee787', '#f0c000', '#c792ea',
        ],
        neon: [
            '#00ff87', '#f72585', '#4cc9f0', '#fee440', '#7209b7',
            '#00f5d4', '#ff006e', '#3a86ff', '#fb5607', '#8338ec',
            '#72efdd', '#ff477e', '#80ffdb', '#ffbe0b', '#560bad',
        ],
        pastel: [
            '#ffadad', '#a0c4ff', '#bdb2ff', '#caffbf', '#ffd6a5',
            '#fdffb6', '#9bf6ff', '#d0b4ff', '#ffc6ff', '#ffcfd2',
            '#98f5e1', '#b8c0ff', '#fde4cf', '#c8e7ff', '#e4c1f9',
        ],
        highContrast: [
            '#ffffff', '#ffff00', '#00ffff', '#ff00ff', '#ff0000',
            '#00ff00', '#ff8800', '#0088ff', '#88ff00', '#ff0088',
            '#00ff88', '#8800ff', '#ffcc00', '#00ccff', '#cc00ff',
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
