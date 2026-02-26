/**
 * race_strategy.js — Config page interactions (dynamic driver rows)
 * and detail page interactions (fuel toggles, pit type toggles).
 */

/* ── Config Page: Dynamic Driver Rows ──────────── */
(function() {
    'use strict';

    var DRIVER_COLORS = ['#58a6ff','#f78166','#7ee787','#d2a8ff','#ffa657','#79c0ff'];

    var container = document.getElementById('rs-drivers-container');
    var addBtn    = document.getElementById('rs-add-driver');
    if (!container || !addBtn) return;

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        if (attrs) {
            Object.keys(attrs).forEach(function(k) {
                if (k === 'textContent') { node.textContent = attrs[k]; }
                else if (k === 'className') { node.className = attrs[k]; }
                else if (k === 'style') { node.style.cssText = attrs[k]; }
                else { node.setAttribute(k, attrs[k]); }
            });
        }
        if (children) {
            children.forEach(function(c) { if (c) node.appendChild(c); });
        }
        return node;
    }

    function textNode(text) {
        return document.createTextNode(text);
    }

    function makeInput(type, name, placeholder, value) {
        var attrs = { type: type, name: name };
        if (placeholder) attrs.placeholder = placeholder;
        if (value) attrs.value = value;
        if (type === 'number') attrs.step = '0.1';
        return el('input', attrs);
    }

    function makeFormGroup(labelText, inputEl, style) {
        var label = el('label', {}, [textNode(labelText)]);
        var attrs = { className: 'form-group' };
        if (style) attrs.style = style;
        return el('div', attrs, [label, inputEl]);
    }

    function getNextIndex() {
        var rows = container.querySelectorAll('.rs-driver-row');
        var max = -1;
        rows.forEach(function(row) {
            var idx = parseInt(row.getAttribute('data-index'), 10);
            if (idx > max) max = idx;
        });
        return max + 1;
    }

    function createDriverRow(idx) {
        var removeBtn = el('button', {
            type: 'button',
            className: 'btn btn-danger-text rs-remove-driver',
            title: 'Remove',
            textContent: '\u00D7'
        });

        var header = el('div', { className: 'rs-driver-header' }, [
            el('strong', { textContent: 'Driver ' + (idx + 1) }),
            removeBtn
        ]);

        var nameInput = makeInput('text', 'driver_name_' + idx, 'Driver name');
        nameInput.setAttribute('required', '');
        nameInput.setAttribute('list', 'known-drivers-list');

        var defaultColor = DRIVER_COLORS[idx % DRIVER_COLORS.length];
        var colorInput = el('input', {
            type: 'color',
            name: 'driver_color_' + idx,
            value: defaultColor,
            style: 'width:40px;height:30px;padding:0;border:none;cursor:pointer;'
        });

        var mainRow = el('div', { className: 'form-row' }, [
            makeFormGroup('Name *', nameInput, 'flex:2'),
            el('input', { type: 'hidden', name: 'driver_order_' + idx, value: '' + (idx + 1) }),
            makeFormGroup('Weight (kg)', makeInput('number', 'driver_weight_' + idx, '70')),
            makeFormGroup('COM Channel', makeInput('text', 'driver_com_' + idx, 'CH 7')),
            makeFormGroup('Color', colorInput, 'width:60px')
        ]);

        var constraintRow1 = el('div', { className: 'form-row' }, [
            makeFormGroup('Min Stint (MM:SS)', makeInput('text', 'driver_min_stint_' + idx, '20:00')),
            makeFormGroup('Max Stint (MM:SS)', makeInput('text', 'driver_max_stint_' + idx, '60:00')),
            makeFormGroup('Min Rest (MM:SS)', makeInput('text', 'driver_min_rest_' + idx, '5:00'))
        ]);

        var constraintRow2 = el('div', { className: 'form-row' }, [
            makeFormGroup('Min Cumulative (MM:SS)', makeInput('text', 'driver_min_cumulative_' + idx, '30:00')),
            makeFormGroup('Max Cumulative (MM:SS)', makeInput('text', 'driver_max_cumulative_' + idx, '90:00'))
        ]);

        var summary = el('summary', { textContent: 'Stint Constraints' });
        var details = el('details', { className: 'rs-constraints-toggle' }, [
            summary, constraintRow1, constraintRow2
        ]);

        return el('div', { className: 'rs-driver-row', 'data-index': '' + idx }, [
            header, mainRow, details
        ]);
    }

    addBtn.addEventListener('click', function() {
        var idx = getNextIndex();
        container.appendChild(createDriverRow(idx));
    });

    container.addEventListener('click', function(e) {
        if (e.target.classList.contains('rs-remove-driver')) {
            var row = e.target.closest('.rs-driver-row');
            if (row) row.remove();
        }
    });
})();

/* ── Config Page: Pit Window Rows ─────────────── */
(function() {
    'use strict';

    var windowList = document.getElementById('rs-windows-list');
    var addWindowBtn = document.getElementById('rs-add-window');
    if (!addWindowBtn || !windowList) return;

    var windowIdx = windowList.querySelectorAll('.rs-window-row').length;

    function createWindowRow(idx) {
        var row = document.createElement('div');
        row.className = 'rs-window-row form-row';
        row.setAttribute('data-window-idx', idx);

        // Type select
        var typeGroup = document.createElement('div');
        typeGroup.className = 'form-group';
        var typeLabel = document.createElement('label');
        typeLabel.textContent = 'Type';
        var typeSelect = document.createElement('select');
        typeSelect.name = 'window_type_' + idx;
        var types = [
            { value: 'pitlane', text: 'Pit Lane' },
            { value: 'refuel', text: 'Refuel' },
            { value: 'tech_stop', text: 'Tech Stop' }
        ];
        types.forEach(function(t) {
            var opt = document.createElement('option');
            opt.value = t.value;
            opt.textContent = t.text;
            typeSelect.appendChild(opt);
        });
        typeGroup.appendChild(typeLabel);
        typeGroup.appendChild(typeSelect);

        // Label input
        var labelGroup = document.createElement('div');
        labelGroup.className = 'form-group';
        var labelLabel = document.createElement('label');
        labelLabel.textContent = 'Label';
        var labelInput = document.createElement('input');
        labelInput.type = 'text';
        labelInput.name = 'window_label_' + idx;
        labelInput.placeholder = 'Window ' + (idx + 1);
        labelGroup.appendChild(labelLabel);
        labelGroup.appendChild(labelInput);

        // Start input
        var startGroup = document.createElement('div');
        startGroup.className = 'form-group';
        var startLabel = document.createElement('label');
        startLabel.textContent = 'Start (H:MM)';
        var startInput = document.createElement('input');
        startInput.type = 'text';
        startInput.name = 'window_start_' + idx;
        startInput.placeholder = '0:30';
        startGroup.appendChild(startLabel);
        startGroup.appendChild(startInput);

        // End input
        var endGroup = document.createElement('div');
        endGroup.className = 'form-group';
        var endLabel = document.createElement('label');
        endLabel.textContent = 'End (H:MM)';
        var endInput = document.createElement('input');
        endInput.type = 'text';
        endInput.name = 'window_end_' + idx;
        endInput.placeholder = '3:00';
        endGroup.appendChild(endLabel);
        endGroup.appendChild(endInput);

        // Rules group (hidden by default, shown for tech_stop)
        var rulesGroup = document.createElement('div');
        rulesGroup.className = 'form-group rs-window-rules';
        rulesGroup.style.display = 'none';
        var refuelLabel = document.createElement('label');
        var refuelCheck = document.createElement('input');
        refuelCheck.type = 'checkbox';
        refuelCheck.name = 'window_refuel_' + idx;
        refuelLabel.appendChild(refuelCheck);
        refuelLabel.appendChild(document.createTextNode(' Refuel'));
        var driverChangeLabel = document.createElement('label');
        var driverChangeCheck = document.createElement('input');
        driverChangeCheck.type = 'checkbox';
        driverChangeCheck.name = 'window_driver_change_' + idx;
        driverChangeLabel.appendChild(driverChangeCheck);
        driverChangeLabel.appendChild(document.createTextNode(' Driver Change'));
        rulesGroup.appendChild(refuelLabel);
        rulesGroup.appendChild(driverChangeLabel);

        // Remove button
        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-ghost rs-remove-window';
        removeBtn.title = 'Remove';
        removeBtn.textContent = '\u00D7';

        row.appendChild(typeGroup);
        row.appendChild(labelGroup);
        row.appendChild(startGroup);
        row.appendChild(endGroup);
        row.appendChild(rulesGroup);
        row.appendChild(removeBtn);

        return row;
    }

    addWindowBtn.addEventListener('click', function() {
        var idx = windowIdx++;
        windowList.appendChild(createWindowRow(idx));
    });

    windowList.addEventListener('click', function(e) {
        if (e.target.classList.contains('rs-remove-window')) {
            e.target.closest('.rs-window-row').remove();
        }
    });

    // Show/hide tech_stop rule checkboxes based on type selection
    windowList.addEventListener('change', function(e) {
        if (e.target.tagName === 'SELECT') {
            var rules = e.target.closest('.rs-window-row').querySelector('.rs-window-rules');
            if (rules) {
                rules.style.display = e.target.value === 'tech_stop' ? '' : 'none';
            }
        }
    });
})();

/* ── Shared: Clickable Table Rows ─────────────── */
(function() {
    'use strict';
    document.querySelectorAll('.clickable-row').forEach(function(row) {
        row.style.cursor = 'pointer';
        row.addEventListener('click', function(e) {
            if (e.target.tagName === 'BUTTON' || e.target.tagName === 'A') return;
            window.location = row.getAttribute('data-href');
        });
    });
})();

/* ── Detail Page: Fuel Toggle & Pit Type APIs ──── */

/**
 * Toggle refuel on/off for the pit stop before a given stint.
 * Calls POST /<race_id>/api/toggle-fuel and reloads on success.
 *
 * @param {number} raceId  - The race_configs.race_id
 * @param {number} stintOrder - The stint_order that this pit stop feeds into
 */
function rsToggleFuel(raceId, stintOrder) {
    'use strict';
    fetch('/race-strategy/' + raceId + '/api/toggle-fuel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stint_order: stintOrder })
    })
    .then(function(resp) { return resp.json(); })
    .then(function(data) {
        if (data.ok) {
            // Reload the page to reflect cascade changes (fuel, ballast, violations)
            window.location.reload();
        } else {
            console.error('toggle-fuel error:', data.error);
        }
    })
    .catch(function(err) {
        console.error('toggle-fuel fetch failed:', err);
    });
}

/**
 * Cycle pit type between "full" and "quick" for a pit stop.
 * Calls POST /<race_id>/api/set-pit-type and reloads on success.
 *
 * @param {number} raceId  - The race_configs.race_id
 * @param {number} stintOrder - The stint_order that this pit stop feeds into
 * @param {HTMLElement} btn - The button element (for reading current state)
 */
function rsTogglePitType(raceId, stintOrder, btn) {
    'use strict';
    var currentType = btn.classList.contains('rs-pit-type-full') ? 'full' : 'quick';
    var newType = currentType === 'full' ? 'quick' : 'full';
    fetch('/race-strategy/' + raceId + '/api/set-pit-type', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stint_order: stintOrder, pit_type: newType })
    })
    .then(function(resp) { return resp.json(); })
    .then(function(data) {
        if (data.ok) {
            window.location.reload();
        } else {
            console.error('set-pit-type error:', data.error);
        }
    })
    .catch(function(err) {
        console.error('set-pit-type fetch failed:', err);
    });
}

window.ModuleManager.register('race_strategy', {
    init: function () {},
    destroy: function () {}
});
