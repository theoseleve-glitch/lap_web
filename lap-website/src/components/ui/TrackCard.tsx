'use client';

import { useRef, useCallback, useState, type ReactNode } from 'react';

interface TrackCardProps {
  title: string;
  description: string;
  icon?: ReactNode;
  onClick?: () => void;
  className?: string;
  children?: ReactNode;
}

export function TrackCard({
  title,
  description,
  icon,
  onClick,
  className = '',
  children,
}: TrackCardProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [tilt, setTilt] = useState({ rotateX: 0, rotateY: 0 });
  const [spotPos, setSpotPos] = useState({ x: 50, y: 50 });
  const [hovering, setHovering] = useState(false);
  const rafPending = useRef(false);

  // Check reduced motion — prefer the CSS media query approach
  const prefersReducedMotion = useRef(
    typeof window !== 'undefined'
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false,
  );

  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (rafPending.current || prefersReducedMotion.current) return;
    rafPending.current = true;

    const el = containerRef.current;
    if (!el) { rafPending.current = false; return; }

    const rect = el.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;

    requestAnimationFrame(() => {
      setTilt({
        rotateX: (0.5 - y) * 16,  // max +/-8, inverted for natural feel
        rotateY: (x - 0.5) * 16,  // max +/-8
      });
      setSpotPos({ x: x * 100, y: y * 100 });
      rafPending.current = false;
    });
  }, []);

  const handlePointerEnter = useCallback(() => {
    setHovering(true);
  }, []);

  const handlePointerLeave = useCallback(() => {
    setHovering(false);
    setTilt({ rotateX: 0, rotateY: 0 });
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (onClick && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        onClick();
      }
    },
    [onClick],
  );

  // Parallax offsets: title shifts slightly more than body
  const titleShift = {
    x: tilt.rotateY * 0.4,
    y: -tilt.rotateX * 0.4,
  };
  const bodyShift = {
    x: tilt.rotateY * 0.2,
    y: -tilt.rotateX * 0.2,
  };

  return (
    <div
      ref={containerRef}
      className={`group ${className}`}
      style={{ perspective: '1200px' }}
      onPointerMove={handlePointerMove}
      onPointerEnter={handlePointerEnter}
      onPointerLeave={handlePointerLeave}
    >
      <div
        className={`beam-card relative border border-chalk/15 bg-concrete p-5 transition-transform duration-200 ease-out ${
          onClick ? 'cursor-pointer' : ''
        }`}
        style={{
          transform: hovering
            ? `rotateX(${tilt.rotateX}deg) rotateY(${tilt.rotateY}deg)`
            : 'rotateX(0deg) rotateY(0deg)',
          transformStyle: 'preserve-3d',
        }}
        onClick={onClick}
        onKeyDown={handleKeyDown}
        role={onClick ? 'button' : undefined}
        tabIndex={onClick ? 0 : undefined}
      >
        {/* Raycast-style spotlight glow — follows cursor */}
        <div
          className="absolute inset-0 pointer-events-none transition-opacity duration-300"
          style={{
            opacity: hovering ? 1 : 0,
            background: `radial-gradient(500px circle at ${spotPos.x}% ${spotPos.y}%, rgba(201,168,76,0.07), transparent 45%)`,
            zIndex: 1,
          }}
        />

        {/* Icon layer */}
        {icon && (
          <div
            className="relative z-[2] mb-3 text-pit-orange transition-transform duration-200 ease-out"
            style={{
              transform: hovering
                ? `translate(${titleShift.x}px, ${titleShift.y}px)`
                : 'translate(0, 0)',
            }}
          >
            {icon}
          </div>
        )}

        {/* Title layer — shifts more for parallax */}
        <h3
          className="relative z-[2] font-monument text-[var(--text-h3)] mb-2 transition-transform duration-200 ease-out"
          style={{
            transform: hovering
              ? `translate(${titleShift.x}px, ${titleShift.y}px)`
              : 'translate(0, 0)',
          }}
        >
          {title}
        </h3>

        {/* Body layer — shifts less */}
        <p
          className="relative z-[2] text-sm text-steel mb-3 transition-transform duration-200 ease-out"
          style={{
            transform: hovering
              ? `translate(${bodyShift.x}px, ${bodyShift.y}px)`
              : 'translate(0, 0)',
          }}
        >
          {description}
        </p>

        {/* Optional children (buttons, etc.) */}
        {children && (
          <div
            className="relative z-[2] transition-transform duration-200 ease-out"
            style={{
              transform: hovering
                ? `translate(${bodyShift.x}px, ${bodyShift.y}px)`
                : 'translate(0, 0)',
            }}
          >
            {children}
          </div>
        )}

        {/* Sector highlight strip on hover */}
        <div
          className="absolute bottom-0 left-0 right-0 h-[2px] bg-racing-purple transition-all duration-300 ease-out z-[2]"
          style={{
            transform: hovering ? 'scaleX(1)' : 'scaleX(0)',
            transformOrigin: 'left center',
          }}
        />
      </div>
    </div>
  );
}
