'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Vendor, VendorListParams } from '@/types';
import { useApi } from '@/lib/api';
import { VendorTable } from '@/components/vendors/VendorTable';
import { VendorFilters } from '@/components/vendors/VendorFilters';

export default function VendorsPage() {
  const api = useApi();

  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [sortBy, setSortBy] = useState<VendorListParams['sortBy']>('annualSpend');
  const [sortOrder, setSortOrder] = useState<VendorListParams['sortOrder']>('desc');
  const [searchParams, setSearchParams] = useState<VendorListParams>({});

  const handleSort = (key: string, order: 'asc' | 'desc') => {
    setLoading(true);
    setSortBy(key as VendorListParams['sortBy']);
    setSortOrder(order);
    setPage(1);
  };

  const handleFiltersChange = useCallback((params: VendorListParams) => {
    setLoading(true);
    setSearchParams((prev) => (JSON.stringify(prev) === JSON.stringify(params) ? prev : params));
    setPage(1);
  }, []);

  const refetch = () => {
    setLoading(true);
    setRefreshKey((k) => k + 1);
  };

  useEffect(() => {
    let active = true;

    const queryParams: VendorListParams = {
      page,
      pageSize,
      sortBy,
      sortOrder,
      ...searchParams,
    };

    api.vendors
      .list(queryParams)
      .then((res) => {
        if (!active) return;
        setVendors(res.vendors || []);
        setTotal(res.total ?? 0);
        setError(null);
      })
      .catch((caught) => {
        if (!active) return;
        console.error('Failed to load vendors from database:', caught);
        setError(caught instanceof Error ? caught.message : 'Unable to load vendors from database.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [page, pageSize, sortBy, sortOrder, searchParams, refreshKey, api]);

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
              Live PostgreSQL Data
            </span>
          </div>

          {error && (
            <div
              style={{
                margin: '16px 24px',
                padding: '12px 16px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: '#EF4444',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <span>{error}</span>
              <button
                onClick={refetch}
                style={{
                  background: 'none',
                  border: '1px solid #EF4444',
                  borderRadius: 'var(--radius-sm)',
                  padding: '4px 10px',
                  color: '#EF4444',
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontSize: '12px',
                }}
              >
                Retry
              </button>
            </div>
          )}

          <VendorTable
            vendors={vendors}
            onSort={handleSort}
            sortBy={sortBy}
            sortOrder={sortOrder}
            isLoading={loading}
            emptyMessage="No vendors match your filters. Try adjusting your search criteria or add a new vendor."
          />

          {!loading && totalPages > 1 && (
            <div style={{ padding: '16px 24px', borderTop: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                Showing {Math.min((page - 1) * pageSize + 1, total)} to {Math.min(page * pageSize, total)} of {total} vendors
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setLoading(true);
                    setPageSize(Number(e.target.value));
                    setPage(1);
                  }}
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
                  onClick={() => {
                    setLoading(true);
                    setPage((p) => Math.max(1, p - 1));
                  }}
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
                  onClick={() => {
                    setLoading(true);
                    setPage((p) => Math.min(totalPages, p + 1));
                  }}
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
