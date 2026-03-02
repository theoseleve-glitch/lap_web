'use client';

import { useState, useEffect, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';

export function DiagnosticsOverlay() {
  const [visible, setVisible] = useState(false);
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

  if (process.env.NODE_ENV !== 'development' || !visible) return null;

  const cache = queryClient.getQueryCache();
  const queries = cache.getAll();
  const fresh = queries.filter((q) => q.state.status === 'success').length;
  const stale = queries.filter((q) => q.isStale()).length;
  const fetching = queries.filter((q) => q.state.fetchStatus === 'fetching').length;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] bg-asphalt/95 border border-steel/30 rounded-lg p-4 text-xs font-telemetry text-steel shadow-lg max-w-xs">
      <div className="flex justify-between items-center mb-2">
        <span className="text-acid-green font-bold">Diagnostics</span>
        <button onClick={() => setVisible(false)} className="text-steel hover:text-chalk">
          &times;
        </button>
      </div>
      <div className="space-y-1">
        <div>Queries: {queries.length} total, {fresh} fresh, {stale} stale, {fetching} fetching</div>
        <div>ENV: {process.env.NODE_ENV}</div>
        <div>API: {process.env.NEXT_PUBLIC_API_URL || 'localhost:5000'}</div>
      </div>
    </div>
  );
}
