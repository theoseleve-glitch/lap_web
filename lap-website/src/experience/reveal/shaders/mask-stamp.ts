/** Stamps a soft brush at pointer position onto the mask texture */
export const maskStampVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const maskStampFragment = /* glsl */ `
uniform sampler2D tPrevMask;
uniform vec2 uPointer;       // normalized screen coords (0-1)
uniform float uRadius;       // brush radius in UV space
uniform float uSoftness;     // Gaussian sigma multiplier (0-1)
uniform float uStrength;     // stamp opacity (0-1)
varying vec2 vUv;

void main() {
  vec4 prev = texture2D(tPrevMask, vUv);

  // Distance from pointer in UV space
  float dist = distance(vUv, uPointer);
  float normalizedDist = dist / max(uRadius, 0.001);

  // Gaussian falloff for soft edge
  float sigma = mix(0.2, 0.8, uSoftness);
  float brush = exp(-0.5 * (normalizedDist * normalizedDist) / (sigma * sigma));
  brush *= uStrength;

  // Additive stamp (max to prevent darkening)
  float mask = max(prev.r, brush);
  gl_FragColor = vec4(mask, mask, mask, 1.0);
}
`;
