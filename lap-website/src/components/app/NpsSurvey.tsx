'use client';

import { useState, useEffect } from 'react';

const STORAGE_KEY = 'lap_nps_survey';
const SHOW_AFTER_SESSIONS = 3;
const COOLDOWN_DAYS = 90;

interface NpsSurveyProps {
  sessionCount: number;
}

export function NpsSurvey({ sessionCount }: NpsSurveyProps) {
  const [visible, setVisible] = useState(false);
  const [score, setScore] = useState<number | null>(null);
  const [feedback, setFeedback] = useState('');
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (sessionCount < SHOW_AFTER_SESSIONS) return;
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const data = JSON.parse(stored);
        if (data.submittedAt) {
          const daysSince = (Date.now() - data.submittedAt) / (1000 * 60 * 60 * 24);
          if (daysSince < COOLDOWN_DAYS) return;
        }
        if (data.dismissedAt) {
          const daysSince = (Date.now() - data.dismissedAt) / (1000 * 60 * 60 * 24);
          if (daysSince < 14) return;
        }
      }
      // Show after a brief delay
      const timer = setTimeout(() => setVisible(true), 5000);
      return () => clearTimeout(timer);
    } catch { /* ignore */ }
  }, [sessionCount]);

  function dismiss() {
    setVisible(false);
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ dismissedAt: Date.now() }));
  }

  function submit() {
    if (score === null) return;
    // In production, send to analytics endpoint
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      submittedAt: Date.now(),
      score,
      feedback,
    }));
    setSubmitted(true);
    setTimeout(() => setVisible(false), 2000);
  }

  if (!visible) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 w-80 bg-concrete border border-steel/20 rounded-xl shadow-2xl p-5">
      {submitted ? (
        <div className="text-center py-4">
          <p className="text-acid-green font-monument text-sm mb-1">Thank you!</p>
          <p className="text-steel text-xs font-body">Your feedback helps us improve LAP.</p>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-monument text-xs text-chalk">Quick Feedback</h3>
            <button type="button" onClick={dismiss} className="text-steel/30 hover:text-steel text-sm">&times;</button>
          </div>
          <p className="text-steel text-xs font-body mb-3">
            How likely are you to recommend LAP to a fellow racer?
          </p>
          <div className="grid grid-cols-11 gap-1 mb-2">
            {Array.from({ length: 11 }, (_, i) => (
              <button
                type="button"
                key={i}
                onClick={() => setScore(i)}
                className={`h-8 rounded text-[10px] font-telemetry transition-colors ${
                  score === i
                    ? i <= 6 ? 'bg-safety-red text-white' : i <= 8 ? 'bg-marshal-yellow text-carbon' : 'bg-acid-green text-carbon'
                    : 'bg-steel/10 text-steel hover:bg-steel/20'
                }`}
              >
                {i}
              </button>
            ))}
          </div>
          <div className="flex justify-between text-[9px] font-telemetry text-steel/40 uppercase tracking-wider mb-3">
            <span>Not likely</span>
            <span>Very likely</span>
          </div>
          {score !== null && (
            <>
              <textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder={score >= 9 ? "What do you love most?" : score >= 7 ? "What could be better?" : "What's holding you back?"}
                className="w-full h-16 bg-asphalt/40 border border-steel/20 rounded p-2 text-xs text-chalk font-body placeholder:text-steel/30 resize-none mb-3"
              />
              <button
                type="button"
                onClick={submit}
                className="w-full py-2 bg-pit-orange text-carbon font-telemetry text-xs uppercase tracking-wider rounded hover:brightness-110 transition-all"
              >
                Submit
              </button>
            </>
          )}
        </>
      )}
    </div>
  );
}
