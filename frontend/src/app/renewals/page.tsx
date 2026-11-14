'use client';

import React, { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { UpcomingRenewal, RenewalBadgeUrgency } from '@/types';
import { MOCK_UPCOMING_RENEWALS } from '@/lib/mockData';
import { RenewalKPIsBar } from '@/components/renewals/RenewalKPIsBar';
import { RenewalTimelineFilter } from '@/components/renewals/RenewalTimelineFilter';
import { RenewalTimelineCard } from '@/components/renewals/RenewalTimelineCard';
import { RenewalLeverageModal } from '@/components/renewals/RenewalLeverageModal';
import { useToast } from '@/contexts/ToastContext';

export default function RenewalsPage() {
  const router = useRouter();
  const { notify } = useToast();

  const [renewals] = useState<UpcomingRenewal[]>(MOCK_UPCOMING_RENEWALS);
  const [selectedRenewal, setSelectedRenewal] = useState<UpcomingRenewal | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Filters state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedBadge, setSelectedBadge] = useState<RenewalBadgeUrgency | 'all'>('all');
  const [autoRenewOnly, setAutoRenewOnly] = useState(false);

  const filteredRenewals = useMemo(() => {
    return renewals.filter((r) => {
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesVendor = r.vendorName.toLowerCase().includes(q);
        const matchesProduct = r.productName.toLowerCase().includes(q);
        const matchesOwner = r.assignedOwner.toLowerCase().includes(q);
        if (!matchesVendor && !matchesProduct && !matchesOwner) {
          return false;
        }
      }

      if (selectedBadge !== 'all' && r.badge !== selectedBadge) {
        return false;
      }

      if (autoRenewOnly && !r.autoRenew) {
        return false;
      }

      return true;
    });
  }, [renewals, searchQuery, selectedBadge, autoRenewOnly]);

  const handleOpenDossier = (renewal: UpcomingRenewal) => {
    setSelectedRenewal(renewal);
    setIsModalOpen(true);
  };

  const handleLaunchRenewalAgent = (renewal: UpcomingRenewal) => {
    notify.success(
      'Renewal Negotiation Agent Dispatched',
      `Autonomous agent researching market benchmarks and compiling commercial leverage dossier for ${renewal.vendorName}.`
    );

    const prompt = encodeURIComponent(
      `Prepare commercial negotiation strategy and market benchmark leverage dossier for upcoming ${renewal.vendorName} renewal on ${renewal.renewalDate}. Contract: ${renewal.contractNumber}, Spend: $${renewal.annualSpend} (+${renewal.spendYoYPct}% YoY), Okta Utilization: ${renewal.utilizationPct}%. Auto-renew: ${renewal.autoRenew ? 'Yes (Notice required ' + renewal.noticePeriodDays + 'd prior)' : 'No'}. Key points: ${renewal.keyLeveragePoints.join('; ')}`
    );
    router.push(`/assistant?prompt=${prompt}`);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      {/* Header */}
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Commercial Renewal Intelligence & Timeline
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
          Continuous contract expiration monitoring, termination notice tracking, and autonomous negotiation leverage preparation.
        </p>
      </div>

      {/* 1. Overview KPIs */}
      <RenewalKPIsBar renewals={renewals} />

      {/* 2. Timeline Filter */}
      <RenewalTimelineFilter
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        selectedBadge={selectedBadge}
        onBadgeChange={setSelectedBadge}
        autoRenewOnly={autoRenewOnly}
        onAutoRenewOnlyChange={setAutoRenewOnly}
      />

      {/* 3. Chronological Renewal Cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {filteredRenewals.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: '48px 24px',
              backgroundColor: '#FFFFFF',
              borderRadius: 'var(--radius-lg)',
              border: '1px solid var(--border-subtle)',
              color: 'var(--text-muted)',
            }}
          >
            <div style={{ fontSize: '38px', marginBottom: '12px' }}>📅</div>
            <p style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
              No Renewals Found
            </p>
            <p style={{ fontSize: '13px' }}>No contracts match the selected countdown horizon or filter parameters.</p>
          </div>
        ) : (
          filteredRenewals.map((r) => (
            <RenewalTimelineCard
              key={r.id}
              renewal={r}
              onOpenDossier={handleOpenDossier}
              onLaunchAgent={handleLaunchRenewalAgent}
            />
          ))
        )}
      </div>

      {/* 4. Negotiation Leverage Modal */}
      <RenewalLeverageModal
        renewal={selectedRenewal}
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onLaunchRenewalAgent={handleLaunchRenewalAgent}
      />
    </div>
  );
}
