/**
 * fetch_helper.js — Consistent fetch with loading, error, and retry UX.
 *
 * Usage:
 *   FetchHelper.load(container, '/api/endpoint', function(data) {
 *       container.innerHTML = renderContent(data);
 *   });
 *
 *   FetchHelper.load(container, '/api/endpoint', renderFn, {
 *       loadingText: 'Loading chart...',
 *       emptyCheck: function(data) { return data.length === 0; },
 *       emptyIcon: '&#x1F4CA;',
 *       emptyText: 'No data available for this chart.',
 *   });
 */
(function () {
    'use strict';

    var DEFAULT_OPTS = {
        loadingText: 'Loading...',
        errorIcon: '&#x26A0;&#xFE0F;',
        errorText: 'Failed to load data. Please try again.',
        emptyIcon: '&#x1F4ED;',
        emptyText: 'No data available.',
        emptyCheck: null,   // function(data) → bool
        retryLabel: 'Retry',
        timeout: 30000,
    };

    /**
     * Unwrap API envelope responses.
     * The SaaS backend wraps all responses in {ok, data, meta}.
     * Vanilla JS modules expect raw data, so we unwrap here.
     */
    function _unwrapEnvelope(data) {
        if (data && typeof data === 'object' && !Array.isArray(data)) {
            if (data.ok === true && 'data' in data) {
                return data.data;
            }
            if (data.ok === false) {
                throw new Error(data.error || data.message || 'API request failed');
            }
        }
        return data;
    }

    /**
     * Return default headers (e.g. Authorization) set by the host app.
     * The React wrapper sets FetchHelper.getAuthHeaders to provide the
     * current access token and workspace ID for every request.
     */
    function _getDefaultHeaders() {
        if (window.FetchHelper && typeof window.FetchHelper.getAuthHeaders === 'function') {
            return window.FetchHelper.getAuthHeaders();
        }
        return {};
    }

    // ── 401 Auto-Refresh ────────────────────────────────────────────
    // When a request gets a 401, we attempt a silent token refresh
    // and retry once.  A singleton promise prevents concurrent 401s
    // from firing multiple refresh calls (same pattern as api-client.ts).
    var _refreshPromise = null;

    /**
     * Attempt to refresh the auth token via the host app's callback.
     * All concurrent 401 callers share the same promise.
     * @returns {Promise<boolean>} true if refresh succeeded
     */
    function _tryRefresh() {
        if (_refreshPromise) return _refreshPromise;
        if (!window.FetchHelper || typeof window.FetchHelper.onRefreshToken !== 'function') {
            return Promise.resolve(false);
        }
        _refreshPromise = Promise.resolve()
            .then(function () { return window.FetchHelper.onRefreshToken(); })
            .then(function (result) { return !!result; })
            .catch(function () { return false; })
            .then(function (ok) { _refreshPromise = null; return ok; });
        return _refreshPromise;
    }

    /**
     * Retry a request with fresh auth headers after a successful token refresh.
     * Returns parsed (but NOT unwrapped) JSON so callers can continue their
     * existing .then(unwrap) chain.
     */
    function _retryWithNewToken(url, timeout) {
        var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
        var retryOpts = { headers: _getDefaultHeaders() };
        if (ctrl) retryOpts.signal = ctrl.signal;
        var t = ctrl ? setTimeout(function () { ctrl.abort(); }, timeout) : null;
        return fetch(url, retryOpts)
            .then(function (r) {
                if (t) clearTimeout(t);
                if (!r.ok) throw new Error('HTTP ' + r.status + ': ' + r.statusText);
                return r.json();
            })
            .catch(function (err) {
                if (t) clearTimeout(t);
                throw err;
            });
    }

    /**
     * Show a skeleton/loading state inside container,
     * fetch url, call onSuccess(data) or show error with retry.
     */
    function load(container, url, onSuccess, opts) {
        opts = _merge(DEFAULT_OPTS, opts || {});

        // Show loading state with ARIA busy indicator
        container.setAttribute('aria-busy', 'true');
        _showLoading(container, opts.loadingText);

        // Fetch with timeout
        var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        var fetchOpts = controller ? { signal: controller.signal } : {};
        fetchOpts.headers = _getDefaultHeaders();
        var timer = null;

        if (controller) {
            timer = setTimeout(function () {
                controller.abort();
            }, opts.timeout);
        }

        fetch(url, fetchOpts)
            .then(function (response) {
                if (timer) clearTimeout(timer);
                // 401 → attempt silent token refresh, retry once
                if (response.status === 401) {
                    return _tryRefresh().then(function (ok) {
                        if (!ok) {
                            if (window.FetchHelper && window.FetchHelper.onSessionExpired) {
                                window.FetchHelper.onSessionExpired();
                            }
                            throw new Error('HTTP 401: Session expired');
                        }
                        return _retryWithNewToken(url, opts.timeout);
                    });
                }
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status + ': ' + response.statusText);
                }
                return response.json();
            })
            .then(function (data) {
                data = _unwrapEnvelope(data);
                container.removeAttribute('aria-busy');
                // Check for empty data
                if (opts.emptyCheck && opts.emptyCheck(data)) {
                    _showEmpty(container, opts);
                    return;
                }
                // Clear loading & render
                try {
                    onSuccess(data);
                } catch (e) {
                    console.error('Render error:', e);
                    _showError(container, 'Error rendering data.', url, onSuccess, opts);
                }
            })
            .catch(function (err) {
                container.removeAttribute('aria-busy');
                if (timer) clearTimeout(timer);
                var msg = opts.errorText;
                if (err.name === 'AbortError') {
                    msg = 'Request timed out. Please try again.';
                } else if (err.message && err.message.indexOf('HTTP ') === 0) {
                    msg = err.message;
                }
                _showError(container, msg, url, onSuccess, opts);
            });
    }

    function _showLoading(container, text) {
        container.innerHTML =
            '<div class="no-data p-lg">' +
            '<div class="spinner-inline spinner-accent"></div>' +
            '<div class="text-secondary text-sm">' + _escape(text) + '</div>' +
            '</div>';
    }

    function _showError(container, message, url, onSuccess, opts) {
        container.innerHTML =
            '<div class="fetch-error">' +
            '<div class="fetch-error-icon">' + opts.errorIcon + '</div>' +
            '<div class="fetch-error-message">' + _escape(message) + '</div>' +
            '<button class="btn-retry" type="button">' + _escape(opts.retryLabel) + '</button>' +
            '</div>';

        var retryBtn = container.querySelector('.btn-retry');
        if (retryBtn) {
            retryBtn.addEventListener('click', function () {
                load(container, url, onSuccess, opts);
            });
        }

        // Also notify via Toast if available
        if (window.Toast) {
            Toast.error('Load failed', message);
        }
    }

    function _showEmpty(container, opts) {
        container.innerHTML =
            '<div class="no-data">' +
            '<div class="no-data-icon">' + opts.emptyIcon + '</div>' +
            '<div class="no-data-text">' + _escape(opts.emptyText) + '</div>' +
            '</div>';
    }

    function _escape(s) {
        if (!s) return '';
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function _merge(defaults, overrides) {
        var result = {};
        for (var k in defaults) {
            result[k] = overrides[k] !== undefined ? overrides[k] : defaults[k];
        }
        return result;
    }

    /**
     * Lightweight fetch wrapper with automatic timeout.
     * Use for simple one-off fetches that don't need container-based loading UX.
     *
     * Usage:
     *   FetchHelper.fetch('/api/data', { method: 'POST', body: '...' })
     *       .then(function(data) { ... })
     *       .catch(function(err) { ... });
     *
     * @param {string} url
     * @param {object} [opts]  Standard fetch options + optional `timeout` (ms, default 30000)
     * @returns {Promise}
     */
    function fetchWithTimeout(url, opts) {
        opts = opts || {};
        var timeout = opts.timeout || DEFAULT_OPTS.timeout;
        delete opts.timeout;

        // Merge default auth headers, letting caller override.
        var defaults = _getDefaultHeaders();
        var merged = {};
        var k;
        for (k in defaults) { merged[k] = defaults[k]; }
        var existing = opts.headers || {};
        for (k in existing) { merged[k] = existing[k]; }
        opts.headers = merged;

        var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        if (controller) {
            opts.signal = opts.signal || controller.signal;
        }
        var timer = controller ? setTimeout(function () { controller.abort(); }, timeout) : null;

        return fetch(url, opts)
            .then(function (response) {
                if (timer) clearTimeout(timer);
                // 401 → attempt silent token refresh, retry once
                if (response.status === 401) {
                    return _tryRefresh().then(function (ok) {
                        if (!ok) {
                            if (window.FetchHelper && window.FetchHelper.onSessionExpired) {
                                window.FetchHelper.onSessionExpired();
                            }
                            throw new Error('HTTP 401: Session expired');
                        }
                        return _retryWithNewToken(url, timeout);
                    });
                }
                if (!response.ok) throw new Error('HTTP ' + response.status + ': ' + response.statusText);
                return response.json();
            })
            .then(function (data) {
                return _unwrapEnvelope(data);
            })
            .catch(function (err) {
                if (timer) clearTimeout(timer);
                if (err.name === 'AbortError') throw new Error('Request timed out after ' + (timeout / 1000) + 's');
                throw err;
            });
    }

    /**
     * Lazy-init helper: call initFn only when the element's parent tab is visible.
     * If the tab is already active, calls immediately. Otherwise waits for 'tab:activate'.
     *
     * Usage (inside a module's DOMContentLoaded):
     *   FetchHelper.lazyInit('my-container-id', function() {
     *       // fetch data and render...
     *   });
     */
    function lazyInit(containerId, initFn) {
        var el = document.getElementById(containerId);
        if (!el) return;

        // Check if already visible (in an active tab panel or no tab system)
        var panel = el.closest('.tab-panel');
        if (!panel || panel.classList.contains('active')) {
            initFn();
            return;
        }

        // Wait for tab activation
        var done = false;
        panel.addEventListener('tab:activate', function () {
            if (done) return;
            done = true;
            initFn();
        });
    }

    // Public API
    window.FetchHelper = {
        load: load,
        fetch: fetchWithTimeout,
        lazyInit: lazyInit,
    };

    window.ModuleManager.register('fetch_helper', { init: function(){}, destroy: function(){} });
})();
