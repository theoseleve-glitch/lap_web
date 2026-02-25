/**
 * session_editor.js — Inline editing for session metadata fields.
 *
 * Saves changes via AJAX POST to /sessions/<id>/edit
 * with debounced auto-save on blur/change.
 */
(function () {
    'use strict';

    var C = window.Theme ? window.Theme.colors : {};

    var _saveTimer = null;
    var _sessionId = null;
    var _saving = false;

    function init(sessionId) {
        _sessionId = sessionId;

        var fields = document.querySelectorAll('.session-editable');
        fields.forEach(function (el) {
            el.addEventListener('change', function () {
                _save(el);
            });
            el.addEventListener('blur', function () {
                _save(el);
            });
        });
    }

    function _save(el) {
        var field = el.dataset.field;
        var value = el.value;
        var statusEl = document.getElementById('session-save-status');

        if (!field || !_sessionId) return;

        if (_saveTimer) clearTimeout(_saveTimer);
        _saveTimer = setTimeout(function () {
            if (_saving) return;
            _saving = true;
            if (statusEl) statusEl.textContent = 'Saving...';

            FetchHelper.fetch('/sessions/' + _sessionId + '/edit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ field: field, value: value }),
            })
                .then(function () {
                    _saving = false;
                    if (statusEl) {
                        statusEl.textContent = 'Saved';
                        statusEl.style.color = C.green || '#3fb950';
                        setTimeout(function () {
                            statusEl.textContent = '';
                            statusEl.style.color = '';
                        }, 2000);
                    }
                    if (window.Toast) {
                        Toast.success('Session updated');
                    }
                })
                .catch(function (err) {
                    _saving = false;
                    if (statusEl) {
                        statusEl.textContent = 'Save failed';
                        statusEl.style.color = C.red || '#f85149';
                    }
                    if (window.Toast) {
                        Toast.error('Save failed', 'Could not update session.');
                    }
                });
        }, 500);
    }

    window.SessionEditor = { init: init };
})();
