export const refractionFragment = /* glsl */ `
uniform sampler2D tFrom;
uniform sampler2D tTo;
uniform float uProgress;
uniform float uTime;
varying vec2 vUv;

void main() {
  float p = smoothstep(0.0, 1.0, uProgress);

  float distortion = (1.0 - p) * 0.05;
  vec2 offset = vec2(
    sin(vUv.y * 20.0 + uTime * 2.0) * distortion,
    cos(vUv.x * 20.0 + uTime * 2.0) * distortion
  );

  vec4 fromColor = texture2D(tFrom, vUv + offset);
  vec4 toColor = texture2D(tTo, vUv);

  float fresnel = pow(1.0 - abs(dot(normalize(vec3(vUv - 0.5, 1.0)), vec3(0.0, 0.0, 1.0))), 3.0);
  float glow = fresnel * (1.0 - p) * 0.3;

  gl_FragColor = mix(fromColor, toColor, p) + vec4(glow);
}
`;

export const refractionVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
