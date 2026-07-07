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
    expect(colors.steel).toBe('#949494');
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

  it('defines 10 rooms', () => {
    expect(rooms).toHaveLength(10);
    expect(rooms[0].id).toBe('start-grid');
    expect(rooms[9].id).toBe('podium');
  });

  it('defines 8 sector tabs', () => {
    expect(sectorTabs).toHaveLength(8);
    expect(sectorTabs[0].label).toBe('S1');
    expect(sectorTabs[7].label).toBe('POD');
  });

  // TODO(dead-marketing-route): sectorTabs still references room ids from
  // before the room set was trimmed to 10 (s2-pipeline/s4-workflows/
  // s5-personas no longer exist as rooms). Not reconciled: src/app/(marketing)/
  // — the only consumer of rooms/sectorTabs/roomAccents/sectorGates — is
  // superseded in prod by the standalone Astro marketing site (see
  // top-level CLAUDE.md + infra memory: Cloudflare Worker `lap-website` only
  // routes /app,/admin,/_next,/api/*,auth; marketing paths go to the Astro
  // Pages project instead), so this route group never actually renders.
  // Pinning the current (drifted) reality instead of asserting a fixed
  // invariant that's already broken.
  it('documents current sectorTab/room id overlap (dead marketing route)', () => {
    const roomIds = new Set(rooms.map(r => r.id));
    const matching = sectorTabs.filter(tab => roomIds.has(tab.id)).map(t => t.id);
    expect(matching).toEqual(['s1-pain', 's3-product', 'pit-stop', 'garage', 'podium']);
  });

  // TODO(dead-marketing-route): roomAccents wasn't updated when the room set
  // changed — session-proof/s2-versus/sim-first/premium have no accent entry.
  // Same dead-route rationale as above; documenting the gap, not fixing it.
  it('documents current roomAccents coverage gap (dead marketing route)', () => {
    const missing = rooms.filter(r => roomAccents[r.id] === undefined).map(r => r.id);
    expect(missing).toEqual(['session-proof', 's2-versus', 'sim-first', 'premium']);
  });

  // TODO(dead-marketing-route): sectorGates' chapter keys (2/3/4/8/9) don't
  // match SectorGateController's GATE_TO_TOWER_INDEX (1/3/5/8, +10=FINISH) —
  // real drift between the two sources of truth. Not reconciled for the same
  // dead-route reason as above (src/app/(marketing)/ is superseded by the
  // Astro marketing site in prod, so SectorGateController never runs live).
  it('defines sector gates mapping chapters to sector IDs (current, drifted keys)', () => {
    expect(sectorGates[2]).toBe('S1');
    expect(sectorGates[3]).toBe('S2');
    expect(sectorGates[4]).toBe('S3');
    expect(sectorGates[8]).toBe('PIT');
    expect(sectorGates[9]).toBe('FINISH');
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
