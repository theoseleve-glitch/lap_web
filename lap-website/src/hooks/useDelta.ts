'use client';

import { useState, useCallback } from 'react';

export function useDelta() {
  const [delta, setDelta] = useState(0);
  const [history, setHistory] = useState<number[]>([]);

  const addDelta = useCallback((value: number) => {
    setDelta(value);
    setHistory((prev) => [...prev, value]);
  }, []);

  const totalDelta = history.reduce((sum, v) => sum + v, 0);

  const reset = useCallback(() => {
    setDelta(0);
    setHistory([]);
  }, []);

  return { delta, totalDelta, addDelta, reset };
}
