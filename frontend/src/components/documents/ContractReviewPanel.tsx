'use client';

import React, { FormEvent, useEffect, useRef, useState } from 'react';
import { ContractCandidate, ContractReviewCommitRequest, ContractReviewRecord, DocumentDetail } from '@/types';
import { useApi } from '@/lib/api';
import { ExceptionDrawer } from './ExceptionDrawer';
import { ReviewConfidenceChips } from './ReviewConfidenceChips';
import { useReviewHashRequest } from './useReviewHashRequest';

type TermForm = {
    contract_line_id: string;
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
    reviewer_notes: string;
    parent_contract_id: string;
    change_type: 'original' | 'amendment' | 'renewal' | 'price_revision';
    removed_contract_line_ids: string[];
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
        contract_line_id: '',
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

function initializeForm(
    review: ContractReviewRecord | null,
    fallbackVendor: string | null,
    structuredData: Record<string, unknown> | null,
    documentType: string,
): ReviewForm {
    const structured = record(structuredData);
    const reviewData = record(review?.data);
    const data = Object.keys(reviewData).length > 0 ? reviewData : structured;
    const startDate = dateInput(data.start_date);
    const extractedTerms = Array.isArray(data.terms) ? data.terms.map(record) : [];
    const terms = extractedTerms.length
        ? extractedTerms.map((term): TermForm => ({
            contract_line_id: text(term.contract_line_id),
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
        reviewer_notes: '',
        parent_contract_id: text(data.parent_contract_id),
        change_type: (text(data.change_type) || (documentType === 'amendment' ? 'amendment' : 'original')) as ReviewForm['change_type'],
        removed_contract_line_ids: [],
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
        reviewer_notes: form.reviewer_notes.trim() || null,
        parent_contract_id: form.parent_contract_id || null,
        change_type: form.change_type,
        removed_contract_line_ids: form.removed_contract_line_ids,
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
            contract_line_id: term.contract_line_id || null,
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
    const [form, setForm] = useState<ReviewForm>(() =>
        initializeForm(review, document.vendor_name, document.structured_data, document.document_type)
    );
    const apiRef = useRef(api);
    apiRef.current = api;
    const [candidates, setCandidates] = useState<ContractCandidate[]>([]);
    const [candidateError, setCandidateError] = useState<string | null>(null);
    const [candidateLoading, setCandidateLoading] = useState(false);
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

    const isCommercial = document.document_type === 'contract' || document.document_type === 'amendment';
    const parentSelectionRequired = review?.parent_contract_required === true;
    const selectedCandidate = candidates.find((candidate) => candidate.contract_id === form.parent_contract_id);

    useEffect(() => {
        if (!isCommercial) return;
        let active = true;
        setCandidateLoading(true);
        apiRef.current.documents.contractCandidates(document.id)
            .then((response) => { if (active) setCandidates(response.candidates); })
            .catch((caught) => { if (active) setCandidateError(caught instanceof Error ? caught.message : 'Unable to load parent contracts.'); })
            .finally(() => { if (active) setCandidateLoading(false); });
        return () => { active = false; };
    }, [document.id, isCommercial]);

    useEffect(() => {
        if (form.parent_contract_id || form.change_type === 'original') return;
        const matches = candidates.filter((candidate) =>
            candidate.contract_number.trim().toLowerCase() === form.contract_number.trim().toLowerCase()
            && candidate.vendor_name.trim().toLowerCase() === form.vendor_name.trim().toLowerCase()
        );
        if (matches.length === 1) {
            setForm((current) => ({ ...current, parent_contract_id: matches[0].contract_id }));
        }
    }, [candidates, form.parent_contract_id, form.change_type, form.contract_number, form.vendor_name]);
    if (!isCommercial) return null;

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

    // A pending pipeline review is authoritative. Documents extracted before
    // the review workflow existed have no review record but still need a
    // human when their confidence is below the 0.80 gate.
    const reviewIsOpen =
        review?.status === 'pending' ||
        (review?.status == null && document.status === 'review_needed' && document.has_artifact);

    if (!reviewIsOpen) {
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
                        No editable commercial-term review is available for this extraction; inspect the extracted fields in the preview or re-run the pipeline.
                    </p>
                </div>
            </section>
        );
    }

    const updateForm = (field: keyof Pick<ReviewForm, 'contract_number' | 'vendor_name' | 'title' | 'start_date' | 'end_date' | 'renewal_date' | 'notice_period_days' | 'auto_renew' | 'termination_clause' | 'reviewer_notes'>, value: string | boolean) => {
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
            closeDrawer();
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
                        {review?.reason
                            ?? (document.extraction_confidence !== null
                                ? `Extraction confidence is ${confidencePercent(document.extraction_confidence)} for this document.`
                                : 'Extraction confidence is unavailable for this document.')}
                    </p>
                    <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: '12px', lineHeight: 1.5 }}>
                        These terms remain provisional and are not used for invoice reconciliation until you verify and commit them.
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
                            Review & correct terms
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
                    <h3 style={{ margin: '0 0 12px', color: 'var(--text-primary)', fontSize: '13px' }}>Contract header</h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '12px' }}>
                        <Field label="Contract number" value={form.contract_number} required onChange={(value) => updateForm('contract_number', value)} />
                        <Field label="Vendor" value={form.vendor_name} required onChange={(value) => updateForm('vendor_name', value)} />
                        <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: 0 }}>
                            <span style={{ color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 600 }}>Document event</span>
                            <select
                                value={form.change_type}
                                onChange={(event) => setForm((current) => ({
                                    ...current,
                                    change_type: event.target.value as ReviewForm['change_type'],
                                    parent_contract_id: event.target.value === 'original' ? '' : current.parent_contract_id,
                                }))}
                                style={inputStyle}
                            >
                                <option value="original">Original contract</option>
                                <option value="amendment">Amendment</option>
                                <option value="renewal">Renewal</option>
                                <option value="price_revision">Price revision</option>
                            </select>
                        </label>
                        {(form.change_type !== 'original' || parentSelectionRequired) && (
                            <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: 0 }}>
                                <span style={{ color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 600 }}>Parent contract</span>
                                <select
                                    value={form.parent_contract_id}
                                    required={parentSelectionRequired}
                                    onChange={(event) => {
                                        const candidate = candidates.find((item) => item.contract_id === event.target.value);
                                        setForm((current) => ({
                                            ...current,
                                            parent_contract_id: event.target.value,
                                            contract_number: candidate?.contract_number || current.contract_number,
                                            vendor_name: candidate?.vendor_name || current.vendor_name,
                                            change_type: current.change_type === 'original' ? 'amendment' : current.change_type,
                                            removed_contract_line_ids: [],
                                        }));
                                    }}
                                    style={inputStyle}
                                >
                                    <option value="">{candidateLoading ? 'Loading contracts…' : 'Select parent contract'}</option>
                                    {candidates.map((candidate) => (
                                        <option key={candidate.contract_id} value={candidate.contract_id}>
                                            {candidate.contract_number} · {candidate.vendor_name}{candidate.latest_version_no ? ` · v${candidate.latest_version_no}` : ''}
                                        </option>
                                    ))}
                                </select>
                                {candidateError && <span role="alert" style={{ color: 'var(--color-danger)', fontSize: 11 }}>{candidateError}</span>}
                            </label>
                        )}
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

                    {selectedCandidate && selectedCandidate.terms.length > 0 && (
                        <fieldset style={{ margin: '16px 0 0', padding: 12, border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
                            <legend style={{ padding: '0 6px', color: 'var(--text-secondary)', fontSize: 12, fontWeight: 700 }}>Existing product lines in {selectedCandidate.contract_number}</legend>
                            <p style={{ margin: '0 0 8px', color: 'var(--text-muted)', fontSize: 11.5 }}>Map changed lines below. Check a line to end it as of this change’s effective date.</p>
                            <div style={{ display: 'grid', gap: 7 }}>
                                {selectedCandidate.terms.map((term) => (
                                    <label key={term.contract_line_id} style={{ display: 'flex', gap: 8, alignItems: 'center', color: 'var(--text-secondary)', fontSize: 12 }}>
                                        <input
                                            type="checkbox"
                                            checked={form.removed_contract_line_ids.includes(term.contract_line_id)}
                                            onChange={(event) => setForm((current) => ({
                                                ...current,
                                                removed_contract_line_ids: event.target.checked
                                                    ? [...current.removed_contract_line_ids, term.contract_line_id]
                                                    : current.removed_contract_line_ids.filter((id) => id !== term.contract_line_id),
                                            }))}
                                        />
                                        End {term.description || term.product_code || 'product line'} · {term.currency} {Number(term.unit_price).toFixed(2)}{term.uom ? ` / ${term.uom}` : ''}
                                    </label>
                                ))}
                            </div>
                        </fieldset>
                    )}

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
                                    {selectedCandidate && (
                                        <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: 0 }}>
                                            <span style={{ color: 'var(--text-secondary)', fontSize: '12px', fontWeight: 600 }}>Maps to existing line</span>
                                            <select value={term.contract_line_id} onChange={(event) => updateTerm(index, 'contract_line_id', event.target.value)} style={inputStyle}>
                                                <option value="">New product line / match automatically</option>
                                                {selectedCandidate.terms.map((candidateTerm) => (
                                                    <option key={candidateTerm.contract_line_id} value={candidateTerm.contract_line_id}>
                                                        {candidateTerm.description || candidateTerm.product_code || candidateTerm.contract_line_id}
                                                        {candidateTerm.qty_min !== null || candidateTerm.qty_max !== null ? ` · ${candidateTerm.qty_min ?? '−'} to ${candidateTerm.qty_max ?? '∞'}` : ''}
                                                    </option>
                                                ))}
                                            </select>
                                        </label>
                                    )}
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
