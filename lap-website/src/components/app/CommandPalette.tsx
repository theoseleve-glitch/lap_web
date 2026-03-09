'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';

interface PaletteItem {
  label: string;
  href: string;
  section: string;
  keywords?: string;
}

const ITEMS: PaletteItem[] = [
  { label: 'Dashboard', href: '/app/dashboard', section: 'Navigation' },
  { label: 'Sessions', href: '/app/sessions', section: 'Navigation' },
  { label: 'Upload Session', href: '/app/sessions/upload', section: 'Navigation', keywords: 'import csv' },
  { label: 'Tracks', href: '/app/tracks', section: 'Navigation' },
  { label: 'Drivers', href: '/app/drivers', section: 'Navigation' },
  { label: 'Compare Sessions', href: '/app/compare/sessions', section: 'Navigation', keywords: 'diff overlay' },
  { label: 'Compare Drivers', href: '/app/compare/drivers', section: 'Navigation' },
  { label: 'Analytics', href: '/app/analytics', section: 'Navigation', keywords: 'trends charts' },
  { label: 'Leaderboard', href: '/app/leaderboard', section: 'Navigation', keywords: 'ranking' },
  { label: 'Race Strategy', href: '/app/race-strategy', section: 'Navigation', keywords: 'stint pit' },
  { label: 'Karts', href: '/app/karts', section: 'Navigation', keywords: 'equipment' },
  { label: 'Weekends', href: '/app/weekends', section: 'Navigation', keywords: 'event' },
  { label: 'Exports', href: '/app/exports', section: 'Navigation', keywords: 'download pdf' },
  { label: 'Data Health', href: '/app/data-health', section: 'Navigation', keywords: 'quality diagnostics' },
  { label: 'Account Settings', href: '/app/account', section: 'Account', keywords: 'profile preferences' },
  { label: 'Billing', href: '/app/account/billing', section: 'Account', keywords: 'plan subscription' },
  { label: 'Security', href: '/app/account/security', section: 'Account', keywords: 'password 2fa' },
  { label: 'Data & Privacy', href: '/app/account/data', section: 'Account', keywords: 'export delete gdpr' },
  { label: 'Help Center', href: '/help', section: 'Support', keywords: 'faq guide' },
  { label: 'Changelog', href: '/changelog', section: 'Support', keywords: 'updates releases' },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const filtered = query.trim()
    ? ITEMS.filter((item) => {
        const q = query.toLowerCase();
        return (
          item.label.toLowerCase().includes(q) ||
          item.section.toLowerCase().includes(q) ||
          (item.keywords && item.keywords.toLowerCase().includes(q))
        );
      })
    : ITEMS;

  const close = useCallback(() => {
    setOpen(false);
    setQuery('');
    setSelected(0);
  }, []);

  const navigate = useCallback(
    (href: string) => {
      close();
      router.push(href);
    },
    [close, router],
  );

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    setSelected(0);
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelected((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelected((s) => Math.max(s - 1, 0));
    } else if (e.key === 'Enter' && filtered[selected]) {
      navigate(filtered[selected].href);
    } else if (e.key === 'Escape') {
      close();
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]"
      onClick={close}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" />

      {/* Palette */}
      <div
        className="relative w-full max-w-lg bg-concrete border border-steel/20 rounded-xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-steel/10">
          <svg className="w-4 h-4 text-steel shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search pages..."
            className="flex-1 bg-transparent text-chalk text-sm outline-none placeholder:text-steel/50"
          />
          <kbd className="hidden sm:inline text-[10px] text-steel/60 border border-steel/20 rounded px-1.5 py-0.5 font-telemetry">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <ul className="max-h-72 overflow-y-auto py-1" role="listbox">
          {filtered.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-steel/60">No results found</li>
          )}
          {filtered.map((item, i) => (
            <li
              key={item.href}
              role="option"
              aria-selected={i === selected}
              className={`px-4 py-2 cursor-pointer flex items-center justify-between text-sm ${
                i === selected
                  ? 'bg-acid-green/10 text-acid-green'
                  : 'text-chalk hover:bg-steel/5'
              }`}
              onClick={() => navigate(item.href)}
              onMouseEnter={() => setSelected(i)}
            >
              <span>{item.label}</span>
              <span className="text-[10px] text-steel/40 font-telemetry uppercase tracking-wider">
                {item.section}
              </span>
            </li>
          ))}
        </ul>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t border-steel/10 flex gap-3 text-[10px] text-steel/40 font-telemetry">
          <span>↑↓ Navigate</span>
          <span>↵ Open</span>
          <span>ESC Close</span>
        </div>
      </div>
    </div>
  );
}
