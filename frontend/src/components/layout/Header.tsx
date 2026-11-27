'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useLayout } from '@/contexts/LayoutContext';
import { useApi } from '@/lib/api';
import type { PersistedSeatForecast, UpcomingRenewal, Vendor } from '@/types';
import styles from './Header.module.css';

const ORGANIZATION_NAME = process.env.NEXT_PUBLIC_ORGANIZATION_NAME || 'Zellovest';

const PAGES = [
  { label: 'Overview', href: '/', description: 'Procurement dashboard' },
  { label: 'Vendor 360', href: '/vendors', description: 'Vendor spend, contracts and invoices' },
  { label: 'Documents', href: '/documents', description: 'Search procurement documents' },
  { label: 'AP Audit', href: '/compliance', description: 'Invoice exceptions and reconciliation' },
  { label: 'Decentralized Spend', href: '/maverick-spend', description: 'Off-contract purchases' },
  { label: 'License forecasting', href: '/licenses', description: 'Seat recommendations and savings' },
  { label: 'Renewals', href: '/renewals', description: 'Renewal dates and notice deadlines' },
  { label: 'Investigation Agent', href: '/assistant', description: 'Ask the procurement assistant' },
  { label: 'Data Ingestion', href: '/integrations', description: 'Connected data sources' },
  { label: 'Upload Documents', href: '/upload', description: 'Add contracts and invoices' },
  { label: 'Settings', href: '/settings', description: 'Organization and account settings' },
];

type HeaderAction = {
  id: string;
  title: string;
  detail: string;
  href: string;
  kind: 'renewal' | 'forecast' | 'decision';
  urgency: number;
};

/** Shared workspace header with global search and data-backed procurement actions. */
export function Header() {
  const { user, logout } = useAuth();
  const {
    isSidebarCollapsed,
    toggleSidebar,
    toggleMobileSidebar,
    setSidebarCollapsed,
  } = useLayout();
  const api = useApi();
  const router = useRouter();
  const rootRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [isActionCenterOpen, setIsActionCenterOpen] = useState(false);
  const [actions, setActions] = useState<HeaderAction[]>([]);
  const [isLoadingActions, setIsLoadingActions] = useState(false);
  const [actionError, setActionError] = useState('');
  const [actionsLoaded, setActionsLoaded] = useState(false);

  const matchingPages = useMemo(() => {
    const query = search.trim().toLowerCase();
    return PAGES.filter((page) => !query || `${page.label} ${page.description}`.toLowerCase().includes(query));
  }, [search]);

  const searchVendors = useCallback(async (query: string) => {
    setIsSearching(true);
    setSearchError('');
    try {
      const result = await api.vendors.list({ search: query, page: 1, pageSize: 6 });
      setVendors(result.vendors ?? []);
    } catch {
      setVendors([]);
      setSearchError('Vendor search is temporarily unavailable. You can still search app sections.');
    } finally {
      setIsSearching(false);
    }
  }, [api]);

  useEffect(() => {
    const query = search.trim();
    if (!isSearchOpen || query.length < 2) return;
    const timer = window.setTimeout(() => void searchVendors(query), 240);
    return () => window.clearTimeout(timer);
  }, [isSearchOpen, search, searchVendors]);

  useEffect(() => {
    const handleGlobalKeys = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setIsSearchOpen(true);
        setIsActionCenterOpen(false);
        window.requestAnimationFrame(() => searchInputRef.current?.focus());
      } else if (event.key === 'Escape') {
        setIsSearchOpen(false);
        setIsActionCenterOpen(false);
      }
    };
    const handleOutsideClick = (event: MouseEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) {
        setIsSearchOpen(false);
        setIsActionCenterOpen(false);
        setIsUserMenuOpen(false);
      }
    };
    window.addEventListener('keydown', handleGlobalKeys);
    document.addEventListener('mousedown', handleOutsideClick);
    return () => {
      window.removeEventListener('keydown', handleGlobalKeys);
      document.removeEventListener('mousedown', handleOutsideClick);
    };
  }, []);

  const loadActions = useCallback(async () => {
    setIsLoadingActions(true);
    setActionError('');
    const [feedResult, renewalResult, forecastResult] = await Promise.allSettled([
      api.decisionFeed.get({ status: 'pending_review', limit: 6, auto_hydrate: false }),
      api.negotiation.upcomingRenewals({ days_ahead: 120 }),
      api.negotiation.seatForecasts(),
    ]);
    const nextActions: HeaderAction[] = [];
    if (feedResult.status === 'fulfilled') {
      feedResult.value.items.slice(0, 5).forEach((packet, idx) => {
        const href =
          packet.packet_type === 'renewal_dossier'
            ? `/renewals?search=${encodeURIComponent(String(packet.payload?.vendor_name || ''))}&contract=${encodeURIComponent(packet.entity_id)}`
            : packet.packet_type === 'maverick_review'
              ? '/maverick-spend'
              : '/compliance';
        nextActions.push({
          id: `packet:${packet.id}`,
          title: packet.title,
          detail: packet.recommended_action || packet.summary,
          href,
          kind: 'decision',
          urgency: idx - 50,
        });
      });
    }
    if (renewalResult.status === 'fulfilled') {
      renewalResult.value
        .filter((renewal) => renewal.daysUntilRenewal <= 30 || renewal.isNoticeWindowActive)
        .sort((a, b) => Math.min(a.daysUntilRenewal, a.daysUntilNoticeDeadline) - Math.min(b.daysUntilRenewal, b.daysUntilNoticeDeadline))
        .slice(0, 5)
        .forEach((renewal) => {
          if (!nextActions.some((a) => a.id.includes(renewal.contractId))) {
            nextActions.push(renewalAction(renewal));
          }
        });
    }
    if (forecastResult.status === 'fulfilled') {
      latestForecasts(forecastResult.value)
        .filter((forecast) => forecast.recommended_seats < forecast.current_seats)
        .sort((a, b) => numeric(b.savings_estimate) - numeric(a.savings_estimate))
        .slice(0, 5)
        .forEach((forecast) => nextActions.push(forecastAction(forecast)));
    }
    nextActions.sort((a, b) => a.urgency - b.urgency);
    setActions(nextActions.slice(0, 8));
    setActionError(
      feedResult.status === 'rejected' &&
        renewalResult.status === 'rejected' &&
        forecastResult.status === 'rejected'
        ? 'Could not load procurement actions. Try again.'
        : ''
    );
    setActionsLoaded(true);
    setIsLoadingActions(false);
  }, [api]);

  const toggleActionCenter = () => {
    setIsActionCenterOpen((open) => !open);
    setIsSearchOpen(false);
    if (!actionsLoaded || actionError) void loadActions();
  };

  const navigate = (href: string) => {
    setIsSearchOpen(false);
    setIsActionCenterOpen(false);
    setSearch('');
    router.push(href);
  };

  const handleSignOut = () => {
    setIsUserMenuOpen(false);
    setIsSigningOut(true);
    void logout().finally(() => {
      setIsSigningOut(false);
      router.replace('/login');
    });
  };

  const chatPrompt = encodeURIComponent('Help me review the most important procurement actions, upcoming renewal deadlines, and license seat forecasts.');

  /** Toggles the desktop sidebar or opens and closes the mobile navigation drawer. */
  const handleSidebarToggle = () => {
    if (window.matchMedia('(max-width: 1023px)').matches) {
      if (isSidebarCollapsed) setSidebarCollapsed(false);
      toggleMobileSidebar();
      return;
    }

    toggleSidebar();
  };

  return (
    <header className={styles.header} ref={rootRef}>
      <div className={styles.left}>
        <button
          onClick={handleSidebarToggle}
          aria-label="Toggle navigation sidebar"
          aria-controls="navigation-sidebar"
          className={styles.iconButton}
        >
          <Icon name="menu" />
        </button>
      </div>

      <div className={styles.controls}>
        <div className={styles.searchWrap}>
          <label className={styles.searchBox}>
            <Icon name="search" />
            <input
              ref={searchInputRef}
              type="search"
              role="combobox"
              aria-label="Search vendors and workspace pages"
              aria-expanded={isSearchOpen}
              aria-controls="global-search-results"
              aria-autocomplete="list"
              placeholder="Search vendors, pages…"
              value={search}
              onFocus={() => { setIsSearchOpen(true); setIsActionCenterOpen(false); }}
              onChange={(event) => { setSearch(event.target.value); setVendors([]); setSearchError(''); }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  const vendor = vendors[0];
                  const page = matchingPages[0];
                  if (vendor && search.trim().length >= 2) navigate(`/vendors/${vendor.id}`);
                  else if (page) navigate(page.href);
                }
              }}
            />
            <kbd>Ctrl K</kbd>
          </label>
          {isSearchOpen && <div className={styles.popover} id="global-search-results" role="listbox" aria-label="Search results">
            <div className={styles.popoverLabel}>{search.trim().length < 2 ? 'QUICK LINKS' : 'WORKSPACE'}</div>
            {matchingPages.slice(0, 5).map((page) => <button key={page.href} className={styles.searchResult} role="option" aria-selected="false" onClick={() => navigate(page.href)}>
              <span className={styles.resultIcon}><Icon name="grid" /></span><span className={styles.resultText}><strong>{page.label}</strong><small>{page.description}</small></span><Icon name="arrow" />
            </button>)}
            {search.trim().length >= 2 && <>
              {isSearching && <p className={styles.panelMessage}>Searching vendors…</p>}
              {!isSearching && searchError && <p className={styles.panelMessage}>{searchError}</p>}
              {!isSearching && !searchError && vendors.map((vendor) => <button key={vendor.id} className={styles.searchResult} role="option" aria-selected="false" onClick={() => navigate(`/vendors/${vendor.id}`)}>
                <span className={styles.resultIcon}><Icon name="building" /></span><span className={styles.resultText}><strong>{vendor.canonicalName}</strong><small>{vendor.categories?.[0] || 'Vendor'} · {vendor.contractCount} contracts</small></span><Icon name="arrow" />
              </button>)}
              {!isSearching && !searchError && vendors.length === 0 && matchingPages.length === 0 && <p className={styles.panelMessage}>No vendors or pages match “{search}”.</p>}
            </>}
            <div className={styles.searchHint}>Press <kbd>Enter</kbd> to open the first result · <kbd>Esc</kbd> to close</div>
          </div>}
        </div>

        <button className={styles.iconButton} aria-label="Open procurement assistant" title="Ask the procurement assistant" onClick={() => navigate(`/assistant?prompt=${chatPrompt}`)}>
          <Icon name="message" />
        </button>

        <div className={styles.actionWrap}>
          <button className={styles.iconButton} aria-label="Procurement action center" aria-expanded={isActionCenterOpen} aria-controls="action-center" title="Renewal and license actions" onClick={toggleActionCenter}>
            <Icon name="bell" />
            {actions.length > 0 && <span className={styles.actionCount}>{actions.length > 9 ? '9+' : actions.length}</span>}
          </button>
          {isActionCenterOpen && <div className={`${styles.popover} ${styles.actionPopover}`} id="action-center" role="region" aria-label="Procurement action center">
            <div className={styles.actionHead}><div><span className={styles.popoverLabel}>ACTION CENTER</span><h2>Needs your attention</h2></div><div className={styles.actionTools}>{actions.length > 0 && <button className={styles.dismissButton} onClick={() => setActions([])}>Dismiss all</button>}<button className={styles.refreshButton} onClick={() => void loadActions()} disabled={isLoadingActions} aria-label="Refresh action items"><Icon name="refresh" /></button></div></div>
            {isLoadingActions && <p className={styles.panelMessage}>Checking renewal and license data…</p>}
            {!isLoadingActions && actionError && <div className={styles.panelMessage} role="alert">{actionError}<button className={styles.retryLink} onClick={() => void loadActions()}>Try again</button></div>}
            {!isLoadingActions && !actionError && actions.length === 0 && <div className={styles.emptyActions}><span className={styles.emptyCheck}>✓</span><strong>You’re up to date</strong><p>No urgent renewals or seat reduction recommendations were found in the current data.</p></div>}
            {!isLoadingActions && actions.length > 0 && <div className={styles.actionList}>{actions.map((action) => <button key={action.id} className={styles.actionItem} onClick={() => navigate(action.href)}>
              <span className={`${styles.actionMark} ${action.kind === 'renewal' ? styles.renewalMark : styles.forecastMark}`}><Icon name={action.kind === 'renewal' ? 'calendar' : action.kind === 'decision' ? 'bell' : 'users'} /></span><span className={styles.actionCopy}><strong>{action.title}</strong><small>{action.detail}</small><em>{action.kind === 'renewal' ? 'Review renewal' : action.kind === 'decision' ? 'Review decision' : 'Review forecast'} <Icon name="arrow" /></em></span>
            </button>)}</div>}
            <button className={styles.viewActions} onClick={() => navigate('/renewals')}>View renewals <Icon name="arrow" /></button>
          </div>}
        </div>

        <div className={styles.profileWrap}>
          <button className={styles.profileButton} onClick={() => setIsUserMenuOpen((open) => !open)} aria-expanded={isUserMenuOpen} aria-label="Account menu">
            <span className={styles.avatar}>{ORGANIZATION_NAME.charAt(0).toUpperCase()}</span><span className={styles.orgName}>{ORGANIZATION_NAME}</span>
            {user?.isDemo && <span className={styles.demoBadge}>DEMO</span>}
          </button>
          {isUserMenuOpen && <div className={`${styles.popover} ${styles.profileMenu}`}>
            <div className={styles.userInfo}><strong>{user?.name || 'Procurement User'}</strong><span>{user?.email}</span><small>{ORGANIZATION_NAME} · {user?.role || 'Procurement Team Member'}</small></div>
            <button className={styles.signOut} onClick={handleSignOut} disabled={isSigningOut}>{isSigningOut ? 'Signing out…' : 'Sign out'}</button>
          </div>}
        </div>
      </div>
    </header>
  );
}

function numeric(value: number | string | null | undefined): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function latestForecasts(rows: PersistedSeatForecast[]): PersistedSeatForecast[] {
  const latest = new Map<string, PersistedSeatForecast>();
  for (const row of rows) {
    const key = `${row.vendor_id}|${row.department ?? ''}|${row.retention_curve?.horizon_days ?? ''}`;
    const previous = latest.get(key);
    if (!previous || row.forecast_date > previous.forecast_date || (row.forecast_date === previous.forecast_date && row.created_at > previous.created_at)) latest.set(key, row);
  }
  return [...latest.values()];
}

function renewalAction(renewal: UpcomingRenewal): HeaderAction {
  const days = renewal.daysUntilRenewal;
  return {
    id: `renewal:${renewal.id}`,
    title: `${renewal.vendorName} renewal${days >= 0 ? ` in ${days} days` : ` is ${Math.abs(days)} days overdue`}`,
    detail: renewal.isNoticeWindowActive ? `Notice window is open · deadline ${renewal.noticeDeadlineDate}` : `Renewal date ${renewal.renewalDate}`,
    href: `/renewals?search=${encodeURIComponent(renewal.vendorName)}`,
    kind: 'renewal',
    urgency: Math.min(days, renewal.daysUntilNoticeDeadline),
  };
}

function forecastAction(forecast: PersistedSeatForecast): HeaderAction {
  const reduction = forecast.current_seats - forecast.recommended_seats;
  return {
    id: `forecast:${forecast.id}`,
    title: `${forecast.vendor_name}: ${reduction} fewer seats recommended`,
    detail: `${forecast.department || 'Unassigned'} · estimated savings ${numeric(forecast.savings_estimate).toLocaleString('en-US')}`,
    href: '/licenses',
    kind: 'forecast',
    urgency: 100 + Math.max(0, 100 - numeric(forecast.confidence) * 100),
  };
}

function Icon({ name }: { name: 'menu' | 'search' | 'message' | 'bell' | 'grid' | 'building' | 'arrow' | 'calendar' | 'users' | 'refresh' }) {
  const common = { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true as const };
  const shapes: Record<typeof name, React.ReactNode> = {
    menu: <><path d="M4 6h16M4 12h16M4 18h16" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
    message: <><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><path d="M8 10h8M8 13h5" /></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M10 21h4" /></>,
    grid: <><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></>,
    building: <><path d="M3 21h18M5 21V7l7-4 7 4v14M9 10h.01M15 10h.01M9 14h.01M15 14h.01M10 21v-4h4v4" /></>,
    arrow: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18" /></>,
    users: <><path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM20 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M5.6 9a7 7 0 0 1 11.55-2.6L20 12M4 12l2.85 5.6A7 7 0 0 0 18.4 15" /></>,
  };
  return <svg {...common}>{shapes[name]}</svg>;
}
