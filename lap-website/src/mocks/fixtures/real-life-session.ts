import type { SessionContractBundle } from '@/lib/session-contracts-client';

export const realLifeSession: SessionContractBundle = {
  session: {
    session_id: 'fx-real-life-1',
    session_start: '2026-04-10T14:00:00Z',
    duration_s: 1820,
    workspace_id: 'ws-demo',
    source: 'real_life',
    driver: { driver_id: 1, name: 'Demo Driver' },
    track: { track_id: 1, name: 'Franciacorta', layout: 'GP' },
    vehicle: { vehicle_class: 'kart', model: 'Rotax Senior' },
    capabilities: { channels: ['gps', 'lat_g', 'lon_g', 'yaw_rate'] },
    laps: [
      { lap_number: 1, lap_time_s: 52.45, is_valid: true, is_best: false },
      { lap_number: 2, lap_time_s: 51.92, is_valid: true, is_best: true },
      { lap_number: 3, lap_time_s: 52.18, is_valid: true, is_best: false },
    ],
    scores: { overall: 78, pace: 80, consistency: 82, execution: 74, robustness: 76 },
  },
  coaching: {
    storyline: [
      {
        weakness_key: 'late_brake_t3',
        state: 'Detected',
        headline: 'Late braking at Turn 3',
        detail: 'You brake ~8m later than optimal on laps 2 and 3.',
      },
    ],
    global_focus: [
      {
        rank: 1,
        weakness_key: 'late_brake_t3',
        title: 'Brake earlier into T3',
        severity: 'medium',
        cost_ms: 180,
        corner_ids: ['t3'],
      },
    ],
    next_run: [
      {
        item_type: 'technical_focus',
        title: 'Move T3 brake marker',
        body: 'Reference the 50m board.',
        weakness_key: 'late_brake_t3',
      },
    ],
    corner_coaching: {},
    not_evaluable_corners: [],
    validation_checks: [],
  },
  optimizer: {
    depth: 'trajectory_only',
    method: 'trajectory',
    confidence: 0.72,
    theoretical_lap_time_s: 51.35,
    total_time_loss_s: 0.57,
    trajectory_delta: {
      distance_m: [0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000],
      speed_delta_ms: [0, -0.2, -0.4, -0.8, -0.5, -0.3, -0.1, 0.1, 0.3, 0.2, 0],
    },
  },
};
