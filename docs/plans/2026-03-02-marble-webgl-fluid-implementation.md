# Marble Generator WebGL Fluid Engine — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the CPU-bound marble generator with a full WebGL2 Navier-Stokes fluid simulation, N-color distribution system with presets/modes, and configurable initial velocity fields with a custom vector editor.

**Architecture:** WebGL2 fragment shader ping-pong on RGBA32F textures for the fluid solver. Separate ES modules for GL plumbing, fluid engine, color system, velocity presets, and UI. The existing `index.html` becomes a thin shell importing these modules. CLI keeps enhanced CPU path, sharing palette/preset data.

**Tech Stack:** WebGL2, GLSL ES 3.00, ES modules (browser-native), sharp + open-simplex-noise (CLI), no bundler needed

**Design doc:** `docs/plans/2026-03-02-marble-webgl-fluid-design.md`

---

## Phase 1: WebGL2 Foundation (Tasks 1-4)

### Task 1: WebGL2 Renderer Core — Texture Pool + FBO Management

**Files:**
- Create: `marble_generator/src/gl/renderer.js`
- Create: `marble_generator/src/gl/texture-pool.js`

**Step 1: Create texture-pool.js**

This module manages RGBA32F texture creation, ping-pong pairs, and cleanup.

```js
// marble_generator/src/gl/texture-pool.js

export class TexturePool {
  constructor(gl) {
    this.gl = gl;
    this.textures = [];
  }

  createTexture(width, height, internalFormat = null) {
    const gl = this.gl;
    internalFormat = internalFormat || gl.RGBA32F;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, width, height, 0, gl.RGBA, gl.FLOAT, null);
    this.textures.push(tex);
    return tex;
  }

  createPingPong(width, height) {
    return [this.createTexture(width, height), this.createTexture(width, height)];
  }

  destroy() {
    const gl = this.gl;
    for (const tex of this.textures) gl.deleteTexture(tex);
    this.textures = [];
  }
}
```

**Step 2: Create renderer.js**

Core WebGL2 context setup, fullscreen quad VAO, FBO management, and shader compilation.

```js
// marble_generator/src/gl/renderer.js

export class Renderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext('webgl2', { antialias: false, alpha: false });
    if (!this.gl) throw new Error('WebGL2 not supported');

    const gl = this.gl;
    const ext = gl.getExtension('EXT_color_buffer_float');
    if (!ext) throw new Error('EXT_color_buffer_float not supported');
    gl.getExtension('OES_texture_float_linear');

    this.programs = {};
    this.fbo = gl.createFramebuffer();

    // Fullscreen quad
    const quadVerts = new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]);
    this.quadVAO = gl.createVertexArray();
    gl.bindVertexArray(this.quadVAO);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, quadVerts, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
  }

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
      throw new Error('Program link error: ' + log);
    }
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    return prog;
  }

  blit(program, target, width, height) {
    const gl = this.gl;
    gl.useProgram(program);
    if (target) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, target, 0);
      gl.viewport(0, 0, width, height);
    } else {
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    }
    gl.bindVertexArray(this.quadVAO);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  bindTexture(program, uniformName, texture, unit) {
    const gl = this.gl;
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.uniform1i(gl.getUniformLocation(program, uniformName), unit);
  }

  setFloat(program, name, value) {
    this.gl.uniform1f(this.gl.getUniformLocation(program, name), value);
  }

  setVec2(program, name, x, y) {
    this.gl.uniform2f(this.gl.getUniformLocation(program, name), x, y);
  }

  setVec3(program, name, x, y, z) {
    this.gl.uniform3f(this.gl.getUniformLocation(program, name), x, y, z);
  }

  setInt(program, name, value) {
    this.gl.uniform1i(this.gl.getUniformLocation(program, name), value);
  }

  destroy() {
    const gl = this.gl;
    gl.deleteFramebuffer(this.fbo);
    gl.deleteVertexArray(this.quadVAO);
    for (const name in this.programs) gl.deleteProgram(this.programs[name]);
  }
}
```

**Step 3: Verify WebGL2 initializes in the browser**

Open `index.html`, add a temporary `<script type="module">` at the bottom:
```html
<script type="module">
  import { Renderer } from './src/gl/renderer.js';
  const cvs = document.createElement('canvas');
  cvs.width = 100; cvs.height = 100;
  try {
    const r = new Renderer(cvs);
    console.log('WebGL2 + float textures OK');
    r.destroy();
  } catch (e) { console.error(e.message); }
</script>
```

Expected: Console prints "WebGL2 + float textures OK".

**Step 4: Commit**

```bash
git add marble_generator/src/gl/
git commit -m "feat(marble): add WebGL2 renderer core with texture pool and FBO management"
```

---

### Task 2: GLSL Shaders — Vertex + Core Fluid Shaders

**Files:**
- Create: `marble_generator/src/shaders/common.vert`
- Create: `marble_generator/src/shaders/advect.frag`
- Create: `marble_generator/src/shaders/divergence.frag`
- Create: `marble_generator/src/shaders/pressure.frag`
- Create: `marble_generator/src/shaders/gradient-subtract.frag`
- Create: `marble_generator/src/shaders/force.frag`

All shaders use GLSL ES 3.00 (`#version 300 es`).

**Step 1: Create common.vert**

```glsl
#version 300 es
layout(location = 0) in vec2 aPos;
out vec2 vUV;
void main() {
  vUV = aPos * 0.5 + 0.5;
  gl_Position = vec4(aPos, 0.0, 1.0);
}
```

**Step 2: Create advect.frag**

```glsl
#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uVelocity, uSource;
uniform vec2 uTexelSize; uniform float uDt, uDissipation;
void main() {
  vec2 vel = texture(uVelocity, vUV).xy;
  vec2 pos = vUV - vel * uTexelSize * uDt;
  fragColor = uDissipation * texture(uSource, pos);
}
```

**Step 3: Create divergence.frag**

```glsl
#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uVelocity; uniform vec2 uTexelSize;
void main() {
  float uR = texture(uVelocity, vUV + vec2(uTexelSize.x, 0.0)).x;
  float uL = texture(uVelocity, vUV - vec2(uTexelSize.x, 0.0)).x;
  float vT = texture(uVelocity, vUV + vec2(0.0, uTexelSize.y)).y;
  float vB = texture(uVelocity, vUV - vec2(0.0, uTexelSize.y)).y;
  fragColor = vec4(0.5 * (uR - uL + vT - vB), 0.0, 0.0, 1.0);
}
```

**Step 4: Create pressure.frag**

```glsl
#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uPressure, uDivergence; uniform vec2 uTexelSize;
void main() {
  float pR = texture(uPressure, vUV + vec2(uTexelSize.x, 0.0)).x;
  float pL = texture(uPressure, vUV - vec2(uTexelSize.x, 0.0)).x;
  float pT = texture(uPressure, vUV + vec2(0.0, uTexelSize.y)).x;
  float pB = texture(uPressure, vUV - vec2(0.0, uTexelSize.y)).x;
  float div = texture(uDivergence, vUV).x;
  fragColor = vec4((pL + pR + pB + pT - div) * 0.25, 0.0, 0.0, 1.0);
}
```

**Step 5: Create gradient-subtract.frag**

```glsl
#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uPressure, uVelocity; uniform vec2 uTexelSize;
void main() {
  float pR = texture(uPressure, vUV + vec2(uTexelSize.x, 0.0)).x;
  float pL = texture(uPressure, vUV - vec2(uTexelSize.x, 0.0)).x;
  float pT = texture(uPressure, vUV + vec2(0.0, uTexelSize.y)).x;
  float pB = texture(uPressure, vUV - vec2(0.0, uTexelSize.y)).x;
  vec2 vel = texture(uVelocity, vUV).xy;
  vel -= 0.5 * vec2(pR - pL, pT - pB);
  fragColor = vec4(vel, 0.0, 1.0);
}
```

**Step 6: Create force.frag**

```glsl
#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uTarget;
uniform vec2 uPoint; uniform vec3 uValue;
uniform float uRadius, uAspect;
void main() {
  vec2 d = vUV - uPoint; d.x *= uAspect;
  float s = exp(-dot(d, d) / uRadius);
  fragColor = texture(uTarget, vUV) + s * vec4(uValue, 0.0);
}
```

**Step 7: Commit**

```bash
git add marble_generator/src/shaders/
git commit -m "feat(marble): add GLSL shaders for Navier-Stokes fluid simulation"
```

---

### Task 3: Vorticity Confinement Shaders

**Files:**
- Create: `marble_generator/src/shaders/vorticity.frag`
- Create: `marble_generator/src/shaders/vorticity-force.frag`

**Step 1: Create vorticity.frag**

```glsl
#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uVelocity; uniform vec2 uTexelSize;
void main() {
  float vR = texture(uVelocity, vUV + vec2(uTexelSize.x, 0.0)).y;
  float vL = texture(uVelocity, vUV - vec2(uTexelSize.x, 0.0)).y;
  float uT = texture(uVelocity, vUV + vec2(0.0, uTexelSize.y)).x;
  float uB = texture(uVelocity, vUV - vec2(0.0, uTexelSize.y)).x;
  float curl = 0.5 * ((vR - vL) - (uT - uB));
  fragColor = vec4(curl, 0.0, 0.0, 1.0);
}
```

**Step 2: Create vorticity-force.frag**

```glsl
#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uVelocity, uCurl;
uniform vec2 uTexelSize; uniform float uConfinement, uDt;
void main() {
  float cR = abs(texture(uCurl, vUV + vec2(uTexelSize.x, 0.0)).x);
  float cL = abs(texture(uCurl, vUV - vec2(uTexelSize.x, 0.0)).x);
  float cT = abs(texture(uCurl, vUV + vec2(0.0, uTexelSize.y)).x);
  float cB = abs(texture(uCurl, vUV - vec2(0.0, uTexelSize.y)).x);
  vec2 eta = vec2(cR - cL, cT - cB);
  float len = length(eta) + 1e-5; eta /= len;
  float curl = texture(uCurl, vUV).x;
  vec2 force = uConfinement * vec2(eta.y * curl, -eta.x * curl);
  vec2 vel = texture(uVelocity, vUV).xy;
  fragColor = vec4(vel + force * uDt, 0.0, 1.0);
}
```

**Step 3: Commit**

```bash
git add marble_generator/src/shaders/vorticity.frag marble_generator/src/shaders/vorticity-force.frag
git commit -m "feat(marble): add vorticity confinement shaders"
```

---

### Task 4: GPU Fluid Simulation Orchestrator

**Files:**
- Create: `marble_generator/src/engine/fluid-sim.js`
- Create: `marble_generator/src/engine/shader-sources.js`

**Step 1: Create shader-sources.js**

Inline shader source strings as template literals (no bundler needed).

```js
// marble_generator/src/engine/shader-sources.js
// Shader sources as ES module exports for no-bundler setup

export const VERT = `#version 300 es
layout(location=0) in vec2 aPos;
out vec2 vUV;
void main(){vUV=aPos*0.5+0.5;gl_Position=vec4(aPos,0,1);}`;

export const ADVECT = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uVelocity,uSource;
uniform vec2 uTexelSize; uniform float uDt,uDissipation;
void main(){
  vec2 vel=texture(uVelocity,vUV).xy;
  vec2 pos=vUV-vel*uTexelSize*uDt;
  fragColor=uDissipation*texture(uSource,pos);
}`;

export const DIVERGENCE = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uVelocity; uniform vec2 uTexelSize;
void main(){
  float uR=texture(uVelocity,vUV+vec2(uTexelSize.x,0)).x;
  float uL=texture(uVelocity,vUV-vec2(uTexelSize.x,0)).x;
  float vT=texture(uVelocity,vUV+vec2(0,uTexelSize.y)).y;
  float vB=texture(uVelocity,vUV-vec2(0,uTexelSize.y)).y;
  fragColor=vec4(0.5*(uR-uL+vT-vB),0,0,1);
}`;

export const PRESSURE = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uPressure,uDivergence; uniform vec2 uTexelSize;
void main(){
  float pR=texture(uPressure,vUV+vec2(uTexelSize.x,0)).x;
  float pL=texture(uPressure,vUV-vec2(uTexelSize.x,0)).x;
  float pT=texture(uPressure,vUV+vec2(0,uTexelSize.y)).x;
  float pB=texture(uPressure,vUV-vec2(0,uTexelSize.y)).x;
  float div=texture(uDivergence,vUV).x;
  fragColor=vec4((pL+pR+pB+pT-div)*0.25,0,0,1);
}`;

export const GRADIENT_SUBTRACT = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uPressure,uVelocity; uniform vec2 uTexelSize;
void main(){
  float pR=texture(uPressure,vUV+vec2(uTexelSize.x,0)).x;
  float pL=texture(uPressure,vUV-vec2(uTexelSize.x,0)).x;
  float pT=texture(uPressure,vUV+vec2(0,uTexelSize.y)).x;
  float pB=texture(uPressure,vUV-vec2(0,uTexelSize.y)).x;
  vec2 vel=texture(uVelocity,vUV).xy;
  vel-=0.5*vec2(pR-pL,pT-pB);
  fragColor=vec4(vel,0,1);
}`;

export const FORCE = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uTarget;
uniform vec2 uPoint; uniform vec3 uValue;
uniform float uRadius,uAspect;
void main(){
  vec2 d=vUV-uPoint; d.x*=uAspect;
  float s=exp(-dot(d,d)/uRadius);
  fragColor=texture(uTarget,vUV)+s*vec4(uValue,0);
}`;

export const VORTICITY = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uVelocity; uniform vec2 uTexelSize;
void main(){
  float vR=texture(uVelocity,vUV+vec2(uTexelSize.x,0)).y;
  float vL=texture(uVelocity,vUV-vec2(uTexelSize.x,0)).y;
  float uT=texture(uVelocity,vUV+vec2(0,uTexelSize.y)).x;
  float uB=texture(uVelocity,vUV-vec2(0,uTexelSize.y)).x;
  fragColor=vec4(0.5*((vR-vL)-(uT-uB)),0,0,1);
}`;

export const VORTICITY_FORCE = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uVelocity,uCurl;
uniform vec2 uTexelSize; uniform float uConfinement,uDt;
void main(){
  float cR=abs(texture(uCurl,vUV+vec2(uTexelSize.x,0)).x);
  float cL=abs(texture(uCurl,vUV-vec2(uTexelSize.x,0)).x);
  float cT=abs(texture(uCurl,vUV+vec2(0,uTexelSize.y)).x);
  float cB=abs(texture(uCurl,vUV-vec2(0,uTexelSize.y)).x);
  vec2 eta=vec2(cR-cL,cT-cB);
  float len=length(eta)+1e-5; eta/=len;
  float curl=texture(uCurl,vUV).x;
  vec2 force=uConfinement*vec2(eta.y*curl,-eta.x*curl);
  vec2 vel=texture(uVelocity,vUV).xy;
  fragColor=vec4(vel+force*uDt,0,1);
}`;

export const DISPLAY = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uTexture;
void main(){
  fragColor=vec4(texture(uTexture,vUV).rgb,1.0);
}`;

export const ADVECT_DYE = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform sampler2D uVelocity, uDye;
uniform vec2 uTexelSize;
uniform float uDt, uDissipation;
void main(){
  vec2 vel=texture(uVelocity,vUV).xy;
  vec2 pos=vUV-vel*uTexelSize*uDt;
  fragColor=uDissipation*texture(uDye,pos);
}`;

export const COLOR_MAP = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
#define MAX_COLORS 8
uniform sampler2D uDye;
uniform sampler2D uDye2;
uniform int uColorCount;
uniform vec3 uColors[MAX_COLORS];
uniform float uThresholds[MAX_COLORS];
uniform float uContrast;
void main(){
  vec4 d1 = texture(uDye, vUV);
  vec4 d2 = texture(uDye2, vUV);
  vec3 col = vec3(0.0);
  float total = 0.0;
  for(int i=0; i<MAX_COLORS; i++){
    if(i >= uColorCount) break;
    float density = i<4 ? d1[i] : d2[i-4];
    col += uColors[i] * density;
    total += density;
  }
  if(total > 0.001) col /= total;
  else col = uColors[0];
  col = 0.5 + (col - 0.5) * uContrast;
  col = clamp(col, 0.0, 1.0);
  fragColor = vec4(col, 1.0);
}`;

export const VELOCITY_INIT = `#version 300 es
precision highp float;
in vec2 vUV; out vec4 fragColor;
uniform int uPreset;
uniform float uMagnitude;
uniform float uAngle;
uniform sampler2D uNoise;
void main(){
  vec2 vel = vec2(0.0);
  vec2 c = vUV - 0.5;
  float r = length(c) + 0.001;
  float mag = uMagnitude * 0.01;
  if(uPreset == 1){
    vel = vec2(cos(uAngle), sin(uAngle)) * mag;
  } else if(uPreset == 2){
    vel = vec2(-sin(uAngle), cos(uAngle)) * mag;
  } else if(uPreset == 3){
    vel = normalize(c) * mag * (1.0 - r);
  } else if(uPreset == 4){
    vel = -normalize(c) * mag * r;
  } else if(uPreset == 5){
    vel = vec2(-c.y, c.x) / r * mag * exp(-r * 4.0);
  } else if(uPreset == 6){
    vec2 c1 = vUV - vec2(0.35, 0.5);
    vec2 c2 = vUV - vec2(0.65, 0.5);
    float r1 = length(c1) + 0.01;
    float r2 = length(c2) + 0.01;
    vel = vec2(-c1.y, c1.x)/r1 * mag * exp(-r1*3.0)
        + vec2(c2.y, -c2.x)/r2 * mag * exp(-r2*3.0);
  } else {
    float freq = uPreset == 7 ? 4.0 : 2.0;
    vec2 uv = vUV * freq;
    float eps = 0.01;
    float pU = texture(uNoise, vec2(uv.x, uv.y+eps)).x;
    float pD = texture(uNoise, vec2(uv.x, uv.y-eps)).x;
    float pR = texture(uNoise, vec2(uv.x+eps, uv.y)).x;
    float pL = texture(uNoise, vec2(uv.x-eps, uv.y)).x;
    vel.x = (pU - pD) / (2.0*eps) * mag;
    vel.y = -(pR - pL) / (2.0*eps) * mag;
  }
  fragColor = vec4(vel, 0.0, 1.0);
}`;
```

**Step 2: Create fluid-sim.js**

See design doc for full FluidSimGPU class. Key methods:
- `constructor(renderer, gridWidth, gridHeight)` — allocate textures, compile programs
- `step()` — advect, vorticity, divergence, pressure solve, gradient subtract
- `addForce(uvX, uvY, forceX, forceY, radius)` — splat force
- `destroy()` — cleanup GL resources

(Full implementation provided in the design — copy from Task 4 Step 2 above.)

**Step 3: Commit**

```bash
git add marble_generator/src/engine/
git commit -m "feat(marble): add GPU fluid simulation orchestrator with shader sources"
```

---

## Phase 2: Color Distribution System (Tasks 5-7)

### Task 5: N-Color Palette + Presets Module

**Files:**
- Create: `marble_generator/src/color/palette.js`
- Create: `marble_generator/src/color/presets.js`

**Step 1: Create palette.js**

Functions: `hexToRgb(hex)`, `rgbToHex(c)`, `createPalette(entries)`.
`createPalette` takes `[{hex, ratio, density?, viscosity?}]` and returns `{colors, ratios, densities, viscosities, thresholds, count}`.

**Step 2: Create presets.js**

8 marble presets: Nero Marquina, Calacatta Gold, Verde Guatemala, Rosso Levanto, Blue Sodalite, Arabescato, Portoro, Rainbow Onyx. Each has colors array and distribution mode.

**Step 3: Commit**

```bash
git add marble_generator/src/color/
git commit -m "feat(marble): add N-color palette system with 8 marble presets"
```

---

### Task 6: Color Distribution Modes

**Files:**
- Create: `marble_generator/src/color/distribution.js`

**Step 1: Create distribution.js**

5 distribution functions: `veined`, `radial`, `linear`, `clustered`, `swirl`.
Each takes `(x, y, noiseFn, params)` and returns a [0,1] value mapped to palette thresholds.

**Step 2: Commit**

```bash
git add marble_generator/src/color/distribution.js
git commit -m "feat(marble): add 5 color distribution modes"
```

---

### Task 7: Dye Advection + Color Mapping Shaders

Already included in Task 4 shader-sources.js (`ADVECT_DYE` and `COLOR_MAP` exports).

---

## Phase 3: Initial Velocity System (Tasks 8-10)

### Task 8: Velocity Preset Generator (CPU-side)

**Files:**
- Create: `marble_generator/src/engine/velocity-presets.js`

**Step 1: Create velocity-presets.js**

8 presets: curl-noise, laminar-h, laminar-v, radial-out, radial-in, vortex, double-vortex, turbulent. Each generates a Float32Array velocity field. Turbulence overlay added on top of any preset.

**Step 2: Commit**

```bash
git add marble_generator/src/engine/velocity-presets.js
git commit -m "feat(marble): add 8 velocity preset generators with turbulence overlay"
```

---

### Task 9: Velocity Init Shader (GPU-side)

Already included in Task 4 shader-sources.js (`VELOCITY_INIT` export).

---

### Task 10: Custom Vector Field Editor

**Files:**
- Create: `marble_generator/src/ui/vector-editor.js`

**Step 1: Create vector-editor.js**

SVG overlay for placing/dragging velocity arrows. Click to place, drag head to set direction/magnitude, double-click to remove. `toVelocityField(gw, gh)` exports RBF-interpolated Float32Array.

**Step 2: Commit**

```bash
git add marble_generator/src/ui/vector-editor.js
git commit -m "feat(marble): add interactive vector field editor with RBF interpolation"
```

---

## Phase 4: UI Integration + Full Pipeline (Tasks 11-14)

### Task 11: UI Controls Module

**Files:**
- Create: `marble_generator/src/ui/controls.js`

Dynamic color rows (add/remove, max 8), preset dropdown, distribution mode select, physics sliders (viscosity, vorticity, diffusion, timestep, pressure iterations), velocity controls (preset, magnitude, angle, turbulence), Edit Vectors button.

---

### Task 12: Multi-Phase Dye Manager

**Files:**
- Create: `marble_generator/src/engine/multi-phase.js`

Manages N dye textures packed into RGBA channels (tex0: phases 0-3, tex1: phases 4-7). Methods: `initFromDistribution(mode, noiseFn, params)`, `advect(velocityTex, dt)`, `renderColor(target, w, h)`.

---

### Task 13: Gallery + Studio UI Modules

**Files:**
- Create: `marble_generator/src/ui/gallery.js`
- Create: `marble_generator/src/ui/studio.js`

Gallery: card rendering, generation queue, progress bar. Studio: GPU-accelerated interactive fluid editing with mouse drag.

---

### Task 14: Rewrite index.html as Thin Shell

**Files:**
- Modify: `marble_generator/index.html`

Replace 740-line monolith with thin HTML shell importing ES modules. Keep existing CSS. Script section becomes ~100 lines of wiring between modules.

Serve via `npx serve marble_generator/` (ES modules require HTTP).

---

## Phase 5: CLI Enhancement + Polish (Tasks 15-16)

### Task 15: Enhance CLI with N-Color + Velocity Presets

**Files:**
- Modify: `marble_generator/src/cli.js`
- Modify: `marble_generator/src/generator.js`

New CLI flags: `--preset`, `--colors`, `--distribution`, `--velocity`, `--magnitude`, `--viscosity`, `--vorticity`.

---

### Task 16: CPU Fallback for WebGL-Unsupported Browsers

**Files:**
- Modify: `marble_generator/index.html`

Detect WebGL2 + float texture support. Fall back to enhanced CPU FluidSim if unavailable.

---

## Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 | 1-4 | WebGL2 foundation: renderer, shaders, fluid sim orchestrator |
| 2 | 5-7 | N-color palette, presets, distribution modes, dye shaders |
| 3 | 8-10 | Velocity presets, GPU init shader, vector field editor |
| 4 | 11-14 | UI controls, multi-phase manager, gallery/studio, index.html rewrite |
| 5 | 15-16 | CLI enhancement, CPU fallback |

**Total**: 16 tasks, ~30 new files, estimated 2500-3000 lines of code.
