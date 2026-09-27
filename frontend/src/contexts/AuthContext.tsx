'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { UserSession, AuthContextType } from '@/types';

/**
 * AuthContext: Manages user authentication and session state.
 * 
 * Per PRD specifications:
 * - Single-tenant deployment per enterprise.
 * - Single role across all users: 'Procurement Team Member' with uniform capabilities.
 * - Architecture designed for outsourced IAM via WSO2 Identity Server / Asgardeo (OIDC / OAuth 2.0).
 * 
 * When WSO2 is plugged in:
 * 1. User redirects to WSO2 login endpoint with PKCE.
 * 2. On callback, WSO2 issues ID Token (claims) and Access Token (Bearer).
 * 3. AuthContext stores tokens and populates the UserSession.
 * 4. API requests to FastAPI carry `Authorization: Bearer <accessToken>`.
 */

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const AUTH_STORAGE_KEY = 'zellovest_auth_session';

// Default mock user session matching the single-role procurement persona
const DEFAULT_USER: UserSession = {
  id: 'usr_oidc_sarah_chen',
  name: 'Sarah Chen',
  email: 'sarah.chen@acmetech.com',
  role: 'Procurement Team Member',
  department: 'Procurement & Strategic Sourcing',
  organizationName: 'Acme Technologies Inc.',
  avatarUrl: '',
  accessToken: 'mock_wso2_jwt_access_token',
};

export function AuthProvider({ children }: { children: ReactNode }) {
  // Always start with the same value the server renders, then hydrate from
  // localStorage after mount to avoid SSR/client hydration mismatches.
  const [user, setUser] = useState<UserSession | null>(DEFAULT_USER);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  useEffect(() => {
    // Deferred so hydration completes with the server-rendered default first.
    const timer = setTimeout(() => {
      try {
        const stored = localStorage.getItem(AUTH_STORAGE_KEY);
        if (stored) {
          setUser(JSON.parse(stored));
        } else {
          localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(DEFAULT_USER));
        }
      } catch {
        // Storage unavailable: keep the default session
      }
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  // Sync localStorage when user changes
  useEffect(() => {
    if (user) {
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(user));
    }
  }, [user]);

  const login = async (email?: string) => {
    setIsLoading(true);
    // Simulating OIDC Authorization Code + PKCE token resolution from WSO2
    await new Promise((resolve) => setTimeout(resolve, 400));

    const userEmail = email || 'sarah.chen@acmetech.com';
    const newUser: UserSession = {
      id: `usr_wso2_${Date.now()}`,
      name: userEmail.split('@')[0].replace('.', ' ').replace(/\b\w/g, (l) => l.toUpperCase()),
      email: userEmail,
      role: 'Procurement Team Member',
      department: 'Procurement & Strategic Sourcing',
      organizationName: 'Acme Technologies Inc.',
      accessToken: `wso2_jwt_${Math.random().toString(36).substring(2)}`,
    };

    setUser(newUser);
    try {
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(newUser));
    } catch {
      // Ignore storage errors
    }
    setIsLoading(false);
  };

  const logout = () => {
    setUser(null);
    try {
      localStorage.removeItem(AUTH_STORAGE_KEY);
      // In production with WSO2, this also invokes the WSO2 OIDC RP-initiated logout endpoint
    } catch {
      // Ignore storage errors
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        logout,
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
