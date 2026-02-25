/**
 * context_menu.js — Reusable right-click context menu for data tables.
 *
 * Usage:
 *   ContextMenu.init('.data-table tbody', 'tr[data-session-id]', function(row) {
 *       return [
 *           { label: 'Open', icon: '&#x1F4C4;', action: function() { ... } },
 *           { separator: true },
 *           { label: 'Delete', icon: '&#x1F5D1;', action: function() { ... }, danger: true },
 *       ];
 *   });
 */
(function () {
    'use strict';

    var menuEl = null;
    var _triggerEl = null;

    function create() {
        if (menuEl) return;
        menuEl = document.createElement('div');
        menuEl.className = 'ctx-menu';
        menuEl.setAttribute('role', 'menu');
        menuEl.style.display = 'none';
        document.body.appendChild(menuEl);

        // Close on click-away, Escape, scroll.
        document.addEventListener('click', function (e) {
            if (!menuEl.contains(e.target)) hide();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') hide();
            if (menuEl.style.display === 'none') return;
            // Arrow key navigation within open menu
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                var items = menuEl.querySelectorAll('.ctx-menu-item');
                if (items.length === 0) return;
                var cur = Array.prototype.indexOf.call(items, document.activeElement);
                var next = e.key === 'ArrowDown'
                    ? Math.min(cur + 1, items.length - 1)
                    : Math.max(cur - 1, 0);
                items[next].focus();
            }
        });
        window.addEventListener('scroll', hide, { capture: true, passive: true });
    }

    function show(x, y, items, targetEl) {
        create();
        _triggerEl = targetEl || null;
        menuEl.innerHTML = '';

        items.forEach(function (item) {
            if (item.separator) {
                var sep = document.createElement('div');
                sep.className = 'ctx-menu-separator';
                menuEl.appendChild(sep);
                return;
            }
            var el = document.createElement('div');
            el.className = 'ctx-menu-item' + (item.danger ? ' danger' : '');
            el.setAttribute('role', 'menuitem');
            el.setAttribute('tabindex', '0');
            if (item.icon) {
                var iconSpan = document.createElement('span');
                iconSpan.className = 'ctx-menu-icon';
                iconSpan.innerHTML = item.icon; // Trusted HTML entity (e.g. &#x1F4C4;)
                el.appendChild(iconSpan);
            }
            var labelSpan = document.createElement('span');
            labelSpan.textContent = item.label; // Safe: textContent escapes HTML
            el.appendChild(labelSpan);
            function activate(e) {
                e.stopPropagation();
                hide();
                if (typeof item.action === 'function') item.action();
            }
            el.addEventListener('click', activate);
            el.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    activate(e);
                }
            });
            menuEl.appendChild(el);
        });

        // Position — clamp to viewport.
        menuEl.style.display = 'block';
        var mw = menuEl.offsetWidth;
        var mh = menuEl.offsetHeight;
        var vw = window.innerWidth;
        var vh = window.innerHeight;
        if (x + mw > vw) x = vw - mw - 8;
        if (y + mh > vh) y = vh - mh - 8;
        if (x < 0) x = 4;
        if (y < 0) y = 4;
        menuEl.style.left = x + 'px';
        menuEl.style.top = y + 'px';

        // Focus the first menu item for keyboard navigation.
        var firstItem = menuEl.querySelector('.ctx-menu-item');
        if (firstItem) firstItem.focus();
    }

    function hide() {
        if (_triggerEl) {
            _triggerEl.focus();
            _triggerEl = null;
        }
        if (menuEl) menuEl.style.display = 'none';
    }

    /**
     * Attach a context-menu handler to rows matching `rowSelector`
     * within `containerSelector`.
     *
     * @param {string} containerSelector  CSS selector for the parent container
     * @param {string} rowSelector        CSS selector for individual rows
     * @param {function} getMenuItems     fn(rowElement) → array of menu items
     */
    function init(containerSelector, rowSelector, getMenuItems) {
        var containers = document.querySelectorAll(containerSelector);
        containers.forEach(function (container) {
            container.addEventListener('contextmenu', function (e) {
                var row = e.target.closest(rowSelector);
                if (!row) return;
                e.preventDefault();
                var items = getMenuItems(row);
                if (items && items.length > 0) {
                    show(e.clientX, e.clientY, items, row);
                }
            });
        });
    }

    window.ContextMenu = {
        init: init,
        show: show,
        hide: hide,
    };
})();
