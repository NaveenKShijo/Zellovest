import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { jwtVerify } from 'jose';

/**
 * GET /api/me — identity of the currently signed-in user.
 *
 * Verifies the SDK's httpOnly session cookie (HS256, ASGARDEO_SECRET),
 * then reads authoritative OIDC claims from the UserInfo endpoint with
 * the session's access token. Only non-sensitive display claims are
 * returned — tokens never leave the server.
 *
 * 200 { sub, username, givenName, familyName, name, email } (fields may
 *     be null when the provider does not release them; `sub` alone is
 *     returned when UserInfo is unreachable).
 * 401 when there is no usable session.
 */

export const dynamic = 'force-dynamic';

/** Must match the SDK's CookieConfig.SESSION_COOKIE_NAME (`__<prefix>__session`). */
const SESSION_COOKIE_NAME = '__asgardeo__session';

function getSecret(): Uint8Array {
    const secret = process.env.ASGARDEO_SECRET;
    if (!secret) {
        throw new Error('ASGARDEO_SECRET is not configured');
    }
    return new TextEncoder().encode(secret);
}

export async function GET() {
    try {
        const sessionToken = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
        if (!sessionToken) {
            return NextResponse.json({ error: 'Not signed in' }, { status: 401 });
        }

        const { payload } = await jwtVerify(sessionToken, getSecret());
        if (payload['type'] !== 'session') {
            return NextResponse.json({ error: 'Not signed in' }, { status: 401 });
        }

        const accessToken = payload['accessToken'];
        const baseUrl = (process.env.NEXT_PUBLIC_ASGARDEO_BASE_URL || '').replace(/\/+$/, '');
        if (typeof accessToken !== 'string' || !accessToken || !baseUrl) {
            return NextResponse.json({ sub: (payload['sub'] as string) ?? null });
        }

        const userInfo = await fetch(`${baseUrl}/oauth2/userinfo`, {
            headers: { Authorization: `Bearer ${accessToken}` },
            cache: 'no-store',
        });
        if (!userInfo.ok) {
            return NextResponse.json({ sub: (payload['sub'] as string) ?? null });
        }

        const claims = (await userInfo.json()) as Record<string, unknown>;
        const text = (value: unknown): string | null =>
            typeof value === 'string' && value.trim() ? value : null;

        return NextResponse.json({
            sub: text(claims['sub']) ?? (payload['sub'] as string) ?? null,
            username: text(claims['preferred_username']) ?? text(claims['userName']),
            givenName: text(claims['given_name']),
            familyName: text(claims['family_name']),
            name: text(claims['name']),
            email: text(claims['email']),
        });
    } catch {
        return NextResponse.json({ error: 'Not signed in' }, { status: 401 });
    }
}
