import { NextResponse } from 'next/server';
import { sendServerConversion } from '@/lib/server-conversions';

interface ConversionBody {
  event: string;
  sourcePath?: string;
  leadType?: string;
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as ConversionBody | null;

  if (!body?.event || typeof body.event !== 'string') {
    return NextResponse.json(
      {
        ok: false,
        message: 'Missing required event name.',
      },
      { status: 400 },
    );
  }

  await sendServerConversion({
    event: body.event,
    sourcePath: body.sourcePath,
    leadType: body.leadType,
  });

  return NextResponse.json({ ok: true, message: 'Conversion accepted.' });
}
