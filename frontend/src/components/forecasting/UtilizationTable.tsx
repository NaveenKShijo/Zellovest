'use client';

import React from 'react';
import { SaaSUtilizationItem } from '@/types';

interface UtilizationTableProps {
  items: SaaSUtilizationItem[];
  selectedAppId: string;
  onSelectApp: (item: SaaSUtilizationItem) => void;
}

export function UtilizationTable({
  items,
  selectedAppId,
  onSelectApp,
}: UtilizationTableProps) {
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
        boxShadow: 'var(--shadow-sm)',
        overflow: 'hidden',
      }}
    >
      <div style={{ padding: '18px 22px', borderBottom: '1px solid var(--border-subtle)' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
          Okta SaaS Utilization & Inactivity Signals (ML Feature Matrix)
        </h3>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
          Real-time IdP login cadence feeding the survival model to replace static zombie heuristics.
        </p>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
          <thead>
            <tr style={{ backgroundColor: 'var(--bg-surface-tint)', borderBottom: '1px solid var(--border-subtle)' }}>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Application & Vendor
              </th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Purchased vs Active
              </th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Utilization %
              </th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Inactive 30d
              </th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Inactive 60d
              </th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Inactive 90d+
              </th>
              <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Contract Cost / Seat
              </th>
              <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Recoverable Spend
              </th>
              <th style={{ padding: '12px 16px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)' }}>
                ML Action
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const isSelected = item.id === selectedAppId;
              return (
                <tr
                  key={item.id}
                  onClick={() => onSelectApp(item)}
                  style={{
                    borderBottom: '1px solid var(--border-subtle)',
                    backgroundColor: isSelected ? 'var(--bg-surface-tint)' : '#FFFFFF',
                    cursor: 'pointer',
                    transition: 'background-color var(--transition-fast)',
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) e.currentTarget.style.backgroundColor = 'var(--bg-surface-hover)';
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) e.currentTarget.style.backgroundColor = '#FFFFFF';
                  }}
                >
                  {/* Vendor / App */}
                  <td style={{ padding: '14px 16px' }}>
                    <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{item.vendorName}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                      {item.appCode}
                    </div>
                  </td>

                  {/* Purchased vs Active */}
                  <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                    <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{item.activeLogins}</span>
                    <span style={{ color: 'var(--text-muted)' }}> / {item.purchasedSeats}</span>
                  </td>

                  {/* Utilization % */}
                  <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-full)',
                        fontSize: '11.5px',
                        fontWeight: 700,
                        backgroundColor: item.utilizationRatePct < 75 ? 'var(--color-danger-subtle)' : 'var(--color-success-subtle)',
                        color: item.utilizationRatePct < 75 ? 'var(--color-danger)' : 'var(--color-success)',
                      }}
                    >
                      {item.utilizationRatePct.toFixed(1)}%
                    </span>
                  </td>

                  {/* 30d inactive */}
                  <td style={{ padding: '14px 16px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                    {item.inactive30dSeats} seats
                  </td>

                  {/* 60d inactive */}
                  <td style={{ padding: '14px 16px', textAlign: 'center', color: 'var(--color-warning)', fontWeight: 600 }}>
                    {item.inactive60dSeats} seats
                  </td>

                  {/* 90d inactive */}
                  <td style={{ padding: '14px 16px', textAlign: 'center', color: 'var(--color-danger)', fontWeight: 700 }}>
                    {item.inactive90dSeats} seats
                  </td>

                  {/* Contracted unit price */}
                  <td style={{ padding: '14px 16px', textAlign: 'right', color: 'var(--text-secondary)' }}>
                    {formatCurrency(item.contractedUnitCost)}/yr
                  </td>

                  {/* Recoverable Spend */}
                  <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                    <div style={{ fontWeight: 800, color: 'var(--color-success)', fontSize: '13.5px' }}>
                      +{formatCurrency(item.recoverableSpendAnnual)}
                    </div>
                  </td>

                  {/* Action button */}
                  <td style={{ padding: '14px 16px', textAlign: 'center' }}>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectApp(item);
                      }}
                      style={{
                        padding: '5px 12px',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: isSelected ? 'var(--color-brand)' : 'var(--bg-app)',
                        color: isSelected ? '#FFFFFF' : 'var(--text-primary)',
                        border: '1px solid var(--border-strong)',
                        fontSize: '11.5px',
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      {isSelected ? 'Viewing Model' : 'View Forecast'}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
