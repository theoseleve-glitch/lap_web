/** Radial vignette that darkens edges — shifts toward corner apex when turning */
export const vignetteVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const vignetteFragment = /* glsl */ `
uniform float uRadius;
uniform vec2 uShift;
varying vec2 vUv;

void main() {
  vec2 center = vec2(0.5) + uShift;
  float dist = distance(vUv, center);
  // Smooth vignette falloff: fully transparent at center, opaque at edges
  float vignette = smoothstep(uRadius, uRadius + 0.5, dist);
  gl_FragColor = vec4(0.0, 0.0, 0.0, vignette * 0.6);
}
`;
