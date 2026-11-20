'use client';

import { NegotiationBriefResponse, UpcomingRenewal } from '@/types';

/** Freshness window: renewals fetched within 30s are considered fresh. */
const STALE_TIME_MS = 30 * 1000;

/** Maximum retention: cached items older than 5 minutes are garbage collected. */
const CACHE_TTL_MS = 5 * 60 * 1000;

interface CacheEntry<T> {
  value?: T;
  timestamp: number;
  pending?: Promise<T>;
}

const renewalsListCache = new Map<string, CacheEntry<UpcomingRenewal[]>>();
const negotiationBriefCache = new Map<string, CacheEntry<NegotiationBriefResponse>>();

const renewalsSubscribers = new Set<() => void>();

function cacheKey(scopeId: string, resourceKey: string): string {
  return `${scopeId}:${resourceKey}`;
}

/** Subscribe to renewals list invalidation events across components. */
export function subscribeRenewals(callback: () => void): () => void {
  renewalsSubscribers.add(callback);
  return () => {
    renewalsSubscribers.delete(callback);
  };
}

function notifyRenewalsSubscribers(): void {
  for (const listener of renewalsSubscribers) {
    try {
      listener();
    } catch {
      // Ignore subscriber errors
    }
  }
}

/**
 * Synchronously peek at cached upcoming renewals if present.
 * Allows the Renewals page to render instantly (0ms) on mount rather than showing a blank screen.
 */
export function peekRenewalsList(
  scopeId: string,
  filterKey: string
): UpcomingRenewal[] | null {
  const key = cacheKey(scopeId, filterKey);
  const entry = renewalsListCache.get(key);
  if (!entry?.value) return null;
  if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
    renewalsListCache.delete(key);
    return null;
  }
  return entry.value;
}

/**
 * Read upcoming renewals using Stale-While-Revalidate (SWR):
 * 1. If fresh cached data exists, returns it immediately.
 * 2. If stale cached data exists, returns it immediately AND triggers background revalidation,
 *    notifying `onRevalidate` with fresh server data when it resolves.
 * 3. If cache miss, loads from network with inflight promise deduplication.
 */
export function readRenewalsList(
  scopeId: string,
  filterKey: string,
  load: () => Promise<UpcomingRenewal[]>,
  options?: {
    onRevalidate?: (fresh: UpcomingRenewal[]) => void;
    force?: boolean;
  }
): Promise<UpcomingRenewal[]> {
  const key = cacheKey(scopeId, filterKey);
  const now = Date.now();
  const existing = renewalsListCache.get(key);

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

  const entry: CacheEntry<UpcomingRenewal[]> = existing ?? { timestamp: 0 };
  const pending = load()
    .then((value) => {
      entry.value = value;
      entry.timestamp = Date.now();
      entry.pending = undefined;
      return value;
    })
    .catch((error: unknown) => {
      if (renewalsListCache.get(key) === entry) {
        renewalsListCache.delete(key);
      }
      throw error;
    });

  entry.pending = pending;
  renewalsListCache.set(key, entry);
  return pending;
}

/**
 * Synchronously peek at cached negotiation brief.
 */
export function peekNegotiationBrief(
  scopeId: string,
  briefKey: string
): NegotiationBriefResponse | null {
  const key = cacheKey(scopeId, briefKey);
  const entry = negotiationBriefCache.get(key);
  if (!entry?.value) return null;
  if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
    negotiationBriefCache.delete(key);
    return null;
  }
  return entry.value;
}

/**
 * Read negotiation brief through SWR cache so opening dossiers doesn't trigger
 * repetitive LLM syntheses if already requested within freshness window.
 */
export function readNegotiationBrief(
  scopeId: string,
  briefKey: string,
  load: () => Promise<NegotiationBriefResponse>,
  options?: {
    onRevalidate?: (fresh: NegotiationBriefResponse) => void;
    force?: boolean;
  }
): Promise<NegotiationBriefResponse> {
  const key = cacheKey(scopeId, briefKey);
  const now = Date.now();
  const existing = negotiationBriefCache.get(key);

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

  const entry: CacheEntry<NegotiationBriefResponse> = existing ?? { timestamp: 0 };
  const pending = load()
    .then((value) => {
      entry.value = value;
      entry.timestamp = Date.now();
      entry.pending = undefined;
      return value;
    })
    .catch((error: unknown) => {
      if (negotiationBriefCache.get(key) === entry) {
        negotiationBriefCache.delete(key);
      }
      throw error;
    });

  entry.pending = pending;
  negotiationBriefCache.set(key, entry);
  return pending;
}

/**
 * Invalidate cached renewal views (e.g. on manual refresh or reminder created).
 */
export function invalidateRenewals(scopeId?: string): void {
  if (scopeId) {
    const prefix = `${scopeId}:`;
    for (const key of renewalsListCache.keys()) {
      if (key.startsWith(prefix)) renewalsListCache.delete(key);
    }
    for (const key of negotiationBriefCache.keys()) {
      if (key.startsWith(prefix)) negotiationBriefCache.delete(key);
    }
  } else {
    renewalsListCache.clear();
    negotiationBriefCache.clear();
  }
  notifyRenewalsSubscribers();
}
