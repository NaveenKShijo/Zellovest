'use client';

import React, { Suspense } from 'react';
import { DocumentExplorer } from '@/components/documents/DocumentExplorer';

/**
 * Document Explorer route (``/documents``).
 *
 * Read-only inventory of the ingestion pipeline (real GCS documents).
 * URL state (tab/status/vendor/search/page) is read via useSearchParams
 * inside the explorer, which requires a <Suspense> boundary for
 * prerendering (Next.js requirement for client hooks reading the URL).
 */
export default function DocumentsPage() {
    return (
        <Suspense
            fallback={
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <div style={{ height: '64px', background: 'var(--bg-surface-tint)', borderRadius: 'var(--radius-md)', animation: 'pulse 1.5s ease-in-out infinite' }} />
                    <div style={{ height: '280px', background: 'var(--bg-surface-tint)', borderRadius: 'var(--radius-md)', animation: 'pulse 1.5s ease-in-out infinite' }} />
                </div>
            }
        >
            <DocumentExplorer />
        </Suspense>
    );
}
