import type { SessionContractBundle } from '@/lib/session-contracts-client';

export const iracingSession: SessionContractBundle = {
  session: {
    session_id: 'fx-iracing-1',
    session_start: '2026-04-12T18:00:00Z',
    duration_s: 3600,
    workspace_id: 'ws-demo',
    source: 'iracing',
    driver: { driver_id: 2, name: 'Sim Driver' },
    track: { track_id: 2, name: 'Spa-Francorchamps', layout: 'GP' },
    vehicle: { vehicle_class: 'gt3', model: 'BMW M4 GT3' },
    capabilities: {
      channels: ['gps', 'lat_g', 'lon_g', 'yaw_rate', 'throttle', 'brake', 'steer', 'wheel_spd'],
    },
    laps: [
      { lap_number: 1, lap_time_s: 138.21, is_valid: true, is_best: false },
      { lap_number: 2, lap_time_s: 137.44, is_valid: true, is_best: true },
    ],
    scores: { overall: 84, pace: 86, consistency: 88, execution: 82, robustness: 80 },
  },
  coaching: {
    storyline: [
      {
        weakness_key: 'throttle_trail_eau_rouge',
        state: 'Detected',
        headline: 'Throttle trail into Eau Rouge',
        detail: 'You lift ~0.3s before apex on every lap.',
      },
      {
        weakness_key: 'brake_release_les_combes',
        state: 'Detected',
        headline: 'Abrupt brake release at Les Combes',
        detail: 'Brake pressure drops from 40% to 0 in <150ms.',
      },
    ],
    global_focus: [
      {
        rank: 1,
        weakness_key: 'throttle_trail_eau_rouge',
        title: 'Carry throttle through Eau Rouge',
        severity: 'high',
        cost_ms: 320,
        corner_ids: ['er'],
      },
      {
        rank: 2,
        weakness_key: 'brake_release_les_combes',
        title: 'Smooth brake release at Les Combes',
        severity: 'medium',
        cost_ms: 140,
        corner_ids: ['lc'],
      },
    ],
    next_run: [
      {
        item_type: 'technical_focus',
        title: 'Keep throttle >=90% at Eau Rouge apex',
        body: 'Target throttle trace >=0.9 from kink to apex.',
        weakness_key: 'throttle_trail_eau_rouge',
      },
    ],
    corner_coaching: {},
    not_evaluable_corners: [],
    validation_checks: [],
  },
  optimizer: {
    depth: 'full_fidelity',
    method: 'qss_enhanced',
    confidence: 0.94,
    theoretical_lap_time_s: 136.58,
    total_time_loss_s: 0.86,
    trajectory_delta: {
      distance_m: [0, 1000, 2000, 3000, 4000, 5000, 6000, 7000],
      speed_delta_ms: [0, -0.3, -0.7, -0.2, 0.1, -0.5, -0.1, 0],
    },
    reconstructed_inputs: {
      distance_m: [0, 1000, 2000, 3000, 4000, 5000, 6000, 7000],
      throttle:   [1, 0.9, 0.1, 0.8, 1, 0.3, 0.95, 1],
      brake:      [0, 0, 0.9, 0.1, 0, 0.7, 0,    0],
      steer:      [0, 0.05, 0.3, 0.2, 0, 0.4, 0.1, 0],
    },
    corner_deltas: [
      { corner_id: 'er', phase: 'apex', root_cause: 'throttle trail', time_loss_s: 0.32 },
      { corner_id: 'lc', phase: 'brake_release', root_cause: 'brake release', time_loss_s: 0.14 },
    ],
  },
};
