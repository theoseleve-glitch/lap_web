/**
 * corner_replay_cockpit.js — Virtual cockpit canvas for corner replay.
 *
 * Renders: speedometer arc gauge, vertical brake/throttle bars,
 * mini G-force ball, and corner info overlay.
 *
 * Brake/throttle derived from accel_long:
 *   brake   = clamp(-accel_long / 12, 0, 1)
 *   throttle = clamp(accel_long / 8, 0, 1)
 *
 * Public API:
 *   window.CornerReplayCockpit.init(canvasId)
 *   window.CornerReplayCockpit.render(data, opts)
 *   window.CornerReplayCockpit.renderCompact(canvasId, data, opts)
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {
        bgCard: '#1e1e2e', border: '#333', textPrimary: '#e0e0e0',
        textSecondary: '#aaa', textMuted: '#777', accent: '#f97316',
    };

    var MAX_BRAKE_G = 12.0;    // m/s^2 for full brake bar
    var MAX_THROTTLE_G = 8.0;  // m/s^2 for full throttle bar
    var MAX_SPEED_KPH = 120;   // speedometer max for karts

    var _canvas, _ctx;

    window.CornerReplayCockpit = {
        init: init,
        render: render,
        renderCompact: renderCompact,
    };

    function init(canvasId) {
        _canvas = document.getElementById(canvasId);
        if (!_canvas) return;
        _ctx = _canvas.getContext('2d');
    }

    /**
     * Render full cockpit on the main canvas.
     * data: { speed, accel_lat, accel_long, brake, throttle }
     * opts: { cornerName, refSpeed, lapLabel }
     */
    function render(data, opts) {
        if (!_canvas || !_canvas.parentElement) return;
        var dims = _setup(_canvas, _ctx);
        if (!dims) return;

        var ctx = _ctx;
        opts = opts || {};
        data = _normalizeData(data);

        // Background
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, dims.w, dims.h);

        // Layout: speedometer top-center, bars left, G-ball right-bottom
        var centerX = dims.w / 2;
        var speedoR = Math.min(dims.w * 0.28, dims.h * 0.35);
        var speedoCY = speedoR + 30;

        _drawSpeedometer(ctx, centerX, speedoCY, speedoR, data.speed, opts.refSpeed);

        // Brake bar (left side)
        var barW = 22;
        var barH = dims.h * 0.52;
        var barY = 30;
        _drawPedalBar(ctx, 25, barY, barW, barH, data.brake, '#f85149', 'BRK');
        _drawPedalBar(ctx, 25 + barW + 10, barY, barW, barH, data.throttle, '#3fb950', 'THR');

        // G-force ball (bottom right)
        var gBallR = Math.min(dims.w * 0.15, 55);
        var gBallX = dims.w - gBallR - 20;
        var gBallY = dims.h - gBallR - 20;
        _drawGBall(ctx, gBallX, gBallY, gBallR, data.accel_lat, data.accel_long);

        // Corner info
        if (opts.cornerName) {
            ctx.fillStyle = C.textPrimary || '#e0e0e0';
            ctx.font = 'bold 13px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(opts.cornerName, centerX, dims.h - 12);
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
     */
    function renderCompact(canvasId, data, opts) {
        var canvas = document.getElementById(canvasId);
        if (!canvas || !canvas.parentElement) return;
        var ctx = canvas.getContext('2d');
        var dims = _setup(canvas, ctx);
        if (!dims) return;

        opts = opts || {};
        data = _normalizeData(data);

        // Background
        ctx.fillStyle = C.bgCard || '#1a1f2e';
        ctx.fillRect(0, 0, dims.w, dims.h);

        // Compact layout: speedometer left-center, bars right, G-ball far right
        var speedoR = Math.min(dims.w * 0.2, dims.h * 0.35);
        var speedoCX = speedoR + 15;
        var speedoCY = dims.h / 2;

        _drawSpeedometer(ctx, speedoCX, speedoCY, speedoR, data.speed, opts.refSpeed);

        // Brake/throttle bars (center)
        var barW = 16;
        var barH = dims.h * 0.6;
        var barX = speedoCX + speedoR + 20;
        var barY = (dims.h - barH) / 2;
        _drawPedalBar(ctx, barX, barY, barW, barH, data.brake, '#f85149', 'B');
        _drawPedalBar(ctx, barX + barW + 6, barY, barW, barH, data.throttle, '#3fb950', 'T');

        // G-ball (right side)
        var gBallR = Math.min(dims.w * 0.12, 35);
        var gBallX = dims.w - gBallR - 12;
        var gBallY = dims.h / 2;
        _drawGBall(ctx, gBallX, gBallY, gBallR, data.accel_lat, data.accel_long);

        // Speed text overlay (large, top-center)
        ctx.fillStyle = C.textPrimary || '#e0e0e0';
        ctx.font = 'bold 11px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(Math.round(data.speed) + ' kph', speedoCX + speedoR + 20, 18);
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

        // G-ball position
        // accel_lat is in m/s2, convert to G and normalize
        var gLat = (accelLat || 0) / 9.81;   // convert to G
        var gLong = (accelLong || 0) / 9.81;

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
        return {
            speed: speedKph,
            accel_lat: data.accel_lat || 0,
            accel_long: aLong,
            brake: Math.max(0, Math.min(1, -aLong / MAX_BRAKE_G)),
            throttle: Math.max(0, Math.min(1, aLong / MAX_THROTTLE_G)),
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

})();
