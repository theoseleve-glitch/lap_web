'use client';

interface TelemetryTracesProps {
  progress?: number;
  hoveredTrace?: string | null;
  onTraceHover?: (trace: string | null) => void;
  useWebGL?: boolean;
  className?: string;
}

export function TelemetryTraces({
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  progress = 1,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  hoveredTrace = null,
  onTraceHover,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  useWebGL = false,
  className = '',
}: TelemetryTracesProps) {
  return (
    <div
      className={`relative ${className}`}
      onMouseLeave={() => onTraceHover?.(null)}
    >
      {/* Canvas telemetry traces removed — being rebuilt */}
      <div className="w-full h-full bg-concrete/50 rounded" />

      {/* Invisible hover zones for trace selection */}
      <div className="absolute inset-0 flex flex-col">
        <div
          className="flex-1 cursor-pointer"
          onMouseEnter={() => onTraceHover?.('speed')}
          aria-label="Speed Trace"
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
