'use client';

import React from 'react';
import Link from 'next/link';
import { DocumentRecord, DocumentStatus } from '@/types';
import { StatusPill } from './StatusPill';
import { VendorTag } from './VendorTag';
import { confidenceColor, formatConfidence, formatDateTime, formatFileSize, humanizeLabel } from './format';

/** Explorer columns that can be sorted via URL params (`sort` + `dir`). */
export type DocumentSortField = 'filename' | 'uploaded_at' | 'size_bytes' | 'extraction_confidence';

const DOC_TYPE_META: Record<string, { label: string; icon: React.ReactNode }> = {
    contract: {
        label: 'Contract',
        icon: (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
            </svg>
        ),
    },
    amendment: {
        label: 'Amendment',
        icon: (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
            </svg>
        ),
    },
    purchase_order: {
        label: 'Purchase Order',
        icon: (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                <polyline points="9 14 11 16 15 11" />
            </svg>
        ),
    },
    invoice: {
        label: 'Invoice',
        icon: (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
        ),
    },
    policy: {
        label: 'Policy',
        icon: (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
        ),
    },
    other: {
        label: 'Other',
        icon: (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
            </svg>
        ),
    },
};

const COLUMN_DEFAULT_WIDTHS: Record<string, string> = {
    document: '280px',
    type: '120px',
    vendor: '150px',
    status: '140px',
    uploaded: '180px',
    size: '100px',
    confidence: '120px',
};

/** Visual + semantic model for one sortable Explorer column. */
const TABLE_COLUMNS: Array<{
    key: string;
    label: string;
    align: 'left' | 'center' | 'right';
    sortField?: DocumentSortField;
}> = [
    { key: 'document', label: 'Document', align: 'left' },
    { key: 'type', label: 'Type', align: 'center' },
    { key: 'vendor', label: 'Vendor', align: 'left' },
    { key: 'status', label: 'Status', align: 'center' },
    { key: 'uploaded', label: 'Uploaded', align: 'left', sortField: 'uploaded_at' },
    { key: 'size', label: 'Size', align: 'right', sortField: 'size_bytes' },
    { key: 'confidence', label: 'Confidence', align: 'center', sortField: 'extraction_confidence' },
];

/**
 * Row-clickable Explorer inventory table (read-only).
 * Sorting defers to the parent (URL params); no mutations here.
 */
export function DocumentTable({
    documents,
    sortField,
    sortDir,
    onSortChange,
}: {
    documents: DocumentRecord[];
    sortField: DocumentSortField | null;
    sortDir: 'asc' | 'desc';
    onSortChange: (field: DocumentSortField) => void;
}) {
    if (documents.length === 0) {
        return (
            <div
                style={{
                    textAlign: 'center',
                    padding: '48px 24px',
                    color: 'var(--text-muted)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-lg)',
                    backgroundColor: 'var(--bg-surface)',
                }}
            >
                <div style={{ fontSize: '44px', marginBottom: '12px', opacity: 0.5 }}>🗂️</div>
                <p style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-secondary)', margin: 0 }}>
                    No documents match these filters
                </p>
                <p style={{ fontSize: '13px', marginTop: '6px' }}>
                    Try another tab, clear the status filter, or upload files in the Upload queue.
                </p>
            </div>
        );
    }

    return (
        <div
            style={{
                backgroundColor: 'var(--bg-surface)',
                borderRadius: 'var(--radius-lg)',
                border: '1px solid var(--border-subtle)',
                overflow: 'hidden',
            }}
        >
            <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                    <thead>
                        <tr style={{ backgroundColor: 'var(--bg-surface-tint)', borderBottom: '1px solid var(--border-subtle)' }}>
                            {TABLE_COLUMNS.map((column) => {
                                const isSorted = column.sortField && column.sortField === sortField;
                                return (
                                    <th
                                        key={column.key}
                                        style={{
                                            padding: '12px 16px',
                                            textAlign: column.align,
                                            fontWeight: 600,
                                            color: 'var(--text-secondary)',
                                            whiteSpace: 'nowrap',
                                            width: COLUMN_DEFAULT_WIDTHS[column.key],
                                        }}
                                    >
                                        {column.sortField ? (
                                            <button
                                                type="button"
                                                onClick={() => onSortChange(column.sortField as DocumentSortField)}
                                                title={`Sort by ${column.label.toLowerCase()}`}
                                                style={{
                                                    all: 'unset',
                                                    cursor: 'pointer',
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    gap: '4px',
                                                    color: isSorted ? 'var(--color-brand)' : 'inherit',
                                                }}
                                            >
                                                {column.label}
                                                <span style={{ fontSize: '9px', opacity: isSorted ? 1 : 0.35 }}>
                                                    {isSorted && sortDir === 'asc' ? '▲' : '▼'}
                                                </span>
                                            </button>
                                        ) : (
                                            column.label
                                        )}
                                    </th>
                                );
                            })}
                        </tr>
                    </thead>
                    <tbody>
                        {documents.map((doc) => {
                            const typeMeta = DOC_TYPE_META[doc.document_type] ?? DOC_TYPE_META.other;
                            return (
                                <tr
                                    key={doc.id}
                                    style={{
                                        borderBottom: '1px solid var(--border-subtle)',
                                        transition: 'background-color var(--transition-fast)',
                                    }}
                                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--bg-surface-hover)')}
                                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                                >
                                    <td style={{ padding: '13px 16px' }}>
                                        <Link
                                            href={`/documents/${doc.id}`}
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '10px',
                                                textDecoration: 'none',
                                                color: 'inherit',
                                            }}
                                        >
                                            <span style={{ color: 'var(--color-brand)', flexShrink: 0, display: 'flex' }}>
                                                {typeMeta.icon}
                                            </span>
                                            <div style={{ minWidth: 0 }}>
                                                <div
                                                    style={{
                                                        fontWeight: 600,
                                                        color: 'var(--text-primary)',
                                                        maxWidth: '260px',
                                                        whiteSpace: 'nowrap',
                                                        overflow: 'hidden',
                                                        textOverflow: 'ellipsis',
                                                    }}
                                                    title={doc.filename}
                                                >
                                                    {doc.filename}
                                                </div>
                                                {doc.error ? (
                                                    <div style={{ fontSize: '11px', color: 'var(--color-danger)', marginTop: '2px', maxWidth: '260px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={doc.error}>
                                                        {doc.error}
                                                    </div>
                                                ) : doc.route ? (
                                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                                                        route: {doc.route} · {humanizeLabel(doc.file_type)}
                                                    </div>
                                                ) : null}
                                            </div>
                                        </Link>
                                    </td>
                                    <td style={{ padding: '13px 16px', textAlign: 'center' }}>
                                        <span
                                            style={{
                                                fontSize: '11px',
                                                fontWeight: 600,
                                                padding: '3px 10px',
                                                borderRadius: 'var(--radius-full)',
                                                backgroundColor: 'var(--bg-surface-tint)',
                                                color: 'var(--color-brand)',
                                                border: '1px solid var(--border-tint)',
                                                whiteSpace: 'nowrap',
                                            }}
                                        >
                                            {typeMeta.label}
                                        </span>
                                    </td>
                                    <td style={{ padding: '13px 16px' }}>
                                        <VendorTag name={doc.vendor_name} />
                                    </td>
                                    <td style={{ padding: '13px 16px', textAlign: 'center' }}>
                                        <StatusPill status={doc.status as DocumentStatus} />
                                        {doc.status === 'review_needed' && (
                                            <Link
                                                href={`/documents/${doc.id}#review`}
                                                style={{
                                                    display: 'inline-block',
                                                    marginTop: '5px',
                                                    fontSize: '11px',
                                                    fontWeight: 700,
                                                    color: 'var(--color-brand)',
                                                    textDecoration: 'underline',
                                                }}
                                            >
                                                Review exception
                                            </Link>
                                        )}
                                    </td>
                                    <td style={{ padding: '13px 16px', fontSize: '12.5px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                                        {formatDateTime(doc.uploaded_at)}
                                    </td>
                                    <td style={{ padding: '13px 16px', textAlign: 'right', fontSize: '12.5px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                                        {formatFileSize(doc.size_bytes)}
                                    </td>
                                    <td style={{ padding: '13px 16px', textAlign: 'center' }}>
                                        {doc.extraction_confidence !== null && doc.extraction_confidence !== undefined ? (
                                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                                                <div style={{ width: '56px', height: '6px', backgroundColor: 'var(--border-subtle)', borderRadius: 'var(--radius-full)', overflow: 'hidden' }}>
                                                    <div
                                                        style={{
                                                            width: `${Math.min(100, Math.round(doc.extraction_confidence * 100))}%`,
                                                            height: '100%',
                                                            backgroundColor: confidenceColor(doc.extraction_confidence),
                                                            borderRadius: 'var(--radius-full)',
                                                        }}
                                                    />
                                                </div>
                                                <span style={{ fontSize: '12px', fontWeight: 600, fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
                                                    {formatConfidence(doc.extraction_confidence)}
                                                </span>
                                            </div>
                                        ) : (
                                            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>—</span>
                                        )}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
