'use client';

import React from 'react';
import { useToast } from '@/contexts/ToastContext';
import { ToastNotification, NotificationType } from '@/types';

/**
 * ToastContainer: Fixed floating container rendering live toasts.
 * 
 * Positioned in the bottom-right corner with a high z-index (100)
 * so it remains visible above tables, modals, and sticky headers.
 */

export function ToastContainer() {
  const { toasts, removeToast } = useToast();

  if (toasts.length === 0) return null;

  return (
    <aside
      aria-label="Notifications"
      style={{
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        zIndex: 'var(--z-toast)',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
        maxWidth: '400px',
        width: 'calc(100vw - 48px)',
        pointerEvents: 'none',
      }}
    >
      {toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} onDismiss={() => removeToast(toast.id)} />
      ))}
    </aside>
  );
}

// Muted organic theme tokens (Avoids bright neon colors)
const TOAST_THEMES: Record<
  NotificationType,
  {
    borderColor: string;
    iconColor: string;
    iconSvg: React.ReactNode;
  }
> = {
  success: {
    borderColor: 'var(--color-success)',
    iconColor: 'var(--color-success)',
    iconSvg: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
      </svg>
    ),
  },
  error: {
    borderColor: 'var(--color-danger)',
    iconColor: 'var(--color-danger)',
    iconSvg: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="15" y1="9" x2="9" y2="15" />
        <line x1="9" y1="9" x2="15" y2="15" />
      </svg>
    ),
  },
  warning: {
    borderColor: 'var(--color-warning)',
    iconColor: 'var(--color-warning)',
    iconSvg: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    ),
  },
  info: {
    borderColor: 'var(--color-info)',
    iconColor: 'var(--color-info)',
    iconSvg: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="16" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12.01" y2="8" />
      </svg>
    ),
  },
};

interface ToastCardProps {
  toast: ToastNotification;
  onDismiss: () => void;
}

function ToastCard({ toast, onDismiss }: ToastCardProps) {
  const theme = TOAST_THEMES[toast.type];
  const duration = toast.durationMs || 4500;

  return (
    <div
      role="status"
      style={{
        pointerEvents: 'auto',
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: '#FFFFFF',
        borderRadius: 'var(--radius-md)',
        boxShadow: 'var(--shadow-toast)',
        border: '1px solid var(--border-subtle)',
        borderLeft: `4px solid ${theme.borderColor}`,
        animation: 'toastSlideIn var(--transition-normal) ease-out forwards',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', padding: '13px 15px', gap: '12px' }}>
        {/* Semantic Icon */}
        <span style={{ color: theme.iconColor, flexShrink: 0, marginTop: '2px' }}>
          {theme.iconSvg}
        </span>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.3 }}>
            {toast.title}
          </div>
          {toast.message && (
            <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '3px', lineHeight: 1.4 }}>
              {toast.message}
            </div>
          )}

          {/* Optional Action Button */}
          {toast.action && (
            <button
              onClick={toast.action.onClick}
              style={{
                marginTop: '6px',
                fontSize: '12px',
                fontWeight: 600,
                color: theme.iconColor,
                textDecoration: 'underline',
                padding: 0,
              }}
            >
              {toast.action.label} →
            </button>
          )}
        </div>

        {/* Dismiss Button */}
        <button
          onClick={onDismiss}
          aria-label="Close notification"
          style={{
            color: 'var(--text-muted)',
            padding: '3px',
            borderRadius: 'var(--radius-sm)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text-primary)')}
          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      {/* Auto-Dismiss Timer Progress Indicator Bar */}
      {duration > 0 && (
        <div
          style={{
            height: '2.5px',
            backgroundColor: theme.borderColor,
            width: '100%',
            transformOrigin: 'left',
            animation: `shrinkWidth ${duration}ms linear forwards`,
          }}
        />
      )}

      <style>{`
        @keyframes shrinkWidth {
          from { transform: scaleX(1); }
          to { transform: scaleX(0); }
        }
      `}</style>
    </div>
  );
}
