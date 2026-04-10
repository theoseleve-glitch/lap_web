'use client';

type EventRow = {
  event_type: string;
  user_email: string;
  user_name: string | null;
  path: string;
  properties: Record<string, unknown>;
  created_at: string;
};

type Props = {
  data: EventRow[];
};

function badgeClass(eventType: string): string {
  if (eventType.startsWith('session.')) {
    return 'bg-[#C9A84C]/15 text-[#C9A84C] border border-[#C9A84C]/30';
  }
  if (eventType.startsWith('chart.') || eventType.startsWith('compare.')) {
    return 'bg-[#8B5CF6]/15 text-[#8B5CF6] border border-[#8B5CF6]/30';
  }
  if (eventType.startsWith('report.')) {
    return 'bg-[#22c55e]/15 text-[#22c55e] border border-[#22c55e]/30';
  }
  if (eventType.startsWith('limit.')) {
    return 'bg-[#FF2A2A]/15 text-[#FF2A2A] border border-[#FF2A2A]/30';
  }
  return 'bg-white/[0.08] text-white/50 border border-white/10';
}

export default function EventTimeline({ data }: Props) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.03] p-5">
      <h2 className="mb-4 text-sm font-medium text-white">Event Timeline</h2>

      <div className="max-h-[400px] overflow-y-auto">
        <div className="divide-y divide-white/5">
          {data.length === 0 && (
            <p className="py-8 text-center text-xs text-white/30">No events</p>
          )}
          {data.map((event, i) => (
            <div
              key={i}
              className="flex items-center gap-3 py-2 text-xs"
            >
              {/* Time */}
              <span
                className="shrink-0 tabular-nums text-white/30"
                style={{ width: 70 }}
              >
                {new Date(event.created_at).toLocaleTimeString()}
              </span>

              {/* Email */}
              <span
                className="shrink-0 truncate text-white/50"
                style={{ width: 140 }}
                title={event.user_email}
              >
                {event.user_email}
              </span>

              {/* Badge */}
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 font-medium ${badgeClass(event.event_type)}`}
              >
                {event.event_type}
              </span>

              {/* Path */}
              <span className="min-w-0 flex-1 truncate text-white/30" title={event.path}>
                {event.path}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
