'use client';

import { useEffect, useRef, useCallback } from 'react';
import { sectorTabs } from '@/lib/tokens';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { useSound } from '@/hooks/useSound';
import {
  trackIndexOverlayOpen,
  trackIndexOverlayNav,
  trackNavRouteClick,
} from '@/lib/analytics';

interface IndexOverlayProps {
  isOpen: boolean;
  onClose: () => void;
  fromSection?: string;
}

const sectionDescriptions: Record<string, string> = {
  S1: 'WHY TIME IS LOST',
  S2: 'HOW IT WORKS',
  S3: 'THE PRODUCT',
  S4: 'WORKFLOW COVERAGE',
  S5: 'PERSONA PAGES',
  PIT: 'PRICING & DEMO',
  GAR: 'TECH & COMPLIANCE',
  POD: 'FINAL ACTION',
};

const sectionVisuals: Record<string, { image: string; icon: string }> = {
  S1: { image: '/images/screenshots/corner-replay.png', icon: 'A' },
  S2: { image: '/images/screenshots/lap-table.png', icon: 'B' },
  S3: { image: '/images/screenshots/dashboard-hero.png', icon: 'C' },
  S4: { image: '/images/screenshots/score-overview.png', icon: 'D' },
  S5: { image: '/images/screenshots/driving-style-radar.png', icon: 'E' },
  PIT: { image: '/images/screenshots/grade-badge.png', icon: 'P' },
  GAR: { image: '/images/screenshots/lap-table.png', icon: 'G' },
  POD: { image: '/images/screenshots/dashboard-hero.png', icon: 'F' },
};

export function IndexOverlay({ isOpen, onClose, fromSection = '' }: IndexOverlayProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const { reducedMotion, toggle: toggleMotion } = useReducedMotion();
  const { enabled: soundEnabled, toggle: toggleSound } = useSound();

  // Track open
  useEffect(() => {
    if (isOpen) trackIndexOverlayOpen(fromSection);
  }, [isOpen, fromSection]);

  // Escape to close
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isOpen, onClose]);

  // Focus trap
  useEffect(() => {
    if (!isOpen || !overlayRef.current) return;
    const focusable = overlayRef.current.querySelectorAll<HTMLElement>(
      'button, [href], [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length > 0) focusable[0].focus();
  }, [isOpen]);

  const navigate = useCallback(
    (id: string) => {
      trackIndexOverlayNav(id);
      onClose();
      setTimeout(() => {
        document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
      }, 100);
    },
    [onClose],
  );

  if (!isOpen) return null;

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 flex flex-col items-center justify-center"
      style={{
        zIndex: 'var(--z-overlay)' as unknown as number,
        background: 'rgba(0, 0, 0, 0.96)',
        backdropFilter: 'blur(8px)',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Site navigation"
    >
      {/* Close button */}
      <button
        className="absolute top-4 right-4 font-telemetry text-2xl text-steel hover:text-chalk transition-colors"
        onClick={onClose}
        aria-label="Close navigation"
      >
        &times;
      </button>

      {/* Navigation grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-6 md:gap-8 px-8 max-w-5xl w-full">
        {sectorTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => navigate(tab.id)}
            className="text-left p-4 bg-concrete/50 hover:bg-concrete transition-colors duration-[420ms] group border border-chalk/15"
          >
            <span className="relative block mb-3">
              <img
                src={sectionVisuals[tab.label]?.image}
                alt={`${tab.label} preview`}
                className="h-24 w-full object-cover opacity-75 group-hover:opacity-100 transition-opacity duration-[420ms]"
              />
              <span className="absolute top-2 left-2 font-telemetry text-[10px] bg-asphalt/80 px-2 py-1 border border-chalk/20 text-chalk">
                {sectionVisuals[tab.label]?.icon ?? tab.label}
              </span>
            </span>
            <span className="font-monument text-[clamp(30px,3.2vw,48px)] block mb-1 group-hover:text-acid-green transition-colors duration-[420ms]">
              {tab.label}
            </span>
            <span className="font-telemetry text-[10px] tracking-[0.12em] text-steel uppercase">
              {sectionDescriptions[tab.label] ?? ''}
            </span>
          </button>
        ))}
      </div>

      <div className="mt-8 flex flex-wrap items-center justify-center gap-3 px-8">
        {[
          { label: 'Pricing', href: '/pricing' },
          { label: 'Drivers', href: '/drivers' },
          { label: 'Circuits', href: '/circuits' },
          { label: 'Teams', href: '/teams' },
          { label: 'Endurance', href: '/endurance' },
        ].map((link) => (
          <a
            key={link.href}
            href={link.href}
            className="font-telemetry text-[11px] tracking-[0.12em] uppercase border border-chalk/20 px-3 py-2 text-steel hover:text-chalk hover:border-chalk/40"
            onClick={() => trackNavRouteClick(link.href, 'index_overlay')}
          >
            {link.label}
          </a>
        ))}
      </div>

      {/* Bottom toggles */}
      <div className="absolute bottom-6 flex gap-8">
        <button
          className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk transition-colors"
          onClick={toggleSound}
        >
          SOUND: {soundEnabled ? 'ON' : 'OFF'}
        </button>
        <button
          className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk transition-colors"
          onClick={toggleMotion}
        >
          MOTION: {reducedMotion ? 'REDUCED' : 'FULL'}
        </button>
      </div>
    </div>
  );
}
