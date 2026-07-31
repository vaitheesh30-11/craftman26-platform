import { expect, test } from "@playwright/test";

function encodeEvent(event: string, data: string | Record<string, unknown>): string {
  const payload = typeof data === "string" ? data : JSON.stringify(data);
  return `event: ${event}\ndata: ${payload}\n\n`;
}

async function login(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/auth/login");
  const signInHref = await page.getByRole("link", { name: "Sign in" }).getAttribute("href");
  const state = new URL(signInHref!).searchParams.get("state");
  await page.goto(`/auth/callback?code=mock-auth-code&state=${state}`);
  await expect(page).toHaveURL("/");
}

// phase-01 §7: "Playwright: full chat flow with a mocked backend streaming
// 5 progress lines + a result." `page.routeWebSocket` intercepts the real
// `WebSocket` the browser opens against `NEXT_PUBLIC_WS_URL` (`lib/env.ts`'s
// zero-config dev default), so `lib/websocket-client.ts`'s actual parsing
// and `store/chat-session.ts`'s actual reducer logic run end-to-end against
// a scripted server, not a stub.
test("chat: send a query, stream progress, then render the result", async ({ page }) => {
  await login(page);

  await page.routeWebSocket(/ws:\/\/localhost:8081\/.*/, (ws) => {
    ws.onMessage((message) => {
      const frame = JSON.parse(message.toString()) as { action: string };
      if (frame.action !== "chat") return;

      ws.send(encodeEvent("started", { correlation_id: "c1" }));
      for (let i = 1; i <= 5; i += 1) {
        ws.send(encodeEvent("progress", `analyzing step ${i} of 5`));
      }
      ws.send(
        encodeEvent("result", {
          decision_id: "d1",
          correlation_id: "c1",
          principal: "arn:aws:iam::111122223333:user/dev",
          query: {},
          specialist_verdicts: [],
          findings: [],
          remediations_proposed: [],
          remediations_applied: [],
          status: "ANSWERED",
          narrative: "No PassRole blast-radius issues found for this account.",
          evidence_ref: {},
          decided_at: new Date().toISOString(),
        }),
      );
    });
  });

  await page.goto("/chat");
  await expect(page.getByText("Connected")).toBeVisible();

  await page.getByLabel("Message Sentinel Prime").fill("audit passrole for this account");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("ANSWERED")).toBeVisible();
  await expect(page.getByText("No PassRole blast-radius issues found for this account.")).toBeVisible();
});

test("chat: cancel becomes available once the server echoes a correlation_id", async ({ page }) => {
  await login(page);

  await page.routeWebSocket(/ws:\/\/localhost:8081\/.*/, (ws) => {
    ws.onMessage((message) => {
      const frame = JSON.parse(message.toString()) as { action: string; correlation_id?: string };
      if (frame.action === "chat") {
        ws.send(encodeEvent("started", { correlation_id: "c1" }));
        ws.send(encodeEvent("progress", "still working..."));
      } else if (frame.action === "cancel") {
        ws.send(encodeEvent("error", { code: "CANCELED", message: "canceled by client", correlation_id: "c1" }));
      }
    });
  });

  await page.goto("/chat");
  await page.getByLabel("Message Sentinel Prime").fill("audit passrole");
  await page.getByRole("button", { name: "Send" }).click();

  const cancelButton = page.getByRole("button", { name: "Cancel" });
  await expect(cancelButton).toBeEnabled();
  await cancelButton.click();

  await expect(page.getByText("Canceled.")).toBeVisible();
});
