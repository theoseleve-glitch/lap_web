'use client';

import { useCallback, useRef } from 'react';
import type { IntakeResult } from '@/types/bundles';
import { useUploadBundle } from '@/hooks/useUploadBundle';
import { getErrorMessage } from '@/lib/bundle-vocabulary';

interface Props {
  onSuccess: (result: IntakeResult) => void;
}

export function BundleUploadPanel({ onSuccess }: Props) {
  const { state, upload, reset, setDragover } = useUploadBundle();
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback((file: File) => {
    if (!file.name.endsWith('.zip')) {
      return;
    }
    upload(file);
  }, [upload]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragover(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile, setDragover],
  );

  // Navigate on success
  if (state.phase === 'done') {
    onSuccess(state.result);
  }

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragover(true); }}
        onDragLeave={() => setDragover(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`
          relative flex flex-col items-center justify-center
          rounded-xl border-2 border-dashed p-12 cursor-pointer
          transition-colors
          ${state.phase === 'dragover'
            ? 'border-gold bg-gold/5'
            : 'border-steel/30 hover:border-gold/50 bg-concrete'}
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".zip"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
        />

        {state.phase === 'idle' || state.phase === 'dragover' ? (
          <>
            <p className="text-sm font-monument text-chalk mb-1">
              Drop session bundle here
            </p>
            <p className="text-xs font-body text-steel">
              or click to browse (.zip)
            </p>
          </>
        ) : null}

        {state.phase === 'uploading' && (
          <div className="w-full max-w-xs">
            <p className="text-sm font-telemetry text-chalk mb-2 text-center">
              Uploading... {state.progress}%
            </p>
            <div className="h-1.5 rounded-full bg-steel/20 overflow-hidden">
              <div
                className="h-full rounded-full bg-gold transition-all duration-300"
                style={{ width: `${state.progress}%` }}
              />
            </div>
          </div>
        )}

        {state.phase === 'processing' && (
          <div className="flex items-center gap-2">
            <div className="h-4 w-4 rounded-full border-2 border-gold border-t-transparent animate-spin" />
            <span className="text-sm font-telemetry text-chalk">Processing...</span>
          </div>
        )}
      </div>

      {/* Error display */}
      {state.phase === 'error' && (
        <div className="rounded-xl border border-safety-red/30 bg-safety-red/5 p-4">
          <p className="text-sm font-body text-safety-red mb-2">
            {state.code ? getErrorMessage(state.code) : state.message}
          </p>
          {state.existingBundleId && (
            <a
              href={`/app/bundles/${state.existingBundleId}`}
              className="text-sm font-telemetry text-gold hover:text-gold/80 transition-colors"
            >
              View existing session &rarr;
            </a>
          )}
          <button
            onClick={reset}
            className="ml-4 text-sm font-telemetry text-steel hover:text-chalk transition-colors"
          >
            Try again
          </button>
        </div>
      )}
    </div>
  );
}
