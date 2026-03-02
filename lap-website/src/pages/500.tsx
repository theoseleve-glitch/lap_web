export default function Custom500() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: '#0d0d0d', color: '#e0e0e0', fontFamily: 'monospace' }}>
      <div style={{ textAlign: 'center' }}>
        <h1 style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>500</h1>
        <p style={{ opacity: 0.6 }}>Server error</p>
      </div>
    </div>
  );
}
