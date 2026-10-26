'use client';

import React, { Suspense, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { resetPassword } from '@/lib/auth';

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get('token') || '';
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [complete, setComplete] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (!token) {
      setError('This reset link is invalid or expired.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    setIsSubmitting(true);
    try {
      await resetPassword(token, password);
      setComplete(true);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not reset your password.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section style={{ width: '100%', maxWidth: 420, padding: 36, background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-lg)' }}>
      <h1 style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)' }}>Choose a new password</h1>
      {complete ? (
        <p role="status" style={{ marginTop: 12, fontSize: 13, color: 'var(--text-secondary)' }}>Your password has been updated. <Link href="/login" style={{ color: 'var(--color-brand)', fontWeight: 600 }}>Sign in</Link>.</p>
      ) : (
        <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 20 }}>
          <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>New password
            <input type="password" required minLength={8} maxLength={128} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} style={{ display: 'block', marginTop: 6, width: '100%', padding: 11, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: 14 }} />
          </label>
          <label style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>Confirm password
            <input type="password" required minLength={8} maxLength={128} autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} style={{ display: 'block', marginTop: 6, width: '100%', padding: 11, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: 14 }} />
          </label>
          {error && <p role="alert" style={{ color: 'var(--color-danger)', fontSize: 12 }}>{error}</p>}
          <button type="submit" disabled={isSubmitting} style={{ padding: 12, borderRadius: 'var(--radius-md)', background: 'var(--color-brand)', color: '#fff', fontWeight: 700 }}>{isSubmitting ? 'Updating…' : 'Update password'}</button>
        </form>
      )}
    </section>
  );
}

export default function ResetPasswordPage() {
  return <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg-app)', padding: 24 }}><Suspense><ResetPasswordForm /></Suspense></main>;
}
