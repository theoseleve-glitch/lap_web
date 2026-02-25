/**
 * race_strategy_live.js — Live dashboard: client-side timer, 2s polling,
 * 6-component rendering.
 */
(function() {
    'use strict';

    var root = document.getElementById('rs-live-root');
    if (!root) return;

    var RACE_ID       = root.getAttribute('data-race-id');
    var RACE_DURATION = parseInt(root.getAttribute('data-race-duration'), 10) || 0;
    var RACE_START    = root.getAttribute('data-race-start');
    var FUEL_AUTONOMY = parseInt(root.getAttribute('data-fuel-autonomy'), 10) || 0;

    var DRIVER_COLORS = ['#58a6ff','#f78166','#7ee787','#d2a8ff','#ffa657','#79c0ff'];
    var POLL_INTERVAL = 2000;

    var state = null;  // latest server state

    // ── Helpers ──────────────────────────────────

    function fmtTime(s) {
        if (s == null || isNaN(s)) return '--:--:--';
        s = Math.max(0, Math.round(s));
        var h = Math.floor(s / 3600);
        var m = Math.floor((s % 3600) / 60);
        var sec = s % 60;
        return h + ':' + pad2(m) + ':' + pad2(sec);
    }

    function fmtShort(s) {
        if (s == null || isNaN(s)) return '--:--';
        s = Math.max(0, Math.round(s));
        var m = Math.floor(s / 60);
        var sec = s % 60;
        return m + ':' + pad2(sec);
    }

    function pad2(n) { return n < 10 ? '0' + n : '' + n; }

    function getElapsed() {
        if (!RACE_START) return 0;
        var start = new Date(RACE_START).getTime();
        return Math.max(0, Math.floor((Date.now() - start) / 1000));
    }

    function driverColor(driverOrder) {
        return DRIVER_COLORS[(driverOrder - 1) % DRIVER_COLORS.length];
    }

    function setText(id, text) {
        var el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function clearChildren(el) {
        while (el.firstChild) el.removeChild(el.firstChild);
    }

    // ── 1. Race Timer ────────────────────────────

    function updateTimer() {
        var elapsed = getElapsed();
        var remaining = Math.max(0, RACE_DURATION - elapsed);
        var pct = RACE_DURATION > 0 ? Math.min(100, (elapsed / RACE_DURATION) * 100) : 0;

        setText('rs-timer-elapsed', fmtTime(elapsed));
        setText('rs-timer-remaining', 'Remaining: ' + fmtTime(remaining));

        var bar = document.getElementById('rs-timer-bar');
        if (bar) {
            bar.style.width = pct + '%';
            if (pct > 90)      bar.style.background = 'var(--red, #f85149)';
            else if (pct > 75) bar.style.background = 'var(--yellow, #d29922)';
            else               bar.style.background = 'var(--green)';
        }

        if (state && state.stints) {
            var completed = state.stints.filter(function(s) { return s.status === 'completed'; }).length;
            var active = state.stints.filter(function(s) { return s.status === 'active'; }).length;
            setText('rs-stint-current', '' + (completed + active));
            setText('rs-stint-total', '' + state.stints.length);
        }
    }

    // ── 2. Fuel & Ballast ────────────────────────

    function updateFuel() {
        if (!state || !state.active_stint) return;
        var elapsed = getElapsed();
        var stintElapsed = elapsed - (state.active_stint.actual_start_s || 0);

        var fuelPct = 100;
        if (FUEL_AUTONOMY > 0) {
            fuelPct = Math.max(0, Math.min(100, 100 - (stintElapsed / FUEL_AUTONOMY) * 100));
        }

        var bar = document.getElementById('rs-fuel-bar');
        if (bar) {
            bar.style.width = fuelPct + '%';
            bar.textContent = Math.round(fuelPct) + '%';
            bar.className = 'rs-fuel-bar ' +
                (fuelPct < 15 ? 'rs-fuel-critical' : fuelPct < 30 ? 'rs-fuel-low' : 'rs-fuel-ok');
        }

        if (FUEL_AUTONOMY > 0) {
            var remainingFuelS = Math.max(0, FUEL_AUTONOMY - stintElapsed);
            setText('rs-fuel-autonomy', fmtShort(remainingFuelS));
        } else {
            setText('rs-fuel-autonomy', 'N/A');
        }

        setText('rs-ballast', (state.active_stint.ballast_kg || 0).toFixed(1) + ' kg');

        // Total weight (rough estimate)
        if (state.race.empty_kart_kg && state.active_stint.driver_weight_kg) {
            var total = state.race.empty_kart_kg +
                        (state.active_stint.driver_weight_kg || 0) +
                        (state.active_stint.ballast_kg || 0);
            setText('rs-total-weight', total.toFixed(1) + ' kg');
        }
    }

    // ── 3. Current & Next Driver ─────────────────

    function updateDrivers() {
        if (!state) return;
        var elapsed = getElapsed();

        if (state.active_stint) {
            setText('rs-active-driver', state.active_stint.driver_name);
            var stintElapsed = elapsed - (state.active_stint.actual_start_s || 0);
            setText('rs-stint-elapsed', fmtShort(stintElapsed));

            var maxStint = state.active_stint.planned_duration_s || 0;
            setText('rs-stint-max', fmtShort(maxStint));

            var pct = maxStint > 0 ? Math.min(100, (stintElapsed / maxStint) * 100) : 0;
            var stintBar = document.getElementById('rs-stint-bar');
            if (stintBar) {
                stintBar.style.width = pct + '%';
                stintBar.className = 'rs-fuel-bar ' +
                    (pct > 90 ? 'rs-fuel-critical' : pct > 75 ? 'rs-fuel-low' : 'rs-fuel-ok');
            }
        } else {
            setText('rs-active-driver', 'No active stint');
            setText('rs-stint-elapsed', '--:--');
        }

        if (state.next_stint) {
            setText('rs-next-driver', state.next_stint.driver_name);
            var info = document.getElementById('rs-next-info');
            if (info) {
                var cum = (state.driver_cumulative[state.next_stint.driver_id] || 0);
                info.textContent = ' (cumulative: ' + fmtShort(cum) + ')';
            }
        } else {
            setText('rs-next-driver', 'Last stint');
            setText('rs-next-info', '');
        }
    }

    // ── 4. Stint Timeline ────────────────────────

    function updateTimeline() {
        if (!state || !state.stints) return;
        var container = document.getElementById('rs-stint-timeline');
        var legend = document.getElementById('rs-stint-legend');
        if (!container) return;

        clearChildren(container);

        var totalDuration = state.stints.reduce(function(sum, s) {
            return sum + (s.planned_duration_s || 0);
        }, 0);

        state.stints.forEach(function(s) {
            var block = document.createElement('div');
            block.className = 'rs-stint-block';
            if (s.status === 'completed') block.className += ' rs-stint-completed';
            else if (s.status === 'active') block.className += ' rs-stint-active';
            else block.className += ' rs-stint-planned';

            var driverIdx = 0;
            if (state.drivers) {
                for (var i = 0; i < state.drivers.length; i++) {
                    if (state.drivers[i].id === s.driver_id) {
                        driverIdx = (state.drivers[i].driver_order || 1) - 1;
                        break;
                    }
                }
            }
            block.style.background = DRIVER_COLORS[driverIdx % DRIVER_COLORS.length];
            block.style.flex = '' + (s.planned_duration_s || 1);
            block.textContent = (s.driver_name || '').substring(0, 3);
            container.appendChild(block);
        });

        // Legend
        if (legend && state.drivers) {
            clearChildren(legend);
            state.drivers.forEach(function(d) {
                var span = document.createElement('span');
                var swatch = document.createElement('span');
                swatch.className = 'rs-legend-swatch';
                swatch.style.background = driverColor(d.driver_order);
                span.appendChild(swatch);
                span.appendChild(document.createTextNode(d.driver_name));
                legend.appendChild(span);
            });
        }
    }

    // ── 5. Stint Log ─────────────────────────────

    function updateStintLog() {
        if (!state || !state.stints) return;
        var tbody = document.getElementById('rs-stint-log-body');
        if (!tbody) return;

        clearChildren(tbody);

        state.stints.forEach(function(s) {
            var tr = document.createElement('tr');
            if (s.status === 'active') tr.className = 'rs-active-row';
            else if (s.status === 'completed') tr.className = 'rs-completed-row';

            var planned = s.planned_duration_s || 0;
            var actual = s.actual_duration_s || 0;
            var delta = actual ? actual - planned : null;

            var cells = [
                '' + s.stint_order,
                s.driver_name,
                fmtShort(planned),
                s.status === 'completed' ? fmtShort(actual) : (s.status === 'active' ? 'running' : '—'),
                delta !== null ? (delta >= 0 ? '+' : '') + Math.round(delta) + 's' : '—',
                (s.ballast_kg || 0).toFixed(1) + ' kg',
                s.notes || ''
            ];

            cells.forEach(function(text) {
                var td = document.createElement('td');
                td.textContent = text;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
    }

    // ── 6. Race Summary ──────────────────────────

    function updateSummary() {
        if (!state) return;
        var elapsed = getElapsed();
        var remaining = Math.max(0, RACE_DURATION - elapsed);
        setText('rs-summary-time', fmtShort(elapsed) + ' / ' + fmtShort(remaining));

        var pitCount = state.pit_stops ? state.pit_stops.filter(function(p) {
            return p.actual_at_s != null;
        }).length : 0;
        setText('rs-summary-pits', '' + pitCount);

        // Health: compare actual elapsed to planned schedule
        if (state.active_stint) {
            var plannedEnd = state.active_stint.planned_end_s || 0;
            var diff = elapsed - plannedEnd;
            if (Math.abs(diff) < 60) setText('rs-summary-health', 'ON PLAN');
            else if (diff < 0) setText('rs-summary-health', 'AHEAD');
            else setText('rs-summary-health', 'BEHIND');
        }

        // Driver time bars
        var barsEl = document.getElementById('rs-driver-bars');
        if (barsEl && state.drivers) {
            clearChildren(barsEl);

            var maxTime = 0;
            state.drivers.forEach(function(d) {
                var t = state.driver_cumulative[d.id] || 0;
                if (t > maxTime) maxTime = t;
            });
            // Include active stint time
            if (state.active_stint) {
                var activeTime = elapsed - (state.active_stint.actual_start_s || 0);
                var activeCum = (state.driver_cumulative[state.active_stint.driver_id] || 0) + activeTime;
                if (activeCum > maxTime) maxTime = activeCum;
            }

            state.drivers.forEach(function(d) {
                var cumTime = state.driver_cumulative[d.id] || 0;
                if (state.active_stint && state.active_stint.driver_id === d.id) {
                    cumTime += elapsed - (state.active_stint.actual_start_s || 0);
                }
                var pct = maxTime > 0 ? (cumTime / maxTime) * 100 : 0;

                var row = document.createElement('div');
                row.className = 'rs-driver-bar-row';

                var nameEl = document.createElement('div');
                nameEl.className = 'rs-driver-bar-name';
                nameEl.textContent = d.driver_name;

                var trackEl = document.createElement('div');
                trackEl.className = 'rs-driver-bar-track';
                var fillEl = document.createElement('div');
                fillEl.className = 'rs-driver-bar-fill';
                fillEl.style.width = pct + '%';
                fillEl.style.background = driverColor(d.driver_order);
                trackEl.appendChild(fillEl);

                var timeEl = document.createElement('div');
                timeEl.className = 'rs-driver-bar-time';
                timeEl.textContent = fmtShort(cumTime);

                row.appendChild(nameEl);
                row.appendChild(trackEl);
                row.appendChild(timeEl);
                barsEl.appendChild(row);
            });
        }
    }

    // ── Polling ──────────────────────────────────

    function fetchState() {
        fetch('/race-strategy/' + RACE_ID + '/api/state')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) return;
                state = data;
                updateTimeline();
                updateStintLog();
            })
            .catch(function() {});
    }

    // ── Actions ──────────────────────────────────

    var endBtn = document.getElementById('rs-btn-end-stint');
    if (endBtn) {
        endBtn.addEventListener('click', function() {
            if (!confirm('End current stint?')) return;
            fetch('/race-strategy/' + RACE_ID + '/api/stint/end', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ driver_change: true, refueled: true })
            })
            .then(function(r) { return r.json(); })
            .then(function() { fetchState(); });
        });
    }

    var reoptBtn = document.getElementById('rs-btn-reoptimize');
    if (reoptBtn) {
        reoptBtn.addEventListener('click', function() {
            if (!confirm('Re-optimize remaining stints?')) return;
            fetch('/race-strategy/' + RACE_ID + '/api/reoptimize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(function(r) { return r.json(); })
            .then(function() { fetchState(); });
        });
    }

    // ── Init ─────────────────────────────────────

    fetchState();

    // Client-side timer tick (1s)
    setInterval(function() {
        updateTimer();
        updateFuel();
        updateDrivers();
        updateSummary();
    }, 1000);

    // Server poll (2s)
    setInterval(fetchState, POLL_INTERVAL);

})();
