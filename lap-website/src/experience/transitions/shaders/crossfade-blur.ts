export const crossfadeBlurFragment = /* glsl */ `
uniform sampler2D tFrom;
uniform sampler2D tTo;
uniform float uProgress;
varying vec2 vUv;

void main() {
  float p = smoothstep(0.0, 1.0, uProgress);
  float blurAmount = 8.0 * (1.0 - abs(p - 0.5) * 2.0);

  vec2 dir = vec2(blurAmount / 1000.0, 0.0);
  vec4 fromColor = vec4(0.0);
  vec4 toColor = vec4(0.0);

  for (int i = -4; i <= 4; i++) {
    vec2 offset = dir * float(i);
    fromColor += texture2D(tFrom, vUv + offset);
    toColor += texture2D(tTo, vUv + offset);
  }
  fromColor /= 9.0;
  toColor /= 9.0;

  gl_FragColor = mix(fromColor, toColor, p);
}
`;

export const crossfadeBlurVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
