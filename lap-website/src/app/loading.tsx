export default function Loading() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-asphalt">
      <div className="flex flex-col items-center gap-4">
        <div className="w-10 h-10 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        <p className="font-telemetry text-steel text-[11px] uppercase tracking-wider">Loading</p>
      </div>
    </div>
  );
}
