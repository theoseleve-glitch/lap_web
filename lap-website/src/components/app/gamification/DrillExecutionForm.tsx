'use client';

import { useState } from 'react';
import { api } from '@/lib/api-client';
import type { XpResult } from './types';

interface SessionOption {
  session_id: number;
  csv_filename: string;
  session_date: string;
}

interface DrillExecutionFormProps {
  planId: number;
  weekNumber: number;
  drillIndex: number;
  sessions: SessionOption[];
  onSubmit: (result: XpResult) => void;
  className?: string;
}

type DrillStatus = 'attempted' | 'completed' | 'skipped';

const STATUS_OPTIONS: { value: DrillStatus; label: string; color: string }[] = [
  { value: 'completed', label: 'Completed', color: '#22C55E' },
  { value: 'attempted', label: 'Attempted', color: '#f59e0b' },
  { value: 'skipped', label: 'Skipped', color: '#949494' },
];

export default function DrillExecutionForm({
  planId,
  weekNumber,
  drillIndex,
  sessions,
  onSubmit,
  className = '',
}: DrillExecutionFormProps) {
  const [sessionId, setSessionId] = useState<number | ''>('');
  const [status, setStatus] = useState<DrillStatus>('completed');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [xpGained, setXpGained] = useState<number | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setXpGained(null);
    setSubmitting(true);

    try {
      const body: Record<string, unknown> = {
        status,
        notes: notes.trim() || null,
      };
      if (sessionId !== '') {
        body.session_id = sessionId;
      }

      const result = await api.post<XpResult>(
        `/dev-plans/${planId}/drills/${weekNumber}/${drillIndex}/execute`,
        body,
      );

      if (result.xp_result && result.xp_result.xp_gained > 0) {
        setXpGained(result.xp_result.xp_gained);
      }

      onSubmit(result);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to submit drill';
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className={`space-y-4 ${className}`}>
      {/* Session selector */}
      <div>
        <label
          htmlFor="drill-session"
          className="block text-xs font-telemetry text-steel mb-1"
        >
          Link Session (optional)
        </label>
        <select
          id="drill-session"
          value={sessionId}
          onChange={(e) =>
            setSessionId(e.target.value === '' ? '' : Number(e.target.value))
          }
          className="w-full rounded-lg px-3 py-2 text-sm font-body text-chalk border transition-colors focus:outline-none focus:ring-1"
          style={{
            backgroundColor: '#141414',
            borderColor: '#949494',
          }}
        >
          <option value="">-- No session --</option>
          {sessions.map((s) => (
            <option key={s.session_id} value={s.session_id}>
              {s.csv_filename} ({s.session_date})
            </option>
          ))}
        </select>
      </div>

      {/* Status radio group */}
      <div>
        <p className="text-xs font-telemetry text-steel mb-2">Status</p>
        <div className="flex gap-3">
          {STATUS_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className="flex items-center gap-1.5 cursor-pointer"
            >
              <input
                type="radio"
                name="drill-status"
                value={opt.value}
                checked={status === opt.value}
                onChange={() => setStatus(opt.value)}
                className="sr-only"
              />
              <span
                className="w-4 h-4 rounded-full border-2 flex items-center justify-center transition-colors"
                style={{
                  borderColor: status === opt.value ? opt.color : '#949494',
                }}
              >
                {status === opt.value && (
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: opt.color }}
                  />
                )}
              </span>
              <span
                className="text-sm font-body"
                style={{ color: status === opt.value ? opt.color : '#949494' }}
              >
                {opt.label}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Notes */}
      <div>
        <label
          htmlFor="drill-notes"
          className="block text-xs font-telemetry text-steel mb-1"
        >
          Notes (optional)
        </label>
        <textarea
          id="drill-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder="How did it go?"
          className="w-full rounded-lg px-3 py-2 text-sm font-body text-chalk border resize-none transition-colors focus:outline-none focus:ring-1"
          style={{
            backgroundColor: '#141414',
            borderColor: '#949494',
          }}
        />
      </div>

      {/* Error */}
      {error && (
        <p className="text-sm font-body" style={{ color: '#ef4444' }}>
          {error}
        </p>
      )}

      {/* XP result */}
      {xpGained !== null && (
        <p className="text-sm font-telemetry font-semibold" style={{ color: '#22C55E' }}>
          +{xpGained} XP earned!
        </p>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={submitting}
        className="w-full py-2.5 px-4 rounded-lg font-monument text-sm font-bold uppercase tracking-wider transition-opacity disabled:opacity-50"
        style={{
          backgroundColor: '#22C55E',
          color: '#141414',
        }}
      >
        {submitting ? 'Submitting...' : 'Log Drill'}
      </button>
    </form>
  );
}
