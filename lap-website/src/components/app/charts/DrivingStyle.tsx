'use client';

import { useCallback, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface StyleData {
  labels: string[];
  values: number[];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 30, right: 30, bottom: 30, left: 30 };

export function DrivingStyle({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'style'],
    queryFn: () => api.get<StyleData>(`/sessions/${sessionId}/style`),
  });

  const verticesRef = useRef<{ x: number; y: number; label: string; value: number }[]>([]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.labels.length === 0) return;

      const { labels, values } = data;
      const cx = w / 2, cy = h / 2;
      const radius = Math.max(1, Math.min(cx, cy) - 30);
      const n = labels.length;
      const angleStep = (Math.PI * 2) / Math.max(n, 1);

      // Store vertex positions for tooltip
      const verts: typeof verticesRef.current = [];
      for (let i = 0; i < n; i++) {
        const rawVal = values[i];
        const val = Math.max(0, Math.min(1, Number.isFinite(rawVal) ? rawVal : 0));
        const angle = i * angleStep - Math.PI / 2;
        verts.push({
          x: cx + Math.cos(angle) * val * radius,
          y: cy + Math.sin(angle) * val * radius,
          label: labels[i],
          value: values[i],
        });
      }
      verticesRef.current = verts;

      // Find nearest vertex for hover
      let nearIdx = -1;
      if (hover) {
        let nearDist = Infinity;
        for (let i = 0; i < verts.length; i++) {
          const dx = verts[i].x - hover.x, dy = verts[i].y - hover.y;
          const d = dx * dx + dy * dy;
          if (d < nearDist) { nearDist = d; nearIdx = i; }
        }
        if (nearDist > 900) nearIdx = -1; // 30px radius
      }

      // Grid rings
      for (let ring = 1; ring <= 5; ring++) {
        const r = (ring / 5) * radius;
        ctx.beginPath();
        ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
        ctx.lineWidth = 0.5;
        for (let i = 0; i <= n; i++) {
          const angle = i * angleStep - Math.PI / 2;
          const x = cx + Math.cos(angle) * r;
          const y = cy + Math.sin(angle) * r;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.stroke();
      }

      // Axis lines + labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (let i = 0; i < n; i++) {
        const angle = i * angleStep - Math.PI / 2;
        const xEnd = cx + Math.cos(angle) * radius;
        const yEnd = cy + Math.sin(angle) * radius;

        ctx.beginPath();
        ctx.strokeStyle = i === nearIdx ? 'rgba(182, 255, 46, 0.4)' : 'rgba(138, 143, 152, 0.2)';
        ctx.lineWidth = i === nearIdx ? 1.5 : 0.5;
        ctx.moveTo(cx, cy);
        ctx.lineTo(xEnd, yEnd);
        ctx.stroke();

        const labelR = radius + 15;
        ctx.fillStyle = i === nearIdx ? '#B6FF2E' : '#8A8F98';
        ctx.fillText(labels[i], cx + Math.cos(angle) * labelR, cy + Math.sin(angle) * labelR);
      }

      // Data polygon
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const { x, y } = verts[i];
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fillStyle = '#B6FF2E22';
      ctx.fill();
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Data points
      for (let i = 0; i < n; i++) {
        const isHov = i === nearIdx;
        ctx.beginPath();
        ctx.arc(verts[i].x, verts[i].y, isHov ? 6 : 3, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E';
        ctx.fill();
        if (isHov) {
          ctx.strokeStyle = '#F3F0E8';
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      }
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const verts = verticesRef.current;
      if (verts.length === 0) return null;
      let nearest = 0, nearDist = Infinity;
      for (let i = 0; i < verts.length; i++) {
        const dx = verts[i].x - hover.x, dy = verts[i].y - hover.y;
        const d = dx * dx + dy * dy;
        if (d < nearDist) { nearDist = d; nearest = i; }
      }
      if (nearDist > 900) return null;
      const v = verts[nearest];
      return {
        lines: [
          { label: v.label, value: `${(v.value * 100).toFixed(0)}%`, color: '#B6FF2E' },
        ],
      };
    },
    [],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data],
    padding: PAD,
    getTooltipData,
  });

  return (
    <ChartPanel title="Driving Style" subtitle="Radar chart of style metrics" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
