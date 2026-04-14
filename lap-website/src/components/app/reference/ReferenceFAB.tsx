'use client';

import { useState, useEffect, useRef, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { useReferenceOverlay } from './ReferenceOverlayProvider';
import type { ReferenceCandidate } from './types';

interface ReferenceFABProps {
  sessionId: string;
}

export function ReferenceFAB({ sessionId }: ReferenceFABProps) {
  const { referenceSession, referenceLap, referenceData, isLoading, setReference, clearReference } =
    useReferenceOverlay();
  const [open, setOpen] = useState(false);
  const [candidates, setCandidates] = useState<ReferenceCandidate[]>([]);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [search, setSearch] = useState('');
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingCandidates(true);
    api
      .get<ReferenceCandidate[]>(
        `/sessions/${sessionId}/reference-candidates`
      )
      .then((list) => {
        if (!cancelled) {
          setCandidates(Array.isArray(list) ? list : []);
        }
      })
      .catch(() => {
        if (!cancelled) setCandidates([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingCandidates(false);
      });
    return () => { cancelled = true; };
  }, [open, sessionId]);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  const filtered = useMemo(() => {
    if (!search.trim()) return candidates;
    const q = search.toLowerCase();
    return candidates.filter(
      (c) =>
        c.driver_name?.toLowerCase().includes(q) ||
        c.session_date?.includes(q) ||
        c.session_type?.toLowerCase().includes(q)
    );
  }, [candidates, search]);

  function handleSelect(c: ReferenceCandidate) {
    setReference(c.session_id, 1);
    setOpen(false);
    setSearch('');
  }

  function formatTime(s: number | null): string {
    if (s == null) return '--';
    const mins = Math.floor(s / 60);
    const secs = (s % 60).toFixed(1);
    return mins > 0 ? `${mins}:${secs.padStart(4, '0')}` : `${secs}s`;
  }

  // Active state — pill showing reference info
  if (referenceSession && referenceData) {
    const ref = referenceData.reference;
    const dateStr = ref.session_date
      ? new Date(ref.session_date).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' })
      : '';
    return (
      <div className="absolute bottom-4 right-4 z-20 flex items-center gap-2 bg-concrete border border-racing-purple/40 rounded-full px-3 py-1.5 font-telemetry text-xs text-racing-purple shadow-lg">
        {isLoading && (
          <span className="animate-spin w-3 h-3 border border-racing-purple border-t-transparent rounded-full" />
        )}
        <span className="text-chalk">{dateStr}</span>
        <span>L{ref.lap_number}</span>
        <span>({formatTime(ref.lap_time_s)})</span>
        <button
          onClick={clearReference}
          className="ml-1 text-racing-purple hover:text-chalk transition-colors"
          aria-label="Clear reference lap"
        >
          &times;
        </button>
      </div>
    );
  }

  return (
    <div className="absolute bottom-4 right-4 z-20" ref={modalRef}>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="w-10 h-10 bg-racing-purple rounded-full flex items-center justify-center text-white text-lg shadow-lg hover:bg-racing-purple/80 transition-colors"
          aria-label="Add reference lap from another session"
          title="Add reference lap"
        >
          +
        </button>
      )}

      {open && (
        <div className="absolute bottom-12 right-0 w-72 bg-concrete border border-steel/20 rounded-xl shadow-2xl overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-steel/10">
            <span className="text-xs font-monument text-chalk">Add Reference Lap</span>
            <button
              onClick={() => setOpen(false)}
              className="text-steel hover:text-chalk text-sm"
            >
              &times;
            </button>
          </div>
          <div className="p-2">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search sessions..."
              className="w-full bg-asphalt text-chalk border border-steel/20 rounded px-2 py-1.5 text-xs font-telemetry placeholder:text-steel/50 focus:outline-none focus:border-racing-purple/50"
            />
          </div>
          <div className="max-h-60 overflow-y-auto px-2 pb-2 space-y-1">
            {loadingCandidates && (
              <div className="text-center py-4 text-steel text-xs">Loading...</div>
            )}
            {!loadingCandidates && filtered.length === 0 && (
              <div className="text-center py-4 text-steel text-xs">No sessions on this track</div>
            )}
            {filtered.map((c) => (
              <button
                key={c.session_id}
                onClick={() => handleSelect(c)}
                className="w-full text-left px-2 py-1.5 rounded hover:bg-steel/10 transition-colors group"
              >
                <div className="flex justify-between items-center">
                  <span className="text-xs font-telemetry text-chalk">
                    {c.session_date
                      ? new Date(c.session_date).toLocaleDateString('en-GB', {
                          month: 'short',
                          day: 'numeric',
                        })
                      : 'Unknown'}{' '}
                    &mdash; {c.session_type || 'session'}
                  </span>
                  <span className="text-xs font-telemetry text-racing-purple">
                    {formatTime(c.best_lap_time_s)}
                  </span>
                </div>
                <div className="text-[10px] font-telemetry text-steel">
                  {c.driver_name} &bull; {c.n_laps} laps
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
