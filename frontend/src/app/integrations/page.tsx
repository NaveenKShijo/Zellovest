'use client';

import React, { useEffect, useState, useTransition } from 'react';

interface IntegrationStatusState {
  connected: boolean;
  provider: string;
  tenant_id: string;
  status: string;
  scopes: string[];
  token_expires_at?: string | null;
  updated_at?: string | null;
}

export default function IntegrationsPage() {
  const [rampStatus, setRampStatus] = useState<IntegrationStatusState | null>(null);
  const [oktaStatus, setOktaStatus] = useState<IntegrationStatusState | null>(null);
  const [isLoadingStatus, setIsLoadingStatus] = useState<boolean>(true);
  const [isConnecting, setIsConnecting] = useState<boolean>(false);
  const [connectingProvider, setConnectingProvider] = useState<'ramp' | 'okta' | null>(null);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [syncFeedback, setSyncFeedback] = useState<string | null>(null);
  const [bannerNotice, setBannerNotice] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const tenantId = 'default-org';

  // Check URL query parameters on return from OAuth callback
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const statusParam = params.get('status');
    const providerParam = params.get('provider');
    const messageParam = params.get('message');

    const providerLabel =
      providerParam === 'okta' ? 'Okta' : providerParam === 'google-drive' ? 'Google Drive' : 'Ramp';
    if (statusParam === 'connected' && providerParam) {
      setBannerNotice({
        type: 'success',
        message: `${providerLabel} successfully connected! Your access tokens are securely stored and encrypted.`,
      });
      // Clean up the URL query params without reloading
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (statusParam === 'error') {
      setBannerNotice({
        type: 'error',
        message: `Failed to complete ${providerLabel} connection: ${messageParam || 'unknown error'}. Please try again.`,
      });
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, []);

  const disconnectedState = (provider: string): IntegrationStatusState => ({
    connected: false,
    provider,
    tenant_id: tenantId,
    status: 'DISCONNECTED',
    scopes: [],
  });

  // Fetch current integration statuses (Ramp + Okta)
  const checkStatus = async () => {
    setIsLoadingStatus(true);
    try {
      const [rampRes, oktaRes] = await Promise.all([
        fetch(`/api/v1/integrations/ramp/status?tenant_id=${tenantId}`),
        fetch(`/api/v1/integrations/okta/status?tenant_id=${tenantId}`),
      ]);
      setRampStatus(rampRes.ok ? await rampRes.json() : disconnectedState('ramp'));
      setOktaStatus(oktaRes.ok ? await oktaRes.json() : disconnectedState('okta'));
    } catch {
      setRampStatus(disconnectedState('ramp'));
      setOktaStatus(disconnectedState('okta'));
    } finally {
      setIsLoadingStatus(false);
    }
  };

  useEffect(() => {
    checkStatus();
  }, []);

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

  // Shared OAuth-connect flow: POST connect -> redirect to the provider's
  // real authorize page. No intermediate step: the provider itself asks
  // the user to sign in and approve access.
  const handleConnectProvider = async (
    provider: 'ramp' | 'okta',
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
    } catch (err: any) {
      setBannerNotice({
        type: 'error',
        message: `Unable to initiate ${label} connection: ${err.message}`,
      });
      setIsConnecting(false);
      setConnectingProvider(null);
    }
  };

  // Single Sync Now for Ramp: schedules both entities sequentially and
  // reports one combined result instead of two separate buttons.
  const handleSyncRampNow = async () => {
    setIsSyncing(true);
    setSyncFeedback(null);
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
          outcomes.push(`${entity.replace('_', ' ')} failed: ${err.detail || res.statusText}`);
        }
      }
      setSyncFeedback(`Ramp sync scheduled: ${outcomes.join('; ')}`);
      void checkStatus();
    } catch (err: any) {
      setSyncFeedback(`Sync error: ${err.message}`);
    } finally {
      setIsSyncing(false);
    }
  };

  // Single Sync Now for Okta: pulls users/apps/logs in one batch request.
  const handleSyncOktaNow = async () => {
    setIsSyncing(true);
    setSyncFeedback(null);
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
        setSyncFeedback(`Okta sync failed: ${err.detail || res.statusText}`);
      }
      void checkStatus();
    } catch (err: any) {
      setSyncFeedback(`Sync error: ${err.message}`);
    } finally {
      setIsSyncing(false);
    }
  };

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
              border: rampStatus?.connected ? '1px solid var(--color-success-border)' : '1px solid var(--border-strong)',
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
                    backgroundColor: rampStatus?.connected ? 'var(--color-success-subtle)' : 'var(--bg-surface-tint)',
                    color: rampStatus?.connected ? 'var(--color-success)' : 'var(--text-muted)',
                    border: `1px solid ${rampStatus?.connected ? 'var(--color-success-border)' : 'var(--border-subtle)'}`,
                  }}
                >
                  {isLoadingStatus ? 'Loading...' : rampStatus?.connected ? 'Connected' : 'Not Connected'}
                </span>
              </div>

              <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.45', margin: '0 0 12px 0' }}>
                Ingests corporate card transactions, spend trends, and accounts payable bills via Ramp API.
              </p>

              {rampStatus?.connected && (
                <div style={{ marginBottom: '12px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                  <div>Scopes: <strong style={{ color: 'var(--text-primary)' }}>{rampStatus.scopes.join(', ') || 'transactions:read, bills:read'}</strong></div>
                  {rampStatus.updated_at && (
                    <div style={{ marginTop: '2px' }}>
                      Last synced: {new Date(rampStatus.updated_at).toLocaleDateString()} {new Date(rampStatus.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {!rampStatus?.connected ? (
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
              border: oktaStatus?.connected ? '1px solid var(--color-success-border)' : '1px solid var(--border-subtle)',
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
                    backgroundColor: oktaStatus?.connected ? 'var(--color-success-subtle)' : 'var(--bg-surface-tint)',
                    color: oktaStatus?.connected ? 'var(--color-success)' : 'var(--text-secondary)',
                    border: `1px solid ${oktaStatus?.connected ? 'var(--color-success-border)' : 'var(--border-subtle)'}`,
                  }}
                >
                  {isLoadingStatus ? 'Loading...' : oktaStatus?.connected ? 'Connected' : 'Not Connected'}
                </span>
              </div>
              <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.45', margin: '0 0 12px 0' }}>
                Synchronizing employee application assignments and user seat provisioning for zombie license detection.
              </p>

              {oktaStatus?.connected && (
                <div style={{ marginBottom: '12px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                  <div>Scopes: <strong style={{ color: 'var(--text-primary)' }}>{oktaStatus.scopes.join(', ') || 'openid, okta.users.read, okta.apps.read, okta.logs.read'}</strong></div>
                  {oktaStatus.updated_at && (
                    <div style={{ marginTop: '2px' }}>
                      Last synced: {new Date(oktaStatus.updated_at).toLocaleDateString()} {new Date(oktaStatus.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {!oktaStatus?.connected ? (
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
              border: '1px solid var(--border-subtle)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
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
                    backgroundColor: 'var(--bg-surface-tint)',
                    color: 'var(--text-secondary)',
                    border: '1px solid var(--border-subtle)',
                  }}
                >
                  Active Listener
                </span>
              </div>
              <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', lineHeight: '1.45', margin: 0 }}>
                Automated ingress folder listener for vendor order forms, service contracts, and invoices.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
