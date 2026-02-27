'use client';

interface ProgressRingProps {
  value: number;
  max: number | null;
  label: string;
  size?: number;
  strokeWidth?: number;
}

export function ProgressRing({
  value,
  max,
  label,
  size = 80,
  strokeWidth = 6,
}: ProgressRingProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = max ? Math.min(value / max, 1) : 0;
  const dashOffset = circumference * (1 - progress);

  const isUnlimited = max === null;
  const isNearLimit = max !== null && value / max >= 0.8;

  const progressColor = isNearLimit ? '#E53E3E' : '#B6FF2E'; // safety-red or acid-green

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          {/* Background ring */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            className="text-steel/20"
          />
          {/* Progress ring */}
          {!isUnlimited && (
            <circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={progressColor}
              strokeWidth={strokeWidth}
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              className="transition-all duration-500"
            />
          )}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-sm font-telemetry text-chalk">
            {isUnlimited ? '\u221E' : value}
          </span>
          {!isUnlimited && (
            <span className="text-[10px] text-steel font-body">/ {max}</span>
          )}
        </div>
      </div>
      <span className="text-xs font-body text-steel text-center">{label}</span>
    </div>
  );
}
