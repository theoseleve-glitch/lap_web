'use client';

interface FocusModeProps {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Focus Mode — being rebuilt.
 * Previously rendered a multi-panel chart dashboard overlay.
 */
export function FocusMode({ isOpen, onClose }: FocusModeProps) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-asphalt/95"
      role="dialog"
      aria-modal="true"
      aria-label="Focus Mode"
    >
      <div className="text-center">
        <h2 className="text-xl font-bold text-zinc-100 mb-2">Focus Mode</h2>
        <p className="text-zinc-400 mb-4">Being rebuilt with new chart system.</p>
        <button
          onClick={onClose}
          className="px-4 py-2 bg-zinc-700 text-zinc-100 rounded hover:bg-zinc-600 transition-colors"
          aria-label="Close focus mode"
        >
          Close
        </button>
      </div>
    </div>
  );
}
