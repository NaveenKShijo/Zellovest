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
  };
}

export type ApiClient = ReturnType<typeof useApi>;