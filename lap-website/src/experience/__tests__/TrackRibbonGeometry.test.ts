import { describe, it, expect } from 'vitest';
import { buildRibbonPoints, buildRibbonCurve, extrudeRibbonGeometry, TOTAL_LENGTH } from '../renderer/TrackRibbonGeometry';
import { TRACK_PATH } from '../narrative/TrackPath';

describe('buildRibbonPoints', () => {
  it('generates points from TRACK_PATH', () => {
    const points = buildRibbonPoints(TRACK_PATH);
    expect(points.length).toBeGreaterThan(0);
  });

  it('starts near origin', () => {
    const points = buildRibbonPoints(TRACK_PATH);
    expect(Math.abs(points[0].x)).toBeLessThan(1);
    expect(Math.abs(points[0].z)).toBeLessThan(1);
  });

  it('generates at least one point per chapter', () => {
    const points = buildRibbonPoints(TRACK_PATH);
    expect(points.length).toBeGreaterThanOrEqual(TRACK_PATH.length);
  });

  it('TOTAL_LENGTH is positive', () => {
    expect(TOTAL_LENGTH).toBeGreaterThan(0);
  });

  it('generates consistent output for same input', () => {
    const a = buildRibbonPoints(TRACK_PATH);
    const b = buildRibbonPoints(TRACK_PATH);
    expect(a.length).toBe(b.length);
    expect(a[0].x).toBe(b[0].x);
  });

  it('all points have y=0 (flat ribbon)', () => {
    const points = buildRibbonPoints(TRACK_PATH);
    for (const p of points) {
      expect(p.y).toBe(0);
    }
  });
});

describe('buildRibbonCurve', () => {
  it('returns a CatmullRomCurve3', () => {
    const curve = buildRibbonCurve(TRACK_PATH);
    expect(curve).toBeDefined();
    expect(curve.getPointAt(0)).toBeDefined();
    expect(curve.getPointAt(1)).toBeDefined();
  });

  it('curve start and end are different points', () => {
    const curve = buildRibbonCurve(TRACK_PATH);
    const start = curve.getPointAt(0);
    const end = curve.getPointAt(1);
    const dist = start.distanceTo(end);
    expect(dist).toBeGreaterThan(0);
  });
});

describe('extrudeRibbonGeometry', () => {
  it('returns a BufferGeometry with positions and UVs', () => {
    const curve = buildRibbonCurve(TRACK_PATH);
    const geo = extrudeRibbonGeometry(curve, 8, 50);
    expect(geo.attributes.position).toBeDefined();
    expect(geo.attributes.uv).toBeDefined();
    expect(geo.index).not.toBeNull();
    geo.dispose();
  });

  it('vertex count is (segments+1) * 2', () => {
    const curve = buildRibbonCurve(TRACK_PATH);
    const segments = 50;
    const geo = extrudeRibbonGeometry(curve, 8, segments);
    expect(geo.attributes.position.count).toBe((segments + 1) * 2);
    geo.dispose();
  });
});
