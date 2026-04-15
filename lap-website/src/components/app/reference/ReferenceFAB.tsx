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
    // Use the reference session's best lap
    setReference(c.session_id, c.best_lap_number ?? 1);
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
  // Active state — labeled pill showing reference info
  if (referenceSession && referenceData) {
    const ref = referenceData.reference;
    const dateStr = ref.session_date
      ? new Date(ref.session_date).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' })
      : '';
    return (
      <div className="inline-flex items-center gap-2 bg-concrete border border-racing-purple/50 rounded-lg px-3 py-1.5 font-telemetry text-xs">
        {isLoading && (
          <span className="animate-spin w-3 h-3 border border-racing-purple border-t-transparent rounded-full" />
        )}
        <span className="text-steel uppercase text-[9px] tracking-wider">Reference</span>
        <span className="text-racing-purple">{dateStr} L{ref.lap_number}</span>
        <span className="text-chalk">({formatTime(ref.lap_time_s)})</span>
        <button
          onClick={clearReference}
          className="ml-1 text-steel hover:text-safety-red transition-colors text-base leading-none"
          aria-label="Clear reference lap"
          title="Remove reference lap"
        >
          &times;
        </button>
      </div>
    );
  }

  return (
    <div className="relative inline-block" ref={modalRef}>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 bg-racing-purple/15 border border-racing-purple/50 text-racing-purple hover:bg-racing-purple/25 hover:border-racing-purple rounded-lg px-3 py-1.5 text-xs font-telemetry transition-colors"
          aria-label="Compare with a lap from another session"
          title="Overlay a lap from another session on these charts"
        >
          <span className="text-base leading-none">+</span>
          <span className="uppercase tracking-wider text-[10px]">Compare with another session</span>
        </button>
      )}

      {open && (
        <div className="absolute top-10 right-0 w-80 bg-concrete border border-steel/20 rounded-xl shadow-2xl overflow-hidden z-30">
          <div className="flex items-center justify-between px-3 py-2 border-b border-steel/10">
            <div>
              <div className="text-xs font-monument text-chalk">Compare with another session</div>
              <div className="text-[10px] font-telemetry text-steel mt-0.5">Pick a session on this track to overlay its best lap</div>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-steel hover:text-chalk text-base leading-none"
              aria-label="Close"
            >
              &times;
            </button>
          </div>
          <div className="p-2">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by date, driver, or type..."
              className="w-full bg-asphalt text-chalk border border-steel/20 rounded px-2 py-1.5 text-xs font-telemetry placeholder:text-steel/50 focus:outline-none focus:border-racing-purple/50"
            />
          </div>
          <div className="max-h-60 overflow-y-auto px-2 pb-2 space-y-1">
            {loadingCandidates && (
              <div className="text-center py-4 text-steel text-xs">Loading sessions...</div>
            )}
            {!loadingCandidates && filtered.length === 0 && (
              <div className="text-center py-4 text-steel text-xs">No other sessions on this track</div>
            )}
            {filtered.map((c) => (
              <button
                key={c.session_id}
                onClick={() => handleSelect(c)}
                className="w-full text-left px-2 py-1.5 rounded hover:bg-racing-purple/10 hover:border-racing-purple/30 border border-transparent transition-colors group"
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
