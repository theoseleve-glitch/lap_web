import type { CornerReplayData, CornerReplayTrace } from '@/types/corner-replay';

function generateTrace(n: number, withPedals: boolean): CornerReplayTrace {
  const base: CornerReplayTrace = {
    lat: Array.from({ length: n }, (_, i) => 45.0 + i * 0.0001),
    lon: Array.from({ length: n }, (_, i) => 9.0 + i * 0.0001),
    dist_m: Array.from({ length: n }, (_, i) => i * 5),
    speed_mps: Array.from({ length: n }, (_, i) => 15 + (i % 20) * 0.5),
    accel_lat: Array.from({ length: n }, (_, i) => 0.1 * (i % 10 - 5)),
    accel_lon: Array.from({ length: n }, (_, i) => 0.05 * (i % 8 - 4)),
  };

  if (withPedals) {
    base.brake = Array.from({ length: n }, (_, i) => (i % 30 < 10 ? 0.8 : 0));
    base.throttle = Array.from({ length: n }, (_, i) => (i % 30 >= 15 ? 0.9 : 0.1));
    base.steering = Array.from({ length: n }, (_, i) => Math.sin(i / 10) * 45);
  }

  return base;
}

export const mockCornerReplayResponse: CornerReplayData = {
  session_id: 'sess-001',
  track_id: 'track-001',
  has_pedal_data: true,
  has_steering_data: true,
  corners: [
    { corner_id: '1', label: 'Turn 1', lat: 45.005, lon: 9.005, dist_m: 100 },
    { corner_id: '2', label: 'Hairpin', lat: 45.010, lon: 9.010, dist_m: 500 },
    { corner_id: '3', label: 'Chicane', lat: 45.015, lon: 9.015, dist_m: 800 },
  ],
  laps: [
    { lap_number: 1, lap_time_s: 61.0 },
    { lap_number: 2, lap_time_s: 60.5 },
  ],
  traces: {
    '1': generateTrace(200, true),
    '2': generateTrace(200, true),
  },
  replay_windows: {
    '1': [
      { lap_number: 1, start_idx: 0, end_idx: 60, estimated_duration_s: 4.5 },
      { lap_number: 2, start_idx: 0, end_idx: 60, estimated_duration_s: 4.3 },
    ],
    '2': [
      { lap_number: 1, start_idx: 80, end_idx: 140, estimated_duration_s: 5.2 },
      { lap_number: 2, start_idx: 80, end_idx: 140, estimated_duration_s: 5.0 },
    ],
    '3': [
      { lap_number: 1, start_idx: 140, end_idx: 199, estimated_duration_s: 4.8 },
      { lap_number: 2, start_idx: 140, end_idx: 199, estimated_duration_s: 4.6 },
    ],
  },
  corner_metrics: {
    '1': [
      { lap_number: 1, brake_point_m: 90, entry_speed_mps: 20, apex_speed_mps: 15, exit_speed_mps: 18, time_loss_ms: 50, coaching_hint: null },
      { lap_number: 2, brake_point_m: 92, entry_speed_mps: 21, apex_speed_mps: 16, exit_speed_mps: 19, time_loss_ms: 30, coaching_hint: 'Brake later into Turn 1' },
    ],
    '2': [
      { lap_number: 1, brake_point_m: 490, entry_speed_mps: 22, apex_speed_mps: 12, exit_speed_mps: 16, time_loss_ms: 80, coaching_hint: null },
      { lap_number: 2, brake_point_m: 492, entry_speed_mps: 23, apex_speed_mps: 13, exit_speed_mps: 17, time_loss_ms: 60, coaching_hint: 'Carry more speed through Hairpin' },
    ],
    '3': [
      { lap_number: 1, brake_point_m: 790, entry_speed_mps: 18, apex_speed_mps: 14, exit_speed_mps: 17, time_loss_ms: 40, coaching_hint: null },
      { lap_number: 2, brake_point_m: 792, entry_speed_mps: 19, apex_speed_mps: 15, exit_speed_mps: 18, time_loss_ms: 25, coaching_hint: null },
    ],
  },
};

export const mockCornerReplayNoPedals: CornerReplayData = {
  ...mockCornerReplayResponse,
  has_pedal_data: false,
  has_steering_data: false,
  traces: {
    '1': generateTrace(200, false),
    '2': generateTrace(200, false),
  },
};

export const mockKeyCorners = [
  { corner_id: 1, label: 'Turn 1', lat: 45.005, lon: 9.005, dist_m: 100 },
  { corner_id: 2, label: 'Hairpin', lat: 45.010, lon: 9.010, dist_m: 500 },
  { corner_id: 3, label: 'Chicane', lat: 45.015, lon: 9.015, dist_m: 800 },
  { corner_id: 4, label: 'Final', lat: 45.018, lon: 9.018, dist_m: 950 },
];
