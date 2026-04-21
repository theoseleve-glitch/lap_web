import { describe, it, expect } from 'vitest';
import { realLifeSession, iracingSession } from './fixtures';
import type { SessionContract } from '@/types/contracts';

describe('MSW fixtures', () => {
  it('real-life session declares gps+imu channels and no driver inputs', () => {
    const s: SessionContract = realLifeSession.session;
    expect(s.source).toBe('real_life');
    expect(s.capabilities.channels).toEqual(
      expect.arrayContaining(['gps', 'lat_g', 'lon_g']),
    );
    expect(s.capabilities.channels).not.toEqual(
      expect.arrayContaining(['throttle', 'brake', 'steer']),
    );
  });

  it('iracing session declares driver inputs + wheel speed', () => {
    const s = iracingSession.session;
    expect(s.source).toBe('iracing');
    expect(s.capabilities.channels).toEqual(
      expect.arrayContaining(['throttle', 'brake', 'steer', 'wheel_spd']),
    );
  });

  it('iracing optimizer is full_fidelity; real-life is trajectory_only', () => {
    expect(iracingSession.optimizer?.depth).toBe('full_fidelity');
    expect(realLifeSession.optimizer?.depth).toBe('trajectory_only');
  });
});
