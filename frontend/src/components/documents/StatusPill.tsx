'use client';

import React from 'react';
import { DocumentStatus } from '@/types';

/**
 * Derived document lifecycle pill (PRD §7): Extracted / Processing /
 * Review Needed / Failed, each with the burgundy design-system variant.
 */
const STATUS_META: Record<
    DocumentStatus,
    { label: string; color: string; subtle: string; border: string }
> = {
    extracted: {
        label: 'Extracted',
        color: 'var(--color-success)',
        subtle: 'var(--color-success-subtle)',
        border: 'var(--color-success-border)',
    },
    processing: {
        label: 'Processing',
        color: 'var(--color-info)',
        subtle: 'var(--color-info-subtle)',
        border: 'var(--color-info-border)',
    },
    review_needed: {
        label: 'Review Needed',
        color: 'var(--color-warning)',
        subtle: 'var(--color-warning-subtle)',
        border: 'var(--color-warning-border)',
    },
    failed: {
        label: 'Failed',
        color: 'var(--color-danger)',
        subtle: 'var(--color-danger-subtle)',
        border: 'var(--color-danger-border)',
    },
};

export function StatusPill({
    status,
    size = 'md',
}: {
    status: DocumentStatus;
    size?: 'sm' | 'md';
}) {
    const meta = STATUS_META[status] ?? {
        label: status,
        color: 'var(--text-secondary)',
        subtle: 'var(--bg-surface-tint)',
        border: 'var(--border-subtle)',
    };

    return (
        <span
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: size === 'sm' ? '5px' : '7px',
                fontSize: size === 'sm' ? '10.5px' : '11px',
                fontWeight: 700,
                padding: size === 'sm' ? '2px 8px' : '3px 10px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: meta.subtle,
                color: meta.color,
                border: `1px solid ${meta.border}`,
                whiteSpace: 'nowrap',
            }}
        >
            <span
                aria-hidden="true"
                style={{
                    width: '6px',
                    height: '6px',
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: meta.color,
                    flexShrink: 0,
                }}
            />
            {meta.label}
        </span>
    );
}
