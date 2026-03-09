'use client';

import { useRef, useEffect } from 'react';

interface ScrutineeringStampProps {
  label: string;
  detail?: string;
  variant?: 'default' | 'slam';
  className?: string;
}

function hashCode(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return hash;
}

export function ScrutineeringStamp({
  label,
  detail,
  variant = 'default',
  className = '',
}: ScrutineeringStampProps) {
  const ref = useRef<HTMLDivElement>(null);
  const rotation = ((hashCode(label) % 5) - 2) * 0.8; // -1.6° to +1.6°
  const offsetX = (hashCode(label + 'x') % 3) - 1; // -1px to +1px

  useEffect(() => {
    if (variant !== 'slam' || !ref.current) return;

    const el = ref.current;
    el.style.opacity = '0';
    el.style.transform = `rotate(${rotation}deg) scale(1.8)`;

    const loadGsap = async () => {
      const { gsap } = await import('gsap');
      gsap.to(el, {
        opacity: 1,
        scale: 1,
        duration: 0.42,
        ease: 'back.out(1.7)',
      });
    };
    loadGsap();
  }, [variant, rotation]);

  return (
    <div
      ref={ref}
      className={`inline-block border-2 border-current px-3 py-1 font-telemetry ${className}`}
      style={{
        transform: `rotate(${rotation}deg) translateX(${offsetX}px)`,
        zIndex: 'var(--z-stamps)' as unknown as number,
      }}
    >
      <span className="text-[11px] tracking-[0.12em] uppercase">{label}</span>
      {detail && (
        <span className="block text-[9px] tracking-[0.12em] uppercase text-steel mt-0.5">
          {detail}
        </span>
      )}
    </div>
  );
}
