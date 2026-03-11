/**
 * CornerGHistogram.tsx — Lateral G-force distribution per corner.
 *
 * Fetches GG data for the best lap and slices lateral acceleration
 * values within each corner's [s_start, s_end] distance range,
 * then draws a histogram of absolute lateral G.
 */
'use client';

import { useEffect, useRef, useState, useMemo } from 'react';
import { api } from '@/lib/api-client';

interface CornerInfo {
  corner_id: number;
  s_start: number;
  s_end: number;
  direction?: 'L' | 'R';
}

interface CornerGHistogramProps {
  sessionId: string;
  corners: CornerInfo[];
  bestLap?: number | null;
}

interface GGData {
  accel_lat: number[];
  distances: number[];
  available: boolean;
}

export function CornerGHistogram({ sessionId, corners, bestLap }: CornerGHistogramProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ggData, setGGData] = useState<GGData | null>(null);
  const [selectedCorner, setSelectedCorner] = useState<number | null>(null);

  // Fetch GG data (uses api client for auth headers + 401 retry)
  useEffect(() => {
    const lap = bestLap ?? 1;

    api.get<{ available: boolean; accel_lat?: number[]; distances?: number[] }>(
      `/sessions/${sessionId}/gg-data?lap=${lap}`,
    )
      .then((d) => {
        if (d.available && d.accel_lat?.length) {
          setGGData({ accel_lat: d.accel_lat, distances: d.distances ?? [], available: true });
        }
      })
      .catch(() => {
        // Non-critical chart — silent fail is acceptable
      });
  }, [sessionId, bestLap]);

  // Compute per-corner lateral G arrays
  const cornerGData = useMemo(() => {
    if (!ggData || !ggData.available) return {};
    const { accel_lat, distances } = ggData;
    const result: Record<number, number[]> = {};

    for (const c of corners) {
      const gValues: number[] = [];
      for (let i = 0; i < distances.length; i++) {
        if (distances[i] >= c.s_start && distances[i] <= c.s_end) {
          const absG = Math.abs(accel_lat[i] / 9.81); // convert m/s² to G
          gValues.push(absG);
        }
      }
      if (gValues.length > 0) {
        result[c.corner_id] = gValues;
      }
    }
    return result;
  }, [ggData, corners]);

  // Auto-select first corner with data
  useEffect(() => {
    if (selectedCorner !== null && cornerGData[selectedCorner]) return;
    const first = corners.find((c) => cornerGData[c.corner_id]);
    if (first) setSelectedCorner(first.corner_id);
  }, [cornerGData, corners, selectedCorner]);

  // Draw histogram
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || selectedCorner === null) return;

    const values = cornerGData[selectedCorner];
    if (!values || values.length < 2) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 300;
    const h = 160;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // Background
    ctx.fillStyle = '#1a1f2e';
    ctx.fillRect(0, 0, w, h);

    // Histogram bins — Sturges' rule
    const nBins = Math.max(5, Math.min(15, Math.ceil(1 + Math.log2(values.length))));
    const minV = Math.min(...values);
    const maxV = Math.max(...values);
    const range = maxV - minV || 0.1;
    const binWidth = range / nBins;

    const bins = new Array(nBins).fill(0);
    for (const v of values) {
      const idx = Math.min(Math.floor((v - minV) / binWidth), nBins - 1);
      bins[idx]++;
    }
    const maxCount = Math.max(...bins);

    // Chart area
    const pad = { top: 20, right: 10, bottom: 30, left: 40 };
    const pW = w - pad.left - pad.right;
    const pH = h - pad.top - pad.bottom;
    const barW = pW / nBins - 2;

    // Draw bars
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    for (let i = 0; i < nBins; i++) {
      const barH = maxCount > 0 ? (bins[i] / maxCount) * pH : 0;
      const x = pad.left + (pW / nBins) * i + 1;
      const y = pad.top + pH - barH;

      // Color: higher G = more intense green
      const binCenter = minV + binWidth * (i + 0.5);
      const intensity = (binCenter - minV) / range;
      ctx.fillStyle = `rgba(61, 220, 132, ${0.3 + intensity * 0.6})`;
      ctx.fillRect(x, y, barW, barH);
    }

    // Mean line
    const meanX = pad.left + ((mean - minV) / range) * pW;
    ctx.strokeStyle = '#ff8c42';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(meanX, pad.top);
    ctx.lineTo(meanX, pad.top + pH);
    ctx.stroke();
    ctx.setLineDash([]);

    // X axis labels (G values)
    ctx.fillStyle = '#8b949e';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let i = 0; i <= nBins; i += Math.max(1, Math.floor(nBins / 5))) {
      const val = minV + binWidth * i;
      const x = pad.left + (pW / nBins) * i;
      ctx.fillText(val.toFixed(2) + 'G', x, pad.top + pH + 6);
    }

    // Y axis label
    ctx.save();
    ctx.translate(12, pad.top + pH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.fillText('Count', 0, 0);
    ctx.restore();

    // Mean label
    ctx.fillStyle = '#ff8c42';
    ctx.font = '9px -apple-system, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(`Avg: ${mean.toFixed(2)}G`, meanX + 4, pad.top + 2);
  }, [selectedCorner, cornerGData]);

  if (!ggData?.available || Object.keys(cornerGData).length === 0) {
    return (
      <div className="text-steel/60 text-sm text-center p-4">
        No lateral G data available for corner histogram
      </div>
    );
  }

  return (
    <div>
      {/* Corner selector pills */}
      <div className="flex gap-1.5 flex-wrap mb-3">
        {corners
          .filter((c) => cornerGData[c.corner_id])
          .map((c) => (
            <button
              key={c.corner_id}
              type="button"
              onClick={() => setSelectedCorner(c.corner_id)}
              className={`text-xs px-2 py-0.5 rounded font-body transition-colors ${
                selectedCorner === c.corner_id
                  ? 'bg-acid-green/20 text-acid-green border border-acid-green/40'
                  : 'bg-zinc-800 text-steel border border-zinc-700 hover:border-zinc-600'
              }`}
            >
              T{c.corner_id}{c.direction ? ` (${c.direction})` : ''}
            </button>
          ))}
      </div>

      <canvas
        ref={canvasRef}
        className="w-full"
        style={{ height: 160 }}
        aria-label="Histogram of lateral G-force for the selected corner"
      />

      {selectedCorner !== null && cornerGData[selectedCorner] && (
        <div className="flex gap-4 mt-2 text-xs text-steel font-body">
          <span>{cornerGData[selectedCorner].length} data points</span>
          <span>
            Peak: {Math.max(...cornerGData[selectedCorner]).toFixed(2)}G
          </span>
        </div>
      )}
    </div>
  );
}
