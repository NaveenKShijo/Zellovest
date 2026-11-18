'use client';

import { useCallback, useMemo } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import {
  Vendor,
  VendorListParams,
  VendorListResponse,
  Contract,
  ContractCandidatesResponse,
  ContractHistory,
  VendorContractLine,
  Invoice,
  CardTransaction,
  Document,
  DocumentListParams,
  DocumentListResponse,
  DocumentDetail,
  DocumentFileResponse,
  ContractReviewCommitRequest,
  ContractReviewCommitResponse,
  InvoiceReviewCommitRequest,
  InvoiceReviewCommitResponse,
  AskAIResponse,
  RAGSearchResponse,
  APAuditKPIs,
  ReconciliationItem,
  UpcomingRenewal,
  RawUpcomingRenewalResponse,
  NegotiationBriefResponse,
  RenewalReminderRequest,
  RenewalReminderResponse,
  RenewalReminderItem,
  MaverickAlertItem,
  MaverickSpendKPIs,
} from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/api';

/**
 * Extract a human-readable message from a failed API response.
 *
 * FastAPI returns `detail` as a string for domain errors and as a list of
 * validation issues for 422s, so both shapes are flattened into one line.
 * Non-JSON bodies fall back to a generic message with the HTTP status.
 */
async function parseError(response: Response): Promise<string> {
  const requestId = response.headers.get('x-request-id');
  const includeRequestId = (message: string) =>
    response.status >= 500 && requestId
      ? `${message} (request ID: ${requestId})`
      : message;
  try {
    const error = (await response.json()) as { detail?: unknown; message?: unknown };
    if (Array.isArray(error.detail)) {
      const issues = error.detail
        .map((issue: { msg?: unknown }) => issue?.msg)
        .filter((msg): msg is string => typeof msg === 'string' && msg.length > 0);
      if (issues.length > 0) return includeRequestId(issues.join('; '));
    } else if (typeof error.detail === 'string' && error.detail) {
      return includeRequestId(error.detail);
    }
    if (typeof error.message === 'string' && error.message) {
      return includeRequestId(error.message);
    }
  } catch {
    // Non-JSON error body: fall through to the generic message.
  }
  return includeRequestId(`Request failed (HTTP ${response.status})`);
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export function useApi() {
  const { user, getValidAccessToken } = useAuth();

  /**
   * Fetch with automatic access-token refresh on 401.
   *
   * 1. Resolve a valid access token (refreshing silently if near expiry).
   * 2. Make the request.
   * 3. On 401, perform one refresh and retry exactly once — this covers
   *    the race where the token expired between the validity check and
   *    the request.
   */
  const request = useCallback(
    async <T>(endpoint: string, options: RequestInit = {}): Promise<T> => {
      const attempt = async (token: string | null): Promise<Response> => {
        const headers: HeadersInit = {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...options.headers,
        };
        return fetch(`${API_BASE}${endpoint}`, { ...options, headers });
      };

      const token = await getValidAccessToken();
      let response = await attempt(token);

      if (response.status === 401) {
        // Token expired mid-flight: refresh once and retry.
        const refreshed = await getValidAccessToken(true);
        if (refreshed && refreshed !== token) {
          response = await attempt(refreshed);
        }
      }

      return handleResponse<T>(response);
    },
    [getValidAccessToken]
  );

  const upload = useCallback(
    async <T>(
      endpoint: string,
      formData: FormData,
      onProgress?: (progress: number) => void
    ): Promise<T> => {
      return new Promise((resolve, reject) => {
        (async () => {
          const token = await getValidAccessToken();
          const xhr = new XMLHttpRequest();
          xhr.open('POST', `${API_BASE}${endpoint}`);
          if (token) {
            xhr.setRequestHeader('Authorization', `Bearer ${token}`);
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
        })().catch(reject);
      });
    },
    [getValidAccessToken]
  );

  return useMemo(
    () => ({
    askAi: {
      ask: (question: string, vendorId?: string) =>
        request<AskAIResponse>('/agentic/ask-ai', {
          method: 'POST',
          body: JSON.stringify({
            question,
            context: vendorId ? { vendor_id: vendorId } : undefined,
            stream: false,
          }),
        }),
    },
    rag: {
      search: (params: {
        query: string;
        vendor_id?: string;
        document_type?: string;
        limit?: number;
      }) =>
        request<RAGSearchResponse>('/agentic/rag/search', {
          method: 'POST',
          body: JSON.stringify(params),
        }),
    },
    negotiation: {
      upcomingRenewals: async (params?: {
        days_ahead?: number;
        badge?: string;
        auto_renew_only?: boolean;
        search?: string;
      }): Promise<UpcomingRenewal[]> => {
        const searchParams = new URLSearchParams();
        if (params) {
          if (params.days_ahead) searchParams.set('days_ahead', String(params.days_ahead));
          if (params.badge && params.badge !== 'all') searchParams.set('badge', params.badge);
          if (params.auto_renew_only) searchParams.set('auto_renew_only', 'true');
          if (params.search) searchParams.set('search', params.search);
        }
        const query = searchParams.toString();
        const raw = await request<RawUpcomingRenewalResponse[]>(
          `/agentic/negotiation/upcoming-renewals${query ? `?${query}` : ''}`
        );
        return (raw || []).map((r) => ({\
          id: r.id,
          contractId: r.contract_id,
          contractNumber: r.contract_number,
          vendorId: r.vendor_id,
          vendorName: r.vendor_name,
          productName: r.product_name,
          annualSpend: r.annual_spend,
          spendYoYPct: r.spend_yoy_pct,
          renewalDate: r.renewal_date,
          daysUntilRenewal: r.days_until_renewal,
          badge: r.badge,
          autoRenew: r.auto_renew,
          noticePeriodDays: r.notice_period_days,
          noticeDeadlineDate: r.notice_deadline_date,
          daysUntilNoticeDeadline: r.days_until_notice_deadline,
          isNoticeWindowActive: r.is_notice_window_active,
          utilizationPct: r.utilization_pct,
          assignedOwner: r.assigned_owner,
          status: r.status,
          keyLeveragePoints: r.key_leverage_points || [],
        }));
      },
      prepareBrief: (data: {
        vendor_id: string;
        contract_id?: string;
        objectives?: string[];
      }) =>
        request<NegotiationBriefResponse>('/agentic/negotiation/brief', {
          method: 'POST',
          body: JSON.stringify(data),
        }),
      createReminder: (data: RenewalReminderRequest) =>
        request<RenewalReminderResponse>('/agentic/negotiation/remind', {
          method: 'POST',
          body: JSON.stringify(data),
        }),
      listReminders: () =>
        request<RenewalReminderItem[]>('/agentic/negotiation/reminders'),
    },
    vendors: {
      list: (params?: VendorListParams) => {
        const searchParams = new URLSearchParams();
        if (params) {
          Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
              if (Array.isArray(value)) {
                value.forEach((v) => searchParams.append(key, String(v)));
              } else {
                searchParams.set(key, String(value));
              }
            }
          });
        }
        const query = searchParams.toString();
        return request<VendorListResponse>(`/v1/vendors${query ? `?${query}` : ''}`);
      },
      get: (id: string) => request<Vendor>(`/v1/vendors/${id}`),
      create: (data: Partial<Vendor>) =>
        request<Vendor>('/v1/vendors', {
          method: 'POST',
          body: JSON.stringify(data),
        }),
      update: (id: string, data: Partial<Vendor>) =>
        request<Vendor>(`/v1/vendors/${id}`, {
          method: 'PATCH',
          body: JSON.stringify(data),
        }),
      delete: (id: string) => request<void>(`/v1/vendors/${id}`, { method: 'DELETE' }),
    },
    contracts: {
      listByVendor: (vendorId: string) => request<VendorContractLine[]>(`/vendors/${vendorId}/contracts`),
      history: (contractId: string) => request<ContractHistory>(`/contracts/${contractId}/history`),
      get: (id: string) => request<Contract>(`/contracts/${id}`),
      create: (vendorId: string, data: Partial<Contract>) =>
        request<Contract>(`/vendors/${vendorId}/contracts`, {
          method: 'POST',
          body: JSON.stringify(data),
        }),
      update: (id: string, data: Partial<Contract>) =>
        request<Contract>(`/contracts/${id}`, {
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
      upload: (file: File, documentType: string, vendorId?: string) => {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('documentType', documentType);
        if (vendorId) formData.append('vendorId', vendorId);
        return upload<Document>('/documents/upload', formData);
      },
      delete: (id: string) => request<void>(`/v1/documents/${id}`, { method: 'DELETE' }),
      // Document Explorer — read-only over the ingestion pipeline (GET /api/v1/documents).
      list: (params?: DocumentListParams) => {
        const searchParams = new URLSearchParams();
        if (params) {
          Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined && value !== null && value !== '') {
              searchParams.set(key, String(value));
            }
          });
        }
        const query = searchParams.toString();
        return request<DocumentListResponse>(`/v1/documents${query ? `?${query}` : ''}`);
      },
      get: (id: string) => request<DocumentDetail>(`/v1/documents/${id}`),
      commitReview: (id: string, data: ContractReviewCommitRequest) =>
        request<ContractReviewCommitResponse>(`/v1/documents/${id}/review/commit`, {
          method: 'POST',
          body: JSON.stringify(data),
        }),
      contractCandidates: (id: string) =>
        request<ContractCandidatesResponse>(`/v1/documents/${id}/contract-candidates`),
      commitInvoiceReview: (id: string, data: InvoiceReviewCommitRequest) =>
        request<InvoiceReviewCommitResponse>(`/v1/documents/${id}/review/commit-invoice`, {
          method: 'POST',
          body: JSON.stringify(data),
        }),
      fileUrl: (id: string) => request<DocumentFileResponse>(`/v1/documents/${id}/file`),
      fileContent: async (id: string): Promise<Blob> => {
        const endpoint = `/v1/documents/${id}/content`;
        const attempt = (token: string | null) =>
          fetch(`${API_BASE}${endpoint}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          });

        let token = await getValidAccessToken();
        let response = await attempt(token);
        if (response.status === 401) {
          const refreshedToken = await getValidAccessToken(true);
          if (refreshedToken && refreshedToken !== token) {
            token = refreshedToken;
            response = await attempt(token);
          }
        }

        if (!response.ok) {
          throw new Error(await parseError(response));
        }
        return response.blob();
      },
    },
    upload: {
      uploadFile: (file: File, documentType: string, vendorId?: string, onProgress?: (progress: number) => void) => {
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
        /** Optional hint; the backend defaults to `other` and the pipeline classifies. */
        document_type?: string;
        vendor_id?: string | null;
      }) => {
        return (async () => {
          const token = await getValidAccessToken();
          const response = await fetch('/api/v1/uploads/init', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ ...data, vendor_id: data.vendor_id ?? null }),
          });
          return handleResponse<UploadInitResponse>(response);
        })();
      },
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
      complete: (uploadId: string) => {
        return (async () => {
          const token = await getValidAccessToken();
          const response = await fetch(`/api/v1/uploads/${uploadId}/complete`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
          });
          return handleResponse<UploadCompleteResponse>(response);
        })();
      },
      get: (uploadId: string) => {
        return (async () => {
          const token = await getValidAccessToken();
          const headers: HeadersInit = {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          };
          return request<UploadLease>(`/v1/uploads/${uploadId}`);
        })();
      },
      list: (status?: string, page = 1, pageSize = 20) => {
        const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
        if (status) params.set('status', status);
        return request<UploadLeaseList>(`/v1/uploads?${params.toString()}`);
      },
      remove: (uploadId: string) => {
        return (async () => {
          const token = await getValidAccessToken();
          const headers: HeadersInit = {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          };
          return request<void>(`/v1/uploads/${uploadId}`, { method: 'DELETE', headers });
        })();
      },
    },
    compliance: {
      getKpis: (tenantId?: string) => {
        const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : '';
        return request<APAuditKPIs>(`/v1/compliance/kpis${query}`);
      },
      listExceptions: (params?: {
        rule_type?: string;
        status?: string;
        severity?: string;
        search?: string;
        page?: number;
        page_size?: number;
      }) => {
        const searchParams = new URLSearchParams();
        if (params) {
          Object.entries(params).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== '') {
              searchParams.set(k, String(v));
            }
          });
        }
        const query = searchParams.toString();
        return request<{
          items: ReconciliationItem[];
          total: number;
          page: number;
          page_size: number;
        }>(`/v1/compliance/exceptions${query ? `?${query}` : ''}`);
      },
      updateStatus: (exceptionId: string, status: string) =>
        request<{ status: string; exception_id: string; new_status: string }>(
          `/v1/compliance/exceptions/${exceptionId}/status`,
          {
            method: 'PATCH',
            body: JSON.stringify({ status }),
          }
        ),
      triggerReconcile: (invoiceId: string, force = true) =>
        request<{
          tenant_id: string;
          invoice_id: string;
          status: string;
          exception_count: number;
          total_discrepancy_amount: number;
        }>(`/v1/compliance/invoices/${invoiceId}/reconcile?force=${force}`, {
          method: 'POST',
        }),
      purgeOrphans: (tenantId?: string) => {
        const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : '';
        return request<{
          status: string;
          tenant_id: string;
          purged: Record<string, number>;
        }>(`/v1/compliance/purge-orphans${query}`, {
          method: 'POST',
        });
      },
    },
    maverick: {
      getFeed: (params?: { department?: string; status?: string; min_overlap?: number; tenant_id?: string }) => {
        const queryParams = new URLSearchParams();
        queryParams.set('tenant_id', params?.tenant_id || 'default-org');
        if (params?.department && params.department !== 'all') queryParams.set('department', params.department);
        if (params?.status && params.status !== 'all') queryParams.set('status', params.status);
        if (params?.min_overlap) queryParams.set('min_overlap', String(params.min_overlap));
        const qs = queryParams.toString();
        return request<{
          alerts: MaverickAlertItem[];
          kpis: MaverickSpendKPIs;
        }>(`/v1/maverick-spend?${qs}`);
      },
      updateStatus: (alertId: string, status: string, tenantId = 'default-org') => {
        const query = `?tenant_id=${encodeURIComponent(tenantId)}`;
        return request<{ id: string; status: string; updated: boolean }>(
          `/v1/maverick-spend/${alertId}/status${query}`,
          {
            method: 'PATCH',
            body: JSON.stringify({ status }),
          }
        );
      },
      triggerDetection: (
        lookbackDays = 90,
        tenantId = 'default-org',
        options?: { gcsKey?: string; syncId?: string; source?: 'gcs' | 'db'; runInline?: boolean }
      ) =>
        request<{
          status: string;
          task_id: string;
          tenant_id: string;
          lookback_days: number;
          mode?: string;
          gcs_key?: string | null;
          sync_id?: string | null;
        }>('/v1/maverick-spend/trigger', {
          method: 'POST',
          body: JSON.stringify({
            tenant_id: tenantId,
            lookback_days: lookbackDays,
            source: options?.source ?? 'gcs',
            gcs_key: options?.gcsKey,
            sync_id: options?.syncId,
            run_inline: options?.runInline,
          }),
        }),
    },
  }), [request, upload, getValidAccessToken]);
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
