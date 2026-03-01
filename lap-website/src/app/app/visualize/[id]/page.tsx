'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api, BACKEND_URL } from '@/lib/api-client';
import { SpeedTraceZoom, GpsTrace, GGExplorer } from '@/components/app/charts';

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
  const [selectedLap, setSelectedLap] = useState<number | null>(null);
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
    const best = laps.find((l) => l.is_best === 1);
    return best?.lap_number ?? (laps.length > 0 ? laps[0].lap_number : null);
  }, [laps]);

  const gpsLaps = useMemo(() => laps.map((l) => l.lap_number), [laps]);

  const activeLap = selectedLap ?? bestLap;

  const handleLapSelect = useCallback((lapNum: number) => {
    setSelectedLap(lapNum);
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

  // ── Loading state ──────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-[#0f1117]">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-acid-green border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-steel font-body">Loading visualization...</p>
        </div>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="flex items-center justify-center h-screen bg-[#0f1117]">
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
    <div className="flex flex-col h-screen bg-[#0f1117] overflow-hidden">
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
          <span className="text-steel/30">|</span>
          <span className="text-chalk font-telemetry text-sm truncate max-w-[300px]">
            {session.csv_filename}
          </span>
          {session.track_name && (
            <>
              <span className="text-steel/30">-</span>
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
          <button
            type="button"
            onClick={toggleSidebar}
            className="text-steel hover:text-chalk text-sm font-body transition-colors px-2 py-1 rounded border border-steel/20 hover:border-steel/40"
          >
            {sidebarOpen ? 'Hide Laps' : 'Show Laps'}
          </button>
        </div>
      </div>

      {/* Main content — 3-panel layout */}
      <div className="flex flex-1 min-h-0">
        {/* GPS Map — left, full height */}
        <div className="flex-1 min-w-0 flex flex-col border-r border-steel/10">
          <div className="px-3 py-2 border-b border-steel/10 bg-concrete/50">
            <h3 className="text-xs font-monument text-steel uppercase tracking-wider">
              GPS Track Map
            </h3>
          </div>
          <div className="flex-1 p-2 overflow-hidden">
            <GpsTrace
              sessionId={sessionId}
              apiBase={apiBase}
              gpsLaps={gpsLaps}
              bestLap={activeLap}
              className="w-full h-full"
            />
          </div>
        </div>

        {/* Right panels — Speed Trace + GG Diagram, stacked */}
        <div className="flex-1 min-w-0 flex flex-col">
          {/* Speed Trace — top right */}
          <div className="flex-1 flex flex-col border-b border-steel/10">
            <div className="px-3 py-2 border-b border-steel/10 bg-concrete/50">
              <h3 className="text-xs font-monument text-steel uppercase tracking-wider">
                Speed Trace
              </h3>
            </div>
            <div className="flex-1 p-2 overflow-hidden">
              <SpeedTraceZoom
                sessionId={sessionId}
                apiBase={apiBase}
                gpsLaps={gpsLaps}
                bestLap={activeLap}
                className="w-full h-full"
              />
            </div>
          </div>

          {/* GG Diagram — bottom right */}
          <div className="flex-1 flex flex-col">
            <div className="px-3 py-2 border-b border-steel/10 bg-concrete/50">
              <h3 className="text-xs font-monument text-steel uppercase tracking-wider">
                G-G Diagram
              </h3>
            </div>
            <div className="flex-1 p-2 overflow-hidden">
              <GGExplorer
                sessionId={sessionId}
                apiBase={apiBase}
                gpsLaps={gpsLaps}
                bestLap={activeLap}
                className="w-full h-full"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Lap selector bar — bottom, collapsible */}
      {sidebarOpen && (
        <div className="border-t border-steel/10 bg-concrete shrink-0">
          <div className="px-4 py-2 flex items-center gap-2 overflow-x-auto">
            <span className="text-steel text-xs font-body shrink-0 mr-2">Laps:</span>
            {laps.map((lap) => {
              const isActive = lap.lap_number === activeLap;
              const isBest = lap.is_best === 1;
              return (
                <button
                  key={lap.lap_number}
                  type="button"
                  onClick={() => handleLapSelect(lap.lap_number)}
                  className={`
                    shrink-0 px-3 py-1.5 rounded text-xs font-telemetry transition-colors
                    ${
                      isActive
                        ? 'bg-acid-green/20 text-acid-green border border-acid-green/40'
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
              <span className="text-steel/50 text-xs font-body">No lap data available</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
