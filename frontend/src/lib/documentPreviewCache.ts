'use client';

/** Maximum number of document blobs retained in a browser tab. */
const MAX_ENTRIES = 5;

/** Maximum combined size of retained document blobs (50 MiB). */
const MAX_BYTES = 50 * 1024 * 1024;

/** A stable preview URL leased to one mounted viewer. */
export interface DocumentPreviewAsset {
  mimeType: string | null;
  url: string;
  release: () => void;
}

/** A cached document body, preview URL, and its recency metadata. */
interface CacheEntry {
  blob?: Blob;
  bytes: number;
  lastAccessed: number;
  objectUrl?: string;
  pending?: Promise<CacheEntry>;
  leases: number;
}

/**
 * Tab-scoped preview cache. It intentionally lives only in JavaScript memory:
 * source documents are sensitive and must not persist to disk or be shared
 * across browser sessions.
 */
const previewCache = new Map<string, CacheEntry>();

/** Build a user-scoped cache key for a document preview. */
function cacheKey(scopeId: string, documentId: string): string {
  return `${scopeId}:${documentId}`;
}

/** Return the byte total of all fulfilled cache entries. */
function cachedBytes(): number {
  return Array.from(previewCache.values()).reduce(
    (total, entry) => total + (entry.blob ? entry.bytes : 0),
    0
  );
}

/**
 * Remove least-recently-used fulfilled entries until cache bounds are met.
 * In-flight entries are retained so React remounts can share their request.
 */
function evictIfNeeded(protectedKey?: string): void {
  while (previewCache.size > MAX_ENTRIES || cachedBytes() > MAX_BYTES) {
    const candidate = Array.from(previewCache.entries())
      .filter(([key, entry]) =>
        key !== protectedKey && entry.blob && !entry.pending && entry.leases === 0
      )
      .sort(([, left], [, right]) => left.lastAccessed - right.lastAccessed)[0];
    if (!candidate) return;
    if (candidate[1].objectUrl) URL.revokeObjectURL(candidate[1].objectUrl);
    previewCache.delete(candidate[0]);
  }
}

/**
 * Create a viewer lease for a fulfilled cache entry.
 */
function createLease(entry: CacheEntry): DocumentPreviewAsset {
  if (!entry.blob || !entry.objectUrl) {
    throw new Error('Document preview cache entry was not fulfilled.');
  }
  entry.leases += 1;
  entry.lastAccessed = Date.now();
  let released = false;
  return {
    url: entry.objectUrl,
    mimeType: entry.blob.type || null,
    release: () => {
      if (released) return;
      released = true;
      entry.leases = Math.max(0, entry.leases - 1);
      entry.lastAccessed = Date.now();
      evictIfNeeded();
    },
  };
}

/**
 * Fetch a document once per user/document pair and lease a stable object URL
 * to each viewer. Concurrent React mounts share the same in-flight request
 * and the same resulting URL, preventing PDF.js from reinitializing for a
 * logically unchanged file.
 */
export function acquireDocumentPreview(
  scopeId: string,
  documentId: string,
  load: () => Promise<Blob>
): Promise<DocumentPreviewAsset> {
  const key = cacheKey(scopeId, documentId);
  const existing = previewCache.get(key);
  if (existing?.blob) {
    return Promise.resolve(createLease(existing));
  }
  if (existing?.pending) {
    return existing.pending.then((entry) => createLease(entry));
  }

  const entry: CacheEntry = { bytes: 0, lastAccessed: Date.now(), leases: 0 };
  const pending = load()
    .then((blob) => {
      entry.blob = blob;
      entry.bytes = blob.size;
      entry.objectUrl = URL.createObjectURL(blob);
      entry.lastAccessed = Date.now();
      entry.pending = undefined;
      evictIfNeeded(key);
      return entry;
    })
    .catch((error: unknown) => {
      previewCache.delete(key);
      throw error;
    });
  entry.pending = pending;
  previewCache.set(key, entry);
  evictIfNeeded();
  return pending.then((fulfilledEntry) => createLease(fulfilledEntry));
}

/** Remove one user's cached preview, such as after the source is deleted. */
export function invalidateDocumentPreview(scopeId: string, documentId: string): void {
  const key = cacheKey(scopeId, documentId);
  const entry = previewCache.get(key);
  if (entry?.objectUrl) URL.revokeObjectURL(entry.objectUrl);
  previewCache.delete(key);
}
