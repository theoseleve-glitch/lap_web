'use client';
import { useKernelStore } from '@/experience/state/store';

export function usePointerInfluence() {
  const pointerX = useKernelStore((s) => s.pointerX);
  const pointerY = useKernelStore((s) => s.pointerY);
  const magnetism = useKernelStore((s) => s.pointerMagnetism);
  return { pointerX, pointerY, magnetism };
}
