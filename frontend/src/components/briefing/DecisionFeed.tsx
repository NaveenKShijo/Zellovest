'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import type { DecisionPacketItem } from '@/types';
import styles from './DecisionFeed.module.css';

interface DecisionFeedProps {
  items: DecisionPacketItem[];
  loading: boolean;
  error: boolean;
  activeFilter: string;
  onFilterChange: (filter: string) => void;
  onAction: (
    packet: DecisionPacketItem,
    action: 'acknowledge' | 'resolve' | 'dismiss' | 'mark_migrated' | 'create_workflow'
  ) => Promise<void>;
}

const FILTERS = [
  { id: 'all', label: 'All Ready Outcomes' },
  { id: 'ap_investigation', label: 'AP Exceptions' },
  { id: 'renewal_dossier', label: 'Renewals' },
  { id: 'maverick_review', label: 'Unmanaged SaaS' },
];

const money = (amount?: number | null, currency = 'USD') => {
  if (amount == null || !Number.isFinite(amount)) return null;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency || 'USD',
    maximumFractionDigits: 0,
  }).format(amount);
};

/**
 * Renders pre-computed procurement outcomes with inline evidence and
 * 1-click in-app resolution actions (zero external notifications).
 */
export function DecisionFeed({
  items,
  loading,
  error,
  activeFilter,
  onFilterChange,
  onAction,
}: DecisionFeedProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [busyPacketId, setBusyPacketId] = useState<string | null>(null);

  const visibleItems =
    activeFilter === 'all'
      ? items
      : items.filter((item) => item.packet_type === activeFilter);

  const triggerAction = async (
    packet: DecisionPacketItem,
    action: 'acknowledge' | 'resolve' | 'dismiss' | 'mark_migrated' | 'create_workflow'
  ) => {
    setBusyPacketId(packet.id);
    try {
      await onAction(packet, action);
    } finally {
      setBusyPacketId(null);
    }
  };

  return (
    <div>
      <div className={styles.filters} role="tablist" aria-label="Filter decision outcomes">
        {FILTERS.map((filter) => (
          <button
            key={filter.id}
            type="button"
            role="tab"
            aria-selected={activeFilter === filter.id}
            className={`${styles.filterBtn} ${activeFilter === filter.id ? styles.filterActive : ''}`}
            onClick={() => onFilterChange(filter.id)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {loading && items.length === 0 ? (
        <div className={styles.empty} role="status">
          Preparing pre-computed procurement outcomes…
        </div>
      ) : error && items.length === 0 ? (
        <div className={styles.empty} role="alert">
          Decision feed is temporarily unavailable. Use the workspace queues or refresh to retry.
        </div>
      ) : visibleItems.length === 0 ? (
        <div className={styles.empty} role="status">
          No pending decision packets in this category. Background workers continuously monitor invoices, contracts, and card activity.
        </div>
      ) : (
        <div className={styles.feed}>
          {visibleItems.map((packet) => {
            const isExpanded = expandedId === packet.id;
            const isBusy = busyPacketId === packet.id;
            const impactText = money(packet.financial_impact, packet.currency);
            const typeClass =
              packet.packet_type === 'ap_investigation'
                ? styles.typeAp
                : packet.packet_type === 'renewal_dossier'
                  ? styles.typeRenewal
                  : styles.typeMaverick;
            const typeLabel =
              packet.packet_type === 'ap_investigation'
                ? 'AP Audit Finding'
                : packet.packet_type === 'renewal_dossier'
                  ? 'Renewal Dossier'
                  : 'Unmanaged SaaS';

            const facts = packet.payload?.confirmed_facts ?? [];
            const calculations = packet.payload?.calculated_values ?? [];
            const explanations = packet.payload?.possible_explanations ?? [];
            const briefLeverage = packet.payload?.brief?.leverage_points ?? [];
            const briefClauses = packet.payload?.brief?.contractual_clauses ?? [];
            const citations = packet.payload?.citations ?? [];
            const hasEvidence =
              facts.length > 0 ||
              calculations.length > 0 ||
              explanations.length > 0 ||
              briefLeverage.length > 0 ||
              briefClauses.length > 0;

            return (
              <article key={packet.id} className={styles.packet}>
                <div className={styles.packetTop}>
                  <div className={styles.badges}>
                    <span className={`${styles.typePill} ${typeClass}`}>{typeLabel}</span>
                    {packet.urgency_date && (
                      <span className={styles.urgencyText}>Target date: {packet.urgency_date}</span>
                    )}
                  </div>
                  {impactText && <span className={styles.impact}>{impactText} impact</span>}
                </div>

                <h3 className={styles.title}>{packet.title}</h3>
                <p className={styles.summary}>{packet.summary}</p>

                {packet.recommended_action && (
                  <div className={styles.recommendation}>
                    <strong>Recommended outcome:</strong> {packet.recommended_action}
                  </div>
                )}

                {hasEvidence && (
                  <>
                    <button
                      type="button"
                      className={styles.evidenceToggle}
                      onClick={() => setExpandedId(isExpanded ? null : packet.id)}
                    >
                      {isExpanded ? '▾ Hide pre-computed evidence' : '▸ View pre-computed evidence & citations'}
                    </button>

                    {isExpanded && (
                      <div className={styles.evidenceBox}>
                        {facts.length > 0 && (
                          <div className={styles.evidenceGroup}>
                            <h4>Confirmed Facts</h4>
                            <ul>
                              {facts.map((item, idx) => (
                                <li key={idx}>{item.statement}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {calculations.length > 0 && (
                          <div className={styles.evidenceGroup}>
                            <h4>Deterministic Calculations</h4>
                            <ul>
                              {calculations.map((item, idx) => (
                                <li key={idx}>{item.statement}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {explanations.length > 0 && (
                          <div className={styles.evidenceGroup}>
                            <h4>Contract & Amendment Context</h4>
                            <ul>
                              {explanations.map((item, idx) => (
                                <li key={idx}>{item.statement}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {briefLeverage.length > 0 && (
                          <div className={styles.evidenceGroup}>
                            <h4>Negotiation Leverage</h4>
                            <ul>
                              {briefLeverage.map((point, idx) => (
                                <li key={idx}>{point}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {(citations.some((c) => c.document_id) || briefClauses.some((c) => c.document_id)) && (
                          <div className={styles.citationRow}>
                            {citations
                              .filter((c) => c.document_id)
                              .slice(0, 3)
                              .map((c, idx) => (
                                <Link
                                  key={`cit-${idx}`}
                                  className={styles.citationChip}
                                  href={`/documents/${encodeURIComponent(c.document_id!)}`}
                                >
                                  Source: {c.section || 'Document'}{c.page ? ` (p.${c.page})` : ''} ↗
                                </Link>
                              ))}
                            {briefClauses
                              .filter((c) => c.document_id)
                              .slice(0, 3)
                              .map((c, idx) => (
                                <Link
                                  key={`cl-${idx}`}
                                  className={styles.citationChip}
                                  href={`/documents/${encodeURIComponent(c.document_id!)}`}
                                >
                                  {c.filename || c.section || 'Contract'}{c.page ? ` (p.${c.page})` : ''} ↗
                                </Link>
                              ))}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}

                <div className={styles.actions}>
                  <div className={styles.actionButtons}>
                    {packet.packet_type === 'ap_investigation' && (
                      <>
                        <button
                          type="button"
                          className={styles.primaryBtn}
                          disabled={isBusy}
                          onClick={() => void triggerAction(packet, 'resolve')}
                        >
                          Resolve &amp; Stage Recovery
                        </button>
                        <button
                          type="button"
                          className={styles.secondaryBtn}
                          disabled={isBusy}
                          onClick={() => void triggerAction(packet, 'acknowledge')}
                        >
                          Acknowledge
                        </button>
                        <Link className={styles.linkBtn} href="/compliance">
                          Inspect Line Items ↗
                        </Link>
                      </>
                    )}

                    {packet.packet_type === 'renewal_dossier' && (
                      <>
                        <Link
                          className={styles.primaryBtn}
                          style={{ textDecoration: 'none' }}
                          href={`/renewals?search=${encodeURIComponent(String(packet.payload?.vendor_name || ''))}&contract=${encodeURIComponent(packet.entity_id)}`}
                        >
                          Open Pre-Built Brief ↗
                        </Link>
                        <button
                          type="button"
                          className={styles.secondaryBtn}
                          disabled={isBusy}
                          onClick={() => void triggerAction(packet, 'create_workflow')}
                        >
                          Create Renewal Task
                        </button>
                        <button
                          type="button"
                          className={styles.secondaryBtn}
                          disabled={isBusy}
                          onClick={() => void triggerAction(packet, 'resolve')}
                        >
                          Stage Seat Savings
                        </button>
                      </>
                    )}

                    {packet.packet_type === 'maverick_review' && (
                      <>
                        <button
                          type="button"
                          className={styles.primaryBtn}
                          disabled={isBusy}
                          onClick={() => void triggerAction(packet, 'mark_migrated')}
                        >
                          Mark Consolidated
                        </button>
                        <button
                          type="button"
                          className={styles.secondaryBtn}
                          disabled={isBusy}
                          onClick={() => void triggerAction(packet, 'create_workflow')}
                        >
                          Create Task
                        </button>
                        <Link className={styles.linkBtn} href="/maverick-spend">
                          View Overlap ↗
                        </Link>
                      </>
                    )}
                  </div>

                  <button
                    type="button"
                    className={styles.ghostBtn}
                    disabled={isBusy}
                    onClick={() => void triggerAction(packet, 'dismiss')}
                  >
                    Dismiss
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
