'use client';

import React, { useState } from 'react';
import { ProposedAction } from '@/types/askAi';

interface ActionCardProps {
  action: ProposedAction;
  onExecuteLowRisk: (action: ProposedAction) => Promise<void>;
  onRequestHighRiskConfirm: (action: ProposedAction) => void;
}

/**
 * ActionCard: Displays Low-Risk Inline Actions and High-Risk Confirmation Gated Actions
 *
 * Implements PRD #24:
 * - Low-risk actions can execute inline with a single click.
 * - High-risk actions require explicit human confirmation modal with dry-run preview.
 */
export const ActionCard: React.FC<ActionCardProps> = ({
  action,
  onExecuteLowRisk,
  onRequestHighRiskConfirm,
}) => {
  const [isRunningInline, setIsRunningInline] = useState(false);
  const isHighRisk = action.risk_class === 'high_risk' || action.requires_confirmation;
  const isExecuted = action.executed;

  const handleLowRiskClick = async () => {
    if (isRunningInline || isExecuted) return;
    setIsRunningInline(true);
    try {
      await onExecuteLowRisk(action);
    } finally {
      setIsRunningInline(false);
    }
  };

  return (
    <div
      style={{
        padding: '11px 14px',
        borderRadius: '10px',
        border: isHighRisk
          ? isExecuted
            ? '1px solid #c6f6d5'
            : '1px solid #feb2b2'
          : isExecuted
          ? '1px solid #c6f6d5'
          : '1px solid #e2d9e6',
        backgroundColor: isHighRisk
          ? isExecuted
            ? '#f0fff4'
            : '#fffaf0'
          : isExecuted
          ? '#f0fff4'
          : '#fcfbfe',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              fontSize: '10px',
              fontWeight: 800,
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              padding: '2px 7px',
              borderRadius: '4px',
              backgroundColor: isHighRisk ? '#fed7d7' : '#edf2f7',
              color: isHighRisk ? '#9b2c2c' : '#4a5568',
              border: isHighRisk ? '1px solid #feb2b2' : '1px solid #cbd5e0',
            }}
          >
            {isHighRisk ? 'HIGH RISK' : 'LOW RISK (INLINE)'}
          </span>

          <span
            style={{
              fontSize: '11px',
              fontWeight: 650,
              color: '#718096',
              fontFamily: 'Consolas, monospace',
            }}
          >
            {action.server} → {action.tool}
          </span>
        </div>

        {isExecuted && (
          <span
            style={{
              fontSize: '11px',
              fontWeight: 750,
              color: '#22543d',
              backgroundColor: '#c6f6d5',
              padding: '2px 8px',
              borderRadius: '999px',
            }}
          >
            ✓ Executed
          </span>
        )}
      </div>

      <div style={{ fontSize: '13px', fontWeight: 600, color: '#2d3748' }}>
        {action.description}
      </div>

      {action.error && (
        <div style={{ fontSize: '11.5px', color: '#c53030', backgroundColor: '#fff5f5', padding: '6px 8px', borderRadius: '4px' }}>
          {action.error}
        </div>
      )}

      {/* Button Row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '2px' }}>
        <span style={{ fontSize: '10.5px', color: '#a0aec0' }}>
          Idempotency: {action.idempotency_key.slice(0, 18)}…
        </span>

        {!isExecuted && (
          <div>
            {isHighRisk ? (
              <button
                type="button"
                onClick={() => onRequestHighRiskConfirm(action)}
                style={{
                  padding: '5px 12px',
                  borderRadius: '6px',
                  border: '1px solid #e53e3e',
                  backgroundColor: '#fff',
                  color: '#e53e3e',
                  fontSize: '11.5px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '5px',
                  transition: 'all 120ms ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = '#e53e3e';
                  e.currentTarget.style.color = '#fff';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = '#fff';
                  e.currentTarget.style.color = '#e53e3e';
                }}
              >
                <span>Review & Confirm</span>
                <span aria-hidden="true">⚠</span>
              </button>
            ) : (
              <button
                type="button"
                disabled={isRunningInline}
                onClick={() => void handleLowRiskClick()}
                style={{
                  padding: '5px 12px',
                  borderRadius: '6px',
                  border: '1px solid #8a526f',
                  backgroundColor: '#8a526f',
                  color: '#fff',
                  fontSize: '11.5px',
                  fontWeight: 650,
                  cursor: isRunningInline ? 'not-allowed' : 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '5px',
                }}
              >
                {isRunningInline ? (
                  <>
                    <span
                      style={{
                        width: '10px',
                        height: '10px',
                        border: '2px solid rgba(255,255,255,0.4)',
                        borderTopColor: '#fff',
                        borderRadius: '50%',
                        animation: 'spin 0.8s infinite linear',
                      }}
                    />
                    <span>Executing…</span>
                  </>
                ) : (
                  <>
                    <span>Execute Inline</span>
                    <span aria-hidden="true">→</span>
                  </>
                )}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
