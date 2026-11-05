'use client';

import React from 'react';
import { ContractReviewRecord } from '@/types';

function confidencePercent(value: number): string {
    return `${Math.round(value * 100)}%`;
}

/**
 * Render the extracted fields that fell below the review threshold.
 *
 * Confidence is shown lowest-first so the reviewer can start with the least
 * trustworthy values. The component renders nothing when every field meets
 * the configured threshold.
 */
export function ReviewConfidenceChips({ review }: { review: ContractReviewRecord }) {
    const threshold = review.confidence_threshold ?? 0.8;
    const fieldConfidence = review.field_confidence ?? {};
    const uncertainFields = Object.entries(fieldConfidence)
        .filter(([, confidence]) => confidence < threshold)
        .sort(([, confidenceA], [, confidenceB]) => confidenceA - confidenceB);

    if (uncertainFields.length === 0) return null;

    return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '7px', marginTop: '11px' }}>
            {uncertainFields.map(([field, confidence]) => (
                <span
                    key={field}
                    style={{
                        padding: '4px 8px',
                        borderRadius: 'var(--radius-sm)',
                        background: 'var(--color-warning-subtle)',
                        color: 'var(--color-warning)',
                        fontSize: '11px',
                        fontWeight: 600,
                    }}
                >
                    {field.replaceAll('_', ' ')} · {confidencePercent(confidence)}
                </span>
            ))}
        </div>
    );
}
