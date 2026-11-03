'use client';

import React, { ReactNode, useEffect, useId, useRef } from 'react';

/**
 * Accessible right-side exception drawer used by human-in-the-loop review.
 *
 * The drawer is a modal surface: it locks page scrolling, traps the initial
 * focus inside the panel, closes on Escape or backdrop click, and keeps the
 * destructive-free commit action in a sticky footer so long term forms remain
 * reviewable without losing the primary action.
 */
export function ExceptionDrawer({
    open,
    onClose,
    title,
    subtitle,
    badge,
    children,
    footer,
}: {
    open: boolean;
    onClose: () => void;
    title: string;
    subtitle?: string;
    badge?: ReactNode;
    children: ReactNode;
    footer?: ReactNode;
}) {
    const panelRef = useRef<HTMLDivElement>(null);
    const titleId = useId();

    useEffect(() => {
        if (!open) return;
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.stopPropagation();
                onClose();
            }
        };
        document.addEventListener('keydown', handleKeyDown);
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        panelRef.current?.focus();

        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = previousOverflow;
        };
    }, [open, onClose]);

    if (!open) return null;

    return (
        <div
            role="presentation"
            onMouseDown={(event) => {
                if (event.target === event.currentTarget) onClose();
            }}
            style={{
                position: 'fixed',
                inset: 0,
                zIndex: 220,
                display: 'flex',
                justifyContent: 'flex-end',
                backgroundColor: 'rgba(15, 23, 42, 0.45)',
                backdropFilter: 'blur(2px)',
            }}
        >
            <aside
                ref={panelRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                tabIndex={-1}
                style={{
                    width: 'min(720px, 100vw)',
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    backgroundColor: 'var(--bg-surface)',
                    borderLeft: '1px solid var(--border-subtle)',
                    boxShadow: '-18px 0 48px rgba(15, 23, 42, 0.18)',
                    outline: 'none',
                }}
            >
                <header
                    style={{
                        display: 'flex',
                        alignItems: 'flex-start',
                        justifyContent: 'space-between',
                        gap: '16px',
                        padding: '20px 24px',
                        borderBottom: '1px solid var(--border-subtle)',
                    }}
                >
                    <div style={{ minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                            <h2
                                id={titleId}
                                style={{ margin: 0, fontSize: '17px', fontWeight: 700, color: 'var(--text-primary)' }}
                            >
                                {title}
                            </h2>
                            {badge}
                        </div>
                        {subtitle && (
                            <p style={{ margin: '6px 0 0', fontSize: '12.5px', lineHeight: 1.5, color: 'var(--text-secondary)' }}>
                                {subtitle}
                            </p>
                        )}
                    </div>
                    <button
                        type="button"
                        aria-label="Close review drawer"
                        onClick={onClose}
                        style={{
                            flexShrink: 0,
                            width: '32px',
                            height: '32px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            border: '1px solid var(--border-subtle)',
                            borderRadius: 'var(--radius-md)',
                            backgroundColor: 'var(--bg-surface)',
                            color: 'var(--text-secondary)',
                            cursor: 'pointer',
                            fontSize: '18px',
                            lineHeight: 1,
                        }}
                    >
                        ×
                    </button>
                </header>

                <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '20px 24px' }}>
                    {children}
                </div>

                {footer && (
                    <footer
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'flex-end',
                            gap: '10px',
                            flexWrap: 'wrap',
                            padding: '16px 24px',
                            borderTop: '1px solid var(--border-subtle)',
                            backgroundColor: 'var(--bg-surface)',
                        }}
                    >
                        {footer}
                    </footer>
                )}
            </aside>
        </div>
    );
}
