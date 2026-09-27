'use client';

import React from 'react';
import { useParams } from 'next/navigation';
import { Invoice } from '@/types';
import { InvoiceTable } from '@/components/vendors/InvoiceTable';

const MOCK_INVOICES: Invoice[] = [
  {
    id: 'inv_001',
    vendorId: 'ven_001',
    contractId: 'ctr_001',
    invoiceNumber: 'INV-2025-045',
    amount: 21000,
    currency: 'USD',
    status: 'flagged',
    variance: 16.7,
    varianceReason: 'Unit price $175 vs contracted $150',
    invoiceDate: '2025-08-15',
    dueDate: '2025-09-29',
    pdfUrl: '#',
    createdAt: '2025-08-15T10:00:00Z',
    updatedAt: '2025-08-15T10:00:00Z',
  },
  {
    id: 'inv_002',
    vendorId: 'ven_001',
    contractId: 'ctr_001',
    invoiceNumber: 'INV-2025-042',
    amount: 18000,
    currency: 'USD',
    status: 'paid',
    variance: 0,
    invoiceDate: '2025-07-15',
    dueDate: '2025-08-29',
    paidDate: '2025-08-20',
    pdfUrl: '#',
    createdAt: '2025-07-15T10:00:00Z',
    updatedAt: '2025-08-20T10:00:00Z',
  },
  {
    id: 'inv_003',
    vendorId: 'ven_001',
    contractId: 'ctr_002',
    invoiceNumber: 'INV-2025-038',
    amount: 2500,
    currency: 'USD',
    status: 'approved',
    variance: 0,
    invoiceDate: '2025-08-01',
    dueDate: '2025-09-15',
    pdfUrl: '#',
    createdAt: '2025-08-01T10:00:00Z',
    updatedAt: '2025-08-01T10:00:00Z',
  },
];

export default function VendorInvoicesPage() {
  const params = useParams();
  const vendorId = params.id as string;

  const invoices = MOCK_INVOICES.filter(i => i.vendorId === vendorId);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)' }}>Invoices ({invoices.length})</h2>
      </div>
      <InvoiceTable invoices={invoices} />
    </div>
  );
}