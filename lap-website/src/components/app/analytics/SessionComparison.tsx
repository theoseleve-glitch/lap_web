'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';

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
  useEffect(() => {
    if (!compareData || !speedCanvasRef.current) return;
    const canvas = speedCanvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 200 * dpr;
    canvas.style.height = '200px';
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = 200;
    const pad = { top: 10, right: 10, bottom: 25, left: 45 };
    const pw = w - pad.left - pad.right;
    const ph = h - pad.top - pad.bottom;

    // Background — matches SpeedTraceChart (#141414)
    ctx.fillStyle = '#141414';
    ctx.fillRect(0, 0, w, h);

    const { distances, speeds_a, speeds_b } = compareData;
    if (!distances?.length) return;

    const xMax = Math.max(...distances);
    const allSpeeds = [...speeds_a, ...speeds_b].filter(isFinite);
    const yMin = Math.min(...allSpeeds) * 0.95;
    const yMax = Math.max(...allSpeeds) * 1.05;

    const xScale = (v: number) => pad.left + (v / xMax) * pw;
    const yScale = (v: number) => pad.top + ph - ((v - yMin) / (yMax - yMin)) * ph;

    // Grid lines — matches SpeedTraceChart
    ctx.strokeStyle = '#30363d';
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

    // Draw lines — acid-green (#3ddc84) for current, pit-orange (#ff8c00) for comparison
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

    drawLine(speeds_a, '#3ddc84'); // acid-green = current session
    drawLine(speeds_b, '#ff8c00'); // pit-orange = comparison

    // Y-axis labels
    ctx.fillStyle = '#888888';
    ctx.font = '11px "Space Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= ySteps; i++) {
      const val = yMax - (yMax - yMin) * (i / ySteps);
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
    ctx.fillText('Speed (m/s)', 0, 0);
    ctx.restore();

    // Legend — matches SpeedTraceChart style
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.fillStyle = '#3ddc84';
    ctx.fillText('\u2500\u2500 This session', pad.left + 8, pad.top + 8);
    ctx.fillStyle = '#ff8c00';
    ctx.fillText('\u2500\u2500 Comparison', pad.left + 8, pad.top + 20);
  }, [compareData]);

  // Draw cumulative delta strip
  useEffect(() => {
    if (!compareData || !deltaCanvasRef.current) return;
    const canvas = deltaCanvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 60 * dpr;
    canvas.style.height = '60px';
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = 60;
    const pad = { left: 45, right: 10 };
    const pw = w - pad.left - pad.right;

    // Background — matches SpeedTraceChart (#141414)
    ctx.fillStyle = '#141414';
    ctx.fillRect(0, 0, w, h);

    const { distances, delta_s } = compareData;
    if (!distances?.length || !delta_s?.length) return;

    const xMax = Math.max(...distances);
    const absMax = Math.max(...delta_s.map(Math.abs), 0.001);

    const xScale = (v: number) => pad.left + (v / xMax) * pw;
    const yMid = h / 2;
    const yScale = (v: number) => yMid - (v / absMax) * (h / 2 - 5);

    // Zero line
    ctx.strokeStyle = '#30363d';
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
    ctx.fillStyle = 'rgba(16, 185, 129, 0.2)';
    ctx.fill();

    // Red fill (negative = slower)
    ctx.beginPath();
    ctx.moveTo(xScale(distances[0]), yMid);
    for (let i = 0; i < distances.length; i++) {
      ctx.lineTo(xScale(distances[i]), yScale(Math.min(0, delta_s[i])));
    }
    ctx.lineTo(xScale(distances[distances.length - 1]), yMid);
    ctx.closePath();
    ctx.fillStyle = 'rgba(239, 68, 68, 0.2)';
    ctx.fill();

    // Delta line
    ctx.strokeStyle = '#F0EDE5';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < distances.length; i++) {
      const x = xScale(distances[i]);
      const y = yScale(delta_s[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Label
    ctx.fillStyle = '#888888';
    ctx.font = '10px "Space Mono", monospace';
    ctx.textAlign = 'left';
    ctx.fillText('Time delta (s)', pad.left + 5, 12);
  }, [compareData]);

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
        <div className="flex items-center justify-center p-8 text-gray-500">
          <div className="text-sm">Loading comparison...</div>
        </div>
      )}
      {error && <div className="text-red-400 text-sm p-4">{error}</div>}

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
                <div className={`text-sm font-telemetry ${compareData.session_a.best_time_s <= compareData.session_b.best_time_s ? 'text-green-400' : 'text-red-400'}`}>
                  {compareData.session_a.best_time_s <= compareData.session_b.best_time_s ? '-' : '+'}
                  {Math.abs(compareData.session_a.best_time_s - compareData.session_b.best_time_s).toFixed(3)}s
                </div>
              </div>
            )}
          </div>

          {/* Speed overlay */}
          <div>
            <div className="text-xs text-steel font-body uppercase tracking-wider mb-1">Speed Overlay</div>
            <canvas ref={speedCanvasRef} style={{ width: '100%', display: 'block' }} />
          </div>

          {/* Cumulative delta */}
          <div>
            <div className="text-xs text-steel font-body uppercase tracking-wider mb-1">Cumulative Time Delta</div>
            <canvas ref={deltaCanvasRef} style={{ width: '100%', display: 'block' }} />
          </div>
        </div>
      )}
    </div>
  );
}
