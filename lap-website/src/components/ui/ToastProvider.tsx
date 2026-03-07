'use client';

import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';
import { Toast } from './Toast';

type ToastSeverity = 'info' | 'success' | 'warning' | 'error';

interface ToastItem {
  id: number;
  message: string;
  severity: ToastSeverity;
  duration?: number;
  action?: { label: string; onClick: () => void };
}

interface ToastContextValue {
  toast: (message: string, severity?: ToastSeverity, opts?: { duration?: number; action?: ToastItem['action'] }) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const MAX_VISIBLE = 5;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const toast = useCallback((
    message: string,
    severity: ToastSeverity = 'info',
    opts?: { duration?: number; action?: ToastItem['action'] },
  ) => {
    const id = ++idRef.current;
    setToasts(prev => [...prev.slice(-(MAX_VISIBLE - 1)), { id, message, severity, ...opts }]);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-live="polite"
        aria-label="Notifications"
        className="fixed bottom-6 right-6 z-overlay flex flex-col-reverse gap-2 pointer-events-none"
      >
        {toasts.map((t, i) => (
          <div key={t.id} className="pointer-events-auto" style={{ opacity: i < MAX_VISIBLE ? 1 : 0 }}>
            <Toast
              message={t.message}
              severity={t.severity}
              duration={t.duration}
              action={t.action}
              onDismiss={() => dismiss(t.id)}
            />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>');
  return ctx;
}
