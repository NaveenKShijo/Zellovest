'use client';

import React, { useState, useCallback } from 'react';
import { UploadFile, UploadStatus, DocumentType } from '@/types';

const STATUS_LABELS: Record<UploadStatus, string> = {
  queued: 'Queued',
  uploading: 'Uploading',
  processing: 'Processing',
  completed: 'Completed',
  error: 'Error',
};

const STATUS_COLORS: Record<UploadStatus, { bg: string; text: string; border: string }> = {
  queued: { bg: 'var(--bg-app)', text: 'var(--text-muted)', border: 'var(--border-subtle)' },
  uploading: { bg: 'var(--color-info-subtle)', text: 'var(--color-info)', border: 'var(--color-info-border)' },
  processing: { bg: 'var(--color-warning-subtle)', text: 'var(--color-warning)', border: 'var(--color-warning-border)' },
  completed: { bg: 'var(--color-success-subtle)', text: 'var(--color-success)', border: 'var(--color-success-border)' },
  error: { bg: 'var(--color-danger-subtle)', text: 'var(--color-danger)', border: 'var(--color-danger-border)' },
};

const DOC_TYPE_LABELS: Record<DocumentType, string> = {
  contract: 'Contract',
  invoice: 'Invoice',
  purchase_order: 'Purchase Order',
  amendment: 'Amendment',
  vendor_policy: 'Vendor Policy',
  other: 'Other',
};

interface UploadQueueProps {
  files: UploadFile[];
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
  onClearCompleted: () => void;
  isProcessing?: boolean;
}

export function UploadQueue({ files, onRemove, onRetry, onClearCompleted, isProcessing }: UploadQueueProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const pendingCount = files.filter(f => f.status !== 'completed' && f.status !== 'error').length;
  const completedCount = files.filter(f => f.status === 'completed').length;
  const errorCount = files.filter(f => f.status === 'error').length;

  if (files.length === 0) {
    return (
      <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', padding: '48px 24px', textAlign: 'center' }}>
        <div style={{ fontSize: '48px', marginBottom: '16px', opacity: 0.3 }}>📤</div>
        <p style={{ fontSize: '15px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '4px' }}>Upload queue is empty</p>
        <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Drag and drop files to get started</p>
      </div>
    );
  }

  return (
    <div style={{ backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', overflow: 'hidden' }}>
      <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
          Upload Queue ({files.length})
        </h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '12px' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-info)' }}>
            <span style={{ width: '8px', height: '8px', borderRadius: 'var(--radius-full)', backgroundColor: 'var(--color-info)' }} />
            {pendingCount} pending
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-success)' }}>
            <span style={{ width: '8px', height: '8px', borderRadius: 'var(--radius-full)', backgroundColor: 'var(--color-success)' }} />
            {completedCount} done
          </span>
          {errorCount > 0 && (
            <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-danger)' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: 'var(--radius-full)', backgroundColor: 'var(--color-danger)' }} />
              {errorCount} failed
            </span>
          )}
        </div>
        {completedCount > 0 && (
          <button
            onClick={onClearCompleted}
            disabled={isProcessing}
            style={{
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '12px',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              backgroundColor: 'var(--bg-app)',
              border: '1px solid var(--border-subtle)',
            }}
            onMouseEnter={(e) => { if (!isProcessing) e.currentTarget.style.borderColor = 'var(--color-brand)'; }}
            onMouseLeave={(e) => e.currentTarget.style.borderColor = 'var(--border-subtle)'}
          >
            Clear Completed
          </button>
        )}
      </div>

      <div style={{ maxHeight: '500px', overflowY: 'auto' }}>
        {files.map((file) => {
          const colors = STATUS_COLORS[file.status];
          const isExpanded = expandedIds.has(file.id);
          const canRetry = file.status === 'error';
          const canRemove = file.status !== 'uploading';

          return (
            <div
              key={file.id}
              style={{
                borderBottom: '1px solid var(--border-subtle)',
                backgroundColor: file.status === 'error' ? 'var(--color-danger-subtle)' : 'transparent',
                transition: 'background-color var(--transition-fast)',
              }}
            >
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'auto 1fr auto auto auto',
                  gap: '12px',
                  alignItems: 'center',
                  padding: '14px 24px',
                }}
                onClick={() => setExpandedIds(prev => {
                  const next = new Set(prev);
                  if (next.has(file.id)) next.delete(file.id);
                  else next.add(file.id);
                  return next;
                })}
              >
                <div style={{ width: '40px', height: '40px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--color-brand-subtle)', color: 'var(--color-brand)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '14px', flexShrink: 0 }}>
                  📄
                </div>

                <div style={{ minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '300px' }}>
                      {file.name}
                    </span>
                    <span style={{ fontSize: '10.5px', fontWeight: 700, padding: '2px 7px', borderRadius: 'var(--radius-full)', backgroundColor: 'var(--bg-surface-tint)', color: 'var(--color-brand)', border: '1px solid var(--border-tint)', whiteSpace: 'nowrap' }}>
                      {DOC_TYPE_LABELS[file.documentType]}
                    </span>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {formatFileSize(file.size)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: colors.text, fontWeight: 600 }}>
                      <span style={{ width: '8px', height: '8px', borderRadius: 'var(--radius-full)', backgroundColor: colors.text }} />
                      {STATUS_LABELS[file.status]}
                    </span>
                    {file.status === 'uploading' && (
                      <span style={{ fontFamily: 'monospace' }}>{file.progress}%</span>
                    )}
                    {file.status === 'completed' && file.documentId && (
                      <span style={{ fontFamily: 'monospace', color: 'var(--color-success)' }}>✓ {file.documentId.slice(0, 8)}</span>
                    )}
                    {file.error && (
                      <span style={{ color: 'var(--color-danger)' }}>Error: {file.error}</span>
                    )}
                  </div>
                </div>

                {file.status === 'uploading' || file.status === 'processing' ? (
                  <div style={{ width: '120px', height: '6px', backgroundColor: colors.border, borderRadius: 'var(--radius-full)', overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${file.status === 'uploading' ? file.progress : 50}%`,
                        height: '100%',
                        backgroundColor: colors.text,
                        borderRadius: 'var(--radius-full)',
                        transition: file.status === 'uploading' ? 'width var(--transition-fast)' : 'none',
                        animation: file.status === 'processing' ? 'pulse 1.5s ease-in-out infinite' : 'none',
                      }}
                    />
                  </div>
                ) : (
                  <div style={{ width: '120px', textAlign: 'center', color: colors.text, fontWeight: 600, fontSize: '12px' }}>
                    {file.status === 'completed' ? '✓ Done' : file.status === 'error' ? '✗ Failed' : '⏳ Waiting'}
                  </div>
                )}

                <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                  {canRetry && (
                    <button
                      onClick={(e) => { e.stopPropagation(); onRetry(file.id); }}
                      style={{
                        padding: '6px 10px',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '11px',
                        fontWeight: 600,
                        color: 'var(--color-brand)',
                        backgroundColor: 'var(--bg-surface-tint)',
                        border: '1px solid var(--border-tint)',
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--color-brand-subtle)'}
                      onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-surface-tint)'}
                    >
                      Retry
                    </button>
                  )}
                  {canRemove && (
                    <button
                      onClick={(e) => { e.stopPropagation(); onRemove(file.id); }}
                      style={{
                        padding: '6px 10px',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '11px',
                        fontWeight: 600,
                        color: 'var(--color-danger)',
                        backgroundColor: 'var(--color-danger-subtle)',
                        border: '1px solid var(--color-danger-border)',
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--color-danger)'; e.currentTarget.style.color = '#FFFFFF'; }}
                      onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'var(--color-danger-subtle)'; e.currentTarget.style.color = 'var(--color-danger)'; }}
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>

              {isExpanded && (
                <div style={{ padding: '0 24px 16px 76px', borderLeft: '2px solid var(--border-subtle)', marginLeft: '20px' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', fontSize: '12px' }}>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>File ID:</span>
                      <code style={{ display: 'block', marginTop: '2px', color: 'var(--text-secondary)', fontFamily: 'monospace', backgroundColor: 'var(--bg-app)', padding: '4px 8px', borderRadius: 'var(--radius-sm)' }}>{file.id}</code>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Status:</span>
                      <div style={{ marginTop: '2px' }}>
                        <span style={{ padding: '2px 8px', borderRadius: 'var(--radius-full)', backgroundColor: colors.bg, color: colors.text, border: `1px solid ${colors.border}`, fontWeight: 600, fontSize: '11px' }}>
                          {STATUS_LABELS[file.status]}
                        </span>
                      </div>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Type:</span>
                      <div style={{ marginTop: '2px', color: 'var(--text-secondary)' }}>{DOC_TYPE_LABELS[file.documentType]}</div>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Size:</span>
                      <div style={{ marginTop: '2px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{formatFileSize(file.size)}</div>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>MIME Type:</span>
                      <div style={{ marginTop: '2px', color: 'var(--text-secondary)', fontFamily: 'monospace', fontSize: '11px' }}>{file.type}</div>
                    </div>
                    {file.vendorId && (
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Vendor ID:</span>
                        <div style={{ marginTop: '2px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{file.vendorId}</div>
                      </div>
                    )}
                    {file.documentId && (
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Document ID:</span>
                        <div style={{ marginTop: '2px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{file.documentId}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}