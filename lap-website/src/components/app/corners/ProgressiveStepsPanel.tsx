'use client';

import type { FocusArea } from './useCornerData';

interface ProgressiveStepsPanelProps {
  focusArea: FocusArea | null;
  coachingHint: string | null | undefined;
}

function splitIntoSteps(text: string): string[] {
  // Try numbered items first: "1. Do this 2. Do that"
  const numbered = text.match(/\d+\.\s+[^.]+(?:\.|$)/g);
  if (numbered && numbered.length > 1) return numbered.map((s) => s.replace(/^\d+\.\s*/, '').trim());

  // Try semicolons
  const semicolons = text.split(/;\s*/);
  if (semicolons.length > 1) return semicolons.map((s) => s.trim()).filter(Boolean);

  // Fall back to sentences
  const sentences = text.split(/(?<=\.)\s+/).filter((s) => s.length > 10);
  if (sentences.length > 1) return sentences;

  return [text];
}

export function ProgressiveStepsPanel({ focusArea, coachingHint }: ProgressiveStepsPanelProps) {
  const rawText = focusArea?.advice ?? coachingHint;

  if (!rawText) {
    return <p className="text-steel text-sm font-body">No coaching available for this corner.</p>;
  }

  const steps = splitIntoSteps(rawText);

  return (
    <div className="space-y-3">
      {focusArea && (
        <p className="text-steel text-xs font-telemetry uppercase tracking-wider mb-2">
          {focusArea.category.replace(/_/g, ' ')} — {focusArea.time_loss_s.toFixed(3)}s total loss
        </p>
      )}
      <ol className="space-y-3">
        {steps.map((step, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="shrink-0 w-6 h-6 rounded-full bg-concrete border border-steel/20 flex items-center justify-center text-xs font-telemetry text-steel">
              {i + 1}
            </span>
            <p className="text-chalk/80 text-sm font-body leading-relaxed pt-0.5">{step}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
