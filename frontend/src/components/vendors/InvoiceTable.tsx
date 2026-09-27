'use client';

import React from 'react';
import { Invoice } from '@/types';

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending Review',
  approved: 'Approved',
  paid: 'Paid',
  rejected: 'Rejected',
  flagged: 'Flagged',
};

const STATUS_VARIANTS: Record<string, 'success' | 'danger' | 'warning' | 'info' | 'default'> = {
  pending: 'info',
  approved: 'success',
  paid: 'success',
  rejected: 'danger',
  flagged: 'danger',
};

export interface InvoiceTableProps {
  invoices: Invoice[];
  isLoading?: boolean;
  onViewInvoice?: (invoice: Invoice) => void;
}

export function InvoiceTable({ invoices, isLoading, onViewInvoice }: InvoiceTableProps) {
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

  const formatVariance = (variance?: number) => {
    if (variance === undefined || variance === null) return '—';
    const sign = variance > 0 ? '+' : '';
    return `${sign}${variance.toFixed(1)}%`;
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

  if (invoices.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: '48px', marginBottom: '16px', opacity: 0.5 }}>🧾</div>
        <p style={{ fontSize: '16px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '8px' }}>
          No invoices found
        </p>
        <p style={{ fontSize: '13px' }}>Upload invoice documents to track compliance.</p>
      </div>
    );
  }

  return (
    <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', overflow: 'hidden' }}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
          <thead>
            <tr style={{ backgroundColor: 'var(--bg-surface-tint)', borderBottom: '1px solid var(--border-subtle)' }}>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>Invoice #</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '140px' }}>Date</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '140px' }}>Due Date</th>
              <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '160px' }}>Amount</th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '140px' }}>Variance</th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '140px' }}>Status</th>
              <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)', whiteSpace: 'nowrap', width: '100px' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((invoice) => (
              <tr
                key={invoice.id}
                style={{
                  borderBottom: '1px solid var(--border-subtle)',
                  transition: 'background-color var(--transition-fast)',
                  cursor: onViewInvoice ? 'pointer' : 'default',
                }}
                onClick={() => onViewInvoice?.(invoice)}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-surface-hover)')}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
              >
                <td style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {invoice.invoiceNumber}
                </td>
                <td style={{ padding: '14px 16px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
                  {formatDate(invoice.invoiceDate)}
                </td>
                <td style={{ padding: '14px 16px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
                  {formatDate(invoice.dueDate)}
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--color-brand)' }}>
                  {formatCurrency(invoice.amount, invoice.currency)}
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'center', fontWeight: 600 }}>
                  {invoice.variance !== undefined && invoice.variance !== null ? (
                    <span
                      style={{
                        color: invoice.variance > 0 ? 'var(--color-danger)' : invoice.variance < 0 ? 'var(--color-success)' : 'var(--text-secondary)',
                        fontFamily: 'monospace',
                      }}
                    >
                      {formatVariance(invoice.variance)}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>—</span>
                  )}
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                  <span
                    style={{
                      fontSize: '11px',
                      fontWeight: 700,
                      padding: '3px 10px',
                      borderRadius: 'var(--radius-full)',
                      backgroundColor: `var(--color-${STATUS_VARIANTS[invoice.status]}-subtle)`,
                      color: `var(--color-${STATUS_VARIANTS[invoice.status]})`,
                      border: `1px solid var(--color-${STATUS_VARIANTS[invoice.status]}-border)`,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {STATUS_LABELS[invoice.status] || invoice.status}
                  </span>
                </td>
                <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                  {invoice.pdfUrl && (
                    <a
                      href={invoice.pdfUrl}
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
      {invoices.some((i) => i.variance !== undefined && i.variance !== null && Math.abs(i.variance) > 0) && (
        <div style={{ padding: '12px 16px', backgroundColor: 'var(--color-danger-subtle)', borderTop: '1px solid var(--color-danger-border)', fontSize: '12px', color: 'var(--color-danger)' }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ display: 'inline-block', verticalAlign: 'middle', marginRight: '6px' }}>
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <strong>Variance detected:</strong> Some invoices show pricing discrepancies vs. contract terms. Review flagged items in AP Audit.
        </div>
      )}
    </div>
  );
}