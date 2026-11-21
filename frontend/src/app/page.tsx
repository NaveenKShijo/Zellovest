'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { useApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import type { UpcomingRenewal, PersistedSeatForecast } from '@/types';
import styles from './page.module.css';

type Result<T> = { state: 'loading' } | { state: 'error' } | { state: 'ready'; data: T };
type Audit = { total_invoices_count: number; exception_invoices_count: number; unreconciled_invoices_count: number };
type Overview = { renewals: Result<UpcomingRenewal[]>; audit: Result<Audit>; reviews: Result<number>; forecasts: Result<PersistedSeatForecast[]> };
const pending = (): Overview => ({ renewals: { state: 'loading' }, audit: { state: 'loading' }, reviews: { state: 'loading' }, forecasts: { state: 'loading' } });

/** Summarize operational queues using independent live data sources. */
export default function OverviewDashboardPage() {
  const api = useApi();
  const { user } = useAuth();
  const [overview, setOverview] = useState<Overview>(pending);
  const [generation, setGeneration] = useState(0);
  const [updated, setUpdated] = useState<Date | null>(null);

  useEffect(() => {
    if (!user) return;
    // Clear the previous account's results before starting requests for this user.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOverview(pending());
    let active = true;
    const settle = <T,>(promise: Promise<T>, key: keyof Overview) => {
      promise.then((data) => {
        if (active) setOverview((previous) => ({ ...previous, [key]: { state: 'ready', data } }));
      }).catch(() => {
        if (active) setOverview((previous) => ({ ...previous, [key]: { state: 'error' } }));
      });
    };
    settle(api.negotiation.upcomingRenewals({ days_ahead: 120 }), 'renewals');
    settle(api.compliance.getOverview(), 'audit');
    settle(api.documents.list({ status: 'review_needed', page: 1, page_size: 1 }).then((result) => result.total), 'reviews');
    settle(api.negotiation.seatForecasts(), 'forecasts');
    return () => { active = false; };
  }, [api, user, generation]);

  const urgent = useMemo(() => overview.renewals.state === 'ready'
    ? overview.renewals.data.filter((r) => r.autoRenew && r.daysUntilRenewal >= 0 && r.daysUntilNoticeDeadline <= 30).sort((a, b) => a.daysUntilNoticeDeadline - b.daysUntilNoticeDeadline)
    : [], [overview.renewals]);
  const refresh = () => { setOverview(pending()); setUpdated(new Date()); setGeneration((value) => value + 1); };

  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>PROCUREMENT OVERVIEW</span><h1>Your work, in focus.</h1><p>See what needs attention across renewals, invoices and documents, then move directly to the next step.</p></div><button className={styles.refresh} onClick={refresh}>↻ <span>Refresh overview</span></button></header>
    <section className={styles.metrics} aria-label="Operational overview">
      <Metric label="Notice deadlines" value={value(overview.renewals, String(urgent.length))} caption="Due within 30 days or passed, for renewals within 120 days" href="/renewals" />
      <Metric label="Invoices flagged" value={value(overview.audit, overview.audit.state === 'ready' ? String(overview.audit.data.exception_invoices_count) : '')} caption="Invoices with open or acknowledged exceptions" href="/compliance" />
      <Metric label="Awaiting audit" value={value(overview.audit, overview.audit.state === 'ready' ? String(overview.audit.data.unreconciled_invoices_count) : '')} caption="Invoices not yet reconciled" href="/compliance" />
      <Metric label="Documents to review" value={value(overview.reviews, overview.reviews.state === 'ready' ? String(overview.reviews.data) : '')} caption="Documents marked for review" href="/documents?status=review_needed" />
    </section>
    <div className={styles.layout}><div className={styles.main}>
      <section className={styles.card}><div className={styles.sectionHead}><div><span className={styles.eyebrow}>YOUR PRIORITIES</span><h2>Renewals to look at</h2><p>Notice deadlines due or passed for auto-renewals in the next 120 days.</p></div><Link href="/renewals">View timeline ↗</Link></div>
        {overview.renewals.state === 'loading' ? <State>Loading renewal deadlines…</State> : overview.renewals.state === 'error' ? <State>Renewals are unavailable. Try refreshing or open the renewal timeline.</State> : urgent.length === 0 ? <State>No auto-renew notice deadlines need attention in the next 30 days among renewals in the next 120 days.</State> : <div className={styles.rows}>{urgent.slice(0, 5).map((r) => <Link className={styles.row} key={r.contractId} href={`/renewals?search=${encodeURIComponent(r.vendorName)}`}><span className={styles.initial}>{r.vendorName.slice(0, 1).toUpperCase()}</span><span className={styles.rowMain}><strong>{r.vendorName}</strong><small>{r.productName} · {r.contractNumber}</small></span><span className={styles.rowEnd}><strong className={r.daysUntilNoticeDeadline <= 0 ? styles.danger : styles.warning}>{r.daysUntilNoticeDeadline < 0 ? `${Math.abs(r.daysUntilNoticeDeadline)}d past notice` : r.daysUntilNoticeDeadline === 0 ? 'Notice due today' : `${r.daysUntilNoticeDeadline}d to notice`}</strong><small>Notice {r.noticeDeadlineDate} · renews {r.renewalDate}</small></span><span className={styles.arrow}>↗</span></Link>)}</div>}
        <p className={styles.footnote}>Based on the renewal timeline. Confirm notice terms against the contract.</p>
      </section>
      <section className={styles.card}><div className={styles.sectionHead}><div><span className={styles.eyebrow}>CONTROL &amp; COMPLIANCE</span><h2>Keep the review moving</h2><p>Open the queue that needs your attention.</p></div></div><div className={styles.queue}>
        <Queue title="Invoice exceptions" description="Investigate discrepancies against contract terms." href="/compliance" count={value(overview.audit, overview.audit.state === 'ready' ? String(overview.audit.data.exception_invoices_count) : '')} />
        <Queue title="Unreconciled invoices" description="Check invoices awaiting a commercial audit." href="/compliance" count={value(overview.audit, overview.audit.state === 'ready' ? String(overview.audit.data.unreconciled_invoices_count) : '')} />
        <Queue title="Documents for review" description="Verify extracted information and source documents." href="/documents?status=review_needed" count={value(overview.reviews, overview.reviews.state === 'ready' ? String(overview.reviews.data) : '')} />
      </div></section>
    </div><aside className={styles.side}>
      <section className={styles.darkCard}><span className={styles.darkEyebrow}>ASK ZELLOVEST</span><h2>Start with a question.</h2><p>Explore vendor history, contract terms and procurement evidence in one place.</p><Link href="/assistant">Open Ask AI <span>↗</span></Link><div className={styles.prompts}><Link href={`/assistant?prompt=${encodeURIComponent('Which renewals need attention and what evidence should I review?')}`}>Which renewals need attention? ↗</Link><Link href={`/assistant?prompt=${encodeURIComponent('What invoice discrepancies should we investigate first?')}`}>What invoice discrepancies need review? ↗</Link></div></section>
      <section className={styles.card}><span className={styles.eyebrow}>LICENSE PLANNING</span><h2>Forecast workspace</h2><p className={styles.sideCopy}>Review model recommendations and expected true-up costs by department.</p><div className={styles.forecastCount}><strong>{value(overview.forecasts, overview.forecasts.state === 'ready' ? String(overview.forecasts.data.length) : '')}</strong><span>persisted forecast records<br /><small>across all available runs</small></span></div><Link className={styles.outlineLink} href="/licenses">Explore forecasts <span>→</span></Link></section>
      <section className={styles.card}><span className={styles.eyebrow}>QUICK ACCESS</span><nav aria-label="Procurement tools" className={styles.quick}><Link href="/vendors">Vendor overview <span>↗</span></Link><Link href="/maverick-spend">Maverick spend <span>↗</span></Link><Link href="/integrations">Data integrations <span>↗</span></Link></nav></section>
    </aside></div>
    <p className={styles.bottomNote}>{updated ? `Refresh requested ${updated.toLocaleTimeString()}. ` : ''}Counts come from their respective operational queues. Open a workflow to review details and source evidence.</p>
  </main>;
}

function value<T>(result: Result<T>, ready: string): string { return result.state === 'loading' ? '…' : result.state === 'error' ? 'Unavailable' : ready; }
function Metric({ label, value: content, caption, href }: { label: string; value: string; caption: string; href: string }) { return <Link href={href} className={styles.metric}><div><span>{label}</span><span aria-hidden="true">↗</span></div><strong className={content === 'Unavailable' ? styles.unavailable : ''}>{content}</strong><small>{caption}</small></Link>; }
function Queue({ title, description, href, count }: { title: string; description: string; href: string; count: string }) { return <Link href={href} className={styles.queueItem}><div><strong>{title}</strong><p>{description}</p></div><span>{count}</span><b aria-hidden="true">→</b></Link>; }
function State({ children }: { children: React.ReactNode }) { return <div className={styles.state} role="status">{children}</div>; }
