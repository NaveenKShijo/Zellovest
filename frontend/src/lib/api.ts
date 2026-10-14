'use client';

import { useAuth } from '@/contexts/AuthContext';
import {
  Vendor,
  VendorListParams,
  VendorListResponse,
  Contract,
  Invoice,
  CardTransaction,
  Document,
  UploadFile,
  DocumentType,
} from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/api';

function getAuthHeaders(accessToken?: string): HeadersInit {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }
  return headers;
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: 'Request failed' }));
    throw new Error(error.message || `HTTP ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json();
}

export function useApi() {
  const { user } = useAuth();
  const accessToken = user?.accessToken;

  const request = async <T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> => {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers: {
        ...getAuthHeaders(accessToken),
        ...options.headers,
      },
    });
    return handleResponse<T>(response);
  };

  const upload = async <T>(
    endpoint: string,
    formData: FormData,
    onProgress?: (progress: number) => void
  ): Promise<T> => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE}${endpoint}`);
      if (accessToken) {
        xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
      }
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch {
            resolve(undefined as T);
          }
        } else {
          try {
            const error = JSON.parse(xhr.responseText);
            reject(new Error(error.message || `Upload failed: ${xhr.status}`));
          } catch {
            reject(new Error(`Upload failed: ${xhr.status}`));
          }
        }
      };
      xhr.onerror = () => reject(new Error('Network error'));
      xhr.send(formData);
    });
  };

  return {
    vendors: {
      list: (params?: VendorListParams) => {
        const searchParams = new URLSearchParams();
        if (params) {
          Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
              if (Array.isArray(value)) {
                value.forEach(v => searchParams.append(key, String(v)));
              } else {
                searchParams.set(key, String(value));
              }
            }
          });
        }
        const query = searchParams.toString();
        return request<VendorListResponse>(`/vendors${query ? `?${query}` : ''}`);
      },
      get: (id: string) => request<Vendor>(`/vendors/${id}`),
      create: (data: Partial<Vendor>) => request<Vendor>('/vendors', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
      update: (id: string, data: Partial<Vendor>) => request<Vendor>(`/vendors/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
      delete: (id: string) => request<void>(`/vendors/${id}`, { method: 'DELETE' }),
    },
    contracts: {
      listByVendor: (vendorId: string) => request<Contract[]>(`/vendors/${vendorId}/contracts`),
      get: (id: string) => request<Contract>(`/contracts/${id}`),
      create: (vendorId: string, data: Partial<Contract>) => request<Contract>(`/vendors/${vendorId}/contracts`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
      update: (id: string, data: Partial<Contract>) => request<Contract>(`/contracts/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    },
    invoices: {
      listByVendor: (vendorId: string) => request<Invoice[]>(`/vendors/${vendorId}/invoices`),
      get: (id: string) => request<Invoice>(`/invoices/${id}`),
    },
    transactions: {
      listByVendor: (vendorId: string) => request<CardTransaction[]>(`/vendors/${vendorId}/transactions`),
      listUnmanaged: () => request<CardTransaction[]>('/transactions/unmanaged'),
    },
    documents: {
      listByVendor: (vendorId: string) => request<Document[]>(`/vendors/${vendorId}/documents`),
      upload: (file: File, documentType: DocumentType, vendorId?: string) => {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('documentType', documentType);
        if (vendorId) formData.append('vendorId', vendorId);
        return upload<Document>('/documents/upload', formData);
      },
      delete: (id: string) => request<void>(`/documents/${id}`, { method: 'DELETE' }),
    },
    upload: {
      uploadFile: (file: File, documentType: DocumentType, vendorId?: string, onProgress?: (progress: number) => void) => {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('documentType', documentType);
        if (vendorId) formData.append('vendorId', vendorId);
        return upload<Document>('/documents/upload', formData, onProgress);
      },
    },
    // Direct-to-GCS manual upload leases (ingestion gateway, /api/v1).
    uploads: {
      init: (data: {
        filename: string;
        mime_type: string;
        size_bytes: number;
        document_type: string;
        vendor_id?: string | null;
      }) => fetch('/api/v1/uploads/init', {
        method: 'POST',
        headers: getAuthHeaders(accessToken),
        body: JSON.stringify({ ...data, vendor_id: data.vendor_id ?? null }),
      }).then(handleResponse<UploadInitResponse>),
      putBytes: (
        signedUrl: string,
        file: File,
        contentType: string,
        onProgress?: (progress: number) => void,
        onXhr?: (xhr: XMLHttpRequest) => void
      ) => new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('PUT', signedUrl);
        if (onXhr) onXhr(xhr);
        xhr.setRequestHeader('Content-Type', contentType || 'application/octet-stream');
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable && onProgress) {
            onProgress(Math.round((event.loaded / event.total) * 100));
          }
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) resolve();
          else reject(new Error(`GCS upload failed: ${xhr.status}`));
        };
        xhr.onerror = () => reject(new Error('Network error during GCS upload'));
        xhr.send(file);
      }),
      complete: (uploadId: string) => fetch(`/api/v1/uploads/${uploadId}/complete`, {
        method: 'POST',
        headers: getAuthHeaders(accessToken),
      }).then(handleResponse<UploadCompleteResponse>),
      get: (uploadId: string) => request<UploadLease>(`/v1/uploads/${uploadId}`),
      list: (status?: string, page = 1, pageSize = 20) => {
        const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
        if (status) params.set('status', status);
        return request<UploadLeaseList>(`/v1/uploads?${params.toString()}`);
      },
      remove: (uploadId: string) => request<void>(`/v1/uploads/${uploadId}`, { method: 'DELETE' }),
    },
  };
}

export interface UploadInitResponse {
  upload_id: string;
  gcs_key: string;
  signed_url: string;
  expires_at: string;
}

export interface UploadCompleteResponse {
  upload_id: string;
  gcs_key: string;
  status: string;
  size_actual: number;
  task_id: string | null;
}

export interface UploadLease {
  id: string;
  tenant_id: string;
  filename: string;
  document_type: string;
  status: string;
  gcs_key: string;
  size_expected: number;
  mime_type: string;
  vendor_id: string | null;
  error: string | null;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadLeaseList {
  uploads: UploadLease[];
  total: number;
  page: number;
  page_size: number;
}

export type ApiClient = ReturnType<typeof useApi>;