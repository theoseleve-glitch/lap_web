'use client';

import { useRef, useEffect } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { background } from '@/experience/motion/springs';

const SPOKE_COUNT = 5;
const OUTER_RADIUS = 60;
const INNER_RADIUS = 40;
const HUB_RADIUS = 12;

// Pre-computed spoke geometry (module-level, never changes)
const SPOKES = Array.from({ length: SPOKE_COUNT }, (_, i) => {
  const angle = (i / SPOKE_COUNT) * Math.PI * 2;
  return {
    x1: Math.cos(angle) * HUB_RADIUS,
    y1: Math.sin(angle) * HUB_RADIUS,
    x2: Math.cos(angle) * INNER_RADIUS,
    y2: Math.sin(angle) * INNER_RADIUS,
    key: i,
  };
});

// Pre-computed tread marks (module-level)
const TREAD_MARKS = Array.from({ length: 16 }, (_, i) => {
  const angle = (i / 16) * Math.PI * 2;
  return {
    x1: Math.cos(angle) * (OUTER_RADIUS - 4),
    y1: Math.sin(angle) * (OUTER_RADIUS - 4),
    x2: Math.cos(angle) * (OUTER_RADIUS + 4),
    y2: Math.sin(angle) * (OUTER_RADIUS + 4),
    key: i,
  };
});

export function PitWheel() {
  const rotationRef = useRef(0);
  const velocityRef = useRef(0);
  const svgRef = useRef<SVGGElement>(null);
  const containerRef = useRef<SVGSVGElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    let mounted = true;

    const animate = () => {
      if (!mounted) return;

      const { scrollVelocity, trackPath, reducedMotion } = useKernelStore.getState();

      // Respect reduced motion — skip rotation updates
      if (reducedMotion) {
        rafRef.current = requestAnimationFrame(animate);
        return;
      }

      // Drive velocity from scroll * velocityMultiplier
      const input = scrollVelocity * trackPath.velocityMultiplier;
      velocityRef.current += input * 2;

      // Apply wheel friction for deceleration
      velocityRef.current *= background.wheelFriction;

      // Cap rotation velocity (pit limiter: max ~360 deg/s at 60fps = 6 deg/frame)
      const maxVelocity = 6;
      if (Math.abs(velocityRef.current) > maxVelocity) {
        velocityRef.current = Math.sign(velocityRef.current) * maxVelocity;
      }

      // Clamp very small values to zero
      if (Math.abs(velocityRef.current) < 0.001) {
        velocityRef.current = 0;
      }

      // Accumulate rotation, normalize to 0-360 to prevent float overflow
      rotationRef.current = (rotationRef.current + velocityRef.current * 3) % 360;

      // Apply rotation to SVG group
      if (svgRef.current) {
        svgRef.current.setAttribute('transform', `rotate(${rotationRef.current})`);
      }

      // Opacity pulse: sin(time * 0.5) * 0.02 + 0.08
      if (containerRef.current) {
        const t = performance.now() * 0.001;
        const opacity = Math.sin(t * 0.5) * 0.02 + 0.08;
        containerRef.current.style.opacity = String(opacity);
      }

      rafRef.current = requestAnimationFrame(animate);
    };

    rafRef.current = requestAnimationFrame(animate);

    return () => {
      mounted = false;
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <div
      className="absolute pointer-events-none"
      aria-hidden="true"
    >
      <svg
        ref={containerRef}
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
          {SPOKES.map((s) => (
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
          {TREAD_MARKS.map((t) => (
            <line
              key={`tread-${t.key}`}
              x1={t.x1}
              y1={t.y1}
              x2={t.x2}
              y2={t.y2}
              stroke="currentColor"
              strokeWidth={1}
              className="text-steel"
            />
          ))}
        </g>
      </svg>
    </div>
  );
}
