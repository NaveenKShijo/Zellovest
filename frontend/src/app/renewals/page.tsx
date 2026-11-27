'use client';

import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { UpcomingRenewal, RenewalBadgeUrgency } from '@/types';
import { RenewalKPIsBar } from '@/components/renewals/RenewalKPIsBar';
import { RenewalTimelineFilter } from '@/components/renewals/RenewalTimelineFilter';
import { RenewalTimelineCard } from '@/components/renewals/RenewalTimelineCard';
import { RenewalLeverageModal } from '@/components/renewals/RenewalLeverageModal';
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
  const { user } = useAuth();
  const api = useApi();
  const cacheScopeId = useMemo(() => user?.id ?? 'anonymous', [user]);

  // Filters state
  const [searchQuery, setSearchQuery] = useState(() =>
    typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('search') ?? '' : ''
  );
  const [deepLinkContractId] = useState<string | null>(() =>
    typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('contract') : null
  );
  const [deepLinkDismissed, setDeepLinkDismissed] = useState(false);
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
  const [loadError, setLoadError] = useState('');
  const [selectedRenewal, setSelectedRenewal] = useState<UpcomingRenewal | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const requestIdRef = useRef(0);

  // Fetch renewals data through SWR cache
  const loadData = useCallback(
    (force: boolean = false) => {
      const requestId = ++requestIdRef.current;
      setLoadError('');
      const cached = peekRenewalsList(cacheScopeId, viewKey);
      if (!cached || force) {
        setIsLoading(true);
      }

      readRenewalsList(
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
      )
        .then((data) => {
          if (requestId !== requestIdRef.current) return;
          setRenewals(data || []);
          setIsLoading(false);
        })
        .catch((err: unknown) => {
          if (requestId !== requestIdRef.current) return;
          console.error('Failed to load upcoming renewals from database:', err);
          setLoadError(err instanceof Error ? err.message : 'Unable to load renewals.');
          if (!cached) setRenewals([]);
          setIsLoading(false);
        });
    },
    // api.negotiation is recreated each render; the query params below are
    // the authoritative inputs that should trigger a fresh fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cacheScopeId, viewKey, selectedBadge, autoRenewOnly, searchQuery]
  );

  useEffect(() => {
    // The cache-backed loader synchronizes this view with the current filters.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData(false);
  }, [loadData, retryKey]);

  // Invalidation subscriber: automatically refresh when a reminder or contract changes
  useEffect(() => {
    return subscribeRenewals(() => {
      setRetryKey((k) => k + 1);
    });
  }, []);

  // Window focus / visibility revalidation (SWR)
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        loadData(false);
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('focus', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('focus', handleVisibilityChange);
    };
  }, [loadData]);

  const filteredRenewals = useMemo(() => {
    return renewals.filter((r) => {
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesVendor = r.vendorName?.toLowerCase().includes(q);
        const matchesProduct = r.productName?.toLowerCase().includes(q);
        const matchesOwner = r.assignedOwner?.toLowerCase().includes(q);
        const matchesContract = r.contractNumber?.toLowerCase().includes(q);
        if (!matchesVendor && !matchesProduct && !matchesOwner && !matchesContract) {
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

  const activeModalRenewal =
    (isModalOpen ? selectedRenewal : null) ??
    (!deepLinkDismissed && deepLinkContractId
      ? renewals.find((r) => r.contractId === deepLinkContractId) ?? null
      : null);
  const isDossierOpen = activeModalRenewal !== null;

  const handleLaunchRenewalAgent = (renewal: UpcomingRenewal) => {
    const prompt = encodeURIComponent(
      `Help me prepare for the ${renewal.vendorName} renewal for contract ${renewal.contractNumber}. Review the notice deadline, utilization, invoice discrepancies and contractual price escalation terms, and cite supporting evidence.`
    );
    router.push(`/assistant?prompt=${prompt}&vendorId=${encodeURIComponent(renewal.vendorId)}`);
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
            loadData(true);
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
      {loadError && <div role="alert" style={{ padding: '14px', background: 'var(--color-danger-subtle)', color: 'var(--color-danger)', borderRadius: 'var(--radius-sm)' }}>Could not refresh renewals: {loadError} <button onClick={() => loadData(true)} style={{ textDecoration: 'underline', color: 'inherit', marginLeft: 8 }}>Try again</button></div>}
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
      {isDossierOpen && activeModalRenewal && <RenewalLeverageModal
        key={activeModalRenewal.contractId}
        renewal={activeModalRenewal}
        isOpen={isDossierOpen}
        onClose={() => {
          setIsModalOpen(false);
          setSelectedRenewal(null);
          setDeepLinkDismissed(true);
        }}
        onLaunchRenewalAgent={handleLaunchRenewalAgent}
      />}
    </div>
  );
}
