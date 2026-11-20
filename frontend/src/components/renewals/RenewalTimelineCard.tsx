'use client';

import React from 'react';
import { UpcomingRenewal, RenewalBadgeUrgency } from '@/types';

interface RenewalTimelineCardProps {
  renewal: UpcomingRenewal;
  onOpenDossier: (renewal: UpcomingRenewal) => void;
  onLaunchAgent: (renewal: UpcomingRenewal) => void;
}

const BADGE_CONFIG: Record<
  RenewalBadgeUrgency,
  { label: string; bg: string; color: string; border: string }
> = {
  '30d': {
    label: 'Expires in ≤ 30 Days',
    bg: 'var(--color-danger)',
    color: '#FFFFFF',
    border: 'var(--color-danger)',
  },
  '60d': {
    label: 'Expires in ≤ 60 Days',
    bg: 'var(--color-danger-subtle)',
    color: 'var(--color-danger)',
    border: 'var(--color-danger-border)',
  },
  '90d': {
    label: 'Expires in ≤ 90 Days',
    bg: 'var(--color-warning-subtle)',
    color: 'var(--color-warning)',
    border: 'var(--color-warning-border)',
  },
  '120d': {
    label: 'Expires in ≤ 120 Days',
    bg: 'var(--color-info-subtle)',
    color: 'var(--color-info)',
    border: 'var(--color-info-border)',
  },
  future: {
    label: 'Planning Horizon (> 120d)',
    bg: 'var(--bg-app)',
    color: 'var(--text-secondary)',
    border: 'var(--border-strong)',
  },
};

export function RenewalTimelineCard({
  renewal,
  onOpenDossier,
  onLaunchAgent,
}: RenewalTimelineCardProps) {
  const badgeStyle = BADGE_CONFIG[renewal.badge] || BADGE_CONFIG.future;

  const formatCurrency = (val: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(val);

  return (
    <div
      style={{
        backgroundColor: '#FFFFFF',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-subtle)',
        padding: '24px',
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        flexDirection: 'column',
        gap: '18px',
        transition: 'all var(--transition-fast)',
      }}
    >
      {/* Top Bar: Urgency Badge & Notice Period */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {/* 30/60/90/120d Badge */}
          <span
            style={{
              fontSize: '11px',
              fontWeight: 800,
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
              padding: '3px 10px',
              borderRadius: 'var(--radius-full)',
              backgroundColor: badgeStyle.bg,
              color: badgeStyle.color,
              border: `1px solid ${badgeStyle.border}`,
            }}
          >
            {badgeStyle.label}
          </span>

          {/* Auto-renew flag */}
          {renewal.autoRenew ? (
            <span
              style={{
                fontSize: '11px',
                fontWeight: 700,
                padding: '2px 8px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: 'var(--color-warning-subtle)',
                color: 'var(--color-warning)',
                border: '1px solid var(--color-warning-border)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <span>⚠️</span>
              Auto-Renews ({renewal.noticePeriodDays}d Notice Required)
            </span>
          ) : (
            <span
              style={{
                fontSize: '11px',
                fontWeight: 600,
                padding: '2px 8px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: 'var(--bg-app)',
                color: 'var(--text-muted)',
              }}
            >
              Manual Renewal
            </span>
          )}
        </div>

        <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
          Renewal Date: <strong style={{ color: 'var(--text-primary)' }}>{renewal.renewalDate}</strong> ({renewal.daysUntilRenewal} days remaining)
        </div>
      </div>

      {/* Main Content Info */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '16px', alignItems: 'center' }}>
        {/* Vendor & Product */}
        <div>
          <h3 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {renewal.vendorName}
          </h3>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            {renewal.productName} • Contract: <code style={{ fontSize: '11.5px' }}>{renewal.contractNumber}</code>
          </p>
          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Lead: {renewal.assignedOwner}
          </div>
        </div>

        {/* Annual Spend & YoY */}
        <div>
          <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
            Annual Spend
          </span>
          <div style={{ fontSize: '17px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '2px' }}>
            {formatCurrency(renewal.annualSpend)}
          </div>
          <div style={{ fontSize: '11px', color: renewal.spendYoYPct > 10 ? 'var(--color-danger)' : 'var(--text-muted)', fontWeight: 600 }}>
            {renewal.spendYoYPct > 0 ? `+${renewal.spendYoYPct}%` : `${renewal.spendYoYPct}%`} YoY
          </div>
        </div>

        {/* Notice Deadline Warning */}
        <div>
          <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
            Notice Deadline
          </span>
          <div style={{ fontSize: '14.5px', fontWeight: 700, color: renewal.isNoticeWindowActive ? 'var(--color-danger)' : 'var(--text-primary)', marginTop: '3px' }}>
            {renewal.noticeDeadlineDate}
          </div>
          <div style={{ fontSize: '11px', color: renewal.isNoticeWindowActive ? 'var(--color-danger)' : 'var(--text-muted)', fontWeight: 600 }}>
            {renewal.daysUntilNoticeDeadline <= 0 ? 'Window Open / Urgent' : `${renewal.daysUntilNoticeDeadline}d remaining`}
          </div>
        </div>
      </div>

      {/* Action Footer */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px',
          paddingTop: '14px',
          borderTop: '1px solid var(--border-subtle)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
          <span style={{ fontSize: '14px' }}>🎯</span>
          <span>{renewal.keyLeveragePoints[0]}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={() => onOpenDossier(renewal)}
            style={{
              padding: '7px 14px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-strong)',
              backgroundColor: '#FFFFFF',
              color: 'var(--text-primary)',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Commercial Dossier
          </button>

          <button
            onClick={() => onLaunchAgent(renewal)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '7px 16px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--color-brand)',
              color: '#FFFFFF',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
              boxShadow: 'var(--shadow-sm)',
            }}
          >
            <span>🤖</span>
            Launch Renewal Agent
          </button>
        </div>
      </div>
    </div>
  );
}
