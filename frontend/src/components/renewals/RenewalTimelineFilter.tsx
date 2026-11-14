'use client';

import React from 'react';
import { RenewalBadgeUrgency } from '@/types';

interface RenewalTimelineFilterProps {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  selectedBadge: RenewalBadgeUrgency | 'all';
  onBadgeChange: (badge: RenewalBadgeUrgency | 'all') => void;
  autoRenewOnly: boolean;
  onAutoRenewOnlyChange: (val: boolean) => void;
}

export function RenewalTimelineFilter({
  searchQuery,
  onSearchChange,
  selectedBadge,
  onBadgeChange,
  autoRenewOnly,
  onAutoRenewOnlyChange,
}: RenewalTimelineFilterProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '12px',
        alignItems: 'center',
        justifyContent: 'space-between',
        backgroundColor: '#FFFFFF',
        padding: '14px 18px',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)',
      }}
    >
      {/* Search */}
      <div style={{ position: 'relative', minWidth: '260px', flex: '1 1 260px' }}>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Filter renewals by vendor, product, or owner..."
          style={{
            width: '100%',
            padding: '9px 12px 9px 36px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-strong)',
            backgroundColor: 'var(--bg-app)',
            fontSize: '13px',
            color: 'var(--text-primary)',
          }}
        />
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            position: 'absolute',
            left: '12px',
            top: '50%',
            transform: 'translateY(-50%)',
            color: 'var(--text-muted)',
          }}
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        {/* Countdown Badge Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label htmlFor="renewal-urgency-filter" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Urgency Horizon:
          </label>
          <select
            id="renewal-urgency-filter"
            value={selectedBadge}
            onChange={(e) => onBadgeChange(e.target.value as RenewalBadgeUrgency | 'all')}
            style={{
              padding: '8px 12px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-strong)',
              backgroundColor: '#FFFFFF',
              fontSize: '12.5px',
              color: 'var(--text-primary)',
              cursor: 'pointer',
            }}
          >
            <option value="all">All Horizons (30d - 120d+)</option>
            <option value="30d">≤ 30 Days (Urgent)</option>
            <option value="60d">≤ 60 Days (Approaching)</option>
            <option value="90d">≤ 90 Days (Active Planning)</option>
            <option value="120d">≤ 120 Days (Preparation)</option>
            <option value="future">&gt; 120 Days (Future)</option>
          </select>
        </div>

        {/* Auto-renew checkbox toggle */}
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '12.5px',
            color: 'var(--text-primary)',
            cursor: 'pointer',
            padding: '6px 12px',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: autoRenewOnly ? 'var(--color-warning-subtle)' : 'var(--bg-app)',
            border: autoRenewOnly ? '1px solid var(--color-warning-border)' : '1px solid var(--border-subtle)',
          }}
        >
          <input
            type="checkbox"
            checked={autoRenewOnly}
            onChange={(e) => onAutoRenewOnlyChange(e.target.checked)}
            style={{ accentColor: 'var(--color-warning)' }}
          />
          <span style={{ fontWeight: autoRenewOnly ? 700 : 500 }}>
            Auto-Renew Clauses Only
          </span>
        </label>
      </div>
    </div>
  );
}
