'use client';

import React from 'react';
import { UploadProvider, useUpload } from '@/components/upload/UploadProvider';
import { DropZone } from '@/components/upload/DropZone';
import { UploadQueue } from '@/components/upload/UploadQueue';
import { useApi } from '@/lib/api';
import { DocumentType } from '@/types';

// Backend allows `policy`; the UI type calls it `vendor_policy`.
const toBackendDocType = (t: DocumentType): string =>
  t === 'vendor_policy' ? 'policy' : t;

function UploadPageContent() {
  const { files, addFile, removeFile, retryFile, clearCompleted, updateFileStatus } = useUpload();
  const api = useApi();
  const [documentType, setDocumentType] = useState<DocumentType>('contract');
  const [isUploading, setIsUploading] = useState(false);

  const handleFilesSelect = (newFiles: File[], type: DocumentType) => {
    newFiles.forEach(file => {
      addFile(file, type);
    });
  };

  // Real three-step flow per file: init lease → PUT bytes to the
  // signed URL → complete (verify + enqueue worker). Retry re-queues.
  const processQueue = async () => {
    const queuedFiles = files.filter(f => f.status === 'queued');
    if (queuedFiles.length === 0 || isUploading) return;

    setIsUploading(true);

    for (const item of queuedFiles) {
      try {
        // 1. Mint the signed-URL lease (metadata only, no bytes).
        updateFileStatus(item.id, 'uploading', 0);
        const lease = await api.uploads.init({
          filename: item.name,
          mime_type: item.type || 'application/octet-stream',
          size_bytes: item.size,
          document_type: toBackendDocType(item.documentType),
          vendor_id: item.vendorId ?? null,
        });

        // 2. PUT bytes directly to GCS (pinned content type).
        await api.uploads.putBytes(
          lease.signed_url,
          item.file,
          item.type,
          (progress) => updateFileStatus(item.id, 'uploading', progress)
        );

        // 3. Complete: backend verifies bytes + enqueues extraction.
        updateFileStatus(item.id, 'processing', 100);
        const done = await api.uploads.complete(lease.upload_id);
        updateFileStatus(item.id, 'completed', 100, undefined, done.upload_id);
      } catch (err) {
        updateFileStatus(
          item.id,
          'error',
          undefined,
          err instanceof Error ? err.message : 'Upload failed'
        );
      }
    }

    setIsUploading(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Document Upload
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
          Upload contracts, invoices, purchase orders, and other procurement documents for AI-powered extraction.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '20px' }}>
        <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', padding: '24px' }}>
          <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '20px' }}>
            Drop Files Here
          </h2>
          <DropZone
            onFilesSelect={handleFilesSelect}
            documentType={documentType}
            setDocumentType={setDocumentType}
            disabled={isUploading}
            maxFiles={10}
            maxSizeMB={50}
          />
        </div>

        <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', overflow: 'hidden' }}>
          <UploadQueue
            files={files}
            onRemove={removeFile}
            onRetry={retryFile}
            onClearCompleted={clearCompleted}
            isProcessing={isUploading}
          />

          {files.some(f => f.status === 'queued') && (
            <div style={{ padding: '16px 24px', borderTop: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={processQueue}
                disabled={isUploading}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '12px 24px',
                  borderRadius: 'var(--radius-md)',
                  backgroundColor: isUploading ? 'var(--border-subtle)' : 'var(--color-brand)',
                  color: '#FFFFFF',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: isUploading ? 'not-allowed' : 'pointer',
                }}
              >
                {isUploading ? (
                  <>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animation: 'spin 1s linear infinite' }}>
                      <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
                      <path d="M12 2a10 10 0 0 1 10 10" strokeOpacity="1" />
                    </svg>
                    Processing...
                  </>
                ) : (
                  <>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12h14" />
                      <path d="M12 5l7 7-7 7" />
                    </svg>
                    Process Queue ({files.filter(f => f.status === 'queued').length} files)
                  </>
                )}
              </button>
            </div>
          )}

          <style jsx>{`
            @keyframes spin {
              from { transform: rotate(0deg); }
              to { transform: rotate(360deg); }
            }
          `}</style>
        </div>
      </div>

      <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', padding: '24px' }}>
        <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '16px' }}>
          Supported Formats & Limits
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
          <div style={{ padding: '16px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--color-brand)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              <strong style={{ color: 'var(--text-primary)' }}>PDF Documents</strong>
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              Contracts, invoices, purchase orders, amendments, vendor policies. Text-based and scanned PDFs supported.
            </p>
          </div>
          <div style={{ padding: '16px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--color-brand)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <polyline points="3 9 21 9 9 21" />
              </svg>
              <strong style={{ color: 'var(--text-primary)' }}>TIFF Images</strong>
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              Scanned documents, multi-page TIFFs. OCR and document AI extraction applied automatically.
            </p>
          </div>
          <div style={{ padding: '16px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--color-brand)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <strong style={{ color: 'var(--text-primary)' }}>File Limits</strong>
            </div>
            <ul style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.8, paddingLeft: '20px' }}>
              <li>Max 50MB per file</li>
              <li>Max 10 files per batch</li>
              <li>Auto-classification available</li>
            </ul>
          </div>
          <div style={{ padding: '16px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--color-brand)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
              <strong style={{ color: 'var(--text-primary)' }}>Extraction Pipeline</strong>
            </div>
            <ul style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.8, paddingLeft: '20px' }}>
              <li>OCR + Layout analysis</li>
              <li>Table & form extraction</li>
              <li>Confidence scoring</li>
              <li>Provenance tracking</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

import { useState } from 'react';

export default function UploadPage() {
  return (
    <UploadProvider>
      <UploadPageContent />
    </UploadProvider>
  );
}