/** Track ribbon surface shader — dark base with emissive edges and progress glow */
export const trackRibbonVertex = /* glsl */ `
varying vec2 vUv;
varying float vProgress;

uniform float uCameraProgress;

void main() {
  vUv = uv;
  vProgress = uv.y;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const trackRibbonFragment = /* glsl */ `
uniform float uCameraProgress;
uniform float uEdgeEmissive;
uniform float uForwardGlow;
uniform vec3 uEdgeColor;
uniform vec3 uSectorColor;
uniform float uSectorGlow;
uniform float uSectorStart;
uniform float uSectorEnd;
uniform float uFinishProgress;

varying vec2 vUv;
varying float vProgress;

void main() {
  // Base: very dark, barely visible
  vec3 base = vec3(0.04, 0.045, 0.06);

  // Edge glow: bright thin lines at U=0 and U=1
  float edgeDist = min(vUv.x, 1.0 - vUv.x);
  float edgeMask = smoothstep(0.05, 0.0, edgeDist);
  vec3 edge = uEdgeColor * edgeMask * uEdgeEmissive;

  // Forward progress glow: brighter ahead, dimmer behind
  float progressDelta = vProgress - uCameraProgress;
  float forwardMask = smoothstep(-0.05, 0.1, progressDelta) * smoothstep(0.3, 0.05, progressDelta);
  vec3 forward = uEdgeColor * forwardMask * uForwardGlow;

  // Completed sector highlight
  float sectorMask = step(uSectorStart, vProgress) * step(vProgress, uSectorEnd);
  vec3 sector = uSectorColor * sectorMask * uSectorGlow * edgeMask;

  // Finish line checkered pattern
  float finishDist = abs(vProgress - uFinishProgress);
  float finishMask = smoothstep(0.012, 0.0, finishDist);
  float checkerX = step(0.5, fract(vUv.x * 8.0));
  float checkerY = step(0.5, fract(vProgress * 200.0));
  float checker = abs(checkerX - checkerY); // XOR pattern
  vec3 finishColor = mix(vec3(0.9), vec3(0.1), checker) * finishMask;

  vec3 color = base + edge + forward + sector + finishColor;
  float alpha = 0.8 * edgeMask + 0.15 + forwardMask * 0.3 + sectorMask * 0.2 + finishMask * 0.8;

  gl_FragColor = vec4(color, clamp(alpha, 0.0, 1.0));
}
`;
