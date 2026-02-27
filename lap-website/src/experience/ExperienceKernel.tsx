'use client';

import type { ReactNode } from 'react';
import { InputManager } from './input/InputManager';
import { QualityManager } from './quality/QualityManager';
import { SafetyCarMode } from './quality/SafetyCarMode';
import { DebugHUD } from './quality/DebugHUD';
import { MotionOrchestrator } from './motion/MotionOrchestrator';
import { SectorGateController } from './narrative/SectorGateController';
import { DrsController } from './narrative/DrsController';
import { DeltaTickController } from './narrative/DeltaTickController';
import { EXPERIENCE_V2 } from '@/lib/feature-flags';

interface ExperienceKernelProps {
  children: ReactNode;
}

export function ExperienceKernel({ children }: ExperienceKernelProps) {
  return (
    <>
      <QualityManager />
      <SafetyCarMode />
      <InputManager />
      <MotionOrchestrator />
      {EXPERIENCE_V2 && <SectorGateController />}
      {EXPERIENCE_V2 && <DrsController />}
      {EXPERIENCE_V2 && <DeltaTickController />}
      <DebugHUD />
      {children}
    </>
  );
}
