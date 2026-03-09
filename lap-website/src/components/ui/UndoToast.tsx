'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { create } from 'zustand';

interface UndoAction {
  id: string;
  message: string;
  onUndo: () => void;
  createdAt: number;
}

interface UndoStore {
  toasts: UndoAction[];
  push: (message: string, onUndo: () => void) => void;
  dismiss: (id: string) => void;
}

export const useUndoStore = create<UndoStore>((set) => ({
  toasts: [],
  push: (message, onUndo) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    set((s) => ({ toasts: [...s.toasts, { id, message, onUndo, createdAt: Date.now() }] }));
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

const TIMEOUT_MS = 5000;

function UndoToastItem({ toast }: { toast: UndoAction }) {
  const dismiss = useUndoStore((s) => s.dismiss);
  const [progress, setProgress] = useState(100);
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    const start = toast.createdAt;
    timerRef.current = setInterval(() => {
      const elapsed = Date.now() - start;
      const remaining = Math.max(0, 100 - (elapsed / TIMEOUT_MS) * 100);
      setProgress(remaining);
      if (remaining <= 0) {
        dismiss(toast.id);
      }
    }, 50);
    return () => clearInterval(timerRef.current);
  }, [toast, dismiss]);

  const handleUndo = useCallback(() => {
    clearInterval(timerRef.current);
    toast.onUndo();
    dismiss(toast.id);
  }, [toast, dismiss]);

  return (
    <div className="bg-concrete border border-steel/20 rounded-lg shadow-xl px-4 py-3 flex items-center gap-3 min-w-[280px] animate-in slide-in-from-bottom-2">
      <p className="text-sm text-chalk flex-1">{toast.message}</p>
      <button
        type="button"
        onClick={handleUndo}
        className="text-xs font-telemetry uppercase tracking-wider text-acid-green hover:text-acid-green/80 transition-colors shrink-0"
      >
        Undo
      </button>
      <button
        type="button"
        onClick={() => dismiss(toast.id)}
        className="text-steel hover:text-chalk transition-colors text-sm"
        aria-label="Dismiss"
      >
        &times;
      </button>
      {/* Progress bar */}
      <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-steel/10 overflow-hidden rounded-b-lg">
        <div
          className="h-full bg-acid-green/40 transition-none"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

export function UndoToastContainer() {
  const toasts = useUndoStore((s) => s.toasts);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <UndoToastItem key={t.id} toast={t} />
      ))}
    </div>
  );
}
