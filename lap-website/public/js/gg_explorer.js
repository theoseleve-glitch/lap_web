/**
 * gg_explorer.js — Interactive G-G Explorer with mini track map.
 *
 * Three modes:
 *   All     — Density-colored heatmap of ALL laps (no click-to-map)
 *   Single  — One lap's G-G in white dots, click → orange marker on map
 *   Compare — Primary (white) + compare (cyan), click maps primary
 *
 * Public API:  window.GGExplorer = { init }
 */
(function () {
    'use strict';

    var _lc = window.LifecycleHelpers.create();
    var MAX_LAP_CACHE = 20;

    var C = window.Theme ? window.Theme.colors : {};
    window.GGExplorer = { init: init };

    /* ── state ─────────────────────────────────── */
    var _sid;
    var _ggCanvas, _ggCtx, _mapCanvas, _mapCtx;
    var _tooltip, _infoBar, _loadingEl, _statsEl;
    var _modeGroup, _primaryLabel, _primarySelect;
    var _compareLabel, _compareSelect;

    var _state = {
        mode: 'all',
        primaryLap: null,
        compareLap: null,
        lapDataCache: {},
        allGGData: null,
        perLap: null,
        selectedIdx: null,
        corners: [],
        zoomLevel: 1.0,
        panX: 0,
        panY: 0,
        baseAxisMax: 1.0,
        frictionR: 0,
        projection: null,
    };

    var _ggPad = { top: 35, right: 35, bottom: 55, left: 70 };
    var _mapPad = { top: 10, right: 10, bottom: 10, left: 10 };
    var _isDragging = false;
    var _dragMoved = false;
    var _dragStartX = 0, _dragStartY = 0;
    var _dragStartPanX = 0, _dragStartPanY = 0;

    /* ── Time animation state ──────────────────── */
    var _animFrame = null;
    var _animIdx = 0;
    var _animPlaying = false;
    var _animSpeed = 3;   // points per frame
    var _animBtn = null;

    /* ── init ──────────────────────────────────── */
    function init(containerId, sessionId) {
        var container = document.getElementById(containerId);
        if (!container) return;
        _sid = sessionId;

        _ggCanvas = document.getElementById('gg-explorer-canvas');
        _mapCanvas = document.getElementById('gg-explorer-minimap');
        _tooltip = container.querySelector('.gg-explorer-tooltip');
        _infoBar = document.getElementById('gg-info-bar');
        _loadingEl = document.getElementById('gg-loading');
        _statsEl = document.getElementById('gg-stats');
        _modeGroup = document.getElementById('gg-mode-group');
        _primaryLabel = document.getElementById('gg-primary-label');
        _primarySelect = document.getElementById('gg-primary-select');
        _compareLabel = document.getElementById('gg-compare-label');
        _compareSelect = document.getElementById('gg-compare-select');

        if (!_ggCanvas || !_mapCanvas) return;
        _ggCtx = _ggCanvas.getContext('2d');
        _mapCtx = _mapCanvas.getContext('2d');

        _setupModeButtons();
        _setupDropdowns();
        _setupGGEvents();
        _setupAnimButton();

        /* Lazy-init on tab activate */
        var panel = container.closest('.tab-panel');
        var _loaded = false;
        function _load() {
            if (_loaded) return;
            if (!_ggCanvas.parentElement || _ggCanvas.parentElement.clientWidth < 50) return;
            _loaded = true;
            _fetchData();
        }
        if (panel) {
            _lc.addListener(panel, 'tab:activate', function () {
                requestAnimationFrame(_load);
            });
        }
        /* Try immediately (covers late tab-switch) */
        _load();
    }

    /* ── data fetch ────────────────────────────── */
    function _fetchData() {
        var T = window.TELEMETRY;
        if (!T) return;

        var ggUrl = '/api/session/' + encodeURIComponent(_sid) + '/gg_data';
        var cornerUrl = '/api/session/' + encodeURIComponent(_sid) + '/corner-positions';
        var bestLap = T.bestLap || (T.gpsLaps && T.gpsLaps[0]);

        var promises = [
            FetchHelper.fetch(ggUrl),
            FetchHelper.fetch(cornerUrl).catch(function () { return { corners: [] }; }),
        ];

        /* Pre-load best lap GPS for mini map */
        if (bestLap) {
            var gpsUrl = '/api/session/' + encodeURIComponent(_sid) + '/gps/' + bestLap;
            promises.push(FetchHelper.fetch(gpsUrl).then(function (d) {
                if (d) {
                    _state.lapDataCache[bestLap] = d;
                    var _cKeys = Object.keys(_state.lapDataCache);
                    if (_cKeys.length > MAX_LAP_CACHE) {
                        delete _state.lapDataCache[_cKeys[0]];
                    }
                }
            }).catch(function () {}));
        }

        Promise.all(promises).then(function (results) {
            var ggData = results[0];
            var cornerResp = results[1];

            if (!ggData || !ggData.accel_lat || ggData.accel_lat.length === 0) {
                _showNoData('No acceleration data available.');
                return;
            }

            _state.allGGData = { accel_lat: ggData.accel_lat, accel_long: ggData.accel_long };
            _state.perLap = ggData.per_lap || {};
            _state.corners = (cornerResp && cornerResp.corners) ? cornerResp.corners : [];
            _state.primaryLap = bestLap;

            _populateDropdowns();
            _hideLoading();
            _sizeCanvases();
            _computeGGBounds(_state.allGGData.accel_lat, _state.allGGData.accel_long);
            _drawAll();

            // Register __redraw for ResizeObserver on both canvases
            _ggCanvas.__redraw = function() {
                if (!_state.allGGData) return;
                _sizeCanvases();
                _drawAll();
            };
            _mapCanvas.__redraw = function() {
                if (!_state.allGGData) return;
                _sizeCanvases();
                _drawAll();
            };
        }).catch(function () {
            _showNoData('Failed to load acceleration data.');
        });
    }

    /* ── helpers ───────────────────────────────── */
    function _showNoData(msg) {
        if (!_loadingEl) return;
        _loadingEl.textContent = '';
        var div = document.createElement('div');
        div.className = 'no-data';
        var icon = document.createElement('div');
        icon.className = 'no-data-icon';
        icon.textContent = '\u26A0';
        var txt = document.createElement('div');
        txt.className = 'no-data-text';
        txt.textContent = msg;
        div.appendChild(icon);
        div.appendChild(txt);
        _loadingEl.appendChild(div);
        _loadingEl.style.display = '';
    }

    function _hideLoading() {
        if (_loadingEl) _loadingEl.style.display = 'none';
    }

    function _sizeCanvases() {
        var dpr = window.devicePixelRatio || 1;

        /* GG canvas */
        var ggW = _ggCanvas.parentElement.clientWidth;
        var ggH = Math.max(350, Math.min(480, ggW * 0.7));
        _ggCanvas.width = ggW * dpr;
        _ggCanvas.height = ggH * dpr;
        _ggCanvas.style.width = ggW + 'px';
        _ggCanvas.style.height = ggH + 'px';
        _ggCtx.setTransform(1, 0, 0, 1, 0, 0);
        _ggCtx.scale(dpr, dpr);

        /* Mini map */
        var mapW = _mapCanvas.parentElement.clientWidth;
        var mapH = ggH; /* match GG height */
        _mapCanvas.width = mapW * dpr;
        _mapCanvas.height = mapH * dpr;
        _mapCanvas.style.width = mapW + 'px';
        _mapCanvas.style.height = mapH + 'px';
        _mapCtx.setTransform(1, 0, 0, 1, 0, 0);
        _mapCtx.scale(dpr, dpr);
    }

    /* ── G-G coordinate system ─────────────────── */
    function _computeGGBounds(aLat, aLong) {
        var maxG = 0;
        for (var i = 0; i < aLat.length; i++) {
            if (aLat[i] === null || aLong[i] === null) continue;
            if (!isFinite(aLat[i]) || !isFinite(aLong[i])) continue;
            var mag = Math.sqrt(aLat[i] * aLat[i] + aLong[i] * aLong[i]);
            if (mag > maxG) maxG = mag;
        }
        var axisMax = Math.ceil(maxG * 1.15 * 10) / 10;
        if (axisMax < 0.5) axisMax = 0.5;
        _state.baseAxisMax = axisMax;
        _state.frictionR = maxG * 0.95;
    }

    function _getAxisMax() { return _state.baseAxisMax / _state.zoomLevel; }

    function _ggW() { return parseFloat(_ggCanvas.style.width) || _ggCanvas.parentElement.clientWidth; }
    function _ggH() { return parseFloat(_ggCanvas.style.height) || 400; }
    function _ggPW() { return _ggW() - _ggPad.left - _ggPad.right; }
    function _ggPH() { return _ggH() - _ggPad.top - _ggPad.bottom; }

    function _xToPixel(v) {
        var axisMax = _getAxisMax();
        return _ggPad.left + ((v - _state.panX) + axisMax) / (2 * axisMax) * _ggPW();
    }
    function _yToPixel(v) {
        var axisMax = _getAxisMax();
        return _ggPad.top + _ggPH() - ((v - _state.panY) + axisMax) / (2 * axisMax) * _ggPH();
    }
    function _pixelToGX(px) {
        var axisMax = _getAxisMax();
        return ((px - _ggPad.left) / _ggPW()) * (2 * axisMax) - axisMax + _state.panX;
    }
    function _pixelToGY(py) {
        var axisMax = _getAxisMax();
        return (1 - (py - _ggPad.top) / _ggPH()) * (2 * axisMax) - axisMax + _state.panY;
    }

    /* ── mini map projection ───────────────────── */
    function _computeProjection() {
        var lapData = _getLapForMap();
        if (!lapData || !lapData.latitudes || lapData.latitudes.length < 2) {
            _state.projection = null;
            return;
        }

        var allLats = [], allLons = [];
        for (var i = 0; i < lapData.latitudes.length; i++) {
            if (lapData.latitudes[i] !== null && lapData.longitudes[i] !== null) {
                allLats.push(lapData.latitudes[i]);
                allLons.push(lapData.longitudes[i]);
            }
        }
        if (allLats.length < 2) { _state.projection = null; return; }

        var latMin = Math.min.apply(null, allLats);
        var latMax = Math.max.apply(null, allLats);
        var lonMin = Math.min.apply(null, allLons);
        var lonMax = Math.max.apply(null, allLons);
        var originLat = (latMin + latMax) / 2;

        var mPerDegLat = 111320;
        var mPerDegLon = 111320 * Math.cos(originLat * Math.PI / 180);
        var rangeX = (lonMax - lonMin) * mPerDegLon;
        var rangeY = (latMax - latMin) * mPerDegLat;

        var mW = parseFloat(_mapCanvas.style.width) || _mapCanvas.parentElement.clientWidth;
        var mH = parseFloat(_mapCanvas.style.height) || 350;
        var plotW = mW - _mapPad.left - _mapPad.right;
        var plotH = mH - _mapPad.top - _mapPad.bottom;

        var scaleX = plotW / Math.max(rangeX, 1);
        var scaleY = plotH / Math.max(rangeY, 1);
        var scale = Math.min(scaleX, scaleY) * 0.88;

        _state.projection = {
            mPerDegLat: mPerDegLat,
            mPerDegLon: mPerDegLon,
            scale: scale,
            offsetX: _mapPad.left + (plotW - rangeX * scale) / 2,
            offsetY: _mapPad.top + (plotH - rangeY * scale) / 2,
            latMin: latMin, latMax: latMax, lonMin: lonMin, lonMax: lonMax,
            width: mW, height: mH,
        };
    }

    function _toPixel(lat, lon) {
        var p = _state.projection;
        if (!p) return null;
        var mx = (lon - p.lonMin) * p.mPerDegLon;
        var my = (lat - p.latMin) * p.mPerDegLat;
        return {
            x: p.offsetX + mx * p.scale,
            y: p.offsetY + (p.latMax - p.latMin) * p.mPerDegLat * p.scale - my * p.scale,
        };
    }

    function _getLapForMap() {
        return _state.lapDataCache[_state.primaryLap] || null;
    }

    /* ── color helpers ─────────────────────────── */
    function _densityColor(t) {
        t = Math.max(0, Math.min(1, t));
        var r, g, b;
        if (t < 0.25) {
            r = 0; g = Math.round(100 + 155 * (t / 0.25)); b = 255;
        } else if (t < 0.5) {
            r = 0; g = 255; b = Math.round(255 * (1 - (t - 0.25) / 0.25));
        } else if (t < 0.75) {
            r = Math.round(255 * ((t - 0.5) / 0.25)); g = 255; b = 0;
        } else {
            r = 255; g = Math.round(255 * (1 - (t - 0.75) / 0.25)); b = 0;
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    function _speedColor(speed, minSpd, maxSpd) {
        var t = maxSpd > minSpd ? (speed - minSpd) / (maxSpd - minSpd) : 0.5;
        t = Math.max(0, Math.min(1, t));
        var r, g, b;
        if (t < 0.33) {
            var s = t / 0.33;
            r = Math.round(50 + s * 205); g = Math.round(200 + s * 55); b = Math.round(50 - s * 20);
        } else if (t < 0.66) {
            var s2 = (t - 0.33) / 0.33;
            r = 255; g = Math.round(255 - s2 * 100); b = 30;
        } else {
            var s3 = (t - 0.66) / 0.34;
            r = 255; g = Math.round(155 - s3 * 155); b = Math.round(30 + s3 * 20);
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    /* ── draw orchestrator ─────────────────────── */
    function _drawAll() {
        _drawGG();
        _computeProjection();
        _drawMiniMap();
        _updateStats();
    }

    /* ── G-G scatter ───────────────────────────── */
    function _drawGG() {
        if (!_state.allGGData || !_ggCtx) return;
        var w = _ggW(), h = _ggH();
        var ctx = _ggCtx;
        var pW = _ggPW(), pH = _ggPH();
        var axisMax = _getAxisMax();

        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, w, h);

        /* Clip to plot area */
        ctx.save();
        ctx.beginPath();
        ctx.rect(_ggPad.left, _ggPad.top, pW, pH);
        ctx.clip();

        /* Grid */
        ctx.strokeStyle = C.border || '#30363d';
        ctx.lineWidth = 0.5;
        var step = axisMax <= 0.3 ? 0.05 : axisMax <= 0.6 ? 0.1 : axisMax <= 1.2 ? 0.25 : 0.5;
        var gMin = -_state.baseAxisMax * 2;
        var gMax = _state.baseAxisMax * 2;
        for (var g = Math.ceil(gMin / step) * step; g <= gMax; g += step) {
            var yy = _yToPixel(g);
            if (yy >= _ggPad.top && yy <= _ggPad.top + pH) {
                ctx.beginPath(); ctx.moveTo(_ggPad.left, yy); ctx.lineTo(_ggPad.left + pW, yy); ctx.stroke();
            }
            var xx = _xToPixel(g);
            if (xx >= _ggPad.left && xx <= _ggPad.left + pW) {
                ctx.beginPath(); ctx.moveTo(xx, _ggPad.top); ctx.lineTo(xx, _ggPad.top + pH); ctx.stroke();
            }
        }

        /* Axes through origin */
        ctx.strokeStyle = C.textMuted || '#484f58';
        ctx.lineWidth = 1;
        var ox = _xToPixel(0), oy = _yToPixel(0);
        ctx.beginPath(); ctx.moveTo(ox, _ggPad.top); ctx.lineTo(ox, _ggPad.top + pH); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(_ggPad.left, oy); ctx.lineTo(_ggPad.left + pW, oy); ctx.stroke();

        /* Friction circle */
        var cx = _xToPixel(0), cy = _yToPixel(0);
        var rPx = axisMax > 0 ? (_state.frictionR / axisMax) * (pW / 2) : 0;
        if (rPx > 0) {
            ctx.strokeStyle = 'rgba(139, 148, 158, 0.8)';
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 4]);
            ctx.beginPath(); ctx.arc(cx, cy, rPx, 0, 2 * Math.PI); ctx.stroke();
        }
        ctx.setLineDash([]);

        /* Render based on mode */
        if (_state.mode === 'all') {
            _drawDensityScatter(ctx, _state.allGGData.accel_lat, _state.allGGData.accel_long, null);
        } else if (_state.mode === 'single') {
            var lapKey = String(_state.primaryLap);
            var lapGG = _state.perLap[lapKey];
            if (lapGG) {
                _drawSingleScatter(ctx, lapGG.accel_lat, lapGG.accel_long, '#e6edf3', true);
            }
        } else if (_state.mode === 'compare') {
            /* Compare lap first (under) */
            var cmpKey = String(_state.compareLap);
            var cmpGG = _state.perLap[cmpKey];
            if (cmpGG) {
                _drawSingleScatter(ctx, cmpGG.accel_lat, cmpGG.accel_long, '#00d4ff', false);
            }
            /* Primary lap on top */
            var priKey = String(_state.primaryLap);
            var priGG = _state.perLap[priKey];
            if (priGG) {
                _drawSingleScatter(ctx, priGG.accel_lat, priGG.accel_long, '#e6edf3', true);
            }
        }

        /* Highlight selected point */
        if (_state.selectedIdx !== null && _state.mode !== 'all' && _state.perLap) {
            var lapGGData = _state.perLap[String(_state.primaryLap)];
            if (lapGGData) {
                var si = _state.selectedIdx;
                if (si < lapGGData.accel_lat.length) {
                    var sx = _xToPixel(lapGGData.accel_lat[si]);
                    var sy = _yToPixel(lapGGData.accel_long[si]);
                    ctx.strokeStyle = C.accent || '#ff6b35';
                    ctx.lineWidth = 2.5;
                    ctx.beginPath(); ctx.arc(sx, sy, 6, 0, 2 * Math.PI); ctx.stroke();
                    ctx.fillStyle = C.accent || '#ff6b35';
                    ctx.globalAlpha = 0.4;
                    ctx.beginPath(); ctx.arc(sx, sy, 6, 0, 2 * Math.PI); ctx.fill();
                    ctx.globalAlpha = 1;
                }
            }
        }

        /* Friction circle label */
        ctx.fillStyle = C.textPrimary || '#c9d1d9';
        ctx.font = '12px "Inter", "Segoe UI", sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(_state.frictionR.toFixed(2) + 'G envelope', cx + rPx + 6, cy - rPx + 14);

        ctx.restore(); /* End clip */

        /* Axis tick labels */
        ctx.fillStyle = C.textPrimary || '#c9d1d9';
        ctx.font = '13px "Inter", "Segoe UI", sans-serif';
        for (var g2 = Math.ceil(gMin / step) * step; g2 <= gMax; g2 += step) {
            if (Math.abs(g2) < 0.001) continue;
            var xp = _xToPixel(g2);
            if (xp >= _ggPad.left && xp <= _ggPad.left + pW) {
                ctx.textAlign = 'center'; ctx.textBaseline = 'top';
                ctx.fillText(g2.toFixed(2) + 'G', xp, _ggPad.top + pH + 8);
            }
            var yp = _yToPixel(g2);
            if (yp >= _ggPad.top && yp <= _ggPad.top + pH) {
                ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
                ctx.fillText(g2.toFixed(2) + 'G', _ggPad.left - 10, yp);
            }
        }

        /* Axis titles */
        ctx.fillStyle = C.textPrimary || '#e6edf3';
        ctx.font = 'bold 14px "Inter", "Segoe UI", sans-serif';
        ctx.textAlign = 'center'; ctx.textBaseline = 'top';
        ctx.fillText('Lateral G', _ggPad.left + pW / 2, h - 16);
        ctx.save();
        ctx.translate(16, _ggPad.top + pH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.textBaseline = 'middle';
        ctx.fillText('Longitudinal G', 0, 0);
        ctx.restore();

        /* Quadrant labels */
        ctx.fillStyle = C.textSecondary || 'rgba(201, 209, 217, 0.5)';
        ctx.font = 'bold 12px "Inter", "Segoe UI", sans-serif';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        var qCx = _xToPixel(0), qCy = _yToPixel(0);
        if (qCy > _ggPad.top + 20 && qCy < _ggPad.top + pH) {
            ctx.fillText('BRAKING', qCx, Math.max(_ggPad.top + 16, qCy - pH * 0.35));
            ctx.fillText('ACCELERATION', qCx, Math.min(_ggPad.top + pH - 12, qCy + pH * 0.35));
        }
        if (qCx > _ggPad.left && qCx < _ggPad.left + pW) {
            ctx.fillText('LEFT', Math.max(_ggPad.left + 30, qCx - pW * 0.35), qCy);
            ctx.fillText('RIGHT', Math.min(_ggPad.left + pW - 30, qCx + pW * 0.35), qCy);
        }

        /* Zoom indicator */
        if (_state.zoomLevel > 1.01) {
            ctx.fillStyle = C.accent || 'rgba(255, 107, 53, 0.8)';
            ctx.font = '11px "Inter", "Segoe UI", sans-serif';
            ctx.textAlign = 'right'; ctx.textBaseline = 'top';
            ctx.fillText('Zoom: ' + _state.zoomLevel.toFixed(1) + 'x  (dbl-click to reset)', w - _ggPad.right, _ggPad.top + 4);
        }
    }

    /* Density heatmap (All mode) */
    function _drawDensityScatter(ctx, aLat, aLong) {
        var gridSize = 40;
        var grid = {};
        var pts = [];
        for (var i = 0; i < aLat.length; i++) {
            if (aLat[i] === null || aLong[i] === null) continue;
            if (!isFinite(aLat[i]) || !isFinite(aLong[i])) continue;
            var px = _xToPixel(aLat[i]);
            var py = _yToPixel(aLong[i]);
            if (px < _ggPad.left || px > _ggPad.left + _ggPW()) continue;
            if (py < _ggPad.top || py > _ggPad.top + _ggPH()) continue;
            var gx = Math.floor(px / gridSize);
            var gy = Math.floor(py / gridSize);
            var key = gx + ',' + gy;
            grid[key] = (grid[key] || 0) + 1;
            pts.push({ px: px, py: py, key: key });
        }
        var maxDensity = 0;
        for (var k in grid) { if (grid[k] > maxDensity) maxDensity = grid[k]; }

        var dotR = pts.length > 5000 ? 1.2 : pts.length > 1000 ? 1.8 : 2.5;
        for (var j = 0; j < pts.length; j++) {
            var density = grid[pts[j].key] || 1;
            var t = Math.min(1, density / Math.max(1, maxDensity * 0.6));
            ctx.fillStyle = _densityColor(t);
            ctx.globalAlpha = 0.7;
            ctx.beginPath(); ctx.arc(pts[j].px, pts[j].py, dotR, 0, 2 * Math.PI); ctx.fill();
        }
        ctx.globalAlpha = 1;
    }

    /* Single-color scatter (Single / Compare modes) */
    function _drawSingleScatter(ctx, aLat, aLong, color, isPrimary) {
        var n = Math.min(aLat.length, aLong.length);
        var dotR = n > 3000 ? 1.5 : n > 800 ? 2.0 : 2.8;
        ctx.fillStyle = color;
        ctx.globalAlpha = isPrimary ? 0.7 : 0.45;
        for (var i = 0; i < n; i++) {
            if (aLat[i] === null || aLong[i] === null) continue;
            if (!isFinite(aLat[i]) || !isFinite(aLong[i])) continue;
            var px = _xToPixel(aLat[i]);
            var py = _yToPixel(aLong[i]);
            if (px < _ggPad.left || px > _ggPad.left + _ggPW()) continue;
            if (py < _ggPad.top || py > _ggPad.top + _ggPH()) continue;
            ctx.beginPath(); ctx.arc(px, py, dotR, 0, 2 * Math.PI); ctx.fill();
        }
        ctx.globalAlpha = 1;
    }

    /* ── mini track map ────────────────────────── */
    function _drawMiniMap() {
        var p = _state.projection;
        var mW = parseFloat(_mapCanvas.style.width) || _mapCanvas.parentElement.clientWidth;
        var mH = parseFloat(_mapCanvas.style.height) || 350;
        var ctx = _mapCtx;

        ctx.clearRect(0, 0, mW, mH);
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, mW, mH);

        var lapData = _getLapForMap();
        if (!p || !lapData || !lapData.latitudes) {
            ctx.fillStyle = C.textMuted || '#484f58';
            ctx.font = '12px "Inter", "Segoe UI", sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('No GPS data for map', mW / 2, mH / 2);
            return;
        }

        /* Speed range */
        var speeds = lapData.speeds || [];
        var minSpd = Infinity, maxSpd = -Infinity;
        for (var i = 0; i < speeds.length; i++) {
            if (speeds[i] !== null && isFinite(speeds[i])) {
                if (speeds[i] < minSpd) minSpd = speeds[i];
                if (speeds[i] > maxSpd) maxSpd = speeds[i];
            }
        }
        if (minSpd === Infinity) { minSpd = 0; maxSpd = 1; }

        /* Draw speed-colored polyline */
        ctx.lineCap = 'round'; ctx.lineJoin = 'round';
        ctx.lineWidth = 3; ctx.globalAlpha = 0.9;
        for (var i2 = 0; i2 < lapData.latitudes.length - 1; i2++) {
            if (lapData.latitudes[i2] === null || lapData.latitudes[i2 + 1] === null) continue;
            var p1 = _toPixel(lapData.latitudes[i2], lapData.longitudes[i2]);
            var p2 = _toPixel(lapData.latitudes[i2 + 1], lapData.longitudes[i2 + 1]);
            if (!p1 || !p2) continue;
            ctx.strokeStyle = (speeds[i2] !== null && speeds[i2] !== undefined)
                ? _speedColor(speeds[i2], minSpd, maxSpd) : (C.textSecondary || '#8b949e');
            ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
        }
        ctx.globalAlpha = 1;

        /* S/F marker */
        if (lapData.latitudes[0] !== null) {
            var sf = _toPixel(lapData.latitudes[0], lapData.longitudes[0]);
            if (sf) {
                ctx.beginPath(); ctx.arc(sf.x, sf.y, 5, 0, Math.PI * 2);
                ctx.fillStyle = C.accent || '#ff6b35'; ctx.fill();
                ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke();
                ctx.fillStyle = '#fff'; ctx.font = 'bold 9px "Inter", "Segoe UI", sans-serif';
                ctx.textAlign = 'left'; ctx.fillText('S/F', sf.x + 8, sf.y + 3);
            }
        }

        /* Corner markers */
        _drawCorners(ctx);

        /* Selected point marker */
        if (_state.selectedIdx !== null && _state.mode !== 'all') {
            var ld = lapData;
            var si2 = _state.selectedIdx;
            if (si2 < ld.latitudes.length && ld.latitudes[si2] !== null) {
                var mp = _toPixel(ld.latitudes[si2], ld.longitudes[si2]);
                if (mp) {
                    ctx.beginPath(); ctx.arc(mp.x, mp.y, 8, 0, Math.PI * 2);
                    ctx.fillStyle = C.accent || '#ff6b35'; ctx.fill();
                    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2.5; ctx.stroke();
                }
            }
        }

        /* Map title */
        ctx.fillStyle = C.textMuted || '#484f58';
        ctx.font = '10px "Inter", "Segoe UI", sans-serif';
        ctx.textAlign = 'center';
        var lapLabel = _state.primaryLap ? ('Lap ' + _state.primaryLap) : 'Best Lap';
        ctx.fillText(lapLabel + ' track', mW / 2, mH - 4);
    }

    function _drawCorners(ctx) {
        if (!_state.corners || _state.corners.length === 0) return;
        var COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6'];
        for (var i = 0; i < _state.corners.length; i++) {
            var c = _state.corners[i];
            var pp = _toPixel(c.lat, c.lon);
            if (!pp) continue;
            var col = COLORS[i % COLORS.length];
            ctx.beginPath(); ctx.arc(pp.x, pp.y, 10, 0, Math.PI * 2);
            ctx.fillStyle = col; ctx.fill();
            ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke();
            ctx.fillStyle = '#fff'; ctx.font = 'bold 9px "Inter", "Segoe UI", sans-serif';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText('C' + c.corner_id, pp.x, pp.y);
            ctx.textBaseline = 'alphabetic';
        }
    }

    /* ── time animation ─────────────────────────── */
    function _startAnimation() {
        if (_state.mode !== 'single' || !_state.perLap) return;
        var lapData = _state.lapDataCache[_state.primaryLap];
        if (!lapData) return;
        _animPlaying = true;
        _animIdx = 0;
        if (_animBtn) _animBtn.textContent = '\u25A0'; // stop icon
        _animTick(lapData);
    }

    function _stopAnimation() {
        _animPlaying = false;
        if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null; }
        if (_animBtn) _animBtn.textContent = '\u25B6'; // play icon
        _drawAll(); // redraw full
    }

    function _animTick(lapData) {
        if (!_animPlaying || !_ggCtx) return;
        var aLat = lapData.a_lat;
        var aLong = lapData.a_long;
        if (!aLat || !aLong) return;
        var total = Math.min(aLat.length, aLong.length);
        _animIdx = Math.min(_animIdx + _animSpeed, total);

        // Redraw base
        _drawGG_base();

        // Draw animated subset
        var ctx = _ggCtx;
        var axisMax = _getAxisMax();
        var pW = _ggPW(), pH = _ggPH();
        ctx.save();
        ctx.beginPath();
        ctx.rect(_ggPad.left, _ggPad.top, pW, pH);
        ctx.clip();
        for (var i = 0; i < _animIdx; i++) {
            var lat = aLat[i] / 9.81;
            var lng = aLong[i] / 9.81;
            var t = i / total;
            ctx.fillStyle = window.Theme ? window.Theme.heatColor(t) : 'rgba(255,255,255,0.7)';
            ctx.beginPath();
            ctx.arc(_xToPixel(lat), _yToPixel(lng), 2.5, 0, 2 * Math.PI);
            ctx.fill();
        }
        ctx.restore();

        // Time progress bar
        var barY = _ggH() - 8;
        var barW = _ggW() - _ggPad.left - _ggPad.right;
        var progress = _animIdx / total;
        ctx.fillStyle = C.border || '#30363d';
        ctx.fillRect(_ggPad.left, barY, barW, 4);
        ctx.fillStyle = C.accent || '#ff6b35';
        ctx.fillRect(_ggPad.left, barY, barW * progress, 4);

        if (_animIdx < total) {
            _animFrame = requestAnimationFrame(function () { _animTick(lapData); });
        } else {
            _animPlaying = false;
            if (_animBtn) _animBtn.textContent = '\u25B6';
        }
    }

    /** Draw GG background without scatter points (for animation base) */
    function _drawGG_base() {
        if (!_state.allGGData || !_ggCtx) return;
        var w = _ggW(), h = _ggH();
        var ctx = _ggCtx;
        var pW = _ggPW(), pH = _ggPH();
        var axisMax = _getAxisMax();
        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, w, h);
        ctx.save();
        ctx.beginPath();
        ctx.rect(_ggPad.left, _ggPad.top, pW, pH);
        ctx.clip();
        // Grid
        ctx.strokeStyle = C.border || '#30363d';
        ctx.lineWidth = 0.5;
        var step = axisMax <= 0.3 ? 0.05 : axisMax <= 0.6 ? 0.1 : axisMax <= 1.2 ? 0.25 : 0.5;
        var gMin = -_state.baseAxisMax * 2, gMax = _state.baseAxisMax * 2;
        for (var g = Math.ceil(gMin / step) * step; g <= gMax; g += step) {
            var yy = _yToPixel(g);
            if (yy >= _ggPad.top && yy <= _ggPad.top + pH) {
                ctx.beginPath(); ctx.moveTo(_ggPad.left, yy); ctx.lineTo(_ggPad.left + pW, yy); ctx.stroke();
            }
            var xx = _xToPixel(g);
            if (xx >= _ggPad.left && xx <= _ggPad.left + pW) {
                ctx.beginPath(); ctx.moveTo(xx, _ggPad.top); ctx.lineTo(xx, _ggPad.top + pH); ctx.stroke();
            }
        }
        // Axes
        ctx.strokeStyle = C.textMuted || '#484f58';
        ctx.lineWidth = 1;
        var ox = _xToPixel(0), oy = _yToPixel(0);
        ctx.beginPath(); ctx.moveTo(ox, _ggPad.top); ctx.lineTo(ox, _ggPad.top + pH); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(_ggPad.left, oy); ctx.lineTo(_ggPad.left + pW, oy); ctx.stroke();
        // Friction circle
        var cx = _xToPixel(0), cy = _yToPixel(0);
        var rPx = axisMax > 0 ? (_state.frictionR / axisMax) * (pW / 2) : 0;
        if (rPx > 0) {
            ctx.strokeStyle = 'rgba(139, 148, 158, 0.8)';
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 4]);
            ctx.beginPath(); ctx.arc(cx, cy, rPx, 0, 2 * Math.PI); ctx.stroke();
            ctx.setLineDash([]);
        }
        ctx.restore();
    }

    function _setupAnimButton() {
        if (!_modeGroup) return;
        _animBtn = document.createElement('button');
        _animBtn.textContent = '\u25B6'; // play icon
        _animBtn.title = 'Animate GG trace over time';
        _animBtn.className = 'gg-mode-btn';
        _animBtn.style.cssText = 'margin-left:6px;padding:2px 8px;cursor:pointer;font-size:11px;border:1px solid rgba(148,148,148,0.3);border-radius:4px;background:transparent;color:#949494;';
        _modeGroup.appendChild(_animBtn);
        _lc.addListener(_animBtn, 'click', function () {
            if (_animPlaying) {
                _stopAnimation();
            } else {
                // Switch to single mode if not already
                if (_state.mode !== 'single') {
                    var btns = _modeGroup.querySelectorAll('.gg-mode-btn[data-mode]');
                    for (var j = 0; j < btns.length; j++) {
                        btns[j].classList.remove('active');
                        if (btns[j].getAttribute('data-mode') === 'single') btns[j].classList.add('active');
                    }
                    _state.mode = 'single';
                    _updateDropdownVisibility();
                }
                _ensureLapData(_state.primaryLap, function () { _startAnimation(); });
            }
        });
    }

    /* ── mode buttons ──────────────────────────── */
    function _setupModeButtons() {
        if (!_modeGroup) return;
        var btns = _modeGroup.querySelectorAll('.gg-mode-btn');
        for (var i = 0; i < btns.length; i++) {
            _lc.addListener(btns[i], 'click', function () {
                var mode = this.getAttribute('data-mode');
                if (!mode || mode === _state.mode) return;
                if (_animPlaying) _stopAnimation();
                /* Update active button */
                for (var j = 0; j < btns.length; j++) btns[j].classList.remove('active');
                this.classList.add('active');
                _state.mode = mode;
                _state.selectedIdx = null;
                _updateDropdownVisibility();
                _updateInfoBar(null);
                _drawAll();
            });
        }
    }

    function _updateDropdownVisibility() {
        if (_primaryLabel) _primaryLabel.style.display = (_state.mode !== 'all') ? '' : 'none';
        if (_compareLabel) _compareLabel.style.display = (_state.mode === 'compare') ? '' : 'none';
    }

    /* ── dropdowns ─────────────────────────────── */
    function _setupDropdowns() {
        if (_primarySelect) {
            _lc.addListener(_primarySelect, 'change', function () {
                _state.primaryLap = parseInt(this.value, 10);
                _state.selectedIdx = null;
                _ensureLapData(_state.primaryLap, function () { _drawAll(); });
            });
        }
        if (_compareSelect) {
            _lc.addListener(_compareSelect, 'change', function () {
                _state.compareLap = parseInt(this.value, 10);
                _drawAll();
            });
        }
    }

    function _populateDropdowns() {
        if (!_primarySelect || !_compareSelect) return;
        var T = window.TELEMETRY;
        if (!T || !T.gpsLaps) return;
        var laps = T.gpsLaps;
        var bestLap = T.bestLap;

        /* Clear */
        _primarySelect.textContent = '';
        _compareSelect.textContent = '';

        /* None option for compare */
        var noneOpt = document.createElement('option');
        noneOpt.value = '';
        noneOpt.textContent = '-- none --';
        _compareSelect.appendChild(noneOpt);

        for (var i = 0; i < laps.length; i++) {
            var ln = laps[i];
            var label = 'Lap ' + ln + (ln === bestLap ? ' (Best)' : '');

            var opt1 = document.createElement('option');
            opt1.value = String(ln);
            opt1.textContent = label;
            if (ln === _state.primaryLap) opt1.selected = true;
            _primarySelect.appendChild(opt1);

            var opt2 = document.createElement('option');
            opt2.value = String(ln);
            opt2.textContent = label;
            _compareSelect.appendChild(opt2);
        }
    }

    function _ensureLapData(lapNum, cb) {
        if (_state.lapDataCache[lapNum]) { cb(); return; }
        var url = '/api/session/' + encodeURIComponent(_sid) + '/gps/' + lapNum;
        FetchHelper.fetch(url).then(function (data) {
            if (data) {
                _state.lapDataCache[lapNum] = data;
                var _cKeys = Object.keys(_state.lapDataCache);
                if (_cKeys.length > MAX_LAP_CACHE) {
                    delete _state.lapDataCache[_cKeys[0]];
                }
            }
            cb();
        }).catch(function () { cb(); });
    }

    /* ── info bar (safe DOM methods) ───────────── */
    function _updateInfoBar(info) {
        if (!_infoBar) return;
        /* Clear existing children */
        while (_infoBar.firstChild) _infoBar.removeChild(_infoBar.firstChild);

        if (!info) {
            var hint = document.createElement('span');
            hint.className = 'text-muted text-xs';
            if (_state.mode === 'all') {
                hint.textContent = 'Switch to Single or Compare mode to click points';
            } else {
                hint.textContent = 'Click a point to see its track position';
            }
            _infoBar.appendChild(hint);
            return;
        }

        var parts = [
            { label: 'Lat', value: info.latG.toFixed(3) + 'G' },
            { label: 'Long', value: info.longG.toFixed(3) + 'G' },
            { label: 'Total', value: info.totalG.toFixed(3) + 'G' },
        ];
        if (info.speed !== null && info.speed !== undefined) {
            parts.push({ label: 'Speed', value: (info.speed * 3.6).toFixed(0) + ' km/h' });
        }
        if (info.distance !== null && info.distance !== undefined) {
            parts.push({ label: 'Dist', value: info.distance.toFixed(0) + 'm' });
        }
        if (info.quadrant) {
            parts.push({ label: 'Zone', value: info.quadrant });
        }

        for (var i = 0; i < parts.length; i++) {
            if (i > 0) {
                var sep = document.createElement('span');
                sep.textContent = ' | ';
                sep.style.opacity = '0.4';
                _infoBar.appendChild(sep);
            }
            var span = document.createElement('span');
            var lbl = document.createElement('span');
            lbl.className = 'text-muted';
            lbl.textContent = parts[i].label + ': ';
            var val = document.createElement('strong');
            val.textContent = parts[i].value;
            span.appendChild(lbl);
            span.appendChild(val);
            _infoBar.appendChild(span);
        }
    }

    function _getQuadrant(latG, longG) {
        var lat = latG > 0.05 ? 'Right' : latG < -0.05 ? 'Left' : '';
        var lon = longG > 0.05 ? 'Accel' : longG < -0.05 ? 'Brake' : '';
        if (lat && lon) return lon + ' + ' + lat;
        if (lat) return 'Turn ' + lat;
        if (lon) return lon;
        return 'Neutral';
    }

    /* ── stats ─────────────────────────────────── */
    function _updateStats() {
        if (!_statsEl) return;
        var mode = _state.mode;
        var count = 0;
        if (mode === 'all') {
            count = _state.allGGData ? _state.allGGData.accel_lat.length : 0;
        } else {
            var ld = _state.perLap ? _state.perLap[String(_state.primaryLap)] : null;
            count = ld ? ld.accel_lat.length : 0;
        }
        _statsEl.textContent = count + ' pts | Max: ' + _state.frictionR.toFixed(2) + 'G';
    }

    /* ── tooltip (safe DOM methods) ────────────── */
    function _showTooltip(mx, my, latG, longG, speed, distance) {
        if (!_tooltip) return;
        /* Clear existing children */
        while (_tooltip.firstChild) _tooltip.removeChild(_tooltip.firstChild);

        var mag = Math.sqrt(latG * latG + longG * longG);

        var items = [
            'Lat: ' + latG.toFixed(3) + 'G',
            'Long: ' + longG.toFixed(3) + 'G',
            'Total: ' + mag.toFixed(3) + 'G',
        ];
        if (speed !== null && speed !== undefined && isFinite(speed)) {
            items.push((speed * 3.6).toFixed(0) + ' km/h');
        }
        if (distance !== null && distance !== undefined && isFinite(distance)) {
            items.push(distance.toFixed(0) + 'm');
        }

        _tooltip.textContent = items.join(' | ');
        _tooltip.style.display = 'block';
        _tooltip.style.left = (mx + 12) + 'px';
        _tooltip.style.top = (my - 30) + 'px';
    }

    function _hideTooltip() {
        if (_tooltip) _tooltip.style.display = 'none';
    }

    /* ── events ────────────────────────────────── */
    function _setupGGEvents() {
        if (!_ggCanvas) return;
        _ggCanvas.style.cursor = 'crosshair';
        _ggCanvas.setAttribute('tabindex', '0');
        _ggCanvas.style.outline = 'none';

        /* Wheel zoom */
        _lc.addListener(_ggCanvas, 'wheel', function (e) {
            e.preventDefault();
            var rect = _ggCanvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;
            var gxBefore = _pixelToGX(mx);
            var gyBefore = _pixelToGY(my);
            var delta = e.deltaY > 0 ? 0.85 : 1.18;
            _state.zoomLevel = Math.max(0.5, Math.min(10, _state.zoomLevel * delta));
            var gxAfter = _pixelToGX(mx);
            var gyAfter = _pixelToGY(my);
            _state.panX += gxBefore - gxAfter;
            _state.panY += gyBefore - gyAfter;
            _drawGG();
        }, { passive: false });

        /* Drag (pan) + click (select) */
        _lc.addListener(_ggCanvas, 'mousedown', function (e) {
            _isDragging = true;
            _dragMoved = false;
            _dragStartX = e.clientX;
            _dragStartY = e.clientY;
            _dragStartPanX = _state.panX;
            _dragStartPanY = _state.panY;
            _ggCanvas.style.cursor = 'grabbing';
        });

        _lc.addListener(window, 'mousemove', function (e) {
            if (!_isDragging) return;
            var dx = e.clientX - _dragStartX;
            var dy = e.clientY - _dragStartY;
            if (Math.abs(dx) > 3 || Math.abs(dy) > 3) _dragMoved = true;
            var axisMax = _getAxisMax();
            _state.panX = _dragStartPanX - dx / _ggPW() * (2 * axisMax);
            _state.panY = _dragStartPanY + dy / _ggPH() * (2 * axisMax);
            _drawGG();
        });

        _lc.addListener(window, 'mouseup', function (e) {
            if (!_isDragging) return;
            _isDragging = false;
            _ggCanvas.style.cursor = 'crosshair';
            if (!_dragMoved) _handleGGClick(e);
        });

        /* Double-click reset */
        _lc.addListener(_ggCanvas, 'dblclick', function () {
            _state.zoomLevel = 1.0;
            _state.panX = 0;
            _state.panY = 0;
            _drawAll();
        });

        /* Hover tooltip */
        _lc.addListener(_ggCanvas, 'mousemove', function (e) {
            if (_isDragging) { _hideTooltip(); return; }
            var rect = _ggCanvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;
            if (mx < _ggPad.left || mx > _ggPad.left + _ggPW() ||
                my < _ggPad.top || my > _ggPad.top + _ggPH()) {
                _hideTooltip(); return;
            }

            var gx = _pixelToGX(mx), gy = _pixelToGY(my);
            var aLat, aLong, speeds, distances;

            if (_state.mode === 'all') {
                aLat = _state.allGGData.accel_lat;
                aLong = _state.allGGData.accel_long;
            } else {
                var lk = String(_state.primaryLap);
                if (!_state.perLap) { _hideTooltip(); return; }
                var ld = _state.perLap[lk];
                if (!ld) { _hideTooltip(); return; }
                aLat = ld.accel_lat;
                aLong = ld.accel_long;
                var gps = _state.lapDataCache[_state.primaryLap];
                if (gps) { speeds = gps.speeds; distances = gps.distances; }
            }

            /* Find nearest point */
            var bestIdx = -1, bestDist = Infinity;
            for (var i = 0; i < aLat.length; i++) {
                if (aLat[i] === null || aLong[i] === null) continue;
                var ddx = aLat[i] - gx, ddy = aLong[i] - gy;
                var d2 = ddx * ddx + ddy * ddy;
                if (d2 < bestDist) { bestDist = d2; bestIdx = i; }
            }

            if (bestIdx >= 0 && bestDist < 0.05) {
                var spd = (speeds && bestIdx < speeds.length) ? speeds[bestIdx] : null;
                var dist = (distances && bestIdx < distances.length) ? distances[bestIdx] : null;
                _showTooltip(mx, my, aLat[bestIdx], aLong[bestIdx], spd, dist);
            } else {
                _hideTooltip();
            }
        });

        _lc.addListener(_ggCanvas, 'mouseleave', function () { _hideTooltip(); });

        /* Keyboard */
        _lc.addListener(_ggCanvas, 'keydown', function (e) {
            var axisMax = _getAxisMax();
            var panStep = axisMax * 0.15;
            var handled = true;
            switch (e.key) {
                case '+': case '=': _state.zoomLevel = Math.min(10, _state.zoomLevel * 1.18); break;
                case '-': case '_': _state.zoomLevel = Math.max(0.5, _state.zoomLevel * 0.85); break;
                case 'ArrowLeft': _state.panX -= panStep; break;
                case 'ArrowRight': _state.panX += panStep; break;
                case 'ArrowUp': _state.panY += panStep; break;
                case 'ArrowDown': _state.panY -= panStep; break;
                case '0': case 'Escape':
                    _state.zoomLevel = 1.0; _state.panX = 0; _state.panY = 0;
                    _state.selectedIdx = null; _updateInfoBar(null);
                    break;
                case '1': _activateMode('all'); break;
                case '2': _activateMode('single'); break;
                case '3': _activateMode('compare'); break;
                default: handled = false; break;
            }
            if (handled) { e.preventDefault(); _drawAll(); }
        });

        /* Resize */
        var _resizeTimer;
        _lc.addListener(window, 'resize', function () {
            clearTimeout(_resizeTimer);
            _resizeTimer = _lc.addTimer(function () {
                if (!_state.allGGData) return;
                _sizeCanvases();
                _drawAll();
            }, 150);
        });
    }

    /* Click handler — select nearest point, map to GPS */
    function _handleGGClick(e) {
        if (_state.mode === 'all') return; /* no GPS index in aggregated data */

        var rect = _ggCanvas.getBoundingClientRect();
        var mx = e.clientX - rect.left;
        var my = e.clientY - rect.top;
        if (mx < _ggPad.left || mx > _ggPad.left + _ggPW() ||
            my < _ggPad.top || my > _ggPad.top + _ggPH()) return;

        var gx = _pixelToGX(mx), gy = _pixelToGY(my);
        var lapKey = String(_state.primaryLap);
        if (!_state.perLap) return;
        var lapGG = _state.perLap[lapKey];
        if (!lapGG) return;

        var aLat = lapGG.accel_lat, aLong = lapGG.accel_long;
        var bestIdx = -1, bestDist = Infinity;
        for (var i = 0; i < aLat.length; i++) {
            if (aLat[i] === null || aLong[i] === null) continue;
            var dx = aLat[i] - gx, dy = aLong[i] - gy;
            var d = dx * dx + dy * dy;
            if (d < bestDist) { bestDist = d; bestIdx = i; }
        }

        if (bestIdx < 0 || bestDist > 0.1) {
            _state.selectedIdx = null;
            _updateInfoBar(null);
            _drawAll();
            return;
        }

        _state.selectedIdx = bestIdx;

        /* Build info */
        var latG = aLat[bestIdx];
        var longG = aLong[bestIdx];
        var totalG = Math.sqrt(latG * latG + longG * longG);
        var gps = _state.lapDataCache[_state.primaryLap];
        var speed = (gps && gps.speeds && bestIdx < gps.speeds.length) ? gps.speeds[bestIdx] : null;
        var distance = (gps && gps.distances && bestIdx < gps.distances.length) ? gps.distances[bestIdx] : null;

        _updateInfoBar({
            latG: latG, longG: longG, totalG: totalG,
            speed: speed, distance: distance,
            quadrant: _getQuadrant(latG, longG),
        });

        _drawAll();
    }

    function _activateMode(mode) {
        if (!_modeGroup) return;
        var btns = _modeGroup.querySelectorAll('.gg-mode-btn');
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].getAttribute('data-mode') === mode) {
                btns[i].classList.add('active');
            } else {
                btns[i].classList.remove('active');
            }
        }
        _state.mode = mode;
        _state.selectedIdx = null;
        _updateDropdownVisibility();
        _updateInfoBar(null);
    }

    function destroy() {
        _lc.destroyAll();
        _state.lapDataCache = {};
        _state.allGGData = null;
        _state.perLap = null;
        _state.selectedIdx = null;
        if (_ggCanvas) { _ggCanvas.width = 0; _ggCanvas.height = 0; }
        if (_mapCanvas) { _mapCanvas.width = 0; _mapCanvas.height = 0; }
    }

    window.ModuleManager.register('gg_explorer', {
        init: function () { /* auto-inits via tab:activate */ },
        destroy: destroy
    });

})();
