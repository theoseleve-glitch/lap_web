'use client';

import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend,
} from 'recharts';
import type { DriverProgression } from '@/lib/api-types';
import { colors } from '@/lib/tokens';

interface Props {
  data: DriverProgression[];
}

function fmtDate(d: string | null): string {
  if (!d) return '';
  return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
}

export function ProgressionChart({ data }: Props) {
  if (data.length === 0) {
    return (
      <p className="text-steel font-body text-sm text-center py-8">
        No progression data yet. Upload more sessions to track improvement.
      </p>
    );
  }

  const chartData = data.map((d) => ({
    date: fmtDate(d.session_date),
    score: d.total_score,
    pace: d.pace_delta_s != null ? Math.abs(d.pace_delta_s) : null,
    consistency: d.consistency_cv_pct,
  }));

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div>
        <h4 className="font-telemetry text-xs text-steel/60 uppercase mb-3">Score Trend</h4>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 148, 148, 0.12)" />
            <XAxis dataKey="date" tick={{ fill: colors.steel, fontSize: 10 }} />
            <YAxis domain={[0, 100]} tick={{ fill: colors.steel, fontSize: 10 }} />
            <Tooltip
              contentStyle={{ backgroundColor: colors.concrete, border: '1px solid rgba(148, 148, 148, 0.2)', borderRadius: 8 }}
              labelStyle={{ color: colors.chalk }}
              itemStyle={{ color: colors.chalk }}
            />
            <Line type="monotone" dataKey="score" stroke={colors.acidGreen} strokeWidth={2} dot={{ r: 3 }} name="Score" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div>
        <h4 className="font-telemetry text-xs text-steel/60 uppercase mb-3">Consistency (CV%)</h4>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 148, 148, 0.12)" />
            <XAxis dataKey="date" tick={{ fill: colors.steel, fontSize: 10 }} />
            <YAxis tick={{ fill: colors.steel, fontSize: 10 }} />
            <Tooltip
              contentStyle={{ backgroundColor: colors.concrete, border: '1px solid rgba(148, 148, 148, 0.2)', borderRadius: 8 }}
              labelStyle={{ color: colors.chalk }}
              itemStyle={{ color: colors.chalk }}
            />
            <Line type="monotone" dataKey="consistency" stroke={colors.pitOrange} strokeWidth={2} dot={{ r: 3 }} name="CV %" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
