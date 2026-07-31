import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const dynamic = "force-dynamic";

/**
 * The actual OAuth `state` minting + HttpOnly cookie write happens in
 * `/auth/login/start` (a Route Handler) rather than here -- cookie writes
 * are only legal in a Server Action or Route Handler, not a page render.
 */
export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>IAM Sentinel</CardTitle>
          <CardDescription>Sign in with your organization&apos;s Cognito identity to continue.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild className="w-full">
            <a href="/auth/login/start">Sign in</a>
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
