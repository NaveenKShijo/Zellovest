'use client';

import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { MaverickAlertItem, MaverickSpendKPIs } from '@/types';
import { MaverickKPIsBar } from '@/components/maverick/MaverickKPIsBar';
import { MaverickFilters } from '@/components/maverick/MaverickFilters';
import { MaverickAlertFeed } from '@/components/maverick/MaverickAlertFeed';
import { useToast } from '@/contexts/ToastContext';
import { useAuth } from '@/contexts/AuthContext';
import { useApi } from '@/lib/api';
import {
  invalidateMaverickFeeds,
  peekMaverickFeed,
  readMaverickFeed,
} from '@/lib/maverickDataCache';

const DEFAULT_KPIS: MaverickSpendKPIs = {
  totalUnmanagedSpend: 0,
  activeAlertsCount: 0,
  potentialAnnualSavings: 0,
  avgOverlapSimilarity: 0,
};

export default function MaverickSpendPage() {
  const router = useRouter();
  const { notify } = useToast();
  const { user } = useAuth();
  const api = useApi();
  const cacheScopeId = useMemo(() => user?.id ?? 'anonymous', [user]);

  const [isScanning, setIsScanning] = useState(false);
  const [isRefreshingProducts, setIsRefreshingProducts] = useState(false);
  const [productIndexStatus, setProductIndexStatus] = useState<string | null>(null);

  // Filters state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDepartment, setSelectedDepartment] = useState('all');
  const [minOverlapThreshold, setMinOverlapThreshold] = useState<number>(0);
  const [selectedStatus, setSelectedStatus] = useState('all');
  const viewKey = useMemo(
    () => [selectedDepartment, selectedStatus, minOverlapThreshold].join('|'),
    [selectedDepartment, selectedStatus, minOverlapThreshold]
  );

  // Reuse a previously visited feed immediately, then revalidate it as needed.
  const initialCached = peekMaverickFeed(cacheScopeId, viewKey);
  const [alerts, setAlerts] = useState<MaverickAlertItem[]>(() => initialCached?.alerts ?? []);
  const [kpis, setKpis] = useState<MaverickSpendKPIs>(() => initialCached?.kpis ?? DEFAULT_KPIS);
  const [isLoading, setIsLoading] = useState<boolean>(() => !initialCached);
  const requestIdRef = useRef(0);

  const loadData = useCallback(async (force: boolean = false) => {
    const requestId = ++requestIdRef.current;
    const cached = peekMaverickFeed(cacheScopeId, viewKey);
    if (cached && !force) {
      setAlerts(cached.alerts || []);
      setKpis(cached.kpis || DEFAULT_KPIS);
      setIsLoading(false);
    } else {
      setIsLoading(true);
    }

    try {
      const res = await readMaverickFeed(
        cacheScopeId,
        viewKey,
        () => api.maverick.getFeed({
          department: selectedDepartment,
          status: selectedStatus,
          min_overlap: minOverlapThreshold > 0 ? minOverlapThreshold : undefined,
        }),
        {
          force,
          onRevalidate: (fresh) => {
            if (requestId !== requestIdRef.current) return;
            setAlerts(fresh.alerts || []);
            setKpis(fresh.kpis || DEFAULT_KPIS);
            setIsLoading(false);
          },
        }
      );
      if (requestId === requestIdRef.current) {
        setAlerts(res.alerts || []);
        setKpis(res.kpis || DEFAULT_KPIS);
      }
    } catch {
      // Retain a last-known-good result when revalidation temporarily fails.
      if (requestId === requestIdRef.current && !cached) {
        setAlerts([]);
        setKpis(DEFAULT_KPIS);
      }
    } finally {
      if (requestId === requestIdRef.current) {
        setIsLoading(false);
      }
    }
  }, [api.maverick, cacheScopeId, minOverlapThreshold, selectedDepartment, selectedStatus, viewKey]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Align with Document Explorer: revalidate when the user returns to the tab.
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void loadData();
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('focus', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('focus', handleVisibilityChange);
    };
  }, [loadData]);

  const handleTriggerScan = async () => {
    try {
      setIsScanning(true);
      await api.maverick.triggerDetection(90, 'default-org', { source: 'gcs' });
      notify.success(
        'Maverick Scan Dispatched',
        'Worker is normalizing the latest Ramp card-transaction batch from GCS and running Jev identification against the approved software catalog.'
      );
      invalidateMaverickFeeds(cacheScopeId);
      window.setTimeout(() => {
        void loadData(true);
      }, 4000);
      window.setTimeout(() => {
        void loadData(true);
      }, 12000);
    } catch {
      notify.error('Scan Failed', 'Could not dispatch background maverick scan.');
    } finally {
      setIsScanning(false);
    }
  };

  const pollContractProductIndex = useCallback(async (taskId: string, attempt = 0) => {
    try {
      const result = await api.maverick.getContractProductReindexStatus(taskId);
      if (result.status === 'SUCCESS') {
        const indexed = result.summary?.indexed_products ?? 0;
        const failed = result.summary?.enrichment_failures ?? 0;
        setProductIndexStatus(
          failed > 0
            ? `${indexed} approved product(s) indexed; ${failed} line(s) need Groq enrichment retry.`
            : `${indexed} approved product(s) indexed from active contracts.`
        );
        notify.success('Approved Software Updated', `${indexed} active contract product(s) are ready for matching.`);
        return;
      }
      if (result.status === 'FAILURE') {
        setProductIndexStatus(result.error || 'Approved-software indexing failed.');
        notify.error('Approved Software Update Failed', result.error || 'Review the worker logs and retry.');
        return;
      }
      if (attempt < 12) {
        window.setTimeout(() => {
          void pollContractProductIndex(taskId, attempt + 1);
        }, 2500);
      } else {
        setProductIndexStatus('Indexing is still running. Refresh this page shortly for the result.');
      }
    } catch {
      setProductIndexStatus('Could not read the approved-software indexing status.');
    }
  }, [api, notify]);

  const handleRefreshApprovedSoftware = async () => {
    try {
      setIsRefreshingProducts(true);
      setProductIndexStatus('Indexing active contract products…');
      const queued = await api.maverick.reindexContractProducts('default-org');
      void pollContractProductIndex(queued.task_id);
    } catch {
      setProductIndexStatus('Could not queue approved-software indexing.');
      notify.error('Approved Software Update Failed', 'Could not dispatch the contract-product indexing task.');
    } finally {
      setIsRefreshingProducts(false);
    }
  };

  const filteredAlerts = useMemo(() => {
    return alerts.filter((alert) => {
      // Search matching
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesMerchant = alert.merchantName.toLowerCase().includes(q);
        const matchesEmployee = alert.employeeName.toLowerCase().includes(q);
        const matchesEmail = alert.employeeEmail.toLowerCase().includes(q);
        const matchesApproved = alert.overlap?.approvedAlternative.toLowerCase().includes(q);
        if (!matchesMerchant && !matchesEmployee && !matchesEmail && !matchesApproved) {
          return false;
        }
      }

      // Department matching
      if (selectedDepartment !== 'all' && alert.department !== selectedDepartment) {
        return false;
      }

      // Overlap threshold
      if (
        minOverlapThreshold > 0
        && (alert.overlap?.cosineSimilarity ?? 0) < minOverlapThreshold
      ) {
        return false;
      }

      // Status matching
      if (selectedStatus !== 'all' && alert.status !== selectedStatus) {
        return false;
      }

      return true;
    });
  }, [alerts, searchQuery, selectedDepartment, minOverlapThreshold, selectedStatus]);

  const handleDismiss = (alertId: string) => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === alertId ? { ...a, status: 'dismissed' as const } : a))
    );
    invalidateMaverickFeeds(cacheScopeId);
    api.maverick.updateStatus(alertId, 'dismissed').catch(() => {});
    notify.info('Exception Logged', 'Corporate card charge approved as legitimate standalone exception.');
  };

  const handleViewContract = (contractId: string) => {
    router.push(`/vendors?contract=${contractId}`);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      {/* Page Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
            Decentralized Spend & Semantic Overlap
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
            TypeSafe AI (Jev System One) detects unmanaged recurring subscriptions on corporate cards and maps semantic overlap to active procurement contract products.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={handleTriggerScan}
            disabled={isScanning}
            style={{
              padding: '8px 14px',
              fontSize: '12.5px',
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-subtle)',
              backgroundColor: '#FFFFFF',
              color: 'var(--text-primary)',
              cursor: isScanning ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: 'var(--shadow-sm)',
            }}
            title="Scan recent card transactions for potential maverick SaaS spend"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            {isScanning ? 'Scanning...' : 'Scan Card Transactions'}
          </button>
          <button
            onClick={handleRefreshApprovedSoftware}
            disabled={isRefreshingProducts}
            style={{
              padding: '8px 14px',
              fontSize: '12.5px',
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-subtle)',
              backgroundColor: '#FFFFFF',
              color: 'var(--text-primary)',
              cursor: isRefreshingProducts ? 'not-allowed' : 'pointer',
              boxShadow: 'var(--shadow-sm)',
            }}
            title="Index active contract products for semantic matching"
          >
            {isRefreshingProducts ? 'Refreshing...' : 'Refresh Approved Software'}
          </button>
        </div>
        {productIndexStatus && (
          <p style={{ color: 'var(--text-secondary)', fontSize: '12px', marginTop: '8px' }}>
            {productIndexStatus}
          </p>
        )}
      </div>

      {/* 1. KPIs Overview */}
      <MaverickKPIsBar kpis={kpis} />

      {/* 2. Filters */}
      <MaverickFilters
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        selectedDepartment={selectedDepartment}
        onDepartmentChange={setSelectedDepartment}
        minOverlapThreshold={minOverlapThreshold}
        onOverlapThresholdChange={setMinOverlapThreshold}
        selectedStatus={selectedStatus}
        onStatusChange={setSelectedStatus}
      />

      {/* 3. Feed of Alerts */}
      {isLoading ? (
        <div
          style={{
            textAlign: 'center',
            padding: '48px 24px',
            backgroundColor: '#FFFFFF',
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--border-subtle)',
            color: 'var(--text-muted)',
            fontSize: '13.5px',
          }}
        >
          Loading decentralized spend records...
        </div>
      ) : (
        <MaverickAlertFeed
          alerts={filteredAlerts}
          onDismiss={handleDismiss}
          onViewContract={handleViewContract}
        />
      )}
    </div>
  );
}
