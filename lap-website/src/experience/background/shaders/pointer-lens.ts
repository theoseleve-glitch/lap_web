// Fragment shader for radial barrel distortion around the pointer position.
// Used as a postprocessing Effect.

export const pointerLensFragment = /* glsl */ `
uniform vec2 uPointerPos;       // normalized [0,1] screen position
uniform float uDistortionStrength; // max displacement (~0.003)
uniform float uRadius;          // falloff radius (~0.15)
uniform float uQualityTier;     // 2=high (chromatic), 1=balanced (mono), 0=off

void mainUv(inout vec2 uv) {
  if (uQualityTier < 1.0) return;

  vec2 delta = uv - uPointerPos;
  float dist = length(delta);
  float falloff = 1.0 - smoothstep(0.0, uRadius, dist);

  // Barrel distortion: push UVs outward from pointer
  vec2 distortion = delta * falloff * uDistortionStrength;
  uv += distortion;
}

void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor) {
  if (uQualityTier < 2.0) {
    // Balanced: no chromatic fringe, just the distorted UV
    outputColor = inputColor;
    return;
  }

  // High tier: chromatic fringe (slight R/B channel offset)
  vec2 delta = uv - uPointerPos;
  float dist = length(delta);
  float falloff = 1.0 - smoothstep(0.0, uRadius, dist);
  float fringeOffset = falloff * uDistortionStrength * 0.5;
  vec2 dir = normalize(delta + vec2(0.001));

  float r = texture2D(inputBuffer, uv + dir * fringeOffset).r;
  float g = inputColor.g;
  float b = texture2D(inputBuffer, uv - dir * fringeOffset).b;

  outputColor = vec4(r, g, b, inputColor.a);
}
`;
