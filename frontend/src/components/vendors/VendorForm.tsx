'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Vendor, VendorCategory, VendorStatus } from '@/types';

const CATEGORY_OPTIONS: VendorCategory[] = [
  'CRM & Sales',
  'Design & Prototyping',
  'Cloud Infrastructure',
  'Productivity & Messaging',
  'Development Tools',
  'HR & Finance',
  'Marketing & Analytics',
  'Security & Compliance',
  'Other',
];

const PAYMENT_TERMS_OPTIONS = [
  { value: 'net_30', label: 'Net 30' },
  { value: 'net_45', label: 'Net 45' },
  { value: 'net_60', label: 'Net 60' },
  { value: 'custom', label: 'Custom' },
];

interface VendorFormProps {
  initialData?: Partial<Vendor>;
  isEditing?: boolean;
  onSubmit: (data: Partial<Vendor>) => Promise<void>;
  onCancel: () => void;
  isSubmitting?: boolean;
}

export function VendorForm({ initialData, isEditing, onSubmit, onCancel, isSubmitting }: VendorFormProps) {
  const router = useRouter();
  const [formData, setFormData] = useState<Partial<Vendor>>({
    canonicalName: '',
    domain: '',
    primaryContact: { name: '', email: '', phone: '' },
    paymentTerms: 'net_30',
    customPaymentTerms: '',
    categories: [],
    annualSpend: 0,
    currency: 'USD',
    status: 'compliant',
    ...initialData,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  const validate = () => {
    const newErrors: Record<string, string> = {};
    if (!formData.canonicalName?.trim()) newErrors.canonicalName = 'Canonical name is required';
    if (formData.primaryContact?.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.primaryContact.email)) {
      newErrors.primaryContactEmail = 'Invalid email address';
    }
    if (formData.paymentTerms === 'custom' && !formData.customPaymentTerms?.trim()) {
      newErrors.customPaymentTerms = 'Custom payment terms required';
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleChange = (field: string, value: unknown) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    if (touched[field]) {
      setErrors((prev) => ({ ...prev, [field]: '' }));
    }
  };

  const handleBlur = (field: string) => {
    setTouched((prev) => ({ ...prev, [field]: true }));
    validate();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    const submitData = { ...formData };
    if (submitData.paymentTerms !== 'custom') {
      delete submitData.customPaymentTerms;
    }
    if (!submitData.primaryContact?.name && !submitData.primaryContact?.email) {
      delete submitData.primaryContact;
    }

    await onSubmit(submitData);
  };

  const handleCategoryToggle = (category: VendorCategory) => {
    setFormData((prev) => ({
      ...prev,
      categories: prev.categories?.includes(category)
        ? prev.categories.filter((c) => c !== category)
        : [...(prev.categories || []), category],
    }));
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: '16px', borderBottom: '1px solid var(--border-subtle)' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)' }}>
          {isEditing ? 'Edit Vendor' : 'Add New Vendor'}
        </h2>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button
            type="button"
            onClick={onCancel}
            style={{
              padding: '10px 20px',
              borderRadius: 'var(--radius-md)',
              fontSize: '13px',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              backgroundColor: 'var(--bg-app)',
              border: '1px solid var(--border-subtle)',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-brand)')}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSubmitting}
            style={{
              padding: '10px 20px',
              borderRadius: 'var(--radius-md)',
              fontSize: '13px',
              fontWeight: 600,
              color: '#FFFFFF',
              backgroundColor: 'var(--color-brand)',
            }}
            onMouseEnter={(e) => { if (!isSubmitting) e.currentTarget.style.backgroundColor = 'var(--color-brand-hover)'; }}
            onMouseLeave={(e) => { if (!isSubmitting) e.currentTarget.style.backgroundColor = 'var(--color-brand)'; }}
          >
            {isSubmitting ? 'Saving...' : isEditing ? 'Save Changes' : 'Create Vendor'}
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' }}>
        {/* Basic Information */}
        <fieldset style={{ border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <legend style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', padding: '0 8px' }}>
            Basic Information
          </legend>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Canonical Vendor Name <span style={{ color: 'var(--color-danger)' }}>*</span>
            </label>
            <input
              type="text"
              value={formData.canonicalName || ''}
              onChange={(e) => handleChange('canonicalName', e.target.value)}
              onBlur={() => handleBlur('canonicalName')}
              placeholder="e.g., Salesforce, Inc."
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 'var(--radius-sm)',
                border: `1px solid ${errors.canonicalName && touched.canonicalName ? 'var(--color-danger)' : 'var(--border-subtle)'}`,
                backgroundColor: 'var(--bg-app)',
                fontSize: '13px',
                color: 'var(--text-primary)',
                outline: 'none',
              }}
            />
            {errors.canonicalName && touched.canonicalName && (
              <p style={{ fontSize: '11px', color: 'var(--color-danger)', marginTop: '4px' }}>{errors.canonicalName}</p>
            )}
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Domain (optional)
            </label>
            <input
              type="text"
              value={formData.domain || ''}
              onChange={(e) => handleChange('domain', e.target.value)}
              placeholder="e.g., salesforce.com"
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                backgroundColor: 'var(--bg-app)',
                fontSize: '13px',
                color: 'var(--text-primary)',
                outline: 'none',
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Categories
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {CATEGORY_OPTIONS.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => handleCategoryToggle(cat)}
                  style={{
                    fontSize: '11px',
                    fontWeight: 600,
                    padding: '6px 12px',
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: formData.categories?.includes(cat) ? 'var(--color-brand-subtle)' : 'var(--bg-app)',
                    color: formData.categories?.includes(cat) ? 'var(--color-brand)' : 'var(--text-secondary)',
                    border: formData.categories?.includes(cat) ? '1px solid var(--color-brand)' : '1px solid var(--border-subtle)',
                    transition: 'all var(--transition-fast)',
                  }}
                >
                  {cat}
                </button>
              ))}
            </div>
            {formData.categories?.length === 0 && (
              <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>Select at least one category</p>
            )}
          </div>
        </fieldset>

        {/* Contact & Payment Terms */}
        <fieldset style={{ border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-lg)', padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <legend style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', padding: '0 8px' }}>
            Contact & Payment Terms
          </legend>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
                Contact Name
              </label>
              <input
                type="text"
                value={formData.primaryContact?.name || ''}
                onChange={(e) => handleChange('primaryContact', { ...formData.primaryContact, name: e.target.value })}
                placeholder="John Doe"
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-subtle)',
                  backgroundColor: 'var(--bg-app)',
                  fontSize: '13px',
                  color: 'var(--text-primary)',
                  outline: 'none',
                }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
                Contact Email
              </label>
              <input
                type="email"
                value={formData.primaryContact?.email || ''}
                onChange={(e) => handleChange('primaryContact', { ...formData.primaryContact, email: e.target.value })}
                onBlur={() => handleBlur('primaryContactEmail')}
                placeholder="john@vendor.com"
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  border: `1px solid ${errors.primaryContactEmail && touched.primaryContactEmail ? 'var(--color-danger)' : 'var(--border-subtle)'}`,
                  backgroundColor: 'var(--bg-app)',
                  fontSize: '13px',
                  color: 'var(--text-primary)',
                  outline: 'none',
                }}
              />
              {errors.primaryContactEmail && touched.primaryContactEmail && (
                <p style={{ fontSize: '11px', color: 'var(--color-danger)', marginTop: '4px' }}>{errors.primaryContactEmail}</p>
              )}
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Contact Phone
            </label>
            <input
              type="tel"
              value={formData.primaryContact?.phone || ''}
              onChange={(e) => handleChange('primaryContact', { ...formData.primaryContact, phone: e.target.value })}
              placeholder="+1 (555) 123-4567"
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                backgroundColor: 'var(--bg-app)',
                fontSize: '13px',
                color: 'var(--text-primary)',
                outline: 'none',
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Payment Terms <span style={{ color: 'var(--color-danger)' }}>*</span>
            </label>
            <select
              value={formData.paymentTerms}
              onChange={(e) => handleChange('paymentTerms', e.target.value as Vendor['paymentTerms'])}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                backgroundColor: 'var(--bg-app)',
                fontSize: '13px',
                color: 'var(--text-primary)',
                outline: 'none',
                cursor: 'pointer',
              }}
            >
              {PAYMENT_TERMS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {formData.paymentTerms === 'custom' && (
            <div>
              <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
                Custom Terms <span style={{ color: 'var(--color-danger)' }}>*</span>
              </label>
              <input
                type="text"
                value={formData.customPaymentTerms || ''}
                onChange={(e) => handleChange('customPaymentTerms', e.target.value)}
                onBlur={() => handleBlur('customPaymentTerms')}
                placeholder="e.g., Net 30 with 2% early payment discount"
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  border: `1px solid ${errors.customPaymentTerms && touched.customPaymentTerms ? 'var(--color-danger)' : 'var(--border-subtle)'}`,
                  backgroundColor: 'var(--bg-app)',
                  fontSize: '13px',
                  color: 'var(--text-primary)',
                  outline: 'none',
                }}
              />
              {errors.customPaymentTerms && touched.customPaymentTerms && (
                <p style={{ fontSize: '11px', color: 'var(--color-danger)', marginTop: '4px' }}>{errors.customPaymentTerms}</p>
              )}
            </div>
          )}
        </fieldset>
      </div>

      {!isEditing && (
        <div style={{ padding: '16px', backgroundColor: 'var(--bg-surface-tint)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-tint)' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-brand)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: '2px' }}>
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="16" x2="12" y2="12" />
              <line x1="12" y1="8" x2="12.01" y2="8" />
            </svg>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              <strong>Note:</strong> After creating the vendor, you can upload contracts, invoices, and other documents from the Vendor 360 page. Annual spend and contract counts will be computed automatically from uploaded documents and linked transactions.
            </div>
          </div>
        </div>
      )}
    </form>
  );
}