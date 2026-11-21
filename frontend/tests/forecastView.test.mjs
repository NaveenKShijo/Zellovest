import { test } from 'node:test';
import assert from 'node:assert/strict';
import { forecastAmount, latestForecasts } from '../src/lib/forecastView.ts';

test('selects latest runs independently by vendor, department and recorded horizon', () => {
  const row = (id, vendor, department, day, horizon) => ({ id, vendor_id: vendor, vendor_name: vendor, department, forecast_date: day, created_at: `${day}T00:00:00Z`, retention_curve: horizon == null ? null : { horizon_days: horizon } });
  const rows = [row('old', 'A', 'Design', '2026-01-01', 90), row('new', 'A', 'Design', '2026-02-01', 90), row('other-horizon', 'A', 'Design', '2026-01-01', 60), row('other-department', 'A', 'Sales', '2026-01-01', 90), row('other-vendor', 'B', 'Design', '2026-01-01', 90), row('unknown', 'A', 'Design', '2026-01-01', null)];
  assert.deepEqual(new Set(latestForecasts(rows).map((item) => item.id)), new Set(['new', 'other-horizon', 'other-department', 'other-vendor', 'unknown']));
});

test('distinguishes missing or invalid values from zero', () => {
  assert.equal(forecastAmount(null), 'Not available');
  assert.equal(forecastAmount('invalid'), 'Not available');
  assert.equal(forecastAmount(0), '0');
});
