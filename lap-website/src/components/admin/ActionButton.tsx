'use client';

import { useState } from 'react';

interface ActionButtonProps {
  label: string;
  onConfirm: (reason: string) => Promise<void>;
  variant?: 'danger' | 'primary';
  requireReason?: boolean;
}

export function ActionButton({
  label,
  onConfirm,
  variant = 'primary',
  requireReason = true,
}: ActionButtonProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(false);

  const colors = variant === 'danger'
    ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
    : 'bg-gold/20 text-gold hover:bg-gold/30';

  async function handleConfirm() {
    if (requireReason && !reason.trim()) return;
    setLoading(true);
    try {
      await onConfirm(reason);
      setOpen(false);
      setReason('');
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`rounded px-3 py-1 text-xs font-medium transition-colors ${colors}`}
      >
        {label}
      </button>
    );
  }

  return (
    <div className="rounded-lg border border-white/10 bg-concrete p-3">
      {requireReason && (
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason (required)..."
          className="mb-2 w-full rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk placeholder-white/30"
          rows={2}
        />
      )}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleConfirm}
          disabled={loading || (requireReason && !reason.trim())}
          className="rounded bg-red-500/20 px-3 py-1 text-xs text-red-400 transition-colors hover:bg-red-500/30 disabled:opacity-50"
        >
          {loading ? 'Working...' : 'Confirm'}
        </button>
        <button
          type="button"
          onClick={() => { setOpen(false); setReason(''); }}
          className="rounded px-3 py-1 text-xs text-steel hover:text-chalk"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
