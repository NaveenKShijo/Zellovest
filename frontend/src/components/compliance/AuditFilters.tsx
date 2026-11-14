'use client';

import React from 'react';
import { ExceptionRuleType, AuditExceptionStatus } from '@/types';

interface AuditFiltersProps {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  selectedRule: ExceptionRuleType | 'all';
  onRuleChange: (rule: ExceptionRuleType | 'all') => void;
  selectedStatus: AuditExceptionStatus | 'all';
  onStatusChange: (status: AuditExceptionStatus | 'all') => void;
}

export function AuditFilters({
  searchQuery,
  onSearchChange,
  selectedRule,
  onRuleChange,
  selectedStatus,
  onStatusChange,
}: AuditFiltersProps) {
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
      {/* Search Input */}
      <div style={{ position: 'relative', minWidth: '280px', flex: '1 1 280px' }}>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Filter by invoice #, vendor name, or contract..."
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

      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
        {/* Rule Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label htmlFor="rule-filter" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Flag Reason:
          </label>
          <select
            id="rule-filter"
            value={selectedRule}
            onChange={(e) => onRuleChange(e.target.value as ExceptionRuleType | 'all')}
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
            <option value="all">All Discrepancy Rules</option>
            <option value="price">Price Creep</option>
            <option value="quantity">Quantity Tier Mismatch</option>
            <option value="missing_po">Missing PO</option>
            <option value="discount">Discount Omission</option>
            <option value="tax">Tax Exemption</option>
            <option value="date">Date Window Mismatch</option>
          </select>
        </div>

        {/* Status Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label htmlFor="status-filter" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Status:
          </label>
          <select
            id="status-filter"
            value={selectedStatus}
            onChange={(e) => onStatusChange(e.target.value as AuditExceptionStatus | 'all')}
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
            <option value="all">All Statuses</option>
            <option value="open">Open (Needs Action)</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
            <option value="dismissed">Dismissed</option>
          </select>
        </div>
      </div>
    </div>
  );
}
