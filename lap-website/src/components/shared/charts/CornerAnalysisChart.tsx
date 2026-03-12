/**
 * CornerAnalysisChart.tsx — Per-corner speed analysis (grouped bar chart).
 * For each corner: entry speed (blue), min speed (acid-green), exit speed (amber).
 * Error whiskers on min speed show +/-1 std deviation. Canvas-based.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';

interface CornerMetric {
  corner_id: number;
  corner_number: number;
  min_speed_avg: number;
  min_speed_std: number;
  apex_dist_avg: number;
  entry_speed_avg: number;
  exit_speed_avg: number;
  n_samples: number;
}

interface CornerSummaryResponse { corners: CornerMetric[]; available: boolean; }
interface CornerAnalysisChartProps {
  sessionId: string; gpsLaps: number[]; bestLap: number | null; className?: string;
}

const FONT = '10px "JetBrains Mono", monospace';
const COL = { entry: '#3b82f6', min: '#b4ff39', exit: '#f59e0b', text: '#c4c4c4', grid: 'rgba(255,255,255,0.08)', whisker: '#c4c4c4' };
const MS_KMH = 3.6;

export function CornerAnalysisChart({ sessionId, gpsLaps, bestLap, className = '' }: CornerAnalysisChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<CornerMetric[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await apiFetch<CornerSummaryResponse>(
        `/sessions/${encodeURIComponent(sessionId)}/corner-metrics/summary`,
      );
      if (!res.available || !res.corners.length) {
        dataRef.current = []; setError('No corner data available');
      } else { dataRef.current = res.corners; }
    } catch (e) {
      dataRef.current = [];
      setError(e instanceof Error ? e.message : 'Failed to load corner data');
    } finally { setLoading(false); }
  }, [sessionId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const corners = dataRef.current;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement?.clientWidth || canvas.clientWidth || 700;
    const h = 280;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    if (!corners.length) {
      ctx.fillStyle = COL.text; ctx.font = '13px "JetBrains Mono", monospace';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('No corner data available', w / 2, h / 2);
      return;
    }

    // Legend
    ctx.font = FONT; ctx.textBaseline = 'top'; ctx.textAlign = 'left';
    const legends = [{ t: 'Entry', c: COL.entry }, { t: 'Min', c: COL.min }, { t: 'Exit', c: COL.exit }];
    let lx = 8;
    for (const l of legends) {
      ctx.fillStyle = l.c; ctx.fillRect(lx, 7, 8, 8);
      ctx.fillStyle = COL.text; ctx.fillText(l.t, lx + 12, 6);
      lx += ctx.measureText(l.t).width + 24;
    }

    // Layout
    const pad = { top: 28, right: 16, bottom: 36, left: 48 };
    const pW = w - pad.left - pad.right, pH = h - pad.top - pad.bottom;
    const n = corners.length;

    // Y range (km/h) including whiskers
    let yMin = Infinity, yMax = -Infinity;
    for (const c of corners) {
      const vals = [c.entry_speed_avg, c.exit_speed_avg,
        c.min_speed_avg + c.min_speed_std, c.min_speed_avg - c.min_speed_std];
      for (const v of vals) { const k = v * MS_KMH; if (k < yMin) yMin = k; if (k > yMax) yMax = k; }
    }
    yMin = Math.max(0, Math.floor(yMin / 10) * 10 - 10);
    yMax = Math.ceil(yMax / 10) * 10 + 10;
    const yRange = yMax - yMin || 1;
    const yPx = (v: number) => pad.top + pH - ((v - yMin) / yRange) * pH;

    // Grid + Y axis labels
    const yStep = yRange <= 60 ? 10 : yRange <= 150 ? 20 : 50;
    ctx.font = FONT; ctx.fillStyle = COL.text;
    for (let v = yMin; v <= yMax; v += yStep) {
      const y = yPx(v);
      ctx.strokeStyle = COL.grid; ctx.lineWidth = 0.5;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText(v.toFixed(0), pad.left - 6, y);
    }

    // Y axis title
    ctx.save(); ctx.translate(10, pad.top + pH / 2); ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center'; ctx.fillStyle = COL.text; ctx.fillText('km/h', 0, 0); ctx.restore();

    // Bar geometry
    const gw = pW / n;
    const gap = Math.max(2, gw * 0.08);
    const baw = gw - gap * 2;
    const bw = Math.max(4, Math.floor(baw / 3));
    const gOffset = (baw - (bw * 3 + 2)) / 2;
    const bars = [
      { key: 'entry_speed_avg' as const, color: COL.entry },
      { key: 'min_speed_avg' as const, color: COL.min },
      { key: 'exit_speed_avg' as const, color: COL.exit },
    ];

    // Clip to plot area
    ctx.save(); ctx.beginPath(); ctx.rect(pad.left, pad.top, pW, pH); ctx.clip();
    const base = yPx(yMin);

    for (let ci = 0; ci < n; ci++) {
      const c = corners[ci]!;
      const gx = pad.left + ci * gw + gap + gOffset;

      for (let bi = 0; bi < bars.length; bi++) {
        const bar = bars[bi]!;
        const spd = c[bar.key] * MS_KMH;
        const bx = gx + bi * (bw + 1);
        const by = yPx(spd);
        ctx.fillStyle = bar.color; ctx.globalAlpha = 0.85;
        ctx.fillRect(bx, by, bw, base - by); ctx.globalAlpha = 1;

        // Whiskers on min speed bar
        if (bi === 1 && c.min_speed_std > 0) {
          const wt = yPx((c.min_speed_avg + c.min_speed_std) * MS_KMH);
          const wb = yPx((c.min_speed_avg - c.min_speed_std) * MS_KMH);
          const mx = bx + bw / 2, cw = Math.max(4, bw * 0.5);
          ctx.strokeStyle = COL.whisker; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(mx, wt); ctx.lineTo(mx, wb); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(mx - cw / 2, wt); ctx.lineTo(mx + cw / 2, wt); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(mx - cw / 2, wb); ctx.lineTo(mx + cw / 2, wb); ctx.stroke();
        }
      }
    }
    ctx.restore();

    // X axis labels
    ctx.fillStyle = COL.text; ctx.font = FONT; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (let ci = 0; ci < n; ci++) {
      ctx.fillText(`T${corners[ci]!.corner_number}`, pad.left + ci * gw + gw / 2, pad.top + pH + 6);
    }
    ctx.textBaseline = 'bottom';
    ctx.fillText('Corner', pad.left + pW / 2, h - 2);
  }, []);

  useEffect(() => { if (!loading) draw(); }, [loading, draw]);

  useEffect(() => {
    const c = containerRef.current; if (!c) return;
    const ro = new ResizeObserver(() => draw()); ro.observe(c);
    return () => ro.disconnect();
  }, [draw]);

  // Corner data availability is handled by the API response (res.available),
  // so no early gpsLaps guard — allows Focus Mode to render with gpsLaps=[]

  return (
    <div ref={containerRef} className={className} role="img" aria-label="Corner analysis chart showing entry, minimum, and exit speeds per corner">
      <div className="flex items-center gap-3 mb-3 flex-wrap text-sm">
        {loading && <span className="text-xs text-[#c4c4c4] animate-pulse">Loading corner data...</span>}
        {error && !loading && <span className="text-xs text-red-400">{error}</span>}
      </div>
      <div className="relative" style={{ width: '100%' }}>
        <canvas ref={canvasRef} style={{ width: '100%', height: '280px', display: 'block' }} />
      </div>
    </div>
  );
}
