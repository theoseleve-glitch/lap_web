// Shared GLSL utilities for the metallic background layer.
// Imported as string and prepended to vertex/fragment shaders.

export const metallicCommon = /* glsl */ `

// ── Fresnel ────────────────────────────────────
// Schlick approximation: F0 + (1 - F0) * (1 - cosTheta)^power
float fresnelSchlick(float cosTheta, float power) {
  return pow(clamp(1.0 - cosTheta, 0.0, 1.0), power);
}

// ── Anisotropic specular (Ward-Ashikhmin) ──────
// N: surface normal, H: half-vector, T: tangent, B: bitangent
// roughnessT/B: directional roughness, specPower: overall sharpness
float anisotropicSpecular(
  vec3 N, vec3 H, vec3 T, vec3 B,
  float roughnessT, float roughnessB, float specPower
) {
  float NdotH = max(dot(N, H), 0.0);
  float TdotH = dot(T, H);
  float BdotH = dot(B, H);

  float exponent = -(
    (TdotH * TdotH) / (roughnessT * roughnessT) +
    (BdotH * BdotH) / (roughnessB * roughnessB)
  ) / max(NdotH * NdotH, 0.001);

  float norm = 1.0 / (4.0 * 3.14159 * roughnessT * roughnessB);
  return norm * exp(exponent) * pow(NdotH, specPower);
}

// ── Hue shift (Rodrigues rotation in RGB) ──────
// Rotates color hue by angleRadians around the luminance axis (1,1,1)/sqrt(3)
vec3 hueShift(vec3 color, float angleRadians) {
  float cosA = cos(angleRadians);
  float sinA = sin(angleRadians);
  // Rodrigues: v_rot = v*cos + (k×v)*sin + k*(k·v)*(1-cos)
  // k = normalize(1,1,1) = (0.577, 0.577, 0.577)
  float k = 0.57735;
  vec3 kVec = vec3(k);
  float kDotC = dot(kVec, color);
  vec3 kCrossC = vec3(
    k * color.z - k * color.y,
    k * color.x - k * color.z,
    k * color.y - k * color.x
  );
  return color * cosA + kCrossC * sinA + kVec * kDotC * (1.0 - cosA);
}

// ── Event animation pulse shapes ───────────────
// t: normalized progress 0→1

// Shimmer: quick attack, ringing decay (sector completion)
float pulseShimmer(float t) {
  float attack = smoothstep(0.0, 0.15, t);
  float ring = sin(t * 12.566) * exp(-t * 4.0); // 2*PI*2 = 4 oscillations
  return attack * (0.6 + 0.4 * ring) * (1.0 - t);
}

// Sustained: ramp up, hold, gentle fade (DRS glow)
float pulseSustained(float t) {
  float ramp = smoothstep(0.0, 0.2, t);
  float fade = 1.0 - smoothstep(0.7, 1.0, t);
  return ramp * fade;
}

// Flash: sharp spike, instant decay (finish line)
float pulseFlash(float t) {
  return exp(-t * 8.0) * step(0.0, t);
}
`;
