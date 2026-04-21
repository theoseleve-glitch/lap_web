import { http, HttpResponse } from 'msw';
import { realLifeSession, iracingSession } from './fixtures';
import type { SessionContractBundle } from '@/lib/session-contracts-client';

const envelope = <T>(data: T) => ({ ok: true, data, error: null, meta: {} });

function toRow(bundle: SessionContractBundle) {
  return {
    session_id: bundle.session.session_id,
    session_date: bundle.session.session_start,
    track_name: bundle.session.track.name,
    driver_name: bundle.session.driver.name,
    n_laps: bundle.session.laps?.length ?? 0,
    best_lap_time_s: bundle.session.laps?.find((l) => l.is_best)?.lap_time_s ?? null,
    mean_lap_time_s: null,
    total_score: bundle.session.scores?.overall ?? null,
    grade: null,
    session_type: 'practice',
    track_state: 'dry',
    source: bundle.session.source,
    capabilities: bundle.session.capabilities,
  };
}

export const handlers = [
  http.get('*/api/v1/sessions/:id/contract', ({ params }) => {
    const id = params.id as string;
    if (id === iracingSession.session.session_id) {
      return HttpResponse.json(envelope(iracingSession));
    }
    return HttpResponse.json(envelope(realLifeSession));
  }),

  http.get('*/api/v1/sessions', () =>
    HttpResponse.json(
      envelope({
        sessions: [toRow(realLifeSession), toRow(iracingSession)],
        total: 2,
        limit: 25,
        offset: 0,
      }),
    ),
  ),
];
