/* Driving Analyzer — TypeScript interfaces */

/* ── Corner replay API types (self-contained) ──────────── */

export interface CornerReplayTrace {
  lat: number[];
  lon: number[];
  speed_mps: number[];
  dist_m?: number[];
  accel_lat?: number[];
  accel_lon?: number[];
  brake?: number[];
  throttle?: number[];
  steering?: number[];
}

export interface CornerReplayLap {
  lap_number: number;
  lap_time_s: number | null;
}

export interface CornerReplayCorner {
  corner_id: string;
  label: string;
  dist_m: number;
}

export interface CornerReplayData {
  traces: Record<string, CornerReplayTrace>;
  laps: CornerReplayLap[];
  corners: CornerReplayCorner[];
  has_pedal_data?: boolean;
  has_steering_data?: boolean;
}

/* ── Playback speeds ─────────────────────────────────────── */

export type PlaybackSpeed = 0.25 | 0.5 | 1 | 2 | 4;

export const PLAYBACK_SPEEDS: PlaybackSpeed[] = [0.25, 0.5, 1, 2, 4];

/* ── Section definitions (track segments) ─────────────────── */

export interface SectionDef {
  id: string;          // 'full' | 'S1' | 'T1' | 'S2' | ...
  label: string;       // Display label
  startDist: number;   // meters from lap start
  endDist: number;     // meters from lap start
  type: 'full' | 'straight' | 'corner';
  cornerIndex?: number; // index into corners array, if type === 'corner'
}

/* ── Chart configuration ─────────────────────────────────── */

export type ChartType = 'speed' | 'g-lat' | 'brake-throttle' | 'steering';

export interface ChartConfig {
  type: ChartType;
  label: string;
  unit: string;
  color: string;
  /** If true, chart draws two series (brake + throttle) */
  dual?: boolean;
}

export const DEFAULT_CHARTS: ChartConfig[] = [
  { type: 'speed', label: 'Speed', unit: 'km/h', color: '#F0EDE5' },
  { type: 'g-lat', label: 'Lateral G', unit: 'G', color: '#C9A84C' },
  { type: 'brake-throttle', label: 'Brake / Throttle', unit: '%', color: '#FF2A2A', dual: true },
  { type: 'steering', label: 'Steering', unit: 'deg', color: '#949494' },
];

/* ── Reducer state ───────────────────────────────────────── */

export interface AnalyzerState {
  playing: boolean;
  currentDistance: number;       // PRIMARY CURSOR — meters from section start
  playbackSpeed: PlaybackSpeed;

  primaryLap: number;
  overlayLap: number | null;
  activeSection: string;         // 'full' | 'S1' | 'T1' | etc.

  visibleCharts: ChartType[];
}

export type AnalyzerAction =
  | { type: 'TOGGLE_PLAY' }
  | { type: 'SET_DISTANCE'; distance: number }
  | { type: 'SET_SPEED'; speed: PlaybackSpeed }
  | { type: 'SET_LAP'; lap: number }
  | { type: 'SET_OVERLAY_LAP'; lap: number | null }
  | { type: 'SET_SECTION'; section: string }
  | { type: 'TOGGLE_CHART'; chart: ChartType }
  | { type: 'RESET' };

/* ── Processed trace data for the analyzer ────────────────── */

export interface AnalyzerTrace {
  lapNumber: number;
  lat: number[];
  lon: number[];
  distance: number[];          // cumulative distance in meters
  speed: number[];             // km/h
  gLat: number[];              // lateral G
  gLon: number[];              // longitudinal G
  brake: number[];             // 0..1
  throttle: number[];          // 0..1
  steering: number[];          // degrees
  lapTime: number | null;      // seconds
}

/* ── Props for DrivingAnalyzer ───────────────────────────── */

export interface DrivingAnalyzerProps {
  sessionId: string;
  cornerFilter?: number[];     // optional: only show these corner indices
  onClose: () => void;
}
