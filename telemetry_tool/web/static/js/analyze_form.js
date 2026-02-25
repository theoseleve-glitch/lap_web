/**
 * analyze_form.js — Wizard-style analysis form UX with real async progress.
 *
 * - In-app file browser (fetch, select, upload, drag-drop).
 * - 3-step wizard: Select Data → Configure → Analyze.
 * - Async analysis via /analyze/api/start + polling /analyze/api/status.
 * - Real pipeline stage progress from backend.
 * - Multi-driver: dynamic "Add Driver" rows with dropdown + accent-insensitive matching.
 * - Track selection with "New Track" + predefined track search.
 * - Kart model selection from predefined list.
 * - Session type hints with per-type report descriptions.
 * - File reminder banner in step 2.
 * - Multi-condition: pill-style toggles synced to hidden field.
 * - Lap range hidden from basic mode (only shown in endurance).
 * - Form validation with visual feedback.
 */
(function () {
    'use strict';

    // ── Session type report descriptions ──
    var SESSION_TYPE_HINTS = {
        practice:   'Consistency analysis, lap-to-lap progression, driving style breakdown',
        qualifying: 'Peak pace focus, single-lap optimization, sector analysis',
        race:       'Race craft analysis, position defense, tire management, strategy review',
        warmup:     'Setup validation, baseline performance check, system readiness',
        sprint:     'Short-burst performance, reaction times, overtaking opportunities',
        endurance:  'Stint management, driver swaps, consistency over distance, fuel/tire strategy',
        test:       'Data validation, sensor calibration, baseline measurements',
    };

    document.addEventListener('DOMContentLoaded', function () {
        var form = document.getElementById('analyze-form');
        var submitBtn = document.getElementById('submit-btn');

        if (!form) return;

        // ── Wizard step navigation ──
        var currentStep = 1;
        var panels = document.querySelectorAll('.wizard-panel');
        var steps = document.querySelectorAll('.wizard-step');
        var lines = document.querySelectorAll('.wizard-step-line');

        function showStep(step) {
            currentStep = step;
            panels.forEach(function (p) {
                var pStep = parseInt(p.getAttribute('data-panel'));
                if (pStep === step) { p.classList.remove('hidden'); }
                else { p.classList.add('hidden'); }
            });
            steps.forEach(function (s) {
                var sStep = parseInt(s.getAttribute('data-step'));
                s.classList.remove('active', 'completed');
                if (sStep === step) s.classList.add('active');
                else if (sStep < step) s.classList.add('completed');
            });
            lines.forEach(function (l, i) {
                l.classList.toggle('completed', (i + 1) < step);
            });
            var header = document.querySelector('.page-header');
            if (header) header.scrollIntoView({ behavior: 'smooth', block: 'start' });
            var activePanel = document.querySelector('.wizard-panel:not(.hidden)');
            if (activePanel) {
                var heading = activePanel.querySelector('h2, h3, legend, label');
                if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus({ preventScroll: true }); }
            }
        }

        var step1Next = document.getElementById('step1-next');
        var step2Back = document.getElementById('step2-back');

        if (step1Next) {
            step1Next.addEventListener('click', function () {
                var selectedFile = document.getElementById('selected-file-hidden');
                var csvUpload = document.getElementById('csv-upload');
                if ((!selectedFile || !selectedFile.value) && (!csvUpload || !csvUpload.files || csvUpload.files.length === 0)) {
                    var info = document.getElementById('selected-file-info');
                    if (info) {
                        info.textContent = 'Please select or upload a CSV file first.';
                        info.classList.remove('hidden');
                        info.style.color = 'var(--red)';
                        info.setAttribute('role', 'alert');
                        setTimeout(function () { info.style.color = ''; }, 3000);
                    }
                    return;
                }
                // Show file reminder in step 2
                _updateFileReminder();
                showStep(2);
            });
        }

        if (step2Back) {
            step2Back.addEventListener('click', function () {
                showStep(1);
            });
        }

        // ── File reminder banner ──
        function _updateFileReminder() {
            var banner = document.getElementById('file-reminder-banner');
            var text = document.getElementById('file-reminder-text');
            var selectedFile = document.getElementById('selected-file-hidden');
            if (banner && text && selectedFile && selectedFile.value) {
                text.textContent = 'Analyzing: ' + selectedFile.value;
                banner.classList.remove('hidden');
            }
        }

        // ── In-app file browser ──
        var fileBrowser = document.getElementById('file-browser');
        var fileList = document.getElementById('file-list');
        var fileDrop = document.getElementById('file-drop');
        var fileUploadInput = document.getElementById('csv-upload');
        var selectedFileHidden = document.getElementById('selected-file-hidden');
        var selectedFileInfo = document.getElementById('selected-file-info');

        function loadFileList() {
            FetchHelper.fetch('/api/files/list')
                .then(function (data) {
                    if (!data.files || data.files.length === 0) {
                        fileList.textContent = '';
                        var emptyDiv = document.createElement('div');
                        emptyDiv.className = 'file-browser-empty';
                        emptyDiv.textContent = 'No CSV files found in data/raw/. Upload one above or drag & drop below.';
                        fileList.appendChild(emptyDiv);
                        return;
                    }
                    fileList.textContent = '';
                    data.files.forEach(function (f) {
                        var isSelected = selectedFileHidden && selectedFileHidden.value === f.name;
                        var row = document.createElement('div');
                        row.className = 'file-row' + (isSelected ? ' selected' : '');
                        row.dataset.filename = f.name;
                        row.tabIndex = 0;
                        row.setAttribute('role', 'option');
                        row.setAttribute('aria-selected', isSelected ? 'true' : 'false');

                        var info = document.createElement('div');
                        info.className = 'file-row-info';
                        var nameSpan = document.createElement('span');
                        nameSpan.className = 'file-row-name';
                        nameSpan.textContent = f.name;
                        info.appendChild(nameSpan);

                        var meta = document.createElement('div');
                        meta.className = 'file-row-meta';
                        var sizeSpan = document.createElement('span');
                        sizeSpan.textContent = f.size_human;
                        var modSpan = document.createElement('span');
                        modSpan.textContent = f.modified_human;
                        meta.appendChild(sizeSpan);
                        meta.appendChild(modSpan);

                        row.appendChild(info);
                        row.appendChild(meta);
                        fileList.appendChild(row);
                    });
                    if (selectedFileHidden && selectedFileHidden.value) {
                        showSelectedInfo(selectedFileHidden.value);
                    }
                })
                .catch(function () {
                    fileList.textContent = '';
                    var errDiv = document.createElement('div');
                    errDiv.className = 'file-browser-empty';
                    errDiv.textContent = 'Error loading files.';
                    fileList.appendChild(errDiv);
                });
        }

        function selectFile(filename) {
            if (!selectedFileHidden) return;
            selectedFileHidden.value = filename;
            var rows = fileList.querySelectorAll('.file-row');
            rows.forEach(function (r) {
                if (r.getAttribute('data-filename') === filename) {
                    r.classList.add('selected');
                    r.setAttribute('aria-selected', 'true');
                } else {
                    r.classList.remove('selected');
                    r.setAttribute('aria-selected', 'false');
                }
            });
            showSelectedInfo(filename);
        }

        function showSelectedInfo(filename) {
            if (selectedFileInfo) {
                selectedFileInfo.textContent = '';
                var checkMark = document.createTextNode('\u2705 Selected: ');
                var strong = document.createElement('strong');
                strong.textContent = filename;
                selectedFileInfo.appendChild(checkMark);
                selectedFileInfo.appendChild(strong);
                selectedFileInfo.classList.remove('hidden');
                selectedFileInfo.style.color = 'var(--green)';
            }
        }

        function uploadFile(file) {
            var formData = new FormData();
            formData.append('file', file);

            var progressWrap = document.getElementById('upload-progress-wrap');
            var progressFill = document.getElementById('upload-progress-fill');
            var progressText = document.getElementById('upload-progress-text');

            if (progressWrap) progressWrap.classList.remove('hidden');
            if (progressFill) progressFill.style.width = '0%';
            if (progressText) progressText.textContent = 'Uploading ' + file.name + '...';

            if (selectedFileInfo) {
                selectedFileInfo.textContent = 'Uploading ' + file.name + '...';
                selectedFileInfo.classList.remove('hidden');
                selectedFileInfo.style.color = 'var(--accent)';
            }

            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/files/upload', true);

            xhr.upload.addEventListener('progress', function (e) {
                if (e.lengthComputable) {
                    var pct = Math.round((e.loaded / e.total) * 100);
                    if (progressFill) progressFill.style.width = pct + '%';
                    if (progressText) progressText.textContent = 'Uploading ' + file.name + '... ' + pct + '%';
                }
            });

            xhr.addEventListener('load', function () {
                if (progressFill) progressFill.style.width = '100%';
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data.error) {
                        if (selectedFileInfo) {
                            selectedFileInfo.textContent = 'Upload error: ' + data.error;
                            selectedFileInfo.style.color = 'var(--red)';
                        }
                        if (progressText) progressText.textContent = 'Upload failed';
                        return;
                    }
                    selectedFileHidden.value = data.name;
                    loadFileList();
                    if (selectedFileInfo) {
                        selectedFileInfo.textContent = '';
                        var check = document.createTextNode('\u2705 Uploaded: ');
                        var strong = document.createElement('strong');
                        strong.textContent = data.name;
                        var size = document.createTextNode(' (' + data.size_human + ')');
                        selectedFileInfo.appendChild(check);
                        selectedFileInfo.appendChild(strong);
                        selectedFileInfo.appendChild(size);
                        selectedFileInfo.style.color = 'var(--green)';
                    }
                    if (progressText) progressText.textContent = 'Upload complete!';
                    if (window.Toast) Toast.success('File uploaded', data.name + ' (' + data.size_human + ')');
                    setTimeout(function () {
                        if (progressWrap) progressWrap.classList.add('hidden');
                    }, 2000);
                } catch (err) {
                    if (progressText) progressText.textContent = 'Upload failed';
                    if (window.Toast) Toast.error('Upload failed', 'Could not parse server response.');
                }
            });

            xhr.addEventListener('error', function () {
                if (selectedFileInfo) {
                    selectedFileInfo.textContent = 'Upload failed. Please try again.';
                    selectedFileInfo.style.color = 'var(--red)';
                }
                if (progressText) progressText.textContent = 'Upload failed';
                if (window.Toast) Toast.error('Upload failed', 'Network error.');
            });

            xhr.send(formData);
        }

        // File list click & keyboard handlers
        if (fileList) {
            fileList.addEventListener('click', function (e) {
                var row = e.target.closest('.file-row');
                if (row && row.dataset.filename) selectFile(row.dataset.filename);
            });
            fileList.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    var row = e.target.closest('.file-row');
                    if (row && row.dataset.filename) { e.preventDefault(); selectFile(row.dataset.filename); }
                }
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    var rows = fileList.querySelectorAll('.file-row');
                    var currentIdx = Array.prototype.indexOf.call(rows, e.target.closest('.file-row'));
                    var nextIdx = e.key === 'ArrowDown' ? Math.min(currentIdx + 1, rows.length - 1) : Math.max(currentIdx - 1, 0);
                    rows[nextIdx].focus();
                }
            });
            loadFileList();
        }

        if (fileUploadInput) {
            fileUploadInput.addEventListener('change', function () {
                if (fileUploadInput.files.length > 0) uploadFile(fileUploadInput.files[0]);
            });
        }

        // Drag & drop
        if (fileBrowser && fileDrop) {
            fileBrowser.addEventListener('dragover', function (e) {
                e.preventDefault(); e.stopPropagation();
                fileDrop.classList.remove('hidden');
                fileDrop.classList.add('drag-over');
            });
            fileBrowser.addEventListener('dragleave', function (e) {
                e.preventDefault(); e.stopPropagation();
                if (!fileBrowser.contains(e.relatedTarget)) {
                    fileDrop.classList.remove('drag-over');
                    fileDrop.classList.add('hidden');
                }
            });
            fileBrowser.addEventListener('drop', function (e) {
                e.preventDefault(); e.stopPropagation();
                fileDrop.classList.remove('drag-over');
                fileDrop.classList.add('hidden');
                var files = e.dataTransfer.files;
                if (files.length > 0) {
                    for (var i = 0; i < files.length; i++) {
                        if (files[i].name.toLowerCase().endsWith('.csv')) {
                            uploadFile(files[i]);
                            return;
                        }
                    }
                    if (selectedFileInfo) {
                        selectedFileInfo.textContent = 'Please drop a .csv file.';
                        selectedFileInfo.classList.remove('hidden');
                        selectedFileInfo.style.color = 'var(--yellow)';
                    }
                }
            });
        }

        // ── Session type hint ──
        var sessionTypeSelect = document.getElementById('session-type');
        var sessionTypeHintText = document.getElementById('session-type-hint-text');

        function updateSessionTypeHint() {
            if (!sessionTypeSelect || !sessionTypeHintText) return;
            var val = sessionTypeSelect.value;
            sessionTypeHintText.textContent = SESSION_TYPE_HINTS[val] || '';
        }

        // ── Async submit + real progress polling ──
        form.addEventListener('submit', function (e) {
            e.preventDefault();

            // Sync hidden fields
            if (sessionTypeSelect && sessionTypeSelect.value === 'endurance') {
                syncStintsToFormFields();
            } else {
                // Sync driver name from select/input
                var firstDriverInput = form.querySelector('.driver-name-input');
                var firstDriverSelect = form.querySelector('.driver-select');
                var primaryHidden = document.getElementById('primary-driver-hidden');
                if (primaryHidden) {
                    var dName = '';
                    if (firstDriverSelect && firstDriverSelect.value && firstDriverSelect.value !== '__new__') {
                        dName = firstDriverSelect.value;
                    }
                    if (firstDriverInput && !firstDriverInput.classList.contains('hidden') && firstDriverInput.value.trim()) {
                        dName = firstDriverInput.value.trim();
                    }
                    if (!dName && firstDriverInput) dName = firstDriverInput.value.trim();
                    primaryHidden.value = dName || 'Driver_1';

                    var dn0 = form.querySelector('input[name="driver_name_0"]');
                    if (dn0 && !dn0.value.trim() && dName) dn0.value = dName;
                }
                syncTrackState();
            }

            // Sync track name for "New Track"
            var trackSelectEl = document.getElementById('track-name');
            var newTrackInputEl = document.getElementById('new-track-name');
            if (trackSelectEl && trackSelectEl.value === '__new__' && newTrackInputEl && newTrackInputEl.value.trim()) {
                var existingHidden = form.querySelector('input.new-track-field');
                if (existingHidden) existingHidden.remove();
                var h = document.createElement('input');
                h.type = 'hidden';
                h.name = 'track_name';
                h.value = newTrackInputEl.value.trim();
                h.className = 'new-track-field';
                form.appendChild(h);
                trackSelectEl.disabled = true;
            }

            // Sync kart model
            var kartSelectEl = document.getElementById('kart-model-select');
            var kartHiddenEl = document.getElementById('kart-model-hidden');
            var newKartInputEl = document.getElementById('new-kart-name');
            if (kartHiddenEl) {
                if (kartSelectEl && kartSelectEl.value === '__new__' && newKartInputEl) {
                    kartHiddenEl.value = newKartInputEl.value.trim();
                } else if (kartSelectEl) {
                    kartHiddenEl.value = kartSelectEl.value || '';
                }
            }

            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.classList.add('btn-loading');
                submitBtn.textContent = 'Analyzing...';
            }

            form.setAttribute('aria-busy', 'true');
            showStep(3);

            if (trackSelectEl) trackSelectEl.disabled = false;

            var formData = new FormData(form);

            fetch('/analyze/api/start', { method: 'POST', body: formData })
                .then(function (resp) { return resp.json(); })
                .then(function (data) {
                    if (data.error) {
                        showAnalysisError(data.error);
                        return;
                    }
                    pollProgress(data.job_id);
                })
                .catch(function (err) {
                    showAnalysisError('Network error: ' + err.message);
                });
        });

        function pollProgress(jobId) {
            var stageText = document.getElementById('analysis-stage-text');
            var overallFill = document.getElementById('analysis-overall-fill');
            var elapsedEl = document.getElementById('analysis-elapsed');
            var stagesDots = document.querySelectorAll('.pipeline-stage');
            var startTime = Date.now();

            var stageThresholds = [5, 20, 33, 60, 75, 85, 92, 96];

            var cornerPickerShown = false;
            var cornersSubmitted = false;
            var analysisDone = false;
            var doneSessionId = null;

            var jokerPanelShown = false;
            var jokerConfirmed = false;
            var jokerSelectedLap = null;

            function updateStageDots(pct) {
                stagesDots.forEach(function (s, i) {
                    var threshold = stageThresholds[i] || 0;
                    var dot = s.querySelector('.pipeline-stage-dot');
                    if (pct > threshold) {
                        s.classList.add('completed');
                        s.classList.remove('active');
                        if (dot) { dot.classList.add('completed'); dot.classList.remove('active'); }
                    } else if (pct >= threshold - 10) {
                        s.classList.add('active');
                        s.classList.remove('completed');
                        if (dot) { dot.classList.add('active'); dot.classList.remove('completed'); }
                    }
                });
            }

            function showCornerPicker(trackLayout) {
                if (cornerPickerShown) return;
                cornerPickerShown = true;

                var panel = document.getElementById('corner-picker-panel');
                var statusEl = document.getElementById('corner-picker-status');
                var confirmBtn = document.getElementById('corner-picker-confirm');

                if (!panel) return;
                panel.classList.remove('hidden');

                var trackId = trackLayout.track_id || null;

                if (!window.CornerPicker) return;

                window.CornerPicker.init('corner-picker-canvas', trackLayout);

                // Wire up selection change callback
                window.CornerPicker.onSelectionChange(function (points) {
                    var count = points.length;
                    if (count < 3) {
                        statusEl.textContent = 'Select at least ' + (3 - count) + ' more point' + (3 - count !== 1 ? 's' : '');
                        statusEl.className = 'corner-picker-status status-warn';
                        confirmBtn.disabled = true;
                    } else if (count > 8) {
                        statusEl.textContent = 'Maximum 8 points';
                        statusEl.className = 'corner-picker-status status-warn';
                        confirmBtn.disabled = true;
                    } else {
                        statusEl.textContent = count + ' area' + (count !== 1 ? 's' : '') + ' of interest selected';
                        statusEl.className = 'corner-picker-status status-ok';
                        confirmBtn.disabled = false;
                    }
                });

                // Check for existing key corners saved for this track
                if (trackId) {
                    _loadSavedKeyCorners(trackId, panel, statusEl, confirmBtn);
                }

                // Confirm button: save selection
                if (confirmBtn) {
                    confirmBtn.addEventListener('click', function () {
                        _saveCornerSelection(jobId, panel, statusEl, confirmBtn);
                    });
                }
            }

            function _loadSavedKeyCorners(trackId, panel, statusEl, confirmBtn) {
                fetch('/api/track/' + encodeURIComponent(trackId) + '/key-corners')
                    .then(function (resp) { return resp.json(); })
                    .then(function (saved) {
                        if (!saved || !saved.length) return;
                        // Only use saved corners that have lat/lon
                        var valid = saved.filter(function (s) {
                            return s.lat != null && s.lon != null;
                        });
                        if (valid.length < 3) return;

                        // Pre-load saved points into the picker
                        window.CornerPicker.setPoints(valid);

                        // Show "using saved" banner
                        var banner = document.createElement('div');
                        banner.className = 'corner-saved-banner';
                        banner.style.cssText = 'background:rgba(16,185,129,0.12);border:1px solid rgba(16,185,129,0.3);border-radius:8px;padding:8px 14px;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:13px;color:#10b981;';

                        var bannerText = document.createElement('span');
                        bannerText.textContent = 'Using ' + valid.length + ' saved areas of interest from previous session';
                        banner.appendChild(bannerText);

                        var resetBtn = document.createElement('button');
                        resetBtn.type = 'button';
                        resetBtn.textContent = 'Clear & re-select';
                        resetBtn.style.cssText = 'background:transparent;border:1px solid rgba(16,185,129,0.4);color:#10b981;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:12px;';
                        resetBtn.addEventListener('click', function () {
                            window.CornerPicker.setPoints([]);
                            banner.remove();
                            statusEl.textContent = 'Click on the track to place areas of interest';
                            statusEl.className = 'corner-picker-status status-warn';
                            confirmBtn.disabled = true;
                        });
                        banner.appendChild(resetBtn);

                        // Insert banner before the canvas
                        var canvasEl = document.getElementById('corner-picker-canvas');
                        if (canvasEl && canvasEl.parentNode) {
                            canvasEl.parentNode.insertBefore(banner, canvasEl);
                        }

                        // Update status to show saved points are loaded
                        statusEl.textContent = valid.length + ' areas of interest loaded from track';
                        statusEl.className = 'corner-picker-status status-ok';
                        confirmBtn.disabled = false;
                    })
                    .catch(function () {
                        // Silently ignore — user can still pick manually
                    });
            }

            function _saveCornerSelection(currentJobId, panel, statusEl, confirmBtn) {
                var points = window.CornerPicker ? window.CornerPicker.getSelected() : [];
                if (points.length < 3 || points.length > 8) return;

                confirmBtn.disabled = true;
                confirmBtn.textContent = 'Saving...';

                fetch('/analyze/api/corners/' + currentJobId, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ corners: points }),
                })
                    .then(function (resp) { return resp.json(); })
                    .then(function (result) {
                        if (result.error) {
                            statusEl.textContent = result.error;
                            statusEl.className = 'corner-picker-status status-warn';
                            confirmBtn.disabled = false;
                            confirmBtn.textContent = 'Confirm Selection';
                            return;
                        }
                        cornersSubmitted = true;
                        confirmBtn.textContent = 'Selection saved!';
                        statusEl.textContent = result.count + ' areas of interest saved';
                        statusEl.className = 'corner-picker-status status-ok';
                        panel.classList.add('submitted');

                        // Remove saved banner if present
                        var savedBanner = panel.querySelector('.corner-saved-banner');
                        if (savedBanner) savedBanner.remove();

                        if (analysisDone && doneSessionId) {
                            _redirect(doneSessionId);
                        }
                    })
                    .catch(function () {
                        statusEl.textContent = 'Save failed \u2014 try again';
                        statusEl.className = 'corner-picker-status status-warn';
                        confirmBtn.disabled = false;
                        confirmBtn.textContent = 'Confirm Selection';
                    });
            }

            function showJokerPanel(jokerData) {
                if (jokerPanelShown) return;
                jokerPanelShown = true;

                var panel = document.getElementById('joker-confirm-panel');
                var tbody = document.getElementById('joker-laps-tbody');
                var statusEl = document.getElementById('joker-confirm-status');
                var confirmBtn = document.getElementById('joker-confirm-btn');
                var rejectBtn = document.getElementById('joker-reject-btn');
                if (!panel || !tbody) return;

                panel.classList.remove('hidden');

                var laps = [];
                var distances = jokerData.all_distances || {};
                var deltas = jokerData.delta_from_median || {};
                var times = jokerData.all_times || {};
                var timeDeltas = jokerData.time_delta_from_median || {};
                var candidateLap = jokerData.candidate_lap;
                var confidence = jokerData.confidence || 0;

                for (var lapStr in distances) {
                    var lap = parseInt(lapStr);
                    laps.push({
                        lap: lap,
                        dist: distances[lapStr],
                        delta: deltas[lapStr] || 0,
                        time: times[lapStr] || 0,
                        timeDelta: timeDeltas[lapStr] || 0,
                        isCandidate: lap === candidateLap,
                    });
                }

                laps.sort(function (a, b) { return Math.abs(b.delta) - Math.abs(a.delta); });
                jokerSelectedLap = candidateLap;

                tbody.textContent = '';
                laps.forEach(function (l) {
                    var tr = document.createElement('tr');
                    if (l.isCandidate) tr.className = 'joker-candidate-highlight';

                    var tdRadio = document.createElement('td');
                    var radio = document.createElement('input');
                    radio.type = 'radio';
                    radio.name = 'joker_lap_radio';
                    radio.value = String(l.lap);
                    if (l.lap === jokerSelectedLap) radio.checked = true;
                    tdRadio.appendChild(radio);
                    tr.appendChild(tdRadio);

                    var tdLap = document.createElement('td');
                    tdLap.textContent = String(l.lap);
                    if (l.isCandidate) {
                        tdLap.appendChild(document.createTextNode(' '));
                        var badge = document.createElement('span');
                        badge.className = 'badge-joker';
                        badge.textContent = 'candidate';
                        tdLap.appendChild(badge);
                    }
                    tr.appendChild(tdLap);

                    var tdDist = document.createElement('td');
                    tdDist.textContent = l.dist.toFixed(1);
                    tr.appendChild(tdDist);

                    var tdDelta = document.createElement('td');
                    tdDelta.textContent = (l.delta > 0 ? '+' : '') + l.delta.toFixed(1) + ' m';
                    tdDelta.style.color = l.delta > 0 ? 'var(--orange,#e67e22)' : 'var(--text-secondary)';
                    tr.appendChild(tdDelta);

                    var tdTime = document.createElement('td');
                    tdTime.textContent = l.time.toFixed(3);
                    tr.appendChild(tdTime);

                    var tdTimeDelta = document.createElement('td');
                    tdTimeDelta.textContent = (l.timeDelta > 0 ? '+' : '') + l.timeDelta.toFixed(3) + ' s';
                    tr.appendChild(tdTimeDelta);

                    var tdConf = document.createElement('td');
                    tdConf.textContent = l.isCandidate ? (confidence * 100).toFixed(0) + '%' : '';
                    tr.appendChild(tdConf);

                    tbody.appendChild(tr);
                });

                tbody.addEventListener('change', function (e) {
                    if (e.target.name === 'joker_lap_radio') {
                        jokerSelectedLap = parseInt(e.target.value);
                        if (statusEl) statusEl.textContent = 'Joker lap ' + jokerSelectedLap + ' selected';
                    }
                });

                if (confirmBtn) {
                    confirmBtn.addEventListener('click', function () {
                        if (jokerSelectedLap == null) return;
                        confirmBtn.disabled = true;
                        confirmBtn.textContent = 'Confirming...';

                        fetch('/analyze/api/confirm-joker/' + jobId, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ action: 'confirm', lap_number: jokerSelectedLap }),
                        })
                            .then(function (resp) { return resp.json(); })
                            .then(function (result) {
                                if (result.error) {
                                    if (statusEl) statusEl.textContent = result.error;
                                    confirmBtn.disabled = false;
                                    confirmBtn.textContent = 'Confirm Joker Lap';
                                    return;
                                }
                                jokerConfirmed = true;
                                confirmBtn.textContent = 'Joker lap confirmed!';
                                if (statusEl) statusEl.textContent = 'Lap ' + jokerSelectedLap + ' marked as joker \u2014 pipeline resuming';
                                panel.classList.add('confirmed');

                                if (analysisDone && doneSessionId) {
                                    if (!cornerPickerShown || cornersSubmitted) {
                                        _redirect(doneSessionId);
                                    }
                                }
                            })
                            .catch(function () {
                                if (statusEl) statusEl.textContent = 'Failed \u2014 try again';
                                confirmBtn.disabled = false;
                                confirmBtn.textContent = 'Confirm Joker Lap';
                            });
                    });
                }

                if (rejectBtn) {
                    rejectBtn.addEventListener('click', function () {
                        rejectBtn.disabled = true;
                        rejectBtn.textContent = 'Rejecting...';

                        fetch('/analyze/api/confirm-joker/' + jobId, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ action: 'reject' }),
                        })
                            .then(function (resp) { return resp.json(); })
                            .then(function (result) {
                                if (result.error) {
                                    if (statusEl) statusEl.textContent = result.error;
                                    rejectBtn.disabled = false;
                                    rejectBtn.textContent = 'No Joker Lap';
                                    return;
                                }
                                jokerConfirmed = true;
                                if (statusEl) statusEl.textContent = 'No joker lap \u2014 pipeline resuming';
                                panel.classList.add('confirmed');

                                if (analysisDone && doneSessionId) {
                                    if (!cornerPickerShown || cornersSubmitted) {
                                        _redirect(doneSessionId);
                                    }
                                }
                            })
                            .catch(function () {
                                if (statusEl) statusEl.textContent = 'Failed \u2014 try again';
                                rejectBtn.disabled = false;
                                rejectBtn.textContent = 'No Joker Lap';
                            });
                    });
                }
            }

            function _redirect(sessionId) {
                if (window.Toast) Toast.success('Analysis complete', 'Redirecting to session...');
                setTimeout(function () {
                    window.location.href = '/sessions/' + sessionId;
                }, 600);
            }

            var elapsedInterval = setInterval(function () {
                var elapsed = Math.round((Date.now() - startTime) / 1000);
                if (elapsedEl) elapsedEl.textContent = 'Elapsed: ' + elapsed + 's';
            }, 1000);

            function poll() {
                fetch('/analyze/api/status/' + jobId)
                    .then(function (resp) { return resp.json(); })
                    .then(function (data) {
                        if (data.error && data.status === 'error') {
                            clearInterval(elapsedInterval);
                            showAnalysisError(data.error);
                            return;
                        }

                        if (stageText) stageText.textContent = data.stage + '...';
                        if (overallFill) overallFill.style.width = data.progress + '%';
                        if (elapsedEl) elapsedEl.textContent = 'Elapsed: ' + data.elapsed + 's';
                        updateStageDots(data.progress);

                        if (data.corners_ready && data.track_layout && !cornerPickerShown) {
                            showCornerPicker(data.track_layout);
                        }

                        if (data.joker_ready && data.joker_candidates && !jokerPanelShown) {
                            showJokerPanel(data.joker_candidates);
                        }

                        if (data.joker_ready && !jokerConfirmed && !data.joker_timed_out) {
                            if (stageText) stageText.textContent = 'Confirm or reject the joker lap to continue...';
                        }

                        if (data.status === 'done') {
                            clearInterval(elapsedInterval);
                            if (overallFill) overallFill.style.width = '100%';
                            if (stageText) stageText.textContent = 'Analysis complete!';

                            stagesDots.forEach(function (s) {
                                s.classList.add('completed');
                                s.classList.remove('active');
                                var d = s.querySelector('.pipeline-stage-dot');
                                if (d) { d.classList.add('completed'); d.classList.remove('active'); }
                            });

                            analysisDone = true;
                            doneSessionId = data.session_id;

                            if (data.session_id) {
                                var cornersOk = !cornerPickerShown || cornersSubmitted;
                                var jokerOk = !jokerPanelShown || jokerConfirmed;
                                if (cornersOk && jokerOk) {
                                    _redirect(data.session_id);
                                } else {
                                    var waiting = [];
                                    if (!cornersOk) waiting.push('areas of interest');
                                    if (!jokerOk) waiting.push('joker lap');
                                    if (stageText) stageText.textContent = 'Confirm your ' + waiting.join(' and ') + ' to continue';
                                }
                            } else if (data.error) {
                                showAnalysisError(data.error);
                            } else {
                                window.location.href = '/';
                            }
                            return;
                        }

                        setTimeout(poll, 800);
                    })
                    .catch(function () {
                        setTimeout(poll, 2000);
                    });
            }

            setTimeout(poll, 500);
        }

        function showAnalysisError(message) {
            var stageText = document.getElementById('analysis-stage-text');
            var overallFill = document.getElementById('analysis-overall-fill');
            var progressPanel = document.getElementById('analysis-progress');

            if (stageText) {
                stageText.textContent = 'Analysis failed';
                stageText.style.color = 'var(--red)';
            }
            if (overallFill) {
                overallFill.style.background = 'var(--red)';
            }

            if (progressPanel) {
                var errorDiv = document.createElement('div');
                errorDiv.className = 'analysis-error-details';

                var errP = document.createElement('p');
                errP.className = 'text-red';
                errP.style.cssText = 'margin-top:var(--sp-md);word-break:break-word;';
                errP.textContent = message;
                errorDiv.appendChild(errP);

                var retryBtn = document.createElement('button');
                retryBtn.type = 'button';
                retryBtn.className = 'btn btn-primary';
                retryBtn.style.marginTop = 'var(--sp-md)';
                retryBtn.textContent = 'Try Again';
                retryBtn.addEventListener('click', function () { window.location.reload(); });
                errorDiv.appendChild(retryBtn);

                progressPanel.appendChild(errorDiv);
            }

            if (window.Toast) Toast.error('Analysis failed', message);
        }

        // ── Multi-driver management with dropdown ──
        var driverContainer = document.getElementById('drivers-container');
        var addDriverBtn = document.getElementById('add-driver-btn');
        var driverCount = 1;
        var existingDriverOptions = [];
        var driverSelects = document.querySelectorAll('.driver-select');
        if (driverSelects.length > 0) {
            // Clone options from first select for reuse in new rows
            var opts = driverSelects[0].querySelectorAll('option');
            opts.forEach(function (o) {
                existingDriverOptions.push({ value: o.value, text: o.textContent });
            });
        }

        function buildDriverSelect(idx) {
            var sel = document.createElement('select');
            sel.className = 'form-select driver-select';
            sel.dataset.idx = String(idx);
            existingDriverOptions.forEach(function (o) {
                var opt = document.createElement('option');
                opt.value = o.value;
                opt.textContent = o.text;
                sel.appendChild(opt);
            });
            return sel;
        }

        function setupDriverRow(row) {
            var sel = row.querySelector('.driver-select');
            var inp = row.querySelector('.driver-name-input');
            var hint = row.querySelector('.driver-match-hint');
            if (!sel || !inp) return;

            sel.addEventListener('change', function () {
                if (sel.value === '__new__') {
                    inp.classList.remove('hidden');
                    inp.value = '';
                    inp.focus();
                } else if (sel.value) {
                    inp.classList.add('hidden');
                    inp.value = sel.value;
                    if (hint) hint.classList.add('hidden');
                } else {
                    inp.classList.add('hidden');
                    inp.value = '';
                }
            });

            var debounceTimer = null;
            inp.addEventListener('blur', function () {
                clearTimeout(debounceTimer);
                var name = inp.value.trim();
                if (!name || name.length < 2) { if (hint) hint.classList.add('hidden'); return; }
                debounceTimer = setTimeout(function () {
                    fetch('/api/drivers/normalize', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: name }),
                    })
                        .then(function (r) { return r.json(); })
                        .then(function (data) {
                            if (data.match && data.match.driver_name !== name) {
                                if (hint) {
                                    hint.textContent = 'Did you mean "' + data.match.driver_name + '"? Using existing driver.';
                                    hint.classList.remove('hidden');
                                }
                                inp.value = data.match.driver_name;
                            } else {
                                if (hint) hint.classList.add('hidden');
                            }
                        })
                        .catch(function () { /* ignore */ });
                }, 300);
            });
        }

        var firstDriverRow = driverContainer ? driverContainer.querySelector('.driver-row') : null;
        if (firstDriverRow) setupDriverRow(firstDriverRow);

        if (addDriverBtn && driverContainer) {
            addDriverBtn.addEventListener('click', function () {
                var idx = driverCount++;
                var row = document.createElement('div');
                row.className = 'driver-row';
                row.dataset.driverIndex = idx;

                var fields = document.createElement('div');
                fields.className = 'driver-row-fields';

                var fg = document.createElement('div');
                fg.className = 'form-group';
                fg.style.cssText = 'flex:2;min-width:180px;';
                var lbl = document.createElement('label');
                lbl.textContent = 'Driver';
                fg.appendChild(lbl);

                var wrap = document.createElement('div');
                wrap.className = 'driver-select-wrap';

                var sel = buildDriverSelect(idx);
                wrap.appendChild(sel);

                var inp = document.createElement('input');
                inp.type = 'text';
                inp.name = 'driver_name_' + idx;
                inp.className = 'form-input driver-name-input hidden';
                inp.placeholder = 'Enter driver name';
                inp.autocomplete = 'name';
                inp.dataset.idx = String(idx);
                wrap.appendChild(inp);

                fg.appendChild(wrap);

                var hintSpan = document.createElement('span');
                hintSpan.className = 'driver-match-hint hidden';
                hintSpan.dataset.idx = String(idx);
                fg.appendChild(hintSpan);

                fields.appendChild(fg);

                var actionFg = document.createElement('div');
                actionFg.className = 'form-group driver-col-action';
                var removeBtn = document.createElement('button');
                removeBtn.type = 'button';
                removeBtn.className = 'btn btn-xs remove-driver-btn';
                removeBtn.setAttribute('aria-label', 'Remove driver');
                removeBtn.textContent = '\u00D7';
                actionFg.appendChild(removeBtn);
                fields.appendChild(actionFg);

                row.appendChild(fields);
                driverContainer.appendChild(row);
                setupDriverRow(row);
                updateRemoveButtons();
            });

            driverContainer.addEventListener('click', function (e) {
                if (e.target.classList.contains('remove-driver-btn')) {
                    var row = e.target.closest('.driver-row');
                    if (row) { row.remove(); updateRemoveButtons(); }
                }
            });
        }

        function updateRemoveButtons() {
            if (!driverContainer) return;
            var rows = driverContainer.querySelectorAll('.driver-row');
            rows.forEach(function (r) {
                var btn = r.querySelector('.remove-driver-btn');
                if (btn) {
                    if (rows.length > 1) { btn.removeAttribute('hidden'); } else { btn.setAttribute('hidden', ''); }
                }
            });
        }

        // ── Track selection with "New Track" + predefined search ──
        var trackSelect = document.getElementById('track-name');
        var newTrackInput = document.getElementById('new-track-name');
        var predefinedSearch = document.getElementById('predefined-track-search');
        var predefinedFilter = document.getElementById('predefined-track-filter');
        var predefinedResults = document.getElementById('predefined-track-results');
        var jokerCheckbox = document.getElementById('enable-joker');
        var predefinedTracks = null;

        if (trackSelect) {
            trackSelect.addEventListener('change', function () {
                var val = trackSelect.value;

                if (val === '__new__') {
                    if (newTrackInput) { newTrackInput.classList.remove('hidden'); newTrackInput.focus(); }
                    if (predefinedSearch) predefinedSearch.classList.add('hidden');
                } else {
                    if (newTrackInput) newTrackInput.classList.add('hidden');
                    if (predefinedSearch) predefinedSearch.classList.add('hidden');
                }

                if (jokerCheckbox) {
                    var selected = trackSelect.options[trackSelect.selectedIndex];
                    var hasJoker = selected ? selected.getAttribute('data-has-joker') : '0';
                    jokerCheckbox.checked = (hasJoker === '1');
                }
            });

            fetch('/api/predefined-tracks')
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    predefinedTracks = data.tracks || [];
                })
                .catch(function () { /* predefined tracks not available */ });

            if (predefinedFilter && predefinedResults) {
                predefinedFilter.addEventListener('input', function () {
                    if (!predefinedTracks) return;
                    var q = predefinedFilter.value.trim().toLowerCase();
                    if (q.length < 2) { predefinedResults.textContent = ''; return; }
                    var matches = predefinedTracks.filter(function (t) {
                        return t.label.toLowerCase().indexOf(q) >= 0 ||
                               t.country.toLowerCase().indexOf(q) >= 0 ||
                               (t.city && t.city.toLowerCase().indexOf(q) >= 0);
                    }).slice(0, 20);

                    predefinedResults.textContent = '';
                    matches.forEach(function (t) {
                        var item = document.createElement('div');
                        item.className = 'predefined-track-item';
                        item.dataset.trackLabel = t.label;
                        item.dataset.trackName = t.name;
                        item.textContent = t.label;
                        var country = document.createElement('span');
                        country.className = 'track-country';
                        country.textContent = t.country;
                        item.appendChild(country);
                        predefinedResults.appendChild(item);
                    });
                });

                predefinedResults.addEventListener('click', function (e) {
                    var item = e.target.closest('.predefined-track-item');
                    if (!item) return;
                    var name = item.dataset.trackName;
                    trackSelect.value = '__new__';
                    if (newTrackInput) {
                        newTrackInput.classList.remove('hidden');
                        newTrackInput.value = name;
                    }
                    if (predefinedSearch) predefinedSearch.classList.add('hidden');
                    if (predefinedFilter) predefinedFilter.value = '';
                    predefinedResults.textContent = '';
                });
            }
        }

        // Add browse predefined button
        if (trackSelect) {
            var trackCardBody = trackSelect.closest('.config-card-body');
            if (trackCardBody) {
                var browseBtn = document.createElement('button');
                browseBtn.type = 'button';
                browseBtn.className = 'btn btn-xs mt-sm';
                browseBtn.textContent = 'Browse predefined tracks';
                browseBtn.style.marginRight = '0.5rem';
                browseBtn.addEventListener('click', function () {
                    if (predefinedSearch) {
                        predefinedSearch.classList.toggle('hidden');
                        if (!predefinedSearch.classList.contains('hidden') && predefinedFilter) {
                            predefinedFilter.focus();
                        }
                    }
                });
                var formRow = trackCardBody.querySelector('.form-row');
                if (formRow) formRow.parentNode.insertBefore(browseBtn, formRow.nextSibling);
            }
        }

        // ── Kart Model selection ──
        var kartSelect = document.getElementById('kart-model-select');
        var kartHidden = document.getElementById('kart-model-hidden');
        var newKartInput = document.getElementById('new-kart-name');
        var kartSpecs = document.getElementById('kart-specs');

        if (kartSelect) {
            fetch('/api/predefined-karts')
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    var segments = data.segments || {};
                    for (var seg in segments) {
                        var group = document.createElement('optgroup');
                        group.label = seg;
                        segments[seg].forEach(function (k) {
                            var opt = document.createElement('option');
                            opt.value = k.model;
                            var label = k.model;
                            if (k.power_hp) label += ' (' + k.power_hp + 'hp)';
                            opt.textContent = label;
                            opt.dataset.engine = k.engine || '';
                            opt.dataset.weight = k.kart_weight_kg || '';
                            opt.dataset.topSpeed = k.top_speed_kmh || '';
                            opt.dataset.power = k.power_hp || '';
                            opt.dataset.lateralG = k.lateral_g_est || '';
                            group.appendChild(opt);
                        });
                        kartSelect.appendChild(group);
                    }
                })
                .catch(function () { /* kart list not available */ });

            kartSelect.addEventListener('change', function () {
                if (kartSelect.value === '__new__') {
                    if (newKartInput) { newKartInput.classList.remove('hidden'); newKartInput.focus(); }
                    if (kartSpecs) kartSpecs.classList.add('hidden');
                    if (kartHidden) kartHidden.value = '';
                } else if (kartSelect.value) {
                    if (newKartInput) newKartInput.classList.add('hidden');
                    if (kartHidden) kartHidden.value = kartSelect.value;
                    var opt = kartSelect.options[kartSelect.selectedIndex];
                    if (kartSpecs && opt) {
                        kartSpecs.textContent = '';
                        var specItems = [];
                        if (opt.dataset.engine) specItems.push(opt.dataset.engine);
                        if (opt.dataset.power) specItems.push(opt.dataset.power + ' hp');
                        if (opt.dataset.weight) specItems.push(opt.dataset.weight + ' kg');
                        if (opt.dataset.topSpeed) specItems.push(opt.dataset.topSpeed + ' km/h');
                        if (opt.dataset.lateralG) specItems.push(opt.dataset.lateralG + ' G lat');
                        specItems.forEach(function (txt) {
                            var tag = document.createElement('span');
                            tag.className = 'kart-spec-tag';
                            tag.textContent = txt;
                            kartSpecs.appendChild(tag);
                        });
                        if (specItems.length > 0) {
                            kartSpecs.classList.remove('hidden');
                        } else {
                            kartSpecs.classList.add('hidden');
                        }
                    }
                } else {
                    if (newKartInput) newKartInput.classList.add('hidden');
                    if (kartSpecs) kartSpecs.classList.add('hidden');
                    if (kartHidden) kartHidden.value = '';
                }
            });
        }

        // ── Endurance stint management ──
        var standardConditions = document.getElementById('standard-conditions-group');
        var standardDrivers = document.getElementById('standard-drivers-group');
        var enduranceGroup = document.getElementById('endurance-stints-group');
        var stintsContainer = document.getElementById('stints-container');
        var addStintBtn = document.getElementById('add-stint-btn');
        var stintsSummary = document.getElementById('stints-summary');
        var stintCount = 0;

        var CONDITION_OPTIONS = [
            'dry', 'wet', 'damp', 'mixed', 'drying', 'greasy', 'flooded', 'dusty', 'cold', 'hot'
        ];

        function _buildConditionSelect(selected) {
            var sel = document.createElement('select');
            sel.className = 'form-select stint-condition';
            sel.style.cssText = 'padding:0.3rem 0.5rem;font-size:0.85rem;';
            CONDITION_OPTIONS.forEach(function (c) {
                var opt = document.createElement('option');
                opt.value = c;
                opt.textContent = c.charAt(0).toUpperCase() + c.slice(1);
                if (c === selected) opt.selected = true;
                sel.appendChild(opt);
            });
            return sel;
        }

        function addStintRow(driverVal, lapsVal, conditionVal) {
            var idx = stintCount++;
            var row = document.createElement('div');
            row.className = 'stint-row form-row';
            row.dataset.stintIndex = idx;
            row.style.cssText = 'display:flex;gap:0.5rem;align-items:flex-end;flex-wrap:wrap;padding:0.5rem 0.6rem;margin-bottom:0.4rem;'
                + 'background:var(--bg-tertiary,#161b22);border-radius:8px;border-left:3px solid var(--accent);';

            // Number
            var numDiv = document.createElement('div');
            numDiv.style.cssText = 'min-width:26px;font-weight:700;color:var(--accent);font-size:0.9rem;padding-bottom:0.4rem;';
            var numSpan = document.createElement('span');
            numSpan.className = 'stint-number';
            numSpan.textContent = String(idx + 1);
            numDiv.appendChild(numSpan);
            row.appendChild(numDiv);

            // Driver
            var driverFg = document.createElement('div');
            driverFg.className = 'form-group';
            driverFg.style.cssText = 'flex:2;min-width:130px;margin:0;';
            var driverLabel = document.createElement('label');
            driverLabel.style.cssText = 'font-size:0.72rem;font-weight:600;';
            driverLabel.textContent = 'Driver';
            driverFg.appendChild(driverLabel);
            var driverInp = document.createElement('input');
            driverInp.type = 'text';
            driverInp.className = 'form-input stint-driver';
            driverInp.placeholder = 'Driver name';
            driverInp.value = driverVal || '';
            driverInp.style.cssText = 'padding:0.3rem 0.5rem;font-size:0.85rem;';
            driverFg.appendChild(driverInp);
            row.appendChild(driverFg);

            // Laps
            var lapsFg = document.createElement('div');
            lapsFg.className = 'form-group';
            lapsFg.style.cssText = 'flex:1;min-width:80px;max-width:100px;margin:0;';
            var lapsLabel = document.createElement('label');
            lapsLabel.style.cssText = 'font-size:0.72rem;font-weight:600;';
            lapsLabel.textContent = 'Laps';
            lapsFg.appendChild(lapsLabel);
            var lapsInp = document.createElement('input');
            lapsInp.type = 'number';
            lapsInp.className = 'form-input stint-laps';
            lapsInp.min = '1';
            lapsInp.max = '999';
            lapsInp.step = '1';
            lapsInp.placeholder = '# laps';
            lapsInp.value = lapsVal || '';
            lapsInp.style.cssText = 'padding:0.3rem 0.5rem;font-size:0.85rem;';
            lapsFg.appendChild(lapsInp);
            row.appendChild(lapsFg);

            // Conditions
            var condFg = document.createElement('div');
            condFg.className = 'form-group';
            condFg.style.cssText = 'flex:1.5;min-width:110px;margin:0;';
            var condLabel = document.createElement('label');
            condLabel.style.cssText = 'font-size:0.72rem;font-weight:600;';
            condLabel.textContent = 'Conditions';
            condFg.appendChild(condLabel);
            condFg.appendChild(_buildConditionSelect(conditionVal || 'dry'));
            row.appendChild(condFg);

            // Remove button
            var removeDiv = document.createElement('div');
            removeDiv.style.cssText = 'margin:0;padding-bottom:0.15rem;';
            var removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'btn btn-xs remove-stint-btn';
            removeBtn.setAttribute('aria-label', 'Remove stint');
            removeBtn.style.cssText = 'color:var(--red);font-size:1rem;line-height:1;padding:0.2rem 0.4rem;';
            removeBtn.textContent = '\u00D7';
            removeDiv.appendChild(removeBtn);
            row.appendChild(removeDiv);

            stintsContainer.appendChild(row);
            updateStintNumbers();
            updateStintsSummary();
            return row;
        }

        function updateStintNumbers() {
            var rows = stintsContainer.querySelectorAll('.stint-row');
            rows.forEach(function (r, i) {
                var num = r.querySelector('.stint-number');
                if (num) num.textContent = i + 1;
            });
            rows.forEach(function (r) {
                var btn = r.querySelector('.remove-stint-btn');
                if (btn) btn.style.display = rows.length <= 1 ? 'none' : '';
            });
        }

        function updateStintsSummary() {
            var rows = stintsContainer.querySelectorAll('.stint-row');
            var totalLaps = 0;
            var driverSet = {};
            var condSet = {};
            rows.forEach(function (r) {
                var laps = parseInt(r.querySelector('.stint-laps').value) || 0;
                totalLaps += laps;
                var drv = (r.querySelector('.stint-driver').value || '').trim();
                if (drv) driverSet[drv] = true;
                condSet[r.querySelector('.stint-condition').value] = true;
            });
            var parts = [];
            parts.push(rows.length + ' stint' + (rows.length !== 1 ? 's' : ''));
            if (totalLaps > 0) parts.push(totalLaps + ' total laps');
            var driverNames = Object.keys(driverSet);
            if (driverNames.length > 0) parts.push(driverNames.length + ' driver' + (driverNames.length !== 1 ? 's' : ''));
            var conds = Object.keys(condSet);
            if (conds.length > 0) parts.push('Conditions: ' + conds.join(', '));
            if (stintsSummary) stintsSummary.textContent = parts.join('  \u00B7  ');
        }

        function syncStintsToFormFields() {
            var oldFields = form.querySelectorAll('.stint-generated-field');
            oldFields.forEach(function (f) { f.remove(); });

            var rows = stintsContainer.querySelectorAll('.stint-row');
            var lapCursor = 1;
            var allConditions = {};

            rows.forEach(function (r, idx) {
                var driver = (r.querySelector('.stint-driver').value || 'Driver_1').trim();
                var laps = parseInt(r.querySelector('.stint-laps').value) || 0;
                var condition = r.querySelector('.stint-condition').value;

                allConditions[condition] = true;

                var lapStart = lapCursor;
                var lapEnd = laps > 0 ? lapCursor + laps - 1 : 999;
                if (laps > 0) lapCursor = lapEnd + 1;

                _addHidden('driver_name_' + idx, driver);
                _addHidden('driver_lap_start_' + idx, lapStart);
                _addHidden('driver_lap_end_' + idx, lapEnd);

                if (idx === 0) {
                    var primary = document.getElementById('primary-driver-hidden');
                    if (primary) primary.value = driver;
                }
            });

            var trackStateHidden = document.getElementById('track-state-hidden');
            if (trackStateHidden) {
                var conds = Object.keys(allConditions);
                trackStateHidden.value = conds.length > 0 ? conds.join(',') : 'dry';
            }
        }

        function _addHidden(name, value) {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = value;
            input.className = 'stint-generated-field';
            form.appendChild(input);
        }

        function switchToEnduranceMode() {
            if (standardConditions) standardConditions.style.display = 'none';
            if (standardDrivers) standardDrivers.style.display = 'none';
            if (enduranceGroup) enduranceGroup.classList.remove('hidden');

            if (stintsContainer && stintsContainer.querySelectorAll('.stint-row').length === 0) {
                var existingDriverRows = document.querySelectorAll('#drivers-container .driver-row');
                if (existingDriverRows.length > 0) {
                    existingDriverRows.forEach(function (r) {
                        var inp = r.querySelector('.driver-name-input');
                        var name = inp ? inp.value : '';
                        addStintRow(name, '', 'dry');
                    });
                } else {
                    addStintRow('Driver_1', '', 'dry');
                }
            }
        }

        function switchToStandardMode() {
            if (standardConditions) standardConditions.style.display = '';
            if (standardDrivers) standardDrivers.style.display = '';
            if (enduranceGroup) enduranceGroup.classList.add('hidden');
        }

        if (sessionTypeSelect) {
            sessionTypeSelect.addEventListener('change', function () {
                updateSessionTypeHint();
                if (sessionTypeSelect.value === 'endurance') {
                    switchToEnduranceMode();
                } else {
                    switchToStandardMode();
                }
            });
            if (sessionTypeSelect.value === 'endurance') switchToEnduranceMode();
            updateSessionTypeHint();
        }

        if (addStintBtn) {
            addStintBtn.addEventListener('click', function () {
                var lastRow = stintsContainer.querySelector('.stint-row:last-child');
                var lastDriver = lastRow ? (lastRow.querySelector('.stint-driver').value || '') : '';
                var lastCond = lastRow ? lastRow.querySelector('.stint-condition').value : 'dry';
                addStintRow(lastDriver, '', lastCond);
            });
        }

        if (stintsContainer) {
            stintsContainer.addEventListener('click', function (e) {
                if (e.target.classList.contains('remove-stint-btn')) {
                    var row = e.target.closest('.stint-row');
                    if (row) {
                        row.remove();
                        updateStintNumbers();
                        updateStintsSummary();
                    }
                }
            });

            stintsContainer.addEventListener('input', function () {
                updateStintsSummary();
            });
            stintsContainer.addEventListener('change', function () {
                updateStintsSummary();
            });
        }

        // ── Track conditions sync ──
        function syncTrackState() {
            var boxes = document.querySelectorAll('input[name="track_conditions"]:checked');
            var vals = [];
            boxes.forEach(function (cb) { vals.push(cb.value); });
            var hidden = document.getElementById('track-state-hidden');
            if (hidden) {
                hidden.value = vals.length > 0 ? vals.join(',') : 'dry';
            }
        }

        // ── Helpers ──
        function escapeHtml(s) {
            var d = document.createElement('div');
            d.textContent = s;
            return d.innerHTML;
        }
        function escapeAttr(s) {
            return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }
    });
})();
