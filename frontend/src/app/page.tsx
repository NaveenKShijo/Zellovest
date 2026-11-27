'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { useApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/contexts/ToastContext';
import { DecisionFeed } from '@/components/briefing/DecisionFeed';
import type {
  DecisionFeedResponse,
  DecisionPacketItem,
  PersistedSeatForecast,
  WorkflowItem,
} from '@/types';
import styles from './page.module.css';

type Result<T> = { state: 'loading' } | { state: 'error' } | { state: 'ready'; data: T };

const money = (value: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value);

/** Outcome-first procurement briefing powered by pre-computed decision packets. */
export default function OverviewDashboardPage() {
  const api = useApi();
  const { user } = useAuth();
  const { notify } = useToast();

  const [feedState, setFeedState] = useState<Result<DecisionFeedResponse>>({ state: 'loading' });
  const [workflows, setWorkflows] = useState<Result<WorkflowItem[]>>({ state: 'loading' });
  const [forecasts, setForecasts] = useState<Result<PersistedSeatForecast[]>>({ state: 'loading' });
  const [activeFilter, setActiveFilter] = useState('all');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [updated, setUpdated] = useState<Date | null>(null);

  const loadOverview = useCallback(async () => {
    const [feedRes, wfRes, fcRes] = await Promise.allSettled([
      api.decisionFeed.get({ status: 'pending_review', limit: 25 }),
      api.workflows.list({ status: 'pending', page_size: 5 }),
      api.negotiation.seatForecasts(),
    ]);

    if (feedRes.status === 'fulfilled') {
      setFeedState({ state: 'ready', data: feedRes.value });
    } else {
      setFeedState({ state: 'error' });
    }

    if (wfRes.status === 'fulfilled') {
      setWorkflows({ state: 'ready', data: wfRes.value.workflows || [] });
    } else {
      setWorkflows({ state: 'error' });
    }

    if (fcRes.status === 'fulfilled') {
      setForecasts({ state: 'ready', data: fcRes.value || [] });
    } else {
      setForecasts({ state: 'error' });
    }
  }, [api]);

  useEffect(() => {
    if (!user) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadOverview();
  }, [user, loadOverview]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await api.decisionFeed.refresh();
      await loadOverview();
      setUpdated(new Date());
      notify.success('Briefing Refreshed', 'Pre-computed outcomes updated from the latest ledger and telemetry.');
    } catch {
      await loadOverview();
    } finally {
      setIsRefreshing(false);
    }
  };

  const handlePacketAction = async (
    packet: DecisionPacketItem,
    action: 'acknowledge' | 'resolve' | 'dismiss' | 'mark_migrated' | 'create_workflow'
  ) => {
    try {
      const res = await api.decisionFeed.executeAction(packet.id, action);
      notify.success('Outcome Recorded', res.message);
      await loadOverview();
    } catch (err) {
      notify.error(
        'Action Failed',
        err instanceof Error ? err.message : 'Unable to complete the requested action.'
      );
    }
  };

  const handleCompleteWorkflow = async (wfId: string) => {
    try {
      await api.workflows.action(wfId, 'approve', 'Completed directly from procurement briefing');
      notify.success('Task Completed', 'Workflow marked approved in the procurement log.');
      await loadOverview();
    } catch (err) {
      notify.error(
        'Unable to Update Task',
        err instanceof Error ? err.message : 'Try again shortly.'
      );
    }
  };

  const summary = feedState.state === 'ready' ? feedState.data.summary : null;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>AUTOMATED PROCUREMENT BRIEFING</span>
          <h1>Decisions ready for you.</h1>
          <p>
            Background workers continuously audit invoices, monitor renewals, and analyze card spend—review pre-computed findings and act in one click.
          </p>
        </div>
        <button className={styles.refresh} onClick={handleRefresh} disabled={isRefreshing}>
          ↻ <span>{isRefreshing ? 'Refreshing outcomes…' : 'Refresh outcomes'}</span>
        </button>
      </header>

      <section className={styles.metrics} aria-label="Operational overview">
        <Metric
          label="Ready decisions"
          value={
            feedState.state === 'loading'
              ? '…'
              : feedState.state === 'error'
                ? 'Unavailable'
                : String(summary?.pending_count ?? 0)
          }
          caption="Pre-computed AP, renewal & SaaS findings awaiting your call"
          href="/compliance"
        />
        <Metric
          label="Actionable exposure"
          value={
            feedState.state === 'loading'
              ? '…'
              : feedState.state === 'error'
                ? 'Unavailable'
                : money(summary?.total_financial_impact ?? 0)
          }
          caption="Total dollar variance & optimization opportunity detected"
          href="/renewals"
        />
        <Metric
          label="Staged savings"
          value={
            feedState.state === 'loading'
              ? '…'
              : feedState.state === 'error'
                ? 'Unavailable'
                : money(summary?.potential_savings_total ?? 0)
          }
          caption="Hard-cash recovery & cost avoidance staged in ledger"
          href="/maverick-spend"
        />
        <Metric
          label="Documents to review"
          value={
            feedState.state === 'loading'
              ? '…'
              : feedState.state === 'error'
                ? 'Unavailable'
                : String(summary?.documents_review_needed ?? 0)
          }
          caption="Low-confidence extractions needing human verification"
          href="/documents?status=review_needed"
        />
      </section>

      <div className={styles.layout}>
        <div className={styles.main}>
          <section className={styles.card}>
            <div className={styles.sectionHead}>
              <div>
                <span className={styles.eyebrow}>DECISION FEED</span>
                <h2>Pre-computed outcomes &amp; next steps</h2>
                <p>
                  Investigations and renewal dossiers are prepared automatically before you open them.
                </p>
              </div>
              <Link href="/compliance">Open AP Audit ↗</Link>
            </div>
            <DecisionFeed
              items={feedState.state === 'ready' ? feedState.data.items : []}
              loading={feedState.state === 'loading'}
              error={feedState.state === 'error'}
              activeFilter={activeFilter}
              onFilterChange={setActiveFilter}
              onAction={handlePacketAction}
            />
          </section>
        </div>

        <aside className={styles.side}>
          <section className={styles.card}>
            <div className={styles.sectionHead}>
              <div>
                <span className={styles.eyebrow}>IN-APP TASKS</span>
                <h2>Active workflows</h2>
              </div>
            </div>
            {workflows.state === 'loading' ? (
              <State>Loading active tasks…</State>
            ) : workflows.state === 'error' ? (
              <State>Tasks are temporarily unavailable.</State>
            ) : workflows.data.length === 0 ? (
              <State>No open tasks. Create tasks directly from any finding in the Decision Feed.</State>
            ) : (
              <div className={styles.rows}>
                {workflows.data.map((wf) => (
                  <div
                    key={wf.id}
                    className={styles.row}
                    style={{ cursor: 'default' }}
                  >
                    <span className={styles.rowMain}>
                      <strong>{wf.title}</strong>
                      <small>{wf.workflow_type.replace('_', ' ')} · {wf.status}</small>
                    </span>
                    <button
                      type="button"
                      onClick={() => void handleCompleteWorkflow(wf.id)}
                      style={{
                        border: '1px solid var(--border-strong)',
                        background: '#FFFFFF',
                        borderRadius: '7px',
                        padding: '5px 10px',
                        fontSize: '11.5px',
                        fontWeight: 700,
                        color: 'var(--color-brand)',
                        cursor: 'pointer',
                      }}
                    >
                      Done ✓
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className={styles.darkCard}>
            <span className={styles.darkEyebrow}>ASK ZELLOVEST</span>
            <h2>Dig deeper on any vendor.</h2>
            <p>Ask ad-hoc questions across contracts, usage, invoices, and card spend with full citations.</p>
            <Link href="/assistant">
              Open Ask AI <span>↗</span>
            </Link>
            <div className={styles.prompts}>
              <Link href={`/assistant?prompt=${encodeURIComponent('Which renewals need attention and what evidence should I review?')}`}>
                Which renewals need attention? ↗
              </Link>
              <Link href={`/assistant?prompt=${encodeURIComponent('What invoice discrepancies should we investigate first?')}`}>
                What invoice discrepancies need review? ↗
              </Link>
            </div>
          </section>

          <section className={styles.card}>
            <span className={styles.eyebrow}>LICENSE PLANNING</span>
            <h2>Forecast workspace</h2>
            <p className={styles.sideCopy}>
              Model-backed seat commitments and true-up risk estimates by department.
            </p>
            <div className={styles.forecastCount}>
              <strong>
                {forecasts.state === 'loading'
                  ? '…'
                  : forecasts.state === 'error'
                    ? 'Unavailable'
                    : String(forecasts.data.length)}
              </strong>
              <span>
                persisted forecast records
                <br />
                <small>automatically updated at renewal milestones</small>
              </span>
            </div>
            <Link className={styles.outlineLink} href="/licenses">
              Explore forecasts <span>→</span>
            </Link>
          </section>

          <section className={styles.card}>
            <span className={styles.eyebrow}>QUICK ACCESS</span>
            <nav aria-label="Procurement tools" className={styles.quick}>
              <Link href="/vendors">
                Vendor overview <span>↗</span>
              </Link>
              <Link href="/maverick-spend">
                Maverick spend <span>↗</span>
              </Link>
              <Link href="/integrations">
                Data integrations <span>↗</span>
              </Link>
            </nav>
          </section>
        </aside>
      </div>

      <p className={styles.bottomNote}>
        {updated ? `Refresh completed ${updated.toLocaleTimeString()}. ` : ''}
        {summary?.last_sync_at
          ? `Last automated integration sync: ${new Date(summary.last_sync_at).toLocaleString()}. `
          : ''}
        Background ingestion and audit pipelines keep these outcomes current automatically.
      </p>
    </main>
  );
}

function Metric({
  label,
  value: content,
  caption,
  href,
}: {
  label: string;
  value: string;
  caption: string;
  href: string;
}) {
  return (
    <Link href={href} className={styles.metric}>
      <div>
        <span>{label}</span>
        <span aria-hidden="true">↗</span>
      </div>
      <strong className={content === 'Unavailable' ? styles.unavailable : ''}>{content}</strong>
      <small>{caption}</small>
    </Link>
  );
}

function State({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.state} role="status">
      {children}
    </div>
  );
}
