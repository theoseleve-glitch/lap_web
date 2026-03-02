'use client';

interface MarqueeStripProps {
  items: string[];
  speed?: number;
  separator?: string;
  className?: string;
  reverse?: boolean;
}

export function MarqueeStrip({
  items,
  speed = 30,
  separator = '•',
  className = '',
  reverse = false,
}: MarqueeStripProps) {
  const text = items.join(` ${separator} `) + ` ${separator} `;

  return (
    <div
      className={`overflow-hidden whitespace-nowrap border-y border-chalk/10 py-3 ${className}`}
      aria-hidden="true"
    >
      <div
        className="inline-flex"
        style={{
          animation: `marquee-scroll ${speed}s linear infinite`,
          animationDirection: reverse ? 'reverse' : 'normal',
        }}
      >
        <span className="font-monument text-[clamp(14px,2vw,20px)] text-chalk/20 tracking-[0.08em] px-4">
          {text}
        </span>
        <span className="font-monument text-[clamp(14px,2vw,20px)] text-chalk/20 tracking-[0.08em] px-4">
          {text}
        </span>
        <span className="font-monument text-[clamp(14px,2vw,20px)] text-chalk/20 tracking-[0.08em] px-4">
          {text}
        </span>
        <span className="font-monument text-[clamp(14px,2vw,20px)] text-chalk/20 tracking-[0.08em] px-4">
          {text}
        </span>
      </div>
    </div>
  );
}
