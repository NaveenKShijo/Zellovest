'use client';

import React from 'react';
import { useToast } from '@/contexts/ToastContext';
import { SystemAlert, NotificationType } from '@/types';

/**
 * AlertBanner: Renders persistent system-level alerts and announcements.
 * 
 * Styled with warm butter tones and muted status indicators.
 */

export function AlertBanner() {
  const { alerts, dismissAlert } = useToast();

  if (alerts.length === 0) return null;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        padding: '10px 28px 0 28px',
        backgroundColor: 'var(--bg-app)',
      }}
    >
      {alerts.map((alert) => (
        <SingleAlert key={alert.id} alert={alert} onDismiss={() => dismissAlert(alert.id)} />
      ))}
    </div>
  );
}

// Muted, non-bright alert themes
const ALERT_STYLES: Record<
  NotificationType,
  {
    bg: string;
    border: string;
    color: string;
    accent: string;
  }
> = {
  warning: {
    bg: 'var(--color-warning-subtle)',
    border: 'var(--color-warning-border)',
    color: '#8A5314',
    accent: 'var(--color-warning)',
  },
  error: {
    bg: 'var(--color-danger-subtle)',
    border: 'var(--color-danger-border)',
    color: '#8B3230',
    accent: 'var(--color-danger)',
  },
  info: {
    bg: 'var(--color-info-subtle)',
    border: 'var(--color-info-border)',
    color: '#345768',
    accent: 'var(--color-info)',
  },
  success: {
    bg: 'var(--color-success-subtle)',
    border: 'var(--color-success-border)',
    color: '#2E5539',
    accent: 'var(--color-success)',
  },
};

function SingleAlert({ alert, onDismiss }: { alert: SystemAlert; onDismiss: () => void }) {
  const style = ALERT_STYLES[alert.type];

  return (
    <div
      role="alert"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '9px 14px',
        borderRadius: 'var(--radius-md)',
        backgroundColor: style.bg,
        border: `1px solid ${style.border}`,
        color: style.color,
        fontSize: '13px',
        animation: 'bannerSlideDown var(--transition-normal) ease-out',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '9px', flex: 1 }}>
        <span
          style={{
            display: 'inline-block',
            width: '7px',
            height: '7px',
            borderRadius: 'var(--radius-full)',
            backgroundColor: style.accent,
            flexShrink: 0,
          }}
        />
        <div>
          <strong>{alert.title}:</strong> {alert.message}
          <span style={{ fontSize: '11.5px', opacity: 0.7, marginLeft: '8px' }}>
            ({alert.timestamp})
          </span>
        </div>
      </div>

      {alert.dismissible !== false && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss alert"
          style={{
            background: 'none',
            border: 'none',
            color: style.color,
            padding: '2px 6px',
            cursor: 'pointer',
            fontWeight: 700,
            fontSize: '13px',
            opacity: 0.75,
          }}
          onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
          onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.75')}
        >
          ✕
        </button>
      )}
    </div>
  );
}
