'use client';

import { useState, useMemo, type ReactNode } from 'react';

type SortDir = 'asc' | 'desc' | null;

interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  sortable?: boolean;
  className?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyField: keyof T;
  stickyHeader?: boolean;
  onRowClick?: (row: T) => void;
  emptyMessage?: string;
  className?: string;
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  keyField,
  stickyHeader = false,
  onRowClick,
  emptyMessage = 'No data',
  className = '',
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);

  const handleSort = (col: Column<T>) => {
    if (!col.sortable) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : d === 'desc' ? null : 'asc'));
      if (sortDir === 'desc') setSortKey(null);
    } else {
      setSortKey(col.key);
      setSortDir('asc');
    }
  };

  const sorted = useMemo(() => {
    if (!sortKey || !sortDir) return data;
    return [...data].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [data, sortKey, sortDir]);

  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className="w-full text-sm">
        <thead>
          <tr className={`border-b border-steel/20 ${stickyHeader ? 'sticky top-0 bg-concrete z-10' : ''}`}>
            {columns.map((col) => (
              <th
                key={col.key}
                className={`text-left px-3 py-2 text-[10px] font-telemetry uppercase tracking-wider text-steel/60 ${
                  col.sortable ? 'cursor-pointer select-none hover:text-steel' : ''
                } ${col.className || ''}`}
                onClick={() => handleSort(col)}
              >
                <span className="inline-flex items-center gap-1">
                  {col.header}
                  {col.sortable && (
                    <span className="inline-flex flex-col text-[8px] leading-none" aria-hidden="true">
                      <span className={sortKey === col.key && sortDir === 'asc' ? 'text-acid-green' : 'text-steel/30'}>
                        &#9650;
                      </span>
                      <span className={sortKey === col.key && sortDir === 'desc' ? 'text-acid-green' : 'text-steel/30'}>
                        &#9660;
                      </span>
                    </span>
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-3 py-8 text-center text-steel/50">
                {emptyMessage}
              </td>
            </tr>
          )}
          {sorted.map((row) => (
            <tr
              key={String(row[keyField])}
              className={`border-b border-steel/10 transition-colors hover:bg-steel/5 ${
                onRowClick ? 'cursor-pointer' : ''
              }`}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((col) => (
                <td key={col.key} className={`px-3 py-2.5 text-chalk ${col.className || ''}`}>
                  {col.render ? col.render(row) : (row[col.key] as ReactNode) ?? '\u2014'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
