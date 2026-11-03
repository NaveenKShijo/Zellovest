'use client';

import React from 'react';

/**
 * Vendor tag chip for the Explorer table.
 *
 * `vendor_name` is the canonical `vendors.name` when the lease's raw
 * `vendor_id` parsed as a UUID and matched a registry row; otherwise the
 * raw id itself is passed through (e.g. Ramp ids). Null → quiet dash.
 */
export function VendorTag({ name, truncate = true }: { name: string | null | undefined; truncate?: boolean }) {
    if (!name) {
        return <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>—</span>;
    }

    if (!truncate) {
        return (
            <span
                style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '5px',
                    fontSize: '11.5px',
                    fontWeight: 600,
                    padding: '3px 9px',
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: 'var(--bg-surface-tint)',
                    color: 'var(--color-brand)',
                    border: '1px solid var(--border-tint)',
                    whiteSpace: 'nowrap',
                }}
            >
                {name}
            </span>
        );
    }

    return (
        <span
            title={name}
            style={{
                display: 'inline-block',
                maxWidth: '160px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontSize: '12px',
                fontWeight: 600,
                color: 'var(--text-secondary)',
            }}
        >
            {name}
        </span>
    );
}
