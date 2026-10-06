'use client';

import React from 'react';
import { usePathname } from 'next/navigation';
import { LayoutShell } from '@/components/layout/LayoutShell';

/** Standalone pages that render without the sidebar/header application shell. */
const SHELL_LESS_ROUTES = ['/login', '/auth/callback'];

/**
 * ShellGate: renders the application shell (sidebar, header, breadcrumbs)
 * around authenticated app pages, but leaves standalone pages such as the
 * login screen bare — an industry-standard login page has no app chrome.
 */
export function ShellGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const bare = SHELL_LESS_ROUTES.some(
    (route) => pathname === route || pathname?.startsWith(`${route}/`)
  );

  if (bare) {
    return <>{children}</>;
  }

  return <LayoutShell>{children}</LayoutShell>;
}
