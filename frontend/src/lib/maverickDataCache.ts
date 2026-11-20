'use client';

import { MaverickAlertItem, MaverickSpendKPIs } from '@/types';

/** Freshness window: feed results fetched within 30 seconds are reused. */
const STALE_TIME_MS = 30 * 1000;

/** Maximum retention before a feed entry is discarded. */
const CACHE_TTL_MS = 5 * 60 * 1000;

export interface MaverickFeedResponse {
  alerts: MaverickAlertItem[];
  kpis: MaverickSpendKPIs;
}

interface CacheEntry<T> {
  value?: T;
  timestamp: number;
  pending?: Promise<T>;
}

const maverickFeedCache = new Map<string, CacheEntry<MaverickFeedResponse>>();

/** Build a cache key isolated to the current authenticated user and feed view. */
function cacheKey(scopeId: string, viewKey: string): string {
  return `${scopeId}:${viewKey}`;
}

/**
 * Synchronously retrieve a retained decentralized-spend view for instant page rendering.
 */
export function peekMaverickFeed(
  scopeId: string,
  viewKey: string
): MaverickFeedResponse | null {
  const key = cacheKey(scopeId, viewKey);
  const entry = maverickFeedCache.get(key);
  if (!entry?.value) return null;

  if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
    maverickFeedCache.delete(key);
    return null;
  }

  return entry.value;
}

/**
 * Read a decentralized-spend feed using stale-while-revalidate semantics.
 *
 * Fresh data is returned immediately. Retained but stale data is rendered while
 * one shared background request refreshes it. Cache misses are deduplicated so
 * concurrent components cannot issue duplicate feed requests.
 */
export function readMaverickFeed(
  scopeId: string,
  viewKey: string,
  load: () => Promise<MaverickFeedResponse>,
  options?: {
    onRevalidate?: (fresh: MaverickFeedResponse) => void;
    force?: boolean;
  }
): Promise<MaverickFeedResponse> {
  const key = cacheKey(scopeId, viewKey);
  const now = Date.now();
  const existing = maverickFeedCache.get(key);

  if (!options?.force && existing?.value && now - existing.timestamp < CACHE_TTL_MS) {
    if (now - existing.timestamp < STALE_TIME_MS) {
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
    } else if (options?.onRevalidate) {
      existing.pending.then(options.onRevalidate).catch(() => {});
    }

    return Promise.resolve(existing.value);
  }

  if (!options?.force && existing?.pending) {
    return existing.pending;
  }

  const entry: CacheEntry<MaverickFeedResponse> = existing ?? { timestamp: 0 };
  const pending = load()
    .then((value) => {
      entry.value = value;
      entry.timestamp = Date.now();
      entry.pending = undefined;
      return value;
    })
    .catch((error: unknown) => {
      if (maverickFeedCache.get(key) === entry) {
        maverickFeedCache.delete(key);
      }
      throw error;
    });

  entry.pending = pending;
  maverickFeedCache.set(key, entry);
  return pending;
}

/** Invalidate cached decentralized-spend views after a server-side mutation. */
export function invalidateMaverickFeeds(scopeId?: string): void {
  if (!scopeId) {
    maverickFeedCache.clear();
    return;
  }

  const prefix = `${scopeId}:`;
  for (const key of maverickFeedCache.keys()) {
    if (key.startsWith(prefix)) {
      maverickFeedCache.delete(key);
    }
  }
}
