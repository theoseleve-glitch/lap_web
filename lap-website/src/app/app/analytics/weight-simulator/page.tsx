'use client';

import { useState, useCallback } from 'react';
import { PageHeader, ChartPanel } from '@/components/app';
import { useCanvas } from '@/hooks/useCanvas';

/* ---------- physics model ---------- */

// Approximate lap time delta per kg of extra weight.
// For a typical kart on a 40-60s circuit, ~0.03-0.05s per kg.
const SECONDS_PER_KG = 0.04;

function computeDelta(driverKg: number, kartKg: number, ballastKg: number, baseWeight: number): number {
  const totalWeight = driverKg + kartKg + ballastKg;
  return (totalWeight - baseWeight) * SECONDS_PER_KG;
}

/* ---------- component ---------- */

export default function WeightSimulatorPage() {
  const [driverWeight, setDriverWeight] = useState(75);
  const [kartWeight, setKartWeight] = useState(80);
  const [ballast, setBallast] = useState(0);
  const [baseWeight] = useState(155); // reference total weight (driver + kart)

  const totalWeight = driverWeight + kartWeight + ballast;
  const delta = computeDelta(driverWeight, kartWeight, ballast, baseWeight);

  /* ---------- projection chart ---------- */
  const drawChart = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, width, height);

      const pad = { top: 24, right: 24, bottom: 40, left: 56 };
      const drawW = width - pad.left - pad.right;
      const drawH = height - pad.top - pad.bottom;

      // Plot: weight offset (kg) vs delta time (s)
      const rangeKg = 30; // -15 to +15 from base
      const minKg = -rangeKg / 2;
      const maxKg = rangeKg / 2;
      const minDelta = minKg * SECONDS_PER_KG;
      const maxDelta = maxKg * SECONDS_PER_KG;

      const toX = (kg: number) => pad.left + ((kg - minKg) / (maxKg - minKg)) * drawW;
      const toY = (d: number) => pad.top + drawH - ((d - minDelta) / (maxDelta - minDelta)) * drawH;

      // Grid
      ctx.strokeStyle = '#8A8F9818';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = pad.top + (i / 4) * drawH;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        ctx.stroke();
      }

      // Zero line
      ctx.strokeStyle = '#8A8F9840';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      const zeroY = toY(0);
      ctx.beginPath();
      ctx.moveTo(pad.left, zeroY);
      ctx.lineTo(width - pad.right, zeroY);
      ctx.stroke();
      ctx.setLineDash([]);

      // Line: delta per kg
      ctx.beginPath();
      ctx.moveTo(toX(minKg), toY(minDelta));
      ctx.lineTo(toX(maxKg), toY(maxDelta));
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Current position marker
      const currentOffset = totalWeight - baseWeight;
      if (currentOffset >= minKg && currentOffset <= maxKg) {
        const cx = toX(currentOffset);
        const cy = toY(currentOffset * SECONDS_PER_KG);
        ctx.beginPath();
        ctx.arc(cx, cy, 6, 0, Math.PI * 2);
        ctx.fillStyle = '#FF6A00';
        ctx.fill();
        ctx.strokeStyle = '#FF6A00';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Label
        ctx.fillStyle = '#F3F0E8';
        ctx.font = '10px "IBM Plex Mono", monospace';
        ctx.textAlign = 'left';
        const sign = delta >= 0 ? '+' : '';
        ctx.fillText(`${sign}${delta.toFixed(2)}s`, cx + 10, cy - 4);
      }

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Weight Offset from Base (kg)', width / 2, height - 6);
      ctx.save();
      ctx.translate(14, height / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText('Lap Time Delta (s)', 0, 0);
      ctx.restore();

      // Tick labels
      for (let i = 0; i <= 6; i++) {
        const kg = minKg + (i / 6) * (maxKg - minKg);
        ctx.textAlign = 'center';
        ctx.fillText(`${kg >= 0 ? '+' : ''}${kg.toFixed(0)}`, toX(kg), height - pad.bottom + 14);
      }
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const d = minDelta + (i / 4) * (maxDelta - minDelta);
        const y = pad.top + drawH - (i / 4) * drawH;
        ctx.fillText(`${d >= 0 ? '+' : ''}${d.toFixed(2)}`, pad.left - 6, y + 3);
      }
    },
    [totalWeight, baseWeight, delta],
  );

  const chartRef = useCanvas(drawChart, [drawChart]);

  return (
    <div>
      <PageHeader
        title="Weight Simulator"
        subtitle="Estimate lap time impact of weight changes"
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Input panel */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-5">
          <h3 className="font-body text-chalk text-sm font-medium mb-4">Configuration</h3>

          <div className="mb-4">
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              Driver Weight (kg)
            </label>
            <input
              type="number"
              value={driverWeight}
              onChange={(e) => setDriverWeight(Number(e.target.value))}
              min={30}
              max={150}
              step={1}
              className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 transition-colors"
            />
          </div>

          <div className="mb-4">
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              Kart Weight (kg)
            </label>
            <input
              type="number"
              value={kartWeight}
              onChange={(e) => setKartWeight(Number(e.target.value))}
              min={50}
              max={200}
              step={1}
              className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 transition-colors"
            />
          </div>

          <div className="mb-6">
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              Ballast (kg)
            </label>
            <input
              type="number"
              value={ballast}
              onChange={(e) => setBallast(Number(e.target.value))}
              min={0}
              max={50}
              step={0.5}
              className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 transition-colors"
            />
          </div>

          {/* Results */}
          <div className="border-t border-steel/20 pt-4 space-y-3">
            <div className="flex justify-between items-baseline">
              <span className="text-steel font-telemetry text-xs uppercase">Total Weight</span>
              <span className="font-monument text-lg text-chalk">{totalWeight.toFixed(1)} kg</span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-steel font-telemetry text-xs uppercase">vs Base ({baseWeight} kg)</span>
              <span className={`font-monument text-lg ${delta > 0 ? 'text-safety-red' : delta < 0 ? 'text-acid-green' : 'text-steel'}`}>
                {delta >= 0 ? '+' : ''}{(totalWeight - baseWeight).toFixed(1)} kg
              </span>
            </div>
            <div className="flex justify-between items-baseline">
              <span className="text-steel font-telemetry text-xs uppercase">Est. Delta</span>
              <span className={`font-monument text-2xl ${delta > 0 ? 'text-safety-red' : delta < 0 ? 'text-acid-green' : 'text-steel'}`}>
                {delta >= 0 ? '+' : ''}{delta.toFixed(3)}s
              </span>
            </div>
          </div>
        </div>

        {/* Chart */}
        <div className="lg:col-span-2">
          <ChartPanel
            title="Projected Lap Time Change"
            subtitle={`${SECONDS_PER_KG}s per kg — orange dot = current setup`}
          >
            <div className="h-80 relative">
              <canvas ref={chartRef} className="absolute inset-0 w-full h-full" />
            </div>
          </ChartPanel>
        </div>
      </div>
    </div>
  );
}
