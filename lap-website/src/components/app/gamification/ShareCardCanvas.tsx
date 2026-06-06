'use client';

import { useRef, useCallback } from 'react';
import { RacingBadge } from './RacingBadge';

/* ── Types ────────────────────────────────────────────────── */

interface Badge {
  title: string;
  description: string;
  unlocked: boolean;
  category?: 'progress' | 'technique' | 'consistency' | 'learning' | 'endurance';
}

interface ShareCardCanvasProps {
  sessionData: {
    trackName?: string;
    driverName?: string;
    sessionDate?: string;
    sessionType?: string;
    bestLapTime?: number | null;
    totalScore?: number | null;
    grade?: string | null;
    nLaps?: number | null;
    cvPct?: number | null;
    badges?: { id: string; tier: string }[];
  };
  /** Optional structured badges for RacingBadge display */
  racingBadges?: Badge[];
  licenseLevel?: 'N' | 'D' | 'C' | 'B' | 'A' | 'S';
  className?: string;
}

const licenseLevelColors: Record<string, string> = {
  N: '#22C55E',   // acid-green
  D: '#C9A84C',   // gold
  C: '#FACC15',   // marshal-yellow
  B: '#8B5CF6',   // racing-purple
  A: '#FF2A2A',   // safety-red
  S: '#F0EDE5',   // chalk
};

function formatLapTime(seconds: number | null | undefined): string {
  if (seconds == null || seconds <= 0) return '--:--.---';
  const mins = Math.floor(seconds / 60);
  const secs = seconds - mins * 60;
  const wholeS = Math.floor(secs);
  const ms = Math.round((secs - wholeS) * 1000);
  return `${mins}:${String(wholeS).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

/* ── Component ────────────────────────────────────────────── */

export function ShareCardCanvas({ sessionData, racingBadges, licenseLevel = 'N', className }: ShareCardCanvasProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const licenseColor = licenseLevelColors[licenseLevel] ?? '#22C55E';

  const driver = sessionData.driverName || 'Driver';
  const track = sessionData.trackName || 'Unknown Track';
  const sessionType = (sessionData.sessionType || 'practice').charAt(0).toUpperCase() + (sessionData.sessionType || 'practice').slice(1);

  let displayDate = sessionData.sessionDate || '';
  try {
    if (displayDate) {
      const d = new Date(displayDate);
      displayDate = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    }
  } catch { /* keep raw */ }

  const bestLap = formatLapTime(sessionData.bestLapTime);
  const score = sessionData.totalScore != null ? Math.round(sessionData.totalScore) : null;
  const nLaps = sessionData.nLaps ?? null;
  const cvPct = sessionData.cvPct != null ? Math.round(sessionData.cvPct) : null;

  const handleDownload = useCallback(async () => {
    const card = cardRef.current;
    if (!card) return;

    try {
      // html2canvas is a browser-only lib; the dynamic import keeps it in a
      // lazy client chunk (out of the SSR/worker bundle).
      const { default: html2canvas } = await import('html2canvas');
      const canvas = await html2canvas(card, {
        backgroundColor: '#000000',
        scale: 2,
        width: 1200,
        height: 630,
        useCORS: true,
      });
      canvas.toBlob((blob: Blob | null) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `lap-coach-${driver.replace(/\s+/g, '-')}.png`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 'image/png');
    } catch (err) {
      console.error('Share card render failed:', err);
      alert('Could not generate the image. Please try again.');
    }
  }, [driver]);

  return (
    <div className={className}>
      {/* Main Card — optimized for social sharing (1200x630 aspect) */}
      <div
        ref={cardRef}
        className="relative rounded-3xl overflow-hidden"
        style={{
          background: 'linear-gradient(135deg, #0a0a0a, #1a1a1a, #000000)',
          width: '100%',
          maxWidth: '600px',
          aspectRatio: '1200/630',
          boxShadow: '0 8px 60px rgba(0,0,0,0.7)',
        }}
      >
        {/* Grid pattern background */}
        <div
          className="absolute inset-0 opacity-5"
          style={{
            backgroundImage: `
              linear-gradient(rgba(240,237,229,0.5) 1px, transparent 1px),
              linear-gradient(90deg, rgba(240,237,229,0.5) 1px, transparent 1px)
            `,
            backgroundSize: '40px 40px',
          }}
        />

        {/* Gradient overlay */}
        <div
          className="absolute inset-0 opacity-20"
          style={{
            background: `radial-gradient(circle at top right, ${licenseColor}40, transparent 50%)`,
          }}
        />

        <div className="relative h-full p-6 sm:p-8 flex flex-col">
          {/* Header */}
          <div className="flex items-start justify-between mb-4">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-telemetry text-[10px] text-steel uppercase tracking-[0.2em]">LAP COACH</span>
                <div className="h-3 w-px bg-steel" />
                <span className="font-telemetry text-[10px] text-steel uppercase tracking-wider">{sessionType}</span>
              </div>
              <h2 className="font-monument text-2xl sm:text-3xl font-bold text-chalk mb-1">{driver}</h2>
              <div className="font-body text-sm text-steel">
                <span className="uppercase tracking-wide">{track}</span>
                <span className="mx-2">•</span>
                <span>{displayDate}</span>
              </div>
            </div>

            {/* License badge */}
            <div
              className="w-14 h-14 sm:w-16 sm:h-16 rounded-xl flex items-center justify-center border-2 font-monument text-2xl sm:text-3xl font-bold shrink-0"
              style={{
                borderColor: licenseColor,
                backgroundColor: `${licenseColor}15`,
                color: licenseColor,
                boxShadow: `0 0 30px ${licenseColor}40`,
              }}
            >
              {licenseLevel}
            </div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-4 gap-3 sm:gap-4 mb-4">
            <div>
              <div className="font-telemetry text-[9px] text-steel uppercase tracking-wider mb-1">Best Lap</div>
              <div
                className="font-telemetry text-lg sm:text-2xl font-bold tracking-tight"
                style={{
                  color: '#22C55E',
                  textShadow: '0 0 20px rgba(34,197,94,0.4)',
                }}
              >
                {bestLap}
              </div>
            </div>
            <div>
              <div className="font-telemetry text-[9px] text-steel uppercase tracking-wider mb-1">Score</div>
              <div className="font-telemetry text-lg sm:text-2xl font-bold text-chalk">
                {score ?? '--'}
                <span className="text-sm text-steel">/100</span>
              </div>
            </div>
            <div>
              <div className="font-telemetry text-[9px] text-steel uppercase tracking-wider mb-1">Laps</div>
              <div className="font-telemetry text-lg sm:text-2xl font-bold text-chalk">{nLaps ?? '--'}</div>
            </div>
            <div>
              <div className="font-telemetry text-[9px] text-steel uppercase tracking-wider mb-1">Consistency</div>
              <div
                className="font-telemetry text-lg sm:text-2xl font-bold"
                style={{
                  color: '#22C55E',
                  textShadow: '0 0 15px rgba(34,197,94,0.3)',
                }}
              >
                {cvPct != null ? `${cvPct}%` : '--'}
              </div>
            </div>
          </div>

          {/* Badges showcase */}
          {racingBadges && racingBadges.filter((b) => b.unlocked).length > 0 && (
            <div className="mt-auto">
              <div className="font-telemetry text-[9px] text-steel uppercase tracking-wider mb-2">Achievement Highlights</div>
              <div className="flex gap-2 overflow-hidden">
                {racingBadges
                  .filter((b) => b.unlocked)
                  .slice(0, 4)
                  .map((badge, i) => (
                    <div key={i} className="scale-[0.6] origin-top-left -mr-8">
                      <RacingBadge {...badge} />
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Footer branding */}
          <div className="absolute bottom-4 right-6 font-telemetry text-[9px] text-steel tracking-[0.3em] uppercase">
            lap-coach.racing
          </div>
        </div>

        {/* Accent lines */}
        <div
          className="absolute top-0 left-0 right-0 h-1"
          style={{ background: `linear-gradient(90deg, transparent, ${licenseColor}, transparent)` }}
        />
        <div
          className="absolute bottom-0 left-0 right-0 h-1"
          style={{ background: `linear-gradient(90deg, transparent, ${licenseColor}, transparent)` }}
        />
      </div>

      {/* Action buttons */}
      <div className="flex gap-3 mt-4 max-w-md">
        <button
          type="button"
          onClick={handleDownload}
          className="flex-1 inline-flex items-center justify-center gap-2 bg-gold text-white font-telemetry text-sm uppercase tracking-wider px-5 py-3 rounded hover:bg-gold/80 transition-colors"
          style={{ boxShadow: '0 0 20px rgba(201,168,76,0.3)' }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Download Card
        </button>

        <button
          type="button"
          onClick={() => {
            if (navigator.share) {
              navigator.share({ title: `${driver} - Lap Coach`, text: `${driver} at ${track}: ${bestLap}`, url: window.location.href });
            }
          }}
          className="flex-1 inline-flex items-center justify-center gap-2 bg-acid-green text-white font-telemetry text-sm uppercase tracking-wider px-5 py-3 rounded hover:bg-acid-green/80 transition-colors"
          style={{ boxShadow: '0 0 20px rgba(34,197,94,0.3)' }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
          </svg>
          Share
        </button>
      </div>
    </div>
  );
}
