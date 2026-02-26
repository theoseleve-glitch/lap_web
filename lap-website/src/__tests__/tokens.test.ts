import { describe, it, expect } from 'vitest';
import { colors, timing, easing, rooms, sectorTabs } from '@/lib/tokens';

describe('Token system', () => {
  it('exports all base colors', () => {
    expect(colors.asphalt).toBe('#0B0C0F');
    expect(colors.concrete).toBe('#161A20');
    expect(colors.chalk).toBe('#F3F0E8');
    expect(colors.steel).toBe('#8A8F98');
  });

  it('exports all accent colors', () => {
    expect(colors.acidGreen).toBe('#B6FF2E');
    expect(colors.safetyRed).toBe('#FF2A2A');
    expect(colors.marshalYellow).toBe('#FFD400');
    expect(colors.pitOrange).toBe('#FF6A00');
  });

  it('exports timing in seconds for GSAP', () => {
    expect(timing.micro).toBe(0.42);
    expect(timing.room).toBe(0.9);
    expect(timing.monument).toBe(1.4);
  });

  it('exports GSAP easing strings', () => {
    expect(easing.inertia).toBe('power3.out');
    expect(easing.overshoot).toContain('back.out');
  });

  it('defines 9 rooms', () => {
    expect(rooms).toHaveLength(9);
    expect(rooms[0].id).toBe('start-grid');
    expect(rooms[8].id).toBe('podium');
  });

  it('defines 6 sector tabs', () => {
    expect(sectorTabs).toHaveLength(6);
    expect(sectorTabs[0].label).toBe('S1');
    expect(sectorTabs[5].label).toBe('POD');
  });
});
