'use client';

import { useMemo } from 'react';
import { roomAccents, colors } from '@/lib/tokens';

const accentMap: Record<string, string> = {
  none: colors.chalk,
  green: colors.acidGreen,
  red: colors.safetyRed,
  yellow: colors.marshalYellow,
  orange: colors.pitOrange,
};

export function useAccentColor(roomId: string): string {
  return useMemo(() => {
    const key = roomAccents[roomId] ?? 'none';
    return accentMap[key] ?? colors.chalk;
  }, [roomId]);
}
