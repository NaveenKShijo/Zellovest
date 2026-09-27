'use client';

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { UploadFile, DocumentType, UploadStatus } from '@/types';

interface UploadContextType {
  files: UploadFile[];
  addFile: (file: File, documentType: DocumentType, vendorId?: string) => string;
  removeFile: (id: string) => void;
  retryFile: (id: string) => void;
  clearCompleted: () => void;
  updateFileStatus: (id: string, status: UploadStatus, progress?: number, error?: string, documentId?: string) => void;
}

const UploadContext = createContext<UploadContextType | undefined>(undefined);

export function UploadProvider({ children }: { children: ReactNode }) {
  const [files, setFiles] = useState<UploadFile[]>([]);

  const addFile = useCallback((file: File, documentType: DocumentType, vendorId?: string): string => {
    const id = `upload_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    const newFile: UploadFile = {
      id,
      file,
      name: file.name,
      size: file.size,
      type: file.type,
      documentType,
      vendorId,
      status: 'queued',
      progress: 0,
      createdAt: new Date().toISOString(),
    };
    setFiles(prev => [...prev, newFile]);
    return id;
  }, []);

  const removeFile = useCallback((id: string) => {
    setFiles(prev => prev.filter(f => f.id !== id));
  }, []);

  const retryFile = useCallback((id: string) => {
    setFiles(prev => prev.map(f => f.id === id ? { ...f, status: 'queued' as UploadStatus, progress: 0, error: undefined } : f));
  }, []);

  const clearCompleted = useCallback(() => {
    setFiles(prev => prev.filter(f => f.status !== 'completed'));
  }, []);

  const updateFileStatus = useCallback((id: string, status: UploadStatus, progress?: number, error?: string, documentId?: string) => {
    setFiles(prev => prev.map(f => {
      if (f.id !== id) return f;
      return {
        ...f,
        status,
        progress: progress ?? f.progress,
        error,
        documentId: documentId ?? f.documentId,
      };
    }));
  }, []);

  return (
    <UploadContext.Provider value={{ files, addFile, removeFile, retryFile, clearCompleted, updateFileStatus }}>
      {children}
    </UploadContext.Provider>
  );
}

export function useUpload() {
  const context = useContext(UploadContext);
  if (!context) {
    throw new Error('useUpload must be used within an UploadProvider');
  }
  return context;
}