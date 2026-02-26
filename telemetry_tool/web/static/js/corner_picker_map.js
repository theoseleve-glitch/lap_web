/**
 * corner_picker_map.js — Interactive track map for placing areas of interest.
 *
 * Renders a GPS track outline.  Users click anywhere on the track to place
 * custom markers (areas of interest).  Auto-detected corners are shown as
 * small reference guides.
 *
 * Public API:
 *   window.CornerPicker.init(canvasId, trackLayout)
 *   window.CornerPicker.getSelected()       → [{corner_id, lat, lon, dist_m, label}, ...]
 *   window.CornerPicker.setPoints(points)   → pre-load saved areas of interest
 *   window.CornerPicker.onSelectionChange(cb)
 *   window.CornerPicker.toggleCorner(id)    → toggle a custom point by id
 */
(function () {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {
        bgCard: '#1e1e2e', border: '#333', textPrimary: '#e0e0e0',
        textSecondary: '#aaa', textMuted: '#777', accent: '#f97316',
    };

    var MIN_POINTS = 3;
    var MAX_POINTS = 8;
    var POINT_RADIUS = 16;
    var REF_RADIUS = 6;        // auto-detected corner reference size
    var SNAP_DIST_PX = 25;     // max pixel distance from track to place a point
    var HIT_RADIUS = 20;       // click detection radius for existing points

    var canvas, ctx;
    var trackLayout = null;
    var projection = null;
    var changeCb = null;
    var pad = { top: 30, right: 30, bottom: 30, left: 30 };

    // Custom areas of interest placed by user
    var customPoints = [];     // [{id, corner_id, lat, lon, dist_m, label, _px, _py}]
    var nextPointId = 1;

    // Auto-detected corners (reference guides, not interactive)
    var autoCorners = [];      // [{corner_id, lat, lon, dist_m, direction, _px, _py}]

    // Projected track points cache
    var trackPixels = [];      // [{x, y, lat, lon, dist_m, idx}]

    // Interaction state
    var hoverTrackPt = null;   // ghost preview: {x, y} or null
    var hoveredPointId = null; // id of custom point under cursor

    window.CornerPicker = {
        init: init,
        getSelected: getSelected,
        setPoints: setPoints,
        onSelectionChange: function (cb) { changeCb = cb; },
        toggleCorner: function (pointId) {
            var idx = _findPointIndex(pointId);
            if (idx >= 0) {
                customPoints.splice(idx, 1);
            }
            _draw();
            if (changeCb) changeCb(getSelected());
        },
    };

    function init(canvasId, layout) {
        canvas = document.getElementById(canvasId);
        if (!canvas) return;
        ctx = canvas.getContext('2d');
        trackLayout = layout;

        if (!layout || !layout.latitudes || layout.latitudes.length === 0) {
            _msg('No track layout available');
            return;
        }

        // Reset state
        customPoints = [];
        nextPointId = 1;
        autoCorners = [];
        trackPixels = [];
        hoverTrackPt = null;
        hoveredPointId = null;

        _computeProjection();
        _cacheTrackPixels();
        // Auto-detected corners no longer shown — user-defined only
        _draw();
        _setupEvents();
    }

    function getSelected() {
        var result = [];
        for (var i = 0; i < customPoints.length; i++) {
            var p = customPoints[i];
            result.push({
                corner_id: p.corner_id,
                lat: p.lat,
                lon: p.lon,
                dist_m: p.dist_m,
                label: p.label,
            });
        }
        // Sort by distance along track, then assign sequential corner_ids
        // so stored IDs always match the visual P1, P2, ... labels.
        result.sort(function (a, b) { return a.dist_m - b.dist_m; });
        for (var j = 0; j < result.length; j++) {
            result[j].corner_id = j + 1;
        }
        return result;
    }

    function setPoints(points) {
        customPoints = [];
        nextPointId = 1;
        if (!points || !points.length) return;

        for (var i = 0; i < points.length; i++) {
            var p = points[i];
            if (p.lat == null || p.lon == null) continue;
            var px = _toPixel(p.lat, p.lon);
            customPoints.push({
                id: nextPointId,
                corner_id: p.corner_id || nextPointId,
                lat: p.lat,
                lon: p.lon,
                dist_m: p.dist_m || 0,
                label: p.label || ('P' + nextPointId),
                _px: px ? px.x : 0,
                _py: px ? px.y : 0,
            });
            nextPointId++;
        }
        _draw();
        if (changeCb) changeCb(getSelected());
    }

    function _findPointIndex(pointId) {
        for (var i = 0; i < customPoints.length; i++) {
            if (customPoints[i].id === pointId) return i;
        }
        return -1;
    }

    // ── Projection ──

    function _computeProjection() {
        var lats = trackLayout.latitudes;
        var lons = trackLayout.longitudes;
        var allLats = [], allLons = [];

        for (var i = 0; i < lats.length; i++) {
            if (lats[i] !== null && lons[i] !== null) {
                allLats.push(lats[i]);
                allLons.push(lons[i]);
            }
        }
        if (allLats.length === 0) return;

        var latMin = Math.min.apply(null, allLats);
        var latMax = Math.max.apply(null, allLats);
        var lonMin = Math.min.apply(null, allLons);
        var lonMax = Math.max.apply(null, allLons);

        var originLat = (latMin + latMax) / 2;
        var mPerDegLat = 111320;
        var mPerDegLon = 111320 * Math.cos(originLat * Math.PI / 180);

        var rangeX = (lonMax - lonMin) * mPerDegLon;
        var rangeY = (latMax - latMin) * mPerDegLat;

        var dpr = window.devicePixelRatio || 1;
        var container = canvas.parentElement;
        var w = (container ? container.clientWidth : 600) - 8;
        var h = Math.max(350, Math.min(500, w * 0.65));

        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        var plotW = w - pad.left - pad.right;
        var plotH = h - pad.top - pad.bottom;

        var scaleX = plotW / Math.max(rangeX, 1);
        var scaleY = plotH / Math.max(rangeY, 1);
        var scale = Math.min(scaleX, scaleY) * 0.90;

        var offsetX = pad.left + (plotW - rangeX * scale) / 2;
        var offsetY = pad.top + (plotH - rangeY * scale) / 2;

        projection = {
            mPerDegLat: mPerDegLat, mPerDegLon: mPerDegLon,
            scale: scale, offsetX: offsetX, offsetY: offsetY,
            width: w, height: h,
            latMin: latMin, latMax: latMax, lonMin: lonMin, lonMax: lonMax,
        };
    }

    function _toPixel(lat, lon) {
        if (!projection) return null;
        var p = projection;
        var mx = (lon - p.lonMin) * p.mPerDegLon;
        var my = (lat - p.latMin) * p.mPerDegLat;
        return {
            x: p.offsetX + mx * p.scale,
            y: p.offsetY + (p.latMax - p.latMin) * p.mPerDegLat * p.scale - my * p.scale,
        };
    }

    function _cacheTrackPixels() {
        trackPixels = [];
        if (!trackLayout || !projection) return;
        var lats = trackLayout.latitudes;
        var lons = trackLayout.longitudes;
        var dists = trackLayout.distances || [];
        for (var i = 0; i < lats.length; i++) {
            if (lats[i] === null || lons[i] === null) continue;
            var px = _toPixel(lats[i], lons[i]);
            if (!px) continue;
            trackPixels.push({
                x: px.x, y: px.y,
                lat: lats[i], lon: lons[i],
                dist_m: dists[i] || 0,
                idx: i,
            });
        }
    }

    function _cacheAutoCorners() {
        autoCorners = [];
        if (!trackLayout || !trackLayout.corners) return;
        var corners = trackLayout.corners;
        for (var i = 0; i < corners.length; i++) {
            var c = corners[i];
            var px = _toPixel(c.lat, c.lon);
            if (!px) continue;
            autoCorners.push({
                corner_id: c.corner_id,
                direction: c.direction || '',
                lat: c.lat,
                lon: c.lon,
                dist_m: c.dist_m || 0,
                _px: px.x,
                _py: px.y,
            });
        }
    }

    // ── Nearest track point to mouse position ──

    function _nearestTrackPoint(mx, my) {
        var best = null;
        var bestDist = Infinity;
        for (var i = 0; i < trackPixels.length; i++) {
            var tp = trackPixels[i];
            var dx = tp.x - mx, dy = tp.y - my;
            var d = dx * dx + dy * dy;
            if (d < bestDist) {
                bestDist = d;
                best = tp;
            }
        }
        if (!best) return null;
        var distPx = Math.sqrt(bestDist);
        return {
            x: best.x, y: best.y,
            lat: best.lat, lon: best.lon,
            dist_m: best.dist_m,
            idx: best.idx,
            distPx: distPx,
        };
    }

    // ── Hit test: check if mouse is near a custom point ──

    function _hitTestCustom(mx, my) {
        for (var i = 0; i < customPoints.length; i++) {
            var p = customPoints[i];
            var dx = p._px - mx, dy = p._py - my;
            if (dx * dx + dy * dy <= HIT_RADIUS * HIT_RADIUS) {
                return p.id;
            }
        }
        return null;
    }

    // ── Speed color (green → yellow → red) ──

    function _speedColor(speed, minSpd, maxSpd) {
        var t = maxSpd > minSpd ? (speed - minSpd) / (maxSpd - minSpd) : 0.5;
        t = Math.max(0, Math.min(1, t));
        var r, g, b;
        if (t < 0.5) {
            var s = t / 0.5;
            r = Math.round(60 + s * 195);
            g = Math.round(190 + s * 65);
            b = Math.round(60 - s * 30);
        } else {
            var s2 = (t - 0.5) / 0.5;
            r = 255;
            g = Math.round(255 - s2 * 200);
            b = Math.round(30);
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    // ── Drawing ──

    function _draw() {
        if (!projection || !trackLayout) return;
        var w = projection.width, h = projection.height;
        ctx.clearRect(0, 0, w, h);

        // Background
        ctx.fillStyle = C.bgCard;
        ctx.fillRect(0, 0, w, h);

        // Subtle border
        ctx.strokeStyle = C.border;
        ctx.lineWidth = 1;
        ctx.strokeRect(0.5, 0.5, w - 1, h - 1);

        // Draw track outline (speed-colored)
        _drawTrackOutline();

        // Start/finish marker
        var lats = trackLayout.latitudes;
        var lons = trackLayout.longitudes;
        if (lats[0] !== null) {
            var sf = _toPixel(lats[0], lons[0]);
            if (sf) {
                ctx.beginPath();
                ctx.arc(sf.x, sf.y, 5, 0, Math.PI * 2);
                ctx.fillStyle = '#fff';
                ctx.fill();
                ctx.strokeStyle = C.accent;
                ctx.lineWidth = 2;
                ctx.stroke();
            }
        }

        // Custom area-of-interest markers (user-placed)
        _drawCustomPoints();

        // Ghost preview of where a new point would be placed
        _drawHoverPreview();

        // Selection count indicator
        var count = customPoints.length;
        ctx.fillStyle = C.textSecondary;
        ctx.font = '12px system-ui, sans-serif';
        ctx.textAlign = 'right';
        var countColor = (count >= MIN_POINTS && count <= MAX_POINTS) ? '#10b981' : '#ef4444';
        ctx.fillStyle = countColor;
        ctx.fillText(count + '/' + MIN_POINTS + '-' + MAX_POINTS + ' selected', w - 12, h - 10);

        // Hint text
        ctx.fillStyle = C.textMuted;
        ctx.font = '11px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Click on the track to define key corners for replay', 12, h - 10);
    }

    function _drawTrackOutline() {
        var lats = trackLayout.latitudes;
        var lons = trackLayout.longitudes;
        var spds = trackLayout.speeds;
        var allSpd = [];
        for (var i = 0; i < spds.length; i++) {
            if (spds[i] !== null && isFinite(spds[i])) allSpd.push(spds[i]);
        }
        var minSpd = allSpd.length > 0 ? Math.min.apply(null, allSpd) : 0;
        var maxSpd = allSpd.length > 0 ? Math.max.apply(null, allSpd) : 1;

        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.lineWidth = 3;
        ctx.globalAlpha = 0.85;

        for (var i = 0; i < lats.length - 1; i++) {
            if (lats[i] === null || lats[i + 1] === null) continue;
            var p1 = _toPixel(lats[i], lons[i]);
            var p2 = _toPixel(lats[i + 1], lons[i + 1]);
            if (!p1 || !p2) continue;

            ctx.strokeStyle = _speedColor(spds[i] || 0, minSpd, maxSpd);
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
        }
        ctx.globalAlpha = 1.0;
    }

    function _drawAutoCornerGuides() {
        for (var i = 0; i < autoCorners.length; i++) {
            var ac = autoCorners[i];
            ctx.beginPath();
            ctx.arc(ac._px, ac._py, REF_RADIUS, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(100, 100, 130, 0.5)';
            ctx.fill();
            ctx.strokeStyle = 'rgba(150, 150, 170, 0.4)';
            ctx.lineWidth = 1;
            ctx.stroke();

            // Tiny label
            ctx.fillStyle = 'rgba(180, 180, 200, 0.6)';
            ctx.font = '9px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('C' + ac.corner_id, ac._px, ac._py);
            ctx.textBaseline = 'alphabetic';
        }
    }

    function _drawCustomPoints() {
        for (var i = 0; i < customPoints.length; i++) {
            var p = customPoints[i];
            var isHover = hoveredPointId === p.id;

            // Outer glow
            ctx.beginPath();
            ctx.arc(p._px, p._py, POINT_RADIUS + 4, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(249, 115, 22, 0.25)';
            ctx.fill();

            // Main circle
            ctx.beginPath();
            ctx.arc(p._px, p._py, POINT_RADIUS, 0, Math.PI * 2);
            ctx.fillStyle = isHover ? '#fb923c' : C.accent;
            ctx.fill();

            // Border
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2.5;
            ctx.stroke();

            // Label
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 11px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(p.label, p._px, p._py);
            ctx.textBaseline = 'alphabetic';

            // Remove hint on hover
            if (isHover) {
                ctx.fillStyle = 'rgba(239, 68, 68, 0.9)';
                ctx.font = '10px system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('click to remove', p._px, p._py + POINT_RADIUS + 14);
            }
        }
    }

    function _drawHoverPreview() {
        if (!hoverTrackPt || hoveredPointId !== null) return;
        if (customPoints.length >= MAX_POINTS) return;

        ctx.beginPath();
        ctx.arc(hoverTrackPt.x, hoverTrackPt.y, POINT_RADIUS, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(249, 115, 22, 0.2)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(249, 115, 22, 0.5)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);

        // Preview label
        ctx.fillStyle = 'rgba(249, 115, 22, 0.7)';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('P' + (customPoints.length + 1), hoverTrackPt.x, hoverTrackPt.y + 3);
    }

    function _msg(text) {
        if (!canvas) return;
        var dpr = window.devicePixelRatio || 1;
        canvas.style.width = '';
        var w = canvas.clientWidth || (canvas.parentElement ? canvas.parentElement.clientWidth : 400);
        canvas.width = w * dpr;
        canvas.height = 180 * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = '180px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = C.bgCard;
        ctx.fillRect(0, 0, w, 180);
        ctx.fillStyle = C.textMuted;
        ctx.font = '14px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(text, w / 2, 90);
    }

    // ── Check if a click is too close to an existing point ──

    function _isTooCloseToExisting(lat, lon) {
        var MIN_SEP_PX = POINT_RADIUS * 2;
        var px = _toPixel(lat, lon);
        if (!px) return true;
        for (var i = 0; i < customPoints.length; i++) {
            var cp = customPoints[i];
            var dx = cp._px - px.x, dy = cp._py - px.y;
            if (dx * dx + dy * dy < MIN_SEP_PX * MIN_SEP_PX) {
                return true;
            }
        }
        return false;
    }

    // ── Interaction ──

    function _setupEvents() {
        _lc.addListener(canvas, 'click', function (e) {
            var rect = canvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            // 1. Check if clicking on an existing custom point → remove it
            var hitId = _hitTestCustom(mx, my);
            if (hitId !== null) {
                var idx = _findPointIndex(hitId);
                if (idx >= 0) {
                    customPoints.splice(idx, 1);
                    // Relabel remaining points sequentially
                    _relabelPoints();
                    _draw();
                    if (changeCb) changeCb(getSelected());
                }
                return;
            }

            // 2. Find nearest track point
            if (customPoints.length >= MAX_POINTS) return;

            var nearest = _nearestTrackPoint(mx, my);
            if (!nearest || nearest.distPx > SNAP_DIST_PX) return;

            // 3. Check not too close to existing point
            if (_isTooCloseToExisting(nearest.lat, nearest.lon)) return;

            // 4. Place new custom point
            var label = 'P' + (customPoints.length + 1);

            customPoints.push({
                id: nextPointId,
                corner_id: nextPointId,
                lat: nearest.lat,
                lon: nearest.lon,
                dist_m: nearest.dist_m,
                label: label,
                _px: nearest.x,
                _py: nearest.y,
            });
            nextPointId++;

            _draw();
            if (changeCb) changeCb(getSelected());
        });

        _lc.addListener(canvas, 'mousemove', function (e) {
            var rect = canvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            // Check hover on existing point
            var hitId = _hitTestCustom(mx, my);
            var needRedraw = false;

            if (hitId !== hoveredPointId) {
                hoveredPointId = hitId;
                needRedraw = true;
            }

            // Ghost preview on track
            if (hitId === null && customPoints.length < MAX_POINTS) {
                var nearest = _nearestTrackPoint(mx, my);
                if (nearest && nearest.distPx <= SNAP_DIST_PX) {
                    if (!hoverTrackPt || hoverTrackPt.x !== nearest.x || hoverTrackPt.y !== nearest.y) {
                        hoverTrackPt = { x: nearest.x, y: nearest.y };
                        needRedraw = true;
                    }
                    canvas.style.cursor = 'crosshair';
                } else {
                    if (hoverTrackPt !== null) {
                        hoverTrackPt = null;
                        needRedraw = true;
                    }
                    canvas.style.cursor = 'default';
                }
            } else if (hitId !== null) {
                canvas.style.cursor = 'pointer';
                if (hoverTrackPt !== null) {
                    hoverTrackPt = null;
                    needRedraw = true;
                }
            } else {
                canvas.style.cursor = 'default';
                if (hoverTrackPt !== null) {
                    hoverTrackPt = null;
                    needRedraw = true;
                }
            }

            if (needRedraw) _draw();
        });

        _lc.addListener(canvas, 'mouseleave', function () {
            var needRedraw = hoverTrackPt !== null || hoveredPointId !== null;
            hoverTrackPt = null;
            hoveredPointId = null;
            canvas.style.cursor = 'default';
            if (needRedraw) _draw();
        });
    }

    function _relabelPoints() {
        // Sort by distance and relabel P1, P2, ...
        customPoints.sort(function (a, b) { return a.dist_m - b.dist_m; });
        for (var i = 0; i < customPoints.length; i++) {
            customPoints[i].label = 'P' + (i + 1);
        }
    }

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('corner_picker_map', {
        init: function () {},
        destroy: destroy
    });
})();
