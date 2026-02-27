'use client';

import { useRef, useEffect } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { background } from '@/experience/motion/springs';

const SPOKE_COUNT = 8;
const OUTER_RADIUS = 60;
const INNER_RADIUS = 40;
const HUB_RADIUS = 12;

export function PitWheel() {
  const rotationRef = useRef(0);
  const velocityRef = useRef(0);
  const svgRef = useRef<SVGGElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    let mounted = true;

    const animate = () => {
      if (!mounted) return;

      const { scrollVelocity, trackPath } = useKernelStore.getState();

      // Drive velocity from scroll * velocityMultiplier
      const input = scrollVelocity * trackPath.velocityMultiplier;
      velocityRef.current += input * 2;

      // Apply wheel friction for deceleration
      velocityRef.current *= background.wheelFriction;

      // Clamp very small values to zero
      if (Math.abs(velocityRef.current) < 0.001) {
        velocityRef.current = 0;
      }

      // Accumulate rotation (degrees)
      rotationRef.current += velocityRef.current * 3;

      // Apply to SVG group
      if (svgRef.current) {
        svgRef.current.setAttribute(
          'transform',
          `rotate(${rotationRef.current})`,
        );
      }

      rafRef.current = requestAnimationFrame(animate);
    };

    rafRef.current = requestAnimationFrame(animate);

    return () => {
      mounted = false;
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // Generate spokes
  const spokes = Array.from({ length: SPOKE_COUNT }, (_, i) => {
    const angle = (i / SPOKE_COUNT) * Math.PI * 2;
    const x1 = Math.cos(angle) * HUB_RADIUS;
    const y1 = Math.sin(angle) * HUB_RADIUS;
    const x2 = Math.cos(angle) * INNER_RADIUS;
    const y2 = Math.sin(angle) * INNER_RADIUS;
    return { x1, y1, x2, y2, key: i };
  });

  return (
    <div
      className="absolute pointer-events-none"
      style={{ zIndex: 0 }}
      aria-hidden="true"
    >
      <svg
        width={OUTER_RADIUS * 2 + 20}
        height={OUTER_RADIUS * 2 + 20}
        viewBox={`${-(OUTER_RADIUS + 10)} ${-(OUTER_RADIUS + 10)} ${(OUTER_RADIUS + 10) * 2} ${(OUTER_RADIUS + 10) * 2}`}
        className="opacity-[0.08]"
      >
        <g ref={svgRef}>
          {/* Outer tire */}
          <circle
            cx={0}
            cy={0}
            r={OUTER_RADIUS}
            fill="none"
            stroke="currentColor"
            strokeWidth={8}
            className="text-steel"
          />

          {/* Inner rim */}
          <circle
            cx={0}
            cy={0}
            r={INNER_RADIUS}
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            className="text-steel"
          />

          {/* Hub */}
          <circle
            cx={0}
            cy={0}
            r={HUB_RADIUS}
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            className="text-chalk"
          />

          {/* Center dot */}
          <circle
            cx={0}
            cy={0}
            r={3}
            fill="currentColor"
            className="text-chalk"
          />

          {/* Spokes */}
          {spokes.map((s) => (
            <line
              key={s.key}
              x1={s.x1}
              y1={s.y1}
              x2={s.x2}
              y2={s.y2}
              stroke="currentColor"
              strokeWidth={1.5}
              className="text-steel"
            />
          ))}

          {/* Tread marks on outer tire */}
          {Array.from({ length: 16 }, (_, i) => {
            const angle = (i / 16) * Math.PI * 2;
            const x1 = Math.cos(angle) * (OUTER_RADIUS - 4);
            const y1 = Math.sin(angle) * (OUTER_RADIUS - 4);
            const x2 = Math.cos(angle) * (OUTER_RADIUS + 4);
            const y2 = Math.sin(angle) * (OUTER_RADIUS + 4);
            return (
              <line
                key={`tread-${i}`}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke="currentColor"
                strokeWidth={1}
                className="text-steel"
              />
            );
          })}
        </g>
      </svg>
    </div>
  );
}
