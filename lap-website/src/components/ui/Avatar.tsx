interface AvatarProps {
  name?: string | null;
  src?: string | null;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const SIZE_MAP = {
  sm: 'w-6 h-6 text-[10px]',
  md: 'w-8 h-8 text-xs',
  lg: 'w-10 h-10 text-sm',
};

const PALETTE = [
  'bg-pit-orange/20 text-pit-orange',
  'bg-acid-green/20 text-acid-green',
  'bg-racing-purple/20 text-racing-purple',
  'bg-marshal-yellow/20 text-marshal-yellow',
  'bg-safety-red/20 text-safety-red',
];

function hashCode(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

export function Avatar({ name, src, size = 'md', className = '' }: AvatarProps) {
  const sizeClass = SIZE_MAP[size];

  if (src) {
    return (
      <img
        src={src}
        alt={name || 'User avatar'}
        className={`${sizeClass} rounded-full object-cover ${className}`}
      />
    );
  }

  const displayName = name || '?';
  const colorClass = PALETTE[hashCode(displayName) % PALETTE.length];
  const initials = displayName === '?' ? '?' : getInitials(displayName);

  return (
    <span
      className={`${sizeClass} ${colorClass} rounded-full inline-flex items-center justify-center font-telemetry font-bold shrink-0 ${className}`}
      aria-label={name || 'Unknown user'}
      role="img"
    >
      {initials}
    </span>
  );
}
