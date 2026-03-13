'use client';

import { useEffect, useRef, useState } from 'react';

interface LevelUpModalProps {
  oldLevel: number;
  newLevel: number;
  totalXp: number;
  onClose: () => void;
}

const LEVEL_UP_STYLE_ID = 'gamification-level-up-pulse';

/**
 * Inject a CSS @keyframes rule for the level-up pulse animation
 * via DOM API (avoids dangerouslySetInnerHTML).
 */
function useLevelUpPulseStyle() {
  const injectedRef = useRef(false);

  useEffect(() => {
    if (injectedRef.current) return;
    if (typeof document === 'undefined') return;
    if (document.getElementById(LEVEL_UP_STYLE_ID)) {
      injectedRef.current = true;
      return;
    }

    const style = document.createElement('style');
    style.id = LEVEL_UP_STYLE_ID;
    style.textContent = [
      '@keyframes level-up-pulse {',
      '  0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(163, 230, 53, 0.4); }',
      '  50% { transform: scale(1.1); box-shadow: 0 0 24px 8px rgba(163, 230, 53, 0.3); }',
      '}',
    ].join('\n');
    document.head.appendChild(style);
    injectedRef.current = true;
  }, []);
}

export default function LevelUpModal({
  oldLevel,
  newLevel,
  totalXp,
  onClose,
}: LevelUpModalProps) {
  const [visible, setVisible] = useState(false);
  useLevelUpPulseStyle();

  useEffect(() => {
    // Trigger fade-in on mount
    const frame = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  // Guard: don't render if no actual level-up occurred
  if (oldLevel === newLevel || newLevel <= 0) return null;

  function handleClose() {
    setVisible(false);
    setTimeout(onClose, 200);
  }

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{
        backgroundColor: visible
          ? 'rgba(0, 0, 0, 0.6)'
          : 'rgba(0, 0, 0, 0)',
        transition: 'background-color 0.2s ease',
      }}
      onClick={handleClose}
    >
      {/* Modal card */}
      <div
        className="relative rounded-xl p-8 max-w-sm w-full text-center"
        style={{
          backgroundColor: '#1a1a2e',
          border: '2px solid #a3e635',
          transform: visible ? 'scale(1)' : 'scale(0.9)',
          opacity: visible ? 1 : 0,
          transition:
            'transform 0.3s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.3s ease',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Heading */}
        <h2
          className="font-monument text-3xl font-black tracking-wider mb-6"
          style={{ color: '#a3e635' }}
        >
          LEVEL UP!
        </h2>

        {/* Level transition */}
        <div className="flex items-center justify-center gap-4 mb-6">
          {/* Old level */}
          <div
            className="flex items-center justify-center w-16 h-16 rounded-full border-2"
            style={{
              borderColor: '#94a3b8',
              backgroundColor: 'rgba(148, 163, 184, 0.1)',
            }}
          >
            <span className="font-monument text-2xl font-bold text-steel">
              {oldLevel}
            </span>
          </div>

          {/* Arrow */}
          <span className="text-2xl text-steel">&rarr;</span>

          {/* New level with pulse */}
          <div
            className="flex items-center justify-center w-16 h-16 rounded-full border-2"
            style={{
              borderColor: '#a3e635',
              backgroundColor: 'rgba(163, 230, 53, 0.15)',
              animation: 'level-up-pulse 1.5s ease-in-out infinite',
            }}
          >
            <span
              className="font-monument text-2xl font-bold"
              style={{ color: '#a3e635' }}
            >
              {newLevel}
            </span>
          </div>
        </div>

        {/* Total XP */}
        <p className="font-telemetry text-sm text-steel mb-6">
          Total XP:{' '}
          <span className="text-chalk font-semibold">
            {totalXp.toLocaleString()}
          </span>
        </p>

        {/* Continue button */}
        <button
          type="button"
          onClick={handleClose}
          className="w-full py-2.5 px-6 rounded-lg font-monument text-sm font-bold uppercase tracking-wider transition-colors"
          style={{
            backgroundColor: '#a3e635',
            color: '#1a1a2e',
          }}
          onMouseEnter={(e) => {
            (e.target as HTMLButtonElement).style.backgroundColor = '#84cc16';
          }}
          onMouseLeave={(e) => {
            (e.target as HTMLButtonElement).style.backgroundColor = '#a3e635';
          }}
        >
          Continue
        </button>
      </div>
    </div>
  );
}
