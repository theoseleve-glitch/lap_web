'use client';

import {
  useReducer,
  useRef,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { api } from '@/lib/api-client';
import type { CornerData } from './CornersTab';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface TracePoint {
  lat: number;
  lon: number;
  speed_mps: number;
  accel_lat?: number;
  accel_long?: number;
  distance_m: number;
  brake?: number;
  throttle?: number;
}

interface ReplayLap {
  lap_number: number;
  lap_time_s: number;
  traces: TracePoint[];
}

interface ReplayData {
  corner_positions: Record<number, { s_start: number; s_end: number; s_apex?: number; direction?: string }>;
  corner_metrics: Record<
    number,
    {
      entry_speed?: number;
      apex_speed?: number;
      exit_speed?: number;
      time_loss_s?: number;
      coaching?: string;
      grip_utilization?: number;
      brake_point_m?: number;
    }
  >;
  laps: ReplayLap[];
  best_lap_number: number;
  has_pedal_data: boolean;
  has_steering_data: boolean;
}

type PlaybackMode = 'review' | 'split' | 'top3';
type PlaybackSpeed = 0.25 | 0.5 | 1 | 2;

interface PlaybackState {
  mode: PlaybackMode;
  cornerIdx: number;
  lapA: number;
  lapB: number;
  frame: number;
  playing: boolean;
  speed: PlaybackSpeed;
}

type PlaybackAction =
  | { type: 'SET_MODE'; mode: PlaybackMode }
  | { type: 'SET_CORNER'; idx: number }
  | { type: 'PREV_CORNER'; total: number }
  | { type: 'NEXT_CORNER'; total: number }
  | { type: 'SET_LAP_A'; lap: number }
  | { type: 'SET_LAP_B'; lap: number }
  | { type: 'SET_FRAME'; frame: number }
  | { type: 'TOGGLE_PLAY' }
  | { type: 'SET_SPEED'; speed: PlaybackSpeed }
  | { type: 'TICK' };

const SPEEDS: PlaybackSpeed[] = [0.25, 0.5, 1, 2];

function playbackReducer(state: PlaybackState, action: PlaybackAction): PlaybackState {
  switch (action.type) {
    case 'SET_MODE':
      return { ...state, mode: action.mode, frame: 0, playing: false };
    case 'SET_CORNER':
      return { ...state, cornerIdx: action.idx, frame: 0, playing: false };
    case 'PREV_CORNER': {
      const idx = (state.cornerIdx - 1 + action.total) % action.total;
      return { ...state, cornerIdx: idx, frame: 0, playing: false };
    }
    case 'NEXT_CORNER': {
      const idx = (state.cornerIdx + 1) % action.total;
      return { ...state, cornerIdx: idx, frame: 0, playing: false };
    }
    case 'SET_LAP_A':
      return { ...state, lapA: action.lap, frame: 0 };
    case 'SET_LAP_B':
      return { ...state, lapB: action.lap, frame: 0 };
    case 'SET_FRAME':
      return { ...state, frame: action.frame };
    case 'TOGGLE_PLAY':
      return { ...state, playing: !state.playing };
    case 'SET_SPEED':
      return { ...state, speed: action.speed };
    case 'TICK':
      return { ...state, frame: state.frame + 1 };
    default:
      return state;
  }
}

/* ------------------------------------------------------------------ */
/*  Canvas: Cockpit Gauge (rebuilt — larger, more detail)              */
/* ------------------------------------------------------------------ */

function drawCockpit(
  canvas: HTMLCanvasElement,
  speedKmh: number,
  gLat: number,
  gLon: number,
  hasAccel: boolean,
  brake: number,
  throttle: number,
  hasPedalData: boolean,
) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;

  // Background
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, W, H);

  // === SPEEDOMETER ===
  const cx = W * 0.35;
  const cy = H * 0.45;
  const R = Math.min(W * 0.28, H * 0.38) - 8;

  const startAngle = Math.PI * 0.75;
  const endAngle = Math.PI * 2.25;
  const maxSpeed = 200;
  const speedFrac = Math.min(speedKmh / maxSpeed, 1);
  const sweepAngle = startAngle + (endAngle - startAngle) * speedFrac;

  // Track arc
  ctx.beginPath();
  ctx.arc(cx, cy, R, startAngle, endAngle);
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.lineWidth = 6;
  ctx.lineCap = 'round';
  ctx.stroke();

  // Tick marks
  for (let spd = 0; spd <= maxSpeed; spd += 20) {
    const frac = spd / maxSpeed;
    const angle = startAngle + frac * (endAngle - startAngle);
    const isMajor = spd % 40 === 0;
    const innerR = isMajor ? R - 12 : R - 6;
    ctx.beginPath();
    ctx.moveTo(cx + innerR * Math.cos(angle), cy + innerR * Math.sin(angle));
    ctx.lineTo(cx + R * Math.cos(angle), cy + R * Math.sin(angle));
    ctx.strokeStyle = isMajor ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.1)';
    ctx.lineWidth = isMajor ? 1.5 : 0.5;
    ctx.lineCap = 'butt';
    ctx.stroke();

    if (isMajor && R > 40) {
      ctx.fillStyle = 'rgba(138,143,152,0.5)';
      ctx.font = `${Math.max(8, R * 0.12)}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const labelR = innerR - 10;
      ctx.fillText(`${spd}`, cx + labelR * Math.cos(angle), cy + labelR * Math.sin(angle));
    }
  }

  // Value arc (speed color gradient: green → yellow → red)
  const speedColor = speedKmh < 80 ? '#4ade80' : speedKmh < 140 ? '#c3a54b' : '#ef4444';
  ctx.beginPath();
  ctx.arc(cx, cy, R, startAngle, sweepAngle);
  ctx.strokeStyle = speedColor;
  ctx.lineWidth = 6;
  ctx.lineCap = 'round';
  ctx.stroke();

  // Speed text
  ctx.fillStyle = '#F3F0E8';
  ctx.font = `bold ${Math.max(20, R * 0.4)}px system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(Math.round(speedKmh).toString(), cx, cy - 4);

  ctx.font = `${Math.max(9, R * 0.1)}px system-ui, sans-serif`;
  ctx.fillStyle = 'rgba(138,143,152,0.7)';
  ctx.fillText('km/h', cx, cy + R * 0.22);

  // === G-FORCE DIAMOND ===
  if (hasAccel) {
    const gR = Math.min(W * 0.18, H * 0.25);
    const gx = W * 0.75;
    const gy = H * 0.4;

    // Diamond outline
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(gx, gy - gR);
    ctx.lineTo(gx + gR, gy);
    ctx.lineTo(gx, gy + gR);
    ctx.lineTo(gx - gR, gy);
    ctx.closePath();
    ctx.stroke();

    // Inner diamond (half)
    ctx.beginPath();
    ctx.moveTo(gx, gy - gR * 0.5);
    ctx.lineTo(gx + gR * 0.5, gy);
    ctx.lineTo(gx, gy + gR * 0.5);
    ctx.lineTo(gx - gR * 0.5, gy);
    ctx.closePath();
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.stroke();

    // Crosshairs
    ctx.beginPath();
    ctx.moveTo(gx - gR, gy);
    ctx.lineTo(gx + gR, gy);
    ctx.moveTo(gx, gy - gR);
    ctx.lineTo(gx, gy + gR);
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 0.5;
    ctx.stroke();

    // G-force dot
    const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
    const dotX = gx + clamp(gLat / 2, -1, 1) * gR;
    const dotY = gy - clamp(gLon / 2, -1, 1) * gR;

    // Glow
    const gGlow = ctx.createRadialGradient(dotX, dotY, 0, dotX, dotY, 10);
    gGlow.addColorStop(0, '#c3a54b55');
    gGlow.addColorStop(1, '#c3a54b00');
    ctx.fillStyle = gGlow;
    ctx.beginPath();
    ctx.arc(dotX, dotY, 10, 0, Math.PI * 2);
    ctx.fill();

    ctx.beginPath();
    ctx.arc(dotX, dotY, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#c3a54b';
    ctx.fill();

    // Labels
    ctx.fillStyle = 'rgba(138,143,152,0.5)';
    ctx.font = `${Math.max(8, gR * 0.14)}px system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.fillText('G-Force', gx, gy - gR - 6);
    ctx.fillText(`${(gLat ?? 0).toFixed(2)}G lat`, gx, gy + gR + 14);
    ctx.fillText(`${(gLon ?? 0).toFixed(2)}G lon`, gx, gy + gR + 26);
  }

  // === PEDAL BARS ===
  if (hasPedalData) {
    const barY = H * 0.82;
    const barH = Math.max(8, H * 0.05);
    const barX = W * 0.06;
    const barW = W * 0.88;

    // Throttle
    ctx.fillStyle = 'rgba(138,143,152,0.06)';
    ctx.fillRect(barX, barY - barH - 4, barW, barH);
    if (throttle > 0.01) {
      ctx.fillStyle = '#4ade8080';
      ctx.fillRect(barX, barY - barH - 4, barW * Math.min(throttle, 1), barH);
    }
    ctx.fillStyle = 'rgba(138,143,152,0.4)';
    ctx.font = '8px system-ui';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText('THR', barX, barY - barH - 4 - 6);

    // Brake
    ctx.fillStyle = 'rgba(138,143,152,0.06)';
    ctx.fillRect(barX, barY + 2, barW, barH);
    if (brake > 0.01) {
      ctx.fillStyle = '#ef444480';
      ctx.fillRect(barX, barY + 2, barW * Math.min(brake, 1), barH);
    }
    ctx.fillStyle = 'rgba(138,143,152,0.4)';
    ctx.fillText('BRK', barX, barY + barH + 8);
  }
}

/* ------------------------------------------------------------------ */
/*  Canvas: GPS Map (rebuilt — speed-colored trace)                    */
/* ------------------------------------------------------------------ */

function drawGpsMap(
  canvas: HTMLCanvasElement,
  traces: TracePoint[],
  frame: number,
  cornerStart: number | undefined,
  cornerEnd: number | undefined,
  cornerDir: string | undefined,
) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx || traces.length === 0) return;
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const pad = 24;

  // Background
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, W, H);

  // Map projection
  const lats = traces.map((t) => t.lat);
  const lons = traces.map((t) => t.lon);
  let latMin = Infinity, latMax = -Infinity, lonMin = Infinity, lonMax = -Infinity;
  for (let i = 0; i < lats.length; i++) {
    if (lats[i] < latMin) latMin = lats[i];
    if (lats[i] > latMax) latMax = lats[i];
    if (lons[i] < lonMin) lonMin = lons[i];
    if (lons[i] > lonMax) lonMax = lons[i];
  }
  const latRange = latMax - latMin || 0.0001;
  const lonRange = lonMax - lonMin || 0.0001;
  const scaleX = (W - 2 * pad) / lonRange;
  const scaleY = (H - 2 * pad) / latRange;
  const scale = Math.min(scaleX, scaleY);
  const offsetX = pad + ((W - 2 * pad) - lonRange * scale) / 2;
  const offsetY = pad + ((H - 2 * pad) - latRange * scale) / 2;

  const toX = (lon: number) => offsetX + (lon - lonMin) * scale;
  const toY = (lat: number) => H - offsetY - (lat - latMin) * scale;

  // Full trace in dim white
  ctx.beginPath();
  traces.forEach((t, i) => {
    const x = toX(t.lon);
    const y = toY(t.lat);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = 'rgba(255,255,255,0.1)';
  ctx.lineWidth = 2;
  ctx.stroke();

  // Corner zone highlight
  if (cornerStart != null && cornerEnd != null) {
    const cornerColor = cornerDir === 'L' ? 'rgba(96,165,250,0.5)' : cornerDir === 'R' ? 'rgba(251,146,60,0.5)' : 'rgba(239,68,68,0.5)';
    ctx.beginPath();
    let started = false;
    traces.forEach((t) => {
      if (t.distance_m >= cornerStart && t.distance_m <= cornerEnd) {
        const x = toX(t.lon);
        const y = toY(t.lat);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
    });
    ctx.strokeStyle = cornerColor;
    ctx.lineWidth = 6;
    ctx.stroke();
  }

  // Speed-colored traveled path
  const frameIdx = Math.min(frame, traces.length - 1);
  let maxSpd = 1;
  for (let i = 0; i < traces.length; i++) if (traces[i].speed_mps > maxSpd) maxSpd = traces[i].speed_mps;
  for (let i = 1; i <= frameIdx; i++) {
    const spd = traces[i].speed_mps;
    const frac = spd / maxSpd;
    // Green → Yellow → Red
    const r = Math.round(frac < 0.5 ? frac * 2 * 255 : 255);
    const g = Math.round(frac < 0.5 ? 255 : (1 - (frac - 0.5) * 2) * 255);
    ctx.beginPath();
    ctx.moveTo(toX(traces[i - 1].lon), toY(traces[i - 1].lat));
    ctx.lineTo(toX(traces[i].lon), toY(traces[i].lat));
    ctx.strokeStyle = `rgb(${r},${g},50)`;
    ctx.lineWidth = 3;
    ctx.stroke();
  }

  // Current position dot
  const cur = traces[frameIdx];
  if (cur) {
    const px = toX(cur.lon);
    const py = toY(cur.lat);

    // Glow
    const glow = ctx.createRadialGradient(px, py, 0, px, py, 14);
    glow.addColorStop(0, 'rgba(255,255,255,0.3)');
    glow.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(px, py, 14, 0, Math.PI * 2);
    ctx.fill();

    ctx.beginPath();
    ctx.arc(px, py, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#FFFFFF';
    ctx.fill();
    ctx.strokeStyle = '#c3a54b';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // Corner label in top-left
  if (cornerStart != null) {
    ctx.fillStyle = 'rgba(138,143,152,0.4)';
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('Track Map', 8, 8);
  }
}

/* ------------------------------------------------------------------ */
/*  Metrics Panel (HTML, not canvas — full data display)              */
/* ------------------------------------------------------------------ */

function MetricsPanel({
  corner,
  cornerMetrics,
  speedKmh,
  gLat,
  gLon,
}: {
  corner: CornerData | null;
  cornerMetrics: ReplayData['corner_metrics'][number] | undefined;
  speedKmh: number;
  gLat: number;
  gLon: number;
}) {
  function fmtSpd(mps: number | undefined | null): string {
    if (mps == null) return '--';
    return `${(mps * 3.6).toFixed(1)}`;
  }

  const lossMs = cornerMetrics?.time_loss_s != null ? Math.round(cornerMetrics.time_loss_s * 1000) : null;
  const lossColor = lossMs == null ? 'text-steel' : lossMs < 50 ? 'text-acid-green' : lossMs < 150 ? 'text-yellow-400' : 'text-safety-red';

  return (
    <div className="bg-concrete rounded-lg border border-steel/10 p-4 space-y-4">
      {/* Live telemetry */}
      <div>
        <h4 className="text-[10px] font-telemetry uppercase tracking-wider text-steel/50 mb-2">Live</h4>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <p className="text-[9px] text-steel/60 font-telemetry">Speed</p>
            <p className="text-lg text-chalk font-mono">{Math.round(speedKmh)}</p>
            <p className="text-[8px] text-steel/50 font-telemetry">km/h</p>
          </div>
          <div>
            <p className="text-[9px] text-steel/60 font-telemetry">Lat G</p>
            <p className="text-lg text-chalk font-mono">{gLat.toFixed(2)}</p>
          </div>
          <div>
            <p className="text-[9px] text-steel/60 font-telemetry">Lon G</p>
            <p className="text-lg text-chalk font-mono">{gLon.toFixed(2)}</p>
          </div>
        </div>
      </div>

      {/* Corner metrics */}
      {corner && (
        <div>
          <h4 className="text-[10px] font-telemetry uppercase tracking-wider text-steel/50 mb-2">
            C{corner.corner_id} {corner.direction === 'L' ? '\u21B0 Left' : corner.direction === 'R' ? '\u21B1 Right' : ''}
          </h4>

          {/* Speed comparison */}
          <div className="space-y-2 mb-3">
            {([
              { label: 'Entry', actual: cornerMetrics?.entry_speed, theory: corner.entry_speed_theory },
              { label: 'Apex', actual: cornerMetrics?.apex_speed, theory: corner.apex_speed_theory },
              { label: 'Exit', actual: cornerMetrics?.exit_speed, theory: corner.exit_speed_theory },
            ] as const).map(({ label, actual, theory }) => (
              <div key={label} className="flex items-center justify-between">
                <span className="text-[9px] font-telemetry text-steel/60 uppercase w-10">{label}</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-mono text-chalk">{fmtSpd(actual)}</span>
                  <span className="text-[9px] text-steel/50">/</span>
                  <span className="text-xs font-mono text-steel/50">{fmtSpd(theory)}</span>
                  <span className="text-[8px] text-steel/50 font-telemetry">km/h</span>
                </div>
              </div>
            ))}
          </div>

          {/* Grip */}
          {corner.grip_utilisation_pct != null && (
            <div className="flex items-center justify-between mb-2">
              <span className="text-[9px] font-telemetry text-steel/60 uppercase">Grip</span>
              <span className={`text-xs font-mono ${
                corner.grip_utilisation_pct >= 85 ? 'text-acid-green' :
                corner.grip_utilisation_pct >= 70 ? 'text-yellow-400' : 'text-safety-red'
              }`}>
                {corner.grip_utilisation_pct.toFixed(0)}%
              </span>
            </div>
          )}

          {/* Time loss */}
          {lossMs != null && (
            <div className="flex items-center justify-between mb-3">
              <span className="text-[9px] font-telemetry text-steel/60 uppercase">Time Loss</span>
              <span className={`text-sm font-mono ${lossColor}`}>+{lossMs}ms</span>
            </div>
          )}

          {/* Coaching */}
          {(cornerMetrics?.coaching || corner.coaching_hint) && (
            <div className="rounded bg-acid-green/5 border border-acid-green/20 px-3 py-2">
              <p className="text-[10px] font-telemetry text-acid-green/60 uppercase mb-0.5">Coaching</p>
              <p className="text-xs text-acid-green/90 font-body leading-relaxed">
                {cornerMetrics?.coaching || corner.coaching_hint}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

interface CornerReplayProps {
  sessionId: string;
  corners: CornerData[];
}

export function CornerReplay({ sessionId, corners }: CornerReplayProps) {
  const [data, setData] = useState<ReplayData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const initialState: PlaybackState = {
    mode: 'review',
    cornerIdx: 0,
    lapA: 0,
    lapB: 0,
    frame: 0,
    playing: false,
    speed: 1,
  };

  const [state, dispatch] = useReducer(playbackReducer, initialState);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cockpitRef = useRef<HTMLCanvasElement>(null);
  const mapRef = useRef<HTMLCanvasElement>(null);

  // Fetch data
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<ReplayData>(`/sessions/${sessionId}/corner-replay-data`)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          if (res.laps.length > 0) {
            dispatch({ type: 'SET_LAP_A', lap: res.best_lap_number });
          }
        }
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error)?.message ?? 'Failed to load replay data');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Current corner + lap traces
  const currentCorner = corners[state.cornerIdx] ?? null;
  const currentLap = data?.laps?.find((l) => l.lap_number === state.lapA) ?? null;
  const traces = currentLap?.traces ?? [];
  const totalFrames = traces.length;

  const cornerPos = currentCorner
    ? data?.corner_positions?.[currentCorner.corner_id]
    : undefined;

  const cornerMetrics = currentCorner
    ? data?.corner_metrics?.[currentCorner.corner_id]
    : undefined;

  // Build cockpit frame values
  const currentTrace = traces[Math.min(state.frame, totalFrames - 1)] ?? null;
  const speedKmh = currentTrace ? currentTrace.speed_mps * 3.6 : 0;
  const gLat = currentTrace?.accel_lat ?? 0;
  const gLon = currentTrace?.accel_long ?? 0;
  const brake = currentTrace?.brake ?? 0;
  const throttle = currentTrace?.throttle ?? 0;
  const hasAccel =
    traces.some((t) => t.accel_lat != null) || (data?.has_pedal_data ?? false);

  // Draw cockpit
  const renderCockpit = useCallback(() => {
    if (cockpitRef.current) {
      drawCockpit(
        cockpitRef.current,
        speedKmh,
        gLat,
        gLon,
        hasAccel,
        brake,
        throttle,
        data?.has_pedal_data ?? false,
      );
    }
  }, [speedKmh, gLat, gLon, hasAccel, brake, throttle, data?.has_pedal_data]);

  useEffect(() => { renderCockpit(); }, [renderCockpit]);
  useEffect(() => {
    const c = cockpitRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => renderCockpit());
    ro.observe(c);
    return () => ro.disconnect();
  }, [renderCockpit]);

  // Draw GPS map
  const renderMap = useCallback(() => {
    if (mapRef.current) {
      drawGpsMap(
        mapRef.current,
        traces,
        state.frame,
        cornerPos?.s_start,
        cornerPos?.s_end,
        cornerPos?.direction,
      );
    }
  }, [traces, state.frame, cornerPos]);

  useEffect(() => { renderMap(); }, [renderMap]);
  useEffect(() => {
    const c = mapRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => renderMap());
    ro.observe(c);
    return () => ro.disconnect();
  }, [renderMap]);

  // Animation interval
  const tick = useCallback(() => {
    dispatch({ type: 'TICK' });
  }, []);

  useEffect(() => {
    if (state.playing && totalFrames > 0) {
      const ms = Math.round((1000 / 30) / state.speed);
      intervalRef.current = setInterval(tick, ms);
    }
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [state.playing, state.speed, totalFrames, tick]);

  // Stop at end
  useEffect(() => {
    if (state.frame >= totalFrames - 1 && state.playing && totalFrames > 0) {
      dispatch({ type: 'TOGGLE_PLAY' });
    }
  }, [state.frame, totalFrames, state.playing]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;

      switch (e.key) {
        case ' ':
          e.preventDefault();
          dispatch({ type: 'TOGGLE_PLAY' });
          break;
        case 'ArrowLeft':
          e.preventDefault();
          dispatch({ type: 'SET_FRAME', frame: Math.max(0, state.frame - 1) });
          break;
        case 'ArrowRight':
          e.preventDefault();
          dispatch({
            type: 'SET_FRAME',
            frame: Math.min(totalFrames - 1, state.frame + 1),
          });
          break;
        case '[':
          dispatch({ type: 'PREV_CORNER', total: corners.length || 1 });
          break;
        case ']':
          dispatch({ type: 'NEXT_CORNER', total: corners.length || 1 });
          break;
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [state.frame, totalFrames, corners.length]);

  // Lap options
  const lapOptions = useMemo(
    () => data?.laps?.map((l) => l.lap_number) ?? [],
    [data],
  );

  /* ---- Render ---- */

  if (loading) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-6 animate-pulse">
        <div className="h-4 bg-asphalt rounded w-40 mb-4" />
        <div className="h-[420px] bg-asphalt rounded" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-6 text-center">
        <p className="text-steel font-telemetry text-sm mb-1">Failed to load replay data</p>
        <p className="text-steel/60 font-telemetry text-xs">{error}</p>
      </div>
    );
  }

  if (!data || data.laps.length === 0 || corners.length === 0) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-6 text-center">
        <p className="text-steel font-telemetry text-sm">No replay data available.</p>
        <p className="text-steel/60 font-telemetry text-xs mt-1">
          Replay requires GPS trace data with at least one lap.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Controls bar */}
      <div className="bg-concrete rounded-lg border border-steel/10 overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 px-4 py-2.5">
          {/* Mode tabs */}
          <div className="flex items-center bg-asphalt rounded overflow-hidden">
            {(['review', 'split', 'top3'] as PlaybackMode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => dispatch({ type: 'SET_MODE', mode: m })}
                className={`px-3 py-1.5 text-[10px] font-telemetry uppercase tracking-wide transition-colors ${
                  state.mode === m
                    ? 'bg-acid-green/20 text-acid-green'
                    : 'text-steel hover:text-chalk'
                }`}
              >
                {m === 'top3' ? 'Top 3' : m}
              </button>
            ))}
          </div>

          {/* Corner pills */}
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => dispatch({ type: 'PREV_CORNER', total: corners.length })}
              className="text-steel hover:text-chalk text-sm px-1 font-mono"
              aria-label="Previous corner"
            >
              &lsaquo;
            </button>
            <div className="flex items-center gap-0.5 overflow-x-auto max-w-[240px]">
              {corners.map((c, i) => {
                const dirColor = c.direction === 'L' ? 'text-blue-400' : c.direction === 'R' ? 'text-orange-400' : 'text-steel';
                return (
                  <button
                    key={c.corner_id}
                    type="button"
                    onClick={() => dispatch({ type: 'SET_CORNER', idx: i })}
                    className={`px-2 py-0.5 text-[10px] font-mono rounded whitespace-nowrap transition-colors ${
                      state.cornerIdx === i
                        ? `bg-acid-green/20 text-acid-green`
                        : `${dirColor} hover:text-chalk`
                    }`}
                  >
                    C{c.corner_id}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              onClick={() => dispatch({ type: 'NEXT_CORNER', total: corners.length })}
              className="text-steel hover:text-chalk text-sm px-1 font-mono"
              aria-label="Next corner"
            >
              &rsaquo;
            </button>
          </div>

          {/* Play / Pause */}
          <button
            type="button"
            onClick={() => dispatch({ type: 'TOGGLE_PLAY' })}
            className="px-3 py-1.5 text-[10px] font-telemetry rounded bg-asphalt text-chalk hover:bg-steel/20 transition-colors uppercase"
          >
            {state.playing ? 'Pause' : 'Play'}
          </button>

          {/* Speed selector */}
          <div className="flex items-center gap-0.5">
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => dispatch({ type: 'SET_SPEED', speed: s })}
                className={`px-1.5 py-0.5 text-[9px] font-mono rounded transition-colors ${
                  state.speed === s
                    ? 'bg-acid-green/20 text-acid-green'
                    : 'text-steel hover:text-chalk'
                }`}
              >
                {s}x
              </button>
            ))}
          </div>

          {/* Lap selector */}
          {lapOptions.length > 1 && (
            <select
              value={state.lapA}
              onChange={(e) => dispatch({ type: 'SET_LAP_A', lap: Number(e.target.value) })}
              className="bg-asphalt border border-steel/20 rounded text-[10px] text-chalk font-telemetry px-2 py-1"
            >
              {lapOptions.map((ln) => (
                <option key={ln} value={ln}>
                  Lap {ln}{ln === data.best_lap_number ? ' (best)' : ''}
                </option>
              ))}
            </select>
          )}

          {/* Scrubber */}
          <input
            type="range"
            min={0}
            max={Math.max(totalFrames - 1, 0)}
            value={state.frame}
            onChange={(e) => dispatch({ type: 'SET_FRAME', frame: Number(e.target.value) })}
            className="flex-1 min-w-[80px] h-1 accent-acid-green cursor-pointer"
          />
        </div>
      </div>

      {/* Main display: Map + Cockpit + Metrics */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_240px_280px] gap-3" style={{ minHeight: '420px' }}>
        {/* Center: GPS map (largest panel) */}
        <div className="rounded-lg border border-steel/10 overflow-hidden bg-concrete">
          <canvas
            ref={mapRef}
            className="w-full h-full"
            style={{ display: 'block', minHeight: '420px' }}
          />
        </div>

        {/* Middle: Cockpit gauge */}
        <div className="rounded-lg border border-steel/10 overflow-hidden bg-concrete">
          <canvas
            ref={cockpitRef}
            className="w-full h-full"
            style={{ display: 'block', minHeight: '420px' }}
          />
        </div>

        {/* Right: Metrics panel */}
        <MetricsPanel
          corner={currentCorner}
          cornerMetrics={cornerMetrics}
          speedKmh={speedKmh}
          gLat={gLat}
          gLon={gLon}
        />
      </div>

      {/* Keyboard hints */}
      <div className="flex items-center gap-4 px-2 text-[9px] text-steel/50 font-telemetry">
        <span>Space: Play/Pause</span>
        <span>Arrows: Frame step</span>
        <span>[ ]: Prev/Next corner</span>
      </div>
    </div>
  );
}
