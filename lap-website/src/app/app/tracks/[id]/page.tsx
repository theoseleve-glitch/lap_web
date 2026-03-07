'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { StatCard, FormField, QueryError, SkeletonStatCards, SkeletonBox } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

interface TrackDetail {
  id: string;
  name: string;
  lap_length_m: number | null;
  has_joker: boolean;
  session_count: number;
  best_time_s: number | null;
  created_at: string | null;
  updated_at: string | null;
}

function fmtTime(s: number | null): string {
  if (s == null) return '\u2014';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function fmtLength(m: number | null): string {
  if (m == null || m <= 0) return '\u2014';
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${Math.round(m)} m`;
}

export default function TrackDetailPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const id = params.id as string;

  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [form, setForm] = useState({ name: '', has_joker: false });

  const { data: track, isLoading, error, refetch } = useQuery({
    queryKey: ['track', id],
    queryFn: () => api.get<TrackDetail>(`/tracks/${id}`),
  });

  const updateMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.patch<TrackDetail>(`/tracks/${id}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['track', id] });
      queryClient.invalidateQueries({ queryKey: ['tracks'] });
      setEditing(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.delete<{ deleted: boolean }>(`/tracks/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tracks'] });
      router.push('/app/tracks');
    },
  });

  const startEditing = () => {
    if (!track) return;
    setForm({ name: track.name || '', has_joker: track.has_joker });
    setEditing(true);
  };

  const handleSave = () => {
    if (!form.name.trim()) return;
    updateMutation.mutate({
      name: form.name.trim(),
      has_joker: form.has_joker,
    });
  };

  if (isLoading) {
    return (
      <div>
        <div className="mb-4">
          <SkeletonBox className="h-6 w-40 mb-2" />
          <SkeletonBox className="h-3 w-24" />
        </div>
        <SkeletonStatCards count={4} />
      </div>
    );
  }

  if (error) {
    return <QueryError message="Couldn't load track details." onRetry={() => refetch()} />;
  }

  if (!track) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
        <h2 className="font-monument text-lg text-chalk mb-2">Track not found</h2>
        <p className="text-steel font-body text-sm mb-4">This track may have been deleted or the link is invalid.</p>
        <Link href="/app/tracks" className="text-pit-orange font-telemetry text-xs hover:underline">
          Back to tracks
        </Link>
      </div>
    );
  }

  return (
    <div>
      <PageIntro
        title={track.name}
        subtitle={`${fmtLength(track.lap_length_m)} \u00b7 ${track.session_count} session${track.session_count !== 1 ? 's' : ''}`}
        actions={
          <div className="flex gap-2">
            <button
              type="button"
              onClick={startEditing}
              className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
            >
              Edit
            </button>
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="px-4 py-2 border border-safety-red/30 text-safety-red font-telemetry text-sm rounded hover:bg-safety-red/10 transition-colors"
            >
              Delete
            </button>
            <Link
              href="/app/tracks"
              className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
            >
              \u2190 All Tracks
            </Link>
          </div>
        }
      />

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="bg-safety-red/5 border border-safety-red/30 rounded-lg p-4 mb-6">
          <p className="text-chalk font-body text-sm mb-3">
            Are you sure you want to delete <strong>{track.name}</strong>?
            {track.session_count > 0 && (
              <span className="text-safety-red"> This track has {track.session_count} linked session(s) — you must unlink them first.</span>
            )}
          </p>
          {deleteMutation.error && (
            <p className="text-safety-red font-telemetry text-sm mb-2">
              {(deleteMutation.error as Error).message}
            </p>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 bg-safety-red text-white font-telemetry text-sm rounded hover:bg-safety-red/80 transition-colors disabled:opacity-50"
            >
              {deleteMutation.isPending ? 'Deleting...' : 'Confirm Delete'}
            </button>
            <button
              type="button"
              onClick={() => setConfirmDelete(false)}
              className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Edit form */}
      {editing && (
        <div className="bg-concrete rounded-lg border border-pit-orange/30 p-6 mb-6">
          <h2 className="font-monument text-lg text-chalk mb-4">Edit Track</h2>
          <div className="space-y-4">
            <FormField
              label="Track Name"
              value={form.name}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm((prev) => ({ ...prev, name: e.target.value }))}
              required
            />
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={form.has_joker}
                onChange={(e) => setForm((prev) => ({ ...prev, has_joker: e.target.checked }))}
                className="w-4 h-4 accent-pit-orange"
              />
              <span className="text-chalk font-body text-sm">Has joker lap</span>
            </label>
          </div>
          {updateMutation.error && (
            <p className="text-safety-red font-telemetry text-sm mt-2">
              {(updateMutation.error as Error).message}
            </p>
          )}
          <div className="flex gap-2 mt-4">
            <button
              type="button"
              onClick={handleSave}
              disabled={updateMutation.isPending || !form.name.trim()}
              className="px-6 py-2.5 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors disabled:opacity-50"
            >
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="px-6 py-2.5 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Sessions" value={track.session_count} />
        <StatCard label="Track Record" value={fmtTime(track.best_time_s)} />
        <StatCard label="Lap Length" value={fmtLength(track.lap_length_m)} />
        <StatCard label="Joker Lap" value={track.has_joker ? 'Yes' : 'No'} />
      </div>

      {/* Details card */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-4">
        <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-3">Track Information</h2>
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <div>
            <dt className="text-steel font-telemetry text-xs uppercase">Name</dt>
            <dd className="text-chalk font-body mt-0.5">{track.name}</dd>
          </div>
          <div>
            <dt className="text-steel font-telemetry text-xs uppercase">Length</dt>
            <dd className="text-chalk font-body mt-0.5">{fmtLength(track.lap_length_m)}</dd>
          </div>
          <div>
            <dt className="text-steel font-telemetry text-xs uppercase">Best Time</dt>
            <dd className="text-acid-green font-telemetry mt-0.5">{fmtTime(track.best_time_s)}</dd>
          </div>
          {track.created_at && (
            <div>
              <dt className="text-steel font-telemetry text-xs uppercase">First Seen</dt>
              <dd className="text-chalk font-body mt-0.5">{new Date(track.created_at).toLocaleDateString()}</dd>
            </div>
          )}
          {track.updated_at && (
            <div>
              <dt className="text-steel font-telemetry text-xs uppercase">Last Updated</dt>
              <dd className="text-chalk font-body mt-0.5">{new Date(track.updated_at).toLocaleDateString()}</dd>
            </div>
          )}
        </dl>
      </div>
    </div>
  );
}
