/**
 * visualize.js — Full visualization workspace controller.
 *
 * Reads window.VIZ_DATA and orchestrates:
 *   - VizMap:       Leaflet GPS map with all laps + sector markers
 *   - VizSpeed:     Canvas speed-vs-distance chart with sector lines
 *   - VizGG:        Canvas G-G scatter diagram per selected laps
 *   - VizSidebar:   Lap checkboxes, sector table, quick stats
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};
    var lapColor = window.Theme ? window.Theme.lapColor : function (i) {
        var fallback = [
            '#ff6b35', '#3b82f6', '#10b981', '#f59e0b', '#ef4444',
            '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1',
            '#84cc16', '#06b6d4', '#e11d48', '#a855f7', '#0ea5e9',
            '#d946ef', '#22d3ee', '#facc15', '#fb923c', '#4ade80',
        ];
        return fallback[i % fallback.length];
    };

    function speedToColor(speed, minSpd, maxSpd) {
        var t = maxSpd > minSpd ? (speed - minSpd) / (maxSpd - minSpd) : 0.5;
        t = Math.max(0, Math.min(1, t));
        var r, g, b;
        if (t < 0.25) { r = 0; g = Math.round(255 * (t / 0.25)); b = 255; }
        else if (t < 0.5) { r = 0; g = 255; b = Math.round(255 * (1 - (t - 0.25) / 0.25)); }
        else if (t < 0.75) { r = Math.round(255 * ((t - 0.5) / 0.25)); g = 255; b = 0; }
        else { r = 255; g = Math.round(255 * (1 - (t - 0.75) / 0.25)); b = 0; }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    // ── State ────────────────────────────────────────
    var V = window.VIZ_DATA;
    if (!V || !V.sessionId) return;

    var selectedLaps = new Set();           // set of lap numbers currently checked
    var gpsCache = {};                      // { lapNum: { latitudes, longitudes, distances, speeds, accel_lat, accel_long } }
    var deltaCache = {};                    // { "lapA-lapB": { distances, time_delta } }
    var sectorBoundaries = [];              // array of distance_m values
    var sectorMarkers = [];                 // Leaflet markers for sectors
    var refLineData = null;                 // reference line { latitudes, longitudes, distances }
    var refLineLayer = null;                // Leaflet polyline

    // ── Shared hover helpers ────────────────────────────
    var _hoverDist = null;

    function broadcastHover(distM, source) {
        _hoverDist = distM;
        if (distM === null) {
            if (source !== 'speed') VizSpeed.clearCrosshair();
            if (source !== 'gg') VizGG.clearHighlight();
            return;
        }
        if (source !== 'speed') VizSpeed.showCrosshair(distM);
        if (source !== 'gg') VizGG.highlightAtDistance(distM);
        VizMap.moveMarkerToDistance(distM);
    }

    function closestDistIdx(dists, target) {
        if (!dists || dists.length === 0) return -1;
        var lo = 0, hi = dists.length - 1;
        while (lo < hi) {
            var mid = (lo + hi) >> 1;
            if (dists[mid] < target) lo = mid + 1; else hi = mid;
        }
        if (lo > 0 && Math.abs(dists[lo - 1] - target) < Math.abs(dists[lo] - target)) return lo - 1;
        return lo;
    }

    function interpValue(arr, dists, targetDist) {
        if (!arr || !dists || dists.length === 0) return null;
        if (targetDist <= dists[0]) return arr[0];
        if (targetDist >= dists[dists.length - 1]) return arr[arr.length - 1];
        var lo = 0, hi = dists.length - 1;
        while (lo < hi - 1) {
            var mid = (lo + hi) >> 1;
            if (dists[mid] <= targetDist) lo = mid; else hi = mid;
        }
        var t = (targetDist - dists[lo]) / (dists[hi] - dists[lo] || 1);
        var a = arr[lo], b = arr[hi];
        if (a === null || b === null) return a !== null ? a : b;
        return a + (b - a) * t;
    }

    // ── Init ─────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        VizSidebar.init();
        VizMap.init();
        VizSpeed.init();
        VizGG.init();

        // Pre-load GPS data for all laps
        var promises = V.gpsLaps.map(function (lapNum) {
            return loadGps(lapNum);
        });
        Promise.all(promises).then(function () {
            // Default: select best lap
            if (V.bestLap && gpsCache[V.bestLap]) {
                selectedLaps.add(V.bestLap);
            } else if (V.gpsLaps.length > 0) {
                selectedLaps.add(V.gpsLaps[0]);
            }
            VizSidebar.syncCheckboxes();
            onSelectionChanged();

            // Load reference line
            loadRefLine();

            // Load existing sectors
            loadSectors();
        });

        // Responsive resize — redraw canvas charts when window resizes
        var _vizResizeTimer = null;
        window.addEventListener('resize', function () {
            clearTimeout(_vizResizeTimer);
            _vizResizeTimer = setTimeout(function () {
                VizSpeed.draw();
                VizGG.draw();
                // Leaflet map handles its own resize via invalidateSize
                if (VizMap.invalidateSize) VizMap.invalidateSize();
            }, 200);
        });
    });

    function loadGps(lapNum) {
        if (gpsCache[lapNum]) return Promise.resolve(gpsCache[lapNum]);
        return FetchHelper.fetch('/api/session/' + encodeURIComponent(V.sessionId) + '/gps/' + lapNum)
            .then(function (data) {
                if (data) gpsCache[lapNum] = data;
                return data;
            })
            .catch(function (err) { console.warn('GPS load failed for lap', lapNum, err); return null; });
    }

    function loadRefLine() {
        FetchHelper.fetch('/api/session/' + encodeURIComponent(V.sessionId) + '/reference_line')
            .then(function (data) {
                if (data && data.latitudes) {
                    refLineData = data;
                    VizMap.drawRefLine(data);
                }
            })
            .catch(function (err) { console.warn('Reference line load failed:', err); });
    }

    function loadSectors() {
        FetchHelper.fetch('/api/session/' + encodeURIComponent(V.sessionId) + '/sectors')
            .then(function (data) {
                sectorBoundaries = (data.sectors || []).map(function (s) { return s.distance_m; });
                VizMap.drawSectorMarkers(data.sectors || []);
                VizSpeed.draw();
                loadSectorTimes();
            })
            .catch(function (err) { console.warn('Sectors load failed:', err); });
    }

    function loadSectorTimes() {
        if (sectorBoundaries.length === 0) {
            VizSidebar.renderSectorTable(null);
            return;
        }
        FetchHelper.fetch('/api/session/' + encodeURIComponent(V.sessionId) + '/sector_times')
            .then(function (data) {
                VizSidebar.renderSectorTable(data);
            })
            .catch(function (err) { console.warn('Sector times load failed:', err); });
    }

    function onSelectionChanged() {
        VizMap.updateHighlights();
        VizSpeed.draw();
        VizGG.draw();
        VizSidebar.updateStats();
    }

    // ═══════════════════════════════════════════════════
    // VizMap — Leaflet GPS map
    // ═══════════════════════════════════════════════════
    var VizMap = (function () {
        var map = null;
        var allLapLayers = {};   // { lapNum: L.layerGroup }
        var highlightLayers = {};
        var posMarker = null;

        function init() {
            var el = document.getElementById('viz-map');
            if (!el) return;
            map = L.map(el, { zoomControl: true });
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19, attribution: '&copy; OpenStreetMap',
            }).addTo(map);

            // Position marker for hover sync
            posMarker = L.circleMarker([0, 0], {
                radius: 10, color: '#ffffff', fillColor: C.accent || '#ff6b35',
                fillOpacity: 1, weight: 3,
            });
        }

        function drawAllLaps() {
            // Remove existing
            Object.keys(allLapLayers).forEach(function (k) {
                map.removeLayer(allLapLayers[k]);
            });
            allLapLayers = {};

            var bounds = [];
            V.gpsLaps.forEach(function (lapNum) {
                var d = gpsCache[lapNum];
                if (!d || !d.latitudes || d.latitudes.length < 2) return;

                var coords = [];
                for (var i = 0; i < d.latitudes.length; i++) {
                    if (d.latitudes[i] !== null && d.longitudes[i] !== null) {
                        coords.push([d.latitudes[i], d.longitudes[i]]);
                    }
                }
                if (coords.length < 2) return;

                var layer = L.polyline(coords, {
                    color: C.textMuted || '#484f58', weight: 2, opacity: 0.15,
                }).addTo(map);
                allLapLayers[lapNum] = layer;
                bounds = bounds.concat(coords);
            });

            if (bounds.length > 0) {
                map.fitBounds(bounds, { padding: [30, 30] });
            }
        }

        function updateHighlights() {
            // Remove old highlights
            Object.keys(highlightLayers).forEach(function (k) {
                map.removeLayer(highlightLayers[k]);
            });
            highlightLayers = {};

            // Reset all to low opacity
            Object.keys(allLapLayers).forEach(function (k) {
                allLapLayers[k].setStyle({ opacity: 0.12, weight: 2, color: C.textMuted || '#484f58' });
            });

            // Highlighted laps with speed coloring
            var idx = 0;
            selectedLaps.forEach(function (lapNum) {
                var d = gpsCache[lapNum];
                if (!d || !d.latitudes || d.latitudes.length < 2) return;

                var col = lapColor(idx);

                // Speed-colored segments
                var group = L.layerGroup();
                var spds = d.speeds || [];
                var validSpeeds = spds.filter(function (s) { return s !== null && isFinite(s); });
                var minSpd = validSpeeds.length ? Math.min.apply(null, validSpeeds) : 0;
                var maxSpd = validSpeeds.length ? Math.max.apply(null, validSpeeds) : 1;

                for (var i = 0; i < d.latitudes.length - 1; i++) {
                    if (d.latitudes[i] === null || d.latitudes[i + 1] === null) continue;
                    var segColor = speedToColor(spds[i] || 0, minSpd, maxSpd);
                    L.polyline(
                        [[d.latitudes[i], d.longitudes[i]], [d.latitudes[i + 1], d.longitudes[i + 1]]],
                        { color: segColor, weight: 2, opacity: 0.9 }
                    ).addTo(group);
                }
                group.addTo(map);
                highlightLayers[lapNum] = group;

                // Hide the low-opacity version
                if (allLapLayers[lapNum]) {
                    allLapLayers[lapNum].setStyle({ opacity: 0 });
                }

                idx++;
            });

            // Add position marker
            if (posMarker) {
                posMarker.addTo(map);
            }
        }

        function drawRefLine(data) {
            if (refLineLayer) map.removeLayer(refLineLayer);
            var coords = [];
            for (var i = 0; i < data.latitudes.length; i++) {
                if (data.latitudes[i] !== null && data.longitudes[i] !== null) {
                    coords.push([data.latitudes[i], data.longitudes[i]]);
                }
            }
            refLineLayer = L.polyline(coords, {
                color: C.textSecondary || '#8b949e', weight: 3, opacity: 0.6, dashArray: '8,6',
            }).addTo(map);

            // Click on ref line to add sector
            refLineLayer.on('click', function (e) {
                var idx = closestLatLonIndex(data.latitudes, data.longitudes, e.latlng.lat, e.latlng.lng);
                if (idx < 0) return;
                var dist = data.distances ? data.distances[idx] : 0;
                var lat = data.latitudes[idx];
                var lon = data.longitudes[idx];

                FetchHelper.fetch('/api/session/' + encodeURIComponent(V.sessionId) + '/sectors', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ distance_m: dist, latitude: lat, longitude: lon }),
                })
                .then(function (result) {
                    sectorBoundaries = (result.sectors || []).map(function (s) { return s.distance_m; });
                    drawSectorMarkers(result.sectors || []);
                    VizSpeed.draw();
                    loadSectorTimes();
                })
                .catch(function () {
                    if (window.Toast) Toast.show('Failed to create sector', 'error');
                });
            });
        }

        function drawSectorMarkers(sectors) {
            // Remove old markers
            sectorMarkers.forEach(function (m) { map.removeLayer(m); });
            sectorMarkers = [];

            sectors.forEach(function (s) {
                if (s.latitude === null || s.longitude === null) return;
                var marker = L.marker([s.latitude, s.longitude], {
                    icon: L.divIcon({
                        className: '',
                        html: '<span class="sector-marker-label">' + (s.label || 'S?') + '</span>',
                        iconSize: [40, 20],
                        iconAnchor: [20, 10],
                    }),
                    draggable: true,
                });
                marker.sectorId = s.id;
                marker.sectorDistance = s.distance_m;

                // Context menu to delete
                marker.on('contextmenu', function (e) {
                    L.DomEvent.stopPropagation(e);
                    if (confirm('Remove sector ' + (s.label || '') + '?')) {
                        FetchHelper.fetch('/api/session/' + encodeURIComponent(V.sessionId) + '/sectors/' + s.id, {
                            method: 'DELETE',
                        })
                        .then(function (result) {
                            sectorBoundaries = (result.sectors || []).map(function (sec) { return sec.distance_m; });
                            drawSectorMarkers(result.sectors || []);
                            VizSpeed.draw();
                            loadSectorTimes();
                        });
                    }
                });

                marker.addTo(map);
                sectorMarkers.push(marker);
            });
        }

        function moveMarkerToDistance(distM) {
            if (!posMarker) return;
            // Find first selected lap with data
            var lapNum = null;
            selectedLaps.forEach(function (ln) { if (!lapNum && gpsCache[ln]) lapNum = ln; });
            if (!lapNum) return;
            var d = gpsCache[lapNum];
            if (!d || !d.distances) return;

            var idx = closestIndex(d.distances, distM);
            if (idx >= 0 && d.latitudes[idx] !== null) {
                posMarker.setLatLng([d.latitudes[idx], d.longitudes[idx]]);
            }
        }

        function closestIndex(arr, target) {
            if (!arr || arr.length === 0) return -1;
            var lo = 0, hi = arr.length - 1;
            while (lo < hi) {
                var mid = (lo + hi) >> 1;
                if (arr[mid] < target) lo = mid + 1; else hi = mid;
            }
            if (lo > 0 && Math.abs(arr[lo - 1] - target) < Math.abs(arr[lo] - target)) return lo - 1;
            return lo;
        }

        function closestLatLonIndex(lats, lons, lat, lon) {
            var bestIdx = -1, bestDist = Infinity;
            for (var i = 0; i < lats.length; i++) {
                if (lats[i] === null) continue;
                var dlat = lats[i] - lat, dlon = lons[i] - lon;
                var d2 = dlat * dlat + dlon * dlon;
                if (d2 < bestDist) { bestDist = d2; bestIdx = i; }
            }
            return bestIdx;
        }

        return {
            init: init,
            drawAllLaps: drawAllLaps,
            updateHighlights: function () {
                // Ensure all laps drawn first
                if (Object.keys(allLapLayers).length === 0) drawAllLaps();
                updateHighlights();
            },
            drawRefLine: drawRefLine,
            drawSectorMarkers: drawSectorMarkers,
            moveMarkerToDistance: moveMarkerToDistance,
            invalidateSize: function () {
                if (map) map.invalidateSize();
            },
        };
    })();

    // ═══════════════════════════════════════════════════
    // VizSpeed — Canvas speed chart
    // ═══════════════════════════════════════════════════
    var VizSpeed = (function () {
        var canvas, ctx;
        var _pendingDelta = null; // track in-flight delta fetch
        var _chartImage = null;   // saved chart bitmap for crosshair overlay
        var _drawP = null;        // saved draw params {pad,pW,pH,w,h,maxDist,minKmh,maxKmh}

        function init() {
            canvas = document.getElementById('viz-speed-chart');
            if (!canvas) return;
            ctx = canvas.getContext('2d');
            canvas.__redraw = function() { draw(); };

            canvas.addEventListener('mousemove', function (e) {
                var rect = canvas.getBoundingClientRect();
                var x = e.clientX - rect.left;
                var dpr = window.devicePixelRatio || 1;
                x /= 1; // Already in CSS pixels
                handleHover(x);
            });
            canvas.addEventListener('mouseleave', function () {
                broadcastHover(null, 'speed');
                if (_chartImage && ctx) ctx.putImageData(_chartImage, 0, 0);
            });

            // Touch support for mobile — reuse the same hover logic as mousemove
            canvas.addEventListener('touchstart', function (e) {
                if (e.touches.length === 1) {
                    var rect = canvas.getBoundingClientRect();
                    var x = e.touches[0].clientX - rect.left;
                    handleHover(x);
                }
            }, { passive: true });
            canvas.addEventListener('touchmove', function (e) {
                if (e.touches.length === 1) {
                    var rect = canvas.getBoundingClientRect();
                    var x = e.touches[0].clientX - rect.left;
                    handleHover(x);
                }
            }, { passive: true });
        }

        function draw() {
            if (!canvas || !ctx) return;
            var sel = Array.from(selectedLaps);
            var showDelta = sel.length === 2;

            // Wider right padding when showing time-delta right Y-axis
            var pad = { top: 20, right: showDelta ? 60 : 20, bottom: 35, left: 55 };

            var dpr = window.devicePixelRatio || 1;
            canvas.style.width = '';
            canvas.style.height = '';
            var w = canvas.clientWidth || canvas.parentElement.clientWidth || 700;
            var h = canvas.clientHeight || canvas.parentElement.clientHeight || 400;
            canvas.width = w * dpr;
            canvas.height = h * dpr;
            canvas.style.width = w + 'px';
            canvas.style.height = h + 'px';
            ctx.scale(dpr, dpr);

            var pW = w - pad.left - pad.right;
            var pH = h - pad.top - pad.bottom;

            // Collect data ranges
            var maxDist = 0, minSpd = Infinity, maxSpd = 0;
            selectedLaps.forEach(function (lapNum) {
                var d = gpsCache[lapNum];
                if (!d || !d.distances || !d.speeds) return;
                var dMax = d.distances[d.distances.length - 1] || 0;
                if (dMax > maxDist) maxDist = dMax;
                d.speeds.forEach(function (s) {
                    if (s !== null && isFinite(s)) {
                        if (s < minSpd) minSpd = s;
                        if (s > maxSpd) maxSpd = s;
                    }
                });
            });

            if (maxDist === 0 || maxSpd === 0) {
                ctx.fillStyle = C.bgCard || '#1a1f2e';
                ctx.fillRect(0, 0, w, h);
                ctx.fillStyle = C.textSecondary || '#8b949e';
                ctx.font = '13px -apple-system, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('Select laps to view speed trace', w / 2, h / 2);
                return;
            }

            // Convert to km/h for display
            var minKmh = minSpd * 3.6 * 0.95;
            var maxKmh = maxSpd * 3.6 * 1.05;

            function xToP(d) { return pad.left + (d / maxDist) * pW; }
            function yToP(kmh) { return pad.top + pH - (kmh - minKmh) / (maxKmh - minKmh) * pH; }

            // Background
            ctx.fillStyle = C.bgCard || '#1a1f2e';
            ctx.fillRect(0, 0, w, h);

            // Grid
            ctx.strokeStyle = C.border || '#30363d';
            ctx.lineWidth = 0.5;
            var ySteps = 5;
            for (var i = 0; i <= ySteps; i++) {
                var yv = minKmh + (maxKmh - minKmh) * (i / ySteps);
                var yp = yToP(yv);
                ctx.beginPath(); ctx.moveTo(pad.left, yp); ctx.lineTo(w - pad.right, yp); ctx.stroke();
                ctx.fillStyle = C.textSecondary || '#8b949e';
                ctx.font = '10px -apple-system, sans-serif';
                ctx.textAlign = 'right';
                ctx.textBaseline = 'middle';
                ctx.fillText(yv.toFixed(0), pad.left - 6, yp);
            }

            // X axis labels
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            var xSteps = 5;
            for (var i = 0; i <= xSteps; i++) {
                var xd = maxDist * (i / xSteps);
                ctx.fillText(xd.toFixed(0) + 'm', xToP(xd), pad.top + pH + 6);
            }

            // Sector boundary lines
            ctx.strokeStyle = 'rgba(255, 107, 53, 0.5)';
            ctx.lineWidth = 1;
            ctx.setLineDash([6, 4]);
            sectorBoundaries.forEach(function (dist) {
                var sx = xToP(dist);
                ctx.beginPath(); ctx.moveTo(sx, pad.top); ctx.lineTo(sx, pad.top + pH); ctx.stroke();
            });
            ctx.setLineDash([]);

            // Draw speed traces
            var idx = 0;
            selectedLaps.forEach(function (lapNum) {
                var d = gpsCache[lapNum];
                if (!d || !d.distances || !d.speeds) return;
                var col = lapColor(idx);
                ctx.strokeStyle = col;
                ctx.lineWidth = 2;
                ctx.beginPath();
                var started = false;
                for (var i = 0; i < d.distances.length; i++) {
                    if (d.distances[i] === null || d.speeds[i] === null) continue;
                    var x = xToP(d.distances[i]);
                    var y = yToP(d.speeds[i] * 3.6);
                    if (!started) { ctx.moveTo(x, y); started = true; }
                    else ctx.lineTo(x, y);
                }
                ctx.stroke();
                idx++;
            });

            // ── Time delta overlay (when exactly 2 laps selected) ──
            if (showDelta) {
                var lapA = sel[0], lapB = sel[1];
                var deltaKey = lapA + '-' + lapB;
                var cached = deltaCache[deltaKey];
                if (cached) {
                    _drawTimeDelta(ctx, cached, pad, pW, pH, w, h, lapA, lapB);
                } else {
                    // Fetch delta data asynchronously, then redraw
                    var fetchKey = lapA + '-' + lapB;
                    if (_pendingDelta !== fetchKey) {
                        _pendingDelta = fetchKey;
                        FetchHelper.fetch('/api/session/' + encodeURIComponent(V.sessionId) + '/delta?lap_a=' + lapA + '&lap_b=' + lapB)
                            .then(function (data) {
                                if (data && data.distances) {
                                    deltaCache[deltaKey] = data;
                                    _pendingDelta = null;
                                    draw(); // re-draw with delta data
                                }
                            })
                            .catch(function () { _pendingDelta = null; });
                    }
                }
            }

            // Title
            ctx.fillStyle = C.textPrimary || '#e6edf3';
            ctx.font = 'bold 13px -apple-system, sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'top';
            ctx.fillText('Speed (km/h)', pad.left, 4);

            // Lap legend (top right) — truncate when too many laps
            var legX = w - pad.right - 10;
            var legY = 6;
            ctx.font = '10px -apple-system, sans-serif';
            var maxLegEntries = Math.floor((h - pad.top - pad.bottom - 20) / 15);
            var lapArr = sel;
            var showN = Math.min(lapArr.length, maxLegEntries);
            for (var li = 0; li < showN; li++) {
                var col = lapColor(li);
                ctx.fillStyle = col;
                ctx.fillRect(legX - 50, legY + li * 15, 10, 10);
                ctx.fillStyle = C.textSecondary || '#8b949e';
                ctx.textAlign = 'right';
                ctx.fillText('Lap ' + lapArr[li], legX, legY + li * 15 + 9);
            }
            if (lapArr.length > showN) {
                ctx.fillStyle = C.textMuted || '#484f58';
                ctx.textAlign = 'right';
                ctx.fillText('+ ' + (lapArr.length - showN) + ' more', legX, legY + showN * 15 + 9);
            }
            // Delta legend entry
            if (showDelta && deltaCache[sel[0] + '-' + sel[1]]) {
                var dLegY = legY + Math.min(lapArr.length, showN) * 15 + 4;
                ctx.strokeStyle = '#10b981';
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 3]);
                ctx.beginPath();
                ctx.moveTo(legX - 50, dLegY + 5);
                ctx.lineTo(legX - 38, dLegY + 5);
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.fillStyle = '#10b981';
                ctx.textAlign = 'right';
                ctx.fillText('Time Δ (s)', legX, dLegY + 9);
            }

            // Save chart for crosshair overlay
            _drawP = { pad: pad, pW: pW, pH: pH, w: w, h: h, maxDist: maxDist, minKmh: minKmh, maxKmh: maxKmh };
            _chartImage = ctx.getImageData(0, 0, canvas.width, canvas.height);
        }

        /**
         * Draw the time-delta line with a right Y-axis on the speed chart.
         * Positive = lapA ahead (faster cumulative time), negative = lapB ahead.
         */
        function _drawTimeDelta(ctx, data, pad, pW, pH, w, h, lapA, lapB) {
            var dists = data.distances;
            var deltas = data.time_delta;
            if (!dists || !deltas || dists.length === 0) return;

            var maxDist = dists[dists.length - 1] || 1;

            // Find time delta range (symmetric around zero)
            var maxAbs = 0;
            for (var i = 0; i < deltas.length; i++) {
                var a = Math.abs(deltas[i]);
                if (a > maxAbs) maxAbs = a;
            }
            if (maxAbs < 0.01) maxAbs = 0.1;
            maxAbs = Math.ceil(maxAbs * 10) / 10; // round up to 0.1s

            function xToP(d) { return pad.left + (d / maxDist) * pW; }
            function yDelta(v) {
                return pad.top + pH / 2 - (v / maxAbs) * (pH / 2 - 5);
            }

            // Zero line
            ctx.strokeStyle = 'rgba(16, 185, 129, 0.3)';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(pad.left, yDelta(0));
            ctx.lineTo(pad.left + pW, yDelta(0));
            ctx.stroke();
            ctx.setLineDash([]);

            // Shaded fill — green above zero (lapA faster), red below
            ctx.save();
            ctx.beginPath();
            ctx.rect(pad.left, pad.top, pW, pH);
            ctx.clip();

            // Green fill (positive area — lapA faster)
            ctx.beginPath();
            ctx.moveTo(xToP(dists[0]), yDelta(0));
            for (var i = 0; i < dists.length; i++) {
                var x = xToP(dists[i]);
                var y = yDelta(Math.max(0, deltas[i]));
                ctx.lineTo(x, y);
            }
            ctx.lineTo(xToP(dists[dists.length - 1]), yDelta(0));
            ctx.closePath();
            ctx.fillStyle = 'rgba(16, 185, 129, 0.08)';
            ctx.fill();

            // Red fill (negative area — lapB faster)
            ctx.beginPath();
            ctx.moveTo(xToP(dists[0]), yDelta(0));
            for (var i = 0; i < dists.length; i++) {
                var x = xToP(dists[i]);
                var y = yDelta(Math.min(0, deltas[i]));
                ctx.lineTo(x, y);
            }
            ctx.lineTo(xToP(dists[dists.length - 1]), yDelta(0));
            ctx.closePath();
            ctx.fillStyle = 'rgba(239, 68, 68, 0.08)';
            ctx.fill();

            // Delta line
            ctx.strokeStyle = '#10b981';
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 3]);
            ctx.beginPath();
            for (var i = 0; i < dists.length; i++) {
                var x = xToP(dists[i]);
                var y = yDelta(deltas[i]);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.restore();

            // Right Y-axis labels for time delta
            ctx.fillStyle = '#10b981';
            ctx.font = '10px -apple-system, sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            var rightX = pad.left + pW + 6;
            ctx.fillText('+' + maxAbs.toFixed(1) + 's', rightX, yDelta(maxAbs));
            ctx.fillText('0s', rightX, yDelta(0));
            ctx.fillText('-' + maxAbs.toFixed(1) + 's', rightX, yDelta(-maxAbs));

            // Right Y-axis tick marks
            ctx.strokeStyle = '#10b981';
            ctx.lineWidth = 1;
            var tickX = pad.left + pW;
            ctx.beginPath();
            ctx.moveTo(tickX, yDelta(maxAbs)); ctx.lineTo(tickX + 4, yDelta(maxAbs));
            ctx.moveTo(tickX, yDelta(0)); ctx.lineTo(tickX + 4, yDelta(0));
            ctx.moveTo(tickX, yDelta(-maxAbs)); ctx.lineTo(tickX + 4, yDelta(-maxAbs));
            ctx.stroke();

            // Final delta value annotation
            var finalDelta = deltas[deltas.length - 1];
            if (Math.abs(finalDelta) > 0.001) {
                var sign = finalDelta > 0 ? '+' : '';
                var annotation = 'Lap ' + lapA + ' ' + sign + finalDelta.toFixed(3) + 's';
                ctx.fillStyle = finalDelta > 0 ? 'rgba(239, 68, 68, 0.9)' : 'rgba(16, 185, 129, 0.9)';
                ctx.font = 'bold 11px -apple-system, sans-serif';
                ctx.textAlign = 'right';
                ctx.textBaseline = 'bottom';
                ctx.fillText(annotation, pad.left + pW, yDelta(finalDelta) - 4);
            }
        }

        function handleHover(px) {
            if (!canvas || !_drawP) return;
            var p = _drawP;
            var frac = (px - p.pad.left) / p.pW;
            if (frac < 0 || frac > 1) return;
            var distM = frac * p.maxDist;
            broadcastHover(distM, 'speed');
            _drawCrosshair(distM);
        }

        function _drawCrosshair(distM) {
            if (!_chartImage || !_drawP || !canvas || !ctx) return;
            var p = _drawP;
            ctx.putImageData(_chartImage, 0, 0);
            var x = p.pad.left + (distM / p.maxDist) * p.pW;

            // Vertical crosshair line
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 3]);
            ctx.beginPath();
            ctx.moveTo(x, p.pad.top);
            ctx.lineTo(x, p.pad.top + p.pH);
            ctx.stroke();
            ctx.setLineDash([]);

            // Dots and tooltips on each speed trace
            var idx = 0;
            var tooltips = [];
            selectedLaps.forEach(function (lapNum) {
                var d = gpsCache[lapNum];
                if (!d || !d.distances || !d.speeds) { idx++; return; }
                var speed = interpValue(d.speeds, d.distances, distM);
                if (speed === null) { idx++; return; }
                var kmh = speed * 3.6;
                var y = p.pad.top + p.pH - ((kmh - p.minKmh) / (p.maxKmh - p.minKmh)) * p.pH;
                var col = lapColor(idx);
                ctx.fillStyle = col;
                ctx.beginPath();
                ctx.arc(x, y, 4, 0, Math.PI * 2);
                ctx.fill();
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 1.5;
                ctx.stroke();
                tooltips.push({ kmh: kmh, col: col, lapNum: lapNum });
                idx++;
            });

            // Tooltip box
            if (tooltips.length > 0) {
                var boxW = 120;
                var boxH = tooltips.length * 16 + 22;
                var boxX = x + 12;
                var boxY = p.pad.top + 8;
                if (boxX + boxW > p.w - p.pad.right) boxX = x - boxW - 12;
                ctx.fillStyle = 'rgba(0, 0, 0, 0.85)';
                ctx.fillRect(boxX, boxY, boxW, boxH);
                ctx.strokeStyle = 'rgba(255,255,255,0.15)';
                ctx.lineWidth = 1;
                ctx.strokeRect(boxX, boxY, boxW, boxH);
                ctx.fillStyle = '#aaa';
                ctx.font = '9px -apple-system, sans-serif';
                ctx.textAlign = 'left';
                ctx.textBaseline = 'top';
                ctx.fillText(distM.toFixed(0) + ' m', boxX + 8, boxY + 5);
                for (var ti = 0; ti < tooltips.length; ti++) {
                    var t = tooltips[ti];
                    var ty = boxY + 20 + ti * 16;
                    ctx.fillStyle = t.col;
                    ctx.fillRect(boxX + 8, ty, 8, 8);
                    ctx.fillStyle = '#fff';
                    ctx.font = '10px -apple-system, sans-serif';
                    ctx.fillText('L' + t.lapNum + ': ' + t.kmh.toFixed(1) + ' km/h', boxX + 20, ty);
                }
            }
        }

        function showCrosshair(distM) {
            _drawCrosshair(distM);
        }

        function clearCrosshair() {
            if (_chartImage && canvas && ctx) {
                ctx.putImageData(_chartImage, 0, 0);
            }
        }

        return { init: init, draw: draw, showCrosshair: showCrosshair, clearCrosshair: clearCrosshair };
    })();

    // ═══════════════════════════════════════════════════
    // VizGG — G-G scatter diagram
    // ═══════════════════════════════════════════════════
    var VizGG = (function () {
        var canvas, ctx;
        var _chartImage = null;
        var _plotP = null;   // saved plot geometry {cx,cy,scale,maxG,w,h}
        var _ggZoom = 1.0;
        var _ggPanX = 0, _ggPanY = 0;  // in G units
        var _ggDragging = false;
        var _ggDragStartX = 0, _ggDragStartY = 0;
        var _ggDragStartPanX = 0, _ggDragStartPanY = 0;

        function init() {
            canvas = document.getElementById('viz-gg-chart');
            if (!canvas) return;
            ctx = canvas.getContext('2d');
            canvas.__redraw = function() { draw(); };
            canvas.style.cursor = 'crosshair';
            canvas.addEventListener('mousemove', function (e) {
                if (_ggDragging) {
                    // Pan while dragging
                    if (!_plotP) return;
                    var dx = e.clientX - _ggDragStartX;
                    var dy = e.clientY - _ggDragStartY;
                    var effScale = _plotP.scale * _ggZoom;
                    _ggPanX = _ggDragStartPanX - dx / effScale;
                    _ggPanY = _ggDragStartPanY + dy / effScale;
                    draw();
                    return;
                }
                var rect = canvas.getBoundingClientRect();
                _handleHover(e.clientX - rect.left, e.clientY - rect.top);
            });
            canvas.addEventListener('mouseleave', function () {
                broadcastHover(null, 'gg');
                if (_chartImage && ctx) ctx.putImageData(_chartImage, 0, 0);
            });
            canvas.addEventListener('mousedown', function (e) {
                _ggDragging = true;
                _ggDragStartX = e.clientX;
                _ggDragStartY = e.clientY;
                _ggDragStartPanX = _ggPanX;
                _ggDragStartPanY = _ggPanY;
                canvas.style.cursor = 'grabbing';
            });
            window.addEventListener('mouseup', function () {
                if (_ggDragging) {
                    _ggDragging = false;
                    if (canvas) canvas.style.cursor = 'crosshair';
                }
            });
            // Zoom via scroll wheel
            canvas.addEventListener('wheel', function (e) {
                e.preventDefault();
                var delta = e.deltaY > 0 ? 0.85 : 1.18;
                _ggZoom = Math.max(0.5, Math.min(8, _ggZoom * delta));
                draw();
            }, { passive: false });
            // Double-click to reset
            canvas.addEventListener('dblclick', function () {
                _ggZoom = 1.0;
                _ggPanX = 0;
                _ggPanY = 0;
                draw();
            });
            canvas.addEventListener('touchstart', function (e) {
                if (e.touches.length === 1) {
                    var rect = canvas.getBoundingClientRect();
                    _handleHover(e.touches[0].clientX - rect.left, e.touches[0].clientY - rect.top);
                }
            }, { passive: true });
            canvas.addEventListener('touchmove', function (e) {
                if (e.touches.length === 1) {
                    var rect = canvas.getBoundingClientRect();
                    _handleHover(e.touches[0].clientX - rect.left, e.touches[0].clientY - rect.top);
                }
            }, { passive: true });
        }

        function draw() {
            if (!canvas || !ctx) return;
            var dpr = window.devicePixelRatio || 1;
            canvas.style.width = '';
            canvas.style.height = '';
            var w = canvas.clientWidth || canvas.parentElement.clientWidth || 700;
            var h = canvas.clientHeight || canvas.parentElement.clientHeight || 400;
            canvas.width = w * dpr;
            canvas.height = h * dpr;
            canvas.style.width = w + 'px';
            canvas.style.height = h + 'px';
            ctx.scale(dpr, dpr);

            // Background
            ctx.fillStyle = C.bgCard || '#1a1f2e';
            ctx.fillRect(0, 0, w, h);

            // Collect accel data from selected laps
            var allLat = [], allLong = [];
            var perLap = {};
            var idx = 0;
            selectedLaps.forEach(function (lapNum) {
                var d = gpsCache[lapNum];
                if (!d || !d.accel_lat || !d.accel_long) return;
                perLap[lapNum] = { lat: d.accel_lat, long: d.accel_long, color: lapColor(idx) };
                allLat = allLat.concat(d.accel_lat);
                allLong = allLong.concat(d.accel_long);
                idx++;
            });

            if (allLat.length === 0) {
                ctx.fillStyle = C.textSecondary || '#8b949e';
                ctx.font = '13px -apple-system, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('No acceleration data for selected laps', w / 2, h / 2);
                return;
            }

            // Convert to G (divide by 9.81)
            var maxG = 0;
            allLat.forEach(function (v) { var g = Math.abs(v / 9.81); if (g > maxG) maxG = g; });
            allLong.forEach(function (v) { var g = Math.abs(v / 9.81); if (g > maxG) maxG = g; });
            maxG = Math.max(maxG * 1.1, 0.5);

            var padGG = { top: 30, right: 40, bottom: 35, left: 50 };
            var plotW = w - padGG.left - padGG.right;
            var plotH = h - padGG.top - padGG.bottom;
            // Force square plot area
            var plotSize = Math.min(plotW, plotH);
            var cx = padGG.left + plotW / 2;
            var cy = padGG.top + plotH / 2;
            var visibleMaxG = maxG / _ggZoom;
            var scale = plotSize / 2 / visibleMaxG;

            // Square plot boundary
            var sqLeft = cx - plotSize / 2;
            var sqRight = cx + plotSize / 2;
            var sqTop = cy - plotSize / 2;
            var sqBottom = cy + plotSize / 2;

            // Subtle square boundary
            ctx.strokeStyle = C.border || '#30363d';
            ctx.lineWidth = 0.5;
            ctx.strokeRect(sqLeft, sqTop, plotSize, plotSize);

            // Pan offset in pixels
            var panPxX = _ggPanX * scale;
            var panPxY = _ggPanY * scale;

            // Grid circles (centered on pan-adjusted origin)
            var originX = cx - panPxX;
            var originY = cy + panPxY;
            var gSteps = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0];
            gSteps.forEach(function (g) {
                if (g > maxG * 2) return;
                var rPx = g * scale;
                ctx.strokeStyle = C.border || '#30363d';
                ctx.lineWidth = 0.5;
                ctx.beginPath();
                ctx.arc(originX, originY, rPx, 0, Math.PI * 2);
                ctx.stroke();
                ctx.fillStyle = C.textSecondary || '#8b949e';
                ctx.font = '10px -apple-system, sans-serif';
                ctx.textAlign = 'left';
                ctx.fillText(g.toFixed(1) + 'G', originX + rPx + 4, originY - 5);
            });

            // Axis lines through pan-adjusted origin (constrained to square area)
            ctx.strokeStyle = C.textMuted || '#484f58';
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(sqLeft, originY); ctx.lineTo(sqRight, originY); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(originX, sqTop); ctx.lineTo(originX, sqBottom); ctx.stroke();

            // Axis labels — directional
            ctx.fillStyle = C.textSecondary || '#8b949e';
            ctx.font = '11px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Lateral G', cx, sqBottom + 22);
            ctx.save();
            ctx.translate(sqLeft - 22, cy);
            ctx.rotate(-Math.PI / 2);
            ctx.fillText('Longitudinal G', 0, 0);
            ctx.restore();
            // Directional hints
            ctx.fillStyle = C.textMuted || '#484f58';
            ctx.font = '9px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Braking', originX, sqTop - 4);
            ctx.fillText('Accel', originX, sqBottom + 12);
            ctx.textAlign = 'right';
            ctx.fillText('Left', sqLeft - 4, originY + 3);
            ctx.textAlign = 'left';
            ctx.fillText('Right', sqRight + 4, originY + 3);

            // Zoom indicator
            if (_ggZoom > 1.01) {
                ctx.fillStyle = C.accent || 'rgba(255, 107, 53, 0.8)';
                ctx.font = '11px -apple-system, sans-serif';
                ctx.textAlign = 'right';
                ctx.textBaseline = 'top';
                ctx.fillText('Zoom: ' + _ggZoom.toFixed(1) + 'x  (dbl-click reset)', w - padGG.right, padGG.top + 4);
            }

            // Plot points per lap — clipped to square area
            ctx.save();
            ctx.beginPath();
            ctx.rect(sqLeft, sqTop, plotSize, plotSize);
            ctx.clip();
            var nLaps = Object.keys(perLap).length;
            var pointAlpha = nLaps > 3 ? 0.25 : nLaps > 1 ? 0.35 : 0.5;
            var pointRadius = nLaps > 3 ? 2 : 2.5;
            Object.keys(perLap).forEach(function (lapNum) {
                var ld = perLap[lapNum];
                ctx.fillStyle = ld.color;
                ctx.globalAlpha = pointAlpha;
                for (var i = 0; i < ld.lat.length; i++) {
                    if (ld.lat[i] === null || ld.long[i] === null) continue;
                    var gx = ld.lat[i] / 9.81;
                    var gy = ld.long[i] / 9.81;
                    ctx.beginPath();
                    ctx.arc(originX + gx * scale, originY - gy * scale, pointRadius, 0, Math.PI * 2);
                    ctx.fill();
                }
            });
            ctx.globalAlpha = 1.0;
            ctx.restore();

            // Lap legend (top right) — truncate when too many laps
            if (nLaps > 0) {
                var legX = w - padGG.right - 10;
                var legY = padGG.top + 4;
                ctx.textAlign = 'right';
                ctx.font = '10px -apple-system, sans-serif';
                var maxLegendEntries = Math.floor((h - padGG.top - padGG.bottom - 20) / 16);
                var lapKeys = Object.keys(perLap);
                var showCount = Math.min(lapKeys.length, maxLegendEntries);
                for (var li = 0; li < showCount; li++) {
                    var lapNum = lapKeys[li];
                    var ld = perLap[lapNum];
                    ctx.fillStyle = ld.color;
                    ctx.fillRect(legX - 40, legY + li * 16, 10, 10);
                    ctx.fillStyle = C.textSecondary || '#8b949e';
                    ctx.fillText('Lap ' + lapNum, legX, legY + li * 16 + 9);
                }
                if (lapKeys.length > showCount) {
                    ctx.fillStyle = C.textMuted || '#484f58';
                    ctx.fillText('+ ' + (lapKeys.length - showCount) + ' more', legX, legY + showCount * 16 + 9);
                }
            }

            // Title
            ctx.fillStyle = C.textPrimary || '#e6edf3';
            ctx.font = 'bold 13px -apple-system, sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'top';
            ctx.fillText('G-G Diagram', padGG.left, 6);

            // Save chart for hover overlay
            _plotP = { cx: originX, cy: originY, scale: scale, maxG: maxG, w: w, h: h };
            _chartImage = ctx.getImageData(0, 0, canvas.width, canvas.height);
        }

        function _handleHover(mx, my) {
            if (!_plotP || !_chartImage || !canvas || !ctx) return;
            var p = _plotP;
            // Find closest data point in pixel space
            var bestD2 = Infinity, bestLap = null, bestIdx = -1;
            selectedLaps.forEach(function (lapNum) {
                var d = gpsCache[lapNum];
                if (!d || !d.accel_lat || !d.accel_long) return;
                for (var i = 0; i < d.accel_lat.length; i++) {
                    if (d.accel_lat[i] === null || d.accel_long[i] === null) continue;
                    var px = p.cx + (d.accel_lat[i] / 9.81) * p.scale;
                    var py = p.cy - (d.accel_long[i] / 9.81) * p.scale;
                    var dx = px - mx, dy = py - my;
                    var dd = dx * dx + dy * dy;
                    if (dd < bestD2) { bestD2 = dd; bestLap = lapNum; bestIdx = i; }
                }
            });
            // Only match within 20px radius
            if (bestD2 > 400 || bestLap === null || bestIdx < 0) {
                broadcastHover(null, 'gg');
                if (_chartImage) ctx.putImageData(_chartImage, 0, 0);
                return;
            }
            var d = gpsCache[bestLap];
            var distM = (d.distances && d.distances[bestIdx] !== undefined) ? d.distances[bestIdx] : null;
            if (distM !== null) {
                broadcastHover(distM, 'gg');
                highlightAtDistance(distM);
            }
        }

        function highlightAtDistance(distM) {
            if (!_chartImage || !_plotP || !canvas || !ctx) return;
            var p = _plotP;
            ctx.putImageData(_chartImage, 0, 0);
            var idx = 0;
            selectedLaps.forEach(function (lapNum) {
                var d = gpsCache[lapNum];
                if (!d || !d.accel_lat || !d.accel_long || !d.distances) { idx++; return; }
                var ci = closestDistIdx(d.distances, distM);
                if (ci < 0 || d.accel_lat[ci] === null || d.accel_long[ci] === null) { idx++; return; }
                var px = p.cx + (d.accel_lat[ci] / 9.81) * p.scale;
                var py = p.cy - (d.accel_long[ci] / 9.81) * p.scale;
                var col = lapColor(idx);
                // Crosshair lines through point
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.25)';
                ctx.lineWidth = 1;
                ctx.setLineDash([3, 3]);
                ctx.beginPath();
                ctx.moveTo(p.cx - p.maxG * p.scale, py);
                ctx.lineTo(p.cx + p.maxG * p.scale, py);
                ctx.stroke();
                ctx.beginPath();
                ctx.moveTo(px, p.cy - p.maxG * p.scale);
                ctx.lineTo(px, p.cy + p.maxG * p.scale);
                ctx.stroke();
                ctx.setLineDash([]);
                // Highlighted dot
                ctx.fillStyle = col;
                ctx.globalAlpha = 1.0;
                ctx.beginPath();
                ctx.arc(px, py, 6, 0, Math.PI * 2);
                ctx.fill();
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 2;
                ctx.stroke();
                // G-value label
                var gLat = (d.accel_lat[ci] / 9.81).toFixed(2);
                var gLong = (d.accel_long[ci] / 9.81).toFixed(2);
                var lblX = px + 10;
                var lblY = py - 22;
                if (lblX + 85 > p.w) lblX = px - 95;
                if (lblY < 0) lblY = py + 10;
                ctx.fillStyle = 'rgba(0,0,0,0.85)';
                ctx.fillRect(lblX, lblY, 85, 18);
                ctx.fillStyle = '#fff';
                ctx.font = '10px -apple-system, sans-serif';
                ctx.textAlign = 'left';
                ctx.textBaseline = 'middle';
                ctx.fillText(gLat + 'G / ' + gLong + 'G', lblX + 4, lblY + 9);
                idx++;
            });
        }

        function clearHighlight() {
            if (_chartImage && canvas && ctx) {
                ctx.putImageData(_chartImage, 0, 0);
            }
        }

        return { init: init, draw: draw, highlightAtDistance: highlightAtDistance, clearHighlight: clearHighlight };
    })();

    // ═══════════════════════════════════════════════════
    // VizSidebar — lap list, sectors, stats
    // ═══════════════════════════════════════════════════
    var VizSidebar = (function () {
        var lapListEl, statsEl;

        function init() {
            lapListEl = document.getElementById('viz-lap-list');
            statsEl = document.getElementById('viz-stats');

            // Quick buttons
            var btnAll = document.getElementById('viz-select-all');
            var btnNone = document.getElementById('viz-select-none');
            var btnBest = document.getElementById('viz-select-best');

            if (btnAll) btnAll.addEventListener('click', function () {
                V.gpsLaps.forEach(function (ln) { selectedLaps.add(ln); });
                syncCheckboxes();
                onSelectionChanged();
            });
            if (btnNone) btnNone.addEventListener('click', function () {
                selectedLaps.clear();
                syncCheckboxes();
                onSelectionChanged();
            });
            if (btnBest) btnBest.addEventListener('click', function () {
                selectedLaps.clear();
                if (V.bestLap) selectedLaps.add(V.bestLap);
                syncCheckboxes();
                onSelectionChanged();
            });

            buildLapList();
        }

        function buildLapList() {
            if (!lapListEl) return;
            lapListEl.innerHTML = '';

            var lapsMap = {};
            V.laps.forEach(function (l) { lapsMap[l.lap_number] = l; });

            V.gpsLaps.forEach(function (lapNum, idx) {
                var lapInfo = lapsMap[lapNum] || {};
                var col = lapColor(idx);
                var isBest = lapInfo.is_best;

                var div = document.createElement('div');
                div.className = 'viz-lap-item' + (isBest ? ' best' : '');

                var cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.dataset.lap = lapNum;
                cb.checked = selectedLaps.has(lapNum);
                cb.addEventListener('change', function () {
                    if (cb.checked) selectedLaps.add(lapNum);
                    else selectedLaps.delete(lapNum);
                    onSelectionChanged();
                });

                var swatch = document.createElement('span');
                swatch.className = 'viz-lap-swatch';
                swatch.style.background = col;

                var label = document.createElement('span');
                label.textContent = 'Lap ' + lapNum + (isBest ? ' (Best)' : '');

                var timeSpan = document.createElement('span');
                timeSpan.className = 'viz-lap-time';
                timeSpan.textContent = lapInfo.lap_time_s ? lapInfo.lap_time_s.toFixed(3) + 's' : '';

                div.appendChild(cb);
                div.appendChild(swatch);
                div.appendChild(label);
                div.appendChild(timeSpan);
                lapListEl.appendChild(div);
            });
        }

        function syncCheckboxes() {
            if (!lapListEl) return;
            var cbs = lapListEl.querySelectorAll('input[type=checkbox]');
            cbs.forEach(function (cb) {
                var ln = parseInt(cb.dataset.lap, 10);
                cb.checked = selectedLaps.has(ln);
            });
        }

        function renderSectorTable(data) {
            var wrap = document.getElementById('viz-sector-table-wrap');
            if (!wrap) return;

            if (!data || !data.sector_boundaries || data.sector_boundaries.length === 0) {
                wrap.innerHTML = '<p class="viz-ref-hint">Click the reference line on the map to add sector splits.</p>';
                return;
            }

            // Build header
            var nSectors = data.sector_boundaries.length + 1;
            var html = '<table class="viz-sector-table"><thead><tr><th>Lap</th>';
            for (var s = 0; s < nSectors; s++) {
                html += '<th>S' + (s + 1) + '</th>';
            }
            html += '<th>Total</th></tr></thead><tbody>';

            // Find best per sector
            var bestPerSector = [];
            for (var s = 0; s < nSectors; s++) bestPerSector.push(Infinity);
            Object.keys(data.laps).forEach(function (lapKey) {
                var sectors = data.laps[lapKey].sectors || [];
                sectors.forEach(function (sec, idx) {
                    if (sec.time_s < bestPerSector[idx]) bestPerSector[idx] = sec.time_s;
                });
            });

            // Only show selected laps
            selectedLaps.forEach(function (lapNum) {
                var key = String(lapNum);
                var lapData = data.laps[key];
                if (!lapData) return;

                html += '<tr><td style="text-align:left;font-weight:500;">L' + lapNum + '</td>';
                (lapData.sectors || []).forEach(function (sec, idx) {
                    var isBest = sec.time_s <= bestPerSector[idx] + 0.001;
                    html += '<td' + (isBest ? ' class="best-sector"' : '') + '>'
                        + sec.time_s.toFixed(3) + '</td>';
                });
                html += '<td>' + lapData.total_s.toFixed(3) + '</td></tr>';
            });

            html += '</tbody></table>';
            wrap.innerHTML = html;
        }

        function updateStats() {
            if (!statsEl) return;
            var times = [];
            var lapsMap = {};
            V.laps.forEach(function (l) { lapsMap[l.lap_number] = l; });

            selectedLaps.forEach(function (ln) {
                var li = lapsMap[ln];
                if (li && li.lap_time_s) times.push(li.lap_time_s);
            });

            if (times.length === 0) {
                statsEl.innerHTML = '<div class="viz-stat-row"><span class="stat-label">No laps selected</span></div>';
                return;
            }

            var best = Math.min.apply(null, times);
            var mean = times.reduce(function (a, b) { return a + b; }, 0) / times.length;
            var variance = times.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / times.length;
            var stddev = Math.sqrt(variance);
            var consistency = mean > 0 ? (1 - stddev / mean) * 100 : 0;

            var html = '';
            html += '<div class="viz-stat-row"><span class="stat-label">Selected</span><span class="stat-value">' + times.length + ' laps</span></div>';
            html += '<div class="viz-stat-row"><span class="stat-label">Best</span><span class="stat-value" style="color:var(--green);">' + best.toFixed(3) + 's</span></div>';
            html += '<div class="viz-stat-row"><span class="stat-label">Mean</span><span class="stat-value">' + mean.toFixed(3) + 's</span></div>';
            html += '<div class="viz-stat-row"><span class="stat-label">Std Dev</span><span class="stat-value">' + stddev.toFixed(3) + 's</span></div>';
            html += '<div class="viz-stat-row"><span class="stat-label">Consistency</span><span class="stat-value">' + consistency.toFixed(1) + '%</span></div>';
            statsEl.innerHTML = html;
        }

        return {
            init: init,
            syncCheckboxes: syncCheckboxes,
            renderSectorTable: renderSectorTable,
            updateStats: updateStats,
        };
    })();

})();
