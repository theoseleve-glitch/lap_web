/**
 * lifecycle_helpers.js — Tracked listener/timer/rAF helpers for automatic cleanup.
 *
 * Usage:
 *   var lc = window.LifecycleHelpers.create();
 *   lc.addListener(el, 'click', handler);
 *   lc.addInterval(fn, 2000);
 *   lc.addRaf(frameCallback);
 *   // On destroy:
 *   lc.destroyAll();  // removes everything
 */
(function () {
    'use strict';

    window.LifecycleHelpers = {
        create: function () {
            var _listeners = [];
            var _timers = [];
            var _intervals = [];
            var _rafs = [];

            return {
                addListener: function (el, evt, fn, opts) {
                    el.addEventListener(evt, fn, opts);
                    _listeners.push({ el: el, evt: evt, fn: fn, opts: opts });
                },

                removeListener: function (el, evt, fn, opts) {
                    el.removeEventListener(evt, fn, opts);
                    for (var i = _listeners.length - 1; i >= 0; i--) {
                        var l = _listeners[i];
                        if (l.el === el && l.evt === evt && l.fn === fn) {
                            _listeners.splice(i, 1);
                            break;
                        }
                    }
                },

                addTimer: function (fn, ms) {
                    var id = setTimeout(fn, ms);
                    _timers.push(id);
                    return id;
                },

                clearTimer: function (id) {
                    clearTimeout(id);
                    var idx = _timers.indexOf(id);
                    if (idx !== -1) _timers.splice(idx, 1);
                },

                addInterval: function (fn, ms) {
                    var id = setInterval(fn, ms);
                    _intervals.push(id);
                    return id;
                },

                clearInterval: function (id) {
                    clearInterval(id);
                    var idx = _intervals.indexOf(id);
                    if (idx !== -1) _intervals.splice(idx, 1);
                },

                addRaf: function (fn) {
                    var id = requestAnimationFrame(fn);
                    _rafs.push(id);
                    return id;
                },

                cancelRaf: function (id) {
                    cancelAnimationFrame(id);
                    var idx = _rafs.indexOf(id);
                    if (idx !== -1) _rafs.splice(idx, 1);
                },

                destroyAll: function () {
                    var i;
                    for (i = 0; i < _listeners.length; i++) {
                        var l = _listeners[i];
                        l.el.removeEventListener(l.evt, l.fn, l.opts);
                    }
                    for (i = 0; i < _timers.length; i++) {
                        clearTimeout(_timers[i]);
                    }
                    for (i = 0; i < _intervals.length; i++) {
                        clearInterval(_intervals[i]);
                    }
                    for (i = 0; i < _rafs.length; i++) {
                        cancelAnimationFrame(_rafs[i]);
                    }
                    _listeners = [];
                    _timers = [];
                    _intervals = [];
                    _rafs = [];
                }
            };
        }
    };

    /**
     * sizeCanvas — Standard DPR-aware canvas sizing.
     * Use setTransform (absolute) instead of scale (cumulative) to prevent
     * double-scaling bugs on resize.
     */
    window.sizeCanvas = function (canvas, w, h) {
        var dpr = window.devicePixelRatio || 1;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        var ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        return ctx;
    };
})();
