/**
 * FluidSimGPU — orchestrates a full Navier-Stokes fluid simulation on the GPU.
 *
 * Uses ping-pong textures for velocity and pressure fields, and performs:
 *   1. Semi-Lagrangian advection of velocity
 *   2. Vorticity confinement (when vorticity > 0)
 *   3. Divergence computation
 *   4. Pressure solve (Jacobi iteration)
 *   5. Gradient subtraction (pressure projection)
 *
 * External forces can be injected via addForce() as Gaussian splats.
 */

import { TexturePool } from '../gl/texture-pool.js';
import {
  VERT,
  ADVECT,
  DIVERGENCE,
  PRESSURE,
  GRADIENT_SUBTRACT,
  FORCE,
  VORTICITY,
  VORTICITY_FORCE,
  BOUNDARY,
} from './shader-sources.js';

export class FluidSimGPU {
  /**
   * @param {import('../gl/renderer.js').Renderer} renderer
   * @param {number} gridWidth - simulation grid width in texels
   * @param {number} gridHeight - simulation grid height in texels
   */
  constructor(renderer, gridWidth, gridHeight) {
    this.renderer = renderer;
    this.gl = renderer.gl;
    this.width = gridWidth;
    this.height = gridHeight;

    // Physics parameters
    this.viscosity = 0.001;
    this.vorticity = 15.0;
    this.pressureIterations = 40;
    this.dt = 0.5;
    this.velocityDissipation = 0.998;

    // Texel size for neighbor sampling
    this._texelX = 1.0 / gridWidth;
    this._texelY = 1.0 / gridHeight;

    // Allocate textures
    this._pool = new TexturePool(this.gl);

    const pp = (w, h) => this._pool.createPingPong(w, h);
    const tex = (w, h) => this._pool.createTexture(w, h);

    // Velocity ping-pong (RG = u,v)
    const velPP = pp(gridWidth, gridHeight);
    this.velRead = velPP[0];
    this.velWrite = velPP[1];

    // Pressure ping-pong (R channel)
    const presPP = pp(gridWidth, gridHeight);
    this.pRead = presPP[0];
    this.pWrite = presPP[1];

    // Divergence (R channel, single texture)
    this.divergenceTex = tex(gridWidth, gridHeight);

    // Curl / vorticity (R channel, single texture)
    this.curlTex = tex(gridWidth, gridHeight);

    // Compile all shader programs
    this._advectProg = renderer.createProgram(VERT, ADVECT);
    this._divergenceProg = renderer.createProgram(VERT, DIVERGENCE);
    this._pressureProg = renderer.createProgram(VERT, PRESSURE);
    this._gradientProg = renderer.createProgram(VERT, GRADIENT_SUBTRACT);
    this._forceProg = renderer.createProgram(VERT, FORCE);
    this._vorticityProg = renderer.createProgram(VERT, VORTICITY);
    this._vorticityForceProg = renderer.createProgram(VERT, VORTICITY_FORCE);
    this._boundaryProg = renderer.createProgram(VERT, BOUNDARY);
  }

  /** Swap velocity read/write textures. */
  swapVel() {
    const tmp = this.velRead;
    this.velRead = this.velWrite;
    this.velWrite = tmp;
  }

  /** Swap pressure read/write textures. */
  swapP() {
    const tmp = this.pRead;
    this.pRead = this.pWrite;
    this.pWrite = tmp;
  }

  /**
   * Perform one full Navier-Stokes timestep.
   *
   * Pipeline:
   *   advect velocity -> vorticity confinement -> divergence ->
   *   pressure solve (Jacobi) -> gradient subtraction
   */
  step() {
    const r = this.renderer;
    const w = this.width;
    const h = this.height;
    const tx = this._texelX;
    const ty = this._texelY;

    // --- 1. Advect velocity ---
    const advP = this._advectProg;
    r.gl.useProgram(advP);
    r.bindTexture(advP, 'uVelocity', this.velRead, 0);
    r.bindTexture(advP, 'uSource', this.velRead, 1);
    r.setVec2(advP, 'uTexelSize', tx, ty);
    r.setFloat(advP, 'uDt', this.dt);
    r.setFloat(advP, 'uDissipation', this.velocityDissipation);
    r.blit(advP, this.velWrite, w, h);
    this.swapVel();

    // --- 2. Vorticity confinement (skip if vorticity == 0) ---
    if (this.vorticity > 0) {
      // 2a. Compute curl
      const vortP = this._vorticityProg;
      r.gl.useProgram(vortP);
      r.bindTexture(vortP, 'uVelocity', this.velRead, 0);
      r.setVec2(vortP, 'uTexelSize', tx, ty);
      r.blit(vortP, this.curlTex, w, h);

      // 2b. Apply vorticity force
      const vfP = this._vorticityForceProg;
      r.gl.useProgram(vfP);
      r.bindTexture(vfP, 'uVelocity', this.velRead, 0);
      r.bindTexture(vfP, 'uCurl', this.curlTex, 1);
      r.setVec2(vfP, 'uTexelSize', tx, ty);
      r.setFloat(vfP, 'uConfinement', this.vorticity);
      r.setFloat(vfP, 'uDt', this.dt);
      r.blit(vfP, this.velWrite, w, h);
      this.swapVel();
    }

    // --- 3. Compute divergence ---
    const divP = this._divergenceProg;
    r.gl.useProgram(divP);
    r.bindTexture(divP, 'uVelocity', this.velRead, 0);
    r.setVec2(divP, 'uTexelSize', tx, ty);
    r.blit(divP, this.divergenceTex, w, h);

    // --- 4. Pressure solve (Jacobi iteration) ---
    // Clear pressure before solve
    this._clearTexture(this.pRead);
    this._clearTexture(this.pWrite);

    const presP = this._pressureProg;
    for (let i = 0; i < this.pressureIterations; i++) {
      r.gl.useProgram(presP);
      r.bindTexture(presP, 'uPressure', this.pRead, 0);
      r.bindTexture(presP, 'uDivergence', this.divergenceTex, 1);
      r.setVec2(presP, 'uTexelSize', tx, ty);
      r.blit(presP, this.pWrite, w, h);
      this.swapP();
    }

    // --- 5. Subtract pressure gradient ---
    const gradP = this._gradientProg;
    r.gl.useProgram(gradP);
    r.bindTexture(gradP, 'uPressure', this.pRead, 0);
    r.bindTexture(gradP, 'uVelocity', this.velRead, 1);
    r.setVec2(gradP, 'uTexelSize', tx, ty);
    r.blit(gradP, this.velWrite, w, h);
    this.swapVel();

    // --- 6. Boundary enforcement (no-penetration) ---
    const bndP = this._boundaryProg;
    r.gl.useProgram(bndP);
    r.bindTexture(bndP, 'uVelocity', this.velRead, 0);
    r.setVec2(bndP, 'uTexelSize', tx, ty);
    r.blit(bndP, this.velWrite, w, h);
    this.swapVel();
  }

  /**
   * Splat a Gaussian force at the given UV position.
   * @param {number} uvX - horizontal position [0, 1]
   * @param {number} uvY - vertical position [0, 1]
   * @param {number} forceX - force X component
   * @param {number} forceY - force Y component
   * @param {number} radius - Gaussian radius (in UV space, squared denominator)
   */
  addForce(uvX, uvY, forceX, forceY, radius) {
    const r = this.renderer;
    const w = this.width;
    const h = this.height;
    const aspect = w / h;
    const prog = this._forceProg;

    r.gl.useProgram(prog);
    r.bindTexture(prog, 'uTarget', this.velRead, 0);
    r.setVec2(prog, 'uPoint', uvX, uvY);
    r.setVec3(prog, 'uValue', forceX, forceY, 0.0);
    r.setFloat(prog, 'uRadius', radius);
    r.setFloat(prog, 'uAspect', aspect);
    r.blit(prog, this.velWrite, w, h);
    this.swapVel();
  }

  /**
   * Clear a texture to all zeros by rendering a clear color into it.
   * @param {WebGLTexture} tex
   * @private
   */
  _clearTexture(tex) {
    const gl = this.gl;
    const r = this.renderer;
    gl.bindFramebuffer(gl.FRAMEBUFFER, r.fbo);
    gl.framebufferTexture2D(
      gl.FRAMEBUFFER,
      gl.COLOR_ATTACHMENT0,
      gl.TEXTURE_2D,
      tex,
      0
    );
    gl.viewport(0, 0, this.width, this.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  /** Release all GPU resources. */
  destroy() {
    const gl = this.gl;
    this._pool.destroy();
    gl.deleteProgram(this._advectProg);
    gl.deleteProgram(this._divergenceProg);
    gl.deleteProgram(this._pressureProg);
    gl.deleteProgram(this._gradientProg);
    gl.deleteProgram(this._forceProg);
    gl.deleteProgram(this._vorticityProg);
    gl.deleteProgram(this._vorticityForceProg);
    gl.deleteProgram(this._boundaryProg);
  }
}
