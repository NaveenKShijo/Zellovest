'use client';

import React from 'react';
import Link from 'next/link';
import { Vendor, VendorStatus, VendorCategory } from '@/types';

const STATUS_LABELS: Record<VendorStatus, string> = {
  compliant: 'Compliant',
  variance_flagged: 'Variance Flagged',
  up_for_renewal: 'Up for Renewal',
  maverick_detected: 'Maverick Detected',
  inactive: 'Inactive',
};

const STATUS_VARIANTS: Record<VendorStatus, 'success' | 'danger' | 'warning' | 'info' | 'default'> = {
  compliant: 'success',
  variance_flagged: 'danger',
  up_for_renewal: 'warning',
  maverick_detected: 'info',
  inactive: 'default',
};

const CATEGORY_COLORS: Record<VendorCategory, { bg: string; text: string }> = {
  'CRM & Sales': { bg: 'var(--color-brand-subtle)', text: 'var(--color-brand)' },
  'Design & Prototyping': { bg: '#F5E6FA', text: '#8B5E9E' },
  'Cloud Infrastructure': { bg: '#E8F0FE', text: '#3A6BCC' },
  'Productivity & Messaging': { bg: '#E6F4EA', text: '#2E7D32' },
  'Development Tools': { bg: '#F3E8FD', text: '#7B4FD6' },
  'HR & Finance': { bg: '#FFF3E0', text: '#E67E22' },
  'Marketing & Analytics': { bg: '#FCE4EC', text: '#C2185B' },
  'Security & Compliance': { bg: '#E8EAF6', text: '#3F51B5' },
  'Other': { bg: 'var(--border-subtle)', text: 'var(--text-muted)' },
};

export interface VendorTableProps {
  vendors: Vendor[];
  onSort?: (key: string, order: 'asc' | 'desc') => void;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  isLoading?: boolean;
  emptyMessage?: string;
}

export function VendorTable({
  vendors,
  onSort,
  sortBy,
  sortOrder,
  isLoading,
  emptyMessage = 'No vendors found. Add your first vendor to get started.',
}: VendorTableProps) {
  const formatCurrency = (amount: number, currency = 'USD') => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  };

  const handleSort = (key: string) => {
    if (!onSort) return;
    if (sortBy === key) {
      onSort(key, sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      onSort(key, 'asc');
    }
  };

  const renderSortIcon = (key: string) => {
    if (sortBy !== key) return null;
    return sortOrder === 'asc' ? ' ↑' : ' ↓';
  };

  if (isLoading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {[1, 2, 3].map((i) => (
          <div key={i} style={{ height: '60px', background: 'var(--bg-surface-tint)', borderRadius: 'var(--radius-md)', animation: 'pulse 1.5s ease-in-out infinite' }} />
        ))}
      </div>
    );
  }

  if (vendors.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: '48px', marginBottom: '16px', opacity: 0.5 }}>📦</div>
        <p style={{ fontSize: '16px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '8px' }}>
          No vendors found
        </p>
        <p style={{ fontSize: '13px' }}>{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div style={{ overflowX: 'auto', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
        <thead>
          <tr style={{ backgroundColor: 'var(--bg-surface-tint)', borderBottom: '1px solid var(--border-subtle)' }}>
            <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', cursor: onSort ? 'pointer' : 'default' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                Vendor
                {renderSortIcon('canonicalName')}
              </div>
            </th>
            <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', cursor: onSort ? 'pointer' : 'default' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                Category
                {renderSortIcon('categories')}
              </div>
            </th>
            <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '160px', cursor: onSort ? 'pointer' : 'default' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '4px' }}>
                Annual Spend
                {renderSortIcon('annualSpend')}
              </div>
            </th>
            <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '140px' }}>
              Active Contracts
            </th>
            <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '140px', cursor: onSort ? 'pointer' : 'default' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                Status
                {renderSortIcon('status')}
              </div>
            </th>
            <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '80px' }}>
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {vendors.map((vendor) => (
            <tr
              key={vendor.id}
              style={{
                borderBottom: '1px solid var(--border-subtle)',
                transition: 'background-color var(--transition-fast)',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-surface-hover)')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
            >
              <td style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--text-primary)' }}>
                <Link
                  href={`/vendors/${vendor.id}`}
                  style={{ textDecoration: 'none', color: 'inherit' }}
                >
                  {vendor.canonicalName}
                </Link>
                {vendor.domain && (
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px', fontWeight: 400 }}>
                    {vendor.domain}
                  </div>
                )}
              </td>
              <td style={{ padding: '14px 16px' }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {vendor.categories.slice(0, 3).map((cat, idx) => {
                    const colors = CATEGORY_COLORS[cat] || CATEGORY_COLORS.Other;
                    return (
                      <span
                        key={idx}
                        style={{
                          fontSize: '10.5px',
                          fontWeight: 600,
                          padding: '2px 8px',
                          borderRadius: 'var(--radius-full)',
                          backgroundColor: colors.bg,
                          color: colors.text,
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {cat}
                      </span>
                    );
                  })}
                  {vendor.categories.length > 3 && (
                    <span style={{ fontSize: '10.5px', color: 'var(--text-muted)', padding: '2px 6px' }}>
                      +{vendor.categories.length - 3}
                    </span>
                  )}
                </div>
              </td>
              <td style={{ padding: '14px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--color-brand)' }}>
                {formatCurrency(vendor.annualSpend, vendor.currency)}
              </td>
              <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '32px',
                    height: '32px',
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: 'var(--bg-surface-tint)',
                    color: 'var(--color-brand)',
                    fontWeight: 700,
                    fontSize: '13px',
                  }}
                >
                  {vendor.contractCount}
                </span>
              </td>
              <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    padding: '3px 10px',
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: `var(--color-${STATUS_VARIANTS[vendor.status]}-subtle)`,
                    color: `var(--color-${STATUS_VARIANTS[vendor.status]})`,
                    border: `1px solid var(--color-${STATUS_VARIANTS[vendor.status]}-border)`,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {STATUS_LABELS[vendor.status]}
                </span>
              </td>
              <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                <Link
                  href={`/vendors/${vendor.id}`}
                  style={{
                    padding: '6px 12px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12px',
                    fontWeight: 600,
                    color: 'var(--color-brand)',
                    backgroundColor: 'var(--bg-surface-tint)',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-brand-subtle)')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-surface-tint)')}
                >
                  View
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}