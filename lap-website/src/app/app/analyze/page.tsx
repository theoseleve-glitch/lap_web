'use client';

import { redirect } from 'next/navigation';

/**
 * /app/analyze redirects to /app/sessions/upload
 *
 * The working upload page with synchronous analysis is at
 * /app/sessions/upload. This redirect ensures any links or
 * bookmarks to /app/analyze still work.
 */
export default function AnalyzePage() {
  redirect('/app/sessions/upload');
}
