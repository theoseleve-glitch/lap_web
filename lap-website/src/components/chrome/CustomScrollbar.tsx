'use client';

import { useEffect, useState } from 'react';

export function CustomScrollbar() {
  const [thumbTop, setThumbTop] = useState(0);
  const [thumbHeight, setThumbHeight] = useState(10);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let hideTimer: ReturnType<typeof setTimeout>;

    const update = () => {
      const scrollY = window.scrollY;
      const docHeight = document.documentElement.scrollHeight;
      const winHeight = window.innerHeight;
      const scrollRatio = scrollY / (docHeight - winHeight || 1);
      const thumbH = Math.max((winHeight / docHeight) * 100, 5);

      setThumbTop(scrollRatio * (100 - thumbH));
      setThumbHeight(thumbH);
      setVisible(true);

      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => setVisible(false), 1200);
    };

    window.addEventListener('scroll', update, { passive: true });
    update();

    return () => {
      window.removeEventListener('scroll', update);
      clearTimeout(hideTimer);
    };
  }, []);

  return (
    <div
      className="fixed top-0 right-0 w-[3px] h-full z-[997] pointer-events-none transition-opacity duration-500"
      style={{ opacity: visible ? 1 : 0 }}
      aria-hidden="true"
    >
      <div
        className="absolute right-0 w-full bg-gold/40 rounded-full transition-[top] duration-100 ease-out"
        style={{ top: `${thumbTop}%`, height: `${thumbHeight}%` }}
      />
    </div>
  );
}
