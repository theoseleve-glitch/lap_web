'use client';

interface AnalyzerReadoutsProps {
  speed: number;            // km/h
  gLat: number;             // G
  gLon: number;             // G
  distance: number;         // meters
  turnRadius: number | null; // meters
  gear: number | null;
}

function Readout({ label, value, unit, color }: { label: string; value: string; unit: string; color?: string }) {
  return (
    <div className="px-3 py-2.5 border-b border-steel/5">
      <div className="text-[9px] font-telemetry text-steel/50 uppercase tracking-wider mb-0.5">{label}</div>
      <div className="flex items-baseline gap-1">
        <span className={`font-telemetry text-lg tabular-nums ${color ?? 'text-chalk'}`}>{value}</span>
        <span className="text-[10px] font-telemetry text-steel/60">{unit}</span>
      </div>
    </div>
  );
}

export function AnalyzerReadouts({ speed, gLat, gLon, distance, turnRadius, gear }: AnalyzerReadoutsProps) {
  const totalG = Math.sqrt(gLat * gLat + gLon * gLon);

  return (
    <div className="h-full flex flex-col bg-concrete/50 overflow-y-auto">
      <div className="px-3 py-2 border-b border-steel/10">
        <span className="text-steel/50 font-telemetry text-[9px] uppercase tracking-wider">Live Data</span>
      </div>

      <Readout label="Speed" value={Math.round(speed).toString()} unit="km/h" />
      <Readout label="Distance" value={Math.round(distance).toString()} unit="m" />
      <Readout
        label="Lat G"
        value={gLat.toFixed(2)}
        unit="G"
        color={Math.abs(gLat) > 1.5 ? 'text-pit-orange' : undefined}
      />
      <Readout
        label="Lon G"
        value={gLon.toFixed(2)}
        unit="G"
        color={gLon < -1.0 ? 'text-safety-red' : gLon > 0.5 ? 'text-acid-green' : undefined}
      />
      <Readout
        label="Total G"
        value={totalG.toFixed(2)}
        unit="G"
        color={totalG > 2.0 ? 'text-pit-orange' : undefined}
      />
      {turnRadius !== null && (
        <Readout
          label="Turn Radius"
          value={turnRadius > 500 ? '∞' : Math.round(turnRadius).toString()}
          unit="m"
        />
      )}
      {gear !== null && (
        <Readout label="Gear" value={gear.toString()} unit="" />
      )}
    </div>
  );
}
