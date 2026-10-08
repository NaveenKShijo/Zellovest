'use client';

import React from 'react';

export default function LicensesPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Predictive Liscence Seat Forecasting
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
          Okta activity analysis identifying provisioned SaaS seats that have been inactive for &gt;60 days.
        </p>
      </div>

      <div
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border-subtle)',
          padding: '24px',
          boxShadow: 'var(--shadow-sm)',
        }}
      >
        <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px' }}>
          License Reclamation Dashboard
        </h2>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          Identified 109 inactive seats across Salesforce, Figma, and Zoom representing $38,400 in recoverable annual software spending.
        </p>
      </div>
    </div>
  );
}
