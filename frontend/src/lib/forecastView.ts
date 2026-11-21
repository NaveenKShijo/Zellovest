import type { PersistedSeatForecast } from '@/types';

/** Show the newest available run per vendor, department and explicit horizon. */
export function latestForecasts(rows: PersistedSeatForecast[]): PersistedSeatForecast[] {
  const latest = new Map<string, PersistedSeatForecast>();
  for (const row of rows) {
    const key = JSON.stringify([row.vendor_id, row.department, row.retention_curve?.horizon_days ?? null]);
    const previous = latest.get(key);
    if (!previous || row.forecast_date > previous.forecast_date ||
      (row.forecast_date === previous.forecast_date && row.created_at > previous.created_at)) {
      latest.set(key, row);
    }
  }
  return [...latest.values()].sort((a, b) => b.forecast_date.localeCompare(a.forecast_date) || a.vendor_name.localeCompare(b.vendor_name));
}

/** Format only numeric model values and never infer their currency. */
export function forecastAmount(value: number | string | null | undefined): string {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return 'Not available';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(Number(value));
}
