'use client';

import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  ExceptionRuleType,
  AuditExceptionStatus,
  ReconciliationItem,
  APAuditKPIs,
} from '@/types';
import { APAuditKPIsBar } from '@/components/compliance/APAuditKPIsBar';
import { AuditFilters } from '@/components/compliance/AuditFilters';
import { ReconciliationTable } from '@/components/compliance/ReconciliationTable';
import { LineItemComparisonModal } from '@/components/compliance/LineItemComparisonModal';
import { useToast } from '@/contexts/ToastContext';
import { useApi } from '@/lib/api';

const EMPTY_KPIS: APAuditKPIs = {
  totalInvoicedAmount: 0,
  flaggedDiscrepancyAmount: 0,
  totalInvoicesCount: 0,
  cleanInvoicesCount: 0,
  exceptionInvoicesCount: 0,
  unreconciledInvoicesCount: 0,
  cleanRatePct: 0,
};

type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as UnknownRecord
    : {};
}

export default function CompliancePage() {
  const router = useRouter();
  const api = useApi();
  const { notify } = useToast();

  const [kpis, setKpis] = useState<APAuditKPIs>(EMPTY_KPIS);
  const [items, setItems] = useState<ReconciliationItem[]>([]);
  const [selectedItem, setSelectedItem] = useState<ReconciliationItem | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Filters state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedRule, setSelectedRule] = useState<ExceptionRuleType | 'all'>('all');
  const [selectedStatus, setSelectedStatus] = useState<AuditExceptionStatus | 'all'>('all');

  // Load real data from FastAPI backend
  const fetchData = useCallback(async () => {
    try {
      const statusParam = selectedStatus !== 'all' ? selectedStatus : 'all';
      const [kpiRes, excRes] = await Promise.allSettled([
        api.compliance.getKpis(),
        api.compliance.listExceptions({
          status: statusParam,
        }),
      ]);

      if (kpiRes.status === 'fulfilled' && kpiRes.value) {
        const raw = asRecord(kpiRes.value);
        setKpis({
          totalInvoicedAmount: Number(raw.total_invoiced_amount ?? raw.totalInvoicedAmount ?? 0),
          flaggedDiscrepancyAmount: Number(raw.flagged_discrepancy_amount ?? raw.flaggedDiscrepancyAmount ?? 0),
          totalInvoicesCount: Number(raw.total_invoices_count ?? raw.totalInvoicesCount ?? 0),
          cleanInvoicesCount: Number(raw.clean_invoices_count ?? raw.cleanInvoicesCount ?? 0),
          exceptionInvoicesCount: Number(raw.exception_invoices_count ?? raw.exceptionInvoicesCount ?? 0),
          unreconciledInvoicesCount: Number(raw.unreconciled_invoices_count ?? raw.unreconciledInvoicesCount ?? 0),
          cleanRatePct: Number(raw.clean_rate_pct ?? raw.cleanRatePct ?? 0),
        });
      } else {
        setKpis(EMPTY_KPIS);
      }

      if (excRes.status === 'fulfilled' && excRes.value) {
        const response = asRecord(excRes.value);
        const rawList: unknown[] = Array.isArray(response.items) ? response.items : [];
        const mappedItems: ReconciliationItem[] = rawList.map((entry) => {
          const raw = asRecord(entry);
          const lineItems = raw.line_items_comparison ?? raw.lineItemsComparison;
          const mappedLineItems = (Array.isArray(lineItems) ? lineItems : []).map((lineItem) => {
            const li = asRecord(lineItem);
            return {
              id: String(li.id),
              lineNumber: Number(li.line_number ?? li.lineNumber ?? 1),
              productCode: li.product_code ?? li.productCode ?? '',
              description: li.description ?? '',
              billedUnitPrice: Number(li.billed_unit_price ?? li.billedUnitPrice ?? 0),
              contractedUnitPrice: Number(li.contracted_unit_price ?? li.contractedUnitPrice ?? 0),
              billedQuantity: Number(li.billed_quantity ?? li.billedQuantity ?? 1),
              tierMinQuantity: li.tier_min_quantity ?? li.tierMinQuantity ?? null,
              tierMaxQuantity: li.tier_max_quantity ?? li.tierMaxQuantity ?? null,
              varianceAmount: Number(li.variance_amount ?? li.varianceAmount ?? 0),
              extendedVarianceAmount: li.extended_variance_amount != null
                ? Number(li.extended_variance_amount)
                : li.extendedVarianceAmount != null
                  ? Number(li.extendedVarianceAmount)
                  : undefined,
              variancePct: Number(li.variance_pct ?? li.variancePct ?? 0),
              rule: li.rule ?? 'price',
              explanation: li.explanation ?? 'Line item discrepancy.',
            };
          });
          return ({
          id: String(raw.id),
          invoiceId: String(raw.invoice_id ?? raw.invoiceId),
          invoiceNumber: raw.invoice_number ?? raw.invoiceNumber ?? 'INV-UNKNOWN',
          vendorId: String(raw.vendor_id ?? raw.vendorId),
          vendorName: raw.vendor_name ?? raw.vendorName ?? 'Unknown Vendor',
          invoiceDate: raw.invoice_date ?? raw.invoiceDate,
          dueDate: raw.due_date ?? raw.dueDate ?? '',
          totalAmount: Number(raw.total_amount ?? raw.totalAmount ?? 0),
          currency: raw.currency ?? 'USD',
          discrepancyAmount: Math.abs(Number(raw.discrepancy_amount ?? raw.discrepancyAmount ?? 0)),
          primaryRule: raw.primary_rule ?? raw.primaryRule ?? 'price',
          ruleLabel: raw.rule_label ?? raw.ruleLabel ?? 'Price Discrepancy',
          severity: raw.severity ?? 'medium',
          status: raw.status ?? 'open',
          contractId: String(raw.contract_id ?? raw.contractId),
          contractNumber: raw.contract_number ?? raw.contractNumber ?? 'MSA-CONTRACT',
          contractTitle: raw.contract_title ?? raw.contractTitle ?? 'Master Agreement',
          poNumber: raw.po_number ?? raw.poNumber ?? null,
          detectedAt: raw.detected_at ?? raw.detectedAt ?? new Date().toISOString(),
          investigationReason: raw.investigation_reason ?? raw.investigationReason ?? 'Audit exception flagged.',
          lineItemsComparison: mappedLineItems,
          } as unknown as ReconciliationItem);
        });
        setItems(mappedItems);
      } else {
        setItems([]);
      }
    } catch {
      setKpis(EMPTY_KPIS);
      setItems([]);
    }
  }, [api, selectedStatus]);

  useEffect(() => {
    let active = true;
    const initialFetch = window.setTimeout(() => {
      if (active) void fetchData();
    }, 0);

    // Refetch when the user refocuses the window (e.g. after uploading or deleting documents)
    const handleFocus = () => {
      fetchData();
    };
    window.addEventListener('focus', handleFocus);
    return () => {
      active = false;
      window.clearTimeout(initialFetch);
      window.removeEventListener('focus', handleFocus);
    };
  }, [fetchData]);

  // Filtered items
  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      // Search matching
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesInv = item.invoiceNumber.toLowerCase().includes(q);
        const matchesVendor = item.vendorName.toLowerCase().includes(q);
        const matchesContract = item.contractNumber.toLowerCase().includes(q);
        if (!matchesInv && !matchesVendor && !matchesContract) {
          return false;
        }
      }

      // Rule matching
      if (selectedRule !== 'all' && item.primaryRule !== selectedRule) {
        return false;
      }

      // Status matching
      if (selectedStatus !== 'all' && item.status !== selectedStatus) {
        return false;
      }

      return true;
    });
  }, [items, searchQuery, selectedRule, selectedStatus]);

  const handleRowClick = (item: ReconciliationItem) => {
    setSelectedItem(item);
    setIsModalOpen(true);
  };

  const handleLaunchInvestigation = (item: ReconciliationItem) => {
    notify.info(
      'Investigation Agent Dispatched',
      `Analyzing variance root cause for ${item.vendorName} (${item.invoiceNumber}) against ${item.contractNumber}.`
    );
    const prompt = encodeURIComponent(
      `Investigate AP audit discrepancy on invoice ${item.invoiceNumber} from vendor ${item.vendorName}. Rule: ${item.ruleLabel}, Discrepancy Amount: $${item.discrepancyAmount}. Context: ${item.investigationReason}`
    );
    router.push(`/assistant?prompt=${prompt}`);
  };

  const handleAcknowledge = async (itemId: string) => {
    try {
      await api.compliance.updateStatus(itemId, 'acknowledged');
    } catch {
      // Handled gracefully
    }

    setItems((prev) =>
      prev.map((it) => (it.id === itemId ? { ...it, status: 'acknowledged' as const } : it))
    );
    if (selectedItem?.id === itemId) {
      setSelectedItem((prev) => (prev ? { ...prev, status: 'acknowledged' } : null));
    }
    notify.success('Invoice Discrepancy Acknowledged', 'Status updated to Acknowledged in audit log.');
  };

  const handlePurgeOrphans = async () => {
    try {
      const res = await api.compliance.purgeOrphans();
      const count = Object.values(res.purged).reduce((a, b) => a + b, 0);
      notify.success('Orphan Records Purged', `Cleaned up ${count} stale ledger records not tied to active documents.`);
      fetchData();
    } catch {
      notify.error('Purge Failed', 'Could not purge orphaned records.');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
            AP Audit & Reconciliation Dashboard
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
            Deterministic reconciliation engine checking invoice line items against locked contractual schedules and PO rules.
          </p>
        </div>
        {kpis.unreconciledInvoicesCount > 0 && (
          <button
            onClick={handlePurgeOrphans}
            style={{
              padding: '8px 14px',
              fontSize: '12.5px',
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-subtle)',
              backgroundColor: '#FFFFFF',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
            title="Clean out invoices and ledger records not attached to an active document"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
            Purge Stale/Orphan Records
          </button>
        )}
      </div>

      {/* 1. Overview KPIs (Always real values) */}
      <APAuditKPIsBar kpis={kpis} />

      {/* 2. Filters Bar */}
      <AuditFilters
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        selectedRule={selectedRule}
        onRuleChange={setSelectedRule}
        selectedStatus={selectedStatus}
        onStatusChange={setSelectedStatus}
      />

      {/* 3. Reconciliation Table (Only real discrepancies listed; empty if none) */}
      <ReconciliationTable
        items={filteredItems}
        totalInvoicesCount={kpis.totalInvoicesCount}
        onSelectRow={handleRowClick}
        onLaunchInvestigation={handleLaunchInvestigation}
      />

      {/* 4. Line-Item Comparison Modal */}
      <LineItemComparisonModal
        item={selectedItem}
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onLaunchInvestigation={handleLaunchInvestigation}
        onAcknowledge={handleAcknowledge}
      />
    </div>
  );
}
