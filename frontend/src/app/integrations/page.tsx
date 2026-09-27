'use client';

import React from 'react';

export default function IntegrationsPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Data Ingestion & Integrations
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
          Connect corporate card streams, identity usage, and contract document repositories.
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
        <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '16px' }}>
          Configured Connectors
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px' }}>
          <ConnectorCard title="Ramp Developer API" description="Ingesting corporate card transactions & cadence" status="Connected" />
          <ConnectorCard title="Okta Identity Cloud" description="Synchronizing user activity & provisioned seats" status="Connected" />
          <ConnectorCard title="Google Drive" description="Continuous PDF ingestion for Document AI" status="Active Listener" />
        </div>
      </div>
    </div>
  );
}

function ConnectorCard({ title, description, status }: { title: string; description: string; status: string }) {
  return (
    <div style={{ padding: '16px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-surface-warm)', border: '1px solid var(--border-subtle)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
        <span style={{ fontWeight: 700, fontSize: '14px', color: 'var(--text-primary)' }}>{title}</span>
        <span style={{ fontSize: '11px', fontWeight: 700, padding: '2px 7px', borderRadius: 'var(--radius-full)', backgroundColor: 'var(--color-success-subtle)', color: 'var(--color-success)', border: '1px solid var(--color-success-border)' }}>
          {status}
        </span>
      </div>
      <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', margin: 0 }}>{description}</p>
    </div>
  );
}
