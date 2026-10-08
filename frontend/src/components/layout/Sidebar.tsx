'use client';

import React from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
import { useLayout } from '@/contexts/LayoutContext';
import { useAuth } from '@/contexts/AuthContext';
import { ORGANIZATION_NAME, useDisplayIdentity } from '@/components/auth/AsgardeoAuth';
import { NavSection, NavItem } from '@/types';

/**
 * Sidebar styled after the Velvet Burgundy aesthetic:
 * - Rich Burgundy background (#71091E).
 * - Active tab rendered as a crisp White Pill with burgundy text/icon.
 * - Inactive tabs in soft dusty rose (#E5A8B5).
 * - User avatar pill at bottom.
 */
const NAVIGATION_SECTIONS: NavSection[] = [
  {
    title: 'Core Intelligence',
    items: [
      {
        id: 'overview',
        label: 'Overview',
        href: '/',
        iconName: 'grid',
      },
      {
        id: 'vendors',
        label: 'Vendor 360',
        href: '/vendors',
        iconName: 'building',
        badge: '142',
      },
      {
        id: 'compliance',
        label: 'AP Audit',
        href: '/compliance',
        iconName: 'clipboard-check',
        badge: '3',
        badgeVariant: 'danger',
      },
    ],
  },
  {
    title: 'Optimization',
    items: [
      {
        id: 'maverick-spend',
        label: 'Maverick Spend',
        href: '/maverick-spend',
        iconName: 'credit-card',
        badge: '$14k',
        badgeVariant: 'warning',
      },
      {
        id: 'licenses',
        label: 'Liscence forecasting',
        href: '/licenses',
        iconName: 'users',
        badge: '109',
        badgeVariant: 'info',
      },
      {
        id: 'renewals',
        label: 'Renewals',
        href: '/renewals',
        iconName: 'calendar',
        badge: '2',
      },
    ],
  },
  {
    title: 'Platform',
    items: [
      {
        id: 'assistant',
        label: 'Investigation Agent',
        href: '/assistant',
        iconName: 'bot',
      },
      {
        id: 'integrations',
        label: 'Data Ingestion',
        href: '/integrations',
        iconName: 'database',
      },
      {
        id: 'upload',
        label: 'Upload Documents',
        href: '/upload',
        iconName: 'upload',
      },
      {
        id: 'settings',
        label: 'Settings',
        href: '/settings',
        iconName: 'settings',
      },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();
  // Single-tenant branding: the card leads with the organization name and
  // the signed-in username beneath it (never demo placeholders).
  const { name: displayUsername } = useDisplayIdentity();
  const {
    isSidebarCollapsed,
    toggleSidebar,
    isMobileSidebarOpen,
    closeMobileSidebar,
  } = useLayout();

  return (
    <>
      {/* Mobile Backdrop Overlay */}
      {isMobileSidebarOpen && (
        <div
          onClick={closeMobileSidebar}
          aria-hidden="true"
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(50, 4, 13, 0.65)',
            backdropFilter: 'blur(3px)',
            zIndex: 'calc(var(--z-mobile-drawer) - 1)',
            transition: 'opacity var(--transition-normal)',
          }}
        />
      )}

      {/* Main Sidebar Element (Velvet Burgundy) */}
      <aside
        style={{
          width: isSidebarCollapsed ? 'var(--sidebar-collapsed-width)' : 'var(--sidebar-width)',
          backgroundColor: 'var(--bg-sidebar)',
          display: 'flex',
          flexDirection: 'column',
          height: '100vh',
          zIndex: 'var(--z-sidebar)',
          transition: 'width var(--transition-normal), transform var(--transition-normal)',
          flexShrink: 0,
          overflow: 'hidden',
          boxShadow: '2px 0 12px rgba(113, 9, 30, 0.1)',
        }}
        className={isMobileSidebarOpen ? 'sidebar-mobile-open' : 'sidebar-desktop'}
      >
        {/* Brand Header */}
        <div
          style={{
            height: 'var(--header-height)',
            display: 'flex',
            alignItems: 'center',
            padding: isSidebarCollapsed ? '0 16px' : '0 22px',
            gap: '12px',
            flexShrink: 0,
          }}
        >
          {/* Logo */}
          {isSidebarCollapsed ? (
            <div
              title="Zellovest"
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '8px',
                backgroundColor: '#FFFFFF',
                position: 'relative',
                overflow: 'hidden',
                flexShrink: 0,
              }}
            >
              {/* Cropped Z mark from the full logo */}
              <Image
                src="/zellovest-logo.png"
                alt="Zellovest"
                width={150}
                height={50}
                priority
                style={{ position: 'absolute', left: '-9px', top: '-9px', width: '150px', height: '50px', maxWidth: 'none' }}
              />
            </div>
          ) : (
            <div
              style={{
                backgroundColor: '#FFFFFF',
                borderRadius: '10px',
                padding: '6px 12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                maxWidth: '100%',
              }}
            >
              <Image
                src="/zellovest-logo.png"
                alt="Zellovest"
                width={140}
                height={47}
                priority
                style={{ width: '140px', height: 'auto', display: 'block' }}
              />
            </div>
          )}
        </div>

        {/* Navigation Sections */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            overflowX: 'hidden',
            padding: isSidebarCollapsed ? '16px 8px' : '12px 14px',
            display: 'flex',
            flexDirection: 'column',
            gap: '18px',
          }}
        >
          {NAVIGATION_SECTIONS.map((section, idx) => (
            <div key={idx}>
              {!isSidebarCollapsed && (
                <div
                  style={{
                    fontSize: '10px',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em',
                    color: 'var(--text-sidebar-muted)',
                    padding: '0 10px 6px 10px',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {section.title}
                </div>
              )}

              <nav style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {section.items.map((item) => {
                  const isActive = pathname === item.href;

                  return (
                    <Link
                      key={item.id}
                      href={item.href}
                      onClick={closeMobileSidebar}
                      title={isSidebarCollapsed ? item.label : undefined}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '12px',
                        padding: isSidebarCollapsed ? '10px 0' : '9px 12px',
                        justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: isActive ? 'var(--bg-sidebar-active)' : 'transparent',
                        color: isActive ? 'var(--text-sidebar-active)' : 'var(--text-sidebar)',
                        fontSize: '13px',
                        fontWeight: isActive ? 600 : 500,
                        transition: 'all var(--transition-fast)',
                        boxShadow: isActive ? '0 2px 8px rgba(0, 0, 0, 0.12)' : 'none',
                      }}
                      onMouseEnter={(e) => {
                        if (!isActive) {
                          e.currentTarget.style.backgroundColor = 'var(--bg-sidebar-hover)';
                          e.currentTarget.style.color = '#FFFFFF';
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (!isActive) {
                          e.currentTarget.style.backgroundColor = 'transparent';
                          e.currentTarget.style.color = 'var(--text-sidebar)';
                        }
                      }}
                    >
                      {/* Icon */}
                      <span style={{ display: 'flex', flexShrink: 0 }}>
                        <NavIcon name={item.iconName} active={isActive} />
                      </span>

                      {/* Label & Badges */}
                      {!isSidebarCollapsed && (
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            flex: 1,
                            minWidth: 0,
                          }}
                        >
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {item.label}
                          </span>

                          {item.badge && (
                            <Badge variant={item.badgeVariant} isActive={isActive}>{item.badge}</Badge>
                          )}
                        </div>
                      )}
                    </Link>
                  );
                })}
              </nav>
            </div>
          ))}
        </div>

        {/* Sidebar Bottom: User Profile Avatar & Collapse Toggle */}
        <div
          style={{
            padding: isSidebarCollapsed ? '14px 8px' : '14px 16px',
            borderTop: '1px solid var(--border-sidebar)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: isSidebarCollapsed ? 'center' : 'space-between',
            flexShrink: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.1)',
          }}
        >
          {/* Avatar Icon */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: '#FFFFFF',
                color: 'var(--bg-sidebar)',
                fontWeight: 700,
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              {ORGANIZATION_NAME.charAt(0).toUpperCase()}
            </div>

            {!isSidebarCollapsed && (
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <span style={{ fontSize: '12.5px', fontWeight: 600, color: '#FFFFFF', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {ORGANIZATION_NAME}
                </span>
                <span style={{ fontSize: '10.5px', color: 'var(--text-sidebar)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {displayUsername || user?.name || 'Procurement'}
                </span>
              </div>
            )}
          </div>

          {/* Collapse Button */}
          <button
            onClick={toggleSidebar}
            aria-label={isSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            style={{
              padding: '6px',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-sidebar)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = '#FFFFFF')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-sidebar)')}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{
                transform: isSidebarCollapsed ? 'rotate(180deg)' : 'none',
                transition: 'transform var(--transition-normal)',
              }}
            >
              <polyline points="11 17 6 12 11 7" />
              <polyline points="18 17 13 12 18 7" />
            </svg>
          </button>
        </div>
      </aside>

      {/* Responsive Mobile Drawer Styles */}
      <style>{`
        @media (max-width: 1023px) {
          .sidebar-desktop {
            position: fixed !important;
            left: 0;
            top: 0;
            bottom: 0;
            transform: translateX(-100%);
            box-shadow: var(--shadow-lg);
            z-index: var(--z-mobile-drawer) !important;
          }
          .sidebar-mobile-open {
            position: fixed !important;
            left: 0;
            top: 0;
            bottom: 0;
            transform: translateX(0) !important;
            box-shadow: var(--shadow-lg);
            z-index: var(--z-mobile-drawer) !important;
          }
        }
      `}</style>
    </>
  );
}

// Badge Component
function Badge({
  children,
  variant = 'default',
  isActive = false,
}: {
  children: React.ReactNode;
  variant?: NavItem['badgeVariant'];
  isActive?: boolean;
}) {
  if (isActive) {
    return (
      <span
        style={{
          fontSize: '10.5px',
          fontWeight: 700,
          padding: '1px 6px',
          borderRadius: 'var(--radius-full)',
          backgroundColor: '#F3E3E7',
          color: '#71091E',
          marginLeft: '6px',
        }}
      >
        {children}
      </span>
    );
  }

  const styles: Record<string, { bg: string; color: string }> = {
    default: { bg: 'rgba(255, 255, 255, 0.15)', color: '#FFFFFF' },
    danger: { bg: 'rgba(240, 100, 115, 0.3)', color: '#FFD2D8' },
    warning: { bg: 'rgba(255, 180, 80, 0.3)', color: '#FFE0B8' },
    info: { bg: 'rgba(120, 180, 220, 0.3)', color: '#D4EEF9' },
  };

  const style = styles[variant] || styles.default;

  return (
    <span
      style={{
        fontSize: '10.5px',
        fontWeight: 600,
        padding: '1px 6px',
        borderRadius: 'var(--radius-full)',
        backgroundColor: style.bg,
        color: style.color,
        marginLeft: '6px',
      }}
    >
      {children}
    </span>
  );
}

function NavIcon({ name, active }: { name: string; active?: boolean }) {
  const props = {
    width: '16',
    height: '16',
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: active ? 'var(--text-sidebar-active)' : 'currentColor',
    strokeWidth: '2',
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };

  switch (name) {
    case 'grid':
      return (
        <svg {...props}>
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
        </svg>
      );
    case 'building':
      return (
        <svg {...props}>
          <rect x="4" y="2" width="16" height="20" rx="2" ry="2" />
          <line x1="9" y1="22" x2="9" y2="22.01" />
          <line x1="15" y1="22" x2="15" y2="22.01" />
          <line x1="9" y1="6" x2="9" y2="6.01" />
          <line x1="15" y1="6" x2="15" y2="6.01" />
          <line x1="9" y1="10" x2="9" y2="10.01" />
          <line x1="15" y1="10" x2="15" y2="10.01" />
        </svg>
      );
    case 'clipboard-check':
      return (
        <svg {...props}>
          <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
          <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
          <polyline points="9 14 11 16 15 11" />
        </svg>
      );
    case 'credit-card':
      return (
        <svg {...props}>
          <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
          <line x1="1" y1="10" x2="23" y2="10" />
        </svg>
      );
    case 'users':
      return (
        <svg {...props}>
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
        </svg>
      );
    case 'calendar':
      return (
        <svg {...props}>
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      );
    case 'bot':
      return (
        <svg {...props}>
          <rect x="3" y="11" width="18" height="10" rx="2" />
          <circle cx="12" cy="5" r="2" />
          <path d="M12 7v4" />
          <line x1="8" y1="16" x2="8" y2="16.01" />
          <line x1="16" y1="16" x2="16" y2="16.01" />
        </svg>
      );
    case 'database':
      return (
        <svg {...props}>
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
        </svg>
      );
    case 'settings':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      );
    case 'upload':
      return (
        <svg {...props}>
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
      );
    default:
      return null;
  }
}
