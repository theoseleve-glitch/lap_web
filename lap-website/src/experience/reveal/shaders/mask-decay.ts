/** Decays mask persistence by multiplying by a factor < 1.0 each frame */
export const maskDecayVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const maskDecayFragment = /* glsl */ `
uniform sampler2D tMask;
uniform float uDecay;   // 0.985 = ~3s to 10%
varying vec2 vUv;

void main() {
  float mask = texture2D(tMask, vUv).r;
  mask *= uDecay;
  gl_FragColor = vec4(mask, mask, mask, 1.0);
}
`;
