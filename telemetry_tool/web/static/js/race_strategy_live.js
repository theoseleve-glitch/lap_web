/**
 * race_strategy_live.js — Live dashboard: client-side timer, 2s polling,
 * 6-component rendering.
 */
(function() {
    'use strict';

    var root = document.getElementById('rs-live-root');
    if (!root) return;

    var _lc = window.LifecycleHelpers.create();

    var RACE_ID       = root.getAttribute('data-race-id');
    var RACE_DURATION = parseInt(root.getAttribute('data-race-duration'), 10) || 0;
    var RACE_START    = root.getAttribute('data-race-start');
    var FUEL_AUTONOMY = parseInt(root.getAttribute('data-fuel-autonomy'), 10) || 0;

    var PIT_OPEN  = parseInt(root.getAttribute('data-pit-open'), 10) || 0;
    var PIT_CLOSE_BEFORE_END = parseInt(root.getAttribute('data-pit-close'), 10) || 0;
    var PIT_CLOSE = PIT_CLOSE_BEFORE_END ? RACE_DURATION - PIT_CLOSE_BEFORE_END : 0;

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

    function driverColor(id, byOrder) {
        // Try to get DB-stored color from state.drivers
        if (state && state.drivers) {
            var driver;
            if (byOrder) {
                for (var i = 0; i < state.drivers.length; i++) {
                    if (state.drivers[i].driver_order === id) { driver = state.drivers[i]; break; }
                }
            } else {
                for (var i = 0; i < state.drivers.length; i++) {
                    if (state.drivers[i].id === id) { driver = state.drivers[i]; break; }
                }
            }
            if (driver && driver.color_hex) return driver.color_hex;
            if (driver) return DRIVER_COLORS[(driver.driver_order - 1) % DRIVER_COLORS.length];
        }
        // Fallback to positional palette
        var idx = (typeof id === 'number' ? id - 1 : 0);
        return DRIVER_COLORS[idx % DRIVER_COLORS.length];
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

        var display = document.getElementById('rs-timer-elapsed');
        if (display) {
            if (pct > 90) {
                display.style.color = 'var(--red)';
                display.style.textShadow = '0 0 30px rgba(248, 113, 113, 0.3), 0 0 60px rgba(248, 113, 113, 0.1)';
            } else if (pct > 75) {
                display.style.color = 'var(--yellow)';
                display.style.textShadow = '0 0 30px rgba(251, 191, 36, 0.3), 0 0 60px rgba(251, 191, 36, 0.1)';
            } else {
                display.style.color = 'var(--green)';
                display.style.textShadow = '0 0 30px rgba(52, 211, 153, 0.3), 0 0 60px rgba(52, 211, 153, 0.1)';
            }
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

        var hasFuelModel = state.fuel_model && state.fuel_model.full_tank_kg > 0;
        var hasCurrentFuel = state.current_fuel_kg != null && state.current_fuel_kg >= 0;

        // --- Real-time fuel gauge (kg-based) ---
        var gaugeFill = document.getElementById('rs-fuel-gauge-fill');
        if (gaugeFill) {
            if (hasCurrentFuel && hasFuelModel) {
                var fuelKg = state.current_fuel_kg;
                var fullTank = state.fuel_model.full_tank_kg;
                var fuelPctKg = Math.max(0, Math.min(100, (fuelKg / fullTank) * 100));

                gaugeFill.style.width = Math.max(fuelPctKg, 2) + '%';
                gaugeFill.textContent = fuelKg.toFixed(1) + ' kg';

                // Color thresholds
                var colorClass = 'rs-fuel-gauge-green';
                if (fuelPctKg < 20) colorClass = 'rs-fuel-gauge-red';
                else if (fuelPctKg <= 50) colorClass = 'rs-fuel-gauge-yellow';
                gaugeFill.className = 'rs-fuel-gauge-fill ' + colorClass;
            } else {
                // Fallback: percentage-based estimate from FUEL_AUTONOMY
                var fuelPct = 100;
                if (FUEL_AUTONOMY > 0) {
                    fuelPct = Math.max(0, Math.min(100, 100 - (stintElapsed / FUEL_AUTONOMY) * 100));
                }
                gaugeFill.style.width = Math.max(fuelPct, 2) + '%';
                gaugeFill.textContent = Math.round(fuelPct) + '%';
                var fallbackClass = 'rs-fuel-gauge-green';
                if (fuelPct < 20) fallbackClass = 'rs-fuel-gauge-red';
                else if (fuelPct <= 50) fallbackClass = 'rs-fuel-gauge-yellow';
                gaugeFill.className = 'rs-fuel-gauge-fill ' + fallbackClass;
            }
        }

        // --- Autonomy ---
        if (hasFuelModel && state.fuel_model.fuel_autonomy_s > 0) {
            // Engine-computed autonomy from current fuel level
            setText('rs-fuel-autonomy', fmtShort(state.fuel_model.fuel_autonomy_s));
        } else if (FUEL_AUTONOMY > 0) {
            var remainingFuelS = Math.max(0, FUEL_AUTONOMY - stintElapsed);
            setText('rs-fuel-autonomy', fmtShort(remainingFuelS));
        } else {
            setText('rs-fuel-autonomy', 'N/A');
        }

        // --- Burn rate ---
        if (hasFuelModel && state.fuel_model.burn_rate_kgs > 0) {
            setText('rs-fuel-burn-rate', state.fuel_model.burn_rate_kgs.toFixed(3) + ' kg/s');
        } else {
            setText('rs-fuel-burn-rate', '--');
        }

        // --- Ballast decomposition ---
        var hasBallast = state.current_ballast && state.current_ballast.total_kg != null;
        if (hasBallast) {
            var cb = state.current_ballast;
            setText('rs-ballast-base', 'Base: ' + (cb.base_kg || 0).toFixed(1) + ' kg');
            setText('rs-ballast-fuel-offset', 'Fuel: ' + (cb.fuel_offset_kg || 0).toFixed(1) + ' kg');
            setText('rs-ballast-total', cb.total_kg.toFixed(1) + ' kg');

            var decompEl = document.getElementById('rs-ballast-decomp');
            if (decompEl) decompEl.style.display = '';
        } else {
            // Fallback to simple ballast display
            var simpleBallast = (state.active_stint.ballast_kg || 0);
            setText('rs-ballast-base', 'Base: ' + simpleBallast.toFixed(1) + ' kg');
            setText('rs-ballast-fuel-offset', 'Fuel: -- kg');
            setText('rs-ballast-total', simpleBallast.toFixed(1) + ' kg');
        }

        // --- Pit speed badge ---
        var pitBadge = document.getElementById('rs-pit-speed-badge');
        if (pitBadge) {
            if (state.race && state.race.pit_speed_kmh) {
                pitBadge.className = 'rs-pit-speed-badge';
                pitBadge.textContent = 'Pit: ' + state.race.pit_speed_kmh + ' km/h';
            } else {
                pitBadge.className = '';
                pitBadge.textContent = '';
            }
        }

        // --- Total weight (rough estimate) ---
        if (state.race.empty_kart_kg && state.active_stint.driver_weight_kg) {
            var ballastTotal = hasBallast ? state.current_ballast.total_kg : (state.active_stint.ballast_kg || 0);
            var fuelWeight = hasCurrentFuel ? state.current_fuel_kg : 0;
            var total = state.race.empty_kart_kg +
                        (state.active_stint.driver_weight_kg || 0) +
                        ballastTotal +
                        fuelWeight;
            setText('rs-total-weight', total.toFixed(1) + ' kg');
        }
    }

    // ── 3. Current & Next Driver ─────────────────

    function findDriverById(driverId) {
        if (!state || !state.drivers) return null;
        for (var i = 0; i < state.drivers.length; i++) {
            if (state.drivers[i].id === driverId) return state.drivers[i];
        }
        return null;
    }

    function renderComBadge(elementId, driver) {
        var el = document.getElementById(elementId);
        if (!el) return;
        if (driver && driver.com_channel) {
            el.className = 'rs-com-badge';
            el.textContent = 'COM: Ch ' + driver.com_channel;
        } else {
            el.className = '';
            el.textContent = '';
        }
    }

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

            // COM channel badge for active driver
            var activeDriver = findDriverById(state.active_stint.driver_id);
            renderComBadge('rs-active-com-badge', activeDriver);
        } else {
            setText('rs-active-driver', 'No active stint');
            setText('rs-stint-elapsed', '--:--');
            renderComBadge('rs-active-com-badge', null);
        }

        if (state.next_stint) {
            setText('rs-next-driver', state.next_stint.driver_name);
            var info = document.getElementById('rs-next-info');
            if (info) {
                var cum = (state.driver_cumulative[state.next_stint.driver_id] || 0);
                info.textContent = ' (cumulative: ' + fmtShort(cum) + ')';
            }

            // COM channel badge for next driver
            var nextDriver = findDriverById(state.next_stint.driver_id);
            renderComBadge('rs-next-com-badge', nextDriver);

            // Ballast for next driver (so crew knows what to prepare)
            var nextBallastEl = document.getElementById('rs-next-ballast');
            if (nextBallastEl) {
                var nextBallast = state.next_stint.ballast_base_kg;
                if (nextBallast != null) {
                    var fuelOff = state.next_stint.ballast_fuel_offset_kg || 0;
                    var totalBallast = nextBallast + fuelOff;
                    nextBallastEl.textContent = 'Ballast: ' + totalBallast.toFixed(1) + ' kg (base: ' + nextBallast.toFixed(1) + ' + fuel: ' + fuelOff.toFixed(1) + ')';
                } else if (state.next_stint.ballast_kg != null) {
                    nextBallastEl.textContent = 'Ballast: ' + state.next_stint.ballast_kg.toFixed(1) + ' kg';
                } else {
                    nextBallastEl.textContent = '';
                }
            }
        } else {
            setText('rs-next-driver', 'Last stint');
            setText('rs-next-info', '');
            renderComBadge('rs-next-com-badge', null);
            var nextBallastEl2 = document.getElementById('rs-next-ballast');
            if (nextBallastEl2) nextBallastEl2.textContent = '';
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

            block.style.background = driverColor(s.driver_id, false);
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
                swatch.style.background = driverColor(d.id, false);
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

            // Ballast: show decomposition if available
            var ballastText;
            if (s.ballast_base_kg != null) {
                var bBase = s.ballast_base_kg || 0;
                var bFuel = s.ballast_fuel_offset_kg || 0;
                ballastText = (bBase + bFuel).toFixed(1) + ' kg';
            } else {
                ballastText = (s.ballast_kg || 0).toFixed(1) + ' kg';
            }

            // Fuel column: show fuel_at_start -> fuel_at_end if available, or refueled icon
            var fuelText = '';
            if (s.fuel_at_start != null && s.fuel_at_end != null) {
                fuelText = s.fuel_at_start.toFixed(1) + ' -> ' + s.fuel_at_end.toFixed(1);
            } else if (s.fuel_at_start != null) {
                fuelText = s.fuel_at_start.toFixed(1) + ' kg';
            }

            var cells = [
                '' + s.stint_order,
                s.driver_name,
                fmtShort(planned),
                s.status === 'completed' ? fmtShort(actual) : (s.status === 'active' ? 'running' : '\u2014'),
                delta !== null ? (delta >= 0 ? '+' : '') + Math.round(delta) + 's' : '\u2014',
                ballastText,
                fuelText || '\u2014',
                s.notes || ''
            ];

            cells.forEach(function(text, idx) {
                var td = document.createElement('td');
                if (idx === 1) {
                    // Driver name with color swatch
                    var swatch = document.createElement('span');
                    swatch.className = 'rs-driver-swatch';
                    swatch.style.background = driverColor(s.driver_id, false);
                    td.appendChild(swatch);
                    td.appendChild(document.createTextNode(text));
                } else if (idx === 6 && s.refueled != null) {
                    td.textContent = text;
                    var icon = document.createElement('span');
                    icon.className = 'rs-stint-fuel-icon ' + (s.refueled ? 'rs-refueled' : 'rs-no-refuel');
                    icon.textContent = s.refueled ? ' \u26FD' : '';
                    icon.title = s.refueled ? 'Refueled' : 'No refuel';
                    td.appendChild(icon);
                } else {
                    td.textContent = text;
                }
                // Delta column color coding
                if (idx === 4 && delta !== null) {
                    td.classList.add(delta > 0 ? 'rs-delta-positive' : delta < 0 ? 'rs-delta-negative' : '');
                }
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
                fillEl.style.background = driverColor(d.id, false);
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

    // ── 7. TeamTalk ────────────────────────────

    var CATEGORY_COLORS = {
        pit: 'var(--red, #f85149)', weather: 'var(--blue)', flag: 'var(--yellow, #d29922)',
        driver: 'var(--green)', general: 'var(--text-secondary)'
    };
    var lastMsgCount = 0;

    function updateChat() {
        if (!state || !state.messages) return;
        var log = document.getElementById('rs-chat-log');
        if (!log || state.messages.length === lastMsgCount) return;
        lastMsgCount = state.messages.length;

        clearChildren(log);
        state.messages.forEach(function(m) {
            var row = document.createElement('div');
            row.className = 'rs-chat-row';
            var cat = document.createElement('span');
            cat.className = 'rs-chat-cat';
            cat.style.color = CATEGORY_COLORS[m.category] || CATEGORY_COLORS.general;
            cat.textContent = '[' + (m.category || 'general').toUpperCase() + ']';
            var author = document.createElement('strong');
            author.textContent = ' ' + m.author + ': ';
            var text = document.createElement('span');
            text.textContent = m.message;
            var time = document.createElement('span');
            time.className = 'rs-chat-time';
            time.textContent = m.created_at ? m.created_at.substring(11, 16) : '';
            row.appendChild(cat);
            row.appendChild(author);
            row.appendChild(text);
            row.appendChild(time);
            log.appendChild(row);
        });
        log.scrollTop = log.scrollHeight;
    }

    var chatSend = document.getElementById('rs-chat-send');
    if (chatSend) {
        chatSend.addEventListener('click', function() {
            var author = document.getElementById('rs-chat-author').value.trim();
            var message = document.getElementById('rs-chat-message').value.trim();
            var category = document.getElementById('rs-chat-category').value;
            if (!author || !message) return;
            fetch('/race-strategy/' + RACE_ID + '/api/messages', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({author: author, message: message, category: category})
            }).then(function() {
                document.getElementById('rs-chat-message').value = '';
                fetchState();
            });
        });
    }

    // Allow Enter key to send message
    var chatMsg = document.getElementById('rs-chat-message');
    if (chatMsg) {
        chatMsg.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') { e.preventDefault(); if (chatSend) chatSend.click(); }
        });
    }

    // ── 8. Weather ────────────────────────────────

    var weatherData = null;
    var TRACK_NAME = root.getAttribute('data-track-name') || '';

    function fetchWeather() {
        if (!TRACK_NAME) return;
        fetch('/race-strategy/' + RACE_ID + '/api/weather')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) return;
                weatherData = data;
                renderWeather();
                renderForecast();
                renderRadar(data.lat, data.lon);
                updateFuelWeather();
            })
            .catch(function() {});
    }

    function renderWeather() {
        if (!weatherData || !weatherData.current) return;
        var card = document.getElementById('rs-weather-card');
        var el = document.getElementById('rs-weather-data');
        if (!card || !el) return;
        card.style.display = '';

        var w = weatherData.current;
        var c = weatherData.conditions || {};
        clearChildren(el);

        var items = [
            ['Temp', (w.air_temp_c != null ? w.air_temp_c : '--') + '\u00B0C'],
            ['Humidity', (w.humidity_pct != null ? w.humidity_pct : '--') + '%'],
            ['Wind', w.wind_speed_mps ? (w.wind_speed_mps * 3.6).toFixed(0) + ' km/h' : '--'],
            ['Rain', (w.rain_mm || 0) + ' mm'],
            ['Grip', c.track_state || 'unknown']
        ];
        items.forEach(function(item) {
            var row = document.createElement('div');
            row.className = 'rs-kv';
            row.style.fontSize = '0.85rem';
            var label = document.createElement('span');
            label.className = 'rs-kv-label';
            label.textContent = item[0];
            var val = document.createElement('span');
            val.textContent = item[1];
            row.appendChild(label);
            row.appendChild(val);
            el.appendChild(row);
        });

        var paceEl = document.getElementById('rs-weather-pace');
        if (paceEl && c.grip_score) {
            paceEl.textContent = 'Grip score: ' + (c.grip_score * 100).toFixed(0) + '%';
        }
    }

    function renderForecast() {
        if (!weatherData || !weatherData.forecast) return;
        var bar = document.getElementById('rs-forecast-bar');
        if (!bar) return;

        var hours = weatherData.forecast.hourly || [];
        if (!hours.length) return;

        bar.style.display = 'flex';
        clearChildren(bar);

        hours.forEach(function(h) {
            var block = document.createElement('div');
            block.className = 'rs-forecast-hour';
            block.style.flex = '1';
            var rain = h.rain_mm || 0;
            var opacity = Math.min(1, rain / 5);
            block.style.background = 'rgba(88,166,255,' + opacity + ')';
            block.title = (h.time || '') + ': ' + (h.air_temp_c != null ? h.air_temp_c : '--') + '\u00B0C, rain: ' + rain + 'mm';
            bar.appendChild(block);
        });
    }

    function renderRadar(lat, lon) {
        if (!lat || !lon) return;
        var card = document.getElementById('rs-radar-card');
        var wrap = document.getElementById('rs-radar-wrap');
        if (!card || !wrap) return;
        card.style.display = '';

        fetch('https://api.rainviewer.com/public/weather-maps.json')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.radar || !data.radar.past || !data.radar.past.length) return;
                var latest = data.radar.past[data.radar.past.length - 1];
                var tileUrl = data.host + latest.path + '/256/6/'
                    + Math.floor(lat / (180 / Math.pow(2, 5)))
                    + '/' + Math.floor((lon + 180) / (360 / Math.pow(2, 6)))
                    + '/2/1_1.png';
                wrap.style.backgroundImage = 'url(' + tileUrl + ')';
                wrap.style.backgroundSize = 'cover';
                wrap.style.backgroundPosition = 'center';
            })
            .catch(function() {});
    }

    function updateFuelWeather() {
        if (!weatherData || !weatherData.fuel_autonomy_adjusted_s) return;
        if (!FUEL_AUTONOMY) return;
        var adj = weatherData.fuel_autonomy_adjusted_s;
        if (adj < FUEL_AUTONOMY) {
            var el = document.getElementById('rs-fuel-autonomy');
            if (el && el.textContent.indexOf('wet') === -1) {
                el.textContent = el.textContent + ' (wet: ~' + fmtShort(adj) + ')';
            }
        }
    }

    // Fetch weather on load and every 5 minutes
    if (TRACK_NAME) {
        fetchWeather();
        _lc.addInterval(fetchWeather, 300000);
    }

    // ── Alert Manager ────────────────────────────

    var AlertManager = (function() {
        function AM() {
            this.previousState = {};
            this.muted = false;
            this.cooldowns = {};
            this.audioCtx = null;
            this.history = [];
            this.COOLDOWN_MS = 30000;
            this.MAX_HISTORY = 20;

            // Restore muted state from localStorage
            try { this.muted = localStorage.getItem('rs-alert-muted') === '1'; } catch(e) {}
            this._updateBellUI();
        }

        AM.prototype.playTone = function(freq, durationMs, type) {
            if (this.muted) return;
            try {
                if (!this.audioCtx) {
                    this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                }
                var osc = this.audioCtx.createOscillator();
                var gain = this.audioCtx.createGain();
                osc.connect(gain);
                gain.connect(this.audioCtx.destination);
                osc.type = type || 'sine';
                osc.frequency.value = freq;
                gain.gain.value = 0.15;
                gain.gain.exponentialRampToValueAtTime(0.001, this.audioCtx.currentTime + durationMs / 1000);
                osc.start();
                osc.stop(this.audioCtx.currentTime + durationMs / 1000);
            } catch(e) {}
        };

        AM.prototype._canFire = function(type) {
            var now = Date.now();
            if (this.cooldowns[type] && now - this.cooldowns[type] < this.COOLDOWN_MS) return false;
            this.cooldowns[type] = now;
            return true;
        };

        AM.prototype.notify = function(type, title, body, priority) {
            if (!this._canFire(type)) return;

            // Toast
            this._showToast(type, title + ': ' + body, priority);

            // Browser notification
            if (!this.muted && window.Notification && Notification.permission === 'granted') {
                try { new Notification(title, { body: body, tag: type }); } catch(e) {}
            }

            // History
            this.history.unshift({
                type: type,
                title: title,
                body: body,
                priority: priority,
                time: new Date().toLocaleTimeString()
            });
            if (this.history.length > this.MAX_HISTORY) this.history.pop();
            this._updateHistory();
            this._updateBadge();
        };

        AM.prototype._showToast = function(type, message, priority) {
            var strip = document.getElementById('rs-alert-strip');
            if (!strip) return;

            var toast = document.createElement('div');
            toast.className = 'rs-alert-toast rs-alert-' + (priority || 'medium');

            var text = document.createElement('span');
            text.textContent = message;
            toast.appendChild(text);

            var dismiss = document.createElement('span');
            dismiss.textContent = '\u00D7';
            dismiss.style.cssText = 'margin-left:auto;cursor:pointer;font-weight:700;';
            dismiss.addEventListener('click', function() { toast.remove(); });
            toast.appendChild(dismiss);

            strip.insertBefore(toast, strip.firstChild);

            // Auto-dismiss after 8s
            setTimeout(function() {
                if (toast.parentNode) toast.remove();
            }, 8000);
        };

        AM.prototype._updateHistory = function() {
            var panel = document.getElementById('rs-alert-history-panel');
            var container = document.getElementById('rs-alert-history');
            if (!container) return;

            if (this.history.length > 0 && panel) panel.style.display = '';

            clearChildren(container);
            for (var i = 0; i < this.history.length; i++) {
                var h = this.history[i];
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;gap:0.5rem;padding:0.2rem 0;border-bottom:1px solid var(--rs-card-border);';
                var time = document.createElement('span');
                time.style.color = 'var(--text-secondary)';
                time.textContent = h.time;
                var msg = document.createElement('span');
                msg.textContent = h.title + ': ' + h.body;
                row.appendChild(time);
                row.appendChild(msg);
                container.appendChild(row);
            }
        };

        AM.prototype._updateBadge = function() {
            var bell = document.getElementById('rs-btn-bell');
            if (!bell) return;
            var count = this.history.length;
            var badge = bell.querySelector('.rs-badge');
            if (count > 0) {
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'rs-badge';
                    bell.appendChild(badge);
                }
                badge.textContent = count > 9 ? '9+' : '' + count;
            } else if (badge) {
                badge.remove();
            }
        };

        AM.prototype._updateBellUI = function() {
            var bell = document.getElementById('rs-btn-bell');
            if (!bell) return;
            if (this.muted) {
                bell.classList.add('muted');
                bell.textContent = 'Muted';
            } else {
                bell.classList.remove('muted');
                bell.textContent = 'Bell';
            }
        };

        AM.prototype.toggleMute = function() {
            this.muted = !this.muted;
            try { localStorage.setItem('rs-alert-muted', this.muted ? '1' : '0'); } catch(e) {}
            this._updateBellUI();
        };

        AM.prototype.check = function(newState) {
            if (!newState) return;
            var prev = this.previousState;

            // 1. Fuel status transitions
            var prevFuel = (prev.intelligence && prev.intelligence.fuel) ? prev.intelligence.fuel.fuel_status : 'ok';
            var newFuel = (newState.intelligence && newState.intelligence.fuel) ? newState.intelligence.fuel.fuel_status : 'ok';
            if (prevFuel !== newFuel) {
                if (newFuel === 'critical') {
                    this.notify('fuel_critical', 'FUEL CRITICAL', 'Less than 2 minutes of fuel remaining!', 'high');
                    this.playTone(880, 600, 'square');
                } else if (newFuel === 'warning' && prevFuel === 'ok') {
                    this.notify('fuel_warning', 'Fuel Warning', 'Less than 5 minutes of fuel remaining', 'medium');
                    this.playTone(660, 400, 'sine');
                }
            }

            // 2. Window status transitions
            if (newState.window_status && prev.window_status) {
                for (var i = 0; i < newState.window_status.length; i++) {
                    var nw = newState.window_status[i];
                    var pw = null;
                    for (var j = 0; j < prev.window_status.length; j++) {
                        if (prev.window_status[j].type === nw.type) { pw = prev.window_status[j]; break; }
                    }
                    if (!pw) continue;
                    if (pw.status !== 'open' && nw.status === 'open') {
                        this.notify('window_open_' + nw.type, 'Pit Window Open', nw.type.replace('_', ' ') + ' window is now OPEN', 'high');
                        this.playTone(523, 200, 'sine');
                        setTimeout(function() { this.playTone(659, 200, 'sine'); }.bind(this), 250);
                    }
                    if (pw.status !== 'closing' && nw.status === 'closing') {
                        this.notify('window_closing_' + nw.type, 'Pit Window Closing', nw.type.replace('_', ' ') + ' window closing soon!', 'high');
                        this.playTone(880, 150, 'sawtooth');
                        setTimeout(function() { this.playTone(880, 150, 'sawtooth'); }.bind(this), 200);
                    }
                }
            }

            // 3. Neutralization start/end
            var prevNeut = !!prev.is_neutralized;
            var newNeut = !!newState.is_neutralized;
            if (!prevNeut && newNeut) {
                this.notify('sc_start', 'Safety Car', 'Neutralization period started', 'high');
                this.playTone(440, 800, 'sawtooth');
            } else if (prevNeut && !newNeut) {
                this.notify('sc_end', 'Green Flag', 'Neutralization ended — racing resumes', 'high');
                this.playTone(523, 300, 'sine');
                setTimeout(function() { this.playTone(659, 300, 'sine'); }.bind(this), 350);
            }

            // 4. Swap suggestion appearance
            var prevSwap = prev.intelligence && prev.intelligence.swap;
            var newSwap = newState.intelligence && newState.intelligence.swap;
            if (!prevSwap && newSwap && newSwap.suggest_swap) {
                this.notify('swap', 'Swap Suggestion', newSwap.reason + ' — consider ' + newSwap.next_driver, 'medium');
                this.playTone(587, 300, 'sine');
            }

            // 5. Stint time limit (90% of max)
            if (newState.active_stint) {
                var elapsed = getElapsed();
                var stintElapsed = elapsed - (newState.active_stint.actual_start_s || 0);
                var maxStint = newState.active_stint.planned_duration_s || 0;
                if (maxStint > 0 && stintElapsed > maxStint * 0.9) {
                    this.notify('stint_limit', 'Stint Limit', 'Over 90% of planned stint time used', 'medium');
                    this.playTone(740, 300, 'sine');
                }
            }

            // Save current state for next comparison
            this.previousState = JSON.parse(JSON.stringify(newState));
        };

        return AM;
    })();

    var alertManager = new AlertManager();

    // ── Neutralization ───────────────────────────

    function toggleNeutralization() {
        var isNeutralized = state && state.is_neutralized;
        var endpoint = isNeutralized ? 'end' : 'start';
        fetch('/race-strategy/' + RACE_ID + '/api/neutralization/' + endpoint, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({reason: 'safety_car'})
        })
        .then(function(r) { return r.json(); })
        .then(function() { fetchState(); });
    }

    function updateNeutralizationUI() {
        var banner = document.getElementById('rs-sc-banner');
        var btn = document.getElementById('rs-btn-sc');
        if (!banner || !btn) return;

        var isNeutralized = state && state.is_neutralized;
        banner.style.display = isNeutralized ? '' : 'none';
        if (isNeutralized) {
            btn.classList.add('rs-btn-sc-active');
        } else {
            btn.classList.remove('rs-btn-sc-active');
        }
    }

    var scBtn = document.getElementById('rs-btn-sc');
    if (scBtn) {
        scBtn.addEventListener('click', function() {
            var action = (state && state.is_neutralized) ? 'End Safety Car?' : 'Deploy Safety Car?';
            if (!confirm(action)) return;
            toggleNeutralization();
        });
    }

    var bellBtn = document.getElementById('rs-btn-bell');
    if (bellBtn) {
        bellBtn.addEventListener('click', function() {
            alertManager.toggleMute();
        });
    }

    // ── Intelligence Display ─────────────────────

    function updateIntelligence() {
        if (!state || !state.intelligence) return;
        var intel = state.intelligence;

        // Finish prediction
        if (intel.finish) {
            var f = intel.finish;
            setText('rs-intel-completion', f.completion_pct + '%');
            setText('rs-intel-remaining', 'Remaining: ' + fmtTime(f.remaining_s));

            var statusEl = document.getElementById('rs-intel-pace-status');
            if (statusEl) {
                statusEl.textContent = f.pace_status;
                statusEl.className = 'rs-intel-detail';
                if (f.pace_status === 'AHEAD') statusEl.classList.add('rs-ahead');
                else if (f.pace_status === 'BEHIND') statusEl.classList.add('rs-behind');
                else statusEl.classList.add('rs-on-plan');

                if (f.pace_delta_s && f.pace_delta_s !== 0) {
                    statusEl.textContent += ' (' + (f.pace_delta_s > 0 ? '+' : '') + f.pace_delta_s + 's)';
                }
            }
        }

        // Fuel alerts
        if (intel.fuel) {
            var fu = intel.fuel;
            var fuelStatusEl = document.getElementById('rs-intel-fuel-status');
            if (fuelStatusEl) {
                fuelStatusEl.textContent = fu.fuel_status.toUpperCase();
                fuelStatusEl.className = 'rs-intel-metric';
                if (fu.fuel_status === 'critical') fuelStatusEl.classList.add('rs-fuel-critical');
                else if (fu.fuel_status === 'warning') fuelStatusEl.classList.add('rs-fuel-warning');
            }
            setText('rs-intel-fuel-remaining', fmtShort(fu.fuel_remaining_s) + ' to empty');
            var pitEl = document.getElementById('rs-intel-can-reach-pit');
            if (pitEl) {
                if (fu.can_reach_pit) {
                    pitEl.textContent = 'Can reach pit';
                    pitEl.className = 'rs-intel-detail rs-ahead';
                } else {
                    pitEl.textContent = 'Cannot reach pit! Short by ' + fu.shortfall_s + 's';
                    pitEl.className = 'rs-intel-detail rs-fuel-critical';
                }
            }
        }

        // Pace analysis
        if (intel.pace) {
            var p = intel.pace;
            var trendEl = document.getElementById('rs-intel-pace-trend');
            if (trendEl) {
                trendEl.textContent = p.pace_trend.charAt(0).toUpperCase() + p.pace_trend.slice(1);
                trendEl.className = 'rs-intel-metric';
                if (p.pace_trend === 'degrading') trendEl.classList.add('rs-fuel-warning');
                else if (p.pace_trend === 'improving') trendEl.classList.add('rs-ahead');
            }
            var ownEl = document.getElementById('rs-intel-pace-vs-own');
            if (ownEl && p.pace_vs_own_avg_s != null) {
                ownEl.textContent = 'vs own avg: ' + (p.pace_vs_own_avg_s > 0 ? '+' : '') + p.pace_vs_own_avg_s + 's';
            }
            var recEl = document.getElementById('rs-intel-recommendation');
            if (recEl) {
                recEl.textContent = p.recommendation || '';
                if (p.recommendation) recEl.classList.add('rs-fuel-warning');
            }
        }

        // Swap suggestion (show as toast-like banner if present)
        if (intel.swap && intel.swap.suggest_swap) {
            var swapBanner = document.getElementById('rs-intel-recommendation');
            if (swapBanner) {
                swapBanner.textContent = 'SWAP: ' + intel.swap.reason + ' → ' + intel.swap.next_driver;
                swapBanner.className = 'rs-intel-detail rs-fuel-warning';
            }
        }
    }

    // ── Rival Tracker ────────────────────────────

    function fetchRivals() {
        fetch('/race-strategy/' + RACE_ID + '/api/rivals')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                renderRivals(data.rivals || []);
            })
            .catch(function() {});
    }

    function renderRivals(rivals) {
        var list = document.getElementById('rs-rival-list');
        if (!list) return;
        clearChildren(list);

        if (!rivals.length) {
            var empty = document.createElement('div');
            empty.style.cssText = 'color:var(--text-secondary);font-size:0.85rem;padding:0.5rem 0;';
            empty.textContent = 'No rivals tracked yet. Add a competitor above.';
            list.appendChild(empty);
            return;
        }

        var intel = (state && state.intelligence && state.intelligence.rivals) || [];

        rivals.forEach(function(r) {
            var card = document.createElement('div');
            card.className = 'rs-rival-card';

            // Find intelligence analysis for this rival
            var analysis = null;
            for (var i = 0; i < intel.length; i++) {
                if (intel[i].rival_id === r.id) { analysis = intel[i]; break; }
            }

            var header = document.createElement('div');
            header.className = 'rs-rival-header';
            header.textContent = (r.car_number ? '#' + r.car_number + ' ' : '') + r.team_name;

            var stats = document.createElement('div');
            stats.className = 'rs-rival-stats';
            if (analysis) {
                stats.textContent = analysis.estimated_pits + ' pits';
                if (analysis.avg_stint_s) {
                    stats.textContent += ' | ~' + fmtShort(analysis.avg_stint_s) + ' stints';
                }
                if (analysis.last_activity_s != null) {
                    stats.textContent += ' | Last: ' + fmtShort(analysis.last_activity_s) + ' ago';
                }
            } else {
                stats.textContent = (r.events || []).length + ' events logged';
            }

            var actions = document.createElement('div');
            actions.className = 'rs-rival-actions';
            var eventTypes = ['pit_in', 'pit_out', 'driver_change', 'penalty'];
            eventTypes.forEach(function(et) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn btn-ghost btn-xs';
                btn.textContent = et.replace('_', ' ');
                btn.addEventListener('click', function() {
                    logRivalEvent(r.id, et);
                });
                actions.appendChild(btn);
            });

            var delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.className = 'btn btn-ghost btn-xs rs-rival-del';
            delBtn.textContent = 'X';
            delBtn.title = 'Remove rival';
            delBtn.addEventListener('click', function() {
                if (!confirm('Remove ' + r.team_name + '?')) return;
                deleteRival(r.id);
            });
            actions.appendChild(delBtn);

            card.appendChild(header);
            card.appendChild(stats);
            card.appendChild(actions);
            list.appendChild(card);
        });
    }

    function logRivalEvent(rivalId, eventType) {
        fetch('/race-strategy/' + RACE_ID + '/api/rivals/' + rivalId + '/event', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({event_type: eventType})
        })
        .then(function() { fetchRivals(); });
    }

    function deleteRival(rivalId) {
        fetch('/race-strategy/' + RACE_ID + '/api/rivals/' + rivalId, {
            method: 'DELETE'
        })
        .then(function() { fetchRivals(); });
    }

    // Add rival button handler
    var addRivalBtn = document.getElementById('rs-rival-add-btn');
    if (addRivalBtn) {
        addRivalBtn.addEventListener('click', function() {
            var team = document.getElementById('rs-rival-team').value.trim();
            var car = document.getElementById('rs-rival-car').value.trim();
            if (!team) return;
            fetch('/race-strategy/' + RACE_ID + '/api/rivals', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({team_name: team, car_number: car})
            })
            .then(function() {
                document.getElementById('rs-rival-team').value = '';
                document.getElementById('rs-rival-car').value = '';
                fetchRivals();
            });
        });
    }

    // Collapse toggle
    var rivalsToggle = document.getElementById('rs-rivals-toggle');
    if (rivalsToggle) {
        rivalsToggle.addEventListener('click', function() {
            var content = document.getElementById('rs-rivals-content');
            if (!content) return;
            var hidden = content.style.display === 'none';
            content.style.display = hidden ? '' : 'none';
            rivalsToggle.textContent = hidden ? 'Collapse' : 'Expand';
        });
    }

    // ── Polling ──────────────────────────────────

    function setConnectionStatus(connected) {
        var dot = document.getElementById('rs-connection-dot');
        if (!dot) return;
        if (connected) {
            dot.classList.remove('disconnected');
        } else {
            dot.classList.add('disconnected');
        }
    }

    function fetchState() {
        fetch('/race-strategy/' + RACE_ID + '/api/state')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                setConnectionStatus(true);
                if (data.error) return;
                state = data;
                updateTimeline();
                updateStintLog();
                updateChat();
                updateNeutralizationUI();
                updateIntelligence();
                alertManager.check(state);
            })
            .catch(function() {
                setConnectionStatus(false);
            });
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

    // ── Layout Toggle (enhanced with compact mode) ──

    var toggleContainer = document.getElementById('rs-layout-toggle');

    function applyLayout(layout) {
        var grid = document.getElementById('rs-live-root');
        if (!grid) return;
        grid.classList.remove('rs-vertical', 'rs-compact');
        if (layout === 'vertical') grid.classList.add('rs-vertical');
        if (layout === 'compact') grid.classList.add('rs-compact');

        var btns = document.querySelectorAll('.rs-toggle-btn');
        for (var i = 0; i < btns.length; i++) {
            if (btns[i].getAttribute('data-layout') === layout) {
                btns[i].classList.add('rs-toggle-active');
            } else {
                btns[i].classList.remove('rs-toggle-active');
            }
        }
        try { localStorage.setItem('rs-live-layout', layout); } catch(e) {}
    }

    try {
        var saved = localStorage.getItem('rs-live-layout');
        if (saved === 'vertical' || saved === 'compact') applyLayout(saved);
    } catch(e) {}

    if (toggleContainer) {
        toggleContainer.addEventListener('click', function(e) {
            var btn = e.target.closest('.rs-toggle-btn');
            if (btn) applyLayout(btn.getAttribute('data-layout'));
        });
    }

    // ── Fullscreen Toggle ────────────────────────
    var fsBtn = document.getElementById('rs-btn-fullscreen');
    if (fsBtn) {
        fsBtn.addEventListener('click', function() {
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen().catch(function() {});
            } else {
                document.exitFullscreen();
            }
        });
        document.addEventListener('fullscreenchange', function() {
            if (fsBtn) {
                fsBtn.textContent = document.fullscreenElement ? 'Exit FS' : 'Fullscreen';
            }
        });
    }

    // ── Window Status Bar (Tier 5) ────────────────
    function updateWindowStatus() {
        if (!state || !state.window_status) {
            // Fallback to legacy single pit window banner
            updatePitWindowLegacy();
            return;
        }
        var bar = document.getElementById('rs-window-bar');
        if (!bar) return;

        // Hide legacy banner if window_status is available
        var legacyBanner = document.getElementById('rs-pit-window-banner');
        if (legacyBanner) legacyBanner.style.display = 'none';

        state.window_status.forEach(function(ws) {
            var card = document.getElementById('rs-window-' + ws.type);
            if (!card) return;

            var statusEl = card.querySelector('.rs-window-card-status');
            var countdownEl = card.querySelector('.rs-window-card-countdown');

            card.className = 'rs-window-card rs-window-' + ws.status;

            if (ws.status === 'none') {
                statusEl.textContent = 'Not configured';
                countdownEl.textContent = '';
            } else if (ws.status === 'before') {
                statusEl.textContent = 'Opens in';
                countdownEl.textContent = fmtShort(ws.countdown_s);
            } else if (ws.status === 'open') {
                statusEl.textContent = 'OPEN';
                countdownEl.textContent = 'Closes in ' + fmtShort(ws.countdown_s);
            } else if (ws.status === 'closing') {
                statusEl.textContent = 'CLOSING';
                countdownEl.textContent = fmtShort(ws.countdown_s);
            } else if (ws.status === 'closed') {
                statusEl.textContent = 'CLOSED';
                countdownEl.textContent = '';
            }
        });

        // Update end-stint button warning based on pitlane status
        var pitStatus = state.window_status.find(function(w) { return w.type === 'pitlane'; });
        var endBtn = document.getElementById('rs-btn-end-stint');
        if (endBtn && pitStatus) {
            if (pitStatus.status === 'before' || pitStatus.status === 'closed') {
                endBtn.classList.add('rs-btn-pit-warning');
            } else {
                endBtn.classList.remove('rs-btn-pit-warning');
            }
        }
    }

    // ── Pit Window Banner ────────────────────────

    function updatePitWindowLegacy() {
        var banner = document.getElementById('rs-pit-window-banner');
        var endBtn = document.getElementById('rs-btn-end-stint');
        if (!banner) return;
        if (!PIT_OPEN && !PIT_CLOSE) { banner.style.display = 'none'; return; }

        var elapsed = getElapsed();
        banner.style.display = 'block';

        var outsideWindow = false;

        if (PIT_OPEN && elapsed < PIT_OPEN) {
            var until = PIT_OPEN - elapsed;
            banner.textContent = 'Pit window opens in ' + fmtShort(until);
            banner.className = 'rs-pit-banner rs-pit-banner-before';
            outsideWindow = true;
        } else if (PIT_CLOSE && elapsed > PIT_CLOSE) {
            banner.textContent = 'PIT WINDOW CLOSED';
            banner.className = 'rs-pit-banner rs-pit-banner-closed';
            outsideWindow = true;
        } else if (PIT_CLOSE && PIT_CLOSE - elapsed < 300) {
            var left = PIT_CLOSE - elapsed;
            banner.textContent = 'Pit window closes in ' + fmtShort(left);
            banner.className = 'rs-pit-banner rs-pit-banner-closing';
        } else if (PIT_OPEN && elapsed >= PIT_OPEN) {
            banner.textContent = 'PIT WINDOW OPEN';
            banner.className = 'rs-pit-banner rs-pit-banner-open';
        } else {
            banner.style.display = 'none';
        }

        if (endBtn) {
            if (outsideWindow) {
                endBtn.classList.add('rs-btn-pit-warning');
            } else {
                endBtn.classList.remove('rs-btn-pit-warning');
            }
        }
    }

    // ── Wall Clock ───────────────────────────────
    function updateWallClock() {
        var el = document.getElementById('rs-wall-clock');
        if (!el) return;
        var now = new Date();
        el.textContent = pad2(now.getHours()) + ':' + pad2(now.getMinutes()) + ':' + pad2(now.getSeconds());
    }

    // ── Init ─────────────────────────────────────

    // Request notification permission on first user interaction
    document.addEventListener('click', function requestNotifPerm() {
        if (window.Notification && Notification.permission === 'default') {
            Notification.requestPermission();
        }
        document.removeEventListener('click', requestNotifPerm);
    }, { once: true });

    fetchState();

    // Fetch rivals on load and every 10s
    fetchRivals();
    _lc.addInterval(fetchRivals, 10000);

    // Client-side timer tick (1s)
    _lc.addInterval(function() {
        updateTimer();
        updateFuel();
        updateDrivers();
        updateSummary();
        updateWindowStatus();
        updateWallClock();
        updateNeutralizationUI();
        updateIntelligence();
    }, 1000);

    // Server poll (2s)
    _lc.addInterval(fetchState, POLL_INTERVAL);

    // Pause polling when tab is hidden to save CPU + server load
    _lc.addListener(document, 'visibilitychange', function () {
        if (document.hidden) {
            _lc.destroyAll();
        }
    });

    window.ModuleManager.register('race_strategy_live', {
        init: function () { /* already auto-inits on load */ },
        destroy: function () { _lc.destroyAll(); }
    });

})();
