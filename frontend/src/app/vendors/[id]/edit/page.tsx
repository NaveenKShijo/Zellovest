'use client';

import React, { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Vendor } from '@/types';
import { useApi } from '@/lib/api';
import { VendorForm } from '@/components/vendors/VendorForm';

export default function VendorEditPage() {
  const params = useParams();
  const router = useRouter();
  const vendorId = params.id as string;
  const api = useApi();

  const [vendor, setVendor] = useState<Vendor | null>(null);
  const [loading, setLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.vendors
      .get(vendorId)
      .then((data) => {
        if (!active) return;
        setVendor(data);
      })
      .catch((err) => {
        if (!active) return;
        console.error('Failed to load vendor:', err);
        setError(err instanceof Error ? err.message : 'Vendor not found');
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [vendorId, api]);

  const handleSubmit = async (data: Partial<Vendor>) => {
    setIsSubmitting(true);
    setError(null);
    try {
      await api.vendors.update(vendorId, data);
      router.push(`/vendors/${vendorId}`);
      router.refresh();
    } catch (caught) {
      console.error('Failed to update vendor:', caught);
      setError(caught instanceof Error ? caught.message : 'Failed to update vendor in database.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        <div style={{ height: '40px', background: 'var(--bg-surface-tint)', borderRadius: 'var(--radius-md)', animation: 'pulse 1.5s ease-in-out infinite', width: '300px' }} />
        <div style={{ height: '300px', background: 'var(--bg-surface-tint)', borderRadius: 'var(--radius-lg)', animation: 'pulse 1.5s ease-in-out infinite' }} />
      </div>
    );
  }

  if (!vendor) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-muted)' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px' }}>
          {error || 'Vendor not found'}
        </h2>
        <button
          onClick={() => router.push('/vendors')}
          style={{
            marginTop: '16px',
            padding: '8px 16px',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'var(--color-brand)',
            color: '#FFFFFF',
            fontWeight: 600,
            cursor: 'pointer',
            border: 'none',
          }}
        >
          Back to Vendors
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Edit Vendor
        </h1>
      </div>
      {error && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#EF4444',
            fontSize: '13px',
          }}
        >
          {error}
        </div>
      )}
      <VendorForm
        initialData={vendor}
        isEditing={true}
        onSubmit={handleSubmit}
        onCancel={() => router.push(`/vendors/${vendorId}`)}
        isSubmitting={isSubmitting}
      />
    </div>
  );
}
