'use client';

import React, { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { useAsgardeo } from '@asgardeo/nextjs';
import { useAuth } from '@/contexts/AuthContext';

/** Routes that handle the OIDC flow themselves and must render without a session. */
const PUBLIC_ROUTES = ['/login', '/auth/callback'];

/** Check whether a pathname is a public (unauthenticated) route. */
function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`)
  );
}

/**
 * AuthGuard: Client-side gate in front of the application shell.
 *
 * Two session sources are honored:
 * 1. The official @asgardeo/nextjs SDK session (server httpOnly cookie,
 *    exposed via useAsgardeo) — the primary enterprise SSO path.
 * 2. The legacy local AuthContext session (kept for backwards
 *    compatibility with the hand-rolled OIDC flow).
 *
 * While either session source is still resolving it renders a neutral
 * loading screen (no app chrome, no flicker of protected content). Once
 * both are known to be absent, it redirects to /login.
 *
 * Server-side enforcement additionally belongs to middleware.ts
 * (asgardeoMiddleware + protectRoute) and to the APIs: every FastAPI
 * request carries `Authorization: Bearer <accessToken>`.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isAuthenticated, isLoading } = useAuth();
  const { isSignedIn: isAsgardeoSignedIn, isLoading: isAsgardeoLoading } = useAsgardeo();

  // Either session source grants access; either loading flag holds the gate.
  const isAuthenticatedAny = isAuthenticated || isAsgardeoSignedIn === true;
  const isLoadingAny = isLoading || isAsgardeoLoading === true;

  const isPublic = isPublicRoute(pathname || '/');

  useEffect(() => {
    if (!isLoadingAny && !isAuthenticatedAny && !isPublic) {
      // Replace so the protected route does not linger in history.
      window.location.assign('/login');
    }
  }, [isLoadingAny, isAuthenticatedAny, isPublic]);

  // Public routes render as-is (login/callback pages manage their own layout).
  if (isPublic) {
    return <>{children}</>;
  }

  // Session restore in progress (either source): neutral splash prevents protected flicker.
  if (isLoadingAny) {
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
  if (!isAuthenticatedAny) {
    return null;
  }

  return <>{children}</>;
}
