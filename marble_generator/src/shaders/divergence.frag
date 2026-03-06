#version 300 es
precision highp float;

in vec2 vUV;
out vec4 fragColor;

uniform sampler2D uVelocity;
uniform vec2 uTexelSize;

void main() {
  float uR = texture(uVelocity, vUV + vec2(uTexelSize.x, 0.0)).x;
  float uL = texture(uVelocity, vUV - vec2(uTexelSize.x, 0.0)).x;
  float vT = texture(uVelocity, vUV + vec2(0.0, uTexelSize.y)).y;
  float vB = texture(uVelocity, vUV - vec2(0.0, uTexelSize.y)).y;
  fragColor = vec4(0.5 * (uR - uL + vT - vB), 0.0, 0.0, 1.0);
}
