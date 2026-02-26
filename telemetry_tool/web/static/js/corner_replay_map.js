/**
 * corner_replay_map.js — Canvas track map for corner replay.
 *
 * Renders GPS trace with corner-focused zoom and animated position dots.
 * Supports single-dot (review), dual-dot (split), and triple-dot (top3) modes.
 *
 * Public API:
 *   window.CornerReplayMap.init(canvasId)
 *   window.CornerReplayMap.setTrace(lapNum, traceData)
 *   window.CornerReplayMap.setCorners(cornerPositions)
 *   window.CornerReplayMap.renderReview(cornerWindow, progress, lapA, refLaps)
 *   window.CornerReplayMap.renderDual(cornerWindow, progress, lapA, lapB, deltaText)
 *   window.CornerReplayMap.renderTriple(cornerWindow, progress, top3Laps)
 */
(function () {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {
        bgCard: '#1e1e2e', border: '#333', textPrimary: '#e0e0e0',
        textSecondary: '#aaa', textMuted: '#777', accent: '#f97316',
    };

    var _canvas, _ctx;
    var _traces = {};      // { lapNum: { latitudes, longitudes, distances, speeds, ... } }
    var _corners = [];     // [ { corner_id, lat, lon, brake_point_m } ]
    var _fullProjection = null;  // projection for full track

    // User zoom/pan state
    var _zoom = 1.0;       // 1.0 = default corner-focused view
    var _panX = 0;         // pixel offset
    var _panY = 0;
    var _dragging = false;
    var _dragStartX = 0;
    var _dragStartY = 0;
    var _dragPanStartX = 0;
    var _dragPanStartY = 0;
    var _eventsAttached = false;

    var DOT_COLORS = {
        white: '#ffffff',
        green: '#3fb950',
        red: '#f85149',
        cyan: '#00c8ff',
        gold: '#ffb347',
        purple: '#bc8cff',
    };

    var TOP3_COLORS = [DOT_COLORS.gold, DOT_COLORS.cyan, DOT_COLORS.green];

    window.CornerReplayMap = {
        init: init,
        setTrace: setTrace,
        setCorners: setCorners,
        renderReview: renderReview,
        renderDual: renderDual,
        renderTriple: renderTriple,
    };

    function init(canvasId) {
        _canvas = document.getElementById(canvasId);
        if (!_canvas) return;
        _ctx = _canvas.getContext('2d');
        _attachZoomPan();
    }

    function _attachZoomPan() {
        if (_eventsAttached || !_canvas) return;
        _eventsAttached = true;

        // Mouse wheel zoom
        _lc.addListener(_canvas, 'wheel', function (e) {
            e.preventDefault();
            var rect = _canvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            var oldZoom = _zoom;
            var factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
            _zoom = Math.max(0.3, Math.min(10, _zoom * factor));

            // Zoom toward mouse cursor
            var ratio = _zoom / oldZoom;
            _panX = mx - ratio * (mx - _panX);
            _panY = my - ratio * (my - _panY);

            _triggerRedraw();
        }, { passive: false });

        // Drag to pan
        _lc.addListener(_canvas, 'mousedown', function (e) {
            if (e.button !== 0) return;
            _dragging = true;
            _dragStartX = e.clientX;
            _dragStartY = e.clientY;
            _dragPanStartX = _panX;
            _dragPanStartY = _panY;
            _canvas.style.cursor = 'grabbing';
        });

        _lc.addListener(window, 'mousemove', function (e) {
            if (!_dragging) return;
            _panX = _dragPanStartX + (e.clientX - _dragStartX);
            _panY = _dragPanStartY + (e.clientY - _dragStartY);
            _triggerRedraw();
        });

        _lc.addListener(window, 'mouseup', function () {
            if (_dragging) {
                _dragging = false;
                if (_canvas) _canvas.style.cursor = '';
            }
        });

        // Double-click to reset zoom
        _lc.addListener(_canvas, 'dblclick', function () {
            _zoom = 1.0;
            _panX = 0;
            _panY = 0;
            _triggerRedraw();
        });
    }

    function _triggerRedraw() {
        if (_canvas && _canvas.__redraw) _canvas.__redraw();
    }

    function setTrace(lapNum, traceData) {
        _traces[String(lapNum)] = traceData;
        _fullProjection = null; // invalidate
    }

    function setCorners(cornerPositions) {
        _corners = cornerPositions || [];
        // Reset zoom/pan when corners change
        _zoom = 1.0;
        _panX = 0;
        _panY = 0;
    }

    // ── Render modes ──────────────────────────────────

    function renderReview(cornerWindow, progress, lapA, refLaps) {
        var dims = _setupCanvas();
        if (!dims) return;

        // Register __redraw for ResizeObserver (replays last call)
        if (_canvas) {
            _canvas.__redraw = function() { renderReview(cornerWindow, progress, lapA, refLaps); };
        }

        var proj = _cornerProjection(dims, cornerWindow, lapA);
        if (!proj) return;

        _drawBackground(dims);
        _drawTraceSegment(dims, proj, lapA, cornerWindow, 'rgba(255,255,255,0.25)', 2.5);

        // Reference dots (green if faster, red if slower)
        if (refLaps) {
            refLaps.forEach(function (ref) {
                var color = ref.faster ? DOT_COLORS.green : DOT_COLORS.red;
                _drawDotAtProgress(proj, ref.lapNum, cornerWindow, progress, color, 5, 0.6);
            });
        }

        // Main dot (white)
        _drawDotAtProgress(proj, lapA, cornerWindow, progress, DOT_COLORS.white, 7, 1.0);

        // Corner markers
        _drawCornerMarkers(proj, dims);
    }

    function renderDual(cornerWindow, progress, lapA, lapB, deltaText) {
        var dims = _setupCanvas();
        if (!dims) return;

        // Register __redraw for ResizeObserver (replays last call)
        if (_canvas) {
            _canvas.__redraw = function() { renderDual(cornerWindow, progress, lapA, lapB, deltaText); };
        }

        var proj = _cornerProjection(dims, cornerWindow, lapA);
        if (!proj) return;

        _drawBackground(dims);
        _drawTraceSegment(dims, proj, lapA, cornerWindow, 'rgba(255,255,255,0.15)', 2);
        _drawTraceSegment(dims, proj, lapB, cornerWindow, 'rgba(0,200,255,0.15)', 2);

        // Both dots
        _drawDotAtProgress(proj, lapA, cornerWindow, progress, DOT_COLORS.white, 7, 1.0);
        _drawDotAtProgress(proj, lapB, cornerWindow, progress, DOT_COLORS.cyan, 7, 1.0);

        // Corner markers
        _drawCornerMarkers(proj, dims);

        // Delta text overlay on map (smaller version — main delta is the CSS badge)
        if (deltaText) {
            _ctx.font = 'bold 15px system-ui, sans-serif';
            _ctx.textAlign = 'right';
            _ctx.fillStyle = deltaText.charAt(0) === '-' ? DOT_COLORS.green : DOT_COLORS.red;
            _ctx.fillText(deltaText, dims.w - 10, 24);
        }
    }

    function renderTriple(cornerWindow, progress, top3Laps) {
        var dims = _setupCanvas();
        if (!dims) return;

        // Register __redraw for ResizeObserver (replays last call)
        if (_canvas) {
            _canvas.__redraw = function() { renderTriple(cornerWindow, progress, top3Laps); };
        }

        var proj = _cornerProjection(dims, cornerWindow, top3Laps[0]);
        if (!proj) return;

        _drawBackground(dims);

        // Draw traces for all 3
        top3Laps.forEach(function (ln, i) {
            var alpha = i === 0 ? 0.3 : 0.15;
            _drawTraceSegment(dims, proj, ln, cornerWindow, _alphaColor(TOP3_COLORS[i], alpha), 2);
        });

        // Draw dots
        top3Laps.forEach(function (ln, i) {
            _drawDotAtProgress(proj, ln, cornerWindow, progress, TOP3_COLORS[i], 7, 1.0);
        });

        // Corner markers
        _drawCornerMarkers(proj, dims);
    }

    // ── Internal rendering helpers ────────────────────

    function _setupCanvas() {
        if (!_canvas || !_canvas.parentElement) return null;
        var dpr = window.devicePixelRatio || 1;
        var container = _canvas.parentElement;
        var w = container.clientWidth;
        var h = container.clientHeight;
        if (w < 50 || h < 50) return null;

        _canvas.width = w * dpr;
        _canvas.height = h * dpr;
        _canvas.style.width = w + 'px';
        _canvas.style.height = h + 'px';
        _ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        return { w: w, h: h, dpr: dpr };
    }

    function _drawBackground(dims) {
        _ctx.fillStyle = C.bgCard || '#1a1f2e';
        _ctx.fillRect(0, 0, dims.w, dims.h);
    }

    /**
     * Build a projection focused on a corner window region.
     * Shows the entire track faintly but zooms into the corner area.
     * Applies user zoom/pan on top.
     */
    function _cornerProjection(dims, cornerWindow, primaryLap) {
        var trace = _traces[String(primaryLap)];
        if (!trace || !trace.latitudes || trace.latitudes.length < 2) return null;

        var lats = trace.latitudes;
        var lons = trace.longitudes;

        // Find corner region GPS bounds (with padding)
        var startIdx = cornerWindow.startIdx;
        var endIdx = cornerWindow.endIdx;
        var regionLats = [], regionLons = [];
        for (var i = startIdx; i <= endIdx && i < lats.length; i++) {
            if (lats[i] !== null && lons[i] !== null) {
                regionLats.push(lats[i]);
                regionLons.push(lons[i]);
            }
        }
        if (regionLats.length < 2) return null;

        var latMin = Math.min.apply(null, regionLats);
        var latMax = Math.max.apply(null, regionLats);
        var lonMin = Math.min.apply(null, regionLons);
        var lonMax = Math.max.apply(null, regionLons);

        // Add 15% padding around corner region (tighter zoom on corner)
        var latPad = (latMax - latMin) * 0.15 || 0.0002;
        var lonPad = (lonMax - lonMin) * 0.15 || 0.0002;
        latMin -= latPad;
        latMax += latPad;
        lonMin -= lonPad;
        lonMax += lonPad;

        var originLat = (latMin + latMax) / 2;
        var mPerDegLat = 111320;
        var mPerDegLon = 111320 * Math.cos(originLat * Math.PI / 180);

        var rangeX = (lonMax - lonMin) * mPerDegLon;
        var rangeY = (latMax - latMin) * mPerDegLat;

        var pad = 25;
        var plotW = dims.w - pad * 2;
        var plotH = dims.h - pad * 2;

        var scaleX = plotW / Math.max(rangeX, 1);
        var scaleY = plotH / Math.max(rangeY, 1);
        var baseScale = Math.min(scaleX, scaleY) * 0.90;

        // Apply user zoom
        var scale = baseScale * _zoom;

        // Base center point (before pan)
        var baseCX = pad + plotW / 2;
        var baseCY = pad + plotH / 2;

        // Center of geo region in meters
        var geoCX = rangeX / 2;
        var geoCY = rangeY / 2;

        return {
            toPixel: function (lat, lon) {
                var mx = (lon - lonMin) * mPerDegLon;
                var my = (lat - latMin) * mPerDegLat;
                return {
                    x: baseCX + (mx - geoCX) * scale + _panX,
                    y: baseCY + (geoCY - my) * scale + _panY,
                };
            },
            latMin: latMin, latMax: latMax,
            lonMin: lonMin, lonMax: lonMax,
        };
    }

    function _drawTraceSegment(dims, proj, lapNum, cornerWindow, color, lineWidth) {
        var trace = _traces[String(lapNum)];
        if (!trace) return;

        var lats = trace.latitudes;
        var lons = trace.longitudes;

        // Draw entire trace very faintly
        _ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        _ctx.lineWidth = 1;
        _ctx.lineCap = 'round';
        _ctx.beginPath();
        var started = false;
        for (var i = 0; i < lats.length; i++) {
            if (lats[i] === null || lons[i] === null) continue;
            var p = proj.toPixel(lats[i], lons[i]);
            if (!started) { _ctx.moveTo(p.x, p.y); started = true; }
            else _ctx.lineTo(p.x, p.y);
        }
        _ctx.stroke();

        // Draw corner segment with color
        _ctx.strokeStyle = color;
        _ctx.lineWidth = lineWidth;
        _ctx.beginPath();
        started = false;
        var si = cornerWindow.startIdx;
        var ei = Math.min(cornerWindow.endIdx, lats.length - 1);
        for (var i = si; i <= ei; i++) {
            if (lats[i] === null || lons[i] === null) continue;
            var p = proj.toPixel(lats[i], lons[i]);
            if (!started) { _ctx.moveTo(p.x, p.y); started = true; }
            else _ctx.lineTo(p.x, p.y);
        }
        _ctx.stroke();
    }

    function _drawDotAtProgress(proj, lapNum, cornerWindow, progress, color, radius, alpha) {
        var trace = _traces[String(lapNum)];
        if (!trace) return;

        var pos = _interpolatePosition(trace, cornerWindow, progress);
        if (!pos) return;

        var p = proj.toPixel(pos.lat, pos.lon);

        _ctx.globalAlpha = alpha;

        // Glow
        _ctx.beginPath();
        _ctx.arc(p.x, p.y, radius + 4, 0, Math.PI * 2);
        _ctx.fillStyle = color.replace(')', ', 0.3)').replace('#', '');
        // For hex colors, use rgba approach
        _ctx.fillStyle = _alphaColor(color, 0.25);
        _ctx.fill();

        // Dot
        _ctx.beginPath();
        _ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
        _ctx.fillStyle = color;
        _ctx.fill();

        // Border
        _ctx.strokeStyle = 'rgba(0,0,0,0.5)';
        _ctx.lineWidth = 1.5;
        _ctx.stroke();

        _ctx.globalAlpha = 1.0;
    }

    function _drawCornerMarkers(proj, dims) {
        _corners.forEach(function (c) {
            var p = proj.toPixel(c.lat, c.lon);
            // Only draw if in view
            if (p.x < -20 || p.x > dims.w + 20 || p.y < -20 || p.y > dims.h + 20) return;

            _ctx.beginPath();
            _ctx.arc(p.x, p.y, 12, 0, Math.PI * 2);
            _ctx.fillStyle = 'rgba(255, 107, 53, 0.15)';
            _ctx.fill();
            _ctx.strokeStyle = C.accent || '#ff6b35';
            _ctx.lineWidth = 1.5;
            _ctx.stroke();

            _ctx.fillStyle = C.accent || '#ff6b35';
            _ctx.font = 'bold 9px system-ui, sans-serif';
            _ctx.textAlign = 'center';
            _ctx.textBaseline = 'middle';
            _ctx.fillText('C' + c.corner_id, p.x, p.y);
            _ctx.textBaseline = 'alphabetic';
        });
    }

    // ── Utility ───────────────────────────────────────

    function _interpolatePosition(trace, cornerWindow, progress) {
        var si = cornerWindow.startIdx;
        var ei = cornerWindow.endIdx;
        var range = ei - si;
        if (range <= 0) return null;

        var exactIdx = si + progress * range;
        var idx0 = Math.floor(exactIdx);
        var idx1 = Math.min(idx0 + 1, trace.latitudes.length - 1);
        var frac = exactIdx - idx0;

        var lat0 = trace.latitudes[idx0];
        var lon0 = trace.longitudes[idx0];
        var lat1 = trace.latitudes[idx1];
        var lon1 = trace.longitudes[idx1];

        if (lat0 === null || lon0 === null) return { lat: lat1, lon: lon1 };
        if (lat1 === null || lon1 === null) return { lat: lat0, lon: lon0 };

        return {
            lat: lat0 + (lat1 - lat0) * frac,
            lon: lon0 + (lon1 - lon0) * frac,
        };
    }

    /** Convert hex or named color to rgba */
    function _alphaColor(color, alpha) {
        // Handle named colors and hex
        if (color.charAt(0) === '#') {
            var r = parseInt(color.substr(1, 2), 16);
            var g = parseInt(color.substr(3, 2), 16);
            var b = parseInt(color.substr(5, 2), 16);
            return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
        }
        return color;
    }

    /** Get interpolated data at progress for a given trace */
    function getDataAtProgress(lapNum, cornerWindow, progress) {
        var trace = _traces[String(lapNum)];
        if (!trace) return null;

        var si = cornerWindow.startIdx;
        var ei = cornerWindow.endIdx;
        var range = ei - si;
        if (range <= 0) return null;

        var exactIdx = si + progress * range;
        var idx0 = Math.floor(exactIdx);
        var idx1 = Math.min(idx0 + 1, trace.latitudes.length - 1);
        var frac = exactIdx - idx0;

        function _lerp(arr, i0, i1, f) {
            if (!arr || arr.length === 0) return 0;
            var v0 = arr[i0] != null ? arr[i0] : 0;
            var v1 = arr[i1] != null ? arr[i1] : v0;
            return v0 + (v1 - v0) * f;
        }

        return {
            speed: _lerp(trace.speeds, idx0, idx1, frac),
            accel_lat: _lerp(trace.accel_lat, idx0, idx1, frac),
            accel_long: _lerp(trace.accel_long, idx0, idx1, frac),
            distance: _lerp(trace.distances, idx0, idx1, frac),
        };
    }
    window.CornerReplayMap.getDataAtProgress = getDataAtProgress;

    function destroy() {
        _lc.destroyAll();
        _canvas = null;
        _ctx = null;
        _traces = {};
        _corners = [];
        _fullProjection = null;
        _zoom = 1.0;
        _panX = 0;
        _panY = 0;
        _eventsAttached = false;
        _dragging = false;
    }

    window.ModuleManager.register('corner_replay_map', {
        init: function () {},
        destroy: destroy
    });

})();
