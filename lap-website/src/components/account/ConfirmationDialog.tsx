'use client';

import { type ReactNode, useCallback, useEffect, useRef } from 'react';

interface ConfirmationDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  children?: ReactNode;
}

export function ConfirmationDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  children,
}: ConfirmationDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const handleCancel = useCallback(() => {
    onClose();
  }, [onClose]);

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      className="fixed inset-0 z-50 bg-transparent backdrop:bg-black/60"
    >
      <div className="bg-concrete border border-steel/20 rounded-lg shadow-xl max-w-md w-full mx-auto mt-[20vh] p-6">
        <h3 className="font-monument text-lg text-chalk tracking-tight">{title}</h3>
        {description && (
          <p className="text-sm text-steel font-body mt-2">{description}</p>
        )}
        {children && <div className="mt-4">{children}</div>}
        <div className="flex justify-end gap-3 mt-6">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-telemetry text-steel hover:text-chalk transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={`px-4 py-2 text-sm font-telemetry rounded-md transition-colors ${
              destructive
                ? 'bg-safety-red text-chalk hover:brightness-110'
                : 'bg-acid-green text-asphalt hover:brightness-110'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  );
}
