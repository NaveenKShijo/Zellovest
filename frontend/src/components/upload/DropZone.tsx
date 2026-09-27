'use client';

import React, { useCallback, useState } from 'react';
import { DocumentType } from '@/types';

interface DropZoneProps {
  onFilesSelect: (files: File[], documentType: DocumentType) => void;
  documentType: DocumentType;
  setDocumentType: (type: DocumentType) => void;
  disabled?: boolean;
  maxFiles?: number;
  maxSizeMB?: number;
}

export function DropZone({
  onFilesSelect,
  documentType,
  setDocumentType,
  disabled = false,
  maxFiles = 10,
  maxSizeMB = 50,
}: DropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const validateFiles = (files: File[]): File[] => {
    const validFiles: File[] = [];
    const errors: string[] = [];

    for (const file of files) {
      if (!['application/pdf', 'image/tiff', 'image/tif'].includes(file.type)) {
        errors.push(`${file.name}: Only PDF and TIFF files are allowed`);
        continue;
      }
      if (file.size > maxSizeMB * 1024 * 1024) {
        errors.push(`${file.name}: File size must be less than ${maxSizeMB}MB`);
        continue;
      }
      validFiles.push(file);
    }

    if (errors.length > 0) {
      setError(errors.join('; '));
    } else {
      setError(null);
    }

    return validFiles;
  };

  const handleFiles = useCallback(
    (files: FileList | File[]) => {
      const fileArray = Array.from(files);
      if (fileArray.length > maxFiles) {
        setError(`Maximum ${maxFiles} files allowed`);
        return;
      }
      const validFiles = validateFiles(fileArray);
      if (validFiles.length > 0) {
        onFilesSelect(validFiles, documentType);
      }
    },
    [onFilesSelect, documentType, maxFiles]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) setIsDragging(true);
  }, [disabled]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      if (!disabled && e.dataTransfer.files.length > 0) {
        handleFiles(e.dataTransfer.files);
      }
    },
    [disabled, handleFiles]
  );

  const handleClick = useCallback(() => {
    if (!disabled) fileInputRef.current?.click();
  }, [disabled]);

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFiles(e.target.files);
      }
      e.target.value = '';
    },
    [handleFiles]
  );

  return (
    <div>
      <input
        ref={fileInputRef}
        type="file"
        id="dropzone-file-input"
        accept=".pdf,.tiff,.tif"
        multiple
        onChange={handleFileSelect}
        disabled={disabled}
        style={{ display: 'none' }}
      />

      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        style={{
          border: isDragging
            ? '2px solid var(--color-brand)'
            : disabled
            ? '2px dashed var(--border-subtle)'
            : '2px dashed var(--border-strong)',
          borderRadius: 'var(--radius-lg)',
          padding: '40px 24px',
          textAlign: 'center',
          backgroundColor: isDragging
            ? 'var(--color-brand-subtle)'
            : disabled
            ? 'var(--bg-app)'
            : 'var(--bg-surface)',
          cursor: disabled ? 'not-allowed' : 'pointer',
          transition: 'all var(--transition-fast)',
          position: 'relative',
        }}
      >
        <svg
          width="48"
          height="48"
          viewBox="0 0 24 24"
          fill="none"
          stroke={isDragging ? 'var(--color-brand)' : 'var(--text-muted)'}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ marginBottom: '12px', transition: 'stroke var(--transition-fast)' }}
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        <p style={{ fontSize: '15px', fontWeight: 600, color: isDragging ? 'var(--color-brand)' : disabled ? 'var(--text-muted)' : 'var(--text-primary)', marginBottom: '4px' }}>
          {isDragging ? 'Drop files here...' : disabled ? 'Upload disabled' : 'Drag & drop files here, or click to browse'}
        </p>
        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          Supports PDF, TIFF (max {maxSizeMB}MB, up to {maxFiles} files)
        </p>
      </div>

      {error && (
        <div style={{ marginTop: '12px', padding: '10px 12px', backgroundColor: 'var(--color-danger-subtle)', border: '1px solid var(--color-danger-border)', borderRadius: 'var(--radius-md)', color: 'var(--color-danger)', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10" />
            <line x1="15" y1="9" x2="9" y2="15" />
            <line x1="9" y1="9" x2="15" y2="15" />
          </svg>
          {error}
        </div>
      )}

      <div style={{ marginTop: '16px' }}>
        <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px' }}>
          Document Type
        </label>
        <select
          value={documentType}
          onChange={(e) => setDocumentType(e.target.value as DocumentType)}
          disabled={disabled}
          style={{
            width: '100%',
            padding: '10px 12px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            backgroundColor: disabled ? 'var(--bg-app)' : 'var(--bg-surface)',
            fontSize: '13px',
            color: 'var(--text-primary)',
            outline: 'none',
            cursor: disabled ? 'not-allowed' : 'pointer',
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
    </div>
  );
}