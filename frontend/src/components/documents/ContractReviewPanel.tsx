'use client';

import React, { FormEvent, useEffect, useState } from 'react';
import { ContractReviewCommitRequest, ContractReviewRecord, DocumentDetail } from '@/types';
import { useApi } from '@/lib/api';
import { ExceptionDrawer } from './ExceptionDrawer';

type TermForm = {
    product_code: string;
    description: string;
    unit_price: string;
    currency: string;
    uom: string;
    qty_min: string;
    qty_max: string;
    discount_pct: string;
    effective_from: string;
    effective_to: string;
    escalation_pct: string;
    payment_terms: string;
    freight_terms: string;
    tax_rule: string;
};

type ReviewForm = {
    contract_number: string;
    vendor_name: string;
    title: string;
    start_date: string;
    end_date: string;
    renewal_date: string;
    notice_period_days: string;
    auto_renew: boolean;
    termination_clause: string;
    terms: TermForm[];
};

const REVIEW_FORM_ID = 'contract-review-form';

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

function newTerm(defaultDate = ''): TermForm {
    return {
        product_code: '',
        description: '',
        unit_price: '',
        currency: 'USD',
        uom: '',
        qty_min: '',
        qty_max: '',
        discount_pct: '',
        effective_from: defaultDate,
        effective_to: '',
        escalation_pct: '',
        payment_terms: '',
        freight_terms: '',
        tax_rule: '',
    };
}

function initializeForm(review: ContractReviewRecord | null, fallbackVendor: string | null): ReviewForm {
    const data = record(review?.data);
    const startDate = dateInput(data.start_date);
    const extractedTerms = Array.isArray(data.terms) ? data.terms.map(record) : [];
    const terms = extractedTerms.length
        ? extractedTerms.map((term): TermForm => ({
            product_code: text(term.product_code),
            description: text(term.description),
            unit_price: text(term.unit_price),
            currency: text(term.currency || 'USD'),
            uom: text(term.uom),
            qty_min: text(term.qty_min),
            qty_max: text(term.qty_max),
            discount_pct: text(term.discount_pct),
            effective_from: dateInput(term.effective_from || startDate),
            effective_to: dateInput(term.effective_to),
            escalation_pct: text(term.escalation_pct),
            payment_terms: text(term.payment_terms),
            freight_terms: text(term.freight_terms),
            tax_rule: text(term.tax_rule),
        }))
        : [newTerm(startDate)];

    return {
        contract_number: text(data.contract_number),
        vendor_name: text(data.vendor_name || fallbackVendor),
        title: text(data.title),
        start_date: startDate,
        end_date: dateInput(data.end_date),
        renewal_date: dateInput(data.renewal_date),
        notice_period_days: text(data.notice_period_days),
        auto_renew: data.auto_renew === true || data.auto_renew === 'true',
        termination_clause: text(data.termination_clause),
        terms,
    };
}

function Field({
    label,
    value,
    onChange,
    type = 'text',
    required = false,
    step,
}: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    type?: string;
    required?: boolean;
    step?: string;
}) {
    return (
        <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: 0 }}>
            <span style={{ color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 600 }}>{label}</span>
            <input
                type={type}
                value={value}
                required={required}
                step={step}
                onChange={(event) => onChange(event.target.value)}
                style={inputStyle}
            />
        </label>
    );
}

function optionalNumber(value: string): number | null {
    return value.trim() === '' ? null : Number(value);
}

function toRequest(form: ReviewForm): ContractReviewCommitRequest {
    return {
        contract_number: form.contract_number.trim(),
        vendor_name: form.vendor_name.trim(),
        title: form.title.trim() || null,
        start_date: form.start_date,
        end_date: form.end_date || null,
        renewal_date: form.renewal_date || null,
        notice_period_days: optionalNumber(form.notice_period_days),
        auto_renew: form.auto_renew,
        termination_clause: form.termination_clause.trim() || null,
        terms: form.terms.map((term) => ({
            product_code: term.product_code.trim(),
            description: term.description.trim(),
            unit_price: Number(term.unit_price),
            currency: term.currency.trim().toUpperCase() || 'USD',
            uom: term.uom.trim(),
            qty_min: optionalNumber(term.qty_min),
            qty_max: optionalNumber(term.qty_max),
            discount_pct: optionalNumber(term.discount_pct),
            effective_from: term.effective_from,
            effective_to: term.effective_to || null,
            escalation_pct: optionalNumber(term.escalation_pct),
            payment_terms: term.payment_terms.trim(),
            freight_terms: term.freight_terms.trim(),
            tax_rule: term.tax_rule.trim(),
        })),
    };
}

function validateForm(form: ReviewForm): string | null {
    if (!form.contract_number.trim()) return 'Contract number is required.';
    if (!form.vendor_name.trim()) return 'Vendor is required.';
    if (!form.start_date) return 'Contract start date is required.';
    if (form.end_date && form.end_date < form.start_date) {
        return 'Expiration date must be on or after the start date.';
    }
    if (form.renewal_date && form.renewal_date < form.start_date) {
        return 'Renewal date must be on or after the start date.';
    }
    if (form.terms.length === 0) return 'At least one pricing line is required.';

    for (const [index, term] of form.terms.entries()) {
        const line = index + 1;
        const unitPrice = Number(term.unit_price);
        if (!Number.isFinite(unitPrice) || unitPrice < 0) {
            return `Pricing line ${line}: enter a valid, non-negative unit price.`;
        }
        if (!term.effective_from) {
            return `Pricing line ${line}: effective date is required.`;
        }
        if (term.effective_to && term.effective_to < term.effective_from) {
            return `Pricing line ${line}: expiration date must be on or after its effective date.`;
        }
    }
    return null;
}

function confidencePercent(value: number): string {
    return `${Math.round(value * 100)}%`;
}

function LowConfidenceChips({ review }: { review: ContractReviewRecord }) {
    const threshold = review.confidence_threshold ?? 0.8;
    const fieldConfidence = review.field_confidence ?? {};
    const uncertainFields = Object.entries(fieldConfidence)
        .filter(([, confidence]) => confidence < threshold)
        .sort(([, confidenceA], [, confidenceB]) => confidenceA - confidenceB);

    if (uncertainFields.length === 0) return null;

    return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '7px', marginTop: '11px' }}>
            {uncertainFields.map(([field, confidence]) => (
                <span key={field} style={{
                    padding: '4px 8px', borderRadius: 'var(--radius-sm)',
                    background: 'var(--color-warning-subtle)', color: 'var(--color-warning)',
                    fontSize: '11px', fontWeight: 600,
                }}>
                    {field.replaceAll('_', ' ')} · {confidencePercent(confidence)}
                </span>
            ))}
        </div>
    );
}

/**
 * Human-in-the-loop exception review for low-confidence contract extractions.
 *
 * A compact warning banner remains visible on the document page; the
 * correction form opens in a side drawer so reviewers can compare the source
 * PDF behind it. Committing calls the ledger endpoint, which persists a new
 * immutable contract-term version plus human-verified provenance.
 */
export function ContractReviewPanel({
    document,
    onCommitted,
}: {
    document: DocumentDetail;
    onCommitted: () => void;
}) {
    const api = useApi();
    const review = document.review;
    const [form, setForm] = useState<ReviewForm>(() => initializeForm(review, document.vendor_name));
    const [drawerOpen, setDrawerOpen] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [committed, setCommitted] = useState(false);

    useEffect(() => {
        setForm(initializeForm(review, document.vendor_name));
        setCommitted(review?.status === 'committed');
    }, [review, document.vendor_name]);

    useEffect(() => {
        if (review?.status !== 'pending' && !committed) {
            setDrawerOpen(false);
        }
    }, [review?.status, committed]);

    if (review?.status === 'committed' || committed) {
        return (
            <section aria-label="Human review status" style={{ ...panelStyle, borderLeftColor: 'var(--color-success)' }}>
                <div style={{ padding: '16px 20px' }}>
                    <h2 style={{ margin: '0 0 6px', color: 'var(--text-primary)', fontSize: '15px' }}>
                        Verified and committed to ledger
                    </h2>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '13px' }}>
                        A reviewer confirmed this contract’s commercial terms. The verified values are now available in the operational ledger.
                    </p>
                    {review?.reviewed_at && (
                        <p style={{ margin: '8px 0 0', color: 'var(--text-muted)', fontSize: '11px' }}>
                            Reviewed {new Date(review.reviewed_at).toLocaleString()}
                            {review.reviewer_email ? ` by ${review.reviewer_email}` : ''}
                        </p>
                    )}
                </div>
            </section>
        );
    }

    if (review?.status !== 'pending') {
        if (document.status !== 'review_needed') return null;
        return (
            <section id="review" aria-label="Human review needed" style={panelStyle}>
                <div style={{ padding: '16px 20px' }}>
                    <h2 style={{ margin: '0 0 6px', color: 'var(--text-primary)', fontSize: '15px' }}>
                        Extraction needs a closer look
                    </h2>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '13px', lineHeight: 1.5 }}>
                        {document.extraction_confidence !== null && document.extraction_confidence < 0.8
                            ? 'Extraction confidence is below 80%. Review the document preview and structured data.'
                            : 'This document is marked for review. Inspect the document preview and structured data before relying on its contents.'}{' '}
                        This document type does not have editable commercial terms; review the extracted fields in the preview before relying on them.
                    </p>
                </div>
            </section>
        );
    }

    const updateForm = (field: keyof Omit<ReviewForm, 'terms'>, value: string | boolean) => {
        setForm((current) => ({ ...current, [field]: value }));
    };

    const updateTerm = (index: number, field: keyof TermForm, value: string) => {
        setForm((current) => ({
            ...current,
            terms: current.terms.map((term, termIndex) =>
                termIndex === index ? { ...term, [field]: value } : term
            ),
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
            await api.documents.commitReview(document.id, toRequest(form));
            setCommitted(true);
            setDrawerOpen(false);
            onCommitted();
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : 'Unable to commit verified terms.');
        } finally {
            setSaving(false);
        }
    };

    return (
        <>
            <section id="review" aria-label="Human review" style={panelStyle}>
                <div style={{ padding: '16px 20px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                        <h2 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '15px' }}>Commercial terms need verification</h2>
                        <span style={{
                            padding: '3px 8px', borderRadius: 'var(--radius-full)',
                            background: 'var(--color-warning-subtle)', color: 'var(--color-warning)',
                            fontSize: '11px', fontWeight: 700,
                        }}>
                            Human verification required
                        </span>
                    </div>
                    <p style={{ margin: '8px 0 0', color: 'var(--text-secondary)', fontSize: '12.5px', lineHeight: 1.5 }}>
                        {review.reason || 'One or more commercial fields were extracted below the 80% confidence threshold.'}
                    </p>
                    <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: '12px', lineHeight: 1.5 }}>
                        These terms remain provisional and are not used for invoice reconciliation until you verify and commit them.
                    </p>
                    <LowConfidenceChips review={review} />
                    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginTop: '14px' }}>
                        <button
                            type="button"
                            onClick={() => {
                                setError(null);
                                setDrawerOpen(true);
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
                            Review & correct terms
                        </button>
                        <span style={{ alignSelf: 'center', color: 'var(--text-muted)', fontSize: '11.5px' }}>
                            Source document preview stays available behind the drawer.
                        </span>
                    </div>
                </div>
            </section>

            <ExceptionDrawer
                open={drawerOpen}
                onClose={() => {
                    if (!saving) setDrawerOpen(false);
                }}
                title="Verify commercial terms"
                subtitle="Compare every value against the source document, correct anything the extraction got wrong, then commit the verified terms to the operational ledger."
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
                            onClick={() => setDrawerOpen(false)}
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
                    <h3 style={{ margin: '0 0 12px', color: 'var(--text-primary)', fontSize: '13px' }}>Contract header</h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '12px' }}>
                        <Field label="Contract number" value={form.contract_number} required onChange={(value) => updateForm('contract_number', value)} />
                        <Field label="Vendor" value={form.vendor_name} required onChange={(value) => updateForm('vendor_name', value)} />
                        <Field label="Title" value={form.title} onChange={(value) => updateForm('title', value)} />
                        <Field label="Start date" type="date" value={form.start_date} required onChange={(value) => updateForm('start_date', value)} />
                        <Field label="Expiration date" type="date" value={form.end_date} onChange={(value) => updateForm('end_date', value)} />
                        <Field label="Renewal date" type="date" value={form.renewal_date} onChange={(value) => updateForm('renewal_date', value)} />
                        <Field label="Renewal notice (days)" type="number" step="1" value={form.notice_period_days} onChange={(value) => updateForm('notice_period_days', value)} />
                        <label style={{ display: 'flex', alignItems: 'center', gap: '9px', paddingTop: '22px', color: 'var(--text-secondary)', fontSize: '13px' }}>
                            <input type="checkbox" checked={form.auto_renew} onChange={(event) => updateForm('auto_renew', event.target.checked)} />
                            Automatically renews
                        </label>
                        <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', gridColumn: '1 / -1' }}>
                            <span style={{ color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 600 }}>Termination clause</span>
                            <textarea value={form.termination_clause} onChange={(event) => updateForm('termination_clause', event.target.value)} rows={2} style={{ ...inputStyle, resize: 'vertical' }} />
                        </label>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginTop: '22px' }}>
                        <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '13px' }}>Pricing and commercial terms</h3>
                        <button type="button" onClick={() => setForm((current) => ({ ...current, terms: [...current.terms, newTerm(current.start_date)] }))} style={{ ...inputStyle, width: 'auto', cursor: 'pointer', fontWeight: 600 }}>
                            Add pricing line
                        </button>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '12px' }}>
                        {form.terms.map((term, index) => (
                            <fieldset key={index} style={{ minWidth: 0, margin: 0, padding: '14px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
                                <legend style={{ padding: '0 6px', color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 700 }}>Pricing line {index + 1}</legend>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(175px, 1fr))', gap: '11px' }}>
                                    <Field label="Product code" value={term.product_code} onChange={(value) => updateTerm(index, 'product_code', value)} />
                                    <Field label="Unit price" type="number" step="0.01" value={term.unit_price} required onChange={(value) => updateTerm(index, 'unit_price', value)} />
                                    <Field label="Currency" value={term.currency} required onChange={(value) => updateTerm(index, 'currency', value)} />
                                    <Field label="Unit of measure" value={term.uom} onChange={(value) => updateTerm(index, 'uom', value)} />
                                    <Field label="Minimum quantity" type="number" step="0.01" value={term.qty_min} onChange={(value) => updateTerm(index, 'qty_min', value)} />
                                    <Field label="Maximum quantity" type="number" step="0.01" value={term.qty_max} onChange={(value) => updateTerm(index, 'qty_max', value)} />
                                    <Field label="Discount (%)" type="number" step="0.01" value={term.discount_pct} onChange={(value) => updateTerm(index, 'discount_pct', value)} />
                                    <Field label="Effective date" type="date" value={term.effective_from} required onChange={(value) => updateTerm(index, 'effective_from', value)} />
                                    <Field label="Expiration date" type="date" value={term.effective_to} onChange={(value) => updateTerm(index, 'effective_to', value)} />
                                    <Field label="Escalation cap (%)" type="number" step="0.01" value={term.escalation_pct} onChange={(value) => updateTerm(index, 'escalation_pct', value)} />
                                    <Field label="Payment terms" value={term.payment_terms} onChange={(value) => updateTerm(index, 'payment_terms', value)} />
                                    <Field label="Freight terms" value={term.freight_terms} onChange={(value) => updateTerm(index, 'freight_terms', value)} />
                                    <Field label="Tax terms" value={term.tax_rule} onChange={(value) => updateTerm(index, 'tax_rule', value)} />
                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', gridColumn: '1 / -1' }}>
                                        <span style={{ color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 600 }}>Description</span>
                                        <textarea value={term.description} onChange={(event) => updateTerm(index, 'description', event.target.value)} rows={2} style={{ ...inputStyle, resize: 'vertical' }} />
                                    </label>
                                </div>
                                {form.terms.length > 1 && (
                                    <button type="button" onClick={() => setForm((current) => ({ ...current, terms: current.terms.filter((_, termIndex) => termIndex !== index) }))} style={{ marginTop: '10px', padding: 0, border: 0, background: 'transparent', color: 'var(--color-danger)', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}>
                                        Remove pricing line
                                    </button>
                                )}
                            </fieldset>
                        ))}
                    </div>

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
