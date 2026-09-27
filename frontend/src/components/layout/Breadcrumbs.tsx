'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { BreadcrumbItem } from '@/types';

/**
 * Route labels mapping URL slugs to human-readable procurement domain titles.
 */
const ROUTE_LABELS: Record<string, string> = {
  '': 'Overview',
  vendors: 'Vendor 360',
  compliance: 'AP Audit & Compliance',
  'maverick-spend': 'Maverick SaaS Spend',
  licenses: 'Zombie Licenses',
  renewals: 'Renewal Intelligence',
  assistant: 'Investigation Agent',
  integrations: 'Data Ingestion',
  settings: 'Settings',
};

export function Breadcrumbs() {
  const pathname = usePathname();

  // Parse path segments: "/compliance/invoices/123" -> ["compliance", "invoices", "123"]
  const segments = pathname.split('/').filter(Boolean);

  const breadcrumbs: BreadcrumbItem[] = [
    { label: 'Home', href: '/' },
    ...segments.map((segment, index) => {
      const href = `/${segments.slice(0, index + 1).join('/')}`;
      const isCurrent = index === segments.length - 1;
      const label = ROUTE_LABELS[segment] || segment.replace(/-/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());

      return {
        label,
        href: isCurrent ? undefined : href,
        isCurrent,
      };
    }),
  ];

  return (
    <nav
      aria-label="Breadcrumb"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        padding: '12px 28px 4px 28px',
        fontSize: '12.5px',
        color: 'var(--text-muted)',
        backgroundColor: 'var(--bg-app)',
      }}
    >
      {breadcrumbs.map((crumb, idx) => (
        <React.Fragment key={idx}>
          {idx > 0 && (
            <svg
              width="11"
              height="11"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ color: '#C8BFAD', flexShrink: 0 }}
            >
              <polyline points="9 18 15 12 9 6" />
            </svg>
          )}

          {crumb.href ? (
            <Link
              href={crumb.href}
              style={{
                color: 'var(--text-secondary)',
                fontWeight: 500,
                transition: 'color var(--transition-fast)',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-brand)')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-secondary)')}
            >
              {crumb.label}
            </Link>
          ) : (
            <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
              {crumb.label}
            </span>
          )}
        </React.Fragment>
      ))}
    </nav>
  );
}
