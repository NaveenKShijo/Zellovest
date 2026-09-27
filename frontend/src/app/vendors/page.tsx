'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { Vendor, VendorListParams } from '@/types';
import { VendorTable } from '@/components/vendors/VendorTable';
import { VendorFilters } from '@/components/vendors/VendorFilters';

const MOCK_VENDORS: Vendor[] = [
  {
    id: 'ven_001',
    canonicalName: 'Salesforce',
    domain: 'salesforce.com',
    primaryContact: { name: 'Sarah Mitchell', email: 'sarah.mitchell@salesforce.com', phone: '+1 (415) 901-7000' },
    paymentTerms: 'net_45',
    categories: ['CRM & Sales'],
    annualSpend: 168000,
    currency: 'USD',
    status: 'variance_flagged',
    contractCount: 3,
    invoiceCount: 12,
    transactionCount: 45,
    createdAt: '2024-01-15T10:00:00Z',
    updatedAt: '2025-08-20T14:30:00Z',
  },
  {
    id: 'ven_002',
    canonicalName: 'Figma',
    domain: 'figma.com',
    primaryContact: { name: 'Alex Chen', email: 'alex.chen@figma.com' },
    paymentTerms: 'net_30',
    categories: ['Design & Prototyping'],
    annualSpend: 45000,
    currency: 'USD',
    status: 'compliant',
    contractCount: 1,
    invoiceCount: 4,
    transactionCount: 8,
    createdAt: '2024-03-22T09:15:00Z',
    updatedAt: '2025-07-10T11:20:00Z',
  },
  {
    id: 'ven_003',
    canonicalName: 'Datadog',
    domain: 'datadoghq.com',
    primaryContact: { name: 'Maria Rodriguez', email: 'maria.rodriguez@datadoghq.com' },
    paymentTerms: 'net_60',
    categories: ['Cloud Infrastructure'],
    annualSpend: 92400,
    currency: 'USD',
    status: 'variance_flagged',
    contractCount: 2,
    invoiceCount: 8,
    transactionCount: 23,
    createdAt: '2024-02-10T14:00:00Z',
    updatedAt: '2025-09-01T16:45:00Z',
  },
  {
    id: 'ven_004',
    canonicalName: 'Slack',
    domain: 'slack.com',
    primaryContact: { name: 'James Wilson', email: 'james.wilson@slack.com' },
    paymentTerms: 'net_30',
    categories: ['Productivity & Messaging'],
    annualSpend: 75000,
    currency: 'USD',
    status: 'compliant',
    contractCount: 1,
    invoiceCount: 6,
    transactionCount: 12,
    createdAt: '2023-11-05T10:30:00Z',
    updatedAt: '2025-06-15T09:00:00Z',
  },
  {
    id: 'ven_005',
    canonicalName: 'GitHub',
    domain: 'github.com',
    primaryContact: { name: 'Lisa Park', email: 'lisa.park@github.com' },
    paymentTerms: 'net_30',
    categories: ['Development Tools'],
    annualSpend: 38400,
    currency: 'USD',
    status: 'compliant',
    contractCount: 1,
    invoiceCount: 5,
    transactionCount: 18,
    createdAt: '2024-05-18T11:00:00Z',
    updatedAt: '2025-08-05T13:20:00Z',
  },
  {
    id: 'ven_006',
    canonicalName: 'Workday',
    domain: 'workday.com',
    primaryContact: { name: 'Robert Kim', email: 'robert.kim@workday.com' },
    paymentTerms: 'net_45',
    categories: ['HR & Finance'],
    annualSpend: 142000,
    currency: 'USD',
    status: 'up_for_renewal',
    contractCount: 2,
    invoiceCount: 10,
    transactionCount: 31,
    createdAt: '2023-09-12T08:45:00Z',
    updatedAt: '2025-09-10T10:15:00Z',
  },
  {
    id: 'ven_007',
    canonicalName: 'Adobe',
    domain: 'adobe.com',
    primaryContact: { name: 'Emily Davis', email: 'emily.davis@adobe.com' },
    paymentTerms: 'net_30',
    categories: ['Design & Prototyping', 'Marketing & Analytics'],
    annualSpend: 89000,
    currency: 'USD',
    status: 'up_for_renewal',
    contractCount: 3,
    invoiceCount: 14,
    transactionCount: 28,
    createdAt: '2023-06-20T15:00:00Z',
    updatedAt: '2025-08-28T12:00:00Z',
  },
  {
    id: 'ven_008',
    canonicalName: 'Atlassian',
    domain: 'atlassian.com',
    primaryContact: { name: 'Michael Brown', email: 'michael.brown@atlassian.com' },
    paymentTerms: 'net_30',
    categories: ['Development Tools', 'Productivity & Messaging'],
    annualSpend: 56000,
    currency: 'USD',
    status: 'compliant',
    contractCount: 2,
    invoiceCount: 7,
    transactionCount: 15,
    createdAt: '2024-01-08T12:00:00Z',
    updatedAt: '2025-07-22T14:30:00Z',
  },
  {
    id: 'ven_009',
    canonicalName: 'Snowflake',
    domain: 'snowflake.com',
    primaryContact: { name: 'Jennifer Lee', email: 'jennifer.lee@snowflake.com' },
    paymentTerms: 'net_60',
    categories: ['Cloud Infrastructure'],
    annualSpend: 125000,
    currency: 'USD',
    status: 'compliant',
    contractCount: 1,
    invoiceCount: 4,
    transactionCount: 9,
    createdAt: '2024-04-30T10:00:00Z',
    updatedAt: '2025-08-15T11:00:00Z',
  },
  {
    id: 'ven_010',
    canonicalName: 'Cursor.sh',
    domain: 'cursor.sh',
    primaryContact: { name: 'Unknown', email: 'support@cursor.sh' },
    paymentTerms: 'net_30',
    categories: ['Development Tools'],
    annualSpend: 2400,
    currency: 'USD',
    status: 'maverick_detected',
    contractCount: 0,
    invoiceCount: 0,
    transactionCount: 12,
    createdAt: '2025-07-15T09:00:00Z',
    updatedAt: '2025-09-01T10:00:00Z',
  },
];

function computeFilteredVendors(
  allVendors: Vendor[],
  searchParams: VendorListParams,
  sortBy: VendorListParams['sortBy'],
  sortOrder: VendorListParams['sortOrder'],
  page: number,
  pageSize: number
) {
  let filtered = [...allVendors];

  if (searchParams.search) {
    const q = searchParams.search.toLowerCase();
    filtered = filtered.filter(
      (v) =>
        v.canonicalName.toLowerCase().includes(q) ||
        v.domain?.toLowerCase().includes(q) ||
        v.primaryContact?.name.toLowerCase().includes(q) ||
        v.primaryContact?.email.toLowerCase().includes(q)
    );
  }

  if (searchParams.categories?.length) {
    filtered = filtered.filter((v) => v.categories.some((c) => searchParams.categories!.includes(c)));
  }

  if (searchParams.statuses?.length) {
    filtered = filtered.filter((v) => searchParams.statuses!.includes(v.status));
  }

  if (searchParams.minSpend !== undefined) {
    filtered = filtered.filter((v) => v.annualSpend >= searchParams.minSpend!);
  }

  if (searchParams.maxSpend !== undefined) {
    filtered = filtered.filter((v) => v.annualSpend <= searchParams.maxSpend!);
  }

  filtered.sort((a, b) => {
    const key = sortBy || 'annualSpend';
    const order = sortOrder === 'asc' ? 1 : -1;
    const aVal = a[key as keyof Vendor];
    const bVal = b[key as keyof Vendor];
    if (aVal === undefined || bVal === undefined) return 0;
    if (aVal < bVal) return -1 * order;
    if (aVal > bVal) return 1 * order;
    return 0;
  });

  const total = filtered.length;
  const start = (page - 1) * pageSize;
  const vendors = filtered.slice(start, start + pageSize);
  return { vendors, total };
}

export default function VendorsPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [sortBy, setSortBy] = useState<VendorListParams['sortBy']>('annualSpend');
  const [sortOrder, setSortOrder] = useState<VendorListParams['sortOrder']>('desc');
  const [searchParams, setSearchParams] = useState<VendorListParams>({});

  const { vendors, total } = computeFilteredVendors(MOCK_VENDORS, searchParams, sortBy, sortOrder, page, pageSize);

  const handleSort = (key: string, order: 'asc' | 'desc') => {
    setSortBy(key as VendorListParams['sortBy']);
    setSortOrder(order);
    setPage(1);
  };

  const handleFiltersChange = React.useCallback((params: VendorListParams) => {
    setSearchParams((prev) => (JSON.stringify(prev) === JSON.stringify(params) ? prev : params));
    setPage(1);
  }, []);

  const totalPages = Math.ceil(total / pageSize) || 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
            Vendor 360
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
            Unified procurement profiles connecting corporate cards, contracts, invoices, and Okta seat activity.
          </p>
        </div>
        <Link
          href="/vendors/new"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 16px',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'var(--color-brand)',
            color: '#FFFFFF',
            fontSize: '13px',
            fontWeight: 600,
            whiteSpace: 'nowrap',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-brand-hover)')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-brand)')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          Add Vendor
        </Link>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '20px' }}>
        <VendorFilters initialParams={searchParams} onChange={handleFiltersChange} totalCount={total} />

        <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', overflow: 'hidden' }}>
          <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Active Vendor Catalog ({total})
            </h2>
            <span style={{ fontSize: '12px', color: 'var(--color-brand)', fontWeight: 600 }}>
              Syncing via Ramp & Okta
            </span>
          </div>

          <VendorTable
            vendors={vendors}
            onSort={handleSort}
            sortBy={sortBy}
            sortOrder={sortOrder}
            emptyMessage="No vendors match your filters. Try adjusting your search criteria."
          />

          {totalPages > 1 && (
            <div style={{ padding: '16px 24px', borderTop: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                Showing {Math.min((page - 1) * pageSize + 1, total)} to {Math.min(page * pageSize, total)} of {total} vendors
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <select
                  value={pageSize}
                  onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
                  style={{
                    padding: '6px 10px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-subtle)',
                    backgroundColor: 'var(--bg-app)',
                    fontSize: '12px',
                    color: 'var(--text-primary)',
                    outline: 'none',
                  }}
                >
                  <option value={10}>10 per page</option>
                  <option value={25}>25 per page</option>
                  <option value={50}>50 per page</option>
                  <option value={100}>100 per page</option>
                </select>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  style={{
                    padding: '6px 12px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12px',
                    fontWeight: 600,
                    color: page === 1 ? 'var(--text-muted)' : 'var(--color-brand)',
                    backgroundColor: page === 1 ? 'var(--bg-app)' : 'var(--bg-surface-tint)',
                    border: '1px solid var(--border-subtle)',
                    cursor: page === 1 ? 'not-allowed' : 'pointer',
                  }}
                >
                  Previous
                </button>
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)', minWidth: '40px', textAlign: 'center' }}>
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  style={{
                    padding: '6px 12px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12px',
                    fontWeight: 600,
                    color: page === totalPages ? 'var(--text-muted)' : 'var(--color-brand)',
                    backgroundColor: page === totalPages ? 'var(--bg-app)' : 'var(--bg-surface-tint)',
                    border: '1px solid var(--border-subtle)',
                    cursor: page === totalPages ? 'not-allowed' : 'pointer',
                  }}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}