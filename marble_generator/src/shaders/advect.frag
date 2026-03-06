#version 300 es
precision highp float;

in vec2 vUV;
out vec4 fragColor;

uniform sampler2D uVelocity, uSource;
uniform vec2 uTexelSize;
uniform float uDt, uDissipation;

void main() {
  vec2 vel = texture(uVelocity, vUV).xy;
  vec2 pos = vUV - vel * uTexelSize * uDt;
  fragColor = uDissipation * texture(uSource, pos);
}
