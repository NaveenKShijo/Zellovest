'use client';

import React from 'react';
import { DataGap } from '@/types/askAi';

interface DataGapsAlertProps {
  dataGaps?: DataGap[];
  confirmedZeros?: string[];
}

/**
 * DataGapsAlert: Rigorously distinguishes Unavailable Data from Confirmed Zero
 * per PRD 25.8 & Module M8 evidence-first principles.
 *
 * In commercial procurement, "no unmanaged spend detected" (verified zero)
 * is fundamentally different from "Ramp API connector is offline" (unavailable data).
 */
export const DataGapsAlert: React.FC<DataGapsAlertProps> = ({ dataGaps = [], confirmedZeros = [] }) => {
  if (dataGaps.length === 0 && confirmedZeros.length === 0) return null;

  return (
    <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {/* 1. Confirmed Zero Notices (Verified absence of anomalies) */}
      {confirmedZeros.map((msg, idx) => (
        <div
          key={`zero-${idx}`}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: '9px',
            padding: '8px 12px',
            borderRadius: '8px',
            backgroundColor: '#f1f8f3',
            border: '1px solid #cce5d4',
            color: '#1b5e20',
            fontSize: '12px',
          }}
        >
          <span style={{ fontSize: '14px', flexShrink: 0 }}>✓</span>
          <div>
            <span style={{ fontWeight: 700, marginRight: '4px' }}>Confirmed Zero:</span>
            <span>{msg}</span>
          </div>
        </div>
      ))}

      {/* 2. Unavailable Data Gaps (Explicitly flagged missing integrations/data) */}
      {dataGaps.map((gap, idx) => (
        <div
          key={`gap-${idx}`}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: '10px',
            padding: '10px 13px',
            borderRadius: '8px',
            backgroundColor: '#fff8e6',
            border: '1px solid #fedc96',
            color: '#8c5800',
            fontSize: '12px',
          }}
        >
          <span style={{ fontSize: '15px', flexShrink: 0, marginTop: '-1px' }}>⚠</span>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '3px' }}>
              <span
                style={{
                  fontWeight: 750,
                  fontSize: '11px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                  color: '#9e5200',
                }}
              >
                Unavailable Data — Not Confirmed Zero
              </span>
              {gap.tool && (
                <code
                  style={{
                    fontSize: '10.5px',
                    backgroundColor: '#faebd0',
                    padding: '1px 5px',
                    borderRadius: '4px',
                  }}
                >
                  {gap.tool}
                </code>
              )}
            </div>
            <p style={{ margin: 0, lineHeight: 1.5, color: '#68450c' }}>{gap.message}</p>
          </div>
        </div>
      ))}
    </div>
  );
};
