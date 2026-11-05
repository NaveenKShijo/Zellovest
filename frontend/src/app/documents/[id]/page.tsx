'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { DocumentDetail } from '@/types';
import { useApi } from '@/lib/api';
import { StatusPill } from '@/components/documents/StatusPill';
import { ProvenanceBadge } from '@/components/documents/ProvenanceBadge';
import { VendorTag } from '@/components/documents/VendorTag';
import { StructuredDataPanel } from '@/components/documents/StructuredDataPanel';
import { DocumentPropertiesPanel } from '@/components/documents/DocumentPropertiesPanel';
import { ContractReviewPanel } from '@/components/documents/ContractReviewPanel';
import { InvoiceReviewPanel } from '@/components/documents/InvoiceReviewPanel';
import { formatDateTime, humanizeLabel } from '@/components/documents/format';

// PDF.js reads browser globals during module evaluation, so keep this viewer
// out of the server render and load it only in the browser.
const ProvenancePdfViewer = dynamic(
    () =>
        import('@/components/documents/ProvenancePdfViewer').then(
            (module) => module.ProvenancePdfViewer
        ),
    {
        ssr: false,
        loading: () => (
            <div
                style={{
                    minHeight: '300px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--text-muted)',
                    fontSize: '13px',
                }}
            >
                Loading PDF preview…
            </div>
        ),
    }
);

/** Detail view state; transitions happen only inside promise callbacks. */
type DetailView =
    | { status: 'loading'; detail: null; message: null }
    | { status: 'ready'; detail: DocumentDetail; message: null }
    | { status: 'error'; detail: null; message: string };

const INITIAL_VIEW: DetailView = { status: 'loading', detail: null, message: null };

/**
 * Document detail route (``/documents/[id]``).
 *
 * Document properties, preview, and structured extraction (entities + provenance).
 * properties + inline signed-URL PDF preview with a graceful fallback.
 * The document id is the uploads lease id — one row per GCS object.
 */
export default function DocumentDetailPage() {
    const params = useParams<{ id: string }>();
    const documentId = typeof params.id === 'string' ? params.id : Array.isArray(params.id) ? params.id[0] : null;

    const api = useApi();
    const [view, setView] = useState<DetailView>(INITIAL_VIEW);
    const [retryKey, setRetryKey] = useState(0);
    const requestIdRef = useRef(0);
    const [citedField, setCitedField] = useState<string | null>(null);
    const [citedPage, setCitedPage] = useState<number | null>(null);

    const handleFieldCite = useCallback((field: string, page: number) => {
        setCitedField(field);
        setCitedPage(page);
    }, []);

    useEffect(() => {
        if (!documentId) return; // malformed id handled by derivation below
        const requestId = ++requestIdRef.current;
        api.documents
            .get(documentId)
            .then((response) => {
                if (requestId !== requestIdRef.current) return; // stale response
                setView({ status: 'ready', detail: response, message: null });
            })
            .catch((err: unknown) => {
                if (requestId !== requestIdRef.current) return;
                setView({
                    status: 'error',
                    detail: null,
                    message: err instanceof Error ? err.message : 'Failed to load document',
                });
            });
        // api.documents.filter chain is recreated per render; documentId is
        // the real input and changes with the route.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [documentId, retryKey]);

    // Stale-content guard: while a new id is fetching, show the loading view
    // instead of the previous document's data (no extra state needed).
    const isStale = view.status === 'ready' && view.detail.id !== documentId;
    const shown: DetailView = isStale ? { status: 'loading', detail: null, message: null } : view;
    const detail = documentId && shown.status === 'ready' ? shown.detail : null;
    const isLoading = !documentId ? false : shown.status === 'loading';
    const errorMessage = shown.status === 'error' ? shown.message : null;

    const isMalformed = !documentId;

    // The explorer links low-confidence rows to `#review`; the panel only
    // exists after the async detail fetch, so scroll once it has rendered.
    useEffect(() => {
        if (!detail || window.location.hash !== '#review') return;
        document.getElementById('review')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, [detail]);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Breadcrumb */}
            <nav aria-label="Breadcrumb" style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', color: 'var(--text-muted)' }}>
                <Link href="/documents" style={{ color: 'var(--color-brand)', textDecoration: 'none', fontWeight: 600 }}>
                    Documents
                </Link>
                <span>/</span>
                <span style={{ color: 'var(--text-secondary)', maxWidth: '420px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {detail?.filename ?? documentId ?? '—'}
                </span>
            </nav>

            {/* Header */}
            <header
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '12px',
                    backgroundColor: 'var(--bg-surface)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-lg)',
                    padding: '16px 20px',
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0, flexWrap: 'wrap' }}>
                    <h1
                        style={{
                            fontSize: '18px',
                            fontWeight: 700,
                            color: 'var(--text-primary)',
                            margin: 0,
                            maxWidth: '520px',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                        }}
                        title={detail?.filename}
                    >
                        {detail?.filename ?? 'Loading…'}
                    </h1>
                    {detail && (
                        <span
                            style={{
                                fontSize: '11px',
                                fontWeight: 600,
                                padding: '3px 10px',
                                borderRadius: 'var(--radius-full)',
                                backgroundColor: 'var(--bg-surface-tint)',
                                color: 'var(--color-brand)',
                                border: '1px solid var(--border-tint)',
                            }}
                        >
                            {humanizeLabel(detail.document_type)}
                        </span>
                    )}
                    {detail && <StatusPill status={detail.status} />}
                    {detail && (
                        <ProvenanceBadge method={detail.extraction_method} confidence={detail.extraction_confidence} />
                    )}
                </div>
                {detail && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '12px', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                        <VendorTag name={detail.vendor_name} truncate={false} />
                        <span>uploaded {formatDateTime(detail.uploaded_at)}</span>
                    </div>
                )}
            </header>

            {/* Error banner (malformed id or fetch failure) */}
            {(isMalformed || errorMessage) && (
                <div
                    role="alert"
                    style={{
                        padding: '14px 20px',
                        borderRadius: 'var(--radius-md)',
                        backgroundColor: 'var(--color-danger-subtle)',
                        border: '1px solid var(--color-danger-border)',
                        color: 'var(--color-danger)',
                        fontSize: '13px',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: '12px',
                        flexWrap: 'wrap',
                    }}
                >
                    <span>
                        {isMalformed
                            ? 'This document link is malformed — the id segment is missing.'
                            : errorMessage?.includes('404')
                              ? 'Document not found — it may have been removed, or the link is invalid.'
                              : errorMessage}
                    </span>
                    <div style={{ display: 'flex', gap: '10px' }}>
                        {!isMalformed && (
                            <button
                                type="button"
                                onClick={() => setRetryKey((key) => key + 1)}
                                style={{ all: 'unset', cursor: 'pointer', fontWeight: 700, fontSize: '12px', textDecoration: 'underline' }}
                            >
                                Retry
                            </button>
                        )}
                        <Link href="/documents" style={{ color: 'var(--color-danger)', fontWeight: 700, fontSize: '12px', textDecoration: 'underline' }}>
                            Back to explorer
                        </Link>
                    </div>
                </div>
            )}

            {/* Document details, preview, then structured data */}
            <div
                className="document-detail-grid"
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '16px',
                }}
            >
                {isMalformed || errorMessage ? (
                    <div
                        style={{
                            backgroundColor: 'var(--bg-surface)',
                            border: '1px dashed var(--border-subtle)',
                            borderRadius: 'var(--radius-lg)',
                            padding: '24px',
                            color: 'var(--text-muted)',
                            fontSize: '13px',
                        }}
                    >
                        Properties are unavailable until the document loads.
                    </div>
                ) : isLoading ? (
                    <div
                        style={{
                            backgroundColor: 'var(--bg-surface)',
                            border: '1px solid var(--border-subtle)',
                            borderRadius: 'var(--radius-lg)',
                            height: '300px',
                            animation: 'pulse 1.5s ease-in-out infinite',
                        }}
                        aria-hidden="true"
                    />
                ) : (
                    <DocumentPropertiesPanel document={detail} />
                )}
                <ProvenancePdfViewer
                    documentId={isMalformed ? null : documentId}
                    filename={detail?.filename ?? 'document'}
                    document={detail}
                    highlightedField={citedField}
                    highlightedPage={citedPage}
                    onFieldCite={handleFieldCite}
                />
                {detail && (
                    <ContractReviewPanel
                        key={`${detail.id}:${detail.review?.status ?? 'none'}:${detail.review?.reviewed_at ?? ''}`}
                        document={detail}
                        onCommitted={() => setRetryKey((key) => key + 1)}
                    />
                )}
                {detail && (
                    <InvoiceReviewPanel
                        key={`invoice:${detail.id}:${detail.review?.status ?? 'none'}:${detail.review?.reviewed_at ?? ''}`}
                        document={detail}
                        onCommitted={() => setRetryKey((key) => key + 1)}
                    />
                )}
                <StructuredDataPanel
                    document={detail}
                    isLoading={!isMalformed && isLoading}
                    onFieldCite={handleFieldCite}
                    citedField={citedField}
                    citedPage={citedPage}
                />
            </div>
        </div>
    );
}
