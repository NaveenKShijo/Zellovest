'use client';

import { ContractCandidatesResponse, DocumentDetail, DocumentListResponse } from '@/types';

/** Keep document metadata fresh while absorbing remount and back-navigation reads. */
const CACHE_TTL_MS = 15 * 1000;

/** A fulfilled value or an in-flight request for a cache key. */
interface ReadCacheEntry<T> {
  expiresAt: number;
  pending?: Promise<T>;
  value?: T;
}

/** Tab-scoped caches are isolated by the authenticated user identifier. */
const documentListCache = new Map<string, ReadCacheEntry<DocumentListResponse>>();
const documentDetailCache = new Map<string, ReadCacheEntry<DocumentDetail>>();
const contractCandidatesCache = new Map<string, ReadCacheEntry<ContractCandidatesResponse>>();

/** Build a user-scoped cache key. */
function cacheKey(scopeId: string, resourceKey: string): string {
  return `${scopeId}:${resourceKey}`;
}

/**
 * Return a fresh value or share an in-flight request for the same resource.
 * Failed requests are not cached, so an explicit retry always reaches the API.
 */
function readThrough<T>(
  cache: Map<string, ReadCacheEntry<T>>,
  key: string,
  load: () => Promise<T>
): Promise<T> {
  const now = Date.now();
  const existing = cache.get(key);
  if (existing?.value && existing.expiresAt > now) {
    return Promise.resolve(existing.value);
  }
  if (existing?.pending) return existing.pending;

  const entry: ReadCacheEntry<T> = { expiresAt: 0 };
  const pending = load()
    .then((value) => {
      entry.value = value;
      entry.expiresAt = Date.now() + CACHE_TTL_MS;
      entry.pending = undefined;
      return value;
    })
    .catch((error: unknown) => {
      if (cache.get(key) === entry) cache.delete(key);
      throw error;
    });
  entry.pending = pending;
  cache.set(key, entry);
  return pending;
}

/** Read one filtered document-list result through the short-lived cache. */
export function readDocumentList(
  scopeId: string,
  viewKey: string,
  load: () => Promise<DocumentListResponse>
): Promise<DocumentListResponse> {
  return readThrough(documentListCache, cacheKey(scopeId, viewKey), load);
}

/** Read one document detail record through the short-lived cache. */
export function readDocumentDetail(
  scopeId: string,
  documentId: string,
  load: () => Promise<DocumentDetail>
): Promise<DocumentDetail> {
  return readThrough(documentDetailCache, cacheKey(scopeId, documentId), load);
}

/** Read parent-contract candidates through the short-lived cache. */
export function readContractCandidates(
  scopeId: string,
  documentId: string,
  load: () => Promise<ContractCandidatesResponse>
): Promise<ContractCandidatesResponse> {
  return readThrough(contractCandidatesCache, cacheKey(scopeId, documentId), load);
}

/** Clear cached list views after a document changes the inventory. */
export function invalidateDocumentLists(scopeId: string): void {
  const prefix = `${scopeId}:`;
  for (const key of documentListCache.keys()) {
    if (key.startsWith(prefix)) documentListCache.delete(key);
  }
}

/** Clear one detail record after a review commit, replacement, or deletion. */
export function invalidateDocumentDetail(scopeId: string, documentId: string): void {
  const key = cacheKey(scopeId, documentId);
  documentDetailCache.delete(key);
  contractCandidatesCache.delete(key);
}
