'use client';
import { useKernelStore } from '@/experience/state/store';

export function useScrollVelocity() {
  const scrollVelocity = useKernelStore((s) => s.scrollVelocity);
  const scrollDirection = useKernelStore((s) => s.scrollDirection);
  return { scrollVelocity, scrollDirection };
}
