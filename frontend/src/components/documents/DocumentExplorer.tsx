'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
    DocumentListResponse,
    DocumentRecord,
    DocumentStatus,
} from '@/types';
import { useApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import { DocumentFilters } from './DocumentFilters';
import { DocumentTable } from './DocumentTable';
import type { DocumentSortField } from './DocumentTable';

/** Explorer tabs. `all` shows every type; `policies_other` merges policy + other. */
const EXPLORER_TABS: Array<{
    id: string;
    label: string;
    /** Query param values; undefined = no type filter (all). */
    documentType?: string;
    documentTypes?: string;
}> = [
    { id: 'all', label: 'All Files' },
    { id: 'contracts', label: 'Contracts / MSAs', documentType: 'contract' },
    { id: 'amendments', label: 'Amendments', documentType: 'amendment' },
    { id: 'purchase_orders', label: 'Purchase Orders', documentType: 'purchase_order' },
    { id: 'invoices', label: 'Invoices', documentType: 'invoice' },
    { id: 'policies_other', label: 'Policies / Other', documentTypes: 'policy,other' },
];

const PAGE_SIZE_DEFAULT = 20;

const PAGE_SIZE_OPTIONS = [20, 50];

/** Fetch result keyed by the exact filter combo that produced it. */
interface FetchResult {
    key: string;
    data: DocumentListResponse | null;
    error: string | null;
    /** True once the fetch for `key` settled (success or failure). */
    done: boolean;
}

/**
 * Document Explorer — read-only inventory of every GCS-backed document
 * (uploads leases + extraction artifacts), URL-driven so views are
 * shareable: ``?tab=invoices&status=review_needed&vendor=Adobe&page=2``.
 */
export function DocumentExplorer() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const api = useApi();
    const { notify } = useToast();

    // ---- URL state ------------------------------------------------------
    const tabParam = searchParams.get('tab') ?? 'all';
    const tab = EXPLORER_TABS.some((t) => t.id === tabParam) ? tabParam : 'all';
    const status = (searchParams.get('status') as DocumentStatus | null) ?? null;
    const vendor = searchParams.get('vendor') ?? '';
    const q = searchParams.get('q') ?? '';
    const page = Math.max(1, Number(searchParams.get('page') || '1') || 1);
    const pageSize = PAGE_SIZE_OPTIONS.includes(Number(searchParams.get('page_size')))
        ? Number(searchParams.get('page_size'))
        : PAGE_SIZE_DEFAULT;
    const sortField = (searchParams.get('sort') as DocumentSortField | null) ?? null;
    const sortDir: 'asc' | 'desc' = searchParams.get('dir') === 'asc' ? 'asc' : 'desc';

    /** Identity of the current filter combination. */
    const viewKey = useMemo(
        () =>
            [tab, status ?? '', vendor, q, String(page), String(pageSize)].join('|'),
        [tab, status, vendor, q, page, pageSize]
    );
    const activeTab = useMemo(
        () => EXPLORER_TABS.find((t) => t.id === tab) ?? EXPLORER_TABS[0],
        [tab]
    );

    /** Patch one or more query params into the URL (page resets unless set). */
    const updateParams = useCallback(
        (patch: Record<string, string | null>) => {
            const next = new URLSearchParams(searchParams.toString());
            Object.entries(patch).forEach(([key, value]) => {
                if (value === null || value === '') next.delete(key);
                else next.set(key, value);
            });
            if (!('page' in patch)) next.delete('page'); // view changes reset paging
            router.push(`/documents?${next.toString()}`, { scroll: false });
        },
        [router, searchParams]
    );

    // Debounced search/vendor inputs: local keystrokes first, URL after 350ms.
    // When the URL changes underneath us (deep link, back/forward), the
    // drafts are re-synced via the adjust-state-during-render pattern below.
    const [searchDraft, setSearchDraft] = useState(q);
    const [vendorDraft, setVendorDraft] = useState(vendor);
    const [lastUrl, setLastUrl] = useState({ q, vendor });
    const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    if (lastUrl.q !== q || lastUrl.vendor !== vendor) {
        setLastUrl({ q, vendor });
        setSearchDraft(q);
        setVendorDraft(vendor);
    }

    useEffect(() => {
        return () => {
            if (searchTimer.current) clearTimeout(searchTimer.current);
        };
    }, []);

    const commitDraft = useCallback(
        (key: 'q' | 'vendor', value: string) => {
            if (searchTimer.current) clearTimeout(searchTimer.current);
            searchTimer.current = setTimeout(() => {
                updateParams({ [key]: value || null });
            }, 350);
        },
        [updateParams]
    );

    // ---- Data (only async setState; loading is derived from key staleness)
    const [result, setResult] = useState<FetchResult>({
        key: '',
        data: null,
        error: null,
        done: false,
    });
    const [retryKey, setRetryKey] = useState(0);
    const requestIdRef = useRef(0);

    // ---- Delete flow -----------------------------------------------------
    const [deleteTarget, setDeleteTarget] = useState<DocumentRecord | null>(null);
    const [deletingId, setDeletingId] = useState<string | null>(null);

    useEffect(() => {
        const requestId = ++requestIdRef.current;
        api.documents
            .list({
                document_type: activeTab.documentType,
                document_types: activeTab.documentTypes,
                status: status ?? undefined,
                vendor_id: vendor || undefined,
                search: q || undefined,
                page,
                page_size: pageSize,
            })
            .then((response) => {
                if (requestId !== requestIdRef.current) return; // stale response
                setResult({ key: viewKey, data: response, error: null, done: true });
            })
            .catch((err: unknown) => {
                if (requestId !== requestIdRef.current) return;
                setResult({
                    key: viewKey,
                    data: null,
                    error: err instanceof Error ? err.message : 'Failed to load documents',
                    done: true,
                });
            });
        // api.documents.list is recreated each render; the params above are
        // the real inputs and change with the URL key.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [viewKey, retryKey]);

    const isCurrent = result.done && result.key === viewKey;
    const isLoading = !result.done || result.key !== viewKey;

    // Server returns newest-first always; when the user picks a sort field
    // we re-order the current page client-side (small pages keep it simple).
    const visible = useMemo(() => {
        const rows = result.data?.documents ?? [];
        if (!sortField) return rows;
        const sorted = [...rows].sort((a, b) => {
            const key = sortField as keyof (typeof rows)[number];
            const av = a[key] ?? '';
            const bv = b[key] ?? '';
            if (typeof av === 'number' && typeof bv === 'number') return av - bv;
            return String(av).localeCompare(String(bv));
        });
        return sortDir === 'asc' ? sorted : sorted.reverse();
    }, [result, sortField, sortDir]);

    const totalPages = result.data ? Math.max(1, Math.ceil(result.data.total / result.data.page_size)) : 1;

    const handleSort = useCallback(
        (field: DocumentSortField) => {
            if (sortField === field) {
                updateParams({ sort: field, dir: sortDir === 'asc' ? 'desc' : 'asc' });
            } else {
                updateParams({ sort: field, dir: 'desc' });
            }
        },
        [sortField, sortDir, updateParams]
    );

    useEffect(() => {
        if (!deleteTarget) return;
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape' && !deletingId) setDeleteTarget(null);
        };
        document.addEventListener('keydown', handleKeyDown);
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = previousOverflow;
        };
    }, [deleteTarget, deletingId]);

    const handleDeleteConfirm = useCallback(async () => {
        if (!deleteTarget || deletingId) return;
        const target = deleteTarget;
        setDeletingId(target.id);
        try {
            await api.documents.delete(target.id);
            setDeleteTarget(null);
            notify.success(
                'Document deleted',
                `${target.filename} and every record derived from it were removed.`
            );
            // Deleting the only row on a later page leaves the URL pointing
            // past the end; step back one page instead of showing an empty
            // stale page.
            if (visible.length <= 1 && page > 1) {
                updateParams({ page: String(page - 1) });
            } else {
                setRetryKey((key) => key + 1);
            }
        } catch (error) {
            notify.error(
                'Delete failed',
                error instanceof Error ? error.message : 'The document could not be deleted.'
            );
        } finally {
            setDeletingId(null);
        }
    }, [api, deleteTarget, deletingId, notify, page, updateParams, visible.length]);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
                <div>
                    <h1 style={{ fontSize: '22px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                        Document Explorer
                    </h1>
                    <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '4px 0 0' }}>
                        Every document stored in the pipeline — extraction status, vendor, and provenance at a glance.
                    </p>
                </div>
                {result.data && isCurrent && (
                    <span style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-muted)' }}>
                        {result.data.total} document{result.data.total === 1 ? '' : 's'}
                    </span>
                )}
            </div>

            {/* Tabs */}
            <div role="tablist" aria-label="Document types" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '12px' }}>
                {EXPLORER_TABS.map((t) => {
                    const isActive = t.id === tab;
                    return (
                        <button
                            key={t.id}
                            type="button"
                            role="tab"
                            aria-selected={isActive}
                            onClick={() => updateParams({ tab: t.id, sort: null })}
                            style={{
                                padding: '8px 16px',
                                borderRadius: 'var(--radius-full)',
                                fontSize: '13px',
                                fontWeight: isActive ? 700 : 500,
                                border: `1px solid ${isActive ? 'var(--color-brand)' : 'var(--border-subtle)'}`,
                                backgroundColor: isActive ? 'var(--color-brand)' : 'var(--bg-surface)',
                                color: isActive ? '#FFFFFF' : 'var(--text-secondary)',
                                cursor: 'pointer',
                                transition: 'all var(--transition-fast)',
                            }}
                        >
                            {t.label}
                        </button>
                    );
                })}
            </div>

            {/* Filters */}
            <DocumentFilters
                search={searchDraft}
                status={status}
                vendor={vendorDraft}
                totalCount={result.data?.total ?? 0}
                onSearchChange={(value) => {
                    setSearchDraft(value);
                    commitDraft('q', value);
                }}
                onStatusChange={(value) => updateParams({ status: value })}
                onVendorChange={(value) => {
                    setVendorDraft(value);
                    commitDraft('vendor', value);
                }}
            />

            {/* Error banner (only for the settled fetch of this exact view) */}
            {result.error && isCurrent && (
                <div
                    role="alert"
                    style={{
                        padding: '12px 16px',
                        borderRadius: 'var(--radius-md)',
                        backgroundColor: 'var(--color-danger-subtle)',
                        border: '1px solid var(--color-danger-border)',
                        color: 'var(--color-danger)',
                        fontSize: '13px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '12px',
                    }}
                >
                    <span>Could not load documents: {result.error}</span>
                    <button
                        type="button"
                        onClick={() => setRetryKey((key) => key + 1)}
                        style={{
                            all: 'unset',
                            cursor: 'pointer',
                            fontWeight: 700,
                            fontSize: '12px',
                            textDecoration: 'underline',
                        }}
                    >
                        Retry
                    </button>
                </div>
            )}

            {/* Table / loading skeleton */}
            {isLoading ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }} aria-hidden="true">
                    {[1, 2, 3, 4, 5].map((i) => (
                        <div
                            key={i}
                            style={{
                                height: '54px',
                                background: 'var(--bg-surface-tint)',
                                borderRadius: 'var(--radius-md)',
                                animation: 'pulse 1.5s ease-in-out infinite',
                            }}
                        />
                    ))}
                </div>
            ) : (
                <DocumentTable
                    documents={visible}
                    sortField={sortField}
                    sortDir={sortDir}
                    onSortChange={handleSort}
                    onDelete={setDeleteTarget}
                    deletingId={deletingId}
                />
            )}

            {/* Pagination */}
            {result.data && isCurrent && !isLoading && result.data.total > 0 && (
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        flexWrap: 'wrap',
                        gap: '10px',
                        fontSize: '12.5px',
                        color: 'var(--text-secondary)',
                    }}
                >
                    <span>
                        Showing{' '}
                        {(result.data.page - 1) * result.data.page_size + 1}–
                        {Math.min(result.data.page * result.data.page_size, result.data.total)} of{' '}
                        {result.data.total}
                    </span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <button
                            type="button"
                            aria-label="Previous page"
                            disabled={page <= 1}
                            onClick={() => updateParams({ page: String(page - 1) })}
                            style={{
                                padding: '7px 12px',
                                borderRadius: 'var(--radius-sm)',
                                border: '1px solid var(--border-subtle)',
                                backgroundColor: 'var(--bg-surface)',
                                color: page <= 1 ? 'var(--text-muted)' : 'var(--text-secondary)',
                                fontSize: '12.5px',
                                fontWeight: 600,
                                cursor: page <= 1 ? 'default' : 'pointer',
                            }}
                        >
                            ← Prev
                        </button>
                        <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>
                            Page {result.data.page} of {totalPages}
                        </span>
                        <button
                            type="button"
                            aria-label="Next page"
                            disabled={page >= totalPages}
                            onClick={() => updateParams({ page: String(page + 1) })}
                            style={{
                                padding: '7px 12px',
                                borderRadius: 'var(--radius-sm)',
                                border: '1px solid var(--border-subtle)',
                                backgroundColor: 'var(--bg-surface)',
                                color: page >= totalPages ? 'var(--text-muted)' : 'var(--text-secondary)',
                                fontSize: '12.5px',
                                fontWeight: 600,
                                cursor: page >= totalPages ? 'default' : 'pointer',
                            }}
                        >
                            Next →
                        </button>
                    </div>
                </div>
            )}

            {/* Destructive confirmation: deleting cascades into every ledger. */}
            {deleteTarget && (
                <div
                    role="presentation"
                    onMouseDown={(event) => {
                        if (event.target === event.currentTarget && !deletingId) {
                            setDeleteTarget(null);
                        }
                    }}
                    style={{
                        position: 'fixed',
                        inset: 0,
                        zIndex: 250,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: '20px',
                        backgroundColor: 'rgba(15, 23, 42, 0.45)',
                        backdropFilter: 'blur(2px)',
                    }}
                >
                    <div
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="delete-document-title"
                        aria-describedby="delete-document-description"
                        style={{
                            width: 'min(480px, 100%)',
                            padding: '22px 24px',
                            borderRadius: 'var(--radius-lg)',
                            border: '1px solid var(--border-subtle)',
                            backgroundColor: 'var(--bg-surface)',
                            boxShadow: '0 24px 64px rgba(15, 23, 42, 0.25)',
                        }}
                    >
                        <h2
                            id="delete-document-title"
                            style={{
                                margin: 0,
                                fontSize: '17px',
                                fontWeight: 700,
                                color: 'var(--text-primary)',
                            }}
                        >
                            Delete document?
                        </h2>
                        <div
                            style={{
                                marginTop: '10px',
                                padding: '10px 12px',
                                borderRadius: 'var(--radius-sm)',
                                backgroundColor: 'var(--bg-surface-tint)',
                                border: '1px solid var(--border-subtle)',
                                fontSize: '12.5px',
                                fontWeight: 600,
                                color: 'var(--text-primary)',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                            }}
                            title={deleteTarget.filename}
                        >
                            {deleteTarget.filename}
                        </div>
                        <p
                            id="delete-document-description"
                            style={{
                                margin: '12px 0 0',
                                fontSize: '13px',
                                lineHeight: 1.55,
                                color: 'var(--text-secondary)',
                            }}
                        >
                            This permanently removes the file and its extraction artifact from
                            storage, its RAG search vectors, and every downstream record generated
                            from it — including invoices, purchase orders, contract versions and
                            terms, and reconciliation exceptions. This cannot be undone.
                        </p>
                        {deleteTarget.status === 'processing' && (
                            <p
                                role="alert"
                                style={{
                                    margin: '12px 0 0',
                                    fontSize: '12.5px',
                                    lineHeight: 1.5,
                                    color: 'var(--color-danger)',
                                }}
                            >
                                This upload is still processing and cannot be deleted until the
                                pipeline finishes.
                            </p>
                        )}
                        <div
                            style={{
                                display: 'flex',
                                justifyContent: 'flex-end',
                                gap: '10px',
                                marginTop: '20px',
                            }}
                        >
                            <button
                                type="button"
                                disabled={Boolean(deletingId)}
                                onClick={() => setDeleteTarget(null)}
                                style={{
                                    padding: '8px 14px',
                                    borderRadius: 'var(--radius-sm)',
                                    border: '1px solid var(--border-subtle)',
                                    backgroundColor: 'var(--bg-surface)',
                                    color: 'var(--text-secondary)',
                                    fontSize: '12.5px',
                                    fontWeight: 600,
                                    cursor: deletingId ? 'default' : 'pointer',
                                    opacity: deletingId ? 0.6 : 1,
                                }}
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                autoFocus
                                disabled={Boolean(deletingId) || deleteTarget.status === 'processing'}
                                onClick={handleDeleteConfirm}
                                style={{
                                    padding: '8px 14px',
                                    borderRadius: 'var(--radius-sm)',
                                    border: '1px solid var(--color-danger-border)',
                                    backgroundColor: 'var(--color-danger)',
                                    color: '#FFFFFF',
                                    fontSize: '12.5px',
                                    fontWeight: 700,
                                    cursor:
                                        deletingId || deleteTarget.status === 'processing'
                                            ? 'default'
                                            : 'pointer',
                                    opacity:
                                        deletingId || deleteTarget.status === 'processing' ? 0.6 : 1,
                                }}
                            >
                                {deletingId ? 'Deleting…' : 'Delete document'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
