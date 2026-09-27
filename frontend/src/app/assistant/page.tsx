'use client';

import React from 'react';

export default function AssistantPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Procurement Investigation Agent
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
          Conversational AI agent that inspects contracts, amendments, card transactions, and invoices to explain commercial variances.
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
          Agent Workspace
        </h2>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          Ask questions across the entire procurement knowledge graph (e.g., &quot;Why does invoice INV-23891 charge $140/seat instead of $120/seat?&quot; or &quot;Show me all amendments signed with Salesforce in 2025&quot;).
        </p>
      </div>
    </div>
  );
}
