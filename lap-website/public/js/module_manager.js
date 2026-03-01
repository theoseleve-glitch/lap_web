/**
 * module_manager.js — Central lifecycle coordinator for UI modules.
 *
 * Every module registers via ModuleManager.register(name, { init, destroy, redraw }).
 * Pages call ModuleManager.activate([names]) to init a set and auto-destroy the previous set.
 */
(function () {
    'use strict';

    var _modules = {};
    var _active = [];

    window.ModuleManager = {
        register: function (name, mod) {
            if (!mod || typeof mod.init !== 'function' || typeof mod.destroy !== 'function') {
                console.warn('[ModuleManager] module "' + name + '" missing init or destroy');
            }
            _modules[name] = mod;
        },

        activate: function (names) {
            this.deactivateAll();
            for (var i = 0; i < names.length; i++) {
                var n = names[i];
                if (_modules[n] && typeof _modules[n].init === 'function') {
                    try {
                        _modules[n].init();
                    } catch (e) {
                        console.error('[ModuleManager] init failed:', n, e);
                    }
                    _active.push(n);
                }
            }
        },

        deactivateAll: function () {
            for (var i = 0; i < _active.length; i++) {
                var n = _active[i];
                if (_modules[n] && typeof _modules[n].destroy === 'function') {
                    try {
                        _modules[n].destroy();
                    } catch (e) {
                        console.warn('[ModuleManager] destroy failed:', n, e);
                    }
                }
            }
            _active = [];
        },

        isActive: function (name) {
            return _active.indexOf(name) !== -1;
        },

        getActive: function () {
            return _active.slice();
        },

        getRegistered: function () {
            return Object.keys(_modules);
        }
    };
})();
