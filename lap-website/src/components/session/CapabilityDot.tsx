import type { ChannelTag } from '@/types/contracts';

const LABELS: Record<ChannelTag, string> = {
  gps: 'GPS',
  lat_g: 'Lat G',
  lon_g: 'Lon G',
  yaw_rate: 'Yaw rate',
  throttle: 'Throttle',
  brake: 'Brake',
  steer: 'Steer',
  wheel_spd: 'Wheel speed',
  shock_defl: 'Shock deflection',
};

export function CapabilityDots({ channels }: { channels: ChannelTag[] }) {
  if (!channels.length) return null;
  return (
    <span className="inline-flex items-center gap-1">
      {channels.map((c) => (
        <span
          key={c}
          aria-label={`channel: ${c}`}
          title={LABELS[c]}
          className="w-1.5 h-1.5 rounded-full bg-steel/50"
        />
      ))}
    </span>
  );
}
