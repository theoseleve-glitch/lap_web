import { describe, it, expect } from 'vitest';
import { colors, timing, easing, rooms, sectorTabs, roomAccents } from '@/lib/tokens';

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

  it('exports racing-purple color', () => {
    expect(colors.racingPurple).toBe('#D946EF');
  });

  it('exports narrative timing tokens', () => {
    expect(timing.sectorGate).toBe(0.4);
    expect(timing.drs).toBe(2.0);
    expect(timing.pit).toBe(0.6);
    expect(timing.finish).toBe(0.6);
  });
});
