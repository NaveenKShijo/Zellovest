'use client';

import React, { useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { createInviteRequest } from '@/lib/auth';

export default function SettingsPage() {
  const { user } = useAuth();
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [isInviting, setIsInviting] = useState(false);
  const [copied, setCopied] = useState(false);

  const onInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user?.accessToken) return;
    setIsInviting(true);
    setInviteError(null);
    setInviteLink(null);
    setCopied(false);
    try {
      const data = await createInviteRequest(user.accessToken, inviteEmail.trim());
      // The raw token is shown exactly once — only its hash is stored.
      setInviteLink(`${window.location.origin}/invite/accept?token=${data.invite_token}`);
      setInviteEmail('');
    } catch (err) {
      setInviteError(err instanceof Error ? err.message : 'Could not create the invite.');
    } finally {
      setIsInviting(false);
    }
  };

  const onCopy = async () => {
    if (!inviteLink) return;
    try {
      await navigator.clipboard.writeText(inviteLink);
      setCopied(true);
    } catch {
      // Clipboard unavailable (permissions): the link stays visible for manual copy.
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Platform Settings
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
          Single-tenant deployment configuration and local authentication.
        </p>
      </div>

      <div
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border-subtle)',
          padding: '24px',
          boxShadow: 'var(--shadow-sm)',
        }}
      >
        <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '14px' }}>
          Organization Boundary
        </h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '13px' }}>
          <div><strong>Organization:</strong> {user?.organizationName}</div>
          <div><strong>Role:</strong> {user?.role}</div>
          <div><strong>Department:</strong> {user?.department}</div>
          <div><strong>Identity Provider:</strong> Local authentication (email + password, PBKDF2 + JWT)</div>
        </div>
      </div>

      <div
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border-subtle)',
          padding: '24px',
          boxShadow: 'var(--shadow-sm)',
        }}
      >
        <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '6px' }}>
          Invite a teammate
        </h2>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '16px' }}>
          There is no public signup — new members join through your invite link (single-use, expires in 7 days).
        </p>

        <form onSubmit={onInvite} style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <input
            type="email"
            required
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            placeholder="teammate@company.com"
            style={{ flex: '1 1 240px', padding: '11px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: '14px' }}
          />
          <button
            type="submit"
            disabled={isInviting}
            style={{
              padding: '11px 20px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--color-brand)',
              color: '#FFFFFF',
              fontSize: '14px',
              fontWeight: 700,
              opacity: isInviting ? 0.7 : 1,
              cursor: isInviting ? 'wait' : 'pointer',
            }}
          >
            {isInviting ? 'Creating…' : 'Create invite link'}
          </button>
        </form>

        {inviteError && (
          <div
            role="alert"
            style={{
              marginTop: '14px',
              backgroundColor: 'var(--color-danger-subtle)',
              border: '1px solid var(--color-danger-border)',
              borderRadius: 'var(--radius-sm)',
              padding: '12px 14px',
              fontSize: '12.5px',
              fontWeight: 600,
              color: 'var(--color-danger)',
            }}
          >
            {inviteError}
          </div>
        )}

        {inviteLink && (
          <div
            style={{
              marginTop: '14px',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              padding: '12px 14px',
              display: 'flex',
              gap: '10px',
              alignItems: 'center',
              flexWrap: 'wrap',
            }}
          >
            <code style={{ flex: '1 1 240px', fontSize: '12px', wordBreak: 'break-all', color: 'var(--text-primary)' }}>
              {inviteLink}
            </code>
            <button
              onClick={onCopy}
              style={{
                padding: '8px 16px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                fontSize: '12.5px',
                fontWeight: 700,
                color: 'var(--text-primary)',
              }}
            >
              {copied ? 'Copied!' : 'Copy link'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
