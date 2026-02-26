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
  available_now: 'border-acid-green text-acid-green',
  enterprise_on_request: 'border-marshal-yellow text-marshal-yellow',
  roadmap: 'border-pit-orange text-pit-orange',
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
