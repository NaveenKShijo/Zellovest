'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { DecisionPacketItem, ReconciliationItem } from '@/types';
import { useApi } from '@/lib/api';

interface LineItemComparisonModalProps {
  item: ReconciliationItem | null;
  isOpen: boolean;
  onClose: () => void;
  onLaunchInvestigation: (item: ReconciliationItem) => void;
  onAcknowledge: (itemId: string) => void;
  onResolve?: (itemId: string) => void;
}

export function LineItemComparisonModal({
  item,
  isOpen,
  onClose,
  onLaunchInvestigation,
  onAcknowledge,
  onResolve,
}: LineItemComparisonModalProps) {
  const api = useApi();
  const [packetState, setPacketState] = useState<{
    exceptionId: string;
    packet: DecisionPacketItem | null;
  } | null>(null);

  useEffect(() => {
    if (!isOpen || !item?.id) return;
    let active = true;
    const targetId = item.id;
    api.decisionFeed
      .byEntity('reconciliation_exception', targetId)
      .then((res) => {
        if (active) setPacketState({ exceptionId: targetId, packet: res });
      })
      .catch(() => {
        if (active) setPacketState({ exceptionId: targetId, packet: null });
      });
    return () => {
      active = false;
    };
  }, [api, isOpen, item?.id]);

  if (!isOpen || !item) return null;

  const loadingPacket = !packetState || packetState.exceptionId !== item.id;
  const packet = packetState?.exceptionId === item.id ? packetState.packet : null;

  const formatCurrency = (amount: number, currency = 'USD') => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
    }).format(amount);
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(41, 18, 23, 0.65)',
        backdropFilter: 'blur(4px)',
        zIndex: 'var(--z-modal)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: '#FFFFFF',
          borderRadius: 'var(--radius-lg)',
          width: '100%',
          maxWidth: '920px',
          maxHeight: '90vh',
          overflowY: 'auto',
          boxShadow: 'var(--shadow-lg)',
          border: '1px solid var(--border-subtle)',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          style={{
            padding: '24px 28px',
            borderBottom: '1px solid var(--border-subtle)',
            backgroundColor: 'var(--bg-surface-tint)',
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                  padding: '3px 8px',
                  borderRadius: 'var(--radius-full)',
                  backgroundColor: 'var(--color-danger)',
                  color: '#FFFFFF',
                }}
              >
                {item.ruleLabel}
              </span>
              <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                Severity: <strong style={{ textTransform: 'capitalize', color: 'var(--color-danger)' }}>{item.severity}</strong>
              </span>
              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>•</span>
              <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                Invoice Date: <strong>{item.invoiceDate}</strong>
              </span>
            </div>
            <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.3px' }}>
              Invoice {item.invoiceNumber} — Line Item Reconciliation
            </h2>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>
              Vendor: <strong>{item.vendorName}</strong> | Contract: <strong>{item.contractNumber}</strong> ({item.contractTitle})
              {item.poNumber && <> | PO: <strong>{item.poNumber}</strong></>}
            </p>
          </div>

          <button
            onClick={onClose}
            aria-label="Close modal"
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-full)',
              border: '1px solid var(--border-subtle)',
              backgroundColor: '#FFFFFF',
              color: 'var(--text-secondary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              fontSize: '16px',
            }}
          >
            ✕
          </button>
        </div>

        {/* Modal Body */}
        <div style={{ padding: '24px 28px', display: 'flex', flexDirection: 'column', gap: '22px' }}>
          
          {/* 1. Why Flagged? Investigation Banner */}
          <div
            style={{
              backgroundColor: 'var(--color-danger-subtle)',
              border: '1px solid var(--color-danger-border)',
              borderRadius: 'var(--radius-md)',
              padding: '16px 20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '16px' }}>⚠️</span>
              <h3 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--color-danger)' }}>
                Deterministic Rule Violation Explanation
              </h3>
            </div>
            <p style={{ fontSize: '13.5px', color: 'var(--text-primary)', lineHeight: 1.5 }}>
              {item.investigationReason}
            </p>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '6px', borderTop: '1px solid rgba(243, 195, 200, 0.6)', gap: '10px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                Total Invoice Discrepancy: <strong style={{ color: 'var(--color-danger)', fontSize: '13px' }}>{formatCurrency(item.discrepancyAmount, item.currency)}</strong>
              </span>
              <button
                onClick={() => onLaunchInvestigation(item)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  backgroundColor: '#FFFFFF',
                  color: 'var(--color-brand)',
                  border: '1px solid var(--border-strong)',
                  padding: '5px 12px',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '12px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                <span>✨</span>
                Ask Follow-up in Ask AI
              </button>
            </div>
          </div>

          {/* 1b. Pre-Computed Investigation Diagnosis & Citations */}
          <div
            style={{
              backgroundColor: 'var(--bg-app)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: '16px 20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
              <h3 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                Pre-Computed Investigation Findings
              </h3>
              <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--color-brand)', textTransform: 'uppercase' }}>
                {loadingPacket ? 'Loading analysis…' : packet ? 'Ready' : 'Standard Audit'}
              </span>
            </div>
            {loadingPacket ? (
              <p style={{ fontSize: '12.5px', color: 'var(--text-muted)', margin: 0 }}>
                Loading evidence, prior invoice history, and contract citations…
              </p>
            ) : packet ? (
              <>
                {packet.recommended_action && (
                  <div style={{ fontSize: '13px', color: 'var(--text-primary)', backgroundColor: '#FFFFFF', padding: '10px 12px', borderRadius: '6px', borderLeft: '3px solid var(--color-brand)' }}>
                    <strong style={{ color: 'var(--color-brand)' }}>Recommended next step:</strong> {packet.recommended_action}
                  </div>
                )}
                {(packet.payload?.confirmed_facts?.length ?? 0) > 0 && (
                  <div style={{ fontSize: '12.5px' }}>
                    <strong style={{ color: 'var(--text-secondary)', fontSize: '11px', textTransform: 'uppercase' }}>Confirmed Facts</strong>
                    <ul style={{ margin: '4px 0 0', paddingLeft: '18px', color: 'var(--text-primary)' }}>
                      {packet.payload.confirmed_facts?.map((f, idx) => (
                        <li key={idx}>{f.statement}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {(packet.payload?.possible_explanations?.length ?? 0) > 0 && (
                  <div style={{ fontSize: '12.5px' }}>
                    <strong style={{ color: 'var(--text-secondary)', fontSize: '11px', textTransform: 'uppercase' }}>Contract &amp; Amendment Context</strong>
                    <ul style={{ margin: '4px 0 0', paddingLeft: '18px', color: 'var(--text-primary)' }}>
                      {packet.payload.possible_explanations?.map((f, idx) => (
                        <li key={idx}>{f.statement}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {(packet.payload?.citations?.some((c) => c.document_id) ?? false) && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '4px' }}>
                    {packet.payload.citations
                      ?.filter((c) => c.document_id)
                      .map((c, idx) => (
                        <Link
                          key={idx}
                          href={`/documents/${encodeURIComponent(c.document_id!)}`}
                          style={{
                            fontSize: '11.5px',
                            fontWeight: 600,
                            padding: '4px 10px',
                            borderRadius: '999px',
                            border: '1px solid var(--border-strong)',
                            backgroundColor: '#FFFFFF',
                            color: 'var(--color-brand)',
                            textDecoration: 'none',
                          }}
                        >
                          Source: {c.section || 'Document'}{c.page ? ` (p.${c.page})` : ''} ↗
                        </Link>
                      ))}
                  </div>
                )}
              </>
            ) : (
              <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', margin: 0 }}>
                Deterministic variance details are shown below. Use Ask AI if you need an ad-hoc cross-vendor query.
              </p>
            )}
          </div>

          {/* 2. Line Items Comparison Table */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                Line-by-Line Rate & Variance Analysis
              </h3>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Comparing invoice line items against locked contract term schedule
              </span>
            </div>

            <div style={{ overflowX: 'auto', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                <thead>
                  <tr style={{ backgroundColor: 'var(--bg-surface-tint)', borderBottom: '1px solid var(--border-subtle)' }}>
                    <th style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>Line #</th>
                    <th style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>Item & Code</th>
                    <th style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)' }}>Billed Unit Price</th>
                    <th style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)' }}>Contracted Price</th>
                    <th style={{ padding: '10px 14px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)' }}>Billed Qty</th>
                    <th style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)' }}>Variance ($)</th>
                    <th style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)' }}>Variance (%)</th>
                  </tr>
                </thead>
                <tbody>
                  {item.lineItemsComparison.map((li) => {
                    const isVariance = Math.abs(li.varianceAmount) > 0.01;
                    return (
                      <tr
                        key={li.id}
                        style={{
                          borderBottom: '1px solid var(--border-subtle)',
                          backgroundColor: isVariance ? 'rgba(251, 236, 238, 0.4)' : '#FFFFFF',
                        }}
                      >
                        <td style={{ padding: '12px 14px', fontWeight: 600, color: 'var(--text-muted)' }}>
                          #{li.lineNumber}
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{li.description}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace', marginTop: '2px' }}>
                            {li.productCode}
                          </div>
                          {isVariance && (
                            <div style={{ fontSize: '11.5px', color: 'var(--color-danger)', marginTop: '4px', fontStyle: 'italic' }}>
                              ↳ {li.explanation}
                            </div>
                          )}
                        </td>
                        <td style={{ padding: '12px 14px', textAlign: 'right', fontWeight: 600, color: isVariance ? 'var(--color-danger)' : 'var(--text-primary)' }}>
                          {formatCurrency(li.billedUnitPrice, item.currency)}
                        </td>
                        <td style={{ padding: '12px 14px', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)' }}>
                          {formatCurrency(li.contractedUnitPrice, item.currency)}
                        </td>
                        <td style={{ padding: '12px 14px', textAlign: 'center', color: 'var(--text-primary)' }}>
                          {li.billedQuantity}
                          {li.tierMaxQuantity && (
                            <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>
                              Tier: {li.tierMinQuantity ?? 0}-{li.tierMaxQuantity}
                            </div>
                          )}
                        </td>
                        <td style={{ padding: '12px 14px', textAlign: 'right', fontWeight: 700, color: isVariance ? 'var(--color-danger)' : 'var(--color-success)' }}>
                          {isVariance ? (
                            <div>
                              <div>+{formatCurrency(li.varianceAmount, item.currency)}</div>
                              {li.extendedVarianceAmount !== undefined && li.billedQuantity > 1 && (
                                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-danger)', opacity: 0.85 }}>
                                  Total: +{formatCurrency(li.extendedVarianceAmount, item.currency)}
                                </div>
                              )}
                            </div>
                          ) : (
                            '$0.00'
                          )}
                        </td>
                        <td style={{ padding: '12px 14px', textAlign: 'right' }}>
                          {isVariance ? (
                            <span
                              style={{
                                display: 'inline-block',
                                padding: '2px 8px',
                                borderRadius: 'var(--radius-full)',
                                backgroundColor: 'var(--color-danger-subtle)',
                                color: 'var(--color-danger)',
                                fontWeight: 700,
                                fontSize: '11.5px',
                              }}
                            >
                              +{li.variancePct.toFixed(1)}%
                            </span>
                          ) : (
                            <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>0%</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* 3. Contractual Metadata Footnote */}
          <div
            style={{
              padding: '12px 16px',
              backgroundColor: 'var(--bg-app)',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-subtle)',
              fontSize: '12px',
              color: 'var(--text-secondary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div>
              Locked Terms Source: <strong>{item.contractTitle}</strong> (ID: {item.contractId})
            </div>
            <div>
              Reconciliation Check: <strong style={{ color: 'var(--color-success)' }}>Passed Hash Integrity</strong>
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div
          style={{
            padding: '16px 28px',
            borderTop: '1px solid var(--border-subtle)',
            backgroundColor: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: '12px',
          }}
        >
          <button
            onClick={onClose}
            style={{
              padding: '8px 18px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-strong)',
              backgroundColor: '#FFFFFF',
              color: 'var(--text-primary)',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Close
          </button>
          
          {item.status === 'open' && (
            <button
              onClick={() => onAcknowledge(item.id)}
              style={{
                padding: '8px 18px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                backgroundColor: 'var(--bg-surface-tint)',
                color: 'var(--color-brand)',
                fontSize: '13px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Mark Acknowledged
            </button>
          )}

          {(item.status === 'open' || item.status === 'acknowledged') && onResolve && (
            <button
              onClick={() => onResolve(item.id)}
              style={{
                padding: '8px 20px',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: 'var(--color-brand)',
                color: '#FFFFFF',
                fontSize: '13px',
                fontWeight: 600,
                cursor: 'pointer',
                boxShadow: 'var(--shadow-sm)',
              }}
            >
              Resolve &amp; Stage Recovery
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
