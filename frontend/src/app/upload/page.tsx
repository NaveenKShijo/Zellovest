'use client';

import React from 'react';
import { UploadProvider, useUpload } from '@/components/upload/UploadProvider';
import { DropZone } from '@/components/upload/DropZone';
import { UploadQueue } from '@/components/upload/UploadQueue';
import { useApi, UploadLease } from '@/lib/api';
import { DocumentType } from '@/types';

// Worker-side polling for GET /uploads/{id} after `complete` returns
// `staged`: converge the row to completed/failed instead of leaving it
// stuck at "processing" (which only means "accepted for extraction").
const POLL_INTERVAL_MS = 3000;
const POLL_MAX_ATTEMPTS = 20;

// Backend allows `policy`; the UI type calls it `vendor_policy`.
const toBackendDocType = (t: DocumentType): string =>
  t === 'vendor_policy' ? 'policy' : t;

function UploadPageContent() {
  const { files, addFile, removeFile, retryFile, clearCompleted, updateFileStatus, setUploadId } = useUpload();
  const api = useApi();
  const [documentType, setDocumentType] = useState<DocumentType>('contract');
  const [isUploading, setIsUploading] = useState(false);
  // In-flight PUTs keyed by queue row id, so Cancel can abort the bytes.
  const xhrRefs = useRef(new Map<string, XMLHttpRequest>());
  // Pending poll timers keyed by queue row id (cleared on cancel/unmount).
  const pollRefs = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  // Latest api client for use inside timer callbacks (avoids stale closures).
  const apiRef = useRef(api);
  useEffect(() => {
    apiRef.current = api;
  });

  const stopPolling = (rowId: string) => {
    const timer = pollRefs.current.get(rowId);
    if (timer) {
      clearTimeout(timer);
      pollRefs.current.delete(rowId);
    }
  };

  const handleFilesSelect = (newFiles: File[], type: DocumentType) => {
    newFiles.forEach(file => {
      addFile(file, type);
    });
  };

  // Poll GET /uploads/{id} until the worker reaches a terminal lease
  // status. Transient fetch failures consume an attempt; abandonment
  // (cancel/unmount/row gone) stops the chain via stopPolling.
  const pollLeaseStatus = (rowId: string, uploadId: string, attemptsLeft: number) => {
    if (attemptsLeft <= 0) return;
    stopPolling(rowId);
    const timer = setTimeout(async () => {
      pollRefs.current.delete(rowId);
      let lease: UploadLease | null = null;
      try {
        lease = await apiRef.current.uploads.get(uploadId);
      } catch {
        // Transient: retry while attempts remain.
      }
      if (!lease) {
        pollLeaseStatus(rowId, uploadId, attemptsLeft - 1);
        return;
      }
      if (lease.status === 'completed') {
        updateFileStatus(rowId, 'completed', 100, undefined, uploadId);
        return;
      }
      if (lease.status === 'failed') {
        updateFileStatus(rowId, 'error', undefined, lease.error || 'Extraction failed');
        return;
      }
      pollLeaseStatus(rowId, uploadId, attemptsLeft - 1);
    }, POLL_INTERVAL_MS);
    pollRefs.current.set(rowId, timer);
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

        // Track the lease so Cancel can clean up server-side.
        setUploadId(item.id, lease.upload_id);

        // 2. PUT bytes directly to GCS (pinned content type).
        await api.uploads.putBytes(
          lease.signed_url,
          item.file,
          item.type,
          (progress) => updateFileStatus(item.id, 'uploading', progress),
          (xhr) => xhrRefs.current.set(item.id, xhr)
        );
        xhrRefs.current.delete(item.id);

        // 3. Complete: backend verifies bytes + enqueues extraction.
        updateFileStatus(item.id, 'processing', 100);
        const done = await api.uploads.complete(lease.upload_id);
        // The lease is now `staged`, not extracted: poll the worker-side
        // status until terminal instead of reporting a premature done.
        pollLeaseStatus(item.id, done.upload_id, POLL_MAX_ATTEMPTS);
      } catch (err) {
        xhrRefs.current.delete(item.id);
        // An XHR abort from Cancel surfaces as a caught error; the row is
        // already gone via handleCancel, so don't resurrect it as failed.
        if (files.some(f => f.id === item.id)) {
          updateFileStatus(
            item.id,
            'error',
            undefined,
            err instanceof Error ? err.message : 'Upload failed'
          );
        }
      }
    }

    setIsUploading(false);
  };

  // Pre-complete cancel: abort the in-flight PUT (prevents any object from
  // forming mid-flight), best-effort DELETE the lease row + blob, then drop
  // the row locally. Optimistic: local removal happens even if the DELETE
  // 404s/409s; the janitor backstops anything left behind.
  const handleCancel = async (id: string) => {
    const target = files.find(f => f.id === id);
    stopPolling(id);
    const xhr = xhrRefs.current.get(id);
    if (xhr) {
      xhr.abort();
      xhrRefs.current.delete(id);
    }
    if (target?.uploadId) {
      try {
        await api.uploads.remove(target.uploadId);
      } catch {
        // Best-effort: row/blob may already be gone or beyond pending.
      }
    }
    removeFile(id);
  };

  // --- Recent uploads history (GET /uploads) ---
  const [history, setHistory] = useState<UploadLease[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyStatus, setHistoryStatus] = useState('');
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyKey, setHistoryKey] = useState(0);

  // Loading/error flags are set by the event handlers below (filter
  // change, Refresh), never synchronously inside this effect.
  useEffect(() => {
    let cancelled = false;
    apiRef.current.uploads.list(historyStatus || undefined, 1, 20).then(
      (res) => {
        if (cancelled) return;
        setHistory(res.uploads);
        setHistoryTotal(res.total);
        setHistoryLoading(false);
      },
      (err: unknown) => {
        if (cancelled) return;
        setHistoryError(err instanceof Error ? err.message : 'Failed to load uploads');
        setHistoryLoading(false);
      }
    );
    return () => { cancelled = true; };
  }, [historyStatus, historyKey]);

  // Clear pending poll timers on unmount (rows may outlive the page).
  useEffect(() => {
    const timers = pollRefs.current;
    return () => {
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
    };
  }, []);

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
            onCancel={handleCancel}
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
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
          <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
            Recent Uploads{historyTotal > 0 ? ` (${historyTotal})` : ''}
          </h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <select
              value={historyStatus}
              onChange={(e) => {
                setHistoryStatus(e.target.value);
                setHistoryLoading(true);
                setHistoryError(null);
              }}
              aria-label="Filter uploads by status"
              style={{
                padding: '6px 10px',
                borderRadius: 'var(--radius-sm)',
                fontSize: '12px',
                color: 'var(--text-secondary)',
                backgroundColor: 'var(--bg-app)',
                border: '1px solid var(--border-subtle)',
              }}
            >
              <option value="">All statuses</option>
              <option value="pending">Pending</option>
              <option value="staged">Staged</option>
              <option value="processing">Processing</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
            </select>
            <button
              onClick={() => {
                setHistoryKey((k) => k + 1);
                setHistoryLoading(true);
                setHistoryError(null);
              }}
              disabled={historyLoading}
              style={{
                padding: '6px 12px',
                borderRadius: 'var(--radius-sm)',
                fontSize: '12px',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                backgroundColor: 'var(--bg-app)',
                border: '1px solid var(--border-subtle)',
                cursor: historyLoading ? 'not-allowed' : 'pointer',
              }}
            >
              {historyLoading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>
        {historyError && (
          <p style={{ fontSize: '12px', color: 'var(--color-danger)', marginBottom: '12px' }}>
            Error: {historyError}
          </p>
        )}
        {!historyLoading && !historyError && history.length === 0 && (
          <p style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
            No uploads yet — processed files appear here with their extraction status.
          </p>
        )}
        {history.map((lease) => (
          <div
            key={lease.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '10px 0',
              borderTop: '1px solid var(--border-subtle)',
              fontSize: '12.5px',
            }}
          >
            <span style={{ fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '260px' }}>
              {lease.filename}
            </span>
            <span style={{ color: 'var(--text-muted)' }}>{lease.document_type}</span>
            <span style={{
              fontSize: '11px',
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: 'var(--radius-full)',
              backgroundColor: 'var(--bg-app)',
              color: lease.status === 'failed' ? 'var(--color-danger)' : lease.status === 'completed' ? 'var(--color-success)' : 'var(--color-info)',
              border: '1px solid var(--border-subtle)',
            }}>
              {lease.status}
            </span>
            <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: '11.5px' }}>
              {new Date(lease.created_at).toLocaleString()}
            </span>
          </div>
        ))}
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

import { useState, useRef, useEffect } from 'react';

export default function UploadPage() {
  return (
    <UploadProvider>
      <UploadPageContent />
    </UploadProvider>
  );
}