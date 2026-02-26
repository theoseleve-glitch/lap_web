import { colors } from '@/lib/tokens';

export const chartTheme = {
  bg: colors.concrete,
  gridLine: 'rgba(138, 143, 152, 0.2)',
  axisLabel: colors.chalk,
  primary: colors.acidGreen,
  secondary: colors.pitOrange,
  danger: colors.safetyRed,
  warning: colors.marshalYellow,
} as const;
