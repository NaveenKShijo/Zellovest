'use client';

import React, { useState } from 'react';
import { useParams } from 'next/navigation';
import { Document, DocumentType } from '@/types';
import { DocumentList } from '@/components/vendors/DocumentList';

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

export default function VendorDocumentsPage() {
  const params = useParams();
  const vendorId = params.id as string;
  const [showUpload, setShowUpload] = useState(false);

  const documents = MOCK_DOCUMENTS.filter(d => d.vendorId === vendorId);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)' }}>Documents ({documents.length})</h2>
        <button
          onClick={() => setShowUpload(true)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 16px',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'var(--color-brand)',
            color: '#FFFFFF',
            fontSize: '13px',
            fontWeight: 600,
          }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-brand-hover)')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-brand)')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          Upload Document
        </button>
      </div>

      {showUpload && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(50, 4, 13, 0.65)', backdropFilter: 'blur(3px)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
          <div style={{ width: '100%', maxWidth: '560px', backgroundColor: '#FFFFFF', borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-lg)', overflow: 'hidden' }}>
            <div style={{ padding: '20px 24px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>Upload Document</h3>
              <button onClick={() => setShowUpload(false)} style={{ padding: '8px', borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)' }} onMouseEnter={(e) => e.currentTarget.style.color = 'var(--text-primary)'}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              </button>
            </div>
            <div style={{ padding: '24px' }}>
              <UploadModal vendorId={vendorId} onClose={() => setShowUpload(false)} />
            </div>
          </div>
        </div>
      )}

      <DocumentList documents={documents} />
    </div>
  );
}

function UploadModal({ vendorId, onClose }: { vendorId: string; onClose: () => void }) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState<DocumentType>('contract');
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (!['application/pdf', 'image/tiff', 'image/tif'].includes(file.type)) {
        setError('Only PDF and TIFF files are allowed');
        return;
      }
      if (file.size > 50 * 1024 * 1024) {
        setError('File size must be less than 50MB');
        return;
      }
      setSelectedFile(file);
      setError(null);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const file = e.dataTransfer.files[0];
    if (file) {
      const mockEvent = { target: { files: [file] } } as unknown as React.ChangeEvent<HTMLInputElement>;
      handleFileSelect(mockEvent);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setIsUploading(true);
    setProgress(0);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('documentType', documentType);
      formData.append('vendorId', vendorId);

      const response = await fetch('/api/documents/upload', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) throw new Error('Upload failed');

      // Simulate progress
      const interval = setInterval(() => {
        setProgress(p => Math.min(p + 10, 90));
      }, 200);

      setTimeout(() => {
        clearInterval(interval);
        setProgress(100);
        setIsUploading(false);
        onClose();
      }, 1000);
    } catch (err) {
      setIsUploading(false);
      setError(err instanceof Error ? err.message : 'Upload failed');
    }
  };

  return (
    <div>
      <div
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        style={{
          border: selectedFile ? '2px solid var(--color-success)' : '2px dashed var(--border-subtle)',
          borderRadius: 'var(--radius-lg)',
          padding: '40px 24px',
          textAlign: 'center',
          backgroundColor: selectedFile ? 'var(--color-success-subtle)' : 'var(--bg-app)',
          transition: 'all var(--transition-fast)',
        }}
      >
        <input
          type="file"
          id="file-upload"
          accept=".pdf,.tiff,.tif"
          onChange={handleFileSelect}
          style={{ display: 'none' }}
        />
        {selectedFile ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px', padding: '16px', backgroundColor: '#FFFFFF', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--color-success)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            <div style={{ textAlign: 'left' }}>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{selectedFile.name}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</div>
            </div>
            <button onClick={() => setSelectedFile(null)} style={{ padding: '4px', color: 'var(--text-muted)' }} onMouseEnter={(e) => e.currentTarget.style.color = 'var(--color-danger)'}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
            </button>
          </div>
        ) : (
          <div>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginBottom: '12px' }}>
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <p style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>Drag & drop a file here, or click to browse</p>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Supports PDF, TIFF (max 50MB)</p>
            <button onClick={() => document.getElementById('file-upload')?.click()} style={{ marginTop: '16px', padding: '10px 20px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--color-brand)', color: '#FFFFFF', fontSize: '13px', fontWeight: 600 }}>
              Choose File
            </button>
          </div>
        )}
      </div>

      {selectedFile && (
        <div style={{ marginTop: '20px' }}>
          <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px' }}>
            Document Type
          </label>
          <select
            value={documentType}
            onChange={(e) => setDocumentType(e.target.value as DocumentType)}
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
          >
            <option value="contract">Contract</option>
            <option value="invoice">Invoice</option>
            <option value="purchase_order">Purchase Order</option>
            <option value="amendment">Amendment</option>
            <option value="vendor_policy">Vendor Policy</option>
            <option value="other">Other</option>
          </select>
        </div>
      )}

      {error && (
        <div style={{ marginTop: '16px', padding: '12px', backgroundColor: 'var(--color-danger-subtle)', border: '1px solid var(--color-danger-border)', borderRadius: 'var(--radius-md)', color: 'var(--color-danger)', fontSize: '13px' }}>
          {error}
        </div>
      )}

      {isUploading && (
        <div style={{ marginTop: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>Uploading...</span>
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-brand)' }}>{progress}%</span>
          </div>
          <div style={{ height: '6px', backgroundColor: 'var(--border-subtle)', borderRadius: 'var(--radius-full)', overflow: 'hidden' }}>
            <div style={{ width: `${progress}%`, height: '100%', backgroundColor: 'var(--color-brand)', borderRadius: 'var(--radius-full)', transition: 'width var(--transition-fast)' }} />
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '24px', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
        <button onClick={onClose} disabled={isUploading} style={{ padding: '10px 20px', borderRadius: 'var(--radius-md)', fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
          Cancel
        </button>
        <button
          onClick={handleUpload}
          disabled={!selectedFile || isUploading}
          style={{
            padding: '10px 20px',
            borderRadius: 'var(--radius-md)',
            fontSize: '13px',
            fontWeight: 600,
            color: '#FFFFFF',
            backgroundColor: selectedFile && !isUploading ? 'var(--color-brand)' : 'var(--border-subtle)',
          }}
        >
          {isUploading ? 'Uploading...' : 'Upload Document'}
        </button>
      </div>
    </div>
  );
}