/**
 * CornerReplay.tsx — Corner analysis with playback and split compare.
 *
 * Features:
 *   - Corner selector dropdown
 *   - Side-by-side speed profiles through the corner for two laps
 *   - Playback controls (play/pause, step, scrub slider, speed)
 *   - requestAnimationFrame-driven distance cursor
 *
 * Fetches from /corner-positions, /corner-metrics/summary, /gps-trace.
 */
'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { apiFetch, ApiError } from '@/lib/api-client';

interface Corner {
  corner_id: number;
  corner_name?: string;
  s_start: number;
  s_end: number;
  s_apex: number;
  direction: string;
}

interface CornerSummary {
  corner_id: number;
  avg_entry_speed?: number;
  avg_apex_speed?: number;
  avg_exit_speed?: number;
  avg_time_loss_ms?: number;
}

interface TraceSlice {
  distances: number[];
  speeds: number[];
}

interface CornerReplayProps {
  sessionId: string;
  initialCorner?: number;
  className?: string;
}

/** Binary search: find index of first value >= target */
function lowerBound(arr: number[], target: number): number {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (arr[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Extract a slice of the trace arrays covering [sStart, sEnd] */
function sliceTrace(
  distances: number[],
  speeds: number[],
  sStart: number,
  sEnd: number,
): TraceSlice {
  const startIdx = lowerBound(distances, sStart);
  const endIdx = lowerBound(distances, sEnd);
  return {
    distances: distances.slice(startIdx, endIdx + 1),
    speeds: speeds.slice(startIdx, endIdx + 1),
  };
}

export function CornerReplay({
  sessionId,
  initialCorner,
  className = '',
}: CornerReplayProps) {
  const [corners, setCorners] = useState<Corner[]>([]);
  const [summaries, setSummaries] = useState<CornerSummary[]>([]);
  const [selectedCorner, setSelectedCorner] = useState<number | null>(initialCorner ?? null);
  const [lapA, setLapA] = useState<number>(1);
  const [lapB, setLapB] = useState<number>(2);
  const [traceA, setTraceA] = useState<TraceSlice | null>(null);
  const [traceB, setTraceB] = useState<TraceSlice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Playback state
  const [playing, setPlaying] = useState(false);
  const [playbackPos, setPlaybackPos] = useState(0); // 0–1 normalized
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const animFrameRef = useRef<number>(0);
  const lastTimeRef = useRef<number>(0);

  const canvasRef = useRef<HTMLCanvasElement>(null);

  // ── Fetch corners + summaries on mount ────────────────────────
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        const [cornerData, summaryData] = await Promise.all([
          apiFetch<{ corners: Corner[] }>(`/sessions/${sessionId}/corner-positions`),
          apiFetch<{ corners: CornerSummary[] }>(`/sessions/${sessionId}/corner-metrics/summary`).catch(() => ({ corners: [] })),
        ]);
        if (cancelled) return;

        const c = cornerData.corners ?? [];
        setCorners(c);
        setSummaries(summaryData.corners ?? []);
        if (c.length > 0 && selectedCorner === null) {
          setSelectedCorner(c[0].corner_id);
        }
        setLoading(false);
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Failed to load corners';
        setError(msg);
        setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Fetch GPS traces for selected laps + corner ───────────────
  useEffect(() => {
    if (selectedCorner === null || corners.length === 0) return;
    let cancelled = false;

    const corner = corners.find((c) => c.corner_id === selectedCorner);
    if (!corner) return;

    (async () => {
      try {
        const [gpsA, gpsB] = await Promise.all([
          apiFetch<{ distances: number[]; speeds: number[] }>(
            `/sessions/${sessionId}/speed-trace?lap=${lapA}`,
          ),
          apiFetch<{ distances: number[]; speeds: number[] }>(
            `/sessions/${sessionId}/speed-trace?lap=${lapB}`,
          ).catch(() => null),
        ]);
        if (cancelled) return;

        if (gpsA) {
          setTraceA(sliceTrace(gpsA.distances, gpsA.speeds, corner.s_start, corner.s_end));
        }
        if (gpsB) {
          setTraceB(sliceTrace(gpsB.distances, gpsB.speeds, corner.s_start, corner.s_end));
        } else {
          setTraceB(null);
        }
      } catch {
        // Non-critical — just won't show traces
      }
    })();

    return () => { cancelled = true; };
  }, [sessionId, selectedCorner, lapA, lapB, corners]);

  // ── Draw speed profile canvas ─────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !traceA) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const pad = { top: 20, right: 20, bottom: 30, left: 50 };

    // Clear
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, w, h);

    // Determine axis ranges
    const allDistances = [...traceA.distances, ...(traceB?.distances ?? [])];
    const allSpeeds = [...traceA.speeds, ...(traceB?.speeds ?? [])];
    const dMin = Math.min(...allDistances);
    const dMax = Math.max(...allDistances);
    const sMin = Math.min(...allSpeeds) * 0.95;
    const sMax = Math.max(...allSpeeds) * 1.05;

    const xScale = (d: number) => pad.left + ((d - dMin) / (dMax - dMin || 1)) * (w - pad.left - pad.right);
    const yScale = (s: number) => h - pad.bottom - ((s - sMin) / (sMax - sMin || 1)) * (h - pad.top - pad.bottom);

    // Grid lines
    ctx.strokeStyle = '#2a2a3e';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (i / 4) * (h - pad.top - pad.bottom);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
    }

    // Draw trace A (orange)
    ctx.strokeStyle = '#f97316';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < traceA.distances.length; i++) {
      const x = xScale(traceA.distances[i]);
      const y = yScale(traceA.speeds[i] * 3.6); // m/s → km/h
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Draw trace B (cyan)
    if (traceB && traceB.distances.length > 0) {
      ctx.strokeStyle = '#06b6d4';
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < traceB.distances.length; i++) {
        const x = xScale(traceB.distances[i]);
        const y = yScale(traceB.speeds[i] * 3.6);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    // Playback cursor
    if (playbackPos > 0) {
      const cursorD = dMin + playbackPos * (dMax - dMin);
      const cursorX = xScale(cursorD);
      ctx.strokeStyle = 'rgba(255,255,255,0.6)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(cursorX, pad.top);
      ctx.lineTo(cursorX, h - pad.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Axis labels
    ctx.fillStyle = '#9ca3af';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(`${dMin.toFixed(0)}m`, pad.left, h - 8);
    ctx.fillText(`${dMax.toFixed(0)}m`, w - pad.right, h - 8);
    ctx.textAlign = 'right';
    ctx.fillText(`${(sMin * 3.6).toFixed(0)}`, pad.left - 5, h - pad.bottom);
    ctx.fillText(`${(sMax * 3.6).toFixed(0)} km/h`, pad.left - 5, pad.top + 10);
  }, [traceA, traceB, playbackPos]);

  // ── Playback animation loop ───────────────────────────────────
  const animate = useCallback(
    (timestamp: number) => {
      if (!playing) return;
      if (lastTimeRef.current === 0) lastTimeRef.current = timestamp;

      const elapsed = (timestamp - lastTimeRef.current) / 1000; // seconds
      lastTimeRef.current = timestamp;

      setPlaybackPos((prev) => {
        const next = prev + elapsed * playbackSpeed * 0.2; // 5 seconds for full traverse at 1x
        if (next >= 1) {
          setPlaying(false);
          return 1;
        }
        return next;
      });

      animFrameRef.current = requestAnimationFrame(animate);
    },
    [playing, playbackSpeed],
  );

  useEffect(() => {
    if (playing) {
      lastTimeRef.current = 0;
      animFrameRef.current = requestAnimationFrame(animate);
    }
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [playing, animate]);

  // ── Loading / error states ────────────────────────────────────
  if (loading) {
    return <div className={`text-gray-500 p-4 ${className}`}>Loading corner data...</div>;
  }

  if (error) {
    return <div className={`text-red-400 p-4 ${className}`}>Failed to load corners: {error}</div>;
  }

  if (corners.length === 0) {
    return <div className={`text-gray-500 p-4 ${className}`}>No corners detected</div>;
  }

  const currentCorner = corners.find((c) => c.corner_id === selectedCorner);
  const currentSummary = summaries.find((s) => s.corner_id === selectedCorner);

  return (
    <div className={`bg-gray-900 rounded-lg p-4 ${className}`}>
      {/* Corner selector + summary */}
      <div className="flex items-center gap-3 mb-3 flex-wrap">
        <label className="text-sm text-gray-400">
          Corner:
          <select
            value={selectedCorner ?? ''}
            onChange={(e) => {
              setSelectedCorner(Number(e.target.value));
              setPlaybackPos(0);
              setPlaying(false);
            }}
            className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700 ml-2"
          >
            {corners.map((c) => (
              <option key={c.corner_id} value={c.corner_id}>
                {c.corner_name || `T${c.corner_id}`} ({c.direction})
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm text-gray-400">
          Lap A:
          <input
            type="number"
            min={1}
            value={lapA}
            onChange={(e) => setLapA(Number(e.target.value))}
            className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700 ml-1 w-16"
          />
        </label>

        <label className="text-sm text-gray-400">
          Lap B:
          <input
            type="number"
            min={1}
            value={lapB}
            onChange={(e) => setLapB(Number(e.target.value))}
            className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700 ml-1 w-16"
          />
        </label>
      </div>

      {/* Corner summary stats */}
      {currentSummary && (
        <div className="flex gap-4 text-xs text-gray-400 mb-3">
          {currentSummary.avg_entry_speed != null && (
            <span>Entry: {(currentSummary.avg_entry_speed * 3.6).toFixed(1)} km/h</span>
          )}
          {currentSummary.avg_apex_speed != null && (
            <span>Apex: {(currentSummary.avg_apex_speed * 3.6).toFixed(1)} km/h</span>
          )}
          {currentSummary.avg_exit_speed != null && (
            <span>Exit: {(currentSummary.avg_exit_speed * 3.6).toFixed(1)} km/h</span>
          )}
          {currentSummary.avg_time_loss_ms != null && (
            <span className="text-yellow-400">
              Avg loss: {currentSummary.avg_time_loss_ms.toFixed(0)}ms
            </span>
          )}
        </div>
      )}

      {/* Speed profile canvas */}
      <div className="relative">
        <canvas
          ref={canvasRef}
          style={{ width: '100%', height: '200px', display: 'block' }}
        />
        {/* Legend */}
        <div className="flex gap-3 text-xs mt-1">
          <span className="text-orange-400">Lap {lapA}</span>
          {traceB && <span className="text-cyan-400">Lap {lapB}</span>}
        </div>
      </div>

      {/* Playback controls */}
      <div className="flex items-center gap-2 mt-3">
        <button
          type="button"
          onClick={() => {
            if (playbackPos >= 1) setPlaybackPos(0);
            setPlaying(!playing);
          }}
          className="px-3 py-1 text-xs rounded bg-gray-700 text-white hover:bg-gray-600"
        >
          {playing ? 'Pause' : 'Play'}
        </button>

        <button
          type="button"
          onClick={() => setPlaybackPos((p) => Math.max(0, p - 0.05))}
          className="px-2 py-1 text-xs rounded bg-gray-800 text-gray-400 hover:bg-gray-700"
        >
          Step -
        </button>

        <button
          type="button"
          onClick={() => setPlaybackPos((p) => Math.min(1, p + 0.05))}
          className="px-2 py-1 text-xs rounded bg-gray-800 text-gray-400 hover:bg-gray-700"
        >
          Step +
        </button>

        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={playbackPos}
          onChange={(e) => {
            setPlaybackPos(Number(e.target.value));
            setPlaying(false);
          }}
          className="flex-1 accent-orange-500"
        />

        <select
          value={playbackSpeed}
          onChange={(e) => setPlaybackSpeed(Number(e.target.value))}
          className="bg-gray-800 text-white text-xs rounded px-1 py-1 border border-gray-700"
        >
          <option value={0.25}>0.25x</option>
          <option value={0.5}>0.5x</option>
          <option value={1}>1x</option>
          <option value={2}>2x</option>
        </select>
      </div>

      {/* Distance info */}
      {currentCorner && (
        <div className="text-xs text-gray-500 mt-2">
          {currentCorner.corner_name || `T${currentCorner.corner_id}`}:{' '}
          {currentCorner.s_start.toFixed(0)}m – {currentCorner.s_end.toFixed(0)}m
          (apex {currentCorner.s_apex.toFixed(0)}m)
        </div>
      )}
    </div>
  );
}
