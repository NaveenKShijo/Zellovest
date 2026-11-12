'use client';

import { ContractCandidatesResponse, DocumentDetail, DocumentListResponse } from '@/types';

/** Freshness window: data fetched within 30s is considered fresh. */
const STALE_TIME_MS = 30 * 1000;

/** Maximum retention: cached items older than 5 minutes are garbage collected. */
const CACHE_TTL_MS = 5 * 60 * 1000;

interface CacheEntry<T> {
  value?: T;
  timestamp: number;
  pending?: Promise<T>;
}

const documentListCache = new Map<string, CacheEntry<DocumentListResponse>>();
const documentDetailCache = new Map<string, CacheEntry<DocumentDetail>>();
const contractCandidatesCache = new Map<string, CacheEntry<ContractCandidatesResponse>>();

const listSubscribers = new Set<() => void>();

function cacheKey(scopeId: string, resourceKey: string): string {
  return `${scopeId}:${resourceKey}`;
}

/** Subscribe to document list invalidation events across components. */
export function subscribeDocumentLists(callback: () => void): () => void {
  listSubscribers.add(callback);
  return () => {
    listSubscribers.delete(callback);
  };
}

function notifyListSubscribers(): void {
  for (const listener of listSubscribers) {
    try {
      listener();
    } catch {
      // Ignore subscriber errors
    }
  }
}

/**
 * Synchronously peek at cached document list data if present.
 * Allows components to render in 0ms on mount rather than showing a blank screen.
 */
export function peekDocumentList(
  scopeId: string,
  viewKey: string
): DocumentListResponse | null {
  const key = cacheKey(scopeId, viewKey);
  const entry = documentListCache.get(key);
  if (!entry?.value) return null;
  if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
    documentListCache.delete(key);
    return null;
  }
  return entry.value;
}

/**
 * Synchronously peek at cached document detail.
 */
export function peekDocumentDetail(
  scopeId: string,
  documentId: string
): DocumentDetail | null {
  const key = cacheKey(scopeId, documentId);
  const entry = documentDetailCache.get(key);
  if (!entry?.value) return null;
  if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
    documentDetailCache.delete(key);
    return null;
  }
  return entry.value;
}

/**
 * Read document list using Stale-While-Revalidate (SWR):
 * 1. If fresh cached data exists, returns it immediately.
 * 2. If stale cached data exists, returns it immediately AND triggers background revalidation,
 *    notifying `onRevalidate` with fresh server data when it resolves.
 * 3. If cache miss, loads from network with promise deduplication.
 */
export function readDocumentList(
  scopeId: string,
  viewKey: string,
  load: () => Promise<DocumentListResponse>,
  options?: {
    onRevalidate?: (fresh: DocumentListResponse) => void;
    force?: boolean;
  }
): Promise<DocumentListResponse> {
  const key = cacheKey(scopeId, viewKey);
  const now = Date.now();
  const existing = documentListCache.get(key);

  if (!options?.force && existing?.value && now - existing.timestamp < CACHE_TTL_MS) {
    const isFresh = now - existing.timestamp < STALE_TIME_MS;
    if (isFresh) {
      return Promise.resolve(existing.value);
    }

    // Stale data exists: serve stale immediately, revalidate in background (SWR)
    if (!existing.pending) {
      existing.pending = load()
        .then((fresh) => {
          existing.value = fresh;
          existing.timestamp = Date.now();
          existing.pending = undefined;
          options?.onRevalidate?.(fresh);
          return fresh;
        })
        .catch((error: unknown) => {
          existing.pending = undefined;
          throw error;
        });
    } else if (options?.onRevalidate) {
      existing.pending.then(options.onRevalidate).catch(() => {});
    }

    return Promise.resolve(existing.value);
  }

  if (!options?.force && existing?.pending) {
    return existing.pending;
  }

  const entry: CacheEntry<DocumentListResponse> = existing ?? { timestamp: 0 };
  const pending = load()
    .then((value) => {
      entry.value = value;
      entry.timestamp = Date.now();
      entry.pending = undefined;
      return value;
    })
    .catch((error: unknown) => {
      if (documentListCache.get(key) === entry) {
        documentListCache.delete(key);
      }
      throw error;
    });

  entry.pending = pending;
  documentListCache.set(key, entry);
  return pending;
}

/** Read one document detail record through the SWR cache. */
export function readDocumentDetail(
  scopeId: string,
  documentId: string,
  load: () => Promise<DocumentDetail>,
  options?: {
    onRevalidate?: (fresh: DocumentDetail) => void;
    force?: boolean;
  }
): Promise<DocumentDetail> {
  const key = cacheKey(scopeId, documentId);
  const now = Date.now();
  const existing = documentDetailCache.get(key);

  if (!options?.force && existing?.value && now - existing.timestamp < CACHE_TTL_MS) {
    const isFresh = now - existing.timestamp < STALE_TIME_MS;
    if (isFresh) {
      return Promise.resolve(existing.value);
    }

    if (!existing.pending) {
      existing.pending = load()
        .then((fresh) => {
          existing.value = fresh;
          existing.timestamp = Date.now();
          existing.pending = undefined;
          options?.onRevalidate?.(fresh);
          return fresh;
        })
        .catch((error: unknown) => {
          existing.pending = undefined;
          throw error;
        });
    }

    return Promise.resolve(existing.value);
  }

  if (!options?.force && existing?.pending) {
    return existing.pending;
  }

  const entry: CacheEntry<DocumentDetail> = existing ?? { timestamp: 0 };
  const pending = load()
    .then((value) => {
      entry.value = value;
      entry.timestamp = Date.now();
      entry.pending = undefined;
      return value;
    })
    .catch((error: unknown) => {
      if (documentDetailCache.get(key) === entry) {
        documentDetailCache.delete(key);
      }
      throw error;
    });

  entry.pending = pending;
  documentDetailCache.set(key, entry);
  return pending;
}

/** Read parent-contract candidates through the cache. */
export function readContractCandidates(
  scopeId: string,
  documentId: string,
  load: () => Promise<ContractCandidatesResponse>
): Promise<ContractCandidatesResponse> {
  const key = cacheKey(scopeId, documentId);
  const now = Date.now();
  const existing = contractCandidatesCache.get(key);
  if (existing?.value && now - existing.timestamp < STALE_TIME_MS) {
    return Promise.resolve(existing.value);
  }
  if (existing?.pending) return existing.pending;

  const entry: CacheEntry<ContractCandidatesResponse> = { timestamp: 0 };
  const pending = load()
    .then((value) => {
      entry.value = value;
      entry.timestamp = Date.now();
      entry.pending = undefined;
      return value;
    })
    .catch((error: unknown) => {
      if (contractCandidatesCache.get(key) === entry) {
        contractCandidatesCache.delete(key);
      }
      throw error;
    });
  entry.pending = pending;
  contractCandidatesCache.set(key, entry);
  return pending;
}

/**
 * Invalidate cached list views after a document mutation (upload, delete, status change).
 * Automatically notifies all active components subscribed to the document list.
 */
export function invalidateDocumentLists(scopeId?: string): void {
  if (scopeId) {
    const prefix = `${scopeId}:`;
    for (const key of documentListCache.keys()) {
      if (key.startsWith(prefix)) documentListCache.delete(key);
    }
  } else {
    documentListCache.clear();
  }
  notifyListSubscribers();
}

/**
 * Clear one detail record after a review commit, replacement, or deletion.
 */
export function invalidateDocumentDetail(scopeId: string, documentId: string): void {
  const key = cacheKey(scopeId, documentId);
  documentDetailCache.delete(key);
  contractCandidatesCache.delete(key);
}
