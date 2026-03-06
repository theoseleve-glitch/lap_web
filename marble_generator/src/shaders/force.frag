#version 300 es
precision highp float;

in vec2 vUV;
out vec4 fragColor;

uniform sampler2D uTarget;
uniform vec2 uPoint;
uniform vec3 uValue;
uniform float uRadius, uAspect;

void main() {
  vec2 d = vUV - uPoint;
  d.x *= uAspect;
  float s = exp(-dot(d, d) / uRadius);
  fragColor = texture(uTarget, vUV) + s * vec4(uValue, 0.0);
}
