'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel } from '@/components/app';

interface WeatherAlert {
  severity: 'warning' | 'critical';
  message: string;
  rain_prob_pct?: number;
  rain_mm?: number;
  recommended_compound?: string;
  grip_score?: number;
}

interface WeatherConditions {
  air_temp_c?: number;
  grip_score?: number;
  track_state?: string;
  wind_speed_mps?: number;
}

interface LiveState {
  current_lap: number;
  total_laps: number;
  current_stint: number;
  compound: string;
  elapsed_time: number;
  projected_total: number;
  gap_to_optimal: number;
  last_lap_time: number | null;
  position: number | null;
  tyre_life_pct: number;
  fuel_remaining: number | null;
  next_pit_lap: number | null;
  alerts: { type: string; message: string }[];
  weather_alert?: WeatherAlert | null;
  engine_data?: { weather?: WeatherConditions };
}

const compoundColors: Record<string, string> = {
  soft: 'text-safety-red',
  medium: 'text-marshal-yellow',
  hard: 'text-chalk',
  wet: 'text-blue-400',
  inter: 'text-green-400',
};

function formatTime(s: number): string {
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${mins}:${secs.toFixed(1).padStart(4, '0')}`;
}

export default function RaceStrategyLivePage() {
  const { id } = useParams<{ id: string }>();

  const { data: live, isLoading } = useQuery({
    queryKey: ['race-strategy', id, 'live'],
    queryFn: () => api.get<LiveState>(`/race-strategy/${id}/live`),
    refetchInterval: 3000,
  });

  if (isLoading || !live) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  const progressPct = (live.current_lap / live.total_laps) * 100;

  return (
    <div>
      <PageHeader
        title="Live Strategy"
        subtitle={`Lap ${live.current_lap} / ${live.total_laps}`}
        actions={
          <Link
            href={`/app/race-strategy/${id}`}
            className="px-3 py-1.5 border border-steel/30 text-steel font-telemetry text-xs rounded hover:text-chalk transition-colors"
          >
            Exit Live
          </Link>
        }
      />

      {/* Race progress bar */}
      <div className="mb-6">
        <div className="flex justify-between mb-1">
          <span className="font-telemetry text-xs text-steel">Race Progress</span>
          <span className="font-telemetry text-xs text-acid-green">
            {progressPct.toFixed(0)}%
          </span>
        </div>
        <div className="w-full bg-steel/20 rounded-full h-3">
          <div
            className="bg-acid-green h-3 rounded-full transition-all duration-1000"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Weather Alert */}
      {live.weather_alert && (
        <div className={`rounded-lg p-3 mb-4 flex items-center gap-3 ${
          live.weather_alert.severity === 'critical'
            ? 'bg-safety-red/10 border border-safety-red/40'
            : 'bg-marshal-yellow/10 border border-marshal-yellow/40'
        }`}>
          <span className="text-2xl">
            {live.weather_alert.severity === 'critical' ? '\u{1F327}' : '\u26A0\uFE0F'}
          </span>
          <div>
            <p className={`font-telemetry text-sm font-semibold ${
              live.weather_alert.severity === 'critical' ? 'text-safety-red' : 'text-marshal-yellow'
            }`}>
              {live.weather_alert.severity === 'critical' ? 'RAIN ALERT' : 'Weather Warning'}
            </p>
            <p className="text-sm text-steel">{live.weather_alert.message}</p>
            {live.weather_alert.recommended_compound && (
              <p className="text-xs text-steel mt-0.5">
                Recommended: <span className="text-chalk font-semibold uppercase">{live.weather_alert.recommended_compound}</span>
              </p>
            )}
          </div>
        </div>
      )}

      {/* Current Conditions */}
      {live.engine_data?.weather && (
        <div className="flex gap-6 bg-concrete rounded-lg border border-steel/20 px-4 py-2 mb-4 text-sm font-telemetry">
          <div>
            <span className="text-steel">Temp</span>{' '}
            <span className="text-chalk tabular-nums">{live.engine_data.weather.air_temp_c?.toFixed(1)}&deg;C</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-steel">Grip</span>
            <div className="w-16 h-2 bg-steel/20 rounded-full overflow-hidden">
              <div
                className="h-full bg-acid-green rounded-full transition-all"
                style={{ width: `${live.engine_data.weather.grip_score ?? 0}%` }}
              />
            </div>
            <span className="text-chalk tabular-nums">{live.engine_data.weather.grip_score ?? '--'}%</span>
          </div>
          <div>
            <span className="text-steel">Track</span>{' '}
            <span className="text-chalk uppercase">{live.engine_data.weather.track_state ?? '--'}</span>
          </div>
        </div>
      )}

      {/* Primary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <StatCard
          label="Last Lap"
          value={live.last_lap_time ? `${live.last_lap_time.toFixed(3)}s` : '—'}
        />
        <StatCard label="Gap to Optimal" value={`${live.gap_to_optimal >= 0 ? '+' : ''}${live.gap_to_optimal.toFixed(1)}s`} trend={live.gap_to_optimal <= 0 ? 'up' : 'down'} />
        <StatCard label="Projected Total" value={formatTime(live.projected_total)} />
        {live.position != null && (
          <StatCard label="Position" value={`P${live.position}`} />
        )}
      </div>

      {/* Stint & tyre info */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <div className="text-steel font-telemetry text-xs uppercase mb-1">Current Tyre</div>
          <div
            className={`font-monument text-2xl uppercase ${compoundColors[live.compound] ?? 'text-chalk'}`}
          >
            {live.compound}
          </div>
          <div className="mt-1">
            <div className="flex justify-between text-xs font-telemetry text-steel mb-0.5">
              <span>Tyre Life</span>
              <span>{live.tyre_life_pct.toFixed(0)}%</span>
            </div>
            <div className="w-full bg-steel/20 rounded-full h-1.5">
              <div
                className={`h-1.5 rounded-full transition-all ${
                  live.tyre_life_pct > 50
                    ? 'bg-acid-green'
                    : live.tyre_life_pct > 25
                      ? 'bg-marshal-yellow'
                      : 'bg-safety-red'
                }`}
                style={{ width: `${live.tyre_life_pct}%` }}
              />
            </div>
          </div>
        </div>

        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <div className="text-steel font-telemetry text-xs uppercase mb-1">Stint</div>
          <div className="font-monument text-2xl text-chalk">{live.current_stint}</div>
        </div>

        {live.next_pit_lap != null && (
          <div className="bg-concrete rounded-lg border border-steel/20 p-4">
            <div className="text-steel font-telemetry text-xs uppercase mb-1">Next Pit</div>
            <div className="font-monument text-2xl text-pit-orange">L{live.next_pit_lap}</div>
            <div className="text-xs font-telemetry text-steel mt-1">
              In {live.next_pit_lap - live.current_lap} laps
            </div>
          </div>
        )}

        {live.fuel_remaining != null && (
          <div className="bg-concrete rounded-lg border border-steel/20 p-4">
            <div className="text-steel font-telemetry text-xs uppercase mb-1">Fuel</div>
            <div className="font-monument text-2xl text-chalk">
              {live.fuel_remaining.toFixed(1)}
              <span className="text-sm text-steel ml-1">kg</span>
            </div>
          </div>
        )}
      </div>

      {/* Alerts */}
      {live.alerts.length > 0 && (
        <div className="mb-6">
          <h3 className="font-body text-chalk text-sm mb-2">Alerts</h3>
          <div className="space-y-2">
            {live.alerts.map((alert, i) => (
              <div
                key={i}
                className={`p-3 rounded border text-sm font-body ${
                  alert.type === 'warning'
                    ? 'bg-marshal-yellow/10 border-marshal-yellow/30 text-marshal-yellow'
                    : alert.type === 'danger'
                      ? 'bg-safety-red/10 border-safety-red/30 text-safety-red'
                      : 'bg-acid-green/10 border-acid-green/30 text-acid-green'
                }`}
              >
                {alert.message}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Lap time chart placeholder */}
      <ChartPanel title="Lap Times" subtitle="Real-time lap time tracking">
        <div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">
          Live chart updates every 3 seconds
        </div>
      </ChartPanel>
    </div>
  );
}
