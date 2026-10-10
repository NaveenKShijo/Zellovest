'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { DEMO_EMAIL, DEMO_PASSWORD } from '@/lib/auth';

/**
 * Login page: custom email/password sign-in (invite-only onboarding —
 * there is no public signup; members join via an invite link).
 *
 * Flows:
 * - Member: POST /api/v1/auth/login → JWT + profile → AuthContext
 *   persists the session → route to `/`. Errors render inline (401 shows
 *   the backend's enumeration-safe "Invalid email or password.").
 * - Visitor: "Explore the live demo" signs in with the public demo
 *   account (seeded server-side via scripts/seed_user.py --demo), which
 *   lands on the same mock-data frontend — no integrations needed.
 */
export default function LoginPage() {
  const router = useRouter();
  const { login, isLoggingIn, error } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = await login(email.trim(), password);
    if (ok) router.replace('/');
  };

  const onDemo = async () => {
    const ok = await login(DEMO_EMAIL, DEMO_PASSWORD);
    if (ok) router.replace('/');
  };

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
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: '24px' }}>
          Sign in with your procurement account to continue.
        </p>

        {error && (
          <div
            role="alert"
            style={{
              textAlign: 'left',
              backgroundColor: 'var(--color-danger-subtle)',
              border: '1px solid var(--color-danger-border)',
              borderRadius: 'var(--radius-sm)',
              padding: '12px 14px',
              marginBottom: '20px',
              fontSize: '12.5px',
              fontWeight: 600,
              color: 'var(--color-danger)',
              lineHeight: 1.45,
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px', textAlign: 'left' }}>
          <label style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>
            Work email
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              style={{
                marginTop: '6px',
                width: '100%',
                padding: '11px 12px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                fontSize: '14px',
              }}
            />
          </label>
          <label style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>
            Password
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              style={{
                marginTop: '6px',
                width: '100%',
                padding: '11px 12px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                fontSize: '14px',
              }}
            />
          </label>
          <button
            type="submit"
            disabled={isLoggingIn}
            style={{
              marginTop: '8px',
              width: '100%',
              padding: '13px 16px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--color-brand)',
              color: '#FFFFFF',
              fontSize: '14px',
              fontWeight: 700,
              opacity: isLoggingIn ? 0.7 : 1,
              cursor: isLoggingIn ? 'wait' : 'pointer',
            }}
          >
            {isLoggingIn ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '20px' }}>
          <span style={{ flex: 1, height: '1px', backgroundColor: 'var(--border-subtle)' }} />
          <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            or
          </span>
          <span style={{ flex: 1, height: '1px', backgroundColor: 'var(--border-subtle)' }} />
        </div>

        <button
          onClick={onDemo}
          disabled={isLoggingIn}
          style={{
            marginTop: '14px',
            width: '100%',
            padding: '13px 16px',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'transparent',
            border: '1px solid var(--border-subtle)',
            color: 'var(--text-primary)',
            fontSize: '14px',
            fontWeight: 700,
            opacity: isLoggingIn ? 0.7 : 1,
            cursor: isLoggingIn ? 'wait' : 'pointer',
          }}
        >
          {isLoggingIn ? 'Signing in…' : 'Explore the live demo'}
        </button>

        <p style={{ marginTop: '18px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
          New to the team? Ask a member for an invite link.
        </p>

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
          Protected by local authentication · Authorized procurement team members only.
        </p>
      </div>
    </div>
  );
}
