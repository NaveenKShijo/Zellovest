'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { UserSession, AuthContextType, AuthResponse } from '@/types';
import { acceptInviteRequest, loginRequest } from '@/lib/auth';

/**
 * AuthContext: custom email/password session (invite-only onboarding).
 *
 * Concepts for the reader:
 * - The backend owns passwords (PBKDF2 hash in `users.password_hash`).
 * - On login (or invite claim) it returns a short-lived HS256 JWT
 *   (access_token). The JWT is just a signed JSON blob:
 *   header.payload.signature — the server verifies the signature with
 *   JWT_SECRET_KEY on every call.
 * - The browser keeps the JWT + profile in localStorage (simple and
 *   visible for learning; production-hardening would move it to an
 *   httpOnly cookie to block XSS exfiltration).
 * - Single role in V1: every authenticated user is Procurement Team Member.
 * - No public signup: accounts come from the seed script (first/demo
 *   user) or from claiming an invite link.
 */

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const AUTH_STORAGE_KEY = 'zellovest_auth_session';
const ORGANIZATION_NAME = process.env.NEXT_PUBLIC_ORGANIZATION_NAME || 'Zellovest';

function toSession(data: AuthResponse): UserSession {
  return {
    id: data.user.id,
    name: data.user.name || data.user.email.split('@')[0]?.replace(/[._-]/g, ' ') || 'Procurement User',
    email: data.user.email,
    role: 'Procurement Team Member',
    department: 'Procurement & Strategic Sourcing',
    organizationName: ORGANIZATION_NAME,
    accessToken: data.access_token,
    expiresAt: Date.now() + data.expires_in_minutes * 60 * 1000,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Start unauthenticated on both server and client; the session is restored
  // after mount from localStorage (avoids SSR/client hydration mismatches).
  const [user, setUser] = useState<UserSession | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

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
        acceptInvite,
        logout,
        clearError,
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
