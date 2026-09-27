'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

export interface TabConfig {
  key: string;
  label: string;
  href: string;
  count?: number;
  badgeVariant?: 'default' | 'warning' | 'danger' | 'info';
}

interface TabNavigationProps {
  tabs: TabConfig[];
  vendorId: string;
  activeTab?: TabConfig['key'];
  onTabChange?: (tabKey: TabConfig['key']) => void;
}

export function TabNavigation({ tabs, vendorId, activeTab, onTabChange }: TabNavigationProps) {
  const pathname = usePathname();

  const isClientTabMode = !!onTabChange;

  const getIsActive = (tab: TabConfig) => {
    if (activeTab !== undefined) return activeTab === tab.key;
    return pathname === tab.href || pathname.startsWith(`${tab.href}/`);
  };

  const handleClick = (e: React.MouseEvent, tabKey: string) => {
    if (onTabChange) {
      e.preventDefault();
      onTabChange(tabKey as TabConfig['key']);
    }
    // If no onTabChange, allow default Link behavior
  };

  const renderTab = (tab: TabConfig) => {
    const isActive = getIsActive(tab);
    const commonStyle = {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '6px',
      padding: '10px 16px',
      borderRadius: 'var(--radius-md)',
      fontSize: '13px',
      fontWeight: 600,
      color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
      backgroundColor: isActive ? 'var(--bg-surface-tint)' : 'transparent',
      whiteSpace: 'nowrap' as const,
      textDecoration: 'none',
      transition: 'all var(--transition-fast)',
      cursor: 'pointer',
    };

    const badge = tab.count !== undefined && tab.count > 0 && (
      <span
        style={{
          fontSize: '10.5px',
          fontWeight: 700,
          padding: '1px 6px',
          borderRadius: 'var(--radius-full)',
          backgroundColor: isActive
            ? 'var(--color-brand-subtle)'
            : `var(--color-${tab.badgeVariant || 'default'}-subtle)`,
          color: isActive
            ? 'var(--color-brand)'
            : `var(--color-${tab.badgeVariant || 'default'})`,
          border: isActive
            ? '1px solid var(--color-brand-border)'
            : `1px solid var(--color-${tab.badgeVariant || 'default'}-border)`,
        }}
      >
        {tab.count}
      </span>
    );

    if (isClientTabMode) {
      // Use button for client-side tab switching
      return (
        <button
          key={tab.key}
          role="tab"
          aria-selected={isActive}
          onClick={(e) => handleClick(e, tab.key)}
          style={commonStyle}
          onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.color = 'var(--text-primary)'; }}
          onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.color = 'var(--text-secondary)'; }}
        >
          {tab.label}
          {badge}
        </button>
      );
    }

    // Fallback to Link for deep linking without client-side handler
    return (
      <Link
        key={tab.key}
        href={tab.href}
        role="tab"
        aria-selected={isActive}
        style={commonStyle}
        onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.color = 'var(--text-primary)'; }}
        onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.color = 'var(--text-secondary)'; }}
      >
        {tab.label}
        {badge}
      </Link>
    );
  };

  return (
    <nav
      style={{
        display: 'flex',
        gap: '4px',
        backgroundColor: 'var(--bg-surface)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-subtle)',
        padding: '4px',
        overflowX: 'auto',
      }}
      role="tablist"
      aria-label="Vendor 360 sections"
    >
      {tabs.map(renderTab)}
    </nav>
  );
}

export function createVendorTabs(vendorId: string, counts?: {
  contracts?: number;
  invoices?: number;
  transactions?: number;
  documents?: number;
}): TabConfig[] {
  return [
    { key: 'overview', label: 'Overview', href: `/vendors/${vendorId}`, count: undefined },
    { key: 'contracts', label: 'Contracts', href: `/vendors/${vendorId}/contracts`, count: counts?.contracts, badgeVariant: 'info' },
    { key: 'invoices', label: 'Invoices', href: `/vendors/${vendorId}/invoices`, count: counts?.invoices, badgeVariant: 'warning' },
    { key: 'transactions', label: 'Transactions', href: `/vendors/${vendorId}/transactions`, count: counts?.transactions, badgeVariant: 'default' },
    { key: 'documents', label: 'Documents', href: `/vendors/${vendorId}/documents`, count: counts?.documents, badgeVariant: 'info' },
  ];
}