import { describe, it, expect } from 'vitest';
import { lerpPointer, computeMaskResolution } from '@/experience/reveal/useRevealState';

describe('Reveal state utilities', () => {
  it('lerpPointer applies inertia to pointer position', () => {
    const result = lerpPointer(
      { x: 0, y: 0 },
      { x: 1, y: 1 },
      0.1,
    );
    expect(result.x).toBeCloseTo(0.1);
    expect(result.y).toBeCloseTo(0.1);
  });

  it('lerpPointer converges to target over many steps', () => {
    let smoothed = { x: 0, y: 0 };
    const target = { x: 0.5, y: 0.5 };
    for (let i = 0; i < 100; i++) {
      smoothed = lerpPointer(smoothed, target, 0.1);
    }
    expect(smoothed.x).toBeCloseTo(0.5, 2);
    expect(smoothed.y).toBeCloseTo(0.5, 2);
  });

  it('computeMaskResolution returns correct resolution per quality tier', () => {
    expect(computeMaskResolution('high')).toBe(1024);
    expect(computeMaskResolution('balanced')).toBe(512);
    expect(computeMaskResolution('low')).toBe(0);
  });
});
