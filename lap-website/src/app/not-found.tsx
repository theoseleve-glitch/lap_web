import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-asphalt">
      <div className="text-center">
        <h1 className="font-monument text-6xl text-chalk mb-4">404</h1>
        <p className="text-steel font-body mb-6">Page not found</p>
        <Link
          href="/"
          className="text-acid-green font-telemetry text-sm hover:underline"
        >
          Back to home
        </Link>
      </div>
    </div>
  );
}
