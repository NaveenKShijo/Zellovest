import { randomUUID } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';

const AGENTIC_API_URL = process.env.AGENTIC_API_URL || 'http://localhost:8002';
const ROUTE_PREFIX = '/api/agentic';

/** Forward an authenticated browser request to the agentic FastAPI service. */
async function proxyToAgentic(request: NextRequest): Promise<NextResponse> {
  const headers = new Headers();
  for (const name of ['authorization', 'content-type', 'accept', 'x-request-id']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const requestId = headers.get('x-request-id') || randomUUID();
  headers.set('x-request-id', requestId);

  try {
    const servicePath = request.nextUrl.pathname.slice(ROUTE_PREFIX.length);
    const target = new URL(`/api/v1${servicePath}`, AGENTIC_API_URL);
    target.search = request.nextUrl.search;
    const body = ['GET', 'HEAD'].includes(request.method)
      ? undefined
      : await request.arrayBuffer();
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: 'no-store',
      redirect: 'manual',
    });

    const responseHeaders = new Headers();
    for (const name of ['content-type', 'cache-control', 'x-request-id']) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error('agentic_proxy_upstream_unavailable', {
      errorClass: error instanceof Error ? error.name : 'UnknownError',
    });
    return NextResponse.json(
      {
        detail:
          'Agentic FastAPI service is unreachable. Start agentic-reasoning and check AGENTIC_API_URL.',
      },
      { status: 502, headers: { 'x-request-id': requestId } },
    );
  }
}

export const GET = proxyToAgentic;
export const POST = proxyToAgentic;
