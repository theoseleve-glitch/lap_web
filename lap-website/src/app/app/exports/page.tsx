'use client';

import { useState, useId } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, BACKEND_URL } from '@/lib/api-client';
import { DataTable, QueryError, SkeletonTableRows } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

interface ExportRow {
  id: string;
  data_type: string;
  format: string;
  file_size: number | null;
  status: 'pending' | 'generating' | 'ready' | 'failed';
  created_at: string;
  completed_at: string | null;
  error: string | null;
}

type ExportFormat = 'csv' | 'json' | 'pdf' | 'parquet';

function formatSize(bytes: number | null): string {
  if (bytes == null) return '\u2014';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function capitalizeDataType(dt: string): string {
  return dt.charAt(0).toUpperCase() + dt.slice(1);
}

const statusColors: Record<string, string> = {
  ready: 'text-acid-green',
  pending: 'text-marshal-yellow',
  generating: 'text-marshal-yellow',
  failed: 'text-safety-red',
};

export default function ExportsPage() {
  const fieldId = useId();
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>('csv');
  const [exportType, setExportType] = useState('sessions');

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['exports'],
    queryFn: () => api.get<{ exports: ExportRow[] }>('/exports'),
    refetchInterval: (query) => {
      const exports = query.state.data?.exports;
      const hasActive = exports?.some(
        (e) => e.status === 'generating' || e.status === 'pending',
      );
      return hasActive ? 5000 : false;
    },
  });

  const exports = data?.exports ?? [];

  const handleGenerate = async () => {
    setGenerating(true);
    setGenerateError(null);
    try {
      await api.post('/exports/generate', {
        type: exportType,
        format: selectedFormat,
      });
      await refetch();
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : 'Export generation failed');
    } finally {
      setGenerating(false);
    }
  };

  const handleDownload = (row: ExportRow) => {
    window.open(
      `${BACKEND_URL}/api/v1/exports/${row.id}/download`,
      '_blank',
    );
  };

  return (
    <div>
      <PageIntro title="Exports" subtitle="Download your telemetry data" />

      {/* Generate new export */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h2 className="font-body text-chalk text-sm mb-4">Generate Export</h2>
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
            <span className="block text-steel font-telemetry text-xs uppercase mb-1" id="format-label">
              Format
            </span>
            <div className="flex gap-2" role="group" aria-labelledby="format-label">
              {(['csv', 'json', 'pdf', 'parquet'] as ExportFormat[]).map((fmt) => (
                <button
                  key={fmt}
                  type="button"
                  aria-pressed={selectedFormat === fmt}
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
        {generateError && (
          <p className="text-safety-red text-xs font-telemetry mt-3">{generateError}</p>
        )}
      </div>

      {/* Exports list */}
      {isLoading ? (
        <SkeletonTableRows rows={5} cols={5} />
      ) : error ? (
        <QueryError message="Couldn't load exports." onRetry={() => refetch()} />
      ) : (
        <DataTable
          columns={[
            {
              key: 'data_type',
              header: 'Data Type',
              sortable: true,
              render: (row: ExportRow) => (
                <span>{capitalizeDataType(row.data_type)}</span>
              ),
            },
            {
              key: 'format',
              header: 'Format',
              className: 'font-telemetry text-xs uppercase',
            },
            {
              key: 'file_size',
              header: 'Size',
              className: 'font-telemetry',
              render: (row: ExportRow) => <span>{formatSize(row.file_size)}</span>,
            },
            {
              key: 'status',
              header: 'Status',
              render: (row: ExportRow) => (
                <span
                  className={`font-telemetry text-xs uppercase ${statusColors[row.status] ?? 'text-steel'}`}
                >
                  {row.status === 'generating' || row.status === 'pending' ? (
                    <span className="inline-flex items-center gap-1">
                      <span className="w-3 h-3 border border-marshal-yellow border-t-transparent rounded-full animate-spin" />
                      {row.status}
                    </span>
                  ) : row.status === 'failed' && row.error ? (
                    <span className="inline-flex items-center gap-1" title={row.error}>
                      failed
                      <span className="text-safety-red/60 text-[10px] normal-case truncate max-w-[180px] inline-block align-middle">
                        {row.error}
                      </span>
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
              key: 'actions',
              header: '',
              render: (row: ExportRow) =>
                row.status === 'ready' ? (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDownload(row);
                    }}
                    className="text-acid-green font-telemetry text-xs hover:underline"
                  >
                    Download
                  </button>
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
