'use client';

import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

/* ── Types ──────────────────────────────────────────────── */

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
  grade: string | null;
  session_type: string | null;
  track_state: string | null;
  driver_name: string;
}

interface LeaderboardRow {
  rank: number;
  session_id: string;
  driver_name: string;
  track_name: string;
  best_time: number;
  score: number | null;
  grade: string | null;
  date: string;
  track_state: string | null;
  delta: number;
}

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  if (score >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

const STATE_COLORS: Record<string, string> = {
  dry: '#B6FF2E',
  wet: '#60A5FA',
  damp: '#FFD400',
  mixed: '#A78BFA',
  greasy: '#FF6A00',
};

const TRACK_ALL = '__all__';

/* ── Page ───────────────────────────────────────────────── */

export default function LeaderboardPage() {
  const router = useRouter();
  const [selectedTrack, setSelectedTrack] = useState(TRACK_ALL);

  const { data: tracksData } = useQuery({
    queryKey: ['tracks'],
    queryFn: () => api.get<{ tracks: Track[] }>('/tracks'),
  });

  const tracks = tracksData?.tracks ?? [];
  const trackNameById = useMemo(() => new Map(tracks.map((t) => [t.track_id, t.track_name])), [tracks]);

  const { data, isLoading } = useQuery({
    queryKey: ['leaderboard', selectedTrack, tracks.map((t) => t.track_id).join(',')],
    queryFn: async () => {
      const selectedTrackIds =
        selectedTrack === TRACK_ALL ? tracks.map((t) => t.track_id) : [selectedTrack];

      const responses = await Promise.all(
        selectedTrackIds.map((trackId) =>
          api.get<{ track_id: string; leaderboard: TrackLeaderboardEntry[] }>(
            `/tracks/${encodeURIComponent(trackId)}/leaderboard`,
          ),
        ),
      );

      const raw = responses
        .flatMap((response) =>
          (response.leaderboard ?? []).map((entry) => ({
            session_id: entry.session_id,
            driver_name: entry.driver_name,
            track_name: trackNameById.get(response.track_id) ?? response.track_id,
            best_time: entry.best_lap_time_s,
            score: entry.total_score,
            grade: entry.grade,
            date: entry.session_date,
            track_state: entry.track_state,
          })),
        )
        .sort((a, b) => a.best_time - b.best_time);

      const leader = raw[0]?.best_time ?? 0;
      const entries: LeaderboardRow[] = raw.map((e, i) => ({
        ...e,
        rank: i + 1,
        delta: e.best_time - leader,
      }));

      return { entries };
    },
    enabled: tracks.length > 0,
  });

  const entries = data?.entries ?? [];
  const podium = entries.slice(0, 3);
  const rest = entries.slice(3);

  return (
    <div>
      <PageHeader
        title="Leaderboard"
        subtitle="Best lap times across all sessions"
        actions={
          <select
            className="bg-concrete border border-steel/30 rounded px-3 py-1.5 text-chalk font-body text-sm
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
        }
      />

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : entries.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <div className="text-4xl mb-3">🏆</div>
          <h3 className="font-monument text-lg text-chalk mb-2">No entries yet</h3>
          <p className="text-steel font-body text-sm max-w-md mx-auto">
            Process some sessions to populate the leaderboard. The fastest laps
            across all drivers and tracks will appear here.
          </p>
        </div>
      ) : (
        <>
          {/* ── Podium ──────────────────────────────────── */}
          {podium.length > 0 && (
            <div className="grid grid-cols-3 gap-4 mb-8">
              {/* 2nd place (left) */}
              {podium.length >= 2 ? (
                <PodiumCard entry={podium[1]} href={`/app/sessions/${podium[1].session_id}`} />
              ) : <div />}

              {/* 1st place (center, taller) */}
              <PodiumCard entry={podium[0]} isFirst href={`/app/sessions/${podium[0].session_id}`} />

              {/* 3rd place (right) */}
              {podium.length >= 3 ? (
                <PodiumCard entry={podium[2]} href={`/app/sessions/${podium[2].session_id}`} />
              ) : <div />}
            </div>
          )}

          {/* ── Full Table ──────────────────────────────── */}
          {rest.length > 0 && (
            <DataTable
              columns={[
                {
                  key: 'rank',
                  header: '#',
                  className: 'w-14 font-telemetry',
                  render: (row: LeaderboardRow) => (
                    <span className="text-steel/60 font-telemetry">{row.rank}</span>
                  ),
                },
                { key: 'driver_name', header: 'Driver', sortable: true },
                { key: 'track_name', header: 'Track', sortable: true },
                {
                  key: 'best_time',
                  header: 'Best Lap',
                  sortable: true,
                  className: 'font-telemetry',
                  render: (row: LeaderboardRow) => (
                    <span className="text-acid-green">{fmtTime(row.best_time)}</span>
                  ),
                },
                {
                  key: 'delta',
                  header: 'Gap',
                  className: 'font-telemetry text-right',
                  render: (row: LeaderboardRow) => (
                    <span className="text-safety-red/70">
                      {row.delta > 0 ? `+${row.delta.toFixed(3)}s` : '—'}
                    </span>
                  ),
                },
                {
                  key: 'score',
                  header: 'Score',
                  sortable: true,
                  className: 'font-telemetry text-right',
                  render: (row: LeaderboardRow) => (
                    <span className={scoreColor(row.score)}>
                      {row.score?.toFixed(1) ?? '—'}
                    </span>
                  ),
                },
                {
                  key: 'grade',
                  header: 'Grade',
                  render: (row: LeaderboardRow) => (
                    <span className={`font-monument ${scoreColor(row.score)}`}>
                      {row.grade ?? '—'}
                    </span>
                  ),
                },
                {
                  key: 'track_state',
                  header: 'Cond.',
                  render: (row: LeaderboardRow) => {
                    const st = row.track_state;
                    if (!st) return <span className="text-steel/30">—</span>;
                    const color = STATE_COLORS[st] ?? '#8A8F98';
                    return (
                      <span
                        className="inline-flex px-2 py-0.5 rounded text-[10px] font-telemetry uppercase"
                        style={{ backgroundColor: color + '18', color }}
                      >
                        {st}
                      </span>
                    );
                  },
                },
                {
                  key: 'date',
                  header: 'Date',
                  sortable: true,
                  className: 'font-telemetry text-steel',
                },
              ]}
              data={rest}
              keyField="session_id"
              onRowClick={(row) => router.push(`/app/sessions/${row.session_id}`)}
              emptyMessage="No more entries"
            />
          )}
        </>
      )}
    </div>
  );
}

/* ── Podium Card ────────────────────────────────────────── */

function PodiumCard({
  entry,
  isFirst = false,
  href,
}: {
  entry: LeaderboardRow;
  isFirst?: boolean;
  href: string;
}) {
  const medals = ['🥇', '🥈', '🥉'];
  const borderColors = [
    'border-marshal-yellow/50',
    'border-steel/40',
    'border-pit-orange/40',
  ];

  return (
    <Link
      href={href}
      className={`group bg-concrete rounded-lg border ${borderColors[entry.rank - 1]} p-5 text-center transition-all
        hover:border-acid-green/40 ${isFirst ? 'md:-mt-4 md:pb-8' : ''}`}
    >
      <span className="text-3xl" aria-hidden="true">{medals[entry.rank - 1]}</span>
      <p className="font-monument text-2xl text-chalk mt-2 group-hover:text-acid-green transition-colors">
        {fmtTime(entry.best_time)}
      </p>
      <p className="text-chalk font-body text-sm mt-1">{entry.driver_name}</p>
      <p className="text-steel font-telemetry text-xs mt-0.5">{entry.track_name}</p>
      <div className="flex items-center justify-center gap-3 mt-2">
        {entry.score != null && (
          <span className={`font-telemetry text-xs ${scoreColor(entry.score)}`}>
            {entry.score.toFixed(1)}
          </span>
        )}
        {entry.grade && (
          <span className={`font-monument text-sm ${scoreColor(entry.score)}`}>
            {entry.grade}
          </span>
        )}
      </div>
      <p className="text-steel/40 font-telemetry text-[10px] mt-2">{entry.date}</p>
    </Link>
  );
}
