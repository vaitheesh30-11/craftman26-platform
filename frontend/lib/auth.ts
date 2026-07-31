import { Amplify } from "aws-amplify";

import { getPublicEnv } from "@/lib/env";

const OAUTH_SCOPES = ["openid", "email", "profile"];

/**
 * Configures Amplify's Cognito resource so `@aws-amplify/ui-react` and any
 * future Amplify-aware code share one source of truth for pool/client/
 * domain. Deliberately NOT used for session management: Amplify's own
 * hosted-UI flow persists tokens in the browser (localStorage by default),
 * which phase-00 §3 forbids ("Session tokens stored server-side (HttpOnly
 * cookies via BFF proxy) — never in localStorage"). The actual authorize
 * URL and code exchange below talk to Cognito's OAuth2 endpoints directly
 * so every token stays server-side.
 */
export function configureAmplify(): void {
  const env = getPublicEnv();
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: env.NEXT_PUBLIC_COGNITO_POOL_ID,
        userPoolClientId: env.NEXT_PUBLIC_COGNITO_CLIENT_ID,
        loginWith: {
          oauth: {
            domain: env.NEXT_PUBLIC_COGNITO_DOMAIN,
            scopes: OAUTH_SCOPES,
            redirectSignIn: [`${env.NEXT_PUBLIC_APP_ORIGIN}/auth/callback`],
            redirectSignOut: [`${env.NEXT_PUBLIC_APP_ORIGIN}/auth/login`],
            responseType: "code",
          },
        },
      },
    },
  });
}

export function callbackRedirectUri(): string {
  return `${getPublicEnv().NEXT_PUBLIC_APP_ORIGIN}/auth/callback`;
}

/** Builds the Cognito Hosted UI `/oauth2/authorize` URL. `state` carries the CSRF nonce. */
export function buildHostedUiSignInUrl(state: string): string {
  const env = getPublicEnv();
  const params = new URLSearchParams({
    client_id: env.NEXT_PUBLIC_COGNITO_CLIENT_ID,
    response_type: "code",
    scope: OAUTH_SCOPES.join(" "),
    redirect_uri: callbackRedirectUri(),
    state,
  });
  return `https://${env.NEXT_PUBLIC_COGNITO_DOMAIN}/oauth2/authorize?${params.toString()}`;
}

export function buildHostedUiSignOutUrl(): string {
  const env = getPublicEnv();
  const params = new URLSearchParams({
    client_id: env.NEXT_PUBLIC_COGNITO_CLIENT_ID,
    logout_uri: `${env.NEXT_PUBLIC_APP_ORIGIN}/auth/login`,
  });
  return `https://${env.NEXT_PUBLIC_COGNITO_DOMAIN}/logout?${params.toString()}`;
}

export interface CognitoTokenResponse {
  access_token: string;
  id_token: string;
  refresh_token?: string;
  token_type: string;
  expires_in: number;
}

export class CognitoTokenExchangeError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "CognitoTokenExchangeError";
  }
}

/**
 * Server-side only (called from `app/auth/callback/route.ts`). Exchanges
 * the OAuth `code` for tokens via Cognito's `/oauth2/token` endpoint using
 * stdlib `fetch` — no Amplify client-session side effects, so nothing
 * lands in browser storage.
 */
export async function exchangeCodeForTokens(code: string): Promise<CognitoTokenResponse> {
  const env = getPublicEnv();
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: env.NEXT_PUBLIC_COGNITO_CLIENT_ID,
    code,
    redirect_uri: callbackRedirectUri(),
  });

  const response = await fetch(`https://${env.NEXT_PUBLIC_COGNITO_DOMAIN}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new CognitoTokenExchangeError(
      `Cognito token exchange failed: ${detail.slice(0, 512)}`,
      response.status,
    );
  }

  return (await response.json()) as CognitoTokenResponse;
}

/** Silent refresh, used by the BFF proxy on a 401 from the backend (phase-00 §3). */
export async function refreshTokens(refreshToken: string): Promise<CognitoTokenResponse> {
  const env = getPublicEnv();
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: env.NEXT_PUBLIC_COGNITO_CLIENT_ID,
    refresh_token: refreshToken,
  });

  const response = await fetch(`https://${env.NEXT_PUBLIC_COGNITO_DOMAIN}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new CognitoTokenExchangeError(
      `Cognito token refresh failed: ${detail.slice(0, 512)}`,
      response.status,
    );
  }

  return (await response.json()) as CognitoTokenResponse;
}
