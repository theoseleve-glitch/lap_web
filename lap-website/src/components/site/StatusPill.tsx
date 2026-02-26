import type { CapabilityStatus } from '@/data/claim-registry';

interface StatusPillProps {
  status: CapabilityStatus;
}

const labelMap: Record<CapabilityStatus, string> = {
  available_now: 'Available Now',
  enterprise_on_request: 'Enterprise / On Request',
  roadmap: 'Roadmap',
};

const classMap: Record<CapabilityStatus, string> = {
  available_now: 'border-acid-green bg-acid-green/15 text-acid-green',
  enterprise_on_request: 'border-marshal-yellow bg-marshal-yellow/18 text-marshal-yellow',
  roadmap: 'border-pit-orange bg-pit-orange/18 text-pit-orange',
};

export function StatusPill({ status }: StatusPillProps) {
  return (
    <span
      className={`inline-flex items-center border px-2 py-1 font-telemetry text-[10px] tracking-[0.12em] uppercase ${classMap[status]}`}
    >
      {labelMap[status]}
    </span>
  );
}
