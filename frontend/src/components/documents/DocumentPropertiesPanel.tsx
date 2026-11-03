'use client';

import React from 'react';
import { DocumentDetail, DocumentStatus } from '@/types';
import { ProvenanceBadge } from './ProvenanceBadge';
import { StatusPill } from './StatusPill';
import { VendorTag } from './VendorTag';
import { formatConfidence, formatDateTime, formatFileSize, humanizeLabel } from './format';

/** One label/value property row. */
function PropertyRow({
    label,
    children,
    mono,
}: {
    label: string;
    children: React.ReactNode;
    mono?: boolean;
}) {
    return (
        <div
            style={{
                display: 'flex',
                gap: '12px',
                padding: '9px 20px',
                borderBottom: '1px solid var(--border-subtle)',
                fontSize: '12.5px',
                alignItems: 'baseline',
            }}
        >
            <span style={{ width: '130px', flexShrink: 0, fontWeight: 600, color: 'var(--text-muted)' }}>
                {label}
            </span>
            <span
                style={{
                    flex: 1,
                    minWidth: 0,
                    color: 'var(--text-primary)',
                    fontFamily: mono ? 'monospace' : 'inherit',
                    wordBreak: mono ? 'break-all' : 'break-word',
                }}
            >
                {children}
            </span>
        </div>
    );
}

/**
 * Right pane of the detail view: document properties (source-of-truth
 * filesystem/lease/provenance facts) rendered as a definition table.
 */
export function DocumentPropertiesPanel({ document: doc }: { document: DocumentDetail | null }) {
    if (!doc) {
        return (
            <section
                aria-label="Document properties"
                style={{
                    backgroundColor: 'var(--bg-surface)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-lg)',
                    padding: '24px',
                    color: 'var(--text-muted)',
                    fontSize: '13px',
                }}
            >
                Loading properties…
            </section>
        );
    }

    const classificationConfidence = doc.document_type_confidence;

    return (
        <section
            aria-label="Document properties"
            style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-lg)',
                overflow: 'hidden',
            }}
        >
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
                    Document Properties
                </h2>
                <ProvenanceBadge method={doc.extraction_method} confidence={doc.extraction_confidence} />
            </div>

            <PropertyRow label="Filename">{doc.filename}</PropertyRow>
            <PropertyRow label="Document type">
                {humanizeLabel(doc.document_type)}
                {typeof classificationConfidence === 'number' && (
                    <span style={{ color: 'var(--text-muted)' }}> · {formatConfidence(classificationConfidence)}</span>
                )}
            </PropertyRow>
            {doc.classification_method && (
                <PropertyRow label="Classified by">
                    <ProvenanceBadge method={doc.classification_method} confidence={null} />
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: '6px' }}>Stage-2 classification</span>
                </PropertyRow>
            )}
            <PropertyRow label="Vendor">
                <VendorTag name={doc.vendor_name} truncate={false} />
            </PropertyRow>
            <PropertyRow label="Status">
                <StatusPill status={doc.status as DocumentStatus} />
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: '8px' }}>
                    lease: {doc.upload_status}
                </span>
            </PropertyRow>
            <PropertyRow label="Route">{humanizeLabel(doc.route)}</PropertyRow>
            <PropertyRow label="File type">{humanizeLabel(doc.file_type)}</PropertyRow>
            <PropertyRow label="MIME type" mono>
                {doc.mime_type}
            </PropertyRow>
            <PropertyRow label="Size">{formatFileSize(doc.size_bytes)}</PropertyRow>
            {typeof doc.text_chars === 'number' && <PropertyRow label="Text extracted">{doc.text_chars.toLocaleString()} characters</PropertyRow>}
            {doc.artifact?.triage?.detection_method && (
                <PropertyRow label="Detected via">{humanizeLabel(doc.artifact.triage.detection_method)}</PropertyRow>
            )}
            <PropertyRow label="Uploaded">{formatDateTime(doc.uploaded_at)}</PropertyRow>
            <PropertyRow label="Updated">{formatDateTime(doc.updated_at)}</PropertyRow>
            <PropertyRow label="GCS key" mono>
                {doc.gcs_key}
            </PropertyRow>
            {doc.error && (
                <PropertyRow label="Error">
                    <span style={{ color: 'var(--color-danger)' }}>{doc.error}</span>
                </PropertyRow>
            )}
        </section>
    );
}
