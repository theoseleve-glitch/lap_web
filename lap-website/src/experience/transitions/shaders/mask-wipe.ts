export const maskWipeFragment = /* glsl */ `
uniform sampler2D tFrom;
uniform sampler2D tTo;
uniform float uProgress;
uniform vec3 uAccentColor;
varying vec2 vUv;

void main() {
  float edge = smoothstep(uProgress - 0.005, uProgress + 0.005, vUv.x);
  vec4 fromColor = texture2D(tFrom, vUv);
  vec4 toColor = texture2D(tTo, vUv);

  float edgeGlow = smoothstep(uProgress - 0.01, uProgress, vUv.x)
                 * smoothstep(uProgress + 0.01, uProgress, vUv.x);
  vec4 accent = vec4(uAccentColor, 1.0) * edgeGlow * 2.0;

  gl_FragColor = mix(toColor, fromColor, edge) + accent;
}
`;

export const maskWipeVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
