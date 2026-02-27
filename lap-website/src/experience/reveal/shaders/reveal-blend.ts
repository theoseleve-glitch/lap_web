/** Blends Layer A and Layer B using the mask texture */
export const revealBlendVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const revealBlendFragment = /* glsl */ `
uniform sampler2D tLayerA;   // clean surface (default visible)
uniform sampler2D tLayerB;   // truth layer (revealed by mask)
uniform sampler2D tMask;     // reveal mask (r channel = blend factor)
varying vec2 vUv;

void main() {
  vec4 colorA = texture2D(tLayerA, vUv);
  vec4 colorB = texture2D(tLayerB, vUv);
  float mask = texture2D(tMask, vUv).r;

  gl_FragColor = mix(colorA, colorB, mask);
}
`;
