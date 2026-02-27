export const truthTrackMapVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const truthTrackMapFragment = /* glsl */ `
uniform float uTime;
uniform float uProgress;
uniform vec3 uEdgeColor;
uniform vec3 uSectorColor;
uniform float uSectorEnd;

varying vec2 vUv;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
  // Grid lines — faint blueprint grid
  float gridX = smoothstep(0.02, 0.0, fract(vUv.x * 20.0));
  float gridY = smoothstep(0.02, 0.0, fract(vUv.y * 20.0));
  float grid = max(gridX, gridY) * 0.15;

  // Track centerline
  float centerDist = abs(vUv.x - 0.5);
  float centerLine = smoothstep(0.02, 0.0, centerDist) * 0.8;

  // Sector highlight band
  float sectorMask = step(0.0, vUv.y) * step(vUv.y, uSectorEnd);
  float sectorBand = sectorMask * smoothstep(0.15, 0.1, centerDist) * 0.3;

  // Braking zone markers (periodic dashes)
  float brakeDash = step(0.7, fract(vUv.y * 40.0)) * smoothstep(0.08, 0.05, centerDist) * 0.4;

  // Apex markers (dots at specific positions)
  float apexDot = 0.0;
  for (int i = 0; i < 5; i++) {
    float apexY = float(i) * 0.2 + 0.1;
    float dist = length(vUv - vec2(0.5, apexY));
    apexDot += smoothstep(0.015, 0.005, dist) * 0.6;
  }

  vec3 color = uEdgeColor * (grid + centerLine + brakeDash + apexDot)
             + uSectorColor * sectorBand;

  float n = hash(vUv * 100.0 + uTime) * 0.02;
  float alpha = grid + centerLine + sectorBand + brakeDash + apexDot + n;
  gl_FragColor = vec4(color, clamp(alpha, 0.0, 0.9));
}
`;
