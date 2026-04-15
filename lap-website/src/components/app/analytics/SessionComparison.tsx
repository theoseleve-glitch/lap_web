'use client';

import { useState, useEffect, useRef, useCallback, type MouseEvent as ReactMouseEvent } from 'react';
import { apiFetch } from '@/lib/api-client';
import { chartColor } from '@/components/shared/chart-kit';

const MPS_TO_KMH = 3.6;

// Loop-based min/max — Math.min(...arr) overflows the call stack with large arrays
function minOf(arr: number[]): number {
  let v = Infinity;
  for (let i = 0; i < arr.length; i++) if (arr[i] < v) v = arr[i];
  return v;
}
function maxOf(arr: number[]): number {
  let v = -Infinity;
  for (let i = 0; i < arr.length; i++) if (arr[i] > v) v = arr[i];
  return v;
}

interface SessionSummary {
  session_id: string;
  csv_filename: string;
  driver_name: string;
  track_name: string | null;
  session_date: string;
  best_lap_time_s: number | null;
}

interface CompareData {
  distances: number[];
  speeds_a: number[];
  speeds_b: number[];
  delta_s: number[];
  session_a: { session_id: string; best_time_s: number | null; lap_number: number };
  session_b: { session_id: string; best_time_s: number | null; lap_number: number };
}

interface SessionComparisonProps {
  sessionId: string;
  trackName: string | null;
  className?: string;
}

function fmtTime(s: number | null): string {
  if (s == null || !isFinite(s)) return '--';
  if (s >= 60) {
    const m = Math.floor(s / 60);
    const sec = s - m * 60;
    return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
  }
  return `${s.toFixed(3)}s`;
}

export function SessionComparison({ sessionId, trackName, className = '' }: SessionComparisonProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [compareData, setCompareData] = useState<CompareData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const speedCanvasRef = useRef<HTMLCanvasElement>(null);
  const deltaCanvasRef = useRef<HTMLCanvasElement>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);

  // Fetch available sessions for the same track
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch<{ sessions: SessionSummary[] }>('/sessions');
        if (cancelled) return;
        // Filter to same track, exclude current session, take 10 most recent
        const filtered = (data?.sessions || [])
          .filter((s) => s.session_id !== sessionId && s.track_name === trackName)
          .slice(0, 10);
        setSessions(filtered);
      } catch {
        // Silently fail — dropdown will just be empty
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId, trackName]);

  // Fetch comparison data when a session is selected
  const loadComparison = useCallback(async (targetId: string) => {
    setSelectedId(targetId);
    if (!targetId) { setCompareData(null); return; }
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<CompareData>(`/sessions/${sessionId}/compare?sessionKeyB=${encodeURIComponent(targetId)}`);
      setCompareData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load comparison');
      setCompareData(null);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  // Draw speed overlay canvas
  const drawSpeed = useCallback(() => {
    if (!compareData || !speedCanvasRef.current) return;
    const canvas = speedCanvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    canvas.width = rect.width * dpr;
    canvas.height = 200 * dpr;
    canvas.style.height = '200px';
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = 200;
    const pad = { top: 10, right: 10, bottom: 25, left: 45 };
    const pw = w - pad.left - pad.right;
    const ph = h - pad.top - pad.bottom;

    // Background
    ctx.fillStyle = chartColor.surface;
    ctx.fillRect(0, 0, w, h);

    const { distances, speeds_a, speeds_b } = compareData;
    if (!distances?.length) return;

    const xMax = maxOf(distances) || 1;
    // Convert m/s → km/h for display
    const kmhA = speeds_a.map((v) => v * MPS_TO_KMH);
    const kmhB = speeds_b.map((v) => v * MPS_TO_KMH);
    const allSpeeds = [...kmhA, ...kmhB].filter(isFinite);
    const yMin = minOf(allSpeeds) * 0.95;
    const yMax = maxOf(allSpeeds) * 1.05 || 1;
    const yRange = yMax - yMin || 1;

    const xScale = (v: number) => pad.left + (v / xMax) * pw;
    const yScale = (v: number) => pad.top + ph - ((v - yMin) / yRange) * ph;

    // Grid lines
    ctx.strokeStyle = chartColor.grid;
    ctx.lineWidth = 0.5;
    const ySteps = 5;
    for (let i = 0; i <= ySteps; i++) {
      const y = pad.top + (ph * i) / ySteps;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
    }
    const xSteps = 6;
    for (let i = 0; i <= xSteps; i++) {
      const x = pad.left + (pw * i) / xSteps;
      ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, pad.top + ph); ctx.stroke();
    }

    // Draw lines — acid-green for current, pit-orange for comparison
    const drawLine = (speeds: number[], color: string) => {
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      for (let i = 0; i < distances.length; i++) {
        const x = xScale(distances[i]);
        const y = yScale(speeds[i]);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    };

    drawLine(kmhA, chartColor.series.positive);
    drawLine(kmhB, chartColor.series.primary);

    // Y-axis labels (km/h)
    ctx.fillStyle = chartColor.textSecondary;
    ctx.font = '11px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= ySteps; i++) {
      const val = yMax - yRange * (i / ySteps);
      const y = pad.top + (ph * i) / ySteps;
      ctx.fillText(val.toFixed(0), pad.left - 6, y);
    }

    // X-axis labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let i = 0; i <= xSteps; i++) {
      const val = (xMax * i) / xSteps;
      const x = pad.left + (pw * i) / xSteps;
      ctx.fillText(`${val.toFixed(0)}m`, x, pad.top + ph + 6);
    }

    // Axis titles
    ctx.font = '12px "Space Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Distance (m)', w / 2, h - 2);
    ctx.save();
    ctx.translate(12, h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Speed (km/h)', 0, 0);
    ctx.restore();

    // Legend
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.fillStyle = chartColor.series.positive;
    ctx.fillText('\u2500\u2500 This session', pad.left + 8, pad.top + 8);
    ctx.fillStyle = chartColor.series.primary;
    ctx.fillText('\u2500\u2500 Comparison', pad.left + 8, pad.top + 20);

    // Crosshair hover
    if (hoverX !== null && hoverX >= pad.left && hoverX <= pad.left + pw) {
      const pct = (hoverX - pad.left) / pw;
      const idx = Math.min(Math.round(pct * (distances.length - 1)), distances.length - 1);
      const dist = distances[idx];
      const sA = kmhA[idx];
      const sB = kmhB[idx];

      // Vertical line
      ctx.strokeStyle = chartColor.crosshair;
      ctx.lineWidth = 0.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(hoverX, pad.top);
      ctx.lineTo(hoverX, pad.top + ph);
      ctx.stroke();
      ctx.setLineDash([]);

      // Dots
      const yA = yScale(sA);
      const yB = yScale(sB);
      ctx.fillStyle = chartColor.series.positive;
      ctx.beginPath(); ctx.arc(hoverX, yA, 3, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = chartColor.series.primary;
      ctx.beginPath(); ctx.arc(hoverX, yB, 3, 0, Math.PI * 2); ctx.fill();

      // Tooltip
      const tipX = hoverX + 10 > w - 120 ? hoverX - 120 : hoverX + 10;
      ctx.fillStyle = chartColor.tooltipBg;
      ctx.fillRect(tipX, pad.top + 2, 110, 42);
      ctx.strokeStyle = chartColor.grid;
      ctx.lineWidth = 1;
      ctx.strokeRect(tipX, pad.top + 2, 110, 42);
      ctx.font = '10px "Space Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillStyle = chartColor.textSecondary;
      ctx.fillText(`${dist.toFixed(0)}m`, tipX + 5, pad.top + 14);
      ctx.fillStyle = chartColor.series.positive;
      ctx.fillText(`A: ${sA.toFixed(1)} km/h`, tipX + 5, pad.top + 26);
      ctx.fillStyle = chartColor.series.primary;
      ctx.fillText(`B: ${sB.toFixed(1)} km/h`, tipX + 5, pad.top + 38);
    }
  }, [compareData, hoverX]);

  useEffect(() => { drawSpeed(); }, [drawSpeed]);
  useEffect(() => {
    const c = speedCanvasRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => drawSpeed());
    ro.observe(c);
    return () => ro.disconnect();
  }, [drawSpeed]);

  // Draw cumulative delta strip
  const drawDelta = useCallback(() => {
    if (!compareData || !deltaCanvasRef.current) return;
    const canvas = deltaCanvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    canvas.width = rect.width * dpr;
    canvas.height = 60 * dpr;
    canvas.style.height = '60px';
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = 60;
    const pad = { left: 45, right: 10 };
    const pw = w - pad.left - pad.right;

    // Background
    ctx.fillStyle = chartColor.surface;
    ctx.fillRect(0, 0, w, h);

    const { distances, delta_s } = compareData;
    if (!distances?.length || !delta_s?.length) return;

    const xMax = maxOf(distances);
    let absMax = 0.001;
    for (let i = 0; i < delta_s.length; i++) {
      const a = Math.abs(delta_s[i]);
      if (a > absMax) absMax = a;
    }

    const xScale = (v: number) => pad.left + (v / xMax) * pw;
    const yMid = h / 2;
    const yScale = (v: number) => yMid - (v / absMax) * (h / 2 - 5);

    // Zero line
    ctx.strokeStyle = chartColor.grid;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(pad.left, yMid);
    ctx.lineTo(w - pad.right, yMid);
    ctx.stroke();
    ctx.setLineDash([]);

    // Separate green (above zero) and red (below zero) fills
    // Green fill (positive = faster)
    ctx.beginPath();
    ctx.moveTo(xScale(distances[0]), yMid);
    for (let i = 0; i < distances.length; i++) {
      ctx.lineTo(xScale(distances[i]), yScale(Math.max(0, delta_s[i])));
    }
    ctx.lineTo(xScale(distances[distances.length - 1]), yMid);
    ctx.closePath();
    ctx.fillStyle = `${chartColor.series.positive}33`;
    ctx.fill();

    // Red fill (negative = slower)
    ctx.beginPath();
    ctx.moveTo(xScale(distances[0]), yMid);
    for (let i = 0; i < distances.length; i++) {
      ctx.lineTo(xScale(distances[i]), yScale(Math.min(0, delta_s[i])));
    }
    ctx.lineTo(xScale(distances[distances.length - 1]), yMid);
    ctx.closePath();
    ctx.fillStyle = `${chartColor.series.negative}33`;
    ctx.fill();

    // Delta line
    ctx.strokeStyle = chartColor.text;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < distances.length; i++) {
      const x = xScale(distances[i]);
      const y = yScale(delta_s[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Label
    ctx.fillStyle = chartColor.textSecondary;
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.fillText('Time delta (s)', pad.left + 5, 12);

    // Crosshair hover
    if (hoverX !== null && hoverX >= pad.left && hoverX <= pad.left + pw) {
      const pct = (hoverX - pad.left) / pw;
      const idx = Math.min(Math.round(pct * (distances.length - 1)), distances.length - 1);
      const dist = distances[idx];
      const d = delta_s[idx];

      ctx.strokeStyle = chartColor.crosshair;
      ctx.lineWidth = 0.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(hoverX, 0);
      ctx.lineTo(hoverX, h);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = chartColor.text;
      ctx.beginPath(); ctx.arc(hoverX, yScale(d), 3, 0, Math.PI * 2); ctx.fill();

      const tipX = hoverX + 10 > w - 100 ? hoverX - 100 : hoverX + 10;
      ctx.fillStyle = chartColor.tooltipBg;
      ctx.fillRect(tipX, 2, 90, 28);
      ctx.strokeStyle = chartColor.grid;
      ctx.lineWidth = 1;
      ctx.strokeRect(tipX, 2, 90, 28);
      ctx.font = '10px "Space Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillStyle = chartColor.textSecondary;
      ctx.fillText(`${dist.toFixed(0)}m`, tipX + 5, 14);
      ctx.fillStyle = d >= 0 ? chartColor.series.positive : chartColor.series.negative;
      ctx.fillText(`${d >= 0 ? '+' : ''}${d.toFixed(3)}s`, tipX + 5, 26);
    }
  }, [compareData, hoverX]);

  useEffect(() => { drawDelta(); }, [drawDelta]);
  useEffect(() => {
    const c = deltaCanvasRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => drawDelta());
    ro.observe(c);
    return () => ro.disconnect();
  }, [drawDelta]);

  return (
    <div className={className}>
      {/* Session picker */}
      <div className="flex items-center gap-3 mb-4">
        <label className="text-xs text-steel font-body flex items-center gap-3">
          Compare with:
        <select
          value={selectedId}
          onChange={(e) => loadComparison(e.target.value)}
          className="bg-asphalt text-chalk text-sm rounded px-3 py-1.5 border border-steel/20 font-body"
        >
          <option value="">Select a session...</option>
          {sessions.map((s) => (
            <option key={s.session_id} value={s.session_id}>
              {s.session_date} — {s.driver_name} ({fmtTime(s.best_lap_time_s)})
            </option>
          ))}
        </select>
        </label>
        {sessions.length === 0 && (
          <span className="text-xs text-steel/60">No other sessions on this track</span>
        )}
      </div>

      {/* Loading / error states */}
      {loading && (
        <div className="flex items-center justify-center p-8 text-steel">
          <div className="text-sm">Loading comparison...</div>
        </div>
      )}
      {error && <div className="text-safety-red text-sm p-4">{error}</div>}

      {/* Empty state */}
      {!selectedId && !loading && (
        <div className="flex items-center justify-center p-8 text-steel/60 text-sm">
          Select a session above to compare speed traces and time deltas.
        </div>
      )}

      {/* Charts */}
      {compareData && !loading && (
        <div className="space-y-4">
          {/* Summary cards */}
          <div className="flex gap-4 flex-wrap">
            <div className="bg-asphalt/50 rounded-lg px-4 py-2 border border-steel/10">
              <div className="text-xs text-steel font-body">This Session Best</div>
              <div className="text-sm text-chalk font-telemetry">{fmtTime(compareData.session_a?.best_time_s)}</div>
            </div>
            <div className="bg-asphalt/50 rounded-lg px-4 py-2 border border-steel/10">
              <div className="text-xs text-steel font-body">Comparison Best</div>
              <div className="text-sm text-chalk font-telemetry">{fmtTime(compareData.session_b?.best_time_s)}</div>
            </div>
            {compareData.session_a?.best_time_s != null && compareData.session_b?.best_time_s != null && (
              <div className="bg-asphalt/50 rounded-lg px-4 py-2 border border-steel/10">
                <div className="text-xs text-steel font-body">Delta</div>
                <div className={`text-sm font-telemetry ${compareData.session_a.best_time_s <= compareData.session_b.best_time_s ? 'text-acid-green' : 'text-safety-red'}`}>
                  {compareData.session_a.best_time_s <= compareData.session_b.best_time_s ? '-' : '+'}
                  {Math.abs(compareData.session_a.best_time_s - compareData.session_b.best_time_s).toFixed(3)}s
                </div>
              </div>
            )}
          </div>

          {/* Speed overlay */}
          <div>
            <div className="text-xs text-steel font-body uppercase tracking-wider mb-1">Speed Overlay</div>
            <canvas
              ref={speedCanvasRef}
              style={{ width: '100%', display: 'block', cursor: 'crosshair' }}
              onMouseMove={(e: ReactMouseEvent<HTMLCanvasElement>) => {
                const rect = e.currentTarget.getBoundingClientRect();
                setHoverX(e.clientX - rect.left);
              }}
              onMouseLeave={() => setHoverX(null)}
            />
          </div>

          {/* Cumulative delta */}
          <div>
            <div className="text-xs text-steel font-body uppercase tracking-wider mb-1">Cumulative Time Delta</div>
            <canvas
              ref={deltaCanvasRef}
              style={{ width: '100%', display: 'block', cursor: 'crosshair' }}
              onMouseMove={(e: ReactMouseEvent<HTMLCanvasElement>) => {
                const rect = e.currentTarget.getBoundingClientRect();
                setHoverX(e.clientX - rect.left);
              }}
              onMouseLeave={() => setHoverX(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
