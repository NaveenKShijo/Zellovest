'use client';

import React, { useEffect, useState } from 'react';
import { useAsgardeo } from '@asgardeo/nextjs';

/**
 * Shared Asgardeo (@asgardeo/nextjs) session UI helpers.
 *
 * The SDK owns tokens server-side (httpOnly session cookie) — nothing is
 * stored in localStorage by hand. Identity for display comes from two
 * SDK-backed sources: the context `user` (SCIM profile, may be sparse)
 * and `/api/me` (OIDC UserInfo claims for the session access token).
 */

/** Single-tenant organization display name (public branding, safe for the client). */
export const ORGANIZATION_NAME = process.env.NEXT_PUBLIC_ORGANIZATION_NAME || 'Zellovest';

/** Spinner shown while the SDK is resolving the authentication session. */
export function AsgardeoLoadingIndicator({ label = 'Checking sign-in status…' }: { label?: string }) {
    return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            <span
                aria-hidden="true"
                style={{
                    width: '14px',
                    height: '14px',
                    border: '2px solid var(--border-tint)',
                    borderTopColor: 'var(--color-brand)',
                    borderRadius: 'var(--radius-full)',
                    display: 'inline-block',
                    animation: 'asgardeoSpinner 0.7s linear infinite',
                }}
            />
            <span style={{ fontSize: '12.5px', color: 'var(--text-secondary)' }}>{label}</span>
            <style>{`
        @keyframes asgardeoSpinner {
          to { transform: rotate(360deg); }
        }
      `}</style>
        </span>
    );
}

/** Non-empty trimmed string, or ''. */
function str(v: unknown): string {
    return typeof v === 'string' && v.trim() ? v : '';
}

/** True for UUID-shaped identifiers — never human-friendly display names. */
function isUuid(value: string): boolean {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

/** Nested SCIM `name` object ({ formatted, givenName, familyName }). */
function scimName(record: Record<string, unknown>): string {
    const name = record.name;
    if (typeof name === 'string' && name.trim()) return name;
    if (name && typeof name === 'object') {
        const nested = name as Record<string, unknown>;
        return (
            str(nested.formatted) ||
            [str(nested.givenName), str(nested.familyName)].filter(Boolean).join(' ')
        );
    }
    return '';
}

/** First value of a SCIM multi-valued `emails` array ([{ value }]). */
function scimEmail(record: Record<string, unknown>): string {
    if (str(record.email)) return str(record.email);
    const emails = record.emails;
    if (Array.isArray(emails)) {
        for (const entry of emails) {
            if (typeof entry === 'string' && entry.trim()) return entry;
            if (entry && typeof entry === 'object') {
                const value = str((entry as Record<string, unknown>).value);
                if (value) return value;
            }
        }
    }
    return '';
}

/** Best-effort display name across SCIM-profile and OIDC-claim shapes. */
function resolveDisplayName(record: Record<string, unknown>): string {
    const sub = str(record.sub);
    return (
        str(record.displayName) ||
        scimName(record) ||
        [str(record.given_name), str(record.family_name)].filter(Boolean).join(' ') ||
        [str(record.givenName), str(record.familyName)].filter(Boolean).join(' ') ||
        str(record.userName) ||
        str(record.preferred_username) ||
        scimEmail(record) ||
        // A bare UUID sub identifies the user but is never shown as a name.
        (sub && !isUuid(sub) ? sub : '') ||
        ''
    );
}

/** Best-effort email across SCIM-profile and OIDC-claim shapes. */
function resolveEmail(record: Record<string, unknown>): string {
    return scimEmail(record) || str(record.preferred_username) || '';
}

/** Identity served by our `/api/me` route (OIDC UserInfo claims). */
export interface SessionIdentity {
    sub: string | null;
    username: string | null;
    givenName: string | null;
    familyName: string | null;
    name: string | null;
    email: string | null;
}

/**
 * Session identity from `/api/me` (verified SDK session cookie +
 * OIDC UserInfo). Returns null when signed out or unreachable — callers
 * fall back to other sources instead of showing placeholders.
 */
export function useSessionIdentity() {
    const { isSignedIn } = useAsgardeo();
    const [identity, setIdentity] = useState<SessionIdentity | null>(null);
    const [isLoadingIdentity, setIsLoadingIdentity] = useState(false);

    useEffect(() => {
        let cancelled = false;
        if (!isSignedIn) {
            setIdentity(null);
            return;
        }
        setIsLoadingIdentity(true);
        fetch('/api/me', { cache: 'no-store' })
            .then((res) => (res.ok ? (res.json() as Promise<SessionIdentity>) : null))
            .then((data) => {
                if (!cancelled) setIdentity(data);
            })
            .catch(() => {
                if (!cancelled) setIdentity(null);
            })
            .finally(() => {
                if (!cancelled) setIsLoadingIdentity(false);
            });
        return () => {
            cancelled = true;
        };
    }, [isSignedIn]);

    return { identity, isLoadingIdentity };
}

/**
 * Merged display identity for the header/sidebar: SCIM profile fields
 * first, `/api/me` (UserInfo) claims second, legacy local session third.
 * `name` is null (never a placeholder) when nothing real is known.
 */
export function useDisplayIdentity() {
    const { isLoading, isSignedIn, user: sdkUser } = useAsgardeo();
    const { identity, isLoadingIdentity } = useSessionIdentity();

    if (isLoading || (isSignedIn && isLoadingIdentity && !identity)) {
        return { name: null as string | null, email: '', isLoadingIdentity: true };
    }
    if (!isSignedIn) {
        return { name: null as string | null, email: '', isLoadingIdentity: false };
    }

    const profile = ((sdkUser ?? {}) as unknown) as Record<string, unknown>;
    const session: Record<string, unknown> = {
        ...(identity
            ? {
                  displayName: identity.name,
                  email: identity.email,
                  familyName: identity.familyName,
                  givenName: identity.givenName,
                  preferred_username: identity.username,
                  sub: identity.sub,
                  userName: identity.username,
              }
            : {}),
    };
    // SCIM profile wins where populated; session claims fill the gaps.
    const record: Record<string, unknown> = { ...session };
    for (const [key, value] of Object.entries(profile)) {
        if (typeof value === 'string' ? value.trim() : value !== undefined) {
            record[key] = value;
        }
    }

    const name = resolveDisplayName(record);
    return {
        name: name || null,
        email: resolveEmail(record),
        isLoadingIdentity: false,
    };
}

/**
 * Authenticated user's name/email block for light surfaces (header menu).
 * Renders `signedOutFallback` when signed out; renders nothing rather
 * than a placeholder when signed in but identity is still resolving —
 * callers overlay the loading indicator separately if desired.
 */
export function AsgardeoUserInfo({
    signedOutFallback,
    loadingLabel = 'Signing in…',
}: {
    signedOutFallback?: React.ReactNode;
    loadingLabel?: string;
}) {
    const { isLoading, isSignedIn } = useAsgardeo();
    const { name, email, isLoadingIdentity } = useDisplayIdentity();

    if (isLoading || (isSignedIn && isLoadingIdentity)) {
        return <AsgardeoLoadingIndicator label={loadingLabel} />;
    }
    if (!isSignedIn) {
        return <>{signedOutFallback ?? null}</>;
    }
    // Signed in but the provider released no human-readable name claims
    // (e.g. empty user profile in the console) — show the role, never a
    // raw UUID or demo placeholder.
    if (!name) {
        return (
            <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    Team Member
                </span>
            </span>
        );
    }
    return (
        <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.35 }}>
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>{name}</span>
            {email ? (
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{email}</span>
            ) : null}
        </span>
    );
}
