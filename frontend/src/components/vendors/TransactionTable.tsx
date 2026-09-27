'use client';

import React from 'react';
import { CardTransaction } from '@/types';

const CATEGORY_LABELS: Record<string, string> = {
  saas_subscription: 'SaaS Subscription',
  travel: 'Travel',
  meals: 'Meals',
  office_expenses: 'Office Expenses',
  other: 'Other',
};

const CATEGORY_VARIANTS: Record<string, 'success' | 'danger' | 'warning' | 'info' | 'default'> = {
  saas_subscription: 'warning',
  travel: 'info',
  meals: 'default',
  office_expenses: 'success',
  other: 'default',
};

export interface TransactionTableProps {
  transactions: CardTransaction[];
  isLoading?: boolean;
}

export function TransactionTable({ transactions, isLoading }: TransactionTableProps) {
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

  if (transactions.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: '48px', marginBottom: '16px', opacity: 0.5 }}>💳</div>
        <p style={{ fontSize: '16px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '8px' }}>
          No card transactions found
        </p>
        <p style={{ fontSize: '13px' }}>Connect Ramp or upload transactions to analyze spend.</p>
      </div>
    );
  }

  return (
    <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', overflow: 'hidden' }}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
          <thead>
            <tr style={{ backgroundColor: 'var(--bg-surface-tint)', borderBottom: '1px solid var(--border-subtle)' }}>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>Merchant</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '140px' }}>Date</th>
              <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '140px' }}>Amount</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '160px' }}>Employee / Dept</th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '140px' }}>Category</th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '120px' }}>Recurring</th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '100px' }}>Match</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((txn) => (
              <tr
                key={txn.id}
                style={{
                  borderBottom: '1px solid var(--border-subtle)',
                  transition: 'background-color var(--transition-fast)',
                  backgroundColor: txn.isRecurring && !txn.matchedVendorId ? 'var(--color-warning-subtle)' : 'transparent',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = txn.isRecurring && !txn.matchedVendorId ? 'var(--color-warning-subtle)' : 'var(--bg-surface-hover)')}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = txn.isRecurring && !txn.matchedVendorId ? 'var(--color-warning-subtle)' : 'transparent')}
              >
                <td style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {txn.merchantName}
                </td>
                <td style={{ padding: '14px 16px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
                  {formatDate(txn.transactionDate)}
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--color-brand)' }}>
                  {formatCurrency(txn.amount, txn.currency)}
                </td>
                <td style={{ padding: '14px 16px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
                  <div>{txn.employeeName || '—'}</div>
                  {txn.department && <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{txn.department}</div>}
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                  <span
                    style={{
                      fontSize: '11px',
                      fontWeight: 600,
                      padding: '3px 10px',
                      borderRadius: 'var(--radius-full)',
                      backgroundColor: `var(--color-${CATEGORY_VARIANTS[txn.category]}-subtle)`,
                      color: `var(--color-${CATEGORY_VARIANTS[txn.category]})`,
                      border: `1px solid var(--color-${CATEGORY_VARIANTS[txn.category]}-border)`,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {CATEGORY_LABELS[txn.category] || txn.category}
                  </span>
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                  {txn.isRecurring ? (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        fontSize: '11px',
                        fontWeight: 600,
                        color: 'var(--color-warning)',
                      }}
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="1 4 1 10 7 10" />
                        <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
                      </svg>
                      Recurring
                      {txn.recurrenceInterval && ` (~${txn.recurrenceInterval}d)`}
                    </span>
                  ) : (
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>—</span>
                  )}
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                  {txn.matchedVendorId ? (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        fontSize: '11px',
                        fontWeight: 600,
                        color: 'var(--color-success)',
                      }}
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                      Matched
                    </span>
                  ) : txn.isRecurring ? (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        fontSize: '11px',
                        fontWeight: 600,
                        color: 'var(--color-warning)',
                      }}
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="12" y1="8" x2="12" y2="12" />
                        <line x1="12" y1="16" x2="12.01" y2="16" />
                      </svg>
                      Unmanaged
                    </span>
                  ) : (
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {transactions.some((t) => t.isRecurring && !t.matchedVendorId) && (
        <div style={{ padding: '12px 16px', backgroundColor: 'var(--color-warning-subtle)', borderTop: '1px solid var(--color-warning-border)', fontSize: '12px', color: 'var(--color-warning)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <strong>Maverick spend detected:</strong> {transactions.filter((t) => t.isRecurring && !t.matchedVendorId).length} recurring transaction(s) not linked to approved vendors. Review in Maverick Spend.
        </div>
      )}
    </div>
  );
}