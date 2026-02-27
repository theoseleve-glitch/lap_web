export const truthTelemetryVertex = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const truthTelemetryFragment = /* glsl */ `
uniform float uTime;
uniform float uProgress;
uniform vec3 uTraceColor;
uniform vec3 uGridColor;

varying vec2 vUv;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
  // Fine grid
  float gridX = smoothstep(0.015, 0.0, fract(vUv.x * 30.0));
  float gridY = smoothstep(0.015, 0.0, fract(vUv.y * 30.0));
  float grid = max(gridX, gridY) * 0.1;

  // 3 horizontal trace waveforms
  float trace = 0.0;
  for (int i = 0; i < 3; i++) {
    float yBase = 0.25 + float(i) * 0.25;
    float wave = sin(vUv.x * 40.0 + uTime * 2.0 + float(i) * 1.5) * 0.03;
    float dist = abs(vUv.y - yBase - wave);
    trace += smoothstep(0.008, 0.0, dist) * 0.6;
  }

  // Delta bar at bottom
  float deltaBar = smoothstep(0.06, 0.04, vUv.y) * smoothstep(0.0, 0.02, vUv.y);
  float deltaFill = step(vUv.x, uProgress) * deltaBar * 0.4;

  // Timing dashes along top
  float timingDash = step(0.92, vUv.y) * smoothstep(0.02, 0.0, fract(vUv.x * 15.0)) * 0.3;

  vec3 color = uGridColor * grid + uTraceColor * trace + uTraceColor * deltaFill + uGridColor * timingDash;

  float n = hash(vUv * 200.0 + uTime) * 0.015;
  float alpha = grid + trace + deltaFill + timingDash + n;

  gl_FragColor = vec4(color, clamp(alpha, 0.0, 0.85));
}
`;
