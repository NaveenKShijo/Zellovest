'use client';

import React from 'react';
import { MaverickAlertItem } from '@/types';

interface SemanticOverlapCardProps {
  alert: MaverickAlertItem;
  onNotifyEmployee?: (alertId: string) => void;
  onDismiss: (alertId: string) => void;
  onViewContract: (contractId: string) => void;
}

export function SemanticOverlapCard({
  alert,
  onDismiss,
}: SemanticOverlapCardProps) {
  const { overlap, jevScores } = alert;
  const isHighMatch = (overlap?.cosineSimilarity ?? 0) >= 0.85;

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
        gap: '20px',
      }}
    >
      {/* Header: Unmanaged Transaction & Jev p-scores */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
            <span
              style={{
                fontSize: '11px',
                fontWeight: 700,
                textTransform: 'uppercase',
                padding: '2px 8px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: 'var(--color-warning-subtle)',
                color: 'var(--color-warning)',
                border: '1px solid var(--color-warning-border)',
              }}
            >
              Ramp Card • {alert.cadenceDescription}
            </span>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Last 4: •••• {alert.cardLast4}
            </span>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>•</span>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Swipe Date: {alert.transactionDate}
            </span>
          </div>

          <h3 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {alert.merchantName} ({formatCurrency(alert.amount)}/mo)
          </h3>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Expensed by <strong>{alert.employeeName}</strong> ({alert.employeeEmail}) • <strong>{alert.department}</strong>
          </p>
        </div>

        {/* Jev Probabilistic Decision Badge */}
        <div
          style={{
            backgroundColor: 'var(--bg-app)',
            borderRadius: 'var(--radius-md)',
            padding: '10px 14px',
            border: '1px solid var(--border-subtle)',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            minWidth: '220px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11.5px' }}>
            <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Jev AI System One:</span>
            <span style={{ color: 'var(--color-brand)', fontWeight: 700 }}>Decision Verified</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
            <span style={{ color: 'var(--text-muted)' }}>is_unmanaged_saas:</span>
            <strong style={{ color: 'var(--color-danger)' }}>p = {jevScores.isSaasScore.toFixed(2)}</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
            <span style={{ color: 'var(--text-muted)' }}>warrants_procurement:</span>
            <strong style={{ color: 'var(--color-danger)' }}>p = {jevScores.warrantsReviewScore.toFixed(2)}</strong>
          </div>
        </div>
      </div>

      {/* Semantic Overlap Comparison Box */}
      <div
        style={{
          backgroundColor: 'var(--bg-surface-tint)',
          borderRadius: 'var(--radius-md)',
          padding: '18px 20px',
          border: '1px solid var(--border-tint)',
          display: 'grid',
          gridTemplateColumns: overlap ? '1fr auto 1fr' : '1fr',
          gap: '20px',
          alignItems: 'center',
        }}
      >
        {/* Left: Unmanaged Tool */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div style={{ fontSize: '11.5px', textTransform: 'uppercase', fontWeight: 700, color: 'var(--color-warning)' }}>
            Unmanaged Card Tool
          </div>
          <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {overlap?.unmanagedTool || alert.merchantName}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Category: {overlap?.unmanagedCategory || 'Software'}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--color-danger)', fontWeight: 600, marginTop: '2px' }}>
            Annual Run-Rate: {formatCurrency(alert.amount * 12)}/yr
          </div>
        </div>

        {overlap && <>
        {/* Center: Cosine Similarity Indicator */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '8px 16px',
            backgroundColor: '#FFFFFF',
            borderRadius: 'var(--radius-full)',
            border: `2px solid ${isHighMatch ? 'var(--color-brand)' : 'var(--border-strong)'}`,
            boxShadow: 'var(--shadow-sm)',
            minWidth: '130px',
          }}
        >
          <div style={{ fontSize: '10.5px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
            Semantic Overlap
          </div>
          <div style={{ fontSize: '17px', fontWeight: 800, color: 'var(--color-brand)' }}>
            {(overlap.cosineSimilarity * 100).toFixed(0)}% Match
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
            Cosine: {overlap.cosineSimilarity.toFixed(2)}
          </div>
        </div>

        {/* Right: Approved Enterprise Alternative */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', textAlign: 'right' }}>
          <div style={{ fontSize: '11.5px', textTransform: 'uppercase', fontWeight: 700, color: 'var(--color-success)' }}>
            Approved Enterprise License
          </div>
          <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {overlap.approvedAlternative}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Contracted with: {overlap.approvedVendorName}
          </div>
        </div>
        </>}
      </div>

      {/* Shared Capabilities Pill List */}
      {overlap && overlap.sharedCapabilities.length > 0 && <div>
        <div style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px' }}>
          Overlapping Feature Capabilities (Vector Embedding Match):
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          {overlap.sharedCapabilities.map((cap, idx) => (
            <span
              key={idx}
              style={{
                fontSize: '11.5px',
                padding: '4px 10px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: '#FFFFFF',
                border: '1px solid var(--border-strong)',
                color: 'var(--text-primary)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <span style={{ color: 'var(--color-brand)', fontWeight: 700 }}>✓</span>
              {cap}
            </span>
          ))}
        </div>
      </div>}

      {/* Recommended Action & Action Triggers */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px',
          paddingTop: '16px',
          borderTop: '1px solid var(--border-subtle)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
          <span style={{ fontSize: '15px' }}>💡</span>
          <span>{overlap?.recommendedAction || 'Procurement review recommended.'}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {alert.status === 'open' && (
            <button
              onClick={() => onDismiss(alert.id)}
              style={{
                padding: '7px 14px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-strong)',
                backgroundColor: '#FFFFFF',
                fontSize: '12px',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                cursor: 'pointer',
              }}
            >
              Approve Exception
            </button>
          )}

          {alert.status === 'notified' && (
            <span
              style={{
                padding: '7px 14px',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: 'var(--color-info-subtle)',
                color: 'var(--color-info)',
                fontSize: '12px',
                fontWeight: 600,
                border: '1px solid var(--color-info-border)',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <span>📨</span>
              Employee Notified via Slack (MCP-3)
            </span>
          )}

          {alert.status === 'migrated' && (
            <span
              style={{
                padding: '7px 14px',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: 'var(--color-success-subtle)',
                color: 'var(--color-success)',
                fontSize: '12px',
                fontWeight: 600,
                border: '1px solid var(--color-success-border)',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <span>✓</span>
              Migrated to Enterprise Seat
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
