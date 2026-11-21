'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useApi } from '@/lib/api';
import type { PersistedSeatForecast } from '@/types';
import styles from './licenses.module.css';

const amount = (value: number | string | null) => value == null ? 'Not available' : new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(Number(value));
const percent = (value: number | string | null) => value == null ? 'Not available' : `${(Number(value) * 100).toFixed(1)}%`;

/** Decision workspace for the persisted, department-level model outputs. */
export default function LicensesPage() {
  const api = useApi();
  const [rows, setRows] = useState<PersistedSeatForecast[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState('');
  const [loadedAt, setLoadedAt] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    api.negotiation.seatForecasts().then((data) => {
      if (active) { setRows(data); setLoadedAt(Date.now()); setStatus('ready'); }
    }).catch((err: unknown) => {
      if (active) { setError(err instanceof Error ? err.message : 'Please try again.'); setStatus('error'); }
    });
    return () => { active = false; };
  }, [api, retry]);

  const filtered = useMemo(() => rows.filter((row) => `${row.vendor_name} ${row.department ?? ''}`.toLowerCase().includes(search.trim().toLowerCase())), [rows, search]);
  const forecast = filtered.find((row) => row.id === selected) ?? filtered[0];
  const forecastAge = forecast && loadedAt != null ? Math.floor((loadedAt - Date.parse(`${forecast.forecast_date}T00:00:00Z`)) / 86400000) : 0;
  const retryLoad = () => { setStatus('loading'); setRetry((value) => value + 1); };
  const prompt = forecast ? `Help me review the ${forecast.vendor_name} license renewal forecast for ${forecast.department || 'the department'}. The ${forecast.forecast_date} forecast recommends ${forecast.recommended_seats} seats from ${forecast.current_seats} assigned seats. Investigate renewal timing, contract terms and true-up penalties with sources.` : '';
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>RENEWAL INTELLIGENCE</span><h1>License forecasting</h1><p>Review seat commitments, potential savings and the cost of demand exceeding your commitment.</p></div><button className={styles.secondary} onClick={retryLoad} disabled={status === 'loading'}>Refresh forecasts</button></header>
    {status === 'loading' && <div className={styles.state} role="status">Loading forecast results…</div>}
    {status === 'error' && <div className={styles.state} role="alert"><h2>Could not load forecasts</h2><p>{error}</p><button className={styles.secondary} onClick={retryLoad}>Try again</button></div>}
    {status === 'ready' && rows.length === 0 && <div className={styles.state}><h2>No forecasts available yet</h2><p>Forecasts appear after active license assignments, usage history, renewal features and the model run are available. Check the data integrations and ask your administrator to run the forecast.</p><Link href="/integrations">Review integrations →</Link></div>}
    {status === 'ready' && rows.length > 0 && <><div className={styles.notice}>Forecasts are shown by department and run. The current model output does not identify a product, renewal date or currency, so verify the contract, timing and currency before making a commitment.</div><div className={styles.layout}>
      <section className={styles.card} aria-labelledby="portfolio"><div className={styles.sectionHead}><div><span className={styles.eyebrow}>PORTFOLIO</span><h2 id="portfolio">Forecast results</h2></div><span>{filtered.length} results</span></div><label className={styles.label} htmlFor="forecast-search">Search vendor or department</label><input id="forecast-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search forecasts" />
      {filtered.length === 0 ? <p className={styles.muted}>No forecasts match your search.</p> : <div className={styles.results}>{filtered.map((row) => <button key={row.id} type="button" aria-pressed={forecast?.id === row.id} className={`${styles.result} ${forecast?.id === row.id ? styles.selected : ''}`} onClick={() => setSelected(row.id)}><span><strong>{row.vendor_name}</strong><small>{row.department || 'Department not specified'} · {row.forecast_date}</small></span><span className={styles.right}><strong>{row.recommended_seats} seats</strong><small>from {row.current_seats} · risk {amount(row.trueup_risk_amount)}</small></span></button>)}</div>}</section>
      {forecast && <section className={styles.detail} aria-label="Selected forecast"><div className={styles.card}><span className={styles.eyebrow}>COMMITMENT RECOMMENDATION</span><h2>{forecast.vendor_name}</h2><p className={styles.muted}>{forecast.department || 'Department not specified'} · Forecast run {forecast.forecast_date}{forecast.retention_curve?.horizon_days != null ? ` · T-${forecast.retention_curve.horizon_days}` : ' · Horizon not available'}</p>{forecastAge > 30 && <p className={styles.notice}>This forecast is over 30 days old. Check for a newer run and changes in usage before using it.</p>}<div className={styles.commit}><strong>{forecast.recommended_seats}</strong><span>recommended seats<br />compared with {forecast.current_seats} assigned seats</span></div><p className={styles.muted}>This is a model estimate for this department, not an authorization to change the contract.</p><div className={styles.metrics}><Metric title="Estimated savings" value={amount(forecast.savings_estimate)} text="Estimated savings from the recommended commitment." /><Metric title="Expected shelfware" value={amount(forecast.shelfware_amount)} text="Expected cost of committed seats that go unused." /><Metric title="Expected true-up cost" value={amount(forecast.trueup_risk_amount)} text="Expected cost when demand exceeds the commitment." /></div></div>
      <div className={styles.card}><h3>Demand and uncertainty</h3><p className={styles.muted}>Estimates are based on the usage features and penalty assumptions used by the model. Confidence describes the model estimate; it is not a guarantee.</p><div className={styles.facts}><span>Expected demand <strong>{forecast.retention_curve?.expected_demand ?? 'Not available'}</strong></span><span>Commitment confidence <strong>{percent(forecast.confidence)}</strong></span><span>Model version <strong>{forecast.model_version || 'Not available'}</strong></span><span>Generated <strong>{forecast.created_at ? new Date(forecast.created_at).toLocaleString() : 'Not available'}</strong></span></div>
      {(forecast.retention_curve?.departments ?? []).length > 0 ? <div className={styles.tableWrap}><table><caption>Department demand and available model intervals</caption><thead><tr><th scope="col">Department</th><th scope="col">Expected seats</th><th scope="col">Retention</th><th scope="col">Model interval</th></tr></thead><tbody>{forecast.retention_curve?.departments?.map((dept, i) => <tr key={`${dept.department}-${i}`}><th scope="row">{dept.department}</th><td>{dept.expected_retained_seats}</td><td>{percent(dept.survival_probability)}</td><td>{dept.confidence_intervals?.length ? dept.confidence_intervals.map((interval) => `${Math.round(interval.level * 100)}%: ${interval.lower_seats}–${interval.upper_seats}`).join('; ') : 'Not available'}</td></tr>)}</tbody></table></div> : <p className={styles.muted}>No demand intervals were returned for this run.</p>}<p className={styles.muted}>Renewal date, product, penalty rate and comparable checkpoints are not included in the current forecast record.</p></div>
      <div className={styles.card}><h3>Next steps</h3><p className={styles.muted}>Review the contract’s seat and true-up terms before deciding on a renewal commitment.</p><div className={styles.actions}><Link className={styles.primary} href={`/assistant?prompt=${encodeURIComponent(prompt)}&vendorId=${encodeURIComponent(forecast.vendor_id)}`}>Ask renewal agent →</Link><Link className={styles.secondary} href={`/renewals?search=${encodeURIComponent(forecast.vendor_name)}`}>Open renewal timeline</Link></div></div></section>}
    </div></>}
  </main>;
}

function Metric({ title, value, text }: { title: string; value: string; text: string }) {
  return <div className={styles.metric}><span>{title}</span><strong>{value}</strong><small>{text}</small></div>;
}
