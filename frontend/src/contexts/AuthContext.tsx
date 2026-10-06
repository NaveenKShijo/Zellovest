'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { UserSession, AuthContextType } from '@/types';
import {
  buildAuthorizeUrl,
  consumeState,
  decodeIdToken,
  discoverOidcEndpoints,
  exchangeCodeForTokens,
  getOidcConfig,
} from '@/lib/oidc';

/**
 * AuthContext: Manages user authentication and session state via WSO2 Identity
 * Server (OIDC Authorization Code + PKCE).
 *
 * Per PRD specifications:
 * - Single-tenant deployment per enterprise; authentication outsourced to WSO2.
 * - Single role across all users: 'Procurement Team Member'.
 *
 * Flow:
 * 1. startLogin() redirects the browser to the WSO2 hosted login page (PKCE).
 * 2. WSO2 authenticates the user and redirects back to the Authorized Redirect
 *    URL (/auth/callback) with an authorization `code` + `state`.
 * 3. completeLogin() validates `state`, exchanges the code for ID/Access
 *    tokens, derives the UserSession from ID token claims and persists it.
 * 4. API requests to FastAPI carry `Authorization: Bearer <accessToken>`.
 */

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const AUTH_STORAGE_KEY = 'zellovest_auth_session';

/** Fallback display name when WSO2 claims carry no usable name. */
function deriveDisplayName(claims: Record<string, unknown>, email: string): string {
  if (typeof claims.name === 'string' && claims.name.trim()) return claims.name;
  const given = typeof claims.given_name === 'string' ? claims.given_name : '';
  const family = typeof claims.family_name === 'string' ? claims.family_name : '';
  if (given || family) return `${given} ${family}`.trim();
  if (typeof claims.preferred_username === 'string' && claims.preferred_username.trim()) {
    return claims.preferred_username;
  }
  return email.split('@')[0]?.replace(/[._-]/g, ' ') || 'Procurement User';
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Start unauthenticated on both server and client; the session is restored
  // after mount from localStorage (avoids SSR/client hydration mismatches).
  const [user, setUser] = useState<UserSession | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Deferred so hydration completes with the server-rendered default first
    // (avoids cascading renders and SSR/client hydration mismatches).
    const timer = setTimeout(() => {
      try {
        const stored = localStorage.getItem(AUTH_STORAGE_KEY);
        if (stored) {
          const session = JSON.parse(stored) as UserSession;
          // Drop expired sessions (access token expiry); silent refresh via
          // the WSO2 refresh token is a follow-up concern.
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

  /**
   * Redirect the browser to the WSO2 hosted login page.
   * The Authorized Redirect URL (/auth/callback) receives the result.
   */
  const startLogin = useCallback(async () => {
    setError(null);
    try {
      const authorizeUrl = await buildAuthorizeUrl();
      window.location.assign(authorizeUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the login flow.');
    }
  }, []);

  /**
   * Complete the OIDC Authorization Code flow on /auth/callback.
   * Returns true when a session was established; on failure the error is
   * exposed via `error` and false is returned (never throws).
   */
  const completeLogin = useCallback(async (code: string, state: string | null): Promise<boolean> => {
    setIsLoggingIn(true);
    setError(null);
    try {
      // CSRF protection: the state must match the one generated at /login.
      if (!consumeState(state)) {
        throw new Error('Invalid or expired login state. Please try signing in again.');
      }

      const tokens = await exchangeCodeForTokens(code);
      const claims = decodeIdToken(tokens.id_token);

      const email =
        (typeof claims.email === 'string' && claims.email) ||
        (typeof claims.preferred_username === 'string' ? claims.preferred_username : '') ||
        '';

      const session: UserSession = {
        id: claims.sub,
        name: deriveDisplayName(claims as Record<string, unknown>, email),
        email,
        role: 'Procurement Team Member',
        department: 'Procurement & Strategic Sourcing',
        organizationName:
          (typeof claims.organization_name === 'string' && claims.organization_name) ||
          process.env.NEXT_PUBLIC_ORGANIZATION_NAME ||
          '',
        avatarUrl: typeof claims.picture === 'string' ? claims.picture : '',
        accessToken: tokens.access_token,
        idToken: tokens.id_token,
        expiresAt: Date.now() + tokens.expires_in * 1000,
      };

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

  /** Clear the local session and invoke WSO2 RP-initiated logout. */
  const logout = useCallback(async () => {
    let session: UserSession | null = null;
    try {
      const stored = localStorage.getItem(AUTH_STORAGE_KEY);
      if (stored) session = JSON.parse(stored) as UserSession;
      localStorage.removeItem(AUTH_STORAGE_KEY);
    } catch {
      // Ignore storage errors; the local session is being discarded anyway.
    }
    setUser(null);

    try {
      // RP-initiated logout: clear the WSO2 SSO session and return to the app.
      const { end_session_endpoint } = await discoverOidcEndpoints(getOidcConfig().authority);
      const params = new URLSearchParams({
        post_logout_redirect_uri: process.env.NEXT_PUBLIC_REDIRECT_URI || window.location.origin,
        state: 'logout',
      });
      if (session?.idToken) {
        params.set('id_token_hint', session.idToken);
      }
      if (end_session_endpoint) {
        window.location.assign(`${end_session_endpoint}?${params.toString()}`);
      }
    } catch {
      // OIDC config missing or discovery unreachable: local logout already done.
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        isLoggingIn,
        error,
        startLogin,
        completeLogin,
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
