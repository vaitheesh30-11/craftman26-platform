import { NextResponse, type NextRequest } from 'next/server';

const protectedPrefixes = ['/dashboard', '/sessions'];

function isWellFormedToken(token: string | undefined): boolean {
  return Boolean(token && token.split('.').length === 3 && token.length > 20);
}

export function middleware(request: NextRequest): NextResponse {
  const requiresAuth = protectedPrefixes.some((prefix) => request.nextUrl.pathname.startsWith(prefix));
  if (!requiresAuth || isWellFormedToken(request.cookies.get('sentinel_auth_token')?.value)) return NextResponse.next();
  const loginUrl = new URL('/login', request.url);
  loginUrl.searchParams.set('next', request.nextUrl.pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = { matcher: ['/dashboard/:path*', '/sessions/:path*'] };
