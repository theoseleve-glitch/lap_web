/**
 * MultiPhase — manages N immiscible dye phases packed into RGBA channels.
 *
 * Phases 0-3 are packed into tex0 (RGBA), phases 4-7 into tex1 (RGBA).
 * Each phase represents a distinct color/material in the marble simulation.
 * After each advection step, a phase-snap pass re-discretizes the dye
 * so each cell belongs to exactly one phase (immiscible constraint).
 */

import { TexturePool } from '../gl/texture-pool.js';
import { VERT, ADVECT_DYE, COLOR_MAP, PHASE_SNAP } from './shader-sources.js';

export class MultiPhase {
  /**
   * @param {import('../gl/renderer.js').Renderer} renderer
   * @param {number} gridWidth
   * @param {number} gridHeight
   * @param {import('../color/palette.js').createPalette} palette - palette object from createPalette()
   */
  constructor(renderer, gridWidth, gridHeight, palette) {
    this.renderer = renderer;
    this.gl = renderer.gl;
    this.width = gridWidth;
    this.height = gridHeight;
    this.palette = palette;

    this._pool = new TexturePool(this.gl);

    // Ping-pong pairs for two RGBA32F dye textures
    // tex0: phases 0-3 in RGBA channels
    // tex1: phases 4-7 in RGBA channels
    const pp0 = this._pool.createPingPong(gridWidth, gridHeight);
    this.dye0Read = pp0[0];
    this.dye0Write = pp0[1];

    const pp1 = this._pool.createPingPong(gridWidth, gridHeight);
    this.dye1Read = pp1[0];
    this.dye1Write = pp1[1];

    // Compile shader programs
    this._advectDyeProg = renderer.createProgram(VERT, ADVECT_DYE);
    this._colorMapProg = renderer.createProgram(VERT, COLOR_MAP);
    this._phaseSnapProg = renderer.createProgram(VERT, PHASE_SNAP);

    this._texelX = 1.0 / gridWidth;
    this._texelY = 1.0 / gridHeight;
  }

  /**
   * Initialize dye fields from a distribution mode.
   *
   * For each grid cell, evaluates the distribution function to get a scalar
   * in [0,1], maps it through palette thresholds to find the color index,
   * and sets density=1.0 in the corresponding RGBA channel of the
   * appropriate texture (tex0 for indices 0-3, tex1 for indices 4-7).
   *
   * @param {string} mode - Distribution mode name (key in MODES)
   * @param {Function} noiseFn - 2D noise function (x, y) => [-1, 1]
   * @param {object} [params] - Mode-specific parameters
   */
  initFromDistribution(mode, noiseFn, params) {
    const { MODES } = this._getDistributionModule();
    const distFn = MODES[mode];
    if (!distFn) {
      throw new Error(`Unknown distribution mode "${mode}"`);
    }

    const w = this.width;
    const h = this.height;
    const count = this.palette.count;
    const thresholds = this.palette.thresholds;

    const data0 = new Float32Array(w * h * 4);
    const data1 = new Float32Array(w * h * 4);

    for (let j = 0; j < h; j++) {
      const ny = j / (h - 1 || 1);
      for (let i = 0; i < w; i++) {
        const nx = i / (w - 1 || 1);
        const idx = (j * w + i) * 4;

        const value = distFn(nx, ny, noiseFn, params);

        // Find color index via thresholds
        let colorIdx = 0;
        for (let c = 0; c < count; c++) {
          if (value <= thresholds[c]) {
            colorIdx = c;
            break;
          }
        }

        // Set density=1.0 in the corresponding RGBA channel
        if (colorIdx < 4) {
          data0[idx + colorIdx] = 1.0;
        } else {
          data1[idx + (colorIdx - 4)] = 1.0;
        }
      }
    }

    // Upload to GPU textures
    const gl = this.gl;
    this._uploadData(this.dye0Read, data0, w, h);
    this._uploadData(this.dye1Read, data1, w, h);
  }

  /**
   * Upload Float32Array data to a texture.
   * @private
   */
  _uploadData(texture, data, width, height) {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, width, height, gl.RGBA, gl.FLOAT, data);
  }

  /**
   * Lazy-load the distribution module reference to avoid circular imports.
   * @private
   */
  _getDistributionModule() {
    if (!this._distModule) {
      throw new Error('Distribution module not set. Call setDistributionModule() first.');
    }
    return this._distModule;
  }

  /**
   * Set the distribution module reference.
   * @param {{ MODES: object }} mod
   */
  setDistributionModule(mod) {
    this._distModule = mod;
  }

  /**
   * Advect dye fields using the current velocity texture, then snap
   * each cell to its dominant phase (immiscible enforcement).
   *
   * Pipeline per step:
   *   1. Advect dye0 (bilinear, smooth movement)
   *   2. Advect dye1
   *   3. Phase-snap dye0 (argmax across all phases → 1.0 winner, 0.0 rest)
   *   4. Phase-snap dye1
   *
   * @param {WebGLTexture} velocityTex - Current velocity field texture
   * @param {number} dt - Timestep
   */
  advect(velocityTex, dt) {
    const r = this.renderer;
    const gl = this.gl;
    const w = this.width;
    const h = this.height;
    const advProg = this._advectDyeProg;

    // --- 1. Advect dye texture 0 (phases 0-3) ---
    gl.useProgram(advProg);
    r.bindTexture(advProg, 'uVelocity', velocityTex, 0);
    r.bindTexture(advProg, 'uDye', this.dye0Read, 1);
    r.setVec2(advProg, 'uTexelSize', this._texelX, this._texelY);
    r.setFloat(advProg, 'uDt', dt);
    r.setFloat(advProg, 'uDissipation', 1.0);
    r.blit(advProg, this.dye0Write, w, h);
    this._swapDye0();

    // --- 2. Advect dye texture 1 (phases 4-7) ---
    gl.useProgram(advProg);
    r.bindTexture(advProg, 'uVelocity', velocityTex, 0);
    r.bindTexture(advProg, 'uDye', this.dye1Read, 1);
    r.setVec2(advProg, 'uTexelSize', this._texelX, this._texelY);
    r.setFloat(advProg, 'uDt', dt);
    r.setFloat(advProg, 'uDissipation', 1.0);
    r.blit(advProg, this.dye1Write, w, h);
    this._swapDye1();

    // After advection: dye0Read = advected dye0, dye1Read = advected dye1
    // Save references to advected (pre-snap) textures for both snap passes
    const advDye0 = this.dye0Read;
    const advDye1 = this.dye1Read;

    // --- 3. Phase-snap dye0 ---
    const snapProg = this._phaseSnapProg;
    gl.useProgram(snapProg);
    r.bindTexture(snapProg, 'uDye0', advDye0, 0);
    r.bindTexture(snapProg, 'uDye1', advDye1, 1);
    r.setInt(snapProg, 'uColorCount', Math.min(this.palette.count, 8));
    r.setInt(snapProg, 'uOutputTex', 0);
    r.blit(snapProg, this.dye0Write, w, h);
    this._swapDye0();
    // Now: dye0Read = snapped, dye0Write = advDye0 (original advected)

    // --- 4. Phase-snap dye1 ---
    // Use the original advected textures (dye0Write = advDye0, dye1Read = advDye1)
    gl.useProgram(snapProg);
    r.bindTexture(snapProg, 'uDye0', this.dye0Write, 0); // = advDye0
    r.bindTexture(snapProg, 'uDye1', this.dye1Read, 1);   // = advDye1
    r.setInt(snapProg, 'uColorCount', Math.min(this.palette.count, 8));
    r.setInt(snapProg, 'uOutputTex', 1);
    r.blit(snapProg, this.dye1Write, w, h);
    this._swapDye1();
  }

  /** Swap dye0 read/write textures. @private */
  _swapDye0() {
    const tmp = this.dye0Read;
    this.dye0Read = this.dye0Write;
    this.dye0Write = tmp;
  }

  /** Swap dye1 read/write textures. @private */
  _swapDye1() {
    const tmp = this.dye1Read;
    this.dye1Read = this.dye1Write;
    this.dye1Write = tmp;
  }

  /**
   * Render final composited color from dye phases.
   *
   * Uses argmax: each pixel displays the color of whichever phase
   * has the highest density (immiscible rendering).
   *
   * @param {WebGLTexture|null} target - Render target, null for screen
   * @param {number} displayWidth
   * @param {number} displayHeight
   */
  renderColor(target, displayWidth, displayHeight) {
    const r = this.renderer;
    const gl = this.gl;
    const prog = this._colorMapProg;
    const palette = this.palette;

    gl.useProgram(prog);

    // Bind both dye textures
    r.bindTexture(prog, 'uDye', this.dye0Read, 0);
    r.bindTexture(prog, 'uDye2', this.dye1Read, 1);

    // Upload color array (vec3[8])
    const colorsFlat = new Float32Array(8 * 3);
    for (let i = 0; i < Math.min(palette.count, 8); i++) {
      colorsFlat[i * 3]     = palette.colors[i].r;
      colorsFlat[i * 3 + 1] = palette.colors[i].g;
      colorsFlat[i * 3 + 2] = palette.colors[i].b;
    }
    const colorsLoc = gl.getUniformLocation(prog, 'uColors');
    gl.uniform3fv(colorsLoc, colorsFlat);

    // Upload thresholds array (float[8])
    const thresholdsFlat = new Float32Array(8);
    for (let i = 0; i < Math.min(palette.count, 8); i++) {
      thresholdsFlat[i] = palette.thresholds[i];
    }
    const threshLoc = gl.getUniformLocation(prog, 'uThresholds');
    gl.uniform1fv(threshLoc, thresholdsFlat);

    // Set color count and contrast
    r.setInt(prog, 'uColorCount', Math.min(palette.count, 8));
    r.setFloat(prog, 'uContrast', 1.2);

    r.blit(prog, target, displayWidth, displayHeight);
  }

  /** Release all GPU resources. */
  destroy() {
    const gl = this.gl;
    this._pool.destroy();
    gl.deleteProgram(this._advectDyeProg);
    gl.deleteProgram(this._colorMapProg);
    gl.deleteProgram(this._phaseSnapProg);
  }
}
