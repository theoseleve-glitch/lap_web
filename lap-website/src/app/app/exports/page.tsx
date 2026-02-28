'use client';

import { useState, useId } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface ExportRow {
  id: number;
  name: string;
  format: string;
  size: number;
  status: 'ready' | 'generating' | 'failed';
  created_at: string;
  download_url: string | null;
}

type ExportFormat = 'csv' | 'json' | 'pdf' | 'parquet';

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const statusColors: Record<string, string> = {
  ready: 'text-acid-green',
  generating: 'text-marshal-yellow',
  failed: 'text-safety-red',
};

export default function ExportsPage() {
  const fieldId = useId();
  const [generating, setGenerating] = useState(false);
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>('csv');
  const [exportType, setExportType] = useState('sessions');

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['exports'],
    queryFn: () => api.get<{ exports: ExportRow[] }>('/exports'),
  });

  const exports = data?.exports ?? [];

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await api.post('/exports/generate', {
        type: exportType,
        format: selectedFormat,
      });
      await refetch();
    } catch {
      // Error handling in UI
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div>
      <PageHeader title="Exports" subtitle="Download your telemetry data" />

      {/* Generate new export */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h3 className="font-body text-chalk text-sm mb-4">Generate Export</h3>
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label htmlFor={`${fieldId}-type`} className="block text-steel font-telemetry text-xs uppercase mb-1">
              Data Type
            </label>
            <select
              id={`${fieldId}-type`}
              value={exportType}
              onChange={(e) => setExportType(e.target.value)}
              className="bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm focus:outline-none focus:border-pit-orange"
            >
              <option value="sessions">All Sessions</option>
              <option value="laps">Lap Data</option>
              <option value="drivers">Driver Profiles</option>
              <option value="tracks">Track Data</option>
              <option value="scores">Score History</option>
            </select>
          </div>

          <div>
            <label className="block text-steel font-telemetry text-xs uppercase mb-1">
              Format
            </label>
            <div className="flex gap-2">
              {(['csv', 'json', 'pdf', 'parquet'] as ExportFormat[]).map((fmt) => (
                <button
                  key={fmt}
                  type="button"
                  onClick={() => setSelectedFormat(fmt)}
                  className={`px-3 py-2 rounded border font-telemetry text-xs uppercase transition-colors ${
                    selectedFormat === fmt
                      ? 'border-acid-green bg-acid-green/10 text-acid-green'
                      : 'border-steel/30 text-steel hover:text-chalk'
                  }`}
                >
                  {fmt}
                </button>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            className="px-6 py-2 bg-pit-orange text-asphalt font-telemetry text-sm rounded disabled:opacity-50 hover:bg-pit-orange/80 transition-colors"
          >
            {generating ? 'Generating...' : 'Generate'}
          </button>
        </div>
      </div>

      {/* Exports list */}
      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : (
        <DataTable
          columns={[
            { key: 'name', header: 'Name', sortable: true },
            {
              key: 'format',
              header: 'Format',
              className: 'font-telemetry text-xs uppercase',
            },
            {
              key: 'size',
              header: 'Size',
              className: 'font-telemetry',
              render: (row: ExportRow) => <span>{formatSize(row.size)}</span>,
            },
            {
              key: 'status',
              header: 'Status',
              render: (row: ExportRow) => (
                <span
                  className={`font-telemetry text-xs uppercase ${statusColors[row.status] ?? 'text-steel'}`}
                >
                  {row.status === 'generating' ? (
                    <span className="inline-flex items-center gap-1">
                      <span className="w-3 h-3 border border-marshal-yellow border-t-transparent rounded-full animate-spin" />
                      generating
                    </span>
                  ) : (
                    row.status
                  )}
                </span>
              ),
            },
            {
              key: 'created_at',
              header: 'Created',
              sortable: true,
              className: 'font-telemetry text-sm',
            },
            {
              key: 'download_url',
              header: '',
              render: (row: ExportRow) =>
                row.download_url ? (
                  <a
                    href={row.download_url}
                    className="text-acid-green font-telemetry text-xs hover:underline"
                    download
                  >
                    Download
                  </a>
                ) : null,
            },
          ]}
          data={exports}
          keyField="id"
          emptyMessage="No exports yet. Generate your first export above."
        />
      )}
    </div>
  );
}
