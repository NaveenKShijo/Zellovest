'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Vendor } from '@/types';
import { useApi } from '@/lib/api';
import { VendorForm } from '@/components/vendors/VendorForm';

export default function VendorNewPage() {
  const router = useRouter();
  const api = useApi();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (data: Partial<Vendor>) => {
    setIsSubmitting(true);
    setError(null);
    try {
      const created = await api.vendors.create(data);
      router.push(`/vendors/${created.id}`);
      router.refresh();
    } catch (caught) {
      console.error('Failed to create vendor:', caught);
      setError(caught instanceof Error ? caught.message : 'Failed to create vendor in database.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Add New Vendor
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
        isEditing={false}
        onSubmit={handleSubmit}
        onCancel={() => router.push('/vendors')}
        isSubmitting={isSubmitting}
      />
    </div>
  );
}
