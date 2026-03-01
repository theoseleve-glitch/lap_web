/**
 * focus_mode.js — Focus Mode controller for the telemetry dashboard.
 *
 * Manages the fullscreen overlay, icon dock sidebar, tool registry,
 * SplitPane integration for resizable panels, smart default tool
 * groupings, keyboard shortcuts, and localStorage persistence.
 *
 * Depends on: window.SplitPane (split_pane.js)
 *
 * Public API:
 *   FocusMode.registerTool(id, { icon, label, tabs, render, available })
 *   FocusMode.open({ primaryTool, tab })
 *   FocusMode.close()
 *   FocusMode.toggle(tab)
 */
(function () {
    'use strict';
    var _lc = window.LifecycleHelpers.create();

    // -----------------------------------------------------------------
    // Smart defaults — which tools appear together
    // -----------------------------------------------------------------

    var DEFAULTS = {
        'track-map':        ['track-map', 'speed-trace', 'gg-diagram'],
        'speed-trace':      ['speed-trace', 'track-map', 'lap-overlay'],
        'gg-diagram':       ['gg-diagram', 'track-map', 'speed-trace'],
        'lap-overlay':      ['lap-overlay', 'speed-trace', 'lap-distribution'],
        'lap-distribution': ['lap-distribution', 'lap-progress', 'lap-overlay'],
        'stint-analysis':   ['stint-analysis', 'driver-workload', 'lap-progress'],
        'badges':           ['badges', 'lap-distribution']
    };

    var TAB_DEFAULTS = {
        'analytics':   ['track-map', 'speed-trace', 'gg-diagram', 'lap-distribution'],
        'corners':     ['track-map', 'gg-diagram'],
        'performance': ['stint-analysis', 'driver-workload', 'lap-progress', 'session-timeline'],
        'overview':    ['badges', 'lap-distribution']
    };

    // -----------------------------------------------------------------
    // Private state
    // -----------------------------------------------------------------

    var _tools = {};        // id -> { icon, label, tabs, render, available }
    var _rendered = {};     // id -> result of tool.render()
    var _activeTools = [];  // ordered list of active tool ids
    var _splitPane = null;  // current SplitPane instance
    var _overlay = null;    // the .focus-overlay element
    var _dock = null;       // the .focus-dock element
    var _panelsArea = null; // wrapper for corner nav + panels
    var _cornerNav = null;  // the .focus-corner-nav element
    var _panels = null;     // the .focus-panels element
    var _isOpen = false;
    var _currentTab = null;

    // -----------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------

    function _clearChildren(el) {
        while (el.firstChild) {
            el.removeChild(el.firstChild);
        }
    }

    function _guessCurrentTab() {
        var activeBtn = document.querySelector('.session-tab.active');
        return activeBtn ? activeBtn.dataset.tab : 'analytics';
    }

    function _getSessionId() {
        var el = document.querySelector('[data-session-id]');
        return el ? el.getAttribute('data-session-id') : null;
    }

    // -----------------------------------------------------------------
    // localStorage helpers (wrapped in try/catch)
    // -----------------------------------------------------------------

    function _saveLayout(tab, toolIds) {
        try {
            localStorage.setItem('focus_layout_' + tab, JSON.stringify(toolIds));
        } catch (e) { /* quota or private browsing */ }
    }

    function _loadLayout(tab) {
        try {
            var raw = localStorage.getItem('focus_layout_' + tab);
            if (raw) {
                return JSON.parse(raw);
            }
        } catch (e) { /* parse error or unavailable */ }
        return null;
    }

    // -----------------------------------------------------------------
    // Overlay DOM construction (createElement only, no innerHTML)
    // -----------------------------------------------------------------

    function _ensureOverlay() {
        if (_overlay) return;

        _overlay = document.createElement('div');
        _overlay.className = 'focus-overlay';

        _dock = document.createElement('div');
        _dock.className = 'focus-dock';

        _panelsArea = document.createElement('div');
        _panelsArea.className = 'focus-panels-area';

        _cornerNav = document.createElement('div');
        _cornerNav.className = 'focus-corner-nav';
        _cornerNav.style.display = 'none';

        _panels = document.createElement('div');
        _panels.className = 'focus-panels';

        _panelsArea.appendChild(_cornerNav);
        _panelsArea.appendChild(_panels);

        _overlay.appendChild(_dock);
        _overlay.appendChild(_panelsArea);
        document.body.appendChild(_overlay);
    }

    // -----------------------------------------------------------------
    // Dock building
    // -----------------------------------------------------------------

    function _buildDock() {
        _clearChildren(_dock);

        // Iterate all tools registered for the current tab
        var toolIds = Object.keys(_tools);
        for (var i = 0; i < toolIds.length; i++) {
            var id = toolIds[i];
            var tool = _tools[id];

            // Only show tools that belong to this tab
            if (tool.tabs && tool.tabs.indexOf(_currentTab) === -1) {
                continue;
            }

            var btn = document.createElement('button');
            btn.className = 'focus-dock-btn';
            btn.setAttribute('type', 'button');
            btn.setAttribute('data-tool-id', id);
            btn.textContent = tool.icon || '';

            // Hover label
            var label = document.createElement('span');
            label.className = 'focus-dock-label';
            label.textContent = tool.label || id;
            btn.appendChild(label);

            // Mark active or unavailable
            var isAvailable = typeof tool.available === 'function' ? tool.available() : true;
            if (!isAvailable) {
                btn.classList.add('unavailable');
            } else if (_activeTools.indexOf(id) !== -1) {
                btn.classList.add('active');
            }

            // Click handler (closure to capture id and isAvailable)
            _lc.addListener(btn, 'click', (function (toolId, avail) {
                return function () {
                    if (!avail) return;
                    _toggleTool(toolId);
                };
            })(id, isAvailable));

            _dock.appendChild(btn);
        }

        // Separator
        var sep = document.createElement('div');
        sep.className = 'focus-dock-sep';
        _dock.appendChild(sep);

        // Reset layout button
        var resetBtn = document.createElement('button');
        resetBtn.className = 'focus-dock-btn';
        resetBtn.setAttribute('type', 'button');
        resetBtn.textContent = '\u21BB'; // ↻
        var resetLabel = document.createElement('span');
        resetLabel.className = 'focus-dock-label';
        resetLabel.textContent = 'Reset layout';
        resetBtn.appendChild(resetLabel);
        _lc.addListener(resetBtn, 'click', function () {
            if (_splitPane) {
                _splitPane.resetLayout();
            }
        });
        _dock.appendChild(resetBtn);

        // Close button (pushed to bottom via margin-top: auto in CSS)
        var closeBtn = document.createElement('button');
        closeBtn.className = 'focus-dock-btn focus-dock-close';
        closeBtn.setAttribute('type', 'button');
        closeBtn.textContent = '\u2715'; // ✕
        var closeLabel = document.createElement('span');
        closeLabel.className = 'focus-dock-label';
        closeLabel.textContent = 'Close';
        closeBtn.appendChild(closeLabel);
        _lc.addListener(closeBtn, 'click', function () {
            close();
        });
        _dock.appendChild(closeBtn);
    }

    // -----------------------------------------------------------------
    // Toggle a tool on/off in the active list
    // -----------------------------------------------------------------

    function _toggleTool(id) {
        var idx = _activeTools.indexOf(id);
        if (idx !== -1) {
            _activeTools.splice(idx, 1);
        } else {
            _activeTools.push(id);
        }
        _buildDock();
        _renderPanels();
    }

    // -----------------------------------------------------------------
    // Panel rendering
    // -----------------------------------------------------------------

    function _renderPanels() {
        var sessionId = _getSessionId();

        // Destroy old rendered tools that are no longer active
        var renderedIds = Object.keys(_rendered);
        for (var r = 0; r < renderedIds.length; r++) {
            var rid = renderedIds[r];
            if (_activeTools.indexOf(rid) === -1) {
                if (_rendered[rid] && typeof _rendered[rid].destroy === 'function') {
                    try { _rendered[rid].destroy(); } catch (e) { /* ignore */ }
                }
                delete _rendered[rid];
            }
        }

        // Destroy SplitPane and clear panels container
        if (_splitPane) {
            _splitPane.destroy();
            _splitPane = null;
        }
        _clearChildren(_panels);

        // If no active tools, show placeholder message
        if (_activeTools.length === 0) {
            var msg = document.createElement('div');
            msg.style.display = 'flex';
            msg.style.alignItems = 'center';
            msg.style.justifyContent = 'center';
            msg.style.height = '100%';
            msg.style.color = 'var(--text-muted, #484f58)';
            msg.style.fontSize = '14px';
            msg.textContent = 'Click a tool icon in the sidebar to add a panel.';
            _panels.appendChild(msg);
            return;
        }

        // Create new SplitPane
        _splitPane = window.SplitPane.create(_panels);

        // For each active tool, add panel and render
        for (var i = 0; i < _activeTools.length; i++) {
            var id = _activeTools[i];
            var tool = _tools[id];
            if (!tool) continue;

            var panelEl = _splitPane.addPanel(id);

            // Panel header label
            var header = document.createElement('div');
            header.className = 'sp-panel-header';
            header.textContent = tool.label || id;
            panelEl.appendChild(header);

            // Chart container
            var container = document.createElement('div');
            container.className = 'chart-container';
            panelEl.appendChild(container);

            // Render tool into container
            if (typeof tool.render === 'function') {
                try {
                    var result = tool.render(container, sessionId);
                    _rendered[id] = result || null;
                } catch (e) {
                    console.warn('[FocusMode] render failed for tool "' + id + '":', e);
                    _rendered[id] = null;
                }
            }
        }
    }

    // -----------------------------------------------------------------
    // Public API: registerTool
    // -----------------------------------------------------------------

    function registerTool(id, opts) {
        _tools[id] = {
            icon:      opts.icon || '',
            label:     opts.label || id,
            tabs:      opts.tabs || null,
            render:    opts.render || null,
            available: opts.available || null
        };
    }

    // -----------------------------------------------------------------
    // Public API: open
    // -----------------------------------------------------------------

    function open(opts) {
        opts = opts || {};
        var primaryTool = opts.primaryTool || null;
        var tab = opts.tab || _guessCurrentTab();
        _currentTab = tab;

        _ensureOverlay();

        // 1. Determine tools: check localStorage first
        var toolIds = _loadLayout(tab);

        // 2. If none saved, use DEFAULTS for primaryTool or TAB_DEFAULTS for tab
        if (!toolIds || toolIds.length === 0) {
            if (primaryTool && DEFAULTS[primaryTool]) {
                toolIds = DEFAULTS[primaryTool].slice();
            } else if (TAB_DEFAULTS[tab]) {
                toolIds = TAB_DEFAULTS[tab].slice();
            } else {
                toolIds = [];
            }
        }

        // 3. Filter to only registered + available + matching the tab
        toolIds = toolIds.filter(function (id) {
            var tool = _tools[id];
            if (!tool) return false;
            if (tool.tabs && tool.tabs.indexOf(tab) === -1) return false;
            var avail = typeof tool.available === 'function' ? tool.available() : true;
            return avail;
        });

        // 4. If primaryTool not in list, prepend it
        if (primaryTool && _tools[primaryTool] && toolIds.indexOf(primaryTool) === -1) {
            var pt = _tools[primaryTool];
            var ptAvail = typeof pt.available === 'function' ? pt.available() : true;
            if (ptAvail) {
                toolIds.unshift(primaryTool);
            }
        }

        _activeTools = toolIds;

        // 5. Build dock sidebar
        _buildDock();

        // 6. Load corner time-loss nav bar
        _loadCornerNav();

        // 7. Render panels
        _renderPanels();

        // 8. Show overlay
        _overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
        _isOpen = true;
    }

    // -----------------------------------------------------------------
    // Corner time-loss nav bar (top bar in focus mode)
    // -----------------------------------------------------------------

    var _cornerNavLoaded = false;

    function _loadCornerNav() {
        if (_cornerNavLoaded || !_cornerNav) return;
        _cornerNavLoaded = true;

        var sessionId = _getSessionId();
        if (!sessionId) return;

        var url = '/api/session/' + encodeURIComponent(sessionId) + '/corner-metrics/summary';
        if (typeof FetchHelper !== 'undefined') {
            FetchHelper.fetch(url).then(_renderCornerNav).catch(function () {});
        } else {
            fetch(url).then(function (r) { return r.json(); }).then(_renderCornerNav).catch(function () {});
        }
    }

    function _renderCornerNav(data) {
        if (!data || !data.corners || data.corners.length === 0) return;
        _clearChildren(_cornerNav);
        _cornerNav.style.display = '';

        data.corners.forEach(function (c) {
            var chip = document.createElement('button');
            chip.className = 'focus-corner-chip';
            chip.setAttribute('type', 'button');
            chip.setAttribute('data-corner-id', c.corner_id);

            var name = document.createElement('span');
            name.className = 'focus-corner-chip-name';
            name.textContent = c.label || ('C' + c.corner_id);
            chip.appendChild(name);

            var delta = document.createElement('span');
            var timeLoss = c.avg_time_loss_ms || 0;
            var timeLossS = timeLoss / 1000;
            if (timeLossS > 0.01) {
                delta.className = 'focus-corner-chip-delta loss';
                delta.textContent = '+' + timeLossS.toFixed(2) + 's';
            } else if (timeLossS < -0.01) {
                delta.className = 'focus-corner-chip-delta gain';
                delta.textContent = timeLossS.toFixed(2) + 's';
            } else {
                delta.className = 'focus-corner-chip-delta neutral';
                delta.textContent = '0.00s';
            }
            chip.appendChild(delta);

            _lc.addListener(chip, 'click', function () {
                // Toggle active state visually
                var wasActive = chip.classList.contains('active');
                _cornerNav.querySelectorAll('.focus-corner-chip').forEach(function (el) {
                    el.classList.remove('active');
                });
                if (!wasActive) chip.classList.add('active');
            });

            _cornerNav.appendChild(chip);
        });
    }

    // -----------------------------------------------------------------
    // Public API: close
    // -----------------------------------------------------------------

    function close() {
        if (!_isOpen) return;

        // 1. Save active tools to localStorage
        if (_currentTab) {
            _saveLayout(_currentTab, _activeTools);
        }

        // 2. Destroy all rendered tools
        var renderedIds = Object.keys(_rendered);
        for (var i = 0; i < renderedIds.length; i++) {
            var id = renderedIds[i];
            if (_rendered[id] && typeof _rendered[id].destroy === 'function') {
                try { _rendered[id].destroy(); } catch (e) { /* ignore */ }
            }
        }
        _rendered = {};

        // 3. Destroy SplitPane instance
        if (_splitPane) {
            _splitPane.destroy();
            _splitPane = null;
        }

        // 4. Remove .active from overlay
        if (_overlay) {
            _overlay.classList.remove('active');
        }

        // 5. Restore body overflow
        document.body.style.overflow = '';
        _isOpen = false;
        _activeTools = [];
    }

    // -----------------------------------------------------------------
    // Public API: toggle
    // -----------------------------------------------------------------

    function toggle(tab) {
        if (_isOpen) {
            close();
        } else {
            open({ tab: tab || _guessCurrentTab() });
        }
    }

    // -----------------------------------------------------------------
    // Keyboard shortcuts
    // -----------------------------------------------------------------

    _lc.addListener(document, 'keydown', function (e) {
        var tag = e.target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (e.target.isContentEditable) return;

        if (_isOpen) {
            // Escape — close
            if (e.key === 'Escape') {
                e.preventDefault();
                close();
                return;
            }

            // R — reset layout (not with ctrl/meta)
            if ((e.key === 'r' || e.key === 'R') && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                if (_splitPane) {
                    _splitPane.resetLayout();
                }
                return;
            }

            // S — toggle dock display
            if ((e.key === 's' || e.key === 'S') && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                if (_dock) {
                    _dock.style.display = _dock.style.display === 'none' ? '' : 'none';
                }
                return;
            }

            // 1-9 — toggle tool by position
            var num = parseInt(e.key, 10);
            if (num >= 1 && num <= 9) {
                // Get visible dock buttons (tool buttons only, not reset/close)
                var toolBtns = _dock.querySelectorAll('.focus-dock-btn[data-tool-id]');
                var idx = num - 1;
                if (idx < toolBtns.length) {
                    var toolId = toolBtns[idx].getAttribute('data-tool-id');
                    var tool = _tools[toolId];
                    var isAvail = typeof tool.available === 'function' ? tool.available() : true;
                    if (isAvail) {
                        e.preventDefault();
                        _toggleTool(toolId);
                    }
                }
                return;
            }
        } else {
            // F — open focus mode for current tab (only if #session-tabs exists)
            if ((e.key === 'f' || e.key === 'F') && !e.ctrlKey && !e.metaKey && !e.altKey) {
                if (document.getElementById('session-tabs')) {
                    e.preventDefault();
                    open({ tab: _guessCurrentTab() });
                }
                return;
            }
        }
    });

    // -----------------------------------------------------------------
    // Window resize — redraw rendered tools
    // -----------------------------------------------------------------

    _lc.addListener(window, 'resize', function () {
        if (_isOpen) {
            Object.keys(_rendered).forEach(function (id) {
                if (_rendered[id] && typeof _rendered[id].redraw === 'function') {
                    _rendered[id].redraw();
                }
            });
        }
    });

    // -----------------------------------------------------------------
    // Expose public API
    // -----------------------------------------------------------------

    window.FocusMode = {
        registerTool: registerTool,
        open: open,
        close: close,
        toggle: toggle
    };

    function destroy() {
        if (_isOpen) close();
        _lc.destroyAll();
        if (_splitPane && typeof _splitPane.destroy === 'function') {
            _splitPane.destroy();
        }
        _splitPane = null;
    }

    window.ModuleManager.register('focus_mode', {
        init: function () { /* available globally, no init needed */ },
        destroy: destroy
    });

})();
