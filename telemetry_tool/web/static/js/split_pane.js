/**
 * split_pane.js — Drag-to-resize split pane engine for Focus Mode.
 *
 * Creates a flexible multi-panel layout with draggable resize handles.
 * Panels are arranged in rows with configurable layouts based on count.
 *
 * Public API:
 *   var sp = SplitPane.create(containerElement);
 *   var panel = sp.addPanel('chart-1');   // returns the panel DOM element
 *   sp.removePanel('chart-1');
 *   sp.resetLayout();
 *   sp.getPanelCount();                   // returns current panel count
 *   sp.destroy();                         // full cleanup
 *
 * Layout rules:
 *   1 panel  — fills entire container
 *   2 panels — side by side, one vertical handle
 *   3 panels — 2 on top row + 1 spanning bottom, vertical + horizontal handles
 *   4 panels — 2x2 grid, vertical handle per row + horizontal between rows
 *   5+ panels — 3 on top + rest on bottom
 *
 * Handles:
 *   - Vertical (column resize): 4px wide, class sp-handle sp-handle--horizontal
 *   - Horizontal (row resize): 4px tall, class sp-handle sp-handle--vertical
 *   - Double-click resets adjacent panels to equal flex
 *   - On drag release, triggers canvas.__redraw() on all canvases in panels
 */
(function () {
    'use strict';

    var _lc = window.LifecycleHelpers.create();

    var MIN_PANEL_PX = 150;
    var HANDLE_SIZE = 4; // px

    /**
     * Create a split pane instance bound to the given container element.
     * @param {HTMLElement} container - The DOM element to host the split layout.
     * @returns {{ addPanel, removePanel, resetLayout, destroy, getPanelCount }}
     */
    function create(container) {
        var panels = [];       // { id: string, el: HTMLElement }
        var cleanupFns = [];   // teardown functions for event listeners

        container.classList.add('sp-grid');

        // ----------------------------------------------------------------
        // DOM helpers
        // ----------------------------------------------------------------

        function clearChildren(el) {
            while (el.firstChild) {
                el.removeChild(el.firstChild);
            }
        }

        function createPanelEl(id) {
            var div = document.createElement('div');
            div.className = 'sp-panel';
            div.setAttribute('data-panel-id', id);
            return div;
        }

        function createHandle(direction) {
            var h = document.createElement('div');
            // direction: 'horizontal' → vertical bar (col resize),
            //            'vertical'   → horizontal bar (row resize)
            h.className = 'sp-handle sp-handle--' + direction;
            return h;
        }

        function createRow() {
            var row = document.createElement('div');
            row.className = 'sp-row';
            row.style.display = 'flex';
            row.style.flex = '1 1 0%';
            row.style.minHeight = MIN_PANEL_PX + 'px';
            row.style.overflow = 'hidden';
            return row;
        }

        // ----------------------------------------------------------------
        // Canvas redraw after resize
        // ----------------------------------------------------------------

        function redrawAllCanvases() {
            requestAnimationFrame(function () {
                var canvases = container.querySelectorAll('canvas');
                for (var i = 0; i < canvases.length; i++) {
                    if (typeof canvases[i].__redraw === 'function') {
                        try {
                            canvases[i].__redraw();
                        } catch (e) {
                            console.warn('[SplitPane] redraw failed for', canvases[i].id, e);
                        }
                    }
                }
            });
        }

        // ----------------------------------------------------------------
        // Drag handle logic (pointer events with capture)
        // ----------------------------------------------------------------

        /**
         * Attach drag behaviour to a horizontal handle (column-resize).
         * prevEl and nextEl are the flex siblings on either side.
         */
        function attachHorizontalDrag(handle, prevEl, nextEl) {
            function onPointerDown(e) {
                e.preventDefault();
                handle.setPointerCapture(e.pointerId);
                handle.classList.add('sp-handle--active');

                var startX = e.clientX;
                var prevRect = prevEl.getBoundingClientRect();
                var nextRect = nextEl.getBoundingClientRect();
                var totalWidth = prevRect.width + nextRect.width;

                function onPointerMove(ev) {
                    var dx = ev.clientX - startX;
                    var newPrev = prevRect.width + dx;
                    var newNext = nextRect.width - dx;

                    if (newPrev < MIN_PANEL_PX) {
                        newPrev = MIN_PANEL_PX;
                        newNext = totalWidth - MIN_PANEL_PX;
                    }
                    if (newNext < MIN_PANEL_PX) {
                        newNext = MIN_PANEL_PX;
                        newPrev = totalWidth - MIN_PANEL_PX;
                    }

                    prevEl.style.flex = '0 0 ' + newPrev + 'px';
                    nextEl.style.flex = '0 0 ' + newNext + 'px';
                }

                function onPointerUp() {
                    handle.classList.remove('sp-handle--active');
                    handle.removeEventListener('pointermove', onPointerMove);
                    handle.removeEventListener('pointerup', onPointerUp);
                    redrawAllCanvases();
                }

                handle.addEventListener('pointermove', onPointerMove);
                handle.addEventListener('pointerup', onPointerUp);
            }

            function onDblClick() {
                prevEl.style.flex = '1 1 0%';
                nextEl.style.flex = '1 1 0%';
                redrawAllCanvases();
            }

            handle.addEventListener('pointerdown', onPointerDown);
            handle.addEventListener('dblclick', onDblClick);

            cleanupFns.push(function () {
                handle.removeEventListener('pointerdown', onPointerDown);
                handle.removeEventListener('dblclick', onDblClick);
            });
        }

        /**
         * Attach drag behaviour to a vertical handle (row-resize).
         * prevRow and nextRow are the flex row siblings above and below.
         */
        function attachVerticalDrag(handle, prevRow, nextRow) {
            function onPointerDown(e) {
                e.preventDefault();
                handle.setPointerCapture(e.pointerId);
                handle.classList.add('sp-handle--active');

                var startY = e.clientY;
                var prevRect = prevRow.getBoundingClientRect();
                var nextRect = nextRow.getBoundingClientRect();
                var totalHeight = prevRect.height + nextRect.height;

                function onPointerMove(ev) {
                    var dy = ev.clientY - startY;
                    var newPrev = prevRect.height + dy;
                    var newNext = nextRect.height - dy;

                    if (newPrev < MIN_PANEL_PX) {
                        newPrev = MIN_PANEL_PX;
                        newNext = totalHeight - MIN_PANEL_PX;
                    }
                    if (newNext < MIN_PANEL_PX) {
                        newNext = MIN_PANEL_PX;
                        newPrev = totalHeight - MIN_PANEL_PX;
                    }

                    prevRow.style.flex = '0 0 ' + newPrev + 'px';
                    nextRow.style.flex = '0 0 ' + newNext + 'px';
                }

                function onPointerUp() {
                    handle.classList.remove('sp-handle--active');
                    handle.removeEventListener('pointermove', onPointerMove);
                    handle.removeEventListener('pointerup', onPointerUp);
                    redrawAllCanvases();
                }

                handle.addEventListener('pointermove', onPointerMove);
                handle.addEventListener('pointerup', onPointerUp);
            }

            function onDblClick() {
                prevRow.style.flex = '1 1 0%';
                nextRow.style.flex = '1 1 0%';
                redrawAllCanvases();
            }

            handle.addEventListener('pointerdown', onPointerDown);
            handle.addEventListener('dblclick', onDblClick);

            cleanupFns.push(function () {
                handle.removeEventListener('pointerdown', onPointerDown);
                handle.removeEventListener('dblclick', onDblClick);
            });
        }

        // ----------------------------------------------------------------
        // Populate a row element with panel elements and horizontal handles
        // ----------------------------------------------------------------

        function populateRow(rowEl, panelSubset) {
            for (var i = 0; i < panelSubset.length; i++) {
                var p = panelSubset[i];
                p.el.style.flex = '1 1 0%';
                p.el.style.minWidth = MIN_PANEL_PX + 'px';
                p.el.style.overflow = 'hidden';
                rowEl.appendChild(p.el);

                // Add horizontal handle between adjacent panels in the same row
                if (i < panelSubset.length - 1) {
                    var handle = createHandle('horizontal');
                    rowEl.appendChild(handle);
                    // Attach drag: prevEl = current panel, nextEl = next panel
                    attachHorizontalDrag(handle, p.el, panelSubset[i + 1].el);
                }
            }
        }

        // ----------------------------------------------------------------
        // Rebuild the entire layout from scratch based on current panels[]
        // ----------------------------------------------------------------

        function rebuildLayout() {
            // Tear down previous event listeners
            for (var c = 0; c < cleanupFns.length; c++) {
                cleanupFns[c]();
            }
            cleanupFns = [];

            // Remove existing children but keep panel inner content
            // First detach panel elements so they are not destroyed
            for (var d = 0; d < panels.length; d++) {
                if (panels[d].el.parentNode) {
                    panels[d].el.parentNode.removeChild(panels[d].el);
                }
            }
            clearChildren(container);

            // Set container to column flex (rows stack vertically)
            container.style.display = 'flex';
            container.style.flexDirection = 'column';

            var n = panels.length;
            if (n === 0) {
                return;
            }

            if (n === 1) {
                // Single panel fills entire container
                var solo = panels[0];
                solo.el.style.flex = '1 1 0%';
                solo.el.style.minWidth = '';
                solo.el.style.overflow = 'hidden';
                container.appendChild(solo.el);
                return;
            }

            // Determine row distribution
            var topCount, bottomCount;
            if (n === 2) {
                topCount = 2;
                bottomCount = 0;
            } else if (n === 3) {
                topCount = 2;
                bottomCount = 1;
            } else if (n === 4) {
                topCount = 2;
                bottomCount = 2;
            } else {
                // 5+: 3 on top, rest on bottom
                topCount = 3;
                bottomCount = n - 3;
            }

            var topPanels = panels.slice(0, topCount);
            var bottomPanels = panels.slice(topCount);

            // Build top row
            var topRow = createRow();
            populateRow(topRow, topPanels);
            container.appendChild(topRow);

            if (bottomCount > 0) {
                // Add vertical handle between rows
                var vHandle = createHandle('vertical');
                container.appendChild(vHandle);

                // Build bottom row
                var bottomRow = createRow();
                populateRow(bottomRow, bottomPanels);
                container.appendChild(bottomRow);

                attachVerticalDrag(vHandle, topRow, bottomRow);
            }
        }

        // ----------------------------------------------------------------
        // Public methods
        // ----------------------------------------------------------------

        function addPanel(id) {
            var el = createPanelEl(id);
            panels.push({ id: id, el: el });
            rebuildLayout();
            return el;
        }

        function removePanel(id) {
            var idx = -1;
            for (var i = 0; i < panels.length; i++) {
                if (panels[i].id === id) {
                    idx = i;
                    break;
                }
            }
            if (idx === -1) return;

            var removed = panels.splice(idx, 1)[0];
            if (removed.el.parentNode) {
                removed.el.parentNode.removeChild(removed.el);
            }
            rebuildLayout();
        }

        function resetLayout() {
            // Reset all panels to equal flex — just rebuild
            rebuildLayout();
        }

        function destroy() {
            // Tear down event listeners
            for (var c = 0; c < cleanupFns.length; c++) {
                cleanupFns[c]();
            }
            cleanupFns = [];
            panels = [];

            clearChildren(container);
            container.classList.remove('sp-grid');
            container.style.display = '';
            container.style.flexDirection = '';
        }

        function getPanelCount() {
            return panels.length;
        }

        return {
            addPanel: addPanel,
            removePanel: removePanel,
            resetLayout: resetLayout,
            destroy: destroy,
            getPanelCount: getPanelCount
        };
    }

    // Expose public API
    window.SplitPane = {
        create: create
    };

    function destroy() {
        _lc.destroyAll();
    }

    window.ModuleManager.register('split_pane', {
        init: function () {},
        destroy: destroy
    });
})();
