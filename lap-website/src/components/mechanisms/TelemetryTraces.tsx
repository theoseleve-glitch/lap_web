'use client';

import { TelemetryTracesCanvas } from './TelemetryTracesCanvas';

interface TelemetryTracesProps {
  progress?: number;
  hoveredTrace?: string | null;
  onTraceHover?: (trace: string | null) => void;
  useWebGL?: boolean;
  className?: string;
}

export function TelemetryTraces({
  progress = 1,
  hoveredTrace = null,
  onTraceHover,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  useWebGL = false,
  className = '',
}: TelemetryTracesProps) {
  // Always use Canvas 2D for now — R3F tubes can be wired in Task 16
  // when progressive enhancement is added

  return (
    <div
      className={`relative ${className}`}
      onMouseLeave={() => onTraceHover?.(null)}
    >
      <TelemetryTracesCanvas
        progress={progress}
        hoveredTrace={hoveredTrace}
      />

      {/* Invisible hover zones for trace selection */}
      <div className="absolute inset-0 flex flex-col">
        <div
          className="flex-1 cursor-pointer"
          onMouseEnter={() => onTraceHover?.('speed')}
          aria-label="Speed trace"
        />
        <div
          className="flex-1 cursor-pointer"
          onMouseEnter={() => onTraceHover?.('brake')}
          aria-label="Brake trace"
        />
        <div
          className="flex-1 cursor-pointer"
          onMouseEnter={() => onTraceHover?.('steering')}
          aria-label="Steering trace"
        />
      </div>
    </div>
  );
}
