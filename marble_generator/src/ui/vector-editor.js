/**
 * SVG overlay for drawing velocity arrows on a canvas.
 *
 * Click to place an arrow, drag its head to set direction and magnitude,
 * double-click to remove. Exports an RBF-interpolated velocity field
 * as a Float32Array in RGBA format for GPU texture upload.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';
const ARROW_COLOR = '#c3a54b';
const BASE_COLOR  = '#c3a54b';
const SNAP_HEAD   = 10; // px distance to snap to an arrow head
const SNAP_BASE   = 10; // px distance to snap to an arrow base
const REMOVE_DIST = 15; // px distance for double-click removal

export class VectorEditor {
  /**
   * @param {HTMLElement} container - The parent element that holds the canvas.
   *                                  The SVG will be positioned absolutely on top.
   * @param {number} width  - Width of the overlay in pixels
   * @param {number} height - Height of the overlay in pixels
   */
  constructor(container, width, height) {
    this.container = container;
    this.width = width;
    this.height = height;

    /** @type {Array<{x: number, y: number, vx: number, vy: number}>} */
    this.arrows = [];

    this._selected = null; // { index, mode: 'head' | 'base' }
    this._dragging = false;

    // Create SVG element
    this.svg = document.createElementNS(SVG_NS, 'svg');
    this.svg.setAttribute('width', width);
    this.svg.setAttribute('height', height);
    this.svg.style.position = 'absolute';
    this.svg.style.top = '0';
    this.svg.style.left = '0';
    this.svg.style.pointerEvents = 'all';
    this.svg.style.cursor = 'crosshair';
    this.svg.style.zIndex = '10';

    // Build arrowhead marker definition
    const defs = document.createElementNS(SVG_NS, 'defs');
    const marker = document.createElementNS(SVG_NS, 'marker');
    marker.setAttribute('id', 'vel-arrowhead');
    marker.setAttribute('markerWidth', '10');
    marker.setAttribute('markerHeight', '7');
    marker.setAttribute('refX', '10');
    marker.setAttribute('refY', '3.5');
    marker.setAttribute('orient', 'auto');
    marker.setAttribute('markerUnits', 'strokeWidth');
    const arrowPath = document.createElementNS(SVG_NS, 'polygon');
    arrowPath.setAttribute('points', '0 0, 10 3.5, 0 7');
    arrowPath.setAttribute('fill', ARROW_COLOR);
    marker.appendChild(arrowPath);
    defs.appendChild(marker);
    this.svg.appendChild(defs);

    // Drawing group (cleared and rebuilt on each render)
    this._group = document.createElementNS(SVG_NS, 'g');
    this.svg.appendChild(this._group);

    // Bind event handlers
    this._onMouseDown = this._onMouseDown.bind(this);
    this._onMouseMove = this._onMouseMove.bind(this);
    this._onMouseUp   = this._onMouseUp.bind(this);
    this._onDblClick  = this._onDblClick.bind(this);

    this.svg.addEventListener('mousedown', this._onMouseDown);
    this.svg.addEventListener('mousemove', this._onMouseMove);
    this.svg.addEventListener('mouseup', this._onMouseUp);
    this.svg.addEventListener('dblclick', this._onDblClick);

    container.appendChild(this.svg);
    this._render();
  }

  // -------------------------------------------------------------------------
  // Event handlers
  // -------------------------------------------------------------------------

  _getLocalCoords(e) {
    const rect = this.svg.getBoundingClientRect();
    return {
      mx: e.clientX - rect.left,
      my: e.clientY - rect.top,
    };
  }

  _onMouseDown(e) {
    e.preventDefault();
    const { mx, my } = this._getLocalCoords(e);

    // Check if near an existing arrow head
    for (let i = 0; i < this.arrows.length; i++) {
      const a = this.arrows[i];
      const hx = a.x + a.vx;
      const hy = a.y + a.vy;
      const dHead = Math.sqrt((mx - hx) ** 2 + (my - hy) ** 2);
      if (dHead < SNAP_HEAD) {
        this._selected = { index: i, mode: 'head' };
        this._dragging = true;
        return;
      }
    }

    // Check if near an existing arrow base
    for (let i = 0; i < this.arrows.length; i++) {
      const a = this.arrows[i];
      const dBase = Math.sqrt((mx - a.x) ** 2 + (my - a.y) ** 2);
      if (dBase < SNAP_BASE) {
        this._selected = { index: i, mode: 'base' };
        this._dragging = true;
        return;
      }
    }

    // Place new arrow at click position with zero velocity, start dragging head
    const newArrow = { x: mx, y: my, vx: 0, vy: 0 };
    this.arrows.push(newArrow);
    this._selected = { index: this.arrows.length - 1, mode: 'head' };
    this._dragging = true;
    this._render();
  }

  _onMouseMove(e) {
    if (!this._dragging || !this._selected) return;
    e.preventDefault();
    const { mx, my } = this._getLocalCoords(e);
    const a = this.arrows[this._selected.index];

    if (this._selected.mode === 'head') {
      a.vx = mx - a.x;
      a.vy = my - a.y;
    } else {
      // Dragging the base — keep the head in the same world position
      const hx = a.x + a.vx;
      const hy = a.y + a.vy;
      a.x = mx;
      a.y = my;
      a.vx = hx - mx;
      a.vy = hy - my;
    }

    this._render();
  }

  _onMouseUp() {
    this._selected = null;
    this._dragging = false;
  }

  _onDblClick(e) {
    e.preventDefault();
    const { mx, my } = this._getLocalCoords(e);

    // Remove the closest arrow within REMOVE_DIST
    let bestIdx = -1;
    let bestDist = Infinity;
    for (let i = 0; i < this.arrows.length; i++) {
      const a = this.arrows[i];
      // Check distance to both base and head, take the closer one
      const dBase = Math.sqrt((mx - a.x) ** 2 + (my - a.y) ** 2);
      const hx = a.x + a.vx;
      const hy = a.y + a.vy;
      const dHead = Math.sqrt((mx - hx) ** 2 + (my - hy) ** 2);
      const d = Math.min(dBase, dHead);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
      }
    }

    if (bestIdx >= 0 && bestDist < REMOVE_DIST) {
      this.arrows.splice(bestIdx, 1);
      this._selected = null;
      this._dragging = false;
      this._render();
    }
  }

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  _render() {
    // Clear all children from the drawing group
    while (this._group.firstChild) {
      this._group.removeChild(this._group.firstChild);
    }

    for (const a of this.arrows) {
      const hx = a.x + a.vx;
      const hy = a.y + a.vy;

      // Arrow line
      const line = document.createElementNS(SVG_NS, 'line');
      line.setAttribute('x1', a.x);
      line.setAttribute('y1', a.y);
      line.setAttribute('x2', hx);
      line.setAttribute('y2', hy);
      line.setAttribute('stroke', ARROW_COLOR);
      line.setAttribute('stroke-width', '2');
      line.setAttribute('marker-end', 'url(#vel-arrowhead)');
      this._group.appendChild(line);

      // Base circle (grab handle)
      const circle = document.createElementNS(SVG_NS, 'circle');
      circle.setAttribute('cx', a.x);
      circle.setAttribute('cy', a.y);
      circle.setAttribute('r', '4');
      circle.setAttribute('fill', BASE_COLOR);
      circle.setAttribute('stroke', '#fff');
      circle.setAttribute('stroke-width', '1');
      this._group.appendChild(circle);
    }
  }

  // -------------------------------------------------------------------------
  // Velocity field export
  // -------------------------------------------------------------------------

  /**
   * Convert placed arrows into a full velocity field via RBF interpolation.
   *
   * For each grid cell, compute a Gaussian-weighted sum of all arrow
   * velocities. Sigma is set to 15% of the larger canvas dimension so
   * that arrows have broad, smooth influence.
   *
   * @param {number} gw - Grid width (cells)
   * @param {number} gh - Grid height (cells)
   * @returns {Float32Array} RGBA velocity field [u,v,0,0, ...]
   */
  toVelocityField(gw, gh) {
    const size = gw * gh * 4;
    const field = new Float32Array(size);

    if (this.arrows.length === 0) return field;

    const sigma = Math.max(this.width, this.height) * 0.15;
    const sigma2 = sigma * sigma;

    // Scale factors: pixel coords to grid coords
    const sx = gw / this.width;
    const sy = gh / this.height;

    // Pre-compute arrow positions in grid space and velocity magnitudes
    const arrowsGrid = this.arrows.map(a => ({
      gx: a.x * sx,
      gy: a.y * sy,
      // Scale velocity from pixel space to a normalized range.
      // Keep the sign; the magnitude scaling is determined by
      // the arrow length relative to canvas size.
      vu: a.vx * sx,
      vv: a.vy * sy,
    }));

    // Sigma in grid space
    const gSigma = sigma * Math.max(sx, sy);
    const gSigma2 = gSigma * gSigma;

    for (let j = 0; j < gh; j++) {
      for (let i = 0; i < gw; i++) {
        const idx = (j * gw + i) * 4;
        let wSum = 0;
        let uSum = 0;
        let vSum = 0;

        for (const ag of arrowsGrid) {
          const dx = i - ag.gx;
          const dy = j - ag.gy;
          const w = Math.exp(-(dx * dx + dy * dy) / gSigma2);
          wSum += w;
          uSum += w * ag.vu;
          vSum += w * ag.vv;
        }

        if (wSum > 1e-10) {
          field[idx]     = uSum / wSum;
          field[idx + 1] = vSum / wSum;
        }
        // idx+2, idx+3 remain 0
      }
    }

    return field;
  }

  // -------------------------------------------------------------------------
  // Public helpers
  // -------------------------------------------------------------------------

  /** Remove all arrows. */
  clear() {
    this.arrows = [];
    this._selected = null;
    this._dragging = false;
    this._render();
  }

  /** Show the SVG overlay. */
  show() {
    this.svg.style.display = '';
  }

  /** Hide the SVG overlay. */
  hide() {
    this.svg.style.display = 'none';
  }

  /** Remove the SVG from the DOM and clean up event listeners. */
  destroy() {
    this.svg.removeEventListener('mousedown', this._onMouseDown);
    this.svg.removeEventListener('mousemove', this._onMouseMove);
    this.svg.removeEventListener('mouseup', this._onMouseUp);
    this.svg.removeEventListener('dblclick', this._onDblClick);

    if (this.svg.parentNode) {
      this.svg.parentNode.removeChild(this.svg);
    }

    this.arrows = [];
    this._selected = null;
  }
}
