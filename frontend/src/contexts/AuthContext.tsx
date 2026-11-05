'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode, useRef } from 'react';
import { UserSession, AuthContextType, AuthResponse } from '@/types';
import {
  acceptInviteRequest,
  AuthRequestError,
  demoLoginRequest,
  loginRequest,
  refreshTokenRequest,
} from '@/lib/auth';

/**
 * AuthContext: custom email/password session (invite-only onboarding).
 *
 * Concepts for the reader:
 * - The backend owns passwords (PBKDF2 hash in `users.password_hash`).
 * - On login (or invite claim) it returns a short-lived HS256 JWT
 *   (access_token, default 60 min) plus a long-lived refresh JWT
 *   (JWT_REFRESH_EXPIRE_DAYS, default 7 days). The JWT is just a signed
 *   JSON blob: header.payload.signature — the server verifies the
 *   signature with JWT_SECRET_KEY on every call.
 * - The browser keeps the JWT + profile in localStorage (simple and
 *   visible for learning; production-hardening would move it to an
 *   httpOnly cookie to block XSS exfiltration).
 * - Single role in V1: every authenticated user is Procurement Team Member.
 * - No public signup: accounts come from the seed script (first/demo
 *   user) or from claiming an invite link.
 * - ACCESS TOKEN REFRESH: before the access token expires, the client
 *   silently swaps the refresh token for a new token pair via
 *   POST /auth/refresh. A stored session whose access token has already
 *   expired is restored from its refresh token instead of being deleted,
 *   so closing the tab overnight no longer forces another login. If a
 *   request still hits 401, the client retries once after refreshing.
 */

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const AUTH_STORAGE_KEY = 'zellovest_auth_session';
const ORGANIZATION_NAME = process.env.NEXT_PUBLIC_ORGANIZATION_NAME || 'Zellovest';

/** Start the silent refresh this many seconds before the access token expires. */
const REFRESH_LEAD_SECONDS = 60;

/**
 * Read the access-token expiry for scheduling refreshes.
 *
 * The server's JWT `exp` claim is authoritative. The response duration is
 * retained as a fallback for compatibility with older auth responses.
 */
function getAccessTokenExpiry(accessToken: string, fallbackMinutes: number): number {
  try {
    const payloadSegment = accessToken.split('.')[1];
    if (payloadSegment) {
      const normalized = payloadSegment.replace(/-/g, '+').replace(/_/g, '/');
      const payload = JSON.parse(atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '='))) as {
        exp?: unknown;
      };
      if (typeof payload.exp === 'number' && Number.isFinite(payload.exp)) {
        return payload.exp * 1000;
      }
    }
  } catch {
    // Fall back to the response lifetime for legacy/non-JWT auth responses.
  }
  return Date.now() + fallbackMinutes * 60 * 1000;
}

function toSession(data: AuthResponse): UserSession {
  return {
    id: data.user.id,
    name: data.user.name || data.user.email.split('@')[0]?.replace(/[._-]/g, ' ') || 'Procurement User',
    email: data.user.email,
    role: 'Procurement Team Member',
    department: 'Procurement & Strategic Sourcing',
    organizationName: ORGANIZATION_NAME,
    accessToken: data.access_token,
    refreshToken: data.refresh_token ?? undefined,
    expiresAt: getAccessTokenExpiry(data.access_token, data.expires_in_minutes),
    isDemo: data.user.is_demo === true,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Start unauthenticated on both server and client; the session is restored
  // after mount from localStorage (avoids SSR/client hydration mismatches).
  const [user, setUser] = useState<UserSession | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Latest session for callbacks that must not close over stale React state.
  const sessionRef = useRef<UserSession | null>(null);
  // Shared in-flight refresh so concurrent callers await one rotation.
  const refreshPromise = useRef<Promise<UserSession | null> | null>(null);

  /** Write the session to memory + localStorage (single source of truth). */
  const persistSession = useCallback((session: UserSession | null) => {
    sessionRef.current = session;
    setUser(session);
    try {
      if (session) {
        localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
      } else {
        localStorage.removeItem(AUTH_STORAGE_KEY);
      }
    } catch {
      // Storage unavailable (private mode/quota): keep the in-memory session.
    }
  }, []);

  /**
   * Silent refresh: swap the refresh token for a new access + refresh pair.
   *
   * Returns the new session (or null when refresh is impossible/failed).
   * Concurrent callers share one in-flight request, which prevents two
   * refreshes racing each other after the browser wakes from sleep.
   */
  const performRefresh = useCallback(async (): Promise<UserSession | null> => {
    const current = sessionRef.current;
    if (!current?.refreshToken) return null;
    if (refreshPromise.current) return refreshPromise.current;

    const pending = (async (): Promise<UserSession | null> => {
      try {
        const data = await refreshTokenRequest(current.refreshToken as string);
        const session = toSession(data);
        persistSession(session);
        return session;
      } catch (error) {
        // Invalid/expired refresh tokens require a new sign-in. A transient
        // network or server error should not destroy an otherwise recoverable
        // session; retry shortly and let the next API call retry immediately.
        const status = error instanceof AuthRequestError ? error.status : null;
        if (status === 401 || status === 404) {
          persistSession(null);
          setError('Your session expired. Please sign in again.');
        } else {
          setError('Unable to refresh your session. It will retry on the next request.');
        }
        return null;
      } finally {
        refreshPromise.current = null;
      }
    })();

    refreshPromise.current = pending;
    return pending;
  }, [persistSession]);

  /**
   * Get a valid access token, refreshing in place when needed.
   *
   * `forceRefresh` is used after a 401 because the server may reject a token
   * before the browser's local expiry estimate says it is due.
   */
  const getValidAccessToken = useCallback(async (forceRefresh = false): Promise<string | null> => {
    const current = sessionRef.current;
    if (!current) return null;

    const expiresAt = current.expiresAt;
    const nearExpiry =
      typeof expiresAt === 'number' && Date.now() >= expiresAt - REFRESH_LEAD_SECONDS * 1000;
    if (!forceRefresh && !nearExpiry) return current.accessToken ?? null;

    if (!current.refreshToken) {
      // Legacy sessions cannot be refreshed. Keep a still-valid token for
      // ordinary calls, but do not retry a 401 with the same credentials.
      if (forceRefresh || nearExpiry) persistSession(null);
      return forceRefresh ? null : current.accessToken ?? null;
    }

    const refreshed = await performRefresh();
    return refreshed?.accessToken ?? null;
  }, [performRefresh, persistSession]);

  useEffect(() => {
    // Deferred so hydration completes with the server-rendered default first.
    let cancelled = false;
    const timer = setTimeout(() => {
      const restore = async () => {
        try {
          const stored = localStorage.getItem(AUTH_STORAGE_KEY);
          if (!stored) return;

          const session = JSON.parse(stored) as UserSession;
          if (!session.accessToken) {
            persistSession(null);
            return;
          }

          const accessValid =
            typeof session.expiresAt !== 'number' ||
            Date.now() < session.expiresAt - REFRESH_LEAD_SECONDS * 1000;

          if (accessValid) {
            persistSession(session);
          } else if (session.refreshToken) {
            // Access token expired but the long-lived refresh token may
            // still be valid: restore the session and refresh silently.
            persistSession(session);
            await performRefresh();
          } else {
            persistSession(null);
          }
        } catch {
          // Corrupted storage: start unauthenticated rather than crashing.
          persistSession(null);
        } finally {
          if (!cancelled) setIsLoading(false);
        }
      };
      void restore();
    }, 0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [performRefresh, persistSession]);

  // ---- Background access-token refresh ----
  useEffect(() => {
    if (!user?.refreshToken || !user?.expiresAt) return;

    const delay = Math.max(0, user.expiresAt - Date.now() - REFRESH_LEAD_SECONDS * 1000);
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => {
      void performRefresh();
    }, delay);

    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [user?.refreshToken, user?.expiresAt, performRefresh]);

  // ---- Cross-tab session sync ----
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== AUTH_STORAGE_KEY) return;
      if (!event.newValue) {
        sessionRef.current = null;
        setUser(null);
        return;
      }
      try {
        const session = JSON.parse(event.newValue) as UserSession;
        sessionRef.current = session;
        setUser(session);
      } catch {
        // Ignore malformed cross-tab writes; this tab keeps its own session.
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const clearError = useCallback(() => setError(null), []);

  /** Authenticate with email + password; persists the JWT session. */
  const login = useCallback(async (email: string, password: string): Promise<boolean> => {
    setIsLoggingIn(true);
    setError(null);
    try {
      const data = await loginRequest(email, password);
      persistSession(toSession(data));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed. Please try again.');
      return false;
    } finally {
      setIsLoggingIn(false);
    }
  }, [persistSession]);

  /** One-click sandbox entry (no credentials); persists the demo JWT session. */
  const loginDemo = useCallback(async (): Promise<boolean> => {
    setIsLoggingIn(true);
    setError(null);
    try {
      const data = await demoLoginRequest();
      persistSession(toSession(data));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the demo. Please try again.');
      return false;
    } finally {
      setIsLoggingIn(false);
    }
  }, [persistSession]);

  /** Claim an invite link; creates the account and persists the JWT session. */
  const acceptInvite = useCallback(async (token: string, name: string, password: string): Promise<boolean> => {
    setIsLoggingIn(true);
    setError(null);
    try {
      const data = await acceptInviteRequest(token, name, password);
      persistSession(toSession(data));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not accept the invite. Please try again.');
      return false;
    } finally {
      setIsLoggingIn(false);
    }
  }, [persistSession]);

  /** Clear the local session (stateless JWT — nothing server-side to revoke). */
  const logout = useCallback(async () => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    persistSession(null);
  }, [persistSession]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        isLoggingIn,
        error,
        login,
        loginDemo,
        acceptInvite,
        logout,
        clearError,
        getValidAccessToken,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Custom Hook: useAuth()
 * Read active procurement team member details or handle login/logout.
 */
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
