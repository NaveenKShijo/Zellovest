'use client';

import React, { FormEvent, useState } from 'react';
import { DocumentDetail, InvoiceReviewCommitRequest } from '@/types';
import { useApi } from '@/lib/api';
import { ExceptionDrawer } from './ExceptionDrawer';
import { ReviewConfidenceChips } from './ReviewConfidenceChips';
import { useReviewHashRequest } from './useReviewHashRequest';

type InvoiceLineForm = {
    description: string;
    product_code: string;
    quantity: string;
    unit_price: string;
};

type InvoiceForm = {
    invoice_number: string;
    vendor_name: string;
    invoice_date: string;
    due_date: string;
    currency: string;
    subtotal: string;
    tax_amount: string;
    total_amount: string;
    reviewer_notes: string;
    line_items: InvoiceLineForm[];
};

const REVIEW_FORM_ID = 'invoice-review-form';

const panelStyle: React.CSSProperties = {
    backgroundColor: 'var(--bg-surface)',
    border: '1px solid var(--border-subtle)',
    borderLeft: '4px solid var(--color-warning)',
    borderRadius: 'var(--radius-lg)',
    overflow: 'hidden',
};

const inputStyle: React.CSSProperties = {
    width: '100%',
    minWidth: 0,
    boxSizing: 'border-box',
    padding: '9px 10px',
    color: 'var(--text-primary)',
    backgroundColor: 'var(--bg-surface)',
    border: '1px solid var(--border-subtle)',
    borderRadius: 'var(--radius-sm)',
    fontSize: '13px',
};

function record(value: unknown): Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : {};
}

function text(value: unknown): string {
    return value === null || value === undefined ? '' : String(value);
}

function dateInput(value: unknown): string {
    return text(value).slice(0, 10);
}

function newLine(): InvoiceLineForm {
    return { description: '', product_code: '', quantity: '1', unit_price: '' };
}

function lineTotal(line: InvoiceLineForm): number {
    const quantity = Number(line.quantity);
    const unitPrice = Number(line.unit_price);
    if (!Number.isFinite(quantity) || !Number.isFinite(unitPrice)) return 0;
    return Math.round(quantity * unitPrice * 100) / 100;
}

function initializeForm(document: DocumentDetail): InvoiceForm {
    const structured = record(document.structured_data);
    const reviewData = record(document.review?.data);
    const source = Object.keys(structured).length > 0 ? structured : reviewData;
    const extractedLines = Array.isArray(source.line_items) ? source.line_items.map(record) : [];
    const lineItems = extractedLines.length
        ? extractedLines.map((line): InvoiceLineForm => ({
            description: text(line.description),
            product_code: text(line.product_code),
            quantity: text(line.quantity || 1),
            unit_price: text(line.unit_price),
        }))
        : [newLine()];

    return {
        invoice_number: text(source.invoice_number),
        vendor_name: text(source.vendor_name || document.vendor_name),
        invoice_date: dateInput(source.invoice_date),
        due_date: dateInput(source.due_date),
        currency: text(source.currency || 'USD').toUpperCase(),
        subtotal: text(source.subtotal),
        tax_amount: text(source.tax_amount ?? '0'),
        total_amount: text(source.total_amount),
        reviewer_notes: '',
        line_items: lineItems,
    };
}

function Field({
    label,
    value,
    onChange,
    type = 'text',
    required = false,
    step,
    maxLength,
}: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    type?: string;
    required?: boolean;
    step?: string;
    maxLength?: number;
}) {
    return (
        <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: 0 }}>
            <span style={{ color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 600 }}>{label}</span>
            <input
                type={type}
                value={value}
                required={required}
                step={step}
                maxLength={maxLength}
                onChange={(event) => onChange(event.target.value)}
                style={inputStyle}
            />
        </label>
    );
}

function moneyValue(value: string): number {
    return value.trim() === '' ? NaN : Number(value);
}

function validateForm(form: InvoiceForm): string | null {
    if (!form.invoice_number.trim()) return 'Invoice number is required.';
    if (!form.vendor_name.trim()) return 'Vendor is required.';
    if (!form.invoice_date) return 'Invoice date is required.';
    if (form.due_date && form.due_date < form.invoice_date) {
        return 'Due date must be on or after the invoice date.';
    }
    if (form.currency.trim().length !== 3) return 'Currency must be a three-letter ISO code.';
    for (const [field, label] of [
        [form.subtotal, 'Subtotal'],
        [form.tax_amount, 'Tax amount'],
        [form.total_amount, 'Total amount'],
    ] as const) {
        const amount = moneyValue(field);
        if (!Number.isFinite(amount) || amount < 0) {
            return `${label} must be a valid, non-negative amount.`;
        }
    }
    if (form.line_items.length === 0) return 'At least one line item is required.';
    for (const [index, line] of form.line_items.entries()) {
        if (!line.description.trim()) {
            return `Line ${index + 1}: description is required.`;
        }
        const quantity = Number(line.quantity);
        if (!Number.isFinite(quantity) || quantity <= 0) {
            return `Line ${index + 1}: quantity must be greater than zero.`;
        }
        const unitPrice = Number(line.unit_price);
        if (!Number.isFinite(unitPrice) || unitPrice < 0) {
            return `Line ${index + 1}: enter a valid, non-negative unit price.`;
        }
    }
    return null;
}

function toRequest(form: InvoiceForm): InvoiceReviewCommitRequest {
    return {
        invoice_number: form.invoice_number.trim(),
        vendor_name: form.vendor_name.trim(),
        invoice_date: form.invoice_date,
        due_date: form.due_date || null,
        currency: form.currency.trim().toUpperCase(),
        subtotal: moneyValue(form.subtotal),
        tax_amount: moneyValue(form.tax_amount),
        total_amount: moneyValue(form.total_amount),
        reviewer_notes: form.reviewer_notes.trim() || null,
        line_items: form.line_items.map((line) => ({
            description: line.description.trim(),
            product_code: line.product_code.trim() || null,
            quantity: Number(line.quantity),
            unit_price: Number(line.unit_price),
            total: lineTotal(line),
        })),
    };
}

/**
 * Human-in-the-loop review for low-confidence invoice extractions.
 *
 * The warning banner stays on the page; corrections happen in a side drawer
 * so the reviewer can read the source PDF behind it. Committing updates the
 * provisional invoice and its line items in the operational ledger and writes
 * human-verified provenance plus a review receipt.
 */
export function InvoiceReviewPanel({
    document,
    onCommitted,
}: {
    document: DocumentDetail;
    onCommitted: () => void;
}) {
    const api = useApi();
    const review = document.review;
    const [form, setForm] = useState<InvoiceForm>(() => initializeForm(document));
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [drawerDismissed, setDrawerDismissed] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [committed, setCommitted] = useState(review?.status === 'committed');
    // The explorer's "Review exception" link lands on ``#review``: open the
    // correction drawer immediately instead of making the reviewer hunt for it.
    const reviewHashRequested = useReviewHashRequest();
    const showDrawer = drawerOpen || (reviewHashRequested && !drawerDismissed);

    const openDrawer = () => {
        setDrawerDismissed(false);
        setDrawerOpen(true);
    };

    const closeDrawer = () => {
        setDrawerOpen(false);
        setDrawerDismissed(true);
    };

    if (document.document_type !== 'invoice') return null;

    if (review?.status === 'committed' || committed) {
        return (
            <section aria-label="Human review status" style={{ ...panelStyle, borderLeftColor: 'var(--color-success)' }}>
                <div style={{ padding: '16px 20px' }}>
                    <h2 style={{ margin: '0 0 6px', color: 'var(--text-primary)', fontSize: '15px' }}>
                        Invoice verified and committed to ledger
                    </h2>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '13px' }}>
                        A reviewer confirmed the invoice fields. The corrected values are now the operational ledger record.
                    </p>
                    {review?.reviewed_at && (
                        <p style={{ margin: '8px 0 0', color: 'var(--text-muted)', fontSize: '11px' }}>
                            Reviewed {new Date(review.reviewed_at).toLocaleString()}
                            {review.reviewer_email ? ` by ${review.reviewer_email}` : ''}
                        </p>
                    )}
                    {review?.reviewer_notes && (
                        <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: '11.5px' }}>
                            Notes: {review.reviewer_notes}
                        </p>
                    )}
                    {review?.commercial_match_required && (
                        <p role="alert" style={{ margin: '10px 0 0', padding: '10px 12px', borderRadius: 'var(--radius-md)', background: 'var(--color-warning-subtle)', color: 'var(--color-warning)', fontSize: '12px', lineHeight: 1.5 }}>
                            Contract matching needs review: {review.reason || 'No unique effective contract term matched this invoice.'}
                        </p>
                    )}
                </div>
            </section>
        );
    }

    const reviewIsOpen =
        review?.status === 'pending' ||
        (review?.status == null && document.status === 'review_needed' && document.has_artifact);

    if (!reviewIsOpen) {
        if (document.status !== 'review_needed') return null;
        return (
            <section id="review" aria-label="Human review needed" style={panelStyle}>
                <div style={{ padding: '16px 20px' }}>
                    <h2 style={{ margin: '0 0 6px', color: 'var(--text-primary)', fontSize: '15px' }}>
                        Invoice extraction needs a closer look
                    </h2>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '13px', lineHeight: 1.5 }}>
                        No extraction artifact is available to review yet. Re-run the pipeline or inspect the source document before relying on these values.
                    </p>
                </div>
            </section>
        );
    }

    const updateForm = (field: keyof Omit<InvoiceForm, 'line_items'>, value: string) => {
        setForm((current) => ({ ...current, [field]: value }));
    };

    const updateLine = (index: number, field: keyof InvoiceLineForm, value: string) => {
        setForm((current) => ({
            ...current,
            line_items: current.line_items.map((line, lineIndex) =>
                lineIndex === index ? { ...line, [field]: value } : line
            ),
        }));
    };

    const recalculateTotals = () => {
        const subtotal = form.line_items.reduce((sum, line) => sum + lineTotal(line), 0);
        const tax = Number(form.tax_amount);
        const total = subtotal + (Number.isFinite(tax) ? tax : 0);
        setForm((current) => ({
            ...current,
            subtotal: subtotal.toFixed(2),
            total_amount: total.toFixed(2),
        }));
    };

    const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setError(null);
        const validationError = validateForm(form);
        if (validationError) {
            setError(validationError);
            return;
        }
        setSaving(true);
        try {
            await api.documents.commitInvoiceReview(document.id, toRequest(form));
            setCommitted(true);
            closeDrawer();
            onCommitted();
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : 'Unable to commit verified invoice.');
        } finally {
            setSaving(false);
        }
    };

    return (
        <>
            <section id="review" aria-label="Human review" style={panelStyle}>
                <div style={{ padding: '16px 20px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                        <h2 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '15px' }}>Invoice fields need verification</h2>
                        <span style={{
                            padding: '3px 8px', borderRadius: 'var(--radius-full)',
                            background: 'var(--color-warning-subtle)', color: 'var(--color-warning)',
                            fontSize: '11px', fontWeight: 700,
                        }}>
                            Human verification required
                        </span>
                    </div>
                    <p style={{ margin: '8px 0 0', color: 'var(--text-secondary)', fontSize: '12.5px', lineHeight: 1.5 }}>
                        {review?.reason
                            ?? (document.extraction_confidence !== null
                                ? `Extraction confidence is ${Math.round(document.extraction_confidence * 100)}% for this invoice.`
                                : 'Extraction confidence is unavailable for this invoice.')}
                    </p>
                    <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: '12px', lineHeight: 1.5 }}>
                        {document.structured_data
                            ? 'The provisional ledger values are pre-filled below. Correct anything that differs from the source invoice.'
                            : 'The extraction did not reach the ledger. Complete the fields below from the source invoice to create the record.'}
                    </p>
                    {review && <ReviewConfidenceChips review={review} />}
                    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginTop: '14px' }}>
                        <button
                            type="button"
                            onClick={() => {
                                setError(null);
                                openDrawer();
                            }}
                            style={{
                                border: 0,
                                borderRadius: 'var(--radius-md)',
                                padding: '10px 15px',
                                background: 'var(--color-brand)',
                                color: 'white',
                                fontSize: '12.5px',
                                fontWeight: 700,
                                cursor: 'pointer',
                            }}
                        >
                            Review & correct invoice
                        </button>
                        <span style={{ alignSelf: 'center', color: 'var(--text-muted)', fontSize: '11.5px' }}>
                            Source document preview stays available behind the drawer.
                        </span>
                    </div>
                </div>
            </section>

            <ExceptionDrawer
                open={showDrawer}
                onClose={() => {
                    if (!saving) closeDrawer();
                }}
                title="Verify invoice fields"
                subtitle="Compare every value against the source invoice, correct anything the extraction got wrong, then commit the verified record to the operational ledger."
                badge={(
                    <span style={{
                        padding: '3px 8px', borderRadius: 'var(--radius-full)',
                        background: 'var(--color-warning-subtle)', color: 'var(--color-warning)',
                        fontSize: '11px', fontWeight: 700,
                    }}>
                        Low confidence
                    </span>
                )}
                footer={(
                    <>
                        <button
                            type="button"
                            disabled={saving}
                            onClick={closeDrawer}
                            style={{
                                border: '1px solid var(--border-subtle)',
                                borderRadius: 'var(--radius-md)',
                                padding: '10px 15px',
                                background: 'var(--bg-surface)',
                                color: 'var(--text-secondary)',
                                fontSize: '12.5px',
                                fontWeight: 600,
                                cursor: saving ? 'default' : 'pointer',
                            }}
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            form={REVIEW_FORM_ID}
                            disabled={saving}
                            style={{
                                border: 0,
                                borderRadius: 'var(--radius-md)',
                                padding: '10px 16px',
                                background: saving ? 'var(--text-muted)' : 'var(--color-brand)',
                                color: 'white',
                                fontSize: '12.5px',
                                fontWeight: 700,
                                cursor: saving ? 'wait' : 'pointer',
                            }}
                        >
                            {saving ? 'Committing…' : 'Verify & Commit to Ledger'}
                        </button>
                    </>
                )}
            >
                <form id={REVIEW_FORM_ID} onSubmit={handleSubmit}>
                    <h3 style={{ margin: '0 0 12px', color: 'var(--text-primary)', fontSize: '13px' }}>Invoice header</h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '12px' }}>
                        <Field label="Invoice number" value={form.invoice_number} required onChange={(value) => updateForm('invoice_number', value)} />
                        <Field label="Vendor" value={form.vendor_name} required onChange={(value) => updateForm('vendor_name', value)} />
                        <Field label="Invoice date" type="date" value={form.invoice_date} required onChange={(value) => updateForm('invoice_date', value)} />
                        <Field label="Due date" type="date" value={form.due_date} onChange={(value) => updateForm('due_date', value)} />
                        <Field label="Currency" value={form.currency} required maxLength={3} onChange={(value) => updateForm('currency', value.toUpperCase())} />
                        <Field label="Subtotal" type="number" step="0.01" value={form.subtotal} required onChange={(value) => updateForm('subtotal', value)} />
                        <Field label="Tax amount" type="number" step="0.01" value={form.tax_amount} required onChange={(value) => updateForm('tax_amount', value)} />
                        <Field label="Total amount" type="number" step="0.01" value={form.total_amount} required onChange={(value) => updateForm('total_amount', value)} />
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginTop: '22px' }}>
                        <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '13px' }}>Line items</h3>
                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                            <button type="button" onClick={recalculateTotals} style={{ ...inputStyle, width: 'auto', cursor: 'pointer', fontWeight: 600 }}>
                                Recalculate totals
                            </button>
                            <button type="button" onClick={() => setForm((current) => ({ ...current, line_items: [...current.line_items, newLine()] }))} style={{ ...inputStyle, width: 'auto', cursor: 'pointer', fontWeight: 600 }}>
                                Add line item
                            </button>
                        </div>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '12px' }}>
                        {form.line_items.map((line, index) => (
                            <fieldset key={index} style={{ minWidth: 0, margin: 0, padding: '14px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
                                <legend style={{ padding: '0 6px', color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 700 }}>Line {index + 1}</legend>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(175px, 1fr))', gap: '11px' }}>
                                    <Field label="Description" value={line.description} required onChange={(value) => updateLine(index, 'description', value)} />
                                    <Field label="Product code" value={line.product_code} onChange={(value) => updateLine(index, 'product_code', value)} />
                                    <Field label="Quantity" type="number" step="0.01" value={line.quantity} required onChange={(value) => updateLine(index, 'quantity', value)} />
                                    <Field label="Unit price" type="number" step="0.01" value={line.unit_price} required onChange={(value) => updateLine(index, 'unit_price', value)} />
                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: 0 }}>
                                        <span style={{ color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 600 }}>Line total</span>
                                        <span style={{ ...inputStyle, backgroundColor: 'var(--bg-surface-tint)', color: 'var(--text-secondary)' }}>
                                            {lineTotal(line).toFixed(2)}
                                        </span>
                                    </label>
                                </div>
                                {form.line_items.length > 1 && (
                                    <button type="button" onClick={() => setForm((current) => ({ ...current, line_items: current.line_items.filter((_, lineIndex) => lineIndex !== index) }))} style={{ marginTop: '10px', padding: 0, border: 0, background: 'transparent', color: 'var(--color-danger)', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}>
                                        Remove line
                                    </button>
                                )}
                            </fieldset>
                        ))}
                    </div>

                    <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '18px' }}>
                        <span style={{ color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 600 }}>
                            Reviewer notes (optional)
                        </span>
                        <textarea
                            value={form.reviewer_notes}
                            onChange={(event) => updateForm('reviewer_notes', event.target.value)}
                            rows={3}
                            placeholder="Record what you corrected or anything the next reviewer should know."
                            style={{ ...inputStyle, resize: 'vertical' }}
                        />
                    </label>

                    {error && (
                        <div role="alert" style={{ marginTop: '14px', padding: '10px 12px', borderRadius: 'var(--radius-md)', background: 'var(--color-danger-subtle)', color: 'var(--color-danger)', fontSize: '12.5px' }}>
                            {error}
                        </div>
                    )}
                </form>
            </ExceptionDrawer>
        </>
    );
}
