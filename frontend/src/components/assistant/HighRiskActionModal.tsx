'use client';

import React, { useState } from 'react';
import { ProposedAction, ActionPreviewResponse } from '@/types/askAi';

interface HighRiskActionModalProps {
  isOpen: boolean;
  action: ProposedAction | null;
  previewData: ActionPreviewResponse | null;
  isLoadingPreview: boolean;
  isExecuting: boolean;
  onClose: () => void;
  onConfirm: (note: string) => Promise<void>;
}

/**
 * HighRiskActionModal: Strict Human Confirmation Modal with Dry-Run Preview
 *
 * Implements PRD #24 & Module M8 Human-in-the-Loop Governance:
 * Consequential actions (approve invoice, cancel contract, remove licenses,
 * commit spend) require explicit confirmation and side-effect-free dry-run preview.
 */
export const HighRiskActionModal: React.FC<HighRiskActionModalProps> = ({
  isOpen,
  action,
  previewData,
  isLoadingPreview,
  isExecuting,
  onClose,
  onConfirm,
}) => {
  const [confirmationNote, setConfirmationNote] = useState('');
  const [isAcknowledged, setIsAcknowledged] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen || !action) return null;

  const preview = previewData?.preview || action.preview;
  const financialImpact = preview?.financial_impact;

  const handleAuthorize = async () => {
    if (!isAcknowledged) return;
    setError(null);
    try {
      await onConfirm(confirmationNote);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action authorization failed');
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(15, 12, 20, 0.72)',
        backdropFilter: 'blur(4px)',
        zIndex: 10000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
      }}
      onClick={() => {
        if (!isExecuting) onClose();
      }}
    >
      <div
        style={{
          width: 'min(94vw, 620px)',
          backgroundColor: '#fff',
          borderRadius: '16px',
          boxShadow: '0 25px 60px rgba(0, 0, 0, 0.35)',
          overflow: 'hidden',
          border: '1px solid #e5d8d8',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Warning Banner Header */}
        <div
          style={{
            padding: '16px 20px',
            backgroundColor: '#fff5f5',
            borderBottom: '1px solid #fed7d7',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '8px',
                backgroundColor: '#e53e3e',
                color: '#fff',
                display: 'grid',
                placeItems: 'center',
                fontSize: '16px',
                fontWeight: 800,
              }}
            >
              ⚠
            </span>
            <div>
              <div
                style={{
                  fontSize: '11px',
                  fontWeight: 800,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                  color: '#c53030',
                }}
              >
                High-Risk Procurement Action · Confirmation Required
              </div>
              <h3 style={{ margin: '2px 0 0', fontSize: '16px', fontWeight: 750, color: '#2d3748' }}>
                {action.tool.replace(/_/g, ' ').toUpperCase()}
              </h3>
            </div>
          </div>

          <span
            style={{
              fontSize: '11px',
              fontWeight: 750,
              backgroundColor: '#fed7d7',
              color: '#9b2c2c',
              padding: '4px 8px',
              borderRadius: '6px',
              border: '1px solid #feb2b2',
            }}
          >
            {action.server}
          </span>
        </div>

        {/* Modal Body */}
        <div style={{ padding: '20px', maxHeight: '70vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {error && (
            <div
              style={{
                padding: '10px 14px',
                borderRadius: '8px',
                backgroundColor: '#fff5f5',
                border: '1px solid #feb2b2',
                color: '#c53030',
                fontSize: '12.5px',
              }}
            >
              {error}
            </div>
          )}

          {/* Action Description */}
          <div>
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#718096', textTransform: 'uppercase' }}>
              Action Proposal
            </div>
            <p style={{ margin: '4px 0 0', fontSize: '13.5px', fontWeight: 600, color: '#2d3748', lineHeight: 1.5 }}>
              {action.description}
            </p>
          </div>

          {/* Dry Run Preview Box */}
          <div
            style={{
              padding: '14px',
              borderRadius: '10px',
              backgroundColor: '#f7fafc',
              border: '1px solid #e2e8f0',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '10px',
              }}
            >
              <span
                style={{
                  fontSize: '11.5px',
                  fontWeight: 750,
                  color: '#4a5568',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <span>✦ Dry-Run Preview</span>
                <span
                  style={{
                    fontSize: '10px',
                    backgroundColor: '#edf2f7',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    color: '#718096',
                  }}
                >
                  Side-Effect Free
                </span>
              </span>

              {isLoadingPreview && (
                <span style={{ fontSize: '11px', color: '#718096' }}>Calculating dry-run...</span>
              )}
            </div>

            {preview ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '12.5px' }}>
                <div>
                  <strong style={{ color: '#2d3748' }}>Summary: </strong>
                  <span style={{ color: '#4a5568' }}>{preview.summary}</span>
                </div>
                <div>
                  <strong style={{ color: '#2d3748' }}>Commercial Impact: </strong>
                  <span style={{ color: '#c53030', fontWeight: 600 }}>{preview.impact}</span>
                </div>

                {financialImpact !== undefined && financialImpact !== null && (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '8px 12px',
                      backgroundColor: '#edf2f7',
                      borderRadius: '6px',
                    }}
                  >
                    <span style={{ fontSize: '12px', color: '#4a5568', fontWeight: 600 }}>Financial Commitment:</span>
                    <span style={{ fontSize: '14px', fontWeight: 800, color: '#2d3748' }}>
                      ${typeof financialImpact === 'number' ? financialImpact.toLocaleString() : financialImpact}
                    </span>
                  </div>
                )}

                {preview.warnings && preview.warnings.length > 0 && (
                  <div style={{ marginTop: '4px' }}>
                    <div style={{ fontSize: '11px', fontWeight: 700, color: '#c53030', marginBottom: '4px' }}>
                      Critical Warnings:
                    </div>
                    <ul style={{ margin: 0, paddingLeft: '18px', color: '#742a2a', fontSize: '11.5px' }}>
                      {preview.warnings.map((w, idx) => (
                        <li key={idx} style={{ margin: '2px 0' }}>
                          {w}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: '12px', color: '#718096', fontStyle: 'italic' }}>
                Preview details computed against current active contracts.
              </div>
            )}
          </div>

          {/* Idempotency Key & Audit Info */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '11px',
              color: '#718096',
              padding: '6px 10px',
              backgroundColor: '#f8fafc',
              borderRadius: '6px',
              border: '1px solid #edf2f7',
            }}
          >
            <span>Idempotency Key:</span>
            <code style={{ fontFamily: 'Consolas, monospace', color: '#4a5568' }}>{action.idempotency_key}</code>
          </div>

          {/* Audit Note Input */}
          <div>
            <label
              htmlFor="audit-note"
              style={{ display: 'block', fontSize: '12px', fontWeight: 700, color: '#4a5568', marginBottom: '4px' }}
            >
              Audit Confirmation Reason (Required for AP & Legal compliance)
            </label>
            <textarea
              id="audit-note"
              rows={2}
              value={confirmationNote}
              onChange={(e) => setConfirmationNote(e.target.value)}
              placeholder="e.g. Approved per VP of Procurement sign-off on 2026-11-20"
              style={{
                width: '100%',
                padding: '8px 10px',
                fontSize: '12.5px',
                borderRadius: '8px',
                border: '1px solid #cbd5e0',
                color: '#2d3748',
                boxSizing: 'border-box',
                fontFamily: 'inherit',
              }}
            />
          </div>

          {/* Safety Checkbox */}
          <label
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '10px',
              cursor: 'pointer',
              padding: '10px',
              borderRadius: '8px',
              backgroundColor: '#fffaf0',
              border: '1px solid #feebc8',
              fontSize: '12px',
              color: '#744210',
            }}
          >
            <input
              type="checkbox"
              checked={isAcknowledged}
              onChange={(e) => setIsAcknowledged(e.target.checked)}
              style={{ marginTop: '2px', cursor: 'pointer' }}
            />
            <span>
              <strong>Explicit Human Confirmation:</strong> I have verified the dry-run parameters and authorize this
              consequential procurement action. I understand this action may commit financial spend or modify legal terms.
            </span>
          </label>
        </div>

        {/* Modal Footer */}
        <div
          style={{
            padding: '14px 20px',
            backgroundColor: '#f7fafc',
            borderTop: '1px solid #e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: '10px',
          }}
        >
          <button
            type="button"
            disabled={isExecuting}
            onClick={onClose}
            style={{
              padding: '8px 14px',
              borderRadius: '8px',
              border: '1px solid #cbd5e0',
              backgroundColor: '#fff',
              color: '#4a5568',
              fontSize: '12.5px',
              fontWeight: 650,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>

          <button
            type="button"
            disabled={!isAcknowledged || isExecuting}
            onClick={() => void handleAuthorize()}
            style={{
              padding: '8px 18px',
              borderRadius: '8px',
              border: 'none',
              backgroundColor: isAcknowledged ? '#e53e3e' : '#cbd5e0',
              color: '#fff',
              fontSize: '12.5px',
              fontWeight: 750,
              cursor: isAcknowledged && !isExecuting ? 'pointer' : 'not-allowed',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: isAcknowledged ? '0 2px 6px rgba(229, 62, 62, 0.4)' : 'none',
              transition: 'all 150ms ease',
            }}
          >
            {isExecuting ? 'Executing Action...' : 'Authorize & Execute'}
          </button>
        </div>
      </div>
    </div>
  );
};
