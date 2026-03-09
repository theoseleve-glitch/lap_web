/**
 * unit-preferences.ts — User unit system preferences with conversion helpers.
 *
 * Stores the user's preferred unit system in localStorage and provides
 * conversion functions that respect the preference.
 *
 * Supported conversions:
 * - Speed: m/s ↔ km/h ↔ mph
 * - Temperature: °C ↔ °F
 * - Distance: m ↔ ft, km ↔ mi
 * - Acceleration: m/s² ↔ G (always available)
 */
import { create } from 'zustand';

export type SpeedUnit = 'km/h' | 'mph';
export type TempUnit = 'C' | 'F';
export type DistanceUnit = 'metric' | 'imperial';

interface UnitPreferences {
  speed: SpeedUnit;
  temp: TempUnit;
  distance: DistanceUnit;
  setSpeed: (u: SpeedUnit) => void;
  setTemp: (u: TempUnit) => void;
  setDistance: (u: DistanceUnit) => void;
}

const STORAGE_KEY = 'unit_preferences';

function loadPrefs(): Pick<UnitPreferences, 'speed' | 'temp' | 'distance'> {
  if (typeof window === 'undefined') return { speed: 'km/h', temp: 'C', distance: 'metric' };
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return {
        speed: parsed.speed === 'mph' ? 'mph' : 'km/h',
        temp: parsed.temp === 'F' ? 'F' : 'C',
        distance: parsed.distance === 'imperial' ? 'imperial' : 'metric',
      };
    }
  } catch {}
  return { speed: 'km/h', temp: 'C', distance: 'metric' };
}

function savePrefs(prefs: Pick<UnitPreferences, 'speed' | 'temp' | 'distance'>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {}
}

export const useUnitPreferences = create<UnitPreferences>((set, get) => {
  const initial = loadPrefs();
  return {
    ...initial,
    setSpeed: (u) => {
      set({ speed: u });
      savePrefs({ ...get(), speed: u });
    },
    setTemp: (u) => {
      set({ temp: u });
      savePrefs({ ...get(), temp: u });
    },
    setDistance: (u) => {
      set({ distance: u });
      savePrefs({ ...get(), distance: u });
    },
  };
});

// ── Conversion helpers ──────────────────────────────────────────

/** Convert m/s to the user's preferred speed unit. */
export function convertSpeed(mps: number, unit: SpeedUnit): number {
  if (unit === 'mph') return mps * 2.23694;
  return mps * 3.6; // km/h
}

/** Format speed with unit label. Input is m/s. */
export function formatSpeed(mps: number | null | undefined, unit: SpeedUnit): string {
  if (mps == null || !isFinite(mps)) return '\u2014';
  const converted = convertSpeed(mps, unit);
  return `${converted.toFixed(1)} ${unit}`;
}

/** Convert °C to the user's preferred temp unit. */
export function convertTemp(celsius: number, unit: TempUnit): number {
  if (unit === 'F') return celsius * 9 / 5 + 32;
  return celsius;
}

/** Format temperature with unit label. Input is °C. */
export function formatTemp(celsius: number | null | undefined, unit: TempUnit): string {
  if (celsius == null || !isFinite(celsius)) return '\u2014';
  const converted = convertTemp(celsius, unit);
  return `${converted.toFixed(1)}°${unit}`;
}

/** Convert meters to preferred distance unit. */
export function convertDistance(meters: number, unit: DistanceUnit): { value: number; label: string } {
  if (unit === 'imperial') {
    if (meters >= 1609.34) {
      return { value: meters / 1609.34, label: 'mi' };
    }
    return { value: meters * 3.28084, label: 'ft' };
  }
  if (meters >= 1000) {
    return { value: meters / 1000, label: 'km' };
  }
  return { value: meters, label: 'm' };
}

/** Format distance with unit label. Input is meters. */
export function formatDistanceWithUnit(meters: number | null | undefined, unit: DistanceUnit): string {
  if (meters == null || !isFinite(meters)) return '\u2014';
  const { value, label } = convertDistance(meters, unit);
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${label}`;
}
