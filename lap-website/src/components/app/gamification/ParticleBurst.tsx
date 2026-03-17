'use client';

import { useEffect, useState, useCallback } from 'react';

interface ParticleBurstProps {
  active: boolean;
  color: string;
  count?: number;
}

interface Particle {
  id: number;
  dx: number;
  dy: number;
  size: number;
  delay: number;
}

function generateParticles(count: number): Particle[] {
  const particles: Particle[] = [];
  for (let i = 0; i < count; i++) {
    const angle = (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.4;
    const dist = 100 + Math.random() * 200;
    particles.push({
      id: i,
      dx: Math.cos(angle) * dist,
      dy: Math.sin(angle) * dist,
      size: 3 + Math.random() * 5,
      delay: Math.random() * 0.15,
    });
  }
  return particles;
}

export function ParticleBurst({ active, color, count = 30 }: ParticleBurstProps) {
  const [particles, setParticles] = useState<Particle[] | null>(null);

  const spawn = useCallback(() => {
    setParticles(generateParticles(count));
  }, [count]);

  useEffect(() => {
    if (!active) {
      setParticles(null);
      return;
    }

    spawn();

    const timer = setTimeout(() => {
      setParticles(null);
    }, 1500);

    return () => clearTimeout(timer);
  }, [active, spawn]);

  if (!particles) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        overflow: 'hidden',
        zIndex: 99,
      }}
      aria-hidden="true"
    >
      <style>{`
        @keyframes particleBurst {
          0% {
            transform: translate(-50%, -50%) translate(0px, 0px) scale(1);
            opacity: 1;
          }
          100% {
            transform: translate(-50%, -50%) translate(var(--pb-dx), var(--pb-dy)) scale(0.2);
            opacity: 0;
          }
        }
      `}</style>
      {particles.map((p) => (
        <div
          key={p.id}
          style={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            width: p.size,
            height: p.size,
            borderRadius: '50%',
            backgroundColor: color,
            '--pb-dx': `${p.dx}px`,
            '--pb-dy': `${p.dy}px`,
            animation: `particleBurst 1.2s ${p.delay}s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards`,
          } as React.CSSProperties}
        />
      ))}
    </div>
  );
}
