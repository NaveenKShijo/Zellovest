'use client';

import type { NegotiationBriefResponse } from '@/types';

type CachedBrief = { version: string; brief: NegotiationBriefResponse };
const memory = new Map<string, CachedBrief>();
const inFlight = new Map<string, Promise<NegotiationBriefResponse>>();
const generations = new Map<string, number>();
const lastObjectives = new Map<string, string[]>();

/** Restore the last successfully generated objectives for a contract in this browser. */
export function getLastBriefObjectives(scope: string, vendor: string, contract: string): string[] {
  const key = `zellovest:brief-objectives:${JSON.stringify([scope, vendor, contract])}`;
  if (lastObjectives.has(key)) return lastObjectives.get(key)!;
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : [];
  } catch { return []; }
}

/** Remember the selected objectives only after a successful, verified generation. */
export function setLastBriefObjectives(scope: string, vendor: string, contract: string, objectives: string[]): void {
  const key = `zellovest:brief-objectives:${JSON.stringify([scope, vendor, contract])}`;
  lastObjectives.set(key, objectives);
  try { localStorage.setItem(key, JSON.stringify(objectives)); } catch { /* Memory remains available. */ }
}

/** Return a stable, user-scoped key for a contract and its requested objectives. */
function keyFor(scope: string, vendor: string, contract: string, objectives: string[]): string {
  return `zellovest:brief:${JSON.stringify([scope, vendor, contract, objectives])}`;
}

/** Read a brief from browser storage, if available. */
function read(key: string): CachedBrief | undefined {
  const cached = memory.get(key);
  if (cached) return cached;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return undefined;
    const value = JSON.parse(raw) as CachedBrief;
    if (typeof value.version !== 'string' || !value.brief?.generated_at) return undefined;
    memory.set(key, value);
    return value;
  } catch { return undefined; }
}

/** Reuse a brief only when the server confirms its source snapshot is unchanged. */
export async function readVendorBrief(options: {
  scope: string;
  vendor: string;
  contract: string;
  objectives: string[];
  sourceVersion: () => Promise<{ version: string }>;
  generate: () => Promise<NegotiationBriefResponse>;
  force?: boolean;
}): Promise<NegotiationBriefResponse> {
  const key = keyFor(options.scope, options.vendor, options.contract, options.objectives);
  if (!options.force && inFlight.has(key)) return inFlight.get(key)!;
  const generation = (generations.get(key) ?? 0) + 1;
  generations.set(key, generation);
  const task = (async () => {
    for (let attempt = 0; attempt < 2; attempt++) {
      const before = (await options.sourceVersion()).version;
      const cached = read(key);
      if (!options.force && cached?.version === before) return cached.brief;
      const brief = await options.generate();
      const after = (await options.sourceVersion()).version;
      if (before !== after) continue;
      if (brief.cacheable !== false && generations.get(key) === generation) {
        const value = { version: after, brief };
        memory.set(key, value);
        try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Memory cache still works. */ }
      } else if (brief.cacheable === false && generations.get(key) === generation) {
        memory.delete(key);
        try { localStorage.removeItem(key); } catch { /* Storage may be unavailable. */ }
      }
      return brief;
    }
    throw new Error('Vendor data changed while generating the brief. Please try again.');
  })();
  inFlight.set(key, task);
  try { return await task; }
  finally { if (inFlight.get(key) === task) inFlight.delete(key); }
}
