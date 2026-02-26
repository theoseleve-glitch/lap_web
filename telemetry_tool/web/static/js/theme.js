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
        textSecondary: '#8b949e',
        textMuted:     '#484f58',

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
        colors.bgCard       = cssVar('--bg-card',       colors.bgCard);
        colors.bgHover      = cssVar('--bg-hover',      colors.bgHover);

        colors.textPrimary   = cssVar('--text-primary',   colors.textPrimary);
        colors.textSecondary = cssVar('--text-secondary', colors.textSecondary);
        colors.textMuted     = cssVar('--text-muted',     colors.textMuted);

        colors.accent    = cssVar('--accent',     colors.accent);
        colors.accentDim = cssVar('--accent-dim', colors.accentDim);

        colors.green    = cssVar('--green',   colors.green);
        colors.greenDim = cssVar('--green-dim', colors.greenDim);
        colors.yellow   = cssVar('--yellow',  colors.yellow);
        colors.red      = cssVar('--red',     colors.red);
        colors.blue     = cssVar('--blue',    colors.blue);
        colors.purple   = cssVar('--purple',  colors.purple);

        colors.border      = cssVar('--border',       colors.border);
        colors.borderLight = cssVar('--border-light',  colors.borderLight);
    }

    /* Hydrate immediately (CSS should be loaded before JS) */
    if (document.readyState !== 'loading') {
        hydrate();
    } else {
        document.addEventListener('DOMContentLoaded', hydrate);
    }

    /* ── Deterministic lap color palette ───────── */
    var LAP_PALETTE = [
        '#ff6b35', '#58a6ff', '#3fb950', '#d29922', '#bc8cff',
        '#f85149', '#79c0ff', '#56d364', '#e3b341', '#d2a8ff',
        '#ff7b72', '#a5d6ff', '#7ee787', '#f0c000', '#c792ea',
    ];

    function lapColor(index) {
        return LAP_PALETTE[index % LAP_PALETTE.length];
    }

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
        colors:     colors,
        lapColor:   lapColor,
        heatColor:  heatColor,
        speedColor: speedColor,
        hydrate:    hydrate,
    };

    window.ModuleManager.register('theme', { init: function(){}, destroy: function(){} });
})();
