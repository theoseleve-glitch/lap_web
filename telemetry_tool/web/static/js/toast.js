/**
 * toast.js — Lightweight toast notification system.
 *
 * Usage:
 *   Toast.success('Session saved!');
 *   Toast.error('Upload failed', 'Please check your CSV format.');
 *   Toast.info('Tip', 'You can drag & drop files here.');
 *   Toast.warning('Slow connection', 'Analysis may take longer than usual.');
 *
 * Options:
 *   Toast.show({ type: 'success', title: '...', message: '...', duration: 5000 });
 */
(function () {
    'use strict';

    var ICONS = {
        success: '&#x2705;',
        error: '&#x274C;',
        info: '&#x2139;&#xFE0F;',
        warning: '&#x26A0;&#xFE0F;',
    };

    var DEFAULT_DURATION = 5000; // ms

    var container = null;

    function ensureContainer() {
        if (container) return;
        container = document.createElement('div');
        container.className = 'toast-container';
        container.setAttribute('aria-live', 'polite');
        container.setAttribute('aria-atomic', 'false');
        document.body.appendChild(container);
    }

    function show(opts) {
        if (typeof opts === 'string') {
            opts = { message: opts };
        }

        var type = opts.type || 'info';
        var title = opts.title || '';
        var message = opts.message || '';
        var duration = opts.duration !== undefined ? opts.duration : DEFAULT_DURATION;

        ensureContainer();

        var toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.setAttribute('role', (type === 'error' || type === 'warning') ? 'alert' : 'status');

        var html = '';

        // Icon
        html += '<span class="toast-icon" aria-hidden="true">' + (ICONS[type] || '') + '</span>';

        // Body
        html += '<div class="toast-body">';
        if (title) {
            html += '<div class="toast-title">' + escapeHtml(title) + '</div>';
        }
        if (message) {
            html += '<div class="toast-message">' + escapeHtml(message) + '</div>';
        }
        html += '</div>';

        // Close button
        html += '<button type="button" class="toast-close" aria-label="Dismiss">&times;</button>';

        // Progress bar (only if auto-dismiss)
        if (duration > 0) {
            html += '<div class="toast-progress" style="width: 100%;"></div>';
        }

        toast.innerHTML = html;
        container.appendChild(toast);

        // Close button handler
        var closeBtn = toast.querySelector('.toast-close');
        closeBtn.addEventListener('click', function () {
            dismissToast(toast);
        });
        closeBtn.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                dismissToast(toast);
            }
        });

        // Auto-dismiss with progress
        if (duration > 0) {
            var progress = toast.querySelector('.toast-progress');
            if (progress) {
                // Start progress countdown
                requestAnimationFrame(function () {
                    progress.style.transitionDuration = duration + 'ms';
                    progress.style.width = '0%';
                });
            }

            var timer = setTimeout(function () {
                dismissToast(toast);
            }, duration);

            // Pause on hover
            toast.addEventListener('mouseenter', function () {
                clearTimeout(timer);
                if (progress) {
                    var computed = getComputedStyle(progress).width;
                    progress.style.transitionDuration = '0ms';
                    progress.style.width = computed;
                }
            });

            toast.addEventListener('mouseleave', function () {
                if (progress) {
                    var remaining = (parseFloat(progress.style.width) / toast.offsetWidth) * duration;
                    if (remaining > 200) {
                        progress.style.transitionDuration = remaining + 'ms';
                        progress.style.width = '0%';
                        timer = setTimeout(function () {
                            dismissToast(toast);
                        }, remaining);
                    } else {
                        dismissToast(toast);
                    }
                }
            });
        }
    }

    function dismissToast(toast) {
        if (toast._dismissed) return;
        toast._dismissed = true;
        toast.classList.add('toast-exit');
        setTimeout(function () {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 300);
    }

    function escapeHtml(s) {
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    // Public API
    window.Toast = {
        show: show,
        success: function (titleOrMsg, message) {
            if (message) {
                show({ type: 'success', title: titleOrMsg, message: message });
            } else {
                show({ type: 'success', message: titleOrMsg });
            }
        },
        error: function (titleOrMsg, message) {
            if (message) {
                show({ type: 'error', title: titleOrMsg, message: message, duration: 8000 });
            } else {
                show({ type: 'error', message: titleOrMsg, duration: 8000 });
            }
        },
        info: function (titleOrMsg, message) {
            if (message) {
                show({ type: 'info', title: titleOrMsg, message: message });
            } else {
                show({ type: 'info', message: titleOrMsg });
            }
        },
        warning: function (titleOrMsg, message) {
            if (message) {
                show({ type: 'warning', title: titleOrMsg, message: message, duration: 7000 });
            } else {
                show({ type: 'warning', message: titleOrMsg, duration: 7000 });
            }
        },
    };

    window.ModuleManager.register('toast', { init: function(){}, destroy: function(){} });
})();
