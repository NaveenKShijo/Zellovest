'use client';

import React from 'react';
import { formatConfidence } from './format';

/**
 * Human-readable names for pipeline method strings
 * (extraction route / classifier) used in provenance badges.
 */
const METHOD_LABELS: Record<string, string> = {
    document_ai: 'Document AI',
    pymupdf: 'PyMuPDF',
    pymupdf_pdfplumber: 'PyMuPDF + PDFPlumber',
    pdfplumber: 'PDFPlumber',
    keyword: 'Keyword classifier',
    keyword_fallback: 'Keyword fallback',
    jev: 'Jev AI',
    jev_choice: 'Jev AI',
    route_python: 'Python parser',
    python: 'Python parser',
    ocr: 'OCR',
    llm: 'LLM',
};

/** "document_ai" → "Document AI"; unrecognized values get Title-case passthrough. */
export function methodLabel(method: string | null | undefined): string {
    if (!method) return '';
    const known = METHOD_LABELS[method.toLowerCase()];
    if (known) return known;
    return method
        .split(/[_\s]+/)
        .filter(Boolean)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

/**
 * Provenance badge: what produced this document's data and with how much
 * confidence — e.g. "Document AI · 94%". Renders nothing when there is
 * neither a method nor a confidence (legacy uploads).
 */
export function ProvenanceBadge({
    method,
    confidence,
    prefix,
}: {
    method: string | null | undefined;
    confidence: number | null | undefined;
    prefix?: string;
}) {
    const label = methodLabel(method);
    if (!label && (confidence === null || confidence === undefined)) {
        return null;
    }

    return (
        <span
            title="Extraction provenance"
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                fontSize: '11px',
                fontWeight: 600,
                padding: '3px 9px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: 'var(--color-brand-subtle)',
                color: 'var(--color-brand)',
                border: '1px solid var(--color-brand-border)',
                whiteSpace: 'nowrap',
            }}
        >
            {prefix ? `${prefix} ` : ''}
            {[label, formatConfidence(confidence)].filter(Boolean).join(' · ')}
        </span>
    );
}
