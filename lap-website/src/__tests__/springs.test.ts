import { describe, it, expect } from 'vitest';
import { physics, reveal, background } from '@/experience/motion/springs';

describe('Physics constants', () => {
  it('has existing scroll physics', () => {
    expect(physics.scrollLerp).toBe(0.08);
    expect(physics.magnetismRadius).toBe(120);
  });
});

describe('Reveal constants', () => {
  it('defines brush and decay parameters', () => {
    expect(reveal.brushRadius).toBe(80);
    expect(reveal.brushSoftness).toBe(0.6);
    expect(reveal.decayFactor).toBe(0.985);
    expect(reveal.inertiaLerp).toBe(0.08);
    expect(reveal.drsRadiusMultiplier).toBe(1.4);
    expect(reveal.idleDecayRate).toBe(0.97);
    expect(reveal.mobileBurstRadius).toBe(120);
  });
});

describe('Background constants', () => {
  it('defines turn-feel parameters', () => {
    expect(background.yawDamping).toBe(0.04);
    expect(background.particleDriftX).toBe(2.0);
    expect(background.particleDriftY).toBe(2.0);
    expect(background.streakSpawnThreshold).toBe(0.4);
    expect(background.streakLifetime).toBe(300);
    expect(background.wheelFriction).toBe(0.95);
  });
});
