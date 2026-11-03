'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode, useRef } from 'react';
import { UserSession, AuthContextType, AuthResponse } from '@/types';
import { acceptInviteRequest, demoLoginRequest, loginRequest, refreshTokenRequest } from '@/lib/auth';

/**
 * AuthContext: custom email/password session (invite-only onboarding).
 *
 * Concepts for the reader:
 * - The backend owns passwords (PBKDF2 hash in `users.password_hash`).
 * - On login (or invite claim) it returns a short-lived HS256 JWT
 *   (access_token, default 60 min) plus a long-lived refresh JWT
 *   (7 days). The JWT is just a signed JSON blob:
 *   header.payload.signature — the server verifies the signature with
 *   JWT_SECRET_KEY on every call.
 * - The browser keeps the JWT + profile in localStorage (simple and
 *   visible for learning; production-hardening would move it to an
 *   httpOnly cookie to block XSS exfiltration).
 * - Single role in V1: every authenticated user is Procurement Team Member.
 * - No public signup: accounts come from the seed script (first/demo
 *   user) or from claiming an invite link.
 * - ACCESS TOKEN REFRESH: before the access token expires, the client
 *   silently swaps the refresh token for a new access token via
 *   POST /auth/refresh. If a request still hits 401, the client retries
 *   once after refreshing — users stay logged in across sessions without
 *   re-typing credentials.
 */

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const AUTH_STORAGE_KEY = 'zellovest_auth_session';
const ORGANIZATION_NAME = process.env.NEXT_PUBLIC_ORGANIZATION_NAME || 'Zellovest';

/** Start the silent refresh this many seconds before the access token expires. */
const REFRESH_LEAD_SECONDS = 60;

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
    expiresAt: Date.now() + data.expires_in_minutes * 60 * 1000,
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
  const refreshing = useRef<boolean>(false);

  /** Silent refresh: swap refresh token for a new access token. */
  const performRefresh = useCallback(async () => {
    if (!user?.refreshToken || refreshing.current) return;
    refreshing.current = true;
    try {
      const data = await refreshTokenRequest(user.refreshToken);
      const session = toSession(data);
      setUser(session);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
    } catch (err) {
      // Refresh token expired or invalid: clear session and force sign-in.
      try {
        localStorage.removeItem(AUTH_STORAGE_KEY);
      } catch {
        // ignore
      }
      setUser(null);
      setError('Your session expired. Please sign in again.');
    } finally {
      refreshing.current = false;
    }
  }, [user?.refreshToken]);

  /** Get a valid access token, refreshing in place if expired. */
  const getValidAccessToken = useCallback(async (): Promise<string | null> => {
    if (!user) return null;
    const now = Date.now();
    if (user.expiresAt && now >= user.expiresAt - REFRESH_LEAD_SECONDS * 1000) {
      await performRefresh();
    }
    return (user as UserSession).accessToken ?? null;
  }, [user, performRefresh]);

  useEffect(() => {
    // Deferred so hydration completes with the server-rendered default first.
    const timer = setTimeout(() => {
      try {
        const stored = localStorage.getItem(AUTH_STORAGE_KEY);
        if (stored) {
          const session = JSON.parse(stored) as UserSession;
          if (session.expiresAt && Date.now() >= session.expiresAt) {
            localStorage.removeItem(AUTH_STORAGE_KEY);
          } else {
            setUser(session);
          }
        }
      } catch {
        // Corrupted storage: start unauthenticated rather than crashing.
        try {
          localStorage.removeItem(AUTH_STORAGE_KEY);
        } catch {
          // Storage unavailable: nothing to clean up.
        }
      } finally {
        setIsLoading(false);
      }
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  // ---- Background access-token refresh ----
  useEffect(() => {
    if (!user?.refreshToken || !user?.expiresAt) return;

    const scheduleRefresh = () => {
      const now = Date.now();
      const expiresAt = user.expiresAt;
      if (!expiresAt) return;
      const delay = Math.max(0, expiresAt - now - REFRESH_LEAD_SECONDS * 1000);

      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      if (delay <= 0) {
        // Already past the lead window: refresh now.
        performRefresh();
      } else {
        refreshTimer.current = setTimeout(performRefresh, delay);
      }
    };

    scheduleRefresh();
    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [user?.refreshToken, user?.expiresAt, performRefresh]);

  const clearError = useCallback(() => setError(null), []);

  /** Authenticate with email + password; persists the JWT session. */
  const login = useCallback(async (email: string, password: string): Promise<boolean> => {
    setIsLoggingIn(true);
    setError(null);
    try {
      const data = await loginRequest(email, password);
      const session = toSession(data);
      setUser(session);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed. Please try again.');
      return false;
    } finally {
      setIsLoggingIn(false);
    }
  }, []);

  /** One-click sandbox entry (no credentials); persists the demo JWT session. */
  const loginDemo = useCallback(async (): Promise<boolean> => {
    setIsLoggingIn(true);
    setError(null);
    try {
      const data = await demoLoginRequest();
      const session = toSession(data);
      setUser(session);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the demo. Please try again.');
      return false;
    } finally {
      setIsLoggingIn(false);
    }
  }, []);

  /** Claim an invite link; creates the account and persists the JWT session. */
  const acceptInvite = useCallback(async (token: string, name: string, password: string): Promise<boolean> => {
    setIsLoggingIn(true);
    setError(null);
    try {
      const data = await acceptInviteRequest(token, name, password);
      const session = toSession(data);
      setUser(session);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not accept the invite. Please try again.');
      return false;
    } finally {
      setIsLoggingIn(false);
    }
  }, []);

  /** Clear the local session (stateless JWT — nothing server-side to revoke). */
  const logout = useCallback(async () => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    try {
      localStorage.removeItem(AUTH_STORAGE_KEY);
    } catch {
      // Ignore storage errors; the local session is being discarded anyway.
    }
    setUser(null);
  }, []);

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
