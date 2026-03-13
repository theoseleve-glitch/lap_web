'use client';

import { useState, useEffect, useCallback, useRef } from 'react';

const NOTIFICATIONS = [
  { name: 'A driver in Germany', action: 'just uploaded a session', track: 'Nurburgring GP', time: '2m ago' },
  { name: 'A kart racer', action: 'scored 87/100', track: 'South Garda Karting', time: '4m ago' },
  { name: 'A team in UK', action: 'analyzed 12 sessions', track: 'Brands Hatch', time: '7m ago' },
  { name: 'A driver in Italy', action: 'improved by 1.4s', track: 'Monza', time: '11m ago' },
  { name: 'A junior racer', action: 'earned Grade A', track: 'Spa-Francorchamps', time: '15m ago' },
  { name: 'A coaching academy', action: 'signed up for Racer plan', track: '', time: '18m ago' },
];

export function SocialProofPopup() {
  const [current, setCurrent] = useState<number | null>(null);
  const [visible, setVisible] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout>>();

  const showNext = useCallback(() => {
    const idx = Math.floor(Math.random() * NOTIFICATIONS.length);
    setCurrent(idx);
    setVisible(true);
    clearTimeout(hideTimerRef.current);
    hideTimerRef.current = setTimeout(() => setVisible(false), 4000);
  }, []);

  useEffect(() => {
    // First popup after 8 seconds, then every 30 seconds
    const initial = setTimeout(showNext, 8000);
    const interval = setInterval(showNext, 30000);
    return () => { clearTimeout(initial); clearInterval(interval); clearTimeout(hideTimerRef.current); };
  }, [showNext]);

  if (current === null) return null;
  const notif = NOTIFICATIONS[current];

  return (
    <div
      className={`fixed bottom-4 left-4 z-40 max-w-xs bg-concrete border border-steel/20 rounded-lg p-3 shadow-xl transition-all duration-500 ${
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 pointer-events-none'
      }`}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-full bg-acid-green/20 text-acid-green flex items-center justify-center shrink-0 text-xs font-monument">
          &#10003;
        </div>
        <div className="min-w-0">
          <p className="text-chalk text-sm font-body leading-snug">
            <span className="font-semibold">{notif.name}</span>{' '}
            {notif.action}
          </p>
          {notif.track && (
            <p className="text-steel/60 text-[11px] font-telemetry mt-0.5">{notif.track}</p>
          )}
          <p className="text-steel/40 text-[10px] font-telemetry mt-0.5">{notif.time}</p>
        </div>
        <button
          type="button"
          onClick={() => setVisible(false)}
          className="text-steel/30 hover:text-steel text-xs shrink-0 ml-1"
          aria-label="Dismiss notification"
        >
          &times;
        </button>
      </div>
    </div>
  );
}
