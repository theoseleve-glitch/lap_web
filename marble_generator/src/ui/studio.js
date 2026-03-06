/**
 * Studio — interactive GPU-accelerated fluid editing overlay.
 *
 * Opens a fullscreen overlay with a WebGL canvas. The fluid simulation
 * runs continuously via requestAnimationFrame. Users can drag to inject
 * forces. Play/pause controls and FPS display are provided.
 */

export class Studio {
  /**
   * @param {HTMLElement} studioEl - The .studio overlay element
   * @param {HTMLCanvasElement} canvasEl - The studio canvas element
   */
  constructor(studioEl, canvasEl) {
    this.studioEl = studioEl;
    this.canvasEl = canvasEl;

    /** @type {boolean} */
    this.active = false;

    /** @type {boolean} */
    this.playing = true;

    /** @type {boolean} */
    this.dragging = false;

    /** @type {number} */
    this.lastX = 0;

    /** @type {number} */
    this.lastY = 0;

    /** @type {number} */
    this.animFrame = 0;

    /** @type {import('../gl/renderer.js').Renderer|null} */
    this.renderer = null;

    /** @type {import('../engine/fluid-sim.js').FluidSimGPU|null} */
    this.fluidSim = null;

    /** @type {import('../engine/multi-phase.js').MultiPhase|null} */
    this.multiPhase = null;

    /** @type {object|null} */
    this.config = null;

    // FPS tracking
    this._frameCount = 0;
    this._lastFpsTime = 0;
    this._fpsDisplay = 0;

    this._setupEvents();
  }

  /**
   * Open the studio with a GPU-accelerated fluid simulation.
   * Starts the continuous animation loop immediately.
   *
   * @param {import('../gl/renderer.js').Renderer} renderer
   * @param {import('../engine/fluid-sim.js').FluidSimGPU} fluidSim
   * @param {import('../engine/multi-phase.js').MultiPhase} multiPhase
   * @param {object} config - Generation config
   */
  open(renderer, fluidSim, multiPhase, config) {
    this.renderer = renderer;
    this.fluidSim = fluidSim;
    this.multiPhase = multiPhase;
    this.config = config;
    this.active = true;
    this.playing = true;

    this.studioEl.classList.add('open');

    // Reset FPS counters
    this._frameCount = 0;
    this._lastFpsTime = performance.now();
    this._fpsDisplay = 0;

    // Update play/pause button state
    this._updatePlayPauseBtn();

    // Start continuous animation loop
    this._startLoop();
  }

  /**
   * Close the studio and stop animation.
   */
  close() {
    this.active = false;
    this.playing = false;
    this.dragging = false;
    this.studioEl.classList.remove('open');

    if (this.animFrame) {
      cancelAnimationFrame(this.animFrame);
      this.animFrame = 0;
    }

    this.renderer = null;
    this.fluidSim = null;
    this.multiPhase = null;
    this.config = null;
  }

  /**
   * Toggle play/pause state.
   */
  togglePlay() {
    this.playing = !this.playing;
    this._updatePlayPauseBtn();
    if (this.playing && this.active) {
      this._lastFpsTime = performance.now();
      this._frameCount = 0;
      this._startLoop();
    }
  }

  /**
   * Start the continuous RAF loop.
   * @private
   */
  _startLoop() {
    if (this.animFrame) return;

    const loop = () => {
      if (!this.active) return;

      if (this.playing && this.fluidSim && this.multiPhase) {
        const dt = this.fluidSim.dt;
        this.fluidSim.step();
        this.multiPhase.advect(this.fluidSim.velRead, dt);

        const w = this.canvasEl.width;
        const h = this.canvasEl.height;
        this.multiPhase.renderColor(null, w, h);

        // FPS calculation
        this._frameCount++;
        const now = performance.now();
        const elapsed = now - this._lastFpsTime;
        if (elapsed >= 500) {
          this._fpsDisplay = Math.round((this._frameCount / elapsed) * 1000);
          this._frameCount = 0;
          this._lastFpsTime = now;
          this._updateFps();
        }
      }

      this.animFrame = requestAnimationFrame(loop);
    };

    this.animFrame = requestAnimationFrame(loop);
  }

  /**
   * Update the FPS display element.
   * @private
   */
  _updateFps() {
    const el = document.getElementById('fpsDisplay');
    if (el) el.textContent = this._fpsDisplay + ' fps';
  }

  /**
   * Update the play/pause button text.
   * @private
   */
  _updatePlayPauseBtn() {
    const btn = document.getElementById('playPauseBtn');
    if (btn) btn.textContent = this.playing ? 'Pause' : 'Play';
  }

  /**
   * Set up mouse and touch event listeners on the canvas.
   * @private
   */
  _setupEvents() {
    // --- Mouse ---
    this.canvasEl.addEventListener('mousedown', (e) => {
      if (!this.active || !this.fluidSim) return;
      e.preventDefault();
      this.dragging = true;
      const uv = this._getUV(e);
      this.lastX = uv.x;
      this.lastY = uv.y;
    });

    document.addEventListener('mousemove', (e) => {
      if (!this.dragging || !this.active || !this.fluidSim) return;
      this._applyForce(e);
    });

    document.addEventListener('mouseup', () => {
      this.dragging = false;
    });

    // --- Touch ---
    this.canvasEl.addEventListener('touchstart', (e) => {
      if (!this.active || !this.fluidSim) return;
      e.preventDefault();
      this.dragging = true;
      const uv = this._getUV(e.touches[0]);
      this.lastX = uv.x;
      this.lastY = uv.y;
    }, { passive: false });

    this.canvasEl.addEventListener('touchmove', (e) => {
      if (!this.dragging || !this.active || !this.fluidSim) return;
      e.preventDefault();
      this._applyForce(e.touches[0]);
    }, { passive: false });

    this.canvasEl.addEventListener('touchend', () => {
      this.dragging = false;
    });
  }

  /**
   * Apply force from a pointer event (mouse or touch).
   * @param {MouseEvent|Touch} e
   * @private
   */
  _applyForce(e) {
    const uv = this._getUV(e);
    const dx = uv.x - this.lastX;
    const dy = uv.y - this.lastY;

    if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) return;

    const brushSize = parseFloat(
      (document.getElementById('brushSize') || {}).value || '40'
    );
    const brushStrength = parseFloat(
      (document.getElementById('brushStrength') || {}).value || '80'
    );

    // Radius in UV space (squared for Gaussian falloff)
    const radius = (brushSize / this.canvasEl.width) * 0.5;
    const radiusSq = radius * radius;

    // Force proportional to mouse delta and brush strength
    const force = brushStrength * 0.5;
    this.fluidSim.addForce(uv.x, uv.y, dx * force, dy * force, radiusSq);

    this.lastX = uv.x;
    this.lastY = uv.y;
  }

  /**
   * Convert a mouse/touch event to UV coordinates [0,1] x [0,1].
   * Y is flipped for WebGL convention (bottom=0, top=1).
   *
   * @param {MouseEvent|Touch} e
   * @returns {{ x: number, y: number }}
   * @private
   */
  _getUV(e) {
    const rect = this.canvasEl.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = 1.0 - (e.clientY - rect.top) / rect.height;
    return { x, y };
  }
}
