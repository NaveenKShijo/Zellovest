'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { requestPasswordReset } from '@/lib/auth';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError('');
    try {
      await requestPasswordReset(email.trim());
      setMessage('If an active account exists for that email, a reset link has been sent.');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not send a reset link.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg-app)', padding: 24 }}>
      <section style={{ width: '100%', maxWidth: 420, padding: '36px', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-lg)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)' }}>Reset your password</h1>
        <p style={{ margin: '8px 0 22px', fontSize: 13, color: 'var(--text-secondary)' }}>Enter your work email and we’ll send a secure reset link.</p>
        {message ? (
          <p role="status" style={{ fontSize: 13, color: 'var(--text-primary)' }}>{message}</p>
        ) : (
          <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
              Work email
              <input type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} style={{ display: 'block', marginTop: 6, width: '100%', padding: 11, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: 14 }} />
            </label>
            {error && <p role="alert" style={{ color: 'var(--color-danger)', fontSize: 12 }}>{error}</p>}
            <button type="submit" disabled={isSubmitting} style={{ padding: 12, borderRadius: 'var(--radius-md)', background: 'var(--color-brand)', color: '#fff', fontWeight: 700 }}>{isSubmitting ? 'Sending…' : 'Send reset link'}</button>
          </form>
        )}
        <p style={{ marginTop: 20, fontSize: 13 }}><Link href="/login" style={{ color: 'var(--color-brand)', fontWeight: 600 }}>Back to sign in</Link></p>
      </section>
    </main>
  );
}
