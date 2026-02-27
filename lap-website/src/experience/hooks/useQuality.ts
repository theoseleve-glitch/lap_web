'use client';
import { useKernelStore } from '@/experience/state/store';

export function useQuality() {
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const qualityMode = useKernelStore((s) => s.qualityMode);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const webglAvailable = useKernelStore((s) => s.webglAvailable);

  return {
    qualityTier,
    qualityMode,
    reducedMotion,
    webglAvailable,
    isHigh: qualityTier === 'high',
    isLow: qualityTier === 'low',
    canUseWebgl: webglAvailable && !reducedMotion,
    canUsePost: qualityTier !== 'low' && !reducedMotion,
  };
}
