/**
 * WheelSlipChart.tsx — Wheel slip ratio vs distance with lockup/wheelspin zones.
 * 4 traces (FL, FR, RL, RR). Lockup (<-0.15) = red zone, wheelspin (>0.10) = orange zone.
 * Integrates with useChartHoverStore for cross-chart hover sync.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface WheelSlipData {
  distances: number[]; fl: number[]; fr: number[]; rl: number[]; rr: number[]; available: boolean;
}
interface WheelSlipChartProps {
  sessionId: string; gpsLaps: number[]; bestLap: number | null; className?: string;
}

const TRACES = [
  { key: 'fl' as const, label: 'FL', color: '#3b82f6' },
  { key: 'fr' as const, label: 'FR', color: '#22d3ee' },
  { key: 'rl' as const, label: 'RL', color: '#f97316' },
  { key: 'rr' as const, label: 'RR', color: '#ef4444' },
];
const LOCKUP = -0.15, SPIN = 0.10;

function closestIdx(arr: number[], t: number): number {
  if (!arr || !arr.length) return -1;
  let lo = 0, hi = arr.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; arr[m] < t ? lo = m + 1 : hi = m; }
  return lo > 0 && Math.abs(arr[lo - 1] - t) < Math.abs(arr[lo] - t) ? lo - 1 : lo;
}

export function WheelSlipChart({ sessionId, gpsLaps, bestLap, className = '' }: WheelSlipChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<WheelSlipData | null>(null);
  const boundsRef = useRef<{
    xMin: number; xMax: number; yMin: number; yMax: number;
    plotX: number; plotY: number; plotW: number; plotH: number;
  } | null>(null);
  const [selectedLap, setSelectedLap] = useState<number>(bestLap ?? gpsLaps[0] ?? 0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!selectedLap) { dataRef.current = null; return; }
    setLoading(true); setError(null);
    try {
      const d = await apiFetch<WheelSlipData>(`/sessions/${encodeURIComponent(sessionId)}/wheel-slip?lap=${selectedLap}`);
      if (!d.available) { dataRef.current = null; setError('No wheel slip data available for this lap'); }
      else dataRef.current = d;
    } catch (e) { dataRef.current = null; setError(e instanceof Error ? e.message : 'Failed to load wheel slip'); }
    finally { setLoading(false); }
  }, [sessionId, selectedLap]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const draw = useCallback((hoverDist: number | null = null) => {
    const canvas = canvasRef.current; if (!canvas) return;
    const data = dataRef.current;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement?.clientWidth || canvas.clientWidth || 700, h = 240;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const pad = { top: 20, right: 20, bottom: 38, left: 58 };
    const pW = w - pad.left - pad.right, pH = h - pad.top - pad.bottom;
    ctx.fillStyle = '#1a1f2e'; ctx.fillRect(0, 0, w, h);

    if (!data || !data.distances || data.distances.length < 2) {
      ctx.fillStyle = '#8b949e'; ctx.font = '13px -apple-system, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('No wheel slip data available', w / 2, h / 2);
      boundsRef.current = null; return;
    }
    const dists = data.distances, xMin = 0, xMax = dists[dists.length - 1] || 1;
    let dMin = 0, dMax = 0;
    for (const tr of TRACES) { const a = data[tr.key]; for (let i = 0; i < a.length; i++) { if (a[i] < dMin) dMin = a[i]; if (a[i] > dMax) dMax = a[i]; } }
    const yMin = Math.min(-0.3, Math.floor(dMin * 20) / 20);
    const yMax = Math.max(0.3, Math.ceil(dMax * 20) / 20);
    boundsRef.current = { xMin, xMax, yMin, yMax, plotX: pad.left, plotY: pad.top, plotW: pW, plotH: pH };
    const xPx = (v: number) => pad.left + ((v - xMin) / (xMax - xMin)) * pW;
    const yPx = (v: number) => pad.top + ((yMax - v) / (yMax - yMin)) * pH;

    // Grid
    ctx.strokeStyle = '#30363d'; ctx.lineWidth = 0.5;
    for (let v = yMin; v <= yMax + 0.001; v += 0.05) { ctx.beginPath(); ctx.moveTo(pad.left, yPx(v)); ctx.lineTo(w - pad.right, yPx(v)); ctx.stroke(); }
    const xRange = xMax - xMin;
    const xStep = xRange <= 200 ? 25 : xRange <= 500 ? 50 : xRange <= 1000 ? 100 : xRange <= 3000 ? 250 : 500;
    for (let v = 0; v <= xMax; v += xStep) { ctx.beginPath(); ctx.moveTo(xPx(v), pad.top); ctx.lineTo(xPx(v), pad.top + pH); ctx.stroke(); }
    // Zero line
    ctx.strokeStyle = '#6e7681'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.left, yPx(0)); ctx.lineTo(w - pad.right, yPx(0)); ctx.stroke();

    ctx.save(); ctx.beginPath(); ctx.rect(pad.left, pad.top, pW, pH); ctx.clip();
    // Highlight zones
    for (let i = 0; i < dists.length - 1; i++) {
      let lock = false, spin = false;
      for (const tr of TRACES) { const v = data[tr.key][i]; if (v < LOCKUP) lock = true; if (v > SPIN) spin = true; }
      const x1 = xPx(dists[i]), x2 = xPx(dists[i + 1]);
      if (lock) { ctx.fillStyle = 'rgba(239,68,68,0.08)'; ctx.fillRect(x1, pad.top, x2 - x1, pH); }
      if (spin) { ctx.fillStyle = 'rgba(249,115,22,0.08)'; ctx.fillRect(x1, pad.top, x2 - x1, pH); }
    }
    // Traces
    for (const tr of TRACES) {
      const a = data[tr.key]; ctx.strokeStyle = tr.color; ctx.lineWidth = 1.5; ctx.beginPath();
      for (let i = 0; i < dists.length; i++) { const x = xPx(dists[i]), y = yPx(a[i]); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); }
      ctx.stroke();
    }
    ctx.restore();

    // Labels
    ctx.fillStyle = '#8b949e'; ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (let v = yMin; v <= yMax + 0.001; v += 0.1) ctx.fillText(v.toFixed(1), pad.left - 6, yPx(v));
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (let v = 0; v <= xMax; v += xStep) ctx.fillText(v.toFixed(0) + 'm', xPx(v), pad.top + pH + 6);
    ctx.font = '11px -apple-system, sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('Distance (m)', pad.left + pW / 2, h - 4);
    ctx.save(); ctx.translate(12, pad.top + pH / 2); ctx.rotate(-Math.PI / 2); ctx.fillText('Slip Ratio', 0, 0); ctx.restore();

    // Threshold lines
    ctx.setLineDash([4, 4]); ctx.lineWidth = 0.8;
    ctx.strokeStyle = 'rgba(239,68,68,0.4)'; ctx.beginPath(); ctx.moveTo(pad.left, yPx(LOCKUP)); ctx.lineTo(w - pad.right, yPx(LOCKUP)); ctx.stroke();
    ctx.strokeStyle = 'rgba(249,115,22,0.4)'; ctx.beginPath(); ctx.moveTo(pad.left, yPx(SPIN)); ctx.lineTo(w - pad.right, yPx(SPIN)); ctx.stroke();
    ctx.setLineDash([]);

    // Hover
    if (hoverDist !== null && hoverDist >= xMin && hoverDist <= xMax) {
      const hx = xPx(hoverDist);
      ctx.strokeStyle = 'rgba(255,255,255,0.3)'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(hx, pad.top); ctx.lineTo(hx, pad.top + pH); ctx.stroke(); ctx.setLineDash([]);
      const idx = closestIdx(dists, hoverDist);
      if (idx >= 0) {
        const tips: string[] = [hoverDist.toFixed(0) + 'm'];
        for (const tr of TRACES) {
          const v = data[tr.key][idx]; ctx.beginPath(); ctx.arc(hx, yPx(v), 4, 0, Math.PI * 2);
          ctx.fillStyle = tr.color; ctx.fill(); ctx.strokeStyle = '#e6edf3'; ctx.lineWidth = 1; ctx.stroke();
          tips.push(`${tr.label}: ${v.toFixed(3)}`);
        }
        ctx.font = '10px -apple-system, sans-serif';
        let mw = 0; for (const l of tips) { const m = ctx.measureText(l).width; if (m > mw) mw = m; }
        const tW = mw + 16, tH = tips.length * 14 + 8;
        let tX = hx + 12; if (tX + tW > w - 10) tX = hx - tW - 12;
        ctx.fillStyle = 'rgba(0,0,0,0.85)'; ctx.fillRect(tX, pad.top + 10, tW, tH);
        ctx.fillStyle = '#e6edf3'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
        for (let i = 0; i < tips.length; i++) ctx.fillText(tips[i], tX + 8, pad.top + 14 + i * 14);
      }
    }
    // Legend
    ctx.font = '10px -apple-system, sans-serif'; ctx.textAlign = 'right'; ctx.textBaseline = 'top';
    let lx = w - pad.right;
    for (let i = TRACES.length - 1; i >= 0; i--) {
      const t = TRACES[i], lw = ctx.measureText(t.label).width + 16;
      ctx.fillStyle = t.color; ctx.fillRect(lx - lw, pad.top + 2, 8, 8);
      ctx.fillStyle = '#8b949e'; ctx.fillText(t.label, lx, pad.top + 2); lx -= lw + 8;
    }
  }, []);

  useEffect(() => { if (!loading) draw(); }, [loading, draw]);
  useEffect(() => {
    const c = containerRef.current; if (!c) return;
    const ro = new ResizeObserver(() => draw()); ro.observe(c); return () => ro.disconnect();
  }, [draw]);
  useEffect(() => {
    const unsub = useChartHoverStore.subscribe((s) => { if (s.hoverSource !== 'wheel-slip-chart') draw(s.hoverDistance); });
    return unsub;
  }, [draw]);
  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas) return;
    const { setHover, clearHover } = useChartHoverStore.getState();
    const onMove = (e: MouseEvent) => {
      const b = boundsRef.current; if (!b) return;
      const mx = e.clientX - canvas.getBoundingClientRect().left;
      if (mx < b.plotX || mx > b.plotX + b.plotW) { clearHover(); draw(null); return; }
      const d = b.xMin + ((mx - b.plotX) / b.plotW) * (b.xMax - b.xMin); setHover(d, 'wheel-slip-chart'); draw(d);
    };
    const onLeave = () => { clearHover(); draw(null); };
    canvas.addEventListener('mousemove', onMove); canvas.addEventListener('mouseleave', onLeave);
    return () => { canvas.removeEventListener('mousemove', onMove); canvas.removeEventListener('mouseleave', onLeave); };
  }, [draw]);

  return (
    <div ref={containerRef} className={className} role="img" aria-label="Wheel slip chart showing tire grip levels">
      <div className="flex items-center gap-3 mb-3 flex-wrap text-sm">
        <label className="flex items-center gap-1.5 text-gray-400">
          Lap:
          <select value={selectedLap} onChange={(e) => setSelectedLap(Number(e.target.value))}
            className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700">
            {gpsLaps.map((l) => <option key={l} value={l}>Lap {l}{l === bestLap ? ' (Best)' : ''}</option>)}
          </select>
        </label>
        {loading && <span className="text-xs text-steel animate-pulse">Loading...</span>}
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
      <div className="relative" style={{ width: '100%' }}>
        <canvas ref={canvasRef} style={{ width: '100%', height: '240px', display: 'block' }} />
      </div>
    </div>
  );
}
