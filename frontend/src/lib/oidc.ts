'use client';

/**
 * Minimal OIDC (Authorization Code + PKCE, RFC 7636) client for WSO2 Identity
 * Server / Asgardeo.
 *
 * Flow: /login generates PKCE pair + state, stores them in sessionStorage and
 * redirects to the WSO2 hosted login page. WSO2 authenticates the user and
 * redirects back to the Authorized Redirect URL (/auth/callback) with `code`
 * + `state`. The callback page exchanges the code for tokens at /auth/token.
 *
 * Configuration is environment driven so the same build works per deployment
 * (single-tenant deployments each point at their own WSO2 tenant):
 * - NEXT_PUBLIC_WSO2_AUTHORITY   e.g. https://identity.acmetech.com/t/acmetech.com/oauth2
 * - NEXT_PUBLIC_WSO2_CLIENT_ID   OAuth/OpenID connect client key of this SPA
 * - NEXT_PUBLIC_REDIRECT_URI     Must EXACTLY match a WSO2 "Authorized
 *                                Redirect URL", e.g. http://localhost:3000/auth/callback
 * - NEXT_PUBLIC_OIDC_SCOPES      Optional; defaults to "openid profile email"
 */

const OIDC_SCOPES = process.env.NEXT_PUBLIC_OIDC_SCOPES || 'openid profile email';

/** Session storage keys for the in-flight authorization request. */
const STATE_KEY = 'zellovest_oidc_state';
const VERIFIER_KEY = 'zellovest_oidc_pkce_verifier';

export interface IdTokenClaims {
  sub: string;
  email?: string;
  given_name?: string;
  family_name?: string;
  preferred_username?: string;
  name?: string;
  [key: string]: unknown;
}

export interface TokenResponse {
  access_token: string;
  id_token: string;
  token_type: string;
  expires_in: number;
  refresh_token?: string;
}

/** OIDC issuer metadata from the discovery document. */
export interface OidcDiscovery {
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint?: string;
  issuer: string;
}

export interface OidcConfig {
  authority: string;
  clientId: string;
  redirectUri: string;
  scopes: string;
}

/**
 * Read OIDC configuration from public env vars.
 * Throws a descriptive error when required values are missing so failures
 * surface at login time instead of silently misconfiguring the flow.
 */
export function getOidcConfig(): OidcConfig {
  const authority = process.env.NEXT_PUBLIC_WSO2_AUTHORITY;
  const clientId = process.env.NEXT_PUBLIC_WSO2_CLIENT_ID;
  const redirectUri = process.env.NEXT_PUBLIC_REDIRECT_URI;

  if (!authority || !clientId || !redirectUri) {
    throw new Error(
      'OIDC is not configured. Set NEXT_PUBLIC_WSO2_AUTHORITY, ' +
        'NEXT_PUBLIC_WSO2_CLIENT_ID and NEXT_PUBLIC_REDIRECT_URI ' +
        '(must exactly match a WSO2 Authorized Redirect URL).'
    );
  }
  return { authority: authority.replace(/\/+$/, ''), clientId, redirectUri, scopes: OIDC_SCOPES };
}

/** Resolve OIDC endpoints from the issuer's discovery document. */
export async function discoverOidcEndpoints(authority: string): Promise<OidcDiscovery> {
  const response = await fetch(`${authority}/.well-known/openid-configuration`);
  if (!response.ok) {
    throw new Error(`OIDC discovery failed for ${authority} (HTTP ${response.status})`);
  }
  return (await response.json()) as OidcDiscovery;
}

/** Generate the PKCE code verifier and S256 challenge pair. */
export async function generatePkcePair(): Promise<{ verifier: string; challenge: string }> {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  const verifier = base64UrlEncode(bytes);
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return { verifier, challenge: base64UrlEncode(new Uint8Array(digest)) };
}

/** Base64url-encode bytes without padding (RFC 7636 / RFC 4648 §5). */
function base64UrlEncode(bytes: Uint8Array): string {
  let binary = '';
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Decode a JWT payload without signature verification (client-side display only). */
export function decodeIdToken(idToken: string): IdTokenClaims {
  const parts = idToken.split('.');
  if (parts.length !== 3) {
    throw new Error('Malformed ID token');
  }
  const json = atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'));
  return JSON.parse(json) as IdTokenClaims;
}

/**
 * Build the WSO2 hosted-login URL and persist CSRF state + PKCE verifier.
 * Returns the URL to navigate to.
 */
export async function buildAuthorizeUrl(): Promise<string> {
  const config = getOidcConfig();
  const { authorization_endpoint } = await discoverOidcEndpoints(config.authority);

  const state = base64UrlEncode(crypto.getRandomValues(new Uint8Array(32)));
  const { verifier, challenge } = await generatePkcePair();

  sessionStorage.setItem(STATE_KEY, state);
  sessionStorage.setItem(VERIFIER_KEY, verifier);

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: config.scopes,
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  });

  return `${authorization_endpoint}?${params.toString()}`;
}

/** Build the WSO2 RP-initiated logout URL (end_session_endpoint). */
export async function buildLogoutUrl(): Promise<string> {
  const config = getOidcConfig();
  const { end_session_endpoint } = await discoverOidcEndpoints(config.authority);
  const params = new URLSearchParams({
    post_logout_redirect_uri: config.redirectUri,
    state: 'logout',
  });
  return `${end_session_endpoint}?${params.toString()}`;
}

/**
 * Exchange the authorization code for tokens. The PKCE verifier is consumed
 * (removed from sessionStorage) as part of the exchange.
 */
export async function exchangeCodeForTokens(code: string): Promise<TokenResponse> {
  const config = getOidcConfig();
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  if (!verifier) {
    throw new Error('Missing PKCE verifier — authorization session expired or replayed.');
  }

  const { token_endpoint } = await discoverOidcEndpoints(config.authority);
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: config.redirectUri,
    client_id: config.clientId,
    code_verifier: verifier,
  });

  let response: Response;
  try {
    response = await fetch(token_endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
  } catch {
    throw new Error('Could not reach the token endpoint. Check your network / WSO2 authority URL.');
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new Error(`Token exchange failed (HTTP ${response.status})${detail ? `: ${detail}` : ''}`);
  }

  sessionStorage.removeItem(VERIFIER_KEY);
  return (await response.json()) as TokenResponse;
}

/**
 * Validate that the `state` returned by WSO2 matches the one we generated
 * (CSRF protection) and consume it (single-use).
 */
export function consumeState(returnedState: string | null): boolean {
  const expected = sessionStorage.getItem(STATE_KEY);
  sessionStorage.removeItem(STATE_KEY);
  return Boolean(expected) && expected === returnedState;
}
