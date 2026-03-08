export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname !== '/og') {
      return new Response('Not found', { status: 404 });
    }

    const title = url.searchParams.get('title') || 'LAP';
    const eyebrow = url.searchParams.get('eyebrow') || '';

    // Placeholder SVG - replace with satori + resvg-wasm for PNG output
    const svg = `<svg width="1200" height="630" xmlns="http://www.w3.org/2000/svg">
      <rect width="1200" height="630" fill="#000"/>
      <text x="64" y="200" font-size="24" fill="#888">${escapeXml(eyebrow)}</text>
      <text x="64" y="300" font-size="64" fill="#F0EDE5" font-family="sans-serif">${escapeXml(title)}</text>
      <text x="64" y="580" font-size="20" fill="#C9A84C">LAP — Find Time.</text>
    </svg>`;

    return new Response(svg, {
      headers: {
        'Content-Type': 'image/svg+xml',
        'Cache-Control': 'public, max-age=86400, s-maxage=604800',
        'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'",
      },
    });
  },
};

function escapeXml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}
