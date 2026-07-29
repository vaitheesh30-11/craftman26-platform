import { cookies } from 'next/headers';

const AUTH_COOKIE = 'sentinel_auth_token';

export function isWellFormedToken(token: string | undefined): boolean {
  if (!token) return false;
  return token.split('.').length === 3 && token.length > 20;
}

export function hasAuthenticatedSession(): boolean {
  return isWellFormedToken(cookies().get(AUTH_COOKIE)?.value);
}
