'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useAsgardeo } from '@asgardeo/nextjs';

/**
 * Login page: standalone sign-in screen (no app sidebar/header — see ShellGate).
 *
 * Zellovest uses a single enterprise identity provider, so this page
 * redirects straight to the Asgardeo hosted sign-in instead of asking the
 * user to click through. The card below is the fallback: it shows while
 * the redirect is prepared, and stays (with a plain "Sign in" button) if
 * the automatic redirect fails, is blocked, or the previous attempt was
 * cancelled — the session flag prevents an endless redirect loop.
 */

const SIGN_IN_TIMEOUT_MS = 25000;
const ATTEMPT_KEY = 'zellovest_sso_attempted';

export default function LoginPage() {
  const { signIn } = useAsgardeo();
  const [isRedirecting, setIsRedirecting] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const autoAttempted = useRef(false);
  // Grace timer after the redirect is triggered: navigation away from this
  // page takes a moment (server round-trip), during which no error may show.
  const graceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (graceTimer.current) {
        clearTimeout(graceTimer.current);
      }
    };
  }, []);

  const startSignIn = async () => {
    setError(null);
    if (!signIn) {
      setError('Authentication service is not ready. Please refresh the page and try again.');
      setIsRedirecting(false);
      return;
    }
    setIsRedirecting(true);
    try {
      await Promise.race([
        signIn({}),
        new Promise<never>((_, reject) =>
          setTimeout(
            () =>
              reject(
                new Error(
                  'Could not reach the sign-in service. Check your connection and try again.'
                )
              ),
            SIGN_IN_TIMEOUT_MS
          )
        ),
      ]);
      // The redirect was triggered; the browser needs a moment to unload.
      // Only if we are STILL here after the grace window did it not happen.
      await new Promise((resolve) => {
        graceTimer.current = setTimeout(resolve, 6000);
      });
      setIsRedirecting(false);
      setError('Sign-in did not start. Please try again.');
    } catch (err) {
      setIsRedirecting(false);
      setError(err instanceof Error ? err.message : 'Sign-in failed. Please try again.');
    } finally {
      try {
        sessionStorage.removeItem(ATTEMPT_KEY);
      } catch {
        // Storage unavailable: nothing to clean up.
      }
    }
  };

  useEffect(() => {
    if (autoAttempted.current) return;
    autoAttempted.current = true;

    // A previous automatic attempt already bounced back (cancelled/failed
    // at the identity provider) — do NOT loop; let the user click instead.
    try {
      if (sessionStorage.getItem(ATTEMPT_KEY)) {
        sessionStorage.removeItem(ATTEMPT_KEY);
        setIsRedirecting(false);
        return;
      }
      sessionStorage.setItem(ATTEMPT_KEY, '1');
    } catch {
      // Storage unavailable: proceed with the redirect anyway.
    }

    void startSignIn();
    // startSignIn is stable for this mount; run once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      style={{
        minHeight: '100vh',
        width: '100vw',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'var(--bg-app)',
        padding: '24px',
      }}
    >
      {/* Decorative background wash */}
      <div
        aria-hidden="true"
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 0,
          background:
            'radial-gradient(ellipse 60% 50% at 15% 20%, rgba(113, 9, 30, 0.10), transparent), radial-gradient(ellipse 50% 60% at 85% 85%, rgba(215, 114, 134, 0.14), transparent)',
          pointerEvents: 'none',
        }}
      />

      <div
        style={{
          position: 'relative',
          zIndex: 1,
          width: '100%',
          maxWidth: '420px',
          backgroundColor: 'var(--bg-surface)',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border-subtle)',
          boxShadow: 'var(--shadow-lg)',
          padding: '40px 36px 32px 36px',
          textAlign: 'center',
        }}
      >
        {/* Brand mark */}
        <div
          style={{
            width: '56px',
            height: '56px',
            margin: '0 auto 20px auto',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'var(--color-brand)',
            color: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 800,
            fontSize: '26px',
            letterSpacing: '-1px',
          }}
        >
          Z
        </div>

        <h1
          style={{
            fontSize: '22px',
            fontWeight: 800,
            color: 'var(--text-primary)',
            letterSpacing: '-0.4px',
            marginBottom: '6px',
          }}
        >
          Welcome to Zellovest
        </h1>
        <p
          style={{
            fontSize: '13px',
            color: 'var(--text-secondary)',
            lineHeight: 1.5,
            marginBottom: '28px',
          }}
        >
          {isRedirecting && !error
            ? 'Taking you to your organization’s secure sign-in…'
            : 'Sign in with your organization account to continue.'}
        </p>

        {error && (
          <div
            role="alert"
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '10px',
              textAlign: 'left',
              backgroundColor: 'var(--color-danger-subtle)',
              border: '1px solid var(--color-danger-border)',
              borderRadius: 'var(--radius-sm)',
              padding: '12px 14px',
              marginBottom: '20px',
            }}
          >
            <div style={{ flex: 1 }}>
              <div
                style={{
                  fontSize: '12.5px',
                  fontWeight: 600,
                  color: 'var(--color-danger)',
                  lineHeight: 1.45,
                }}
              >
                {error}
              </div>
              <button
                onClick={() => setError(null)}
                style={{
                  marginTop: '6px',
                  fontSize: '11.5px',
                  fontWeight: 600,
                  color: 'var(--color-danger)',
                  textDecoration: 'underline',
                }}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {isRedirecting && !error ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '10px',
              padding: '13px 16px',
            }}
          >
            <span
              aria-hidden="true"
              style={{
                width: '16px',
                height: '16px',
                border: '2px solid var(--border-tint)',
                borderTopColor: 'var(--color-brand)',
                borderRadius: 'var(--radius-full)',
                display: 'inline-block',
                animation: 'loginSpinner 0.7s linear infinite',
              }}
            />
            <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Redirecting…
            </span>
          </div>
        ) : (
          <button
            onClick={startSignIn}
            disabled={isRedirecting}
            style={{
              width: '100%',
              padding: '13px 16px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--color-brand)',
              color: '#FFFFFF',
              fontSize: '14px',
              fontWeight: 700,
              letterSpacing: '0.1px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '10px',
              opacity: isRedirecting ? 0.7 : 1,
              cursor: isRedirecting ? 'wait' : 'pointer',
            }}
          >
            {isRedirecting && (
              <span
                aria-hidden="true"
                style={{
                  width: '14px',
                  height: '14px',
                  border: '2px solid rgba(255, 255, 255, 0.35)',
                  borderTopColor: '#FFFFFF',
                  borderRadius: 'var(--radius-full)',
                  display: 'inline-block',
                  animation: 'loginSpinner 0.7s linear infinite',
                }}
              />
            )}
            {isRedirecting ? 'Redirecting…' : 'Sign in'}
          </button>
        )}

        <p
          style={{
            marginTop: '22px',
            paddingTop: '18px',
            borderTop: '1px solid var(--border-subtle)',
            fontSize: '11.5px',
            color: 'var(--text-muted)',
            lineHeight: 1.5,
          }}
        >
          Protected by single sign-on · Authorized procurement team members only.
        </p>
      </div>

      <style>{`
        @keyframes loginSpinner {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
