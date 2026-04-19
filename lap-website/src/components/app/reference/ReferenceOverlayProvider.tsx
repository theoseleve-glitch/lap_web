'use client';

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react';
import { api } from '@/lib/api-client';
import type { ReferenceData, ReferenceOverlayContextValue } from './types';

const ReferenceOverlayContext = createContext<ReferenceOverlayContextValue | null>(null);

interface ProviderProps {
  sessionId: string;
  primaryLap: number | null;
  children: ReactNode;
}

export function ReferenceOverlayProvider({
  sessionId,
  primaryLap,
  children,
}: ProviderProps) {
  const [referenceSession, setReferenceSession] = useState<string | null>(null);
  const [referenceLap, setReferenceLap] = useState<number | null>(null);
  const [referenceData, setReferenceData] = useState<ReferenceData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setReference = useCallback((sid: string, lap: number) => {
    setReferenceSession(sid);
    setReferenceLap(lap);
    setError(null);
  }, []);

  const clearReference = useCallback(() => {
    setReferenceSession(null);
    setReferenceLap(null);
    setReferenceData(null);
    setError(null);
  }, []);

  useEffect(() => {
    if (!referenceSession || !referenceLap || !primaryLap) {
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setError(null);

    const params = new URLSearchParams({
      ref_session: referenceSession,
      ref_lap: String(referenceLap),
      primary_lap: String(primaryLap),
    });

    // api.get unwraps the envelope — the resolved value IS the data field
    api
      .get<ReferenceData>(
        `/sessions/${sessionId}/reference-data?${params}`
      )
      .then((data) => {
        if (!cancelled) {
          setReferenceData(data);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : 'Failed to load reference data'
          );
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId, primaryLap, referenceSession, referenceLap]);

  return (
    <ReferenceOverlayContext.Provider
      value={{
        referenceSession,
        referenceLap,
        referenceData,
        isLoading,
        error,
        setReference,
        clearReference,
      }}
    >
      {children}
    </ReferenceOverlayContext.Provider>
  );
}

export function useReferenceOverlay(): ReferenceOverlayContextValue {
  const ctx = useContext(ReferenceOverlayContext);
  if (!ctx) {
    return {
      referenceSession: null,
      referenceLap: null,
      referenceData: null,
      isLoading: false,
      error: null,
      setReference: () => {},
      clearReference: () => {},
    };
  }
  return ctx;
}
