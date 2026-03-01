'use client';

import { useEffect, useState, useRef } from 'react';
import { api } from '@/lib/api-client';

interface DrivingStyleFeature {
  name: string;
  value: number;
}

interface DrivingStyleData {
  available?: boolean;
  style_label?: string;
  style_confidence?: number;
  features: DrivingStyleFeature[];
  strengths: string[];
  weaknesses: string[];
}

const FEATURE_LABELS: Record<string, string> = {
  trail_braking_depth: 'Trail Braking',
  brake_point_consistency: 'Brake Consistency',
  brake_pressure_buildup_rate: 'Brake Buildup',
  apex_speed_ratio: 'Apex Speed',
  turn_in_aggressiveness: 'Turn-in Aggression',
  throttle_onset_delay_m: 'Throttle Onset',
  exit_acceleration_efficiency: 'Exit Acceleration',
  line_variation_index: 'Line Consistency',
  early_vs_late_stint_pace: 'Stint Endurance',
  smoothness_composite: 'Smoothness',
};

function drawRadar(
  canvas: HTMLCanvasElement,
  features: DrivingStyleFeature[],
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
  const cy = H / 2;
  const R = Math.min(cx, cy) - 30;
  const n = features.length;
  if (n === 0) return;

  const angleStep = (2 * Math.PI) / n;

  // Draw rings
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.lineWidth = 1;
  for (let ring = 1; ring <= 4; ring++) {
    const r = (ring / 4) * R;
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const angle = i * angleStep - Math.PI / 2;
      const x = cx + r * Math.cos(angle);
      const y = cy + r * Math.sin(angle);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Draw axes
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + R * Math.cos(angle), cy + R * Math.sin(angle));
    ctx.stroke();
  }

  // Draw data polygon
  ctx.fillStyle = 'rgba(182, 255, 46, 0.15)';
  ctx.strokeStyle = '#B6FF2E';
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i <= n; i++) {
    const idx = i % n;
    const val = Math.max(0, Math.min(1, features[idx].value));
    const r = val * R;
    const angle = idx * angleStep - Math.PI / 2;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.fill();
  ctx.stroke();

  // Draw labels
  ctx.fillStyle = 'rgba(255,255,255,0.6)';
  ctx.font = '10px system-ui, sans-serif';
  ctx.textAlign = 'center';
  for (let i = 0; i < n; i++) {
    const angle = i * angleStep - Math.PI / 2;
    const labelR = R + 18;
    const x = cx + labelR * Math.cos(angle);
    const y = cy + labelR * Math.sin(angle);
    const label = FEATURE_LABELS[features[i].name] || features[i].name;
    ctx.fillText(label, x, y + 3);
  }
}

export function DrivingStyleSection({ sessionId }: { sessionId: string }) {
  const [data, setData] = useState<DrivingStyleData | null>(null);
  const [loading, setLoading] = useState(true);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .get<DrivingStyleData>(`/sessions/${sessionId}/driving-style`)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [sessionId]);

  // Draw radar when data arrives
  useEffect(() => {
    if (data?.features && canvasRef.current) {
      drawRadar(canvasRef.current, data.features);
    }
  }, [data]);

  if (loading) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-6 animate-pulse">
        <div className="h-4 bg-asphalt rounded w-32 mb-4" />
        <div className="h-48 bg-asphalt rounded" />
      </div>
    );
  }

  if (!data || data.available === false || !data.features?.length) {
    return null; // Graceful hide — no driving style data
  }

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <h2 className="text-lg font-monument text-chalk mb-1">Driving Style</h2>
      {data.style_label && (
        <div className="flex items-center gap-2 mb-4">
          <span className="text-acid-green text-sm font-body">{data.style_label}</span>
          {data.style_confidence != null && (
            <span className="text-steel text-xs font-body">
              ({Math.round(data.style_confidence * 100)}% confidence)
            </span>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Radar chart */}
        <div>
          <canvas
            ref={canvasRef}
            className="w-full"
            style={{ height: 260 }}
          />
        </div>

        {/* Trait bars + lists */}
        <div className="space-y-3">
          {data.features.map((f) => {
            const pct = Math.max(0, Math.min(100, f.value * 100));
            return (
              <div key={f.name}>
                <div className="flex justify-between text-xs mb-0.5">
                  <span className="text-steel font-body">
                    {FEATURE_LABELS[f.name] || f.name}
                  </span>
                  <span className="text-chalk font-telemetry">{pct.toFixed(0)}%</span>
                </div>
                <div className="w-full h-1.5 bg-asphalt rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-acid-green/60"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}

          {/* Strengths/Weaknesses from driving style */}
          {data.strengths?.length > 0 && (
            <div className="pt-2">
              <h4 className="text-xs text-green-400 font-body mb-1">Style Strengths</h4>
              <ul className="space-y-0.5">
                {data.strengths.map((s, i) => (
                  <li key={i} className="text-xs text-chalk/80 font-body">+ {s}</li>
                ))}
              </ul>
            </div>
          )}
          {data.weaknesses?.length > 0 && (
            <div className="pt-2">
              <h4 className="text-xs text-red-400 font-body mb-1">Style Weaknesses</h4>
              <ul className="space-y-0.5">
                {data.weaknesses.map((w, i) => (
                  <li key={i} className="text-xs text-chalk/80 font-body">- {w}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
