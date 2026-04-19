'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { formatLapTime } from '@/lib/format-utils';
import { AnimatedCounter } from '@/components/ui/AnimatedCounter';

// ── Types ────────────────────────────────────────────────────

interface FocusArea {
  category: string;
  summary: string;
}

interface TopCorner {
  corner_id: number;
  direction: string | null;
  time_loss_s: number;
  coaching_hint: string | null;
}

interface Drill {
  title: string;
  target_improvement: string;
}

interface Confidence {
  score: number;
  level: string;
}

interface RevealData {
  total_score: number | null;
  grade: string | null;
  best_lap_s: number | null;
  n_laps: number | null;
  track_name: string | null;
  session_date: string | null;
  focus_areas: FocusArea[];
  top_corners: TopCorner[];
  recoverable_s: number | null;
  drills: Drill[];
  confidence: Confidence | null;
}

// ── Grade colors (local, matches session detail page pattern) ────────

// Matches session detail page (page.tsx:130-137) — uses Tailwind palette
// because grade colors need 6 distinct hues beyond our 5 accent tokens.
const GRADE_COLORS: Record<string, string> = {
  S: 'text-yellow-400 border-yellow-400',
  A: 'text-green-400 border-green-400',
  B: 'text-cyan-400 border-cyan-400',
  C: 'text-yellow-500 border-yellow-500',
  D: 'text-orange-400 border-orange-400',
  F: 'text-red-500 border-red-500',
};

function gradeColorClass(grade: string | null): string {
  if (!grade) return 'text-steel border-steel';
  return GRADE_COLORS[grade.charAt(0).toUpperCase()] || 'text-steel border-steel';
}

// ── Confidence pill color ────────────────────────────────────

function confidenceColor(level: string): string {
  if (level === 'high') return 'text-acid-green bg-acid-green/10 border-acid-green/30';
  if (level === 'medium') return 'text-marshal-yellow bg-marshal-yellow/10 border-marshal-yellow/30';
  return 'text-safety-red bg-safety-red/10 border-safety-red/30';
}

// ── Animation wrapper ────────────────────────────────────────

function FadeUp({ delay, children, className = '' }: {
  delay: number;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`opacity-0 translate-y-5 ${className}`}
      style={{
        animation: `fadeUp 400ms ease-out ${delay}ms forwards`,
      }}
    >
      {children}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────

export default function RevealPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.id as string;

  const [data, setData] = useState<RevealData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.get<RevealData>(`/sessions/${sessionId}/reveal`)
      .then((d) => {
        if (!d || !d.n_laps) {
          // Zero valid laps or null — skip reveal
          router.replace(`/app/sessions/${sessionId}`);
          return;
        }
        setData(d);
      })
      .catch(() => {
        setError(true);
      })
      .finally(() => setLoading(false));
  }, [sessionId, router]);

  if (loading) {
    return (
      <div className="min-h-screen bg-asphalt flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-gold rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !data) {
    router.replace('/app/sessions');
    return null;
  }

  const hasScore = data.total_score != null;
  const hasCorners = data.top_corners.length > 0;
  const hasFocus = data.focus_areas.length > 0;
  const hasDrills = data.drills.length > 0;

  return (
    <>
      {/* Keyframes */}
      <style>{`
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>

      <div className="min-h-screen bg-asphalt flex flex-col items-center justify-center px-4 py-12">
        <div className="w-full max-w-2xl space-y-8">

          {/* 1. Header bar (fade-in only, no translateY per spec) */}
          <div
            className="opacity-0 flex items-center justify-between"
            style={{ animation: 'fadeIn 300ms ease-out 0ms forwards' }}
          >
            <div className="font-monument text-sm text-steel">
              {data.track_name || 'Unknown Track'}
              {data.session_date && (
                <span className="ml-2 text-steel/60">{data.session_date}</span>
              )}
            </div>
            {data.confidence && (
              <div>
                <span className={`inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-telemetry ${confidenceColor(data.confidence.level)}`}>
                  {data.confidence.score}% confidence
                </span>
                {data.confidence.score < 60 && (
                  <p className="text-safety-red/70 text-[10px] font-body mt-1 text-right">
                    Limited data — results improve with more laps
                  </p>
                )}
              </div>
            )}
          </div>

          {/* 2. Hero: Score + Grade */}
          <FadeUp delay={200}>
            <div className="text-center py-6">
              <p className="font-body text-steel text-sm mb-2">Your Session Report</p>
              {hasScore ? (
                <div className="flex items-center justify-center gap-4">
                  <span className="font-monument text-6xl text-chalk">
                    <AnimatedCounter value={Math.round(data.total_score!)} duration={1400} />
                  </span>
                  <span className="font-body text-steel text-xl">/ 100</span>
                  {data.grade && (
                    <span className={`w-12 h-12 flex items-center justify-center rounded-lg border-2 font-monument text-xl ${gradeColorClass(data.grade)}`}>
                      {data.grade}
                    </span>
                  )}
                </div>
              ) : data.best_lap_s != null ? (
                <div className="flex items-center justify-center gap-2">
                  <span className="font-monument text-5xl text-chalk">
                    {formatLapTime(data.best_lap_s)}
                  </span>
                  <span className="font-body text-steel text-sm">best lap</span>
                </div>
              ) : (
                <p className="font-monument text-2xl text-steel">Session Analyzed</p>
              )}
            </div>
          </FadeUp>

          {/* 3. Stat row */}
          <FadeUp delay={1600}>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-center">
              <div>
                <div className="font-telemetry text-2xl text-chalk">
                  {data.recoverable_s != null ? `${data.recoverable_s.toFixed(3)}s` : '\u2014'}
                </div>
                <div className="font-body text-xs text-steel mt-1">recoverable</div>
              </div>
              <div>
                <div className="font-telemetry text-2xl text-chalk">
                  {data.best_lap_s != null ? formatLapTime(data.best_lap_s) : '\u2014'}
                </div>
                <div className="font-body text-xs text-steel mt-1">best lap</div>
              </div>
              <div>
                <div className="font-telemetry text-2xl text-chalk">
                  {data.n_laps ?? '\u2014'}
                </div>
                <div className="font-body text-xs text-steel mt-1">laps analyzed</div>
              </div>
            </div>
          </FadeUp>

          {/* 4. Top Corners */}
          {hasCorners && (
            <div>
              <FadeUp delay={2000}>
                <h3 className="font-monument text-xs text-steel uppercase tracking-wider mb-3">
                  Top Corners
                </h3>
              </FadeUp>
              <div className="space-y-2">
                {data.top_corners.map((c, i) => (
                  <FadeUp key={c.corner_id} delay={2000 + (i + 1) * 100}>
                    <div className="bg-concrete rounded-xl border border-steel/10 p-4 flex items-center gap-4">
                      <div className="font-monument text-sm text-chalk whitespace-nowrap">
                        T{c.corner_id}
                        {c.direction && (
                          <span className="ml-1 text-steel text-xs">{c.direction}</span>
                        )}
                      </div>
                      <div className="font-telemetry text-safety-red whitespace-nowrap">
                        -{c.time_loss_s.toFixed(2)}s
                      </div>
                      {c.coaching_hint && (
                        <div className="text-chalk/80 font-body text-sm truncate">
                          {c.coaching_hint}
                        </div>
                      )}
                    </div>
                  </FadeUp>
                ))}
              </div>
            </div>
          )}

          {/* 5. Focus Areas + Drills */}
          {(hasFocus || hasDrills) && (
            <FadeUp delay={2500}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                {hasFocus && (
                  <div>
                    <h3 className="font-monument text-xs text-steel uppercase tracking-wider mb-3">
                      Focus Areas
                    </h3>
                    <ul className="space-y-2">
                      {data.focus_areas.map((fa, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <span className="text-gold mt-1 flex-shrink-0">&#x25CF;</span>
                          <span className="text-chalk font-body text-sm">{fa.summary}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {hasDrills ? (
                  <div>
                    <h3 className="font-monument text-xs text-steel uppercase tracking-wider mb-3">
                      Next-Session Drills
                    </h3>
                    <ol className="space-y-2">
                      {data.drills.map((d, i) => (
                        <li key={i} className="flex items-start gap-2">
                          <span className="font-telemetry text-steel text-xs mt-0.5 flex-shrink-0">
                            {i + 1}.
                          </span>
                          <div>
                            <span className="text-chalk font-body text-sm">{d.title}</span>
                            {d.target_improvement && (
                              <span className="ml-2 text-steel font-telemetry text-xs">
                                ~{d.target_improvement}
                              </span>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : (
                  <div>
                    <h3 className="font-monument text-xs text-steel uppercase tracking-wider mb-3">
                      Next-Session Drills
                    </h3>
                    <p className="text-steel font-body text-sm">
                      Upload more sessions for personalized drills
                    </p>
                  </div>
                )}
              </div>
            </FadeUp>
          )}

          {/* 6. CTA */}
          <FadeUp delay={2900}>
            <div className="text-center pt-4">
              <Link
                href={`/app/sessions/${sessionId}`}
                className="inline-block bg-gold text-white font-telemetry rounded-lg px-8 py-3 hover:bg-gold/80 transition-colors"
              >
                View Full Session
              </Link>
            </div>
          </FadeUp>

        </div>
      </div>
    </>
  );
}
