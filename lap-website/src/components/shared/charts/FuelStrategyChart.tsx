/**
 * FuelStrategyChart.tsx — Fuel remaining + consumption rate per lap.
 * Left Y: fuel remaining (kg) green line with fill. Right Y: consumption rate (kg/lap) orange bars.
 * Projected fuel-out dashed red line. Per-lap summary — no hover sync.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';

interface FuelData { laps: number[]; fuel_remaining: number[]; consumption_rate: number[]; available: boolean; }
interface FuelStrategyChartProps {
  sessionId: string; gpsLaps: number[]; bestLap: number | null; className?: string;
}

export function FuelStrategyChart({ sessionId, gpsLaps, bestLap, className = '' }: FuelStrategyChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<FuelData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchVersionRef = useRef(0);
  void gpsLaps; void bestLap; // props for API consistency

  useEffect(() => {
    const ver = ++fetchVersionRef.current;
    setLoading(true); setError(null); dataRef.current = null;
    (async () => {
      try {
        const d = await apiFetch<FuelData>(`/sessions/${encodeURIComponent(sessionId)}/fuel`);
        if (ver !== fetchVersionRef.current) return;
        if (!d.available) { setError('No fuel data available for this session'); }
        else dataRef.current = d;
      } catch (e) {
        if (ver !== fetchVersionRef.current) return;
        setError(e instanceof Error ? e.message : 'Failed to load fuel data');
      }
      setLoading(false);
    })();
  }, [sessionId]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current; if (!canvas) return;
    const data = dataRef.current;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement?.clientWidth || canvas.clientWidth || 700, h = 240;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const pad = { top: 20, right: 58, bottom: 38, left: 58 };
    const pW = w - pad.left - pad.right, pH = h - pad.top - pad.bottom;
    ctx.fillStyle = '#1a1f2e'; ctx.fillRect(0, 0, w, h);

    if (!data || !data.laps || data.laps.length < 1) {
      ctx.fillStyle = '#8b949e'; ctx.font = '13px -apple-system, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('No fuel data available', w / 2, h / 2); return;
    }
    const laps = data.laps, fuel = data.fuel_remaining, rate = data.consumption_rate;
    const xMin = laps[0], xMax = laps[laps.length - 1], lapR = xMax - xMin || 1;
    let fMax = 0; for (let i = 0; i < fuel.length; i++) { if (fuel[i] > fMax) fMax = fuel[i]; }
    fMax = Math.ceil(fMax / 5) * 5 + 5;
    let rMax = 0; for (let i = 0; i < rate.length; i++) { if (rate[i] > rMax) rMax = rate[i]; }
    rMax = Math.ceil(rMax * 10) / 10 + 0.2; if (rMax < 0.5) rMax = 0.5;

    const xPx = (v: number) => pad.left + ((v - xMin) / lapR) * pW;
    const fPx = (v: number) => pad.top + ((fMax - v) / fMax) * pH;
    const rPx = (v: number) => pad.top + ((rMax - v) / rMax) * pH;

    // Grid
    ctx.strokeStyle = '#30363d'; ctx.lineWidth = 0.5;
    const fStep = fMax <= 20 ? 2 : fMax <= 50 ? 5 : fMax <= 100 ? 10 : 20;
    for (let v = 0; v <= fMax; v += fStep) { ctx.beginPath(); ctx.moveTo(pad.left, fPx(v)); ctx.lineTo(w - pad.right, fPx(v)); ctx.stroke(); }
    for (let i = 0; i < laps.length; i++) { ctx.beginPath(); ctx.moveTo(xPx(laps[i]), pad.top); ctx.lineTo(xPx(laps[i]), pad.top + pH); ctx.stroke(); }

    ctx.save(); ctx.beginPath(); ctx.rect(pad.left, pad.top, pW, pH); ctx.clip();
    // Consumption bars
    const barW = laps.length > 1 ? Math.max(6, (pW / laps.length) * 0.5) : 30;
    for (let i = 0; i < laps.length; i++) {
      const cx = xPx(laps[i]), bh = (rate[i] / rMax) * pH, by = pad.top + pH - bh;
      ctx.fillStyle = 'rgba(249,115,22,0.4)'; ctx.fillRect(cx - barW / 2, by, barW, bh);
      ctx.strokeStyle = 'rgba(249,115,22,0.7)'; ctx.lineWidth = 1; ctx.strokeRect(cx - barW / 2, by, barW, bh);
    }
    // Fuel fill
    ctx.beginPath(); ctx.moveTo(xPx(laps[0]), fPx(0));
    for (let i = 0; i < laps.length; i++) ctx.lineTo(xPx(laps[i]), fPx(fuel[i]));
    ctx.lineTo(xPx(laps[laps.length - 1]), fPx(0)); ctx.closePath();
    ctx.fillStyle = 'rgba(16,185,129,0.15)'; ctx.fill();
    // Fuel line
    ctx.strokeStyle = '#10b981'; ctx.lineWidth = 2; ctx.beginPath();
    for (let i = 0; i < laps.length; i++) { const x = xPx(laps[i]), y = fPx(fuel[i]); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); }
    ctx.stroke();
    // Dots
    for (let i = 0; i < laps.length; i++) { ctx.beginPath(); ctx.arc(xPx(laps[i]), fPx(fuel[i]), 3, 0, Math.PI * 2); ctx.fillStyle = '#10b981'; ctx.fill(); }
    // Projected fuel-out
    if (laps.length >= 3) {
      const n = Math.min(3, rate.length); let ar = 0;
      for (let i = rate.length - n; i < rate.length; i++) ar += rate[i]; ar /= n;
      if (ar > 0) {
        const ll = laps[laps.length - 1], lf = fuel[fuel.length - 1], el = ll + lf / ar;
        ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]);
        ctx.beginPath(); ctx.moveTo(xPx(ll), fPx(lf)); ctx.lineTo(xPx(el), fPx(0)); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = '#ef4444'; ctx.font = '10px -apple-system, sans-serif';
        ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
        ctx.fillText('Empty ~L' + el.toFixed(1), Math.min(xPx(el), w - pad.right - 10), fPx(0) - 4);
      }
    }
    ctx.restore();

    // Axis labels
    ctx.fillStyle = '#8b949e'; ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (let v = 0; v <= fMax; v += fStep) ctx.fillText(v.toFixed(0), pad.left - 6, fPx(v));
    ctx.textAlign = 'left';
    const rStep = rMax <= 0.5 ? 0.1 : rMax <= 1 ? 0.2 : rMax <= 2 ? 0.5 : 1;
    for (let v = 0; v <= rMax; v += rStep) ctx.fillText(v.toFixed(1), w - pad.right + 6, rPx(v));
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (let i = 0; i < laps.length; i++) ctx.fillText('L' + laps[i], xPx(laps[i]), pad.top + pH + 6);
    ctx.font = '11px -apple-system, sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('Lap', pad.left + pW / 2, h - 4);
    ctx.save(); ctx.translate(12, pad.top + pH / 2); ctx.rotate(-Math.PI / 2); ctx.fillText('Fuel (kg)', 0, 0); ctx.restore();
    ctx.save(); ctx.translate(w - 8, pad.top + pH / 2); ctx.rotate(Math.PI / 2); ctx.fillText('Rate (kg/lap)', 0, 0); ctx.restore();

    // Legend
    ctx.font = '10px -apple-system, sans-serif'; ctx.textAlign = 'right'; ctx.textBaseline = 'top';
    let lx = w - pad.right;
    const pL = 'Projected', pLW = ctx.measureText(pL).width + 16;
    ctx.setLineDash([4, 3]); ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(lx - pLW, pad.top + 6); ctx.lineTo(lx - pLW + 8, pad.top + 6); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = '#8b949e'; ctx.fillText(pL, lx, pad.top + 2); lx -= pLW + 8;
    const rL = 'Rate', rLW = ctx.measureText(rL).width + 16;
    ctx.fillStyle = 'rgba(249,115,22,0.5)'; ctx.fillRect(lx - rLW, pad.top + 2, 8, 8);
    ctx.fillStyle = '#8b949e'; ctx.fillText(rL, lx, pad.top + 2); lx -= rLW + 8;
    const fL = 'Fuel', fLW = ctx.measureText(fL).width + 16;
    ctx.fillStyle = '#10b981'; ctx.fillRect(lx - fLW, pad.top + 2, 8, 8);
    ctx.fillStyle = '#8b949e'; ctx.fillText(fL, lx, pad.top + 2);
  }, []);

  useEffect(() => { if (!loading) draw(); }, [loading, draw]);
  useEffect(() => {
    const c = containerRef.current; if (!c) return;
    const ro = new ResizeObserver(() => draw()); ro.observe(c); return () => ro.disconnect();
  }, [draw]);

  return (
    <div ref={containerRef} className={className} role="img" aria-label="Fuel strategy chart showing fuel consumption and pit stop planning">
      <div className="flex items-center gap-3 mb-3 flex-wrap text-sm">
        <span className="text-gray-400">Fuel Strategy</span>
        {loading && <span className="text-xs text-steel animate-pulse">Loading...</span>}
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
      <div className="relative" style={{ width: '100%' }}>
        <canvas ref={canvasRef} style={{ width: '100%', height: '240px', display: 'block' }} />
      </div>
    </div>
  );
}
