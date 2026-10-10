'use client';

import React, { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';

/** Routes that render without a session (login + invite claim). */
const PUBLIC_ROUTES = ['/login', '/invite'];

function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTES.some((route) => pathname === route || pathname.startsWith(`${route}/`));
}

/**
 * AuthGuard: client-side gate in front of the application shell.
 *
 * Single session source: the custom AuthContext JWT (localStorage).
 * While the session is restoring it renders a neutral loading screen;
 * once known-absent it redirects to /login.
 *
 * Server-side enforcement additionally belongs to the FastAPI services:
 * every API request carries `Authorization: Bearer <accessToken>`.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isAuthenticated, isLoading } = useAuth();

  const isPublic = isPublicRoute(pathname || '/');

  useEffect(() => {
    if (!isLoading && !isAuthenticated && !isPublic) {
      // Replace so the protected route does not linger in history.
      window.location.assign('/login');
    }
  }, [isLoading, isAuthenticated, isPublic]);

  // Public routes render as-is (login/invite pages manage their own layout).
  if (isPublic) {
    return <>{children}</>;
  }

  // Session restore in progress: neutral splash prevents protected flicker.
  if (isLoading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          width: '100vw',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'var(--bg-app)',
          gap: '16px',
        }}
      >
        <div
          style={{
            width: '44px',
            height: '44px',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'var(--color-brand)',
            color: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 800,
            fontSize: '20px',
          }}
        >
          Z
        </div>
        <span
          aria-hidden="true"
          style={{
            width: '22px',
            height: '22px',
            border: '3px solid var(--border-tint)',
            borderTopColor: 'var(--color-brand)',
            borderRadius: 'var(--radius-full)',
            display: 'inline-block',
            animation: 'authGuardSpinner 0.8s linear infinite',
          }}
        />
        <style>{`
          @keyframes authGuardSpinner {
            to { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    );
  }

  // Unauthenticated: render nothing; the redirect effect takes over.
  if (!isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}
