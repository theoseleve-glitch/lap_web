/**
 * speed_trace_zoom.js — Interactive zoom & compare on the speed trace.
 *
 * Adds drag-to-select on the existing speed chart (#speed-chart) and renders
 * a zoomed detail canvas below with multi-lap comparison (green = faster,
 * red = slower).  Corner markers on the overview chart are clickable to
 * auto-zoom to each corner's braking-to-throttle window.
 *
 * Reads: window.TELEMETRY = { sessionId, gpsLaps, bestLap }
 *        window.ChartSync  = { getChartData, getChartBounds, getCanvas }
 * Provides: window.SpeedTraceZoom = { init, zoomToCorner, zoomToRange, resetZoom, onOverviewRedrawn }
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};

    // ── State ────────────────────────────────────────
    var _state = {
        selection: null,        // { startDist, endDist } or null
        isDragging: false,
        dragStartX: null,
        primaryLap: null,
        comparisonLaps: [],     // [lapNum, ...]
        corners: [],            // [{ corner_id, brake_point_m, throttle_onset_m }]
        lapDataCache: {},       // { lapNum: { distances, speeds } }
        activeCorner: null,     // corner_id currently zoomed to
        initialized: false,
    };

    // DOM refs
    var _overviewCanvas = null;
    var _selectionRect = null;
    var _zoomPanel = null;
    var _zoomCanvas = null;
    var _zoomCtx = null;
    var _zoomTooltip = null;
    var _primarySelect = null;
    var _compareSelect = null;
    var _cornerPills = null;
    var _legendEl = null;
    var _cornerMarkersEl = null;
    var _dragHint = null;

    // ── Public API ───────────────────────────────────
    window.SpeedTraceZoom = {
        init: init,
        zoomToCorner: zoomToCorner,
        zoomToRange: zoomToRange,
        resetZoom: resetZoom,
        onOverviewRedrawn: onOverviewRedrawn,
    };

    // ── Init ─────────────────────────────────────────
    function init() {
        if (_state.initialized) return;

        _overviewCanvas = document.getElementById('speed-chart');
        _selectionRect = document.getElementById('speed-chart-selection-rect');
        _zoomPanel = document.getElementById('speed-zoom-panel');
        _zoomCanvas = document.getElementById('speed-zoom-canvas');
        _zoomTooltip = document.getElementById('speed-zoom-tooltip');
        _primarySelect = document.getElementById('speed-zoom-primary');
        _compareSelect = document.getElementById('speed-zoom-compare');
        _cornerPills = document.getElementById('speed-zoom-corner-pills');
        _legendEl = document.getElementById('speed-zoom-legend');
        _cornerMarkersEl = document.getElementById('speed-chart-corner-markers');
        _dragHint = document.getElementById('speed-chart-drag-hint');

        if (!_overviewCanvas || !_zoomCanvas) return;

        _zoomCtx = _zoomCanvas.getContext('2d');

        // Populate dropdowns
        _populateDropdowns();

        // Wire events
        _setupSelectionEvents();
        _setupControlEvents();
        _setupZoomHoverEvents();

        // Load corner positions
        _loadCornerPositions();

        // Set primary lap
        var T = window.TELEMETRY;
        _state.primaryLap = T && T.bestLap ? T.bestLap : (T && T.gpsLaps && T.gpsLaps[0]) || null;
        if (_primarySelect && _state.primaryLap) {
            _primarySelect.value = String(_state.primaryLap);
        }

        // Preload primary lap data
        if (_state.primaryLap) {
            _loadLapData(_state.primaryLap);
        }

        // Resize handler
        var _resizeTimer = null;
        window.addEventListener('resize', function () {
            clearTimeout(_resizeTimer);
            _resizeTimer = setTimeout(function () {
                if (_state.selection) _drawZoomedChart();
                onOverviewRedrawn();
            }, 200);
        });

        // Keyboard
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && _state.selection) {
                resetZoom();
            }
        });

        _state.initialized = true;
    }

    // ── Dropdown population ──────────────────────────
    function _populateDropdowns() {
        var T = window.TELEMETRY;
        if (!T || !T.gpsLaps) return;

        var laps = T.gpsLaps;
        var bestLap = T.bestLap;

        // Primary dropdown
        if (_primarySelect) {
            _primarySelect.textContent = '';
            for (var i = 0; i < laps.length; i++) {
                var opt = document.createElement('option');
                opt.value = String(laps[i]);
                opt.textContent = 'Lap ' + laps[i] + (laps[i] === bestLap ? ' (Best)' : '');
                _primarySelect.appendChild(opt);
            }
        }

        // Compare dropdown
        if (_compareSelect) {
            _compareSelect.textContent = '';
            var noneOpt = document.createElement('option');
            noneOpt.value = '';
            noneOpt.textContent = '\u2014 none \u2014';
            _compareSelect.appendChild(noneOpt);
            for (var i = 0; i < laps.length; i++) {
                var opt = document.createElement('option');
                opt.value = String(laps[i]);
                opt.textContent = 'Lap ' + laps[i] + (laps[i] === bestLap ? ' (Best)' : '');
                _compareSelect.appendChild(opt);
            }
        }
    }

    // ── Load corner positions ────────────────────────
    function _loadCornerPositions() {
        var T = window.TELEMETRY;
        if (!T || !T.sessionId) return;

        // Load corner_positions for brake_point_m
        FetchHelper.fetch('/api/session/' + encodeURIComponent(T.sessionId) + '/corner-positions')
            .then(function (data) {
                if (!data) return;
                // API returns { corners: [...] } or flat array
                var arr = Array.isArray(data) ? data : (data.corners || []);
                if (arr.length === 0) return;
                _state.corners = arr.map(function (c) {
                    return {
                        corner_id: c.corner_id,
                        brake_point_m: c.brake_point_m,
                        throttle_onset_m: null, // filled from corner_metrics if available
                    };
                });
                // Also fetch corner metrics for throttle_onset_m
                return FetchHelper.fetch('/api/session/' + encodeURIComponent(T.sessionId) + '/corner-metrics');
            })
            .then(function (metricsData) {
                if (!metricsData) return;
                // metricsData is usually per-lap; get best lap or average
                var metrics = Array.isArray(metricsData) ? metricsData : (metricsData.corners || []);
                // Build a map: corner_id -> max throttle_onset_m across laps
                var throttleMap = {};
                for (var i = 0; i < metrics.length; i++) {
                    var m = metrics[i];
                    var cid = m.corner_id;
                    var to = m.throttle_onset_m;
                    if (to != null && (!throttleMap[cid] || to > throttleMap[cid])) {
                        throttleMap[cid] = to;
                    }
                }
                for (var j = 0; j < _state.corners.length; j++) {
                    var c = _state.corners[j];
                    if (throttleMap[c.corner_id]) {
                        c.throttle_onset_m = throttleMap[c.corner_id];
                    }
                }
                _drawCornerMarkers();
                _populateCornerPills();
            })
            .catch(function () {
                // Corners not available — no markers
                if (_state.corners.length > 0) {
                    _drawCornerMarkers();
                    _populateCornerPills();
                }
            });
    }

    // ── Corner markers on overview chart ─────────────
    function _drawCornerMarkers() {
        if (!_cornerMarkersEl || _state.corners.length === 0) return;

        var bounds = window.ChartSync && window.ChartSync.getChartBounds
            ? window.ChartSync.getChartBounds() : null;
        if (!bounds) return;

        var containerW = _overviewCanvas ? _overviewCanvas.clientWidth : 600;

        _cornerMarkersEl.textContent = '';
        _cornerMarkersEl.style.width = containerW + 'px';

        for (var i = 0; i < _state.corners.length; i++) {
            var corner = _state.corners[i];
            var dist = corner.brake_point_m;
            if (dist == null || dist < bounds.xMin || dist > bounds.xMax) continue;

            // Convert distance to pixel position within the plot area
            var frac = (dist - bounds.xMin) / (bounds.xMax - bounds.xMin);
            var pxLeft = bounds.plotX + frac * bounds.plotW;

            var marker = document.createElement('div');
            marker.className = 'speed-chart-corner-marker';
            if (_state.activeCorner === corner.corner_id) {
                marker.className += ' active';
            }
            marker.style.left = pxLeft + 'px';
            marker.dataset.cornerId = String(corner.corner_id);

            var tick = document.createElement('div');
            tick.className = 'speed-chart-corner-marker-tick';
            marker.appendChild(tick);

            var label = document.createElement('div');
            label.className = 'speed-chart-corner-marker-label';
            label.textContent = 'C' + corner.corner_id;
            marker.appendChild(label);

            marker.addEventListener('click', (function (cid) {
                return function () { zoomToCorner(cid); };
            })(corner.corner_id));

            _cornerMarkersEl.appendChild(marker);
        }
    }

    // ── Corner pills in zoom controls ────────────────
    function _populateCornerPills() {
        if (!_cornerPills || _state.corners.length === 0) return;

        _cornerPills.textContent = '';
        for (var i = 0; i < _state.corners.length; i++) {
            var corner = _state.corners[i];
            var pill = document.createElement('button');
            pill.type = 'button';
            pill.className = 'speed-zoom-corner-pill';
            if (_state.activeCorner === corner.corner_id) {
                pill.className += ' active';
            }
            pill.textContent = 'C' + corner.corner_id;
            pill.dataset.cornerId = String(corner.corner_id);
            pill.addEventListener('click', (function (cid) {
                return function () { zoomToCorner(cid); };
            })(corner.corner_id));
            _cornerPills.appendChild(pill);
        }
    }

    function _updateActiveCornerUI() {
        // Update markers
        if (_cornerMarkersEl) {
            var markers = _cornerMarkersEl.querySelectorAll('.speed-chart-corner-marker');
            for (var i = 0; i < markers.length; i++) {
                var m = markers[i];
                if (parseInt(m.dataset.cornerId, 10) === _state.activeCorner) {
                    m.classList.add('active');
                } else {
                    m.classList.remove('active');
                }
            }
        }
        // Update pills
        if (_cornerPills) {
            var pills = _cornerPills.querySelectorAll('.speed-zoom-corner-pill');
            for (var i = 0; i < pills.length; i++) {
                var p = pills[i];
                if (parseInt(p.dataset.cornerId, 10) === _state.activeCorner) {
                    p.classList.add('active');
                } else {
                    p.classList.remove('active');
                }
            }
        }
    }

    // ── Selection interaction on overview chart ──────
    function _setupSelectionEvents() {
        if (!_overviewCanvas) return;

        var wrapper = _overviewCanvas.parentElement;
        if (!wrapper) return;

        var isDown = false;
        var startX = 0;
        var MIN_DRAG_PX = 10;

        wrapper.addEventListener('mousedown', function (e) {
            if (e.button !== 0) return; // left-click only
            var bounds = window.ChartSync && window.ChartSync.getChartBounds
                ? window.ChartSync.getChartBounds() : null;
            if (!bounds) return;

            var rect = _overviewCanvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            // Only start drag inside the plot area
            if (mx < bounds.plotX || mx > bounds.plotX + bounds.plotW) return;
            if (my < bounds.plotY || my > bounds.plotY + bounds.plotH) return;

            isDown = true;
            startX = mx;
            _state.isDragging = false;

            e.preventDefault();
        });

        document.addEventListener('mousemove', function (e) {
            if (!isDown) return;

            var rect = _overviewCanvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var bounds = window.ChartSync.getChartBounds();
            if (!bounds) return;

            // Clamp to plot area
            mx = Math.max(bounds.plotX, Math.min(bounds.plotX + bounds.plotW, mx));

            if (Math.abs(mx - startX) > MIN_DRAG_PX) {
                _state.isDragging = true;
                _showSelectionRect(Math.min(startX, mx), Math.max(startX, mx));
            }
        });

        document.addEventListener('mouseup', function (e) {
            if (!isDown) return;
            isDown = false;

            if (!_state.isDragging) return;
            _state.isDragging = false;

            var rect = _overviewCanvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var bounds = window.ChartSync.getChartBounds();
            if (!bounds) return;

            mx = Math.max(bounds.plotX, Math.min(bounds.plotX + bounds.plotW, mx));

            var x1 = Math.min(startX, mx);
            var x2 = Math.max(startX, mx);

            // Convert pixel to distance
            var dist1 = bounds.xMin + (x1 - bounds.plotX) / bounds.plotW * (bounds.xMax - bounds.xMin);
            var dist2 = bounds.xMin + (x2 - bounds.plotX) / bounds.plotW * (bounds.xMax - bounds.xMin);

            _state.activeCorner = null;
            _updateActiveCornerUI();
            zoomToRange(dist1, dist2);
        });
    }

    function _showSelectionRect(x1, x2) {
        if (!_selectionRect) return;
        _selectionRect.style.display = 'block';
        _selectionRect.style.left = x1 + 'px';
        _selectionRect.style.width = (x2 - x1) + 'px';
    }

    function _hideSelectionRect() {
        if (!_selectionRect) return;
        _selectionRect.style.display = 'none';
    }

    function _updateSelectionRect() {
        if (!_state.selection || !_overviewCanvas) {
            _hideSelectionRect();
            return;
        }
        var bounds = window.ChartSync && window.ChartSync.getChartBounds
            ? window.ChartSync.getChartBounds() : null;
        if (!bounds) return;

        var x1 = bounds.plotX + (_state.selection.startDist - bounds.xMin) / (bounds.xMax - bounds.xMin) * bounds.plotW;
        var x2 = bounds.plotX + (_state.selection.endDist - bounds.xMin) / (bounds.xMax - bounds.xMin) * bounds.plotW;
        _showSelectionRect(x1, x2);
    }

    // ── Control events ───────────────────────────────
    function _setupControlEvents() {
        // Primary lap dropdown
        if (_primarySelect) {
            _primarySelect.addEventListener('change', function () {
                var lapNum = parseInt(_primarySelect.value, 10);
                if (!lapNum) return;
                _state.primaryLap = lapNum;
                _loadLapData(lapNum, function () {
                    if (_state.selection) _drawZoomedChart();
                });
            });
        }

        // Compare dropdown
        if (_compareSelect) {
            _compareSelect.addEventListener('change', function () {
                var val = _compareSelect.value;
                _state.comparisonLaps = val ? [parseInt(val, 10)] : [];
                if (_state.comparisonLaps.length > 0) {
                    _loadLapData(_state.comparisonLaps[0], function () {
                        if (_state.selection) _drawZoomedChart();
                    });
                } else {
                    if (_state.selection) _drawZoomedChart();
                }
            });
        }

        // Reset button
        var resetBtn = document.getElementById('speed-zoom-reset');
        if (resetBtn) {
            resetBtn.addEventListener('click', resetZoom);
        }
    }

    // ── Zoom hover tooltip ───────────────────────────
    function _setupZoomHoverEvents() {
        if (!_zoomCanvas) return;

        _zoomCanvas.addEventListener('mousemove', function (e) {
            if (!_state.selection) return;
            var rect = _zoomCanvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;
            _showZoomTooltip(mx, my);
        });

        _zoomCanvas.addEventListener('mouseleave', function () {
            _hideZoomTooltip();
        });
    }

    function _showZoomTooltip(mx, my) {
        if (!_zoomTooltip || !_state.selection) return;

        var sel = _state.selection;
        var w = _zoomCanvas.clientWidth;
        var pad = { top: 20, right: 20, bottom: 40, left: 60 };
        var pW = w - pad.left - pad.right;

        if (mx < pad.left || mx > pad.left + pW) {
            _hideZoomTooltip();
            return;
        }

        var dist = sel.startDist + (mx - pad.left) / pW * (sel.endDist - sel.startDist);

        var primaryData = _state.lapDataCache[_state.primaryLap];
        // Build tooltip via DOM
        var frag = document.createDocumentFragment();

        var header = document.createElement('strong');
        header.textContent = dist.toFixed(0) + 'm';
        frag.appendChild(header);

        if (primaryData && primaryData.distances) {
            var idx = _closestIdx(primaryData.distances, dist);
            if (idx >= 0 && idx < primaryData.speeds.length) {
                var spdKmh = (primaryData.speeds[idx] || 0) * 3.6;
                frag.appendChild(document.createElement('br'));
                var pSpan = document.createElement('span');
                pSpan.style.color = '#fff';
                pSpan.textContent = 'Lap ' + _state.primaryLap + ': ' + spdKmh.toFixed(1) + ' km/h';
                frag.appendChild(pSpan);
            }
        }

        for (var ci = 0; ci < _state.comparisonLaps.length; ci++) {
            var cLap = _state.comparisonLaps[ci];
            var cData = _state.lapDataCache[cLap];
            if (!cData || !cData.distances) continue;
            var cIdx = _closestIdx(cData.distances, dist);
            if (cIdx < 0 || cIdx >= cData.speeds.length) continue;
            var cSpd = (cData.speeds[cIdx] || 0) * 3.6;

            // Determine color based on comparison vs primary
            var pSpd = _interpolateSpeed(primaryData, dist);
            var clr = cSpd >= pSpd ? (C.green || '#10b981') : (C.red || '#ef4444');
            var delta = cSpd - pSpd;
            var sign = delta >= 0 ? '+' : '';
            frag.appendChild(document.createElement('br'));
            var cSpan = document.createElement('span');
            cSpan.style.color = clr;
            cSpan.textContent = 'Lap ' + cLap + ': ' + cSpd.toFixed(1)
                + ' km/h (' + sign + delta.toFixed(1) + ')';
            frag.appendChild(cSpan);
        }

        _zoomTooltip.textContent = '';
        _zoomTooltip.appendChild(frag);
        _zoomTooltip.style.display = 'block';

        var tipW = _zoomTooltip.offsetWidth || 120;
        var left = mx + 12;
        if (left + tipW > w - 10) left = mx - tipW - 12;
        _zoomTooltip.style.left = left + 'px';
        _zoomTooltip.style.top = Math.max(4, my - 20) + 'px';
    }

    function _hideZoomTooltip() {
        if (_zoomTooltip) _zoomTooltip.style.display = 'none';
    }

    // ── Public: zoom to range ────────────────────────
    function zoomToRange(startDist, endDist) {
        if (startDist >= endDist) return;

        _state.selection = { startDist: startDist, endDist: endDist };

        // Ensure primary data is loaded
        if (!_state.primaryLap) {
            var T = window.TELEMETRY;
            _state.primaryLap = (T && T.bestLap) || (T && T.gpsLaps && T.gpsLaps[0]) || null;
            if (_primarySelect && _state.primaryLap) _primarySelect.value = String(_state.primaryLap);
        }

        _updateSelectionRect();
        _showZoomPanel();

        // Load primary data then draw
        if (_state.primaryLap) {
            _loadLapData(_state.primaryLap, function () {
                // Also load comparison laps
                var toLoad = _state.comparisonLaps.filter(function (n) { return !_state.lapDataCache[n]; });
                if (toLoad.length > 0) {
                    var promises = toLoad.map(function (n) { return _loadLapData(n); });
                    Promise.all(promises).then(function () { _drawZoomedChart(); });
                } else {
                    _drawZoomedChart();
                }
            });
        }

        // Smooth scroll to zoom panel
        if (_zoomPanel) {
            setTimeout(function () {
                _zoomPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }, 50);
        }
    }

    // ── Public: zoom to corner ───────────────────────
    function zoomToCorner(cornerId) {
        var corner = null;
        for (var i = 0; i < _state.corners.length; i++) {
            if (_state.corners[i].corner_id === cornerId) {
                corner = _state.corners[i];
                break;
            }
        }
        if (!corner || corner.brake_point_m == null) return;

        var startDist = corner.brake_point_m - 30;
        var endDist = (corner.throttle_onset_m || corner.brake_point_m + 80) + 30;
        if (startDist < 0) startDist = 0;

        _state.activeCorner = cornerId;
        _updateActiveCornerUI();

        zoomToRange(startDist, endDist);
    }

    // ── Public: reset zoom ───────────────────────────
    function resetZoom() {
        _state.selection = null;
        _state.activeCorner = null;
        _hideSelectionRect();
        _hideZoomPanel();
        _updateActiveCornerUI();
    }

    // ── Public: overview redrawn callback ────────────
    function onOverviewRedrawn() {
        _drawCornerMarkers();
        _updateSelectionRect();
    }

    // ── Panel show/hide ──────────────────────────────
    function _showZoomPanel() {
        if (_zoomPanel) _zoomPanel.style.display = '';
        if (_dragHint) _dragHint.style.opacity = '0';
    }

    function _hideZoomPanel() {
        if (_zoomPanel) _zoomPanel.style.display = 'none';
        if (_dragHint) _dragHint.style.opacity = '';
    }

    // ── Data loading ─────────────────────────────────
    function _loadLapData(lapNum, cb) {
        if (_state.lapDataCache[lapNum]) {
            if (cb) cb();
            return Promise.resolve();
        }

        var T = window.TELEMETRY;
        if (!T || !T.sessionId) {
            if (cb) cb();
            return Promise.resolve();
        }

        var url = '/api/session/' + encodeURIComponent(T.sessionId) + '/gps/' + lapNum;
        return FetchHelper.fetch(url)
            .then(function (data) {
                if (data && data.distances && data.speeds) {
                    _state.lapDataCache[lapNum] = data;
                }
                if (cb) cb();
            })
            .catch(function (err) {
                console.warn('SpeedTraceZoom: lap data load failed for lap', lapNum, err);
                if (cb) cb();
            });
    }

    // ── Zoomed chart drawing ─────────────────────────
    function _drawZoomedChart() {
        if (!_zoomCtx || !_state.selection) return;

        var primaryData = _state.lapDataCache[_state.primaryLap];
        if (!primaryData || !primaryData.distances) return;

        var canvas = _zoomCanvas;
        var dpr = window.devicePixelRatio || 1;
        var w = canvas.parentElement.clientWidth;
        var h = 280;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        _zoomCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

        var ctx = _zoomCtx;
        var sel = _state.selection;
        var pad = { top: 20, right: 20, bottom: 40, left: 60 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        // Compute Y range from all visible data in the selection range
        var yMax = 0;
        var allLaps = [_state.primaryLap].concat(_state.comparisonLaps);
        for (var li = 0; li < allLaps.length; li++) {
            var ld = _state.lapDataCache[allLaps[li]];
            if (!ld || !ld.distances || !ld.speeds) continue;
            for (var si = 0; si < ld.distances.length; si++) {
                var d = ld.distances[si];
                if (d === null || d < sel.startDist || d > sel.endDist) continue;
                var spd = ld.speeds[si];
                if (spd !== null && isFinite(spd)) {
                    var sKmh = spd * 3.6;
                    if (sKmh > yMax) yMax = sKmh;
                }
            }
        }
        yMax *= 1.1;
        if (yMax <= 0) yMax = 60;

        var xMin = sel.startDist;
        var xMax = sel.endDist;

        function xToPixel(v) { return pad.left + (v - xMin) / (xMax - xMin) * pW; }
        function yToPixel(v) { return pad.top + pH - (v / yMax) * pH; }

        // Background
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = C.border || '#30363d';
        ctx.lineWidth = 0.5;
        var yTicks = _niceRange(0, yMax, 5);
        for (var i = 0; i < yTicks.length; i++) {
            var y = yToPixel(yTicks[i]);
            ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
        }
        var xTicks = _niceRange(xMin, xMax, 6);
        for (var i = 0; i < xTicks.length; i++) {
            var x = xToPixel(xTicks[i]);
            ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, pad.top + pH); ctx.stroke();
        }

        // Y axis labels
        ctx.fillStyle = C.textSecondary || '#8b949e';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (var i = 0; i < yTicks.length; i++) {
            ctx.fillText(yTicks[i].toFixed(0), pad.left - 8, yToPixel(yTicks[i]));
        }

        // X axis labels
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        for (var i = 0; i < xTicks.length; i++) {
            ctx.fillText(xTicks[i].toFixed(0) + 'm', xToPixel(xTicks[i]), pad.top + pH + 8);
        }

        // Axis titles
        ctx.fillStyle = C.textSecondary || '#8b949e';
        ctx.font = '12px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Distance (m)', pad.left + pW / 2, h - 5);
        ctx.save();
        ctx.translate(14, pad.top + pH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('Speed (km/h)', 0, 0);
        ctx.restore();

        // Corner markers in zoomed view
        for (var ci = 0; ci < _state.corners.length; ci++) {
            var corner = _state.corners[ci];
            var bp = corner.brake_point_m;
            if (bp == null || bp < xMin || bp > xMax) continue;

            var cx = xToPixel(bp);
            ctx.strokeStyle = C.accent || '#ff6b35';
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(cx, pad.top);
            ctx.lineTo(cx, pad.top + pH);
            ctx.stroke();
            ctx.setLineDash([]);

            ctx.fillStyle = C.accent || '#ff6b35';
            ctx.font = 'bold 10px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillText('C' + corner.corner_id, cx, pad.top - 2);
        }

        // ── Draw comparison laps (behind primary) ────
        for (var ci = 0; ci < _state.comparisonLaps.length; ci++) {
            var cLapNum = _state.comparisonLaps[ci];
            var cData = _state.lapDataCache[cLapNum];
            if (!cData || !cData.distances || !cData.speeds) continue;

            ctx.lineWidth = 2;
            // Draw segment-by-segment with green/red coloring
            for (var i = 0; i < cData.distances.length - 1; i++) {
                var d1 = cData.distances[i];
                var d2 = cData.distances[i + 1];
                if (d1 === null || d2 === null) continue;
                if (d2 < xMin || d1 > xMax) continue;

                var s1 = cData.speeds[i];
                var s2 = cData.speeds[i + 1];
                if (s1 === null || s2 === null || !isFinite(s1) || !isFinite(s2)) continue;

                var s1Kmh = s1 * 3.6;
                var s2Kmh = s2 * 3.6;

                // Compare against primary at this distance
                var pSpd = _interpolateSpeed(primaryData, (d1 + d2) / 2);
                var avgCSpd = (s1Kmh + s2Kmh) / 2;

                ctx.strokeStyle = avgCSpd >= pSpd
                    ? (C.green || '#10b981')
                    : (C.red || '#ef4444');

                ctx.beginPath();
                ctx.moveTo(xToPixel(d1), yToPixel(s1Kmh));
                ctx.lineTo(xToPixel(d2), yToPixel(s2Kmh));
                ctx.stroke();
            }
        }

        // ── Draw primary lap (white, on top) ─────────
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        var started = false;
        for (var i = 0; i < primaryData.distances.length; i++) {
            var d = primaryData.distances[i];
            var s = primaryData.speeds[i];
            if (d === null || s === null || !isFinite(s)) continue;
            if (d < xMin || d > xMax) continue;

            var px = xToPixel(d);
            var py = yToPixel(s * 3.6);
            if (!started) { ctx.moveTo(px, py); started = true; }
            else { ctx.lineTo(px, py); }
        }
        ctx.stroke();

        // ── Legend ────────────────────────────────────
        _updateLegend();

        // Register __redraw for ResizeObserver
        canvas.__redraw = function() { _drawZoomedChart(); };
    }

    // ── Legend ────────────────────────────────────────
    function _updateLegend() {
        if (!_legendEl) return;

        _legendEl.textContent = '';

        // Primary item
        var pItem = document.createElement('span');
        pItem.className = 'speed-zoom-legend-item';
        var pSwatch = document.createElement('span');
        pSwatch.className = 'speed-zoom-legend-swatch';
        pSwatch.style.background = '#fff';
        pItem.appendChild(pSwatch);
        pItem.appendChild(document.createTextNode(' Lap ' + _state.primaryLap + ' (primary)'));
        _legendEl.appendChild(pItem);

        // Comparison items
        for (var i = 0; i < _state.comparisonLaps.length; i++) {
            var cLap = _state.comparisonLaps[i];
            var cItem = document.createElement('span');
            cItem.className = 'speed-zoom-legend-item';

            var gSwatch = document.createElement('span');
            gSwatch.className = 'speed-zoom-legend-swatch';
            gSwatch.style.background = C.green || '#10b981';
            cItem.appendChild(gSwatch);
            var fasterText = document.createElement('span');
            fasterText.style.color = C.green || '#10b981';
            fasterText.textContent = 'Faster';
            cItem.appendChild(fasterText);

            cItem.appendChild(document.createTextNode(' / '));

            var rSwatch = document.createElement('span');
            rSwatch.className = 'speed-zoom-legend-swatch';
            rSwatch.style.background = C.red || '#ef4444';
            cItem.appendChild(rSwatch);
            var slowerText = document.createElement('span');
            slowerText.style.color = C.red || '#ef4444';
            slowerText.textContent = 'Slower';
            cItem.appendChild(slowerText);

            cItem.appendChild(document.createTextNode(' \u2014 Lap ' + cLap));
            _legendEl.appendChild(cItem);
        }

        // Range text
        if (_state.selection) {
            var rangeSpan = document.createElement('span');
            rangeSpan.className = 'speed-zoom-range-text';
            rangeSpan.textContent = _state.selection.startDist.toFixed(0) + 'm \u2013 '
                + _state.selection.endDist.toFixed(0) + 'm';
            _legendEl.appendChild(rangeSpan);
        }
    }

    // ── Helpers ──────────────────────────────────────

    function _interpolateSpeed(lapData, dist) {
        if (!lapData || !lapData.distances || !lapData.speeds) return 0;
        var dists = lapData.distances;
        var speeds = lapData.speeds;
        var idx = _closestIdx(dists, dist);
        if (idx < 0) return 0;
        var spd = speeds[idx];
        return (spd != null && isFinite(spd)) ? spd * 3.6 : 0;
    }

    function _closestIdx(arr, target) {
        if (!arr || arr.length === 0) return -1;
        var lo = 0, hi = arr.length - 1;
        while (lo < hi) {
            var mid = (lo + hi) >> 1;
            if (arr[mid] < target) lo = mid + 1;
            else hi = mid;
        }
        if (lo > 0 && Math.abs(arr[lo - 1] - target) < Math.abs(arr[lo] - target)) return lo - 1;
        return lo;
    }

    function _niceRange(lo, hi, count) {
        var range = hi - lo;
        if (range <= 0) return [lo];
        var step = range / count;
        var mag = Math.pow(10, Math.floor(Math.log10(step)));
        var residual = step / mag;
        var niceStep;
        if (residual <= 1.5) niceStep = 1;
        else if (residual <= 3) niceStep = 2;
        else if (residual <= 7) niceStep = 5;
        else niceStep = 10;
        niceStep *= mag;
        var ticks = [];
        var start = Math.ceil(lo / niceStep) * niceStep;
        for (var v = start; v <= hi; v += niceStep) ticks.push(v);
        return ticks;
    }

    // ── DOMContentLoaded auto-init ───────────────────
    document.addEventListener('DOMContentLoaded', function () {
        // Delay init to ensure ChartSync has loaded
        setTimeout(function () {
            if (document.getElementById('speed-chart')) {
                init();
            }
        }, 100);
    });

})();
