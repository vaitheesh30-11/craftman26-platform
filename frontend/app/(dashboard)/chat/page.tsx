import { ChatConsole } from "@/components/chat/chat-console";
import { SessionRail } from "@/components/chat/session-rail";

export default function ChatPage() {
  return (
    <main className="container grid h-[calc(100vh-2rem)] grid-cols-[240px_1fr] gap-6 py-4">
      <aside className="border-r pr-4">
        <SessionRail />
      </aside>
      <ChatConsole />
    </main>
  );
}
