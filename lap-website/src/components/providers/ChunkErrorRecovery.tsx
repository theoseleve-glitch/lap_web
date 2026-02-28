'use client';

import { useEffect } from 'react';

const RECOVERY_KEY = 'lap:chunk-recovery-at';
const COOLDOWN_MS = 30_000;

function isChunkLoadFailure(reason: unknown): boolean {
  const message = typeof reason === 'string'
    ? reason
    : reason instanceof Error
      ? reason.message
      : '';
  return /ChunkLoadError|Loading chunk [^ ]+ failed|Failed to fetch RSC payload/i.test(message);
}

function isCoolingDown(): boolean {
  const lastReloadAt = Number(window.sessionStorage.getItem(RECOVERY_KEY) || 0);
  return Number.isFinite(lastReloadAt) && Date.now() - lastReloadAt < COOLDOWN_MS;
}

export function ChunkErrorRecovery() {
  useEffect(() => {
    const shouldReload = (reason: unknown) => {
      if (!isChunkLoadFailure(reason) || isCoolingDown()) {
        return;
      }

      window.sessionStorage.setItem(RECOVERY_KEY, String(Date.now()));
      window.location.reload();
    };

    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      shouldReload(event.reason);
    };

    const onError = (event: ErrorEvent) => {
      shouldReload(event.error || event.message);
    };

    window.addEventListener('unhandledrejection', onUnhandledRejection);
    window.addEventListener('error', onError);

    return () => {
      window.removeEventListener('unhandledrejection', onUnhandledRejection);
      window.removeEventListener('error', onError);
    };
  }, []);

  return null;
}
