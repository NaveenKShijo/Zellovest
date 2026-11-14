'use client';

import React, { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { MaverickAlertItem } from '@/types';
import { MOCK_MAVERICK_ALERTS, MOCK_MAVERICK_KPIS } from '@/lib/mockData';
import { MaverickKPIsBar } from '@/components/maverick/MaverickKPIsBar';
import { MaverickFilters } from '@/components/maverick/MaverickFilters';
import { MaverickAlertFeed } from '@/components/maverick/MaverickAlertFeed';
import { useToast } from '@/contexts/ToastContext';

export default function MaverickSpendPage() {
  const router = useRouter();
  const { notify } = useToast();

  const [alerts, setAlerts] = useState<MaverickAlertItem[]>(MOCK_MAVERICK_ALERTS);

  // Filters state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDepartment, setSelectedDepartment] = useState('all');
  const [minOverlapThreshold, setMinOverlapThreshold] = useState<number>(0);
  const [selectedStatus, setSelectedStatus] = useState('all');

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

  const handleNotifyEmployee = (alertId: string) => {
    const alert = alerts.find((a) => a.id === alertId);
    if (!alert) return;

    setAlerts((prev) =>
      prev.map((a) => (a.id === alertId ? { ...a, status: 'notified' as const } : a))
    );

    notify.success(
      'Migration Notice Dispatched (MCP-3)',
      `Sent automated Slack notification to ${alert.employeeName} (${alert.employeeEmail}) providing 1-click SSO access to ${alert.overlap.approvedAlternative}.`
    );
  };

  const handleDismiss = (alertId: string) => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === alertId ? { ...a, status: 'dismissed' as const } : a))
    );
    notify.info('Exception Logged', 'Corporate card charge approved as legitimate standalone exception.');
  };

  const handleViewContract = (contractId: string) => {
    router.push(`/vendors?contract=${contractId}`);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      {/* Page Header */}
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Maverick Spend & Software Overlap Interface
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
          TypeSafe AI (Jev System One) detects unmanaged recurring subscriptions on corporate cards and maps semantic vector overlap to approved enterprise catalog contracts.
        </p>
      </div>

      {/* 1. KPIs Overview */}
      <MaverickKPIsBar kpis={MOCK_MAVERICK_KPIS} />

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
      <MaverickAlertFeed
        alerts={filteredAlerts}
        onNotifyEmployee={handleNotifyEmployee}
        onDismiss={handleDismiss}
        onViewContract={handleViewContract}
      />
    </div>
  );
}
