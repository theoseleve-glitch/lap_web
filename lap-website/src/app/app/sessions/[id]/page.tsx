'use client';

import { useEffect, useState, useCallback, useMemo, useRef, lazy, Suspense } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api, BACKEND_URL } from '@/lib/api-client';
import { formatLapTime, formatDate, formatDistance, mpsToKmh, mps2ToG } from '@/lib/format-utils';
import { CornersTab, type CornerData } from '@/components/app/corners';
import { AnalyticsTab } from '@/components/app/analytics';
import { DrivingStyleSection } from '@/components/app/DrivingStyleSection';
import { SessionDebrief } from '@/components/app/SessionDebrief';
import { AchievementsBadges } from '@/components/app/AchievementsBadges';
import { FocusMode } from '@/components/app/focus-mode/FocusMode';
import { SkeletonSessionDetail } from '@/components/app/Skeleton';

const DrivingAnalyzer = lazy(() => import('@/components/app/driving-analyzer/DrivingAnalyzer'));

// ── Types ────────────────────────────────────────────────────────

interface SessionData {
  session_id: string;
  csv_filename: string;
  display_name: string | null;
  driver_name: string;
  track_name: string | null;
  track_unnamed?: boolean;
  session_type: string;
  track_state: string;
  session_date: string;
  n_laps: number | null;
  best_lap_time_s: number | null;
  mean_lap_time_s: number | null;
  total_score: number | null;
  grade: string | null;
  notes: string | null;
  driver_id: number | null;
  track_id: string | null;
  kart_id: number | null;
  kart_name: string | null;
}

interface LapData {
  lap_number: number;
  lap_time_s: number | null;
  speed_mean_mps: number | null;
  speed_max_mps: number | null;
  braking_max_mps2: number | null;
  accel_max_mps2: number | null;
  line_length_m: number | null;
  phase_id: number | null;
  is_valid: number;
  is_best: number;
  is_joker: number;
  invalid_reason: string | null;
}

interface ConditionPhase {
  phase_id: number;
  lap_start: number;
  lap_end: number;
  label: string | null;
  confidence: number | null;
  median_pace_s: number | null;
}

interface BadgeData {
  id: string;
  label: string;
  tier: 'bronze' | 'silver' | 'gold';
  category: string;
  criteria: string;
}

interface ScoreData {
  pace_score: number | null;
  pace_max: number | null;
  consistency_score: number | null;
  consistency_max: number | null;
  execution_score: number | null;
  execution_max: number | null;
  robustness_score: number | null;
  robustness_max: number | null;
  adaptation_score: number | null;
  strengths: string[];
  weaknesses: string[];
  badges?: BadgeData[];
}

// ── Helpers ──────────────────────────────────────────────────────

type Tab = 'overview' | 'corners' | 'timeline' | 'analytics' | 'laps';

const TABS: { key: Tab; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'corners', label: 'Corners & Coaching' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'analytics', label: 'Analytics' },
  { key: 'laps', label: 'Lap Data' },
];


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

// ── Track name prompt (unnamed track) ────────────────────────────

function TrackNamePrompt({
  trackId,
  onNamed,
}: {
  trackId: string;
  onNamed: (name: string) => void;
}) {
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setSaving(true);
    setErr(null);
    try {
      await api.patch(`/tracks/${trackId}`, { name: trimmed });
      onNamed(trimmed);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-pit-orange/10 border border-pit-orange/30 rounded-lg p-4 mb-6">
      <h3 className="font-monument text-sm text-chalk mb-1">Name this track</h3>
      <p className="text-steel text-xs font-body mb-3">
        This session was analyzed on a track that hasn&apos;t been named yet.
        Enter a name so it appears in your track list.
      </p>
      <div className="flex gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Franciacorta, Lonato South..."
          onKeyDown={(e) => { if (e.key === 'Enter') handleSave(); }}
          className="flex-1 min-w-0 bg-concrete border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
            placeholder:text-steel/60 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || !name.trim()}
          className="px-5 py-2 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80
            transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
      {err && <p className="text-safety-red text-xs font-telemetry mt-2">{err}</p>}
    </div>
  );
}

// ── Score bar for Overview tab ───────────────────────────────────

function ScoreBar({
  label,
  score,
  max,
  accentColor,
}: {
  label: string;
  score: number | null;
  max: number;
  accentColor: string;
}) {
  const pct = score != null ? Math.min((score / max) * 100, 100) : 0;
  return (
    <div className="mb-3">
      <div className="flex justify-between text-sm mb-1">
        <span className="text-chalk font-body">{label}</span>
        <span className="text-steel font-telemetry">
          {score != null ? Math.round(score) : '\u2014'} / {Math.round(max)}
        </span>
      </div>
      <div className="w-full h-2.5 bg-asphalt rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: accentColor }}
        />
      </div>
    </div>
  );
}

// ── Main page component ──────────────────────────────────────────

export default function SessionDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;

  const [activeTab, setActiveTab] = useState<Tab>('overview');
  const [session, setSession] = useState<SessionData | null>(null);
  const [laps, setLaps] = useState<LapData[]>([]);
  const [scores, setScores] = useState<ScoreData | null>(null);
  const [corners, setCorners] = useState<CornerData[]>([]);
  const [conditionPhases, setConditionPhases] = useState<ConditionPhase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [focusOpen, setFocusOpen] = useState(false);
  const [analyzerOpen, setAnalyzerOpen] = useState(false);
  const [trackNamed, setTrackNamed] = useState(false);

  // Fetch all data on mount
  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      setLoading(true);
      setError(null);

      try {
        // Fetch session detail first (required)
        const sessionData = await api.get<SessionData>(`/sessions/${sessionId}`);
        if (cancelled) return;
        setSession(sessionData);

        // Fetch supplementary data in parallel (non-critical)
        const [lapsRes, scoresRes, cornersRes, phasesRes] = await Promise.allSettled([
          api.get<{ laps: LapData[] }>(`/sessions/${sessionId}/laps`),
          api.get<ScoreData>(`/sessions/${sessionId}/scores`),
          api.get<{ corners: CornerData[] }>(`/sessions/${sessionId}/corners`),
          api.get<{ phases: ConditionPhase[] }>(`/sessions/${sessionId}/condition-phases`),
        ]);

        if (cancelled) return;

        if (lapsRes.status === 'fulfilled') {
          setLaps(lapsRes.value.laps || []);
        }
        if (scoresRes.status === 'fulfilled') {
          setScores(scoresRes.value);
        }
        if (cornersRes.status === 'fulfilled') {
          setCorners(cornersRes.value.corners || []);
        }
        if (phasesRes.status === 'fulfilled') {
          setConditionPhases(phasesRes.value.phases || []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load session');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Derived values
  const bestLap = useMemo(() => {
    const best = laps.find((l) => l.is_best === 1);
    return best?.lap_number ?? (laps.length > 0 ? laps[0].lap_number : null);
  }, [laps]);

  const gpsLaps = useMemo(() => laps.map((l) => l.lap_number), [laps]);

  const handleTabChange = useCallback((tab: Tab) => {
    setActiveTab(tab);
  }, []);

  // F-key shortcut to open Focus Mode, D-key for Driving Analyzer
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === 'f') setFocusOpen(true);
      if (e.key === 'd') setAnalyzerOpen(true);
    }
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, []);

  // ── Loading / error states ─────────────────────────────────────

  if (loading) {
    return <SkeletonSessionDetail />;
  }

  if (error || !session) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <h1 className="text-2xl font-monument text-chalk mb-2">Session Not Found</h1>
          <p className="text-steel font-body mb-4">{error || 'The session could not be loaded.'}</p>
          <Link
            href="/app/sessions"
            className="text-acid-green hover:underline font-body text-sm"
          >
            Back to Sessions
          </Link>
        </div>
      </div>
    );
  }

  // ── Page render ────────────────────────────────────────────────

  const showTrackPrompt = session.track_unnamed && session.track_id && !trackNamed;

  return (
    <div>
      {/* Track name prompt — shown when track has no user-given name */}
      {showTrackPrompt && (
        <TrackNamePrompt
          trackId={session.track_id!}
          onNamed={(newName) => {
            setTrackNamed(true);
            setSession((prev) => prev ? { ...prev, track_name: newName, track_unnamed: false } : prev);
          }}
        />
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link
              href="/app/sessions"
              className="text-steel hover:text-chalk text-sm font-body transition-colors"
            >
              Sessions
            </Link>
            <span className="text-steel/60">/</span>
          </div>
          <h1 className="text-2xl font-monument text-chalk tracking-tight">
            {session.display_name || session.csv_filename?.replace('.csv', '') || session.session_id}
          </h1>
          <p className="text-steel text-sm font-body mt-1">
            {session.driver_name}
            {session.track_name && !session.track_unnamed ? ` \u2022 ${session.track_name}` : ''}
            {` \u2022 ${formatDate(session.session_date)}`}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Grade badge */}
          {session.grade && (
            <div
              className={`w-14 h-14 flex items-center justify-center rounded-lg border-2 font-monument text-2xl ${gradeColorClass(session.grade)}`}
            >
              {session.grade}
            </div>
          )}

          {/* Report download */}
          <a
            href={`${BACKEND_URL}/api/v1/sessions/${sessionId}/report?format=html`}
            className="px-4 py-2 bg-concrete border border-steel/20 rounded-lg text-sm text-chalk font-body hover:bg-steel/10 transition-colors"
            target="_blank"
            rel="noopener noreferrer"
          >
            Download Report
          </a>

          {/* Driving Analyzer */}
          <button
            onClick={() => setAnalyzerOpen(true)}
            className="flex items-center gap-2 px-4 py-2 bg-concrete border border-acid-green/30 rounded-lg text-sm text-acid-green font-body hover:bg-gold/10 transition-colors"
            aria-label="Open Driving Analyzer (D)"
            title="Open Driving Analyzer (D)"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="7" cy="7" r="5" /><path d="M7 4v3l2 1.5" />
            </svg>
            Driving Analyzer
            <kbd className="text-[10px] px-1 py-0.5 rounded bg-asphalt border border-steel/20 text-steel/50 font-telemetry">D</kbd>
          </button>

          {/* Focus Mode */}
          <button
            onClick={() => setFocusOpen(true)}
            className="flex items-center gap-2 px-4 py-2 bg-concrete border border-steel/20 rounded-lg text-sm text-chalk font-body hover:bg-steel/10 transition-colors"
            aria-label="Open focus mode (F)"
            title="Open Focus Mode (F)"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
              <polyline points="8,2 12,2 12,6" /><line x1="12" y1="2" x2="7" y2="7" />
              <polyline points="6,12 2,12 2,8" /><line x1="2" y1="12" x2="7" y2="7" />
            </svg>
            Focus Mode
            <kbd className="text-[10px] px-1 py-0.5 rounded bg-asphalt border border-steel/20 text-steel/50 font-telemetry">F</kbd>
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-6 border-b border-steel/10">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => handleTabChange(tab.key)}
            className={`px-4 py-2.5 text-sm font-body transition-colors relative ${
              activeTab === tab.key
                ? 'text-acid-green'
                : 'text-steel hover:text-chalk'
            }`}
          >
            {tab.label}
            {activeTab === tab.key && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-acid-green" />
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'overview' && (
        <OverviewTab session={session} scores={scores} laps={laps} bestLap={bestLap} sessionId={sessionId} corners={corners} onSessionUpdate={setSession} />
      )}
      {activeTab === 'corners' && <CornersTab corners={corners} sessionId={sessionId} />}
      {activeTab === 'timeline' && <TimelineTab sessionId={sessionId} />}
      {activeTab === 'analytics' && (
        <AnalyticsTab
          sessionId={sessionId}
          gpsLaps={gpsLaps}
          bestLap={bestLap}
          scores={scores}
          corners={corners}
          trackName={session?.track_name ?? null}
        />
      )}
      {activeTab === 'laps' && <LapDataTab laps={laps} conditionPhases={conditionPhases} />}

      <FocusMode
        sessionId={sessionId}
        isOpen={focusOpen}
        onClose={() => setFocusOpen(false)}
        gpsLaps={gpsLaps}
        bestLap={bestLap}
        activeTab={activeTab}
      />

      {analyzerOpen && (
        <Suspense fallback={
          <div className="fixed inset-0 z-50 bg-asphalt/98 flex items-center justify-center">
            <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
          </div>
        }>
          <DrivingAnalyzer
            sessionId={sessionId}
            onClose={() => setAnalyzerOpen(false)}
          />
        </Suspense>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// 1. Overview Tab
// ══════════════════════════════════════════════════════════════════

function OverviewTab({
  session,
  scores,
  laps,
  bestLap,
  sessionId,
  corners,
  onSessionUpdate,
}: {
  session: SessionData;
  scores: ScoreData | null;
  laps: LapData[];
  bestLap: number | null;
  sessionId: string;
  corners: CornerData[];
  onSessionUpdate: (s: SessionData) => void;
}) {
  const bestLapData = laps.find((l) => l.is_best === 1);

  // Editable session info state
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editFields, setEditFields] = useState<Record<string, string | null>>({});

  const startEditing = useCallback(() => {
    setEditFields({
      session_date: session.session_date || '',
      driver_name: session.driver_name || '',
      session_type: session.session_type || 'practice',
      track_state: session.track_state || 'dry',
      display_name: session.display_name || '',
    });
    setEditing(true);
  }, [session]);

  const cancelEditing = useCallback(() => {
    setEditing(false);
    setEditFields({});
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const resp = await api.patch(`/sessions/${session.session_id}`, editFields);
      if (resp) {
        onSessionUpdate({ ...session, ...resp } as SessionData);
        setEditing(false);
      }
    } catch {
      // API errors handled by api-client
    } finally {
      setSaving(false);
    }
  }, [session, editFields, onSessionUpdate]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Left column: Score breakdown */}
      <div className="lg:col-span-2">
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h2 className="text-lg font-monument text-chalk mb-1">Score Breakdown</h2>
          <p className="text-steel text-xs font-body mb-4">How your score is built</p>
          {scores ? (() => {
            // Derive maxes so they always sum to exactly 100
            const paceMax = scores.pace_max ?? 25;
            const consMax = scores.consistency_max ?? 25;
            const execMax = scores.execution_max ?? 20;
            const robMax  = scores.robustness_max ?? 15;
            const adaptMax = Math.max(0, 100 - paceMax - consMax - execMax - robMax);

            // Compute displayed total as sum of visible sub-scores
            // (backend total_score has confidence weighting that makes it diverge)
            const subScores = [
              scores.pace_score, scores.consistency_score,
              scores.execution_score, scores.robustness_score,
              scores.adaptation_score,
            ];
            const computedTotal = subScores.reduce<number>(
              (sum, v) => sum + (v ?? 0), 0,
            );

            return (
            <div>
              {/* Total score */}
              <div className="flex items-center gap-4 mb-6 pb-4 border-b border-steel/10">
                <div className="text-4xl font-monument text-chalk">
                  {subScores.some((v) => v != null)
                    ? Math.round(computedTotal)
                    : '\u2014'}
                </div>
                <div className="text-steel font-body text-sm">/ 100</div>
                {session.grade && (
                  <div
                    className={`ml-auto w-12 h-12 flex items-center justify-center rounded-lg border-2 font-monument text-xl ${gradeColorClass(session.grade)}`}
                  >
                    {session.grade}
                  </div>
                )}
              </div>

              {/* Category bars */}
              <ScoreBar
                label="Pace"
                score={scores.pace_score}
                max={paceMax}
                accentColor="#B6FF2E"
              />
              <ScoreBar
                label="Consistency"
                score={scores.consistency_score}
                max={consMax}
                accentColor="#00d4ff"
              />
              <ScoreBar
                label="Execution"
                score={scores.execution_score}
                max={execMax}
                accentColor="#D946EF"
              />
              <ScoreBar
                label="Robustness"
                score={scores.robustness_score}
                max={robMax}
                accentColor="#FF6A00"
              />
              <ScoreBar
                label="Adaptation"
                score={scores.adaptation_score}
                max={adaptMax}
                accentColor="#FFD400"
              />

              {/* Strengths / Weaknesses */}
              {(scores.strengths?.length > 0 || scores.weaknesses?.length > 0) && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-6 pt-4 border-t border-steel/10">
                  {scores.strengths?.length > 0 && (
                    <div>
                      <h3 className="text-sm font-body text-green-400 mb-2">
                        Strengths
                      </h3>
                      <ul className="space-y-1">
                        {scores.strengths.map((s, i) => (
                          <li
                            key={i}
                            className="text-sm text-chalk/80 font-body"
                          >
                            {s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {scores.weaknesses?.length > 0 && (
                    <div>
                      <h3 className="text-sm font-body text-red-400 mb-2">
                        Areas to Improve
                      </h3>
                      <ul className="space-y-1">
                        {scores.weaknesses.map((w, i) => (
                          <li
                            key={i}
                            className="text-sm text-chalk/80 font-body"
                          >
                            {w}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* Performance Metrics Grid */}
              <div className="mt-6 pt-4 border-t border-steel/10">
                <h3 className="text-sm font-monument text-chalk mb-3">Performance Metrics</h3>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: 'Total', value: computedTotal, max: 100, color: 'text-chalk' },
                    { label: 'Pace', value: scores.pace_score, max: paceMax, color: 'text-acid-green' },
                    { label: 'Consistency', value: scores.consistency_score, max: consMax, color: 'text-cyan-400' },
                    { label: 'Execution', value: scores.execution_score, max: execMax, color: 'text-racing-purple' },
                    { label: 'Robustness', value: scores.robustness_score, max: robMax, color: 'text-pit-orange' },
                    { label: 'Adaptation', value: scores.adaptation_score, max: adaptMax, color: 'text-marshal-yellow' },
                  ].map((m) => (
                    <div key={m.label} className="bg-asphalt rounded-lg p-3">
                      <p className="text-steel text-[10px] font-body uppercase tracking-wider mb-1">{m.label}</p>
                      <span className={`text-xl font-monument ${m.color}`}>
                        {m.value != null ? Math.round(m.value) : '\u2014'}
                      </span>
                      <span className="text-steel text-xs font-body ml-1">/ {Math.round(m.max)}</span>
                    </div>
                  ))}
                  <div className="bg-asphalt rounded-lg p-3">
                    <p className="text-steel text-[10px] font-body uppercase tracking-wider mb-1">Grade</p>
                    <span className={`text-xl font-monument ${gradeColorClass(session.grade).split(' ')[0]}`}>
                      {session.grade || '\u2014'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            );
          })() : (
            <p className="text-steel font-body text-sm">
              No score data available for this session.
            </p>
          )}
        </div>
      </div>

      {/* Right column: Session metadata + best lap */}
      <div className="space-y-6">
        {/* Metadata card */}
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-monument text-chalk">Session Info</h2>
            {!editing ? (
              <button
                onClick={startEditing}
                className="text-xs text-steel hover:text-acid-green transition-colors font-body"
              >
                Edit
              </button>
            ) : (
              <div className="flex gap-2">
                <button
                  onClick={cancelEditing}
                  className="text-xs text-steel hover:text-chalk transition-colors font-body"
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="text-xs text-acid-green hover:text-chalk transition-colors font-body disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
              </div>
            )}
          </div>
          {editing ? (
            <div className="space-y-3">
              <EditRow
                label="Name"
                value={editFields.display_name || ''}
                onChange={(v) => setEditFields({ ...editFields, display_name: v })}
              />
              <EditRow
                label="Driver"
                value={editFields.driver_name || ''}
                onChange={(v) => setEditFields({ ...editFields, driver_name: v })}
              />
              <EditRow
                label="Date"
                value={editFields.session_date || ''}
                type="date"
                onChange={(v) => setEditFields({ ...editFields, session_date: v })}
              />
              <SelectRow
                label="Type"
                value={editFields.session_type || 'practice'}
                options={['practice', 'qualifying', 'race', 'test', 'endurance']}
                onChange={(v) => setEditFields({ ...editFields, session_type: v })}
              />
              <SelectRow
                label="Conditions"
                value={editFields.track_state || 'dry'}
                options={['dry', 'wet', 'damp', 'mixed']}
                onChange={(v) => setEditFields({ ...editFields, track_state: v })}
              />
              <MetaRow label="File" value={session.csv_filename} />
              <MetaRow
                label="Laps"
                value={session.n_laps != null ? String(session.n_laps) : '\u2014'}
              />
            </div>
          ) : (
            <dl className="space-y-3">
              <MetaRow label="File" value={session.csv_filename} />
              <MetaRow label="Driver" value={session.driver_name} />
              <MetaRow label="Track" value={session.track_name || 'Unknown'} />
              <MetaRow label="Type" value={session.session_type} />
              <MetaRow label="Conditions" value={session.track_state} />
              <MetaRow label="Date" value={formatDate(session.session_date)} />
              {session.kart_name && (
                <MetaRow label="Kart" value={session.kart_name} />
              )}
              <MetaRow
                label="Laps"
                value={session.n_laps != null ? String(session.n_laps) : '\u2014'}
              />
            </dl>
          )}
        </div>

        {/* Best lap card */}
        {bestLapData && (
          <div className="bg-concrete rounded-xl border border-acid-green/20 p-6">
            <h2 className="text-lg font-monument text-acid-green mb-4">
              Best Lap #{bestLap}
            </h2>
            <dl className="space-y-3">
              <MetaRow
                label="Time"
                value={formatLapTime(bestLapData.lap_time_s)}
                highlight
              />
              <MetaRow
                label="Avg Speed"
                value={`${mpsToKmh(bestLapData.speed_mean_mps)} km/h`}
              />
              <MetaRow
                label="Max Speed"
                value={`${mpsToKmh(bestLapData.speed_max_mps)} km/h`}
              />
            </dl>
          </div>
        )}
      </div>

      {/* Full-width sections below the 2-column layout */}
      <div className="lg:col-span-3 space-y-6">
        <DrivingStyleSection sessionId={sessionId} />
        <SessionDebrief
          totalScore={session.total_score}
          grade={session.grade}
          scores={scores}
          laps={laps}
          corners={corners}
        />
        <AchievementsBadges badges={scores?.badges} />
      </div>
    </div>
  );
}

function MetaRow({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="flex justify-between">
      <dt className="text-steel text-sm font-body">{label}</dt>
      <dd
        className={`text-sm font-telemetry ${
          highlight ? 'text-acid-green' : 'text-chalk'
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function EditRow({
  label,
  value,
  type = 'text',
  onChange,
}: {
  label: string;
  value: string;
  type?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex justify-between items-center">
      <label className="text-steel text-sm font-body">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-asphalt text-chalk text-sm font-telemetry px-2 py-1 rounded border border-steel/20 focus:border-acid-green/50 outline-none w-40"
      />
    </div>
  );
}

function SelectRow({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex justify-between items-center">
      <label className="text-steel text-sm font-body">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-asphalt text-chalk text-sm font-telemetry px-2 py-1 rounded border border-steel/20 focus:border-acid-green/50 outline-none w-40"
      >
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt.charAt(0).toUpperCase() + opt.slice(1)}
          </option>
        ))}
      </select>
    </div>
  );
}

// (Analytics Tab moved to components/app/analytics/AnalyticsTab.tsx)

// ══════════════════════════════════════════════════════════════════
// 3. Lap Data Tab
// ══════════════════════════════════════════════════════════════════


function LapDataTab({ laps, conditionPhases }: { laps: LapData[]; conditionPhases: ConditionPhase[] }) {
  const chartRef = useRef<HTMLCanvasElement>(null);

  // Derived stats
  const validLaps = useMemo(() => laps.filter((l) => l.is_valid && l.lap_time_s != null && l.lap_time_s > 0), [laps]);
  const validTimes = useMemo(() => validLaps.map((l) => l.lap_time_s!), [validLaps]);

  const bestTime = validTimes.length > 0 ? Math.min(...validTimes) : null;
  const meanTime = validTimes.length > 0 ? validTimes.reduce((a, b) => a + b, 0) / validTimes.length : null;
  const medianTime = useMemo(() => {
    if (validTimes.length === 0) return null;
    const sorted = [...validTimes].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }, [validTimes]);

  const consistencyCV = useMemo(() => {
    if (validTimes.length < 2 || !meanTime) return null;
    const stddev = Math.sqrt(validTimes.reduce((a, t) => a + (t - meanTime) ** 2, 0) / validTimes.length);
    return (stddev / meanTime) * 100;
  }, [validTimes, meanTime]);

  const bestLapData = laps.find((l) => l.is_best === 1);

  // Build phase lookup
  const phaseMap = useMemo(() => {
    const m: Record<number, string> = {};
    for (const p of conditionPhases) {
      for (let lap = p.lap_start; lap <= p.lap_end; lap++) {
        m[lap] = p.label || `Phase ${p.phase_id}`;
      }
    }
    return m;
  }, [conditionPhases]);

  // Lap times bar chart
  useEffect(() => {
    if (!chartRef.current || validLaps.length === 0) return;

    const canvas = chartRef.current;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;
    ctx.clearRect(0, 0, W, H);

    const pad = { top: 25, right: 15, bottom: 35, left: 55 };
    const cW = W - pad.left - pad.right;
    const cH = H - pad.top - pad.bottom;

    const allTimes = laps.filter((l) => l.lap_time_s != null && l.lap_time_s > 0).map((l) => l.lap_time_s!);
    if (allTimes.length === 0) return;

    const minT = Math.min(...allTimes) * 0.995;
    const maxT = Math.max(...allTimes) * 1.005;
    const n = laps.length;
    const barWidth = Math.max(4, Math.min(30, (cW / n) * 0.7));
    const gap = (cW - barWidth * n) / (n + 1);

    const xBar = (i: number) => pad.left + gap + i * (barWidth + gap);
    const yScale = (t: number) => pad.top + cH - ((t - minT) / (maxT - minT)) * cH;

    // Grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    const nGridY = 4;
    for (let i = 0; i <= nGridY; i++) {
      const y = pad.top + (i / nGridY) * cH;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(W - pad.right, y);
      ctx.stroke();
    }

    // Mean line
    if (meanTime != null) {
      ctx.strokeStyle = 'rgba(255,140,0,0.6)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 4]);
      const meanY = yScale(meanTime);
      ctx.beginPath();
      ctx.moveTo(pad.left, meanY);
      ctx.lineTo(W - pad.right, meanY);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Best lap reference line
    if (bestTime != null) {
      ctx.strokeStyle = 'rgba(61,220,132,0.3)';
      ctx.setLineDash([4, 4]);
      const bestY = yScale(bestTime);
      ctx.beginPath();
      ctx.moveTo(pad.left, bestY);
      ctx.lineTo(W - pad.right, bestY);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Y-axis labels
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    for (let i = 0; i <= nGridY; i++) {
      const val = maxT - (i / nGridY) * (maxT - minT);
      const y = pad.top + (i / nGridY) * cH;
      ctx.fillText(formatLapTime(val), pad.left - 5, y + 3);
    }

    // Bars
    for (let i = 0; i < n; i++) {
      const lap = laps[i];
      const time = lap.lap_time_s;
      if (time == null || time <= 0) continue;

      const x = xBar(i);
      const y = yScale(time);
      const barH = pad.top + cH - y;
      const isBest = lap.is_best === 1;
      const isInvalid = lap.is_valid === 0;
      const isIncomplete = lap.invalid_reason?.toLowerCase().includes('incomplete') ||
                           lap.invalid_reason?.toLowerCase().includes('outlap') ||
                           lap.invalid_reason?.toLowerCase().includes('inlap');

      const isJoker = lap.is_joker === 1;
      const isPit = lap.invalid_reason === 'Pitted lap';

      if (isBest) {
        ctx.fillStyle = '#3ddc84';
      } else if (isJoker) {
        ctx.fillStyle = 'rgba(255,214,0,0.35)';
      } else if (isPit) {
        ctx.fillStyle = 'rgba(255,140,0,0.35)';
      } else if (isIncomplete) {
        ctx.fillStyle = 'rgba(255,214,0,0.4)';
      } else if (isInvalid) {
        ctx.fillStyle = 'rgba(255,68,68,0.3)';
      } else {
        ctx.fillStyle = 'rgba(255,255,255,0.25)';
      }
      ctx.fillRect(x, y, barWidth, barH);

      // Lap number label
      ctx.fillStyle = isInvalid ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.5)';
      ctx.font = '9px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(String(lap.lap_number), x + barWidth / 2, H - pad.bottom + 14);
    }

    // Legend
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'left';
    const legendY = 14;
    // Best
    ctx.fillStyle = '#3ddc84';
    ctx.fillRect(pad.left, legendY - 4, 10, 8);
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.fillText('Best', pad.left + 14, legendY + 2);
    // Mean
    const meanLegX = pad.left + 50;
    ctx.strokeStyle = 'rgba(255,140,0,0.8)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(meanLegX, legendY);
    ctx.lineTo(meanLegX + 12, legendY);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.fillText('Mean', meanLegX + 16, legendY + 2);
    // Incomplete
    const incLegX = meanLegX + 55;
    ctx.fillStyle = 'rgba(255,214,0,0.5)';
    ctx.fillRect(incLegX, legendY - 4, 10, 8);
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.fillText('Incomplete', incLegX + 14, legendY + 2);
  }, [laps, validLaps, meanTime, bestTime]);

  if (laps.length === 0) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-8 text-center">
        <p className="text-steel font-body">No lap data available for this session.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Performance Summary — 8 stat cards */}
      <div>
        <h2 className="text-lg font-monument text-chalk mb-4">Performance Summary</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard label="Best Time" value={bestTime != null ? formatLapTime(bestTime) : '\u2014'} accent="text-acid-green" />
          <StatCard label="Mean Time" value={meanTime != null ? formatLapTime(meanTime) : '\u2014'} />
          <StatCard label="Median Time" value={medianTime != null ? formatLapTime(medianTime) : '\u2014'} />
          <StatCard label="Consistency" value={consistencyCV != null ? `${consistencyCV.toFixed(1)}%` : '\u2014'} sub="CV" accent={consistencyCV != null && consistencyCV < 1.5 ? 'text-acid-green' : consistencyCV != null && consistencyCV > 3 ? 'text-safety-red' : undefined} />
          <StatCard label="Total Laps" value={String(laps.length)} />
          <StatCard label="Valid Laps" value={String(validLaps.length)} />
          <StatCard label="Best Avg Speed" value={bestLapData ? `${mpsToKmh(bestLapData.speed_mean_mps)} km/h` : '\u2014'} />
          <StatCard label="Best Max Speed" value={bestLapData ? `${mpsToKmh(bestLapData.speed_max_mps)} km/h` : '\u2014'} />
        </div>
      </div>

      {/* Lap Times Chart */}
      {validLaps.length > 0 && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h2 className="text-lg font-monument text-chalk mb-4">Lap Times</h2>
          <div className="rounded-lg overflow-hidden bg-asphalt">
            <canvas
              ref={chartRef}
              style={{ width: '100%', height: '220px', display: 'block' }}
            />
          </div>
        </div>
      )}

      {/* Lap Data Table */}
      <div>
        <h2 className="text-lg font-monument text-chalk mb-4">Lap Data</h2>
        <div className="bg-concrete rounded-xl border border-steel/10 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-steel/10">
                  <th className="text-left px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">Lap</th>
                  <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">Time</th>
                  <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">Avg Speed</th>
                  <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">Max Speed</th>
                  <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">Max Braking</th>
                  <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">Max Accel</th>
                  <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">Line</th>
                  <th className="text-center px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">Phase</th>
                  <th className="text-center px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">Status</th>
                </tr>
              </thead>
              <tbody>
                {laps.map((lap) => {
                  const isBest = lap.is_best === 1;
                  const isInvalid = lap.is_valid === 0;
                  const isJoker = lap.is_joker === 1;
                  const isPit = lap.invalid_reason === 'Pitted lap';
                  const isIncomplete = isInvalid && (
                    lap.invalid_reason?.toLowerCase().includes('incomplete') ||
                    lap.invalid_reason?.toLowerCase().includes('outlap') ||
                    lap.invalid_reason?.toLowerCase().includes('inlap')
                  );
                  const phaseName = phaseMap[lap.lap_number] || (lap.phase_id != null ? `P${lap.phase_id}` : '\u2014');

                  return (
                    <tr
                      key={lap.lap_number}
                      className={`border-b border-steel/5 transition-colors hover:bg-asphalt/50 ${
                        isBest ? 'bg-acid-green/5' : ''
                      } ${isJoker ? 'opacity-50' : isIncomplete ? 'opacity-60' : isInvalid ? 'opacity-40' : ''}`}
                    >
                      <td className="px-4 py-3 font-telemetry text-chalk">
                        <span className="flex items-center gap-2">
                          {lap.lap_number}
                          {isBest && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-acid-green/20 text-acid-green font-body uppercase tracking-wide">
                              Best
                            </span>
                          )}
                        </span>
                      </td>
                      <td className={`px-4 py-3 text-right font-telemetry ${isBest ? 'text-acid-green' : 'text-chalk'}`}>
                        {formatLapTime(lap.lap_time_s)}
                      </td>
                      <td className="px-4 py-3 text-right font-telemetry text-chalk">
                        {mpsToKmh(lap.speed_mean_mps)} km/h
                      </td>
                      <td className="px-4 py-3 text-right font-telemetry text-chalk">
                        {mpsToKmh(lap.speed_max_mps)} km/h
                      </td>
                      <td className="px-4 py-3 text-right font-telemetry text-chalk">
                        {mps2ToG(lap.braking_max_mps2)} G
                      </td>
                      <td className="px-4 py-3 text-right font-telemetry text-chalk">
                        {mps2ToG(lap.accel_max_mps2)} G
                      </td>
                      <td className="px-4 py-3 text-right font-telemetry text-chalk">
                        {formatDistance(lap.line_length_m)} m
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-steel/10 text-steel font-body">
                          {phaseName}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        {isJoker ? (
                          <span
                            className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase bg-marshal-yellow/20 text-marshal-yellow border border-marshal-yellow/30"
                            title="Joker lap — excluded from ranking"
                          >
                            J
                          </span>
                        ) : isPit ? (
                          <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase bg-pit-orange/20 text-pit-orange border border-pit-orange/30">
                            Pit
                          </span>
                        ) : isIncomplete ? (
                          <span
                            className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase bg-marshal-yellow/20 text-marshal-yellow border border-marshal-yellow/30"
                            title={lap.invalid_reason || 'Incomplete'}
                          >
                            {lap.invalid_reason || 'Incomplete'}
                          </span>
                        ) : isInvalid ? (
                          <span
                            className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase bg-safety-red/20 text-safety-red border border-safety-red/30"
                            title={lap.invalid_reason || 'Invalid lap'}
                          >
                            {lap.invalid_reason || 'Invalid'}
                          </span>
                        ) : (
                          <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase bg-green-500/10 text-green-400 border border-green-500/20">
                            Valid
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Track Condition Phases */}
      {conditionPhases.length > 0 && (
        <div>
          <h2 className="text-lg font-monument text-chalk mb-4">Track Condition Phases</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {conditionPhases.map((phase) => (
              <div
                key={phase.phase_id}
                className="bg-concrete rounded-xl border border-steel/10 p-5"
              >
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-monument text-chalk">
                    {phase.label || `Phase ${phase.phase_id}`}
                  </h3>
                  <span className="text-xs font-telemetry text-steel">
                    Laps {phase.lap_start}–{phase.lap_end}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-steel font-body block">Median Pace</span>
                    <span className="text-chalk font-telemetry text-sm">
                      {formatLapTime(phase.median_pace_s)}
                    </span>
                  </div>
                  <div>
                    <span className="text-steel font-body block">Confidence</span>
                    <span className="text-chalk font-telemetry text-sm">
                      {phase.confidence != null ? `${(phase.confidence * 100).toFixed(0)}%` : '\u2014'}
                    </span>
                  </div>
                  <div>
                    <span className="text-steel font-body block">Laps</span>
                    <span className="text-chalk font-telemetry text-sm">
                      {phase.lap_end - phase.lap_start + 1}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <p className="text-steel text-[10px] font-body uppercase tracking-wider mb-1">{label}</p>
      <span className={`text-lg font-monument ${accent || 'text-chalk'}`}>{value}</span>
      {sub && <span className="text-steel text-xs font-body ml-1">{sub}</span>}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// 6. Timeline Tab
// ══════════════════════════════════════════════════════════════════

interface TimelineEvent {
  lap: number;
  lap_time_s: number;
  event_type: string;
  severity: 'info' | 'positive' | 'warning' | 'highlight';
  description: string;
  delta_to_best_s: number;
  rolling_avg_s: number;
  cumulative_time_s: number;
}

interface SessionTimelineData {
  session_id: string;
  driver_name: string;
  total_laps: number;
  total_time_s: number;
  best_lap: number;
  best_time_s: number;
  events: TimelineEvent[];
  summary: string;
  narrative: string[];
  event_counts: Record<string, number>;
}

interface LapProgressData {
  lap_numbers: number[];
  times: number[];
  rolling_avg: number[];
  trend_slope: number;
  is_improving: boolean;
}

interface StintData {
  stints: {
    stint_number: number;
    lap_start: number;
    lap_end: number;
    n_laps: number;
    best_time: number | null;
    mean_time: number | null;
    pace_drop_pct: number | null;
  }[];
}

const SEVERITY_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  highlight: { bg: 'bg-yellow-400/10', border: 'border-l-yellow-400', text: 'text-yellow-400' },
  positive:  { bg: 'bg-green-400/10',  border: 'border-l-green-400',  text: 'text-green-400' },
  warning:   { bg: 'bg-orange-400/10',  border: 'border-l-orange-400', text: 'text-orange-400' },
  info:      { bg: 'bg-blue-400/5',    border: 'border-l-blue-400',   text: 'text-blue-400' },
};

const EVENT_ICONS: Record<string, string> = {
  pb:              '\u2605',   // star
  hot_lap:         '\u26A1',   // lightning
  slow_lap:        '\u26A0',   // warning
  momentum_up:     '\u2191',   // up arrow
  momentum_down:   '\u2193',   // down arrow
  first_lap:       '\u25B6',   // play
  final_lap:       '\u2588',   // block (finish)
  consistent_run:  '\u2261',   // triple bar
  stint_start:     '\u27A4',   // arrow
};

const DOT_COLORS: Record<string, string> = {
  highlight: 'bg-yellow-400',
  positive:  'bg-green-400',
  warning:   'bg-orange-400',
  info:      'bg-blue-400',
};

function TimelineTab({ sessionId }: { sessionId: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [timeline, setTimeline] = useState<SessionTimelineData | null>(null);
  const [progress, setProgress] = useState<LapProgressData | null>(null);
  const [stints, setStints] = useState<StintData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    Promise.allSettled([
      api.get<SessionTimelineData>(`/sessions/${sessionId}/timeline`),
      api.get<LapProgressData>(`/sessions/${sessionId}/lap-progress`),
      api.get<StintData>(`/sessions/${sessionId}/stint-analysis`),
    ]).then(([timelineResult, progressResult, stintsResult]) => {
      if (cancelled) return;
      if (timelineResult.status === 'fulfilled') setTimeline(timelineResult.value);
      if (progressResult.status === 'fulfilled') setProgress(progressResult.value);
      if (stintsResult.status === 'fulfilled') setStints(stintsResult.value);
      setLoading(false);
    });

    return () => { cancelled = true; };
  }, [sessionId]);

  // Draw lap progress chart
  useEffect(() => {
    if (!progress || !canvasRef.current) return;
    const { lap_numbers, times, rolling_avg, is_improving, trend_slope } = progress;
    if (times.length === 0) return;

    const canvas = canvasRef.current;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = rect.height;

    ctx.clearRect(0, 0, W, H);

    const pad = { top: 25, right: 15, bottom: 35, left: 55 };
    const cW = W - pad.left - pad.right;
    const cH = H - pad.top - pad.bottom;

    const minTime = Math.min(...times) * 0.995;
    const maxTime = Math.max(...times) * 1.005;
    const bestTime = Math.min(...times);
    const n = times.length;
    const barWidth = Math.max(4, Math.min(30, (cW / n) * 0.7));
    const gap = (cW - barWidth * n) / (n + 1);

    const xBar = (i: number) => pad.left + gap + i * (barWidth + gap);
    const yScale = (t: number) => pad.top + cH - ((t - minTime) / (maxTime - minTime)) * cH;

    // Grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    const nGridY = 4;
    for (let i = 0; i <= nGridY; i++) {
      const y = pad.top + (i / nGridY) * cH;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(W - pad.right, y);
      ctx.stroke();
    }

    // Best lap reference line
    ctx.strokeStyle = 'rgba(61,220,132,0.3)';
    ctx.setLineDash([4, 4]);
    const bestY = yScale(bestTime);
    ctx.beginPath();
    ctx.moveTo(pad.left, bestY);
    ctx.lineTo(W - pad.right, bestY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Y-axis labels
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    for (let i = 0; i <= nGridY; i++) {
      const val = maxTime - (i / nGridY) * (maxTime - minTime);
      const y = pad.top + (i / nGridY) * cH;
      ctx.fillText(formatLapTime(val), pad.left - 5, y + 3);
    }

    // Bars
    for (let i = 0; i < n; i++) {
      const x = xBar(i);
      const y = yScale(times[i]);
      const barH = pad.top + cH - y;
      const isBest = times[i] === bestTime;

      ctx.fillStyle = isBest ? '#3ddc84' : 'rgba(255,255,255,0.25)';
      ctx.fillRect(x, y, barWidth, barH);

      // Lap number label
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.font = '9px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(String(lap_numbers[i]), x + barWidth / 2, H - pad.bottom + 14);
    }

    // Rolling average line
    ctx.strokeStyle = '#ff8c00';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const x = xBar(i) + barWidth / 2;
      const y = yScale(rolling_avg[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Trend line
    if (n >= 2) {
      ctx.strokeStyle = is_improving
        ? 'rgba(61,220,132,0.5)'
        : 'rgba(239,68,68,0.5)';
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 4]);
      const trendStart = times[0];
      const trendEnd = trendStart + trend_slope * (n - 1);
      ctx.beginPath();
      ctx.moveTo(xBar(0) + barWidth / 2, yScale(trendStart));
      ctx.lineTo(xBar(n - 1) + barWidth / 2, yScale(trendEnd));
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Legend
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'left';
    const legendY = 14;
    ctx.fillStyle = '#ff8c00';
    ctx.fillRect(pad.left, legendY - 4, 12, 2);
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.fillText('Rolling Avg', pad.left + 16, legendY);
    const trendX = pad.left + 95;
    ctx.fillStyle = is_improving ? 'rgba(61,220,132,0.7)' : 'rgba(239,68,68,0.7)';
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(trendX, legendY - 3);
    ctx.lineTo(trendX + 12, legendY - 3);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.fillText(
      `Trend (${is_improving ? 'improving' : 'degrading'})`,
      trendX + 16,
      legendY,
    );
    const bestX = trendX + 140;
    ctx.fillStyle = 'rgba(61,220,132,0.3)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(bestX, legendY - 3);
    ctx.lineTo(bestX + 12, legendY - 3);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.fillText('Best Lap', bestX + 16, legendY);
  }, [progress]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-6 h-6 border-2 border-acid-green border-t-transparent rounded-full animate-spin mr-3" />
        <span className="text-steel font-body text-sm">Loading timeline...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Session Timeline Event Feed ── */}
      {timeline && timeline.total_laps > 0 ? (
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h2 className="text-lg font-monument text-chalk mb-4">Session Timeline</h2>

          {/* Summary cards */}
          <div className="flex flex-wrap gap-3 mb-4">
            <div className="bg-asphalt rounded-lg px-3 py-2 text-center min-w-[80px]">
              <div className="text-[0.65rem] text-steel uppercase font-body">Total Laps</div>
              <div className="text-base font-bold text-blue-400 font-telemetry">{timeline.total_laps}</div>
            </div>
            <div className="bg-asphalt rounded-lg px-3 py-2 text-center min-w-[80px]">
              <div className="text-[0.65rem] text-steel uppercase font-body">Best Lap</div>
              <div className="text-base font-bold text-yellow-400 font-telemetry">
                L{timeline.best_lap} ({timeline.best_time_s != null ? timeline.best_time_s.toFixed(3) : '—'}s)
              </div>
            </div>
            {(timeline.event_counts.pb ?? 0) > 0 && (
              <div className="bg-asphalt rounded-lg px-3 py-2 text-center min-w-[80px]">
                <div className="text-[0.65rem] text-steel uppercase font-body">PBs Set</div>
                <div className="text-base font-bold text-green-400 font-telemetry">{timeline.event_counts.pb}</div>
              </div>
            )}
            {(timeline.event_counts.hot_lap ?? 0) > 0 && (
              <div className="bg-asphalt rounded-lg px-3 py-2 text-center min-w-[80px]">
                <div className="text-[0.65rem] text-steel uppercase font-body">Hot Laps</div>
                <div className="text-base font-bold text-acid-green font-telemetry">{timeline.event_counts.hot_lap}</div>
              </div>
            )}
            {(timeline.event_counts.slow_lap ?? 0) > 0 && (
              <div className="bg-asphalt rounded-lg px-3 py-2 text-center min-w-[80px]">
                <div className="text-[0.65rem] text-steel uppercase font-body">Slow Laps</div>
                <div className="text-base font-bold text-safety-red font-telemetry">{timeline.event_counts.slow_lap}</div>
              </div>
            )}
          </div>

          {/* Summary text */}
          {timeline.summary && (
            <div className="bg-blue-400/5 px-4 py-2.5 rounded-md text-sm text-steel font-body mb-4">
              {timeline.summary}
            </div>
          )}

          {/* Vertical timeline */}
          {timeline.events.length > 0 && (
            <div className="relative pl-8">
              {/* Vertical line */}
              <div className="absolute left-3 top-0 bottom-0 w-0.5 bg-steel/20" />

              {timeline.events.map((evt, idx) => {
                const sev = SEVERITY_STYLES[evt.severity] || SEVERITY_STYLES.info;
                const icon = EVENT_ICONS[evt.event_type] || '\u2022';
                const dotColor = DOT_COLORS[evt.severity] || DOT_COLORS.info;

                return (
                  <div key={idx} className="relative mb-2.5">
                    {/* Dot on timeline */}
                    <div
                      className={`absolute -left-5 top-1/2 -translate-y-1/2 w-3 h-3 rounded-full ${dotColor} border-2 border-asphalt z-10`}
                    />
                    {/* Event card */}
                    <div className={`${sev.bg} border-l-[3px] ${sev.border} rounded-r-md px-3 py-2`}>
                      <div className="flex items-center justify-between">
                        <span className={`text-sm font-semibold ${sev.text}`}>
                          {icon} Lap {evt.lap}
                        </span>
                        <span className="text-xs text-steel font-telemetry">
                          {evt.lap_time_s != null ? evt.lap_time_s.toFixed(3) : '—'}s
                          {evt.delta_to_best_s != null && evt.delta_to_best_s > 0 && (
                            <span className="text-steel/60"> (+{evt.delta_to_best_s.toFixed(3)})</span>
                          )}
                        </span>
                      </div>
                      <p className="text-xs text-steel font-body mt-0.5">
                        {evt.description}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        <div className="bg-concrete rounded-xl border border-steel/10 p-8 text-center">
          <p className="text-steel font-body text-sm">No timeline data available.</p>
        </div>
      )}

      {/* ── Lap Progress Chart ── */}
      {progress ? (
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-monument text-chalk">Lap Progress</h2>
            <div className="flex items-center gap-2 text-xs font-body">
              {progress.is_improving ? (
                <span className="text-green-400 flex items-center gap-1">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3">
                    <path fillRule="evenodd" d="M8 14a.75.75 0 0 1-.75-.75V4.56L4.03 7.78a.75.75 0 0 1-1.06-1.06l4.5-4.5a.75.75 0 0 1 1.06 0l4.5 4.5a.75.75 0 0 1-1.06 1.06L8.75 4.56v8.69A.75.75 0 0 1 8 14Z" clipRule="evenodd" />
                  </svg>
                  Improving
                </span>
              ) : (
                <span className="text-red-400 flex items-center gap-1">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3">
                    <path fillRule="evenodd" d="M8 2a.75.75 0 0 1 .75.75v8.69l3.22-3.22a.75.75 0 1 1 1.06 1.06l-4.5 4.5a.75.75 0 0 1-1.06 0l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.22 3.22V2.75A.75.75 0 0 1 8 2Z" clipRule="evenodd" />
                  </svg>
                  Degrading
                </span>
              )}
              <span className="text-steel">
                ({progress.trend_slope != null ? Math.abs(progress.trend_slope * 1000).toFixed(1) : '?'} ms/lap)
              </span>
            </div>
          </div>
          <div className="rounded-lg overflow-hidden bg-asphalt">
            <canvas
              ref={canvasRef}
              style={{ width: '100%', height: '250px', display: 'block' }}
            />
          </div>
        </div>
      ) : (
        <div className="bg-concrete rounded-xl border border-steel/10 p-8 text-center">
          <p className="text-steel font-body text-sm">No lap progress data available.</p>
        </div>
      )}

      {/* ── Stint Analysis ── */}
      {stints && stints.stints.length > 0 && (
        <div>
          <h2 className="text-lg font-monument text-chalk mb-4">Stint Analysis</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {stints.stints.map((stint) => (
              <div
                key={stint.stint_number}
                className="bg-concrete rounded-xl border border-steel/10 p-5"
              >
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-monument text-chalk">
                    Stint {stint.stint_number}
                  </h3>
                  <span className="text-xs font-telemetry text-steel">
                    Laps {stint.lap_start}\u2013{stint.lap_end}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-steel font-body block">Best</span>
                    <span className="text-acid-green font-telemetry text-sm">
                      {formatLapTime(stint.best_time)}
                    </span>
                  </div>
                  <div>
                    <span className="text-steel font-body block">Mean</span>
                    <span className="text-chalk font-telemetry text-sm">
                      {formatLapTime(stint.mean_time)}
                    </span>
                  </div>
                  <div>
                    <span className="text-steel font-body block">Laps</span>
                    <span className="text-chalk font-telemetry text-sm">{stint.n_laps}</span>
                  </div>
                  <div>
                    <span className="text-steel font-body block">Pace Drop</span>
                    <span
                      className={`font-telemetry text-sm ${
                        stint.pace_drop_pct != null && stint.pace_drop_pct > 1
                          ? 'text-safety-red'
                          : 'text-green-400'
                      }`}
                    >
                      {stint.pace_drop_pct != null
                        ? `${stint.pace_drop_pct.toFixed(1)}%`
                        : '\u2014'}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
