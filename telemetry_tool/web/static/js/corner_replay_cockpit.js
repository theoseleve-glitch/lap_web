/**
 * corner_replay_cockpit.js — Virtual cockpit canvas for corner replay.
 *
 * Renders: speedometer arc gauge, vertical brake/throttle bars,
 * mini G-force ball, and corner info overlay.
 *
 * Brake/throttle derived from accel_long (values in G):
 *   brake   = clamp(-accel_long / peakBrake, 0, 1)
 *   throttle = clamp(accel_long / peakThrottle, 0, 1)
 *
 * Public API:
 *   window.CornerReplayCockpit.init(canvasId)
 *   window.CornerReplayCockpit.render(data, opts)
 *   window.CornerReplayCockpit.renderCompact(canvasId, data, opts)
 */
(function () {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var C = window.Theme ? window.Theme.colors : {
        bgCard: '#1e1e2e', border: '#333', textPrimary: '#e0e0e0',
        textSecondary: '#aaa', textMuted: '#777', accent: '#f97316',
    };

    var MAX_BRAKE_G = 1.2;     // G default for full brake bar (values stored in G)
    var MAX_THROTTLE_G = 0.8;  // G default for full throttle bar (values stored in G)
    var MAX_SPEED_KPH = 120;   // speedometer max for karts

    // Session-peak calibration: set by setSessionPeaks() so bars hit 100%
    var _peakBrakeG = 0;
    var _peakThrottleG = 0;

    var _canvas, _ctx;

    window.CornerReplayCockpit = {
        init: init,
        render: render,
        renderCompact: renderCompact,
        /** Call once after loading replay data to calibrate bars to session peaks. */
        setSessionPeaks: function(peakBrake, peakThrottle) {
            _peakBrakeG = peakBrake > 0 ? peakBrake : MAX_BRAKE_G;
            _peakThrottleG = peakThrottle > 0 ? peakThrottle : MAX_THROTTLE_G;
        },
    };

    function init(canvasId) {
        _canvas = document.getElementById(canvasId);
        if (!_canvas) return;
        _ctx = _canvas.getContext('2d');
    }

    /**
     * Render full cockpit on the main canvas.
     * data: { speed, accel_lat, accel_long, brake, throttle }
     * opts: { cornerName, refSpeed, lapLabel, showPedals }
     */
    function render(data, opts) {
        if (!_canvas || !_canvas.parentElement) return;
        var dims = _setup(_canvas, _ctx);
        if (!dims) return;

        // Register __redraw for ResizeObserver (replays last call)
        _canvas.__redraw = function() { render(data, opts); };

        var ctx = _ctx;
        opts = opts || {};
        data = _normalizeData(data);

        // Background
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, dims.w, dims.h);

        var showPedals = !!opts.showPedals;
        var leftOffset = 0;

        if (showPedals) {
            // Brake/throttle bars on the left (only when real data exists)
            var barW = 22;
            var barH = dims.h * 0.52;
            var barY = 30;
            _drawPedalBar(ctx, 25, barY, barW, barH, data.brake, '#f85149', 'BRK');
            _drawPedalBar(ctx, 25 + barW + 10, barY, barW, barH, data.throttle, '#3fb950', 'THR');
            leftOffset = 80;
        }

        // Layout: speedometer left of center, G-ball right of center (bigger)
        var usableW = dims.w - leftOffset;
        var centerX = leftOffset + usableW * 0.38;
        var speedoR = Math.min(usableW * 0.18, dims.h * 0.28);
        var speedoCY = speedoR + 24;

        _drawSpeedometer(ctx, centerX, speedoCY, speedoR, data.speed, opts.refSpeed);

        // G-force ball — bigger, positioned right of speedometer
        var gBallR = Math.min(usableW * 0.22, dims.h * 0.30, 80);
        var gBallX = leftOffset + usableW * 0.72;
        var gBallY = dims.h * 0.45;
        _drawGBall(ctx, gBallX, gBallY, gBallR, data.accel_lat, data.accel_long);

        // Corner info
        if (opts.cornerName) {
            ctx.fillStyle = C.textPrimary || '#e0e0e0';
            ctx.font = 'bold 13px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(opts.cornerName, leftOffset + usableW / 2, dims.h - 12);
        }

        // Lap label
        if (opts.lapLabel) {
            ctx.fillStyle = C.textSecondary || '#aaa';
            ctx.font = '11px system-ui, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(opts.lapLabel, dims.w - 8, 16);
        }
    }

    /**
     * Render compact cockpit on a specific canvas (for split mode).
     * opts: { lapLabel, refSpeed, showPedals }
     */
    function renderCompact(canvasId, data, opts) {
        var canvas = document.getElementById(canvasId);
        if (!canvas || !canvas.parentElement) return;
        var ctx = canvas.getContext('2d');
        var dims = _setup(canvas, ctx);
        if (!dims) return;

        // Register __redraw for ResizeObserver (replays last call)
        canvas.__redraw = function() { renderCompact(canvasId, data, opts); };

        opts = opts || {};
        data = _normalizeData(data);

        // Background
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, dims.w, dims.h);

        var showPedals = !!opts.showPedals;

        // Compact layout: speedometer left, G-ball right (bigger, adjacent)
        var speedoR = Math.min(dims.w * 0.18, dims.h * 0.34);
        var speedoCX = speedoR + 18;
        var speedoCY = dims.h / 2;

        _drawSpeedometer(ctx, speedoCX, speedoCY, speedoR, data.speed, opts.refSpeed);

        var nextX = speedoCX + speedoR + 15;

        if (showPedals) {
            // Brake/throttle bars (only when real data exists)
            var barW = 14;
            var barH = dims.h * 0.55;
            var barY = (dims.h - barH) / 2;
            _drawPedalBar(ctx, nextX, barY, barW, barH, data.brake, '#f85149', 'B');
            _drawPedalBar(ctx, nextX + barW + 5, barY, barW, barH, data.throttle, '#3fb950', 'T');
            nextX += barW * 2 + 20;
        }

        // G-ball — bigger and closer to speedometer
        var gBallR = Math.min(dims.w * 0.20, dims.h * 0.32, 60);
        var gBallX = nextX + gBallR + 8;
        // If G-ball would overflow right edge, center it in remaining space
        if (gBallX + gBallR + 8 > dims.w) {
            gBallX = (nextX + dims.w) / 2;
        }
        var gBallY = dims.h / 2;
        _drawGBall(ctx, gBallX, gBallY, gBallR, data.accel_lat, data.accel_long);

        // Lap label (top-right corner)
        if (opts.lapLabel) {
            ctx.fillStyle = C.textSecondary || '#aaa';
            ctx.font = 'bold 11px system-ui, sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText(opts.lapLabel, dims.w - 8, 16);
        }
    }

    // ── Drawing helpers ───────────────────────────────

    function _drawSpeedometer(ctx, cx, cy, r, speed, refSpeed) {
        var startAngle = Math.PI * 0.75;     // 135 degrees
        var endAngle = Math.PI * 2.25;       // 405 degrees (270 deg arc)
        var totalAngle = endAngle - startAngle;

        // Background arc
        ctx.beginPath();
        ctx.arc(cx, cy, r, startAngle, endAngle);
        ctx.strokeStyle = 'rgba(255,255,255,0.08)';
        ctx.lineWidth = r * 0.12;
        ctx.lineCap = 'round';
        ctx.stroke();

        // Speed arc (colored: green → orange → red)
        var speedFrac = Math.max(0, Math.min(1, speed / MAX_SPEED_KPH));
        var speedAngle = startAngle + speedFrac * totalAngle;

        if (speedFrac > 0.01) {
            var grad = ctx.createConicGradient(startAngle, cx, cy);
            // Fallback for browsers without createConicGradient
            var color = _speedBarColor(speedFrac);

            ctx.beginPath();
            ctx.arc(cx, cy, r, startAngle, speedAngle);
            ctx.strokeStyle = color;
            ctx.lineWidth = r * 0.12;
            ctx.lineCap = 'round';
            ctx.stroke();
        }

        // Reference speed marker (dashed gold line)
        if (refSpeed && refSpeed > 0) {
            var refFrac = Math.min(1, refSpeed / MAX_SPEED_KPH);
            var refAngle = startAngle + refFrac * totalAngle;
            var outerR = r + r * 0.08;
            var innerR = r - r * 0.08;
            ctx.beginPath();
            ctx.moveTo(
                cx + Math.cos(refAngle) * innerR,
                cy + Math.sin(refAngle) * innerR
            );
            ctx.lineTo(
                cx + Math.cos(refAngle) * outerR,
                cy + Math.sin(refAngle) * outerR
            );
            ctx.strokeStyle = '#ffb347';
            ctx.lineWidth = 2;
            ctx.setLineDash([3, 2]);
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // Tick marks
        var tickCount = 6;
        for (var i = 0; i <= tickCount; i++) {
            var frac = i / tickCount;
            var angle = startAngle + frac * totalAngle;
            var inner = r - r * 0.15;
            var outer = r + r * 0.02;
            ctx.beginPath();
            ctx.moveTo(cx + Math.cos(angle) * inner, cy + Math.sin(angle) * inner);
            ctx.lineTo(cx + Math.cos(angle) * outer, cy + Math.sin(angle) * outer);
            ctx.strokeStyle = 'rgba(255,255,255,0.3)';
            ctx.lineWidth = 1;
            ctx.stroke();

            // Tick label
            var labelR = r - r * 0.3;
            var tickVal = Math.round(frac * MAX_SPEED_KPH);
            ctx.fillStyle = C.textMuted || '#777';
            ctx.font = (r * 0.14) + 'px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(tickVal, cx + Math.cos(angle) * labelR, cy + Math.sin(angle) * labelR);
        }

        // Center speed text
        ctx.fillStyle = '#fff';
        ctx.font = 'bold ' + (r * 0.5) + 'px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(Math.round(speed), cx, cy - r * 0.05);

        ctx.fillStyle = C.textMuted || '#777';
        ctx.font = (r * 0.18) + 'px system-ui, sans-serif';
        ctx.fillText('km/h', cx, cy + r * 0.25);
        ctx.textBaseline = 'alphabetic';
    }

    function _drawPedalBar(ctx, x, y, w, h, value, color, label) {
        value = Math.max(0, Math.min(1, value || 0));

        // Background
        ctx.fillStyle = 'rgba(255,255,255,0.05)';
        _roundRect(ctx, x, y, w, h, 4);
        ctx.fill();

        // Border
        ctx.strokeStyle = 'rgba(255,255,255,0.1)';
        ctx.lineWidth = 1;
        _roundRect(ctx, x, y, w, h, 4);
        ctx.stroke();

        // Fill (from bottom)
        if (value > 0.01) {
            var fillH = h * value;
            var fillY = y + h - fillH;

            ctx.fillStyle = color;
            ctx.globalAlpha = 0.8;
            _roundRect(ctx, x + 1, fillY, w - 2, fillH, 3);
            ctx.fill();
            ctx.globalAlpha = 1.0;
        }

        // Label below
        ctx.fillStyle = C.textMuted || '#777';
        ctx.font = 'bold 9px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(label, x + w / 2, y + h + 12);

        // Value % on top
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 10px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(Math.round(value * 100), x + w / 2, y - 4);
    }

    function _drawGBall(ctx, cx, cy, r, accelLat, accelLong) {
        var maxG = 1.5; // max G for display range

        // Background circle
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(255,255,255,0.03)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.1)';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Crosshair
        ctx.beginPath();
        ctx.moveTo(cx - r, cy);
        ctx.lineTo(cx + r, cy);
        ctx.moveTo(cx, cy - r);
        ctx.lineTo(cx, cy + r);
        ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        ctx.lineWidth = 0.5;
        ctx.stroke();

        // G-ball position (values already in G from DB)
        var gLat = accelLat || 0;
        var gLong = accelLong || 0;

        var dotX = cx + (gLat / maxG) * r * 0.85;
        var dotY = cy - (gLong / maxG) * r * 0.85;  // negative because Y is inverted

        // Clamp to circle
        var dx = dotX - cx;
        var dy = dotY - cy;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if (dist > r * 0.9) {
            dotX = cx + (dx / dist) * r * 0.9;
            dotY = cy + (dy / dist) * r * 0.9;
        }

        // Ball color based on total G
        var totalG = Math.sqrt(gLat * gLat + gLong * gLong);
        var gFrac = Math.min(1, totalG / maxG);
        var ballColor = _gBallColor(gFrac);

        // Glow
        ctx.beginPath();
        ctx.arc(dotX, dotY, 6, 0, Math.PI * 2);
        ctx.fillStyle = ballColor.replace(')', ',0.3)').replace('rgb', 'rgba');
        ctx.fill();

        // Ball
        ctx.beginPath();
        ctx.arc(dotX, dotY, 4, 0, Math.PI * 2);
        ctx.fillStyle = ballColor;
        ctx.fill();

        // "G" label
        ctx.fillStyle = C.textMuted || '#777';
        ctx.font = '9px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(totalG.toFixed(1) + 'G', cx, cy + r + 12);
    }

    // ── Utility ───────────────────────────────────────

    function _setup(canvas, ctx) {
        if (!canvas.parentElement) return null;
        var dpr = window.devicePixelRatio || 1;
        var w = canvas.parentElement.clientWidth;
        var h = canvas.parentElement.clientHeight;
        if (w < 50 || h < 50) return null;

        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        return { w: w, h: h };
    }

    function _normalizeData(data) {
        data = data || {};
        var aLong = data.accel_long || 0;
        // Speed comes from trace in m/s — convert to km/h for display
        var speedKph = (data.speed || 0) * 3.6;
        // Use session peaks if calibrated, else fall back to defaults
        var brakeMax = _peakBrakeG > 0 ? _peakBrakeG : MAX_BRAKE_G;
        var thrMax = _peakThrottleG > 0 ? _peakThrottleG : MAX_THROTTLE_G;
        return {
            speed: speedKph,
            accel_lat: data.accel_lat || 0,
            accel_long: aLong,
            brake: Math.max(0, Math.min(1, -aLong / brakeMax)),
            throttle: Math.max(0, Math.min(1, aLong / thrMax)),
        };
    }

    function _speedBarColor(frac) {
        if (frac < 0.5) {
            // Green → Yellow
            var t = frac / 0.5;
            var r = Math.round(63 + t * 192);
            var g = Math.round(185 + t * 70);
            var b = Math.round(80 - t * 80);
            return 'rgb(' + r + ',' + g + ',' + b + ')';
        }
        // Yellow → Red
        var t = (frac - 0.5) / 0.5;
        return 'rgb(255,' + Math.round(255 - t * 174) + ',' + Math.round(0) + ')';
    }

    function _gBallColor(frac) {
        if (frac < 0.4) return 'rgb(63,185,80)';
        if (frac < 0.7) return 'rgb(255,200,0)';
        return 'rgb(248,81,73)';
    }

    function _roundRect(ctx, x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
    }

    function destroy() {
        _lc.destroyAll();
        _canvas = null;
        _ctx = null;
    }

    window.ModuleManager.register('corner_replay_cockpit', {
        init: function () {},
        destroy: destroy
    });

})();
