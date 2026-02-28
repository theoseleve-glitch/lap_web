'use client';

const statusMap: Record<string, string> = {
  active: 'bg-green-500/20 text-green-400',
  ok: 'bg-green-500/20 text-green-400',
  completed: 'bg-green-500/20 text-green-400',
  processed: 'bg-green-500/20 text-green-400',
  open: 'bg-green-500/20 text-green-400',
  running: 'bg-blue-500/20 text-blue-400',
  processing: 'bg-blue-500/20 text-blue-400',
  pending: 'bg-amber-500/20 text-amber-400',
  queued: 'bg-amber-500/20 text-amber-400',
  warning: 'bg-amber-500/20 text-amber-400',
  past_due: 'bg-orange-500/20 text-orange-400',
  failed: 'bg-red-500/20 text-red-400',
  error: 'bg-red-500/20 text-red-400',
  cancelled: 'bg-white/10 text-white/40',
  canceled: 'bg-white/10 text-white/40',
  resolved: 'bg-white/10 text-white/40',
};

export function StatusBadge({ status }: { status: string }) {
  const cls = statusMap[status] ?? 'bg-white/10 text-white/40';
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}
