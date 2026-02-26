/**
 * motion.js — Micro-motion utilities.
 *
 * All animations respect prefers-reduced-motion.
 * GPU-accelerated where possible, under 400ms.
 *
 * Provides:
 *   Motion.tickUp(el, target, duration)    — animate number 0→target
 *   Motion.staggerIn(parentEl)             — trigger stagger-in class
 *   Motion.drawLine(ctx, points, duration) — progressive line draw
 */
(function () {
    'use strict';

    var _reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /**
     * Animate a number from 0 to target in an element's textContent.
     * @param {HTMLElement} el - Element to update
     * @param {number} target - Final number value
     * @param {number} [duration=400] - Animation duration in ms
     * @param {number} [decimals=0] - Decimal places
     */
    function tickUp(el, target, duration, decimals) {
        if (!el) return;
        duration = duration || 400;
        decimals = decimals || 0;

        if (_reducedMotion) {
            el.textContent = target.toFixed(decimals);
            return;
        }

        var start = performance.now();
        var from = parseFloat(el.textContent) || 0;
        var delta = target - from;

        function frame(now) {
            var t = Math.min((now - start) / duration, 1);
            // ease-out cubic
            t = 1 - Math.pow(1 - t, 3);
            el.textContent = (from + delta * t).toFixed(decimals);
            if (t < 1) requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
    }

    /**
     * Add 'stagger-in' class to parent, triggering CSS animation on children.
     * @param {HTMLElement} parentEl
     */
    function staggerIn(parentEl) {
        if (!parentEl) return;
        if (_reducedMotion) {
            parentEl.classList.remove('stagger-in');
            return;
        }
        // Remove and re-add to retrigger animation
        parentEl.classList.remove('stagger-in');
        void parentEl.offsetWidth; // force reflow
        parentEl.classList.add('stagger-in');
    }

    /**
     * Progressively draw a polyline on canvas.
     * @param {CanvasRenderingContext2D} ctx
     * @param {Array<{x:number, y:number}>} points
     * @param {number} [duration=400]
     * @param {object} [style] - { color, width }
     */
    function drawLine(ctx, points, duration, style) {
        if (!ctx || !points || points.length < 2) return;
        duration = duration || 400;
        style = style || {};
        var color = style.color || 'var(--accent, #f07030)';
        var lineWidth = style.width || 2;

        if (_reducedMotion) {
            ctx.beginPath();
            ctx.strokeStyle = color;
            ctx.lineWidth = lineWidth;
            ctx.moveTo(points[0].x, points[0].y);
            for (var i = 1; i < points.length; i++) {
                ctx.lineTo(points[i].x, points[i].y);
            }
            ctx.stroke();
            return;
        }

        var totalLen = 0;
        var segLens = [];
        for (var j = 1; j < points.length; j++) {
            var dx = points[j].x - points[j - 1].x;
            var dy = points[j].y - points[j - 1].y;
            var len = Math.sqrt(dx * dx + dy * dy);
            segLens.push(len);
            totalLen += len;
        }

        var start = performance.now();

        function frame(now) {
            var t = Math.min((now - start) / duration, 1);
            t = 1 - Math.pow(1 - t, 3); // ease-out cubic
            var drawLen = t * totalLen;

            ctx.beginPath();
            ctx.strokeStyle = color;
            ctx.lineWidth = lineWidth;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.moveTo(points[0].x, points[0].y);

            var accumulated = 0;
            for (var k = 0; k < segLens.length; k++) {
                if (accumulated + segLens[k] <= drawLen) {
                    ctx.lineTo(points[k + 1].x, points[k + 1].y);
                    accumulated += segLens[k];
                } else {
                    var remain = drawLen - accumulated;
                    var frac = remain / segLens[k];
                    var ix = points[k].x + (points[k + 1].x - points[k].x) * frac;
                    var iy = points[k].y + (points[k + 1].y - points[k].y) * frac;
                    ctx.lineTo(ix, iy);
                    break;
                }
            }
            ctx.stroke();

            if (t < 1) requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
    }

    /* ── Public API ── */

    window.Motion = {
        tickUp: tickUp,
        staggerIn: staggerIn,
        drawLine: drawLine,
        isReduced: function () { return _reducedMotion; }
    };

    window.ModuleManager.register('motion', {
        init: function () {},
        destroy: function () {}
    });
})();
