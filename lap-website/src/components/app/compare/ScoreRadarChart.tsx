/**
 * ScoreRadarChart.tsx — Spider/radar chart comparing scoring dimensions.
 *
 * Draws a canvas-based radar chart with 5 axes (Pace, Consistency,
 * Execution, Robustness, Adaptation) overlaying two sessions' scores.
 */
'use client';

import { useRef, useEffect } from 'react';

interface ScoreData {
  pace_score: number | null;
  pace_max: number | null;
  consistency_score: number | null;
  consistency_max: number | null;
  execution_score: number | null;
  execution_max: number | null;
  robustness_score: number | null;
  robustness_max: number | null;
  adaptation_score: number | null;
}

interface Props {
  scoresA: ScoreData | null;
  scoresB: ScoreData | null;
  colorA?: string;
  colorB?: string;
  size?: number;
}

const DIMENSIONS = [
  { key: 'pace', label: 'Pace' },
  { key: 'consistency', label: 'Consistency' },
  { key: 'execution', label: 'Execution' },
  { key: 'robustness', label: 'Robustness' },
  { key: 'adaptation', label: 'Adaptation' },
] as const;

function getNormalized(scores: ScoreData | null): number[] {
  if (!scores) return [0, 0, 0, 0, 0];
  const vals: { score: number | null; max: number }[] = [
    { score: scores.pace_score, max: scores.pace_max ?? 25 },
    { score: scores.consistency_score, max: scores.consistency_max ?? 25 },
    { score: scores.execution_score, max: scores.execution_max ?? 20 },
    { score: scores.robustness_score, max: scores.robustness_max ?? 15 },
    { score: scores.adaptation_score, max: Math.max(1, 100 - (scores.pace_max ?? 25) - (scores.consistency_max ?? 25) - (scores.execution_max ?? 20) - (scores.robustness_max ?? 15)) },
  ];
  return vals.map(({ score, max }) => score != null && max > 0 ? Math.min(score / max, 1) : 0);
}

export function ScoreRadarChart({
  scoresA,
  scoresB,
  colorA = '#ff6b35',
  colorB = '#58a6ff',
  size = 280,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    ctx.scale(dpr, dpr);

    const cx = size / 2;
    const cy = size / 2;
    const radius = size / 2 - 40;
    const n = DIMENSIONS.length;
    const angleStep = (2 * Math.PI) / n;
    const startAngle = -Math.PI / 2; // top

    // Clear
    ctx.clearRect(0, 0, size, size);

    // Draw grid rings
    for (let ring = 1; ring <= 4; ring++) {
      const r = (ring / 4) * radius;
      ctx.strokeStyle = 'rgba(148, 148, 148, 0.15)';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      for (let i = 0; i <= n; i++) {
        const angle = startAngle + i * angleStep;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.stroke();
    }

    // Draw axis lines + labels
    ctx.fillStyle = '#949494';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'center';
    for (let i = 0; i < n; i++) {
      const angle = startAngle + i * angleStep;
      const x = cx + radius * Math.cos(angle);
      const y = cy + radius * Math.sin(angle);
      ctx.strokeStyle = 'rgba(148, 148, 148, 0.3)';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(x, y);
      ctx.stroke();

      // Label
      const lx = cx + (radius + 18) * Math.cos(angle);
      const ly = cy + (radius + 18) * Math.sin(angle);
      ctx.textBaseline = angle < -0.3 ? 'bottom' : angle > 2.5 ? 'bottom' : 'middle';
      ctx.fillText(DIMENSIONS[i]!.label, lx, ly);
    }

    // Draw data polygon
    function drawPoly(values: number[], color: string, alpha: number) {
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const angle = startAngle + i * angleStep;
        const r = values[i]! * radius;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fillStyle = color.replace(')', `,${alpha})`).replace('rgb', 'rgba');
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.stroke();

      // Dots
      for (let i = 0; i < n; i++) {
        const angle = startAngle + i * angleStep;
        const r = values[i]! * radius;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(cx + r * Math.cos(angle), cy + r * Math.sin(angle), 3, 0, 2 * Math.PI);
        ctx.fill();
      }
    }

    const valsA = getNormalized(scoresA);
    const valsB = getNormalized(scoresB);

    // Helper for hex to rgb
    function hexToRgb(hex: string): string {
      const r = parseInt(hex.slice(1, 3), 16);
      const g = parseInt(hex.slice(3, 5), 16);
      const b = parseInt(hex.slice(5, 7), 16);
      return `rgb(${r},${g},${b})`;
    }

    drawPoly(valsB, hexToRgb(colorB), 0.1);
    drawPoly(valsA, hexToRgb(colorA), 0.15);
  }, [scoresA, scoresB, colorA, colorB, size]);

  return (
    <div className="flex justify-center">
      <canvas ref={canvasRef} style={{ width: size, height: size }} />
    </div>
  );
}
