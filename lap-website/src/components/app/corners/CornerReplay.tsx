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
}

interface ReplayLap {
  lap_number: number;
  lap_time_s: number;
  traces: TracePoint[];
}

interface ReplayData {
  corner_positions: Record<number, { s_start: number; s_end: number }>;
  corner_metrics: Record<
    number,
    {
      entry_speed?: number;
      apex_speed?: number;
      exit_speed?: number;
      time_loss_s?: number;
      coaching?: string;
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
/*  Canvas: Cockpit Gauge                                              */
/* ------------------------------------------------------------------ */

function drawCockpit(
  canvas: HTMLCanvasElement,
  speedKmh: number,
  gLat: number,
  gLon: number,
  hasAccel: boolean,
) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const cx = W / 2;
  const cy = H * 0.55;
  const R = Math.min(cx, cy) - 16;

  // Background
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, W, H);

  // Speed arc
  const startAngle = Math.PI * 0.75;
  const endAngle = Math.PI * 2.25;
  const maxSpeed = 200;
  const speedFrac = Math.min(speedKmh / maxSpeed, 1);
  const sweepAngle = startAngle + (endAngle - startAngle) * speedFrac;

  // Track arc
  ctx.beginPath();
  ctx.arc(cx, cy, R, startAngle, endAngle);
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.lineWidth = 8;
  ctx.lineCap = 'round';
  ctx.stroke();

  // Value arc
  ctx.beginPath();
  ctx.arc(cx, cy, R, startAngle, sweepAngle);
  ctx.strokeStyle = '#c3a54b';
  ctx.lineWidth = 8;
  ctx.lineCap = 'round';
  ctx.stroke();

  // Speed text
  ctx.fillStyle = '#F3F0E8';
  ctx.font = 'bold 28px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(Math.round(speedKmh).toString(), cx, cy - 6);

  ctx.font = '10px system-ui, sans-serif';
  ctx.fillStyle = 'rgba(138,143,152,0.7)';
  ctx.fillText('km/h', cx, cy + 16);

  // G-force diamond
  if (hasAccel) {
    const gR = 24;
    const gy = H - gR - 8;
    const gx = cx;

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

    // G-force dot
    const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
    const dotX = gx + clamp(gLat / 2, -1, 1) * gR;
    const dotY = gy - clamp(gLon / 2, -1, 1) * gR;
    ctx.beginPath();
    ctx.arc(dotX, dotY, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#c3a54b';
    ctx.fill();
  }
}

/* ------------------------------------------------------------------ */
/*  Canvas: GPS Map                                                    */
/* ------------------------------------------------------------------ */

function drawGpsMap(
  canvas: HTMLCanvasElement,
  traces: TracePoint[],
  frame: number,
  cornerStart: number | undefined,
  cornerEnd: number | undefined,
) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx || traces.length === 0) return;
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const pad = 20;

  // Background
  ctx.fillStyle = '#0B0C0F';
  ctx.fillRect(0, 0, W, H);

  // Map projection (simple lat/lon -> pixel)
  const lats = traces.map((t) => t.lat);
  const lons = traces.map((t) => t.lon);
  const latMin = Math.min(...lats);
  const latMax = Math.max(...lats);
  const lonMin = Math.min(...lons);
  const lonMax = Math.max(...lons);
  const latRange = latMax - latMin || 0.0001;
  const lonRange = lonMax - lonMin || 0.0001;

  const toX = (lon: number) => pad + ((lon - lonMin) / lonRange) * (W - 2 * pad);
  const toY = (lat: number) => H - pad - ((lat - latMin) / latRange) * (H - 2 * pad);

  // Draw full trace in dim white
  ctx.beginPath();
  traces.forEach((t, i) => {
    const x = toX(t.lon);
    const y = toY(t.lat);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = 'rgba(255,255,255,0.12)';
  ctx.lineWidth = 2;
  ctx.stroke();

  // Highlight corner zone
  if (cornerStart != null && cornerEnd != null) {
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
    ctx.strokeStyle = 'rgba(239,68,68,0.6)';
    ctx.lineWidth = 4;
    ctx.stroke();
  }

  // Draw traveled path in amber
  const frameIdx = Math.min(frame, traces.length - 1);
  ctx.beginPath();
  for (let i = 0; i <= frameIdx; i++) {
    const x = toX(traces[i].lon);
    const y = toY(traces[i].lat);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = '#c3a54b';
  ctx.lineWidth = 2.5;
  ctx.stroke();

  // Current position dot
  const cur = traces[frameIdx];
  if (cur) {
    ctx.beginPath();
    ctx.arc(toX(cur.lon), toY(cur.lat), 5, 0, Math.PI * 2);
    ctx.fillStyle = '#FFFFFF';
    ctx.fill();
    ctx.strokeStyle = '#c3a54b';
    ctx.lineWidth = 2;
    ctx.stroke();
  }
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
  const currentLap = data?.laps.find((l) => l.lap_number === state.lapA) ?? null;
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
  const hasAccel =
    traces.some((t) => t.accel_lat != null) || (data?.has_pedal_data ?? false);

  // Draw cockpit
  useEffect(() => {
    if (cockpitRef.current) {
      drawCockpit(cockpitRef.current, speedKmh, gLat, gLon, hasAccel);
    }
  }, [speedKmh, gLat, gLon, hasAccel]);

  // Draw GPS map
  useEffect(() => {
    if (mapRef.current) {
      drawGpsMap(
        mapRef.current,
        traces,
        state.frame,
        cornerPos?.s_start,
        cornerPos?.s_end,
      );
    }
  }, [traces, state.frame, cornerPos]);

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
    () => data?.laps.map((l) => l.lap_number) ?? [],
    [data],
  );

  /* ---- Render ---- */

  if (loading) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-6 animate-pulse">
        <div className="h-4 bg-asphalt rounded w-40 mb-4" />
        <div className="h-[380px] bg-asphalt rounded" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-6 text-center">
        <p className="text-steel font-telemetry text-sm">{error}</p>
      </div>
    );
  }

  if (!data || data.laps.length === 0 || corners.length === 0) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-6 text-center">
        <p className="text-steel font-telemetry text-sm">No replay data available.</p>
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-lg border border-steel/10 overflow-hidden">
      {/* Controls bar */}
      <div className="flex flex-wrap items-center gap-3 px-4 py-2.5 border-b border-steel/10">
        {/* Mode tabs */}
        <div className="flex items-center bg-asphalt rounded overflow-hidden">
          {(['review', 'split', 'top3'] as PlaybackMode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => dispatch({ type: 'SET_MODE', mode: m })}
              className={`px-3 py-1 text-[10px] font-telemetry uppercase tracking-wide transition-colors ${
                state.mode === m
                  ? 'bg-amber-400/20 text-amber-400'
                  : 'text-steel hover:text-chalk'
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        {/* Corner pills */}
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => dispatch({ type: 'PREV_CORNER', total: corners.length })}
            className="text-steel hover:text-chalk text-xs px-1"
            aria-label="Previous corner"
          >
            &lsaquo;
          </button>
          <div className="flex items-center gap-0.5 overflow-x-auto max-w-[200px]">
            {corners.map((c, i) => (
              <button
                key={c.corner_id}
                type="button"
                onClick={() => dispatch({ type: 'SET_CORNER', idx: i })}
                className={`px-2 py-0.5 text-[10px] font-mono rounded whitespace-nowrap transition-colors ${
                  state.cornerIdx === i
                    ? 'bg-amber-400/20 text-amber-400'
                    : 'text-steel hover:text-chalk'
                }`}
              >
                C{c.corner_id}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => dispatch({ type: 'NEXT_CORNER', total: corners.length })}
            className="text-steel hover:text-chalk text-xs px-1"
            aria-label="Next corner"
          >
            &rsaquo;
          </button>
        </div>

        {/* Play / Pause */}
        <button
          type="button"
          onClick={() => dispatch({ type: 'TOGGLE_PLAY' })}
          className="px-2 py-1 text-[10px] font-telemetry rounded bg-asphalt text-chalk hover:bg-steel/20 transition-colors"
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
                  ? 'bg-amber-400/20 text-amber-400'
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
                Lap {ln}
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
          className="flex-1 min-w-[80px] h-1 accent-amber-400 cursor-pointer"
        />
      </div>

      {/* 3-pane grid */}
      <div
        className="grid gap-0"
        style={{
          gridTemplateColumns: '180px 1fr 200px',
          height: '380px',
        }}
      >
        {/* Left: Cockpit gauge */}
        <div className="border-r border-steel/10">
          <canvas
            ref={cockpitRef}
            className="w-full h-full"
            style={{ display: 'block' }}
          />
        </div>

        {/* Center: GPS map */}
        <div>
          <canvas
            ref={mapRef}
            className="w-full h-full"
            style={{ display: 'block' }}
          />
        </div>

        {/* Right: Metrics sidebar */}
        <div className="border-l border-steel/10 p-3 overflow-y-auto">
          <h4 className="text-[10px] text-steel font-telemetry uppercase tracking-wider mb-3">
            Metrics
          </h4>

          <div className="space-y-3">
            <div>
              <p className="text-[10px] text-steel/60 font-telemetry">Speed</p>
              <p className="text-lg text-chalk font-mono">{Math.round(speedKmh)} km/h</p>
            </div>

            {cornerMetrics && (
              <>
                <div>
                  <p className="text-[10px] text-steel/60 font-telemetry">Entry</p>
                  <p className="text-sm text-chalk font-mono">
                    {cornerMetrics.entry_speed != null
                      ? `${(cornerMetrics.entry_speed * 3.6).toFixed(1)} km/h`
                      : '--'}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-steel/60 font-telemetry">Apex</p>
                  <p className="text-sm text-chalk font-mono">
                    {cornerMetrics.apex_speed != null
                      ? `${(cornerMetrics.apex_speed * 3.6).toFixed(1)} km/h`
                      : '--'}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-steel/60 font-telemetry">Exit</p>
                  <p className="text-sm text-chalk font-mono">
                    {cornerMetrics.exit_speed != null
                      ? `${(cornerMetrics.exit_speed * 3.6).toFixed(1)} km/h`
                      : '--'}
                  </p>
                </div>
                {cornerMetrics.time_loss_s != null && (
                  <div>
                    <p className="text-[10px] text-steel/60 font-telemetry">Time Loss</p>
                    <p className="text-sm text-red-400 font-mono">
                      +{Math.round(cornerMetrics.time_loss_s * 1000)} ms
                    </p>
                  </div>
                )}
                {cornerMetrics.coaching && (
                  <div>
                    <p className="text-[10px] text-steel/60 font-telemetry">Coaching</p>
                    <p className="text-xs text-amber-400/80 font-body leading-snug">
                      {cornerMetrics.coaching}
                    </p>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* Keyboard hints */}
      <div className="flex items-center gap-4 px-4 py-1.5 border-t border-steel/10 text-[9px] text-steel/30 font-telemetry">
        <span>Space: Play/Pause</span>
        <span>Arrows: Frame step</span>
        <span>[ ]: Prev/Next corner</span>
      </div>
    </div>
  );
}
