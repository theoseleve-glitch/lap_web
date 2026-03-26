/**
 * FingerprintChart.tsx — Canvas radar chart showing a driver's performance
 * fingerprint across 6 dimensions (Pace, Consistency, Execution, etc.).
 *
 * Fetches from GET /sessions/:id/fingerprint and renders a filled polygon
 * on a circular 6-spoke grid. No external chart libraries.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api-client';

interface FingerprintData {
  dimensions: string[];
  values: number[];
  style_label?: string;
}

interface FingerprintChartProps {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
  className?: string;
  controlledLap?: boolean;
}

const STEEL = '#c4c4c4';
const ACID = '#b4ff39';
const GRID_COLOR = 'rgba(196,196,196,0.20)';
const RINGS = [25, 50, 75, 100];
const LABEL_FONT = '11px "Space Mono", monospace';
const GRID_FONT = '10px "Space Mono", monospace';

type StatusMsg = string | null;
function StatusBox({ msg, className }: { msg: string; className?: string }) {
  return (
    <div className={className}>
      <div className="text-steel/60 text-sm text-center p-6">{msg}</div>
    </div>
  );
}

export function FingerprintChart({ sessionId, className = '' }: FingerprintChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dataRef = useRef<FingerprintData | null>(null);

  const [loading, setLoading] = useState(true);
  const [statusMsg, setStatusMsg] = useState<StatusMsg>(null);
  const fetchVersionRef = useRef(0);

  // -- Fetch ------------------------------------------------------------------
  useEffect(() => {
    const ver = ++fetchVersionRef.current;
    setLoading(true);
    setStatusMsg(null);
    dataRef.current = null;
    (async () => {
      try {
        const res = await apiFetch<FingerprintData | { available: false; reason_code: string }>(
          `/sessions/${encodeURIComponent(sessionId)}/fingerprint`,
        );
        if (ver !== fetchVersionRef.current) return;
        if ('available' in res && res.available === false) {
          setStatusMsg('No scoring data available for this session.');
        } else {
          dataRef.current = res as FingerprintData;
        }
      } catch (err) {
        if (ver !== fetchVersionRef.current) return;
        setStatusMsg(err instanceof Error ? err.message : 'Failed to load fingerprint');
      }
      setLoading(false);
    })();
  }, [sessionId]);

  // -- Draw -------------------------------------------------------------------
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const fp = dataRef.current;
    const w = container.clientWidth;
    const h = Math.max(w * 0.85, 220);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    if (!fp || fp.dimensions.length === 0) return;

    const n = fp.dimensions.length;
    const labelMargin = 48;
    const radius = Math.min(w, h) / 2 - labelMargin;
    const cx = w / 2;
    const cy = h / 2 - (fp.style_label ? 10 : 0);
    const step = (Math.PI * 2) / n;
    const start = -Math.PI / 2; // first spoke points up

    const toXY = (i: number, r: number): [number, number] => {
      const a = start + i * step;
      return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
    };

    // Build data polygon path once, reuse for fill + stroke
    const polyPath = new Path2D();
    const verts: [number, number][] = [];
    for (let i = 0; i < n; i++) {
      const v = Math.max(0, Math.min(100, fp.values[i] ?? 0));
      const [x, y] = toXY(i, (v / 100) * radius);
      verts.push([x, y]);
      if (i === 0) polyPath.moveTo(x, y); else polyPath.lineTo(x, y);
    }
    polyPath.closePath();

    // Grid rings
    ctx.lineWidth = 1;
    ctx.strokeStyle = GRID_COLOR;
    for (const ring of RINGS) {
      const r = (ring / 100) * radius;
      ctx.beginPath();
      for (let i = 0; i <= n; i++) {
        const [x, y] = toXY(i % n, r);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.stroke();
    }

    // Grid value labels (right of top spoke)
    ctx.font = GRID_FONT;
    ctx.fillStyle = STEEL;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    for (const ring of RINGS) {
      ctx.fillText(String(ring), cx + 4, cy - (ring / 100) * radius);
    }

    // Spokes
    for (let i = 0; i < n; i++) {
      const [x, y] = toXY(i, radius);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(x, y);
      ctx.stroke();
    }

    // Data polygon — fill then stroke
    ctx.fillStyle = 'rgba(180, 255, 57, 0.2)';
    ctx.fill(polyPath);
    ctx.strokeStyle = 'rgba(180, 255, 57, 0.8)';
    ctx.lineWidth = 2;
    ctx.stroke(polyPath);

    // Vertex dots
    ctx.fillStyle = ACID;
    for (const [x, y] of verts) {
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
    }

    // Axis labels
    ctx.font = LABEL_FONT;
    ctx.fillStyle = STEEL;
    const pad = 16;
    for (let i = 0; i < n; i++) {
      const a = start + i * step;
      const lx = cx + Math.cos(a) * (radius + pad);
      const ly = cy + Math.sin(a) * (radius + pad);
      const cosA = Math.cos(a);
      const sinA = Math.sin(a);
      ctx.textAlign = cosA < -0.1 ? 'right' : cosA > 0.1 ? 'left' : 'center';
      ctx.textBaseline = sinA < -0.3 ? 'bottom' : sinA > 0.3 ? 'top' : 'middle';
      ctx.fillText(fp.dimensions[i] ?? '', lx, ly);
    }

    // Style label below chart
    if (fp.style_label) {
      ctx.font = LABEL_FONT;
      ctx.fillStyle = ACID;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(fp.style_label, cx, cy + radius + pad + 14);
    }
  }, []);

  // -- Redraw on data change --------------------------------------------------
  useEffect(() => { if (!loading) draw(); }, [loading, draw]);

  // -- Resize observer --------------------------------------------------------
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(container);
    return () => ro.disconnect();
  }, [draw]);

  // -- Render -----------------------------------------------------------------
  if (loading) return <StatusBox msg="Loading fingerprint..." className={className} />;
  if (statusMsg) return <StatusBox msg={statusMsg} className={className} />;

  return (
    <div ref={containerRef} className={className} role="img" aria-label="Driver performance fingerprint radar chart">
      <canvas ref={canvasRef} className="w-full" />
    </div>
  );
}
