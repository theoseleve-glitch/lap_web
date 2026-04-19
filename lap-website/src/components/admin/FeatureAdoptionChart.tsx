'use client';

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts';

type FeatureDataPoint = {
  event_type: string;
  count: number;
  unique_users: number;
};

type Props = {
  data: FeatureDataPoint[];
};

function humanize(s: string): string {
  return s
    .split('.')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

type TooltipPayloadItem = {
  payload?: FeatureDataPoint;
};

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div
      style={{
        backgroundColor: '#1a1a1a',
        border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: 6,
        padding: '8px 12px',
        fontSize: 12,
        color: '#fff',
      }}
    >
      <p className="font-medium">{humanize(d.event_type)}</p>
      <p style={{ color: 'rgba(255,255,255,0.6)' }}>Count: {d.count}</p>
      <p style={{ color: 'rgba(255,255,255,0.6)' }}>Unique users: {d.unique_users}</p>
    </div>
  );
}

export default function FeatureAdoptionChart({ data }: Props) {
  const chartHeight = Math.max(200, data.length * 40);

  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.03] p-5">
      <h2 className="mb-4 text-sm font-medium text-white">Feature Adoption (30d)</h2>

      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 0, right: 16, bottom: 0, left: 80 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
          <YAxis
            type="category"
            dataKey="event_type"
            tickFormatter={humanize}
            tick={{ fill: 'rgba(255,255,255,0.5)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={80}
          />
          <XAxis
            type="number"
            tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="count" fill="#C9A84C" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
