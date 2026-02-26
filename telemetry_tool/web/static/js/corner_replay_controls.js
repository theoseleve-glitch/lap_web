/**
 * corner_replay_controls.js — Playback controls for corner replay.
 *
 * Manages: play/pause, scrubber, speed selector, corner nav pills,
 * mode tabs, and lap selection dropdowns.
 *
 * Public API:
 *   window.CornerReplayControls.init(opts)
 *   window.CornerReplayControls.setProgress(0..1)
 *   window.CornerReplayControls.setCorners(cornerPositions)
 *   window.CornerReplayControls.setLaps(lapNumbers, lapTimes, bestLap)
 *   window.CornerReplayControls.destroy()
 */
(function () {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var _opts = {};
    var _corners = [];
    var _activeCornerIdx = 0;
    var _draggingScrubber = false;

    window.CornerReplayControls = {
        init: init,
        setProgress: setProgress,
        setCorners: setCorners,
        setLaps: setLaps,
        destroy: destroy,
    };

    function init(opts) {
        _opts = opts || {};

        // Mode tabs
        var tabs = document.querySelectorAll('.cr-mode-tab');
        tabs.forEach(function (tab) {
            _lc.addListener(tab, 'click', function () {
                tabs.forEach(function (t) { t.classList.remove('active'); });
                tab.classList.add('active');
                if (_opts.onModeChange) _opts.onModeChange(tab.dataset.crMode);
            });
        });

        // Play/pause
        var playBtn = document.getElementById('cr-play-btn');
        if (playBtn) {
            _lc.addListener(playBtn, 'click', function () {
                if (_opts.onTogglePlay) _opts.onTogglePlay();
            });
        }

        // Speed buttons
        var speedBtns = document.querySelectorAll('.cr-speed-btn');
        speedBtns.forEach(function (btn) {
            _lc.addListener(btn, 'click', function () {
                speedBtns.forEach(function (b) { b.classList.remove('active'); });
                btn.classList.add('active');
                if (_opts.onSpeedChange) _opts.onSpeedChange(parseFloat(btn.dataset.crSpeed));
            });
        });

        // Corner nav buttons
        var prevBtn = document.getElementById('cr-prev-corner');
        var nextBtn = document.getElementById('cr-next-corner');
        if (prevBtn) _lc.addListener(prevBtn, 'click', function () { _navCorner(-1); });
        if (nextBtn) _lc.addListener(nextBtn, 'click', function () { _navCorner(1); });

        // Scrubber interactions
        _initScrubber();

        // Lap A/B selects
        var lapASelect = document.getElementById('cr-lap-a-select');
        var lapBSelect = document.getElementById('cr-lap-b-select');
        if (lapASelect) _lc.addListener(lapASelect, 'change', function () {
            if (_opts.onLapAChange) _opts.onLapAChange(parseInt(lapASelect.value, 10));
        });
        if (lapBSelect) _lc.addListener(lapBSelect, 'change', function () {
            if (_opts.onLapBChange) _opts.onLapBChange(parseInt(lapBSelect.value, 10));
        });

        // Keyboard shortcuts
        _lc.addListener(document, 'keydown', _onKeyDown);
    }

    function setProgress(p) {
        if (_draggingScrubber) return;
        var pct = Math.max(0, Math.min(1, p)) * 100;
        var fill = document.getElementById('cr-scrubber-fill');
        var thumb = document.getElementById('cr-scrubber-thumb');
        if (fill) fill.style.width = pct + '%';
        if (thumb) thumb.style.left = pct + '%';
    }

    function setCorners(cornerPositions) {
        _corners = cornerPositions || [];
        _activeCornerIdx = 0;
        var pillsEl = document.getElementById('cr-corner-pills');
        if (!pillsEl) return;

        // Clear
        while (pillsEl.firstChild) pillsEl.removeChild(pillsEl.firstChild);

        _corners.forEach(function (c, i) {
            var pill = document.createElement('button');
            pill.className = 'cr-corner-pill' + (i === 0 ? ' active' : '');
            pill.textContent = c.label || ('P' + c.corner_id);
            pill.title = c.label || ('Corner ' + c.corner_id);
            pill.dataset.idx = i;
            _lc.addListener(pill, 'click', function () {
                _selectCorner(i);
            });
            pillsEl.appendChild(pill);
        });

        _updateNavBtns();
    }

    function setLaps(lapNumbers, lapTimes, bestLap) {
        var lapASelect = document.getElementById('cr-lap-a-select');
        var lapBSelect = document.getElementById('cr-lap-b-select');
        if (!lapASelect || !lapBSelect) return;

        // Clear both selects using safe DOM methods
        while (lapASelect.firstChild) lapASelect.removeChild(lapASelect.firstChild);
        while (lapBSelect.firstChild) lapBSelect.removeChild(lapBSelect.firstChild);

        // Sort laps by time (best first)
        var sorted = lapNumbers.slice().sort(function (a, b) {
            var ta = lapTimes[String(a)] || 9999;
            var tb = lapTimes[String(b)] || 9999;
            return ta - tb;
        });

        sorted.forEach(function (ln) {
            var timeStr = lapTimes[String(ln)] ? lapTimes[String(ln)].toFixed(3) + 's' : '';
            var label = 'Lap ' + ln + (timeStr ? ' (' + timeStr + ')' : '');
            if (ln === bestLap) label += ' *';

            var optA = document.createElement('option');
            optA.value = ln;
            optA.textContent = label;
            lapASelect.appendChild(optA);

            var optB = document.createElement('option');
            optB.value = ln;
            optB.textContent = label;
            lapBSelect.appendChild(optB);
        });

        // Default: Lap A = best, Lap B = worst lap for contrast
        if (bestLap) lapASelect.value = bestLap;
        if (sorted.length >= 2) {
            lapBSelect.value = sorted[sorted.length - 1];
        }
    }

    /** Update play button appearance */
    function setPlaying(playing) {
        var btn = document.getElementById('cr-play-btn');
        if (!btn) return;
        // Clear and set text safely
        while (btn.firstChild) btn.removeChild(btn.firstChild);
        btn.textContent = playing ? '\u23F8' : '\u25B6';
    }
    window.CornerReplayControls.setPlaying = setPlaying;

    /** Show/hide Lap B dropdown based on mode */
    function showLapB(show) {
        var group = document.getElementById('cr-lap-b-group');
        if (group) {
            group.classList.toggle('cr-hidden', !show);
        }
    }
    window.CornerReplayControls.showLapB = showLapB;

    /** Get current active corner index */
    function getActiveCornerIdx() { return _activeCornerIdx; }
    window.CornerReplayControls.getActiveCornerIdx = getActiveCornerIdx;

    /** Get selected lap numbers */
    function getLapA() {
        var el = document.getElementById('cr-lap-a-select');
        return el ? parseInt(el.value, 10) : null;
    }
    function getLapB() {
        var el = document.getElementById('cr-lap-b-select');
        return el ? parseInt(el.value, 10) : null;
    }
    window.CornerReplayControls.getLapA = getLapA;
    window.CornerReplayControls.getLapB = getLapB;

    function destroy() {
        _lc.destroyAll();
    }

    // ── Internal ──────────────────────────────────────

    function _selectCorner(idx) {
        if (idx < 0 || idx >= _corners.length) return;
        _activeCornerIdx = idx;

        // Update pills
        var pills = document.querySelectorAll('.cr-corner-pill');
        pills.forEach(function (p, i) {
            p.classList.toggle('active', i === idx);
        });

        _updateNavBtns();
        if (_opts.onCornerChange) _opts.onCornerChange(idx, _corners[idx]);
    }

    function _navCorner(delta) {
        _selectCorner(_activeCornerIdx + delta);
    }

    function _updateNavBtns() {
        var prev = document.getElementById('cr-prev-corner');
        var next = document.getElementById('cr-next-corner');
        if (prev) prev.disabled = _activeCornerIdx <= 0;
        if (next) next.disabled = _activeCornerIdx >= _corners.length - 1;
    }

    function _initScrubber() {
        var track = document.getElementById('cr-scrubber-track');
        if (!track) return;

        function _scrubTo(e) {
            var rect = track.getBoundingClientRect();
            var p = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
            setProgress(p);
            if (_opts.onScrub) _opts.onScrub(p);
        }

        _lc.addListener(track, 'mousedown', function (e) {
            _draggingScrubber = true;
            _scrubTo(e);
        });

        _lc.addListener(document, 'mousemove', function (e) {
            if (!_draggingScrubber) return;
            _scrubTo(e);
        });

        _lc.addListener(document, 'mouseup', function () {
            _draggingScrubber = false;
        });

        // Touch support
        _lc.addListener(track, 'touchstart', function (e) {
            _draggingScrubber = true;
            _scrubTo(e.touches[0]);
        }, { passive: true });

        _lc.addListener(document, 'touchmove', function (e) {
            if (!_draggingScrubber) return;
            _scrubTo(e.touches[0]);
        }, { passive: true });

        _lc.addListener(document, 'touchend', function () {
            _draggingScrubber = false;
        });
    }

    function _onKeyDown(e) {
        // Only if replay section is visible
        var root = document.getElementById('corner-replay-root');
        if (!root || root.offsetParent === null) return;

        if (e.code === 'Space' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'SELECT') {
            e.preventDefault();
            if (_opts.onTogglePlay) _opts.onTogglePlay();
        } else if (e.code === 'ArrowLeft' && !e.ctrlKey && e.target.tagName !== 'INPUT') {
            e.preventDefault();
            _navCorner(-1);
        } else if (e.code === 'ArrowRight' && !e.ctrlKey && e.target.tagName !== 'INPUT') {
            e.preventDefault();
            _navCorner(1);
        }
    }

    window.ModuleManager.register('corner_replay_controls', {
        init: function () {},
        destroy: destroy
    });

})();
