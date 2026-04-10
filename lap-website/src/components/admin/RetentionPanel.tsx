'use client';

import { useState } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';

type CohortRow = {
  week: string;
  size: number;
  retention: number[];
};

type Props = {
  data: CohortRow[];
};

const LINE_COLORS = ['#22c55e', '#C9A84C', '#8B5CF6', '#949494', '#FF2A2A'];

export default function RetentionPanel({ data }: Props) {
  const [view, setView] = useState<'table' | 'chart'>('table');

  const maxCols = data.length > 0 ? Math.max(...data.map((d) => d.retention.length)) : 0;
  const weekLabels = Array.from({ length: maxCols }, (_, i) => `W${i}`);

  // Build chart-friendly data: one entry per week-index, values per cohort
  const chartData = weekLabels.map((label, wi) => {
    const point: Record<string, number | string> = { week: label };
    data.forEach((cohort) => {
      if (wi < cohort.retention.length) {
        point[cohort.week] = cohort.retention[wi];
      }
    });
    return point;
  });

  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.03] p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium text-white">Retention Cohorts</h2>
        <div className="flex gap-1">
          {(['table', 'chart'] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              className={`rounded px-2 py-1 text-xs border capitalize transition-colors ${
                view === v
                  ? 'bg-[#22c55e]/15 text-[#22c55e] border border-[#22c55e]/30'
                  : 'text-white/40 border border-white/10 hover:text-white/60'
              }`}
            >
              {v}
            </button>
          ))}
        </div>
      </div>

      {view === 'table' ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-white/40">
                <th className="pb-2 pr-3 font-medium">Cohort</th>
                <th className="pb-2 pr-3 font-medium">Size</th>
                {weekLabels.map((l) => (
                  <th key={l} className="pb-2 pr-2 font-medium text-center">
                    {l}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {data.map((cohort) => (
                <tr key={cohort.week}>
                  <td className="py-2 pr-3 text-white/70">{cohort.week}</td>
                  <td className="py-2 pr-3 text-white/50">{cohort.size}</td>
                  {weekLabels.map((_, wi) => {
                    const pct = wi < cohort.retention.length ? cohort.retention[wi] : null;
                    return (
                      <td key={wi} className="py-2 pr-2 text-center">
                        {pct !== null ? (
                          <span
                            className="inline-block rounded px-1.5 py-0.5 text-white"
                            style={{
                              background: `rgba(34, 197, 94, ${(pct / 100) * 0.35})`,
                            }}
                          >
                            {pct}%
                          </span>
                        ) : (
                          <span className="text-white/20">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={chartData} margin={{ top: 4, right: 16, bottom: 0, left: -20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey="week"
              tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1a1a1a',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 6,
                color: '#fff',
                fontSize: 12,
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: 'rgba(255,255,255,0.5)' }} />
            {data.map((cohort, i) => (
              <Line
                key={cohort.week}
                type="monotone"
                dataKey={cohort.week}
                stroke={LINE_COLORS[i % LINE_COLORS.length]}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
