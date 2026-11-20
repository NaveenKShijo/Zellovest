'use client';

import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { UpcomingRenewal, RenewalBadgeUrgency } from '@/types';
import { RenewalKPIsBar } from '@/components/renewals/RenewalKPIsBar';
import { RenewalTimelineFilter } from '@/components/renewals/RenewalTimelineFilter';
import { RenewalTimelineCard } from '@/components/renewals/RenewalTimelineCard';
import { RenewalLeverageModal } from '@/components/renewals/RenewalLeverageModal';
import { useToast } from '@/contexts/ToastContext';
import { useAuth } from '@/contexts/AuthContext';
import { useApi } from '@/lib/api';
import {
  peekRenewalsList,
  readRenewalsList,
  subscribeRenewals,
  invalidateRenewals,
} from '@/lib/renewalDataCache';

export default function RenewalsPage() {
  const router = useRouter();
  const { notify } = useToast();
  const { user } = useAuth();
  const api = useApi();
  const cacheScopeId = useMemo(() => user?.id ?? 'anonymous', [user]);

  // Filters state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedBadge, setSelectedBadge] = useState<RenewalBadgeUrgency | 'all'>('all');
  const [autoRenewOnly, setAutoRenewOnly] = useState(false);

  // Identity of the current filter view
  const viewKey = useMemo(
    () => [selectedBadge, autoRenewOnly ? '1' : '0', searchQuery.trim().toLowerCase()].join('|'),
    [selectedBadge, autoRenewOnly, searchQuery]
  );

  // Initialize synchronously from cache if viewed previously (0ms instant render)
  const initialCached = peekRenewalsList(cacheScopeId, viewKey);
  const [renewals, setRenewals] = useState<UpcomingRenewal[]>(() => initialCached ?? []);
  const [isLoading, setIsLoading] = useState<boolean>(() => !initialCached);
  const [selectedRenewal, setSelectedRenewal] = useState<UpcomingRenewal | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const requestIdRef = useRef(0);

  const fetchRenewals = useCallback(
    async (force: boolean = false) => {
      const requestId = ++requestIdRef.current;
      const cached = peekRenewalsList(cacheScopeId, viewKey);
      if (!cached || force) {
        setIsLoading(true);
      }

      try {
        const data = await readRenewalsList(
          cacheScopeId,
          viewKey,
          () =>
            api.negotiation.upcomingRenewals({
              badge: selectedBadge !== 'all' ? selectedBadge : undefined,
              auto_renew_only: autoRenewOnly || undefined,
              search: searchQuery.trim() || undefined,
            }),
          {
            force,
            onRevalidate: (fresh) => {
              if (requestId !== requestIdRef.current) return;
              setRenewals(fresh || []);
              setIsLoading(false);
            },
          }
        );

        if (requestId === requestIdRef.current) {
          setRenewals(data || []);
        }
      } catch (err: unknown) {
        if (requestId === requestIdRef.current) {
          console.error('Failed to load upcoming renewals from database:', err);
          if (!cached) setRenewals([]);
        }
      } finally {
        if (requestId === requestIdRef.current) {
          setIsLoading(false);
        }
      }
    },
    [api.negotiation, cacheScopeId, viewKey, selectedBadge, autoRenewOnly, searchQuery]
  );

  useEffect(() => {
    fetchRenewals(false);
  }, [fetchRenewals]);

  // Invalidation subscriber: automatically refresh when a reminder or contract changes
  useEffect(() => {
    return subscribeRenewals(() => {
      fetchRenewals(true);
    });
  }, [fetchRenewals]);

  // Window focus / visibility revalidation (SWR)
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        fetchRenewals(false);
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('focus', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('focus', handleVisibilityChange);
    };
  }, [fetchRenewals]);

  const filteredRenewals = useMemo(() => {
    return renewals.filter((r) => {
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesVendor = r.vendorName?.toLowerCase().includes(q);
        const matchesProduct = r.productName?.toLowerCase().includes(q);
        const matchesOwner = r.assignedOwner?.toLowerCase().includes(q);
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
      `Prepare commercial negotiation strategy and market benchmark leverage dossier for upcoming ${renewal.vendorName} renewal on ${renewal.renewalDate}. Contract: ${renewal.contractNumber}, Spend: $${renewal.annualSpend} (+${renewal.spendYoYPct}% YoY). Auto-renew: ${renewal.autoRenew ? 'Yes (Notice required ' + renewal.noticePeriodDays + 'd prior)' : 'No'}. Key points: ${renewal.keyLeveragePoints.join('; ')}`
    );
    router.push(`/assistant?prompt=${prompt}`);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
            Commercial Renewal Intelligence & Timeline
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
            Continuous contract expiration monitoring, termination notice tracking, and autonomous negotiation leverage preparation.
          </p>
        </div>
        <button
          onClick={() => {
            invalidateRenewals(cacheScopeId);
            fetchRenewals(true);
          }}
          disabled={isLoading}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '8px 16px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            backgroundColor: '#FFFFFF',
            fontSize: '13px',
            fontWeight: 600,
            cursor: isLoading ? 'default' : 'pointer',
            color: 'var(--text-primary)',
          }}
        >
          <span>{isLoading ? '⏳' : '🔄'}</span>
          {isLoading ? 'Refreshing...' : 'Refresh Timeline'}
        </button>
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
        {isLoading && renewals.length === 0 ? (
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
            <div style={{ fontSize: '32px', marginBottom: '12px' }}>⏳</div>
            <p style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
              Loading Database Renewals...
            </p>
            <p style={{ fontSize: '13px' }}>Querying active enterprise contracts and notice deadlines from database.</p>
          </div>
        ) : filteredRenewals.length === 0 ? (
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
