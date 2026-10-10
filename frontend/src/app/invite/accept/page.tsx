'use client';

import React, { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { validateInviteRequest } from '@/lib/auth';
import type { InviteStatus } from '@/types';

/**
 * Invite accept page: public, shell-less (see AuthGuard/ShellGate).
 *
 * Flow: read ?token= from the URL → GET /auth/invites/validate shows
 * which email the invite was issued for → name + password form →
 * POST /auth/invites/accept creates the account, burns the token, and
 * returns a JWT session → route to `/`. Invalid/used/expired links all
 * render the same message (the backend is enumeration-safe by design).
 */
function AcceptInviteForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { acceptInvite, isLoggingIn, error } = useAuth();
  const token = searchParams.get('token') || '';

  const [status, setStatus] = useState<'checking' | 'ready' | 'invalid'>('checking');
  const [invite, setInvite] = useState<InviteStatus | null>(null);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');

  useEffect(() => {
    if (!token) {
      setStatus('invalid');
      return;
    }
    let cancelled = false;
    validateInviteRequest(token)
      .then((data) => {
        if (!cancelled) {
          setInvite(data);
          setStatus('ready');
        }
      })
      .catch(() => {
        if (!cancelled) setStatus('invalid');
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = await acceptInvite(token, name.trim(), password);
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
        style={{
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
        <h1 style={{ fontSize: '22px', fontWeight: 800, color: 'var(--text-primary)', marginBottom: '6px' }}>
          Join your team on Zellovest
        </h1>

        {status === 'checking' && (
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '12px' }}>
            Checking your invite…
          </p>
        )}

        {status === 'invalid' && (
          <div
            role="alert"
            style={{
              marginTop: '16px',
              backgroundColor: 'var(--color-danger-subtle)',
              border: '1px solid var(--color-danger-border)',
              borderRadius: 'var(--radius-sm)',
              padding: '12px 14px',
              fontSize: '12.5px',
              fontWeight: 600,
              color: 'var(--color-danger)',
            }}
          >
            This invite link is invalid or expired. Ask a teammate for a fresh invite.
          </div>
        )}

        {status === 'ready' && invite && (
          <>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '24px' }}>
              Invited as <strong>{invite.email}</strong> — choose your name and password.
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
                }}
              >
                {error}
              </div>
            )}

            <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px', textAlign: 'left' }}>
              <label style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>
                Full name
                <input
                  type="text"
                  required
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Ada Lovelace"
                  style={{ marginTop: '6px', width: '100%', padding: '11px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: '14px' }}
                />
              </label>
              <label style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>
                Password (min 8 characters)
                <input
                  type="password"
                  required
                  minLength={8}
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  style={{ marginTop: '6px', width: '100%', padding: '11px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: '14px' }}
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
                {isLoggingIn ? 'Creating account…' : 'Accept invite & sign in'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}

export default function InviteAcceptPage() {
  return (
    <Suspense>
      <AcceptInviteForm />
    </Suspense>
  );
}
