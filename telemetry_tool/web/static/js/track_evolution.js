/**
 * track_evolution.js — Interactive track evolution chart.
 *
 * Shows best lap time progression over time for a given track,
 * with condition-based coloring and driver annotations.
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    var COLORS = {
        dry:     C.green || '#3fb950',
        wet:     C.blue || '#58a6ff',
        damp:    C.yellow || '#d29922',
        drying:  C.purple || '#bc8cff',
        default: C.textSecondary || '#8b949e',
        grid:    'rgba(48, 54, 61, 0.6)',
        text:    C.textSecondary || '#8b949e',
        accent:  C.accent || '#ff6b35',
        bg:      C.bgCard || '#1a1f2e',
    };

    var POINT_RADIUS = 5;
    var HOVER_RADIUS = 8;

    /**
     * Draw a nice axis range: return {min, max, step} for the given data range.
     */
    function niceRange(dataMin, dataMax, targetTicks) {
        targetTicks = targetTicks || 6;
        var range = dataMax - dataMin;
        if (range <= 0) range = 1;
        var rough = range / targetTicks;
        var mag = Math.pow(10, Math.floor(Math.log10(rough)));
        var residual = rough / mag;
        var nice;
        if (residual <= 1.5) nice = 1;
        else if (residual <= 3) nice = 2;
        else if (residual <= 7) nice = 5;
        else nice = 10;
        var step = nice * mag;
        var nMin = Math.floor(dataMin / step) * step;
        var nMax = Math.ceil(dataMax / step) * step;
        return { min: nMin, max: nMax, step: step };
    }

    function conditionColor(state) {
        if (!state) return COLORS.default;
        var s = state.toLowerCase();
        return COLORS[s] || COLORS.default;
    }

    /**
     * Initialise the track evolution chart.
     * @param {string} canvasId  - ID of the canvas element.
     * @param {string} trackId   - Track ID for API call.
     */
    function init(canvasId, trackId) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;

        var ctx = canvas.getContext('2d');
        var container = canvas.parentElement;
        var data = null;
        var hoverIdx = -1;

        // Tooltip element
        var tooltip = document.createElement('div');
        tooltip.className = 'chart-tooltip';
        tooltip.style.cssText = 'position:absolute;display:none;background:' + (C.bgSecondary || '#161b22') + ';color:' + (C.textPrimary || '#e6edf3') + ';' +
            'padding:8px 12px;border-radius:6px;font-size:12px;pointer-events:none;' +
            'border:1px solid ' + (C.border || '#30363d') + ';z-index:10;white-space:nowrap;';
        container.appendChild(tooltip);

        canvas.__redraw = function() { resize(); };

        function fetchData() {
            FetchHelper.fetch('/api/track/' + encodeURIComponent(trackId) + '/evolution')
                .then(function (json) {
                    data = json;
                    resize();
                })
                .catch(function (err) {
                    console.warn('Track evolution data load failed:', err);
                });
        }

        function resize() {
            var rect = container.getBoundingClientRect();
            var dpr = window.devicePixelRatio || 1;
            canvas.width = rect.width * dpr;
            canvas.height = 320 * dpr;
            canvas.style.width = rect.width + 'px';
            canvas.style.height = '320px';
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            draw();
        }

        function draw() {
            if (!data || !data.sessions || data.sessions.length === 0) {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = COLORS.text;
                ctx.font = '14px system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('No evolution data available', canvas.width / 4, canvas.height / 4);
                return;
            }

            var sessions = data.sessions;
            var w = parseFloat(canvas.style.width);
            var h = parseFloat(canvas.style.height);

            var pad = { top: 20, right: 30, bottom: 55, left: 65 };
            var plotW = w - pad.left - pad.right;
            var plotH = h - pad.top - pad.bottom;

            ctx.clearRect(0, 0, w, h);

            // Data ranges
            var times = sessions.map(function (s) { return s.best_time_s; });
            var yAxis = niceRange(Math.min.apply(null, times), Math.max.apply(null, times), 6);

            // X positions (evenly spaced by session index)
            function xPos(i) { return pad.left + (i / Math.max(1, sessions.length - 1)) * plotW; }
            function yPos(t) { return pad.top + (1 - (t - yAxis.min) / (yAxis.max - yAxis.min)) * plotH; }

            // Grid lines (Y)
            ctx.strokeStyle = COLORS.grid;
            ctx.lineWidth = 1;
            ctx.font = '11px system-ui, sans-serif';
            ctx.fillStyle = COLORS.text;
            ctx.textAlign = 'right';
            ctx.textBaseline = 'middle';

            for (var t = yAxis.min; t <= yAxis.max + yAxis.step * 0.001; t += yAxis.step) {
                var y = yPos(t);
                ctx.beginPath();
                ctx.moveTo(pad.left, y);
                ctx.lineTo(w - pad.right, y);
                ctx.stroke();
                ctx.fillText(t.toFixed(2) + 's', pad.left - 8, y);
            }

            // X-axis date labels
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            var maxLabels = Math.floor(plotW / 80);
            var labelStep = Math.max(1, Math.ceil(sessions.length / maxLabels));
            for (var i = 0; i < sessions.length; i += labelStep) {
                var x = xPos(i);
                var dateStr = sessions[i].date || '';
                if (dateStr.length > 10) dateStr = dateStr.substring(0, 10);
                ctx.save();
                ctx.translate(x, h - pad.bottom + 8);
                ctx.rotate(-Math.PI / 6);
                ctx.fillText(dateStr, 0, 0);
                ctx.restore();
            }

            // Connecting line
            ctx.strokeStyle = 'rgba(139, 148, 158, 0.4)';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            for (var i = 0; i < sessions.length; i++) {
                var px = xPos(i);
                var py = yPos(sessions[i].best_time_s);
                if (i === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
            }
            ctx.stroke();

            // Points
            for (var i = 0; i < sessions.length; i++) {
                var px = xPos(i);
                var py = yPos(sessions[i].best_time_s);
                var isHover = (i === hoverIdx);
                var r = isHover ? HOVER_RADIUS : POINT_RADIUS;
                var color = conditionColor(sessions[i].track_state);

                ctx.beginPath();
                ctx.arc(px, py, r, 0, Math.PI * 2);
                ctx.fillStyle = color;
                ctx.fill();
                ctx.strokeStyle = isHover ? '#fff' : 'rgba(0,0,0,0.3)';
                ctx.lineWidth = isHover ? 2 : 1;
                ctx.stroke();
            }

            // Best time annotation
            var bestIdx = 0;
            var bestTime = sessions[0].best_time_s;
            for (var i = 1; i < sessions.length; i++) {
                if (sessions[i].best_time_s < bestTime) {
                    bestTime = sessions[i].best_time_s;
                    bestIdx = i;
                }
            }
            ctx.fillStyle = COLORS.accent;
            ctx.font = 'bold 11px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillText('PB ' + bestTime.toFixed(3) + 's', xPos(bestIdx), yPos(bestTime) - 10);

            // Y-axis label
            ctx.save();
            ctx.translate(14, pad.top + plotH / 2);
            ctx.rotate(-Math.PI / 2);
            ctx.fillStyle = COLORS.text;
            ctx.font = '12px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Best Lap Time (s)', 0, 0);
            ctx.restore();

            // Legend
            var legendItems = [];
            var seenStates = {};
            for (var i = 0; i < sessions.length; i++) {
                var st = (sessions[i].track_state || 'unknown').toLowerCase();
                if (!seenStates[st]) {
                    seenStates[st] = true;
                    legendItems.push({ label: st, color: conditionColor(st) });
                }
            }
            var lx = pad.left + 10;
            ctx.font = '11px system-ui, sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            for (var i = 0; i < legendItems.length; i++) {
                ctx.beginPath();
                ctx.arc(lx, pad.top + 12, 4, 0, Math.PI * 2);
                ctx.fillStyle = legendItems[i].color;
                ctx.fill();
                ctx.fillStyle = COLORS.text;
                ctx.fillText(legendItems[i].label, lx + 8, pad.top + 12);
                lx += ctx.measureText(legendItems[i].label).width + 24;
            }
        }

        // Hover
        canvas.addEventListener('mousemove', function (e) {
            if (!data || !data.sessions || data.sessions.length === 0) return;
            var rect = canvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;
            var w = parseFloat(canvas.style.width);
            var h = parseFloat(canvas.style.height);
            var pad = { top: 20, right: 30, bottom: 55, left: 65 };
            var plotW = w - pad.left - pad.right;
            var plotH = h - pad.top - pad.bottom;
            var sessions = data.sessions;
            var times = sessions.map(function (s) { return s.best_time_s; });
            var yAxis = niceRange(Math.min.apply(null, times), Math.max.apply(null, times), 6);

            function xPos(i) { return pad.left + (i / Math.max(1, sessions.length - 1)) * plotW; }
            function yPos(t) { return pad.top + (1 - (t - yAxis.min) / (yAxis.max - yAxis.min)) * plotH; }

            var closest = -1;
            var closestDist = 20;
            for (var i = 0; i < sessions.length; i++) {
                var dx = mx - xPos(i);
                var dy = my - yPos(sessions[i].best_time_s);
                var d = Math.sqrt(dx * dx + dy * dy);
                if (d < closestDist) {
                    closestDist = d;
                    closest = i;
                }
            }

            if (closest !== hoverIdx) {
                hoverIdx = closest;
                draw();
            }

            if (closest >= 0) {
                var s = sessions[closest];
                tooltip.innerHTML = '<strong>' + esc(s.date || '?') + '</strong><br>' +
                    'Driver: ' + esc(s.driver || '?') + '<br>' +
                    'Time: ' + s.best_time_s.toFixed(3) + 's<br>' +
                    'Score: ' + (s.score != null ? s.score.toFixed(1) : '—') + '<br>' +
                    'Condition: ' + esc(s.track_state || '?');
                tooltip.style.display = 'block';
                var tx = Math.min(e.clientX - rect.left + 12, w - 160);
                var ty = e.clientY - rect.top - 60;
                tooltip.style.left = tx + 'px';
                tooltip.style.top = ty + 'px';
            } else {
                tooltip.style.display = 'none';
            }
        });

        canvas.addEventListener('mouseleave', function () {
            hoverIdx = -1;
            tooltip.style.display = 'none';
            draw();
        });

        // Click navigates to session
        canvas.addEventListener('click', function (e) {
            if (hoverIdx >= 0 && data && data.sessions[hoverIdx]) {
                window.location = '/sessions/' + data.sessions[hoverIdx].session_id;
            }
        });
        canvas.style.cursor = 'pointer';

        var _evolResizeTimer;
        window.addEventListener('resize', function () {
            clearTimeout(_evolResizeTimer);
            _evolResizeTimer = setTimeout(resize, 150);
        });
        fetchData();
    }

    window.TrackEvolution = { init: init };
})();
