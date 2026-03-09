'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';

interface ConsoleEntry {
  level: 'error' | 'warn';
  message: string;
  timestamp: number;
}

const MAX_ENTRIES = 50;

export function DiagnosticsOverlay() {
  const [visible, setVisible] = useState(false);
  const [entries, setEntries] = useState<ConsoleEntry[]>([]);
  const [showLog, setShowLog] = useState(false);
  const originals = useRef<{ error: typeof console.error; warn: typeof console.warn } | null>(null);
  const queryClient = useQueryClient();

  const toggle = useCallback((e: KeyboardEvent) => {
    if (e.ctrlKey && e.shiftKey && e.key === 'D') {
      e.preventDefault();
      setVisible((v) => !v);
    }
  }, []);

  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return;
    window.addEventListener('keydown', toggle);
    return () => window.removeEventListener('keydown', toggle);
  }, [toggle]);

  /* Intercept console.error and console.warn in development */
  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return;
    if (originals.current) return; // already hooked

    const origError = console.error; // eslint-disable-line no-console
    const origWarn = console.warn; // eslint-disable-line no-console
    originals.current = { error: origError, warn: origWarn };

    const capture = (level: 'error' | 'warn', args: unknown[]) => {
      const message = args.map((a) => (typeof a === 'string' ? a : JSON.stringify(a))).join(' ');
      setEntries((prev) => {
        const next = [...prev, { level, message: message.slice(0, 200), timestamp: Date.now() }];
        return next.length > MAX_ENTRIES ? next.slice(-MAX_ENTRIES) : next;
      });
    };

    console.error = (...args: unknown[]) => { // eslint-disable-line no-console
      capture('error', args);
      origError.apply(console, args);
    };
    console.warn = (...args: unknown[]) => { // eslint-disable-line no-console
      capture('warn', args);
      origWarn.apply(console, args);
    };

    return () => {
      console.error = origError; // eslint-disable-line no-console
      console.warn = origWarn; // eslint-disable-line no-console
      originals.current = null;
    };
  }, []);

  if (process.env.NODE_ENV !== 'development' || !visible) return null;

  const cache = queryClient.getQueryCache();
  const queries = cache.getAll();
  const fresh = queries.filter((q) => q.state.status === 'success').length;
  const stale = queries.filter((q) => q.isStale()).length;
  const fetching = queries.filter((q) => q.state.fetchStatus === 'fetching').length;

  const errorCount = entries.filter((e) => e.level === 'error').length;
  const warnCount = entries.filter((e) => e.level === 'warn').length;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] bg-asphalt/95 border border-steel/30 rounded-lg p-4 text-xs font-telemetry text-steel shadow-lg max-w-sm">
      <div className="flex justify-between items-center mb-2">
        <span className="text-acid-green font-bold">Diagnostics</span>
        <button onClick={() => setVisible(false)} className="text-steel hover:text-chalk">
          &times;
        </button>
      </div>
      <div className="space-y-1">
        <div>Queries: {queries.length} total, {fresh} fresh, {stale} stale, {fetching} fetching</div>
        <div className="flex items-center gap-3">
          <span>Console:</span>
          <span className={errorCount > 0 ? 'text-safety-red' : 'text-steel/60'}>{errorCount} errors</span>
          <span className={warnCount > 0 ? 'text-gold' : 'text-steel/60'}>{warnCount} warns</span>
          {entries.length > 0 && (
            <button
              onClick={() => setShowLog((v) => !v)}
              className="text-acid-green hover:underline"
            >
              {showLog ? 'hide' : 'show'}
            </button>
          )}
          {entries.length > 0 && (
            <button
              onClick={() => setEntries([])}
              className="text-steel/40 hover:text-steel"
            >
              clear
            </button>
          )}
        </div>
        <div>ENV: {process.env.NODE_ENV}</div>
        <div>API: {process.env.NEXT_PUBLIC_API_URL || 'localhost:5000'}</div>
      </div>
      {showLog && entries.length > 0 && (
        <div className="mt-2 border-t border-steel/20 pt-2 max-h-40 overflow-y-auto space-y-0.5">
          {entries.slice(-20).map((e, i) => (
            <div
              key={i}
              className={`truncate ${e.level === 'error' ? 'text-safety-red/80' : 'text-gold/80'}`}
              title={e.message}
            >
              <span className="text-steel/40">{new Date(e.timestamp).toLocaleTimeString()}</span>{' '}
              {e.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
