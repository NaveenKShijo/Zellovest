'use client';

import React, { useState } from 'react';
import { useAsgardeo } from '@asgardeo/nextjs';
import { AsgardeoUserInfo, ORGANIZATION_NAME } from '@/components/auth/AsgardeoAuth';
import { useAuth } from '@/contexts/AuthContext';
import { useLayout } from '@/contexts/LayoutContext';
import { useToast } from '@/contexts/ToastContext';

export function Header() {
  const { user, logout } = useAuth();
  const { isSignedIn: isAsgardeoSignedIn, signOut: asgardeoSignOut } = useAsgardeo();
  const [isSigningOut, setIsSigningOut] = useState(false);

  /**
   * Sign out via the SDK session when present (server action clears the
   * session cookie and navigates to the post-logout URL), falling back
   * to the legacy local logout. NOTE: the SDK's <SignOutButton>
   * render-prop path is intentionally NOT used — like <SignInButton>,
   * it renders children with no click handler attached.
   */
  const handleSignOut = () => {
    setIsUserMenuOpen(false);
    if (isAsgardeoSignedIn && asgardeoSignOut) {
      setIsSigningOut(true);
      void asgardeoSignOut().catch(() => logout());
    } else {
      void logout();
    }
  };
  const { toggleMobileSidebar } = useLayout();
  const { toasts, notify } = useToast();
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);

  return (
    <header
      style={{
        height: 'var(--header-height)',
        backgroundColor: 'var(--bg-header)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 32px',
        position: 'relative',
        zIndex: 'var(--z-header)',
      }}
    >
      {/* Left: Mobile Toggle & Page Title Area */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <button
          onClick={toggleMobileSidebar}
          aria-label="Open navigation menu"
          className="header-mobile-toggle"
          style={{
            padding: '8px',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--text-secondary)',
            display: 'none',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>

        <span style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.3px' }}>
          Dashboard
        </span>
      </div>

      {/* Right: Search Input & Utility Icons (Mirrors the reference image) */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        
        {/* Rounded Blush Search Bar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            backgroundColor: '#F2E0E4',
            borderRadius: 'var(--radius-full)',
            padding: '7px 16px',
            gap: '8px',
            width: '260px',
            border: '1px solid transparent',
            transition: 'all var(--transition-fast)',
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9E7D84" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="text"
            placeholder="Search..."
            style={{
              border: 'none',
              background: 'transparent',
              outline: 'none',
              fontSize: '13px',
              color: 'var(--text-primary)',
              width: '100%',
            }}
          />
        </div>

        {/* Message / Chat Bubble Icon */}
        <button
          onClick={() => notify.info('AI Assistant', 'Procurement Investigation Agent is ready for queries.')}
          aria-label="Messages"
          style={{
            padding: '8px',
            borderRadius: 'var(--radius-full)',
            color: 'var(--text-primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#EED8DC')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        </button>

        {/* Bell Notification Icon with Unread Indicator */}
        <button
          onClick={() => notify.warning('AP Variance Alert', '3 new invoice rate exceptions flagged by deterministic audit.')}
          aria-label="Notifications"
          style={{
            position: 'relative',
            padding: '8px',
            borderRadius: 'var(--radius-full)',
            color: 'var(--text-primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#EED8DC')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>

          {toasts.length > 0 && (
            <span
              style={{
                position: 'absolute',
                top: '6px',
                right: '6px',
                width: '7px',
                height: '7px',
                backgroundColor: 'var(--color-brand)',
                borderRadius: 'var(--radius-full)',
              }}
            />
          )}
        </button>

        {/* User Session Profile */}
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '3px 8px 3px 3px',
              borderRadius: 'var(--radius-full)',
              backgroundColor: '#F2E0E4',
            }}
          >
            <div
              style={{
                width: '28px',
                height: '28px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: 'var(--color-brand)',
                color: '#FFFFFF',
                fontWeight: 700,
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {ORGANIZATION_NAME.charAt(0).toUpperCase()}
            </div>
            {/* Single-tenant branding: the badge carries the company name;
                the signed-in user is shown inside the dropdown menu. */}
            <span style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-primary)' }}>
              {ORGANIZATION_NAME}
            </span>
          </button>

          {/* User Dropdown */}
          {isUserMenuOpen && (
            <div
              style={{
                position: 'absolute',
                top: 'calc(100% + 8px)',
                right: 0,
                width: '220px',
                backgroundColor: '#FFFFFF',
                borderRadius: 'var(--radius-md)',
                boxShadow: 'var(--shadow-lg)',
                border: '1px solid var(--border-subtle)',
                padding: '8px',
                zIndex: 'calc(var(--z-header) + 1)',
              }}
            >
              <div style={{ padding: '8px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '4px' }}>
                <AsgardeoUserInfo
                  signedOutFallback={
                    <>
                      <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>{user?.name}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{user?.role}</div>
                    </>
                  }
                />
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  {ORGANIZATION_NAME} · {user?.role || 'Procurement Team Member'}
                </div>
              </div>
              {isAsgardeoSignedIn ? (
                <button
                  onClick={handleSignOut}
                  disabled={isSigningOut}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    padding: '7px 8px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12px',
                    color: 'var(--color-danger)',
                    opacity: isSigningOut ? 0.6 : 1,
                    cursor: isSigningOut ? 'wait' : 'pointer',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-danger-subtle)')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  {isSigningOut ? 'Signing out…' : 'Sign Out'}
                </button>
              ) : (
                <button
                  onClick={handleSignOut}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    padding: '7px 8px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12px',
                    color: 'var(--color-danger)',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-danger-subtle)')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  Sign Out
                </button>
              )}
            </div>
          )}
        </div>

      </div>

      <style>{`
        @media (max-width: 1023px) {
          .header-mobile-toggle {
            display: flex !important;
          }
        }
      `}</style>
    </header>
  );
}
