'use client';

import React, { useState } from 'react';
import { SaaSUtilizationItem } from '@/types';

interface WasteCalculatorWidgetProps {
  selectedApp: SaaSUtilizationItem;
}

export function WasteCalculatorWidget({ selectedApp }: WasteCalculatorWidgetProps) {
  const [reclamationPct, setReclamationPct] = useState<number>(100);
  const [inactivityThreshold, setInactivityThreshold] = useState<30 | 60 | 90>(60);

  // Inactive seats based on threshold
  const targetInactiveSeats =
    inactivityThreshold === 30
      ? selectedApp.inactive30dSeats + selectedApp.inactive60dSeats + selectedApp.inactive90dSeats
      : inactivityThreshold === 60
      ? selectedApp.inactive60dSeats + selectedApp.inactive90dSeats
      : selectedApp.inactive90dSeats;

  const seatsToReclaim = Math.round((targetInactiveSeats * reclamationPct) / 100);
  const calculatedSavings = seatsToReclaim * selectedApp.contractedUnitCost;

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
        gap: '18px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '18px' }}>🧮</span>
            <h3 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Interactive Waste & License Reclamation Calculator
            </h3>
          </div>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Calculates recoverable annual spend: <code>inactive seats &times; contracted unit cost</code> ({formatCurrency(selectedApp.contractedUnitCost)}/seat/yr).
          </p>
        </div>

        {/* Selected app tag */}
        <span
          style={{
            fontSize: '12px',
            fontWeight: 700,
            padding: '3px 10px',
            borderRadius: 'var(--radius-full)',
            backgroundColor: 'var(--bg-surface-tint)',
            color: 'var(--color-brand)',
            border: '1px solid var(--border-tint)',
          }}
        >
          Selected: {selectedApp.vendorName}
        </span>
      </div>

      {/* Calculator Controls */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '16px',
          backgroundColor: 'var(--bg-app)',
          padding: '16px',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        {/* Inactivity Threshold Button Group */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '8px' }}>
            Inactivity Inactivity Threshold:
          </label>
          <div style={{ display: 'flex', gap: '6px' }}>
            {([30, 60, 90] as const).map((days) => (
              <button
                key={days}
                onClick={() => setInactivityThreshold(days)}
                style={{
                  flex: 1,
                  padding: '7px 0',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '12px',
                  fontWeight: 600,
                  border: inactivityThreshold === days ? '1px solid var(--color-brand)' : '1px solid var(--border-strong)',
                  backgroundColor: inactivityThreshold === days ? 'var(--color-brand)' : '#FFFFFF',
                  color: inactivityThreshold === days ? '#FFFFFF' : 'var(--text-primary)',
                  cursor: 'pointer',
                  transition: 'all var(--transition-fast)',
                }}
              >
                &ge; {days} Days
              </button>
            ))}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px' }}>
            Identified: <strong>{targetInactiveSeats} seats</strong> inactive &ge; {inactivityThreshold} days
          </div>
        </div>

        {/* Reclamation Target Slider */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Reclamation Target:
            </label>
            <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-brand)' }}>
              {reclamationPct}%
            </span>
          </div>
          <input
            type="range"
            min="10"
            max="100"
            step="5"
            value={reclamationPct}
            onChange={(e) => setReclamationPct(Number(e.target.value))}
            style={{ width: '100%', accentColor: 'var(--color-brand)', cursor: 'pointer' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            <span>10% (Gentle)</span>
            <span>50% (Standard)</span>
            <span>100% (Full Deprovision)</span>
          </div>
        </div>

        {/* Instant Result Box */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            borderRadius: 'var(--radius-sm)',
            padding: '12px 16px',
            border: '1px solid var(--color-success-border)',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
          }}
        >
          <span style={{ fontSize: '11.5px', fontWeight: 600, color: 'var(--color-success)', textTransform: 'uppercase' }}>
            Recoverable Annual Spend
          </span>
          <div style={{ fontSize: '24px', fontWeight: 800, color: 'var(--color-success)', letterSpacing: '-0.4px', marginTop: '2px' }}>
            {formatCurrency(calculatedSavings)}
          </div>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            Deprovisioning {seatsToReclaim} inactive Okta accounts
          </span>
        </div>
      </div>
    </div>
  );
}
