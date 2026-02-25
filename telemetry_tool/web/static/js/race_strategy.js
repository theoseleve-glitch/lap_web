/**
 * race_strategy.js — Config page interactions (dynamic driver rows).
 */
(function() {
    'use strict';

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

        var mainRow = el('div', { className: 'form-row' }, [
            makeFormGroup('Name *', nameInput, 'flex:2'),
            el('input', { type: 'hidden', name: 'driver_order_' + idx, value: '' + (idx + 1) }),
            makeFormGroup('Weight (kg)', makeInput('number', 'driver_weight_' + idx, '70')),
            makeFormGroup('COM Channel', makeInput('text', 'driver_com_' + idx, 'CH 7'))
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

    // Clickable table rows (for index page)
    document.querySelectorAll('.clickable-row').forEach(function(row) {
        row.style.cursor = 'pointer';
        row.addEventListener('click', function(e) {
            if (e.target.tagName === 'BUTTON' || e.target.tagName === 'A') return;
            window.location = row.getAttribute('data-href');
        });
    });
})();
