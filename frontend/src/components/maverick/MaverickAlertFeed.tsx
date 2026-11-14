'use client';

import React from 'react';
import { MaverickAlertItem } from '@/types';
import { SemanticOverlapCard } from './SemanticOverlapCard';

interface MaverickAlertFeedProps {
  alerts: MaverickAlertItem[];
  onNotifyEmployee: (alertId: string) => void;
  onDismiss: (alertId: string) => void;
  onViewContract: (contractId: string) => void;
}

export function MaverickAlertFeed({
  alerts,
  onNotifyEmployee,
  onDismiss,
  onViewContract,
}: MaverickAlertFeedProps) {
  if (alerts.length === 0) {
    return (
      <div
        style={{
          textAlign: 'center',
          padding: '48px 24px',
          backgroundColor: '#FFFFFF',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border-subtle)',
          color: 'var(--text-muted)',
        }}
      >
        <div style={{ fontSize: '38px', marginBottom: '12px' }}>🛡️</div>
        <p style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
          No Maverick Spend Alerts Found
        </p>
        <p style={{ fontSize: '13px' }}>
          All card transactions either comply with approved software budgets or match configured filter criteria.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {alerts.map((alert) => (
        <SemanticOverlapCard
          key={alert.id}
          alert={alert}
          onNotifyEmployee={onNotifyEmployee}
          onDismiss={onDismiss}
          onViewContract={onViewContract}
        />
      ))}
    </div>
  );
}
