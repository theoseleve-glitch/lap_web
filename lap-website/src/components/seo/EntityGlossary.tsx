const GLOSSARY = [
  { term: 'LAP', definition: 'Lap Analysis Platform — a motorsport telemetry analysis tool that scores driving and generates coaching insights.' },
  { term: 'Telemetry', definition: 'GPS coordinates and sensor data (speed, g-force, RPM) recorded by a data logger during a racing session.' },
  { term: 'Session', definition: 'One continuous recording from a data logger device, typically covering a practice, qualifying, or race stint.' },
  { term: 'Corner', definition: 'An auto-detected turn section of a racing track, identified from GPS trajectory curvature analysis.' },
  { term: 'Pillar Scores', definition: 'Four scoring dimensions — Pace, Consistency, Execution, Robustness — each scored out of 25 for a total of 100.' },
] as const;

export function EntityGlossary() {
  return (
    <details className="mt-12 border border-steel/20 rounded-lg">
      <summary className="cursor-pointer px-4 py-3 font-telemetry text-xs uppercase tracking-wider text-steel hover:text-chalk transition-colors">
        Glossary
      </summary>
      <dl className="px-4 pb-4 space-y-3">
        {GLOSSARY.map(({ term, definition }) => (
          <div key={term}>
            <dt className="font-monument text-sm text-chalk">{term}</dt>
            <dd className="text-sm text-steel font-body">{definition}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
