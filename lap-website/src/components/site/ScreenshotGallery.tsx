'use client';

import { useState } from 'react';

interface ScreenshotItem {
  title: string;
  description: string;
  src: string;
}

interface ScreenshotGalleryProps {
  items: ScreenshotItem[];
  accentColor?: string;
}

export function ScreenshotGallery({ items, accentColor = 'var(--color-acid-green)' }: ScreenshotGalleryProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [lightboxOpen, setLightboxOpen] = useState(false);

  if (items.length === 0) return null;
  const active = items[activeIndex];

  return (
    <div className="space-y-4">
      {/* Hero screenshot */}
      <button
        type="button"
        className="relative w-full border border-steel/20 bg-concrete/30 overflow-hidden cursor-zoom-in"
        onClick={() => setLightboxOpen(true)}
      >
        <img
          src={active.src}
          alt={active.title}
          className="w-full h-[400px] md:h-[500px] object-contain bg-asphalt"
        />
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-asphalt/90 to-transparent p-4">
          <h3 className="font-monument text-lg" style={{ color: accentColor }}>{active.title}</h3>
          <p className="text-steel text-sm">{active.description}</p>
        </div>
      </button>

      {/* Thumbnail strip */}
      <div className="flex gap-2 overflow-x-auto pb-2">
        {items.map((item, i) => (
          <button
            key={item.title}
            type="button"
            className={`flex-shrink-0 border-2 transition-colors ${
              i === activeIndex ? 'border-current' : 'border-steel/20 hover:border-steel/50'
            }`}
            style={i === activeIndex ? { borderColor: accentColor } : undefined}
            onClick={() => setActiveIndex(i)}
          >
            <img
              src={item.src}
              alt={item.title}
              className="w-24 h-16 md:w-32 md:h-20 object-cover"
            />
          </button>
        ))}
      </div>

      {/* Lightbox modal */}
      {lightboxOpen && (
        <div
          className="fixed inset-0 z-[999] bg-asphalt/95 flex items-center justify-center p-4"
          onClick={() => setLightboxOpen(false)}
          role="dialog"
          aria-modal="true"
        >
          <button
            type="button"
            className="absolute top-4 right-4 text-steel hover:text-chalk text-2xl"
            onClick={() => setLightboxOpen(false)}
            aria-label="Close"
          >
            &times;
          </button>
          <img
            src={active.src}
            alt={active.title}
            className="max-w-full max-h-[90vh] object-contain"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  );
}
