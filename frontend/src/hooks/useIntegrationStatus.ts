'use client';

import { useCallback, useEffect, useState } from 'react';

/**
 * Shared integration-connection state for Ramp + Okta OAuth.
 *
 * Polls `GET /api/v1/integrations/{ramp,okta}/status` (proxied to the
 * ingestion API) and derives user-facing reconnect state from the
 * backend's effective status (`ACTIVE` vs `EXPIRED`/`REVOKED`,
 * `needs_reconnect`, `last_error`) plus the wall-clock
 * `token_expires_at` — so an expired access token surfaces as
 * "Reconnect required" instead of a stale "Connected" badge.
 */

export type IntegrationProvider = 'ramp' | 'okta';

export interface IntegrationStatus {
  connected: boolean;
  provider: string;
  tenant_id: string;
  status: string;
  scopes: string[];
  needs_reconnect?: boolean;
  last_error?: string | null;
  token_expires_at?: string | null;
  updated_at?: string | null;
}

export interface ProviderState extends IntegrationStatus {
  /** True when the user must reconnect (EXPIRED/REVOKED or past expiry). */
  needsReconnect: boolean;
  /** True when the token expires within the warning window. */
  isExpiringSoon: boolean;
}

export interface IntegrationStatusResult {
  ramp: ProviderState | null;
  okta: ProviderState | null;
  isLoading: boolean;
  /** Providers currently needing a reconnect (e.g. `['ramp']`). */
  needsReconnectProviders: IntegrationProvider[];
  refresh: () => Promise<void>;
}

/** Warn when the access token expires within this window (24h). */
const EXPIRING_SOON_MS = 24 * 60 * 60 * 1000;

function toProviderState(
  raw: IntegrationStatus | null,
  provider: IntegrationProvider,
  tenantId: string,
  now: number
): ProviderState | null {
  if (!raw) return null;
  const statusUpper = (raw.status || '').toUpperCase();
  const expiresAt = raw.token_expires_at ? Date.parse(raw.token_expires_at) : NaN;
  const pastExpiry = Number.isFinite(expiresAt) && expiresAt <= now;
  const needsReconnect =
    raw.needs_reconnect === true ||
    statusUpper === 'EXPIRED' ||
    statusUpper === 'REVOKED' ||
    pastExpiry;
  const isExpiringSoon =
    !needsReconnect &&
    Number.isFinite(expiresAt) &&
    expiresAt - now <= EXPIRING_SOON_MS;
  if (raw.connected && pastExpiry) {
    // Backend should already derive EXPIRED; guard against stale responses.
    return { ...raw, connected: false, needsReconnect: true, isExpiringSoon: false };
  }
  void tenantId;
  return { ...raw, needsReconnect, isExpiringSoon };
}

function disconnectedState(provider: IntegrationProvider, tenantId: string): ProviderState {
  return {
    connected: false,
    provider,
    tenant_id: tenantId,
    status: 'DISCONNECTED',
    scopes: [],
    needs_reconnect: false,
    last_error: null,
    token_expires_at: null,
    updated_at: null,
    needsReconnect: false,
    isExpiringSoon: false,
  };
}

/**
 * Poll Ramp + Okta connection status.
 *
 * @param tenantId - Single-tenant deployment id (V1 `default-org`).
 * @param pollIntervalMs - Background refresh cadence (0 disables polling).
 */
export function useIntegrationStatus(
  tenantId: string = 'default-org',
  pollIntervalMs: number = 5 * 60 * 1000
): IntegrationStatusResult {
  const [ramp, setRamp] = useState<ProviderState | null>(null);
  const [okta, setOkta] = useState<ProviderState | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const refresh = useCallback(async () => {
    try {
      const [rampRes, oktaRes] = await Promise.all([
        fetch(`/api/v1/integrations/ramp/status?tenant_id=${tenantId}`),
        fetch(`/api/v1/integrations/okta/status?tenant_id=${tenantId}`),
      ]);
      const now = Date.now();
      const rampJson = rampRes.ok
        ? ((await rampRes.json()) as IntegrationStatus)
        : null;
      const oktaJson = oktaRes.ok
        ? ((await oktaRes.json()) as IntegrationStatus)
        : null;
      setRamp(
        toProviderState(rampJson, 'ramp', tenantId, now) ??
          disconnectedState('ramp', tenantId)
      );
      setOkta(
        toProviderState(oktaJson, 'okta', tenantId, now) ??
          disconnectedState('okta', tenantId)
      );
    } catch {
      setRamp((prev) => prev ?? disconnectedState('ramp', tenantId));
      setOkta((prev) => prev ?? disconnectedState('okta', tenantId));
    } finally {
      setIsLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    // Mount + interval fetch legitimately writes fetched state; the polling
    // subscription below is the external-system sync this effect owns.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    if (pollIntervalMs <= 0) return;
    const timer = setInterval(() => {
      void refresh();
    }, pollIntervalMs);
    return () => clearInterval(timer);
  }, [refresh, pollIntervalMs]);

  const needsReconnectProviders = (['ramp', 'okta'] as const).filter(
    (provider) => (provider === 'ramp' ? ramp : okta)?.needsReconnect
  );

  return { ramp, okta, isLoading, needsReconnectProviders, refresh };
}
