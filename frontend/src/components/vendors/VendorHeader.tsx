'use client';

import React from 'react';
import { Vendor, VendorCategory, VendorStatus } from '@/types';

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

const PAYMENT_TERMS_LABELS: Record<string, string> = {
  net_30: 'Net 30',
  net_45: 'Net 45',
  net_60: 'Net 60',
  custom: 'Custom',
};

export interface VendorHeaderProps {
  vendor: Vendor;
  onEdit?: () => void;
  onUploadDocument?: () => void;
}

export function VendorHeader({ vendor, onEdit, onUploadDocument }: VendorHeaderProps) {
  const formatCurrency = (amount: number, currency = 'USD') => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  };

  return (
    <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', padding: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '24px', flexWrap: 'wrap', marginBottom: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flex: 1, minWidth: 0 }}>
          <div
            style={{
              width: '56px',
              height: '56px',
              borderRadius: 'var(--radius-lg)',
              backgroundColor: 'var(--color-brand)',
              color: '#FFFFFF',
              fontWeight: 800,
              fontSize: '22px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              boxShadow: 'var(--shadow-md)',
            }}
          >
            {vendor.canonicalName.charAt(0).toUpperCase()}
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', flexWrap: 'wrap' }}>
              <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {vendor.canonicalName}
              </h1>
              {vendor.domain && (
                <span style={{ fontSize: '13px', color: 'var(--text-muted)', backgroundColor: 'var(--bg-app)', padding: '2px 8px', borderRadius: 'var(--radius-full)', fontWeight: 500 }}>
                  {vendor.domain}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '6px' }}>
              {vendor.categories.slice(0, 4).map((cat, idx) => {
                const colors = CATEGORY_COLORS[cat] || CATEGORY_COLORS.Other;
                return (
                  <span
                    key={idx}
                    style={{
                      fontSize: '11px',
                      fontWeight: 600,
                      padding: '3px 10px',
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
              {vendor.categories.length > 4 && (
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', padding: '3px 10px' }}>
                  +{vendor.categories.length - 4} more
                </span>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          {onUploadDocument && (
            <button
              onClick={onUploadDocument}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 16px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'var(--color-brand)',
                color: '#FFFFFF',
                fontSize: '13px',
                fontWeight: 600,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-brand-hover)')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-brand)')}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              Upload Document
            </button>
          )}
          {onEdit && (
            <button
              onClick={onEdit}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 16px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'var(--bg-surface-tint)',
                color: 'var(--color-brand)',
                fontSize: '13px',
                fontWeight: 600,
                border: '1px solid var(--border-tint)',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--border-tint)')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-surface-tint)')}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              Edit Vendor
            </button>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px', paddingTop: '20px', borderTop: '1px solid var(--border-subtle)' }}>
        <div>
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Annual Spend
          </div>
          <div style={{ fontSize: '28px', fontWeight: 800, color: 'var(--color-brand)', letterSpacing: '-0.5px', lineHeight: 1.2 }}>
            {formatCurrency(vendor.annualSpend, vendor.currency)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Active Contracts
          </div>
          <div style={{ fontSize: '28px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px', lineHeight: 1.2 }}>
            {vendor.contractCount}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Invoices (YTD)
          </div>
          <div style={{ fontSize: '28px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px', lineHeight: 1.2 }}>
            {vendor.invoiceCount}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Card Transactions
          </div>
          <div style={{ fontSize: '28px', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.5px', lineHeight: 1.2 }}>
            {vendor.transactionCount}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Payment Terms
          </div>
          <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.2 }}>
            {PAYMENT_TERMS_LABELS[vendor.paymentTerms] || vendor.paymentTerms}
            {vendor.paymentTerms === 'custom' && vendor.customPaymentTerms && (
              <span style={{ fontSize: '12px', color: 'var(--text-muted)', marginLeft: '8px' }}>
                ({vendor.customPaymentTerms})
              </span>
            )}
          </div>
        </div>
        <div>
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Status
          </div>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              fontSize: '12px',
              fontWeight: 700,
              padding: '4px 12px',
              borderRadius: 'var(--radius-full)',
              backgroundColor: `var(--color-${STATUS_VARIANTS[vendor.status]}-subtle)`,
              color: `var(--color-${STATUS_VARIANTS[vendor.status]})`,
              border: `1px solid var(--color-${STATUS_VARIANTS[vendor.status]}-border)`,
              whiteSpace: 'nowrap',
            }}
          >
            {STATUS_LABELS[vendor.status]}
          </span>
        </div>
      </div>

      {vendor.primaryContact && (
        <div style={{ marginTop: '20px', paddingTop: '20px', borderTop: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Primary Contact
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: 'var(--radius-full)',
                  backgroundColor: 'var(--color-brand)',
                  color: '#FFFFFF',
                  fontWeight: 700,
                  fontSize: '13px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {vendor.primaryContact.name.charAt(0).toUpperCase()}
              </div>
              <div>
                <div style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {vendor.primaryContact.name}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  {vendor.primaryContact.email}
                  {vendor.primaryContact.phone && ` • ${vendor.primaryContact.phone}`}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}