/**
 * corner_replay.js — Main orchestrator for corner replay system.
 *
 * State machine, data fetching, animation loop (rAF), mode switching.
 * Coordinates CornerReplayMap, CornerReplayCockpit, CornerReplayControls.
 *
 * Public API:
 *   window.CornerReplay.init(sessionId)
 */
(function () {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var _sessionId = null;
    var _initialized = false;

    var _state = {
        mode: 'review',       // 'review' | 'split' | 'top3'
        playing: false,
        playbackSpeed: 1.0,
        progress: 0,          // 0..1 within current corner window
        cornerWindow: null,   // { startIdx, endIdx, startDist, endDist, cornerId }
        lapA: null,
        lapB: null,
        top3Laps: [],
        traces: {},           // cached { lapNum: traceData }
        cornerPositions: [],
        cornerMetrics: {},
        lapTimes: {},
        bestLapNum: null,
        allLaps: [],          // sorted lap numbers
        hasPedalData: false,  // true only when CSV had real brake/throttle
        hasSteeringData: false,
    };

    var _rafId = null;
    var _lastFrameTime = 0;

    // Corner window padding in index points (approx 80m before/after key corner)
    var CORNER_WINDOW_PAD = 120;

    window.CornerReplay = { init: init, destroy: destroy };
    window.ModuleManager.register('corner_replay', { init: function() {}, destroy: destroy });

    function init(sessionId) {
        if (_initialized) return;
        _sessionId = sessionId;

        var root = document.getElementById('corner-replay-root');
        if (!root) return;

        // Lazy init — wait until Corners tab is activated
        var panel = root.closest('.tab-panel');
        if (panel) {
            panel.addEventListener('tab:activate', function () {
                if (!_initialized) _bootstrap();
            });
            // If tab is already active (restored from sessionStorage)
            if (window.TELEMETRY && window.TELEMETRY.isTabActive && window.TELEMETRY.isTabActive('corners')) {
                _bootstrap();
            }
        }
    }

    function _bootstrap() {
        if (_initialized) return;
        _initialized = true;

        // Init sub-modules
        CornerReplayMap.init('cr-map-canvas');
        CornerReplayCockpit.init('cr-cockpit-canvas');

        CornerReplayControls.init({
            onModeChange: _onModeChange,
            onTogglePlay: _togglePlay,
            onSpeedChange: function (s) { _state.playbackSpeed = s; },
            onCornerChange: _onCornerChange,
            onScrub: _onScrub,
            onLapAChange: _onLapAChange,
            onLapBChange: _onLapBChange,
        });

        // Fetch initial data (best lap + 2nd best for comparison)
        var T = window.TELEMETRY || {};
        var gpsLaps = T.gpsLaps || [];
        var bestLap = T.bestLap || gpsLaps[0];

        if (gpsLaps.length < 2) {
            _hideSection();
            return;
        }

        // Request all GPS laps (up to 5)
        var lapsToFetch = gpsLaps.slice(0, 5);
        var url = '/api/session/' + encodeURIComponent(_sessionId) +
            '/corner-replay-data?laps=' + lapsToFetch.join(',');

        FetchHelper.fetch(url)
            .then(function (data) {
                if (!data || !data.traces || Object.keys(data.traces).length === 0) {
                    _hideSection();
                    return;
                }

                _state.traces = data.traces;
                _state.cornerMetrics = data.corner_metrics || {};
                _state.lapTimes = data.lap_times || {};
                _state.bestLapNum = data.best_lap_number;
                _state.hasPedalData = !!data.has_pedal_data;
                _state.hasSteeringData = !!data.has_steering_data;

                // Calibrate brake/throttle bars to session peaks
                var peakBrake = 0, peakThrottle = 0;
                Object.keys(data.traces).forEach(function (ln) {
                    var pts = data.traces[ln];
                    for (var i = 0; i < pts.length; i++) {
                        var al = pts[i].accel_long || 0;
                        if (-al > peakBrake) peakBrake = -al;
                        if (al > peakThrottle) peakThrottle = al;
                    }
                });
                if (peakBrake > 0 || peakThrottle > 0) {
                    CornerReplayCockpit.setSessionPeaks(peakBrake, peakThrottle);
                }

                // Build sorted lap list
                _state.allLaps = Object.keys(data.traces).map(Number).sort(function (a, b) {
                    var ta = _state.lapTimes[String(a)] || 9999;
                    var tb = _state.lapTimes[String(b)] || 9999;
                    return ta - tb;
                });

                // Register traces with map module
                Object.keys(_state.traces).forEach(function (ln) {
                    CornerReplayMap.setTrace(parseInt(ln, 10), _state.traces[ln]);
                });

                // Set defaults — ensure lapA is a lap that actually has trace data
                var bestInTraces = _state.traces[String(_state.bestLapNum)]
                    ? _state.bestLapNum : null;
                _state.lapA = bestInTraces || _state.allLaps[0];
                _state.lapB = _state.allLaps.length > 1
                    ? _state.allLaps[_state.allLaps.length - 1]
                    : _state.allLaps[0];
                _state.top3Laps = _state.allLaps.slice(0, 3);

                // Use ONLY user-defined key corners (not auto-detected)
                _loadKeyCorners(data.corner_positions || []);
            })
            .catch(function (err) {
                _hideSection();
            });

        // Resize handler
        var _resizeTimer;
        _lc.addListener(window, 'resize', function () {
            clearTimeout(_resizeTimer);
            _resizeTimer = _lc.addTimer(function () {
                if (_initialized) _renderFrame();
            }, 150);
        });
    }

    // ── Mode switching ────────────────────────────────

    function _onModeChange(mode) {
        _state.mode = mode;
        _state.playing = false;
        _state.progress = 0;
        _cancelAnimation();
        CornerReplayControls.setPlaying(false);
        CornerReplayControls.setProgress(0);

        var viewport = document.getElementById('cr-viewport');
        var cockpitPanel = document.getElementById('cr-cockpit-panel');
        var singleCockpit = document.getElementById('cr-cockpit-canvas');
        var splitCockpit = document.getElementById('cr-split-cockpit');
        var top3Legend = document.getElementById('cr-top3-legend');
        var deltaBadge = document.getElementById('cr-delta-badge');

        // Reset visibility
        if (cockpitPanel) cockpitPanel.style.display = '';
        if (singleCockpit) singleCockpit.style.display = '';
        if (splitCockpit) splitCockpit.style.display = 'none';
        if (top3Legend) top3Legend.style.display = 'none';
        if (deltaBadge) deltaBadge.classList.remove('visible');
        if (viewport) viewport.classList.remove('cr-mode-top3');

        CornerReplayControls.showLapB(false);

        if (mode === 'split') {
            if (singleCockpit) singleCockpit.style.display = 'none';
            if (splitCockpit) splitCockpit.style.display = '';
            CornerReplayControls.showLapB(true);
        } else if (mode === 'top3') {
            if (cockpitPanel) cockpitPanel.style.display = 'none';
            if (viewport) viewport.classList.add('cr-mode-top3');
            if (top3Legend) {
                top3Legend.style.display = '';
                _updateTop3Legend();
            }
        }

        _renderFrame();
    }

    // ── Playback ──────────────────────────────────────

    function _togglePlay() {
        _state.playing = !_state.playing;
        CornerReplayControls.setPlaying(_state.playing);

        if (_state.playing) {
            // Reset if at end
            if (_state.progress >= 0.99) _state.progress = 0;
            _lastFrameTime = performance.now();
            _animate();
        } else {
            _cancelAnimation();
        }
    }

    function _animate() {
        _rafId = _lc.addRaf(function (now) {
            if (!_state.playing) { _rafId = null; return; }

            var dt = (now - _lastFrameTime) / 1000; // seconds
            _lastFrameTime = now;

            // Estimate corner duration from distance/speed
            var duration = _estimateCornerDuration();
            if (duration <= 0) duration = 3; // fallback 3 seconds

            var step = (dt * _state.playbackSpeed) / duration;
            _state.progress = Math.min(1, _state.progress + step);

            CornerReplayControls.setProgress(_state.progress);
            _renderFrame();

            if (_state.progress >= 1) {
                _state.playing = false;
                CornerReplayControls.setPlaying(false);
            } else {
                _animate();
            }
        });
    }

    function _cancelAnimation() {
        if (_rafId) {
            cancelAnimationFrame(_rafId);
            _rafId = null;
        }
    }

    function _onScrub(p) {
        _state.progress = p;
        _renderFrame();
    }

    // ── Corner selection ──────────────────────────────

    function _onCornerChange(idx, corner) {
        _selectCornerByIndex(idx);
    }

    function _selectCornerByIndex(idx) {
        if (idx < 0 || idx >= _state.cornerPositions.length) return;

        var corner = _state.cornerPositions[idx];
        _state.progress = 0;
        _state.playing = false;
        _cancelAnimation();
        CornerReplayControls.setPlaying(false);
        CornerReplayControls.setProgress(0);

        // Compute corner window from distance along track
        var bpDist = corner.brake_point_m || corner.dist_m || 0;
        var trace = _state.traces[String(_state.lapA)] ||
            _state.traces[Object.keys(_state.traces)[0]];
        if (!trace || !trace.distances) return;

        var dists = trace.distances;
        // Find index closest to the corner's distance
        var centerIdx = _bisect(dists, bpDist);

        var startIdx = Math.max(0, centerIdx - CORNER_WINDOW_PAD);
        var endIdx = Math.min(dists.length - 1, centerIdx + CORNER_WINDOW_PAD);

        _state.cornerWindow = {
            startIdx: startIdx,
            endIdx: endIdx,
            startDist: dists[startIdx] || 0,
            endDist: dists[endIdx] || 0,
            cornerId: corner.corner_id,
        };

        // Update corner name display
        var nameEl = document.getElementById('cr-corner-name');
        if (nameEl) {
            nameEl.textContent = (corner.label || 'Corner ' + corner.corner_id);
        }

        _renderFrame();
    }

    // ── Lap changes ───────────────────────────────────

    function _onLapAChange(lapNum) {
        _state.lapA = lapNum;
        _state.progress = 0;
        CornerReplayControls.setProgress(0);

        // Re-fetch if trace not loaded
        if (!_state.traces[String(lapNum)]) {
            _fetchAdditionalLap(lapNum, function () { _renderFrame(); });
        } else {
            _renderFrame();
        }
    }

    function _onLapBChange(lapNum) {
        _state.lapB = lapNum;
        _state.progress = 0;
        CornerReplayControls.setProgress(0);

        if (!_state.traces[String(lapNum)]) {
            _fetchAdditionalLap(lapNum, function () { _renderFrame(); });
        } else {
            _renderFrame();
        }
    }

    function _fetchAdditionalLap(lapNum, cb) {
        var url = '/api/session/' + encodeURIComponent(_sessionId) +
            '/corner-replay-data?laps=' + lapNum;
        FetchHelper.fetch(url).then(function (data) {
            if (data && data.traces && data.traces[String(lapNum)]) {
                _state.traces[String(lapNum)] = data.traces[String(lapNum)];
                CornerReplayMap.setTrace(lapNum, data.traces[String(lapNum)]);
                if (data.corner_metrics && data.corner_metrics[String(lapNum)]) {
                    _state.cornerMetrics[String(lapNum)] = data.corner_metrics[String(lapNum)];
                }
                if (data.lap_times) {
                    Object.keys(data.lap_times).forEach(function (k) {
                        _state.lapTimes[k] = data.lap_times[k];
                    });
                }
            }
            if (cb) cb();
        }).catch(function () { if (cb) cb(); });
    }

    // ── Render ────────────────────────────────────────

    function _renderFrame() {
        if (!_state.cornerWindow) return;
        var cw = _state.cornerWindow;
        var p = _state.progress;

        if (_state.mode === 'review') {
            _renderReviewMode(cw, p);
        } else if (_state.mode === 'split') {
            _renderSplitMode(cw, p);
        } else if (_state.mode === 'top3') {
            _renderTop3Mode(cw, p);
        }
    }

    function _renderReviewMode(cw, p) {
        var lapA = _state.lapA;
        var bestLap = _state.bestLapNum;

        // Build reference laps (other laps that have traces)
        var refLaps = [];
        _state.allLaps.forEach(function (ln) {
            if (ln === lapA) return;
            var tA = _state.lapTimes[String(lapA)] || 9999;
            var tRef = _state.lapTimes[String(ln)] || 9999;
            refLaps.push({
                lapNum: ln,
                faster: tRef < tA,
            });
        });

        // Map
        CornerReplayMap.renderReview(cw, p, lapA, refLaps.slice(0, 3));

        // Cockpit
        var data = CornerReplayMap.getDataAtProgress(lapA, cw, p);
        var cornerLabel = _getCornerLabel(cw.cornerId);
        CornerReplayCockpit.render(data, {
            cornerName: cornerLabel,
            lapLabel: 'Lap ' + lapA,
            refSpeed: _getRefSpeed(bestLap, cw, p),
            showPedals: _state.hasPedalData,
        });
    }

    function _renderSplitMode(cw, p) {
        var lapA = _state.lapA;
        var lapB = _state.lapB;

        // Time delta calculation
        var deltaText = _computeTimeDelta(lapA, lapB, cw, p);

        // Map with dual dots
        CornerReplayMap.renderDual(cw, p, lapA, lapB, deltaText);

        // Dual cockpits
        var dataA = CornerReplayMap.getDataAtProgress(lapA, cw, p);
        var dataB = CornerReplayMap.getDataAtProgress(lapB, cw, p);

        CornerReplayCockpit.renderCompact('cr-cockpit-a', dataA, {
            lapLabel: 'Lap ' + lapA,
            showPedals: _state.hasPedalData,
        });
        CornerReplayCockpit.renderCompact('cr-cockpit-b', dataB, {
            lapLabel: 'Lap ' + lapB,
            showPedals: _state.hasPedalData,
        });

        // Update split labels
        var labelA = document.getElementById('cr-split-label-a');
        var labelB = document.getElementById('cr-split-label-b');
        if (labelA) labelA.textContent = 'Lap ' + lapA;
        if (labelB) labelB.textContent = 'Lap ' + lapB;

        // Update delta badge
        var badge = document.getElementById('cr-delta-badge');
        if (badge && deltaText) {
            badge.textContent = deltaText;
            badge.className = 'cr-delta-badge visible ' +
                (deltaText.charAt(0) === '-' ? 'ahead' : 'behind');
        }
    }

    function _renderTop3Mode(cw, p) {
        CornerReplayMap.renderTriple(cw, p, _state.top3Laps);
    }

    // ── Helpers ───────────────────────────────────────

    function _estimateCornerDuration() {
        if (!_state.cornerWindow) return 3;
        var cw = _state.cornerWindow;
        var trace = _state.traces[String(_state.lapA)];
        if (!trace || !trace.speeds) return 3;

        var totalTime = 0;
        var speeds = trace.speeds;
        var dists = trace.distances;

        for (var i = cw.startIdx; i < cw.endIdx && i < speeds.length - 1; i++) {
            var ds = (dists[i + 1] || 0) - (dists[i] || 0);
            var avgSpd = ((speeds[i] || 1) + (speeds[i + 1] || 1)) / 2;
            // speeds are already in m/s from gps_traces
            if (avgSpd > 0.5) {
                totalTime += ds / avgSpd;
            }
        }

        return Math.max(1, totalTime);
    }

    function _computeTimeDelta(lapA, lapB, cw, progress) {
        // Simple approach: compare cumulative distance/time between traces
        var traceA = _state.traces[String(lapA)];
        var traceB = _state.traces[String(lapB)];
        if (!traceA || !traceB) return '';

        var idx = Math.round(cw.startIdx + progress * (cw.endIdx - cw.startIdx));

        // Estimate time to reach current index for each lap
        function _timeToIdx(trace, targetIdx) {
            var t = 0;
            var speeds = trace.speeds || [];
            var dists = trace.distances || [];
            var start = cw.startIdx;
            for (var i = start; i < targetIdx && i < speeds.length - 1; i++) {
                var ds = (dists[i + 1] || 0) - (dists[i] || 0);
                var avgSpd = ((speeds[i] || 1) + (speeds[i + 1] || 1)) / 2;
                if (avgSpd > 0.5) t += ds / avgSpd;
            }
            return t;
        }

        var timeA = _timeToIdx(traceA, idx);
        var timeB = _timeToIdx(traceB, idx);
        var delta = timeB - timeA; // positive = A is faster (ahead)

        if (Math.abs(delta) < 0.001) return '';
        var sign = delta > 0 ? '+' : '-';
        return sign + Math.abs(delta).toFixed(2) + 's';
    }

    function _getRefSpeed(refLap, cw, progress) {
        if (!refLap) return null;
        var data = CornerReplayMap.getDataAtProgress(refLap, cw, progress);
        // speed is in m/s, convert to km/h for cockpit display
        return data ? data.speed * 3.6 : null;
    }

    function _getCornerLabel(cornerId) {
        for (var i = 0; i < _state.cornerPositions.length; i++) {
            if (_state.cornerPositions[i].corner_id === cornerId) {
                return _state.cornerPositions[i].label || ('Corner ' + cornerId);
            }
        }
        return 'Corner ' + cornerId;
    }

    /**
     * Load user-defined key corners from the track DB.
     * Falls back to auto-detected corners only if no key corners are defined.
     * @param {Array} autoCorners - auto-detected corner_positions from API
     */
    function _loadKeyCorners(autoCorners) {
        var T = window.TELEMETRY || {};
        if (!T.trackId) {
            // No track — fall back to auto-detected
            _applyCorners(autoCorners);
            return;
        }

        FetchHelper.fetch('/api/track/' + encodeURIComponent(T.trackId) + '/key-corners')
            .then(function (keyCorners) {
                if (Array.isArray(keyCorners) && keyCorners.length > 0) {
                    // Convert key corner format to corner_positions format
                    var positions = keyCorners.map(function (kc) {
                        return {
                            corner_id: kc.corner_id,
                            label: kc.label || ('P' + kc.corner_id),
                            lat: kc.lat,
                            lon: kc.lon,
                            brake_point_m: kc.dist_m || 0,
                            dist_m: kc.dist_m || 0,
                        };
                    });
                    _applyCorners(positions);
                } else {
                    // No user-defined corners — show prompt
                    _showNoCorners();
                }
            })
            .catch(function () {
                // API error — show prompt
                _showNoCorners();
            });
    }

    /**
     * Apply corner positions and finish bootstrap.
     */
    function _applyCorners(positions) {
        _state.cornerPositions = positions;
        CornerReplayMap.setCorners(positions);

        if (positions.length === 0) {
            _showNoCorners();
            return;
        }

        CornerReplayControls.setCorners(positions);
        CornerReplayControls.setLaps(
            _state.allLaps, _state.lapTimes, _state.lapA
        );

        _selectCornerByIndex(0);
        _renderFrame();
    }

    /**
     * Show a message when no user-defined corners exist.
     */
    function _showNoCorners() {
        var pills = document.getElementById('cr-corner-pills');
        if (pills) {
            while (pills.firstChild) pills.removeChild(pills.firstChild);
            var msg = document.createElement('span');
            msg.className = 'text-muted text-sm';
            msg.style.padding = '4px 8px';
            msg.textContent = 'Define key corners in the section below to enable replay';
            pills.appendChild(msg);
        }
        // Still show laps even without corners
        CornerReplayControls.setLaps(
            _state.allLaps, _state.lapTimes, _state.lapA
        );
    }

    function _updateTop3Legend() {
        var legend = document.getElementById('cr-top3-legend');
        if (!legend) return;

        // Clear
        while (legend.firstChild) legend.removeChild(legend.firstChild);

        var colors = ['#ffb347', '#00c8ff', '#3fb950'];
        _state.top3Laps.forEach(function (ln, i) {
            var item = document.createElement('div');
            item.className = 'cr-legend-item';

            var swatch = document.createElement('span');
            swatch.className = 'cr-legend-swatch';
            swatch.style.backgroundColor = colors[i] || '#aaa';
            item.appendChild(swatch);

            var label = document.createElement('span');
            label.textContent = 'Lap ' + ln;
            item.appendChild(label);

            var time = document.createElement('span');
            time.className = 'cr-legend-time';
            var t = _state.lapTimes[String(ln)];
            time.textContent = t ? t.toFixed(3) + 's' : '';
            item.appendChild(time);

            legend.appendChild(item);
        });
    }

    function _bisect(arr, val) {
        var lo = 0, hi = arr.length;
        while (lo < hi) {
            var mid = (lo + hi) >>> 1;
            if ((arr[mid] || 0) < val) lo = mid + 1;
            else hi = mid;
        }
        return Math.min(lo, arr.length - 1);
    }

    function _hideSection() {
        var root = document.getElementById('corner-replay-root');
        if (root) root.classList.add('cr-hidden');
    }

    function destroy() {
        _state.playing = false;
        _initialized = false;
        _lc.destroyAll();
        _state.traces = {};
        _state.cornerMetrics = {};
        _state.lapTimes = {};
    }

    // ── Auto-init on DOMContentLoaded ─────────────────

    document.addEventListener('DOMContentLoaded', function () {
        var T = window.TELEMETRY;
        if (T && T.sessionId) {
            CornerReplay.init(T.sessionId);
        }
    });

})();
