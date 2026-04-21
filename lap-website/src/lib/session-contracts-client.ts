import { useQuery } from '@tanstack/react-query';
import { apiFetch } from './api-client';
import type {
  CoachingContract,
  OptimizerContract,
  SessionContract,
} from '@/types/contracts';

export interface SessionContractBundle {
  session: SessionContract;
  coaching: CoachingContract | null;
  optimizer: OptimizerContract | null;
}

function assertSessionContract(raw: unknown): asserts raw is SessionContract {
  const o = raw as Partial<SessionContract>;
  if (!o || typeof o !== 'object' || typeof o.session_id !== 'string' ||
      typeof o.source !== 'string' || typeof o.duration_s !== 'number' ||
      !o.capabilities || !o.driver || !o.track) {
    throw new Error('invalid session contract: missing required fields');
  }
}

export async function fetchSessionContract(sessionId: string): Promise<SessionContractBundle> {
  const bundle = await apiFetch<SessionContractBundle>(
    `/sessions/${encodeURIComponent(sessionId)}/contract`,
  );
  assertSessionContract(bundle.session);
  return bundle;
}

export function useSessionContract(sessionId: string) {
  return useQuery({
    queryKey: ['session-contract', sessionId],
    queryFn: () => fetchSessionContract(sessionId),
    staleTime: 30_000,
  });
}
