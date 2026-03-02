import { describe, it, expect } from 'vitest';
import { formatLapTime, formatDate, formatDistance, mpsToKmh, mps2ToG } from '@/lib/format-utils';

describe('formatLapTime', () => {
  it('returns em dash for null', () => {
    expect(formatLapTime(null)).toBe('\u2014');
  });
  it('returns em dash for undefined', () => {
    expect(formatLapTime(undefined)).toBe('\u2014');
  });
  it('returns em dash for NaN', () => {
    expect(formatLapTime(NaN)).toBe('\u2014');
  });
  it('formats sub-60s as decimal with s suffix', () => {
    expect(formatLapTime(45.123)).toBe('45.123s');
  });
  it('formats exactly 60s as M:SS.sss', () => {
    expect(formatLapTime(60.0)).toBe('1:00.000');
  });
  it('formats over 60s as M:SS.sss', () => {
    expect(formatLapTime(62.345)).toBe('1:02.345');
  });
  it('formats over 10min as MM:SS.sss', () => {
    expect(formatLapTime(625.1)).toBe('10:25.100');
  });
});

describe('formatDate', () => {
  it('returns em dash for null', () => {
    expect(formatDate(null)).toBe('\u2014');
  });
  it('formats ISO date to en-GB short', () => {
    expect(formatDate('2026-01-15')).toBe('15 Jan 2026');
  });
  it('returns raw string for invalid date', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date');
  });
});

describe('formatDistance', () => {
  it('returns em dash for null', () => {
    expect(formatDistance(null)).toBe('\u2014');
  });
  it('rounds to integer (matches desktop)', () => {
    expect(formatDistance(1247.3)).toBe('1247');
  });
  it('rounds 0.5 up', () => {
    expect(formatDistance(999.5)).toBe('1000');
  });
});

describe('mpsToKmh', () => {
  it('returns em dash for null', () => {
    expect(mpsToKmh(null)).toBe('\u2014');
  });
  it('converts m/s to km/h with 1 decimal', () => {
    expect(mpsToKmh(10.0)).toBe('36.0');
  });
});

describe('mps2ToG', () => {
  it('returns em dash for null', () => {
    expect(mps2ToG(null)).toBe('\u2014');
  });
  it('converts m/s2 to G with 2 decimals', () => {
    expect(mps2ToG(9.81)).toBe('1.00');
  });
  it('uses absolute value for negative braking', () => {
    expect(mps2ToG(-9.81)).toBe('1.00');
  });
});
