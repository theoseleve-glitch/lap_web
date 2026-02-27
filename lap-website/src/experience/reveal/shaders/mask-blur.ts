/** Separable 5-tap Gaussian blur for mask softening */
export const maskBlurVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const maskBlurFragment = /* glsl */ `
uniform sampler2D tMask;
uniform vec2 uDirection;    // (1/width, 0) or (0, 1/height) for separable
uniform float uSigma;
varying vec2 vUv;

void main() {
  // 5-tap kernel weights for Gaussian
  float weights[5];
  weights[0] = 0.227027;
  weights[1] = 0.194596;
  weights[2] = 0.121621;
  weights[3] = 0.054054;
  weights[4] = 0.016216;

  float result = texture2D(tMask, vUv).r * weights[0];

  for (int i = 1; i < 5; i++) {
    vec2 offset = uDirection * float(i) * uSigma;
    result += texture2D(tMask, vUv + offset).r * weights[i];
    result += texture2D(tMask, vUv - offset).r * weights[i];
  }

  gl_FragColor = vec4(result, result, result, 1.0);
}
`;
