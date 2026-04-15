'use client';

/**
 * Two slow-drifting radial gradient blobs behind all content.
 * Creates organic depth without GPU cost (pure CSS animation).
 * Gold blob top-left, cool blob bottom-right.
 */
export function AmbientGlow() {
  return (
    <div aria-hidden="true">
      <div
        className="ambient-blob"
        style={{
          width: '50vw',
          height: '50vw',
          maxWidth: '600px',
          maxHeight: '600px',
          top: '10%',
          left: '-5%',
          background: 'radial-gradient(circle, rgba(201,168,76,0.04) 0%, transparent 70%)',
        }}
      />
      <div
        className="ambient-blob"
        style={{
          width: '40vw',
          height: '40vw',
          maxWidth: '500px',
          maxHeight: '500px',
          bottom: '15%',
          right: '-3%',
          background: 'radial-gradient(circle, rgba(139,92,246,0.03) 0%, transparent 70%)',
          animationDelay: '-12s',
          animationDuration: '30s',
        }}
      />
    </div>
  );
}
