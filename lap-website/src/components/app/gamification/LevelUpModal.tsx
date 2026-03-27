'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useFocusTrap } from '@/hooks/useFocusTrap';

/* ── Types ────────────────────────────────────────────────── */

interface LevelUpModalProps {
  oldLevel: number;
  newLevel: number;
  totalXp: number;
  sessionXp?: number;
  onClose: () => void;
}

/* ── SVG Arc Helpers ──────────────────────────────────────── */

const RADIUS = 62;
const CX = 70;
const CY = 70;
const START_ANGLE = 135;
const END_ANGLE = 405;
const ARC_LENGTH = END_ANGLE - START_ANGLE;

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function describeArc(startA: number, endA: number, r: number) {
  const start = polarToCartesian(CX, CY, r, endA);
  const end = polarToCartesian(CX, CY, r, startA);
  const largeArc = endA - startA <= 180 ? 0 : 1;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y}`;
}

/* ── Component ────────────────────────────────────────────── */

export default function LevelUpModal({
  oldLevel,
  newLevel,
  totalXp,
  sessionXp = 340,
  onClose,
}: LevelUpModalProps) {
  const [phase, setPhase] = useState<'hidden' | 'backdrop' | 'card' | 'gauge' | 'stats' | 'done'>('hidden');
  const containerRef = useRef<HTMLDivElement>(null);
  const accent = '#22C55E';

  const handleClose = useCallback(() => {
    setPhase('hidden');
    setTimeout(onClose, 300);
  }, [onClose]);

  useFocusTrap(containerRef, phase !== 'hidden', handleClose);

  useEffect(() => {
    if (oldLevel === newLevel || newLevel <= 0) return;

    setPhase('backdrop');
    const timers = [
      setTimeout(() => setPhase('card'), 200),
      setTimeout(() => setPhase('gauge'), 400),
      setTimeout(() => setPhase('stats'), 800),
      setTimeout(() => setPhase('done'), 1100),
    ];
    return () => timers.forEach(clearTimeout);
  }, [oldLevel, newLevel]);

  if (oldLevel === newLevel || newLevel <= 0) return null;

  const phaseGte = (target: typeof phase): boolean => {
    const order = ['hidden', 'backdrop', 'card', 'gauge', 'stats', 'done'];
    return order.indexOf(phase) >= order.indexOf(target);
  };

  const bgArc = describeArc(START_ANGLE, END_ANGLE, RADIUS);
  const fillArc = describeArc(START_ANGLE, START_ANGLE + ARC_LENGTH, RADIUS);

  // Tick marks
  const ticks = [...Array(12)].map((_, i) => {
    const angle = START_ANGLE + (ARC_LENGTH / 11) * i;
    const inner = polarToCartesian(CX, CY, RADIUS - 8, angle);
    const outer = polarToCartesian(CX, CY, RADIUS - 4, angle);
    return { inner, outer, key: i };
  });

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-label="Level up"
      style={{
        opacity: phaseGte('backdrop') ? 1 : 0,
        transition: 'opacity 0.3s ease',
      }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-asphalt/[0.92]" onClick={handleClose} />

      {/* Radial glow */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `radial-gradient(ellipse 500px 400px at 50% 42%, ${accent}0D 0%, transparent 70%)`,
        }}
      />

      {/* Card */}
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative w-[480px] max-w-[92vw] rounded-[28px] overflow-hidden"
        style={{
          background: '#141414',
          border: '1px solid rgba(240,237,229,0.06)',
          transform: phaseGte('card') ? 'scale(1) translateY(0)' : 'scale(0.92) translateY(20px)',
          opacity: phaseGte('card') ? 1 : 0,
          transition: 'transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.3s ease',
        }}
      >
        {/* Top accent */}
        <div className="h-[2px]" style={{ background: `linear-gradient(90deg, transparent, ${accent}, transparent)` }} />

        {/* Corner dots */}
        <div className="absolute top-4 left-5 flex gap-[3px] opacity-20">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="w-[3px] h-[3px] rounded-[0.5px]" style={{ backgroundColor: accent }} />
          ))}
        </div>
        <div className="absolute top-4 right-5 flex gap-[3px] opacity-20">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="w-[3px] h-[3px] rounded-[0.5px]" style={{ backgroundColor: accent }} />
          ))}
        </div>

        <div className="flex flex-col items-center px-10 pt-12 pb-10">
          {/* Micro label */}
          <p
            className="font-telemetry text-[10px] uppercase tracking-[0.18em] mb-8"
            style={{
              color: accent,
              opacity: phaseGte('card') ? 1 : 0,
              transform: phaseGte('card') ? 'translateY(0)' : 'translateY(8px)',
              transition: 'opacity 0.4s ease 0.1s, transform 0.4s ease 0.1s',
            }}
          >
            Driver Level Up
          </p>

          {/* Circular gauge with level transition */}
          <div
            className="relative w-[140px] h-[140px] mb-8"
            style={{
              transform: phaseGte('gauge') ? 'scale(1)' : 'scale(0.8)',
              opacity: phaseGte('gauge') ? 1 : 0,
              transition: 'transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.3s ease',
            }}
          >
            <svg viewBox="0 0 140 140" className="w-full h-full">
              {/* Background arc */}
              <path
                d={bgArc}
                fill="none"
                stroke="rgba(240,237,229,0.06)"
                strokeWidth="4"
                strokeLinecap="round"
              />

              {/* Dashed progress arc */}
              <path
                d={fillArc}
                fill="none"
                stroke={accent}
                strokeWidth="4"
                strokeLinecap="round"
                strokeDasharray="6 4"
                opacity="0.7"
              />

              {/* Solid progress arc (static — no framer-motion pathLength) */}
              <path
                d={fillArc}
                fill="none"
                stroke={accent}
                strokeWidth="4"
                strokeLinecap="round"
                style={{ filter: `drop-shadow(0 0 6px ${accent}40)` }}
              />

              {/* Tick marks */}
              {ticks.map(({ inner, outer, key }) => (
                <line
                  key={key}
                  x1={inner.x}
                  y1={inner.y}
                  x2={outer.x}
                  y2={outer.y}
                  stroke="rgba(240,237,229,0.1)"
                  strokeWidth="1"
                />
              ))}
            </svg>

            {/* Level numbers in the center */}
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <div className="flex items-center gap-3">
                <span
                  className="font-monument text-2xl font-bold text-steel"
                  style={{
                    opacity: phaseGte('stats') ? 0.3 : 1,
                    transition: 'opacity 0.4s ease',
                  }}
                >
                  {oldLevel}
                </span>

                {/* Arrow */}
                <svg
                  width="20"
                  height="12"
                  viewBox="0 0 20 12"
                  style={{
                    opacity: phaseGte('gauge') ? 0.5 : 0,
                    transform: phaseGte('gauge') ? 'translateX(0)' : 'translateX(-4px)',
                    transition: 'opacity 0.3s ease 0.2s, transform 0.3s ease 0.2s',
                  }}
                >
                  <path
                    d="M0 6H16M12 1L18 6L12 11"
                    stroke="#949494"
                    strokeWidth="1.5"
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>

                <span
                  className="font-monument text-3xl font-bold"
                  style={{
                    color: accent,
                    filter: `drop-shadow(0 0 8px ${accent}40)`,
                    opacity: phaseGte('stats') ? 1 : 0,
                    transform: phaseGte('stats') ? 'scale(1)' : 'scale(0.5)',
                    transition: 'opacity 0.4s ease, transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)',
                  }}
                >
                  {newLevel}
                </span>
              </div>
            </div>
          </div>

          {/* Stats row */}
          <div
            className="flex items-center gap-6 mb-8 px-6 py-3 rounded-[14px]"
            style={{
              background: 'rgba(240,237,229,0.02)',
              border: '1px solid rgba(240,237,229,0.04)',
              opacity: phaseGte('stats') ? 1 : 0,
              transform: phaseGte('stats') ? 'translateY(0)' : 'translateY(8px)',
              transition: 'opacity 0.4s ease, transform 0.4s ease',
            }}
          >
            <div className="text-center">
              <p className="font-telemetry text-[8px] uppercase tracking-[0.15em] text-steel mb-1">
                Total XP
              </p>
              <p className="font-telemetry text-lg font-bold text-chalk">
                {totalXp.toLocaleString()}
              </p>
            </div>

            <div className="w-[1px] h-8" style={{ backgroundColor: 'rgba(240,237,229,0.06)' }} />

            <div className="text-center">
              <p className="font-telemetry text-[8px] uppercase tracking-[0.15em] text-steel mb-1">
                New Level
              </p>
              <p className="font-telemetry text-lg font-bold" style={{ color: accent }}>
                LV.{String(newLevel).padStart(2, '0')}
              </p>
            </div>

            <div className="w-[1px] h-8" style={{ backgroundColor: 'rgba(240,237,229,0.06)' }} />

            <div className="text-center">
              <p className="font-telemetry text-[8px] uppercase tracking-[0.15em] text-steel mb-1">
                Session
              </p>
              <p className="font-telemetry text-lg font-bold text-gold">
                +{sessionXp}
              </p>
            </div>
          </div>

          {/* Continue */}
          <button
            type="button"
            onClick={handleClose}
            className="px-10 py-3 rounded-[14px] font-telemetry text-[10px] uppercase tracking-[0.15em] cursor-pointer transition-all hover:brightness-110"
            style={{
              color: '#000000',
              backgroundColor: accent,
              opacity: phaseGte('done') ? 1 : 0,
              transform: phaseGte('done') ? 'translateY(0)' : 'translateY(8px)',
              transition: 'opacity 0.4s ease, transform 0.4s ease, filter 0.2s ease',
            }}
          >
            Continue
          </button>
        </div>

        {/* Bottom accent */}
        <div className="h-[1px]" style={{ background: `linear-gradient(90deg, transparent, ${accent}30, transparent)` }} />
      </div>
    </div>
  );
}
