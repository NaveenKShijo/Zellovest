'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Vendor } from '@/types';
import { VendorForm } from '@/components/vendors/VendorForm';

export default function VendorNewPage() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (data: Partial<Vendor>) => {
    setIsSubmitting(true);
    await new Promise(r => setTimeout(r, 800));
    setIsSubmitting(false);
    // In real app, would get the new vendor ID from response
    router.push('/vendors/ven_new');
    router.refresh();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Add New Vendor
        </h1>
      </div>
      <VendorForm
        isEditing={false}
        onSubmit={handleSubmit}
        onCancel={() => router.push('/vendors')}
        isSubmitting={isSubmitting}
      />
    </div>
  );
}