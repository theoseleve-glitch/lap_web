/**
 * gps_trace.js — Leaflet GPS map with speed-colored polyline and movable marker.
 *
 * Reads window.TELEMETRY = { sessionId, gpsLaps, bestLap }
 * Provides global:
 *   - window.GpsTrace.updateMarkerByDistance(distanceM)
 *   - window.GpsTrace.onMapHover  (callback for chart sync)
 *   - window.GpsTrace.loadLap(lapNumber)
 *
 * Phase 4/5 additions:
 *   - Reference line overlay (grey dashed)
 *   - Best lap overlay (gold)
 *   - Improved marker with tooltip
 */
(function () {
    'use strict';
    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {};

    // ── Colour helpers ──────────────────────────────
    function speedToColor(speed, minSpd, maxSpd) {
        // Blue (slow) → Green → Yellow → Red (fast)
        var t = maxSpd > minSpd ? (speed - minSpd) / (maxSpd - minSpd) : 0.5;
        t = Math.max(0, Math.min(1, t));
        var r, g, b;
        if (t < 0.25) {
            r = 0; g = Math.round(255 * (t / 0.25)); b = 255;
        } else if (t < 0.5) {
            r = 0; g = 255; b = Math.round(255 * (1 - (t - 0.25) / 0.25));
        } else if (t < 0.75) {
            r = Math.round(255 * ((t - 0.5) / 0.25)); g = 255; b = 0;
        } else {
            r = 255; g = Math.round(255 * (1 - (t - 0.75) / 0.25)); b = 0;
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    // ── State ───────────────────────────────────────
    var map = null;
    var traceLayer = null;
    var marker = null;
    var currentData = null;   // { latitudes, longitudes, distances, speeds }
    var onMapHoverCb = null;

    // Overlay layers.
    var referenceLayer = null;
    var bestLapLayer = null;
    var cornerMarkersLayer = null;
    var allLapsLayer = null;

    // ── Public API ──────────────────────────────────
    window.GpsTrace = {
        updateMarkerByDistance: updateMarkerByDistance,
        set onMapHover(fn) { onMapHoverCb = fn; },
        get currentData() { return currentData; },
        loadLap: loadLap,
    };

    // ── Init ────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        // Guard: already initialized or Leaflet not yet loaded.
        if (map) return;
        if (typeof L === 'undefined' || !L.map) return;

        var T = window.TELEMETRY;
        if (!T || !T.gpsLaps || T.gpsLaps.length === 0) return;

        var mapEl = document.getElementById('gps-map');
        if (!mapEl) return;

        map = L.map('gps-map', { zoomControl: true });
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap',
        }).addTo(map);

        // Load the default (best) lap.
        var defaultLap = T.bestLap || T.gpsLaps[0];
        loadLap(defaultLap);

        // Load corner markers (C1, C2, C3, etc.)
        loadCornerMarkers();

        // Lap selector.
        var sel = document.getElementById('lap-select');
        if (sel) {
            _lc.addListener(sel, 'change', function () {
                loadLap(parseInt(sel.value, 10));
            });
        }

        // Reference line toggle.
        var refToggle = document.getElementById('toggle-reference-line');
        if (refToggle) {
            _lc.addListener(refToggle, 'change', function () {
                if (refToggle.checked) {
                    loadReferenceLine();
                } else {
                    removeReferenceLine();
                }
            });
        }

        // Best lap overlay toggle.
        var bestToggle = document.getElementById('toggle-best-lap');
        if (bestToggle) {
            _lc.addListener(bestToggle, 'change', function () {
                if (bestToggle.checked) {
                    loadBestLapOverlay();
                } else {
                    removeBestLapOverlay();
                }
            });
        }

        // All laps overlay toggle.
        var allLapsToggle = document.getElementById('toggle-all-laps');
        if (allLapsToggle) {
            _lc.addListener(allLapsToggle, 'change', function () {
                if (allLapsToggle.checked) {
                    loadAllLapsOverlay();
                } else {
                    removeAllLapsOverlay();
                }
            });
        }
    });

    // ── Load a lap's GPS data ───────────────────────
    function loadLap(lapNumber) {
        var T = window.TELEMETRY;
        var url = '/api/session/' + encodeURIComponent(T.sessionId)
                + '/gps/' + lapNumber;

        FetchHelper.fetch(url)
            .then(function (data) {
                currentData = data;
                drawTrace(data);
                // Notify chart_sync to reload.
                if (window.ChartSync && window.ChartSync.onLapLoaded) {
                    window.ChartSync.onLapLoaded(data);
                }
            })
            .catch(function (err) {
                console.warn('GPS load failed:', err);
                var mapEl = document.getElementById('gps-map');
                if (mapEl && !mapEl.querySelector('.gps-error')) {
                    var errDiv = document.createElement('div');
                    errDiv.className = 'gps-error';
                    errDiv.style.cssText = 'position:absolute;z-index:999;top:50%;left:50%;' +
                        'transform:translate(-50%,-50%);background:rgba(0,0,0,0.7);' +
                        'padding:12px 20px;border-radius:8px;color:' + (C.red || '#f85149') + ';font-size:13px;';
                    errDiv.textContent = 'Failed to load GPS data for lap ' + lapNumber;
                    mapEl.appendChild(errDiv);
                }
            });
    }

    // ── Draw the speed-colored polyline ─────────────
    function drawTrace(data) {
        if (traceLayer) {
            map.removeLayer(traceLayer);
        }
        if (marker) {
            map.removeLayer(marker);
        }

        var lats = data.latitudes;
        var lons = data.longitudes;
        var spds = data.speeds;
        if (!lats || lats.length < 2) return;

        // Compute speed range.
        var validSpeeds = spds.filter(function (s) { return s !== null && isFinite(s); });
        var minSpd = Math.min.apply(null, validSpeeds);
        var maxSpd = Math.max.apply(null, validSpeeds);

        // Build coloured segments.
        traceLayer = L.layerGroup();
        for (var i = 0; i < lats.length - 1; i++) {
            if (lats[i] === null || lats[i + 1] === null) continue;
            var color = speedToColor(spds[i] || 0, minSpd, maxSpd);
            L.polyline(
                [[lats[i], lons[i]], [lats[i + 1], lons[i + 1]]],
                { color: color, weight: 4, opacity: 0.9 }
            ).addTo(traceLayer);
        }
        traceLayer.addTo(map);

        // Start/finish marker.
        L.circleMarker([lats[0], lons[0]], {
            radius: 7, color: C.accent || '#ff6b35', fillColor: C.accent || '#ff6b35',
            fillOpacity: 0.9, weight: 2,
        }).addTo(traceLayer).bindPopup('Start / Finish');

        // Movable position marker (for hover sync) — larger, more prominent.
        marker = L.circleMarker([lats[0], lons[0]], {
            radius: 12, color: C.textPrimary || '#ffffff', fillColor: C.accent || '#ff6b35',
            fillOpacity: 1, weight: 3,
        }).addTo(map);

        // Bind a tooltip for speed/distance info.
        marker.bindTooltip('', {
            permanent: false,
            direction: 'top',
            offset: [0, -14],
            className: 'gps-marker-tooltip',
        });

        // Fit map to trace bounds.
        var bounds = [];
        for (var j = 0; j < lats.length; j++) {
            if (lats[j] !== null && lons[j] !== null) {
                bounds.push([lats[j], lons[j]]);
            }
        }
        if (bounds.length > 0) {
            map.fitBounds(bounds, { padding: [30, 30] });
        }

        // Speed legend.
        addSpeedLegend(minSpd, maxSpd);

        // Enable map hover → chart sync.
        enableMapHover(data);
    }

    // ── Speed legend control ────────────────────────
    var legendControl = null;
    function addSpeedLegend(minSpd, maxSpd) {
        if (legendControl) {
            map.removeControl(legendControl);
        }

        legendControl = L.control({ position: 'bottomright' });
        legendControl.onAdd = function () {
            var div = L.DomUtil.create('div', 'speed-legend');
            var minKmh = (minSpd * 3.6).toFixed(0);
            var maxKmh = (maxSpd * 3.6).toFixed(0);
            div.innerHTML = '<div class="legend-title">Speed</div>'
                + '<div class="legend-row">'
                + '<span class="legend-swatch" style="background:rgb(0,0,255)"></span>'
                + '<span>' + minKmh + ' km/h</span></div>'
                + '<div class="legend-row">'
                + '<span class="legend-swatch" style="background:rgb(0,255,0)"></span>'
                + '<span>' + ((minSpd + maxSpd) / 2 * 3.6).toFixed(0) + ' km/h</span></div>'
                + '<div class="legend-row">'
                + '<span class="legend-swatch" style="background:rgb(255,0,0)"></span>'
                + '<span>' + maxKmh + ' km/h</span></div>';
            return div;
        };
        legendControl.addTo(map);
    }

    // ── Update marker position by distance ──────────
    function updateMarkerByDistance(distM) {
        if (!currentData || !marker) return;
        var dists = currentData.distances;
        var lats = currentData.latitudes;
        var lons = currentData.longitudes;
        var speeds = currentData.speeds;

        // Binary search for closest distance index.
        var idx = closestIndex(dists, distM);
        if (idx < 0 || idx >= lats.length) return;
        if (lats[idx] === null) return;

        marker.setLatLng([lats[idx], lons[idx]]);

        // Update marker tooltip with speed/distance.
        if (speeds && speeds[idx] !== null && isFinite(speeds[idx])) {
            var kmh = (speeds[idx] * 3.6).toFixed(0);
            marker.setTooltipContent(kmh + ' km/h @ ' + distM.toFixed(0) + 'm');
            marker.openTooltip();
        }
    }

    // ── Enable hover on map segments ────────────────
    function enableMapHover(data) {
        if (!traceLayer) return;

        // On each polyline segment, attach mouseover.
        traceLayer.eachLayer(function (layer) {
            if (layer instanceof L.Polyline && !(layer instanceof L.CircleMarker)) {
                layer.on('mouseover', function (e) {
                    var ll = e.latlng;
                    var idx = closestLatLonIndex(data.latitudes, data.longitudes, ll.lat, ll.lng);
                    if (idx >= 0) {
                        marker.setLatLng([data.latitudes[idx], data.longitudes[idx]]);

                        // Show tooltip on marker.
                        if (data.speeds && data.speeds[idx] !== null && isFinite(data.speeds[idx])) {
                            var kmh = (data.speeds[idx] * 3.6).toFixed(0);
                            var distStr = data.distances[idx] ? data.distances[idx].toFixed(0) : '?';
                            marker.setTooltipContent(kmh + ' km/h @ ' + distStr + 'm');
                            marker.openTooltip();
                        }

                        if (onMapHoverCb) {
                            onMapHoverCb(data.distances[idx], data.speeds[idx], idx);
                        }
                    }
                });
            }
        });
    }

    // ── Reference line overlay ──────────────────────
    function loadReferenceLine() {
        if (referenceLayer) return; // Already loaded.

        var T = window.TELEMETRY;
        if (!T) return;

        var url = '/api/session/' + encodeURIComponent(T.sessionId) + '/reference_line';
        FetchHelper.fetch(url)
            .then(function (data) {
                drawReferenceLine(data);
            })
            .catch(function () {
                var toggle = document.getElementById('toggle-reference-line');
                if (toggle) toggle.checked = false;
            });
    }

    function drawReferenceLine(data) {
        if (!map || !data.latitudes || data.latitudes.length < 2) return;

        var coords = [];
        for (var i = 0; i < data.latitudes.length; i++) {
            if (data.latitudes[i] !== null && data.longitudes[i] !== null) {
                coords.push([data.latitudes[i], data.longitudes[i]]);
            }
        }

        referenceLayer = L.polyline(coords, {
            color: C.textSecondary || '#8b949e',
            weight: 3,
            opacity: 0.6,
            dashArray: '8, 6',
        }).addTo(map);
    }

    function removeReferenceLine() {
        if (referenceLayer && map) {
            map.removeLayer(referenceLayer);
            referenceLayer = null;
        }
    }

    // ── Best lap overlay ────────────────────────────
    function loadBestLapOverlay() {
        if (bestLapLayer) return; // Already loaded.

        var T = window.TELEMETRY;
        if (!T) return;

        var url = '/api/session/' + encodeURIComponent(T.sessionId) + '/best_lap_gps';
        FetchHelper.fetch(url)
            .then(function (data) {
                drawBestLapOverlay(data);
            })
            .catch(function () {
                var toggle = document.getElementById('toggle-best-lap');
                if (toggle) toggle.checked = false;
            });
    }

    function drawBestLapOverlay(data) {
        if (!map || !data.latitudes || data.latitudes.length < 2) return;

        var coords = [];
        for (var i = 0; i < data.latitudes.length; i++) {
            if (data.latitudes[i] !== null && data.longitudes[i] !== null) {
                coords.push([data.latitudes[i], data.longitudes[i]]);
            }
        }

        bestLapLayer = L.polyline(coords, {
            color: C.yellow || '#d29922',
            weight: 3,
            opacity: 0.8,
        }).addTo(map);
    }

    function removeBestLapOverlay() {
        if (bestLapLayer && map) {
            map.removeLayer(bestLapLayer);
            bestLapLayer = null;
        }
    }

    // ── All laps overlay ──────────────────────────
    function loadAllLapsOverlay() {
        if (allLapsLayer) return; // Already loaded.

        var T = window.TELEMETRY;
        if (!T || !T.gpsLaps || T.gpsLaps.length === 0) return;

        allLapsLayer = L.layerGroup();
        var LAP_COLORS = [
            '#636efa', '#ef553b', '#00cc96', '#ab63fa', '#ffa15a',
            '#19d3f3', '#ff6692', '#b6e880', '#ff97ff', '#fecb52',
        ];

        var loaded = 0;
        var total = T.gpsLaps.length;

        T.gpsLaps.forEach(function (lapNum, idx) {
            var url = '/api/session/' + encodeURIComponent(T.sessionId)
                    + '/gps/' + lapNum;
            FetchHelper.fetch(url)
                .then(function (data) {
                    if (!data.latitudes || data.latitudes.length < 2) return;
                    var coords = [];
                    for (var i = 0; i < data.latitudes.length; i++) {
                        if (data.latitudes[i] !== null && data.longitudes[i] !== null) {
                            coords.push([data.latitudes[i], data.longitudes[i]]);
                        }
                    }
                    var isBest = (lapNum === T.bestLap);
                    var color = isBest ? (C.accent || '#ff6b35') : LAP_COLORS[idx % LAP_COLORS.length];
                    var weight = isBest ? 4 : 2;
                    var opacity = isBest ? 0.9 : 0.4;

                    var line = L.polyline(coords, {
                        color: color, weight: weight, opacity: opacity,
                    });
                    line.bindTooltip('Lap ' + lapNum, {
                        sticky: true, direction: 'top', offset: [0, -8],
                    });
                    line.addTo(allLapsLayer);
                })
                .catch(function (err) { console.warn('All-laps overlay: lap load failed:', err); })
                .finally(function () {
                    loaded++;
                    if (loaded === total && allLapsLayer) {
                        allLapsLayer.addTo(map);
                    }
                });
        });
    }

    function removeAllLapsOverlay() {
        if (allLapsLayer && map) {
            map.removeLayer(allLapsLayer);
            allLapsLayer = null;
        }
    }

    // ── Corner markers overlay ─────────────────────
    function loadCornerMarkers() {
        var T = window.TELEMETRY;
        if (!T || !T.sessionId || !map) return;

        var url = '/api/session/' + encodeURIComponent(T.sessionId) + '/corner-positions';
        FetchHelper.fetch(url)
            .then(function (data) {
                if (!data.corners || data.corners.length === 0) return;
                if (cornerMarkersLayer) {
                    map.removeLayer(cornerMarkersLayer);
                }
                cornerMarkersLayer = L.layerGroup();

                var CORNER_COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6'];
                data.corners.forEach(function (c, idx) {
                    var color = CORNER_COLORS[idx % CORNER_COLORS.length];

                    // Corner marker with label
                    var markerIcon = L.divIcon({
                        className: 'corner-marker-icon',
                        html: '<div style="background:' + color + ';color:var(--text-primary);' +
                              'width:28px;height:28px;border-radius:50%;' +
                              'display:flex;align-items:center;justify-content:center;' +
                              'font-weight:bold;font-size:13px;border:2px solid var(--text-primary);' +
                              'box-shadow:0 2px 6px rgba(0,0,0,0.5);">C' + c.corner_id + '</div>',
                        iconSize: [28, 28],
                        iconAnchor: [14, 14],
                    });

                    var m = L.marker([c.lat, c.lon], { icon: markerIcon });
                    m.bindPopup(
                        '<strong>Corner ' + c.corner_id + '</strong><br>' +
                        'Brake point: ' + c.brake_point_m + 'm<br>' +
                        'Range: ' + c.brake_point_range_m[0] + ' – ' +
                        c.brake_point_range_m[1] + 'm'
                    );
                    m.addTo(cornerMarkersLayer);
                });

                cornerMarkersLayer.addTo(map);
            })
            .catch(function (err) {
                console.warn('Corner markers not available:', err);
            });
    }

    // ── Utility: find closest index by distance ─────
    function closestIndex(arr, target) {
        if (!arr || arr.length === 0) return -1;
        var lo = 0, hi = arr.length - 1;
        while (lo < hi) {
            var mid = (lo + hi) >> 1;
            if (arr[mid] < target) lo = mid + 1;
            else hi = mid;
        }
        // Check neighbours.
        if (lo > 0 && Math.abs(arr[lo - 1] - target) < Math.abs(arr[lo] - target)) {
            return lo - 1;
        }
        return lo;
    }

    // ── Utility: find closest index by lat/lon ──────
    function closestLatLonIndex(lats, lons, lat, lon) {
        var bestIdx = -1, bestDist = Infinity;
        for (var i = 0; i < lats.length; i++) {
            if (lats[i] === null) continue;
            var dlat = lats[i] - lat;
            var dlon = lons[i] - lon;
            var d = dlat * dlat + dlon * dlon;
            if (d < bestDist) {
                bestDist = d;
                bestIdx = i;
            }
        }
        return bestIdx;
    }

    function destroy() {
        _lc.destroyAll();
        if (map) {
            map.remove();
            map = null;
        }
        traceLayer = null;
        marker = null;
        referenceLayer = null;
        bestLapLayer = null;
        cornerMarkersLayer = null;
        allLapsLayer = null;
        currentData = null;
    }

    window.ModuleManager.register('gps_trace', {
        init: function () { /* auto-inits on DOMContentLoaded */ },
        destroy: destroy
    });

})();
