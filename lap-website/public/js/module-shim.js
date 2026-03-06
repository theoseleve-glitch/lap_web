/**
 * module-shim.js — Compatibility shim for vanilla JS modules in React SPA.
 *
 * Problems solved:
 *   1. DOMContentLoaded has already fired by the time React loads scripts,
 *      so vanilla modules' auto-init listeners never execute.
 *   2. Re-navigation in the SPA doesn't reload scripts, but modules need
 *      re-initialization when their DOM containers reappear.
 *   3. FetchHelper uses old-style API paths (/api/session/...) while the
 *      SaaS backend uses /api/v1/sessions/... — this shim rewrites them.
 *
 * How it works:
 *   - Provides window.ModuleShim.reinit(moduleName) to manually re-trigger
 *     a module's init path when React re-mounts a component.
 *   - Patches FetchHelper to rewrite legacy API paths to the new v1 routes.
 *   - Must be loaded AFTER module_manager.js and fetch_helper.js.
 */
(function () {
    'use strict';

    /**
     * Rewrite old-tool API paths to v1 SaaS paths.
     *
     * Old format:  /api/session/{id}/gps/{lap}
     * New format:  /api/v1/sessions/{id}/gps/{lap}
     *
     * Old format:  /api/session/{id}/theoretical
     * New format:  /api/v1/sessions/{id}/theoretical
     *
     * Also: /api/session/{id}/lap_times  -> /api/v1/sessions/{id}/lap_times
     *       /api/session/{id}/reference_line  -> /api/v1/sessions/{id}/reference_line
     *       /api/session/{id}/best_lap_gps  -> /api/v1/sessions/{id}/best_lap_gps
     *       /api/session/{id}/corner-positions  -> /api/v1/sessions/{id}/corner-positions  (dedicated endpoint)
     *       /api/session/{id}/corner-metrics  -> /api/v1/sessions/{id}/corner-metrics  (dedicated endpoint)
     *       /api/session/{id}/gg  -> /api/v1/sessions/{id}/gg
     *       /api/session/{id}/gg/{lap}  -> /api/v1/sessions/{id}/gg/{lap}
     */
    function rewriteApiPath(url) {
        // Stage 1: /api/session/ → /api/v1/sessions/
        if (url.indexOf('/api/session/') === 0) {
            url = url.replace('/api/session/', '/api/v1/sessions/');
        } else {
            var idx = url.indexOf('/api/session/');
            if (idx > 0) {
                url = url.substring(0, idx) + url.substring(idx).replace('/api/session/', '/api/v1/sessions/');
            }
        }

        // Stage 2: Rewrite sub-paths to match v1 backend endpoints.
        // /sessions/{id}/gps/{lap} → /sessions/{id}/gps-trace?lap={lap}
        url = url.replace(/(\/sessions\/[^/]+)\/gps\/(\d+)/, '$1/gps-trace?lap=$2');
        // /sessions/{id}/gg/{lap} → /sessions/{id}/gg-data?lap={lap}
        url = url.replace(/(\/sessions\/[^/]+)\/gg\/(\d+)/, '$1/gg-data?lap=$2');
        // /sessions/{id}/gg (no lap) → /sessions/{id}/gg-data
        url = url.replace(/(\/sessions\/[^/]+)\/gg(\?|$)/, '$1/gg-data$2');
        // /sessions/{id}/gg_data → /sessions/{id}/gg-data
        url = url.replace(/(\/sessions\/[^/]+)\/gg_data/, '$1/gg-data');
        // /sessions/{id}/lap_times → /sessions/{id}/laps
        url = url.replace(/(\/sessions\/[^/]+)\/lap_times/, '$1/laps');
        // /sessions/{id}/sector-analysis → /sessions/{id}/sector_times
        url = url.replace(/(\/sessions\/[^/]+)\/sector-analysis/, '$1/sector_times');
        // /sessions/{id}/corner-coaching → /sessions/{id}/corners
        url = url.replace(/(\/sessions\/[^/]+)\/corner-coaching/, '$1/corners');
        // corner-positions and corner-metrics now have dedicated endpoints
        // (previously incorrectly mapped to /corners)
        // /sessions/{id}/speed_overlay → already correct (dedicated endpoint)
        // /sessions/{id}/cross_session → already correct (dedicated endpoint)

        return url;
    }

    /**
     * Patch FetchHelper.fetch and FetchHelper.load to rewrite legacy paths.
     * This runs AFTER the base URL patch from useVanillaChart, so paths
     * will be like: https://api.example.com/api/session/... → rewrite to
     * https://api.example.com/api/v1/sessions/...
     */
    function patchFetchHelperPaths() {
        if (!window.FetchHelper) return;

        var origFetch = window.FetchHelper.fetch;
        if (origFetch && !origFetch._pathPatched) {
            var pathPatchedFetch = function (url, opts) {
                return origFetch.call(window.FetchHelper, rewriteApiPath(url), opts);
            };
            pathPatchedFetch._patched = origFetch._patched;
            pathPatchedFetch._pathPatched = true;
            window.FetchHelper.fetch = pathPatchedFetch;
        }

        var origLoad = window.FetchHelper.load;
        if (origLoad && !origLoad._pathPatched) {
            var pathPatchedLoad = function (container, url, onSuccess, loadOpts) {
                return origLoad.call(window.FetchHelper, container, rewriteApiPath(url), onSuccess, loadOpts);
            };
            pathPatchedLoad._patched = origLoad._patched;
            pathPatchedLoad._pathPatched = true;
            window.FetchHelper.load = pathPatchedLoad;
        }
    }

    // Apply path patches immediately when loaded.
    patchFetchHelperPaths();

    // Re-apply after any future useVanillaChart patches (which run later).
    // The React hook patches FetchHelper in its loadAll() async flow;
    // we re-patch on next tick to layer on top.
    if (typeof MutationObserver !== 'undefined') {
        // Use a lightweight poll: check once when FetchHelper changes.
        var _lastFetch = window.FetchHelper && window.FetchHelper.fetch;
        var _checkInterval = setInterval(function () {
            if (window.FetchHelper && window.FetchHelper.fetch !== _lastFetch) {
                _lastFetch = window.FetchHelper.fetch;
                patchFetchHelperPaths();
            }
        }, 200);

        // Stop polling after 10 seconds (patches should be stable by then).
        setTimeout(function () {
            clearInterval(_checkInterval);
        }, 10000);
    }

    /**
     * Re-initialize a module by name.
     * Useful when React re-mounts a component and needs the module
     * to re-bind to fresh DOM elements.
     */
    function reinit(moduleName) {
        if (!window.ModuleManager) {
            console.warn('[ModuleShim] ModuleManager not available');
            return;
        }

        // First destroy the module if it was active
        window.ModuleManager.deactivateAll();

        // Re-activate just this module (or set of modules)
        var names = Array.isArray(moduleName) ? moduleName : [moduleName];
        window.ModuleManager.activate(names);
    }

    /**
     * Fire DOMContentLoaded-style initialization for a set of modules.
     * Some modules auto-init on DOMContentLoaded. When React loads them
     * after that event has already fired, we manually dispatch the event
     * on the document so their listeners execute.
     *
     * This should only be called once per module load, not on re-renders.
     */
    function fireDOMContentLoaded() {
        try {
            var evt = new Event('DOMContentLoaded', { bubbles: true, cancelable: false });
            document.dispatchEvent(evt);
        } catch (e) {
            // IE11 fallback (shouldn't be needed but just in case).
            console.warn('[ModuleShim] Failed to dispatch DOMContentLoaded:', e);
        }
    }

    // ── Public API ────────────────────────────────
    window.ModuleShim = {
        reinit: reinit,
        fireDOMContentLoaded: fireDOMContentLoaded,
        rewriteApiPath: rewriteApiPath,
        patchFetchHelperPaths: patchFetchHelperPaths,
    };
})();
