/**
 * gg_diagram.js — G-G (lateral vs longitudinal acceleration) scatter plot.
 *
 * Fetches acceleration data from /api/session/<sid>/gg_data and renders
 * a Canvas-based scatter plot with:
 *   - Lateral G on X axis, Longitudinal G on Y axis
 *   - Density-based colour coding (cool->warm)
 *   - Friction circle envelope (dashed)
 *   - Zoom/pan support (scroll to zoom, drag to pan, double-click to reset)
 *   - Dark theme matching the telemetry dashboard
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};

    document.addEventListener('DOMContentLoaded', function () {
        var container = document.getElementById('gg-container');
        if (!container) return;

        var T = window.TELEMETRY;
        if (!T || !T.sessionId) return;

        var url = '/api/session/' + encodeURIComponent(T.sessionId) + '/gg_data';
        var _ggData = null;
        var _ggDrawn = false;

        // Fetch data eagerly (doesn't need visible DOM)
        FetchHelper.fetch(url)
            .then(function (data) {
                if (!data || !data.accel_lat || data.accel_lat.length === 0) {
                    var loadingEl = document.getElementById('gg-loading');
                    if (loadingEl) loadingEl.innerHTML = '<div class="no-data"><div class="no-data-icon">&#x1F3AF;</div><div class="no-data-text">No acceleration data available for this session.</div></div>';
                    return;
                }
                _ggData = data;
                _tryDraw();
            })
            .catch(function () {
                var loadingEl = document.getElementById('gg-loading');
                if (loadingEl) loadingEl.innerHTML = '<div class="no-data"><div class="no-data-icon">&#x26A0;&#xFE0F;</div><div class="no-data-text">Failed to load acceleration data.</div></div>';
            });

        function _tryDraw() {
            if (!_ggData) return;
            var canvas = document.getElementById('gg-diagram');
            if (!canvas || !canvas.parentElement) return;
            var w = canvas.parentElement.clientWidth;
            if (w < 100) return; // Tab still hidden or too small — will retry on resize/tab-switch
            var loadingEl = document.getElementById('gg-loading');
            if (loadingEl) loadingEl.style.display = 'none';
            canvas.style.display = '';
            _ggDrawn = true;
            drawGGDiagram(canvas, _ggData);
        }

        // Tab switching fires window resize — use it to draw when tab becomes visible
        window.addEventListener('resize', function () {
            if (_ggData && !_ggDrawn) _tryDraw();
        });

        // Also listen for tab:activate on the panel
        var panel = container.closest('.tab-panel');
        if (panel) {
            panel.addEventListener('tab:activate', function () {
                requestAnimationFrame(function () { _tryDraw(); });
            });
        }
    });

    function drawGGDiagram(canvas, data) {
        var aLat = data.accel_lat;
        var aLong = data.accel_long;
        if (!aLat || !aLong || aLat.length === 0) return;
        if (!canvas.parentElement) return;

        var ctx = canvas.getContext('2d');
        var dpr = window.devicePixelRatio || 1;
        canvas.style.width = '';
        var w = canvas.clientWidth || canvas.parentElement.clientWidth || 700;

        // If width is 0 (tab just became visible, layout pending), retry after frame
        if (w <= 0) {
            requestAnimationFrame(function () { drawGGDiagram(canvas, data); });
            return;
        }

        var h = 400;  // Taller for better readability
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        ctx.scale(dpr, dpr);

        var pad = { top: 35, right: 35, bottom: 55, left: 70 };
        var pW = w - pad.left - pad.right;
        var pH = h - pad.top - pad.bottom;

        // Data is already in G units from the pipeline.
        var latG = [];
        var longG = [];
        var maxG = 0;
        for (var i = 0; i < aLat.length; i++) {
            if (aLat[i] === null || aLong[i] === null) continue;
            if (!isFinite(aLat[i]) || !isFinite(aLong[i])) continue;
            var lg = aLat[i];
            var lo = aLong[i];
            latG.push(lg);
            longG.push(lo);
            var mag = Math.sqrt(lg * lg + lo * lo);
            if (mag > maxG) maxG = mag;
        }

        if (latG.length < 2) return;

        // Zoom / pan state.
        var baseAxisMax = Math.ceil(maxG * 1.15 * 10) / 10;
        if (baseAxisMax < 0.5) baseAxisMax = 0.5;
        var frictionR = maxG * 0.95;

        var zoomLevel = 1.0;
        var panX = 0;  // in G units
        var panY = 0;  // in G units
        var isDragging = false;
        var dragStartX = 0, dragStartY = 0;
        var dragStartPanX = 0, dragStartPanY = 0;

        function getAxisMax() { return baseAxisMax / zoomLevel; }

        function xToPixel(v) {
            var axisMax = getAxisMax();
            return pad.left + ((v - panX) + axisMax) / (2 * axisMax) * pW;
        }
        function yToPixel(v) {
            var axisMax = getAxisMax();
            return pad.top + pH - ((v - panY) + axisMax) / (2 * axisMax) * pH;
        }
        function pixelToG_X(px) {
            var axisMax = getAxisMax();
            return ((px - pad.left) / pW) * (2 * axisMax) - axisMax + panX;
        }
        function pixelToG_Y(py) {
            var axisMax = getAxisMax();
            return (1 - (py - pad.top) / pH) * (2 * axisMax) - axisMax + panY;
        }

        function render() {
            var axisMax = getAxisMax();

            // Clear.
            ctx.clearRect(0, 0, w, h);

            // Background.
            ctx.fillStyle = C.bgCard || '#1a1f2e';
            ctx.fillRect(0, 0, w, h);

            // Clip to plot area.
            ctx.save();
            ctx.beginPath();
            ctx.rect(pad.left, pad.top, pW, pH);
            ctx.clip();

            // Grid lines.
            ctx.strokeStyle = C.border || '#30363d';
            ctx.lineWidth = 0.5;
            var step = axisMax <= 0.3 ? 0.05 : axisMax <= 0.6 ? 0.1 : axisMax <= 1.2 ? 0.25 : 0.5;
            var gMin = -baseAxisMax * 2;
            var gMax = baseAxisMax * 2;
            for (var g = Math.ceil(gMin / step) * step; g <= gMax; g += step) {
                // Horizontal.
                var yy = yToPixel(g);
                if (yy >= pad.top && yy <= pad.top + pH) {
                    ctx.beginPath();
                    ctx.moveTo(pad.left, yy);
                    ctx.lineTo(pad.left + pW, yy);
                    ctx.stroke();
                }
                // Vertical.
                var xx = xToPixel(g);
                if (xx >= pad.left && xx <= pad.left + pW) {
                    ctx.beginPath();
                    ctx.moveTo(xx, pad.top);
                    ctx.lineTo(xx, pad.top + pH);
                    ctx.stroke();
                }
            }

            // Axes through origin.
            ctx.strokeStyle = C.textMuted || '#484f58';
            ctx.lineWidth = 1;
            var ox = xToPixel(0), oy = yToPixel(0);
            ctx.beginPath();
            ctx.moveTo(ox, pad.top);
            ctx.lineTo(ox, pad.top + pH);
            ctx.stroke();
            ctx.beginPath();
            ctx.moveTo(pad.left, oy);
            ctx.lineTo(pad.left + pW, oy);
            ctx.stroke();

            // Friction circle envelope.
            var cx = xToPixel(0);
            var cy = yToPixel(0);
            var rPx = (frictionR / axisMax) * (pW / 2);
            ctx.strokeStyle = 'rgba(139, 148, 158, 0.8)';
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 4]);
            ctx.beginPath();
            ctx.arc(cx, cy, rPx, 0, 2 * Math.PI);
            ctx.stroke();
            ctx.setLineDash([]);

            // Density grid for coloring.
            var gridSize = 40;
            var grid = {};
            for (var i = 0; i < latG.length; i++) {
                var px = xToPixel(latG[i]);
                var py = yToPixel(longG[i]);
                if (px < pad.left || px > pad.left + pW) continue;
                if (py < pad.top || py > pad.top + pH) continue;
                var gx = Math.floor(px / gridSize);
                var gy = Math.floor(py / gridSize);
                var key = gx + ',' + gy;
                grid[key] = (grid[key] || 0) + 1;
            }
            var maxDensity = 0;
            for (var k in grid) {
                if (grid[k] > maxDensity) maxDensity = grid[k];
            }

            // Draw points.
            var dotR = latG.length > 5000 ? 1.2 : latG.length > 1000 ? 1.8 : 2.5;
            for (var i = 0; i < latG.length; i++) {
                var px = xToPixel(latG[i]);
                var py = yToPixel(longG[i]);

                // Clip to chart area.
                if (px < pad.left || px > pad.left + pW) continue;
                if (py < pad.top || py > pad.top + pH) continue;

                var gx = Math.floor(px / gridSize);
                var gy = Math.floor(py / gridSize);
                var density = grid[gx + ',' + gy] || 1;
                var t = Math.min(1, density / Math.max(1, maxDensity * 0.6));

                ctx.fillStyle = densityColor(t);
                ctx.globalAlpha = 0.7;
                ctx.beginPath();
                ctx.arc(px, py, dotR, 0, 2 * Math.PI);
                ctx.fill();
            }
            ctx.globalAlpha = 1;

            // Friction circle label.
            ctx.fillStyle = C.textPrimary || '#c9d1d9';
            ctx.font = '12px -apple-system, sans-serif';
            ctx.textAlign = 'left';
            ctx.fillText(frictionR.toFixed(2) + 'G envelope', cx + rPx + 6, cy - rPx + 14);

            ctx.restore(); // End clip

            // Axis tick labels (outside clip).
            ctx.fillStyle = C.textPrimary || '#c9d1d9';
            ctx.font = '13px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            for (var g = Math.ceil(gMin / step) * step; g <= gMax; g += step) {
                if (Math.abs(g) < 0.001) continue;
                // X axis labels.
                var xp = xToPixel(g);
                if (xp >= pad.left && xp <= pad.left + pW) {
                    ctx.textBaseline = 'top';
                    ctx.textAlign = 'center';
                    ctx.fillText(g.toFixed(2) + 'G', xp, pad.top + pH + 8);
                }
                // Y axis labels.
                var yp = yToPixel(g);
                if (yp >= pad.top && yp <= pad.top + pH) {
                    ctx.textAlign = 'right';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(g.toFixed(2) + 'G', pad.left - 10, yp);
                }
            }

            // Axis titles (larger, more prominent).
            ctx.fillStyle = C.textPrimary || '#e6edf3';
            ctx.font = 'bold 14px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText('Lateral G', pad.left + pW / 2, h - 16);

            ctx.save();
            ctx.translate(16, pad.top + pH / 2);
            ctx.rotate(-Math.PI / 2);
            ctx.textBaseline = 'middle';
            ctx.fillText('Longitudinal G', 0, 0);
            ctx.restore();

            // Quadrant labels (larger, more visible).
            ctx.fillStyle = C.textSecondary || 'rgba(201, 209, 217, 0.5)';
            ctx.font = 'bold 12px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            var qCx = xToPixel(0), qCy = yToPixel(0);
            if (qCy > pad.top + 20 && qCy < pad.top + pH) {
                ctx.fillText('BRAKING', qCx, Math.max(pad.top + 16, qCy - pH * 0.35));
                ctx.fillText('ACCELERATION', qCx, Math.min(pad.top + pH - 12, qCy + pH * 0.35));
            }
            if (qCx > pad.left && qCx < pad.left + pW) {
                ctx.fillText('LEFT', Math.max(pad.left + 30, qCx - pW * 0.35), qCy);
                ctx.fillText('RIGHT', Math.min(pad.left + pW - 30, qCx + pW * 0.35), qCy);
            }

            // Zoom indicator.
            if (zoomLevel > 1.01) {
                ctx.fillStyle = C.accent || 'rgba(255, 107, 53, 0.8)';
                ctx.font = '11px -apple-system, sans-serif';
                ctx.textAlign = 'right';
                ctx.textBaseline = 'top';
                ctx.fillText('Zoom: ' + zoomLevel.toFixed(1) + 'x  (dbl-click to reset)', w - pad.right, pad.top + 4);
            }

            // Stats summary in top-left.
            ctx.fillStyle = C.textSecondary || 'rgba(201, 209, 217, 0.6)';
            ctx.font = '11px -apple-system, sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'top';
            ctx.fillText(latG.length + ' samples | Max: ' + maxG.toFixed(2) + 'G', pad.left + 4, pad.top + 4);
        }

        // Initial render.
        render();

        // Register __redraw for ResizeObserver
        canvas.__redraw = function() {
            canvas.style.width = '';
            w = canvas.clientWidth || canvas.parentElement.clientWidth || 700;
            canvas.width = w * dpr;
            canvas.height = h * dpr;
            canvas.style.width = w + 'px';
            canvas.style.height = h + 'px';
            ctx.setTransform(1, 0, 0, 1, 0, 0);
            ctx.scale(dpr, dpr);
            pW = w - pad.left - pad.right;
            render();
        };

        // ── Zoom (mouse wheel) ────────────────────────
        canvas.addEventListener('wheel', function (e) {
            e.preventDefault();
            var rect = canvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            // Focus zoom on mouse position.
            var gxBefore = pixelToG_X(mx);
            var gyBefore = pixelToG_Y(my);

            var delta = e.deltaY > 0 ? 0.85 : 1.18;
            zoomLevel = Math.max(0.5, Math.min(10, zoomLevel * delta));

            var gxAfter = pixelToG_X(mx);
            var gyAfter = pixelToG_Y(my);

            // Adjust pan so the point under the mouse stays fixed.
            panX += gxBefore - gxAfter;
            panY += gyBefore - gyAfter;

            render();
        }, { passive: false });

        // ── Pan (drag) ───────────────────────────────
        canvas.addEventListener('mousedown', function (e) {
            isDragging = true;
            dragStartX = e.clientX;
            dragStartY = e.clientY;
            dragStartPanX = panX;
            dragStartPanY = panY;
            canvas.style.cursor = 'grabbing';
        });

        window.addEventListener('mousemove', function (e) {
            if (!isDragging) return;
            var axisMax = getAxisMax();
            var dx = e.clientX - dragStartX;
            var dy = e.clientY - dragStartY;
            panX = dragStartPanX - dx / pW * (2 * axisMax);
            panY = dragStartPanY + dy / pH * (2 * axisMax);
            render();
        });

        window.addEventListener('mouseup', function () {
            if (isDragging) {
                isDragging = false;
                canvas.style.cursor = 'crosshair';
            }
        });

        // ── Double-click to reset ────────────────────
        canvas.addEventListener('dblclick', function () {
            zoomLevel = 1.0;
            panX = 0;
            panY = 0;
            render();
        });

        canvas.style.cursor = 'crosshair';

        // ── Keyboard zoom/pan ────────────────────────
        canvas.setAttribute('tabindex', '0');
        canvas.style.outline = 'none'; // Prevent focus outline on canvas
        canvas.addEventListener('keydown', function (e) {
            var axisMax = getAxisMax();
            var panStep = axisMax * 0.15; // Pan by 15% of visible range
            var handled = true;

            switch (e.key) {
                case '+':
                case '=':
                    // Zoom in (same multiplier as scroll up)
                    zoomLevel = Math.min(10, zoomLevel * 1.18);
                    break;
                case '-':
                case '_':
                    // Zoom out (same multiplier as scroll down)
                    zoomLevel = Math.max(0.5, zoomLevel * 0.85);
                    break;
                case 'ArrowLeft':
                    panX -= panStep;
                    break;
                case 'ArrowRight':
                    panX += panStep;
                    break;
                case 'ArrowUp':
                    panY += panStep;
                    break;
                case 'ArrowDown':
                    panY -= panStep;
                    break;
                case '0':
                    // Reset zoom/pan (same as double-click)
                    zoomLevel = 1.0;
                    panX = 0;
                    panY = 0;
                    break;
                default:
                    handled = false;
                    break;
            }

            if (handled) {
                e.preventDefault();
                render();
            }
        });

        // ── Hover tooltip ────────────────────────────
        var existing = canvas.parentElement.querySelector('[data-gg-tooltip]');
        if (existing) existing.remove();
        var ggTooltip = document.createElement('div');
        ggTooltip.setAttribute('data-gg-tooltip', '1');
        ggTooltip.style.cssText = 'position:absolute;display:none;background:' + (C.bgSecondary || '#161b22') + ';color:' + (C.textPrimary || '#e6edf3') + ';' +
            'padding:6px 10px;border-radius:6px;font-size:12px;pointer-events:none;' +
            'border:1px solid ' + (C.border || '#30363d') + ';z-index:10;white-space:nowrap;';
        canvas.parentElement.appendChild(ggTooltip);

        canvas.addEventListener('mousemove', function (e) {
            if (isDragging) {
                ggTooltip.style.display = 'none';
                return;
            }
            var rect = canvas.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            if (mx < pad.left || mx > pad.left + pW || my < pad.top || my > pad.top + pH) {
                ggTooltip.style.display = 'none';
                return;
            }

            var gx = pixelToG_X(mx);
            var gy = pixelToG_Y(my);

            // Find nearest point.
            var bestIdx = -1, bestDist = Infinity;
            for (var i = 0; i < latG.length; i++) {
                var dx = latG[i] - gx;
                var dy = longG[i] - gy;
                var d = dx * dx + dy * dy;
                if (d < bestDist) {
                    bestDist = d;
                    bestIdx = i;
                }
            }

            if (bestIdx >= 0 && bestDist < 0.05) {
                var mag = Math.sqrt(latG[bestIdx] * latG[bestIdx] + longG[bestIdx] * longG[bestIdx]);
                ggTooltip.innerHTML = 'Lat: <strong>' + latG[bestIdx].toFixed(3) + 'G</strong> | ' +
                    'Long: <strong>' + longG[bestIdx].toFixed(3) + 'G</strong> | ' +
                    'Total: <strong>' + mag.toFixed(3) + 'G</strong>';
                ggTooltip.style.display = 'block';
                ggTooltip.style.left = (mx + 12) + 'px';
                ggTooltip.style.top = (my - 30) + 'px';
            } else {
                ggTooltip.style.display = 'none';
            }
        });

        canvas.addEventListener('mouseleave', function () {
            ggTooltip.style.display = 'none';
        });

        // Resize handler.
        var _ggResizeTimer;
        window.addEventListener('resize', function () {
            clearTimeout(_ggResizeTimer);
            _ggResizeTimer = setTimeout(function () {
                canvas.style.width = '';
                w = canvas.clientWidth || canvas.parentElement.clientWidth || 700;
                canvas.width = w * dpr;
                canvas.height = h * dpr;
                canvas.style.width = w + 'px';
                canvas.style.height = h + 'px';
                ctx.setTransform(1, 0, 0, 1, 0, 0);
                ctx.scale(dpr, dpr);
                pW = w - pad.left - pad.right;
                render();
            }, 150);
        });
    }

    function densityColor(t) {
        // Blue (sparse) -> Cyan -> Green -> Yellow -> Red (dense).
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

})();
