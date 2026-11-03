'use client';

import React from 'react';
import { DocumentDetail } from '@/types';
import { ProvenanceBadge } from './ProvenanceBadge';
import { confidenceColor, formatConfidence, humanizeLabel } from './format';

/** Field row presentation states for the structured-data panel. */
type PanelState = 'loading' | 'processing' | 'failed' | 'review' | 'ready' | 'artifact_unreadable';

type StructuredDataField = {
    field: string;
    value: unknown;
    confidence?: number;
    page?: number;
    extraction_method?: string;
};

/** Flatten nested fields and line items into readable rows. */
function flattenStructuredData(value: unknown, prefix = ''): StructuredDataField[] {
    if (value === null || value === undefined || value === '') return [];
    if (Array.isArray(value)) {
        return value.flatMap((item, index) =>
            flattenStructuredData(item, `${prefix}_item_${index + 1}`)
        );
    }
    if (typeof value === 'object') {
        return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
            flattenStructuredData(child, prefix ? `${prefix}_${key}` : key)
        );
    }
    return prefix ? [{ field: prefix, value }] : [];
}

/** Decide the panel state from loaded extraction and structured fields. */
function panelStateFor(
    doc: DocumentDetail | null,
    isLoading: boolean,
    hasStructuredFields: boolean,
): PanelState {
    if (isLoading) return 'loading';
    if (!doc) return 'review';
    if (doc.status === 'processing') return 'processing';
    if (doc.status === 'failed') return 'failed';
    if (hasStructuredFields) return 'ready';
    if (!doc.has_artifact) return 'review';
    if (doc.artifact === null) return 'artifact_unreadable';
    return 'ready';
}

/**
 * Detail panel: structured fields recovered by the
 * extraction pipeline (entity label, value, confidence bar, page refs),
 * or an honest state card when nothing has been extracted yet.
 */
export function StructuredDataPanel({
    document: doc,
    isLoading,
    onFieldCite,
    citedField,
    citedPage,
}: {
    document: DocumentDetail | null;
    isLoading: boolean;
    /** Callback when a user cites (clicks) an extracted field. */
    onFieldCite?: (field: string, page: number) => void;
    /** Currently cited field key (from PDF overlay deep-link). */
    citedField: string | null;
    /** Currently cited page (from PDF overlay deep-link). */
    citedPage: number | null;
}) {
    const verifiedData = doc?.review?.verified_data;
    const reviewData = doc?.review?.data;
    const structuredData =
        (verifiedData && Object.keys(verifiedData).length > 0 ? verifiedData : reviewData)
        ?? doc?.structured_data
        ?? null;
    const structuredFields = flattenStructuredData(structuredData);
    const entities = doc?.artifact?.extraction?.entities ?? [];
    const extraction = doc?.artifact?.extraction;
    const displayFields: StructuredDataField[] = structuredFields.length > 0
        ? structuredFields.map((field) => ({
            ...field,
            confidence: doc?.review?.field_confidence?.[field.field],
        }))
        : entities;
    const state = panelStateFor(doc, isLoading, structuredFields.length > 0);

    const stateCards: Record<Exclude<PanelState, 'ready'>, { title: string; body: string; tone: 'info' | 'warning' | 'danger' | 'muted' }> = {
        loading: { title: 'Loading structured data…', body: 'Fetching extracted fields and saved document records.', tone: 'muted' },
        processing: {
            title: 'Extraction in progress',
            body: 'This document is still moving through the pipeline (triage → extraction → classification). Structured fields will appear here once processing completes.',
            tone: 'info',
        },
        failed: {
            title: 'Extraction failed',
            body: doc?.error || 'The pipeline failed while processing this document. Re-upload the file to retry.', tone: 'danger',
        },
        review: {
            title: 'Structured data not available yet',
            body: doc && doc.upload_status === 'completed'
                ? 'This document was uploaded before artifact persistence went live — no structured extraction was stored for it. Properties and preview below are available.'
                : 'No extraction artifact is stored for this document yet.',
            tone: 'warning',
        },
        artifact_unreadable: {
            title: 'Artifact temporarily unavailable',
            body: 'The database row exists, but the stored artifact JSON could not be read from the bucket. Properties and preview below are still available.',
            tone: 'warning',
        },
    };

    const toneStyles: Record<string, string> = {
        info: 'var(--color-info-subtle)',
        warning: 'var(--color-warning-subtle)',
        danger: 'var(--color-danger-subtle)',
        muted: 'var(--bg-surface-tint)',
    };

    return (
        <section
            style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-lg)',
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
                minHeight: '280px',
            }}
            aria-label="Structured data"
        >
            {/* Header */}
            <div
                style={{
                    padding: '16px 20px',
                    borderBottom: '1px solid var(--border-subtle)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '8px',
                }}
            >
                <h2 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                    Structured Data
                </h2>
                {state === 'ready' && structuredFields.length === 0 && extraction && (
                    <ProvenanceBadge
                        method={extraction.extraction_method}
                        confidence={extraction.extraction_confidence}
                        prefix="Pipeline"
                    />
                )}
            </div>

            {/* States */}
            {state !== 'ready' ? (
                <div style={{ padding: '28px 20px', textAlign: 'center' }}>
                    <div
                        style={{
                            padding: '16px 20px',
                            borderRadius: 'var(--radius-md)',
                            backgroundColor: toneStyles[stateCards[state].tone],
                            color: 'var(--text-secondary)',
                        }}
                    >
                        <p style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 6px' }}>
                            {stateCards[state].title}
                        </p>
                        <p style={{ fontSize: '12.5px', margin: 0, lineHeight: 1.55 }}>{stateCards[state].body}</p>
                    </div>
                </div>
            ) : (
                <>
                    <div style={{ padding: '8px 0 16px', flex: 1 }}>
                        {displayFields.length === 0 ? (
                            <p style={{ padding: '16px 20px', fontSize: '13px', color: 'var(--text-muted)', margin: 0 }}>
                                No structured fields were extracted for this document.
                            </p>
                        ) : (
                            <>
                                {/* Structured field rows, with OCR entities as a fallback. */}
                                <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                                    {displayFields.map((entity, index) => {
                                        const confidence = typeof entity.confidence === 'number'
                                            ? entity.confidence
                                            : null;
                                        const isCited =
                                            citedField === entity.field && citedPage === entity.page;
                                        const citeHandler = () => {
                                            if (onFieldCite && typeof entity.page === 'number') {
                                                onFieldCite(entity.field, entity.page);
                                            }
                                        };
                                        return (
                                            <li
                                                key={`${entity.field}-${index}`}
                                                style={{
                                                    display: 'flex',
                                                    alignItems: 'flex-start',
                                                    gap: '12px',
                                                    padding: '10px 20px',
                                                    borderBottom: '1px solid var(--border-subtle)',
                                                    borderLeft: isCited
                                                        ? '3px solid var(--color-brand)'
                                                        : '3px solid transparent',
                                                    backgroundColor: isCited
                                                        ? 'rgba(99, 102, 241, 0.06)'
                                                        : 'inherit',
                                                    cursor: onFieldCite && typeof entity.page === 'number'
                                                        ? 'pointer'
                                                        : 'default',
                                                }}
                                                onClick={citeHandler}
                                            >
                                                {/* Label */}
                                                <div style={{ width: '150px', flexShrink: 0 }}>
                                                    <span
                                                        style={{
                                                            fontSize: '12.5px',
                                                            fontWeight: isCited ? 800 : 600,
                                                            color: isCited
                                                                ? 'var(--color-brand)'
                                                                : 'var(--text-primary)',
                                                            display: 'block',
                                                        }}
                                                        title={entity.extraction_method ? `via ${entity.extraction_method}` : undefined}
                                                    >
                                                        {humanizeLabel(entity.field)}
                                                    </span>
                                                    <span style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>
                                                        {typeof entity.page === 'number' ? `Page ${entity.page}` : ''}
                                                    </span>
                                                </div>

                                                {/* Value */}
                                                <div style={{ flex: 1, minWidth: 0 }}>
                                                    <span
                                                        style={{
                                                            fontSize: '13px',
                                                            color: 'var(--text-primary)',
                                                            fontFamily: 'monospace',
                                                            wordBreak: 'break-word',
                                                        }}
                                                    >
                                                        {entity.value === null || entity.value === undefined || entity.value === ''
                                                            ? '—'
                                                            : typeof entity.value === 'object'
                                                              ? JSON.stringify(entity.value)
                                                              : String(entity.value)}
                                                    </span>
                                                </div>

                                                {/* Confidence bar */}
                                                {confidence !== null && (
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0, width: '104px' }}>
                                                        <div style={{ width: '60px', height: '6px', backgroundColor: 'var(--border-subtle)', borderRadius: 'var(--radius-full)', overflow: 'hidden' }}>
                                                            <div
                                                                style={{
                                                                    width: `${Math.min(100, Math.round(confidence * 100))}%`,
                                                                    height: '100%',
                                                                    backgroundColor: confidenceColor(confidence),
                                                                    borderRadius: 'var(--radius-full)',
                                                                }}
                                                            />
                                                        </div>
                                                        <span style={{ fontSize: '11px', fontWeight: 600, fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
                                                            {formatConfidence(confidence)}
                                                        </span>
                                                    </div>
                                                )}
                                            </li>
                                        );
                                    })}
                                </ul>

                            </>
                        )}
                    </div>

                    {/* Footer summary */}
                    <div
                        style={{
                            padding: '12px 20px',
                            borderTop: '1px solid var(--border-subtle)',
                            fontSize: '12px',
                            color: 'var(--text-muted)',
                            display: 'flex',
                            gap: '16px',
                            flexWrap: 'wrap',
                        }}
                    >
                        <span>
                            {displayFields.length} field{displayFields.length === 1 ? '' : 's'}
                        </span>
                        {extraction?.pages?.length ? <span>{extraction.pages.length} pages</span> : null}
                        {extraction?.tables?.length ? <span>{extraction.tables.length} tables</span> : null}
                        {typeof doc?.text_chars === 'number' ? <span>{doc.text_chars.toLocaleString()} chars</span> : null}
                    </div>
                </>
            )}
        </section>
    );
}
