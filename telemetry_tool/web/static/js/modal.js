/**
 * modal.js — Lightweight modal dialog with focus trap and keyboard handling.
 *
 * Usage:
 *   Modal.open({ title, body, footer, onClose, wide, narrow });
 *   Modal.close();
 *
 * Registered with ModuleManager for lifecycle cleanup.
 */
(function () {
    'use strict';

    var _backdrop = null;
    var _modal = null;
    var _previousFocus = null;
    var _onClose = null;
    var _lc = null;

    function _getFocusable() {
        if (!_modal) return [];
        return Array.from(_modal.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )).filter(function (el) {
            return !el.disabled && el.offsetParent !== null;
        });
    }

    function _trapFocus(e) {
        if (e.key !== 'Tab' || !_modal) return;
        var focusable = _getFocusable();
        if (focusable.length === 0) return;

        var first = focusable[0];
        var last = focusable[focusable.length - 1];

        if (e.shiftKey) {
            if (document.activeElement === first) {
                e.preventDefault();
                last.focus();
            }
        } else {
            if (document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    }

    function _onKeyDown(e) {
        if (e.key === 'Escape') {
            Modal.close();
        }
        _trapFocus(e);
    }

    function _onBackdropClick(e) {
        if (e.target === _backdrop) {
            Modal.close();
        }
    }

    function _ensureBackdrop() {
        if (_backdrop) return;
        _backdrop = document.createElement('div');
        _backdrop.className = 'modal-backdrop';
        _backdrop.setAttribute('role', 'dialog');
        _backdrop.setAttribute('aria-modal', 'true');
        document.body.appendChild(_backdrop);
    }

    var Modal = {
        /**
         * Open a modal dialog.
         * @param {Object} opts
         * @param {string} opts.title - Header title text
         * @param {string|HTMLElement} opts.body - Body content (HTML string or element)
         * @param {string|HTMLElement} [opts.footer] - Footer content (HTML string or element)
         * @param {Function} [opts.onClose] - Callback when modal closes
         * @param {boolean} [opts.wide] - Use wide variant (780px)
         * @param {boolean} [opts.narrow] - Use narrow variant (400px)
         */
        open: function (opts) {
            if (!opts) return;

            _previousFocus = document.activeElement;
            _onClose = opts.onClose || null;

            _ensureBackdrop();

            var cls = 'modal';
            if (opts.wide) cls += ' modal--wide';
            if (opts.narrow) cls += ' modal--narrow';

            var html = '<div class="' + cls + '">';
            html += '<div class="modal__header">';
            html += '<h3 class="modal__title">' + (opts.title || '') + '</h3>';
            html += '<button class="modal__close" aria-label="Close">&times;</button>';
            html += '</div>';
            html += '<div class="modal__body"></div>';
            if (opts.footer !== undefined) {
                html += '<div class="modal__footer"></div>';
            }
            html += '</div>';

            _backdrop.innerHTML = html;
            _modal = _backdrop.querySelector('.modal');

            // Set body content
            var bodyEl = _modal.querySelector('.modal__body');
            if (typeof opts.body === 'string') {
                bodyEl.innerHTML = opts.body;
            } else if (opts.body instanceof HTMLElement) {
                bodyEl.appendChild(opts.body);
            }

            // Set footer content
            if (opts.footer !== undefined) {
                var footerEl = _modal.querySelector('.modal__footer');
                if (typeof opts.footer === 'string') {
                    footerEl.innerHTML = opts.footer;
                } else if (opts.footer instanceof HTMLElement) {
                    footerEl.appendChild(opts.footer);
                }
            }

            // Close button handler
            var closeBtn = _modal.querySelector('.modal__close');
            if (closeBtn) {
                closeBtn.addEventListener('click', Modal.close);
            }

            // Keyboard + backdrop click
            document.addEventListener('keydown', _onKeyDown);
            _backdrop.addEventListener('click', _onBackdropClick);

            // Trigger open transition (next frame so CSS transition fires)
            requestAnimationFrame(function () {
                _backdrop.classList.add('open');

                // Focus first focusable or close button
                var focusable = _getFocusable();
                if (focusable.length > 0) {
                    focusable[0].focus();
                }
            });

            // Prevent body scroll
            document.body.style.overflow = 'hidden';
        },

        close: function () {
            if (!_backdrop) return;

            _backdrop.classList.remove('open');

            document.removeEventListener('keydown', _onKeyDown);
            _backdrop.removeEventListener('click', _onBackdropClick);

            // Restore body scroll
            document.body.style.overflow = '';

            // Wait for transition before cleanup
            var cb = _onClose;
            setTimeout(function () {
                if (_backdrop) {
                    _backdrop.innerHTML = '';
                }
                _modal = null;
                _onClose = null;

                // Restore focus
                if (_previousFocus && typeof _previousFocus.focus === 'function') {
                    _previousFocus.focus();
                }
                _previousFocus = null;

                if (typeof cb === 'function') cb();
            }, 200);
        },

        isOpen: function () {
            return _backdrop && _backdrop.classList.contains('open');
        }
    };

    window.Modal = Modal;

    // Register with ModuleManager for lifecycle cleanup
    if (window.ModuleManager) {
        window.ModuleManager.register('modal', {
            init: function () {},
            destroy: function () {
                Modal.close();
            }
        });
    }
})();
