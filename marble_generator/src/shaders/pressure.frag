#version 300 es
precision highp float;

in vec2 vUV;
out vec4 fragColor;

uniform sampler2D uPressure, uDivergence;
uniform vec2 uTexelSize;

void main() {
  float pR = texture(uPressure, vUV + vec2(uTexelSize.x, 0.0)).x;
  float pL = texture(uPressure, vUV - vec2(uTexelSize.x, 0.0)).x;
  float pT = texture(uPressure, vUV + vec2(0.0, uTexelSize.y)).x;
  float pB = texture(uPressure, vUV - vec2(0.0, uTexelSize.y)).x;
  float div = texture(uDivergence, vUV).x;
  fragColor = vec4((pL + pR + pB + pT - div) * 0.25, 0.0, 0.0, 1.0);
}
