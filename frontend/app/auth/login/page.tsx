import { randomBytes } from "node:crypto";

import { cookies } from "next/headers";

import { buildHostedUiSignInUrl } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const dynamic = "force-dynamic";

const OAUTH_STATE_COOKIE = "sentinel_oauth_state";

/**
 * `state` is minted server-side and stored in a short-lived HttpOnly
 * cookie, then echoed by Cognito on the callback — a standard OAuth CSRF
 * defense, independent of the double-submit CSRF cookie the BFF proxy
 * uses post-login.
 */
export default function LoginPage() {
  const state = randomBytes(16).toString("hex");
  cookies().set(OAUTH_STATE_COOKIE, state, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 300,
  });
  const signInUrl = buildHostedUiSignInUrl(state);

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>IAM Sentinel</CardTitle>
          <CardDescription>Sign in with your organization&apos;s Cognito identity to continue.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild className="w-full">
            <a href={signInUrl}>Sign in</a>
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}

export { OAUTH_STATE_COOKIE };
