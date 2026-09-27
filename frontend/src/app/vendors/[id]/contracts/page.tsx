'use client';

import React from 'react';
import { useParams } from 'next/navigation';
import { Contract } from '@/types';
import { ContractTable } from '@/components/vendors/ContractTable';

const MOCK_CONTRACTS: Contract[] = [
  {
    id: 'ctr_001',
    vendorId: 'ven_001',
    product: 'Salesforce Enterprise Edition',
    unitPrice: 150,
    currency: 'USD',
    unitOfMeasurement: 'per_user',
    quantity: 140,
    effectiveFrom: '2024-01-01',
    effectiveTo: '2026-12-31',
    version: 2,
    amendmentOfId: 'ctr_001_v1',
    status: 'active',
    paymentTerms: 'Net 45',
    priceEscalation: 5,
    renewalDate: '2026-12-31',
    autoRenewal: true,
    noticePeriodDays: 60,
    pdfUrl: '#',
    createdAt: '2024-01-15T10:00:00Z',
    updatedAt: '2025-01-15T10:00:00Z',
  },
  {
    id: 'ctr_001_v1',
    vendorId: 'ven_001',
    product: 'Salesforce Enterprise Edition',
    unitPrice: 140,
    currency: 'USD',
    unitOfMeasurement: 'per_user',
    quantity: 120,
    effectiveFrom: '2023-01-01',
    effectiveTo: '2023-12-31',
    version: 1,
    status: 'superseded',
    pdfUrl: '#',
    createdAt: '2023-01-15T10:00:00Z',
    updatedAt: '2023-01-15T10:00:00Z',
  },
  {
    id: 'ctr_002',
    vendorId: 'ven_001',
    product: 'Salesforce Marketing Cloud',
    unitPrice: 2500,
    currency: 'USD',
    unitOfMeasurement: 'per_month',
    quantity: 1,
    effectiveFrom: '2024-06-01',
    effectiveTo: '2026-05-31',
    version: 1,
    status: 'active',
    pdfUrl: '#',
    createdAt: '2024-06-01T10:00:00Z',
    updatedAt: '2024-06-01T10:00:00Z',
  },
];

export default function VendorContractsPage() {
  const params = useParams();
  const vendorId = params.id as string;

  const contracts = MOCK_CONTRACTS.filter(c => c.vendorId === vendorId);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)' }}>Contracts ({contracts.length})</h2>
      </div>
      <ContractTable contracts={contracts} />
    </div>
  );
}