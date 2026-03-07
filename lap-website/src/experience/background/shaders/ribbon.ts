import { metallicCommon } from './metallic-common';

// ── Vertex shader ──────────────────────────────
export const ribbonVertex = /* glsl */ `
precision highp float;

attribute float aCurvature;
attribute float aTrackT;

varying vec2 vUv;
varying vec3 vWorldPos;
varying vec3 vWorldNormal;
varying vec3 vWorldTangent;
varying vec3 vWorldBitangent;
varying vec3 vViewDir;
varying float vEdgeFactor;
varying float vCurvature;
varying float vTrackT;

void main() {
  vec4 worldPos = modelMatrix * vec4(position, 1.0);
  vWorldPos = worldPos.xyz;
  vWorldNormal = normalize((modelMatrix * vec4(normal, 0.0)).xyz);

  // Tangent from attribute (vec4, w = handedness)
  vWorldTangent = normalize((modelMatrix * vec4(tangent.xyz, 0.0)).xyz);
  vWorldBitangent = cross(vWorldNormal, vWorldTangent) * tangent.w;

  vViewDir = normalize(cameraPosition - worldPos.xyz);
  vUv = uv;
  // Edge factor: 0 at ribbon center, 1 at edges (uv.x is across width: 0=left, 1=right)
  vEdgeFactor = abs(uv.x - 0.5) * 2.0;
  vCurvature = aCurvature;
  vTrackT = aTrackT;

  gl_Position = projectionMatrix * viewMatrix * worldPos;
}
`;

// ── Fragment shader ────────────────────────────
export const ribbonFragment = /* glsl */ `
precision highp float;

${metallicCommon}

// Uniforms
uniform float uTime;
uniform float uRibbonProgress;
uniform vec3  uLightDir;
uniform float uLightSweepProgress;
uniform float uPurpleIntensity;
uniform float uGreenIntensity;
uniform float uRimWidth;
uniform float uSpecularPower;
uniform float uAnisotropy;
uniform float uFresnelPower;
uniform float uHueShift;
uniform float uSectorShimmer;
uniform float uDrsGlow;
uniform float uFinishFlash;
uniform float uGuidancePulse;
uniform float uOpacityMin;
uniform float uOpacityMax;
uniform float uQualityTier;

// Varyings
varying vec2 vUv;
varying vec3 vWorldPos;
varying vec3 vWorldNormal;
varying vec3 vWorldTangent;
varying vec3 vWorldBitangent;
varying vec3 vViewDir;
varying float vEdgeFactor;
varying float vCurvature;
varying float vTrackT;

void main() {
  vec3 N = normalize(vWorldNormal);
  vec3 V = normalize(vViewDir);
  vec3 T = normalize(vWorldTangent);
  vec3 B = normalize(vWorldBitangent);
  vec3 L = normalize(uLightDir);
  vec3 H = normalize(L + V);

  // 1. Base: near-black matte
  vec3 baseColor = vec3(0.02, 0.02, 0.025);

  // 2. Edge rim: smoothstep glow at ribbon edges
  float rimMask = smoothstep(1.0 - uRimWidth, 1.0, vEdgeFactor);
  vec3 rimColor = vec3(0.08);

  // 3. Specular: tiered
  float spec = 0.0;
  if (uQualityTier >= 2.0) {
    // High: anisotropic Ward
    float rT = mix(0.06, 0.15, uAnisotropy);
    float rB = mix(0.35, 0.55, uAnisotropy);
    spec = anisotropicSpecular(N, H, T, B, rT, rB, uSpecularPower);
  } else if (uQualityTier >= 1.0) {
    // Balanced: Blinn-Phong
    float NdotH = max(dot(N, H), 0.0);
    spec = pow(NdotH, uSpecularPower);
  } else {
    // Low: simple dot
    float NdotL = max(dot(N, L), 0.0);
    spec = NdotL * 0.5;
  }

  // 4. Fresnel
  float fresnel = 0.0;
  if (uQualityTier >= 1.0) {
    float NdotV = max(dot(N, V), 0.0);
    fresnel = fresnelSchlick(NdotV, uFresnelPower);
  }

  // 5. Hue shift: view-angle iridescence (high tier only)
  vec3 specColor = vec3(1.0);
  if (uQualityTier >= 2.0) {
    float viewAngle = dot(V, T);
    specColor = hueShift(vec3(1.0), uHueShift * viewAngle);
  }

  // 6. Metallic color: purple/green blend
  vec3 purple = vec3(0.85, 0.275, 0.937);  // #D946EF
  vec3 green  = vec3(0.714, 1.0, 0.18);    // #B6FF2E
  vec3 metallicColor = mix(
    mix(vec3(0.5), purple, uPurpleIntensity),
    green,
    uGreenIntensity
  );

  // 7. Light sweep: Gaussian highlight at sweep position
  float sweepDist = abs(vTrackT - uLightSweepProgress);
  // Handle wrap-around (closed track)
  sweepDist = min(sweepDist, 1.0 - sweepDist);
  float sweepHighlight = exp(-sweepDist * sweepDist * 200.0) * 0.15;

  // 8. Event animations
  float sectorFx  = pulseShimmer(uSectorShimmer) * 0.12;
  float drsFx      = pulseSustained(uDrsGlow) * 0.10;
  float finishFx   = pulseFlash(uFinishFlash) * 0.16;
  float guidanceFx = sin(uGuidancePulse * 3.14159) * 0.06;

  // Composite metallic contribution
  float metallicStrength = spec * 0.3 + fresnel * 0.2
    + sectorFx + drsFx + finishFx + guidanceFx + sweepHighlight;
  vec3 metallic = metallicColor * specColor * metallicStrength;

  // 9. Compose
  vec3 color = baseColor + rimColor * rimMask + metallic;

  // 10. Progress fade: ribbon ahead of camera is slightly dimmer
  float aheadDist = vTrackT - uRibbonProgress;
  if (aheadDist < 0.0) aheadDist += 1.0; // wrap
  float progressFade = mix(1.0, 0.6, smoothstep(0.0, 0.4, aheadDist));

  // Final opacity
  float alpha = mix(uOpacityMin, uOpacityMax, rimMask + metallicStrength);
  alpha *= progressFade;
  alpha = clamp(alpha, uOpacityMin, uOpacityMax);

  gl_FragColor = vec4(color, alpha);
}
`;
