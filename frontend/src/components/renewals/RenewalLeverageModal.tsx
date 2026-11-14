'use client';

import React from 'react';
import { UpcomingRenewal } from '@/types';

interface RenewalLeverageModalProps {
  renewal: UpcomingRenewal | null;
  isOpen: boolean;
  onClose: () => void;
  onLaunchRenewalAgent: (renewal: UpcomingRenewal) => void;
}

export function RenewalLeverageModal({
  renewal,
  isOpen,
  onClose,
  onLaunchRenewalAgent,
}: RenewalLeverageModalProps) {
  if (!isOpen || !renewal) return null;

  const formatCurrency = (val: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(val);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(41, 18, 23, 0.65)',
        backdropFilter: 'blur(4px)',
        zIndex: 'var(--z-modal)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: '#FFFFFF',
          borderRadius: 'var(--radius-lg)',
          width: '100%',
          maxWidth: '840px',
          maxHeight: '90vh',
          overflowY: 'auto',
          boxShadow: 'var(--shadow-lg)',
          border: '1px solid var(--border-subtle)',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          style={{
            padding: '24px 28px',
            borderBottom: '1px solid var(--border-subtle)',
            backgroundColor: 'var(--bg-surface-tint)',
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  padding: '2px 8px',
                  borderRadius: 'var(--radius-full)',
                  backgroundColor: 'var(--color-brand)',
                  color: '#FFFFFF',
                }}
              >
                Renewal Agent Dossier
              </span>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                Target Expiration: <strong>{renewal.renewalDate}</strong> ({renewal.daysUntilRenewal} days remaining)
              </span>
            </div>
            <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.3px' }}>
              {renewal.vendorName} — Commercial Negotiation Leverage
            </h2>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Product: <strong>{renewal.productName}</strong> • Contract: <strong>{renewal.contractNumber}</strong>
            </p>
          </div>

          <button
            onClick={onClose}
            aria-label="Close modal"
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-full)',
              border: '1px solid var(--border-subtle)',
              backgroundColor: '#FFFFFF',
              color: 'var(--text-secondary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
            }}
          >
            ✕
          </button>
        </div>

        {/* Modal Content */}
        <div style={{ padding: '24px 28px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* Key Metrics Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '12px' }}>
            <div style={{ padding: '14px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontWeight: 600 }}>CURRENT ARR</span>
              <div style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-primary)', marginTop: '2px' }}>
                {formatCurrency(renewal.annualSpend)}
              </div>
            </div>

            <div style={{ padding: '14px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontWeight: 600 }}>SPEND YoY</span>
              <div style={{ fontSize: '18px', fontWeight: 800, color: renewal.spendYoYPct > 10 ? 'var(--color-danger)' : 'var(--text-primary)', marginTop: '2px' }}>
                {renewal.spendYoYPct > 0 ? `+${renewal.spendYoYPct}%` : `${renewal.spendYoYPct}%`}
              </div>
            </div>

            <div style={{ padding: '14px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontWeight: 600 }}>OKTA UTILIZATION</span>
              <div style={{ fontSize: '18px', fontWeight: 800, color: renewal.utilizationPct < 80 ? 'var(--color-danger)' : 'var(--color-success)', marginTop: '2px' }}>
                {renewal.utilizationPct}%
              </div>
            </div>

            <div style={{ padding: '14px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
              <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontWeight: 600 }}>NOTICE DEADLINE</span>
              <div style={{ fontSize: '15px', fontWeight: 700, color: renewal.isNoticeWindowActive ? 'var(--color-danger)' : 'var(--text-primary)', marginTop: '4px' }}>
                {renewal.noticeDeadlineDate}
              </div>
            </div>
          </div>

          {/* Auto-renew alert if applicable */}
          {renewal.autoRenew && (
            <div
              style={{
                backgroundColor: 'var(--color-warning-subtle)',
                border: '1px solid var(--color-warning-border)',
                borderRadius: 'var(--radius-md)',
                padding: '14px 18px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
              }}
            >
              <span style={{ fontSize: '20px' }}>⚠️</span>
              <div>
                <strong style={{ fontSize: '13.5px', color: 'var(--color-warning)' }}>
                  Auto-Renewal Clause Detected
                </strong>
                <p style={{ fontSize: '12.5px', color: 'var(--text-primary)', marginTop: '2px' }}>
                  Contract will automatically renew for another 12-month term unless formal written opt-out notice is transmitted at least <strong>{renewal.noticePeriodDays} days</strong> prior to expiration.
                </p>
              </div>
            </div>
          )}

          {/* Key Leverage Points */}
          <div>
            <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '10px' }}>
              Identified Commercial Leverage Points (Zellovest Intelligence):
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {renewal.keyLeveragePoints.map((pt, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '10px',
                    padding: '12px 14px',
                    borderRadius: 'var(--radius-sm)',
                    backgroundColor: '#FFFFFF',
                    border: '1px solid var(--border-subtle)',
                  }}
                >
                  <span style={{ color: 'var(--color-brand)', fontWeight: 700, fontSize: '14px' }}>✓</span>
                  <span style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.4 }}>{pt}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div
          style={{
            padding: '16px 28px',
            borderTop: '1px solid var(--border-subtle)',
            backgroundColor: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: '12px',
          }}
        >
          <button
            onClick={onClose}
            style={{
              padding: '8px 18px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-strong)',
              backgroundColor: '#FFFFFF',
              color: 'var(--text-primary)',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Close
          </button>

          <button
            onClick={() => onLaunchRenewalAgent(renewal)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 20px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--color-brand)',
              color: '#FFFFFF',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              boxShadow: 'var(--shadow-sm)',
            }}
          >
            <span>🤖</span>
            Dispatch Renewal Negotiation Agent
          </button>
        </div>
      </div>
    </div>
  );
}
