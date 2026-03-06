#version 300 es
precision highp float;

in vec2 vUV;
out vec4 fragColor;

uniform sampler2D uVelocity, uCurl;
uniform vec2 uTexelSize;
uniform float uConfinement, uDt;

void main() {
  float cR = abs(texture(uCurl, vUV + vec2(uTexelSize.x, 0.0)).x);
  float cL = abs(texture(uCurl, vUV - vec2(uTexelSize.x, 0.0)).x);
  float cT = abs(texture(uCurl, vUV + vec2(0.0, uTexelSize.y)).x);
  float cB = abs(texture(uCurl, vUV - vec2(0.0, uTexelSize.y)).x);
  vec2 eta = vec2(cR - cL, cT - cB);
  float len = length(eta) + 1e-5;
  eta /= len;
  float curl = texture(uCurl, vUV).x;
  vec2 force = uConfinement * vec2(eta.y * curl, -eta.x * curl);
  vec2 vel = texture(uVelocity, vUV).xy;
  fragColor = vec4(vel + force * uDt, 0.0, 1.0);
}
