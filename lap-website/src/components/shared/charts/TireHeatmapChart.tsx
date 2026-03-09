/**
 * TireHeatmapChart.tsx — 2x2 tire temperature heatmap visualization.
 * Color fill: Blue (<60C) -> Green (80-100C) -> Yellow (~110C) -> Red (>120C).
 * 3-zone data (inner/mid/outer) as vertical strips. Balance indicators below.
 * Static per-lap view — does NOT participate in hover sync.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';

interface TireZone { i: number[]; m: number[]; o: number[]; }
interface TireTempData {
  distances: number[]; fl: TireZone; fr: TireZone; rl: TireZone; rr: TireZone; available: boolean;
}
interface TireHeatmapChartProps {
  sessionId: string; gpsLaps: number[]; bestLap: number | null; className?: string;
}

function tempToColor(temp: number): string {
  if (temp < 60) { const t = Math.max(0, temp) / 60; return `rgb(${Math.round(30)},${Math.round(100 + t * 80)},${Math.round(220 - t * 40)})`; }
  if (temp < 100) { const t = (temp - 60) / 40; return `rgb(${Math.round(30 + t * 20)},${Math.round(180 + t * 50)},${Math.round(180 - t * 140)})`; }
  if (temp < 120) { const t = (temp - 100) / 20; return `rgb(${Math.round(50 + t * 190)},${Math.round(230 - t * 40)},${Math.round(40 - t * 10)})`; }
  const t = Math.min(1, (temp - 120) / 30); return `rgb(${Math.round(240 + t * 15)},${Math.round(190 - t * 140)},${Math.round(30 - t * 10)})`;
}

function avg(arr: number[]): number {
  if (!arr || !arr.length) return 0;
  let s = 0; for (let i = 0; i < arr.length; i++) s += arr[i]; return s / arr.length;
}

function drawRoundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath(); ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r); ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.arcTo(x, y + h, x, y + h - r, r); ctx.arcTo(x, y, x + r, y, r); ctx.closePath();
}

export function TireHeatmapChart({ sessionId, gpsLaps, bestLap, className = '' }: TireHeatmapChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<TireTempData | null>(null);
  const [selectedLap, setSelectedLap] = useState<number>(bestLap ?? gpsLaps[0] ?? 0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!selectedLap) { dataRef.current = null; return; }
    setLoading(true); setError(null);
    try {
      const d = await apiFetch<TireTempData>(`/sessions/${encodeURIComponent(sessionId)}/tire-temps?lap=${selectedLap}`);
      if (!d.available) { dataRef.current = null; setError('No tire temperature data available for this lap'); }
      else dataRef.current = d;
    } catch (e) { dataRef.current = null; setError(e instanceof Error ? e.message : 'Failed to load tire temps'); }
    finally { setLoading(false); }
  }, [sessionId, selectedLap]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current; if (!canvas) return;
    const data = dataRef.current;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement?.clientWidth || canvas.clientWidth || 700, h = 280;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#1a1f2e'; ctx.fillRect(0, 0, w, h);

    if (!data) {
      ctx.fillStyle = '#8b949e'; ctx.font = '13px -apple-system, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('No tire temperature data available', w / 2, h / 2); return;
    }

    const tires = [
      { label: 'FL', zone: data.fl }, { label: 'FR', zone: data.fr },
      { label: 'RL', zone: data.rl }, { label: 'RR', zone: data.rr },
    ];
    const avgs = tires.map((t) => ({
      label: t.label, i: avg(t.zone.i), m: avg(t.zone.m), o: avg(t.zone.o),
      total: (avg(t.zone.i) + avg(t.zone.m) + avg(t.zone.o)) / 3,
    }));
    const hasZones = tires.some((t) => t.zone.i.length > 0 && t.zone.m.length > 0 && t.zone.o.length > 0);

    const tireW = Math.min(120, (w - 100) / 3), tireH = 70;
    const gapX = tireW * 0.6, gapY = 30;
    const gridW = tireW * 2 + gapX, gridH = tireH * 2 + gapY;
    const sx = (w - gridW) / 2, sy = 40;
    const positions = [
      { x: sx, y: sy }, { x: sx + tireW + gapX, y: sy },
      { x: sx, y: sy + tireH + gapY }, { x: sx + tireW + gapX, y: sy + tireH + gapY },
    ];
    const R = 8;

    for (let ti = 0; ti < 4; ti++) {
      const p = positions[ti], a = avgs[ti];
      if (hasZones) {
        const sW = tireW / 3, zones = [a.i, a.m, a.o], zL = ['I', 'M', 'O'];
        for (let z = 0; z < 3; z++) {
          const zx = p.x + z * sW; ctx.fillStyle = tempToColor(zones[z]);
          if (z === 0) {
            ctx.beginPath(); ctx.moveTo(zx + R, p.y); ctx.lineTo(zx + sW, p.y); ctx.lineTo(zx + sW, p.y + tireH);
            ctx.lineTo(zx + R, p.y + tireH); ctx.arcTo(zx, p.y + tireH, zx, p.y + tireH - R, R);
            ctx.lineTo(zx, p.y + R); ctx.arcTo(zx, p.y, zx + R, p.y, R); ctx.fill();
          } else if (z === 2) {
            ctx.beginPath(); ctx.moveTo(zx, p.y); ctx.lineTo(zx + sW - R, p.y);
            ctx.arcTo(zx + sW, p.y, zx + sW, p.y + R, R); ctx.lineTo(zx + sW, p.y + tireH - R);
            ctx.arcTo(zx + sW, p.y + tireH, zx + sW - R, p.y + tireH, R); ctx.lineTo(zx, p.y + tireH); ctx.fill();
          } else { ctx.fillRect(zx, p.y, sW, tireH); }
          ctx.fillStyle = '#1a1a2e'; ctx.font = 'bold 9px -apple-system, sans-serif';
          ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillText(zL[z], zx + sW / 2, p.y + 4);
          ctx.font = '10px -apple-system, sans-serif'; ctx.textBaseline = 'bottom';
          ctx.fillText(zones[z].toFixed(0), zx + sW / 2, p.y + tireH - 4);
        }
      } else {
        ctx.fillStyle = tempToColor(a.total); drawRoundedRect(ctx, p.x, p.y, tireW, tireH, R); ctx.fill();
      }
      // Center temp
      ctx.fillStyle = '#1a1a2e'; ctx.font = 'bold 16px -apple-system, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(a.total.toFixed(0) + '\u00B0', p.x + tireW / 2, p.y + tireH / 2);
      // Label above
      ctx.fillStyle = '#e0e0e0'; ctx.font = 'bold 11px -apple-system, sans-serif';
      ctx.textBaseline = 'bottom'; ctx.fillText(a.label, p.x + tireW / 2, p.y - 4);
      // Border
      ctx.strokeStyle = 'rgba(255,255,255,0.15)'; ctx.lineWidth = 1;
      drawRoundedRect(ctx, p.x, p.y, tireW, tireH, R); ctx.stroke();
    }

    // Balance indicators
    const by = sy + gridH + 30;
    const flFr = avgs[0].total - avgs[1].total, rlRr = avgs[2].total - avgs[3].total;
    const frAvg = (avgs[0].total + avgs[1].total) / 2, reAvg = (avgs[2].total + avgs[3].total) / 2;
    const items = [{ l: 'FL-FR', v: flFr }, { l: 'RL-RR', v: rlRr }, { l: 'Front-Rear', v: frAvg - reAvg }];
    const bSp = w / 4;
    ctx.font = '11px -apple-system, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (let b = 0; b < 3; b++) {
      const bx = bSp * (b + 1), it = items[b];
      const col = Math.abs(it.v) > 10 ? '#ef4444' : Math.abs(it.v) > 5 ? '#f59e0b' : '#10b981';
      ctx.fillStyle = '#8b949e'; ctx.fillText(it.l, bx, by);
      ctx.fillStyle = col; ctx.font = 'bold 13px -apple-system, sans-serif';
      ctx.fillText((it.v >= 0 ? '+' : '') + it.v.toFixed(1) + '\u00B0C', bx, by + 16);
      ctx.font = '11px -apple-system, sans-serif';
    }
  }, []);

  useEffect(() => { if (!loading) draw(); }, [loading, draw]);
  useEffect(() => {
    const c = containerRef.current; if (!c) return;
    const ro = new ResizeObserver(() => draw()); ro.observe(c); return () => ro.disconnect();
  }, [draw]);

  return (
    <div ref={containerRef} className={className} role="img" aria-label="Tire heatmap showing temperature distribution across tires">
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
        <canvas ref={canvasRef} style={{ width: '100%', height: '280px', display: 'block' }} />
      </div>
    </div>
  );
}
