'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

interface DriveWatchState {
  channel_id?: string;
  resource_id?: string;
  /** Channel expiry as returned by Google (epoch milliseconds string). */
  expiration?: string | null;
}

interface IntegrationStatusState {
  connected: boolean;
  provider: string;
  tenant_id: string;
  status: string;
  scopes: string[];
  needs_reconnect?: boolean;
  last_error?: string | null;
  token_expires_at?: string | null;
  updated_at?: string | null;
  watch?: DriveWatchState | null;
}

/** True when the user must reconnect (EXPIRED/REVOKED or past expiry). */
function needsReconnect(status: IntegrationStatusState | null): boolean {
  if (!status) return false;
  if (status.needs_reconnect === true) return true;
  const upper = (status.status || '').toUpperCase();
  if (upper === 'EXPIRED' || upper === 'REVOKED') return true;
  if (status.connected && status.token_expires_at) {
    return Date.parse(status.token_expires_at) <= Date.now();
  }
  return false;
}

/** True when the token expires within 24h (early warning, still connected). */
function isExpiringSoon(status: IntegrationStatusState | null): boolean {
  if (!status?.connected || needsReconnect(status) || !status.token_expires_at) {
    return false;
  }
  return Date.parse(status.token_expires_at) - Date.now() <= 24 * 60 * 60 * 1000;
}

/** True when a sync failure means the OAuth token needs a reconnect. */
function isReconnectError(detail: string): boolean {
  const lower = (detail || '').toLowerCase();
  return (
    lower.includes('reconnect') ||
    lower.includes('expired') ||
    lower.includes('revoked') ||
    lower.includes('invalid_grant') ||
    lower.includes('401')
  );
}

/** Render a Drive watch expiry (epoch ms string or ISO) as a local string. */
function formatWatchExpiry(expiration?: string | null): string | null {
  if (!expiration) return null;
  const ms = Number(expiration);
  const date = Number.isFinite(ms) ? new Date(ms) : new Date(expiration);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString();
}

/** Fallback status used when an integration status request fails. */
function disconnectedIntegration(
  provider: string,
  tenantId: string
): IntegrationStatusState {
  return {
    connected: false,
    provider,
    tenant_id: tenantId,
    status: 'DISCONNECTED',
    scopes: [],
  };
}

export default function IntegrationsPage() {
  const [rampStatus, setRampStatus] = useState<IntegrationStatusState | null>(null);
  const [oktaStatus, setOktaStatus] = useState<IntegrationStatusState | null>(null);
  const [driveStatus, setDriveStatus] = useState<IntegrationStatusState | null>(null);
  const [isLoadingStatus, setIsLoadingStatus] = useState<boolean>(true);
  const [isConnecting, setIsConnecting] = useState<boolean>(false);
  const [connectingProvider, setConnectingProvider] = useState<'ramp' | 'okta' | 'drive' | null>(null);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [rampDateFrom, setRampDateFrom] = useState<string>(''); // YYYY-MM-DD
  const [oktaSince, setOktaSince] = useState<string>('');       // YYYY-MM-DD → converted to ISO
  const [syncFeedback, setSyncFeedback] = useState<string | null>(null);
  const [bannerNotice, setBannerNotice] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  // Guard so a single OAuth return kicks off the initial full Drive import once.
  const driveInitialImportStarted = useRef<boolean>(false);

  const tenantId = 'default-org';

  const monthsAgo = (m: number) => {
    const d = new Date(); d.setMonth(d.getMonth() - m);
    return d.toISOString().slice(0, 10);
  };
  const todayStr = () => new Date().toISOString().slice(0, 10);

  // Fetch current integration statuses (Ramp + Okta + Google Drive)
  const checkStatus = useCallback(async () => {
    setIsLoadingStatus(true);
    try {
      const [rampRes, oktaRes, driveRes] = await Promise.all([
        fetch(`/api/v1/integrations/ramp/status?tenant_id=${tenantId}`),
        fetch(`/api/v1/integrations/okta/status?tenant_id=${tenantId}`),
        fetch(`/api/v1/integrations/google-drive/status?tenant_id=${tenantId}`),
      ]);
      setRampStatus(rampRes.ok ? await rampRes.json() : disconnectedIntegration('ramp', tenantId));
      setOktaStatus(oktaRes.ok ? await oktaRes.json() : disconnectedIntegration('okta', tenantId));
      setDriveStatus(driveRes.ok ? await driveRes.json() : disconnectedIntegration('google-drive', tenantId));
    } catch {
      setRampStatus(disconnectedIntegration('ramp', tenantId));
      setOktaStatus(disconnectedIntegration('okta', tenantId));
      setDriveStatus(disconnectedIntegration('google-drive', tenantId));
    } finally {
      setIsLoadingStatus(false);
    }
  }, [tenantId]);

  useEffect(() => {
    // Mount-time status fetch legitimately writes fetched state; this effect
    // owns the external-system sync.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void checkStatus();
  }, [checkStatus]);

  // Handle Connect to Ramp: fetch the authorization URL, then go
  // straight to Ramp (same as Okta below).
  const handleConnectRamp = async () => {
    await handleConnectProvider('ramp', '/api/v1/integrations/ramp/connect', 'Ramp');
  };

  // Handle Connect to Okta: fetch the authorization URL, then go straight
  // to Okta's hosted authorize page (login + consent), like Ramp.
  const handleConnectOkta = async () => {
    await handleConnectProvider('okta', '/api/v1/integrations/okta/connect', 'Okta');
  };

  // Handle Connect to Google Drive: same OAuth-connect flow as Ramp/Okta.
  const handleConnectDrive = async () => {
    await handleConnectProvider('drive', '/api/v1/integrations/google-drive/connect', 'Google Drive');
  };

  // Shared OAuth-connect flow: POST connect -> redirect to the provider's
  // real authorize page. No intermediate step: the provider itself asks
  // the user to sign in and approve access.
  const handleConnectProvider = async (
    provider: 'ramp' | 'okta' | 'drive',
    connectUrl: string,
    label: string
  ) => {
    setIsConnecting(true);
    setConnectingProvider(provider);
    setBannerNotice(null);
    try {
      const res = await fetch(connectUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: tenantId }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Server returned ${res.status}`);
      }

      const data = await res.json();
      if (data.authorization_url) {
        // Go straight to the provider's authorize page.
        window.location.href = data.authorization_url;
      } else {
        throw new Error('No authorization URL returned from ingestion service');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setBannerNotice({
        type: 'error',
        message: `Unable to initiate ${label} connection: ${message}`,
      });
      setIsConnecting(false);
      setConnectingProvider(null);
    }
  };

  // Google Drive sync. `fullSync` triggers the initial/first-load import
  // (re-seeds the change cursor and lists existing files); otherwise only
  // the incremental `changes.list` stream since the last checkpoint is pulled.
  const triggerDriveSync = useCallback(
    async (fullSync: boolean, options?: { clearBanner?: boolean }) => {
      if (options?.clearBanner !== false) setBannerNotice(null);
      setIsSyncing(true);
      setSyncFeedback(null);
      try {
        const res = await fetch('/api/v1/sync/google-drive', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tenant_id: tenantId, full_sync: fullSync }),
        });
        const data = await res.json().catch(() => ({}));
        const label = fullSync ? 'Google Drive full import' : 'Google Drive incremental sync';
        if (res.ok) {
          setSyncFeedback(
            data.deduped
              ? `${label} already running (Job: ${data.sync_id})`
              : `${label} started (Job: ${data.sync_id || 'queued'})`
          );
        } else if (res.status === 409 && isReconnectError(data.detail || '')) {
          setBannerNotice({
            type: 'error',
            message: `Google Drive sync blocked: ${data.detail}. Click Reconnect on the Drive card below, then retry.`,
          });
          setSyncFeedback('Google Drive sync blocked: reconnect required.');
        } else {
          setSyncFeedback(`Google Drive sync failed: ${data.detail || res.statusText}`);
        }
        void checkStatus();
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setSyncFeedback(`Google Drive sync error: ${message}`);
      } finally {
        setIsSyncing(false);
      }
    },
    [tenantId, checkStatus]
  );

  // Check URL query parameters on return from the OAuth callback.
  //
  // On the first successful Google Drive connection we kick off the initial
  // full import automatically; once connected, new/updated Drive files flow in
  // through the incremental `changes.list` cursor (push watch + Sync Now).
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const statusParam = params.get('status');
    const providerParam = params.get('provider');
    const messageParam = params.get('message');

    const providerLabel =
      providerParam === 'okta' ? 'Okta' : providerParam === 'google-drive' ? 'Google Drive' : 'Ramp';
    if (statusParam === 'connected' && providerParam) {
      const isDrive = providerParam === 'google-drive';
      // Reading the OAuth callback query string is an external-system sync;
      // the notice reflects the one-time redirect result.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setBannerNotice({
        type: 'success',
        message: isDrive
          ? `${providerLabel} successfully connected! A full import of your Drive documents has started.`
          : `${providerLabel} successfully connected! Your access tokens are securely stored and encrypted.`,
      });
      // Clean up the URL query params without reloading
      window.history.replaceState({}, document.title, window.location.pathname);
      if (isDrive && !driveInitialImportStarted.current) {
        driveInitialImportStarted.current = true;
        void triggerDriveSync(true, { clearBanner: false });
      }
    } else if (statusParam === 'error') {
      setBannerNotice({
        type: 'error',
        message: `Failed to complete ${providerLabel} connection: ${messageParam || 'unknown error'}. Please try again.`,
      });
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, [triggerDriveSync]);

  // Single Sync Now for Ramp: schedules both entities sequentially and
  // reports one combined result instead of two separate buttons.
  // A 409 with a reconnect detail means the access token expired: surface a
  // reconnect banner instead of a generic "failed" line.
  const handleSyncRampNow = async () => {
    setIsSyncing(true);
    setSyncFeedback(null);
    setBannerNotice(null);
    const outcomes: string[] = [];
    try {
      for (const entity of ['card_transactions', 'bills'] as const) {
        const res = await fetch('/api/v1/sync/ramp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tenant_id: tenantId, entity }),
        });
        if (res.ok) {
          const data = await res.json();
          outcomes.push(`${entity.replace('_', ' ')} (Job: ${data.sync_id || 'queued'})`);
        } else {
          const err = await res.json().catch(() => ({}));
          const detail = err.detail || res.statusText;
          if (res.status === 409 && isReconnectError(detail)) {
            setBannerNotice({
              type: 'error',
              message: `Ramp sync blocked: ${detail}. Click Reconnect on the Ramp card below, then retry.`,
            });
            outcomes.push(`${entity.replace('_', ' ')} blocked: reconnect required`);
          } else {
            outcomes.push(`${entity.replace('_', ' ')} failed: ${detail}`);
          }
        }
      }
      setSyncFeedback(`Ramp sync scheduled: ${outcomes.join('; ')}`);
      void checkStatus();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setSyncFeedback(`Sync error: ${message}`);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleBackfillRamp = async () => {
    if (!rampDateFrom) { setSyncFeedback('Pick a "Fetch history since" date first.'); return; }
    if (rampDateFrom > todayStr()) { setSyncFeedback('Start date cannot be in the future.'); return; }
    // 24-mo guard
    const months = (Date.now() - new Date(rampDateFrom).getTime()) / (30.44*24*3600*1000);
    if (months > 24) { setSyncFeedback('Range exceeds 24 months — this may be a very large job. Narrow the window or use All.'); return; }
    setIsSyncing(true); setSyncFeedback(null);
    const outcomes: string[] = [];
    try {
      for (const entity of ['card_transactions', 'bills'] as const) {
        const res = await fetch('/api/v1/sync/ramp', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tenant_id: tenantId, entity, date_from: rampDateFrom, date_to: todayStr() }),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
          outcomes.push(data.deduped ? `${entity} already running (Job: ${data.sync_id})` : `${entity} backfill since ${rampDateFrom} (Job: ${data.sync_id})`);
        } else if (res.status === 409 && isReconnectError(data.detail || '')) {
          setBannerNotice({
            type: 'error',
            message: `Ramp backfill blocked: ${data.detail}. Click Reconnect on the Ramp card below, then retry.`,
          });
          outcomes.push(`${entity} blocked: reconnect required`);
        } else outcomes.push(`${entity} failed: ${data.detail || res.statusText}`);
      }
      setSyncFeedback(`Ramp backfill: ${outcomes.join('; ')}`);
      void checkStatus();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setSyncFeedback(`Backfill error: ${message}`);
    } finally { setIsSyncing(false); }
  };
  
  // Single Sync Now for Okta: pulls users/apps/logs in one batch request.
  const handleSyncOktaNow = async () => {
    setIsSyncing(true);
    setSyncFeedback(null);
    setBannerNotice(null);
    try {
      const res = await fetch('/api/v1/sync/okta', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: tenantId, entities: ['users', 'apps', 'logs'] }),
      });
      if (res.ok) {
        const data = await res.json();
        setSyncFeedback(`Okta sync scheduled for users, apps, logs (Job: ${data.sync_id || 'queued'})`);
      } else {
        const err = await res.json().catch(() => ({}));
        const detail = err.detail || res.statusText;
        if (res.status === 409 && isReconnectError(detail)) {
          setBannerNotice({
            type: 'error',
            message: `Okta sync blocked: ${detail}. Click Reconnect on the Okta card below, then retry.`,
          });
          setSyncFeedback('Okta sync blocked: reconnect required.');
        } else {
          setSyncFeedback(`Okta sync failed: ${detail}`);
        }
      }
      void checkStatus();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setSyncFeedback(`Sync error: ${message}`);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleBackfillOkta = async () => {
    if (!oktaSince) { setSyncFeedback('Pick a "Fetch history since" date first.'); return; }
    if (oktaSince > todayStr()) { setSyncFeedback('Start date cannot be in the future.'); return; }
    const months = (Date.now() - new Date(oktaSince).getTime()) / (30.44*24*3600*1000);
    if (months > 24) { setSyncFeedback('Range exceeds 24 months — this may be a very large job. Narrow the window.'); return; }
    setIsSyncing(true);
    setSyncFeedback(null);
    try {
      const res = await fetch('/api/v1/sync/okta', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant_id: tenantId,
          entities: ['users', 'apps', 'logs'],
          since: new Date(oktaSince).toISOString(),
          until: new Date().toISOString(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setSyncFeedback(data.deduped
          ? `Okta backfill already running (Job: ${data.sync_id})`
          : `Okta backfill since ${oktaSince} for users, apps, logs (Job: ${data.sync_id})`);
      } else if (res.status === 409 && isReconnectError(data.detail || '')) {
        setBannerNotice({
          type: 'error',
          message: `Okta backfill blocked: ${data.detail}. Click Reconnect on the Okta card below, then retry.`,
        });
        setSyncFeedback('Okta backfill blocked: reconnect required.');
      } else {
        setSyncFeedback(`Okta backfill failed: ${data.detail || res.statusText}`);
      }
      void checkStatus();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setSyncFeedback(`Backfill error: ${message}`);
    } finally {
      setIsSyncing(false);
    }
  };


  const rampNeedsReconnect = needsReconnect(rampStatus);
  const oktaNeedsReconnect = needsReconnect(oktaStatus);
  const driveNeedsReconnect = needsReconnect(driveStatus);
  const rampExpiringSoon = isExpiringSoon(rampStatus);
  const oktaExpiringSoon = isExpiringSoon(oktaStatus);
  const driveExpiringSoon = isExpiringSoon(driveStatus);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '1100px' }}>
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Data Ingestion & Integrations
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '13.5px', marginTop: '3px' }}>
          Manage corporate card feeds, accounts payable bills, and external data pipelines.
        </p>
      </div>

      {bannerNotice && (
        <div
          style={{
            padding: '14px 18px',
            borderRadius: 'var(--radius-md)',
            backgroundColor: bannerNotice.type === 'success' ? 'var(--color-success-subtle)' : 'var(--color-danger-subtle)',
            border: `1px solid ${bannerNotice.type === 'success' ? 'var(--color-success-border)' : 'var(--color-danger-border)'}`,
            color: bannerNotice.type === 'success' ? 'var(--color-success)' : 'var(--color-danger)',
            fontSize: '13.5px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>{bannerNotice.message}</span>
          <button
            onClick={() => setBannerNotice(null)}
            style={{
              background: 'none',
              border: 'none',
              color: 'inherit',
              cursor: 'pointer',
              fontWeight: 700,
              fontSize: '16px',
            }}
          >
            ×
          </button>
        </div>
      )}

      {syncFeedback && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            backgroundColor: 'var(--bg-surface-tint)',
            border: '1px solid var(--border-subtle)',
            color: 'var(--text-primary)',
            fontSize: '13px',
          }}
        >
          {syncFeedback}
        </div>
      )}

      <div
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border-subtle)',
          padding: '24px',
          boxShadow: 'var(--shadow-sm)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <div>
            <h2 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Corporate Card & ERP Connectors
            </h2>
            <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              OAuth 2.0 and API keys for real-time spend audit and document extraction.
            </p>
          </div>
          <button
            onClick={checkStatus}
            disabled={isLoadingStatus}
            style={{
              padding: '6px 12px',
              fontSize: '12px',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              background: 'var(--bg-surface-hover)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              cursor: isLoadingStatus ? 'not-allowed' : 'pointer',
            }}
          >
            {isLoadingStatus ? 'Checking...' : 'Refresh Status'}
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '18px' }}>
          {/* RAMP CONNECTOR CARD */}
          <div
            style={{
              padding: '20px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--bg-surface-warm, #FFF9FA)',
              border: rampNeedsReconnect
                ? '1px solid var(--color-danger-border)'
                : rampStatus?.connected
                  ? '1px solid var(--color-success-border)'
                  : '1px solid var(--border-strong)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              gap: '14px',
            }}
          >
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontWeight: 700, fontSize: '15px', color: 'var(--text-primary)' }}>
                  Ramp Platform
                </span>
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    padding: '3px 9px',
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: rampNeedsReconnect
                      ? 'var(--color-danger-subtle)'
                      : rampStatus?.connected
                        ? 'var(--color-success-subtle)'
                        : 'var(--bg-surface-tint)',
                    color: rampNeedsReconnect ? 'var(--color-danger)' : rampStatus?.connected ? 'var(--color-success)' : 'var(--text-muted)',
                    border: `1px solid ${rampNeedsReconnect ? 'var(--color-danger-border)' : rampStatus?.connected ? 'var(--color-success-border)' : 'var(--border-subtle)'}`,
                  }}
                >
                  {isLoadingStatus
                    ? 'Loading...'
                    : rampNeedsReconnect
                      ? 'Expired — reconnect'
                      : rampStatus?.connected
                        ? 'Connected'
                        : 'Not Connected'}
                </span>
              </div>

              <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.45', margin: '0 0 12px 0' }}>
                Ingests corporate card transactions, spend trends, and accounts payable bills via Ramp API.
              </p>

              {rampNeedsReconnect && (
                <div
                  role="alert"
                  style={{
                    marginBottom: '12px',
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-md)',
                    backgroundColor: 'var(--color-danger-subtle)',
                    border: '1px solid var(--color-danger-border)',
                    color: 'var(--color-danger)',
                    fontSize: '12.5px',
                    lineHeight: '1.5',
                  }}
                >
                  <strong>Access token expired.</strong> Syncs are failing until you reconnect.
                  {rampStatus?.token_expires_at && (
                    <div style={{ marginTop: '2px' }}>
                      Expired: {new Date(rampStatus.token_expires_at).toLocaleString()}
                    </div>
                  )}
                  {rampStatus?.last_error && (
                    <div style={{ marginTop: '2px', fontSize: '11.5px', opacity: 0.9 }}>
                      {rampStatus.last_error}
                    </div>
                  )}
                </div>
              )}

              {!rampNeedsReconnect && rampStatus?.connected && rampStatus?.token_expires_at && (
                <div style={{ marginBottom: '12px', fontSize: '11.5px', color: rampExpiringSoon ? 'var(--color-warning)' : 'var(--text-muted)' }}>
                  {rampExpiringSoon ? 'Token expires soon' : 'Token expires'}: {new Date(rampStatus.token_expires_at).toLocaleString()}
                </div>
              )}

              {rampStatus?.connected && (
                <div style={{ marginBottom: '12px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                  <div>Scopes: <strong style={{ color: 'var(--text-primary)' }}>{rampStatus.scopes.join(', ') || 'transactions:read, bills:read'}</strong></div>
                  {rampStatus.updated_at && (
                    <div style={{ marginTop: '2px' }}>
                      Last synced: {new Date(rampStatus.updated_at).toLocaleDateString()} {new Date(rampStatus.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  )}
                  <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <label style={{ fontSize: '11.5px', fontWeight: 600 }}>Fetch history since (backfill)</label>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                      <input type="date" value={rampDateFrom} max={todayStr()}
                        onChange={(e) => setRampDateFrom(e.target.value)}
                        style={{ padding: '6px 8px', fontSize: '12px', borderRadius: '6px', border: '1px solid var(--border-subtle)' }} />
                      {[3, 6].map((m) => (
                        <button key={m} onClick={() => setRampDateFrom(monthsAgo(m))}
                          style={{ padding: '4px 8px', fontSize: '11px', fontWeight: 600, borderRadius: '6px', border: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', cursor: 'pointer' }}>
                          {m}M</button>
                      ))}
                      <button onClick={() => setRampDateFrom(monthsAgo(12))}
                        title="Default 12-month window"
                        style={{ padding: '4px 8px', fontSize: '11px', fontWeight: 700, borderRadius: '6px', border: '1px solid var(--border-subtle)', cursor: 'pointer' }}>12M ★</button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {!rampStatus?.connected && !rampNeedsReconnect ? (
                <button
                  onClick={handleConnectRamp}
                  disabled={isConnecting}
                  style={{
                    padding: '8px 16px',
                    fontSize: '13px',
                    fontWeight: 700,
                    color: '#FFFFFF',
                    backgroundColor: 'var(--color-brand)',
                    border: 'none',
                    borderRadius: 'var(--radius-md)',
                    cursor: isConnecting ? 'wait' : 'pointer',
                    transition: 'background-color 0.15s ease',
                  }}
                >
                  {isConnecting && connectingProvider === 'ramp' ? 'Redirecting to Ramp...' : 'Connect Ramp'}
                </button>
              ) : rampNeedsReconnect ? (
                <button
                  onClick={handleConnectRamp}
                  disabled={isConnecting}
                  style={{
                    padding: '8px 16px',
                    fontSize: '13px',
                    fontWeight: 700,
                    color: '#FFFFFF',
                    backgroundColor: 'var(--color-danger)',
                    border: 'none',
                    borderRadius: 'var(--radius-md)',
                    cursor: isConnecting ? 'wait' : 'pointer',
                    transition: 'background-color 0.15s ease',
                  }}
                >
                  {isConnecting && connectingProvider === 'ramp' ? 'Redirecting to Ramp...' : 'Reconnect Ramp now'}
                </button>
              ) : (
                <>
                  <button
                    onClick={handleSyncRampNow}
                    disabled={isSyncing}
                    style={{
                      padding: '7px 12px',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: 'var(--radius-md)',
                      cursor: isSyncing ? 'wait' : 'pointer',
                    }}
                  >
                    {isSyncing ? 'Syncing...' : 'Sync Now'}
                    </button>

                    <button onClick={handleBackfillRamp} disabled={isSyncing || !rampDateFrom} title={!rampDateFrom ? 'Pick a start date first' : `Backfill since ${rampDateFrom}`}
                      style={{
                        padding: '7px 12px',
                        fontSize: '12px',
                        fontWeight: 600,
                        color: 'var(--text-primary)',
                        backgroundColor: 'var(--bg-surface)',
                        border: '1px solid var(--border-strong)',
                        borderRadius: 'var(--radius-md)',
                        cursor: (isSyncing || !rampDateFrom) ? 'not-allowed' : 'pointer',
                        opacity: !rampDateFrom ? 0.5 : 1,
                      }}>
                      {isSyncing ? 'Working...' : 'Backfill'}
                    </button>
                  <button
                    onClick={handleConnectRamp}
                    disabled={isConnecting}
                    style={{
                      padding: '7px 12px',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      backgroundColor: 'transparent',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-md)',
                      cursor: isConnecting ? 'wait' : 'pointer',
                    }}
                  >
                    Reconnect
                  </button>
                </>
              )}
            </div>
          </div>

          {/* OKTA CARD */}
          <div
            style={{
              padding: '20px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--bg-surface-warm, #FFF9FA)',
              border: oktaNeedsReconnect
                ? '1px solid var(--color-danger-border)'
                : oktaStatus?.connected
                  ? '1px solid var(--color-success-border)'
                  : '1px solid var(--border-subtle)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              gap: '14px',
            }}
          >
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontWeight: 700, fontSize: '15px', color: 'var(--text-primary)' }}>
                  Okta Identity Cloud
                </span>
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    padding: '3px 9px',
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: oktaNeedsReconnect
                      ? 'var(--color-danger-subtle)'
                      : oktaStatus?.connected
                        ? 'var(--color-success-subtle)'
                        : 'var(--bg-surface-tint)',
                    color: oktaNeedsReconnect ? 'var(--color-danger)' : oktaStatus?.connected ? 'var(--color-success)' : 'var(--text-secondary)',
                    border: `1px solid ${oktaNeedsReconnect ? 'var(--color-danger-border)' : oktaStatus?.connected ? 'var(--color-success-border)' : 'var(--border-subtle)'}`,
                  }}
                >
                  {isLoadingStatus
                    ? 'Loading...'
                    : oktaNeedsReconnect
                      ? 'Expired — reconnect'
                      : oktaStatus?.connected
                        ? 'Connected'
                        : 'Not Connected'}
                </span>
              </div>
              <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.45', margin: '0 0 12px 0' }}>
                Synchronizing employee application assignments and user seat provisioning for zombie license detection.
              </p>

              {oktaNeedsReconnect && (
                <div
                  role="alert"
                  style={{
                    marginBottom: '12px',
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-md)',
                    backgroundColor: 'var(--color-danger-subtle)',
                    border: '1px solid var(--color-danger-border)',
                    color: 'var(--color-danger)',
                    fontSize: '12.5px',
                    lineHeight: '1.5',
                  }}
                >
                  <strong>Access token expired.</strong> Syncs are failing until you reconnect.
                  {oktaStatus?.token_expires_at && (
                    <div style={{ marginTop: '2px' }}>
                      Expired: {new Date(oktaStatus.token_expires_at).toLocaleString()}
                    </div>
                  )}
                  {oktaStatus?.last_error && (
                    <div style={{ marginTop: '2px', fontSize: '11.5px', opacity: 0.9 }}>
                      {oktaStatus.last_error}
                    </div>
                  )}
                </div>
              )}

              {!oktaNeedsReconnect && oktaStatus?.connected && oktaStatus?.token_expires_at && (
                <div style={{ marginBottom: '12px', fontSize: '11.5px', color: oktaExpiringSoon ? 'var(--color-warning)' : 'var(--text-muted)' }}>
                  {oktaExpiringSoon ? 'Token expires soon' : 'Token expires'}: {new Date(oktaStatus.token_expires_at).toLocaleString()}
                </div>
              )}

              {oktaStatus?.connected && (
                <div style={{ marginBottom: '12px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                  <div>Scopes: <strong style={{ color: 'var(--text-primary)' }}>{oktaStatus.scopes.join(', ') || 'openid, okta.users.read, okta.apps.read, okta.logs.read'}</strong></div>
                  {oktaStatus.updated_at && (
                    <div style={{ marginTop: '2px' }}>
                      Last synced: {new Date(oktaStatus.updated_at).toLocaleDateString()} {new Date(oktaStatus.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  )}
                  <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <label style={{ fontSize: '11.5px', fontWeight: 600 }}>Fetch history since (backfill)</label>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                      <input type="date" value={oktaSince} max={todayStr()}
                        onChange={(e) => setOktaSince(e.target.value)}
                        style={{ padding: '6px 8px', fontSize: '12px', borderRadius: '6px', border: '1px solid var(--border-subtle)' }} />
                      {[3, 6].map((m) => (
                        <button key={m} onClick={() => setOktaSince(monthsAgo(m))}
                          style={{ padding: '4px 8px', fontSize: '11px', fontWeight: 600, borderRadius: '6px', border: '1px solid var(--border-subtle)', background: 'var(--bg-surface)', cursor: 'pointer' }}>
                          {m}M</button>
                      ))}
                      <button onClick={() => setOktaSince(monthsAgo(12))}
                        title="Default 12-month window"
                        style={{ padding: '4px 8px', fontSize: '11px', fontWeight: 700, borderRadius: '6px', border: '1px solid var(--border-subtle)', cursor: 'pointer' }}>12M ★</button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {!oktaStatus?.connected && !oktaNeedsReconnect ? (
                <button
                  onClick={handleConnectOkta}
                  disabled={isConnecting}
                  style={{
                    padding: '8px 16px',
                    fontSize: '13px',
                    fontWeight: 700,
                    color: '#FFFFFF',
                    backgroundColor: 'var(--color-brand)',
                    border: 'none',
                    borderRadius: 'var(--radius-md)',
                    cursor: isConnecting ? 'wait' : 'pointer',
                    transition: 'background-color 0.15s ease',
                  }}
                >
                  {isConnecting && connectingProvider === 'okta' ? 'Redirecting to Okta...' : 'Connect Okta'}
                </button>
              ) : oktaNeedsReconnect ? (
                <button
                  onClick={handleConnectOkta}
                  disabled={isConnecting}
                  style={{
                    padding: '8px 16px',
                    fontSize: '13px',
                    fontWeight: 700,
                    color: '#FFFFFF',
                    backgroundColor: 'var(--color-danger)',
                    border: 'none',
                    borderRadius: 'var(--radius-md)',
                    cursor: isConnecting ? 'wait' : 'pointer',
                    transition: 'background-color 0.15s ease',
                  }}
                >
                  {isConnecting && connectingProvider === 'okta' ? 'Redirecting to Okta...' : 'Reconnect Okta now'}
                </button>
              ) : (
                <>
                  <button
                    onClick={handleSyncOktaNow}
                    disabled={isSyncing}
                    style={{
                      padding: '7px 12px',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: 'var(--radius-md)',
                      cursor: isSyncing ? 'wait' : 'pointer',
                    }}
                  >
                    {isSyncing ? 'Syncing...' : 'Sync Now'}
                  </button>
                  <button onClick={handleBackfillOkta} disabled={isSyncing || !oktaSince} title={!oktaSince ? 'Pick a start date first' : `Backfill since ${oktaSince}`}
                    style={{
                      padding: '7px 12px',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: 'var(--radius-md)',
                      cursor: (isSyncing || !oktaSince) ? 'not-allowed' : 'pointer',
                      opacity: !oktaSince ? 0.5 : 1,
                    }}>
                    {isSyncing ? 'Working...' : 'Backfill'}
                  </button>
                  <button
                    onClick={handleConnectOkta}
                    disabled={isConnecting}
                    style={{
                      padding: '7px 12px',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      backgroundColor: 'transparent',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-md)',
                      cursor: isConnecting ? 'wait' : 'pointer',
                    }}
                  >
                    Reconnect
                  </button>
                </>
              )}
            </div>
          </div>

          {/* GOOGLE DRIVE CARD */}
          <div
            style={{
              padding: '20px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--bg-surface-warm, #FFF9FA)',
              border: driveNeedsReconnect
                ? '1px solid var(--color-danger-border)'
                : driveStatus?.connected
                  ? '1px solid var(--color-success-border)'
                  : '1px solid var(--border-subtle)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              gap: '14px',
            }}
          >
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontWeight: 700, fontSize: '15px', color: 'var(--text-primary)' }}>
                  Google Drive / Cloud Storage
                </span>
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    padding: '3px 9px',
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: driveNeedsReconnect
                      ? 'var(--color-danger-subtle)'
                      : driveStatus?.connected
                        ? 'var(--color-success-subtle)'
                        : 'var(--bg-surface-tint)',
                    color: driveNeedsReconnect ? 'var(--color-danger)' : driveStatus?.connected ? 'var(--color-success)' : 'var(--text-secondary)',
                    border: `1px solid ${driveNeedsReconnect ? 'var(--color-danger-border)' : driveStatus?.connected ? 'var(--color-success-border)' : 'var(--border-subtle)'}`,
                  }}
                >
                  {isLoadingStatus
                    ? 'Loading...'
                    : driveNeedsReconnect
                      ? 'Expired — reconnect'
                      : driveStatus?.connected
                        ? 'Connected'
                        : 'Not Connected'}
                </span>
              </div>
              <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.45', margin: '0 0 12px 0' }}>
                Automated ingress folder listener for vendor order forms, service contracts, and invoices.
              </p>

              {driveNeedsReconnect && (
                <div
                  role="alert"
                  style={{
                    marginBottom: '12px',
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-md)',
                    backgroundColor: 'var(--color-danger-subtle)',
                    border: '1px solid var(--color-danger-border)',
                    color: 'var(--color-danger)',
                    fontSize: '12.5px',
                    lineHeight: '1.5',
                  }}
                >
                  <strong>Access token expired.</strong> Syncs are failing until you reconnect.
                  {driveStatus?.token_expires_at && (
                    <div style={{ marginTop: '2px' }}>
                      Expired: {new Date(driveStatus.token_expires_at).toLocaleString()}
                    </div>
                  )}
                  {driveStatus?.last_error && (
                    <div style={{ marginTop: '2px', fontSize: '11.5px', opacity: 0.9 }}>
                      {driveStatus.last_error}
                    </div>
                  )}
                </div>
              )}

              {!driveNeedsReconnect && driveStatus?.connected && driveStatus?.token_expires_at && (
                <div style={{ marginBottom: '12px', fontSize: '11.5px', color: driveExpiringSoon ? 'var(--color-warning)' : 'var(--text-muted)' }}>
                  {driveExpiringSoon ? 'Token expires soon' : 'Token expires'}: {new Date(driveStatus.token_expires_at).toLocaleString()}
                </div>
              )}

              {driveStatus?.connected && (
                <div style={{ marginBottom: '12px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                  <div>Scopes: <strong style={{ color: 'var(--text-primary)' }}>{driveStatus.scopes.join(', ') || 'drive.readonly'}</strong></div>
                  <div style={{ marginTop: '4px' }}>
                    Push watch:{' '}
                    <strong style={{ color: 'var(--text-primary)' }}>
                      {formatWatchExpiry(driveStatus.watch?.expiration)
                        ? `active until ${formatWatchExpiry(driveStatus.watch?.expiration)}`
                        : 'not registered (pull sync active)'}
                    </strong>
                  </div>
                  {driveStatus.updated_at && (
                    <div style={{ marginTop: '2px' }}>
                      Last synced: {new Date(driveStatus.updated_at).toLocaleDateString()} {new Date(driveStatus.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  )}
                  <div
                    style={{
                      marginTop: '10px',
                      padding: '8px 10px',
                      borderRadius: 'var(--radius-md)',
                      backgroundColor: 'var(--bg-surface-tint)',
                      border: '1px solid var(--border-subtle)',
                      lineHeight: '1.45',
                    }}
                  >
                    The first connection runs a <strong style={{ color: 'var(--text-primary)' }}>full import</strong> of your Drive
                    documents automatically. New or updated files afterwards are pulled
                    <strong style={{ color: 'var(--text-primary)' }}> incrementally</strong>.
                  </div>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {!driveStatus?.connected && !driveNeedsReconnect ? (
                <button
                  onClick={handleConnectDrive}
                  disabled={isConnecting}
                  style={{
                    padding: '8px 16px',
                    fontSize: '13px',
                    fontWeight: 700,
                    color: '#FFFFFF',
                    backgroundColor: 'var(--color-brand)',
                    border: 'none',
                    borderRadius: 'var(--radius-md)',
                    cursor: isConnecting ? 'wait' : 'pointer',
                    transition: 'background-color 0.15s ease',
                  }}
                >
                  {isConnecting && connectingProvider === 'drive' ? 'Redirecting to Google Drive...' : 'Connect Google Drive'}
                </button>
              ) : driveNeedsReconnect ? (
                <button
                  onClick={handleConnectDrive}
                  disabled={isConnecting}
                  style={{
                    padding: '8px 16px',
                    fontSize: '13px',
                    fontWeight: 700,
                    color: '#FFFFFF',
                    backgroundColor: 'var(--color-danger)',
                    border: 'none',
                    borderRadius: 'var(--radius-md)',
                    cursor: isConnecting ? 'wait' : 'pointer',
                    transition: 'background-color 0.15s ease',
                  }}
                >
                  {isConnecting && connectingProvider === 'drive' ? 'Redirecting to Google Drive...' : 'Reconnect Google Drive now'}
                </button>
              ) : (
                <>
                  <button
                    onClick={() => void triggerDriveSync(false)}
                    disabled={isSyncing}
                    title="Pull new and updated Drive files since the last checkpoint"
                    style={{
                      padding: '7px 12px',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: 'var(--radius-md)',
                      cursor: isSyncing ? 'wait' : 'pointer',
                    }}
                  >
                    {isSyncing ? 'Syncing...' : 'Sync Now'}
                  </button>
                  <button
                    onClick={() => void triggerDriveSync(true)}
                    disabled={isSyncing}
                    title="Re-run the full Drive import (lists all files again)"
                    style={{
                      padding: '7px 12px',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: 'var(--radius-md)',
                      cursor: isSyncing ? 'wait' : 'pointer',
                    }}
                  >
                    {isSyncing ? 'Working...' : 'Full Import'}
                  </button>
                  <button
                    onClick={handleConnectDrive}
                    disabled={isConnecting}
                    style={{
                      padding: '7px 12px',
                      fontSize: '12px',
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      backgroundColor: 'transparent',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-md)',
                      cursor: isConnecting ? 'wait' : 'pointer',
                    }}
                  >
                    Reconnect
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
