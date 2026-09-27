'use client';

import React from 'react';
import { Contract } from '@/types';

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  expired: 'Expired',
  superseded: 'Superseded',
  draft: 'Draft',
};

const STATUS_VARIANTS: Record<string, 'success' | 'danger' | 'warning' | 'info' | 'default'> = {
  active: 'success',
  expired: 'danger',
  superseded: 'warning',
  draft: 'info',
};

const UNIT_LABELS: Record<string, string> = {
  per_user: '/user',
  per_seat: '/seat',
  per_month: '/mo',
  per_year: '/yr',
  usage_based: '/usage',
  flat: 'flat',
};

export interface ContractTableProps {
  contracts: Contract[];
  isLoading?: boolean;
  onViewContract?: (contract: Contract) => void;
}

export function ContractTable({ contracts, isLoading, onViewContract }: ContractTableProps) {
  const formatCurrency = (amount: number, currency = 'USD') => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  };

  if (isLoading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {[1, 2, 3].map((i) => (
          <div key={i} style={{ height: '56px', background: 'var(--bg-surface-tint)', borderRadius: 'var(--radius-md)', animation: 'pulse 1.5s ease-in-out infinite' }} />
        ))}
      </div>
    );
  }

  if (contracts.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: '48px', marginBottom: '16px', opacity: 0.5 }}>📄</div>
        <p style={{ fontSize: '16px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '8px' }}>
          No contracts found
        </p>
        <p style={{ fontSize: '13px' }}>Upload a contract document to get started.</p>
      </div>
    );
  }

  return (
    <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', overflow: 'hidden' }}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
          <thead>
            <tr style={{ backgroundColor: 'var(--bg-surface-tint)', borderBottom: '1px solid var(--border-subtle)' }}>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>Product</th>
              <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '160px' }}>Unit Price</th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '120px' }}>Qty</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '180px' }}>Effective Period</th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '120px' }}>Status</th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '80px' }}>Version</th>
              <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '100px' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {contracts.map((contract) => (
              <tr
                key={contract.id}
                style={{
                  borderBottom: '1px solid var(--border-subtle)',
                  transition: 'background-color var(--transition-fast)',
                  cursor: onViewContract ? 'pointer' : 'default',
                }}
                onClick={() => onViewContract?.(contract)}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-surface-hover)')}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
              >
                <td style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {contract.product}
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--color-brand)' }}>
                  {formatCurrency(contract.unitPrice, contract.currency)}{UNIT_LABELS[contract.unitOfMeasurement]}
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                  {contract.quantity ? contract.quantity.toLocaleString() : '—'}
                </td>
                <td style={{ padding: '14px 16px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
                  <div>{formatDate(contract.effectiveFrom)}</div>
                  {contract.effectiveTo && (
                    <div style={{ color: 'var(--text-muted)', marginTop: '2px' }}>
                      → {formatDate(contract.effectiveTo)}
                    </div>
                  )}
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                  <span
                    style={{
                      fontSize: '11px',
                      fontWeight: 700,
                      padding: '3px 10px',
                      borderRadius: 'var(--radius-full)',
                      backgroundColor: `var(--color-${STATUS_VARIANTS[contract.status]}-subtle)`,
                      color: `var(--color-${STATUS_VARIANTS[contract.status]})`,
                      border: `1px solid var(--color-${STATUS_VARIANTS[contract.status]}-border)`,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {STATUS_LABELS[contract.status] || contract.status}
                  </span>
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)' }}>
                  v{contract.version}
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                  {contract.pdfUrl && (
                    <a
                      href={contract.pdfUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        padding: '6px 10px',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '12px',
                        fontWeight: 600,
                        color: 'var(--color-brand)',
                        backgroundColor: 'var(--bg-surface-tint)',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-brand-subtle)')}
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-surface-tint)')}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="16" y1="13" x2="8" y2="13" />
                        <line x1="16" y1="17" x2="8" y2="17" />
                        <polyline points="10 9 9 9 8 9" />
                      </svg>
                      View
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {contracts.some((c) => c.amendmentOfId) && (
        <div style={{ padding: '12px 16px', backgroundColor: 'var(--bg-surface-tint)', borderTop: '1px solid var(--border-tint)', fontSize: '12px', color: 'var(--text-secondary)' }}>
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Note:</span> Contracts with amendments show version history. Superseded versions are retained for audit trail per PRD §11.
        </div>
      )}
    </div>
  );
}