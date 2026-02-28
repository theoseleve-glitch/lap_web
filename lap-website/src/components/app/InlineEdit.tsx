'use client';

import { useState, useRef, useEffect, useCallback } from 'react';

/* ─── Types ───────────────────────────────────────────────────────────── */

export interface InlineEditProps {
  /** Current value to display. */
  value: string;
  /** Called when the user commits a new value (blur or Enter). */
  onSave: (newValue: string) => Promise<void>;
  /** Placeholder shown when value is empty. */
  placeholder?: string;
  /** Extra Tailwind classes on the outer wrapper. */
  className?: string;
  /** Use a multi-line textarea instead of a single-line input. */
  multiline?: boolean;
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

/* ─── Component ───────────────────────────────────────────────────────── */

export function InlineEdit({
  value,
  onSave,
  placeholder = 'Click to edit',
  className = '',
  multiline = false,
}: InlineEditProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [status, setStatus] = useState<SaveStatus>('idle');
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  // Keep draft in sync when value prop changes externally
  useEffect(() => {
    if (!editing) {
      setDraft(value);
    }
  }, [value, editing]);

  // Auto-focus input when entering edit mode
  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  // Clear "saved" indicator after a short delay
  useEffect(() => {
    if (status === 'saved') {
      const timer = setTimeout(() => setStatus('idle'), 1500);
      return () => clearTimeout(timer);
    }
  }, [status]);

  const startEditing = useCallback(() => {
    setDraft(value);
    setEditing(true);
    setStatus('idle');
  }, [value]);

  const cancel = useCallback(() => {
    setDraft(value);
    setEditing(false);
    setStatus('idle');
  }, [value]);

  const commit = useCallback(async () => {
    const trimmed = draft.trim();
    // No change — just exit edit mode
    if (trimmed === value) {
      setEditing(false);
      return;
    }
    setStatus('saving');
    try {
      await onSave(trimmed);
      setStatus('saved');
      setEditing(false);
    } catch {
      setStatus('error');
      // Stay in edit mode so user can retry
    }
  }, [draft, value, onSave]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        cancel();
      } else if (e.key === 'Enter' && !multiline) {
        e.preventDefault();
        commit();
      } else if (e.key === 'Enter' && multiline && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        commit();
      }
    },
    [cancel, commit, multiline],
  );

  /* ── Editing state: show input/textarea ── */
  if (editing) {
    const sharedClasses =
      'w-full bg-carbon text-chalk font-telemetry text-sm rounded-md border px-2 py-1 outline-none transition-colors ' +
      (status === 'error'
        ? 'border-safety-red focus:border-safety-red'
        : 'border-steel/40 focus:border-accent-purple');

    return (
      <div className={`relative ${className}`}>
        {multiline ? (
          <textarea
            ref={inputRef as React.RefObject<HTMLTextAreaElement>}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={handleKeyDown}
            className={`${sharedClasses} min-h-[60px] resize-y`}
            placeholder={placeholder}
            rows={3}
            data-testid="inline-edit-textarea"
          />
        ) : (
          <input
            ref={inputRef as React.RefObject<HTMLInputElement>}
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={handleKeyDown}
            className={sharedClasses}
            placeholder={placeholder}
            data-testid="inline-edit-input"
          />
        )}
        {status === 'saving' && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-steel text-xs" data-testid="inline-edit-saving">
            Saving...
          </span>
        )}
        {status === 'error' && (
          <p className="text-safety-red text-xs mt-0.5" data-testid="inline-edit-error">
            Save failed. Press Enter to retry or Escape to cancel.
          </p>
        )}
      </div>
    );
  }

  /* ── Display state: show value with hover pencil ── */
  return (
    <div className={`relative group ${className}`}>
      <button
        type="button"
        onClick={startEditing}
        className="w-full text-left flex items-center gap-1.5 cursor-pointer"
        title="Click to edit"
        data-testid="inline-edit-trigger"
      >
        <span
          className={`font-monument text-3xl ${
            value ? 'text-chalk' : 'text-steel/50 italic'
          } border-b border-transparent group-hover:border-steel/30 transition-colors`}
        >
          {value || placeholder}
        </span>

        {/* Pencil icon — visible on hover */}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className="w-3.5 h-3.5 text-steel/0 group-hover:text-steel/60 transition-colors flex-shrink-0"
          aria-hidden="true"
          data-testid="inline-edit-pencil"
        >
          <path d="M2.695 14.763l-1.262 3.154a.5.5 0 00.65.65l3.155-1.262a4 4 0 001.343-.885L17.5 5.5a2.121 2.121 0 00-3-3L3.58 13.42a4 4 0 00-.885 1.343z" />
        </svg>

        {/* Saved check mark (briefly visible after save) */}
        {status === 'saved' && (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="w-4 h-4 text-acid-green flex-shrink-0"
            aria-hidden="true"
            data-testid="inline-edit-check"
          >
            <path
              fillRule="evenodd"
              d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
              clipRule="evenodd"
            />
          </svg>
        )}
      </button>
    </div>
  );
}
