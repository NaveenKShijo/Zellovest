/**
 * In-memory client-side cache for OAuth integration connection statuses.
 *
 * Prevents redundant HTTP roundtrips when navigating between dashboard tabs
 * and renders integration states instantly (0ms) on mount.
 */

export interface DriveWatchState {
  channel_id?: string;
  resource_id?: string;
  expiration?: string | null;
}

export interface IntegrationStatusState {
  connected: boolean;
  provider: string;
  tenant_id: string;
  status: string;
  scopes: string[];
  needs_reconnect?: boolean;
  refresh_available?: boolean;
  last_error?: string | null;
  token_expires_at?: string | null;
  updated_at?: string | null;
  watch?: DriveWatchState | null;
}

export interface CachedIntegrationStatuses {
  ramp: IntegrationStatusState;
  okta: IntegrationStatusState;
  drive: IntegrationStatusState;
  timestamp: number;
}

/** Cache TTL: 60 seconds (matches server Redis TTL). */
const CACHE_TTL_MS = 60 * 1000;

const statusCache = new Map<string, CachedIntegrationStatuses>();
const inFlightRequests = new Map<string, Promise<{
  ramp: IntegrationStatusState;
  okta: IntegrationStatusState;
  drive: IntegrationStatusState;
}>>();

export function disconnectedIntegration(
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

/** Retrieve cached integration statuses if still fresh. */
export function getCachedIntegrationStatuses(
  tenantId: string = 'default-org'
): CachedIntegrationStatuses | null {
  const cached = statusCache.get(tenantId);
  if (!cached) return null;
  if (Date.now() - cached.timestamp > CACHE_TTL_MS) {
    return null;
  }
  return cached;
}

/** Manually update or seed the client cache. */
export function setCachedIntegrationStatuses(
  tenantId: string,
  statuses: {
    ramp: IntegrationStatusState;
    okta: IntegrationStatusState;
    drive: IntegrationStatusState;
  }
): void {
  statusCache.set(tenantId, {
    ...statuses,
    timestamp: Date.now(),
  });
}

/** Invalidate cached integration statuses (e.g. after connect or disconnect). */
export function clearCachedIntegrationStatuses(tenantId?: string): void {
  if (tenantId) {
    statusCache.delete(tenantId);
    inFlightRequests.delete(tenantId);
  } else {
    statusCache.clear();
    inFlightRequests.clear();
  }
}

/**
 * Fetch integration statuses for Ramp, Okta, and Google Drive.
 *
 * Uses memory cache and in-flight promise deduplication to avoid repeated
 * API polling and eliminate 4-5s load times on tab navigation.
 */
export async function fetchIntegrationStatuses(
  tenantId: string = 'default-org',
  options?: { force?: boolean }
): Promise<{
  ramp: IntegrationStatusState;
  okta: IntegrationStatusState;
  drive: IntegrationStatusState;
}> {
  if (!options?.force) {
    const cached = getCachedIntegrationStatuses(tenantId);
    if (cached) {
      return { ramp: cached.ramp, okta: cached.okta, drive: cached.drive };
    }
    const inFlight = inFlightRequests.get(tenantId);
    if (inFlight) {
      return inFlight;
    }
  }

  const querySuffix = options?.force
    ? `?tenant_id=${tenantId}&fresh=true`
    : `?tenant_id=${tenantId}`;

  const requestPromise = (async () => {
    try {
      const [rampRes, oktaRes, driveRes] = await Promise.all([
        fetch(`/api/v1/integrations/ramp/status${querySuffix}`),
        fetch(`/api/v1/integrations/okta/status${querySuffix}`),
        fetch(`/api/v1/integrations/google-drive/status${querySuffix}`),
      ]);

      const ramp: IntegrationStatusState = rampRes.ok
        ? await rampRes.json()
        : disconnectedIntegration('ramp', tenantId);
      const okta: IntegrationStatusState = oktaRes.ok
        ? await oktaRes.json()
        : disconnectedIntegration('okta', tenantId);
      const drive: IntegrationStatusState = driveRes.ok
        ? await driveRes.json()
        : disconnectedIntegration('google-drive', tenantId);

      const result = { ramp, okta, drive };
      setCachedIntegrationStatuses(tenantId, result);
      return result;
    } catch {
      const fallback = {
        ramp: disconnectedIntegration('ramp', tenantId),
        okta: disconnectedIntegration('okta', tenantId),
        drive: disconnectedIntegration('google-drive', tenantId),
      };
      return fallback;
    } finally {
      inFlightRequests.delete(tenantId);
    }
  })();

  inFlightRequests.set(tenantId, requestPromise);
  return requestPromise;
}
