'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { buildAuthorizeUrl } from '@/lib/oidc';

/**
 * OIDC callback page — the "Authorized Redirect URL" registered in WSO2.
 *
 * WSO2 redirects here after authentication with ?code=...&state=... (or
 * ?error=...&error_description=... on failure). This component:
 *   1. Validates the CSRF `state` against the one generated at /login
 *      (done inside completeLogin, single-use).
 *   2. Exchanges the authorization code for tokens (PKCE verifier).
 *   3. Builds the UserSession from ID token claims and routes to the app.
 *
 * On state mismatch / missing code it retries the login once via silent
 * redirect (guards against back-button replays and stale tabs); repeated
 * failures land back on /login with a banner error.
 */

/** Special state value set by logout; SSO session is gone, just reset UI. */
function isPostLogoutState(state: string | null): boolean {
  return state === 'logout';
}

export default function AuthCallbackPage() {
  const router = useRouter();
  const { completeLogin, error } = useAuth();
  const [status, setStatus] = useState<'processing' | 'retrying' | 'failed'>('processing');
  const hasRun = useRef(false);

  useEffect(() => {
    // Guard against StrictMode dev double-invoke and back/forward replays:
    // the code and state are single-use, so this effect must run exactly once.
    if (hasRun.current) return;
    hasRun.current = true;

    // Read the response straight from the URL: navigating away/back or a
    // rerender must not re-read already-consumed parameters.
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    const oauthError = params.get('error');

    // Strip code/state from the address bar (single-use credentials should
    // not linger in history or be re-submitted on refresh).
    try {
      window.history.replaceState(null, '', window.location.pathname);
    } catch {
      // History manipulation is best-effort; flow continues regardless.
    }

    const redirectToLogin = async (retryAuthorize: boolean) => {
      if (retryAuthorize) {
        // One silent retry: rebuild a fresh state/PKCE pair and bounce to WSO2.
        try {
          setStatus('retrying');
          const authorizeUrl = await buildAuthorizeUrl();
          window.location.assign(authorizeUrl);
          return;
        } catch {
          // Config missing: fall through to the plain login page.
        }
      }
      setStatus('failed');
      router.replace('/login');
    };

    const run = async () => {
      // Post-logout return: no session expected; reset to the login screen.
      if (!code && isPostLogoutState(state)) {
        await redirectToLogin(false);
        return;
      }

      if (oauthError) {
        // e.g. access_denied, invalid_session — no silent retry makes sense.
        await redirectToLogin(false);
        return;
      }

      if (!code) {
        // Direct visit with no code: attempt one silent re-authorize, else /login.
        await redirectToLogin(true);
        return;
      }

      // completeLogin validates + consumes the state, then exchanges the code.
      const ok = await completeLogin(code, state);
      if (ok) {
        router.replace('/');
      } else {
        await redirectToLogin(false);
      }
    };

    void run();
    // completeLogin is consumed imperatively; `error` is read during render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      style={{
        minHeight: '100vh',
        width: '100vw',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'var(--bg-app)',
        gap: '18px',
        padding: '24px',
      }}
    >
      {status !== 'failed' ? (
        <span
          aria-hidden="true"
          style={{
            width: '34px',
            height: '34px',
            border: '3px solid var(--border-tint)',
            borderTopColor: 'var(--color-brand)',
            borderRadius: 'var(--radius-full)',
            display: 'inline-block',
            animation: 'callbackSpinner 0.8s linear infinite',
          }}
        />
      ) : (
        <div
          aria-hidden="true"
          style={{
            width: '44px',
            height: '44px',
            borderRadius: 'var(--radius-full)',
            backgroundColor: 'var(--color-danger-subtle)',
            border: '1px solid var(--color-danger-border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--color-danger)" strokeWidth="2" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </div>
      )}

      <div style={{ textAlign: 'center' }}>
        <div
          style={{
            fontSize: '14px',
            fontWeight: 700,
            color: 'var(--text-primary)',
            marginBottom: '4px',
          }}
        >
          {status !== 'failed'
            ? status === 'retrying'
              ? 'Starting sign-in…'
              : 'Completing sign-in…'
            : 'Sign-in failed'}
        </div>
        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          {status !== 'failed'
            ? 'Validating your WSO2 session and establishing secure access.'
            : error || 'Authentication could not be completed. Redirecting to the login page…'}
        </div>
      </div>

      <style>{`
        @keyframes callbackSpinner {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
