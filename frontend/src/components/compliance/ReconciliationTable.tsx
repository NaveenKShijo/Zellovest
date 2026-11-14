'use client';

import React from 'react';
import { ReconciliationItem, ExceptionRuleType } from '@/types';

interface ReconciliationTableProps {
  items: ReconciliationItem[];
  totalInvoicesCount?: number;
  onSelectRow: (item: ReconciliationItem) => void;
  onLaunchInvestigation: (item: ReconciliationItem) => void;
}

const RULE_BADGE_STYLES: Record<
  ExceptionRuleType,
  { label: string; bg: string; color: string; border: string }
> = {
  price: {
    label: 'Price Creep',
    bg: 'var(--color-danger-subtle)',
    color: 'var(--color-danger)',
    border: 'var(--color-danger-border)',
  },
  quantity: {
    label: 'Quantity Tier Mismatch',
    bg: 'var(--color-warning-subtle)',
    color: 'var(--color-warning)',
    border: 'var(--color-warning-border)',
  },
  missing_po: {
    label: 'Missing PO',
    bg: '#FDF2E9',
    color: '#D35400',
    border: '#F5CBA7',
  },
  discount: {
    label: 'Discount Omission',
    bg: '#F4ECF7',
    color: '#8E44AD',
    border: '#D7BDE2',
  },
  tax: {
    label: 'Tax Discrepancy',
    bg: 'var(--color-info-subtle)',
    color: 'var(--color-info)',
    border: 'var(--color-info-border)',
  },
  freight: {
    label: 'Freight Rule',
    bg: '#EAECEE',
    color: '#2C3E50',
    border: '#D5D8DC',
  },
  date: {
    label: 'Date Window Mismatch',
    bg: '#E8F8F5',
    color: '#16A085',
    border: '#A3E4D7',
  },
  payment_term: {
    label: 'Payment Term Mismatch',
    bg: '#FEF9E7',
    color: '#B7950B',
    border: '#F9E79F',
  },
};

const STATUS_PILL_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  open: { bg: 'var(--color-danger-subtle)', color: 'var(--color-danger)', label: 'Open' },
  acknowledged: { bg: 'var(--color-warning-subtle)', color: 'var(--color-warning)', label: 'Acknowledged' },
  resolved: { bg: 'var(--color-success-subtle)', color: 'var(--color-success)', label: 'Resolved' },
  dismissed: { bg: 'var(--bg-surface-tint)', color: 'var(--text-muted)', label: 'Dismissed' },
};

export function ReconciliationTable({
  items,
  totalInvoicesCount = 0,
  onSelectRow,
  onLaunchInvestigation,
}: ReconciliationTableProps) {
  const formatCurrency = (val: number, currency = 'USD') =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format(val);

  if (items.length === 0) {
    const isZeroProcessed = totalInvoicesCount === 0;
    return (
      <div
        style={{
          textAlign: 'center',
          padding: '48px 24px',
          backgroundColor: '#FFFFFF',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border-subtle)',
          color: 'var(--text-muted)',
        }}
      >
        <div style={{ fontSize: '38px', marginBottom: '12px' }}>
          {isZeroProcessed ? '📄' : '✨'}
        </div>
        <p style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
          {isZeroProcessed ? 'No Invoices Processed' : 'No Reconciliation Exceptions (100% Compliant)'}
        </p>
        <p style={{ fontSize: '13px' }}>
          {isZeroProcessed
            ? 'Upload or process commercial invoices to run deterministic reconciliation against contracted terms.'
            : 'All processed invoices comply with contracted schedules, rates, and purchase orders.'}
        </p>
      </div>
    );
  }

  return (
    <div
      style={{
        overflowX: 'auto',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)',
        backgroundColor: '#FFFFFF',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
        <thead>
          <tr style={{ backgroundColor: 'var(--bg-surface-tint)', borderBottom: '1px solid var(--border-subtle)' }}>
            <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Invoice #
            </th>
            <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Vendor & Contract
            </th>
            <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Discrepancy ($)
            </th>
            <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Flag Reason
            </th>
            <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Status
            </th>
            <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const ruleStyle = RULE_BADGE_STYLES[item.primaryRule] || {
              label: item.ruleLabel,
              bg: 'var(--bg-surface-tint)',
              color: 'var(--text-secondary)',
              border: 'var(--border-subtle)',
            };
            const statusStyle = STATUS_PILL_STYLES[item.status] || STATUS_PILL_STYLES.open;

            return (
              <tr
                key={item.id}
                style={{
                  borderBottom: '1px solid var(--border-subtle)',
                  cursor: 'pointer',
                  transition: 'background-color var(--transition-fast)',
                }}
                onClick={() => onSelectRow(item)}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-surface-hover)')}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#FFFFFF')}
              >
                {/* Invoice ID & Date */}
                <td style={{ padding: '14px 16px' }}>
                  <div style={{ fontWeight: 700, color: 'var(--color-brand)' }}>{item.invoiceNumber}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                    Inv Date: {item.invoiceDate}
                  </div>
                </td>

                {/* Vendor & Contract */}
                <td style={{ padding: '14px 16px' }}>
                  <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{item.vendorName}</div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                    {item.contractNumber} • {item.contractTitle}
                  </div>
                </td>

                {/* Discrepancy Amount */}
                <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                  <div style={{ fontWeight: 700, color: 'var(--color-danger)', fontSize: '14px' }}>
                    +{formatCurrency(item.discrepancyAmount, item.currency)}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                    Total: {formatCurrency(item.totalAmount, item.currency)}
                  </div>
                </td>

                {/* Flag Reason Pill */}
                <td style={{ padding: '14px 16px' }}>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                      padding: '3px 10px',
                      borderRadius: 'var(--radius-full)',
                      fontSize: '11.5px',
                      fontWeight: 600,
                      backgroundColor: ruleStyle.bg,
                      color: ruleStyle.color,
                      border: `1px solid ${ruleStyle.border}`,
                    }}
                  >
                    <span>⚠️</span>
                    {ruleStyle.label}
                  </span>
                </td>

                {/* Status Pill */}
                <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                  <span
                    style={{
                      display: 'inline-block',
                      padding: '2px 9px',
                      borderRadius: 'var(--radius-full)',
                      fontSize: '11px',
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.4px',
                      backgroundColor: statusStyle.bg,
                      color: statusStyle.color,
                    }}
                  >
                    {statusStyle.label}
                  </span>
                </td>

                {/* Actions */}
                <td
                  style={{ padding: '14px 16px', textAlign: 'right' }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '8px' }}>
                    <button
                      onClick={() => onSelectRow(item)}
                      style={{
                        padding: '6px 12px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-strong)',
                        backgroundColor: '#FFFFFF',
                        fontSize: '12px',
                        fontWeight: 600,
                        color: 'var(--text-primary)',
                      }}
                    >
                      Compare Lines
                    </button>
                    <button
                      onClick={() => onLaunchInvestigation(item)}
                      title="Investigate discrepancy with Agent"
                      style={{
                        padding: '6px 10px',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: 'var(--bg-surface-tint)',
                        color: 'var(--color-brand)',
                        fontSize: '12px',
                        fontWeight: 600,
                        border: '1px solid var(--border-subtle)',
                      }}
                    >
                      ✨ Ask AI
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
