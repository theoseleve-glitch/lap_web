import { describe, it, expect } from 'vitest';
import {
  colors, timing, easing, rooms, sectorTabs, roomAccents, sectorGates,
  semantic, elevation, radius, border, spacing, fontFamily, lineHeight,
  letterSpacing, zIndex, focus, touchMin, grid, chartPalette,
} from '@/lib/tokens';

describe('Token system', () => {
  it('exports all base colors matching tokens.css', () => {
    expect(colors.asphalt).toBe('#000000');
    expect(colors.concrete).toBe('#141414');
    expect(colors.chalk).toBe('#F0EDE5');
    expect(colors.steel).toBe('#888888');
  });

  it('exports all accent colors matching tokens.css', () => {
    expect(colors.acidGreen).toBe('#22C55E');
    expect(colors.safetyRed).toBe('#FF2A2A');
    expect(colors.marshalYellow).toBe('#FACC15');
    expect(colors.pitOrange).toBe('#C9A84C');
    expect(colors.racingPurple).toBe('#8B5CF6');
  });

  it('semantic colors reference base palette', () => {
    expect(semantic.success).toBe(colors.acidGreen);
    expect(semantic.warning).toBe(colors.marshalYellow);
    expect(semantic.error).toBe(colors.safetyRed);
    expect(semantic.info).toBe(colors.racingPurple);
    expect(semantic.brand).toBe(colors.pitOrange);
  });

  it('chart palette has 6 series colors', () => {
    expect(chartPalette).toHaveLength(6);
  });

  it('exports timing in seconds for GSAP', () => {
    expect(timing.micro).toBe(0.42);
    expect(timing.room).toBe(0.9);
    expect(timing.monument).toBe(1.4);
  });

  it('exports narrative timing tokens', () => {
    expect(timing.sectorGate).toBe(0.4);
    expect(timing.drs).toBe(2.0);
    expect(timing.pit).toBe(0.6);
    expect(timing.finish).toBe(0.6);
  });

  it('exports GSAP easing strings', () => {
    expect(easing.inertia).toBe('power3.out');
    expect(easing.overshoot).toBe('back.out(1.7)');
  });

  it('defines 11 rooms', () => {
    expect(rooms).toHaveLength(11);
    expect(rooms[0].id).toBe('start-grid');
    expect(rooms[10].id).toBe('podium');
  });

  it('defines 8 sector tabs', () => {
    expect(sectorTabs).toHaveLength(8);
    expect(sectorTabs[0].label).toBe('S1');
    expect(sectorTabs[7].label).toBe('POD');
  });

  it('every sectorTab ID exists in rooms', () => {
    const roomIds = new Set(rooms.map(r => r.id));
    sectorTabs.forEach(tab => expect(roomIds.has(tab.id)).toBe(true));
  });

  it('every room has an accent entry', () => {
    rooms.forEach(r => {
      expect(roomAccents[r.id]).toBeDefined();
    });
  });

  it('defines sector gates mapping chapters to sector IDs', () => {
    expect(sectorGates[1]).toBe('S1');
    expect(sectorGates[3]).toBe('S2');
    expect(sectorGates[5]).toBe('S3');
    expect(sectorGates[8]).toBe('PIT');
    expect(sectorGates[10]).toBe('FINISH');
  });

  it('sector gate chapters are valid room indices', () => {
    Object.keys(sectorGates).forEach((key) => {
      const idx = Number(key);
      expect(idx).toBeGreaterThanOrEqual(0);
      expect(idx).toBeLessThanOrEqual(10);
    });
  });

  it('elevation has 5 levels (e0-e4)', () => {
    expect(Object.keys(elevation)).toHaveLength(5);
    expect(elevation.e0).toContain('--shadow-e0');
  });

  it('radius scale is ordered', () => {
    expect(radius.r0).toBe(0);
    expect(radius.r1).toBeLessThan(radius.r2);
    expect(radius.r2).toBeLessThan(radius.r3);
    expect(radius.r3).toBeLessThan(radius.r4);
    expect(radius.full).toBe(9999);
  });

  it('border widths are defined', () => {
    expect(border.default).toBe(1);
    expect(border.thick).toBe(2);
  });

  it('spacing uses 8px baseline', () => {
    expect(spacing[1]).toBe(8);
    expect(spacing[2]).toBe(16);
    expect(spacing[4]).toBe(32);
  });

  it('font families are defined', () => {
    expect(fontFamily.display).toContain('Space Grotesk');
    expect(fontFamily.body).toContain('Inter');
    expect(fontFamily.mono).toContain('Space Mono');
  });

  it('line heights are defined', () => {
    expect(lineHeight.display).toBe(0.85);
    expect(lineHeight.body).toBe(1.72);
  });

  it('letter spacing values are defined', () => {
    expect(letterSpacing.display).toBe('-0.02em');
    expect(letterSpacing.wide).toBe('0.12em');
  });

  it('z-index scale is ordered', () => {
    expect(zIndex.base).toBeLessThan(zIndex.panels);
    expect(zIndex.nav).toBeLessThan(zIndex.overlay);
    expect(zIndex.overlay).toBeLessThan(zIndex.cursor);
  });

  it('focus ring tokens are defined', () => {
    expect(focus.ringWidth).toBe(3);
    expect(focus.ringOffset).toBe(2);
  });

  it('touch minimum is 44px', () => {
    expect(touchMin).toBe(44);
  });

  it('grid has 12 columns', () => {
    expect(grid.columns).toBe(12);
  });
});
