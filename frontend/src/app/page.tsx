'use client';

import React from 'react';
import { useLayout } from '@/contexts/LayoutContext';
import { useToast } from '@/contexts/ToastContext';

export default function OverviewDashboardPage() {
  const { isSidebarCollapsed, toggleSidebar } = useLayout();
  const { notify, addAlert } = useToast();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      
      {/* 1. TOP ROW: 4 KPI CARDS (Matching the reference image) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
        
        {/* Card 1: Total Spend */}
        <KpiCard
          label="Total Monitored Spend"
          value="$4.28M"
          icon={(
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="5" width="20" height="14" rx="2" />
              <line x1="2" y1="10" x2="22" y2="10" />
            </svg>
          )}
        />

        {/* Card 2: AP Leakage */}
        <KpiCard
          label="AP Audit Leakage"
          value="$48.6K"
          icon={(
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
              <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
            </svg>
          )}
        />

        {/* Card 3: Maverick Spend */}
        <KpiCard
          label="Maverick SaaS Spend"
          value="$14.2K"
          icon={(
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
          )}
        />

        {/* Card 4: Zombie Licenses */}
        <KpiCard
          label="Zombie Inactive Seats"
          value="109"
          icon={(
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="20" x2="18" y2="10" />
              <line x1="12" y1="20" x2="12" y2="4" />
              <line x1="6" y1="20" x2="6" y2="14" />
            </svg>
          )}
        />

      </div>

      {/* 2. MIDDLE ROW: CHARTS & BREAKDOWN (Matching reference image) */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '20px' }}>
        
        {/* Left: Monthly Spend & Audit Trends Line Chart Card */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            borderRadius: 'var(--radius-lg)',
            padding: '24px',
            border: '1px solid var(--border-subtle)',
            boxShadow: 'var(--shadow-sm)',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h2 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Monthly Spend & Reconciliation Trends
            </h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: '14px', fontSize: '11.5px', color: 'var(--text-secondary)' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: 'var(--radius-full)', backgroundColor: '#71091E' }} />
                Contracted Spend
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: 'var(--radius-full)', backgroundColor: '#D77286' }} />
                Billed Invoices
              </span>
            </div>
          </div>

          {/* SVG Line Chart Representation */}
          <div style={{ width: '100%', height: '220px', position: 'relative' }}>
            <svg viewBox="0 0 700 220" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
              {/* Horizontal Gridlines */}
              <line x1="40" y1="20" x2="680" y2="20" stroke="#F4E5E8" strokeWidth="1" strokeDasharray="4 4" />
              <line x1="40" y1="65" x2="680" y2="65" stroke="#F4E5E8" strokeWidth="1" strokeDasharray="4 4" />
              <line x1="40" y1="110" x2="680" y2="110" stroke="#F4E5E8" strokeWidth="1" strokeDasharray="4 4" />
              <line x1="40" y1="155" x2="680" y2="155" stroke="#F4E5E8" strokeWidth="1" strokeDasharray="4 4" />
              <line x1="40" y1="200" x2="680" y2="200" stroke="#E8CED4" strokeWidth="1" />

              {/* Y Axis Labels */}
              <text x="5" y="24" fontSize="10" fill="#9E7D84">1400</text>
              <text x="5" y="69" fontSize="10" fill="#9E7D84">1200</text>
              <text x="5" y="114" fontSize="10" fill="#9E7D84">1000</text>
              <text x="10" y="159" fontSize="10" fill="#9E7D84">800</text>
              <text x="10" y="204" fontSize="10" fill="#9E7D84">600</text>

              {/* Secondary Dusty Rose Line (Billed Invoices) */}
              <polyline
                fill="none"
                stroke="#D77286"
                strokeWidth="2.5"
                points="50,150 125,120 200,105 275,115 350,75 425,70 500,100 575,135 650,90"
              />

              {/* Primary Deep Velvet Burgundy Line (Contracted Baseline) */}
              <polyline
                fill="none"
                stroke="#71091E"
                strokeWidth="3"
                points="50,180 125,110 200,165 275,120 350,135 425,70 500,160 575,40 650,85"
              />

              {/* Data points */}
              {[[50,180],[125,110],[200,165],[275,120],[350,135],[425,70],[500,160],[575,40],[650,85]].map(([cx, cy], i) => (
                <circle key={i} cx={cx} cy={cy} r="3.5" fill="#71091E" stroke="#FFFFFF" strokeWidth="1.5" />
              ))}

              {/* X Axis Month Labels */}
              <text x="45" y="218" fontSize="10" fill="#9E7D84">Jan</text>
              <text x="115" y="218" fontSize="10" fill="#9E7D84">Feb</text>
              <text x="190" y="218" fontSize="10" fill="#9E7D84">Mar</text>
              <text x="265" y="218" fontSize="10" fill="#9E7D84">Apr</text>
              <text x="340" y="218" fontSize="10" fill="#9E7D84">May</text>
              <text x="415" y="218" fontSize="10" fill="#9E7D84">Jun</text>
              <text x="490" y="218" fontSize="10" fill="#9E7D84">Jul</text>
              <text x="565" y="218" fontSize="10" fill="#9E7D84">Aug</text>
              <text x="640" y="218" fontSize="10" fill="#9E7D84">Sep</text>
            </svg>
          </div>
        </div>

        {/* Right Column: Donut + Bar Chart Cards */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* Top Donut / Pie Chart: Traffic / Spend Sources */}
          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: 'var(--radius-lg)',
              padding: '20px 24px',
              border: '1px solid var(--border-subtle)',
              boxShadow: 'var(--shadow-sm)',
            }}
          >
            <h2 style={{ fontSize: '14.5px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '12px' }}>
              Spend Sources
            </h2>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              
              {/* SVG Pie Chart */}
              <div style={{ width: '100px', height: '100px' }}>
                <svg viewBox="0 0 32 32" style={{ width: '100%', height: '100%', transform: 'rotate(-90deg)' }}>
                  <circle r="16" cx="16" cy="16" fill="#F1B3BE" />
                  <circle r="16" cx="16" cy="16" fill="transparent" stroke="#D77286" strokeWidth="32" strokeDasharray="60 100" />
                  <circle r="16" cx="16" cy="16" fill="transparent" stroke="#71091E" strokeWidth="32" strokeDasharray="35 100" />
                </svg>
              </div>

              {/* Legend */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: 'var(--radius-full)', backgroundColor: '#71091E' }} />
                  ERP Contracts (52%)
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: 'var(--radius-full)', backgroundColor: '#D77286' }} />
                  Ramp Cards (34%)
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: 'var(--radius-full)', backgroundColor: '#F1B3BE' }} />
                  Direct Invoices (14%)
                </span>
              </div>
            </div>
          </div>

          {/* Bottom Bar Chart: Spend by Department */}
          <div
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: 'var(--radius-lg)',
              padding: '20px 24px',
              border: '1px solid var(--border-subtle)',
              boxShadow: 'var(--shadow-sm)',
            }}
          >
            <h2 style={{ fontSize: '14.5px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '10px' }}>
              Spend by Department
            </h2>
            <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', height: '70px', padding: '0 8px 10px 8px', borderBottom: '1px solid var(--border-subtle)' }}>
              {[
                { h: 35, c: '#E598A7', l: 'Jan' },
                { h: 58, c: '#71091E', l: 'Feb' },
                { h: 42, c: '#E598A7', l: 'Mar' },
                { h: 65, c: '#D77286', l: 'Apr' },
                { h: 72, c: '#71091E', l: 'May' },
                { h: 48, c: '#D77286', l: 'Jun' },
              ].map((bar, idx) => (
                <div key={idx} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
                  <div style={{ width: '18px', height: `${bar.h}px`, backgroundColor: bar.c, borderRadius: '3px 3px 0 0' }} />
                  <span style={{ fontSize: '10px', color: '#9E7D84' }}>{bar.l}</span>
                </div>
              ))}
            </div>
          </div>

        </div>
      </div>

      {/* 3. BOTTOM ROW: RECENT ALERTS (Matching the reference image) */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
            Recent Alerts
          </h2>
          <div style={{ display: 'flex', gap: '6px' }}>
            <button style={{ padding: '4px 8px', borderRadius: '4px', backgroundColor: '#FFFFFF', border: '1px solid var(--border-subtle)', color: 'var(--text-secondary)', fontSize: '12px' }}>
              &lt;
            </button>
            <button style={{ padding: '4px 8px', borderRadius: '4px', backgroundColor: '#FFFFFF', border: '1px solid var(--border-subtle)', color: 'var(--text-secondary)', fontSize: '12px' }}>
              &gt;
            </button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px' }}>
          
          <AlertCard
            message="Contract renewal clause for Salesforce automatically initiates in 45 days. Notice deadline: May 15."
            timestamp="20 minutes ago"
          />

          <AlertCard
            message="Deterministic AP Audit flagged $4,800 pricing discrepancy on Invoice #INV-23891 vs Master Service Agreement."
            timestamp="40 minutes ago"
          />

          <AlertCard
            message="Unmanaged $20/mo Cursor.sh subscription detected on Ramp card with 91% semantic overlap to contracted Copilot."
            timestamp="2 hours ago"
          />

        </div>
      </div>

      {/* 4. INTERACTIVE TEST CONTROLS (Easily accessible for validation) */}
      <div
        style={{
          backgroundColor: '#FFFFFF',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border-subtle)',
          padding: '20px 24px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>
          State Testing Controls:
        </span>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button
            onClick={toggleSidebar}
            style={{
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--bg-surface-tint)',
              color: 'var(--color-brand)',
              fontSize: '12px',
              fontWeight: 600,
            }}
          >
            Toggle Sidebar ({isSidebarCollapsed ? 'Expand' : 'Collapse'})
          </button>
          <button
            onClick={() => notify.success('Reconciliation Completed', 'All 18 new invoices matched against active contracts.')}
            style={{
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--color-success)',
              color: '#FFFFFF',
              fontSize: '12px',
              fontWeight: 600,
            }}
          >
            Trigger Success Toast
          </button>
          <button
            onClick={() => notify.error('Variance Detected: +16.7%', 'Vendor charged $140/seat instead of contracted $120/seat.')}
            style={{
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--color-brand)',
              color: '#FFFFFF',
              fontSize: '12px',
              fontWeight: 600,
            }}
          >
            Trigger Variance Error
          </button>
          <button
            onClick={() => addAlert({
              type: 'warning',
              title: 'Ramp Card Ingestion',
              message: '14 new corporate card transactions received via webhook.',
              dismissible: true,
            })}
            style={{
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: '#F2E0E4',
              color: 'var(--color-brand)',
              fontSize: '12px',
              fontWeight: 600,
            }}
          >
            Trigger Top Banner
          </button>
        </div>
      </div>

    </div>
  );
}

// KPI Metric Card with the deep burgundy square icon from the reference image
function KpiCard({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <div
      style={{
        backgroundColor: 'var(--bg-surface-tint)',
        borderRadius: 'var(--radius-md)',
        padding: '16px 18px',
        display: 'flex',
        alignItems: 'center',
        gap: '14px',
        border: '1px solid var(--border-tint)',
      }}
    >
      {/* Deep Burgundy Square Icon Container */}
      <div
        style={{
          width: '36px',
          height: '36px',
          borderRadius: '8px',
          backgroundColor: '#71091E',
          color: '#FFFFFF',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        {icon}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <span style={{ fontSize: '11.5px', color: 'var(--text-secondary)', fontWeight: 500 }}>
          {label}
        </span>
        <span style={{ fontSize: '22px', fontWeight: 800, color: '#71091E', letterSpacing: '-0.5px', lineHeight: 1.2 }}>
          {value}
        </span>
      </div>
    </div>
  );
}

// Recent Alert Horizontal Card from bottom row of reference image
function AlertCard({
  message,
  timestamp,
}: {
  message: string;
  timestamp: string;
}) {
  return (
    <div
      style={{
        backgroundColor: '#F5E7EA',
        borderRadius: 'var(--radius-md)',
        padding: '16px 18px',
        border: '1px solid var(--border-tint)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        gap: '10px',
      }}
    >
      <p style={{ fontSize: '12.5px', color: 'var(--text-primary)', lineHeight: 1.45, margin: 0 }}>
        {message}
      </p>
      <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 500 }}>
        {timestamp}
      </span>
    </div>
  );
}
