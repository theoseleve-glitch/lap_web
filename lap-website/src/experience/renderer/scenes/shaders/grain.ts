/** Full-screen grain noise — hash-based white noise modulated by uIntensity */
export const grainVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const grainFragment = /* glsl */ `
uniform float uTime;
uniform float uIntensity;
varying vec2 vUv;

// Hash-based pseudo-random noise (no texture dependency)
float hash(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

void main() {
  // Animate seed with time so grain shimmers each frame
  float noise = hash(vUv * 1000.0 + uTime * 7.13);
  // Center around 0.5 grey, modulate by intensity
  float grain = (noise - 0.5) * uIntensity;
  gl_FragColor = vec4(vec3(0.5 + grain), uIntensity);
}
`;
