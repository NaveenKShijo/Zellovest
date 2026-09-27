'use client';

import React from 'react';
import { useParams } from 'next/navigation';
import { CardTransaction } from '@/types';
import { TransactionTable } from '@/components/vendors/TransactionTable';

const MOCK_TRANSACTIONS: CardTransaction[] = [
  {
    id: 'txn_001',
    vendorId: 'ven_001',
    merchantName: 'SALESFORCE.COM',
    amount: 21000,
    currency: 'USD',
    transactionDate: '2025-08-20',
    cardLast4: '4242',
    employeeName: 'John Smith',
    department: 'Sales',
    category: 'saas_subscription',
    isRecurring: true,
    recurrenceInterval: 30,
    confidenceScore: 0.98,
    matchedVendorId: 'ven_001',
    createdAt: '2025-08-20T10:00:00Z',
  },
  {
    id: 'txn_002',
    vendorId: 'ven_001',
    merchantName: 'SALESFORCE.COM',
    amount: 21000,
    currency: 'USD',
    transactionDate: '2025-07-20',
    cardLast4: '4242',
    employeeName: 'John Smith',
    department: 'Sales',
    category: 'saas_subscription',
    isRecurring: true,
    recurrenceInterval: 30,
    confidenceScore: 0.98,
    matchedVendorId: 'ven_001',
    createdAt: '2025-07-20T10:00:00Z',
  },
];

export default function VendorTransactionsPage() {
  const params = useParams();
  const vendorId = params.id as string;

  const transactions = MOCK_TRANSACTIONS.filter(t => t.vendorId === vendorId);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)' }}>Card Transactions ({transactions.length})</h2>
      </div>
      <TransactionTable transactions={transactions} />
    </div>
  );
}