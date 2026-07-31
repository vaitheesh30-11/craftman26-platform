"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { MessageList } from "@/components/chat/message-list";
import { PromptComposer } from "@/components/chat/prompt-composer";
import { useChatSession } from "@/store/chat-session";

export function ChatConsole() {
  const status = useChatSession((s) => s.status);
  const transcript = useChatSession((s) => s.transcript);
  const activeTurnId = useChatSession((s) => s.activeTurnId);
  const connect = useChatSession((s) => s.connect);
  const disconnect = useChatSession((s) => s.disconnect);
  const sendQuery = useChatSession((s) => s.sendQuery);
  const cancelActive = useChatSession((s) => s.cancelActive);

  useEffect(() => {
    connect();
    return disconnect;
    // Mount-only: `connect`/`disconnect` close over the module-level socket
    // singleton, not component state, so they are stable across renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeTurn = transcript.find((e) => e.kind === "turn" && e.id === activeTurnId);
  const canCancel =
    activeTurn?.kind === "turn" && activeTurn.state === "streaming" && activeTurn.correlationId !== null;

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {status === "open" ? "Connected" : status === "connecting" ? "Connecting…" : "Disconnected"}
        </span>
        {activeTurnId && (
          <Button type="button" variant="outline" size="sm" onClick={cancelActive} disabled={!canCancel}>
            Cancel
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        <MessageList transcript={transcript} />
      </div>

      <PromptComposer disabled={status !== "open" || activeTurnId !== null} onSubmit={sendQuery} />
    </div>
  );
}
