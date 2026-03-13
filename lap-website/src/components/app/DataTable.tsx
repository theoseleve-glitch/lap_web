'use client';

import { useState, useRef, useEffect, useCallback, type ReactNode, type MouseEvent } from 'react';

interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  sortable?: boolean;
  className?: string;
}

/** Context menu action definition. */
export interface ContextAction<T> {
  label: string;
  icon?: ReactNode;
  onClick: (row: T) => void;
  /** Return true to hide this action for a given row. */
  hidden?: (row: T) => boolean;
  destructive?: boolean;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyField: string;
  onRowClick?: (row: T) => void;
  onRowHover?: (row: T) => void;
  emptyMessage?: string;
  rowClassName?: (row: T) => string;
  /** Enable row selection with checkboxes. */
  selectable?: boolean;
  /** Currently selected row keys (controlled). */
  selectedKeys?: Set<string>;
  /** Selection change handler (controlled). */
  onSelectionChange?: (keys: Set<string>) => void;
  /** Right-click context menu actions. */
  contextActions?: ContextAction<T>[];
  /** Server-side sort: if provided, sort arrows are rendered but sorting is delegated. */
  onSortChange?: (key: string, dir: 'asc' | 'desc') => void;
  /** Active sort key (for server-side sort). */
  activeSortKey?: string | null;
  /** Active sort direction (for server-side sort). */
  activeSortDir?: 'asc' | 'desc';
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  keyField,
  onRowClick,
  onRowHover,
  emptyMessage = 'No data available',
  rowClassName,
  selectable = false,
  selectedKeys: controlledSelectedKeys,
  onSelectionChange,
  contextActions,
  onSortChange,
  activeSortKey,
  activeSortDir,
}: DataTableProps<T>) {
  const [internalSortKey, setInternalSortKey] = useState<string | null>(null);
  const [internalSortDir, setInternalSortDir] = useState<'asc' | 'desc'>('asc');
  const [internalSelected, setInternalSelected] = useState<Set<string>>(new Set());

  // Context menu state
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; row: T } | null>(null);
  const ctxRef = useRef<HTMLDivElement>(null);

  // Use controlled or internal selection
  const selected = controlledSelectedKeys ?? internalSelected;
  const setSelected = onSelectionChange ?? setInternalSelected;

  // Use server-side or client-side sort
  const isServerSort = !!onSortChange;
  const sortKey = isServerSort ? (activeSortKey ?? null) : internalSortKey;
  const sortDir = isServerSort ? (activeSortDir ?? 'asc') : internalSortDir;

  const handleSort = (key: string) => {
    if (isServerSort) {
      const newDir = sortKey === key && sortDir === 'asc' ? 'desc' : 'asc';
      onSortChange!(key, newDir);
    } else {
      if (internalSortKey === key) {
        setInternalSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
      } else {
        setInternalSortKey(key);
        setInternalSortDir('asc');
      }
    }
  };

  const sorted = !isServerSort && internalSortKey
    ? [...data].sort((a, b) => {
        const aVal = a[internalSortKey];
        const bVal = b[internalSortKey];
        if (aVal == null) return 1;
        if (bVal == null) return -1;
        const aStr = String(aVal);
        const bStr = String(bVal);
        const cmp = aStr < bStr ? -1 : aStr > bStr ? 1 : 0;
        return internalSortDir === 'asc' ? cmp : -cmp;
      })
    : data;

  // Selection handlers
  const allKeys = data.map((row) => String(row[keyField]));
  const allSelected = allKeys.length > 0 && allKeys.every((k) => selected.has(k));
  const someSelected = allKeys.some((k) => selected.has(k));

  const toggleAll = () => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(allKeys));
    }
  };

  const toggleRow = (key: string, e: MouseEvent) => {
    e.stopPropagation();
    const next = new Set(selected);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    setSelected(next);
  };

  // Context menu handlers
  const handleContextMenu = useCallback(
    (e: MouseEvent, row: T) => {
      if (!contextActions || contextActions.length === 0) return;
      e.preventDefault();
      e.stopPropagation();
      setCtxMenu({ x: e.clientX, y: e.clientY, row });
    },
    [contextActions],
  );

  // Close context menu on outside click or Escape
  useEffect(() => {
    if (!ctxMenu) return;
    const handleClick = (e: Event) => {
      if (ctxRef.current && !ctxRef.current.contains(e.target as Node)) {
        setCtxMenu(null);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setCtxMenu(null);
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [ctxMenu]);

  // Clamp context menu to viewport bounds after render
  useEffect(() => {
    if (!ctxMenu || !ctxRef.current) return;
    const el = ctxRef.current;
    const rect = el.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
      el.style.left = Math.max(0, window.innerWidth - rect.width - 8) + 'px';
    }
    if (rect.bottom > window.innerHeight) {
      el.style.top = Math.max(0, window.innerHeight - rect.height - 8) + 'px';
    }
  }, [ctxMenu]);

  if (data.length === 0) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-8 text-center">
        <p className="text-steel font-body">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden relative">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-steel/20">
              {selectable && (
                <th scope="col" className="w-10 px-3 py-3">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected; }}
                    onChange={toggleAll}
                    className="accent-acid-green w-4 h-4 cursor-pointer"
                    aria-label="Select all rows"
                  />
                </th>
              )}
              {columns.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  className={`text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider ${
                    col.sortable ? 'cursor-pointer hover:text-chalk select-none' : ''
                  } ${col.className ?? ''}`}
                  onClick={col.sortable ? () => handleSort(col.key) : undefined}
                  onKeyDown={
                    col.sortable
                      ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            handleSort(col.key);
                          }
                        }
                      : undefined
                  }
                  tabIndex={col.sortable ? 0 : undefined}
                  role={col.sortable ? 'button' : undefined}
                  aria-sort={
                    col.sortable && sortKey === col.key
                      ? sortDir === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : col.sortable
                        ? 'none'
                        : undefined
                  }
                >
                  {col.header}
                  {col.sortable && sortKey === col.key && (
                    <span className="ml-1" aria-hidden="true">
                      {sortDir === 'asc' ? '↑' : '↓'}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const rowKey = String(row[keyField]);
              const isSelected = selected.has(rowKey);
              return (
                <tr
                  key={rowKey}
                  className={`border-b border-steel/10 ${
                    onRowClick
                      ? 'cursor-pointer hover:bg-asphalt/50 transition-colors'
                      : ''
                  } ${isSelected ? 'bg-acid-green/5' : ''} ${rowClassName ? rowClassName(row) : ''}`}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onPointerEnter={onRowHover ? () => onRowHover(row) : undefined}
                  onContextMenu={contextActions ? (e) => handleContextMenu(e, row) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                  tabIndex={onRowClick ? 0 : undefined}
                  role={onRowClick ? 'button' : undefined}
                >
                  {selectable && (
                    <td className="w-10 px-3 py-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => {}}
                        onClick={(e) => toggleRow(rowKey, e)}
                        className="accent-acid-green w-4 h-4 cursor-pointer"
                        aria-label={`Select row ${rowKey}`}
                      />
                    </td>
                  )}
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`px-4 py-3 text-chalk font-body text-sm ${col.className ?? ''}`}
                    >
                      {col.render ? col.render(row) : String(row[col.key] ?? '—')}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Context menu */}
      {ctxMenu && contextActions && (
        <div
          ref={ctxRef}
          className="fixed z-50 bg-asphalt border border-steel/30 rounded-lg shadow-xl py-1 min-w-[180px]"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
        >
          {contextActions
            .filter((a) => !a.hidden || !a.hidden(ctxMenu.row))
            .map((action) => (
              <button
                key={action.label}
                type="button"
                className={`w-full text-left px-4 py-2 text-sm font-body flex items-center gap-2 transition-colors ${
                  action.destructive
                    ? 'text-safety-red hover:bg-safety-red/10'
                    : 'text-chalk hover:bg-steel/10'
                }`}
                onClick={() => {
                  action.onClick(ctxMenu.row);
                  setCtxMenu(null);
                }}
              >
                {action.icon}
                {action.label}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
