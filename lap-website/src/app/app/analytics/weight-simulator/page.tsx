'use client';

import { useState, useCallback } from 'react';
import { PageHeader, ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

/* ---------- physics model ---------- */

const SECONDS_PER_KG = 0.04;

function computeDelta(driverKg: number, kartKg: number, ballastKg: number, baseWeight: number): number {
  return (driverKg + kartKg + ballastKg - baseWeight) * SECONDS_PER_KG;
}

/* ---------- chart ---------- */

const PAD = { top: 24, right: 24, bottom: 40, left: 56 };

/* ---------- component ---------- */

export default function WeightSimulatorPage() {
  const [driverWeight, setDriverWeight] = useState(75);
  const [kartWeight, setKartWeight] = useState(80);
  const [ballast, setBallast] = useState(0);
  const [baseWeight] = useState(155);

  const totalWeight = driverWeight + kartWeight + ballast;
  const delta = computeDelta(driverWeight, kartWeight, ballast, baseWeight);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number, hover: HoverPoint | null) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, width, height);

      const drawW = width - PAD.left - PAD.right;
      const drawH = height - PAD.top - PAD.bottom;

      const rangeKg = 30;
      const minKg = -rangeKg / 2, maxKg = rangeKg / 2;
      const minDelta = minKg * SECONDS_PER_KG, maxDelta = maxKg * SECONDS_PER_KG;

      const toX = (kg: number) => PAD.left + ((kg - minKg) / (maxKg - minKg)) * drawW;
      const toY = (d: number) => PAD.top + drawH - ((d - minDelta) / (maxDelta - minDelta)) * drawH;

      // Grid
      ctx.strokeStyle = '#8A8F9818';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = PAD.top + (i / 4) * drawH;
        ctx.beginPath();
        ctx.moveTo(PAD.left, y);
        ctx.lineTo(width - PAD.right, y);
        ctx.stroke();
      }

      // Zero line
      ctx.strokeStyle = '#8A8F9840';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(PAD.left, toY(0));
      ctx.lineTo(width - PAD.right, toY(0));
      ctx.stroke();
      ctx.setLineDash([]);

      // Delta line
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

        ctx.fillStyle = '#F3F0E8';
        ctx.font = '10px "IBM Plex Mono", monospace';
        ctx.textAlign = 'left';
        const sign = delta >= 0 ? '+' : '';
        ctx.fillText(`${sign}${delta.toFixed(2)}s`, cx + 10, cy - 4);
      }

      // Hover indicator
      if (hover) {
        const hoverKg = minKg + hover.nx * (maxKg - minKg);
        const hoverDelta = hoverKg * SECONDS_PER_KG;
        const hx = toX(hoverKg), hy = toY(hoverDelta);
        ctx.beginPath();
        ctx.arc(hx, hy, 5, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 1.5;
        ctx.stroke();
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
        ctx.fillText(`${kg >= 0 ? '+' : ''}${kg.toFixed(0)}`, toX(kg), height - PAD.bottom + 14);
      }
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const d = minDelta + (i / 4) * (maxDelta - minDelta);
        const y = PAD.top + drawH - (i / 4) * drawH;
        ctx.fillText(`${d >= 0 ? '+' : ''}${d.toFixed(2)}`, PAD.left - 6, y + 3);
      }
    },
    [totalWeight, baseWeight, delta],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const rangeKg = 30;
      const minKg = -rangeKg / 2, maxKg = rangeKg / 2;
      const hoverKg = minKg + hover.nx * (maxKg - minKg);
      const hoverDelta = hoverKg * SECONDS_PER_KG;
      return {
        lines: [
          { label: 'Offset', value: `${hoverKg >= 0 ? '+' : ''}${hoverKg.toFixed(1)} kg`, color: '#B6FF2E' },
          { label: 'Delta', value: `${hoverDelta >= 0 ? '+' : ''}${hoverDelta.toFixed(3)}s`, color: hoverDelta > 0 ? '#FF2A2A' : '#B6FF2E' },
        ],
      };
    },
    [],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [totalWeight, baseWeight, delta],
    padding: PAD,
    getTooltipData,
    crosshair: true,
    crosshairColor: 'rgba(182, 255, 46, 0.2)',
  });

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
            <div ref={containerRef} className="h-80 relative">
              <canvas ref={canvasRef} className="w-full h-full" />
              <ChartTooltip tooltip={tooltip} />
            </div>
          </ChartPanel>
        </div>
      </div>
    </div>
  );
}
