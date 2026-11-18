'use client';

import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { MaverickAlertItem, MaverickSpendKPIs } from '@/types';
import { MaverickKPIsBar } from '@/components/maverick/MaverickKPIsBar';
import { MaverickFilters } from '@/components/maverick/MaverickFilters';
import { MaverickAlertFeed } from '@/components/maverick/MaverickAlertFeed';
import { useToast } from '@/contexts/ToastContext';
import { useApi } from '@/lib/api';

const DEFAULT_KPIS: MaverickSpendKPIs = {
  totalUnmanagedSpend: 0,
  activeAlertsCount: 0,
  potentialAnnualSavings: 0,
  avgOverlapSimilarity: 0,
};

export default function MaverickSpendPage() {
  const router = useRouter();
  const { notify } = useToast();
  const api = useApi();

  const [alerts, setAlerts] = useState<MaverickAlertItem[]>([]);
  const [kpis, setKpis] = useState<MaverickSpendKPIs>(DEFAULT_KPIS);
  const [isLoading, setIsLoading] = useState(true);
  const [isScanning, setIsScanning] = useState(false);

  // Filters state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDepartment, setSelectedDepartment] = useState('all');
  const [minOverlapThreshold, setMinOverlapThreshold] = useState<number>(0);
  const [selectedStatus, setSelectedStatus] = useState('all');

  const loadData = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await api.maverick.getFeed({
        department: selectedDepartment,
        status: selectedStatus,
        min_overlap: minOverlapThreshold > 0 ? minOverlapThreshold : undefined,
      });
      if (res) {
        setAlerts(res.alerts || []);
        setKpis(res.kpis || DEFAULT_KPIS);
      }
    } catch {
      setAlerts([]);
      setKpis(DEFAULT_KPIS);
    } finally {
      setIsLoading(false);
    }
  }, [api, selectedDepartment, selectedStatus, minOverlapThreshold]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleTriggerScan = async () => {
    try {
      setIsScanning(true);
      await api.maverick.triggerDetection(90, 'default-org', { source: 'gcs' });
      notify.success(
        'Maverick Scan Dispatched',
        'Worker is normalizing the latest Ramp card-transaction batch from GCS and running Jev identification against the approved software catalog.'
      );
      setTimeout(() => {
        loadData();
      }, 4000);
      setTimeout(() => {
        loadData();
      }, 12000);
    } catch {
      notify.error('Scan Failed', 'Could not dispatch background maverick scan.');
    } finally {
      setIsScanning(false);
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
        const matchesApproved = alert.overlap.approvedAlternative.toLowerCase().includes(q);
        if (!matchesMerchant && !matchesEmployee && !matchesEmail && !matchesApproved) {
          return false;
        }
      }

      // Department matching
      if (selectedDepartment !== 'all' && alert.department !== selectedDepartment) {
        return false;
      }

      // Overlap threshold
      if (minOverlapThreshold > 0 && alert.overlap.cosineSimilarity < minOverlapThreshold) {
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
            TypeSafe AI (Jev System One) detects unmanaged recurring subscriptions on corporate cards and maps semantic vector overlap to approved enterprise catalog contracts.
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
        </div>
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
