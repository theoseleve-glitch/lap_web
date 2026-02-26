/**
 * Global ResizeObserver for canvas chart containers.
 * Watches all .chart-container elements and calls canvas.__redraw()
 * when the container resizes. Batches redraws via requestAnimationFrame.
 */
(function() {
    'use strict';

    var pending = new Set();
    var rafId = null;

    function flushRedraws() {
        pending.forEach(function(canvas) {
            if (typeof canvas.__redraw === 'function') {
                try {
                    canvas.__redraw();
                } catch (e) {
                    console.warn('[ResizeObserver] redraw failed for', canvas.id, e);
                }
            }
        });
        pending.clear();
        rafId = null;
    }

    var ro = new ResizeObserver(function(entries) {
        for (var i = 0; i < entries.length; i++) {
            var canvases = entries[i].target.querySelectorAll('canvas');
            for (var j = 0; j < canvases.length; j++) {
                pending.add(canvases[j]);
            }
        }
        if (!rafId) {
            rafId = requestAnimationFrame(flushRedraws);
        }
    });

    function init() {
        var containers = document.querySelectorAll('.chart-container, .chart-frame');
        for (var i = 0; i < containers.length; i++) {
            ro.observe(containers[i]);
        }
        /* Also observe GPS map, corner replay, viz containers */
        var extras = document.querySelectorAll('.gps-map, .cr-viewport, .viz-container, .viz-chart-container');
        for (var j = 0; j < extras.length; j++) {
            ro.observe(extras[j]);
        }
    }

    window.TelemetryResize = {
        observe: function(el) { ro.observe(el); },
        unobserve: function(el) { ro.unobserve(el); },
        init: init
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.ModuleManager.register('resize_observer', { init: function(){}, destroy: function(){} });
})();
