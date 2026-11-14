'use client';

import React from 'react';
import { APAuditKPIs } from '@/types';

interface APAuditKPIsBarProps {
  kpis: APAuditKPIs;
}

export function APAuditKPIsBar({ kpis }: APAuditKPIsBarProps) {
  const formatCurrency = (val: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(val);

  const auditedCount = kpis.cleanInvoicesCount + kpis.exceptionInvoicesCount;
  const hasAudited = auditedCount > 0;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
        gap: '16px',
      }}
    >
      {/* 1. Total Invoiced */}
      <div
        style={{
          backgroundColor: '#FFFFFF',
          borderRadius: 'var(--radius-lg)',
          padding: '20px 22px',
          border: '1px solid var(--border-subtle)',
          boxShadow: 'var(--shadow-sm)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Total Invoiced
          </span>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--bg-surface-tint)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--color-brand)',
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
          </div>
        </div>
        <div>
          <div style={{ fontSize: '26px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
            {formatCurrency(kpis.totalInvoicedAmount)}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Across {kpis.totalInvoicesCount} commercial invoice{kpis.totalInvoicesCount === 1 ? '' : 's'} in ledger
          </div>
        </div>
      </div>

      {/* 2. Flagged Discrepancies ($) */}
      <div
        style={{
          backgroundColor: '#FFFFFF',
          borderRadius: 'var(--radius-lg)',
          padding: '20px 22px',
          border: '1px solid var(--color-danger-border)',
          boxShadow: 'var(--shadow-sm)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-danger)' }}>
            Flagged Discrepancy ($)
          </span>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--color-danger-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--color-danger)',
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
        </div>
        <div>
          <div style={{ fontSize: '26px', fontWeight: 700, color: 'var(--color-danger)', letterSpacing: '-0.5px' }}>
            {formatCurrency(kpis.flaggedDiscrepancyAmount)}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
            {kpis.exceptionInvoicesCount} invoice{kpis.exceptionInvoicesCount === 1 ? '' : 's'} queued for credit reclamation
          </div>
        </div>
      </div>

      {/* 3. Clean vs Exception Ratio */}
      <div
        style={{
          backgroundColor: '#FFFFFF',
          borderRadius: 'var(--radius-lg)',
          padding: '20px 22px',
          border: '1px solid var(--border-subtle)',
          boxShadow: 'var(--shadow-sm)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Compliance Rate
          </span>
          <span
            style={{
              fontSize: '12px',
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: 'var(--radius-full)',
              backgroundColor: hasAudited
                ? kpis.cleanRatePct >= 80
                  ? 'var(--color-success-subtle)'
                  : 'var(--color-warning-subtle)'
                : 'var(--bg-surface-tint)',
              color: hasAudited
                ? kpis.cleanRatePct >= 80
                  ? 'var(--color-success)'
                  : 'var(--color-warning)'
                : 'var(--text-muted)',
            }}
          >
            {hasAudited ? `${kpis.cleanRatePct}% Clean` : 'No Audits Run'}
          </span>
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
            <span style={{ fontSize: '26px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
              {kpis.cleanInvoicesCount}
            </span>
            <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>clean /</span>
            <span style={{ fontSize: '20px', fontWeight: 700, color: 'var(--color-danger)' }}>
              {kpis.exceptionInvoicesCount}
            </span>
            <span style={{ fontSize: '13px', color: 'var(--color-danger)' }}>exceptions</span>
          </div>

          {/* Ratio bar */}
          <div
            style={{
              width: '100%',
              height: '8px',
              backgroundColor: hasAudited ? 'var(--color-danger-subtle)' : 'var(--bg-surface-tint)',
              borderRadius: 'var(--radius-full)',
              marginTop: '10px',
              overflow: 'hidden',
              display: 'flex',
            }}
          >
            {hasAudited ? (
              <>
                <div
                  style={{
                    width: `${kpis.cleanRatePct}%`,
                    height: '100%',
                    backgroundColor: 'var(--color-success)',
                    borderRadius: 'var(--radius-full) 0 0 var(--radius-full)',
                  }}
                />
                <div
                  style={{
                    width: `${100 - kpis.cleanRatePct}%`,
                    height: '100%',
                    backgroundColor: 'var(--color-danger)',
                  }}
                />
              </>
            ) : (
              <div style={{ width: '100%', height: '100%', backgroundColor: 'var(--border-subtle)' }} />
            )}
          </div>
        </div>
      </div>

      {/* 4. Audit Coverage (Audited vs Unreconciled) */}
      <div
        style={{
          backgroundColor: '#FFFFFF',
          borderRadius: 'var(--radius-lg)',
          padding: '20px 22px',
          border: '1px solid var(--border-subtle)',
          boxShadow: 'var(--shadow-sm)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Reconciliation Scope
          </span>
          <span
            style={{
              fontSize: '12px',
              fontWeight: 600,
              padding: '2px 8px',
              borderRadius: 'var(--radius-full)',
              backgroundColor: kpis.unreconciledInvoicesCount > 0 ? 'var(--color-info-subtle)' : 'var(--bg-surface-tint)',
              color: kpis.unreconciledInvoicesCount > 0 ? 'var(--color-info)' : 'var(--text-muted)',
            }}
          >
            {kpis.unreconciledInvoicesCount > 0 ? `${kpis.unreconciledInvoicesCount} Pending` : 'Up to Date'}
          </span>
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
            <span style={{ fontSize: '26px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
              {auditedCount}
            </span>
            <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>audited /</span>
            <span style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-secondary)' }}>
              {kpis.unreconciledInvoicesCount}
            </span>
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>unreconciled</span>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
            {kpis.unreconciledInvoicesCount === 0
              ? 'All invoices audited against contracts'
              : 'Unreconciled invoices lack matching contracts or POs'}
          </div>
        </div>
      </div>
    </div>
  );
}
