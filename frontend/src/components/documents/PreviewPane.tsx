'use client';

import React, { useEffect, useState } from 'react';
import { useApi } from '@/lib/api';

/** Signed-URL fetch result keyed by the document id that produced it. */
interface PreviewState {
    id: string | null;
    url: string | null;
    failed: boolean;
    /** True once the fetch for `id` settled. */
    done: boolean;
}

/** Prevent parent row-click handlers from hijacking preview actions. */
const stopPropagation = (event: React.MouseEvent) => event.stopPropagation();

const linkButtonStyle: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '8px 16px',
    borderRadius: 'var(--radius-sm)',
    border: '1px solid var(--color-brand-border)',
    backgroundColor: 'var(--bg-surface-tint)',
    color: 'var(--color-brand)',
    fontSize: '12.5px',
    fontWeight: 700,
    textDecoration: 'none',
};

/**
 * Inline PDF preview of the stored document bytes.
 *
 * Fetches a short-lived signed GET URL (``GET /api/v1/documents/{id}/file``)
 * and renders it in an <iframe>. Browsers block remote PDF rendering in some
 * environments; when the frame signals an error, or the URL cannot be minted,
 * a graceful fallback offers "open in new tab" / "download" instead.
 */
export function PreviewPane({
    documentId,
    filename,
}: {
    documentId: string | null;
    filename: string;
}) {
    const api = useApi();
    const [state, setState] = useState<PreviewState>({ id: null, url: null, failed: false, done: true });

    useEffect(() => {
        if (!documentId) {
            // Missing id renders the "not ready" fallback (derived below).
            return;
        }
        let cancelled = false;
        api.documents
            .fileUrl(documentId)
            .then((response) => {
                if (cancelled) return;
                setState({ id: response.document_id, url: response.url, failed: false, done: true });
            })
            .catch(() => {
                if (cancelled) return;
                setState({ id: documentId, url: null, failed: true, done: true });
            });
        return () => {
            cancelled = true;
        };
        // api.documents is recreated per render; documentId is the real input.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [documentId]);

    const isCurrent = state.done && state.id === documentId;
    const isLoading = !documentId ? false : !state.done || state.id !== documentId;
    const failed = isCurrent && state.failed;
    const url = isCurrent ? state.url : null;

    const fallbackSection = (reason: string) => (
        <div
            style={{
                padding: '32px 20px',
                textAlign: 'center',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '12px',
            }}
        >
            <div style={{ fontSize: '34px' }}>📄</div>
            <div>
                <p style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                    {reason}
                </p>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '4px 0 0' }}>
                    Inline preview is unavailable in this environment — use the buttons below.
                </p>
            </div>
            {url && (
                <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', justifyContent: 'center' }}>
                    <a href={url} target="_blank" rel="noopener noreferrer" style={linkButtonStyle} onClick={stopPropagation}>
                        Open in new tab
                    </a>
                    <a
                        href={url}
                        download={filename}
                        style={{
                            ...linkButtonStyle,
                            backgroundColor: 'var(--color-brand)',
                            color: '#FFFFFF',
                            borderColor: 'var(--color-brand)',
                        }}
                        onClick={stopPropagation}
                    >
                        Download
                    </a>
                </div>
            )}
        </div>
    );

    return (
        <section
            aria-label="Document preview"
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
                    gap: '8px',
                }}
            >
                <h2 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                    Preview
                </h2>
                {url && !failed && (
                    <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-brand)', textDecoration: 'none' }}
                        onClick={stopPropagation}
                    >
                        Open full size ↗
                    </a>
                )}
            </div>

            <div style={{ minHeight: '360px', backgroundColor: 'var(--bg-app)' }}>
                {isLoading ? (
                    <div
                        aria-hidden="true"
                        style={{
                            height: '360px',
                            margin: '16px',
                            borderRadius: 'var(--radius-md)',
                            background:
                                'linear-gradient(100deg, var(--bg-surface-tint) 30%, var(--bg-surface-hover) 50%, var(--bg-surface-tint) 70%)',
                            backgroundSize: '200% 100%',
                            animation: 'shimmer 1.4s infinite linear',
                        }}
                    />
                ) : failed ? (
                    fallbackSection('Preview unavailable')
                ) : url ? (
                    <iframe
                        src={url}
                        title={`Preview of ${filename}`}
                        onError={() => setState((prev) => ({ ...prev, failed: true }))}
                        style={{
                            width: '100%',
                            height: '460px',
                            border: 'none',
                            display: 'block',
                            margin: '16px',
                            borderRadius: 'var(--radius-md)',
                            backgroundColor: '#FFFFFF',
                        }}
                    />
                ) : (
                    fallbackSection(documentId ? 'Preview not ready' : 'No preview available')
                )}
            </div>
        </section>
    );
}
