'use client';

import React, { useCallback, useMemo } from 'react';
import { ExtractionEntity } from '@/types';
import { humanizeLabel } from './format';

/**
 * Props for the per-page provenance bounding-box overlay.
 */
export interface ProvenanceOverlayProps {
    /** 1-based PDF page number this overlay renders for. */
    pageNumber: number;
    /** All extraction entities (filtered internally to this page). */
    entities: ExtractionEntity[];
    /** PDF page width in points (PDF.js coordinate space, origin bottom-left). */
    pdfWidth: number;
    /** PDF page height in points (PDF.js coordinate space, origin bottom-left). */
    pdfHeight: number;
    /** Rendered canvas width in CSS pixels. */
    renderedWidth: number;
    /** Rendered canvas height in CSS pixels. */
    renderedHeight: number;
    /** Field key currently highlighted (from citation click), null when none. */
    highlightedField: string | null;
    /** Page currently highlighted (from citation click), null when none. */
    highlightedPage: number | null;
    /** Fired when the user hovers/clicks an entity box. */
    onFieldCite: (field: string, page: number) => void;
}

/**
 * Renders bounding-box overlays for extracted fields on a single PDF page.
 *
 * Coordinate transform: PDF.js stores boxes in points with origin at
 * bottom-left; CSS renders with origin at top-left. Boxes are scaled from
 * PDF space to the rendered canvas size and the Y axis is flipped.
 */
export function ProvenanceOverlay({
    pageNumber,
    entities,
    pdfWidth,
    pdfHeight,
    renderedWidth,
    renderedHeight,
    highlightedField,
    highlightedPage,
    onFieldCite,
}: ProvenanceOverlayProps) {
    const boxes = useMemo(
        () => {
            const scaleX = renderedWidth / pdfWidth;
            const scaleY = renderedHeight / pdfHeight;
            return entities
                .filter(
                    (e) =>
                        e.page === pageNumber &&
                        Array.isArray(e.bounding_box) &&
                        e.bounding_box.length === 4
                )
                .map((e) => {
                    const [x0, y0, x1, y1] = e.bounding_box as number[];
                    return {
                        field: e.field,
                        left: Math.max(0, x0 * scaleX),
                        top: Math.max(0, (pdfHeight - y1) * scaleY),
                        width: Math.max(0, (x1 - x0) * scaleX),
                        height: Math.max(0, (y1 - y0) * scaleY),
                    };
                });
        },
        [entities, pageNumber, pdfWidth, pdfHeight, renderedWidth, renderedHeight]
    );

    const isHighlighted = useCallback(
        (field: string) =>
            highlightedField === field && highlightedPage === pageNumber,
        [highlightedField, highlightedPage, pageNumber]
    );

    return (
        <div
            style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                pointerEvents: 'none',
                overflow: 'visible',
            }}
        >
            {boxes.map((box, index) => {
                const highlighted = isHighlighted(box.field);
                return (
                    <div
                        key={`${box.field}-${index}-p${pageNumber}`}
                        onClick={(event) => {
                            event.stopPropagation();
                            onFieldCite(box.field, pageNumber);
                        }}
                        onMouseEnter={(event) => {
                            event.stopPropagation();
                            onFieldCite(box.field, pageNumber);
                        }}
                        onMouseLeave={() => {
                            // Keep the last-cited field highlighted until a
                            // different one is cited; no auto-clear on leave.
                        }}
                        style={{
                            position: 'absolute',
                            left: Math.round(box.left),
                            top: Math.round(box.top),
                            width: Math.max(1, Math.round(box.width)),
                            height: Math.max(1, Math.round(box.height)),
                            border: highlighted
                                ? '2px solid var(--color-brand)'
                                : '1px solid var(--color-brand)',
                            backgroundColor: highlighted
                                ? 'rgba(99, 102, 241, 0.15)'
                                : 'rgba(99, 102, 241, 0.05)',
                            borderRadius: '2px',
                            pointerEvents: 'auto',
                            cursor: 'pointer',
                            zIndex: 10,
                            boxSizing: 'border-box',
                            fontSize: '10px',
                            fontWeight: 700,
                            color: 'var(--color-brand)',
                            overflow: 'hidden',
                            whiteSpace: 'nowrap',
                            textOverflow: 'ellipsis',
                            padding: '1px 4px',
                        }}
                        title={`${humanizeLabel(box.field)} — Page ${pageNumber}`}
                    >
                        {highlighted && box.width > 36
                            ? humanizeLabel(box.field)
                            : ''}
                    </div>
                );
            })}
        </div>
    );
}
