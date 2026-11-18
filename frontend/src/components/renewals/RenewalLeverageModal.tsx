'use client';

import React, { useState, useEffect } from 'react';
import { UpcomingRenewal, NegotiationBriefResponse, ClauseCitation } from '@/types';
import { useApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';

interface RenewalLeverageModalProps {
  renewal: UpcomingRenewal | null;
  isOpen: boolean;
  onClose: () => void;
  onLaunchRenewalAgent: (renewal: UpcomingRenewal) => void;
}

export function RenewalLeverageModal({
  renewal,
  isOpen,
  onClose,
  onLaunchRenewalAgent,
}: RenewalLeverageModalProps) {
  const api = useApi();
  const { notify } = useToast();

  const [activeTab, setActiveTab] = useState<'overview' | 'aiBrief'>('overview');
  const [brief, setBrief] = useState<NegotiationBriefResponse | null>(null);
  const [isBriefLoading, setIsBriefLoading] = useState(false);
  const [isSettingReminder, setIsSettingReminder] = useState(false);
  const [reminderScheduledDate, setReminderScheduledDate] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && renewal) {
      setActiveTab('overview');
      setReminderScheduledDate(null);
      // Pre-fetch negotiation brief for live dossier
      setIsBriefLoading(true);
      api.negotiation
        .prepareBrief({
          vendor_id: renewal.vendorId,
          contract_id: renewal.contractId,
        })
        .then((res) => setBrief(res))
        .catch(() => setBrief(null))
        .finally(() => setIsBriefLoading(false));
    }
  }, [isOpen, renewal]);

  if (!isOpen || !renewal) return null;

  const formatCurrency = (val: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(val);

  const handleScheduleReminder = async (remindDaysBefore: number = 14) => {
    try {
      setIsSettingReminder(true);
      const res = await api.negotiation.createReminder({
        contract_id: renewal.contractId,
        vendor_id: renewal.vendorId,
        remind_days_before_notice: remindDaysBefore,
      });
      setReminderScheduledDate(res.remind_date);
      notify.success(
        'Notice Deadline Reminder Scheduled',
        `Automated alert will notify procurement on ${res.remind_date} (${remindDaysBefore} days before notice cutoff).`
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to schedule reminder';
      notify.error('Reminder Failed', msg);
    } finally {
      setIsSettingReminder(false);
    }
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
          maxWidth: '880px',
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  padding: '2px 8px',
                  borderRadius: 'var(--radius-full)',
                  backgroundColor: 'var(--color-brand)',
                  color: '#FFFFFF',
                }}
              >
                Renewal Agent Dossier
              </span>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                Target Expiration: <strong>{renewal.renewalDate}</strong> ({renewal.daysUntilRenewal} days remaining)
              </span>
            </div>
            <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.3px' }}>
              {renewal.vendorName} — Commercial Negotiation Leverage
            </h2>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Product: <strong>{renewal.productName}</strong> • Contract: <strong>{renewal.contractNumber}</strong>
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
            }}
          >
            ✕
          </button>
        </div>

        {/* Tab Selection */}
        <div
          style={{
            display: 'flex',
            gap: '8px',
            padding: '12px 28px',
            borderBottom: '1px solid var(--border-subtle)',
            backgroundColor: '#FAFAF9',
          }}
        >
          <button
            onClick={() => setActiveTab('overview')}
            style={{
              padding: '6px 14px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              border: activeTab === 'overview' ? '1px solid var(--color-brand)' : '1px solid transparent',
              backgroundColor: activeTab === 'overview' ? '#FFFFFF' : 'transparent',
              color: activeTab === 'overview' ? 'var(--color-brand)' : 'var(--text-secondary)',
            }}
          >
            Commercial Leverage Overview
          </button>
          <button
            onClick={() => setActiveTab('aiBrief')}
            style={{
              padding: '6px 14px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              border: activeTab === 'aiBrief' ? '1px solid var(--color-brand)' : '1px solid transparent',
              backgroundColor: activeTab === 'aiBrief' ? '#FFFFFF' : 'transparent',
              color: activeTab === 'aiBrief' ? 'var(--color-brand)' : 'var(--text-secondary)',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>🤖</span>
            AI Negotiation Intelligence Dossier
            {isBriefLoading && <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>(Analyzing...)</span>}
          </button>
        </div>

        {/* Modal Content */}
        <div style={{ padding: '24px 28px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {activeTab === 'overview' ? (
            <>
              {/* Key Metrics Grid */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '12px' }}>
                <div style={{ padding: '14px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
                  <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontWeight: 600 }}>CURRENT ARR</span>
                  <div style={{ fontSize: '18px', fontWeight: 800, color: 'var(--text-primary)', marginTop: '2px' }}>
                    {formatCurrency(renewal.annualSpend)}
                  </div>
                </div>

                <div style={{ padding: '14px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
                  <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontWeight: 600 }}>SPEND YoY</span>
                  <div style={{ fontSize: '18px', fontWeight: 800, color: renewal.spendYoYPct > 10 ? 'var(--color-danger)' : 'var(--text-primary)', marginTop: '2px' }}>
                    {renewal.spendYoYPct > 0 ? `+${renewal.spendYoYPct}%` : `${renewal.spendYoYPct}%`}
                  </div>
                </div>

                <div style={{ padding: '14px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
                  <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontWeight: 600 }}>OKTA UTILIZATION</span>
                  <div style={{ fontSize: '18px', fontWeight: 800, color: renewal.utilizationPct < 80 ? 'var(--color-danger)' : 'var(--color-success)', marginTop: '2px' }}>
                    {renewal.utilizationPct}%
                  </div>
                </div>

                <div style={{ padding: '14px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
                  <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontWeight: 600 }}>NOTICE DEADLINE</span>
                  <div style={{ fontSize: '15px', fontWeight: 700, color: renewal.isNoticeWindowActive ? 'var(--color-danger)' : 'var(--text-primary)', marginTop: '4px' }}>
                    {renewal.noticeDeadlineDate}
                  </div>
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {renewal.daysUntilNoticeDeadline > 0
                      ? `${renewal.daysUntilNoticeDeadline} days remaining`
                      : 'Deadline passed'}
                  </span>
                </div>
              </div>

              {/* Auto-renew alert & reminder trigger */}
              {renewal.autoRenew && (
                <div
                  style={{
                    backgroundColor: 'var(--color-warning-subtle)',
                    border: '1px solid var(--color-warning-border)',
                    borderRadius: 'var(--radius-md)',
                    padding: '16px 20px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '12px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                    <span style={{ fontSize: '22px' }}>⚠️</span>
                    <div style={{ flex: 1 }}>
                      <strong style={{ fontSize: '13.5px', color: 'var(--color-warning)' }}>
                        Notice Deadline Critical Window Active
                      </strong>
                      <p style={{ fontSize: '12.5px', color: 'var(--text-primary)', marginTop: '2px' }}>
                        This contract will auto-renew for another 12-month period if formal notice is not served by{' '}
                        <strong>{renewal.noticeDeadlineDate}</strong> ({renewal.noticePeriodDays} days notice required).
                      </p>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '8px', borderTop: '1px solid rgba(0,0,0,0.06)' }}>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                      {reminderScheduledDate ? (
                        <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>
                          ✓ Notice alert scheduled for {reminderScheduledDate}
                        </span>
                      ) : (
                        'Prevent unbudgeted lock-in by scheduling automated notice alerts.'
                      )}
                    </div>
                    <button
                      onClick={() => handleScheduleReminder(14)}
                      disabled={isSettingReminder || !!reminderScheduledDate}
                      style={{
                        padding: '6px 14px',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: reminderScheduledDate ? 'var(--color-success)' : 'var(--color-brand)',
                        color: '#FFFFFF',
                        border: 'none',
                        fontSize: '12px',
                        fontWeight: 600,
                        cursor: isSettingReminder || !!reminderScheduledDate ? 'default' : 'pointer',
                        opacity: isSettingReminder ? 0.7 : 1,
                      }}
                    >
                      {reminderScheduledDate
                        ? 'Reminder Set'
                        : isSettingReminder
                        ? 'Scheduling...'
                        : '⏰ Schedule Notice Reminder (14d before)'}
                    </button>
                  </div>
                </div>
              )}

              {/* Identified Commercial Leverage Points */}
              <div>
                <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '10px' }}>
                  Identified Commercial Leverage Points (Zellovest Intelligence):
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {renewal.keyLeveragePoints.map((pt, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '10px',
                        padding: '12px 14px',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: '#FFFFFF',
                        border: '1px solid var(--border-subtle)',
                      }}
                    >
                      <span style={{ color: 'var(--color-brand)', fontWeight: 700, fontSize: '14px' }}>✓</span>
                      <span style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.4 }}>{pt}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          ) : (
            /* AI Negotiation Intelligence Brief Tab */
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {isBriefLoading ? (
                <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)' }}>
                  <div style={{ fontSize: '28px', marginBottom: '8px' }}>⚡</div>
                  <p style={{ fontWeight: 600 }}>Synthesizing Clause Citations, AP Discrepancies, and BATNA Targets...</p>
                </div>
              ) : brief ? (
                <>
                  {/* Talking Points */}
                  {brief.talking_points && brief.talking_points.length > 0 && (
                    <div style={{ padding: '16px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
                      <h4 style={{ fontSize: '13px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-brand)', marginBottom: '8px' }}>
                        Tactical Supplier Talking Points
                      </h4>
                      <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '13px', color: 'var(--text-primary)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {brief.talking_points.map((tp: string, i: number) => (
                          <li key={i}>{tp}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Recommended Actions & Leverage */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                    <div style={{ padding: '14px', borderRadius: 'var(--radius-md)', backgroundColor: '#FFFFFF', border: '1px solid var(--border-subtle)' }}>
                      <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--color-brand)' }}>RECOMMENDED ACTIONS</span>
                      <ul style={{ margin: '8px 0 0 0', paddingLeft: '18px', fontSize: '12.5px', color: 'var(--text-primary)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {(brief.recommended_actions || []).map((action: string, i: number) => (
                          <li key={i}>{action}</li>
                        ))}
                      </ul>
                    </div>
                    <div style={{ padding: '14px', borderRadius: 'var(--radius-md)', backgroundColor: '#FFFFFF', border: '1px solid var(--border-subtle)' }}>
                      <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--color-danger)' }}>COMMERCIAL RISK FACTORS</span>
                      <ul style={{ margin: '8px 0 0 0', paddingLeft: '18px', fontSize: '12.5px', color: 'var(--text-primary)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {(brief.risk_factors || []).map((risk: string, i: number) => (
                          <li key={i}>{risk}</li>
                        ))}
                      </ul>
                    </div>
                  </div>

                  {/* Contract Clause Citations */}
                  {brief.contractual_clauses && brief.contractual_clauses.length > 0 && (
                    <div>
                      <h4 style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px' }}>
                        Verified Contract Clause Citations (RAG Grounded):
                      </h4>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {brief.contractual_clauses.map((c: ClauseCitation, i: number) => (
                          <div
                            key={i}
                            style={{
                              padding: '10px 14px',
                              borderRadius: 'var(--radius-sm)',
                              backgroundColor: '#FAFAF9',
                              border: '1px solid var(--border-subtle)',
                              fontSize: '12.5px',
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                              <strong style={{ color: 'var(--text-primary)' }}>{c.clause_type}</strong>
                              {c.section && <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Section: {c.section}</span>}
                            </div>
                            <p style={{ margin: '0 0 4px 0', color: 'var(--text-primary)' }}>{c.summary}</p>
                            {c.verbatim_excerpt && (
                              <blockquote style={{ margin: 0, fontStyle: 'italic', color: 'var(--text-secondary)', borderLeft: '2px solid var(--color-brand)', paddingLeft: '8px' }}>
                                &ldquo;{c.verbatim_excerpt}&rdquo;
                              </blockquote>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>
                  Failed to load live AI brief. Please use the Commercial Leverage Overview.
                </div>
              )}
            </div>
          )}
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

          <button
            onClick={() => onLaunchRenewalAgent(renewal)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
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
            <span>🤖</span>
            Dispatch Renewal Negotiation Agent
          </button>
        </div>
      </div>
    </div>
  );
}
