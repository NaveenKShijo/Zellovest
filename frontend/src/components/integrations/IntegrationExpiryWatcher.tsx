'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { useToast } from '@/contexts/ToastContext';
import {
  IntegrationProvider,
  useIntegrationStatus,
} from '@/hooks/useIntegrationStatus';

/**
 * IntegrationExpiryWatcher: global reconnect nudge for expired OAuth tokens.
 *
 * Polls Ramp + Okta + Google Drive status in the background and raises a
 * persistent `AlertBanner` entry (with a link to `/integrations`) whenever a
 * provider needs a reconnect — so expired access tokens are surfaced on every
 * page instead of failing silently inside sync jobs. Mounted once in
 * `AppProviders`; renders nothing itself.
 */

const PROVIDER_LABELS: Record<IntegrationProvider, string> = {
  ramp: 'Ramp',
  okta: 'Okta',
  drive: 'Google Drive',
};

export function IntegrationExpiryWatcher({
  tenantId = 'default-org',
}: {
  tenantId?: string;
}) {
  const pathname = usePathname();
  const { addAlert, dismissAlert } = useToast();
  const { ramp, okta, drive, isLoading } = useIntegrationStatus(tenantId);
  // Active alert id per provider, so reconnect prompts are raised once and
  // cleared when the connection recovers.
  const activeAlerts = useRef<Partial<Record<IntegrationProvider, string>>>({});

  useEffect(() => {
    if (isLoading) return;
    // The integrations page renders its own inline reconnect UI.
    if (pathname?.startsWith('/integrations')) return;
    const states: Array<{
      provider: IntegrationProvider;
      needsReconnect: boolean;
    }> = [
      { provider: 'ramp', needsReconnect: ramp?.needsReconnect === true },
      { provider: 'okta', needsReconnect: okta?.needsReconnect === true },
      { provider: 'drive', needsReconnect: drive?.needsReconnect === true },
    ];
    for (const { provider, needsReconnect } of states) {
      const existingId = activeAlerts.current[provider];
      if (needsReconnect && !existingId) {
        const label = PROVIDER_LABELS[provider];
        activeAlerts.current[provider] = addAlert({
          type: 'error',
          title: `${label} connection expired`,
          message:
            `Your ${label} access token expired and syncs are failing. ` +
            `Reconnect to resume ingestion.`,
          action: { label: 'Reconnect now', href: '/integrations' },
        });
      } else if (!needsReconnect && existingId) {
        dismissAlert(existingId);
        delete activeAlerts.current[provider];
      }
    }
  }, [isLoading, ramp, okta, drive, pathname, addAlert, dismissAlert]);

  return null;
}

export default IntegrationExpiryWatcher;
