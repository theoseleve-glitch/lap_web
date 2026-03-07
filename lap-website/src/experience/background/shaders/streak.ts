import { metallicCommon } from './metallic-common';

export const streakVertex = /* glsl */ `
precision highp float;

// Per-instance attributes (set via instanceMatrix)
// We use the instance matrix columns to encode:
//   col0 = velocity direction (xyz), col0.w = age
//   col1.x = lifetime, col1.y = speed magnitude
// Position is encoded in col3 (translation)

varying float vLifeProgress;
varying float vEdge;
varying vec3 vWorldPos;

void main() {
  // Decode from instance matrix
  mat4 inst = instanceMatrix;
  vec3 offset = inst[3].xyz;
  float age = inst[0].w;
  float lifetime = inst[1].x;
  float speed = inst[1].y;

  vLifeProgress = clamp(age / max(lifetime, 0.001), 0.0, 1.0);

  // Elongate quad along X based on speed (streak stretches at high speed)
  vec3 pos = position;
  pos.x *= 1.0 + speed * 3.0;

  // Orient along velocity direction stored in col0.xyz
  vec3 velDir = normalize(inst[0].xyz + vec3(0.0, 0.0, 0.001));
  vec3 up = vec3(0.0, 0.0, 1.0);
  vec3 right = normalize(cross(velDir, up));
  vec3 fwd = normalize(cross(up, right));

  vec3 worldPos = offset + right * pos.x + fwd * pos.y + up * pos.z;
  vWorldPos = worldPos;
  vEdge = abs(position.y); // 0 at center, 0.5 at edge

  gl_Position = projectionMatrix * viewMatrix * vec4(worldPos, 1.0);
}
`;

export const streakFragment = /* glsl */ `
precision highp float;

${metallicCommon}

uniform float uTime;
uniform float uPurpleIntensity;
uniform float uGreenIntensity;

varying float vLifeProgress;
varying float vEdge;
varying vec3 vWorldPos;

void main() {
  // White-to-transparent gradient along lifetime
  float lifeFade = 1.0 - vLifeProgress;
  float edgeFade = 1.0 - smoothstep(0.3, 0.5, vEdge);

  // Metallic tip at leading edge (front of the streak)
  vec3 purple = vec3(0.85, 0.275, 0.937);
  vec3 green  = vec3(0.714, 1.0, 0.18);
  vec3 tipColor = mix(purple, green, uGreenIntensity);
  vec3 bodyColor = vec3(0.9, 0.9, 0.95);

  float tipMask = smoothstep(0.3, 0.0, vLifeProgress);
  vec3 color = mix(bodyColor, tipColor, tipMask * 0.6);

  float alpha = lifeFade * edgeFade * 0.12;
  alpha = clamp(alpha, 0.0, 0.14);

  gl_FragColor = vec4(color, alpha);
}
`;
