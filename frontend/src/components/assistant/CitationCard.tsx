'use client';

import React from 'react';
import Link from 'next/link';
import { AskAICitation, EvidenceItem } from '@/types/askAi';

interface CitationCardProps {
  citation: AskAICitation;
  evidenceItem?: EvidenceItem;
  index: number;
  onOpenDocument: (
    documentId: string,
    page: number,
    bbox?: number[] | null,
    title?: string,
    excerpt?: string | null
  ) => void;
}

/**
 * CitationCard: Interactive Evidence Card (PRD #23 & #25.8)
 *
 * Displays source document, page, section, and excerpt.
 * Clicking directly opens the document viewer at the EXACT PAGE with
 * animated bounding-box highlight over the cited clause!
 */
export const CitationCard: React.FC<CitationCardProps> = ({
  citation,
  evidenceItem,
  index,
  onOpenDocument,
}) => {
  const documentId = evidenceItem?.document_id || citation.source_id;
  const page = evidenceItem?.page ?? citation.page ?? 1;
  const section = evidenceItem?.section;
  const bbox = evidenceItem?.bbox ?? citation.bbox;
  const excerpt = evidenceItem?.excerpt || citation.excerpt;
  const isDocument = citation.source_type === 'document' || evidenceItem?.kind === 'document';

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    if (documentId) {
      onOpenDocument(documentId, page, bbox, citation.description, excerpt);
    }
  };

  return (
    <div
      style={{
        padding: '10px 12px',
        border: '1px solid #e7e2ea',
        borderRadius: '10px',
        backgroundColor: '#fcfbfd',
        transition: 'all 150ms ease',
        cursor: isDocument ? 'pointer' : 'default',
      }}
      onClick={isDocument ? handleClick : undefined}
      onMouseEnter={(e) => {
        if (isDocument) {
          e.currentTarget.style.borderColor = '#c69db2';
          e.currentTarget.style.backgroundColor = '#fdfafc';
        }
      }}
      onMouseLeave={(e) => {
        if (isDocument) {
          e.currentTarget.style.borderColor = '#e7e2ea';
          e.currentTarget.style.backgroundColor = '#fcfbfd';
        }
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
          <span
            style={{
              display: 'grid',
              width: '20px',
              height: '20px',
              placeItems: 'center',
              borderRadius: '5px',
              backgroundColor: '#f0e3ea',
              color: '#7a3e5c',
              fontSize: '11px',
              fontWeight: 800,
              flexShrink: 0,
            }}
          >
            {index + 1}
          </span>

          <span
            style={{
              fontSize: '12px',
              fontWeight: 700,
              color: '#342f3d',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
            title={citation.description}
          >
            {citation.description}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
          {isDocument && (
            <span
              style={{
                fontSize: '10.5px',
                fontWeight: 750,
                padding: '2px 7px',
                borderRadius: '4px',
                backgroundColor: '#ede7f6',
                color: '#5e35b1',
                border: '1px solid #d1c4e9',
              }}
            >
              Page {page}
            </span>
          )}

          {bbox && (
            <span
              style={{
                fontSize: '10px',
                fontWeight: 700,
                padding: '2px 5px',
                borderRadius: '4px',
                backgroundColor: '#fff3e0',
                color: '#e65100',
                border: '1px solid #ffe0b2',
              }}
              title="Exact bounding-box coordinates indexed"
            >
              BBox ✦
            </span>
          )}

          {isDocument && (
            <button
              type="button"
              onClick={handleClick}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--color-brand, #8a526f)',
                fontSize: '11px',
                fontWeight: 750,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '2px',
                padding: '2px 4px',
              }}
            >
              <span>View @ Page</span>
              <span aria-hidden="true">↗</span>
            </button>
          )}

          {!isDocument && (
            <span
              style={{
                fontSize: '10px',
                fontWeight: 650,
                color: '#75707e',
                backgroundColor: '#eee9f0',
                padding: '2px 6px',
                borderRadius: '4px',
              }}
            >
              {citation.source_type}
            </span>
          )}
        </div>
      </div>

      {section && (
        <div style={{ marginTop: '4px', marginLeft: '28px', fontSize: '11px', fontWeight: 600, color: '#686273' }}>
          {section}
        </div>
      )}

      {excerpt && (
        <p
          style={{
            margin: '6px 0 0 28px',
            fontSize: '11.5px',
            lineHeight: 1.5,
            color: '#65606e',
            backgroundColor: '#f5f2f7',
            padding: '6px 9px',
            borderRadius: '6px',
            borderLeft: '2px solid var(--color-brand, #8a526f)',
            fontStyle: 'italic',
          }}
        >
          &ldquo;{excerpt}&rdquo;
        </p>
      )}

      {/* Explorer deep link */}
      {isDocument && documentId && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '6px' }}>
          <Link
            href={`/documents/${documentId}?page=${page}`}
            onClick={(e) => e.stopPropagation()}
            style={{
              fontSize: '10.5px',
              color: '#817a8c',
              textDecoration: 'none',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.textDecoration = 'underline')}
            onMouseLeave={(e) => (e.currentTarget.style.textDecoration = 'none')}
          >
            Open in Document Explorer ↗
          </Link>
        </div>
      )}
    </div>
  );
};
