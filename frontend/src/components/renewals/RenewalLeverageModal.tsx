'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import { useAuth } from '@/contexts/AuthContext';
import { getLastBriefObjectives, readVendorBrief, setLastBriefObjectives } from '@/lib/negotiationBriefCache';
import { UpcomingRenewal, NegotiationBriefResponse, RenewalPreparationResponse, RAGSearchChunk } from '@/types';
import styles from './RenewalLeverageModal.module.css';

interface Props {
  renewal: UpcomingRenewal | null;
  isOpen: boolean;
  onClose: () => void;
  onLaunchRenewalAgent: (renewal: UpcomingRenewal) => void;
}

const money = (value: number | string | null | undefined) => {
  const number = Number(value);
  return value == null || !Number.isFinite(number) ? 'Not available' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(number);
};

/** Show a selected renewal, source passages and a configurable executive brief. */
export function RenewalLeverageModal({ renewal, isOpen, onClose, onLaunchRenewalAgent }: Props) {
  const api = useApi();
  const { notify } = useToast();
  const { user } = useAuth();
  const scope = user?.id ?? 'anonymous';
  const [prep, setPrep] = useState<RenewalPreparationResponse | null>(null);
  const [brief, setBrief] = useState<NegotiationBriefResponse | null>(null);
  const [prepError, setPrepError] = useState('');
  const [briefError, setBriefError] = useState('');
  const [loadingPrep, setLoadingPrep] = useState(true);
  const [loadingBrief, setLoadingBrief] = useState(true);
  const [objectives, setObjectives] = useState(() => renewal ? getLastBriefObjectives(scope, renewal.vendorId, renewal.contractId).join('\n') : '');
  const [query, setQuery] = useState('price escalation cap renewal notice');
  const [passages, setPassages] = useState<RAGSearchChunk[]>([]);
  const [searchState, setSearchState] = useState<'idle' | 'loading' | 'done'>('idle');
  const [searchError, setSearchError] = useState('');
  const [reminding, setReminding] = useState(false);
  const [reminder, setReminder] = useState('');
  const requestVersion = useRef(0);

  useEffect(() => {
    if (!isOpen || !renewal) return;
    const version = ++requestVersion.current;
    const data = { vendor_id: renewal.vendorId, contract_id: renewal.contractId };
    api.negotiation.renewalPrep(data).then((result) => {
      if (version === requestVersion.current) setPrep(result);
    }).catch((error: unknown) => {
      if (version === requestVersion.current) setPrepError(error instanceof Error ? error.message : 'Unable to load renewal preparation.');
    }).finally(() => { if (version === requestVersion.current) setLoadingPrep(false); });
    const savedObjectives = getLastBriefObjectives(scope, renewal.vendorId, renewal.contractId);
    readVendorBrief({ scope, vendor: renewal.vendorId, contract: renewal.contractId, objectives: savedObjectives,
      sourceVersion: () => api.negotiation.briefSourceVersion(renewal.vendorId),
      generate: () => api.negotiation.prepareBrief({ ...data, objectives: savedObjectives }),
    }).then((result) => {
      if (version === requestVersion.current) setBrief(result);
    }).catch((error: unknown) => {
      if (version === requestVersion.current) setBriefError(error instanceof Error ? error.message : 'Unable to generate the brief.');
    }).finally(() => { if (version === requestVersion.current) setLoadingBrief(false); });
    return () => { if (requestVersion.current === version) requestVersion.current = version + 1; };
  }, [isOpen, renewal, api, scope]);

  const generate = useCallback(async () => {
    if (!renewal) return;
    const version = requestVersion.current;
    setLoadingBrief(true); setBriefError('');
    try {
      const requestedObjectives = objectives.split('\n').map((item) => item.trim()).filter(Boolean);
      const result = await readVendorBrief({
        scope, vendor: renewal.vendorId, contract: renewal.contractId, objectives: requestedObjectives,
        sourceVersion: () => api.negotiation.briefSourceVersion(renewal.vendorId),
        generate: () => api.negotiation.prepareBrief({ vendor_id: renewal.vendorId, contract_id: renewal.contractId, objectives: requestedObjectives }),
        force: true,
      });
      setLastBriefObjectives(scope, renewal.vendorId, renewal.contractId, requestedObjectives);
      if (version === requestVersion.current) setBrief(result);
    } catch (error) {
      if (version === requestVersion.current) setBriefError(error instanceof Error ? error.message : 'Unable to generate the brief.');
    } finally { if (version === requestVersion.current) setLoadingBrief(false); }
  }, [renewal, objectives, api, scope]);

  if (!isOpen || !renewal) return null;

  const search = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    const version = requestVersion.current;
    setSearchState('loading'); setSearchError(''); setPassages([]);
    try {
      const result = await api.rag.search({ query: query.trim(), vendor_id: renewal.vendorId, limit: 5 });
      if (version === requestVersion.current) { setPassages(result.chunks || []); setSearchState('done'); }
    } catch (error) {
      if (version === requestVersion.current) { setSearchError(error instanceof Error ? error.message : 'Search failed.'); setSearchState('done'); }
    }
  };

  const schedule = async () => {
    setReminding(true);
    try {
      const result = await api.negotiation.createReminder({ contract_id: renewal.contractId, vendor_id: renewal.vendorId, remind_days_before_notice: 14 });
      setReminder(result.remind_date);
      notify.success('Reminder scheduled', `Reminder date: ${result.remind_date}`);
    } catch (error) { notify.error('Reminder failed', error instanceof Error ? error.message : 'Please try again.'); }
    finally { setReminding(false); }
  };

  const exportBrief = () => {
    if (!brief) return;
    const printWindow = window.open('', '_blank');
    if (!printWindow) { notify.error('Unable to open print preview', 'Allow pop-ups and try again.'); return; }
    const doc = printWindow.document;
    doc.title = `${renewal.vendorName} - Executive renewal brief`;
    const style = doc.createElement('style');
    style.textContent = 'body{font:13px/1.5 Arial,sans-serif;color:#23151a;margin:42px} h1{font-size:24px;color:#71091e} h2{font-size:15px;border-bottom:1px solid #ddd;padding-bottom:5px;margin-top:22px} li{margin:5px 0} blockquote{border-left:3px solid #ccc;margin:8px 0;padding-left:12px;color:#555} .meta{color:#555} @media print{body{margin:0} section{break-inside:avoid}}';
    doc.head.appendChild(style);
    const add = (tag: string, value: string, parent: HTMLElement = doc.body) => { const el = doc.createElement(tag); el.textContent = value; parent.appendChild(el); return el; };
    add('h1', `${renewal.vendorName} — Executive renewal brief`);
    add('p', `${renewal.productName} | ${renewal.contractNumber} | Renewal ${renewal.renewalDate}`);
    add('p', `Annual spend: ${money(renewal.annualSpend)} | YoY: ${renewal.spendYoYPct}% | Notice deadline: ${renewal.noticeDeadlineDate}`);
    add('p', `Timeline utilization: ${renewal.utilizationPct == null ? 'Not available' : `${renewal.utilizationPct}%`}${prep ? ` | Preparation reports ${prep.unused_licenses} unused licenses and ${money(prep.potential_savings)} potential savings` : ''}`);
    add('p', `Generated ${brief.generated_at}. Review recommendations and source documents before making decisions.`);
    const section = (title: string, items: string[]) => { const box = add('section', ''); add('h2', title, box); if (!items.length) add('p', 'Not available.', box); else { const list = add('ul', '', box); items.forEach((item) => add('li', item, list)); } };
    section('Renewal observations', renewal.keyLeveragePoints || []);
    section('Commercial position and leverage', brief.leverage_points || []);
    section('Recommended actions', brief.recommended_actions || []);
    section('Negotiation talking points', brief.talking_points || []);
    section('Risks and constraints', brief.risk_factors || []);
    const citations = brief.contractual_clauses?.length ? brief.contractual_clauses : (brief.clause_citations || []);
    const box = add('section', ''); add('h2', 'Supporting contract passages', box);
    if (!citations.length) add('p', 'No contract passages were returned for this brief.', box);
    citations.forEach((citation, index) => { add('p', `[${index + 1}] ${citation.filename || 'Document'}${citation.page != null ? `, page ${citation.page}` : ''}${citation.section ? `, ${citation.section}` : ''}${citation.document_id ? ` (ID: ${citation.document_id})` : ''}: ${citation.summary}`, box); if (citation.verbatim_excerpt) add('blockquote', citation.verbatim_excerpt, box); });
    printWindow.focus(); printWindow.print();
  };

  const citations = brief?.contractual_clauses?.length ? brief.contractual_clauses : (brief?.clause_citations || []);
  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="renewal-title" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => { if (event.key === 'Escape') onClose(); }}>
        <header className={styles.header}>
          <div><span className={styles.eyebrow}>RENEWAL PREPARATION</span><h2 id="renewal-title">{renewal.vendorName}</h2><p>{renewal.productName} · {renewal.contractNumber}</p></div>
          <button className={styles.close} onClick={onClose} aria-label="Close renewal preparation">×</button>
        </header>
        <div className={styles.body}>
          <div className={styles.metrics}>
            <Metric label="Annual spend" value={money(renewal.annualSpend)} detail={`${renewal.spendYoYPct > 0 ? '+' : ''}${renewal.spendYoYPct}% year over year`} />
            <Metric label="Renewal" value={renewal.renewalDate} detail={`${renewal.daysUntilRenewal} days until renewal`} />
            <Metric label="Notice deadline" value={renewal.noticeDeadlineDate} detail={renewal.daysUntilNoticeDeadline < 0 ? 'Deadline passed — confirm options' : `${renewal.daysUntilNoticeDeadline} days remaining`} />
            <Metric label="Utilization" value={renewal.utilizationPct == null ? 'Not available' : `${renewal.utilizationPct}%`} detail={prep ? `${prep.unused_licenses} unused licenses reported in preparation` : 'From renewal timeline'} />
          </div>
          <p className={styles.note}>Agent-generated figures and recommendations should be checked against the underlying records. Different data sources may report different utilization figures.</p>
          <div className={styles.columns}>
            <div className={styles.main}>
              <section className={styles.card}><div className={styles.sectionHead}><div><span className={styles.eyebrow}>COMMERCIAL CONTEXT</span><h3>Renewal overview</h3></div><span className={styles.tag}>{renewal.autoRenew ? 'Auto-renew' : 'Manual renewal'}</span></div>
                <p className={styles.muted}>{renewal.noticePeriodDays}-day notice period · {renewal.assignedOwner}</p>
                {renewal.keyLeveragePoints.length > 0 ? <ul className={styles.list}>{renewal.keyLeveragePoints.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p className={styles.muted}>No timeline observations returned.</p>}
                {renewal.autoRenew && <div className={styles.reminder}><span>{reminder ? `Reminder scheduled for ${reminder}` : 'Keep the notice deadline on your radar.'}</span><button className={styles.secondary} onClick={schedule} disabled={reminding || !!reminder || renewal.daysUntilNoticeDeadline <= 14}>{reminding ? 'Scheduling…' : reminder ? 'Scheduled' : 'Remind me 14 days before'}</button></div>}
                {renewal.autoRenew && renewal.daysUntilNoticeDeadline <= 14 && !reminder && <p className={styles.muted}>The 14-day reminder date has passed. Review the notice deadline now.</p>}
              </section>
              <section className={styles.card}><span className={styles.eyebrow}>RENEWAL AGENT</span><h3>Preparation and opportunities</h3>
                {loadingPrep ? <p className={styles.muted}>Preparing commercial indicators…</p> : prepError ? <p className={styles.error} role="alert">{prepError}</p> : prep && <><div className={styles.prepStats}><span>Unused licenses <strong>{prep.unused_licenses}</strong></span><span>Potential savings <strong>{money(prep.potential_savings)}</strong></span><span>Utilization <strong>{(prep.utilization_rate * 100).toFixed(1)}%</strong></span></div><h4>Potential negotiation levers</h4><List items={prep.negotiation_levers} /><h4>Constraints to verify</h4><List items={prep.contract_constraints} /></>}
              </section>
              <section className={styles.card}><div className={styles.sectionHead}><div><span className={styles.eyebrow}>EXECUTIVE BRIEF</span><h3>Negotiation strategy</h3></div><button className={styles.secondary} onClick={exportBrief} disabled={!brief || loadingBrief}>Export Brief to PDF</button></div>
                <label className={styles.label} htmlFor="renewal-objectives">Objectives <span>(optional, one per line)</span></label><textarea id="renewal-objectives" rows={2} value={objectives} onChange={(event) => setObjectives(event.target.value)} placeholder="e.g. Hold unit price or reduce unused seats" />
                <button className={styles.primary} onClick={generate} disabled={loadingBrief}>{loadingBrief ? 'Generating brief…' : brief ? 'Regenerate brief' : 'Generate brief'}</button>
                {briefError && <p className={styles.error} role="alert">{briefError}</p>}
                {brief && <div className={styles.brief}><p className={styles.muted}>Generated {new Date(brief.generated_at).toLocaleString()} · Recommendations for procurement review</p>{brief.executive_summary && <p>{brief.executive_summary}</p>}<h4>Commercial leverage</h4><List items={brief.leverage_points} /><h4>Recommended actions</h4><List items={brief.recommended_actions} /><h4>Talking points</h4><List items={brief.talking_points} /><h4>Risks and constraints</h4><List items={brief.risk_factors} /><h4>Supporting contract passages</h4>{citations.length ? citations.map((citation, i) => <article className={styles.citation} key={i}><strong>[{i + 1}] {citation.filename || citation.clause_type || 'Contract document'}</strong><span>{citation.page != null ? `Page ${citation.page}` : 'Page unavailable'}{citation.section ? ` · ${citation.section}` : ''}</span><p>{citation.summary}</p>{citation.verbatim_excerpt && <blockquote>{citation.verbatim_excerpt}</blockquote>}{citation.document_id && <Link href={`/documents/${encodeURIComponent(citation.document_id)}`}>View document ↗</Link>}</article>) : <p className={styles.muted}>No contract passages returned. Search vendor documents to investigate further.</p>}</div>}
              </section>
            </div>
            <aside className={styles.aside}><section className={styles.card}><span className={styles.eyebrow}>DOCUMENT RESEARCH</span><h3>Find contract evidence</h3><p className={styles.muted}>Search this vendor’s indexed documents for escalation caps, notice terms and other clauses.</p><form onSubmit={search}><label className={styles.label} htmlFor="renewal-search">Search passages</label><input id="renewal-search" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={500} /><button className={styles.primary} type="submit" disabled={!query.trim() || searchState === 'loading'}>{searchState === 'loading' ? 'Searching…' : 'Search documents'}</button></form>{searchError && <p className={styles.error} role="alert">{searchError}</p>}{searchState === 'done' && !searchError && passages.length === 0 && <p className={styles.muted}>No matching passages found.</p>}{passages.map((chunk) => <article className={styles.citation} key={chunk.chunk_id}><strong>{chunk.provenance?.filename || 'Vendor document'}</strong><span>{chunk.page != null ? `Page ${chunk.page}` : 'Page unavailable'}{chunk.section ? ` · ${chunk.section}` : ''}</span><p>{chunk.content}</p>{chunk.document_id && <Link href={`/documents/${encodeURIComponent(chunk.document_id)}`}>View document ↗</Link>}</article>)}</section><section className={styles.card}><h3>Continue the investigation</h3><p className={styles.muted}>Ask the copilot follow-up questions about this renewal.</p><button className={styles.secondary} onClick={() => onLaunchRenewalAgent(renewal)}>Open Ask AI →</button></section></aside>
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className={styles.metric}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function List({ items }: { items?: string[] }) {
  return items?.length ? <ul className={styles.list}>{items.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className={styles.muted}>No information returned.</p>;
}
