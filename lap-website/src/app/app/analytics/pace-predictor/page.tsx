'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, ChartPanel } from '@/components/app';

/* ---------- types ---------- */

interface TrackOption {
  id: string;
  name: string;
}

interface TrackListResponse {
  tracks: TrackOption[];
}

interface PredictionResponse {
  predicted_time: number;
  confidence_low: number;
  confidence_high: number;
  confidence_pct: number;
  based_on_sessions: number;
}

/* ---------- helpers ---------- */

function formatTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

/* ---------- component ---------- */

export default function PacePredictorPage() {
  const [trackId, setTrackId] = useState('');
  const [temperature, setTemperature] = useState(20);
  const [humidity, setHumidity] = useState(50);
  const [gripLevel, setGripLevel] = useState<'low' | 'medium' | 'high'>('medium');

  const { data: trackList } = useQuery({
    queryKey: ['tracks-list'],
    queryFn: () => api.get<TrackListResponse>('/tracks'),
  });

  const tracks = trackList?.tracks ?? [];

  const conditions = `temp=${temperature}&humidity=${humidity}&grip=${gripLevel}`;
  const canPredict = trackId !== '';

  const { data: prediction, isLoading: predicting, error } = useQuery({
    queryKey: ['pace-prediction', trackId, conditions],
    queryFn: () =>
      api.get<PredictionResponse>(`/analytics/predict-pace?track_id=${trackId}&${conditions}`),
    enabled: canPredict,
  });

  return (
    <div>
      <PageHeader
        title="Pace Predictor"
        subtitle="Predict target lap times based on track and conditions"
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Input panel */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-5">
          <h3 className="font-body text-chalk text-sm font-medium mb-4">Conditions</h3>

          {/* Track selector */}
          <div className="mb-4">
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              Track
            </label>
            <select
              value={trackId}
              onChange={(e) => setTrackId(e.target.value)}
              className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                focus:outline-none focus:border-pit-orange transition-colors"
            >
              <option value="">Select track...</option>
              {tracks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>

          {/* Temperature */}
          <div className="mb-4">
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              Temperature (C)
            </label>
            <input
              type="number"
              value={temperature}
              onChange={(e) => setTemperature(Number(e.target.value))}
              min={-10}
              max={50}
              step={1}
              className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 transition-colors"
            />
          </div>

          {/* Humidity */}
          <div className="mb-4">
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              Humidity (%)
            </label>
            <input
              type="number"
              value={humidity}
              onChange={(e) => setHumidity(Number(e.target.value))}
              min={0}
              max={100}
              step={5}
              className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 transition-colors"
            />
          </div>

          {/* Grip level */}
          <div className="mb-4">
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              Grip Level
            </label>
            <div className="flex gap-2">
              {(['low', 'medium', 'high'] as const).map((level) => (
                <button
                  key={level}
                  onClick={() => setGripLevel(level)}
                  className={`flex-1 py-2 px-3 rounded font-telemetry text-xs uppercase transition-colors border ${
                    gripLevel === level
                      ? 'bg-acid-green/20 border-acid-green text-acid-green'
                      : 'bg-asphalt border-steel/30 text-steel hover:text-chalk'
                  }`}
                >
                  {level}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Results panel */}
        <div className="lg:col-span-2">
          {!canPredict && (
            <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center h-full flex items-center justify-center">
              <p className="text-steel font-body">
                Select a track and set conditions to predict pace.
              </p>
            </div>
          )}

          {predicting && (
            <div className="bg-concrete rounded-lg border border-steel/20 p-12 flex items-center justify-center h-full">
              <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
            </div>
          )}

          {error && canPredict && !predicting && (
            <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
              <p className="text-safety-red font-telemetry text-sm">
                Failed to generate prediction. Insufficient historical data for this track/condition combination.
              </p>
            </div>
          )}

          {prediction && !predicting && (
            <div className="space-y-4">
              {/* Main prediction display */}
              <div className="bg-concrete rounded-lg border border-acid-green/30 p-8 text-center">
                <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-2">
                  Predicted Lap Time
                </p>
                <p className="font-monument text-6xl text-acid-green tracking-tight">
                  {formatTime(prediction.predicted_time)}
                </p>
                <p className="text-steel font-telemetry text-xs mt-3">
                  Based on {prediction.based_on_sessions} historical sessions
                </p>
              </div>

              {/* Confidence interval */}
              <div className="bg-concrete rounded-lg border border-steel/20 p-6">
                <h3 className="font-body text-chalk text-sm font-medium mb-4">
                  Confidence Interval
                </h3>
                <div className="flex items-center gap-4 mb-4">
                  <div className="flex-1 text-right">
                    <p className="text-steel font-telemetry text-xs uppercase">Fastest</p>
                    <p className="font-monument text-lg text-acid-green">
                      {formatTime(prediction.confidence_low)}
                    </p>
                  </div>
                  <div className="w-32">
                    {/* Visual range bar */}
                    <div className="h-3 bg-asphalt rounded-full overflow-hidden relative">
                      <div
                        className="absolute inset-y-0 bg-acid-green/30 rounded-full"
                        style={{
                          left: '10%',
                          right: '10%',
                        }}
                      />
                      <div
                        className="absolute top-0 bottom-0 w-1 bg-acid-green rounded-full"
                        style={{
                          left: '50%',
                          transform: 'translateX(-50%)',
                        }}
                      />
                    </div>
                  </div>
                  <div className="flex-1">
                    <p className="text-steel font-telemetry text-xs uppercase">Slowest</p>
                    <p className="font-monument text-lg text-pit-orange">
                      {formatTime(prediction.confidence_high)}
                    </p>
                  </div>
                </div>
                <p className="text-center text-steel font-telemetry text-xs">
                  {prediction.confidence_pct}% confidence interval
                </p>
              </div>

              {/* Conditions summary */}
              <ChartPanel title="Applied Conditions" subtitle="Parameters used for this prediction">
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <p className="text-steel font-telemetry text-xs uppercase mb-1">Temperature</p>
                    <p className="font-monument text-lg text-chalk">{temperature}°C</p>
                  </div>
                  <div>
                    <p className="text-steel font-telemetry text-xs uppercase mb-1">Humidity</p>
                    <p className="font-monument text-lg text-chalk">{humidity}%</p>
                  </div>
                  <div>
                    <p className="text-steel font-telemetry text-xs uppercase mb-1">Grip</p>
                    <p className="font-monument text-lg text-chalk capitalize">{gripLevel}</p>
                  </div>
                </div>
              </ChartPanel>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
