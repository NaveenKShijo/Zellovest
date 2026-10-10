'use client';

/**
 * Custom-auth API client (invite-only onboarding, public signup removed).
 *
 * Learning map — what happens on the wire:
 * - login: POST JSON { email, password } → 200
 *   { access_token, expires_in_minutes, user } or 401 JSON detail.
 * - me: GET with `Authorization: Bearer <jwt>` → the backend verifies the
 *   HS256 signature + exp, then loads the user row.
 * - invites (member): POST /auth/invites with Bearer → 201
 *   { email, invite_token, expires_at }. The raw token is shown once;
 *   only its SHA-256 hash is stored server-side.
 * - invites (public): GET /auth/invites/validate?token=… → invited email;
 *   POST /auth/invites/accept { token, name, password } → AuthResponse.
 *
 * Base URL: same-origin `/api/v1` (Next rewrites proxy to the ingestion
 * gateway at INGESTION_API_URL). Override with NEXT_PUBLIC_API_BASE.
 */

import type { AuthResponse, AuthUser, InviteResponse, InviteStatus } from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/api';

/** Public demo credentials (documented, low-value sandbox account). */
export const DEMO_EMAIL = process.env.NEXT_PUBLIC_DEMO_EMAIL || 'demo@zellovest.ai';
export const DEMO_PASSWORD = process.env.NEXT_PUBLIC_DEMO_PASSWORD || 'zellovest-demo';

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown; message?: unknown };
    if (typeof body.detail === 'string') return body.detail;
    if (typeof body.message === 'string') return body.message;
  } catch {
    // Non-JSON error body: fall through to the status fallback.
  }
  return `Request failed (HTTP ${response.status})`;
}

export async function loginRequest(email: string, password: string): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return (await response.json()) as AuthResponse;
}

export async function meRequest(accessToken: string): Promise<AuthUser> {
  const response = await fetch(`${API_BASE}/v1/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: 'no-store',
  });
  if (!response.ok) throw new Error(await parseError(response));
  return (await response.json()) as AuthUser;
}

export async function createInviteRequest(accessToken: string, email: string): Promise<InviteResponse> {
  const response = await fetch(`${API_BASE}/v1/auth/invites`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ email }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return (await response.json()) as InviteResponse;
}

export async function validateInviteRequest(token: string): Promise<InviteStatus> {
  const response = await fetch(`${API_BASE}/v1/auth/invites/validate?token=${encodeURIComponent(token)}`, {
    cache: 'no-store',
  });
  if (!response.ok) throw new Error(await parseError(response));
  return (await response.json()) as InviteStatus;
}

export async function acceptInviteRequest(token: string, name: string, password: string): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/v1/auth/invites/accept`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, name, password }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return (await response.json()) as AuthResponse;
}
