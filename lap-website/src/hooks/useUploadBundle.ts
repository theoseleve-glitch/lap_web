'use client';

import { useCallback, useRef, useState } from 'react';
import { BACKEND_URL } from '@/lib/api-client';
import { getAccessToken } from '@/lib/auth-store';
import type { IntakeResult, UploadState } from '@/types/bundles';

export function useUploadBundle() {
  const [state, setState] = useState<UploadState>({ phase: 'idle' });
  const xhrRef = useRef<XMLHttpRequest | null>(null);

  const upload = useCallback((file: File) => {
    setState({ phase: 'uploading', progress: 0 });

    const formData = new FormData();
    formData.append('bundle', file);

    const xhr = new XMLHttpRequest();
    xhrRef.current = xhr;

    xhr.open('POST', `${BACKEND_URL}/api/v1/bundles`);
    xhr.withCredentials = true;

    const token = getAccessToken();
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        setState({ phase: 'uploading', progress: pct });
      }
    };

    xhr.onloadend = () => {
      if (xhr.status === 0) {
        setState({ phase: 'error', message: 'Connection lost. Please try again.' });
        return;
      }
      let envelope: { ok?: boolean; data?: IntakeResult; error?: { code?: string; message?: string; details?: Array<{ existing_bundle_id?: string }> } };
      try {
        envelope = JSON.parse(xhr.responseText);
      } catch {
        setState({ phase: 'error', message: 'Unexpected server response.' });
        return;
      }
      if (envelope.ok && envelope.data) {
        setState({ phase: 'done', result: envelope.data });
      } else {
        const code = envelope.error?.code;
        const msg = envelope.error?.message ?? 'Upload failed.';
        const existingId = envelope.error?.details?.[0]?.existing_bundle_id;
        setState({ phase: 'error', message: msg, code, existingBundleId: existingId });
      }
    };

    xhr.onerror = () => {
      setState({ phase: 'error', message: 'Network error. Check your connection and try again.' });
    };

    xhr.ontimeout = () => {
      setState({ phase: 'error', message: 'Upload timed out. Try again with a smaller bundle.' });
    };

    xhr.send(formData);
  }, []);

  const reset = useCallback(() => {
    if (xhrRef.current) {
      xhrRef.current.abort();
      xhrRef.current = null;
    }
    setState({ phase: 'idle' });
  }, []);

  const setDragover = useCallback((over: boolean) => {
    setState((prev) => {
      if (prev.phase === 'idle' && over) return { phase: 'dragover' };
      if (prev.phase === 'dragover' && !over) return { phase: 'idle' };
      return prev;
    });
  }, []);

  return { state, upload, reset, setDragover };
}
