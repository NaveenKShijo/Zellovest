'use client';

import React from 'react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { Breadcrumbs } from './Breadcrumbs';
import { AlertBanner } from '@/components/ui/AlertBanner';

/**
 * LayoutShell: The permanent master administrative frame.
 * 
 * Styled after the Velvet Burgundy & Soft Blush Rose reference image.
 * - Sidebar, Header, Breadcrumbs remain stationary.
 * - Dynamic content canvas scrolls independently.
 */

export function LayoutShell({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        width: '100vw',
        maxHeight: '100vh',
        overflow: 'hidden',
        backgroundColor: 'var(--bg-app)',
        position: 'relative',
      }}
    >
      {/* 1. Velvet Burgundy Permanent Navigation Sidebar */}
      <Sidebar />

      {/* 2. Main Column: Static Header & Breadcrumbs + Scrollable Blush Content Canvas */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          flex: 1,
          height: '100vh',
          minWidth: 0,
          overflow: 'hidden',
        }}
      >
        {/* Stationary Pinned Header */}
        <div style={{ flexShrink: 0 }}>
          <Header />
        </div>

        {/* System Announcements & Alerts (if any) */}
        <div style={{ flexShrink: 0 }}>
          <AlertBanner />
        </div>

        {/* Stationary Pinned Breadcrumbs */}
        <div style={{ flexShrink: 0 }}>
          <Breadcrumbs />
        </div>

        {/* 
          DYNAMIC CONTENT VIEWPORT (Soft Blush Rose Canvas)
          Only this area scrolls independently.
        */}
        <main
          id="content-viewport"
          style={{
            flex: 1,
            overflowY: 'auto',
            overflowX: 'hidden',
            backgroundColor: 'var(--bg-app)',
            padding: '16px 32px 48px 32px',
            width: '100%',
          }}
        >
          <div style={{ maxWidth: '1600px', margin: '0 auto' }}>
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
