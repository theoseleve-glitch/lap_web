/**
 * TexturePool — manages RGBA32F texture creation, ping-pong pairs, and cleanup.
 *
 * All textures are tracked for bulk cleanup via destroy().
 * Ping-pong pairs are returned as a two-element array [read, write].
 */
export class TexturePool {
  constructor(gl) {
    this.gl = gl;
    this.textures = [];
  }

  /**
   * Create a single RGBA32F texture with LINEAR filtering and CLAMP_TO_EDGE wrapping.
   * @param {number} width
   * @param {number} height
   * @param {GLenum|null} internalFormat - defaults to gl.RGBA32F
   * @returns {WebGLTexture}
   */
  createTexture(width, height, internalFormat = null) {
    const gl = this.gl;
    internalFormat = internalFormat || gl.RGBA32F;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      internalFormat,
      width,
      height,
      0,
      gl.RGBA,
      gl.FLOAT,
      null
    );
    this.textures.push(tex);
    return tex;
  }

  /**
   * Create a ping-pong pair (two textures of the same dimensions).
   * @param {number} width
   * @param {number} height
   * @returns {[WebGLTexture, WebGLTexture]}
   */
  createPingPong(width, height) {
    return [this.createTexture(width, height), this.createTexture(width, height)];
  }

  /**
   * Delete all tracked textures and clear the internal list.
   */
  destroy() {
    const gl = this.gl;
    for (const tex of this.textures) {
      gl.deleteTexture(tex);
    }
    this.textures = [];
  }
}
