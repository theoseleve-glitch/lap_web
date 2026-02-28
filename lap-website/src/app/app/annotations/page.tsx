'use client';

import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable, QueryError } from '@/components/app';

interface AnnotationRow {
  id: number;
  session_id: string;
  session_label: string;
  type: string;
  text: string;
  timestamp_s: number | null;
  created_at: string;
}

function formatTimestamp(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(1).padStart(4, '0')}`;
}

function typeColor(type: string): string {
  switch (type.toLowerCase()) {
    case 'note': return 'text-chalk bg-steel/20';
    case 'incident': return 'text-safety-red bg-safety-red/10';
    case 'highlight': return 'text-acid-green bg-acid-green/10';
    case 'flag': return 'text-pit-orange bg-pit-orange/10';
    default: return 'text-steel bg-steel/10';
  }
}

export default function AnnotationsPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['annotations'],
    queryFn: () => api.get<{ annotations: AnnotationRow[] }>('/annotations'),
  });

  const filtered = useMemo(() => {
    const annotations = data?.annotations ?? [];
    if (!search.trim()) return annotations;
    const q = search.toLowerCase();
    return annotations.filter(
      (a) =>
        a.text.toLowerCase().includes(q) ||
        a.session_label.toLowerCase().includes(q) ||
        a.type.toLowerCase().includes(q),
    );
  }, [data, search]);

  return (
    <div>
      <PageHeader
        title="Annotations"
        subtitle={`${filtered.length} annotation${filtered.length !== 1 ? 's' : ''}${search ? ' (filtered)' : ''}`}
        actions={
          <div className="relative">
            <input
              type="text"
              placeholder="Search annotations..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-asphalt border border-steel/30 rounded px-3 py-1.5 pl-8 text-chalk font-body text-sm w-56
                placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 transition-colors"
            />
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-steel text-xs">
              ⌕
            </span>
            {search && (
              <button
                onClick={() => setSearch('')}
                aria-label="Clear search"
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-steel hover:text-chalk text-xs transition-colors"
              >
                ✕
              </button>
            )}
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : error ? (
        <QueryError message="Couldn't load annotations." onRetry={() => refetch()} />
      ) : (
        <DataTable
          columns={[
            {
              key: 'session_label',
              header: 'Session',
              sortable: true,
              render: (row: AnnotationRow) => (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    router.push(`/app/sessions/${row.session_id}`);
                  }}
                  className="text-acid-green hover:underline font-body text-sm"
                >
                  {row.session_label}
                </button>
              ),
            },
            {
              key: 'type',
              header: 'Type',
              sortable: true,
              render: (row: AnnotationRow) => (
                <span className={`px-2 py-0.5 rounded text-xs font-telemetry uppercase tracking-wide ${typeColor(row.type)}`}>
                  {row.type}
                </span>
              ),
            },
            {
              key: 'text',
              header: 'Text',
              render: (row: AnnotationRow) => (
                <span className="text-chalk font-body text-sm line-clamp-2 max-w-sm">{row.text}</span>
              ),
            },
            {
              key: 'timestamp_s',
              header: 'Timestamp',
              sortable: true,
              className: 'font-telemetry',
              render: (row: AnnotationRow) => (
                <span className="text-steel">{formatTimestamp(row.timestamp_s)}</span>
              ),
            },
            {
              key: 'created_at',
              header: 'Created',
              sortable: true,
              className: 'text-steel font-telemetry text-xs',
            },
          ]}
          data={filtered}
          keyField="id"
          onRowClick={(row) => router.push(`/app/sessions/${row.session_id}`)}
          emptyMessage={search ? 'No annotations match your search.' : 'No annotations found.'}
        />
      )}
    </div>
  );
}
