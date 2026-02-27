'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface LeaderboardRow {
  rank: number;
  session_id: string;
  driver_name: string;
  track_name: string;
  best_time: number;
  score: number | null;
  date: string;
}

interface Track {
  track_id: string;
  track_name: string;
}

interface TrackLeaderboardEntry {
  rank: number;
  session_id: string;
  session_date: string;
  best_lap_time_s: number;
  total_score: number | null;
  driver_name: string;
}

function formatTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-pit-orange';
  return 'text-safety-red';
}

function rankBadge(rank: number): string {
  if (rank === 1) return 'text-yellow-400';
  if (rank === 2) return 'text-steel';
  if (rank === 3) return 'text-pit-orange';
  return 'text-chalk/60';
}

const TRACK_ALL = '__all__';

export default function LeaderboardPage() {
  const router = useRouter();
  const [selectedTrack, setSelectedTrack] = useState(TRACK_ALL);

  const { data: tracksData, isLoading: isTracksLoading } = useQuery({
    queryKey: ['tracks'],
    queryFn: () => api.get<{ tracks: Track[] }>('/tracks'),
  });

  const tracks = tracksData?.tracks ?? [];
  const trackNameById = new Map(tracks.map((track) => [track.track_id, track.track_name]));

  const { data, isLoading: isLeaderboardLoading } = useQuery({
    queryKey: ['leaderboard', selectedTrack, tracks.map((track) => track.track_id).join(',')],
    queryFn: async () => {
      const selectedTrackIds =
        selectedTrack === TRACK_ALL ? tracks.map((track) => track.track_id) : [selectedTrack];

      const responses = await Promise.all(
        selectedTrackIds.map((trackId) =>
          api.get<{ track_id: string; leaderboard: TrackLeaderboardEntry[] }>(
            `/tracks/${encodeURIComponent(trackId)}/leaderboard`,
          ),
        ),
      );

      const entries = responses
        .flatMap((response) =>
          response.leaderboard.map((entry) => ({
            rank: entry.rank,
            session_id: entry.session_id,
            driver_name: entry.driver_name,
            track_name: trackNameById.get(response.track_id) ?? response.track_id,
            best_time: entry.best_lap_time_s,
            score: entry.total_score,
            date: entry.session_date,
          })),
        )
        .sort((a, b) => a.best_time - b.best_time)
        .map((entry, index) => ({ ...entry, rank: index + 1 }));

      return { entries };
    },
    enabled: tracks.length > 0,
  });

  const entries = data?.entries ?? [];
  const isLoading = isTracksLoading || isLeaderboardLoading;

  return (
    <div>
      <PageHeader
        title="Leaderboard"
        subtitle="Best lap times across all sessions"
        actions={
          <div className="flex items-center gap-2">
            <label className="text-steel font-telemetry text-xs uppercase">Track</label>
            <select
              className="bg-asphalt border border-steel/30 rounded px-3 py-1.5 text-chalk font-body text-sm
                focus:outline-none focus:border-pit-orange transition-colors"
              value={selectedTrack}
              onChange={(e) => setSelectedTrack(e.target.value)}
            >
              <option value={TRACK_ALL}>All Tracks</option>
              {tracks.map((track) => (
                <option key={track.track_id} value={track.track_id}>
                  {track.track_name}
                </option>
              ))}
            </select>
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : (
        <DataTable
          columns={[
            {
              key: 'rank',
              header: '#',
              className: 'w-12 font-telemetry',
              render: (row: LeaderboardRow) => (
                <span className={`font-monument text-sm ${rankBadge(row.rank)}`}>
                  {row.rank}
                </span>
              ),
            },
            { key: 'driver_name', header: 'Driver', sortable: true },
            { key: 'track_name', header: 'Track', sortable: true },
            {
              key: 'best_time',
              header: 'Best Time',
              sortable: true,
              className: 'font-telemetry',
              render: (row: LeaderboardRow) => (
                <span className="text-acid-green font-monument">{formatTime(row.best_time)}</span>
              ),
            },
            {
              key: 'score',
              header: 'Score',
              sortable: true,
              className: 'font-telemetry text-right',
              render: (row: LeaderboardRow) => (
                <span className={scoreColor(row.score)}>
                  {row.score != null ? row.score.toFixed(1) : '—'}
                </span>
              ),
            },
            { key: 'date', header: 'Date', sortable: true, className: 'text-steel' },
          ]}
          data={entries}
          keyField="session_id"
          onRowClick={(row) => router.push(`/app/sessions/${row.session_id}`)}
          emptyMessage="No leaderboard entries yet. Process some sessions to populate the leaderboard."
        />
      )}
    </div>
  );
}
