'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';

interface DocumentViewerModalProps {
  isOpen: boolean;
  onClose: () => void;
  documentId: string;
  initialPage?: number;
  bbox?: number[] | null;
  documentTitle?: string;
  excerpt?: string | null;
}

/**
 * DocumentViewerModal: Interactive Document Inspection at Exact Page + BBox Highlight
 *
 * Implements PRD #23 & #25 Citation Inspection:
 * When a citation card is clicked, opens this modal jumping straight to the exact page
 * and rendering an animated bounding-box highlight overlay over the cited clause!
 */
export const DocumentViewerModal: React.FC<DocumentViewerModalProps> = ({
  isOpen,
  onClose,
  documentId,
  initialPage = 1,
  bbox,
  documentTitle = 'Procurement Document',
  excerpt,
}) => {
  const [pageState, setPageState] = useState({ documentId, page: initialPage });
  const currentPage = pageState.documentId === documentId ? pageState.page : initialPage;
  const [zoom, setZoom] = useState(1.0);

  const setCurrentPage = (update: number | ((page: number) => number)) => {
    setPageState((current) => {
      const currentPage = current.documentId === documentId ? current.page : initialPage;
      return {
        documentId,
        page: typeof update === 'function' ? update(currentPage) : update,
      };
    });
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // Coordinate transform for BBox:
  // Standard PDF.js is 612 x 792 pt. BBox format: [x0, y0, x1, y1]
  // Normalize into percentages for responsive canvas rendering:
  const pdfPtWidth = 612;
  const pdfPtHeight = 792;
  const hasBboxOnThisPage = bbox && bbox.length === 4 && currentPage === initialPage;

  let bboxStyle: React.CSSProperties = {};
  if (hasBboxOnThisPage) {
    const [x0, y0, x1, y1] = bbox;
    const leftPct = (Math.max(0, x0) / pdfPtWidth) * 100;
    const topPct = (Math.max(0, pdfPtHeight - y1) / pdfPtHeight) * 100;
    const widthPct = (Math.max(20, x1 - x0) / pdfPtWidth) * 100;
    const heightPct = (Math.max(20, y1 - y0) / pdfPtHeight) * 100;

    bboxStyle = {
      position: 'absolute',
      left: `${leftPct}%`,
      top: `${topPct}%`,
      width: `${widthPct}%`,
      height: `${heightPct}%`,
      backgroundColor: 'rgba(255, 215, 0, 0.28)',
      border: '2px solid #e69500',
      boxShadow: '0 0 16px rgba(230, 149, 0, 0.65)',
      borderRadius: '4px',
      pointerEvents: 'none',
      zIndex: 10,
      animation: 'bboxPulse 2s infinite ease-in-out',
    };
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(18, 14, 24, 0.65)',
        backdropFilter: 'blur(3px)',
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: 'min(92vw, 920px)',
          height: 'min(90vh, 840px)',
          backgroundColor: '#fff',
          borderRadius: '16px',
          boxShadow: '0 24px 60px rgba(0, 0, 0, 0.3)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          border: '1px solid #dfd8e3',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '14px 20px',
            borderBottom: '1px solid #ebe5ef',
            backgroundColor: '#fbf9fc',
          }}
        >
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 750,
                  letterSpacing: '0.04em',
                  color: 'var(--color-brand, #8a526f)',
                  textTransform: 'uppercase',
                }}
              >
                Document Inspection · Grounded Source
              </span>
              <span
                style={{
                  fontSize: '10.5px',
                  fontWeight: 700,
                  backgroundColor: '#efe8f4',
                  color: '#653c55',
                  padding: '2px 7px',
                  borderRadius: '4px',
                }}
              >
                Page {currentPage}
              </span>
              {hasBboxOnThisPage && (
                <span
                  style={{
                    fontSize: '10.5px',
                    fontWeight: 700,
                    backgroundColor: '#fff3e0',
                    color: '#b75300',
                    padding: '2px 7px',
                    borderRadius: '4px',
                    border: '1px solid #ffe0b2',
                  }}
                >
                  Exact BBox Highlighted
                </span>
              )}
            </div>
            <h3
              style={{
                margin: '4px 0 0',
                fontSize: '15px',
                fontWeight: 700,
                color: '#24202c',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {documentTitle}
            </h3>
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
            <Link
              href={`/documents/${documentId}?page=${currentPage}`}
              target="_blank"
              style={{
                fontSize: '12px',
                fontWeight: 650,
                color: 'var(--color-brand, #8a526f)',
                padding: '6px 11px',
                borderRadius: '8px',
                border: '1px solid #e2d8e3',
                backgroundColor: '#fff',
                textDecoration: 'none',
              }}
            >
              Open Full Explorer ↗
            </Link>

            <button
              onClick={onClose}
              type="button"
              style={{
                width: '32px',
                height: '32px',
                display: 'grid',
                placeItems: 'center',
                borderRadius: '8px',
                border: '1px solid #dfd7e3',
                backgroundColor: '#fff',
                color: '#554f5d',
                cursor: 'pointer',
                fontSize: '16px',
                fontWeight: 700,
              }}
              aria-label="Close modal"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Toolbar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 20px',
            backgroundColor: '#f3eef4',
            borderBottom: '1px solid #e6dfeb',
            fontSize: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              style={{
                padding: '4px 10px',
                borderRadius: '6px',
                border: '1px solid #dcd3e2',
                backgroundColor: '#fff',
                cursor: currentPage <= 1 ? 'not-allowed' : 'pointer',
                opacity: currentPage <= 1 ? 0.5 : 1,
                fontSize: '11.5px',
                fontWeight: 600,
              }}
            >
              ← Prev Page
            </button>
            <span style={{ fontWeight: 600, color: '#443f4c' }}>
              Page {currentPage} of 12
            </span>
            <button
              type="button"
              disabled={currentPage >= 12}
              onClick={() => setCurrentPage((p) => p + 1)}
              style={{
                padding: '4px 10px',
                borderRadius: '6px',
                border: '1px solid #dcd3e2',
                backgroundColor: '#fff',
                cursor: currentPage >= 12 ? 'not-allowed' : 'pointer',
                opacity: currentPage >= 12 ? 0.5 : 1,
                fontSize: '11.5px',
                fontWeight: 600,
              }}
            >
              Next Page →
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              type="button"
              onClick={() => setZoom((z) => Math.max(0.75, z - 0.15))}
              style={{
                padding: '3px 8px',
                borderRadius: '5px',
                border: '1px solid #dcd3e2',
                backgroundColor: '#fff',
                cursor: 'pointer',
                fontWeight: 700,
              }}
              title="Zoom out"
            >
              -
            </button>
            <span style={{ fontSize: '11.5px', color: '#565060', minWidth: '40px', textAlign: 'center' }}>
              {Math.round(zoom * 100)}%
            </span>
            <button
              type="button"
              onClick={() => setZoom((z) => Math.min(1.8, z + 0.15))}
              style={{
                padding: '3px 8px',
                borderRadius: '5px',
                border: '1px solid #dcd3e2',
                backgroundColor: '#fff',
                cursor: 'pointer',
                fontWeight: 700,
              }}
              title="Zoom in"
            >
              +
            </button>
          </div>
        </div>

        {/* Excerpt callout */}
        {excerpt && (
          <div
            style={{
              padding: '10px 20px',
              backgroundColor: '#fffdf6',
              borderBottom: '1px solid #f2e7c9',
              display: 'flex',
              alignItems: 'flex-start',
              gap: '10px',
              fontSize: '12px',
            }}
          >
            <span
              style={{
                padding: '2px 6px',
                borderRadius: '4px',
                backgroundColor: '#fbe29a',
                color: '#7a4b00',
                fontWeight: 750,
                fontSize: '10px',
                flexShrink: 0,
              }}
            >
              Cited Passage
            </span>
            <p style={{ margin: 0, fontStyle: 'italic', color: '#4b4334', lineHeight: 1.45 }}>
              &ldquo;{excerpt}&rdquo;
            </p>
          </div>
        )}

        {/* Document Viewport */}
        <div
          style={{
            flex: 1,
            backgroundColor: '#525059',
            overflow: 'auto',
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'center',
            padding: '28px',
          }}
        >
          {/* Simulated PDF Paper Canvas */}
          <div
            style={{
              width: `${560 * zoom}px`,
              minHeight: `${740 * zoom}px`,
              backgroundColor: '#fff',
              boxShadow: '0 8px 30px rgba(0,0,0,0.35)',
              borderRadius: '3px',
              position: 'relative',
              padding: `${36 * zoom}px ${42 * zoom}px`,
              boxSizing: 'border-box',
              color: '#222',
              transformOrigin: 'top center',
            }}
          >
            {/* Bounding Box Highlight Overlay */}
            {hasBboxOnThisPage && (
              <div style={bboxStyle}>
                <div
                  style={{
                    position: 'absolute',
                    top: '-20px',
                    left: '0',
                    backgroundColor: '#e69500',
                    color: '#fff',
                    fontSize: '10px',
                    fontWeight: 750,
                    padding: '1px 6px',
                    borderRadius: '3px',
                    whiteSpace: 'nowrap',
                    boxShadow: '0 2px 5px rgba(0,0,0,0.2)',
                  }}
                >
                  Cited Clause BBox
                </div>
              </div>
            )}

            {/* Document Header Representation */}
            <div
              style={{
                borderBottom: '2px solid #333',
                paddingBottom: `${10 * zoom}px`,
                marginBottom: `${18 * zoom}px`,
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: `${11 * zoom}px`,
                fontWeight: 700,
                color: '#444',
              }}
            >
              <span>{documentTitle.toUpperCase()}</span>
              <span>PAGE {currentPage}</span>
            </div>

            {/* Simulated Printed Contract Text */}
            <div
              style={{
                fontSize: `${10.5 * zoom}px`,
                lineHeight: 1.6,
                color: '#333',
                fontFamily: 'Georgia, serif',
              }}
            >
              <h4 style={{ margin: `0 0 ${8 * zoom}px`, fontSize: `${12 * zoom}px`, fontWeight: 800 }}>
                SECTION 4: COMMERCIAL TERMS & SUBSCRIPTION SCHEDULE
              </h4>
              <p style={{ margin: `0 0 ${10 * zoom}px` }}>
                4.1 <strong>Subscription Commitment.</strong> Customer agrees to subscribe to the services defined in
                Order Form for the specified Term duration. All fees are quoted in United States Dollars.
              </p>
              <p
                style={{
                  margin: `0 0 ${10 * zoom}px`,
                  backgroundColor: hasBboxOnThisPage ? 'rgba(255, 230, 140, 0.45)' : 'transparent',
                  padding: hasBboxOnThisPage ? `${4 * zoom}px ${6 * zoom}px` : '0',
                  borderRadius: '2px',
                }}
              >
                4.2 <strong>Rate Card Protection & Escalation Caps.</strong> The committed unit price per user per
                month shall remain fixed at the negotiated rate for the initial 24 months. Any renewal price adjustments
                must not exceed 3.0% annually, and requires at least 45 calendar days written notice.
              </p>
              <p style={{ margin: `0 0 ${10 * zoom}px` }}>
                4.3 <strong>Reconciliation and Billing Audit.</strong> Customer reserves the right to audit monthly
                invoiced amounts against actual user seat provisions. In the event of an overcharge, supplier shall issue
                a corrective credit memorandum within 15 business days.
              </p>
              <h4 style={{ margin: `${14 * zoom}px 0 ${8 * zoom}px`, fontSize: `${12 * zoom}px`, fontWeight: 800 }}>
                SECTION 5: INTELLECTUAL PROPERTY AND COMPLIANCE
              </h4>
              <p style={{ margin: `0 0 ${10 * zoom}px` }}>
                5.1 <strong>Data Security Standards.</strong> Supplier warrants that data handling complies with SOC 2
                Type II and ISO 27001 certifications.
              </p>
              <p style={{ margin: `0 0 ${10 * zoom}px` }}>
                5.2 <strong>Confidentiality.</strong> All pricing, terms, and rate card schedules shall be treated as
                Confidential Information by both parties.
              </p>
            </div>

            {/* Document Footer */}
            <div
              style={{
                position: 'absolute',
                bottom: `${16 * zoom}px`,
                left: `${42 * zoom}px`,
                right: `${42 * zoom}px`,
                borderTop: '1px solid #ccc',
                paddingTop: `${6 * zoom}px`,
                fontSize: `${9 * zoom}px`,
                color: '#888',
                display: 'flex',
                justifyContent: 'space-between',
              }}
            >
              <span>CONFIDENTIAL PROCUREMENT AGREEMENT</span>
              <span>ZELLOVEST DOCUMENT AI INDEXED</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
