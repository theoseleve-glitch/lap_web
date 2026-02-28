'use client';

interface ModeSelectorProps {
  value: 'b2c' | 'b2b';
  onChange: (value: 'b2c' | 'b2b') => void;
  className?: string;
}

export function ModeSelector({ value, onChange, className = '' }: ModeSelectorProps) {
  const isB2B = value === 'b2b';

  return (
    <div
      className={`inline-flex items-center gap-4 ${className}`}
      role="switch"
      aria-checked={isB2B}
      aria-label="Toggle between driver and circuit mode"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onChange(isB2B ? 'b2c' : 'b2b');
        }
      }}
    >
      <span
        className={`font-telemetry text-[11px] tracking-[0.12em] uppercase cursor-pointer transition-colors duration-[420ms] ${
          !isB2B ? 'text-chalk' : 'text-steel'
        }`}
        onClick={() => onChange('b2c')}
      >
        DRIVERS
      </span>

      <button
        className="relative w-[56px] h-[28px] bg-concrete border-2 border-steel rounded-none cursor-pointer"
        style={{ minHeight: '44px', minWidth: '56px' }}
        onClick={() => onChange(isB2B ? 'b2c' : 'b2b')}
        aria-label={`Switch to ${isB2B ? 'driver' : 'circuit'} mode`}
      >
        <span
          className="absolute top-1/2 -translate-y-1/2 w-[20px] h-[20px] bg-chalk transition-all duration-[420ms] ease-[cubic-bezier(0.22,1.2,0.36,1)]"
          style={{ left: isB2B ? 'calc(100% - 24px)' : '4px' }}
        />
      </button>

      <span
        className={`font-telemetry text-[11px] tracking-[0.12em] uppercase cursor-pointer transition-colors duration-[420ms] ${
          isB2B ? 'text-chalk' : 'text-steel'
        }`}
        onClick={() => onChange('b2b')}
      >
        CIRCUITS
      </span>
    </div>
  );
}
