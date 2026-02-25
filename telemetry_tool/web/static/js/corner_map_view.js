/**
 * corner_map_view.js — Read-only track map for Corners & Coaching tab.
 *
 * Renders a compact GPS track outline with corner markers, color-coded
 * by time loss. Fetches data lazily when the Corners tab is activated.
 *
 * Public API:
 *   window.CornerMapView.init(canvasId, sessionId)
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {
        bgCard: '#1e1e2e', border: '#333', textPrimary: '#e0e0e0',
        textSecondary: '#aaa', textMuted: '#777', accent: '#f97316',
    };

    window.CornerMapView = { init: init };

    function init(canvasId, sessionId) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var ctx = canvas.getContext('2d');

        var T = window.TELEMETRY;
        if (!T || !T.gpsLaps || T.gpsLaps.length === 0) {
            _msg(canvas, ctx, 'No GPS data available');
            return;
        }

        var bestLap = T.bestLap || T.gpsLaps[0];

        // Show loading state
        _msg(canvas, ctx, 'Loading track map...');

        // Fetch GPS trace for best lap + corner positions + corner coaching summary
        var gpsUrl = '/api/session/' + encodeURIComponent(sessionId) + '/gps/' + bestLap;
        var cornerUrl = '/api/session/' + encodeURIComponent(sessionId) + '/corner-positions';
        var coachUrl = '/api/session/' + encodeURIComponent(sessionId) + '/corner-coaching';

        Promise.all([
            FetchHelper.fetch(gpsUrl).catch(function () { return null; }),
            FetchHelper.fetch(cornerUrl).catch(function () { return null; }),
            FetchHelper.fetch(coachUrl).catch(function () { return null; }),
        ]).then(function (results) {
            var gps = results[0];
            var corners = results[1];
            var coaching = results[2];

            if (!gps || !gps.latitudes || gps.latitudes.length < 2) {
                _msg(canvas, ctx, 'No GPS data for track map');
                return;
            }

            // Build corner info (merge positions + coaching hints)
            var cornerInfo = _mergeCornerData(
                corners ? corners.corners || [] : [],
                coaching ? coaching.corners || [] : []
            );

            _render(canvas, ctx, gps, cornerInfo);
        });
    }

    function _mergeCornerData(positions, coaching) {
        // Map coaching data by corner_id
        var coachMap = {};
        coaching.forEach(function (c) {
            coachMap[c.corner_id] = c;
        });

        // Use positions as base, merge coaching data
        if (positions.length > 0) {
            return positions.map(function (p) {
                var coach = coachMap[p.corner_id] || {};
                return {
                    corner_id: p.corner_id,
                    lat: p.lat,
                    lon: p.lon,
                    avg_time_loss_ms: coach.avg_time_loss_ms || 0,
                    coaching_hint: coach.coaching_hint || '',
                    avg_grip: coach.avg_grip || null,
                };
            });
        }

        // If no positions but coaching has data, we can't place them on the map
        return [];
    }

    function _render(canvas, ctx, gps, corners) {
        var lats = gps.latitudes;
        var lons = gps.longitudes;
        var spds = gps.speeds || [];

        // Compute bounds
        var allLats = [], allLons = [];
        for (var i = 0; i < lats.length; i++) {
            if (lats[i] !== null && lons[i] !== null) {
                allLats.push(lats[i]);
                allLons.push(lons[i]);
            }
        }
        if (allLats.length === 0) {
            _msg(canvas, ctx, 'Invalid GPS data');
            return;
        }

        var latMin = Math.min.apply(null, allLats);
        var latMax = Math.max.apply(null, allLats);
        var lonMin = Math.min.apply(null, allLons);
        var lonMax = Math.max.apply(null, allLons);

        var originLat = (latMin + latMax) / 2;
        var mPerDegLat = 111320;
        var mPerDegLon = 111320 * Math.cos(originLat * Math.PI / 180);

        var rangeX = (lonMax - lonMin) * mPerDegLon;
        var rangeY = (latMax - latMin) * mPerDegLat;

        // Sizing — compact view for the coaching section
        var dpr = window.devicePixelRatio || 1;
        var container = canvas.parentElement;
        var w = (container ? container.clientWidth : 600) - 8;
        var h = Math.max(280, Math.min(420, w * 0.55));

        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        var pad = { top: 30, right: 30, bottom: 30, left: 30 };
        var plotW = w - pad.left - pad.right;
        var plotH = h - pad.top - pad.bottom;

        var scaleX = plotW / Math.max(rangeX, 1);
        var scaleY = plotH / Math.max(rangeY, 1);
        var scale = Math.min(scaleX, scaleY) * 0.90;

        var offsetX = pad.left + (plotW - rangeX * scale) / 2;
        var offsetY = pad.top + (plotH - rangeY * scale) / 2;

        function toPixel(lat, lon) {
            var mx = (lon - lonMin) * mPerDegLon;
            var my = (lat - latMin) * mPerDegLat;
            return {
                x: offsetX + mx * scale,
                y: offsetY + (latMax - latMin) * mPerDegLat * scale - my * scale,
            };
        }

        // Background
        ctx.fillStyle = C.bgCard;
        ctx.fillRect(0, 0, w, h);
        ctx.strokeStyle = C.border;
        ctx.lineWidth = 1;
        ctx.strokeRect(0.5, 0.5, w - 1, h - 1);

        // Title
        ctx.fillStyle = C.textSecondary;
        ctx.font = 'bold 12px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Track Layout — Corner Overview', w / 2, 18);

        // Speed range for coloring
        var allSpd = [];
        for (var i = 0; i < spds.length; i++) {
            if (spds[i] !== null && isFinite(spds[i])) allSpd.push(spds[i]);
        }
        var minSpd = allSpd.length > 0 ? Math.min.apply(null, allSpd) : 0;
        var maxSpd = allSpd.length > 0 ? Math.max.apply(null, allSpd) : 1;

        // Draw track outline (speed-colored)
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.lineWidth = 3;
        ctx.globalAlpha = 0.85;

        for (var i = 0; i < lats.length - 1; i++) {
            if (lats[i] === null || lats[i + 1] === null) continue;
            var p1 = toPixel(lats[i], lons[i]);
            var p2 = toPixel(lats[i + 1], lons[i + 1]);

            ctx.strokeStyle = _speedColor(spds[i] || 0, minSpd, maxSpd);
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
        }
        ctx.globalAlpha = 1.0;

        // Start/finish marker
        if (lats[0] !== null) {
            var sf = toPixel(lats[0], lons[0]);
            ctx.beginPath();
            ctx.arc(sf.x, sf.y, 5, 0, Math.PI * 2);
            ctx.fillStyle = '#fff';
            ctx.fill();
            ctx.strokeStyle = C.accent;
            ctx.lineWidth = 2;
            ctx.stroke();
        }

        // Corner markers — color-coded by time loss
        if (corners.length > 0) {
            // Find max time loss for normalization
            var maxLoss = 0;
            corners.forEach(function (c) {
                if (c.avg_time_loss_ms > maxLoss) maxLoss = c.avg_time_loss_ms;
            });

            corners.forEach(function (c) {
                var p = toPixel(c.lat, c.lon);
                if (!p) return;
                var r = 16;

                // Color: green (no loss) → yellow (moderate) → red (high loss)
                var col = _lossColor(c.avg_time_loss_ms, maxLoss);

                // Outer ring glow
                ctx.beginPath();
                ctx.arc(p.x, p.y, r + 3, 0, Math.PI * 2);
                ctx.fillStyle = col.replace(')', ', 0.2)').replace('rgb', 'rgba');
                ctx.fill();

                // Main circle
                ctx.beginPath();
                ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
                ctx.fillStyle = col;
                ctx.fill();
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 2;
                ctx.stroke();

                // Label
                ctx.fillStyle = '#fff';
                ctx.font = 'bold 10px system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText('C' + c.corner_id, p.x, p.y);
                ctx.textBaseline = 'alphabetic';
            });

            // Legend (bottom)
            _drawLossLegend(ctx, w, h, maxLoss);
        }
    }

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
            var s = (t - 0.5) / 0.5;
            r = 255;
            g = Math.round(255 - s * 200);
            b = Math.round(30);
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    function _lossColor(lossMs, maxLoss) {
        if (maxLoss <= 0) return 'rgb(76, 175, 80)'; // green
        var t = Math.min(1, lossMs / Math.max(maxLoss, 1));
        var r, g, b;
        if (t < 0.4) {
            // Green → Yellow
            var s = t / 0.4;
            r = Math.round(76 + s * 179);
            g = Math.round(175 + s * 80);
            b = Math.round(80 - s * 60);
        } else {
            // Yellow → Red
            var s = (t - 0.4) / 0.6;
            r = Math.round(255);
            g = Math.round(255 - s * 200);
            b = Math.round(20 + s * 20);
        }
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    function _drawLossLegend(ctx, w, h, maxLoss) {
        if (maxLoss <= 0) return;
        var legW = 120, legH = 8;
        var legX = (w - legW) / 2;
        var legY = h - 14;

        // Gradient bar
        for (var i = 0; i < legW; i++) {
            var t = i / legW;
            ctx.fillStyle = _lossColor(t * maxLoss, maxLoss);
            ctx.fillRect(legX + i, legY, 1, legH);
        }

        // Border
        ctx.strokeStyle = C.textMuted;
        ctx.lineWidth = 0.5;
        ctx.strokeRect(legX, legY, legW, legH);

        // Labels
        ctx.fillStyle = C.textMuted;
        ctx.font = '9px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('0ms', legX, legY - 2);
        ctx.textAlign = 'right';
        ctx.fillText(maxLoss.toFixed(0) + 'ms loss', legX + legW, legY - 2);
    }

    function _msg(canvas, ctx, text) {
        var dpr = window.devicePixelRatio || 1;
        var w = (canvas.parentElement ? canvas.parentElement.clientWidth : 400) - 8;
        canvas.width = w * dpr;
        canvas.height = 160 * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = '160px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = C.bgCard;
        ctx.fillRect(0, 0, w, 160);
        ctx.fillStyle = C.textMuted;
        ctx.font = '13px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(text, w / 2, 80);
    }
})();
