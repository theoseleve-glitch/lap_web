'use client';

import { useState, useRef, useEffect, useCallback, type ReactNode } from 'react';

interface DropdownOption {
  value: string;
  label: string;
  group?: string;
}

interface DropdownProps {
  options: DropdownOption[];
  value?: string;
  onChange: (value: string) => void;
  placeholder?: string;
  searchable?: boolean;
  className?: string;
  trigger?: ReactNode;
}

export function Dropdown({ options, value, onChange, placeholder = 'Select...', searchable = false, className = '', trigger }: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [highlighted, setHighlighted] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = query
    ? options.filter((o) => o.label.toLowerCase().includes(query.toLowerCase()))
    : options;

  const selectedLabel = options.find((o) => o.value === value)?.label;

  const close = useCallback(() => {
    setOpen(false);
    setQuery('');
    setHighlighted(0);
  }, []);

  const select = useCallback(
    (val: string) => {
      onChange(val);
      close();
    },
    [onChange, close],
  );

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) close();
    }
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [open, close]);

  useEffect(() => {
    if (open && searchable) {
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open, searchable]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlighted((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlighted((h) => Math.max(h - 1, 0));
    } else if (e.key === 'Enter' && filtered[highlighted]) {
      select(filtered[highlighted].value);
    } else if (e.key === 'Escape') {
      close();
    }
  };

  // Group options
  const groups = new Map<string, DropdownOption[]>();
  for (const opt of filtered) {
    const g = opt.group || '';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)!.push(opt);
  }

  let flatIndex = 0;

  return (
    <div ref={containerRef} className={`relative ${className}`} onKeyDown={handleKeyDown}>
      {trigger ? (
        <div
          role="button"
          tabIndex={0}
          onClick={() => setOpen(!open)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              setOpen(!open);
            }
          }}
        >{trigger}</div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="w-full flex items-center justify-between gap-2 bg-asphalt border border-steel/30 rounded px-3 py-2 text-sm text-left transition-colors focus:outline-none focus:border-pit-orange"
          aria-haspopup="listbox"
          aria-expanded={open}
        >
          <span className={selectedLabel ? 'text-chalk' : 'text-steel/50'}>{selectedLabel || placeholder}</span>
          <span className="text-steel text-xs" aria-hidden="true">{open ? '\u25B2' : '\u25BC'}</span>
        </button>
      )}

      {open && (
        <div className="absolute z-40 top-full left-0 right-0 mt-1 bg-concrete border border-steel/20 rounded-lg shadow-xl overflow-hidden">
          {searchable && (
            <div className="p-2 border-b border-steel/10">
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => { setQuery(e.target.value); setHighlighted(0); }}
                placeholder="Search..."
                className="w-full bg-asphalt/50 border border-steel/20 rounded px-2 py-1.5 text-xs text-chalk placeholder:text-steel/40 focus:outline-none"
              />
            </div>
          )}
          <ul className="max-h-60 overflow-y-auto py-1" role="listbox">
            {filtered.length === 0 && (
              <li className="px-3 py-2 text-xs text-steel/50 text-center">No options</li>
            )}
            {Array.from(groups.entries()).map(([group, opts]) => (
              <li key={group} role="group" aria-label={group || undefined}>
                {group && (
                  <p className="px-3 py-1.5 text-[10px] text-steel/50 font-telemetry uppercase tracking-wider">{group}</p>
                )}
                <ul>
                  {opts.map((opt) => {
                    const idx = flatIndex++;
                    return (
                      <li
                        key={opt.value}
                        role="option"
                        aria-selected={opt.value === value}
                        className={`px-3 py-2 text-sm cursor-pointer transition-colors ${
                          idx === highlighted
                            ? 'bg-acid-green/10 text-acid-green'
                            : opt.value === value
                              ? 'text-chalk bg-steel/5'
                              : 'text-steel hover:text-chalk hover:bg-steel/5'
                        }`}
                        onClick={() => select(opt.value)}
                        onMouseEnter={() => setHighlighted(idx)}
                      >
                        {opt.label}
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
