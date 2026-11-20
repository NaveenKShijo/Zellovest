import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readVendorBrief } from '../src/lib/negotiationBriefCache.ts';

test('reuses unchanged briefs, refreshes changed sources and separates objectives', async () => {
  let version = 'one';
  let calls = 0;
  const options = {
    scope: 'cache-test-user', vendor: 'vendor', contract: 'contract', objectives: [],
    sourceVersion: async () => ({ version }),
    generate: async () => ({ generated_at: `generation-${++calls}` }),
  };
  const first = await readVendorBrief(options);
  assert.equal((await readVendorBrief(options)).generated_at, first.generated_at);
  assert.equal(calls, 1);
  version = 'two';
  assert.equal((await readVendorBrief(options)).generated_at, 'generation-2');
  await readVendorBrief({ ...options, objectives: ['Reduce seats'] });
  assert.equal(calls, 3);
  await readVendorBrief({ ...options, force: true });
  assert.equal(calls, 4);
});

test('does not cache a brief generated across a source change', async () => {
  let version = 'before';
  let calls = 0;
  const options = {
    scope: 'race-test-user', vendor: 'vendor', contract: 'contract', objectives: [],
    sourceVersion: async () => ({ version }),
    generate: async () => { calls++; version = 'after'; return { generated_at: `generation-${calls}` }; },
  };
  assert.equal((await readVendorBrief(options)).generated_at, 'generation-2');
  assert.equal((await readVendorBrief(options)).generated_at, 'generation-2');
  assert.equal(calls, 2);
});

test('restores a stored brief after a page reload', async () => {
  const storage = new Map();
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
  };
  let calls = 0;
  const options = {
    scope: 'reload-user', vendor: 'vendor', contract: 'contract', objectives: [],
    sourceVersion: async () => ({ version: 'unchanged' }),
    generate: async () => ({ generated_at: `generation-${++calls}` }),
  };
  await readVendorBrief(options);
  const reloaded = await import('../src/lib/negotiationBriefCache.ts?reload-test');
  assert.equal((await reloaded.readVendorBrief(options)).generated_at, 'generation-1');
  assert.equal(calls, 1);
  delete globalThis.localStorage;
});

test('does not retain a fallback response when generation fails', async () => {
  let calls = 0;
  const options = {
    scope: 'fallback-user', vendor: 'vendor', contract: 'contract', objectives: [],
    sourceVersion: async () => ({ version: 'one' }),
    generate: async () => ({ generated_at: `generation-${++calls}`, cacheable: false }),
  };
  await readVendorBrief(options);
  await readVendorBrief(options);
  assert.equal(calls, 2);
});
