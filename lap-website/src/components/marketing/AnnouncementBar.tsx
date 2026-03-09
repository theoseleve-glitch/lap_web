'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

interface AnnouncementBarProps {
  /** Unique key for this announcement — changing it resets dismissal */
  id: string;
  message: string;
  link?: { href: string; label: string };
}

const STORAGE_PREFIX = 'lap_dismissed_';

export function AnnouncementBar({ id, message, link }: AnnouncementBarProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const dismissed = localStorage.getItem(`${STORAGE_PREFIX}${id}`);
    if (!dismissed) setVisible(true);
  }, [id]);

  const dismiss = () => {
    setVisible(false);
    localStorage.setItem(`${STORAGE_PREFIX}${id}`, '1');
  };

  if (!visible) return null;

  return (
    <div className="bg-pit-orange/10 border-b border-pit-orange/20 px-4 py-2 text-center text-sm text-chalk relative">
      <span className="font-body">
        {message}
        {link && (
          <Link href={link.href} className="ml-2 underline underline-offset-2 text-pit-orange hover:text-chalk transition-colors">
            {link.label}
          </Link>
        )}
      </span>
      <button
        onClick={dismiss}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-steel hover:text-chalk transition-colors"
        aria-label="Dismiss announcement"
      >
        &times;
      </button>
    </div>
  );
}
