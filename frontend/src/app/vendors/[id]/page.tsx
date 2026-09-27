'use client';

import React, { useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { Vendor, Contract, Invoice, CardTransaction, Document } from '@/types';
import { VendorHeader } from '@/components/vendors/VendorHeader';
import { TabNavigation, createVendorTabs, TabConfig } from '@/components/vendors/TabNavigation';
import { ContractTable } from '@/components/vendors/ContractTable';
import { InvoiceTable } from '@/components/vendors/InvoiceTable';
import { TransactionTable } from '@/components/vendors/TransactionTable';
import { DocumentList } from '@/components/vendors/DocumentList';

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
  {
    id: 'ven_002',
    canonicalName: 'Figma',
    domain: 'figma.com',
    primaryContact: { name: 'Alex Chen', email: 'alex.chen@figma.com' },
    paymentTerms: 'net_30',
    categories: ['Design & Prototyping'],
    annualSpend: 45000,
    currency: 'USD',
    status: 'compliant',
    contractCount: 1,
    invoiceCount: 4,
    transactionCount: 8,
    createdAt: '2024-03-22T09:15:00Z',
    updatedAt: '2025-07-10T11:20:00Z',
  },
  {
    id: 'ven_003',
    canonicalName: 'Datadog',
    domain: 'datadoghq.com',
    primaryContact: { name: 'Maria Rodriguez', email: 'maria.rodriguez@datadoghq.com' },
    paymentTerms: 'net_60',
    categories: ['Cloud Infrastructure'],
    annualSpend: 92400,
    currency: 'USD',
    status: 'variance_flagged',
    contractCount: 2,
    invoiceCount: 8,
    transactionCount: 23,
    createdAt: '2024-02-10T14:00:00Z',
    updatedAt: '2025-09-01T16:45:00Z',
  },
];

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

const MOCK_DOCUMENTS: Document[] = [
  {
    id: 'doc_001',
    vendorId: 'ven_001',
    documentType: 'contract',
    fileName: 'Salesforce_MSA_2024.pdf',
    fileSize: 2457600,
    mimeType: 'application/pdf',
    pageCount: 24,
    extractionStatus: 'completed',
    extractionConfidence: 0.94,
    storageUrl: '#',
    uploadedBy: 'Sarah Chen',
    uploadedAt: '2025-01-15T10:30:00Z',
  },
  {
    id: 'doc_002',
    vendorId: 'ven_001',
    documentType: 'amendment',
    fileName: 'Salesforce_Amendment_1.pdf',
    fileSize: 512000,
    mimeType: 'application/pdf',
    pageCount: 6,
    extractionStatus: 'completed',
    extractionConfidence: 0.91,
    storageUrl: '#',
    uploadedBy: 'Sarah Chen',
    uploadedAt: '2025-01-15T11:00:00Z',
  },
  {
    id: 'doc_003',
    vendorId: 'ven_001',
    documentType: 'invoice',
    fileName: 'INV-2025-045.pdf',
    fileSize: 384000,
    mimeType: 'application/pdf',
    pageCount: 2,
    extractionStatus: 'completed',
    extractionConfidence: 0.97,
    storageUrl: '#',
    uploadedBy: 'AP Team',
    uploadedAt: '2025-08-15T14:00:00Z',
  },
];

export default function VendorDetailPage() {
  const params = useParams();
  const vendorId = params.id as string;
  const [vendor] = useState<Vendor | null>(() => MOCK_VENDORS.find((v) => v.id === vendorId) || null);
  const [contracts] = useState<Contract[]>(() => MOCK_CONTRACTS.filter((c) => c.vendorId === vendorId));
  const [invoices] = useState<Invoice[]>(() => MOCK_INVOICES.filter((i) => i.vendorId === vendorId));
  const [transactions] = useState<CardTransaction[]>(() => MOCK_TRANSACTIONS.filter((t) => t.vendorId === vendorId));
  const [documents] = useState<Document[]>(() => MOCK_DOCUMENTS.filter((d) => d.vendorId === vendorId));
  const [isLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'contracts' | 'invoices' | 'transactions' | 'documents'>('overview');

  if (isLoading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        <div style={{ height: '40px', background: 'var(--bg-surface-tint)', borderRadius: 'var(--radius-md)', animation: 'pulse 1.5s ease-in-out infinite', width: '300px' }} />
        <div style={{ height: '200px', background: 'var(--bg-surface-tint)', borderRadius: 'var(--radius-lg)', animation: 'pulse 1.5s ease-in-out infinite' }} />
      </div>
    );
  }

  if (!vendor) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: '48px', marginBottom: '16px' }}>🔍</div>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '8px' }}>Vendor not found</h2>
        <p style={{ fontSize: '13px' }}>The vendor you&apos;re looking for doesn&apos;t exist or has been removed.</p>
        <Link href="/vendors" style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', marginTop: '16px', padding: '10px 16px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--color-brand)', color: '#FFFFFF', fontSize: '13px', fontWeight: 600 }}>
          &larr; Back to Vendors
        </Link>
      </div>
    );
  }

  const tabs = createVendorTabs(vendorId, {
    contracts: contracts.length,
    invoices: invoices.length,
    transactions: transactions.length,
    documents: documents.length,
  });

  const renderTabContent = () => {
    switch (activeTab) {
      case 'overview':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
              <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', padding: '20px' }}>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '8px' }}>Total Contract Value</div>
                <div style={{ fontSize: '24px', fontWeight: 800, color: 'var(--color-brand)' }}>
                  ${contracts.reduce((sum, c) => sum + (c.unitPrice * (c.quantity || 1)), 0).toLocaleString()}
                </div>
              </div>
              <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', padding: '20px' }}>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '8px' }}>Pending Invoices</div>
                <div style={{ fontSize: '24px', fontWeight: 800, color: 'var(--color-warning)' }}>
                  ${invoices.filter(i => i.status === 'pending' || i.status === 'approved').reduce((sum, i) => sum + i.amount, 0).toLocaleString()}
                </div>
              </div>
              <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', padding: '20px' }}>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '8px' }}>YTD Card Spend</div>
                <div style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)' }}>
                  ${transactions.reduce((sum, t) => sum + t.amount, 0).toLocaleString()}
                </div>
              </div>
              <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', padding: '20px' }}>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '8px' }}>Documents</div>
                <div style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-primary)' }}>
                  {documents.length}
                </div>
              </div>
            </div>

            <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', padding: '24px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '16px' }}>Quick Actions</h3>
              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                <button onClick={() => setActiveTab('contracts')} style={{ padding: '10px 16px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-surface-tint)', color: 'var(--color-brand)', fontSize: '13px', fontWeight: 600, border: 'none', cursor: 'pointer' }}>View All Contracts</button>
                <button onClick={() => setActiveTab('invoices')} style={{ padding: '10px 16px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-surface-tint)', color: 'var(--color-brand)', fontSize: '13px', fontWeight: 600, border: 'none', cursor: 'pointer' }}>View All Invoices</button>
                <button onClick={() => setActiveTab('documents')} style={{ padding: '10px 16px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-surface-tint)', color: 'var(--color-brand)', fontSize: '13px', fontWeight: 600, border: 'none', cursor: 'pointer' }}>Manage Documents</button>
              </div>
            </div>
          </div>
        );
      case 'contracts':
        return <ContractTable contracts={contracts} isLoading={false} />;
      case 'invoices':
        return <InvoiceTable invoices={invoices} isLoading={false} />;
      case 'transactions':
        return <TransactionTable transactions={transactions} isLoading={false} />;
      case 'documents':
        return <DocumentList documents={documents} isLoading={false} />;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <VendorHeader
        vendor={vendor}
        onEdit={() => {}}
        onUploadDocument={() => setActiveTab('documents')}
      />

      <TabNavigation tabs={tabs} vendorId={vendorId} activeTab={activeTab} onTabChange={setActiveTab as (tabKey: TabConfig['key']) => void} />

      <div style={{ animation: 'fadeIn var(--transition-normal) ease-out' }}>
        {renderTabContent()}
      </div>

      <style jsx>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}