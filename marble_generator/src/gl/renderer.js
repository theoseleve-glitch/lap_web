/**
 * Renderer — WebGL2 context setup with required extensions, fullscreen quad VAO,
 * FBO management, shader compilation, and uniform helpers.
 *
 * Required extensions:
 *   - EXT_color_buffer_float  (render to RGBA32F)
 *   - OES_texture_float_linear (linear filtering on float textures)
 */
export class Renderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @throws {Error} if WebGL2 or EXT_color_buffer_float is unavailable
   */
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext('webgl2', { antialias: false, alpha: false });
    if (!this.gl) {
      throw new Error('WebGL2 not supported');
    }

    const gl = this.gl;

    // Required: render-to-float-texture
    const extFloat = gl.getExtension('EXT_color_buffer_float');
    if (!extFloat) {
      throw new Error('EXT_color_buffer_float not supported');
    }

    // Optional but desired: linear filtering on float textures
    gl.getExtension('OES_texture_float_linear');

    this.programs = {};
    this.fbo = gl.createFramebuffer();

    // Build fullscreen quad VAO (two triangles covering clip space)
    const quadVerts = new Float32Array([
      -1, -1,
       1, -1,
      -1,  1,
      -1,  1,
       1, -1,
       1,  1,
    ]);
    this.quadVAO = gl.createVertexArray();
    gl.bindVertexArray(this.quadVAO);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, quadVerts, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
    this._quadBuf = buf;
  }

  /**
   * Compile a single shader (vertex or fragment).
   * @param {GLenum} type - gl.VERTEX_SHADER or gl.FRAGMENT_SHADER
   * @param {string} source - GLSL source
   * @returns {WebGLShader}
   * @throws {Error} on compilation failure
   */
  compileShader(type, source) {
    const gl = this.gl;
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error('Shader compile error: ' + log);
    }
    return shader;
  }

  /**
   * Create a linked program from vertex and fragment sources.
   * Shaders are deleted after linking (they are ref-counted by the program).
   * @param {string} vertSrc
   * @param {string} fragSrc
   * @returns {WebGLProgram}
   * @throws {Error} on link failure
   */
  createProgram(vertSrc, fragSrc) {
    const gl = this.gl;
    const vs = this.compileShader(gl.VERTEX_SHADER, vertSrc);
    const fs = this.compileShader(gl.FRAGMENT_SHADER, fragSrc);
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      const log = gl.getProgramInfoLog(prog);
      gl.deleteProgram(prog);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      throw new Error('Program link error: ' + log);
    }
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    return prog;
  }

  /**
   * Draw a fullscreen quad with the given program, rendering into target texture
   * (via the internal FBO) or to the canvas (target = null).
   * @param {WebGLProgram} program
   * @param {WebGLTexture|null} target - render target texture, or null for canvas
   * @param {number} width - viewport width (ignored when target is null)
   * @param {number} height - viewport height (ignored when target is null)
   */
  blit(program, target, width, height) {
    const gl = this.gl;
    gl.useProgram(program);
    if (target) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
      gl.framebufferTexture2D(
        gl.FRAMEBUFFER,
        gl.COLOR_ATTACHMENT0,
        gl.TEXTURE_2D,
        target,
        0
      );
      gl.viewport(0, 0, width, height);
    } else {
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    }
    gl.bindVertexArray(this.quadVAO);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  /**
   * Bind a texture to a sampler uniform.
   * @param {WebGLProgram} program
   * @param {string} uniformName
   * @param {WebGLTexture} texture
   * @param {number} unit - texture unit index (0, 1, 2, ...)
   */
  bindTexture(program, uniformName, texture, unit) {
    const gl = this.gl;
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.uniform1i(gl.getUniformLocation(program, uniformName), unit);
  }

  /**
   * Set a float uniform.
   * @param {WebGLProgram} program
   * @param {string} name
   * @param {number} value
   */
  setFloat(program, name, value) {
    this.gl.uniform1f(this.gl.getUniformLocation(program, name), value);
  }

  /**
   * Set a vec2 uniform.
   * @param {WebGLProgram} program
   * @param {string} name
   * @param {number} x
   * @param {number} y
   */
  setVec2(program, name, x, y) {
    this.gl.uniform2f(this.gl.getUniformLocation(program, name), x, y);
  }

  /**
   * Set a vec3 uniform.
   * @param {WebGLProgram} program
   * @param {string} name
   * @param {number} x
   * @param {number} y
   * @param {number} z
   */
  setVec3(program, name, x, y, z) {
    this.gl.uniform3f(this.gl.getUniformLocation(program, name), x, y, z);
  }

  /**
   * Set an int uniform.
   * @param {WebGLProgram} program
   * @param {string} name
   * @param {number} value
   */
  setInt(program, name, value) {
    this.gl.uniform1i(this.gl.getUniformLocation(program, name), value);
  }

  /**
   * Delete all GL resources owned by this renderer.
   */
  destroy() {
    const gl = this.gl;
    gl.deleteFramebuffer(this.fbo);
    gl.deleteVertexArray(this.quadVAO);
    gl.deleteBuffer(this._quadBuf);
    for (const name in this.programs) {
      gl.deleteProgram(this.programs[name]);
    }
    this.programs = {};
  }
}
