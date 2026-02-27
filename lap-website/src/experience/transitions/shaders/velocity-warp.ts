export const velocityWarpFragment = /* glsl */ `
uniform sampler2D tFrom;
uniform sampler2D tTo;
uniform float uProgress;
uniform float uVelocity;
varying vec2 vUv;

void main() {
  float p = smoothstep(0.0, 1.0, uProgress);

  float warpStrength = abs(uVelocity) * 0.3 * sin(p * 3.14159);
  vec2 warpedUv = vUv;
  warpedUv.y += warpStrength * sign(uVelocity) * sin(vUv.x * 6.28318);

  vec4 fromColor = texture2D(tFrom, warpedUv);
  vec4 toColor = texture2D(tTo, vUv);

  gl_FragColor = mix(fromColor, toColor, p);
}
`;

export const velocityWarpVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
