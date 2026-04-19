'use client';

import { useEffect, useState, useCallback, useMemo, useLayoutEffect } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api, BACKEND_URL } from '@/lib/api-client';
import { SpeedTraceZoom, GpsTrace, GGExplorer } from '@/components/app/charts';
import { ChartErrorBoundary } from '@/components/shared/ChartErrorBoundary';
import { FullscreenToggle } from '@/components/shared/charts/FullscreenToggle';
import { ReferenceOverlayProvider, ReferenceFAB } from '@/components/app/reference';

// ── Types ────────────────────────────────────────────────────────

interface SessionData {
  session_id: string;
  csv_filename: string;
  driver_name: string;
  track_name: string | null;
  session_date: string;
  n_laps: number | null;
  best_lap_time_s: number | null;
}

interface LapData {
  lap_number: number;
  lap_time_s: number | null;
  is_best: number;
}

// ── Full-screen Visualize Page ──────────────────────────────────

export default function VisualizeSessionPage() {
  const params = useParams();
  const sessionId = params.id as string;

  const [session, setSession] = useState<SessionData | null>(null);
  const [laps, setLaps] = useState<LapData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedLaps, setSelectedLaps] = useState<number[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Fetch session + laps on mount
  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      setLoading(true);
      setError(null);

      try {
        const sessionData = await api.get<SessionData>(`/sessions/${sessionId}`);
        if (cancelled) return;
        setSession(sessionData);

        try {
          const lapsRes = await api.get<{ laps: LapData[] }>(`/sessions/${sessionId}/laps`);
          if (!cancelled) {
            setLaps(lapsRes.laps || []);
          }
        } catch {
          // Laps are non-critical
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
    const best = laps.find((l) => l.is_best);
    return best?.lap_number ?? (laps.length > 0 ? laps[0].lap_number : null);
  }, [laps]);

  const gpsLaps = useMemo(() => laps.map((l) => l.lap_number), [laps]);

  // Primary lap = first selected, or best. Compare lap = second selected.
  const primaryLap = selectedLaps.length > 0 ? selectedLaps[0] : bestLap;
  const compareLap = selectedLaps.length > 1 ? selectedLaps[1] : null;
  const primaryLapTime = laps.find((l) => l.lap_number === primaryLap)?.lap_time_s ?? null;
  const compareLapTime = compareLap != null ? (laps.find((l) => l.lap_number === compareLap)?.lap_time_s ?? null) : null;

  const handleLapSelect = useCallback((lapNum: number) => {
    setSelectedLaps((prev) => {
      if (prev.includes(lapNum)) {
        // Deselect — remove from selection
        return prev.filter((l) => l !== lapNum);
      }
      if (prev.length < 2) {
        // Add to selection (max 2)
        return [...prev, lapNum];
      }
      // Replace second selection
      return [prev[0], lapNum];
    });
  }, []);

  const toggleSidebar = useCallback(() => {
    setSidebarOpen((prev) => !prev);
  }, []);

  function formatLapTime(seconds: number | null | undefined): string {
    if (seconds == null || !isFinite(seconds)) return '--';
    if (seconds >= 60) {
      const mins = Math.floor(seconds / 60);
      const secs = seconds - mins * 60;
      return `${mins}:${secs.toFixed(3).padStart(6, '0')}`;
    }
    return `${seconds.toFixed(3)}s`;
  }

  const apiBase = BACKEND_URL;

  // Lock body scroll — this page is a full viewport overlay
  useLayoutEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  // ── Loading state ──────────────────────────────────────────────

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-asphalt">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-acid-green border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-steel font-body">Loading visualization...</p>
        </div>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-asphalt">
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

  // ── Full-screen layout ─────────────────────────────────────────

  return (
    <ReferenceOverlayProvider sessionId={sessionId} primaryLap={primaryLap}>
    <div className="fixed inset-0 z-50 flex flex-col bg-asphalt overflow-hidden">
      {/* Top bar — minimal chrome */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-steel/10 bg-concrete shrink-0">
        <div className="flex items-center gap-3">
          <Link
            href={`/app/sessions/${sessionId}`}
            className="text-steel hover:text-chalk text-sm font-body transition-colors flex items-center gap-1"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
              className="w-4 h-4"
            >
              <path
                fillRule="evenodd"
                d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z"
                clipRule="evenodd"
              />
            </svg>
            Back to Session
          </Link>
          <span className="text-steel/50">|</span>
          <span className="text-chalk font-telemetry text-sm truncate max-w-[300px]">
            {session.csv_filename}
          </span>
          {session.track_name && (
            <>
              <span className="text-steel/50">-</span>
              <span className="text-steel font-body text-sm">{session.track_name}</span>
            </>
          )}
        </div>

        <div className="flex items-center gap-3">
          {session.best_lap_time_s != null && (
            <span className="text-acid-green font-telemetry text-sm">
              Best: {formatLapTime(session.best_lap_time_s)}
            </span>
          )}
          <ReferenceFAB sessionId={sessionId} />
          <button
            type="button"
            onClick={toggleSidebar}
            className="text-steel hover:text-chalk text-sm font-body transition-colors px-2 py-1 rounded border border-steel/20 hover:border-steel/40"
          >
            {sidebarOpen ? 'Hide Laps' : 'Show Laps'}
          </button>
        </div>
      </div>

      {/* Main content — 3-panel VRS-style layout */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* GPS Map — left, full height */}
          <div className="flex-1 min-w-0 min-h-0 relative border-r border-steel/10">
            <span className="absolute top-1 left-2 z-10 text-[9px] font-monument text-steel/40 uppercase tracking-wider pointer-events-none">
              track map
            </span>
            <FullscreenToggle className="h-full w-full overflow-hidden" label="GPS Track Map fullscreen">
              <ChartErrorBoundary chartName="GpsTrace">
                <GpsTrace
                  sessionId={sessionId}
                  apiBase={apiBase}
                  gpsLaps={[]}
                  bestLap={primaryLap}
                  compareLap={compareLap}
                  className="w-full h-full"
                />
              </ChartErrorBoundary>
            </FullscreenToggle>
          </div>

          {/* Right panels — Speed Trace + GG Diagram, stacked */}
          <div className="flex-1 min-w-0 min-h-0 flex flex-col">
            {/* Speed Trace — top right */}
            <div className="flex-1 min-h-0 relative border-b border-steel/10">
              <span className="absolute top-1 left-2 z-10 text-[9px] font-monument text-steel/40 uppercase tracking-wider pointer-events-none">
                speed trace
              </span>
              <FullscreenToggle className="h-full w-full overflow-hidden" label="Speed Trace fullscreen">
                <ChartErrorBoundary chartName="SpeedTrace">
                  <SpeedTraceZoom
                    sessionId={sessionId}
                    apiBase={apiBase}
                    gpsLaps={[]}
                    bestLap={primaryLap}
                    compareLap={compareLap}
                    primaryLapTime={primaryLapTime}
                    compareLapTime={compareLapTime}
                    className="w-full h-full"
                  />
                </ChartErrorBoundary>
              </FullscreenToggle>
            </div>

            {/* GG Diagram — bottom right */}
            <div className="flex-1 min-h-0 relative">
              <span className="absolute top-1 left-2 z-10 text-[9px] font-monument text-steel/40 uppercase tracking-wider pointer-events-none">
                g-g diagram
              </span>
              <FullscreenToggle className="h-full w-full overflow-hidden" label="G-G Diagram fullscreen">
                <ChartErrorBoundary chartName="GGExplorer">
                  <GGExplorer
                    sessionId={sessionId}
                    apiBase={apiBase}
                    gpsLaps={[]}
                    bestLap={primaryLap}
                    className="w-full h-full"
                  />
                </ChartErrorBoundary>
              </FullscreenToggle>
            </div>
          </div>

        </div>

      {/* Lap selector bar — bottom, collapsible */}
      {sidebarOpen && (
        <div className="border-t border-steel/10 bg-concrete shrink-0">
          <div className="px-4 py-2 flex items-center gap-2 overflow-x-auto">
            <span className="text-steel text-xs font-body shrink-0 mr-2">Laps:</span>
            {laps.map((lap) => {
              const isPrimary = lap.lap_number === primaryLap;
              const isCompare = lap.lap_number === compareLap;
              const isBest = !!lap.is_best;
              return (
                <button
                  key={lap.lap_number}
                  type="button"
                  onClick={() => handleLapSelect(lap.lap_number)}
                  className={`
                    shrink-0 px-3 py-1.5 rounded text-xs font-telemetry transition-colors
                    ${
                      isPrimary
                        ? 'bg-acid-green/20 text-acid-green border border-acid-green/40'
                        : isCompare
                          ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                          : 'bg-asphalt text-steel border border-steel/20 hover:text-chalk hover:border-steel/40'
                    }
                  `}
                >
                  {lap.lap_number}
                  {isBest && (
                    <span className="ml-1 text-[9px] uppercase text-acid-green">best</span>
                  )}
                  {lap.lap_time_s != null && (
                    <span className="ml-1.5 text-steel/60">{formatLapTime(lap.lap_time_s)}</span>
                  )}
                </button>
              );
            })}
            {laps.length === 0 && (
              <span className="text-steel/50 text-xs font-body">No Lap Data available</span>
            )}
            {compareLap != null && (
              <span className="text-steel/40 text-[10px] font-telemetry shrink-0 ml-2">
                Delta: Lap {primaryLap} vs {compareLap}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
    </ReferenceOverlayProvider>
  );
}
