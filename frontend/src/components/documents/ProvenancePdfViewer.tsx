'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { useApi } from '@/lib/api';
import { DocumentDetail } from '@/types';
import { formatConfidence, humanizeLabel } from './format';
import { ProvenanceOverlay } from './ProvenanceOverlay';

// Point react-pdf at the local PDF.js worker bundle (served from /public).
pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';

/** Zoom levels expressed as a CSS width multiplier relative to the container. */
const ZOOM_LEVELS = [0.75, 1.0, 1.25, 1.5, 2.0];

interface ProvenancePdfViewerProps {
    /** Upload lease id used to mint the signed preview URL. */
    documentId: string | null;
    /** Display filename for fallback UI. */
    filename: string;
    /** Full document detail (used for artifact entities + filename). */
    document: DocumentDetail | null;
    /** Field key currently cited (from the metadata panel), null when none. */
    highlightedField: string | null;
    /** Page currently cited (from the metadata panel), null when none. */
    highlightedPage: number | null;
    /** Fired when the user cites a field from the PDF overlay. */
    onFieldCite: (field: string, page: number) => void;
}

/** Fetch result keyed by the exact document id that produced it. */
interface PreviewResult {
    key: string;
    url: string | null;
    mimeType: string | null;
    error: string | null;
    /** True once the fetch for `key` settled (success or failure). */
    done: boolean;
}

interface PdfDocumentCanvasProps {
    file: string;
    pageNumber: number;
    width: number | undefined;
    onDocumentLoadSuccess: (result: { numPages: number }) => void;
    onLoadError: (error: unknown) => void;
    onGetPage: (page: { width: number; height: number }) => void;
    onPageRenderSuccess: (result: {
        pageNumber: number;
        width: number;
        height: number;
    }) => void;
}

/** Keep react-pdf's canvas mounted when citation or metadata state changes. */
const PdfDocumentCanvas = React.memo(function PdfDocumentCanvas({
    file,
    pageNumber,
    width,
    onDocumentLoadSuccess,
    onLoadError,
    onGetPage,
    onPageRenderSuccess,
}: PdfDocumentCanvasProps) {
    return (
        <Document
            file={file}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onLoadError}
        >
            <Page
                pageNumber={pageNumber}
                width={width}
                onLoadSuccess={onGetPage}
                onRenderSuccess={onPageRenderSuccess}
                rotate={0}
            />
        </Document>
    );
});

/**
 * In-browser PDF viewer with provenance bounding-box overlays.
 *
 * Renders the signed-URL PDF via react-pdf / PDF.js, draws extracted-field
 * bounding boxes (ProvenanceOverlay) on each page, and supports zoom, page
 * navigation, and text selection. Clicking/hovering an overlay box cites the
 * field back to the metadata panel.
 *
 * State discipline: only async setState inside promise callbacks
 * (react-hooks/set-state-in-effect); loading/staleness derived from keyed
 * fetch results.
 */
export function ProvenancePdfViewer({
    documentId,
    filename,
    document,
    highlightedField,
    highlightedPage,
    onFieldCite,
}: ProvenancePdfViewerProps) {
    const api = useApi();
    const [result, setResult] = useState<PreviewResult>({
        key: '',
        url: null,
        mimeType: null,
        error: null,
        done: false,
    });
    const [numPages, setNumPages] = useState<number | null>(null);
    const [pageNumber, setPageNumber] = useState(1);
    const [zoomIndex, setZoomIndex] = useState(1); // default 1.0
    const [pdfWidth, setPdfWidth] = useState<number | null>(null);
    const [pdfHeight, setPdfHeight] = useState<number | null>(null);
    const [renderedWidth, setRenderedWidth] = useState<number | null>(null);
    const [renderedHeight, setRenderedHeight] = useState<number | null>(null);
    const [renderError, setRenderError] = useState<string | null>(null);
    const [containerWidth, setContainerWidth] = useState(0);

    const containerRef = useRef<HTMLDivElement>(null);
    const requestIdRef = useRef(0);
    const zoom = ZOOM_LEVELS[zoomIndex] ?? 1.0;

    // ---- Authenticated content fetch (keyed by documentId; stale responses ignored) ----
    useEffect(() => {
        if (!documentId) return;
        const requestId = ++requestIdRef.current;
        let active = true;
        let objectUrl: string | null = null;
        api.documents
            .fileContent(documentId)
            .then((blob) => {
                const nextObjectUrl = URL.createObjectURL(blob);
                if (!active || requestId !== requestIdRef.current) {
                    URL.revokeObjectURL(nextObjectUrl);
                    return;
                }
                objectUrl = nextObjectUrl;
                setResult({
                    key: documentId,
                    url: nextObjectUrl,
                    mimeType: blob.type || null,
                    error: null,
                    done: true,
                });
            })
            .catch((error: unknown) => {
                if (!active || requestId !== requestIdRef.current) return;
                setResult({
                    key: documentId,
                    url: null,
                    mimeType: null,
                    error:
                        error instanceof Error
                            ? error.message
                            : 'Failed to load the document file from storage.',
                    done: true,
                });
            });
        // The hook returns a new API object per render; documentId is the input.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        return () => {
            active = false;
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        };
    }, [documentId]);

    const isCurrent = result.done && result.key === documentId;
    const url = isCurrent ? result.url : null;
    const mimeType = isCurrent ? result.mimeType : null;
    const failed = isCurrent && result.error !== null;
    const isImageFile = mimeType?.startsWith('image/') ?? false;
    const isPdfFile = mimeType === 'application/pdf' || filename.toLowerCase().endsWith('.pdf');

    // Measure after the PDF container is mounted. The loading state has no
    // section ref, so measuring only once on initial mount would leave the
    // page at its intrinsic size until the window is resized.
    useEffect(() => {
        if (!url || !containerRef.current) return;
        const container = containerRef.current;
        const updateWidth = () => {
            const nextWidth = container.clientWidth;
            setContainerWidth((currentWidth) =>
                currentWidth === nextWidth ? currentWidth : nextWidth
            );
        };

        updateWidth();
        const observer = new ResizeObserver(updateWidth);
        observer.observe(container);
        return () => observer.disconnect();
    }, [url]);

    // ---- Page entities with bounding boxes (memoized per document) ----
    const pageEntities = useMemo(
        () =>
            (document?.artifact?.extraction?.entities ?? []).filter(
                (e) =>
                    typeof e.page === 'number' &&
                    Array.isArray(e.bounding_box) &&
                    e.bounding_box.length === 4 &&
                    e.page === pageNumber
            ),
        [document?.artifact?.extraction?.entities, pageNumber]
    );

    const onDocumentLoadSuccess = useCallback(({ numPages: n }: { numPages: number }) => {
        setNumPages(n);
        setRenderError(null);
    }, []);

    const onPageRenderSuccess = useCallback(
        ({
            pageNumber: n,
            width,
            height,
        }: {
            pageNumber: number;
            width: number;
            height: number;
        }) => {
            if (n !== pageNumber) return;
            setRenderedWidth(width);
            setRenderedHeight(height);
        },
        [pageNumber]
    );

    const onGetPage = useCallback(
        (pdfPage: { width: number; height: number }) => {
            setPdfWidth(pdfPage.width);
            setPdfHeight(pdfPage.height);
        },
        []
    );

    const onLoadError = useCallback((error: unknown) => {
        setRenderError(
            error instanceof Error
                ? error.message
                : 'Failed to load PDF — the signed URL may have expired.'
        );
    }, []);

    const goToPage = useCallback(
        (target: number) => {
            if (!numPages) return;
            const next = Math.max(1, Math.min(target, numPages));
            setPageNumber(next);
        },
        [numPages]
    );

    // Sync to the cited page when the citation changes (external deep-link).
    // Done during render (adjust-state-during-render pattern) rather than in
    // an effect, to avoid react-hooks/set-state-in-effect.
    if (highlightedPage && highlightedPage !== pageNumber) {
        setPageNumber(highlightedPage);
    }

    if (!documentId) {
        return (
            <div
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                    color: 'var(--text-muted)',
                    fontSize: '13px',
                }}
            >
                <div style={{ fontSize: '34px', marginBottom: '8px' }}>📄</div>
                <p>No document selected.</p>
            </div>
        );
    }

    if (failed || (!url && result.done)) {
        return (
            <div
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                    color: 'var(--text-muted)',
                    fontSize: '13px',
                    padding: '24px',
                }}
            >
                <div style={{ fontSize: '34px', marginBottom: '8px' }}>⚠️</div>
                <p style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                    Preview unavailable
                </p>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '4px 0 0' }}>
                    {result.error ?? 'The signed preview URL could not be minted for this document.'}
                </p>
            </div>
        );
    }

    if (!url) {
        return (
            <div
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                    color: 'var(--text-muted)',
                    fontSize: '13px',
                }}
            >
                <div style={{ fontSize: '34px', marginBottom: '8px' }}>📄</div>
                <p>Preparing preview…</p>
            </div>
        );
    }

    const pageWidth = containerWidth * zoom || undefined;

    return (
        <section
            ref={containerRef}
            aria-label="PDF preview"
            style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-lg)',
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
                minHeight: '420px',
            }}
        >
            {/* Toolbar */}
            <div
                style={{
                    padding: '10px 16px',
                    borderBottom: '1px solid var(--border-subtle)',
                    backgroundColor: 'var(--bg-surface-tint)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    flexWrap: 'wrap',
                }}
            >
                <h2
                    style={{
                        fontSize: '15px',
                        fontWeight: 700,
                        color: 'var(--text-primary)',
                        margin: 0,
                        flexShrink: 0,
                    }}
                >
                    Preview
                </h2>
                <div style={{ flex: 1, minWidth: 0 }} />
                <button
                    type="button"
                    disabled={!numPages || pageNumber <= 1}
                    onClick={() => goToPage(pageNumber - 1)}
                    style={{
                        all: 'unset',
                        cursor: pageNumber <= 1 || !numPages ? 'default' : 'pointer',
                        padding: '6px 12px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        backgroundColor: 'var(--bg-surface)',
                        color: (pageNumber <= 1 || !numPages)
                            ? 'var(--text-muted)'
                            : 'var(--text-secondary)',
                        fontSize: '12px',
                        fontWeight: 600,
                    }}
                >
                    ← Prev
                </button>
                <span
                    style={{
                        fontSize: '12px',
                        color: 'var(--text-secondary)',
                        fontWeight: 600,
                        minWidth: '60px',
                        textAlign: 'center',
                    }}
                >
                    Page {pageNumber}{numPages ? ` of ${numPages}` : ''}
                </span>
                <button
                    type="button"
                    disabled={!numPages || pageNumber >= numPages}
                    onClick={() => goToPage(pageNumber + 1)}
                    style={{
                        all: 'unset',
                        cursor: !numPages || pageNumber >= numPages ? 'default' : 'pointer',
                        padding: '6px 12px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        backgroundColor: 'var(--bg-surface)',
                        color: (!numPages || pageNumber >= numPages)
                            ? 'var(--text-muted)'
                            : 'var(--text-secondary)',
                        fontSize: '12px',
                        fontWeight: 600,
                    }}
                >
                    Next →
                </button>
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        borderLeft: '1px solid var(--border-subtle)',
                        paddingLeft: '10px',
                    }}
                >
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Zoom</span>
                    {ZOOM_LEVELS.map((level) => (
                        <button
                            key={level}
                            type="button"
                            aria-label={`Zoom ${Math.round(level * 100)}%`}
                            onClick={() => setZoomIndex(ZOOM_LEVELS.indexOf(level))}
                            style={{
                                all: 'unset',
                                cursor: 'pointer',
                                padding: '4px 8px',
                                borderRadius: 'var(--radius-sm)',
                                border: `1px solid ${
                                    zoomIndex === ZOOM_LEVELS.indexOf(level)
                                        ? 'var(--color-brand)'
                                        : 'var(--border-subtle)'
                                }`,
                                backgroundColor: zoomIndex === ZOOM_LEVELS.indexOf(level)
                                    ? 'var(--color-brand)'
                                    : 'var(--bg-surface)',
                                color: zoomIndex === ZOOM_LEVELS.indexOf(level)
                                    ? '#FFFFFF'
                                    : 'var(--text-secondary)',
                                fontSize: '11px',
                                fontWeight: 700,
                            }}
                        >
                            {Math.round(level * 100)}%
                        </button>
                    ))}
                </div>
            </div>

            {/* Page canvas + provenance overlay */}
            <div
                style={{
                    flex: 1,
                    position: 'relative',
                    overflow: 'auto',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    backgroundColor: 'var(--bg-app)',
                    minHeight: 0,
                }}
            >
                {renderError ? (
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
                        <div style={{ fontSize: '34px' }}>⚠️</div>
                        <p style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                            Preview unavailable
                        </p>
                        <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0 }}>
                            {renderError}
                        </p>
                    </div>
                ) : isImageFile ? (
                    <img
                        src={url}
                        alt={filename}
                        style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                    />
                ) : isPdfFile ? (
                    <div style={{ position: 'relative', display: 'inline-block', maxWidth: '100%', lineHeight: 0 }}>
                        <PdfDocumentCanvas
                            file={url}
                            pageNumber={pageNumber}
                            width={pageWidth}
                            onDocumentLoadSuccess={onDocumentLoadSuccess}
                            onLoadError={onLoadError}
                            onGetPage={onGetPage}
                            onPageRenderSuccess={onPageRenderSuccess}
                        />
                        {pdfWidth && pdfHeight && renderedWidth && renderedHeight ? (
                            <ProvenanceOverlay
                                pageNumber={pageNumber}
                                entities={pageEntities}
                                pdfWidth={pdfWidth}
                                pdfHeight={pdfHeight}
                                renderedWidth={renderedWidth}
                                renderedHeight={renderedHeight}
                                highlightedField={highlightedField}
                                highlightedPage={highlightedPage}
                                onFieldCite={onFieldCite}
                            />
                        ) : null}
                    </div>
                ) : (
                    <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                        Preview is available for PDF and image files.
                    </p>
                )}
            </div>

            {/* Footer: page info + provenance hint */}
            {document && (
                <div
                    style={{
                        padding: '8px 16px',
                        borderTop: '1px solid var(--border-subtle)',
                        fontSize: '11.5px',
                        color: 'var(--text-muted)',
                        display: 'flex',
                        gap: '12px',
                        flexWrap: 'wrap',
                    }}
                >
                    <span>
                        {humanizeLabel(document.document_type)} •{' '}
                        {typeof document.extraction_confidence === 'number'
                            ? `confidence ${formatConfidence(document.extraction_confidence)}`
                            : 'no confidence'}
                    </span>
                    <span>
                        {pageEntities.length} provenance field{pageEntities.length === 1 ? '' : 's'}
                        {` on this page`}
                    </span>
                    <span style={{ fontSize: '11px', fontStyle: 'italic' }}>
                        Hover or click a highlighted box to cite the field
                    </span>
                </div>
            )}
        </section>
    );
}
