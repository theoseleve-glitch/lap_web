/**
 * Shader source strings as ES module exports.
 *
 * All shaders use GLSL ES 3.00 (#version 300 es).
 * These inline sources mirror the .vert/.frag files in src/shaders/
 * so the engine works without a bundler or fetch calls.
 */

// ---------------------------------------------------------------------------
// Vertex shader — fullscreen quad
// ---------------------------------------------------------------------------
export const VERT = `#version 300 es
layout(location = 0) in vec2 aPos;
out vec2 vUV;
void main() {
  vUV = aPos * 0.5 + 0.5;
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

// ---------------------------------------------------------------------------
// Semi-Lagrangian advection (velocity or any quantity)
// ---------------------------------------------------------------------------
export const ADVECT = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uVelocity, uSource;
uniform vec2 uTexelSize;
uniform float uDt, uDissipation;
void main() {
  vec2 vel = texture(uVelocity, vUV).xy;
  vec2 pos = vUV - vel * uTexelSize * uDt;
  fragColor = uDissipation * texture(uSource, pos);
}`;

// ---------------------------------------------------------------------------
// Velocity divergence
// ---------------------------------------------------------------------------
export const DIVERGENCE = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uVelocity;
uniform vec2 uTexelSize;
void main() {
  float uR = texture(uVelocity, vUV + vec2(uTexelSize.x, 0.0)).x;
  float uL = texture(uVelocity, vUV - vec2(uTexelSize.x, 0.0)).x;
  float vT = texture(uVelocity, vUV + vec2(0.0, uTexelSize.y)).y;
  float vB = texture(uVelocity, vUV - vec2(0.0, uTexelSize.y)).y;
  fragColor = vec4(0.5 * (uR - uL + vT - vB), 0.0, 0.0, 1.0);
}`;

// ---------------------------------------------------------------------------
// Jacobi pressure iteration
// ---------------------------------------------------------------------------
export const PRESSURE = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uPressure, uDivergence;
uniform vec2 uTexelSize;
void main() {
  float pR = texture(uPressure, vUV + vec2(uTexelSize.x, 0.0)).x;
  float pL = texture(uPressure, vUV - vec2(uTexelSize.x, 0.0)).x;
  float pT = texture(uPressure, vUV + vec2(0.0, uTexelSize.y)).x;
  float pB = texture(uPressure, vUV - vec2(0.0, uTexelSize.y)).x;
  float div = texture(uDivergence, vUV).x;
  fragColor = vec4((pL + pR + pB + pT - div) * 0.25, 0.0, 0.0, 1.0);
}`;

// ---------------------------------------------------------------------------
// Subtract pressure gradient from velocity
// ---------------------------------------------------------------------------
export const GRADIENT_SUBTRACT = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uPressure, uVelocity;
uniform vec2 uTexelSize;
void main() {
  float pR = texture(uPressure, vUV + vec2(uTexelSize.x, 0.0)).x;
  float pL = texture(uPressure, vUV - vec2(uTexelSize.x, 0.0)).x;
  float pT = texture(uPressure, vUV + vec2(0.0, uTexelSize.y)).x;
  float pB = texture(uPressure, vUV - vec2(0.0, uTexelSize.y)).x;
  vec2 vel = texture(uVelocity, vUV).xy;
  vel -= 0.5 * vec2(pR - pL, pT - pB);
  fragColor = vec4(vel, 0.0, 1.0);
}`;

// ---------------------------------------------------------------------------
// Gaussian splat for external forces
// ---------------------------------------------------------------------------
export const FORCE = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uTarget;
uniform vec2 uPoint;
uniform vec3 uValue;
uniform float uRadius, uAspect;
void main() {
  vec2 d = vUV - uPoint;
  d.x *= uAspect;
  float s = exp(-dot(d, d) / uRadius);
  fragColor = texture(uTarget, vUV) + s * vec4(uValue, 0.0);
}`;

// ---------------------------------------------------------------------------
// Compute curl of velocity field (vorticity magnitude)
// ---------------------------------------------------------------------------
export const VORTICITY = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uVelocity;
uniform vec2 uTexelSize;
void main() {
  float vR = texture(uVelocity, vUV + vec2(uTexelSize.x, 0.0)).y;
  float vL = texture(uVelocity, vUV - vec2(uTexelSize.x, 0.0)).y;
  float uT = texture(uVelocity, vUV + vec2(0.0, uTexelSize.y)).x;
  float uB = texture(uVelocity, vUV - vec2(0.0, uTexelSize.y)).x;
  float curl = 0.5 * ((vR - vL) - (uT - uB));
  fragColor = vec4(curl, 0.0, 0.0, 1.0);
}`;

// ---------------------------------------------------------------------------
// Vorticity confinement: eta x curl
// ---------------------------------------------------------------------------
export const VORTICITY_FORCE = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uVelocity, uCurl;
uniform vec2 uTexelSize;
uniform float uConfinement, uDt;
void main() {
  float cR = abs(texture(uCurl, vUV + vec2(uTexelSize.x, 0.0)).x);
  float cL = abs(texture(uCurl, vUV - vec2(uTexelSize.x, 0.0)).x);
  float cT = abs(texture(uCurl, vUV + vec2(0.0, uTexelSize.y)).x);
  float cB = abs(texture(uCurl, vUV - vec2(0.0, uTexelSize.y)).x);
  vec2 eta = vec2(cR - cL, cT - cB);
  float len = length(eta) + 1e-5;
  eta /= len;
  float curl = texture(uCurl, vUV).x;
  vec2 force = uConfinement * vec2(eta.y * curl, -eta.x * curl);
  vec2 vel = texture(uVelocity, vUV).xy;
  fragColor = vec4(vel + force * uDt, 0.0, 1.0);
}`;

// ---------------------------------------------------------------------------
// Boundary enforcement: zero outward velocity at domain edges
// ---------------------------------------------------------------------------
export const BOUNDARY = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uVelocity;
uniform vec2 uTexelSize;
void main() {
  vec2 vel = texture(uVelocity, vUV).xy;
  // No-penetration: clamp outward-facing normal velocity at each edge
  if (vUV.x < uTexelSize.x)       vel.x = max(vel.x, 0.0);
  if (vUV.x > 1.0 - uTexelSize.x) vel.x = min(vel.x, 0.0);
  if (vUV.y < uTexelSize.y)       vel.y = max(vel.y, 0.0);
  if (vUV.y > 1.0 - uTexelSize.y) vel.y = min(vel.y, 0.0);
  fragColor = vec4(vel, 0.0, 1.0);
}`;

// ---------------------------------------------------------------------------
// Passthrough display shader
// ---------------------------------------------------------------------------
export const DISPLAY = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uTexture;
void main() {
  fragColor = vec4(texture(uTexture, vUV).rgb, 1.0);
}`;

// ---------------------------------------------------------------------------
// Dye advection (separate from velocity advection for different dissipation)
// ---------------------------------------------------------------------------
export const ADVECT_DYE = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uVelocity, uDye;
uniform vec2 uTexelSize;
uniform float uDt, uDissipation;
void main() {
  vec2 vel = texture(uVelocity, vUV).xy;
  vec2 pos = vUV - vel * uTexelSize * uDt;
  fragColor = uDissipation * texture(uDye, pos);
}`;

// ---------------------------------------------------------------------------
// Phase snap: re-discretize dye after advection to enforce immiscibility.
// Reads both dye textures, finds the global winning phase, and outputs
// 1.0 for the winner in the selected output texture, 0.0 elsewhere.
// ---------------------------------------------------------------------------
export const PHASE_SNAP = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;
uniform sampler2D uDye0;
uniform sampler2D uDye1;
uniform int uColorCount;
uniform int uOutputTex; // 0 = write dye0, 1 = write dye1
void main() {
  vec4 d0 = texture(uDye0, vUV);
  vec4 d1 = texture(uDye1, vUV);
  int bestIdx = 0;
  float bestVal = d0.r;
  if (d0.g > bestVal) { bestVal = d0.g; bestIdx = 1; }
  if (uColorCount > 2 && d0.b > bestVal) { bestVal = d0.b; bestIdx = 2; }
  if (uColorCount > 3 && d0.a > bestVal) { bestVal = d0.a; bestIdx = 3; }
  if (uColorCount > 4 && d1.r > bestVal) { bestVal = d1.r; bestIdx = 4; }
  if (uColorCount > 5 && d1.g > bestVal) { bestVal = d1.g; bestIdx = 5; }
  if (uColorCount > 6 && d1.b > bestVal) { bestVal = d1.b; bestIdx = 6; }
  if (uColorCount > 7 && d1.a > bestVal) { bestVal = d1.a; bestIdx = 7; }
  if (uOutputTex == 0) {
    fragColor = vec4(
      bestIdx == 0 ? 1.0 : 0.0,
      bestIdx == 1 ? 1.0 : 0.0,
      bestIdx == 2 ? 1.0 : 0.0,
      bestIdx == 3 ? 1.0 : 0.0
    );
  } else {
    fragColor = vec4(
      bestIdx == 4 ? 1.0 : 0.0,
      bestIdx == 5 ? 1.0 : 0.0,
      bestIdx == 6 ? 1.0 : 0.0,
      bestIdx == 7 ? 1.0 : 0.0
    );
  }
}`;

// ---------------------------------------------------------------------------
// N-color compositing: immiscible phases — each pixel snaps to the
// single phase with the highest density (winner-takes-all / argmax).
// ---------------------------------------------------------------------------
export const COLOR_MAP = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;

#define MAX_COLORS 8

uniform sampler2D uDye;
uniform sampler2D uDye2;
uniform int uColorCount;
uniform vec3 uColors[MAX_COLORS];
uniform float uThresholds[MAX_COLORS];
uniform float uContrast;

void main() {
  vec4 d1 = texture(uDye, vUV);
  vec4 d2 = texture(uDye2, vUV);
  int bestIdx = 0;
  float bestDensity = -1.0;
  for (int i = 0; i < MAX_COLORS; i++) {
    if (i >= uColorCount) break;
    float density = i < 4 ? d1[i] : d2[i - 4];
    if (density > bestDensity) {
      bestDensity = density;
      bestIdx = i;
    }
  }
  vec3 col = uColors[bestIdx];
  fragColor = vec4(col, 1.0);
}`;

// ---------------------------------------------------------------------------
// GPU-side velocity presets.
// uPreset int selects the pattern:
//   0 = curl noise (requires uNoise sampler)
//   1 = laminar horizontal
//   2 = laminar vertical
//   3 = radial outward
//   4 = radial inward
//   5 = single vortex
//   6 = double counter-rotating vortex
//   7 = turbulent (high-freq curl noise)
// ---------------------------------------------------------------------------
export const VELOCITY_INIT = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 fragColor;

uniform int uPreset;
uniform float uMagnitude;
uniform float uAngle;
uniform sampler2D uNoise;

void main() {
  vec2 vel = vec2(0.0);
  vec2 c = vUV - 0.5;
  float r = length(c) + 0.001;
  float mag = uMagnitude * 0.01;

  if (uPreset == 1) {
    // Laminar horizontal
    vel = vec2(cos(uAngle), sin(uAngle)) * mag;
  } else if (uPreset == 2) {
    // Laminar vertical
    vel = vec2(-sin(uAngle), cos(uAngle)) * mag;
  } else if (uPreset == 3) {
    // Radial outward
    vel = normalize(c) * mag * (1.0 - r);
  } else if (uPreset == 4) {
    // Radial inward
    vel = -normalize(c) * mag * r;
  } else if (uPreset == 5) {
    // Single vortex
    vel = vec2(-c.y, c.x) / r * mag * exp(-r * 4.0);
  } else if (uPreset == 6) {
    // Double counter-rotating vortex
    vec2 c1 = vUV - vec2(0.35, 0.5);
    vec2 c2 = vUV - vec2(0.65, 0.5);
    float r1 = length(c1) + 0.01;
    float r2 = length(c2) + 0.01;
    vel = vec2(-c1.y, c1.x) / r1 * mag * exp(-r1 * 3.0)
        + vec2(c2.y, -c2.x) / r2 * mag * exp(-r2 * 3.0);
  } else {
    // Preset 0 (curl noise) and 7 (turbulent)
    float freq = uPreset == 7 ? 4.0 : 2.0;
    vec2 uv = vUV * freq;
    float eps = 0.01;
    float pU = texture(uNoise, vec2(uv.x, uv.y + eps)).x;
    float pD = texture(uNoise, vec2(uv.x, uv.y - eps)).x;
    float pR = texture(uNoise, vec2(uv.x + eps, uv.y)).x;
    float pL = texture(uNoise, vec2(uv.x - eps, uv.y)).x;
    vel.x =  (pU - pD) / (2.0 * eps) * mag;
    vel.y = -(pR - pL) / (2.0 * eps) * mag;
  }

  fragColor = vec4(vel, 0.0, 1.0);
}`;
