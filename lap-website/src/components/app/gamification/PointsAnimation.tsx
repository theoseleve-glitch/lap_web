'use client';

import { useEffect, useState } from 'react';

/* ── Types ────────────────────────────────────────────────── */

interface FloatingPoint {
  id: string;
  points: number;
  x: number;
  y: number;
}

interface PointsAnimationProps {
  floatingPoints: FloatingPoint[];
}

/* ── Component ────────────────────────────────────────────── */

export function PointsAnimation({ floatingPoints }: PointsAnimationProps) {
  const [visible, setVisible] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const newVisible: Record<string, boolean> = {};
    floatingPoints.forEach((p) => {
      newVisible[p.id] = true;
    });
    setVisible(newVisible);

    // Fade out after animation
    const timer = setTimeout(() => {
      setVisible({});
    }, 1500);
    return () => clearTimeout(timer);
  }, [floatingPoints]);

  return (
    <div className="fixed inset-0 pointer-events-none z-50">
      {floatingPoints.map((point) => (
        <div
          key={point.id}
          className="absolute flex items-center gap-1 font-telemetry font-bold text-2xl text-marshal-yellow"
          style={{
            left: point.x,
            top: point.y,
            opacity: visible[point.id] ? 1 : 0,
            transform: visible[point.id] ? 'translateY(-100px) scale(1.5)' : 'translateY(0) scale(1)',
            transition: 'opacity 1.5s ease-out, transform 1.5s ease-out',
          }}
        >
          {/* Star icon */}
          <svg width="24" height="24" viewBox="0 0 24 24" fill="#FACC15" stroke="#FACC15" strokeWidth="1">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
          +{point.points}
        </div>
      ))}
    </div>
  );
}
