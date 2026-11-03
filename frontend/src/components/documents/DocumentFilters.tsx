'use client';

import React from 'react';
import { DocumentStatus } from '@/types';
import { StatusPill } from './StatusPill';

/** Filter state owned by the DocumentExplorer (URL-is the source of truth). */
export interface DocumentFilterState {
    search: string;
    status: DocumentStatus | null;
    vendor: string;
}

const STATUS_OPTIONS: Array<{ value: DocumentStatus | null; label: string }> = [
    { value: null, label: 'All' },
    { value: 'extracted', label: 'Extracted' },
    { value: 'processing', label: 'Processing' },
    { value: 'review_needed', label: 'Review Needed' },
    { value: 'failed', label: 'Failed' },
];

/**
 * Search + status + vendor filter bar for the Explorer.
 * Presentational: the parent pushes edits into the URL (query params).
 */
export function DocumentFilters({
    search,
    status,
    vendor,
    totalCount,
    onSearchChange,
    onStatusChange,
    onVendorChange,
}: {
    search: string;
    status: DocumentStatus | null;
    vendor: string;
    totalCount: number;
    onSearchChange: (value: string) => void;
    onStatusChange: (value: DocumentStatus | null) => void;
    onVendorChange: (value: string) => void;
}) {
    const inputStyle: React.CSSProperties = {
        padding: '9px 12px',
        borderRadius: 'var(--radius-sm)',
        border: '1px solid var(--border-subtle)',
        backgroundColor: 'var(--bg-surface)',
        fontSize: '13px',
        color: 'var(--text-primary)',
        outline: 'none',
    };

    return (
        <div
            style={{
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '10px',
            }}
        >
            {/* Filename search */}
            <label
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    flex: '1 1 260px',
                    minWidth: '220px',
                    padding: '0 12px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-subtle)',
                    backgroundColor: 'var(--bg-surface)',
                }}
            >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                <input
                    type="search"
                    value={search}
                    placeholder="Search by filename…"
                    aria-label="Search documents by filename"
                    onChange={(e) => onSearchChange(e.target.value)}
                    style={{
                        flex: 1,
                        border: 'none',
                        outline: 'none',
                        padding: '9px 0',
                        fontSize: '13px',
                        color: 'var(--text-primary)',
                        backgroundColor: 'transparent',
                        fontFamily: 'inherit',
                    }}
                />
            </label>

            {/* Status chips (single select; click again to clear) */}
            <div role="group" aria-label="Filter by status" style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {STATUS_OPTIONS.map((option) => {
                    const isActive = option.value === status;
                    if (option.value === null) {
                        return (
                            <button
                                key="all"
                                type="button"
                                onClick={() => onStatusChange(null)}
                                aria-pressed={isActive}
                                style={{
                                    padding: '7px 12px',
                                    borderRadius: 'var(--radius-full)',
                                    fontSize: '12px',
                                    fontWeight: 600,
                                    border: `1px solid ${isActive ? 'var(--color-brand)' : 'var(--border-subtle)'}`,
                                    backgroundColor: isActive ? 'var(--color-brand)' : 'var(--bg-surface)',
                                    color: isActive ? '#FFFFFF' : 'var(--text-secondary)',
                                    cursor: 'pointer',
                                    transition: 'all var(--transition-fast)',
                                }}
                            >
                                All{!isActive ? ` · ${totalCount}` : ''}
                            </button>
                        );
                    }
                    return (
                        <button
                            key={option.value}
                            type="button"
                            onClick={() => onStatusChange(isActive ? null : option.value)}
                            aria-pressed={isActive}
                            style={{ all: 'unset', cursor: 'pointer' }}
                        >
                            <span
                                style={{
                                    display: 'inline-block',
                                    padding: isActive ? '2px 9px' : '3px 10px',
                                    borderRadius: 'var(--radius-full)',
                                    opacity: isActive ? 1 : 0.66,
                                    boxShadow: isActive ? '0 0 0 2px var(--color-brand-border)' : 'none',
                                    filter: isActive ? 'none' : 'grayscale(0.35)',
                                    transition: 'all var(--transition-fast)',
                                }}
                            >
                                <StatusPill status={option.value} size="sm" />
                            </span>
                        </button>
                    );
                })}
            </div>

            {/* Vendor filter (name, UUID deep-link, or raw tag) */}
            <input
                type="text"
                value={vendor}
                placeholder="Vendor…"
                aria-label="Filter by vendor"
                onChange={(e) => onVendorChange(e.target.value)}
                style={{ ...inputStyle, width: '180px' }}
            />
        </div>
    );
}
