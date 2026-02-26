'use client';

import { useEffect, useRef, useCallback } from 'react';
import { sectorTabs } from '@/lib/tokens';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { useSound } from '@/hooks/useSound';
import { trackIndexOverlayOpen, trackIndexOverlayNav } from '@/lib/analytics';

interface IndexOverlayProps {
  isOpen: boolean;
  onClose: () => void;
  fromSection?: string;
}

const sectionDescriptions: Record<string, string> = {
  S1: 'WHY TIME IS LOST',
  S2: 'HOW IT WORKS',
  S3: 'THE PRODUCT',
  PIT: 'PRICING & DEMO',
  GAR: 'TECH & COMPLIANCE',
  POD: 'FINAL ACTION',
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
        background: 'rgba(11, 12, 15, 0.96)',
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
      <div className="grid grid-cols-2 md:grid-cols-3 gap-6 md:gap-8 px-8 max-w-4xl w-full">
        {sectorTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => navigate(tab.id)}
            className="text-left p-6 bg-concrete/50 hover:bg-concrete transition-colors duration-[420ms] group"
          >
            <span className="font-monument text-[clamp(36px,4vw,56px)] block mb-2 group-hover:text-acid-green transition-colors duration-[420ms]">
              {tab.label}
            </span>
            <span className="font-telemetry text-[11px] tracking-[0.12em] text-steel uppercase">
              {sectionDescriptions[tab.label] ?? ''}
            </span>
          </button>
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
