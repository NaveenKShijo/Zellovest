'use client';

import React, { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Vendor } from '@/types';
import { VendorForm } from '@/components/vendors/VendorForm';

const MOCK_VENDORS: Vendor[] = [
  {
    id: 'ven_001',
    canonicalName: 'Salesforce',
    domain: 'salesforce.com',
    primaryContact: { name: 'Sarah Mitchell', email: 'sarah.mitchell@salesforce.com', phone: '+1 (415) 901-7000' },
    paymentTerms: 'net_45',
    categories: ['CRM & Sales'],
    annualSpend: 168000,
    currency: 'USD',
    status: 'variance_flagged',
    contractCount: 3,
    invoiceCount: 12,
    transactionCount: 45,
    createdAt: '2024-01-15T10:00:00Z',
    updatedAt: '2025-08-20T14:30:00Z',
  },
];

export default function VendorEditPage() {
  const params = useParams();
  const router = useRouter();
  const vendorId = params.id as string;
  const [isSubmitting, setIsSubmitting] = useState(false);

  const vendor = MOCK_VENDORS.find(v => v.id === vendorId);

  const handleSubmit = async (data: Partial<Vendor>) => {
    setIsSubmitting(true);
    await new Promise(r => setTimeout(r, 800));
    setIsSubmitting(false);
    router.push(`/vendors/${vendorId}`);
    router.refresh();
  };

  if (!vendor) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-muted)' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px' }}>Vendor not found</h2>
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